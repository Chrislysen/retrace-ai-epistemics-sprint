"""Independent pre-dispatch driver guards; fake files/transport, never paid calls."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import scripts.run_frontier_v6h_paced as driver
from retrace.adaption_v6h import PRIMARY_MODELS


def write(root, relative, value):
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8');return path


def complete_canary():
    return {'schema':'retrace.adaption-v6h-summary.v1','canary':True,'status':'completed','stream':True,
        'planned':10,'issued_slots':10,'slot_outcomes':10,'valid_terminal_records':10,
        'issued_operational_failures':0,'dependency_skips':0,'unissued_slot_ids':[],
        'issued_without_outcome_attempt_ids':[],'models':{m:2 for m in PRIMARY_MODELS}}


class PacedDriverTests(unittest.IsolatedAsyncioTestCase):
    def setup_execute(self, root, phase='canary'):
        ledger=root/'results/frontier-v6h/budget/ledger.jsonl'
        ledger.parent.mkdir(parents=True);ledger.write_bytes(b'closed-prefix\n')
        dependency=root/'retrace/new_runtime.py';dependency.parent.mkdir();dependency.write_text('original',encoding='utf-8')
        slots=write(root,'data/test-slots.json',[{'slot_id':'fake-only'}])
        frozen={'phase':phase,'runtime_config':driver.CONFIG,'primary_admission_cutoff_utc':driver.CUTOFF.isoformat(),
            'files':[{'path':'retrace/new_runtime.py','sha256':driver.sha(dependency)}],
            'ledger_prefix_sha256':driver.sha(ledger),'sessions_path':'data/test-slots.json','scheduled_slots':1}
        path=write(root,f'data/frontier-v6h-paced-{phase}-freeze.json',frozen)
        if phase=='primary':write(root,driver.BASE+'/canary/summary.json',complete_canary())
        return path,ledger,dependency

    def guarded(self, root, *, instant=None, integrity=None, key_callback=None):
        stack=ExitStack();self.addCleanup(stack.close)
        clock=SimpleNamespace(value=instant or driver.CUTOFF-timedelta(hours=1))
        class Clock:
            @staticmethod
            def now(_):return clock.value
        stdin=SimpleNamespace(readline=Mock(side_effect=key_callback,return_value='offline-test-key'))
        ledger=Mock(side_effect=AssertionError('A real ledger must not be opened'))
        transport=Mock(side_effect=AssertionError('A transport must not be constructed'))
        fake_module=SimpleNamespace(run_slots=AsyncMock(side_effect=AssertionError('No dispatch permitted')))
        stack.enter_context(patch.object(driver,'ROOT',root))
        stack.enter_context(patch.object(driver,'datetime',Clock))
        stack.enter_context(patch.object(driver,'original_integrity',integrity or Mock(return_value={'files':[]})))
        stack.enter_context(patch.object(driver,'RollingLedger',ledger))
        stack.enter_context(patch.object(driver,'AiohttpTransport',transport))
        stack.enter_context(patch.object(driver.sys,'stdin',stdin))
        stack.enter_context(patch.dict('sys.modules',{'retrace.adaption_global_v6h':fake_module}))
        return clock,stdin,ledger,transport,fake_module

    async def test_expired_deadline_rejects_before_credentials_or_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_,_=self.setup_execute(root)
            _,stdin,ledger,transport,_=self.guarded(root,instant=driver.CUTOFF)
            with self.assertRaisesRegex(ValueError,'delivery_buffer_reached'):await driver.execute('canary',driver.sha(path))
            stdin.readline.assert_not_called();ledger.assert_not_called();transport.assert_not_called()

    async def test_cutoff_crossed_during_integrity_check_does_not_read_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_,_=self.setup_execute(root)
            hook=Mock();clock,stdin,ledger,transport,_=self.guarded(root,integrity=hook)
            hook.side_effect=lambda:setattr(clock,'value',driver.CUTOFF)
            with self.assertRaisesRegex(ValueError,'delivery_buffer_reached'):await driver.execute('canary',driver.sha(path))
            stdin.readline.assert_not_called();ledger.assert_not_called();transport.assert_not_called()

    async def test_cutoff_crossed_while_waiting_for_key_opens_no_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_,_=self.setup_execute(root)
            clock,stdin,ledger,transport,_=self.guarded(root)
            def key():clock.value=driver.CUTOFF;return 'offline-test-key'
            stdin.readline.side_effect=key
            with self.assertRaisesRegex(ValueError,'delivery_buffer_reached'):await driver.execute('canary',driver.sha(path))
            stdin.readline.assert_called_once();ledger.assert_not_called();transport.assert_not_called()

    async def test_failed_original_canary_cannot_unlock_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_,_=self.setup_execute(root,'primary')
            failed=complete_canary();failed['valid_terminal_records']=9
            write(root,driver.BASE+'/canary/summary.json',failed)
            _,stdin,ledger,transport,_=self.guarded(root)
            with self.assertRaisesRegex(ValueError,'canary_not_terminal_complete'):await driver.execute('primary',driver.sha(path))
            stdin.readline.assert_not_called();ledger.assert_not_called();transport.assert_not_called()

    async def test_intervening_ledger_append_rejected_before_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,ledger_path,_=self.setup_execute(root)
            with ledger_path.open('ab') as f:f.write(b'new-attempt\n')
            _,stdin,ledger,transport,_=self.guarded(root)
            with self.assertRaisesRegex(ValueError,'intervening_calls'):await driver.execute('canary',driver.sha(path))
            stdin.readline.assert_not_called();ledger.assert_not_called();transport.assert_not_called()

    async def test_ledger_append_while_waiting_for_key_rejected_before_open(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,ledger_path,_=self.setup_execute(root)
            _,stdin,ledger,transport,_=self.guarded(root)
            def key():
                with ledger_path.open('ab') as f:f.write(b'intervening-attempt\n')
                return 'offline-test-key'
            stdin.readline.side_effect=key
            with self.assertRaisesRegex(ValueError,'intervening_calls'):await driver.execute('canary',driver.sha(path))
            stdin.readline.assert_called_once();ledger.assert_not_called();transport.assert_not_called()

    async def test_lock_held_prefix_recheck_closes_ledger_before_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,ledger_path,_=self.setup_execute(root)
            _,stdin,ledger,transport,_=self.guarded(root)
            opened=SimpleNamespace(close=Mock())
            def acquire(*_,**__):
                with ledger_path.open('ab') as f:f.write(b'completed-during-lock-race\n')
                return opened
            ledger.side_effect=acquire
            with self.assertRaisesRegex(ValueError,'intervening_calls'):await driver.execute('canary',driver.sha(path))
            stdin.readline.assert_called_once();ledger.assert_called_once();opened.close.assert_called_once();transport.assert_not_called()

    async def test_changed_paced_module_rejected_before_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_,dependency=self.setup_execute(root)
            dependency.write_text('changed',encoding='utf-8')
            _,stdin,ledger,transport,_=self.guarded(root)
            with self.assertRaisesRegex(ValueError,'paced_dependency_changed'):await driver.execute('canary',driver.sha(path))
            stdin.readline.assert_not_called();ledger.assert_not_called();transport.assert_not_called()

    async def test_freeze_digest_and_declared_cutoff_cannot_be_overridden(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_,_=self.setup_execute(root)
            _,stdin,ledger,transport,_=self.guarded(root)
            with self.assertRaisesRegex(ValueError,'paced_freeze_changed'):await driver.execute('canary','0'*64)
            frozen=json.loads(path.read_text());frozen['primary_admission_cutoff_utc']=(driver.CUTOFF+timedelta(hours=1)).isoformat()
            path.write_text(json.dumps(frozen),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'cutoff_changed'):await driver.execute('canary',driver.sha(path))
            stdin.readline.assert_not_called();ledger.assert_not_called();transport.assert_not_called()

    def test_primary_freeze_rejects_post_canary_runtime_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);module=root/'retrace/new_runtime.py';module.parent.mkdir();module.write_text('version-before-canary')
            write(root,'data/frontier-v6h-paced-canary-freeze.json',{'runtime_config':driver.CONFIG,
                'files':[{'path':'retrace/new_runtime.py','sha256':driver.sha(module)}]})
            module.write_text('version-after-canary')
            with patch.object(driver,'ROOT',root),patch.object(driver,'original_integrity',return_value={'files':[]}):
                with self.assertRaisesRegex(ValueError,'post_canary_dependency_changed'):driver.frozen_paths('primary')

    def test_canary_freeze_rejects_probe_prefix_drift_before_tests_or_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);snapshot=root/driver.QUOTA_SNAPSHOT;snapshot.parent.mkdir();snapshot.write_bytes(b'probe-closure\n')
            ledger=root/'results/frontier-v6h/budget/ledger.jsonl';ledger.parent.mkdir(parents=True);ledger.write_bytes(b'probe-closure\nextra\n')
            write(root,'results/frontier-v6h-quota-probe/summary.json',{'rounds':[{'issued_attempts':5,'http_429_attempts':0,'first_attempt_completed':5} for _ in range(3)]})
            with patch.object(driver,'ROOT',root),patch.object(driver,'QUOTA_SHA',driver.sha(snapshot)),patch.object(driver,'frozen_paths',return_value=set()),patch.object(driver.unittest.TextTestRunner,'run') as tests:
                with self.assertRaisesRegex(ValueError,'intervening_calls'):driver.freeze('canary')
                tests.assert_not_called()
            self.assertFalse((root/'data/frontier-v6h-paced-ledger-before-canary.jsonl').exists())


if __name__=='__main__':unittest.main()
