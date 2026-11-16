"""Offline serial-policy tests. No credentials, provider, or historical edits."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from retrace.adaption_v6i import (BASELINE, BASELINE_LEDGER, CAP, DEADLINE,
    RUNTIME_CONFIG, RollingLedger, digest, nano, request_bound, retry_delay,
    run_slots, verify_execution_manifest, verify_prior_ledger)
from tests.test_adaption_v6h import KEY, MODEL, emit, final, slot

ROOT = Path(__file__).resolve().parents[1]
OTHER = "deepseek-v4-flash"


class Clock:
    def __init__(self, early_wakes=0): self.value = 0.0; self.early_wakes = early_wakes
    def now(self): return self.value
    async def sleep(self, seconds):
        if self.early_wakes: self.early_wakes -= 1
        else: self.value += seconds
        await asyncio.sleep(0)


def manifest(path, slots, **overrides):
    value = {"sessions_sha256": digest(slots), "runtime_config": RUNTIME_CONFIG,
        "deadline_utc": DEADLINE.isoformat(), **overrides}
    raw = json.dumps(value).encode(); path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class SerialRuntimeTests(unittest.TestCase):
    def run_case(self, slots, factory=None, *, clock=None, utc_start=None, before=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); clock = clock or Clock(); starts = []; ends = []; reservations = []
            class Ledger(RollingLedger):
                def record(self, event):
                    if event["kind"] == "reserve": reservations.append((clock.now(), event["slot_id"]))
                    super().record(event)
            ledger = Ledger(root / "budget", baseline_path=ROOT / BASELINE_LEDGER)
            p = root / "execution.json"; sha = manifest(p, slots)
            chosen = factory(clock, starts, ends) if factory else lambda body: emit(final(body))
            active = [0]; peak = [0]
            async def transport(body):
                starts.append((clock.now(), body["model"], body["input"][-1]["content"]))
                active[0] += 1; peak[0] = max(peak[0], active[0])
                try:
                    async for event in chosen(body): yield event
                finally:
                    active[0] -= 1; ends.append(clock.now())
            start = utc_start or datetime(2026, 11, 14, tzinfo=timezone.utc)
            try:
                if before: before(ledger, root, clock)
                summary = asyncio.run(run_slots(slots, api_key=KEY, output_dir=root / "run", ledger=ledger,
                    transport=transport, execution_manifest_path=p, execution_manifest_sha256=sha,
                    _clock=clock.now, _sleep=clock.sleep, _utcnow=lambda: start + timedelta(seconds=clock.now())))
                rows = lambda name: [json.loads(x) for x in (root / "run" / name).read_text().splitlines()]
                return {"summary": summary, "requests": rows("requests.jsonl"), "responses": rows("responses.jsonl"),
                    "outcomes": rows("slot-outcomes.jsonl"), "manifest": rows("run.json")[0],
                    "ledger": [json.loads(x) for x in (root / "budget" / "ledger.jsonl").read_text().splitlines()],
                    "starts": starts, "ends": ends, "peak": peak[0], "reservations": reservations}
            finally: ledger.close()

    def test_carry_all_old_unknowns_and_closed_halt_without_release(self):
        v = verify_prior_ledger(ROOT / BASELINE_LEDGER)
        self.assertEqual(v["carry_credits"], "47.409962587")
        self.assertEqual(v["unknown_429_retained"], 8); self.assertEqual(v["unknown_timeout_retained"], 1)
        self.assertEqual(v["cumulative_inherited_unsettled_attempts"], 16)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RollingLedger(Path(tmp), baseline_path=ROOT / BASELINE_LEDGER)
            try:
                self.assertEqual(ledger.snapshot()["accounted_credits"], BASELINE)
                self.assertEqual(ledger.snapshot()["historical_carry_credits"], BASELINE)
            finally: ledger.close()

    def test_serial_completion_gap_includes_long_attempts_and_precedes_reserve(self):
        def factory(clock, starts, ends):
            async def t(body):
                clock.value += 23
                async for event in emit(final(body)): yield event
            return t
        result = self.run_case([slot(0), slot(1, OTHER), slot(2)], factory)
        self.assertEqual(result["peak"], 1)
        self.assertEqual([x[0] for x in result["starts"]], [0, 27, 54])
        for start, end in zip(result["starts"][1:], result["ends"]): self.assertGreaterEqual(start[0] - end, 4)
        self.assertEqual([x[0] for x in result["reservations"]], [x[0] for x in result["starts"]])

    def test_early_wake_cannot_shorten_completion_delay(self):
        result = self.run_case([slot(0), slot(1)], clock=Clock(early_wakes=50))
        self.assertGreaterEqual(result["starts"][1][0] - result["ends"][0], 4)

    def test_fair_ready_rotation_and_model_order(self):
        slots = [slot(0), slot(1), slot(2, OTHER), slot(3, OTHER)]
        result = self.run_case(slots)
        self.assertEqual([r["slot_id"] for r in result["requests"]], ["s-0", "s-2", "s-1", "s-3"])

    def test_429_retry_same_body_after_global65_and_no_slot_overtake(self):
        def factory(clock, starts, ends):
            return lambda b: emit(b'{}', 429, '2') if len(starts) == 1 else emit(final(b))
        result = self.run_case([slot(0), slot(1)], factory)
        self.assertEqual([r["slot_id"] for r in result["requests"]], ["s-0", "s-0", "s-1"])
        self.assertGreaterEqual(result["starts"][1][0] - result["ends"][0], 65)
        self.assertEqual(result["requests"][0]["request"], result["requests"][1]["request"])
        self.assertNotEqual(result["requests"][0]["attempt_id"], result["requests"][1]["attempt_id"])
        self.assertEqual(result["summary"]["first_attempt_completed"], 1)
        self.assertEqual(result["summary"]["eventual_completed"], 2)

    def test_large_retry_after_blocks_every_model_and_fixed_floor_repeated(self):
        def factory(clock, starts, ends):
            return lambda b: emit(b'{}', 429, '95') if len(starts) == 1 else emit(final(b))
        result = self.run_case([slot(0), slot(1, OTHER)], factory)
        self.assertGreaterEqual(result["starts"][1][0] - result["ends"][0], 95)
        self.assertEqual([x[1] for x in result["starts"]], [MODEL, OTHER, MODEL])
        self.assertEqual(retry_delay('Wed, 21 Oct 2015 07:30:00 GMT', utc_now=datetime(2015, 10, 21, 7, 28, tzinfo=timezone.utc)), 120)
        self.assertEqual(retry_delay('bad'), 65)

    def test_exhausted429_retains_three_bounds_and_independent_continues(self):
        def factory(clock, starts, ends):
            return lambda b: emit(b'{}', 429, '60') if b['model'] == MODEL else emit(final(b))
        result = self.run_case([slot(0), slot(1, OTHER), slot(2, OTHER)], factory)
        a = [r for r in result["responses"] if r['model'] == MODEL]
        self.assertEqual(len(a), 3); self.assertEqual(result['summary']['status'], 'completed')
        self.assertEqual(result['summary']['eventual_completed'], 2)
        self.assertEqual(result['summary']['budget']['unknown_429_attempts_retained'], 3)
        for i, response in enumerate(result['responses'][:-1]):
            if response['http_status'] == 429: self.assertGreaterEqual(result['starts'][i + 1][0] - result['ends'][i], 65)

    def test_timeout_retained_failure_skips_history_and_continues(self):
        def factory(clock, starts, ends):
            async def t(body):
                if len(starts) == 1:
                    clock.value += 180
                    raise asyncio.TimeoutError()
                async for event in emit(final(body)): yield event
            return t
        result = self.run_case([slot(0), slot(1, history_from=['s-0']), slot(2)], factory)
        self.assertEqual([r['slot_id'] for r in result['requests']], ['s-0', 's-2'])
        self.assertEqual(result['summary']['status'], 'completed')
        self.assertEqual(result['summary']['dependency_skips'], 1)
        self.assertEqual(result['responses'][0]['failure_scope'], 'slot')
        self.assertIsNone(result['responses'][0]['settled_credits'])
        self.assertEqual(result['summary']['budget']['unknown_operational_attempts_retained'], 1)
        self.assertGreaterEqual(result['starts'][1][0], 184)
        self.assertFalse(result['summary']['budget']['halted'])

    def test_exhausted429_still_delays_next_independent_slot(self):
        first = slot(0); second = slot(1); second['input'] = 'independent second'
        def factory(clock, starts, ends):
            return lambda b: emit(b'{}', 429, '60') if b['input'][-1]['content'] == 'Source text' else emit(final(b))
        result = self.run_case([first, second], factory)
        self.assertEqual([r['attempt_number'] for r in result['responses']], [1, 2, 3, 1])
        self.assertGreaterEqual(result['starts'][3][0] - result['ends'][2], 65)
        self.assertEqual(result['summary']['eventual_completed'], 1)

    def test_429_header_then_body_timeout_keeps_cooldown_without_retry(self):
        def factory(clock, starts, ends):
            async def t(body):
                if len(starts) == 1:
                    yield {'http_status': 429, 'content_type': 'application/json', 'retry_after': '90'}
                    raise asyncio.TimeoutError()
                async for item in emit(final(body)): yield item
            return t
        result = self.run_case([slot(0), slot(1)], factory)
        self.assertEqual(result['responses'][0]['error'], 'timeout')
        self.assertEqual(result['summary']['retries'], 0)
        self.assertEqual(result['summary']['http_429_attempts'], 0)
        self.assertGreaterEqual(result['starts'][1][0] - result['ends'][0], 90)

    def test408_and5xx_continue_without_retry_or_guessed_usage(self):
        for code in (408, 500, 503):
            with self.subTest(code=code):
                def factory(clock, starts, ends):
                    return lambda b: emit(b'{"error":"provider failure"}', code) if len(starts) == 1 else emit(final(b))
                result = self.run_case([slot(0), slot(1)], factory)
                self.assertEqual(result['summary']['status'], 'completed'); self.assertEqual(result['summary']['retries'], 0)
                self.assertEqual(result['summary']['eventual_completed'], 1); self.assertIsNone(result['responses'][0]['usage'])
                self.assertEqual(result['responses'][0]['failure_scope'], 'slot')

    def test_auth_payment_and_unsafe_protocol_halt(self):
        for code in (401, 402, 403):
            with self.subTest(code=code):
                result = self.run_case([slot(0), slot(1)], lambda *args: lambda b: emit(b'{}', code))
                self.assertEqual(result['summary']['status'], 'stopped'); self.assertEqual(len(result['requests']), 1)
                self.assertEqual(result['responses'][0]['failure_scope'], 'global')
                self.assertTrue(result['summary']['budget']['halted'])
        result = self.run_case([slot(0), slot(1)], lambda *args: lambda b: emit(final(b, usage=False)))
        self.assertEqual(result['responses'][0]['error'], 'missing_usage'); self.assertEqual(len(result['requests']), 1)

    def test_network_error_is_fatal_not_inferred_transient(self):
        async def bad(body):
            raise RuntimeError('arbitrary transport text must not leak')
            yield b''
        result = self.run_case([slot(0), slot(1)], lambda *args: bad)
        self.assertEqual(result['summary']['status'], 'stopped')
        self.assertEqual(result['responses'][0]['error'], 'network_or_transport_failure')

    def test_valid_truncation_settles_and_skips_transitive_history(self):
        result = self.run_case([slot(0), slot(1, history_from=['s-0']), slot(2, history_from=['s-1']), slot(3)], lambda *args: lambda b: emit(final(b, truncated=True)))
        self.assertEqual(result['summary']['dependency_skips'], 2); self.assertEqual(result['summary']['retries'], 0)
        self.assertEqual(result['summary']['budget']['settled_attempts'], 2)
        self.assertEqual(result['summary']['status'], 'completed')

    def test_actual_history_after_eventual_completion_and_output_only_projection(self):
        a = slot(0); b = slot(1, history_from=['s-0']); b['input'] = 'actual event'
        c = slot(2); c['input'] = ''; c['input_from'] = {'slot_id': 's-1', 'mode': 'assistant_output_only'}
        result = self.run_case([a, b, c], lambda *args: lambda body: emit(final(body, text=body['input'][-1]['content'] + ' RESPONSE')))
        self.assertEqual(result['requests'][1]['request']['input'], [{'role': 'user', 'content': 'Source text'}, {'role': 'assistant', 'content': 'Source text RESPONSE'}, {'role': 'user', 'content': 'actual event'}])
        self.assertEqual(result['requests'][2]['request']['input'], [{'role': 'user', 'content': 'actual event RESPONSE'}])
        self.assertEqual(len(result['requests'][2]['dependency_bindings']), 1)

    def test_deadline_before_reservation_and_expiry_during_gap(self):
        result = self.run_case([slot(0)], utc_start=DEADLINE)
        self.assertEqual(len(result['requests']), 0); self.assertEqual(result['summary']['stop_reasons'], ['administrative_deadline'])
        result = self.run_case([slot(0), slot(1)], utc_start=DEADLINE - timedelta(seconds=2))
        self.assertEqual(len(result['requests']), 1); self.assertEqual(result['summary']['stop_reasons'], ['administrative_deadline'])

    def test_manifest_mismatch_before_output_or_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'manifest.json'; slots = [slot()]
            sha = manifest(p, slots)
            verify_execution_manifest(p, sha, slots)
            with self.assertRaisesRegex(ValueError, 'sessions'): verify_execution_manifest(p, sha, [slot(9)])
            changed = dict(RUNTIME_CONFIG); changed['global_concurrency'] = 2
            sha = manifest(p, slots, runtime_config=changed)
            with self.assertRaisesRegex(ValueError, 'policy'): verify_execution_manifest(p, sha, slots)
            p.write_bytes(p.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'hash'): verify_execution_manifest(p, sha, slots)

    def test_retained_failure_cannot_later_be_settled_or_double_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RollingLedger(Path(tmp), baseline_path=ROOT / BASELINE_LEDGER)
            try:
                ledger.record({'kind': 'reserve', 'attempt_id': 'x', 'bound_nanocredits': 100})
                ledger.record({'kind': 'retain_unknown', 'attempt_id': 'x', 'reason': 'timeout', 'response_sha256': 'a' * 64})
                before = ledger.snapshot()
                with self.assertRaises(ValueError): ledger.record({'kind': 'settle', 'attempt_id': 'x', 'accounted_nanocredits': 0})
                with self.assertRaises(ValueError): ledger.record({'kind': 'retain_429', 'attempt_id': 'x'})
                self.assertEqual(before, ledger.snapshot())
            finally: ledger.close()

    def test_cap_stop_happens_before_new_reservation(self):
        def before(ledger, root, clock):
            ledger.record({'kind': 'reserve', 'attempt_id': 'synthetic-existing', 'slot_id': 'synthetic-existing', 'bound_nanocredits': CAP - ledger.accounted - 1})
            ledger.record({'kind': 'retain_unknown', 'attempt_id': 'synthetic-existing', 'reason': 'synthetic timeout', 'response_sha256': 'a' * 64})
        result = self.run_case([slot()], before=before)
        self.assertEqual(result['summary']['issued_attempts'], 0); self.assertEqual(result['summary']['stop_reasons'], ['cumulative_budget_stop'])

    def test_closed_ledger_reopen_preserves_retained_unknown_balance(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RollingLedger(Path(tmp), baseline_path=ROOT / BASELINE_LEDGER)
            ledger.record({'kind': 'reserve', 'attempt_id': 'x', 'bound_nanocredits': 12345})
            ledger.record({'kind': 'retain_unknown', 'attempt_id': 'x', 'reason': 'timeout', 'response_sha256': 'a' * 64})
            ledger.record({'kind': 'run_closed', 'run_id': 'synthetic', 'status': 'completed'})
            before = ledger.snapshot(); ledger.close()
            reopened = RollingLedger(Path(tmp), baseline_path=ROOT / BASELINE_LEDGER)
            try:
                self.assertEqual(reopened.snapshot(), before)
                self.assertEqual(reopened.accounted, nano(BASELINE) + 12345)
            finally: reopened.close()


if __name__ == '__main__': unittest.main()
