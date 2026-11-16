"""Synthetic transport tests; no provider access or paid calls."""
import asyncio
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from retrace.adaption_v6h import (BASELINE,BASELINE_LEDGER,PRIMARY_MODELS,MODEL_PRICING,CAP,
    RollingLedger,run_slots,verify_prior_ledger,validate_slots,retry_delay,plan,build_body,nano,
    request_bound,usage_cost,SSEDecoder,StreamJournal,consume_stream)
from scripts.run_frontier_v6h import verify_canary,integrity,verify_corpus,verify_runtime_config
ROOT=Path(__file__).resolve().parents[1]
KEY='synthetic-testing-key-never-live'
MODEL='gemma-4-31b-it'


def slot(i=0,model=MODEL,**kw):
    return dict(slot_id=f's-{i}',case_id='case-public',model=model,condition='test',phase='test',
        instructions='Fixed instructions',input='Source text',max_output_tokens=8192 if model!='qwen3.5-397b' else 16384,**kw)


def frame(obj):return ('data: '+json.dumps(obj,ensure_ascii=False)+'\n\n').encode()


def final(body,text='answer',truncated=False,usage=True):
    r={'id':'synthetic-response','model':body['model'],'status':'incomplete' if truncated else 'completed','output_text':text}
    if truncated:r['incomplete_details']={'reason':'max_output_tokens'}
    if usage:r['usage']={'input_tokens':30,'output_tokens':10,'total_tokens':40}
    return frame({'type':'response.completed','response':r})


async def emit(raw,status=200,retry_after=None):
    yield {'http_status':status,'content_type':'text/event-stream' if status==200 else 'application/json','retry_after':retry_after}
    for i in range(0,len(raw),19):yield raw[i:i+19]


class Clock:
    def __init__(self):self.value=0.0
    def now(self):return self.value
    async def sleep(self,d):self.value+=d;await asyncio.sleep(0)


class RuntimeTests(unittest.TestCase):
    def run_case(self,slots,transport,**kw):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);clock=Clock();ledger=RollingLedger(root/'budget',baseline_path=ROOT/BASELINE_LEDGER)
            try:
                summary=asyncio.run(run_slots(slots,api_key=KEY,output_dir=root/'run',ledger=ledger,transport=transport,
                    model_interval=0,_clock=clock.now,_sleep=clock.sleep,_jitter=lambda:0,**kw))
                requests=[json.loads(x) for x in (root/'run/requests.jsonl').read_text().splitlines()]
                responses=[json.loads(x) for x in (root/'run/responses.jsonl').read_text().splitlines()]
                outcomes=[json.loads(x) for x in (root/'run/slot-outcomes.jsonl').read_text().splitlines()]
                ledger_rows=[json.loads(x) for x in (root/'budget/ledger.jsonl').read_text().splitlines()]
                return summary,requests,responses,outcomes,ledger_rows
            finally:ledger.close()

    def test_prior_replay_binds_idle_closure_and_keeps_seven_unknown(self):
        v=verify_prior_ledger(ROOT/BASELINE_LEDGER)
        self.assertEqual(v['carry_credits'],'43.633207445');self.assertEqual(v['issued_attempts'],48)
        self.assertEqual(v['cumulative_inherited_unsettled_attempts'],7)
        self.assertEqual(v['primary_calls_in_interrupted_run'],0)

    def test_decimal_qwen_bound_and_usage_reasoning_not_double_counted(self):
        self.assertEqual(request_bound('qwen3.5-397b',16384),129433600)
        u={'input_tokens':100,'output_tokens':20,'output_tokens_details':{'reasoning_tokens':19}}
        self.assertEqual(usage_cost(MODEL,u,8192),nano('0.0000158'))

    def test_body_is_stateless_and_output_only_cannot_add_source(self):
        s=slot(1);s['input']='';s['input_from']={'slot_id':'s-0','mode':'assistant_output_only'}
        b=build_body(s,{'s-0':{'actual_input':'DO NOT COPY SOURCE','output_text':'actual NL'}})
        self.assertEqual(b['input'],[{'role':'user','content':'actual NL'}]);self.assertIsNone(b['previous_response_id'])
        self.assertFalse(b['store']);self.assertEqual(b['temperature'],1)
        s['input']='blind gloss mapping';s['input_from']['mode']='assistant_output_with_fixed_prefix'
        self.assertEqual(build_body(s,{'s-0':{'output_text':'actual NL'}})['input'][-1]['content'],'blind gloss mapping\n\nactual NL')

    def test_invalid_dependency_schema_and_cross_case_reject_before_dispatch(self):
        a=slot();b=slot(1);b['input']='';b['input_from']={'slot_id':'s-0','mode':'assistant_output_only'}
        validate_slots([a,b]);b['case_id']='wrong'
        with self.assertRaisesRegex(ValueError,'scope'):validate_slots([a,b])
        b['case_id']=a['case_id'];b['input']='source leakage'
        with self.assertRaisesRegex(ValueError,'prefix'):validate_slots([a,b])
        b['input']='';b['history_from']=['s-0']
        with self.assertRaisesRegex(ValueError,'dependency'):validate_slots([a,b])

    def test_canary_only_primary_models_and_plan_no_reservation(self):
        slots=[slot(i,m) for i,m in enumerate(PRIMARY_MODELS)]+[slot(i+5,m) for i,m in enumerate(PRIMARY_MODELS)]
        p=plan(slots,canary=True);self.assertEqual(p['planned_slots'],10);self.assertFalse(p['reservation_created'])
        slots[-1]['model']='qwen3.5-397b';slots[-1]['max_output_tokens']=16384
        with self.assertRaisesRegex(ValueError,'canary'):plan(slots,canary=True)

    def test_retry_after_numeric_and_http_date_never_under_60(self):
        self.assertEqual(retry_delay('1',0,jitter=0),60)
        self.assertEqual(retry_delay('95',0,jitter=2),97)
        self.assertEqual(retry_delay('bad',1,jitter=0),120)
        self.assertEqual(retry_delay('Wed, 21 Oct 2015 07:30:00 GMT',0,utc_now=datetime(2015,10,21,7,28,tzinfo=timezone.utc),jitter=0),120)

    def test_retry_preserves_first_attempt_and_retains_unknown_bound(self):
        calls=[]
        def transport(body):
            calls.append(body)
            return emit(b'{"error":"limited"}',429,'60') if len(calls)==1 else emit(final(body))
        s,req,res,out,ledger=self.run_case([slot()],transport)
        self.assertEqual(s['retries'],1);self.assertEqual(s['first_attempt_completed'],0);self.assertEqual(s['eventual_completed'],1)
        self.assertEqual([r['attempt_number'] for r in req],[1,2]);self.assertNotEqual(req[0]['attempt_id'],req[1]['attempt_id'])
        self.assertEqual(res[0]['model_outcome'],'http_429');self.assertTrue(out[0]['slot_final'])
        self.assertEqual(s['budget']['unknown_429_attempts_retained'],1)
        self.assertEqual(s['budget']['accounted_credits'],str((nano(BASELINE)+request_bound(MODEL,8192)+usage_cost(MODEL,res[1]['usage'],8192))/1e9))

    def test_only_two_retries_then_final_failure_no_fourth(self):
        s,req,res,out,_=self.run_case([slot()],lambda b:emit(b'{}',429))
        self.assertEqual(len(req),3);self.assertEqual(s['retries'],2);self.assertEqual(len(out),1)
        self.assertEqual(out[0]['model_outcome'],'http_429');self.assertEqual(s['budget']['unsettled_attempts'],3)

    def test_429_explicit_usage_settles_but_does_not_count_completed(self):
        n=[0]
        def t(b):
            n[0]+=1
            return emit(json.dumps({'usage':{'input_tokens':0,'output_tokens':0}}).encode(),429) if n[0]==1 else emit(final(b))
        s,_,res,_,_=self.run_case([slot()],t)
        self.assertEqual(s['budget']['unsettled_attempts'],0);self.assertEqual(res[0]['settled_credits'],'0')
        self.assertFalse(res[0]['terminal_valid'])

    def test_timeout_and_network_error_are_never_retried(self):
        async def bad(b):
            raise RuntimeError('contains arbitrary transport text')
            yield b''
        s,req,res,out,_=self.run_case([slot(),slot(1)],bad,concurrency=1)
        self.assertEqual(len(req),1);self.assertEqual(s['retries'],0);self.assertEqual(s['status'],'stopped')
        self.assertEqual(res[0]['error'],'network_or_transport_failure');self.assertEqual(len(out),2)

    def test_missing_usage_stops_and_keeps_bound(self):
        s,req,res,_,_=self.run_case([slot(),slot(1)],lambda b:emit(final(b,usage=False)),concurrency=1)
        self.assertEqual(len(req),1);self.assertEqual(res[0]['error'],'missing_usage');self.assertEqual(s['budget']['unsettled_attempts'],1)

    def test_truncation_not_retried_propagates_dependency_skip(self):
        a=slot();b=slot(1,history_from=['s-0']);c=slot(2,history_from=['s-1']);d=slot(3)
        s,req,res,out,_=self.run_case([a,b,c,d],lambda b:emit(final(b,truncated=True)))
        self.assertEqual(len(req),2);self.assertEqual(s['retries'],0);self.assertEqual(s['dependency_skips'],2)
        self.assertEqual(s['truncated'],2);self.assertTrue(all(r['terminal_valid'] for r in res));self.assertEqual(len(out),4)

    def test_actual_history_and_two_stage_dependency_only(self):
        a=slot();b=slot(1);b['input']='';b['input_from']={'slot_id':'s-0','mode':'assistant_output_only'}
        c=slot(2,history_from=['s-0','s-1'])
        s,req,_,_,_=self.run_case([a,b,c],lambda b:emit(final(b,text='model answer')))
        self.assertEqual(s['completed'],3)
        self.assertEqual(req[1]['request']['input'],[{'role':'user','content':'model answer'}])
        self.assertEqual(req[2]['request']['input'][2],{'role':'user','content':'model answer'})
        self.assertEqual(len(req[2]['dependency_bindings']),2)
        self.assertEqual(req[1]['dependency_bindings'][0]['output_sha256'],hashlib.sha256(b'model answer').hexdigest())

    def test_concurrent_same_model_can_have_multiple_inflight(self):
        entered=[0];release=None
        async def t(b):
            nonlocal release
            if release is None:release=asyncio.Event()
            entered[0]+=1
            if entered[0]==3:release.set()
            await release.wait()
            async for chunk in emit(final(b)):yield chunk
        s,req,_,_,_=self.run_case([slot(i) for i in range(3)],t,per_model_concurrency=3,concurrency=3)
        self.assertEqual(s['completed'],3);self.assertEqual(entered[0],3)

    def test_global_429_flood_stop_prevents_unbounded_attempts(self):
        s,req,_,out,_=self.run_case([slot(i) for i in range(25)],lambda b:emit(b'{}',429),concurrency=1)
        self.assertIn('rate_limit_flood_stop',s['stop_reasons']);self.assertLessEqual(len(req),10)
        self.assertEqual(len(out),25)

    def test_stop_file_before_start_creates_zero_attempt_admin_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            stop=Path(tmp)/'STOP';stop.write_text('stop')
            s,req,_,out,rows=self.run_case([slot()],lambda b:emit(final(b)),stop_file=stop)
        self.assertEqual(req,[]);self.assertIn('administrative_stop_file',s['stop_reasons']);self.assertEqual(out[0]['model_outcome'],'not_issued_global_stop')
        self.assertTrue(rows[-1]['event']['administrative'])

    def test_invalid_sse_and_duplicate_keys_never_repaired(self):
        for raw in (b'data: [DONE]\n\n',b'data: {"type":"response.completed","type":"other"}\n\n'):
            d=SSEDecoder()
            with self.assertRaises(ValueError):d.feed(raw);d.finish()

    def test_split_utf8_and_terminal_text_preserved(self):
        body={'model':MODEL};raw=final(body,'café 🧭');d=SSEDecoder()
        for b in raw:d.feed(bytes([b]))
        self.assertEqual(d.finish()['output_text'],'café 🧭')

    def test_429_bound_is_retained_across_new_run_ledger_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'budget';l=RollingLedger(path,baseline_path=ROOT/BASELINE_LEDGER)
            l.record({'kind':'reserve','attempt_id':'test','bound_nanocredits':100})
            l.record({'kind':'retain_429','attempt_id':'test'});l.record({'kind':'run_closed','run_id':'test'})
            before=l.accounted;l.close();l=RollingLedger(path,baseline_path=ROOT/BASELINE_LEDGER)
            self.assertEqual(l.accounted,before);self.assertEqual(l.snapshot()['unknown_429_attempts_retained'],1);l.close()

    def test_authorization_all_protected_and_six_model_metadata(self):
        auth=json.loads((ROOT/'data/frontier-v6h-authorization.json').read_text())
        models=json.loads((ROOT/'data/frontier-v6c-model-availability.json').read_text())
        self.assertEqual(integrity(auth,models),695)

    def test_sixty_case_partition_and_long_subset_gate(self):
        c={'schema':'retrace.frontier-v6h-corpus.v1','cases':[
            {'case_id':f'S{i}-{j}','partition':'synthetic','family_id':f'F{i}'} for i in range(1,7) for j in range(8)] + [
            {'case_id':f'ECO-{i:02}','partition':'ecological','family_id':'ECO'} for i in range(1,13)]}
        c['long_context_subset_ids']=[r['case_id'] for r in c['cases'][:24]]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'corpus.json'
            for valid in (True,False):
                if not valid:c['cases'][0]['family_id']='F2'
                p.write_text(json.dumps(c));h=hashlib.sha256(p.read_bytes()).hexdigest()
                if valid:self.assertEqual(len(verify_corpus(p,h)),60)
                else:
                    with self.assertRaisesRegex(ValueError,'family_counts'):verify_corpus(p,h)

    def test_per_model_spacing_and_429_cooldown_across_models(self):
        async def scenario(tmp):
            clock=Clock();starts=[];first=[True]
            async def t(body):
                starts.append((body['model'],clock.now()))
                if first[0]:
                    first[0]=False
                    async for x in emit(b'{}',429,'65'):yield x
                else:
                    async for x in emit(final(body)):yield x
            l=RollingLedger(Path(tmp)/'budget',baseline_path=ROOT/BASELINE_LEDGER)
            try:
                s=await run_slots([slot(0),slot(1),slot(2,'deepseek-v4-flash'),slot(3,'deepseek-v4-flash')],api_key=KEY,
                    output_dir=Path(tmp)/'run',ledger=l,transport=t,model_interval=2,concurrency=4,
                    _clock=clock.now,_sleep=clock.sleep,_jitter=lambda:0)
                return s,starts
            finally:l.close()
        with tempfile.TemporaryDirectory() as tmp:s,starts=asyncio.run(scenario(tmp))
        self.assertEqual(s['eventual_completed'],4)
        for model in {x[0] for x in starts}:
            ts=[t for m,t in starts if m==model]
            self.assertTrue(all(b-a>=2-1e-8 for a,b in zip(ts,ts[1:])))
        self.assertTrue(all(t>=65 for _,t in starts[2:]),starts)

    def test_stop_file_drains_inflight_and_blocks_new_starts(self):
        async def scenario(tmp):
            root=Path(tmp);stop=root/'STOP';clock=Clock();started=[0];gate=asyncio.Event()
            async def t(body):
                started[0]+=1
                if started[0]==2:stop.write_text('stop');gate.set()
                await gate.wait()
                async for x in emit(final(body)):yield x
            l=RollingLedger(root/'budget',baseline_path=ROOT/BASELINE_LEDGER)
            try:return await run_slots([slot(i) for i in range(3)],api_key=KEY,output_dir=root/'run',ledger=l,transport=t,
                concurrency=2,model_interval=0,stop_file=stop,_clock=clock.now,_sleep=clock.sleep)
            finally:l.close()
        with tempfile.TemporaryDirectory() as tmp:s=asyncio.run(scenario(tmp))
        self.assertEqual(s['issued_slots'],2);self.assertEqual(s['eventual_completed'],2)
        self.assertEqual(s['slot_outcomes'],3);self.assertEqual(s['budget']['unsettled_attempts'],0)

    def test_timeout_retains_bound_and_never_retries(self):
        async def t(body):
            await asyncio.sleep(1)
            yield b'never'
        s,req,res,_,_=self.run_case([slot()],t,timeout_seconds=.01)
        self.assertEqual(len(req),1);self.assertEqual(res[0]['error'],'timeout');self.assertEqual(s['retries'],0)
        self.assertEqual(s['budget']['unsettled_attempts'],1)

    def test_budget_stop_occurs_before_new_reservation_or_transport(self):
        async def scenario(tmp):
            root=Path(tmp);clock=Clock();l=RollingLedger(root/'budget',baseline_path=ROOT/BASELINE_LEDGER)
            l.record({'kind':'reserve','attempt_id':'synthetic-encumbrance','bound_nanocredits':CAP-l.accounted-1})
            try:
                return await run_slots([slot()],api_key=KEY,output_dir=root/'run',ledger=l,transport=lambda b:emit(final(b)),
                    model_interval=0,_clock=clock.now,_sleep=clock.sleep)
            finally:l.close()
        with tempfile.TemporaryDirectory() as tmp:s=asyncio.run(scenario(tmp))
        self.assertEqual(s['issued_attempts'],0);self.assertIn('cumulative_budget_stop',s['stop_reasons'])
        self.assertLessEqual(nano(s['budget']['accounted_credits']),CAP)

    def test_operational_canary_gate_allows_failed_model_truncation(self):
        slots=[slot(i,m) for i,m in enumerate(PRIMARY_MODELS)]+[slot(i+5,m) for i,m in enumerate(PRIMARY_MODELS)]
        s,_,_,_,_=self.run_case(slots,lambda b:emit(final(b,truncated=True)),canary=True)
        verify_canary(s);self.assertEqual(s['truncated'],10);self.assertEqual(s['completed'],0)

    def test_runtime_settings_frozen_exactly_and_canary_eight_per_model(self):
        args=SimpleNamespace(model_interval=2.,per_model_concurrency=8,concurrency=40,timeout=180.,canary=True)
        frozen={'runtime_config':{'model_interval_seconds':2.,'per_model_concurrency':8,'global_concurrency':40,'timeout_seconds':180.,'max_retries':2}}
        verify_runtime_config(frozen,args);args.per_model_concurrency=64
        with self.assertRaisesRegex(ValueError,'not_exactly_frozen'):verify_runtime_config(frozen,args)
        frozen['runtime_config']['per_model_concurrency']=64
        with self.assertRaisesRegex(ValueError,'canary_runtime'):verify_runtime_config(frozen,args)
        args.canary=False;verify_runtime_config(frozen,args)

    def test_sixty_four_simultaneous_per_model_stay_below_credit_cap(self):
        entered=[0];peak=[0];active=[0];gate=None
        async def t(body):
            nonlocal gate
            if gate is None:gate=asyncio.Event()
            entered[0]+=1;active[0]+=1;peak[0]=max(peak[0],active[0])
            if entered[0]==64:gate.set()
            await gate.wait()
            async for x in emit(final(body)):yield x
            active[0]-=1
        s,_,_,_,_=self.run_case([slot(i) for i in range(65)],t,per_model_concurrency=64,concurrency=384)
        self.assertEqual(s['completed'],65);self.assertEqual(peak[0],64)
        self.assertLessEqual(nano(s['budget']['accounted_credits']),CAP)

    def test_temporary_reserved_headroom_waits_for_settlement(self):
        async def scenario(tmp):
            root=Path(tmp);clock=Clock();l=RollingLedger(root/'budget',baseline_path=ROOT/BASELINE_LEDGER)
            bound=request_bound(MODEL,8192);cost=usage_cost(MODEL,{'input_tokens':30,'output_tokens':10},8192)
            l.record({'kind':'reserve','attempt_id':'synthetic-encumbrance',
                      'bound_nanocredits':CAP-l.accounted-bound-2*cost})
            peaks=[]
            async def t(body):
                peaks.append(l.accounted)
                await asyncio.sleep(0)
                async for x in emit(final(body)):yield x
            try:
                result=await run_slots([slot(0),slot(1)],api_key=KEY,output_dir=root/'run',ledger=l,transport=t,
                    model_interval=0,concurrency=2,_clock=clock.now,_sleep=clock.sleep)
                return result,peaks
            finally:l.close()
        with tempfile.TemporaryDirectory() as tmp:s,peaks=asyncio.run(scenario(tmp))
        self.assertEqual(s['completed'],2);self.assertEqual(s['stop_reasons'],[])
        self.assertTrue(all(x<=CAP for x in peaks));self.assertEqual(len(peaks),2)


if __name__=='__main__':unittest.main()
