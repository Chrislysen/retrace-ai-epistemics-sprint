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

from scripts import audit_frontier_v6m_runtime as audit
from tests import test_adaption_v6m as runtime_fixtures
from tests.test_adaption_v6m import synthetic_carry, slot, emit, final, QWEN, ROUTE


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



def carry_fixture():
    from tests.test_recovery_v6m import fixture
    slots,receipt,contents=fixture()
    q=audit.jsonl(contents[receipt['source_segments'][2]['paths']['requests']])[-1]
    proof={'orphan':{'attempt_id':q['attempt_id'],'slot_id':q['slot_id'],
        'request_sha256':q['request_sha256'],'request_row_sha256':audit.digest(q),
        'response_observed':False,'final_observed':False,'provider_completion_unknown':True,
        'reserved_credits':audit.credits(audit.bound(slots[3]))}}
    return slots,receipt,contents,proof


class RecoveryCarryTests(unittest.TestCase):
    def test_orphan_is_carried_not_response_or_retry(self):
        s,r,c,p=carry_fixture();before=deepcopy(c)
        final,q,a,counts=audit.reconstruct_carry(s,r,c,p)
        self.assertEqual(counts,dict(full_planned_slots=5,carried_final_slots=4,carried_issued_slots=4,continuation_slots=1))
        self.assertEqual((len(q),len(a)),(4,3));self.assertFalse(audit.completed(final[s[3]['slot_id']]))
        self.assertTrue(final[s[3]['slot_id']]['actual_request_issued']);self.assertEqual(c,before)

    def test_overlay_cannot_fabricate_status_output_or_usage(self):
        for change in ({'output_text':'partial guessed answer'},{'usage':{'input_tokens':1}},
                       {'actual_request_issued':False},{'issued':True},{'terminal_valid':True}):
            s,r,c,p=carry_fixture();out=audit.jsonl(c[r['orphan_disposition_path']]);out[0].update(change)
            c[r['orphan_disposition_path']]=lines(out)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'derived orphan'):audit.reconstruct_carry(s,r,c,p)

    def test_orphan_second_missing_response_and_lower_bound_reject(self):
        s,r,c,p=carry_fixture();p['orphan']['reserved_credits']='0'
        with self.assertRaisesRegex(ValueError,'full bound'):audit.reconstruct_carry(s,r,c,p)
        s,r,c,p=carry_fixture();c[r['source_segments'][2]['paths']['responses']]=b''
        with self.assertRaisesRegex(ValueError,'one final orphan'):audit.reconstruct_carry(s,r,c,p)

    def test_fabricated_k_closure_or_reissue_reject(self):
        s,r,c,p=carry_fixture();r['source_segments'][2]['paths']['summary']='invented/summary.json'
        with self.assertRaisesRegex(ValueError,'fabricated k'):audit.reconstruct_carry(s,r,c,p)
        s,r,c,p=carry_fixture();r['continuation_slot_ids'].insert(0,s[3]['slot_id']);r['continuation_slots']+=1
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
            error='host_interruption_orphan_request',attempt_id=None,first_attempt_id=q[0]['attempt_id'])
        v=capture(slots,carried=c,oldq=q,oldr=[]);result=replay(v)
        self.assertEqual(result['counts']['dependency_skips'],1)
        self.assertEqual([x['slot_id'] for x in v['requests']],['s-2','s-3'])
        self.assertEqual(len(v['original_responses']),0)


def artifact_fixture():
    """File-boundary fixtures mock only the separately tested prefix/core replays."""
    s,r,c,p=carry_fixture(); slots=s+[slot(n) for n in range(5,1800)]
    files={};sources=[];refs=[]
    for seg in r['source_segments']:
        name=seg['segment']; paths={k:audit.PREFIXES[name]+v for k,v in audit.ROLE_NAMES.items() if name!='k' or k not in ('summary','audit')}
        paths['ledger']=f'results/frontier-v6{name}/budget/ledger.jsonl'
        for role,path in paths.items():
            if role in seg['paths']:
                raw=c[seg['paths'][role]]
                if role=='run_manifest':
                    value=json.loads(raw);value.update(slots=slots,sessions_sha256=audit.digest(slots));raw=encoded(value)
                elif role=='outcomes' and name!='k':
                    values=audit.jsonl(raw)
                    for other in slots[5:]:
                        values.append({**{key:other[key] for key in ('slot_id','case_id','model','condition','phase')},
                            'run_id':seg['run_id'],'issued':False,'attempts_issued':0,'model_outcome':'not_issued_global_stop'})
                    raw=lines(values)
                files[path]=raw
            elif role=='ledger':files[path]=b'{}\n'
            else:files[path]=encoded({'passed':True})
        out=audit.jsonl(files[paths['outcomes']]);first=out[0]
        refs.append({'segment':name,'slot_id':first['slot_id'],'source_path':paths['outcomes'],'source_line_one_based':1,
            'row_sha256':audit.digest(first),'attempt_id':first['attempt_id'],'model_outcome':first['model_outcome']})
        sources.append({**seg,'paths':paths,'sha256':{key:sha256(files[path]).hexdigest() for key,path in paths.items()},
            'freeze_path':f'data/frontier-v6{name}-freeze.json',
            'freeze_sha256':{'i':audit.I_FREEZE_SHA,'j':audit.J_FREEZE_SHA,'k':'pending'}[name]})
    files['historical.txt']=b'unchanged old byte fixture'
    files['data/frontier-v6k-freeze.json']=encoded({'files':[{'path':'historical.txt','sha256':sha256(files['historical.txt']).hexdigest()}]})
    ksha=sha256(files['data/frontier-v6k-freeze.json']).hexdigest();sources[-1]['freeze_sha256']=ksha
    for lock in audit.ALLOWED_ALIAS:files[lock]=b'preserved historical lock'
    q=audit.jsonl(files[sources[-1]['paths']['requests']])[-1]
    files[audit.BASELINE]=lines([{'sha256':'d'*64,'event':{'kind':'reserve','attempt_id':q['attempt_id']}}])
    files[sources[-1]['paths']['ledger']]=files[audit.BASELINE]
    sources[-1]['sha256']['ledger']=sha256(files[audit.BASELINE]).hexdigest()
    proof={**p,'passed':True,'final_closed':False,'schedule_status':'interrupted_without_closure',
        'cumulative_accounted_credits':'249','cumulative_inherited_unsettled_attempts':73,
        'host_observation':{'observed_at_utc':r['recovery_observed_at_utc']},'ledger_chain_sha256':'d'*64,
        'prior_segment_audits':{'i':{'passed':True},'j':{'passed':True}},
        'input_bindings':{path:{'sha256':sha256(raw).hexdigest(),'bytes':len(raw)} for path,raw in files.items()}}
    files[audit.PROOF]=encoded(proof);proof_sha=sha256(files[audit.PROOF]).hexdigest()
    overlay=audit.jsonl(c[r['orphan_disposition_path']])[0]
    overlay.update(recovery_proof_path=audit.PROOF,recovery_proof_sha256=proof_sha)
    files[audit.OVERLAY]=lines([overlay])
    refs.append({'segment':'recovery','slot_id':overlay['slot_id'],'source_path':audit.OVERLAY,'source_line_one_based':1,
        'row_sha256':audit.digest(overlay),'attempt_id':None,'model_outcome':'issued_without_response'})
    files['scripts/audit_frontier_v6m_prefix.py']=b'# explicit mocked prefix replay fixture\n'
    files['scripts/audit_frontier_v6m_runtime.py']=Path(audit.__file__).read_bytes()
    sessionpath='data/frontier-v6i-sessions.json';files[sessionpath]=encoded(slots)
    common={'prior_freeze_path':'data/frontier-v6k-freeze.json','prior_freeze_sha256':ksha,
        'baseline_snapshot_path':audit.BASELINE,'baseline_snapshot_sha256':sha256(files[audit.BASELINE]).hexdigest(),
        'historical_conservative_carry_credits':'249','inherited_unsettled_attempts':73,
        'previous_cumulative_cap_credits':'250','cumulative_cap_credits':'750','deadline_utc':audit.DEADLINE.isoformat()}
    receipt={**r,**common,'schema':'retrace.frontier-v6m-continuation.v1','full_planned_slots':1800,
        'actual_prior_requests':4,'observed_prior_responses':3,
        'sessions_path':sessionpath,'sessions_sha256':audit.digest(slots),'source_segments':sources,'carried_final_outcomes':refs,
        'continuation_slots':1796,'continuation_slot_ids':[x['slot_id'] for x in slots[4:]],'observed_response_models':audit.ROUTE,
        'recovery_proof_path':audit.PROOF,'recovery_proof_sha256':proof_sha,'orphan_disposition_path':audit.OVERLAY,
        'orphan_disposition_sha256':sha256(files[audit.OVERLAY]).hexdigest(),'recovery_auditor_path':'scripts/audit_frontier_v6m_prefix.py',
        'recovery_auditor_sha256':sha256(files['scripts/audit_frontier_v6m_prefix.py']).hexdigest(),
        'prior_journal_files':{path:sha256(files[path]).hexdigest() for seg in sources for path in seg['paths'].values()}}
    receiptpath='data/frontier-v6m-continuation.json';files[receiptpath]=encoded(receipt)
    auth={**common,'schema':'retrace.frontier-v6m-authorization.v1','prior_status':'interrupted_without_closure',
        'prior_stop_reason':'host_session_loss','original_rows_changed':False,'old_k_closure_asserted':False,'orphan_retried':False,
        'protected_v5_file_count':402,'protected':{path:sha256(raw).hexdigest() for path,raw in files.items()}}
    authpath='data/frontier-v6m-authorization.json';files[authpath]=encoded(auth)
    freeze={'schema':'retrace.frontier-v6m-freeze.v1',**common,'created_at':'2026-11-15T14:40:01+00:00',
        'runtime_config':audit.CONFIG,'authorization_path':authpath,'authorization_sha256':sha256(files[authpath]).hexdigest(),
        'continuation_path':receiptpath,'continuation_sha256':sha256(files[receiptpath]).hexdigest(),
        'baseline_path':audit.BASELINE,'baseline_sha256':common['baseline_snapshot_sha256'],
        'observed_response_models':audit.ROUTE,'sessions_path':sessionpath,'sessions_sha256':audit.digest(slots),
        'sessions_file_sha256':sha256(files[sessionpath]).hexdigest(),'scheduled_slots':1800,'carried_final_slots':4,'carried_issued_slots':4,
        'continuation_slots':1796,'output_path':'results/frontier-v6m/continuation','ledger_path':'results/frontier-v6m/budget',
        'files':[{'path':path,'sha256':sha256(raw).hexdigest(),'bytes':len(raw)} for path,raw in files.items()]}
    files['data/frontier-v6m-freeze.json']=encoded(freeze);fsha=sha256(files['data/frontier-v6m-freeze.json']).hexdigest()
    run='results/frontier-v6m/continuation/'
    files[run+'run.json']=encoded({'run_id':'new-m','created_at':'2026-11-15T14:45:00+00:00','execution_manifest_sha256':fsha,
        'continuation_path':receiptpath,'continuation_sha256':freeze['continuation_sha256'],'carryover_bindings':refs,
        'earliest_next_admission_utc':'2026-11-15T14:40:04+00:00'})
    for name in ('requests.jsonl','responses.jsonl','slot-outcomes.jsonl'):files[run+name]=b''
    files[run+'summary.json']=encoded({'status':'stopped'})
    files['results/frontier-v6m/budget/ledger.jsonl']=b'{}\n'
    fake={'passed':True,'final_closed':True,'schedule_status':'stopped','checks':1,'counts':{'planned':1796},'cumulative_accounted_credits':'249'}
    return files,fsha,ksha,proof,fake


def artifact_call(data, *, relocated=False, mutate=None):
    files,fsha,ksha,proof,fake=data
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);snapshot='data/frontier-v6m-ledger-after-continuation.jsonl'
        for name,raw in files.items():
            target=audit.ALLOWED_ALIAS.get(name,name) if relocated else name
            if relocated and name=='results/frontier-v6m/budget/ledger.jsonl':target=snapshot
            path=root/target;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        if mutate:mutate(root)
        with patch.object(audit,'K_FREEZE_SHA',ksha),patch.object(audit.prefix_audit,'audit',return_value=proof),patch.object(audit,'audit_evidence',return_value=deepcopy(fake)):
            return audit.audit(root,fsha,frozen_aliases=audit.ALLOWED_ALIAS if relocated else None,ledger_snapshot=snapshot if relocated else None)


class ArtifactTests(unittest.TestCase):
    def test_relocation_with_two_inert_locks_is_exact(self):
        fixture=artifact_fixture();a=artifact_call(fixture);b=artifact_call(fixture,relocated=True)
        self.assertEqual(a,b);self.assertFalse(a['recovery_prefix_proof']['final_closed'])
        self.assertEqual(a['request_accounting']['historical_actual_requests'],4)
        self.assertEqual(a['request_accounting']['historical_provider_responses'],3)
        self.assertIn(audit.OVERLAY,a['input_bindings'])

    def test_no_fake_k_closure_or_live_new_lock(self):
        for path in ('results/frontier-v6k/continuation/summary.json','results/frontier-v6k/continuation/runtime-audit.json','results/frontier-v6m/budget/active.lock'):
            def mutate(root):
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'{}')
            with self.subTest(path=path),self.assertRaises(ValueError):artifact_call(artifact_fixture(),mutate=mutate)

    def test_freeze_counts_policy_and_deadline_cannot_drift(self):
        for key,value in (('carried_issued_slots',5),('scheduled_slots',1799),('deadline_utc','2026-11-16T03:55:00+00:00'),('previous_cumulative_cap_credits','500')):
            data=list(artifact_fixture());freeze=json.loads(data[0]['data/frontier-v6m-freeze.json']);freeze[key]=value
            data[0]['data/frontier-v6m-freeze.json']=encoded(freeze);data[1]=sha256(data[0]['data/frontier-v6m-freeze.json']).hexdigest()
            with self.subTest(key=key),self.assertRaises(ValueError):artifact_call(data)

    def test_changed_orphan_stream_or_proof_rejected(self):
        data=artifact_fixture()
        def mutate(root): (root/audit.BASELINE).write_bytes(b'tamper\n')
        with self.assertRaises(ValueError):artifact_call(data,mutate=mutate)
        data=list(artifact_fixture());data[3]['final_closed']=True
        with self.assertRaisesRegex(ValueError,'prefix proof'):artifact_call(data)


if __name__=="__main__":unittest.main()
if __name__=="__main__":unittest.main()
