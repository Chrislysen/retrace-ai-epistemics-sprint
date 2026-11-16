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
from retrace import adaption_v6k as runtime
from scripts import audit_frontier_v6k_runtime as audit
from tests.test_adaption_v6k import synthetic_carry,make_manifest,Clock,QWEN,ROUTE
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
    def test_serial_complete_and_sixty_four_inherited_unknowns(self):
        v=captured([slot(0),slot(1)]);r=replay(v)
        self.assertEqual(r['counts']['planned'],2);self.assertEqual(r['historical_carry_credits'],'80.145946577')
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
            if calls[0]==1:
                yield {'http_status':200,'content_type':'text/event-stream','retry_after':None}
                yield b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"unfinished"}\n\n'
                raise ConnectionResetError('message must not be logged')
            async for e in emit(final(body)):yield e
        v=captured([slot(0),slot(1)],t);r=replay(v)
        self.assertEqual(r['counts']['per_slot_operational_failures'],1);self.assertEqual(r['counts']['completed'],1)
        self.assertGreater(float(r['retained_run_bounds_credits']),0)
        self.assertEqual(v['responses'][0]['transport_exception_type'],'builtins.ConnectionResetError')
        self.assertNotIn('message must not be logged',repr(v))
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

    def test_reset_after429_has_cooldown_but_no_retry(self):
        calls=[0]
        async def t(body):
            calls[0]+=1
            if calls[0]==1:
                yield {'http_status':429,'content_type':'application/json','retry_after':'70'}
                yield b'{"partial":'
                raise ConnectionResetError()
            async for e in emit(final(body)):yield e
        v=captured([slot(0),slot(1)],t);r=replay(v)
        self.assertEqual(r['counts']['issued_attempts'],2);self.assertEqual(r['counts']['retries'],0)
        self.assertEqual(r['counts']['http_429_attempts'],0)
        self.assertEqual(v['responses'][0]['model_outcome'],'operational_failure')
        self.assertGreaterEqual(v['responses'][0]['retry_cooldown_seconds'],70)
        self.assertGreaterEqual(r['minimum_completion_gap_seconds'],70)
        self.assertIsNone(v['responses'][0]['settled_credits'])

    def test_preheader_reset_and_transport_timeout_remain_global(self):
        for exception in (ConnectionResetError,asyncio.TimeoutError):
            async def t(body):
                raise exception('not recorded')
                yield b''
            v=captured([slot(0),slot(1)],t);r=replay(v)
            self.assertEqual(r['schedule_status'],'stopped');self.assertEqual(r['counts']['issued_attempts'],1)
            self.assertEqual(v['responses'][0]['transport_failure_stage'],'before_validated_headers')
            bad=deepcopy(v);bad['responses'][0]['failure_scope']='slot'
            with self.assertRaisesRegex(ValueError,'failure scope'):replay(bad)
            bad={**v['responses'][0],'error':'timeout','failure_scope':'slot'}
            with self.assertRaisesRegex(ValueError,'outer timeout'):audit.check_transport_classification(bad)

    def test_postheader_unknown_exception_or_parser_error_remains_global(self):
        for parser in (False,True):
            async def t(body):
                yield {'http_status':200,'content_type':'text/event-stream','retry_after':None}
                if parser:yield b'data: not-json\n\n'
                raise RuntimeError('not a whitelisted transport reset')
            v=captured([slot(0),slot(1)],t);r=replay(v)
            self.assertEqual(r['schedule_status'],'stopped');self.assertEqual(r['counts']['issued_attempts'],1)
            self.assertEqual(v['responses'][0]['failure_scope'],'global')
            if parser:self.assertIsNone(v['responses'][0]['transport_exception_type'])

    def test_forged_local_exception_type_header_status_or_settlement_rejected(self):
        async def t(body):
            yield {'http_status':200,'content_type':'text/event-stream','retry_after':None}
            raise ConnectionResetError()
        v=captured([slot(0)],t);self.assertTrue(replay(v)['passed'])
        for changes in ({'transport_exception_type':'builtins.RuntimeError','exception_type':'builtins.RuntimeError'},
                        {'transport_headers_validated':False},{'transport_content_type':'text/html'},
                        {'transport_failure_stage':'before_validated_headers'}, {'settled_credits':'0'},
                        {'http_status':401},{'exception_type':'秘密.Type'}):
            row={**v['responses'][0],**changes}
            with self.subTest(changes=changes),self.assertRaises(ValueError):audit.check_transport_classification(row)

    def test_success_requires_validated_sse_and_absence_of_exception_metadata(self):
        v=captured([slot(0)]);row=v['responses'][0]
        self.assertFalse(audit.check_transport_classification(row))
        for changes in ({'transport_headers_validated':False},{'transport_content_type':'text/html'},
                        {'exception_type':'builtins.ValueError'},
                        {'exception_type':'builtins.ConnectionResetError','transport_exception_type':'builtins.ConnectionResetError','transport_failure_stage':'response_body'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):audit.check_transport_classification({**row,**changes})

    def test_tampered_prefix_cannot_keep_same_capture_hash(self):
        async def t(body):
            yield {'http_status':200,'content_type':'text/event-stream','retry_after':None}
            yield b': partial stream\n\n'
            raise ConnectionResetError()
        v=captured([slot(0)],t);name=next(iter(v['streams']));v['streams'][name]+=b'forged bytes'
        with self.assertRaisesRegex(ValueError,'capture length'):replay(v)

    def test_complete_terminal_prefix_then_disconnect_is_still_failed_and_retained(self):
        async def t(body):
            async for e in emit(final(body)):yield e
            raise ConnectionResetError()
        v=captured([slot(0)],t);r=replay(v)
        self.assertEqual(r['counts']['completed'],0)
        self.assertIsNotNone(v['responses'][0]['stream_terminal_event'])
        self.assertIsNone(v['responses'][0]['raw_response']);self.assertIsNone(v['responses'][0]['settled_credits'])
        self.assertEqual(v['responses'][0]['output_text'],'')

    def test_artifact_layer_replays_three_segments_and_relocates_without_lock(self):
        # Synthetic metadata only. Pure raw-stream/accounting replay is exercised
        # above; this test mocks only that layer to isolate artifact authentication.
        from datetime import timedelta
        raw=lambda value:(json.dumps(value)+'\n').encode()
        lines=lambda values:b''.join(raw(v) for v in values)
        files={}; slots=[{'slot_id':f's-{n}'} for n in range(1800)]
        priors={};sources=[];refs=[];all_selected=[]
        for segment,offset,count,skip_count,stop in [('i',0,6,0,'response_model_mismatch'),('j',6,207,11,'network_or_transport_failure')]:
            prefix=audit.PREFIXES[segment];rid='old-'+segment;outcomes=[];issued=[]
            for n in range(offset,1800):
                yes=n<offset+count;dependency=offset+count<=n<offset+count+skip_count
                row={'slot_id':f's-{n}','run_id':rid,'issued':yes,'attempt_id':f'{rid}:{n}' if yes else None,
                    'model_outcome':'completed' if yes else 'not_issued_dependency_failed' if dependency else 'not_issued_global_stop',
                    'terminal_valid':yes,'failure_scope':None,'error':None}
                if n==offset+count-1:row.update(model_outcome='operational_failure',terminal_valid=False,failure_scope='global',error=stop)
                outcomes.append(row)
                if yes:issued.append(row)
                if yes or dependency:
                    refs.append({'segment':segment,'slot_id':row['slot_id'],'source_path':prefix+'slot-outcomes.jsonl',
                        'source_line_one_based':len(outcomes),'row_sha256':audit.digest(row),'attempt_id':row['attempt_id'],'model_outcome':row['model_outcome']})
                    all_selected.append(row)
            summary={'run_id':rid,'status':'stopped','stop_reasons':[stop],'issued_attempts':count,'retries':0}
            paths={r:prefix+name for r,name in audit.ROLE_NAMES.items()};paths['ledger']=f'results/frontier-v6{segment}/budget/ledger.jsonl'
            for role,values in [('requests',issued),('responses',issued),('outcomes',outcomes)]:files[paths[role]]=lines(values)
            files[paths['summary']]=raw(summary);files[paths['run_manifest']]=raw({'run_id':rid})
            baseline='data/frontier-v6i-ledger-after-study.jsonl' if segment=='i' else 'data/frontier-v6j-ledger-after-continuation.jsonl'
            files[paths['ledger']]=(ROOT/baseline).read_bytes();files[baseline]=files[paths['ledger']]
            bindings={p:{'sha256':sha256(files[p]).hexdigest(),'bytes':len(files[p])} for r,p in paths.items() if r!='audit'}
            prior={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':'stopped',
                'counts':{'issued_attempts':count,'dependency_skips':skip_count},
                'cumulative_accounted_credits':'47.653269434' if segment=='i' else audit.CARRY,'input_bindings':bindings}
            if segment=='j':prior['original_audit']=priors['i']
            priors[segment]=prior;files[paths['audit']]=raw(prior)
            sources.append({'segment':segment,'run_id':rid,'freeze_sha256':audit.I_FREEZE_SHA if segment=='i' else audit.J_FREEZE_SHA,
                'paths':paths,'sha256':{r:sha256(files[p]).hexdigest() for r,p in paths.items()},'definitive_final_slots':count+skip_count,'issued_slots':count})
        sessions='data/frontier-v6i-sessions.json';files[sessions]=raw(slots)
        carried=[r['slot_id'] for r in all_selected];pending=[s['slot_id'] for s in slots if s['slot_id'] not in carried]
        baseline='data/frontier-v6j-ledger-after-continuation.jsonl'
        receipt={'schema':'retrace.frontier-v6k-continuation.v1','prior_freeze_sha256':audit.J_FREEZE_SHA,
            'baseline_snapshot_path':baseline,'historical_conservative_carry_credits':audit.CARRY,'sessions_sha256':audit.digest(slots),
            'prior_journal_files':{p:sha256(files[p]).hexdigest() for source in sources for p in source['paths'].values()},
            'source_segments':sources,'original_run_ids':['old-i','old-j'],'carried_final_outcomes':refs,
            'permanently_excluded_final_slot_ids':carried,'permanently_excluded_issued_slot_ids':[r['slot_id'] for r in all_selected if r['issued']],
            'continuation_slot_ids':pending,'full_planned_slots':1800,'carried_issued_slots':213,'carried_final_slots':224,'continuation_slots':1576,
            'failed_producer_descendant_slot_ids':[pending[0]]}
        receiptpath='data/frontier-v6k-continuation.json';files[receiptpath]=raw(receipt);rsha=sha256(files[receiptpath]).hexdigest()
        lock=next(iter(audit.ALLOWED_ALIAS));alias=audit.ALLOWED_ALIAS[lock];files[lock]=b'historical inert lock'
        files['scripts/audit_frontier_v6k_runtime.py']=Path(audit.__file__).read_bytes()
        for n in range(1301-len(files)):files[f'protected/{n}.txt']=str(n).encode()
        authpath='data/frontier-v6k-authorization.json';files[authpath]=raw({'protected':{p:sha256(v).hexdigest() for p,v in files.items()},
            'protected_v5_file_count':402,'inherited_unsettled_attempts':64});asha=sha256(files[authpath]).hexdigest()
        freeze={'schema':'retrace.frontier-v6k-freeze.v1','created_at':'2026-11-14T00:00:00+00:00',
            'files':[{'path':p,'sha256':sha256(v).hexdigest(),'bytes':len(v)} for p,v in files.items()],
            'authorization_path':authpath,'authorization_sha256':asha,'continuation_path':receiptpath,'continuation_sha256':rsha,
            'baseline_path':baseline,'baseline_sha256':audit.PRIOR_SHA,'historical_conservative_carry_credits':audit.CARRY,
            'observed_response_models':audit.ROUTE,'sessions_path':sessions,'sessions_sha256':audit.digest(slots),'sessions_file_sha256':sha256(files[sessions]).hexdigest(),
            'output_path':'results/frontier-v6k/continuation','ledger_path':'results/frontier-v6k/budget'}
        files['data/frontier-v6k-freeze.json']=raw(freeze);fsha=sha256(files['data/frontier-v6k-freeze.json']).hexdigest()
        prefix=freeze['output_path']+'/'
        files[prefix+'run.json']=raw({'execution_manifest_sha256':fsha,'created_at':'2026-11-14T23:00:00+00:00','run_id':'new-k',
            'continuation_sha256':rsha,'continuation_path':receiptpath,'carryover_bindings':refs,
            'earliest_next_admission_utc':(audit.stamp(audit.jsonl(files[baseline])[-1]['at'])+timedelta(seconds=4)).isoformat()})
        files[prefix+'requests.jsonl']=b'';files[prefix+'responses.jsonl']=b''
        files[prefix+'slot-outcomes.jsonl']=lines([{'slot_id':sid,'issued':False,'model_outcome':'not_issued_dependency_failed'} for sid in pending])
        files[prefix+'summary.json']=raw({'status':'completed'})
        canonical='results/frontier-v6k/budget/ledger.jsonl';snapshot='data/frontier-v6k-ledger-after-continuation.jsonl';files[canonical]=b'{}\n'
        fake={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':'completed','counts':{'planned':1576},'checks':1}
        with tempfile.TemporaryDirectory() as tmp:
            left,right=Path(tmp)/'original',Path(tmp)/'relocated'
            for root in (left,right):
                for name,value in files.items():
                    name=alias if root==right and name==lock else snapshot if root==right and name==canonical else name
                    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
            with patch.object(audit,'RECEIPT_SHA',rsha),patch.object(audit,'AUTH_SHA',asha),\
                 patch.object(audit.prior_j_audit,'audit',return_value=priors['j']),\
                 patch.object(audit,'audit_evidence',side_effect=lambda *a,**k:dict(fake)):
                original=audit.audit(left,fsha);relocated=audit.audit(right,fsha,frozen_aliases=audit.ALLOWED_ALIAS,ledger_snapshot=snapshot)
                self.assertEqual(original,relocated);self.assertEqual(relocated['prior_segment_audits'],priors)
                self.assertIn(canonical,relocated['input_bindings']);self.assertNotIn(snapshot,relocated['input_bindings'])
                (right/alias).write_bytes(b'tampered historical bytes')
                with self.assertRaisesRegex(ValueError,'frozen file'):audit.audit(right,fsha,frozen_aliases=audit.ALLOWED_ALIAS,ledger_snapshot=snapshot)


if __name__=='__main__':unittest.main()

