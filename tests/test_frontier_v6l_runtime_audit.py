"""Invented four-segment fixtures; no live journals, semantic answers or API."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts import audit_frontier_v6l_runtime as audit
from tests import test_adaption_v6l as runtime_fixtures
from tests.test_adaption_v6l import synthetic_carry, slot, emit, final, QWEN, ROUTE


def encoded(value): return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
def lines(values): return b''.join(encoded(v) for v in values)


def capture(slots, factory=None, *, carried=None, oldq=None, oldr=None):
    seed=synthetic_carry(slots,carried)
    if oldr:seed['last_issued_model']=oldr[-1]['model']
    v=runtime_fixtures.ContinuationTests().run_case(slots,factory,carry=seed)
    v['slots']=slots;v['carryover']=carried or {};v['original_requests']=oldq or [];v['original_responses']=oldr or []
    return v


def replay(v):
    return audit.audit_evidence(v['slots'],v['manifest'],v['requests'],v['responses'],v['outcomes'],v['summary'],v['ledger'],
        lambda name:v['streams'][name].encode('utf-8'),historical={'carry_credits':'249','ledger_sha256':'b'*64,'inherited_unsettled_attempts':73},
        carryover=v['carryover'],original_requests=v['original_requests'],original_responses=v['original_responses'],allow_test_hooks=True)


def carried_seed(slots,success=True):
    s=slots[0];aid='prior:'+s['slot_id'];body=audit.expected_body(s,{},{});at='2026-11-13T23:00:00+00:00'
    r={**{k:s[k] for k in ('slot_id','model','case_id','condition','phase')},'issued':True,'terminal_valid':success,
       'model_outcome':'completed' if success else 'operational_failure','response_status':'completed' if success else None,
       'error':None if success else 'response_model_mismatch','failure_scope':None if success else 'global',
       'output_text':'ACTUAL CLOSED ANSWER' if success else '', 'attempt_id':aid,'at':at}
    return {s['slot_id']:r},[{'attempt_id':aid,'request':body}],[r]


class CoreAuditTests(unittest.TestCase):
    def test_new_reservation_can_cross250_but_uses_owned750_cap(self):
        from scripts import audit_frontier_v6k_runtime as frozen
        before=frozen.CAP
        v=capture([slot(0,'glm-5.2'),slot(1)]);r=replay(v)
        self.assertGreater(float(r['maximum_accounted_credits']),250)
        self.assertLess(float(r['maximum_accounted_credits']),750)
        self.assertEqual(r['budget_cap_credits'],'750');self.assertEqual(r['historical_carry_credits'],'249')
        self.assertEqual(r['inherited_unsettled_attempts'],73);self.assertEqual(r['counts']['planned'],2)
        self.assertEqual(frozen.CAP,before);self.assertEqual(frozen.CAP,250_000_000_000)
        self.assertEqual(audit.CAP,750_000_000_000)

    def test_initialize250_cannot_be_mistaken_for750(self):
        v=capture([slot(0)]);v['ledger'][0]['event']['cap_credits']='250'
        chain='0'*64
        for r in v['ledger']:
            r['previous_sha256']=chain;r['sha256']=audit.digest({k:x for k,x in r.items() if k!='sha256'});chain=r['sha256']
        with self.assertRaisesRegex(ValueError,'carry initialization'):replay(v)

    def test_inherited_unknowns_and_budget_before_cap_cannot_reset(self):
        v=capture([slot(0)])
        for change in ('unknown','cap'):
            bad=deepcopy(v)
            if change=='unknown':bad['summary']['budget']['cumulative_inherited_unsettled_attempts']=64
            else:bad['manifest']['budget_before']['cumulative_cap_credits']='250'
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'earlier unknowns'):replay(bad)

    def test_actual_prior_history_preserved_and_not_reissued(self):
        slots=[slot(0),slot(1,history_from=['s-0'])];c,q,r=carried_seed(slots)
        v=capture(slots,carried=c,oldq=q,oldr=r);out=replay(v)
        self.assertEqual(out['counts']['planned'],1);self.assertIn('ACTUAL CLOSED ANSWER',str(v['requests'][0]['request']))
        self.assertEqual([x['slot_id'] for x in v['requests']],['s-1'])
        v['original_requests'][0]['request']['input'][-1]['content']='fabricated old input'
        with self.assertRaisesRegex(ValueError,'actual source'):replay(v)

    def test_prior_global_failure_retains_two_dependency_skips(self):
        slots=[slot(0,QWEN),slot(1,QWEN,history_from=['s-0']),slot(2,QWEN,history_from=['s-0','s-1']),slot(3)]
        c,q,r=carried_seed(slots,False);v=capture(slots,carried=c,oldq=q,oldr=r);out=replay(v)
        self.assertEqual(out['counts']['planned'],3);self.assertEqual(out['counts']['dependency_skips'],2)
        self.assertEqual(out['counts']['issued_attempts'],1);self.assertEqual(c['s-0']['failure_scope'],'global')

    def test_429_three_distinct_attempts_preserve_first_failure_and_cooldown(self):
        def factory(clock,starts,ends):
            async def transport(body):
                if len(starts)<=2:
                    yield {'http_status':429,'content_type':'application/json','retry_after':'70'}
                    yield b'{"error":"rate limit"}'
                else:
                    async for e in emit(final(body)):yield e
            return transport
        v=capture([slot(0)],factory);r=replay(v)
        self.assertEqual(r['counts']['retries'],2);self.assertEqual(r['counts']['first_attempt_completed'],0)
        self.assertEqual(r['counts']['eventual_completed'],1);self.assertGreater(float(r['retained_run_bounds_credits']),0)
        self.assertGreaterEqual(r['minimum_completion_gap_seconds'],70)

    def test_reset_after_valid_headers_retains_bound_without_retry(self):
        def factory(clock,starts,ends):
            async def transport(body):
                if len(starts)==1:
                    yield {'http_status':200,'content_type':'text/event-stream','retry_after':None}
                    yield b': prefix\n\n';raise ConnectionResetError('not retained in records')
                async for e in emit(final(body)):yield e
            return transport
        v=capture([slot(0),slot(1)],factory);r=replay(v)
        self.assertEqual(r['counts']['retries'],0);self.assertEqual(r['counts']['per_slot_operational_failures'],1)
        self.assertEqual(r['counts']['completed'],1);self.assertGreater(float(r['retained_run_bounds_credits']),0)
        self.assertNotIn('not retained in records',repr(v))

    def test_raw_stream_pacing_and_settlement_tampering_reject(self):
        v=capture([slot(0),slot(1)])
        for change in ('stream','pacing','settlement'):
            bad=deepcopy(v)
            if change=='stream':bad['streams'][next(iter(bad['streams']))]+='tampered'
            elif change=='pacing':bad['requests'][1]['admitted_monotonic']-=1
            else:bad['responses'][0]['settled_credits']='0'
            with self.subTest(change=change),self.assertRaises(ValueError):replay(bad)

    def test_qwen_observed_route_not_invented_alias(self):
        def factory(*args):return lambda body:emit(final({**body,'model':ROUTE}))
        v=capture([slot(0,QWEN)],factory);self.assertTrue(replay(v)['passed'])
        v['responses'][0]['returned_model']=QWEN
        with self.assertRaisesRegex(ValueError,'returned model'):replay(v)

    def test_protocol_failure_cannot_be_reclassified_completed(self):
        v=capture([slot(0,QWEN),slot(1)]);self.assertEqual(replay(v)['schedule_status'],'stopped')
        v['summary']['status']='completed'
        with self.assertRaises(ValueError):replay(v)


def artifact_fixture():
    """Isolate file/receipt authentication from the independently tested core.

    Prior audits are explicit mocks, not assertions that these invented short
    ledgers are genuine budget-stop executions. No actual prior answer is read.
    """
    files={};slots=[{'slot_id':f's-{n}'} for n in range(1800)]
    carry='249.9';inherited=65;priors={};sources=[];refs=[];selected_all=[]
    for name,offset,count,skips,stop in [('i',0,6,0,'response_model_mismatch'),
        ('j',6,207,11,'network_or_transport_failure'),('k',224,3,2,'cumulative_budget_stop')]:
        prefix=audit.PREFIXES[name];rid='prior-'+name;outcomes=[];issued=[]
        for n in range(offset,1800):
            yes=n<offset+count;dep=offset+count<=n<offset+count+skips
            r={'slot_id':f's-{n}','run_id':rid,'issued':yes,'attempt_id':f'{rid}:{n}' if yes else None,
               'model_outcome':'completed' if yes else 'not_issued_dependency_failed' if dep else 'not_issued_global_stop',
               'terminal_valid':yes,'failure_scope':None,'error':None}
            if yes and n==offset+count-1:
                r.update(model_outcome='operational_failure',terminal_valid=False,
                         failure_scope='slot' if name=='k' else 'global',error='timeout' if name=='k' else stop)
            outcomes.append(r)
            if yes:issued.append(r)
            if yes or dep:
                refs.append({'segment':name,'slot_id':r['slot_id'],'source_path':prefix+'slot-outcomes.jsonl',
                    'source_line_one_based':len(outcomes),'row_sha256':audit.digest(r),
                    'attempt_id':r['attempt_id'],'model_outcome':r['model_outcome']})
                selected_all.append(r)
        paths={role:prefix+file for role,file in audit.ROLE_NAMES.items()}
        paths['ledger']=f'results/frontier-v6{name}/budget/ledger.jsonl'
        summary={'run_id':rid,'status':'stopped','stop_reasons':[stop],'issued_attempts':count,'retries':0,
                 'budget':{'cumulative_cap_credits':'250','accounted_credits':carry if name=='k' else '80.145946577',
                           'cumulative_inherited_unsettled_attempts':64,'unsettled_attempts':1 if name=='k' else 0}}
        for role,values in [('requests',issued),('responses',issued),('outcomes',outcomes)]:files[paths[role]]=lines(values)
        files[paths['summary']]=encoded(summary);files[paths['run_manifest']]=encoded({'run_id':rid})
        ledger=[{'at':'2026-11-15T00:00:00+00:00','sha256':name*64,'event':{'kind':'run_closed'}}]
        files[paths['ledger']]=lines(ledger)
        proof={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':'stopped',
            'counts':{'issued_attempts':count,'issued_slots':count,'dependency_skips':skips},'cumulative_accounted_credits':carry if name=='k' else '80.145946577',
            'ledger_chain_sha256':name*64,
            'input_bindings':{p:{'sha256':sha256(files[p]).hexdigest(),'bytes':len(files[p])} for role,p in paths.items() if role!='audit'}}
        if name=='j':proof['original_audit']=priors['i']
        if name=='k':proof['prior_segment_audits']={key:priors[key] for key in ('i','j')}
        priors[name]=proof;files[paths['audit']]=encoded(proof)
        sources.append({'segment':name,'run_id':rid,'freeze_path':f'data/frontier-v6{name}-freeze.json','freeze_sha256':{'i':audit.I_FREEZE_SHA,'j':audit.J_FREEZE_SHA,'k':'PENDING'}[name],
            'paths':paths,'sha256':{role:sha256(files[p]).hexdigest() for role,p in paths.items()},
            'definitive_final_slots':count+skips,'issued_slots':count})
    files[audit.BASELINE]=files['results/frontier-v6k/budget/ledger.jsonl'];baseline_sha=sha256(files[audit.BASELINE]).hexdigest()
    files['historical.txt']=b'unchanged historical byte fixture'
    files['data/frontier-v6k-freeze.json']=encoded({'files':[{'path':'historical.txt','sha256':sha256(files['historical.txt']).hexdigest()}]})
    ksha=sha256(files['data/frontier-v6k-freeze.json']).hexdigest();sources[-1]['freeze_sha256']=ksha
    sessions='data/frontier-v6i-sessions.json';files[sessions]=encoded(slots)
    carried=[r['slot_id'] for r in selected_all];pending=[s['slot_id'] for s in slots if s['slot_id'] not in carried]
    common={'prior_freeze_path':'data/frontier-v6k-freeze.json','prior_freeze_sha256':ksha,
        'baseline_snapshot_path':audit.BASELINE,'baseline_snapshot_sha256':baseline_sha,
        'historical_conservative_carry_credits':carry,'previous_cumulative_cap_credits':'250','cumulative_cap_credits':'750',
        'inherited_unsettled_attempts':inherited,'deadline_utc':audit.DEADLINE.isoformat()}
    receipt={**common,'schema':'retrace.frontier-v6l-continuation.v1','sessions_path':sessions,'sessions_sha256':audit.digest(slots),
        'prior_journal_files':{p:sha256(files[p]).hexdigest() for entry in sources for p in entry['paths'].values()},
        'source_segments':sources,'original_run_id':'prior-i','original_run_ids':['prior-i','prior-j','prior-k'],'carried_final_outcomes':refs,
        'permanently_excluded_final_slot_ids':carried,'permanently_excluded_issued_slot_ids':[r['slot_id'] for r in selected_all if r['issued']],
        'continuation_slot_ids':pending,'full_planned_slots':1800,'carried_issued_slots':216,'carried_final_slots':229,'continuation_slots':1571,
        'failed_producer_descendant_slot_ids':[],'observed_response_models':audit.ROUTE}
    receiptpath='data/frontier-v6l-continuation.json';files[receiptpath]=encoded(receipt)
    lock=next(iter(audit.ALLOWED_ALIAS));files[lock]=b'inert historical lock fixture'
    files['scripts/audit_frontier_v6l_runtime.py']=Path(audit.__file__).read_bytes()
    auth={**common,'schema':'retrace.frontier-v6l-authorization.v1','protected_v5_file_count':402,'prior_status':'stopped','prior_stop_reason':'cumulative_budget_stop',
          'protected':{p:sha256(v).hexdigest() for p,v in files.items()}}
    authpath='data/frontier-v6l-authorization.json';files[authpath]=encoded(auth)
    freeze={'schema':'retrace.frontier-v6l-freeze.v1','cumulative_cap_credits':'750','previous_cumulative_cap_credits':'250','runtime_config':audit.CONFIG,'deadline_utc':audit.DEADLINE.isoformat(),'created_at':'2026-11-15T00:00:01+00:00',
        'scheduled_slots':1800,'carried_final_slots':229,'carried_issued_slots':216,'continuation_slots':1571,
        'authorization_path':authpath,'authorization_sha256':sha256(files[authpath]).hexdigest(),
        'continuation_path':receiptpath,'continuation_sha256':sha256(files[receiptpath]).hexdigest(),
        'baseline_path':audit.BASELINE,'baseline_sha256':baseline_sha,'historical_conservative_carry_credits':carry,
        'observed_response_models':audit.ROUTE,'sessions_path':sessions,'sessions_sha256':audit.digest(slots),
        'sessions_file_sha256':sha256(files[sessions]).hexdigest(),'output_path':'results/frontier-v6l/continuation',
        'ledger_path':'results/frontier-v6l/budget'}
    # Finalize all immutable files before adding new run evidence.
    freeze['files']=[{'path':p,'sha256':sha256(v).hexdigest(),'bytes':len(v)} for p,v in files.items()]
    files['data/frontier-v6l-freeze.json']=encoded(freeze);fsha=sha256(files['data/frontier-v6l-freeze.json']).hexdigest()
    prefix='results/frontier-v6l/continuation/'
    manifest={'execution_manifest_sha256':fsha,'created_at':'2026-11-15T01:00:00+00:00','run_id':'new-l',
        'continuation_sha256':freeze['continuation_sha256'],'continuation_path':receiptpath,'carryover_bindings':refs,
        'earliest_next_admission_utc':(audit.stamp('2026-11-15T00:00:00+00:00')+timedelta(seconds=4)).isoformat()}
    files[prefix+'run.json']=encoded(manifest);files[prefix+'requests.jsonl']=b'';files[prefix+'responses.jsonl']=b''
    files[prefix+'slot-outcomes.jsonl']=lines([{'slot_id':sid,'issued':False,'model_outcome':'not_issued_global_stop'} for sid in pending])
    files[prefix+'summary.json']=encoded({'status':'stopped'})
    files['results/frontier-v6l/budget/ledger.jsonl']=b'{}\n'
    fake={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':'stopped',
        'counts':{'planned':1571},'checks':1,'budget_cap_credits':'750','historical_carry_credits':carry}
    return files,fsha,ksha,priors,fake


def artifact_call(files,fsha,ksha,priors,fake,*,relocated=False,mutate=None):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);snapshot='data/frontier-v6l-ledger-after-continuation.jsonl'
        for name,value in files.items():
            name=audit.ALLOWED_ALIAS.get(name,name) if relocated else name
            if relocated and name=='results/frontier-v6l/budget/ledger.jsonl':name=snapshot
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
        if mutate:mutate(root)
        # Mock references only in the NEW module; no imported frozen global is
        # mutated. The core is isolated here; its own capture tests are separate.
        with patch.object(audit,'K_FREEZE_SHA',ksha),\
             patch.object(audit,'prior_k_audit',SimpleNamespace(audit=lambda *a,**kw:deepcopy(priors['k']))),\
             patch.object(audit,'audit_evidence',side_effect=lambda *a,**kw:deepcopy(fake)) as core:
            result=audit.audit(root,fsha,frozen_aliases=audit.ALLOWED_ALIAS if relocated else None,ledger_snapshot=snapshot if relocated else None)
            return result,core.call_args


class ArtifactAuditTests(unittest.TestCase):
    def test_four_segment_bindings_and_relocation_are_exact(self):
        f,sha,ksha,priors,core=artifact_fixture()
        left,args=artifact_call(f,sha,ksha,priors,core);right,_=artifact_call(f,sha,ksha,priors,core,relocated=True)
        self.assertEqual(left,right);self.assertEqual(left['prior_segment_audits'],priors)
        self.assertEqual(left['counts']['planned'],1571)
        self.assertEqual(args.kwargs['historical'],{'carry_credits':'249.9','ledger_sha256':sha256(f[audit.BASELINE]).hexdigest(),'inherited_unsettled_attempts':65})
        self.assertEqual(len(args.kwargs['carryover']),229)
        self.assertIn('results/frontier-v6l/budget/ledger.jsonl',right['input_bindings'])
        self.assertNotIn('data/frontier-v6l-ledger-after-continuation.jsonl',right['input_bindings'])

    def test_new_and_prior_active_locks_reject(self):
        fixture=artifact_fixture()
        for segment in ('k','l'):
            def mutate(root):
                p=root/f'results/frontier-v6{segment}/budget/active.lock';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('active')
            with self.subTest(segment=segment),self.assertRaisesRegex(ValueError,'still active'):artifact_call(*fixture,mutate=mutate)

    def test_wrong_old_or_new_cap_and_unknown_release_reject(self):
        for role,field,value in [('authorization','cumulative_cap_credits','250'),('continuation','previous_cumulative_cap_credits','500'),
            ('authorization','inherited_unsettled_attempts',64),('continuation','inherited_unsettled_attempts',64)]:
            f,_,ksha,priors,core=artifact_fixture();name=f'data/frontier-v6l-{role}.json'
            obj=json.loads(f[name]);obj[field]=value;f[name]=encoded(obj)
            f,sha=refreeze(f)
            with self.subTest(role=role,field=field),self.assertRaises(ValueError):artifact_call(f,sha,ksha,priors,core)

    def test_inconsistent_freeze_counts_policy_and_authorization_reject(self):
        for key,value in [('scheduled_slots',1799),('carried_final_slots',228),('carried_issued_slots',215),('continuation_slots',1572),
            ('runtime_config',{**audit.CONFIG,'completion_delay_seconds':3}),('deadline_utc','2026-11-16T04:00:00+00:00'),
            ('previous_cumulative_cap_credits','500')]:
            f,_,ksha,priors,core=artifact_fixture();p='data/frontier-v6l-freeze.json';o=json.loads(f[p]);o[key]=value;f[p]=encoded(o);f,sha=refreeze(f)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'freeze'):artifact_call(f,sha,ksha,priors,core)
        for key,value in [('prior_status','completed'),('prior_stop_reason','administrative_stop')]:
            f,_,ksha,priors,core=artifact_fixture();p='data/frontier-v6l-authorization.json';o=json.loads(f[p]);o[key]=value;f[p]=encoded(o);f,sha=refreeze(f)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'authorization only'):artifact_call(f,sha,ksha,priors,core)

    def test_segment_freeze_path_and_original_run_id_are_exact(self):
        for change in ('path','run'):
            f,_,ksha,priors,core=artifact_fixture();p='data/frontier-v6l-continuation.json';o=json.loads(f[p])
            if change=='path':o['source_segments'][1]['freeze_path']='data/frontier-v6i-freeze.json'
            else:o['original_run_id']='prior-j'
            f[p]=encoded(o);f,sha=refreeze(f)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'segment freeze|run IDs'):artifact_call(f,sha,ksha,priors,core)

    def test_not_budget_stop_cannot_authorize_new_segment(self):
        for reason in ('deadline_stop','network_or_transport_failure','administrative_stop_file'):
            f,_,ksha,priors,core=artifact_fixture();p='results/frontier-v6k/continuation/summary.json'
            obj=json.loads(f[p]);obj['stop_reasons']=[reason];f[p]=encoded(obj)
            # Even rehashed metadata cannot change the independent saved proof.
            f,sha=refreeze(f)
            with self.subTest(reason=reason),self.assertRaises(ValueError):artifact_call(f,sha,ksha,priors,core)

    def test_tampered_carried_source_index_or_duplicate_is_rejected(self):
        for change in ('zero','bool','duplicate','wrong_hash'):
            f,_,ksha,priors,core=artifact_fixture();p='data/frontier-v6l-continuation.json';o=json.loads(f[p])
            if change=='zero':o['carried_final_outcomes'][0]['source_line_one_based']=0
            elif change=='bool':o['carried_final_outcomes'][0]['source_line_one_based']=True
            elif change=='duplicate':o['carried_final_outcomes'][1]=deepcopy(o['carried_final_outcomes'][0])
            else:o['carried_final_outcomes'][0]['row_sha256']='0'*64
            f[p]=encoded(o);f,sha=refreeze(f)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'source index|carried row'):artifact_call(f,sha,ksha,priors,core)

    def test_historical_alias_and_new_snapshot_must_match(self):
        f,sha,ksha,priors,core=artifact_fixture()
        def mutate(root): (root/next(iter(audit.ALLOWED_ALIAS.values()))).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'frozen file'):artifact_call(f,sha,ksha,priors,core,relocated=True,mutate=mutate)
        def conflicting(root):
            p=root/'results/frontier-v6l/budget/ledger.jsonl';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'conflicting')
        with self.assertRaisesRegex(ValueError,'differs from immutable snapshot'):artifact_call(f,sha,ksha,priors,core,relocated=True,mutate=conflicting)


def refreeze(files):
    """Rehash only synthetic NEW metadata so deeper admission guards execute."""
    files=deepcopy(files);authpath='data/frontier-v6l-authorization.json';receiptpath='data/frontier-v6l-continuation.json'
    auth=json.loads(files[authpath]);auth['protected']={p:sha256(files[p]).hexdigest() for p in auth['protected']}
    files[authpath]=encoded(auth)
    p='data/frontier-v6l-freeze.json';o=json.loads(files[p])
    o['authorization_sha256']=sha256(files[authpath]).hexdigest();o['continuation_sha256']=sha256(files[receiptpath]).hexdigest()
    o['files']=[{'path':r['path'],'sha256':sha256(files[r['path']]).hexdigest(),'bytes':len(files[r['path']])} for r in o['files']]
    files[p]=encoded(o);fsha=sha256(files[p]).hexdigest()
    run='results/frontier-v6l/continuation/run.json';m=json.loads(files[run]);m.update(execution_manifest_sha256=fsha,continuation_sha256=o['continuation_sha256'],carryover_bindings=json.loads(files[receiptpath])['carried_final_outcomes'])
    files[run]=encoded(m);return files,fsha


if __name__=='__main__': unittest.main()
