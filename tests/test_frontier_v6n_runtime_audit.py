"""Invented host-recovery fixtures; no live journals, semantic answers or API."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts import audit_frontier_v6n_runtime as audit
from tests import test_adaption_v6n as runtime_fixtures
from tests.test_adaption_v6n import synthetic_carry, slot, emit, final, QWEN, ROUTE


def encoded(value): return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
def lines(values): return b''.join(encoded(v) for v in values)


def capture(slots, factory=None, *, carried=None, oldq=None, oldr=None):
    seed=synthetic_carry(slots,carried)
    if oldq:seed['last_issued_model']=oldq[-1]['request']['model']
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

    def test_admission_cutoff_is0656_not_old0700(self):
        self.assertEqual(audit.DEADLINE.isoformat(),'2026-11-16T06:56:00+00:00')
        v=runtime_fixtures.ContinuationTests().run_case([slot(0)],utc_start=audit.DEADLINE)
        v.update(slots=[slot(0)],carryover={},original_requests=[],original_responses=[])
        self.assertEqual(replay(v)['schedule_status'],'stopped')
        self.assertEqual(v['requests'],[])
        v['manifest']['deadline_utc']='2026-11-16T07:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'policy binding'):replay(v)


def carry_fixture():
    from tests.test_recovery_v6n import fixture
    slots,receipt,contents=fixture(); proofs=[]
    for seg,n in zip(receipt['source_segments'][2:],(3,5)):
        q=audit.jsonl(contents[seg['paths']['requests']])[-1]
        proofs.append({'orphan':{'attempt_id':q['attempt_id'],'slot_id':q['slot_id'],
            'request_sha256':q['request_sha256'],'request_row_sha256':audit.digest(q),
            'response_observed':False,'final_observed':False,'provider_completion_unknown':True,
            'reserved_credits':audit.credits(audit.bound(slots[n]))}})
    return slots,receipt,contents,{**proofs[1],'recovery_prefix_proof':proofs[0]}


class RecoveryCarryTests(unittest.TestCase):
    def test_two_orphans_are_carried_not_responses_or_retried(self):
        s,r,c,p=carry_fixture();before=deepcopy(c)
        final,q,a,counts=audit.reconstruct_carry(s,r,c,p)
        self.assertEqual(counts,dict(full_planned_slots=7,carried_final_slots=6,carried_issued_slots=6,continuation_slots=1))
        self.assertEqual((len(q),len(a)),(6,4));self.assertEqual(c,before)
        for n in (3,5):
            self.assertFalse(audit.completed(final[s[n]['slot_id']]))
            self.assertTrue(final[s[n]['slot_id']]['actual_request_issued'])

    def test_either_overlay_cannot_fabricate_completion_even_rehashed(self):
        for which in (0,1):
            for change in ({'output_text':'guessed answer'},{'usage':{'input_tokens':1}},
                           {'actual_request_issued':False},{'issued':True},{'terminal_valid':True}):
                s,r,c,p=carry_fixture();spec=r['orphan_dispositions'][which]
                out=audit.jsonl(c[spec['path']]);out[0].update(change);c[spec['path']]=lines(out)
                spec['sha256']=sha256(c[spec['path']]).hexdigest()
                with self.subTest(which=which,change=change),self.assertRaisesRegex(ValueError,'derived orphan'):
                    audit.reconstruct_carry(s,r,c,p)

    def test_orphan_order_count_and_full_bounds_are_exact(self):
        for change in ('old_bound','new_bound','extra','swap'):
            s,r,c,p=carry_fixture()
            if change=='old_bound':p['recovery_prefix_proof']['orphan']['reserved_credits']='0'
            elif change=='new_bound':p['orphan']['reserved_credits']='0'
            elif change=='extra':c[r['source_segments'][3]['paths']['responses']]=b''
            else:r['orphan_attempt_ids'].reverse()
            with self.subTest(change=change),self.assertRaises(ValueError):audit.reconstruct_carry(s,r,c,p)

    def test_either_fake_closure_or_orphan_reissue_rejects(self):
        for which in (2,3):
            s,r,c,p=carry_fixture();r['source_segments'][which]['paths']['summary']='invented/summary.json'
            with self.assertRaisesRegex(ValueError,'fabricated k/m'):audit.reconstruct_carry(s,r,c,p)
        s,r,c,p=carry_fixture();r['continuation_slot_ids'].insert(0,s[5]['slot_id']);r['continuation_slots']+=1
        with self.assertRaisesRegex(ValueError,'untouched'):audit.reconstruct_carry(s,r,c,p)

    def test_pointer_line_and_historical_failure_are_not_normalized(self):
        s,r,c,p=carry_fixture();r['carried_final_outcomes'][0]['source_line_one_based']=0
        with self.assertRaisesRegex(ValueError,'row pointers'):audit.reconstruct_carry(s,r,c,p)
        s,r,c,p=carry_fixture();path=r['source_segments'][0]['paths']['summary'];summary=json.loads(c[path]);summary['status']='completed';c[path]=encoded(summary)
        with self.assertRaisesRegex(ValueError,'stopped status'):audit.reconstruct_carry(s,r,c,p)

    def test_orphan_seed_skips_history_and_rotates_after_last_request(self):
        slots=[slot(0,'glm-5.2'),slot(1,'glm-5.2',history_from=['s-0']),slot(2),slot(3,'glm-5.2')]
        c,q,r=carried_seed(slots,False)
        c['s-0'].update(issued=False,actual_request_issued=True,model_outcome='issued_without_response',
            error='process_interruption_orphan_request',attempt_id=None,first_attempt_id=q[0]['attempt_id'])
        v=capture(slots,carried=c,oldq=q,oldr=[]);result=replay(v)
        self.assertEqual(result['counts']['dependency_skips'],1)
        self.assertEqual([x['slot_id'] for x in v['requests']],['s-2','s-3'])
        self.assertEqual(len(v['original_responses']),0)


def artifact_fixture():
    """Mock only historical prefix/core replays at this file-authentication boundary."""
    s,r,c,p=carry_fixture();slots=s+[slot(n) for n in range(7,1800)]
    files={};sources=[];refs=[]
    for seg in r['source_segments']:
        name=seg['segment'];paths={k:audit.PREFIXES[name]+v for k,v in audit.ROLE_NAMES.items() if name in ('i','j') or k not in ('summary','audit')}
        paths['ledger']=f'results/frontier-v6{name}/budget/ledger.jsonl'
        for role,path in paths.items():
            if role in seg['paths']:
                raw=c[seg['paths'][role]]
                if role=='run_manifest':
                    value=json.loads(raw);value.update(slots=slots,sessions_sha256=audit.digest(slots));raw=encoded(value)
                elif role=='outcomes' and name in ('i','j'):
                    values=audit.jsonl(raw)
                    for other in slots[7:]:
                        values.append({**{key:other[key] for key in ('slot_id','case_id','model','condition','phase')},
                            'run_id':seg['run_id'],'issued':False,'attempts_issued':0,'model_outcome':'not_issued_global_stop'})
                    raw=lines(values)
                files[path]=raw
            elif role=='ledger':files[path]=b'{}\n'
            else:files[path]=encoded({'passed':True})
        first=audit.jsonl(files[paths['outcomes']])[0]
        refs.append({'segment':name,'slot_id':first['slot_id'],'source_path':paths['outcomes'],'source_line_one_based':1,
            'row_sha256':audit.digest(first),'attempt_id':first['attempt_id'],'model_outcome':first['model_outcome']})
        sources.append({**seg,'paths':paths,'sha256':{key:sha256(files[path]).hexdigest() for key,path in paths.items()},
            'freeze_path':f'data/frontier-v6{name}-freeze.json',
            'freeze_sha256':{'i':audit.I_FREEZE_SHA,'j':audit.J_FREEZE_SHA,'k':audit.K_FREEZE_SHA,'m':'pending'}[name]})
    files['historical.txt']=b'unchanged old byte fixture'
    files['data/frontier-v6m-freeze.json']=encoded({'files':[{'path':'historical.txt','sha256':sha256(files['historical.txt']).hexdigest()}]})
    msha=sha256(files['data/frontier-v6m-freeze.json']).hexdigest();sources[-1]['freeze_sha256']=msha
    for lock in audit.ALLOWED_ALIAS:files[lock]=b'preserved historical lock'
    q=audit.jsonl(files[sources[-1]['paths']['requests']])[-1]
    files[audit.BASELINE]=lines([{'sha256':'d'*64,'event':{'kind':'reserve','attempt_id':q['attempt_id']}}])
    files[sources[-1]['paths']['ledger']]=files[audit.BASELINE]
    sources[-1]['sha256']['ledger']=sha256(files[audit.BASELINE]).hexdigest()
    prior={**p['recovery_prefix_proof'],'passed':True,'final_closed':False,'schedule_status':'interrupted_without_closure',
        'prior_segment_audits':{'i':{'passed':True},'j':{'passed':True}}}
    files[audit.OLD_PROOF]=encoded(prior);oldpsha=sha256(files[audit.OLD_PROOF]).hexdigest()
    oldoverlay=audit.jsonl(c[audit.OLD_OVERLAY])[0];oldoverlay['recovery_proof_sha256']=oldpsha
    files[audit.OLD_OVERLAY]=lines([oldoverlay])
    proof={**p,'recovery_prefix_proof':prior,'passed':True,'final_closed':False,'schedule_status':'interrupted_without_closure',
        'cumulative_accounted_credits':'300','cumulative_inherited_unsettled_attempts':74,
        'host_observation':{'observed_at_utc':r['recovery_observed_at_utc']},'ledger_chain_sha256':'d'*64,
        'prior_segment_audits':prior['prior_segment_audits'],
        'input_bindings':{path:{'sha256':sha256(raw).hexdigest(),'bytes':len(raw)} for path,raw in files.items()}}
    files[audit.PROOF]=encoded(proof);proof_sha=sha256(files[audit.PROOF]).hexdigest()
    overlay=audit.jsonl(c[audit.OVERLAY])[0];overlay['recovery_proof_sha256']=proof_sha
    files[audit.OVERLAY]=lines([overlay]);specs=deepcopy(r['orphan_dispositions'])
    for spec,row,psha,segment in zip(specs,(oldoverlay,overlay),(oldpsha,proof_sha),('recovery','recovery_m')):
        spec['sha256']=sha256(files[spec['path']]).hexdigest();spec['proof_sha256']=psha
        refs.append({'segment':segment,'slot_id':row['slot_id'],'source_path':spec['path'],'source_line_one_based':1,
            'row_sha256':audit.digest(row),'attempt_id':None,'model_outcome':'issued_without_response'})
    files['scripts/audit_frontier_v6n_prefix.py']=b'# explicit mocked prefix replay fixture\n'
    files['scripts/audit_frontier_v6n_runtime.py']=Path(audit.__file__).read_bytes()
    sessionpath='data/frontier-v6i-sessions.json';files[sessionpath]=encoded(slots)
    common={'prior_freeze_path':'data/frontier-v6m-freeze.json','prior_freeze_sha256':msha,
        'baseline_snapshot_path':audit.BASELINE,'baseline_snapshot_sha256':sha256(files[audit.BASELINE]).hexdigest(),
        'historical_conservative_carry_credits':'300','inherited_unsettled_attempts':74,
        'previous_cumulative_cap_credits':'750','cumulative_cap_credits':'750','deadline_utc':audit.DEADLINE.isoformat()}
    receipt={**r,**common,'schema':'retrace.frontier-v6n-continuation.v1','full_planned_slots':1800,
        'actual_prior_requests':6,'observed_prior_responses':4,
        'sessions_path':sessionpath,'sessions_sha256':audit.digest(slots),'source_segments':sources,'carried_final_outcomes':refs,
        'continuation_slots':1794,'continuation_slot_ids':[x['slot_id'] for x in slots[6:]],'observed_response_models':audit.ROUTE,
        'recovery_proof_path':audit.PROOF,'recovery_proof_sha256':proof_sha,'orphan_dispositions':specs,
        'recovery_auditor_path':'scripts/audit_frontier_v6n_prefix.py',
        'recovery_auditor_sha256':sha256(files['scripts/audit_frontier_v6n_prefix.py']).hexdigest(),
        'prior_journal_files':{path:sha256(files[path]).hexdigest() for seg in sources for path in seg['paths'].values()}}
    receiptpath='data/frontier-v6n-continuation.json';files[receiptpath]=encoded(receipt)
    auth={**common,'schema':'retrace.frontier-v6n-authorization.v1','prior_status':'interrupted_without_closure',
        'prior_stop_reason':'process_exit_without_closure','original_rows_changed':False,'old_k_closure_asserted':False,
        'old_m_closure_asserted':False,'orphan_retried':False,
        'protected_v5_file_count':402,'protected':{path:sha256(raw).hexdigest() for path,raw in files.items()}}
    authpath='data/frontier-v6n-authorization.json';files[authpath]=encoded(auth)
    freeze={'schema':'retrace.frontier-v6n-freeze.v1',**common,'created_at':'2026-11-15T16:40:01+00:00',
        'runtime_config':audit.CONFIG,'authorization_path':authpath,'authorization_sha256':sha256(files[authpath]).hexdigest(),
        'continuation_path':receiptpath,'continuation_sha256':sha256(files[receiptpath]).hexdigest(),
        'baseline_path':audit.BASELINE,'baseline_sha256':common['baseline_snapshot_sha256'],
        'observed_response_models':audit.ROUTE,'sessions_path':sessionpath,'sessions_sha256':audit.digest(slots),
        'sessions_file_sha256':sha256(files[sessionpath]).hexdigest(),'scheduled_slots':1800,'carried_final_slots':6,'carried_issued_slots':6,
        'continuation_slots':1794,'output_path':'results/frontier-v6n/continuation','ledger_path':'results/frontier-v6n/budget',
        'files':[{'path':path,'sha256':sha256(raw).hexdigest(),'bytes':len(raw)} for path,raw in files.items()]}
    files['data/frontier-v6n-freeze.json']=encoded(freeze);fsha=sha256(files['data/frontier-v6n-freeze.json']).hexdigest()
    run='results/frontier-v6n/continuation/'
    files[run+'run.json']=encoded({'run_id':'new-n','created_at':'2026-11-15T16:45:00+00:00','execution_manifest_sha256':fsha,
        'continuation_path':receiptpath,'continuation_sha256':freeze['continuation_sha256'],'carryover_bindings':refs,
        'earliest_next_admission_utc':'2026-11-15T16:15:35.861481+00:00'})
    for name in ('requests.jsonl','responses.jsonl','slot-outcomes.jsonl'):files[run+name]=b''
    files[run+'summary.json']=encoded({'status':'stopped'});files['results/frontier-v6n/budget/ledger.jsonl']=b'{}\n'
    fake={'passed':True,'final_closed':True,'schedule_status':'stopped','checks':1,'counts':{'planned':1794},'cumulative_accounted_credits':'300'}
    return files,fsha,msha,proof,fake


def artifact_call(data, *, relocated=False, mutate=None):
    files,fsha,msha,proof,fake=data
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);snapshot='data/frontier-v6n-ledger-after-continuation.jsonl'
        for name,raw in files.items():
            target=audit.ALLOWED_ALIAS.get(name,name) if relocated else name
            if relocated and name=='results/frontier-v6n/budget/ledger.jsonl':target=snapshot
            path=root/target;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        if mutate:mutate(root)
        with patch.object(audit,'M_FREEZE_SHA',msha),patch.object(audit.prefix_audit,'audit',return_value=proof),patch.object(audit,'audit_evidence',return_value=deepcopy(fake)):
            return audit.audit(root,fsha,frozen_aliases=audit.ALLOWED_ALIAS if relocated else None,ledger_snapshot=snapshot if relocated else None)


class ArtifactTests(unittest.TestCase):
    def test_relocation_with_three_inert_locks_is_exact(self):
        fixture=artifact_fixture();a=artifact_call(fixture);b=artifact_call(fixture,relocated=True)
        self.assertEqual(a,b);self.assertFalse(a['recovery_prefix_proof']['final_closed'])
        self.assertFalse(a['recovery_prefix_proof']['recovery_prefix_proof']['final_closed'])
        self.assertEqual(a['request_accounting']['historical_actual_requests'],6)
        self.assertEqual(a['request_accounting']['historical_provider_responses'],4)
        self.assertEqual(a['request_accounting']['historical_orphan_requests'],2)
        self.assertIn(audit.OVERLAY,a['input_bindings']);self.assertIn(audit.OLD_OVERLAY,a['input_bindings'])

    def test_no_fake_k_or_m_closure_or_live_n_lock(self):
        paths=[f'results/frontier-v6{x}/continuation/{name}' for x in ('k','m') for name in ('summary.json','runtime-audit.json')]
        for path in paths+['results/frontier-v6n/budget/active.lock']:
            def mutate(root):
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'{}')
            with self.subTest(path=path),self.assertRaises(ValueError):artifact_call(artifact_fixture(),mutate=mutate)

    def test_freeze_counts_policy_and_deadline_cannot_drift(self):
        for key,value in (('carried_issued_slots',7),('scheduled_slots',1799),('deadline_utc','2026-11-16T07:00:00+00:00'),('previous_cumulative_cap_credits','250')):
            data=list(artifact_fixture());freeze=json.loads(data[0]['data/frontier-v6n-freeze.json']);freeze[key]=value
            data[0]['data/frontier-v6n-freeze.json']=encoded(freeze);data[1]=sha256(data[0]['data/frontier-v6n-freeze.json']).hexdigest()
            with self.subTest(key=key),self.assertRaises(ValueError):artifact_call(data)

    def test_changed_orphan_snapshot_or_nested_proof_rejected(self):
        def mutate(root): (root/audit.BASELINE).write_bytes(b'tamper\n')
        with self.assertRaises(ValueError):artifact_call(artifact_fixture(),mutate=mutate)
        data=list(artifact_fixture());data[3]['recovery_prefix_proof']['final_closed']=True
        with self.assertRaisesRegex(ValueError,'prefix proof'):artifact_call(data)


if __name__=='__main__':unittest.main()



