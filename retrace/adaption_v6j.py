"""Prospective serial v6j continuation transport. No network or credential access at import.

Frozen h request construction, SSE parsing, raw journaling and prices are reused.
The new policy continues after explicit per-slot provider failures, preserves all
unknown costs, and never retries anything except an explicit HTTP 429.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
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
)
from .adaption_v6i import verify_prior_ledger as verify_original_h, BASELINE_LEDGER as H_LEDGER

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "47.653269434"
BASELINE_LEDGER = "data/frontier-v6i-ledger-after-study.jsonl"
BASELINE_SHA256 = "899d54ea6c6780ecf4474abef51ba97b3b7068483c998f7babfa8dd8c44185d1"
BASELINE_CHAIN = "0d7bde3bb481f594683d543822c6ca112deb7c4c0df55aaabb41a287bd8b7773"
OBSERVED_RESPONSE_MODELS = {"qwen3.5-397b": "qwen3.5-397b-a17b-nvfp4"}
ORIGINAL_FREEZE = "data/frontier-v6i-freeze.json"
ORIGINAL_FREEZE_SHA = "156173e0dabc3a6f88c4301847f892f16bd6d0d73fd7c83c6d3dfc64b3a3a600"
CONTINUATION = "data/frontier-v6j-continuation.json"
CONTINUATION_SHA = "89310028826c19aee5393e4f38ba236062aaeb0db8dc434306164997ff00eba4"
ORIGINAL_FILES = {
    "run": ("results/frontier-v6i/primary/run.json", "d80059a34ca4f339e2ec4609d58dd131d9c9a8fc26cf979fc09eaf0d54f613ec"),
    "requests": ("results/frontier-v6i/primary/requests.jsonl", "60de2aaad489dc4fb605e5b8d988566bac86758ff8bec8c9641c9f057ccd9664"),
    "responses": ("results/frontier-v6i/primary/responses.jsonl", "aae4b303b3058fce795d3dd567f96e626f975359b294bb37c80b184eb01af0fc"),
    "outcomes": ("results/frontier-v6i/primary/slot-outcomes.jsonl", "996921f104f96e105b5326d1f7112e96203ef8e23e4474ca14aef023d243356e"),
    "summary": ("results/frontier-v6i/primary/summary.json", "6c81a01452243f45246dd65fc7b1e2c8cd4d7eed91d1ff9cd335f8e6d094dc14"),
}
DEADLINE = datetime(2026, 11, 16, 3, 55, tzinfo=timezone.utc)
RUNTIME_CONFIG = {"global_concurrency": 1, "completion_delay_seconds": 4.0,
    "rate_limit_cooldown_seconds": 65.0, "max_retries": 2, "timeout_seconds": 180.0}
RETRY_POLICY = {"only_http_status": 429, "max_retries": 2,
    "minimum_cooldown_seconds": 65.0, "backoff": "max(65 seconds, Retry-After), after every 429 attempt completes",
    "flood_stop": None, "unknown_attempt_bound_retained": True, "quota_verified": False}


def verify_prior_ledger(path):
    """Carry all six original attempts, including the unaccepted model route."""
    earlier = verify_original_h(ROOT / H_LEDGER)
    require(earlier["carry_credits"] == "47.409962587", "historical_h_carry")
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == BASELINE_SHA256 and raw.endswith(b"\n"), "prior_ledger_changed")
    previous = "0" * 64; accounted = nano("47.409962587"); attempts = {}; halts = set(); rows = []
    for seq, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        row = strict_event_json(line); rows.append(row)
        require(row["seq"] == seq and row["previous_sha256"] == previous, "prior_chain")
        require(row["sha256"] == digest({k: v for k, v in row.items() if k != "sha256"}), "prior_hash")
        previous = row["sha256"]; e = row["event"]; kind = e["kind"]
        if kind == "initialize":
            require(seq == 1 and e["historical_credits"] == "47.409962587" and e["cap_credits"] == "250", "prior_initialize")
        elif kind == "reserve":
            key = e["attempt_id"]; bound = e["bound_nanocredits"]
            integer(bound, 1, CAP, "prior_bound"); require(key not in attempts, "prior_duplicate")
            attempts[key] = {"bound": bound, "settled": False, "retained_unknown": False}; accounted += bound
        elif kind == "settle":
            a = attempts[e["attempt_id"]]; cost = e["accounted_nanocredits"]
            integer(cost, 0, a["bound"], "prior_cost")
            require(not a["settled"] and not a["retained_unknown"], "prior_double_settle")
            accounted += cost - a["bound"]; a["settled"] = True
        elif kind == "retain_unknown":
            a = attempts[e["attempt_id"]]
            require(not a["settled"] and not a["retained_unknown"] and e["reason"] == "response_model_mismatch", "prior_retention")
            a["retained_unknown"] = True
        elif kind == "halt":
            require(e["reason"] == "response_model_mismatch" and e["attempt_id"] in attempts, "prior_halt")
            halts.add(e["attempt_id"])
        else: require(kind in ("run_started", "run_closed"), "prior_event")
        require(accounted <= CAP, "prior_cap")
    unknown = {k for k, a in attempts.items() if a["retained_unknown"]}
    require(len(rows) == 16 and previous == BASELINE_CHAIN and accounted == nano(BASELINE), "prior_carry")
    require(len(attempts) == 6 and sum(a["settled"] for a in attempts.values()) == 5
        and unknown == halts and len(unknown) == 1, "prior_accounting_counts")
    require(rows[-1]["event"]["kind"] == "run_closed" and rows[-1]["event"]["status"] == "stopped", "prior_not_closed")
    return {"file_sha256": BASELINE_SHA256, "chain_sha256": previous, "carry_credits": BASELINE,
        "issued_attempts": 6, "settled_attempts": 5, "unknown_model_mismatch_retained": 1,
        "earlier_frozen_ledger": earlier,
        "cumulative_inherited_unsettled_attempts": earlier["cumulative_inherited_unsettled_attempts"] + 1,
        "authorization": "Prospective continuation of never-issued slots; original six attempts and all prior unknown bounds remain unchanged."}


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
                    "cap_credits": "250", "authorization": "User-directed v6j continuation; no prior reservation released"})
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


def verify_continuation(slots, continuation_path=None, continuation_sha256=CONTINUATION_SHA):
    """Authenticate original journals and return six immutable dependency seeds.

    Called once before a new run; no carried output is fabricated or rescored.
    Runtime journals will contain only the independently derived unissued set.
    """
    path = Path(continuation_path) if continuation_path is not None else ROOT / CONTINUATION
    require(path.resolve() == (ROOT / CONTINUATION).resolve(), "continuation_path_mismatch")
    raw = path.read_bytes()
    require(continuation_sha256 == CONTINUATION_SHA and hashlib.sha256(raw).hexdigest() == CONTINUATION_SHA, "continuation_hash")
    receipt = strict_event_json(raw.decode("utf-8"))
    require(receipt["schema"] == "retrace.frontier-v6j-continuation.v1"
        and receipt["prior_freeze_path"] == ORIGINAL_FREEZE and receipt["prior_freeze_sha256"] == ORIGINAL_FREEZE_SHA
        and receipt["observed_response_models"] == OBSERVED_RESPONSE_MODELS, "continuation_contract")
    require(hashlib.sha256((ROOT / ORIGINAL_FREEZE).read_bytes()).hexdigest() == ORIGINAL_FREEZE_SHA, "original_freeze_changed")
    require(receipt["baseline_snapshot_path"] == BASELINE_LEDGER and receipt["baseline_snapshot_sha256"] == BASELINE_SHA256
        and receipt["historical_conservative_carry_credits"] == BASELINE and receipt["cumulative_cap_credits"] == "250", "continuation_budget")
    require(len(slots) == receipt["full_planned_slots"] == 1800 and receipt["sessions_sha256"] == digest(slots)
        and receipt["sessions_path"] == "data/frontier-v6i-sessions.json", "original_schedule_changed")
    expected_files = {p: h for p, h in ORIGINAL_FILES.values()}
    expected_files.update({BASELINE_LEDGER: BASELINE_SHA256, "results/frontier-v6i/budget/ledger.jsonl": BASELINE_SHA256})
    require(receipt["prior_journal_files"] == expected_files, "prior_journal_inventory")
    contents = {}
    for name, expected in expected_files.items():
        b = (ROOT / name).read_bytes(); require(hashlib.sha256(b).hexdigest() == expected, "prior_journal_changed")
        contents[name] = b
    read = lambda role: strict_event_json(contents[ORIGINAL_FILES[role][0]].decode("utf-8"))
    def lines(role):
        b = contents[ORIGINAL_FILES[role][0]]; require(b.endswith(b"\n"), "prior_partial_journal")
        return [strict_event_json(x.decode("utf-8")) for x in b.splitlines()]
    old_run = read("run"); old_summary = read("summary")
    requests = lines("requests"); responses = lines("responses"); old_finals = lines("outcomes")
    require(old_run["slots"] == slots and old_run["sessions_sha256"] == digest(slots)
        and old_run["run_id"] == receipt["original_run_id"], "original_run_binding")
    require(old_summary["status"] == "stopped" and old_summary["stop_reasons"] == ["response_model_mismatch"]
        and old_summary["issued_attempts"] == old_summary["issued_slots"] == 6
        and old_summary["budget"]["accounted_credits"] == BASELINE, "original_closure_binding")
    require(len(requests) == len(responses) == 6 and len(old_finals) == 1800, "original_counts")
    request_map = {r["attempt_id"]: r for r in requests}; response_map = {r["attempt_id"]: r for r in responses}
    issued = [r["slot_id"] for r in requests]; index = {s["slot_id"]: s for s in slots}
    require(len(set(issued)) == 6 and receipt["permanently_excluded_issued_slot_ids"] == issued, "issued_exclusion_set")
    finals = {}; completed = {}; bindings = []
    for line_number, final in enumerate(old_finals, 1):
        sid = final["slot_id"]
        if sid not in issued:
            require(final["issued"] is False and final["model_outcome"] == "not_issued_global_stop"
                and final["attempts_issued"] == 0, "noncarried_original_outcome")
            continue
        require(sid not in finals and final["issued"] is True and final["attempts_issued"] == 1, "carryover_final_identity")
        aid = final["attempt_id"]; r = response_map[aid]; q = request_map[aid]; s = index[sid]
        require(all(final.get(k) == v for k, v in r.items()) and q["slot_id"] == sid
            and q["request"] == build_body(s, {}) and q["request_sha256"] == digest(q["request"]), "carryover_actual_request_output")
        require(r["first_attempt"] is True and r["attempt_number"] == 1 and final["first_attempt_id"] == aid, "carryover_first_attempt")
        if r["terminal_valid"]:
            terminal = strict_event_json(r["raw_response"])
            require(r["error"] is None and r["response_status"] == r["model_outcome"] == "completed"
                and terminal["model"] == s["model"] and response_text(terminal) == r["output_text"], "carried_completion_invalid")
            completed[sid] = {"actual_input": q["request"]["input"][-1]["content"], "output_text": r["output_text"]}
        else:
            require(s["model"] == "qwen3.5-397b" and r["error"] == "response_model_mismatch"
                and r["failure_scope"] == "global" and r["output_text"] == "" and r["settled_credits"] is None, "original_failed_route_must_remain_failure")
        finals[sid] = deepcopy(final)
        bindings.append({"slot_id": sid, "source_path": ORIGINAL_FILES["outcomes"][0], "source_line_one_based": line_number,
            "row_sha256": digest(final), "attempt_id": aid, "model_outcome": final["model_outcome"]})
    require(len(finals) == 6 and len(completed) == 5 and bindings == receipt["carryover_rows"], "carryover_rows_changed")
    continuation_ids = [s["slot_id"] for s in slots if s["slot_id"] not in finals]
    require(continuation_ids == receipt["continuation_slot_ids"] and len(continuation_ids) == receipt["continuation_slots"] == 1794
        and receipt["carried_issued_slots"] == 6, "continuation_selection_changed")
    unavailable = set(finals) - set(completed); descendants = []
    for s in slots:
        if s["slot_id"] not in finals and any(d in unavailable for d in slot_dependencies(s)):
            unavailable.add(s["slot_id"]); descendants.append(s["slot_id"])
    require(descendants == receipt["failed_producer_descendant_slot_ids"] and len(descendants) == 2, "failed_producer_descendants_changed")
    prior_closure = strict_event_json(contents[BASELINE_LEDGER].splitlines()[-1].decode("utf-8"))
    return {"finals": finals, "completed": completed, "issued_slot_ids": issued,
        "continuation_slot_ids": continuation_ids, "bindings": bindings, "failed_descendant_slot_ids": descendants,
        "last_issued_model": requests[-1]["request"]["model"], "original_run_id": old_run["run_id"],
        "earliest_next_admission_utc": (datetime.fromisoformat(prior_closure["at"]) + timedelta(seconds=4)).isoformat(),
        "continuation_path": CONTINUATION, "continuation_sha256": CONTINUATION_SHA}


def verify_execution_manifest(path, expected_sha256, slots):
    raw = Path(path).read_bytes()
    require(isinstance(expected_sha256, str) and len(expected_sha256) == 64
        and hashlib.sha256(raw).hexdigest() == expected_sha256, "execution_manifest_hash")
    value = strict_event_json(raw.decode("utf-8"))
    require(value.get("sessions_sha256") == digest(slots), "execution_sessions_mismatch")
    require(value.get("runtime_config") == RUNTIME_CONFIG
        and all(type(value["runtime_config"][k]) in (int, float) and type(value["runtime_config"][k]) is not bool for k in RUNTIME_CONFIG), "execution_policy_mismatch")
    require(datetime.fromisoformat(value.get("deadline_utc", "")) == DEADLINE, "execution_deadline_mismatch")
    require(value.get("continuation_path") == CONTINUATION and value.get("continuation_sha256") == CONTINUATION_SHA
        and value.get("observed_response_models") == OBSERVED_RESPONSE_MODELS, "execution_continuation_policy")
    require(hashlib.sha256((ROOT / CONTINUATION).read_bytes()).hexdigest() == CONTINUATION_SHA, "continuation_changed")
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
    carry = verify_continuation(slots, ROOT / execution["continuation_path"], execution["continuation_sha256"])
    carry_ids = set(carry["finals"]); continuation_ids = carry["continuation_slot_ids"]
    continuation_slots = [s for s in slots if s["slot_id"] not in carry_ids]
    require(timeout_seconds == 180 and type(timeout_seconds) in (int, float), "invalid_timeout")
    require(isinstance(api_key, str) and len(api_key) >= 8 and not any(c.isspace() for c in api_key), "invalid_credential")
    require(api_key not in encoded(slots) and api_key not in str(output_dir), "credential_in_configuration")
    require(not ledger.halted, "ledger_halted")
    clock = _clock or time.monotonic; sleep = _sleep or asyncio.sleep
    utcnow = _utcnow or (lambda: datetime.now(timezone.utc))
    scrub = lambda text: text.replace(api_key, "[REDACTED_CREDENTIAL]").replace(json.dumps(api_key)[1:-1], "[REDACTED_CREDENTIAL]")
    directory = Path(output_dir); directory.mkdir(parents=True, exist_ok=False); (directory / "streams").mkdir()
    run_id = uuid.uuid4().hex; files = []
    manifest = {"schema": "retrace.adaption-v6j-run.v1", "run_id": run_id, "created_at": now(),
        "endpoint": ENDPOINT, "sessions_sha256": digest(slots), "slots": slots,
        "original_planned": len(slots), "planned": len(continuation_slots),
        "carryover_slot_ids": carry["issued_slot_ids"], "continuation_slot_ids": continuation_ids,
        "carryover_bindings": carry["bindings"], "original_run_id": carry["original_run_id"],
        "continuation_path": carry["continuation_path"], "continuation_sha256": carry["continuation_sha256"],
        "observed_response_models": OBSERVED_RESPONSE_MODELS,
        "earliest_next_admission_utc": carry["earliest_next_admission_utc"],
        "model_route_scope": "Observed provider route for future diagnostic requests only; not a vendor-verified alias or full-precision identity. Original mismatch remains failed.",
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
        ledger.record({"kind": "run_started", "run_id": run_id, "sessions_sha256": digest(slots), "planned": len(continuation_slots),
            "continuation_sha256": carry["continuation_sha256"], "execution_manifest_sha256": execution_manifest_sha256})
        stopped = False; stop_reasons = []; completed = deepcopy(carry["completed"]); finals = deepcopy(carry["finals"]); attempt_rows = []; issued = []
        states = {s["slot_id"]: {"attempts": 0, "not_before": 0.0} for s in slots}
        model_order = list(dict.fromkeys(s["model"] for s in slots))
        cursor = (model_order.index(carry["last_issued_model"]) + 1) % len(model_order) if carry["last_issued_model"] else 0
        models = {m: [s for s in slots if s["model"] == m] for m in model_order}
        next_admission = clock() + max(0.0, (datetime.fromisoformat(carry["earliest_next_admission_utc"]) - utcnow()).total_seconds())
        last_finished = None

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
            key = slot["slot_id"]; require(key not in finals and key not in carry_ids, "duplicate_or_carried_slot_outcome")
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
                parsed = strict_event_json(raw)
                require(parsed.get("model") == OBSERVED_RESPONSE_MODELS.get(slot["model"], slot["model"]), "response_model_mismatch")
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
                    expected_model = OBSERVED_RESPONSE_MODELS.get(slot["model"], slot["model"])
                    require(error_body.get("model", expected_model) == expected_model, "response_model_mismatch")
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
                "requested_model": slot["model"], "returned_model": parsed.get("model") if isinstance(parsed, dict) else None,
                "model_identity_policy": "prospectively_pinned_observed_route_not_verified_alias" if slot["model"] in OBSERVED_RESPONSE_MODELS else "exact_model_id",
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
                require(key not in carry_ids, "carried_slot_must_never_reissue")
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
        new_finals = {k: v for k, v in finals.items() if k not in carry_ids}
        new_completed = {k: v for k, v in completed.items() if k not in carry_ids}
        summary = {"schema": "retrace.adaption-v6j-summary.v1", "run_id": run_id, "status": "stopped" if stopped else "completed",
            "transport_revision": "serial_completion_paced_v6j_v1", "runtime_config": deepcopy(RUNTIME_CONFIG), "stream": True,
            "planned": len(continuation_slots), "original_planned": len(slots), "carried_over_slots": len(carry_ids),
            "carryover_slot_ids": carry["issued_slot_ids"], "continuation_slot_ids": continuation_ids,
            "continuation_sha256": carry["continuation_sha256"], "observed_response_models": OBSERVED_RESPONSE_MODELS,
            "models": dict(Counter(s["model"] for s in continuation_slots)), "issued_attempts": len(issued),
            "issued_slots": sum(bool(s["attempts"]) for s in states.values()), "responses": len(attempt_rows), "slot_outcomes": len(finals),
            "completed": len(new_completed), "eventual_completed": len(new_completed), "first_attempt_completed": sum(r["model_outcome"] == "completed" for r in first),
            "first_attempt_valid_terminal_records": sum(r["terminal_valid"] for r in first), "first_attempt_truncated": sum(r["model_outcome"] == "truncated_max_output_tokens" for r in first),
            "first_attempt_http_429": sum(r["model_outcome"] == "http_429" for r in first), "valid_terminal_records": sum(r["terminal_valid"] for r in attempt_rows),
            "eventual_terminal_slots": sum(r["terminal_valid"] for r in new_finals.values()), "truncated": sum(r["model_outcome"] == "truncated_max_output_tokens" for r in new_finals.values()),
            "http_429_attempts": sum(r["model_outcome"] == "http_429" for r in attempt_rows), "issued_operational_failures": sum(r["model_outcome"] == "operational_failure" for r in attempt_rows),
            "per_slot_operational_failures": sum(r["model_outcome"] == "operational_failure" and r["failure_scope"] == "slot" for r in attempt_rows),
            "dependency_skips": sum(r["model_outcome"] == "not_issued_dependency_failed" for r in new_finals.values()),
            "unissued_slot_ids": [s["slot_id"] for s in continuation_slots if not states[s["slot_id"]]["attempts"]],
            "issued_without_outcome_attempt_ids": sorted({a for a in ledger.attempts if a.startswith(run_id + ":")} - {r["attempt_id"] for r in attempt_rows}),
            "retries": len(issued) - sum(bool(s["attempts"]) for s in states.values()), "max_retries_per_slot": 2,
            "retry_policy": deepcopy(RETRY_POLICY), "stop_reasons": stop_reasons, "all_scheduled_outcomes_recorded": len(new_finals) == len(continuation_slots),
            "completion_definition": "Continuation scheduling closure only; six original issued outcomes remain in the separate stopped v6i segment without reinterpretation.", "actual_billed_credits": None}
        summary["slot_outcomes"] = len(new_finals)
        ledger.record({"kind": "run_closed", "run_id": run_id, "status": summary["status"], "issued_attempts": len(issued),
            "issued_slots": summary["issued_slots"], "unissued_slots": len(summary["unissued_slot_ids"]), "administrative": any(s.startswith("administrative_") for s in stop_reasons)})
        summary["budget"] = ledger.snapshot()
        sf = DurableJSONL(directory / "summary.json", scrub=scrub); files.append(sf); sf.write(summary)
        return summary
    finally:
        for f in files: f.close()
