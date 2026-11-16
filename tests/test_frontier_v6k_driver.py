"""Offline admission/immutability tests for the additive three-segment driver."""
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import run_frontier_v6k as d


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(d, 'ROOT', self.root))
        class Clock:
            @staticmethod
            def now(tz): return datetime(2026,11,14,tzinfo=tz)
        self.stack.enter_context(patch.object(d, 'datetime', Clock))

    def write(self, name, value):
        p = self.root/name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode())
        return p

    def fixture(self):
        slots = [{'slot_id':str(i)} for i in range(1800)]
        for name in d.NEW_FILES: self.write(name, {'fixture':name})
        self.write(d.SESSIONS,slots); self.write(d.BASELINE_LEDGER,b'closed exact carry\n')
        receipt = {'sessions_sha256':d.digest(slots), 'full_planned_slots':1800,
            'observed_response_models':dict(d.OBSERVED_ROUTES), 'continuation_slot_ids':[str(i) for i in range(224,1800)]}
        self.write(d.CONTINUATION,receipt); receipt_hash = d.sha(self.root/d.CONTINUATION)
        self.stack.enter_context(patch.object(d,'CONTINUATION_SHA',receipt_hash))
        carry = {'finals':{str(i):{} for i in range(224)}, 'issued_slot_ids':[str(i) for i in range(213)],
            'continuation_slot_ids':receipt['continuation_slot_ids'][:]}
        self.carry = carry
        self.verifier = self.stack.enter_context(patch.object(d,'verify_continuation',return_value=carry))
        protected = {'data/protected.txt':d.sha(self.write('data/protected.txt',b'old byte exact'))}
        self.write('results/preflight.json',{'passed':True,'paid_calls':0})
        names = set(d.NEW_FILES)|set(protected)|{d.BASELINE_LEDGER,'results/preflight.json'}
        frozen = {'schema':'retrace.frontier-v6k-freeze.v1',
            'files':[{'path':p,'sha256':d.sha(self.root/p),'bytes':(self.root/p).stat().st_size} for p in sorted(names)],
            'sessions_path':d.SESSIONS,'sessions_file_sha256':d.sha(self.root/d.SESSIONS),'sessions_sha256':d.digest(slots),
            'study_path':d.DESIGN,'output_path':d.OUTPUT,'ledger_path':d.LEDGER,'baseline_path':d.BASELINE_LEDGER,
            'baseline_sha256':d.sha(self.root/d.BASELINE_LEDGER),'scheduled_slots':1800,'continuation_slots':1576,
            'carried_issued_slots':213,'carried_final_slots':224,'continuation_path':d.CONTINUATION,'continuation_sha256':receipt_hash,
            'observed_response_models':dict(d.OBSERVED_ROUTES),'authorization_path':d.AUTH,'authorization_sha256':d.AUTH_SHA,
            'cumulative_cap_credits':'250','historical_conservative_carry_credits':d.BASELINE,
            'preflight_path':'results/preflight.json','runtime_config':d.RUNTIME_CONFIG,'deadline_utc':d.DEADLINE.isoformat()}
        self.write(d.FREEZE,frozen)
        self.stack.enter_context(patch.object(d,'historical_integrity',return_value={'protected':protected}))
        self.stack.enter_context(patch.object(d,'local_dependencies',return_value=set()))
        self.stack.enter_context(patch.object(d,'verify_execution_manifest',return_value=frozen))
        return slots,receipt,frozen

    def test_exact_additive_freeze_and_runtime_carry_validation(self):
        slots,receipt,_ = self.fixture()
        self.assertEqual(d.verify_frozen(d.sha(self.root/d.FREEZE)),slots)
        self.assertEqual(d.continuation_integrity(slots),receipt)
        self.verifier.assert_called_with(slots,self.root/d.CONTINUATION,d.CONTINUATION_SHA)

    def test_failed_or_changed_carry_validation_blocks_admission(self):
        slots,_,_ = self.fixture()
        self.verifier.side_effect=ValueError('source_bytes_changed')
        with self.assertRaisesRegex(ValueError,'source_bytes_changed'):d.continuation_integrity(slots)

    def test_definitive_skips_must_be_carried_and_issued_count_stays213(self):
        slots,_,_ = self.fixture()
        for key in ('finals','issued_slot_ids'):
            old=deepcopy(self.carry[key])
            self.carry[key].pop(next(iter(self.carry[key]))) if isinstance(old,dict) else self.carry[key].pop()
            with self.assertRaisesRegex(ValueError,'exact_prior_definitive'):d.continuation_integrity(slots)
            self.carry[key]=old

    def test_carried_final_can_never_be_reissued(self):
        slots,receipt,_=self.fixture()
        self.carry['continuation_slot_ids'][0]='0'
        receipt['continuation_slot_ids'][0]='0';self.write(d.CONTINUATION,receipt)
        with patch.object(d,'CONTINUATION_SHA',d.sha(self.root/d.CONTINUATION)):
            with self.assertRaisesRegex(ValueError,'no_reissued_final'):d.continuation_integrity(slots)

    def test_old_path_budget_or_counts_rejected(self):
        _,_,frozen=self.fixture()
        for key,value in [('output_path','results/frontier-v6j/continuation'),('historical_conservative_carry_credits','47.653269434'),('carried_final_slots',213),('continuation_slots',1794),('cumulative_cap_credits','251')]:
            bad=deepcopy(frozen);bad[key]=value;self.write(d.FREEZE,bad)
            with self.assertRaisesRegex(ValueError,'freeze_fixed_contract'):d.verify_frozen(d.sha(self.root/d.FREEZE))

    def test_modified_protected_input_or_new_dependency_rejected(self):
        _,_,_=self.fixture();expected=d.sha(self.root/d.FREEZE)
        helper=self.write('retrace/unlisted.py',b'pass\n')
        with patch.object(d,'local_dependencies',return_value={helper}):
            with self.assertRaisesRegex(ValueError,'missing_execution_dependency'):d.verify_frozen(expected)
        self.write(d.BASELINE_LEDGER,b'changed accounting\n')
        with self.assertRaisesRegex(ValueError,'frozen_dependency_changed'):d.verify_frozen(expected)

    def test_duplicate_inventory_and_failed_preflight_rejected(self):
        _,_,frozen=self.fixture();frozen['files'].append(deepcopy(frozen['files'][0]));self.write(d.FREEZE,frozen)
        with self.assertRaisesRegex(ValueError,'duplicate_frozen_file'):d.verify_frozen(d.sha(self.root/d.FREEZE))
        frozen['files'].pop();self.write(d.FREEZE,frozen);self.write('results/preflight.json',{'passed':False})
        with self.assertRaisesRegex(ValueError,'passed_preflight_required'):d.verify_frozen(d.sha(self.root/d.FREEZE))

    def test_outputs_and_freeze_are_exclusive(self):
        for name,reason in [(d.OUTPUT,'study_already_exists'),(d.LEDGER,'ledger_already_exists'),(d.BASE+'/STOP','stop_file_present')]:
            p=self.write(name,b'preserve')
            with self.assertRaisesRegex(ValueError,reason):d.fresh_destination()
            self.assertEqual(p.read_bytes(),b'preserve');p.unlink()
        p=self.write(d.FREEZE,b'preserve')
        with self.assertRaisesRegex(ValueError,'freeze_already_exists'):d.freeze()
        with self.assertRaises(FileExistsError):d.write_new(p,{})

    def execution(self):
        calls=[];slots=[{'fixture':'full frozen schedule'}]
        self.stack.enter_context(patch.object(d,'verify_frozen',side_effect=lambda h:calls.append(('verify',h)) or slots))
        self.stack.enter_context(patch.object(d.sys,'stdin',io.StringIO('synthetic-test-key\n')))
        class Ledger:
            def __init__(self,directory,*,baseline_path):calls.append(('ledger',directory,baseline_path))
            def close(self):calls.append(('close',))
        class Transport:
            def __init__(self,key,timeout,connections):calls.append(('transport',timeout,connections))
            async def __aenter__(self):return self
            async def __aexit__(self,*_):calls.append(('exit',))
        async def run(slots,**kw):calls.append(('run',slots,kw));return {'synthetic':True}
        for name,value in [('RollingLedger',Ledger),('AiohttpTransport',Transport),('run_slots',run)]:self.stack.enter_context(patch.object(d,name,value))
        return calls

    def test_execution_reauthenticates_before_exclusive_single_worker(self):
        calls=self.execution();asyncio.run(d.execute('a'*64))
        self.assertEqual([x[0] for x in calls],['verify','verify','ledger','transport','run','exit','close'])
        self.assertIn(('transport',180,1),calls)
        kw=next(x[2] for x in calls if x[0]=='run')
        self.assertEqual(kw['output_dir'],self.root/d.OUTPUT)
        self.assertEqual(kw['execution_manifest_sha256'],'a'*64)

    def test_changed_freeze_or_deadline_during_stdin_cannot_start(self):
        calls=self.execution()
        with patch.object(d,'verify_frozen',side_effect=[[],ValueError('changed')]):
            with self.assertRaisesRegex(ValueError,'changed'):asyncio.run(d.execute('a'*64))
        self.assertFalse((self.root/d.LEDGER).exists());self.assertEqual(calls,[])
        class Past:
            @staticmethod
            def now(tz):return d.DEADLINE+timedelta(seconds=1)
        with patch.object(d,'datetime',Past):
            with self.assertRaisesRegex(ValueError,'delivery_buffer_reached'):asyncio.run(d.execute('a'*64))
        self.assertEqual(calls,[])

    def test_runtime_exception_closes_ledger_without_retry(self):
        calls=self.execution()
        async def fail(*a,**kw):raise RuntimeError('synthetic')
        with patch.object(d,'run_slots',fail):
            with self.assertRaisesRegex(RuntimeError,'synthetic'):asyncio.run(d.execute('a'*64))
        self.assertEqual(sum(x[0]=='transport' for x in calls),1)
        self.assertEqual([x[0] for x in calls][-2:],['exit','close'])


if __name__=='__main__':unittest.main()
