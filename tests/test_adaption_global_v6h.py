"""Synthetic pre-admission timing tests; never load credentials or make HTTP calls."""
import ast
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retrace.adaption_global_v6h import run_slots
from retrace.adaption_v6h import BASELINE_LEDGER, PRIMARY_MODELS, RollingLedger
from tests.test_adaption_v6h import KEY, MODEL, slot, emit, final

ROOT = Path(__file__).resolve().parents[1]
OTHER = "deepseek-v4-flash"


class Clock:
    def __init__(self, early_wakes=0):
        self.value = 0.0; self.early_wakes = early_wakes
    def now(self): return self.value
    async def sleep(self, duration):
        if self.early_wakes: self.early_wakes -= 1
        else: self.value += duration
        await asyncio.sleep(0)


class GlobalAdmissionTests(unittest.TestCase):
    def run_case(self, slots, transport_factory=None, *, global_interval=5.0, clock=None, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); clock = clock or Clock(); reservations = []; starts = []; timers = []
            class Ledger(RollingLedger):
                def record(self, event):
                    if event["kind"] == "reserve": reservations.append((clock.now(), event["slot_id"], event["attempt_number"]))
                    super().record(event)
            ledger = Ledger(root / "budget", baseline_path=ROOT / BASELINE_LEDGER)
            real_wait_for = asyncio.wait_for
            async def wait_for(coroutine, timeout):
                timers.append((clock.now(), timeout, len(reservations)))
                return await real_wait_for(coroutine, timeout)
            def default(body): return emit(final(body))
            selected = transport_factory(clock, starts, reservations) if transport_factory else default
            def transport(body):
                starts.append((clock.now(), body["model"]))
                return selected(body)
            try:
                with patch("retrace.adaption_global_v6h.asyncio.wait_for", wait_for):
                    summary = asyncio.run(run_slots(slots, api_key=KEY, output_dir=root / "run", ledger=ledger,
                        transport=transport, global_interval=global_interval, model_interval=kwargs.pop("model_interval", 2.0),
                        concurrency=kwargs.pop("concurrency", 3), per_model_concurrency=kwargs.pop("per_model_concurrency", 3),
                        _clock=clock.now, _sleep=clock.sleep, _jitter=lambda: 0, **kwargs))
                def load_rows(name): return [json.loads(line) for line in (root / "run" / name).read_text().splitlines()]
                return {"summary": summary, "requests": load_rows("requests.jsonl"), "responses": load_rows("responses.jsonl"),
                        "outcomes": load_rows("slot-outcomes.jsonl"), "manifest": load_rows("run.json")[0],
                        "reservations": reservations, "starts": starts, "timers": timers}
            finally: ledger.close()

    def test_global_gate_precedes_reservation_across_models(self):
        result = self.run_case([slot(0), slot(1, OTHER), slot(2)])
        reserved = result["reservations"]
        self.assertEqual(len(reserved), 3)
        self.assertTrue(all(b[0] - a[0] >= 5 for a, b in zip(reserved, reserved[1:])))
        self.assertTrue(all(b[0] - a[0] >= 5 for a, b in zip(result["starts"], result["starts"][1:])))
        self.assertEqual(result["summary"]["global_interval_seconds"], 5)
        self.assertEqual(result["manifest"]["transport_revision"], "pre_admission_global_v6h_v1")

    def test_early_sleep_return_never_licenses_early_admission(self):
        result = self.run_case([slot(0), slot(1, OTHER)], clock=Clock(early_wakes=25))
        self.assertGreaterEqual(result["reservations"][1][0] - result["reservations"][0][0], 5)
        self.assertGreaterEqual(result["starts"][1][0] - result["starts"][0][0], 5)

    def test_per_model_interval_remains_effective_when_larger_than_global(self):
        result = self.run_case([slot(0), slot(1, OTHER), slot(2)], global_interval=0.5, model_interval=2)
        per_model = [time for time, model in result["starts"] if model == MODEL]
        self.assertGreaterEqual(per_model[1] - per_model[0], 2)
        self.assertTrue(all(b[0] - a[0] >= 0.5 for a, b in zip(result["starts"], result["starts"][1:])))

    def test_cooldown_blocks_all_new_reservations_then_spacing_resumes(self):
        def factory(clock, starts, reservations):
            def transport(body):
                return emit(b"{}", 429, "60") if len(starts) == 1 else emit(final(body))
            return transport
        result = self.run_case([slot(0), slot(1, OTHER), slot(2)], factory)
        self.assertGreaterEqual(result["reservations"][1][0] - result["starts"][0][0], 60)
        self.assertTrue(all(b[0] - a[0] >= 5 for a, b in zip(result["reservations"][1:], result["reservations"][2:])))
        self.assertEqual(result["summary"]["retries"], 1)
        self.assertEqual(result["summary"]["first_attempt_completed"], 2)
        self.assertEqual(result["summary"]["eventual_completed"], 3)
        self.assertEqual(result["summary"]["budget"]["unknown_429_attempts_retained"], 1)

    def test_timeout_is_created_after_admission_with_full_180_seconds(self):
        result = self.run_case([slot(i, MODEL if i % 2 else OTHER) for i in range(5)], global_interval=21)
        self.assertEqual(len(result["timers"]), 5)
        for index, (started, timeout, reserved_count) in enumerate(result["timers"]):
            self.assertEqual(timeout, 180)
            self.assertEqual(reserved_count, index + 1)
            self.assertGreaterEqual(started, result["reservations"][index][0])
            self.assertLess(started - result["reservations"][index][0], 1)
        self.assertGreaterEqual(result["timers"][-1][0], 84)

    def test_up_to_three_long_requests_remain_concurrent_without_start_burst(self):
        entered = [0]; peak = [0]; inflight = [0]
        def factory(clock, starts, reservations):
            gate = None
            async def transport(body):
                nonlocal gate
                if gate is None: gate = asyncio.Event()
                entered[0] += 1; inflight[0] += 1; peak[0] = max(peak[0], inflight[0])
                if entered[0] == 3: gate.set()
                await gate.wait()
                async for chunk in emit(final(body)): yield chunk
                inflight[0] -= 1
            return transport
        result = self.run_case([slot(i, MODEL if i % 2 else OTHER) for i in range(6)], factory)
        self.assertEqual(peak[0], 3)
        self.assertEqual(result["summary"]["completed"], 6)
        self.assertTrue(all(b[0] - a[0] >= 5 for a, b in zip(result["starts"], result["starts"][1:])))

    def test_model_major_input_gets_ready_round_robin_with_heterogeneous_durations(self):
        slots = [slot(i * 3 + j, model) for i, model in enumerate(PRIMARY_MODELS) for j in range(3)]
        def factory(clock, starts, reservations):
            async def transport(body):
                # One slow model must not let a fast early model monopolize
                # the spare global slot before the remaining ready models run.
                end = clock.now() + (4.0 if body["model"] == PRIMARY_MODELS[1] else 0.2)
                while clock.now() < end: await asyncio.sleep(0)
                async for chunk in emit(final(body)): yield chunk
            return transport
        result = self.run_case(slots, factory, global_interval=0.5, concurrency=2, per_model_concurrency=1)
        self.assertEqual([model for _, model in result["starts"][:5]], list(PRIMARY_MODELS))
        for i, model in enumerate(PRIMARY_MODELS):
            ids = [r["slot_id"] for r in result["requests"] if r["request"]["model"] == model]
            self.assertEqual(ids, [f"s-{i * 3 + j}" for j in range(3)])
        self.assertEqual(result["summary"]["completed"], 15)
        self.assertIn("round_robin", result["manifest"]["ready_model_order"])

    def test_exhausted_429_keeps_every_attempt_and_all_final_slots(self):
        result = self.run_case([slot(0)], lambda *_: lambda body: emit(b"{}", 429, "60"))
        self.assertEqual(len(result["requests"]), 3)
        self.assertEqual(len(result["responses"]), 3)
        self.assertEqual(result["outcomes"][0]["model_outcome"], "http_429")
        self.assertEqual(result["summary"]["budget"]["unsettled_attempts"], 3)
        self.assertEqual(result["summary"]["slot_outcomes"], 1)

    def test_truncation_and_dependencies_keep_frozen_semantics(self):
        result = self.run_case([slot(0), slot(1, history_from=["s-0"]), slot(2, OTHER)],
            lambda *_: lambda body: emit(final(body, truncated=True)))
        self.assertEqual(result["summary"]["dependency_skips"], 1)
        self.assertEqual(result["summary"]["truncated"], 2)
        self.assertEqual(result["summary"]["retries"], 0)
        self.assertEqual(result["summary"]["slot_outcomes"], 3)

    def test_network_failure_stops_unissued_slots_without_retry(self):
        def factory(*_):
            async def transport(body):
                raise RuntimeError("synthetic transport failure")
                yield b""
            return transport
        result = self.run_case([slot(0), slot(1, OTHER)], factory)
        self.assertEqual(result["summary"]["status"], "stopped")
        self.assertEqual(len(result["requests"]), 1)
        self.assertEqual(result["summary"]["slot_outcomes"], 2)
        self.assertEqual(result["summary"]["retries"], 0)

    def test_invalid_interval_rejects_before_output_or_reservation(self):
        for value in (None, True, 0, 0.49, 60.01, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "invalid_global_interval"):
                    self.run_case([slot(0)], global_interval=value)

    def test_nested_retry_and_finalization_bodies_unchanged_from_frozen_h(self):
        def nested(path):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            main = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_slots")
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.walk(main)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        original = nested(ROOT / "retrace/adaption_v6h.py")
        revised = nested(ROOT / "retrace/adaption_global_v6h.py")
        for name in ("attempt", "guarded_attempt", "finalize", "skipped", "stop", "check_stop_file", "observe_headers"):
            self.assertEqual(revised[name], original[name], name)


if __name__ == "__main__": unittest.main()
