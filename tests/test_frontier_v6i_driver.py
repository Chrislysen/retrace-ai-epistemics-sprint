"""Offline launch-driver admission tests, isolated from all real artifacts.

Full corpus/transport semantics have separate tests. These fixtures replace
those expensive semantic checks while exercising the driver's hash inventory,
exclusive paths, stdin ordering and exact runtime wiring without network calls.
"""
import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_frontier_v6i as driver
from retrace.adaption_v6i import DEADLINE, RUNTIME_CONFIG, digest


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(driver, 'ROOT', self.root))
        class FixedDateTime:
            @staticmethod
            def now(tz=None): return datetime(2026, 11, 14, tzinfo=tz or timezone.utc)
        self.stack.enter_context(patch.object(driver, 'datetime', FixedDateTime))

    def write(self, relative, value, *, raw=False):
        path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if raw else json.dumps(value).encode())
        return path

    def admission_fixture(self):
        # 1,800 slot identities exercise the driver's count/hash contract only;
        # full source and dependency validation is separately tested upstream.
        slots = [{'slot_id': f'fixture-{i}'} for i in range(1800)]
        for relative in driver.NEW_FILES: self.write(relative, {'fixture': relative})
        self.write(driver.SESSIONS, slots)
        self.write(driver.BASELINE_LEDGER, b'preserved-ledger-fixture\n', raw=True)
        self.write('results/fixture-preflight.json', {'passed': True, 'paid_calls': 0})
        protected = {'data/prior-fixture.txt': hashlib.sha256(b'unchanged').hexdigest()}
        self.write('data/prior-fixture.txt', b'unchanged', raw=True)
        required = set(driver.NEW_FILES) | set(protected) | {driver.BASELINE_LEDGER, 'results/fixture-preflight.json'}
        inventory = [{'path': p, 'sha256': driver.sha(self.root / p), 'bytes': (self.root / p).stat().st_size} for p in sorted(required)]
        freeze = {'schema': 'retrace.frontier-v6i-freeze.v1', 'files': inventory,
            'sessions_path': driver.SESSIONS, 'study_path': driver.DESIGN,
            'sessions_sha256': digest(slots), 'sessions_file_sha256': driver.sha(self.root / driver.SESSIONS),
            'output_path': driver.OUTPUT, 'ledger_path': driver.LEDGER,
            'baseline_path': driver.BASELINE_LEDGER, 'baseline_sha256': driver.sha(self.root / driver.BASELINE_LEDGER),
            'scheduled_slots': 1800, 'authorization_path': driver.AUTH, 'authorization_sha256': driver.AUTH_SHA,
            'cumulative_cap_credits': '250', 'historical_conservative_carry_credits': driver.BASELINE,
            'preflight_path': 'results/fixture-preflight.json', 'runtime_config': RUNTIME_CONFIG,
            'deadline_utc': DEADLINE.isoformat()}
        self.write(driver.FREEZE, freeze)
        self.stack.enter_context(patch.object(driver, 'historical_integrity', return_value={'protected': protected}))
        self.stack.enter_context(patch.object(driver, 'local_dependencies', return_value=set()))
        return slots, freeze, driver.sha(self.root / driver.FREEZE)

    def replace_freeze(self, value):
        self.write(driver.FREEZE, value)
        return driver.sha(self.root / driver.FREEZE)

    def test_complete_inventory_and_exact_sessions_admitted(self):
        slots, _, sha = self.admission_fixture()
        self.assertEqual(driver.verify_frozen(sha), slots)

    def test_modified_dependency_or_baseline_rejected(self):
        _, _, sha = self.admission_fixture()
        self.write('data/prior-fixture.txt', b'changed', raw=True)
        with self.assertRaisesRegex(ValueError, 'dependency_changed'): driver.verify_frozen(sha)
        self.write('data/prior-fixture.txt', b'unchanged', raw=True)
        self.write(driver.BASELINE_LEDGER, b'different retained amount\n', raw=True)
        with self.assertRaisesRegex(ValueError, 'dependency_changed'): driver.verify_frozen(sha)

    def test_missing_or_duplicate_inventory_cannot_admit(self):
        _, frozen, _ = self.admission_fixture()
        original = list(frozen['files'])
        frozen['files'] = [r for r in original if r['path'] != 'retrace/adaption_v6i.py']
        with self.assertRaisesRegex(ValueError, 'incomplete_freeze_inventory'): driver.verify_frozen(self.replace_freeze(frozen))
        frozen['files'] = original + [original[0]]
        with self.assertRaisesRegex(ValueError, 'duplicate_frozen_file'): driver.verify_frozen(self.replace_freeze(frozen))

    def test_newly_imported_local_dependency_must_be_frozen(self):
        _, _, sha = self.admission_fixture()
        path = self.write('retrace/new-dependency.py', b'pass\n', raw=True)
        with patch.object(driver, 'local_dependencies', return_value={path}):
            with self.assertRaisesRegex(ValueError, 'missing_execution_dependency'): driver.verify_frozen(sha)

    def test_invalid_or_changed_preflight_rejected(self):
        _, frozen, _ = self.admission_fixture()
        self.write('results/fixture-preflight.json', {'passed': False})
        with self.assertRaisesRegex(ValueError, 'passed_preflight_required'): driver.verify_frozen(self.replace_freeze(frozen))
        self.write('results/fixture-preflight.json', {'passed': True, 'paid_calls': 0, 'changed': True})
        with self.assertRaisesRegex(ValueError, 'dependency_changed'): driver.verify_frozen(self.replace_freeze(frozen))

    def test_preflight_outside_workspace_is_rejected_before_read(self):
        _, frozen, _ = self.admission_fixture()
        frozen['preflight_path'] = '../outside-preflight.json'
        frozen['files'].append({'path': '../outside-preflight.json', 'sha256': '0' * 64, 'bytes': 0})
        with self.assertRaisesRegex(ValueError, 'invalid_frozen_path'): driver.verify_frozen(self.replace_freeze(frozen))

    def test_canonical_output_and_budget_contract_cannot_be_redirected(self):
        _, frozen, _ = self.admission_fixture()
        frozen['output_path'] = 'results/different-run'
        with self.assertRaisesRegex(ValueError, 'freeze_fixed_contract'): driver.verify_frozen(self.replace_freeze(frozen))

    def test_policy_and_session_count_checked_even_with_new_manifest_hash(self):
        _, frozen, _ = self.admission_fixture()
        config = dict(RUNTIME_CONFIG); config['global_concurrency'] = 2
        frozen['runtime_config'] = config
        with self.assertRaisesRegex(ValueError, 'execution_policy_mismatch'): driver.verify_frozen(self.replace_freeze(frozen))
        frozen['runtime_config'] = RUNTIME_CONFIG
        frozen['scheduled_slots'] = 1799
        with self.assertRaisesRegex(ValueError, 'freeze_fixed_contract'): driver.verify_frozen(self.replace_freeze(frozen))

    def test_any_existing_destination_or_stop_blocks_launch(self):
        for relative, error in ((driver.OUTPUT, 'study_already_exists'), (driver.LEDGER, 'ledger_already_exists'), (driver.BASE + '/STOP', 'stop_file_present')):
            with self.subTest(relative=relative):
                path = self.write(relative, b'', raw=True)
                with self.assertRaisesRegex(ValueError, error): driver.fresh_destination()
                path.unlink()

    def test_parent_junction_escape_is_rejected(self):
        original = Path.resolve; base = self.root / driver.BASE
        def resolve(path, *args, **kwargs):
            if path == base or base in path.parents: return self.root.parent / 'redirected-outside' / path.name
            return original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolve):
            with self.assertRaises(ValueError): driver.fresh_destination()
        self.assertFalse((self.root / driver.LEDGER).exists())

    def test_existing_freeze_never_overwrites(self):
        p = self.write(driver.FREEZE, b'original bytes', raw=True)
        with self.assertRaisesRegex(ValueError, 'freeze_already_exists'): driver.freeze()
        self.assertEqual(p.read_bytes(), b'original bytes')
        with self.assertRaises(FileExistsError): driver.write_new(p, {'replacement': True})

    def test_failed_preflight_is_preserved_but_cannot_create_freeze(self):
        slots, _, _ = self.admission_fixture()
        (self.root / driver.FREEZE).unlink()
        class Failed:
            testsRun = 3
            def wasSuccessful(self): return False
        class Runner:
            def __init__(self, **kwargs): pass
            def run(self, suite): return Failed()
        with patch.object(driver, 'scientific_integrity', return_value=slots), \
             patch.object(driver.unittest, 'TextTestRunner', Runner), \
             patch.object(driver.unittest.defaultTestLoader, 'loadTestsFromNames', return_value=object()), \
             patch.object(driver.importlib.metadata, 'version', return_value='offline-fixture'):
            with self.assertRaisesRegex(ValueError, 'preflight_failed'): driver.freeze()
        self.assertFalse((self.root / driver.FREEZE).exists())
        preserved = list((self.root / 'results').glob('frontier-v6i-preflight-*.json'))
        self.assertEqual(len(preserved), 1)
        self.assertIs(driver.read(preserved[0])['passed'], False)

    def execution_fakes(self, *, stdin='synthetic-not-live-key\n'):
        calls = []; slots = [{'fixture': True}]
        self.stack.enter_context(patch.object(driver, 'verify_frozen', side_effect=lambda expected: calls.append(('verify', expected)) or slots))
        self.stack.enter_context(patch.object(driver.sys, 'stdin', io.StringIO(stdin)))
        class Ledger:
            def __init__(self, directory, *, baseline_path): calls.append(('ledger', directory, baseline_path))
            def close(self): calls.append(('close',))
        class Transport:
            def __init__(self, key, timeout, connections): calls.append(('transport', timeout, connections)); self.key = key
            async def __aenter__(self): calls.append(('enter',)); return self
            async def __aexit__(self, *_): calls.append(('exit',))
        async def run(got_slots, **kwargs):
            calls.append(('run', got_slots, kwargs)); return {'status': 'completed', 'per_slot_operational_failures': 2}
        self.stack.enter_context(patch.object(driver, 'RollingLedger', Ledger))
        self.stack.enter_context(patch.object(driver, 'AiohttpTransport', Transport))
        self.stack.enter_context(patch.object(driver, 'run_slots', run))
        return calls

    def test_execute_revalidates_after_stdin_and_wires_exact_policy(self):
        calls = self.execution_fakes()
        result = asyncio.run(driver.execute('a' * 64))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([c[0] for c in calls], ['verify', 'verify', 'ledger', 'transport', 'enter', 'run', 'exit', 'close'])
        self.assertEqual(next(c for c in calls if c[0] == 'transport')[1:], (180, 1))
        kw = next(c for c in calls if c[0] == 'run')[2]
        self.assertEqual(kw['output_dir'], self.root / driver.OUTPUT)
        self.assertEqual(kw['execution_manifest_path'], self.root / driver.FREEZE)
        self.assertEqual(kw['execution_manifest_sha256'], 'a' * 64)
        self.assertEqual(kw['stop_file'], self.root / driver.BASE / 'STOP')
        self.assertEqual(kw['timeout_seconds'], 180)
        self.assertEqual(next(c for c in calls if c[0] == 'ledger')[2], self.root / driver.BASELINE_LEDGER)

    def test_invalid_freeze_fails_before_reading_credential(self):
        class ForbiddenInput:
            def readline(self): raise AssertionError('credential read before integrity')
        with patch.object(driver, 'verify_frozen', side_effect=ValueError('freeze_changed')), patch.object(driver.sys, 'stdin', ForbiddenInput()):
            with self.assertRaisesRegex(ValueError, 'freeze_changed'): asyncio.run(driver.execute('wrong'))
        self.assertFalse((self.root / driver.LEDGER).exists())

    def test_invalid_key_never_creates_ledger_or_transport(self):
        calls = self.execution_fakes(stdin='short\n')
        with self.assertRaisesRegex(ValueError, 'invalid_credential'): asyncio.run(driver.execute('a' * 64))
        self.assertEqual([c[0] for c in calls], ['verify'])
        self.assertFalse((self.root / driver.LEDGER).exists())

    def test_stdin_wait_tamper_stops_before_transport(self):
        calls = self.execution_fakes()
        def verify(expected):
            calls.append(('verify', expected))
            if len(calls) > 1: raise ValueError('frozen_dependency_changed')
            return []
        with patch.object(driver, 'verify_frozen', side_effect=verify):
            with self.assertRaisesRegex(ValueError, 'frozen_dependency_changed'): asyncio.run(driver.execute('a' * 64))
        self.assertFalse((self.root / driver.LEDGER).exists())

    def test_destination_created_during_stdin_wait_stops_before_transport(self):
        calls = self.execution_fakes()
        root = self.root
        class RacingInput:
            def readline(self):
                (root / driver.LEDGER).mkdir(parents=True)
                return 'synthetic-not-live-key\n'
        with patch.object(driver.sys, 'stdin', RacingInput()):
            with self.assertRaisesRegex(ValueError, 'ledger_already_exists'): asyncio.run(driver.execute('a' * 64))
        self.assertEqual([c[0] for c in calls], ['verify', 'verify'])

    def test_atomic_directory_race_never_constructs_transport(self):
        calls = self.execution_fakes(); original = Path.mkdir; expected = self.root / driver.LEDGER
        def mkdir(path, *args, **kwargs):
            if path == expected:
                self.assertIs(kwargs.get('exist_ok'), False)
                raise FileExistsError('another launcher won the exclusive directory')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', mkdir):
            with self.assertRaises(FileExistsError): asyncio.run(driver.execute('a' * 64))
        self.assertEqual([c[0] for c in calls], ['verify', 'verify'])

    def test_deadline_blocks_before_credential_read(self):
        class Past:
            @staticmethod
            def now(tz): return DEADLINE + timedelta(seconds=1)
        class ForbiddenInput:
            def readline(self): raise AssertionError('credential read after deadline')
        with patch.object(driver, 'datetime', Past), patch.object(driver.sys, 'stdin', ForbiddenInput()):
            with self.assertRaisesRegex(ValueError, 'delivery_buffer_reached'): asyncio.run(driver.execute('a' * 64))
        self.assertFalse((self.root / driver.LEDGER).exists())

    def test_runtime_exception_still_closes_ledger_and_does_not_retry(self):
        calls = self.execution_fakes()
        async def fail(*args, **kwargs): calls.append(('run_failed',)); raise RuntimeError('synthetic journal fault')
        with patch.object(driver, 'run_slots', fail):
            with self.assertRaisesRegex(RuntimeError, 'synthetic journal fault'): asyncio.run(driver.execute('a' * 64))
        self.assertEqual(sum(c[0] == 'transport' for c in calls), 1)
        self.assertEqual([c[0] for c in calls][-2:], ['exit', 'close'])
        self.assertTrue((self.root / driver.LEDGER).exists())
        with self.assertRaisesRegex(ValueError, 'ledger_already_exists'): driver.fresh_destination()


if __name__ == '__main__': unittest.main()
