"""Offline continuation tests; original observations remain immutable fixtures."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retrace import adaption_v6h as h
from retrace import adaption_v6j as j
from tests.test_adaption_v6h import KEY, MODEL, emit, final, slot
from tests import test_adaption_v6i as prior_tests
Clock = prior_tests.Clock

ROOT = Path(__file__).resolve().parents[1]
QWEN = 'qwen3.5-397b'
ROUTE = 'qwen3.5-397b-a17b-nvfp4'


def synthetic_carry(slots, seeds=None):
    seeds = seeds or {}; completed = {}
    for s in slots:
        if s['slot_id'] in seeds and seeds[s['slot_id']]['terminal_valid']:
            completed[s['slot_id']] = {'actual_input': s['input'], 'output_text': seeds[s['slot_id']]['output_text']}
    return {'finals': deepcopy(seeds), 'completed': completed, 'issued_slot_ids': list(seeds),
        'continuation_slot_ids': [s['slot_id'] for s in slots if s['slot_id'] not in seeds],
        'bindings': [], 'failed_descendant_slot_ids': [], 'last_issued_model': None,
        'original_run_id': 'synthetic-original', 'earliest_next_admission_utc': '2026-11-14T00:00:00+00:00',
        'continuation_path': j.CONTINUATION, 'continuation_sha256': j.CONTINUATION_SHA}


def make_manifest(path, slots, **overrides):
    value = {'sessions_sha256': j.digest(slots), 'runtime_config': j.RUNTIME_CONFIG,
        'deadline_utc': j.DEADLINE.isoformat(), 'continuation_path': j.CONTINUATION,
        'continuation_sha256': j.CONTINUATION_SHA, 'observed_response_models': j.OBSERVED_RESPONSE_MODELS, **overrides}
    raw = json.dumps(value).encode(); path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class ContinuationTests(unittest.TestCase):
    def run_case(self, slots, factory=None, *, clock=None, utc_start=None, before=None, carry=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); clock = clock or Clock(); starts = []; ends = []; reservations = []
            class Ledger(j.RollingLedger):
                def record(self, event):
                    if event['kind'] == 'reserve': reservations.append((clock.now(), event['slot_id']))
                    super().record(event)
            ledger = Ledger(root / 'budget', baseline_path=ROOT / j.BASELINE_LEDGER)
            p = root / 'execution.json'; sha = make_manifest(p, slots)
            chosen = factory(clock, starts, ends) if factory else lambda body: emit(final(body))
            active = [0]; peak = [0]
            async def transport(body):
                starts.append((clock.now(), body['model'], body['input'][-1]['content']))
                active[0] += 1; peak[0] = max(peak[0], active[0])
                try:
                    async for event in chosen(body): yield event
                finally:
                    active[0] -= 1; ends.append(clock.now())
            start = utc_start or datetime(2026, 11, 14, tzinfo=timezone.utc)
            seed = deepcopy(carry) if carry is not None else synthetic_carry(slots)
            before_seed = deepcopy(seed)
            try:
                if before: before(ledger, root, clock)
                with patch.object(j, 'verify_continuation', return_value=seed):
                    summary = asyncio.run(j.run_slots(slots, api_key=KEY, output_dir=root / 'run', ledger=ledger,
                        transport=transport, execution_manifest_path=p, execution_manifest_sha256=sha,
                        _clock=clock.now, _sleep=clock.sleep, _utcnow=lambda: start + timedelta(seconds=clock.now())))
                self.assertEqual(seed, before_seed, 'Runtime mutated authenticated original state')
                rows = lambda name: [json.loads(x) for x in (root / 'run' / name).read_text().splitlines()]
                return {'summary': summary, 'requests': rows('requests.jsonl'), 'responses': rows('responses.jsonl'),
                    'outcomes': rows('slot-outcomes.jsonl'), 'manifest': rows('run.json')[0],
                    'ledger': [json.loads(x) for x in (root / 'budget/ledger.jsonl').read_text().splitlines()],
                    'starts': starts, 'ends': ends, 'peak': peak[0], 'reservations': reservations}
            finally: ledger.close()

    # The same frozen synthetic behavioral tests exercise the unchanged pacing
    # and ordinary-failure policies against the NEW runtime through our helper.
    test_serial_completion_gap = prior_tests.SerialRuntimeTests.test_serial_completion_gap_includes_long_attempts_and_precedes_reserve
    test_early_wake = prior_tests.SerialRuntimeTests.test_early_wake_cannot_shorten_completion_delay
    test_fair_rotation = prior_tests.SerialRuntimeTests.test_fair_ready_rotation_and_model_order
    test_429_same_body = prior_tests.SerialRuntimeTests.test_429_retry_same_body_after_global65_and_no_slot_overtake
    test_larger_retry_after = prior_tests.SerialRuntimeTests.test_large_retry_after_blocks_every_model_and_fixed_floor_repeated
    test_exhausted_retry_continuation = prior_tests.SerialRuntimeTests.test_exhausted429_retains_three_bounds_and_independent_continues
    test_exhausted_retry_cooldown = prior_tests.SerialRuntimeTests.test_exhausted429_still_delays_next_independent_slot
    test_timeout_continuation = prior_tests.SerialRuntimeTests.test_timeout_retained_failure_skips_history_and_continues
    test_header429_body_timeout = prior_tests.SerialRuntimeTests.test_429_header_then_body_timeout_keeps_cooldown_without_retry
    test408_5xx_continuation = prior_tests.SerialRuntimeTests.test408_and5xx_continue_without_retry_or_guessed_usage
    test_auth_protocol_halt = prior_tests.SerialRuntimeTests.test_auth_payment_and_unsafe_protocol_halt
    test_system_halt = prior_tests.SerialRuntimeTests.test_network_error_is_fatal_not_inferred_transient
    test_truncation = prior_tests.SerialRuntimeTests.test_valid_truncation_settles_and_skips_transitive_history
    test_actual_new_history = prior_tests.SerialRuntimeTests.test_actual_history_after_eventual_completion_and_output_only_projection
    test_deadline = prior_tests.SerialRuntimeTests.test_deadline_before_reservation_and_expiry_during_gap
    test_budget = prior_tests.SerialRuntimeTests.test_cap_stop_happens_before_new_reservation

    def test_exact_frozen_parser_body_and_prices_are_reused(self):
        self.assertIs(j.SSEDecoder, h.SSEDecoder); self.assertIs(j.StreamJournal, h.StreamJournal)
        self.assertIs(j.build_body, h.build_body); self.assertIs(j.usage_cost, h.usage_cost)

    def test_real_closed_carry_preserves_seventeen_unknowns(self):
        actual = j.verify_prior_ledger(ROOT / j.BASELINE_LEDGER)
        self.assertEqual(actual['carry_credits'], '47.653269434')
        self.assertEqual(actual['settled_attempts'], 5); self.assertEqual(actual['unknown_model_mismatch_retained'], 1)
        self.assertEqual(actual['cumulative_inherited_unsettled_attempts'], 17)

    def test_real_receipt_excludes_all_six_without_rescuing_original_failure(self):
        slots = json.loads((ROOT / 'data/frontier-v6i-sessions.json').read_text(encoding='utf-8'))
        carry = j.verify_continuation(slots)
        self.assertEqual(len(carry['finals']), 6); self.assertEqual(len(carry['completed']), 5)
        self.assertEqual(len(carry['continuation_slot_ids']), 1794)
        self.assertFalse(set(carry['issued_slot_ids']) & set(carry['continuation_slot_ids']))
        failed = [r for r in carry['finals'].values() if not r['terminal_valid']]
        self.assertEqual(len(failed), 1); self.assertEqual(failed[0]['failure_scope'], 'global')
        self.assertEqual(failed[0]['error'], 'response_model_mismatch'); self.assertEqual(failed[0]['output_text'], '')
        self.assertEqual(len(carry['failed_descendant_slot_ids']), 2)
        slots[0]['input'] += 'changed source'
        with self.assertRaisesRegex(ValueError, 'schedule_changed'): j.verify_continuation(slots)

    def test_carried_success_used_as_actual_history_never_reissued(self):
        old = slot(0); new = slot(1, history_from=['s-0']); new['input'] = 'next event'
        seed = {'s-0': {'slot_id': 's-0', 'terminal_valid': True, 'output_text': 'original actual answer',
            'attempt_id': 'original-attempt', 'failure_scope': None, 'model_outcome': 'completed'}}
        result = self.run_case([old, new], carry=synthetic_carry([old, new], seed))
        self.assertEqual([r['slot_id'] for r in result['requests']], ['s-1'])
        self.assertEqual([r['slot_id'] for r in result['outcomes']], ['s-1'])
        body = result['requests'][0]['request']
        self.assertEqual(body['input'], [{'role': 'user', 'content': 'Source text'}, {'role': 'assistant', 'content': 'original actual answer'}, {'role': 'user', 'content': 'next event'}])
        self.assertEqual(result['requests'][0]['dependency_bindings'][0]['final_attempt_id'], 'original-attempt')
        self.assertEqual(result['summary']['planned'], 1); self.assertEqual(result['summary']['original_planned'], 2)
        self.assertEqual(result['summary']['carried_over_slots'], 1); self.assertEqual(result['summary']['completed'], 1)

    def test_carried_global_failure_propagates_two_skips_without_halting_new_independent_slot(self):
        slots = [slot(0, QWEN), slot(1, QWEN, history_from=['s-0']), slot(2, QWEN, history_from=['s-0', 's-1']), slot(3)]
        seed = {'s-0': {'slot_id': 's-0', 'terminal_valid': False, 'output_text': '', 'attempt_id': 'original-failed',
            'failure_scope': 'global', 'error': 'response_model_mismatch', 'model_outcome': 'operational_failure'}}
        result = self.run_case(slots, carry=synthetic_carry(slots, seed))
        self.assertEqual([r['slot_id'] for r in result['requests']], ['s-3'])
        self.assertEqual(len(result['outcomes']), 3); self.assertEqual(result['summary']['dependency_skips'], 2)
        self.assertEqual(result['summary']['status'], 'completed')
        self.assertEqual(result['summary']['issued_operational_failures'], 0)
        self.assertEqual(result['summary']['budget']['attempt_reservations'], 1)

    def test_only_observed_future_qwen_route_is_accepted_without_rewriting_raw(self):
        def factory(*args):
            def t(body):
                response_body = dict(body); response_body['model'] = ROUTE
                return emit(final(response_body, text='future answer'))
            return t
        result = self.run_case([slot(0, QWEN)], factory)
        row = result['responses'][0]
        self.assertEqual(row['model'], QWEN); self.assertEqual(row['requested_model'], QWEN)
        self.assertEqual(row['returned_model'], ROUTE); self.assertEqual(json.loads(row['raw_response'])['model'], ROUTE)
        self.assertEqual(result['requests'][0]['request']['model'], QWEN)
        self.assertEqual(row['model_identity_policy'], 'prospectively_pinned_observed_route_not_verified_alias')
        self.assertTrue(row['terminal_valid']); self.assertEqual(result['summary']['budget']['settled_attempts'], 1)

    def test_wrong_qwen_and_primary_alias_still_halt_and_retain(self):
        for requested, returned in ((QWEN, QWEN), (QWEN, 'qwen3.5-397b-some-other-route'), (MODEL, ROUTE)):
            with self.subTest(requested=requested, returned=returned):
                def factory(*args):
                    return lambda body: emit(final({**body, 'model': returned}))
                result = self.run_case([slot(0, requested), slot(1, requested)], factory)
                self.assertEqual(len(result['requests']), 1); self.assertEqual(result['summary']['status'], 'stopped')
                self.assertEqual(result['responses'][0]['error'], 'response_model_mismatch')
                self.assertEqual(result['responses'][0]['returned_model'], returned)
                self.assertEqual(result['summary']['budget']['unknown_operational_attempts_retained'], 1)

    def test_first_continuation_honors_previous_process_closure_gap(self):
        slots = [slot()]; carry = synthetic_carry(slots)
        carry['earliest_next_admission_utc'] = '2026-11-14T00:00:04+00:00'
        result = self.run_case(slots, carry=carry)
        self.assertGreaterEqual(result['starts'][0][0], 4)

    def test_manifest_cannot_change_route_or_continuation_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'manifest.json'; slots = [slot()]
            sha = make_manifest(p, slots); j.verify_execution_manifest(p, sha, slots)
            sha = make_manifest(p, slots, observed_response_models={QWEN: QWEN})
            with self.assertRaisesRegex(ValueError, 'continuation_policy'): j.verify_execution_manifest(p, sha, slots)
            sha = make_manifest(p, slots, continuation_sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'continuation_policy'): j.verify_execution_manifest(p, sha, slots)


if __name__ == '__main__': unittest.main()
