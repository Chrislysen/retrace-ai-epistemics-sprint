"""Prospective serial v6i transport. No network or credential access at import.

Frozen h request construction, SSE parsing, raw journaling and prices are reused.
The new policy continues after explicit per-slot provider failures, preserves all
unknown costs, and never retries anything except an explicit HTTP 429.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid

from .adaption_v6h import (
    AiohttpTransport, CAP, ENDPOINT, KNOWN_ERRORS, MODEL_PRICING, PRICING_URL,
    VERIFIED_DATE, DurableJSONL, StreamJournal, SSEDecoder, build_body,
    consume_stream, credits, digest, encoded, integer, nano, now,
    request_bound, require, response_text, slot_dependencies, strict_event_json,
    usage_cost, validate_slots, RollingLedger as HistoricalLedger,
    verify_prior_ledger as verify_historical_f, BASELINE_LEDGER as F_LEDGER,
)

BASELINE = "47.409962587"
BASELINE_LEDGER = "data/frontier-v6h-ledger-after-paced-canary.jsonl"
BASELINE_SHA256 = "0f8e54bbe0a13fbf56f50e3c40b43578e63200ab02bba130b7f8c4eb704057f6"
BASELINE_CHAIN = "57765aa545987f8219401c6d4650b1b693794eee020db6450b21e07847072a30"
DEADLINE = datetime(2026, 11, 16, 3, 55, tzinfo=timezone.utc)
RUNTIME_CONFIG = {"global_concurrency": 1, "completion_delay_seconds": 4.0,
    "rate_limit_cooldown_seconds": 65.0, "max_retries": 2, "timeout_seconds": 180.0}
RETRY_POLICY = {"only_http_status": 429, "max_retries": 2,
    "minimum_cooldown_seconds": 65.0, "backoff": "max(65 seconds, Retry-After), after every 429 attempt completes",
    "flood_stop": None, "unknown_attempt_bound_retained": True, "quota_verified": False}


def verify_prior_ledger(path):
    """Verify and carry the whole halted-but-closed h ledger without releasing it."""
    root = Path(__file__).resolve().parents[1]
    earlier = verify_historical_f(root / F_LEDGER)
    require(earlier["carry_credits"] == "43.633207445", "historical_f_carry")
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == BASELINE_SHA256 and raw.endswith(b"\n"), "prior_ledger_changed")
    previous = "0" * 64; accounted = nano("43.633207445"); attempts = {}; halts = set(); rows = []
    for seq, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        row = strict_event_json(line); rows.append(row)
        require(row["seq"] == seq and row["previous_sha256"] == previous, "prior_chain")
        require(row["sha256"] == digest({k: v for k, v in row.items() if k != "sha256"}), "prior_hash")
        previous = row["sha256"]; e = row["event"]; kind = e["kind"]
        if kind == "initialize":
            require(seq == 1 and e["historical_credits"] == "43.633207445" and e["cap_credits"] == "250", "prior_initialize")
        elif kind == "reserve":
            key = e["attempt_id"]; bound = e["bound_nanocredits"]
            integer(bound, 1, CAP, "prior_bound"); require(key not in attempts, "prior_duplicate")
            attempts[key] = {"bound": bound, "settled": False, "retained_429": False}; accounted += bound
        elif kind == "settle":
            a = attempts[e["attempt_id"]]; cost = e["accounted_nanocredits"]
            integer(cost, 0, a["bound"], "prior_cost")
            require(not a["settled"] and not a["retained_429"], "prior_double_settle")
            accounted += cost - a["bound"]; a["settled"] = True
        elif kind == "retain_429":
            a = attempts[e["attempt_id"]]
            require(not a["settled"] and not a["retained_429"], "prior_double_retention")
            a["retained_429"] = True
        elif kind == "halt":
            require(e["reason"] == "timeout" and e["attempt_id"] in attempts, "prior_halt")
            halts.add(e["attempt_id"])
        else: require(kind in ("run_started", "run_closed"), "prior_event")
        require(accounted <= CAP, "prior_cap")
    unknown = {k for k, a in attempts.items() if not a["settled"] and not a["retained_429"]}
    require(len(rows) == 95 and previous == BASELINE_CHAIN and accounted == nano(BASELINE), "prior_carry")
    require(len(attempts) == 42 and sum(a["settled"] for a in attempts.values()) == 33
        and sum(a["retained_429"] for a in attempts.values()) == 8 and unknown == halts and len(unknown) == 1, "prior_accounting_counts")
    require(rows[-1]["event"]["kind"] == "run_closed" and rows[-1]["event"]["status"] == "stopped", "prior_not_closed")
    return {"file_sha256": BASELINE_SHA256, "chain_sha256": previous, "carry_credits": BASELINE,
        "issued_attempts": 42, "settled_attempts": 33, "unknown_429_retained": 8,
        "unknown_timeout_retained": 1, "earlier_frozen_ledger": earlier,
        "cumulative_inherited_unsettled_attempts": earlier["cumulative_inherited_unsettled_attempts"] + 9,
        "authorization": "New user-directed execution policy; prior halted run remains closed and all full unknown bounds remain in the carry."}


class RollingLedger(HistoricalLedger):
    """New exclusive ledger; explicit retained failures never become free credit."""
    def __init__(self, directory, *, baseline_path):
        self.prior_evidence = verify_prior_ledger(baseline_path)
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.directory / "active.lock"
        self.lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self.file = None; self.attempts = {}; self.accounted = nano(BASELINE)
        self.halted = False; self.seq = 0; self.last_hash = "0" * 64
        try:
            path = self.directory / "ledger.jsonl"; exists = path.exists()
            if exists:
                raw = path.read_bytes(); require(raw and raw.endswith(b"\n"), "ledger_truncated")
                last = None
                for line in raw.decode("utf-8").splitlines():
                    row = strict_event_json(line)
                    require(row["seq"] == self.seq + 1 and row["previous_sha256"] == self.last_hash, "ledger_chain_invalid")
                    require(row["sha256"] == digest({k: v for k, v in row.items() if k != "sha256"}), "ledger_hash_invalid")
                    self._apply(row["event"]); self.seq = row["seq"]; self.last_hash = row["sha256"]; last = row["event"]
                require(not self.halted, "ledger_previously_halted")
                require(last["kind"] == "run_closed", "ledger_run_not_closed")
                require(all(a["settled"] or a.get("retained_429") or a.get("retained_unknown") for a in self.attempts.values()), "ledger_has_unresolved_attempt")
            self.file = DurableJSONL(path, append=exists)
            if not exists:
                self.record({"kind": "initialize", "historical_credits": BASELINE, "historical_sha256": BASELINE_SHA256,
                    "cap_credits": "250", "authorization": "User-directed v6i serial policy; no prior reservation released"})
        except BaseException:
            self.close(); raise

    def _apply(self, event):
        kind = event["kind"]
        if kind == "initialize":
            require(self.seq == 0 and event["historical_sha256"] == BASELINE_SHA256
                and event["historical_credits"] == BASELINE and event["cap_credits"] == "250", "invalid_initial_ledger")
        elif kind == "retain_unknown":
            a = self.attempts[event["attempt_id"]]
            require(not a["settled"] and not a.get("retained_429") and not a.get("retained_unknown"), "double_retention")
            require(isinstance(event.get("reason"), str) and bool(event["reason"])
                and isinstance(event.get("response_sha256"), str) and len(event["response_sha256"]) == 64, "unknown_retention_evidence")
            a["retained_unknown"] = event["reason"]
        else:
            if kind == "reserve": require(not self.halted, "ledger_halted")
            if kind in ("settle", "retain_429"):
                a = self.attempts[event["attempt_id"]]
                require(not a.get("retained_unknown") and not a.get("retained_429"), "retained_attempt_cannot_settle")
            super()._apply(event)

    def snapshot(self):
        value = super().snapshot(); value["historical_carry_credits"] = BASELINE
        value["unknown_operational_attempts_retained"] = sum(bool(a.get("retained_unknown")) for a in self.attempts.values())
        value["cumulative_inherited_unsettled_attempts"] = self.prior_evidence["cumulative_inherited_unsettled_attempts"]
        return value


def retry_delay(retry_after, *, utc_now=None):
    """Fixed 65-second floor; larger numeric/date Retry-After is honored."""
    delay = 65.0
    if isinstance(retry_after, str):
        try:
            if retry_after.strip().isdigit(): delay = max(delay, float(retry_after.strip()))
            else:
                dt = parsedate_to_datetime(retry_after)
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                delay = max(delay, (dt - (utc_now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError): pass
    require(math.isfinite(delay), "invalid_retry_delay")
    return delay


def verify_execution_manifest(path, expected_sha256, slots):
    raw = Path(path).read_bytes()
    require(isinstance(expected_sha256, str) and len(expected_sha256) == 64
        and hashlib.sha256(raw).hexdigest() == expected_sha256, "execution_manifest_hash")
    value = strict_event_json(raw.decode("utf-8"))
    require(value.get("sessions_sha256") == digest(slots), "execution_sessions_mismatch")
    require(value.get("runtime_config") == RUNTIME_CONFIG
        and all(type(value["runtime_config"][k]) in (int, float) and type(value["runtime_config"][k]) is not bool for k in RUNTIME_CONFIG), "execution_policy_mismatch")
    require(datetime.fromisoformat(value.get("deadline_utc", "")) == DEADLINE, "execution_deadline_mismatch")
    return value


async def run_slots(slots, *, api_key, output_dir, ledger, transport,
                    execution_manifest_path, execution_manifest_sha256,
                    timeout_seconds=180, stop_file=None, _clock=None, _sleep=None, _utcnow=None):
    """One serial worker: all pacing finishes before reservation and timeout.

    Root's driver authenticates the execution manifest's full file inventory.
    This entry point independently binds exact session/config/deadline bytes.
    Test hooks are explicit in the durable run manifest and never implicit.
    """
    slots = validate_slots(slots)
    execution = verify_execution_manifest(execution_manifest_path, execution_manifest_sha256, slots)
    require(timeout_seconds == 180 and type(timeout_seconds) in (int, float), "invalid_timeout")
    require(isinstance(api_key, str) and len(api_key) >= 8 and not any(c.isspace() for c in api_key), "invalid_credential")
    require(api_key not in encoded(slots) and api_key not in str(output_dir), "credential_in_configuration")
    require(not ledger.halted, "ledger_halted")
    clock = _clock or time.monotonic; sleep = _sleep or asyncio.sleep
    utcnow = _utcnow or (lambda: datetime.now(timezone.utc))
    scrub = lambda text: text.replace(api_key, "[REDACTED_CREDENTIAL]").replace(json.dumps(api_key)[1:-1], "[REDACTED_CREDENTIAL]")
    directory = Path(output_dir); directory.mkdir(parents=True, exist_ok=False); (directory / "streams").mkdir()
    run_id = uuid.uuid4().hex; files = []
    manifest = {"schema": "retrace.adaption-v6i-run.v1", "run_id": run_id, "created_at": now(),
        "endpoint": ENDPOINT, "sessions_sha256": digest(slots), "slots": slots,
        "execution_manifest_path": str(execution_manifest_path), "execution_manifest_sha256": execution_manifest_sha256,
        "runtime_config": deepcopy(RUNTIME_CONFIG), "deadline_utc": DEADLINE.isoformat(),
        "retry_policy": deepcopy(RETRY_POLICY), "ready_model_order": "deterministic_round_robin_first_appearance; preserve eligible slot order within model",
        "completion_definition": "Scheduling closure is separate from successful provider/model outcomes.",
        "models_pricing": MODEL_PRICING, "pricing_source": PRICING_URL, "pricing_verified_date": VERIFIED_DATE,
        "prior_ledger_replay": ledger.prior_evidence, "budget_before": ledger.snapshot(),
        "store": False, "previous_response_id": None, "agentic_memory": False, "tools": False, "stream": True,
        "stop_file": str(stop_file) if stop_file else None, "test_hooks": any(x is not None for x in (_clock, _sleep, _utcnow))}
    try:
        for name in ("run.json", "requests.jsonl", "responses.jsonl", "slot-outcomes.jsonl"):
            files.append(DurableJSONL(directory / name, scrub=scrub))
        mf, requests, responses, outcomes = files; mf.write(manifest)
        ledger.record({"kind": "run_started", "run_id": run_id, "sessions_sha256": digest(slots), "planned": len(slots), "execution_manifest_sha256": execution_manifest_sha256})
        stopped = False; stop_reasons = []; completed = {}; finals = {}; attempt_rows = []; issued = []
        states = {s["slot_id"]: {"attempts": 0, "not_before": 0.0} for s in slots}
        model_order = list(dict.fromkeys(s["model"] for s in slots)); cursor = 0
        models = {m: [s for s in slots if s["model"] == m] for m in model_order}
        next_admission = 0.0; last_finished = None

        def stop(reason, attempt_id=None):
            nonlocal stopped
            stopped = True
            if reason not in stop_reasons:
                stop_reasons.append(reason)
                try: ledger.record({"kind": "halt", "run_id": run_id, "reason": reason, "attempt_id": attempt_id})
                except Exception: stop_reasons.append("ledger_write_failure")

        def check_stop():
            if stop_file and Path(stop_file).exists(): stop("administrative_stop_file")
            if utcnow() >= DEADLINE: stop("administrative_deadline")

        def finalize(slot, row):
            key = slot["slot_id"]; require(key not in finals, "duplicate_slot_outcome")
            value = {**row, "slot_final": True, "attempts_issued": states[key]["attempts"],
                "first_attempt_id": next((r["attempt_id"] for r in attempt_rows if r["slot_id"] == key), None)}
            outcomes.write(value); finals[key] = value

        def skipped(slot, reason, blocked=()):
            return {"run_id": run_id, "slot_id": slot["slot_id"], "case_id": slot["case_id"], "model": slot["model"],
                "condition": slot["condition"], "phase": slot["phase"], "issued": False, "terminal_valid": False,
                "model_outcome": reason, "error": reason, "response_status": None, "output_text": "",
                "blocked_dependencies": list(blocked), "at": now()}

        async def attempt(slot, body, aid, bound, number):
            nonlocal next_admission, last_finished
            started = clock(); journal = None; decoder = SSEDecoder(); status = None; raw = None; parsed = None
            cost = None; text = ""; error = None; outcome = None; observed_429 = None
            def observe(headers):
                nonlocal observed_429
                if headers["http_status"] == 429: observed_429 = retry_delay(headers.get("retry_after"), utc_now=utcnow())
            try:
                journal = StreamJournal(directory / "streams" / (hashlib.sha256(aid.encode()).hexdigest() + ".sse"), api_key)
                status, raw = await asyncio.wait_for(consume_stream(transport(body), journal, decoder, observe), timeout=180)
                require(scrub(raw) == raw, "credential_echo_detected")
                parsed = strict_event_json(raw); require(parsed.get("model") == slot["model"], "response_model_mismatch")
                cost = usage_cost(slot["model"], parsed.get("usage"), slot["max_output_tokens"])
                require(cost <= bound, "reservation_bound_breached"); text = response_text(parsed)
                outcome = "completed" if parsed["status"] == "completed" else "truncated_max_output_tokens"
            except asyncio.TimeoutError: error = "timeout"
            except UnicodeError: error = "stream_invalid_utf8"
            except ValueError as exc:
                code = str(exc); error = code if code in KNOWN_ERRORS or (code.startswith("http_") and len(code) == 8 and code[5:].isdigit()) else "invalid_response"
            except Exception: error = "network_or_transport_failure"
            finally:
                if journal:
                    try: journal.close()
                    except Exception: error = "stream_journal_failure"
            status = status if status is not None else journal.http_status if journal else None
            is_429 = error == "http_429" and status == 429
            if is_429 and journal and not journal.redacted:
                try:
                    error_body = strict_event_json(journal.path.read_text(encoding="utf-8"))
                    require(error_body.get("model", slot["model"]) == slot["model"], "response_model_mismatch")
                    candidate_cost = usage_cost(slot["model"], error_body.get("usage"), slot["max_output_tokens"])
                    require(candidate_cost <= bound, "reservation_bound_breached"); parsed = error_body; cost = candidate_cost
                except (ValueError, UnicodeError, OSError): cost = None
            transient = error == "timeout" or (error == "http_" + str(status) and type(status) is int and (status == 408 or 500 <= status <= 599))
            scope = None if error is None else "slot" if (is_429 or transient) else "global"
            delay = max(observed_429 or 0, retry_delay(getattr(journal, "retry_after", None), utc_now=utcnow())) if status == 429 else None
            row = {"run_id": run_id, "attempt_id": aid, "attempt_number": number, "first_attempt": number == 1,
                "slot_id": slot["slot_id"], "case_id": slot["case_id"], "model": slot["model"], "condition": slot["condition"], "phase": slot["phase"],
                "issued": True, "terminal_valid": error is None, "model_outcome": outcome if error is None else "http_429" if is_429 else "operational_failure",
                "failure_scope": scope, "response_status": parsed.get("status") if isinstance(parsed, dict) else None,
                "http_status": status, "error": error, "raw_response": scrub(raw) if isinstance(raw, str) else None,
                "stream_evidence": journal.metadata() if journal else None, "stream_terminal_event": decoder.terminal, "stream_event_count": decoder.event_count,
                "output_text": text if error is None and outcome == "completed" else "", "partial_output_text": text if error is None and outcome == "truncated_max_output_tokens" else "",
                "usage": parsed.get("usage") if isinstance(parsed, dict) else None, "latency_ms": round((clock() - started) * 1000, 3),
                "attempt_started_monotonic": started, "transport_finished_monotonic": clock(),
                "at": now(), "reserved_credits": credits(bound), "settled_credits": credits(cost) if cost is not None and (error is None or is_429) else None,
                "retry_after": getattr(journal, "retry_after", None), "retry_cooldown_seconds": delay}
            responses.write(row); attempt_rows.append(row)
            if cost is not None and (error is None or is_429):
                ledger.record({"kind": "settle", "attempt_id": aid, "accounted_nanocredits": cost, "response_sha256": digest(row), "basis": "explicit_bounded_usage_uncached_no_double_reasoning", "model_outcome": row["model_outcome"]})
            else:
                ledger.record({"kind": "retain_429" if is_429 else "retain_unknown", "attempt_id": aid, "response_sha256": digest(row),
                    "reason": error, "basis": "no_valid_usage_full_bound_retained"})
            if scope == "global": stop(error, aid)
            if is_429 and number < 3 and not stopped:
                states[slot["slot_id"]]["not_before"] = clock() + delay
            else:
                if error is None and outcome == "completed": completed[slot["slot_id"]] = {"actual_input": body["input"][-1]["content"], "output_text": text}
                finalize(slot, row)
            # Start the gap after response/ledger/finalization durability, not
            # request admission or header arrival. It covers exhausted 429 too.
            last_finished = clock(); next_admission = last_finished + max(4.0, delay or 0)

        async def worker():
            nonlocal cursor
            while len(finals) < len(slots):
                check_stop()
                if stopped: break
                # Re-evaluate ready-slot order only AFTER the global gap. A
                # pending retry must not be overtaken merely because it was
                # still cooling down when the previous attempt completed.
                while not stopped and clock() < next_admission:
                    check_stop()
                    if not stopped: await sleep(min(.1, max(0.0, next_admission - clock())))
                check_stop()
                if stopped: break
                selected = None
                for model in model_order[cursor:] + model_order[:cursor]:
                    for slot in models[model]:
                        key = slot["slot_id"]
                        if key in finals: continue
                        deps = slot_dependencies(slot); bad = [d for d in deps if d in finals and d not in completed]
                        if bad: finalize(slot, skipped(slot, "not_issued_dependency_failed", bad)); continue
                        if any(d not in completed for d in deps): continue
                        if clock() < states[key]["not_before"]: continue
                        selected = slot; break
                    if selected: break
                if selected is None:
                    if len(finals) == len(slots): break
                    await sleep(.05); continue
                check_stop()
                if stopped: break
                key = selected["slot_id"]; body = build_body(selected, completed)
                bound = request_bound(selected["model"], selected["max_output_tokens"])
                if ledger.accounted + bound > CAP: stop("cumulative_budget_stop"); break
                # Reauthenticate exact manifest bytes at admission; immutable
                # scientific/runtime inventory verification belongs to driver.
                verify_execution_manifest(execution_manifest_path, execution_manifest_sha256, slots)
                check_stop()
                if stopped: break
                number = states[key]["attempts"] + 1; aid = run_id + ":" + key + ":attempt-" + str(number)
                ledger.record({"kind": "reserve", "attempt_id": aid, "run_id": run_id, "slot_id": key, "attempt_number": number, "model": selected["model"], "bound_nanocredits": bound})
                requests.write({"attempt_id": aid, "slot_id": key, "attempt_number": number, "first_attempt": number == 1, "at": now(),
                    "request": body, "request_sha256": digest(body), "reserved_credits": credits(bound),
                    "previous_attempt_finished_monotonic": last_finished, "admitted_monotonic": clock(),
                    "dependency_bindings": [{"slot_id": d, "final_attempt_id": finals[d].get("attempt_id"), "output_sha256": hashlib.sha256(completed[d]["output_text"].encode()).hexdigest()} for d in slot_dependencies(selected)]})
                states[key]["attempts"] = number; issued.append(aid); cursor = (model_order.index(selected["model"]) + 1) % len(model_order)
                await attempt(selected, body, aid, bound, number)
        task = asyncio.create_task(worker())
        try: await asyncio.shield(task)
        except asyncio.CancelledError:
            stop("administrative_run_cancelled"); await asyncio.shield(task)
        except BaseException: stop("unexpected_worker_or_journal_failure")
        for slot in slots:
            key = slot["slot_id"]
            if key in finals: continue
            rows = [r for r in attempt_rows if r["slot_id"] == key]
            if rows: finalize(slot, {**rows[-1], "retry_abandoned_due_global_stop": rows[-1]["model_outcome"] == "http_429"})
            else: finalize(slot, skipped(slot, "issued_without_response" if states[key]["attempts"] else "not_issued_global_stop"))
        first = [r for r in attempt_rows if r["first_attempt"]]
        summary = {"schema": "retrace.adaption-v6i-summary.v1", "run_id": run_id, "status": "stopped" if stopped else "completed",
            "transport_revision": "serial_completion_paced_v6i_v1", "runtime_config": deepcopy(RUNTIME_CONFIG), "stream": True,
            "planned": len(slots), "models": dict(Counter(s["model"] for s in slots)), "issued_attempts": len(issued),
            "issued_slots": sum(bool(s["attempts"]) for s in states.values()), "responses": len(attempt_rows), "slot_outcomes": len(finals),
            "completed": len(completed), "eventual_completed": len(completed), "first_attempt_completed": sum(r["model_outcome"] == "completed" for r in first),
            "first_attempt_valid_terminal_records": sum(r["terminal_valid"] for r in first), "first_attempt_truncated": sum(r["model_outcome"] == "truncated_max_output_tokens" for r in first),
            "first_attempt_http_429": sum(r["model_outcome"] == "http_429" for r in first), "valid_terminal_records": sum(r["terminal_valid"] for r in attempt_rows),
            "eventual_terminal_slots": sum(r["terminal_valid"] for r in finals.values()), "truncated": sum(r["model_outcome"] == "truncated_max_output_tokens" for r in finals.values()),
            "http_429_attempts": sum(r["model_outcome"] == "http_429" for r in attempt_rows), "issued_operational_failures": sum(r["model_outcome"] == "operational_failure" for r in attempt_rows),
            "per_slot_operational_failures": sum(r["model_outcome"] == "operational_failure" and r["failure_scope"] == "slot" for r in attempt_rows),
            "dependency_skips": sum(r["model_outcome"] == "not_issued_dependency_failed" for r in finals.values()),
            "unissued_slot_ids": [s["slot_id"] for s in slots if not states[s["slot_id"]]["attempts"]],
            "issued_without_outcome_attempt_ids": sorted({a for a in ledger.attempts if a.startswith(run_id + ":")} - {r["attempt_id"] for r in attempt_rows}),
            "retries": len(issued) - sum(bool(s["attempts"]) for s in states.values()), "max_retries_per_slot": 2,
            "retry_policy": deepcopy(RETRY_POLICY), "stop_reasons": stop_reasons, "all_scheduled_outcomes_recorded": len(finals) == len(slots),
            "completion_definition": "Scheduling closure; per-slot provider failures remain failures and do not stop independent slots.", "actual_billed_credits": None}
        ledger.record({"kind": "run_closed", "run_id": run_id, "status": summary["status"], "issued_attempts": len(issued),
            "issued_slots": summary["issued_slots"], "unissued_slots": len(summary["unissued_slot_ids"]), "administrative": any(s.startswith("administrative_") for s in stop_reasons)})
        summary["budget"] = ledger.snapshot()
        sf = DurableJSONL(directory / "summary.json", scrub=scrub); files.append(sf); sf.write(summary)
        return summary
    finally:
        for f in files: f.close()
