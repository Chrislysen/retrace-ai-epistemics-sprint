"""Independent continuation audit against fake-clock runtime captures; no API."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from retrace import adaption_v6j as runtime
from scripts import audit_frontier_v6j_runtime as audit
from tests.test_adaption_v6j import synthetic_carry,make_manifest,Clock,QWEN,ROUTE
from tests.test_adaption_v6h import KEY,slot,emit,final
ROOT=Path(__file__).resolve().parents[1]


def captured(slots, factory=None, *, seeds=None, oldq=None, oldr=None):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);clock=Clock();ledger=runtime.RollingLedger(root/'budget',baseline_path=ROOT/runtime.BASELINE_LEDGER)
        p=root/'execution.json';h=make_manifest(p,slots);carry=synthetic_carry(slots,seeds)
        if oldr:carry['last_issued_model']=oldr[-1]['model']
        async def transport(body):
            if factory:
                async for x in factory(body):yield x
            else:
                async for x in emit(final({**body,'model':runtime.OBSERVED_RESPONSE_MODELS.get(body['model'],body['model'])})):yield x
        try:
            with patch.object(runtime,'verify_continuation',return_value=carry):
                asyncio.run(runtime.run_slots(slots,api_key=KEY,output_dir=root/'run',ledger=ledger,transport=transport,execution_manifest_path=p,execution_manifest_sha256=h,_clock=clock.now,_sleep=clock.sleep,_utcnow=lambda:datetime(2026,11,14,tzinfo=timezone.utc)))
        finally:ledger.close()
        read=lambda name:audit.jsonl((root/name).read_bytes())
        return {'slots':slots,'manifest':read('run/run.json')[0],'requests':read('run/requests.jsonl'),'responses':read('run/responses.jsonl'),'finals':read('run/slot-outcomes.jsonl'),'summary':json.loads((root/'run/summary.json').read_text()),'ledger':read('budget/ledger.jsonl'),'streams':{p.name:p.read_bytes() for p in (root/'run/streams').iterdir()},'carryover':seeds or {},'original_requests':oldq or [],'original_responses':oldr or []}


def replay(v):
    return audit.audit_evidence(**{k:x for k,x in v.items() if k!='streams'},read_stream=lambda name:v['streams'][name],allow_test_hooks=True)


def seed(slots, success=True):
    s=slots[0];aid='original:'+s['slot_id'];body=audit.expected_body(s,{},{});at='2026-11-13T23:00:00+00:00'
    row={**{k:s[k] for k in ('slot_id','model','case_id','condition','phase')},'issued':True,'terminal_valid':success,'model_outcome':'completed' if success else 'operational_failure','response_status':'completed' if success else None,'error':None if success else 'response_model_mismatch','failure_scope':None if success else 'global','output_text':'ACTUAL PRIOR' if success else '', 'attempt_id':aid,'at':at}
    return {s['slot_id']:row},[{'attempt_id':aid,'request':body}], [row]


class AuditTests(unittest.TestCase):
    def test_serial_complete_and_seventeen_inherited_unknowns(self):
        v=captured([slot(0),slot(1)]);r=replay(v)
        self.assertEqual(r['counts']['planned'],2);self.assertEqual(r['historical_carry_credits'],'47.653269434')
        self.assertGreaterEqual(r['minimum_completion_gap_seconds'],4)
    def test_observed_route_only_and_raw_identity_retained(self):
        v=captured([slot(0,QWEN)]);r=replay(v);self.assertTrue(r['passed'])
        v['responses'][0]['returned_model']=QWEN
        with self.assertRaisesRegex(ValueError,'returned model'):replay(v)
    def test_carried_actual_output_and_cursor_no_reissue(self):
        slots=[slot(0,QWEN),slot(1,QWEN,history_from=['s-0'])]
        # History must have same model for valid runtime schema.
        slots[1]['model']=QWEN
        c,q,r=seed(slots);v=captured(slots,seeds=c,oldq=q,oldr=r);result=replay(v)
        self.assertEqual(result['counts']['planned'],1);self.assertEqual(result['original_planned_slots'],2)
        self.assertIn('ACTUAL PRIOR',str(v['requests'][0]['request']))
        bad=deepcopy(v);bad['original_requests'][0]['request']['input'][-1]['content']='invented'
        with self.assertRaisesRegex(ValueError,'actual source'):replay(bad)
    def test_failed_carried_producer_two_skips(self):
        slots=[slot(0,QWEN),slot(1,QWEN,history_from=['s-0']),slot(2,QWEN,history_from=['s-0','s-1']),slot(3)]
        c,q,r=seed(slots,False);v=captured(slots,seeds=c,oldq=q,oldr=r);out=replay(v)
        self.assertEqual(out['counts']['dependency_skips'],2);self.assertEqual(out['counts']['issued_attempts'],1)
        self.assertEqual(out['schedule_status'],'completed')
    def test_429_retry_and_exhaustion_delay(self):
        async def t(body):
            yield {'http_status':429,'content_type':'application/json','retry_after':'66'}
            yield b'{"error":"rate limited"}'
        v=captured([slot(0),slot(1)],t);r=replay(v)
        self.assertEqual(r['counts']['http_429_attempts'],6);self.assertGreaterEqual(r['minimum_cooldown_margin_seconds'],0)
    def test_failed_slot_retains_full_bound_and_continues(self):
        calls=[0]
        async def t(body):
            calls[0]+=1
            if calls[0]==1:raise asyncio.TimeoutError()
            async for e in emit(final(body)):yield e
        v=captured([slot(0),slot(1)],t);r=replay(v)
        self.assertEqual(r['counts']['per_slot_operational_failures'],1);self.assertEqual(r['counts']['completed'],1)
        self.assertGreater(float(r['retained_run_bounds_credits']),0)
    def test_new_global_route_failure_cannot_complete(self):
        v=captured([slot(0,QWEN)],lambda body:emit(final(body)));self.assertEqual(replay(v)['schedule_status'],'stopped')
        v['summary']['status']='completed'
        with self.assertRaises(ValueError):replay(v)
    def test_carried_slot_in_new_journal_is_rejected(self):
        slots=[slot(0),slot(1)];c,q,r=seed(slots);v=captured(slots,seeds=c,oldq=q,oldr=r)
        v['finals'].append(c['s-0'])
        with self.assertRaisesRegex(ValueError,'carried slot'):replay(v)
    def test_snapshot_missing_or_active_is_not_a_completed_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):audit.audit(tmp,'0'*64)

    def test_full_artifact_authentication_relocates_with_only_pinned_alias(self):
        # Artifact-layer fixture only; actual runtime semantics are separately
        # replayed in the tests above, without mocking the pure core.
        from datetime import timedelta
        slots=[{"slot_id":f"s-{n}"} for n in range(1800)]
        ids=[s["slot_id"] for s in slots[:6]];pending=[s["slot_id"] for s in slots[6:]]
        oldrows=[{"slot_id":sid,"issued":True,"attempt_id":"old:"+sid,"model_outcome":"completed","terminal_valid":True,"failure_scope":None} for sid in ids]
        oldrows[-1].update(model_outcome="operational_failure",terminal_valid=False,failure_scope="global",error="response_model_mismatch")
        raw=lambda x:(json.dumps(x)+"\n").encode()
        olddir="results/frontier-v6i/primary/";newdir="results/frontier-v6j/continuation/"
        files={olddir+"requests.jsonl":b"".join(raw(x) for x in oldrows),olddir+"responses.jsonl":b"".join(raw(x) for x in oldrows),olddir+"slot-outcomes.jsonl":b"".join(raw(x) for x in oldrows),olddir+"summary.json":raw({"run_id":"old","stop_reasons":["response_model_mismatch"],"issued_attempts":6,"retries":0}),olddir+"run.json":raw({"run_id":"old"})}
        oldbindings={name:{"sha256":sha256(value).hexdigest(),"bytes":len(value)} for name,value in files.items()}
        oldaudit={"schedule_status":"stopped","cumulative_accounted_credits":audit.CARRY,"input_bindings":oldbindings}
        files[olddir+"runtime-audit.json"]=raw(oldaudit)
        baseline="data/frontier-v6i-ledger-after-study.jsonl";files[baseline]=(ROOT/baseline).read_bytes()
        sessions="data/frontier-v6i-sessions.json";files[sessions]=raw(slots)
        receipt={"baseline_snapshot_path":baseline,"historical_conservative_carry_credits":audit.CARRY,"sessions_sha256":audit.digest(slots),"prior_journal_files":{k:v['sha256'] for k,v in oldbindings.items()},"original_run_id":"old","carryover_rows":[{"slot_id":r['slot_id'],"source_path":olddir+'slot-outcomes.jsonl',"source_line_one_based":n,"row_sha256":audit.digest(r),"attempt_id":r['attempt_id'],"model_outcome":r['model_outcome']} for n,r in enumerate(oldrows,1)],"permanently_excluded_issued_slot_ids":ids,"continuation_slot_ids":pending,"route_evidence":{"original_response_row_sha256":audit.digest(oldrows[-1])},"failed_producer_descendant_slot_ids":pending[:2]}
        receiptpath='data/frontier-v6j-continuation.json';files[receiptpath]=raw(receipt);rsha=sha256(files[receiptpath]).hexdigest()
        lock=next(iter(audit.ALLOWED_ALIAS));inert=audit.ALLOWED_ALIAS[lock];files[lock]=b'inert old lock'
        for n in range(1035-len(files)):files[f'protected/{n}.txt']=str(n).encode()
        protected={name:sha256(value).hexdigest() for name,value in files.items()}
        authname='data/frontier-v6j-authorization.json';files[authname]=raw({'protected':protected,'protected_v5_file_count':402})
        freeze={'schema':'retrace.frontier-v6j-freeze.v1','created_at':'2026-11-14T00:00:00+00:00','files':[{'path':k,'sha256':sha256(v).hexdigest()} for k,v in files.items()],'authorization_path':authname,'authorization_sha256':sha256(files[authname]).hexdigest(),'continuation_path':receiptpath,'continuation_sha256':rsha,'baseline_path':baseline,'baseline_sha256':audit.PRIOR_SHA,'historical_conservative_carry_credits':audit.CARRY,'observed_response_models':audit.ROUTE,'sessions_path':sessions,'sessions_sha256':audit.digest(slots),'sessions_file_sha256':sha256(files[sessions]).hexdigest(),'output_path':newdir.rstrip('/'),'ledger_path':'results/frontier-v6j/budget'}
        files['data/frontier-v6j-freeze.json']=raw(freeze);fsha=sha256(files['data/frontier-v6j-freeze.json']).hexdigest()
        earliest=(audit.stamp(audit.jsonl(files[baseline])[-1]['at'])+timedelta(seconds=4)).isoformat()
        files[newdir+'run.json']=raw({'execution_manifest_sha256':fsha,'created_at':'2026-11-14T10:00:00+00:00','continuation_sha256':rsha,'continuation_path':receiptpath,'original_run_id':'old','carryover_bindings':receipt['carryover_rows'],'earliest_next_admission_utc':earliest})
        files[newdir+'requests.jsonl']=b'';files[newdir+'responses.jsonl']=b''
        files[newdir+'slot-outcomes.jsonl']=b''.join(raw({'slot_id':sid,'issued':False,'model_outcome':'not_issued_dependency_failed'}) for sid in pending)
        files[newdir+'summary.json']=raw({'status':'completed'})
        canonical='results/frontier-v6j/budget/ledger.jsonl';snapshot='data/frontier-v6j-ledger-after-continuation.jsonl';files[canonical]=b'{}\n'
        fake={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':'completed','checks':1,'counts':{'planned':1794}}
        with tempfile.TemporaryDirectory() as tmp:
            left,right=Path(tmp)/'left',Path(tmp)/'right'
            for root in (left,right):
                for name,value in files.items():
                    target=inert if root==right and name==lock else snapshot if root==right and name==canonical else name
                    path=root/target;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
            with patch.object(audit,'RECEIPT_SHA',rsha),patch.object(audit.original_audit,'audit',return_value=oldaudit),patch.object(audit,'audit_evidence',side_effect=lambda *a,**k:dict(fake)):
                a=audit.audit(left,fsha);b=audit.audit(right,fsha,frozen_aliases=audit.ALLOWED_ALIAS,ledger_snapshot=snapshot)
                self.assertEqual(a,b);self.assertIn(canonical,b['input_bindings']);self.assertNotIn(snapshot,b['input_bindings'])
                (right/inert).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'frozen file'):audit.audit(right,fsha,frozen_aliases=audit.ALLOWED_ALIAS,ledger_snapshot=snapshot)

if __name__=='__main__':unittest.main()

