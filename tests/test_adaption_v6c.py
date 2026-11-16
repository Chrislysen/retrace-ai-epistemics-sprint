"""Transport/accounting tests use synthetic credentials and fake responses only."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from retrace.adaption_v6c import (
    AiohttpTransport, BASELINE, BASELINE_LEDGER, CAP, ENDPOINT, MODEL_PRICING, DurableJSONL, RollingLedger,
    nano, plan, request_bound, run_slots, usage_cost, validate_slots,
)

ROOT = Path(__file__).resolve().parents[1]
KEY = "synthetic-test-only-credential"
MODELS = list(MODEL_PRICING)


def slot(number=0, model=MODELS[0], **updates):
    result = {"slot_id": f"slot-{number}", "case_id": "case-1", "model": model,
              "condition": "test", "phase": "verdict", "instructions": "Use only supplied source.",
              "input": "A fixed public prompt.", "max_output_tokens": 1024}
    result.update(updates)
    return result


def good(body, text="actual answer", **updates):
    value = {"status": "completed", "model": body["model"], "output_text": text,
             "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                       "output_tokens_details": {"reasoning_tokens": 5}}}
    value.update(updates)
    return 200, json.dumps(value)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def ledger(self):
        result = RollingLedger(self.path / "budget", baseline_path=ROOT / BASELINE_LEDGER)
        self.addCleanup(result.close)
        return result

    def test_full_context_bounds_use_current_prices_and_larger_glm_limit(self):
        self.assertEqual(request_bound("deepseek-v4-flash", 1024), nano("0.04732928"))
        self.assertEqual(request_bound("glm-5.2", 8192), nano("1.50404980"))
        self.assertEqual(usage_cost("gemma-4-31b-it", {"input_tokens": 100, "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 50}, "output_tokens_details": {"reasoning_tokens": 15}}, 1024), nano(".0000158"))

    def test_historical_carry_fixed_and_new_settlement_releases_only_new_bound(self):
        ledger = self.ledger()
        ledger.record({"kind": "reserve", "attempt_id": "a", "bound_nanocredits": nano("2")})
        self.assertEqual(ledger.accounted, nano(BASELINE) + nano(2))
        ledger.record({"kind": "settle", "attempt_id": "a", "accounted_nanocredits": nano(".01")})
        self.assertEqual(ledger.accounted, nano(BASELINE) + nano(".01"))
        before = ledger.last_hash
        ledger.close()
        reopened = self.ledger()
        self.assertEqual(reopened.last_hash, before)
        self.assertEqual(reopened.accounted, nano(BASELINE) + nano(".01"))

    def test_cap_checked_before_every_reservation_and_double_settlement_rejected(self):
        ledger = self.ledger()
        ledger.record({"kind": "reserve", "attempt_id": "a", "bound_nanocredits": CAP-nano(BASELINE)})
        with self.assertRaisesRegex(ValueError, "cap"):
            ledger.record({"kind": "reserve", "attempt_id": "b", "bound_nanocredits": 1})
        self.assertEqual(ledger.accounted, CAP)
        ledger.record({"kind": "settle", "attempt_id": "a", "accounted_nanocredits": 0})
        with self.assertRaisesRegex(ValueError, "double"):
            ledger.record({"kind": "settle", "attempt_id": "a", "accounted_nanocredits": 0})

    def test_exclusive_process_lock_prevents_competing_budget(self):
        self.ledger()
        with self.assertRaises(FileExistsError):
            self.ledger()

    def test_unresolved_crash_reservation_blocks_automatic_resume(self):
        ledger = self.ledger()
        ledger.record({"kind": "reserve", "attempt_id": "a", "bound_nanocredits": 100})
        ledger.close()
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.ledger()

    def test_hash_chain_and_truncation_detect_changes(self):
        ledger = self.ledger()
        ledger.close()
        path = self.path / "budget/ledger.jsonl"
        text = path.read_text()
        path.write_text(text.replace("250", "251"))
        with self.assertRaisesRegex(ValueError, "hash"):
            self.ledger()
        path.write_text(text.rstrip())
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.ledger()

    def test_canary_exactly_two_per_model_and_plan_never_reserves(self):
        slots = [slot(2*i+j, model) for i,model in enumerate(MODELS) for j in range(2)]
        prepared = plan(slots, canary=True)
        self.assertEqual(prepared["planned_slots"], 10)
        self.assertFalse(prepared["reservation_created"])
        with self.assertRaisesRegex(ValueError, "canary"):
            plan(slots[:-1], canary=True)
        with self.assertRaisesRegex(ValueError, "unverified_model"):
            plan([slot(model="glm-53-flash")])

    def test_missing_or_bad_usage_never_estimated_from_text(self):
        for usage in (None, {}, {"input_tokens": True, "output_tokens": 3},
                      {"input_tokens": 1, "output_tokens": 1025},
                      {"input_tokens": 2, "output_tokens": 3, "total_tokens": 9},
                      {"input_tokens": 2, "output_tokens": 3, "output_tokens_details": {"reasoning_tokens": 4}}):
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                usage_cost(MODELS[0], usage, 1024)

    def test_execution_freeze_covers_runtime_and_detects_mutation(self):
        from scripts import run_frontier_v6c as cli
        names = ["sessions.json", "scripts/run_frontier_v6c.py", "retrace/adaption_v6c.py",
                 "data/frontier-v6c-authorization.json", "data/frontier-v6c-model-availability.json"]
        entries = []
        for name in names:
            path = self.path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixed bytes",encoding="utf-8")
            entries.append({"path":name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        frozen = self.path / "freeze.json"
        frozen.write_text(json.dumps({"files":entries}))
        expected = hashlib.sha256(frozen.read_bytes()).hexdigest()
        with patch.object(cli,"ROOT",self.path), patch.object(cli,"__file__",str(self.path/names[1])):
            self.assertEqual(cli.verify_freeze(frozen,expected,self.path/names[0]),5)
            (self.path/names[2]).write_text("modified code")
            with self.assertRaisesRegex(ValueError,"frozen_dependency_changed"):
                cli.verify_freeze(frozen,expected,self.path/names[0])


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.ledger = RollingLedger(self.path / "budget", baseline_path=ROOT / BASELINE_LEDGER)
        self.addCleanup(self.ledger.close)

    async def run_mock(self, slots, transport, **settings):
        return await run_slots(slots, api_key=KEY, output_dir=self.path / "run", ledger=self.ledger,
                               transport=transport, model_interval=0, global_interval=0, **settings)

    def rows(self, name):
        return [json.loads(x) for x in (self.path / "run" / name).read_text().splitlines()]

    async def test_completed_requests_settle_and_do_not_leak_credential(self):
        async def fake(body): return good(body)
        summary = await self.run_mock([slot()], fake)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["budget"]["unsettled_attempts"], 0)
        self.assertEqual(self.ledger.accounted, nano(BASELINE)+usage_cost(MODELS[0], {"input_tokens":100,"output_tokens":20},1024))
        for path in self.path.rglob("*.json*"):
            self.assertNotIn(KEY, path.read_text())
        request = self.rows("requests.jsonl")[0]["request"]
        self.assertFalse(request["store"])
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["tool_choice"], "none")

    async def test_actual_prior_text_replayed_once_and_gold_assistant_input_not_allowed(self):
        bodies = []
        async def fake(body):
            bodies.append(deepcopy(body))
            return good(body, text="model observed " + str(len(bodies)))
        slots = [slot(0), slot(1, input="Withdraw A.", history_from=["slot-0"]),
                 slot(2, input="Restore A.", history_from=["slot-0", "slot-1"])]
        await self.run_mock(slots, fake)
        self.assertEqual([m["content"] for m in bodies[2]["input"]],
                         ["A fixed public prompt.", "model observed 1", "Withdraw A.", "model observed 2", "Restore A."])
        with self.assertRaises(ValueError):
            validate_slots([slot(0, assistant="invented answer")])

    async def test_429_is_terminal_without_retry_and_keeps_full_bound(self):
        calls = []
        async def fake(body):
            calls.append(body)
            return 429, '{"error":"rate limited"}'
        summary = await self.run_mock([slot(0), slot(1), slot(2, MODELS[1])], fake)
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary["stop_reasons"], ["http_429"])
        self.assertEqual(self.ledger.accounted, nano(BASELINE)+request_bound(MODELS[0],1024))
        self.assertEqual(summary["unissued_slot_ids"], ["slot-1", "slot-2"])

    async def test_missing_usage_stops_even_completed_output(self):
        async def fake(body): return good(body, usage=None)
        summary = await self.run_mock([slot(), slot(1)], fake)
        self.assertEqual(summary["stop_reasons"], ["missing_usage"])
        self.assertEqual(summary["issued"], 1)
        self.assertEqual(summary["budget"]["unsettled_attempts"], 1)

    async def test_incomplete_stops_and_does_not_settle_valid_usage(self):
        async def fake(body): return good(body, status="incomplete")
        summary = await self.run_mock([slot(), slot(1)], fake)
        self.assertEqual(summary["stop_reasons"], ["response_not_completed"])
        self.assertEqual(summary["budget"]["settled_attempts"], 0)

    async def test_inflight_other_model_can_finish_after_stop_but_no_new_calls(self):
        calls = []
        async def fake(body):
            calls.append(body["model"])
            if body["model"] == MODELS[0]:
                await asyncio.sleep(.01)
                return 429, "{}"
            await asyncio.sleep(.03)
            return good(body)
        slots = [slot(0), slot(1), slot(2,MODELS[1]), slot(3,MODELS[1]), slot(4,MODELS[2])]
        summary = await self.run_mock(slots, fake, concurrency=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["budget"]["unsettled_attempts"], 1)

    async def test_timeout_has_one_attempt_and_no_exception_text(self):
        async def fake(body): await asyncio.sleep(1)
        summary = await self.run_mock([slot(),slot(1)], fake, timeout_seconds=.01)
        self.assertEqual(summary["stop_reasons"], ["timeout"])
        self.assertEqual(summary["issued"], 1)

    async def test_raw_credential_echo_redacted_and_exception_message_whitelisted(self):
        async def fake(body): return good(body, text=KEY)
        summary = await self.run_mock([slot()], fake)
        self.assertEqual(summary["stop_reasons"], ["credential_echo_detected"])
        for path in self.path.rglob("*.json*"):
            self.assertNotIn(KEY, path.read_text())
        self.assertIn("[REDACTED_CREDENTIAL]", self.rows("responses.jsonl")[0]["raw_response"])

    async def test_transport_exception_does_not_log_arbitrary_details(self):
        async def fake(body): raise ValueError(KEY)
        summary = await self.run_mock([slot()], fake)
        self.assertEqual(summary["stop_reasons"], ["invalid_response"])
        self.assertNotIn(KEY, (self.path / "budget/ledger.jsonl").read_text())

    async def test_response_journal_failure_retains_reserve_and_stops(self):
        async def fake(body): return good(body)
        original = DurableJSONL.write
        def failing(file, value):
            if file.stream.name.endswith("responses.jsonl"):
                raise OSError("synthetic disk fault")
            return original(file, value)
        with patch.object(DurableJSONL, "write", failing):
            summary = await self.run_mock([slot(),slot(1)], fake)
        self.assertEqual(summary["stop_reasons"], ["response_or_settlement_journal_failure"])
        self.assertEqual(summary["issued"], 1)
        self.assertEqual(summary["budget"]["unsettled_attempts"], 1)

    async def test_existing_run_never_overwritten(self):
        async def fake(body): return good(body)
        await self.run_mock([slot()], fake)
        before = (self.path / "run/requests.jsonl").read_bytes()
        with self.assertRaises(FileExistsError):
            await self.run_mock([slot(1)], fake)
        self.assertEqual((self.path / "run/requests.jsonl").read_bytes(), before)

    async def test_per_model_queue_pacing_and_case_order(self):
        starts = []
        async def fake(body):
            starts.append((body["input"][-1]["content"],time.monotonic()))
            return good(body)
        slots = [slot(0,input="first"),slot(1,input="second")]
        await run_slots(slots, api_key=KEY, output_dir=self.path / "run", ledger=self.ledger,
                        transport=fake, model_interval=.025, global_interval=0)
        self.assertEqual([s[0] for s in starts], ["first","second"])
        self.assertGreaterEqual(starts[1][1]-starts[0][1], .020)

    async def test_parent_cancellation_drains_inflight_before_closing_journals(self):
        started = asyncio.Event()
        finished = []
        async def fake(body):
            started.set()
            await asyncio.sleep(.025)
            finished.append(True)
            return good(body)
        task = asyncio.create_task(self.run_mock([slot(),slot(1)], fake))
        await started.wait()
        task.cancel()
        summary = await task
        self.assertEqual(finished, [True])
        self.assertEqual(summary["stop_reasons"], ["run_cancelled"])
        self.assertEqual(summary["issued"], 1)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(len(self.rows("responses.jsonl")), 1)

    async def test_unexpected_dispatch_error_halts_and_awaits_workers(self):
        async def fake(body): return good(body)
        actual = request_bound
        calls = [0]
        def fail_after_plan(model, maximum):
            calls[0] += 1
            if calls[0] > 2:
                raise RuntimeError("sensitive unexpected detail")
            return actual(model, maximum)
        with patch("retrace.adaption_v6c.request_bound", side_effect=fail_after_plan):
            summary = await self.run_mock([slot(),slot(1,MODELS[1])], fake)
        self.assertEqual(summary["issued"], 0)
        self.assertEqual(summary["stop_reasons"], ["unexpected_worker_failure"])
        self.assertNotIn("sensitive", (self.path / "budget/ledger.jsonl").read_text())

    async def test_aiohttp_fixed_endpoint_no_proxy_redirect_or_retry_and_all_chunks(self):
        class Content:
            async def iter_chunked(self, maximum):
                for chunk in (b'{"sta', b'tus":"completed"}'):
                    yield chunk
        response = MagicMock()
        response.status = 200
        response.content = Content()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post.return_value = context
        session.close = AsyncMock()
        session._retry_connection = True
        with patch("aiohttp.ClientSession", return_value=session) as constructor:
            async with AiohttpTransport(KEY) as transport:
                status, raw = await transport({"model":MODELS[0]})
                self.assertEqual(json.loads(raw)["status"], "completed")
                self.assertEqual(status, 200)
            self.assertFalse(constructor.call_args.kwargs["trust_env"])
            self.assertFalse(session._retry_connection)
            self.assertEqual(session.post.call_count, 1)
            self.assertEqual(session.post.call_args.args, (ENDPOINT,))
            self.assertFalse(session.post.call_args.kwargs["allow_redirects"])
            session.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
