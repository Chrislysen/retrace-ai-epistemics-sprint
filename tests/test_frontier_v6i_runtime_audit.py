"""Constructed closed journals only; no provider access or live-run reads."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import audit_frontier_v6i_runtime as audit
from retrace.adaption_v6i import BASELINE_LEDGER, DEADLINE, RollingLedger, run_slots
from tests.test_adaption_v6h import KEY, MODEL, emit, final, slot
from tests.test_adaption_v6i import Clock, manifest

ROOT = Path(__file__).resolve().parents[1]
OTHER = "deepseek-v4-flash"


def captured(slots, factory=None, *, deadline=False):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); clock = Clock(); calls = []
        ledger = RollingLedger(root/"budget", baseline_path=ROOT/BASELINE_LEDGER)
        p = root/"execution.json"; sha = manifest(p, slots)
        chosen = factory(clock, calls) if factory else lambda body: emit(final(body))
        async def transport(body):
            calls.append(body)
            async for item in chosen(body): yield item
        start = DEADLINE if deadline else datetime(2026, 11, 14, tzinfo=timezone.utc)
        try:
            summary = asyncio.run(run_slots(slots, api_key=KEY, output_dir=root/"run", ledger=ledger,
                transport=transport, execution_manifest_path=p, execution_manifest_sha256=sha,
                _clock=clock.now, _sleep=clock.sleep, _utcnow=lambda: start+timedelta(seconds=clock.now())))
        finally: ledger.close()
        read = lambda name: audit.jsonl((root/"run"/name).read_bytes())
        streams = {p.name: p.read_bytes() for p in (root/"run/streams").glob("*.sse")}
        return {"slots": deepcopy(slots), "manifest": read("run.json")[0], "requests": read("requests.jsonl"),
                "responses": read("responses.jsonl"), "finals": read("slot-outcomes.jsonl"), "summary": summary,
                "ledger": audit.jsonl((root/"budget/ledger.jsonl").read_bytes()), "streams": streams}


def replay(value, **kwargs):
    return audit.audit_evidence(**{k: v for k, v in value.items() if k != "streams"},
                                read_stream=lambda name: value["streams"][name], allow_test_hooks=True, **kwargs)


class RuntimeAuditTests(unittest.TestCase):
    def test_prior95_entry_replay_and_decimal_qwen_price(self):
        result = audit.replay_prior((ROOT/BASELINE_LEDGER).read_bytes())
        self.assertEqual(result["carry_credits"], "47.409962587")
        self.assertEqual((result["settled"], result["retained_429"], result["retained_timeout"]), (33, 8, 1))
        self.assertEqual(audit.bound({"model": "qwen3.5-397b", "max_output_tokens": 16384}), 129433600)
        with self.assertRaisesRegex(ValueError, "snapshot hash"):
            audit.replay_prior((ROOT/BASELINE_LEDGER).read_bytes()+b" ")

    def test_successful_serial_history_and_output_only_dependency(self):
        a, b, c = slot(0), slot(1, history_from=["s-0"]), slot(2)
        b["input"] = "actual event"; c.update(input="", input_from={"slot_id": "s-1", "mode": "assistant_output_only"})
        data = captured([a, b, c]); result = replay(data)
        self.assertTrue(result["passed"] and result["final_closed"] and result["all_scheduled_outcomes_accounted"])
        self.assertEqual(result["counts"]["planned"], 3)
        self.assertEqual(result["counts"]["eventual_completed"], 3)
        self.assertGreaterEqual(result["minimum_completion_gap_seconds"], 4)
        self.assertEqual(result["observed_peak_transports"], 1)

    def test_explicit429_body_retained_and_eventual_completion_separate(self):
        def factory(clock, calls):
            return lambda b: emit(b'{"error":"rate limit"}', 429, "75") if len(calls) == 1 else emit(final(b))
        data = captured([slot(0), slot(1, OTHER)], factory); result = replay(data)
        self.assertEqual(result["counts"]["retries"], 1)
        self.assertEqual(result["counts"]["first_attempt_completed"], 1)
        self.assertEqual(result["counts"]["eventual_completed"], 2)
        self.assertEqual(result["raw_stream_counts"]["http_429"], 1)
        self.assertGreaterEqual(result["minimum_cooldown_margin_seconds"], 0)
        self.assertGreater(audit.nano(result["retained_run_bounds_credits"]), 0)

    def test_exhausted429_still_cools_before_later_independent_request(self):
        def factory(clock, calls):
            return lambda b: emit(b"{}", 429, "1") if b["model"] == MODEL else emit(final(b))
        data = captured([slot(0)]+[slot(i, OTHER) for i in range(1, 5)], factory)
        result = replay(data)
        self.assertEqual(result["counts"]["http_429_attempts"], 3)
        self.assertEqual(result["schedule_status"], "completed")
        failed = [i for i, r in enumerate(data["responses"]) if r["http_status"] == 429][-1]
        self.assertLess(failed+1, len(data["requests"]))
        q = data["requests"][failed+1]
        q["admitted_monotonic"] = q["previous_attempt_finished_monotonic"] + 64.9
        with self.assertRaisesRegex(ValueError, "gap/cooldown"): replay(data)

    def test_partial_timeout_preserves_bytes_skips_dependency_continues(self):
        def factory(clock, calls):
            async def t(body):
                if len(calls) == 1:
                    yield {"http_status": 200, "content_type": "text/event-stream", "retry_after": None}
                    yield b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
                    clock.value += 180
                    raise asyncio.TimeoutError()
                async for item in emit(final(body)): yield item
            return t
        data = captured([slot(0), slot(1, history_from=["s-0"]), slot(2)], factory)
        result = replay(data)
        self.assertEqual(result["counts"]["dependency_skips"], 1)
        self.assertEqual(result["counts"]["eventual_completed"], 1)
        self.assertEqual(result["counts"]["per_slot_operational_failures"], 1)
        self.assertEqual(data["responses"][0]["output_text"], "")
        self.assertTrue(any(b"partial" in raw for raw in data["streams"].values()))

    def test_503_failure_and_explicit_usage429_have_distinct_accounting(self):
        def factory(clock, calls):
            def choose(body):
                if len(calls) == 1: return emit(b'{"error":"unavailable"}', 503)
                if len(calls) == 2:
                    return emit(json.dumps({"model": body["model"], "usage": {"input_tokens": 2, "output_tokens": 0}}).encode(), 429, "65")
                return emit(final(body))
            return choose
        data = captured([slot(0), slot(1)], factory); result = replay(data)
        self.assertEqual(result["counts"]["per_slot_operational_failures"], 1)
        self.assertEqual(result["counts"]["http_429_attempts"], 1)
        self.assertIsNotNone(data["responses"][1]["settled_credits"])
        self.assertIsNone(data["responses"][0]["settled_credits"])

    def test_stopped_deadline_is_closed_not_successfully_completed(self):
        data = captured([slot(0)], deadline=True); result = replay(data)
        self.assertEqual(result["schedule_status"], "stopped")
        self.assertEqual(result["counts"]["issued_attempts"], 0)
        self.assertEqual(result["counts"]["planned"], 1)

    def test_raw_stream_mutation_rejected(self):
        data = captured([slot(0)]); name = next(iter(data["streams"]))
        data["streams"][name] += b" "
        with self.assertRaisesRegex(ValueError, "capture length"): replay(data)

    def test_changed_returned_text_not_rescued_by_final_copy(self):
        data = captured([slot(0)])
        data["responses"][0]["output_text"] = "invented replacement"
        data["finals"][0]["output_text"] = "invented replacement"
        with self.assertRaisesRegex(ValueError, "output binding"): replay(data)

    def test_three_point_nine_second_gap_is_not_accepted(self):
        data = captured([slot(0), slot(1)])
        q = data["requests"][1]
        q["admitted_monotonic"] = q["previous_attempt_finished_monotonic"] + 3.9
        with self.assertRaisesRegex(ValueError, "gap/cooldown"): replay(data)

    def test_retyped_dependency_text_cannot_pass_even_with_new_body_hash(self):
        data = captured([slot(0), slot(1, history_from=["s-0"])])
        q = data["requests"][1]; q["request"]["input"][1]["content"] = "reference substitution"
        q["request_sha256"] = audit.digest(q["request"])
        with self.assertRaisesRegex(ValueError, "source/history/projection"): replay(data)

    def test_no_timeout_retry_even_with429_status_seen(self):
        def factory(clock, calls):
            return lambda b: emit(b"{}", 429, "65") if len(calls) == 1 else emit(final(b))
        data = captured([slot(0)], factory)
        data["responses"][0].update(error="timeout", model_outcome="operational_failure", failure_scope="slot")
        with self.assertRaisesRegex(ValueError, "no non429 retry|fair ready-model"): replay(data)

    def test_missing_final_and_dishonest_summary_reject(self):
        data = captured([slot(0), slot(1)])
        missing = deepcopy(data); missing["finals"].pop()
        with self.assertRaisesRegex(ValueError, "all planned final"): replay(missing)
        data["summary"]["first_attempt_completed"] = 999
        with self.assertRaisesRegex(ValueError, "denominator counts"): replay(data)

    def test_retained_unknown_cannot_be_released_by_zero_settlement(self):
        data = captured([slot(0)], lambda clock, calls: lambda b: emit(b"{}", 503))
        for row in data["ledger"]:
            if row["event"]["kind"] == "retain_unknown":
                row["event"].update(kind="settle", accounted_nanocredits=0)
        chain = "0"*64
        for row in data["ledger"]:
            row["previous_sha256"] = chain
            row["sha256"] = audit.digest({k: v for k, v in row.items() if k != "sha256"}); chain = row["sha256"]
        with self.assertRaisesRegex(ValueError, "exact settlement"): replay(data)

    def test_global_auth_failure_retained_and_remaining_slots_unissued(self):
        data = captured([slot(0), slot(1)], lambda clock, calls: lambda b: emit(b"{}", 401))
        result = replay(data)
        self.assertEqual(result["schedule_status"], "stopped")
        self.assertEqual(result["counts"]["issued_attempts"], 1)
        self.assertEqual(result["counts"]["eventual_completed"], 0)

    def test_global_failure_cannot_hide_behind_rehashed_completed_ledger(self):
        data = captured([slot(0), slot(1)], lambda clock, calls: lambda b: emit(b"{}", 401))
        data["ledger"] = [r for r in data["ledger"] if r["event"]["kind"] != "halt"]
        data["ledger"][-1]["event"]["status"] = "completed"
        chain = "0"*64
        for n, row in enumerate(data["ledger"], 1):
            row.update(seq=n, previous_sha256=chain)
            row["sha256"] = audit.digest({k: v for k, v in row.items() if k != "sha256"}); chain = row["sha256"]
        data["summary"].update(status="completed", stop_reasons=[])
        data["summary"]["budget"].update(halted=False, ledger_sha256=chain)
        with self.assertRaisesRegex(ValueError, "global failure requires its recorded halt|completed schedule leaves"): replay(data)

    def test_unissued_global_stop_cannot_be_forged_as_completed_no_request_run(self):
        data = captured([slot(0)], deadline=True)
        data["ledger"] = [r for r in data["ledger"] if r["event"]["kind"] != "halt"]
        data["ledger"][-1]["event"]["status"] = "completed"
        chain = "0"*64
        for n, row in enumerate(data["ledger"], 1):
            row.update(seq=n, previous_sha256=chain)
            row["sha256"] = audit.digest({k: v for k, v in row.items() if k != "sha256"}); chain = row["sha256"]
        data["summary"].update(status="completed", stop_reasons=[])
        data["summary"]["budget"].update(halted=False, ledger_sha256=chain)
        with self.assertRaisesRegex(ValueError, "global-stop outcome requires|completed schedule leaves"): replay(data)

    def test_fully_rehashed_serial_run_still_must_follow_ready_model_rotation(self):
        data = captured([slot(0), slot(1), slot(2, OTHER), slot(3, OTHER)])
        data["requests"].sort(key=lambda q: q["slot_id"])
        by_attempt = {r["attempt_id"]: r for r in data["responses"]}
        data["responses"] = [by_attempt[q["attempt_id"]] for q in data["requests"]]
        base = audit.stamp(data["manifest"]["created_at"])+timedelta(seconds=1)
        reserve = {r["event"]["attempt_id"]: r for r in data["ledger"] if r["event"]["kind"] == "reserve"}
        settle = {r["event"]["attempt_id"]: r for r in data["ledger"] if r["event"]["kind"] == "settle"}
        pairs = []
        for i, (q, r) in enumerate(zip(data["requests"], data["responses"])):
            q.update(admitted_monotonic=i*5, previous_attempt_finished_monotonic=None if i == 0 else (i-1)*5+.3,
                     at=(base+timedelta(seconds=i*5)).isoformat())
            r.update(attempt_started_monotonic=i*5, transport_finished_monotonic=i*5+.25, latency_ms=250,
                     at=(base+timedelta(seconds=i*5+.25)).isoformat())
            next(f for f in data["finals"] if f["slot_id"] == q["slot_id"]).update(r)
            a, b = reserve[q["attempt_id"]], settle[q["attempt_id"]]
            a["at"] = q["at"]; b["at"] = r["at"]; b["event"]["response_sha256"] = audit.digest(r)
            pairs.extend((a, b))
        data["ledger"] = data["ledger"][:2] + pairs + data["ledger"][-1:]
        chain = "0"*64
        for n, row in enumerate(data["ledger"], 1):
            row.update(seq=n, previous_sha256=chain)
            row["sha256"] = audit.digest({k: v for k, v in row.items() if k != "sha256"}); chain = row["sha256"]
        data["summary"]["budget"]["ledger_sha256"] = chain
        with self.assertRaisesRegex(ValueError, "fair ready-model"): replay(data)

    def test_slot_failure_cannot_invent_usage_while_retaining_full_bound(self):
        data = captured([slot(0)], lambda clock, calls: lambda b: emit(b"{}", 503))
        r = data["responses"][0]; r["usage"] = {"input_tokens": 1, "output_tokens": 0}
        data["finals"][0].update(r)
        for row in data["ledger"]:
            if row["event"]["kind"] == "retain_unknown": row["event"]["response_sha256"] = audit.digest(r)
        chain = "0"*64
        for row in data["ledger"]:
            row["previous_sha256"] = chain
            row["sha256"] = audit.digest({k: v for k, v in row.items() if k != "sha256"}); chain = row["sha256"]
        data["summary"]["budget"]["ledger_sha256"] = chain
        with self.assertRaisesRegex(ValueError, "cannot invent terminal/usage"): replay(data)

    def test_model_route_mismatch_retains_raw_terminal_without_success(self):
        def factory(clock, calls):
            return lambda body: emit(final({**body, "model": body["model"]+"-different-route"}))
        data = captured([slot(0), slot(1)], factory); result = replay(data)
        self.assertEqual(result["schedule_status"], "stopped")
        self.assertEqual(result["counts"]["eventual_completed"], 0)
        self.assertEqual(data["responses"][0]["error"], "response_model_mismatch")
        self.assertIsNotNone(data["responses"][0]["raw_response"])
        self.assertIsNone(data["responses"][0]["settled_credits"])

    def test429_header_then_partial_body_timeout_still_waits65(self):
        def factory(clock, calls):
            async def t(body):
                if len(calls) == 1:
                    yield {"http_status": 429, "content_type": "application/json", "retry_after": "60"}
                    yield b'{"partial":'
                    clock.value += 180
                    raise asyncio.TimeoutError()
                async for item in emit(final(body)): yield item
            return t
        data = captured([slot(0), slot(1)], factory); result = replay(data)
        self.assertEqual(result["counts"]["retries"], 0)
        self.assertEqual(result["counts"]["per_slot_operational_failures"], 1)
        self.assertGreaterEqual(result["minimum_completion_gap_seconds"], 65)

    def test_first_attempt_dependency_eligibility_does_not_use_eventual_retry(self):
        def factory(clock, calls):
            return lambda b: emit(b"{}", 429, "65") if len(calls) == 1 else emit(final(b))
        data = captured([slot(0), slot(1, history_from=["s-0"])], factory); result = replay(data)
        self.assertEqual(result["counts"]["first_attempt_completed"], 1)
        self.assertEqual(result["first_attempt_dependency_eligible_completed"], 0)
        self.assertEqual(result["eventual_dependency_eligible_completed"], 2)

    def test_relocated_artifact_bindings_equal_with_only_inert_alias_and_snapshot(self):
        # This test isolates artifact authentication/relocation. The16 earlier
        # tests independently exercise real mock-runtime journal replay.
        prior = (ROOT/BASELINE_LEDGER).read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            left, right = Path(tmp)/"left", Path(tmp)/"right"
            common = {}; protected = {}
            lock = next(iter(audit.ALLOWED_ALIAS)); inert = audit.ALLOWED_ALIAS[lock]
            for i in range(997): common[f"protected/p{i}.txt"] = str(i).encode()
            common[lock] = b"inert historical evidence"
            protected = {p: sha256(raw).hexdigest() for p, raw in common.items()}
            auth_name = "data/frontier-v6i-authorization.json"
            common[auth_name] = json.dumps({"protected": protected, "protected_v5_file_count": 402}).encode()
            base_name = "data/frontier-v6h-ledger-after-paced-canary.jsonl"; common[base_name] = prior
            sessions_name = "data/frontier-v6i-sessions.json"
            slots = [{"slot_id": f"fixture-{i}"} for i in range(1800)]
            common[sessions_name] = json.dumps(slots).encode()
            freeze = {"schema": "retrace.frontier-v6i-freeze.v1", "created_at": "2026-11-14T00:00:00+00:00",
                "files": [{"path": p, "sha256": sha256(raw).hexdigest()} for p, raw in common.items()],
                "authorization_path": auth_name, "authorization_sha256": sha256(common[auth_name]).hexdigest(),
                "baseline_path": base_name, "sessions_path": sessions_name,
                "sessions_sha256": audit.digest(slots), "sessions_file_sha256": sha256(common[sessions_name]).hexdigest(),
                "output_path": "results/frontier-v6i/primary", "ledger_path": "results/frontier-v6i/budget"}
            freeze_raw = json.dumps(freeze).encode(); freeze_sha = sha256(freeze_raw).hexdigest()
            common["data/frontier-v6i-freeze.json"] = freeze_raw
            d = freeze["output_path"]
            common[d+"/run.json"] = json.dumps({"execution_manifest_sha256": freeze_sha, "created_at": "2026-11-14T00:01:00+00:00"}).encode()
            for name in ("requests.jsonl", "responses.jsonl", "slot-outcomes.jsonl"): common[d+"/"+name] = b""
            common[d+"/summary.json"] = b"{}"
            canonical = "results/frontier-v6i/budget/ledger.jsonl"
            snapshot = "data/frontier-v6i-ledger-after-study.jsonl"
            common[canonical] = b"{}\n"
            for root in (left, right):
                for name, raw in common.items():
                    dest = (inert if name == lock else snapshot if name == canonical else name) if root == right else name
                    p = root/dest; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
            fake = {"passed": True, "checks": 1, "final_closed": True, "all_scheduled_outcomes_accounted": True, "schedule_status": "completed"}
            with patch.object(audit, "audit_evidence", side_effect=lambda *a, **k: dict(fake)):
                a = audit.audit(left, freeze_sha)
                b = audit.audit(right, freeze_sha, frozen_aliases=audit.ALLOWED_ALIAS, ledger_snapshot=snapshot)
                self.assertEqual(a, b)
                self.assertIn(lock, b["input_bindings"])
                self.assertNotIn(inert, b["input_bindings"])
                self.assertIn(canonical, b["input_bindings"])
                self.assertNotIn(snapshot, b["input_bindings"])
                (right/inert).write_bytes(b"tampered historical lock")
                with self.assertRaisesRegex(ValueError, "frozen file"):
                    audit.audit(right, freeze_sha, frozen_aliases=audit.ALLOWED_ALIAS, ledger_snapshot=snapshot)

    def test_test_hooks_and_arbitrary_alias_rejected_at_real_boundary(self):
        data = captured([slot(0)])
        with self.assertRaisesRegex(ValueError, "test hooks"):
            audit.audit_evidence(**{k: v for k, v in data.items() if k != "streams"}, read_stream=lambda n: data["streams"][n])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "exact inert"):
                audit.audit(tmp, "a"*64, frozen_aliases={"anything": "../escape"})


if __name__ == "__main__": unittest.main()
