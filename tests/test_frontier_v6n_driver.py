"""Offline execution gates for the isolated host-loss recovery driver; invented temporary files only."""
import asyncio
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from datetime import datetime,timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import run_frontier_v6n as d


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(d,'ROOT',self.root))
        class Clock:
            @staticmethod
            def now(tz):return datetime(2026,11,14,tzinfo=tz)
        self.stack.enter_context(patch.object(d,'datetime',Clock))

    def write(self,name,value):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode());return p

    def fixture(self):
        slots=[{'slot_id':str(i)} for i in range(1800)]
        for name in d.NEW_FILES:self.write(name,{'fixture':name})
        self.write(d.SESSIONS,slots);self.write(d.BASELINE_LEDGER,b'closed invented carry\n')
        receipt={'sessions_sha256':d.digest(slots),'full_planned_slots':1800,
            'observed_response_models':dict(d.OBSERVED_ROUTES),'carried_final_slots':700,
            'carried_issued_slots':600,'continuation_slots':1100,'continuation_slot_ids':[str(i) for i in range(700,1800)]}
        self.write(d.CONTINUATION,receipt)
        self.carry={'finals':{str(i):{} for i in range(700)},'issued_slot_ids':[str(i) for i in range(600)],
            'continuation_slot_ids':receipt['continuation_slot_ids'][:]}
        self.verifier=self.stack.enter_context(patch.object(d,'verify_continuation',return_value=self.carry))
        protected={'data/protected.txt':d.sha(self.write('data/protected.txt',b'old byte exact'))}
        auth={'protected':protected,'historical_conservative_carry_credits':'249.5'};self.write(d.AUTH,auth)
        self.write('results/preflight.json',{'passed':True,'paid_calls':0})
        names=set(d.NEW_FILES)|set(protected)|{d.BASELINE_LEDGER,'results/preflight.json'}
        frozen={'schema':'retrace.frontier-v6n-freeze.v1',**d.fixed_contract(auth,receipt),
            'files':[{'path':p,'sha256':d.sha(self.root/p),'bytes':(self.root/p).stat().st_size} for p in sorted(names)],
            'sessions_file_sha256':d.sha(self.root/d.SESSIONS),'sessions_sha256':d.digest(slots),
            'baseline_sha256':d.sha(self.root/d.BASELINE_LEDGER),'preflight_path':'results/preflight.json',
            'runtime_config':d.RUNTIME_CONFIG,'deadline_utc':d.DEADLINE.isoformat()}
        self.write(d.FREEZE,frozen)
        self.stack.enter_context(patch.object(d,'historical_integrity',return_value=auth))
        self.stack.enter_context(patch.object(d,'local_dependencies',return_value=set()))
        self.stack.enter_context(patch.object(d,'verify_execution_manifest',return_value=frozen))
        return slots,receipt,frozen

    def test_exact_dynamic_freeze_and_runtime_carry_validation(self):
        slots,receipt,_=self.fixture()
        self.assertEqual(d.verify_frozen(d.sha(self.root/d.FREEZE)),slots)
        self.assertEqual(d.continuation_integrity(slots),receipt)
        self.verifier.assert_called_with(slots,self.root/d.CONTINUATION,d.sha(self.root/d.CONTINUATION))

    def test_failed_or_changed_carry_blocks_admission(self):
        slots,_,_=self.fixture();self.verifier.side_effect=ValueError('source_bytes_changed')
        with self.assertRaisesRegex(ValueError,'source_bytes_changed'):d.continuation_integrity(slots)

    def test_definitive_skips_and_issued_counts_cannot_be_dropped(self):
        slots,_,_=self.fixture()
        for key in ('finals','issued_slot_ids'):
            old=deepcopy(self.carry[key])
            if isinstance(old,dict):self.carry[key].pop(next(iter(old)))
            else:self.carry[key].pop()
            with self.assertRaisesRegex(ValueError,'exact_prior_definitive'):d.continuation_integrity(slots)
            self.carry[key]=old

    def test_carried_final_cannot_be_reissued(self):
        slots,receipt,_=self.fixture();self.carry['continuation_slot_ids'][0]='0'
        receipt['continuation_slot_ids'][0]='0';self.write(d.CONTINUATION,receipt)
        with self.assertRaisesRegex(ValueError,'no_reissued_final'):d.continuation_integrity(slots)

    def test_old_path_budget_or_counts_rejected(self):
        _,_,f=self.fixture()
        for key,value in [('output_path','results/frontier-v6k/continuation'),('historical_conservative_carry_credits','249.4'),
                ('carried_final_slots',699),('continuation_slots',1101),('cumulative_cap_credits','500'),('cumulative_cap_credits','501'),('previous_cumulative_cap_credits','500')]:
            bad=deepcopy(f);bad[key]=value;self.write(d.FREEZE,bad)
            with self.assertRaisesRegex(ValueError,'freeze_fixed_contract'):d.verify_frozen(d.sha(self.root/d.FREEZE))

    def test_missing_dependency_or_mutation_blocks(self):
        self.fixture();expected=d.sha(self.root/d.FREEZE);helper=self.write('retrace/unlisted.py',b'pass\n')
        with patch.object(d,'local_dependencies',return_value={helper}):
            with self.assertRaisesRegex(ValueError,'missing_execution_dependency'):d.verify_frozen(expected)
        self.write(d.BASELINE_LEDGER,b'changed accounting\n')
        with self.assertRaisesRegex(ValueError,'frozen_dependency_changed'):d.verify_frozen(expected)

    def test_duplicate_inventory_and_failed_preflight_rejected(self):
        _,_,f=self.fixture();f['files'].append(deepcopy(f['files'][0]));self.write(d.FREEZE,f)
        with self.assertRaisesRegex(ValueError,'duplicate_frozen_file'):d.verify_frozen(d.sha(self.root/d.FREEZE))
        f['files'].pop();self.write(d.FREEZE,f);self.write('results/preflight.json',{'passed':False})
        with self.assertRaisesRegex(ValueError,'passed_preflight_required'):d.verify_frozen(d.sha(self.root/d.FREEZE))

    def test_outputs_and_freeze_exclusive(self):
        for name,reason in [(d.OUTPUT,'study_already_exists'),(d.LEDGER,'ledger_already_exists'),(d.BASE+'/STOP','stop_file_present')]:
            p=self.write(name,b'preserve')
            with self.assertRaisesRegex(ValueError,reason):d.fresh_destination()
            self.assertEqual(p.read_bytes(),b'preserve');p.unlink()
        p=self.write(d.FREEZE,b'preserve')
        with self.assertRaisesRegex(ValueError,'freeze_already_exists'):d.freeze()
        with self.assertRaises(FileExistsError):d.write_new(p,{})

    def execution(self):
        self.stack.enter_context(patch.object(d,'keep_system_awake',return_value=nullcontext({'test_fixture':True})))
        calls=[];slots=[{'fixture':'full frozen schedule'}]
        self.write(d.CONTINUATION,{'fixture':'bound receipt'})
        self.stack.enter_context(patch.object(d,'verify_frozen',side_effect=lambda h:calls.append(('verify',h)) or slots))
        self.stack.enter_context(patch.object(d.sys,'stdin',io.StringIO('synthetic-test-key\n')))
        class Ledger:
            def __init__(self,directory,**kw):calls.append(('ledger',directory,kw))
            def close(self):calls.append(('close',))
        class Transport:
            def __init__(self,key,timeout,connections):calls.append(('transport',timeout,connections))
            async def __aenter__(self):return self
            async def __aexit__(self,*_):calls.append(('exit',))
        async def run(slots,**kw):calls.append(('run',slots,kw));return {'synthetic':True}
        for name,value in [('RollingLedger',Ledger),('AiohttpTransport',Transport),('run_slots',run)]:self.stack.enter_context(patch.object(d,name,value))
        return calls

    def historical_fixture(self):
        name='data/protected-old.txt';self.write(name,b'old frozen bytes')
        protected={name:d.sha(self.root/name)}
        self.write(d.PRIOR_FREEZE,{'files':[{'path':name,'sha256':protected[name]}]})
        prior_sha=d.sha(self.root/d.PRIOR_FREEZE)
        self.stack.enter_context(patch.object(d,'PRIOR_FREEZE_SHA',prior_sha))
        protected[d.PRIOR_FREEZE]=prior_sha
        self.write(d.CONTINUATION,{'fixture':'receipt hash'})
        auth={'schema':'retrace.frontier-v6n-authorization.v1','protected_v5_file_count':402,
            'cumulative_cap_credits':'750','previous_cumulative_cap_credits':'750',
            'prior_status':'interrupted_without_closure','prior_stop_reason':'process_exit_without_closure',
            'deadline_utc':d.DEADLINE.isoformat(),
            'prior_freeze_path':d.PRIOR_FREEZE,'prior_freeze_sha256':prior_sha,
            'protected':protected,'historical_conservative_carry_credits':'249.5','inherited_unsettled_attempts':80}
        self.write(d.AUTH,auth)
        verifier=self.stack.enter_context(patch.object(d,'verify_prior_ledger',return_value={
            'carry_credits':'249.5','cumulative_inherited_unsettled_attempts':80}))
        return auth,verifier

    def test_historical_admission_binds_dynamic_carry_and_receipt(self):
        auth,verify=self.historical_fixture()
        self.assertEqual(d.historical_integrity(d.sha(self.root/d.AUTH)),auth)
        verify.assert_called_once_with(self.root/d.BASELINE_LEDGER,
            continuation_path=self.root/d.CONTINUATION,continuation_sha256=d.sha(self.root/d.CONTINUATION))

    def test_other_stop_cap_or_missing_old_protected_file_blocks(self):
        auth,_=self.historical_fixture()
        for key,value in [('prior_stop_reason','operator_stop'),('prior_status','running'),
                ('cumulative_cap_credits','500'),('cumulative_cap_credits','501'),('previous_cumulative_cap_credits','500')]:
            bad=deepcopy(auth);bad[key]=value;self.write(d.AUTH,bad)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'authorization_budget'):d.historical_integrity()
        bad=deepcopy(auth);bad['protected'].pop('data/protected-old.txt');self.write(d.AUTH,bad)
        with self.assertRaisesRegex(ValueError,'historical_inventory_incomplete'):d.historical_integrity()

    def test_historical_active_worker_or_cost_reset_blocks(self):
        auth,verify=self.historical_fixture()
        for key,value in [('historical_conservative_carry_credits','248'),('inherited_unsettled_attempts',79)]:
            bad=deepcopy(auth);bad[key]=value;self.write(d.AUTH,bad)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'authorization_carry'):d.historical_integrity()
        self.write(d.AUTH,auth);verify.reset_mock()
        self.write('results/frontier-v6j/budget/active.lock',b'active')
        with self.assertRaisesRegex(ValueError,'prior_worker_still_active'):d.historical_integrity()
        verify.assert_not_called()

    def test_execute_reauthenticates_and_binds_receipt_to_single_worker(self):
        calls=self.execution();asyncio.run(d.execute('a'*64))
        self.assertEqual([x[0] for x in calls],['verify','verify','ledger','transport','run','exit','close'])
        self.assertIn(('transport',180,1),calls)
        kw=next(x[2] for x in calls if x[0]=='ledger')
        self.assertEqual(kw['continuation_sha256'],d.sha(self.root/d.CONTINUATION))
        self.assertEqual(kw['continuation_path'],self.root/d.CONTINUATION)

    def test_changed_freeze_or_deadline_during_stdin_blocks(self):
        calls=self.execution()
        with patch.object(d,'verify_frozen',side_effect=[[],ValueError('changed')]):
            with self.assertRaisesRegex(ValueError,'changed'):asyncio.run(d.execute('a'*64))
        self.assertFalse((self.root/d.LEDGER).exists());self.assertEqual(calls,[])
        class Past:
            @staticmethod
            def now(tz):return d.DEADLINE+timedelta(seconds=1)
        with patch.object(d,'datetime',Past):
            with self.assertRaisesRegex(ValueError,'delivery_buffer_reached'):asyncio.run(d.execute('a'*64))

    def test_runtime_exception_closes_without_retry(self):
        calls=self.execution()
        async def fail(*a,**kw):raise RuntimeError('synthetic')
        with patch.object(d,'run_slots',fail):
            with self.assertRaisesRegex(RuntimeError,'synthetic'):asyncio.run(d.execute('a'*64))
        self.assertEqual(sum(x[0]=='transport' for x in calls),1)
        self.assertEqual([x[0] for x in calls][-2:],['exit','close'])


if __name__=='__main__':unittest.main()
