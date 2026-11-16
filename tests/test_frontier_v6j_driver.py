"""Isolated continuation-driver admission tests. No network or live artifacts."""
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

from scripts import run_frontier_v6j as driver
from retrace import adaption_v6j as runtime


class ContinuationDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(driver, 'ROOT', self.root))
        self.stack.enter_context(patch.object(runtime, 'ROOT', self.root))
        class Clock:
            @staticmethod
            def now(tz=None): return datetime(2026, 11, 14, tzinfo=tz or timezone.utc)
        self.stack.enter_context(patch.object(driver, 'datetime', Clock))

    def write(self, name, value, raw=False):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if raw else json.dumps(value).encode())
        return path

    def fixture(self):
        slots = [{'slot_id': f'fixture-{i}'} for i in range(1800)]
        for name in driver.NEW_FILES: self.write(name, {'fixture': name})
        self.write(driver.SESSIONS, slots)
        self.write(driver.BASELINE_LEDGER, b'new immutable 47.653269434 carry\n', raw=True)
        self.write('results/fixture-preflight.json', {'passed': True, 'paid_calls': 0})
        self.final_name = 'results/frontier-v6i/primary/slot-outcomes.jsonl'
        finals = [{'slot_id': s['slot_id'], 'issued': i < 6, 'attempt_id': f'prior-{i}' if i < 6 else None}
                  for i, s in enumerate(slots)]
        self.write(self.final_name, ('\n'.join(json.dumps(r) for r in finals) + '\n').encode(), raw=True)
        receipt = {'sessions_sha256': driver.digest(slots), 'full_planned_slots': 1800,
            'observed_response_models': dict(driver.OBSERVED_ROUTES),
            'permanently_excluded_issued_slot_ids': [s['slot_id'] for s in slots[:6]],
            'continuation_slot_ids': [s['slot_id'] for s in slots[6:]],
            'prior_journal_files': {self.final_name: driver.sha(self.root / self.final_name)},
            'carryover_rows': [{'source_path': self.final_name, 'source_line_one_based': i+1,
                'slot_id': row['slot_id'], 'row_sha256': driver.digest(row)} for i, row in enumerate(finals[:6])],
            'failed_producer_descendant_slot_ids': ['fixture-6', 'fixture-7']}
        self.write(driver.CONTINUATION, receipt)
        self.receipt_hash = driver.sha(self.root / driver.CONTINUATION)
        self.stack.enter_context(patch.object(driver, 'CONTINUATION_SHA', self.receipt_hash))
        self.stack.enter_context(patch.object(runtime, 'CONTINUATION_SHA', self.receipt_hash))
        protected = {'data/protected-fixture.txt': driver.sha(self.write('data/protected-fixture.txt', b'unchanged', raw=True))}
        names = set(driver.NEW_FILES) | set(protected) | {driver.BASELINE_LEDGER, self.final_name, 'results/fixture-preflight.json'}
        frozen = {'schema': 'retrace.frontier-v6j-freeze.v1',
            'files': [{'path': p, 'sha256': driver.sha(self.root/p), 'bytes': (self.root/p).stat().st_size} for p in sorted(names)],
            'sessions_path': driver.SESSIONS, 'study_path': driver.DESIGN,
            'sessions_sha256': driver.digest(slots), 'sessions_file_sha256': driver.sha(self.root/driver.SESSIONS),
            'output_path': driver.OUTPUT, 'ledger_path': driver.LEDGER,
            'baseline_path': driver.BASELINE_LEDGER, 'baseline_sha256': driver.sha(self.root/driver.BASELINE_LEDGER),
            'scheduled_slots': 1800, 'continuation_slots': 1794, 'carried_issued_slots': 6,
            'continuation_path': driver.CONTINUATION, 'continuation_sha256': self.receipt_hash,
            'observed_response_models': dict(driver.OBSERVED_ROUTES),
            'authorization_path': driver.AUTH, 'authorization_sha256': driver.AUTH_SHA,
            'cumulative_cap_credits': '250', 'historical_conservative_carry_credits': driver.BASELINE,
            'preflight_path': 'results/fixture-preflight.json', 'runtime_config': runtime.RUNTIME_CONFIG,
            'deadline_utc': runtime.DEADLINE.isoformat()}
        self.write(driver.FREEZE, frozen)
        self.stack.enter_context(patch.object(driver, 'historical_integrity', return_value={'protected': protected}))
        self.stack.enter_context(patch.object(driver, 'local_dependencies', return_value=set()))
        return slots, receipt, frozen

    def pin_receipt(self, receipt):
        self.write(driver.CONTINUATION, receipt)
        value = driver.sha(self.root / driver.CONTINUATION)
        self.stack.enter_context(patch.object(driver, 'CONTINUATION_SHA', value))
        self.stack.enter_context(patch.object(runtime, 'CONTINUATION_SHA', value))

    def test_exact_new_freeze_and_ordered_unissued_complement(self):
        slots, receipt, _ = self.fixture()
        self.assertEqual(driver.verify_frozen(driver.sha(self.root/driver.FREEZE)), slots)
        self.assertEqual(driver.continuation_integrity(slots), receipt)
        self.assertEqual(len(receipt['continuation_slot_ids']), 1794)

    def test_issued_slot_cannot_be_reintroduced_or_unissued_slot_omitted(self):
        slots, receipt, _ = self.fixture()
        bad = deepcopy(receipt); bad['continuation_slot_ids'][0] = 'fixture-0'; self.pin_receipt(bad)
        with self.assertRaisesRegex(ValueError, 'unissued_only_continuation'): driver.continuation_integrity(slots)
        bad = deepcopy(receipt); bad['continuation_slot_ids'].pop(); self.pin_receipt(bad)
        with self.assertRaisesRegex(ValueError, 'unissued_only_continuation'): driver.continuation_integrity(slots)

    def test_exclusion_set_must_match_original_issued_selection(self):
        slots, receipt, _ = self.fixture()
        bad = deepcopy(receipt); bad['permanently_excluded_issued_slot_ids'][-1] = 'fixture-6'
        bad['continuation_slot_ids'] = [s['slot_id'] for s in slots if s['slot_id'] not in bad['permanently_excluded_issued_slot_ids']]
        self.pin_receipt(bad)
        with self.assertRaisesRegex(ValueError, 'carryover_issued_selection'): driver.continuation_integrity(slots)

    def test_original_row_content_and_line_binding_cannot_change(self):
        slots, receipt, _ = self.fixture()
        bad = deepcopy(receipt); bad['carryover_rows'][0]['row_sha256'] = 'f'*64; self.pin_receipt(bad)
        with self.assertRaisesRegex(ValueError, 'carryover_source_row_changed'): driver.continuation_integrity(slots)
        bad = deepcopy(receipt); bad['carryover_rows'][0]['source_line_one_based'] = 2; self.pin_receipt(bad)
        with self.assertRaisesRegex(ValueError, 'carryover_source_row_changed'): driver.continuation_integrity(slots)
        self.pin_receipt(receipt); self.write(self.final_name, b'changed original output\n', raw=True)
        with self.assertRaisesRegex(ValueError, 'carryover_journal_changed'): driver.continuation_integrity(slots)

    def test_duplicate_carry_bindings_and_nonpositive_or_boolean_lines_rejected(self):
        slots, receipt, _ = self.fixture()
        bad = deepcopy(receipt); bad['carryover_rows'][1] = deepcopy(bad['carryover_rows'][0]); self.pin_receipt(bad)
        with self.assertRaisesRegex(ValueError, 'carryover_binding_order_or_duplicate'): driver.continuation_integrity(slots)
        for value in (0, -1799, True, 1801):
            with self.subTest(line=value):
                bad = deepcopy(receipt); bad['carryover_rows'][0]['source_line_one_based'] = value; self.pin_receipt(bad)
                with self.assertRaisesRegex(ValueError, 'carryover_positive_source_line'): driver.continuation_integrity(slots)

    def test_only_exact_observed_route_can_be_authorized(self):
        slots, receipt, frozen = self.fixture()
        bad = deepcopy(receipt); bad['observed_response_models']['qwen3.5-397b'] = 'some-other-route'; self.pin_receipt(bad)
        with self.assertRaisesRegex(ValueError, 'observed_route_changed'): driver.continuation_integrity(slots)
        frozen['observed_response_models'] = {}
        self.write(driver.FREEZE, frozen)
        with self.assertRaisesRegex(ValueError, 'freeze_fixed_contract'): driver.verify_frozen(driver.sha(self.root/driver.FREEZE))

    def test_old_carry_and_old_output_path_cannot_replace_new_contract(self):
        _, _, frozen = self.fixture()
        frozen['historical_conservative_carry_credits'] = '47.409962587'; self.write(driver.FREEZE, frozen)
        with self.assertRaisesRegex(ValueError, 'freeze_fixed_contract'): driver.verify_frozen(driver.sha(self.root/driver.FREEZE))
        frozen['historical_conservative_carry_credits'] = driver.BASELINE
        frozen['output_path'] = 'results/frontier-v6i/primary'; self.write(driver.FREEZE, frozen)
        with self.assertRaisesRegex(ValueError, 'freeze_fixed_contract'): driver.verify_frozen(driver.sha(self.root/driver.FREEZE))

    def test_changed_baseline_or_scoring_dependency_is_rejected(self):
        _, _, _ = self.fixture(); expected = driver.sha(self.root/driver.FREEZE)
        self.write(driver.BASELINE_LEDGER, b'old amount or released bound\n', raw=True)
        with self.assertRaisesRegex(ValueError, 'frozen_dependency_changed'): driver.verify_frozen(expected)

    def test_missing_new_local_dependency_or_duplicate_inventory_rejected(self):
        _, _, frozen = self.fixture(); expected = driver.sha(self.root/driver.FREEZE)
        path = self.write('retrace/new-helper.py', b'pass\n', raw=True)
        with patch.object(driver, 'local_dependencies', return_value={path}):
            with self.assertRaisesRegex(ValueError, 'missing_execution_dependency'): driver.verify_frozen(expected)
        frozen['files'].append(frozen['files'][0]); self.write(driver.FREEZE, frozen)
        with self.assertRaisesRegex(ValueError, 'duplicate_frozen_file'): driver.verify_frozen(driver.sha(self.root/driver.FREEZE))

    def test_fresh_destination_and_exclusive_freeze(self):
        for relative, reason in ((driver.OUTPUT, 'study_already_exists'), (driver.LEDGER, 'ledger_already_exists'), (driver.BASE+'/STOP', 'stop_file_present')):
            p = self.write(relative, b'preserved', raw=True)
            with self.assertRaisesRegex(ValueError, reason): driver.fresh_destination()
            self.assertEqual(p.read_bytes(), b'preserved'); p.unlink()
        p = self.write(driver.FREEZE, b'preserved', raw=True)
        with self.assertRaisesRegex(ValueError, 'freeze_already_exists'): driver.freeze()
        with self.assertRaises(FileExistsError): driver.write_new(p, {})

    def execution_fakes(self):
        calls = []; slots = [{'fixture': 'complete frozen schedule passed to runtime'}]
        self.stack.enter_context(patch.object(driver, 'verify_frozen', side_effect=lambda h: calls.append(('verify', h)) or slots))
        self.stack.enter_context(patch.object(driver.sys, 'stdin', io.StringIO('synthetic-not-live-key\n')))
        class Ledger:
            def __init__(self, directory, *, baseline_path): calls.append(('ledger', directory, baseline_path))
            def close(self): calls.append(('close',))
        class Transport:
            def __init__(self, key, timeout, connections): calls.append(('transport', timeout, connections))
            async def __aenter__(self): return self
            async def __aexit__(self, *_): calls.append(('exit',))
        async def run(slots, **kwargs): calls.append(('run', slots, kwargs)); return {'fixture': True}
        self.stack.enter_context(patch.object(driver, 'RollingLedger', Ledger))
        self.stack.enter_context(patch.object(driver, 'AiohttpTransport', Transport))
        self.stack.enter_context(patch.object(driver, 'run_slots', run))
        return calls

    def test_execute_rechecks_and_passes_new_ledger_full_schedule_and_freeze(self):
        calls = self.execution_fakes(); asyncio.run(driver.execute('a'*64))
        self.assertEqual([r[0] for r in calls], ['verify', 'verify', 'ledger', 'transport', 'run', 'exit', 'close'])
        ledger = next(r for r in calls if r[0] == 'ledger')
        self.assertEqual(ledger[1:], (self.root/driver.LEDGER, self.root/driver.BASELINE_LEDGER))
        self.assertEqual(next(r for r in calls if r[0] == 'transport')[1:], (180, 1))
        kw = next(r for r in calls if r[0] == 'run')[2]
        self.assertEqual(kw['output_dir'], self.root/driver.OUTPUT)
        self.assertEqual(kw['execution_manifest_path'], self.root/driver.FREEZE)
        self.assertEqual(kw['execution_manifest_sha256'], 'a'*64)

    def test_changed_freeze_during_credential_wait_cannot_open_ledger(self):
        calls = self.execution_fakes()
        with patch.object(driver, 'verify_frozen', side_effect=[[], ValueError('changed')]):
            with self.assertRaisesRegex(ValueError, 'changed'): asyncio.run(driver.execute('a'*64))
        self.assertEqual(calls, [])
        self.assertFalse((self.root/driver.LEDGER).exists())

    def test_deadline_before_or_during_credential_wait_blocks_transport(self):
        class Past:
            @staticmethod
            def now(tz): return runtime.DEADLINE+timedelta(seconds=1)
        class Forbidden:
            def readline(self): raise AssertionError('credential read after cutoff')
        with patch.object(driver, 'datetime', Past), patch.object(driver.sys, 'stdin', Forbidden()):
            with self.assertRaisesRegex(ValueError, 'delivery_buffer_reached'): asyncio.run(driver.execute('a'*64))
        calls = self.execution_fakes()
        class Changing:
            count = 0
            @classmethod
            def now(cls, tz):
                cls.count += 1
                return runtime.DEADLINE+timedelta(seconds=1 if cls.count > 1 else -1)
        with patch.object(driver, 'datetime', Changing):
            with self.assertRaisesRegex(ValueError, 'delivery_buffer_reached'): asyncio.run(driver.execute('a'*64))
        self.assertEqual([r[0] for r in calls], ['verify'])

    def test_exclusive_directory_race_and_runtime_failure_never_retry(self):
        calls = self.execution_fakes(); original = Path.mkdir
        def mkdir(path, *args, **kwargs):
            if path == self.root/driver.LEDGER:
                self.assertIs(kwargs.get('exist_ok'), False)
                raise FileExistsError('exclusive race')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', mkdir):
            with self.assertRaises(FileExistsError): asyncio.run(driver.execute('a'*64))
        self.assertEqual([r[0] for r in calls], ['verify', 'verify'])
        calls.clear()
        async def fail(*args, **kwargs): raise RuntimeError('fixture failure')
        with patch.object(driver, 'run_slots', fail), patch.object(driver.sys, 'stdin', io.StringIO('synthetic-not-live-key\n')):
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'): asyncio.run(driver.execute('a'*64))
        self.assertEqual(sum(r[0]=='transport' for r in calls), 1)
        self.assertEqual([r[0] for r in calls][-2:], ['exit', 'close'])


if __name__ == '__main__':
    unittest.main()
