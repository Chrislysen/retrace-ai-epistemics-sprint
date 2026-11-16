"""Prospective serial v6k continuation transport. No network or credential access at import.

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
from .adaption_v6j import verify_prior_ledger as verify_original_i, BASELINE_LEDGER as I_LEDGER
from contextlib import aclosing

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "80.145946577"
BASELINE_LEDGER = "data/frontier-v6j-ledger-after-continuation.jsonl"
BASELINE_SHA256 = "92b06e40498d0a4a8950d3976e8933ad39e3c563a56b32d544a8e7e59558d6e0"
BASELINE_CHAIN = "1f8c44d309a55365eaafb6cad321b086dac8e0d179e561f10e585a765ef3e90c"
OBSERVED_RESPONSE_MODELS = {"qwen3.5-397b": "qwen3.5-397b-a17b-nvfp4"}
ORIGINAL_FREEZE = "data/frontier-v6i-freeze.json"
ORIGINAL_FREEZE_SHA = "156173e0dabc3a6f88c4301847f892f16bd6d0d73fd7c83c6d3dfc64b3a3a600"
CONTINUATION = "data/frontier-v6k-continuation.json"
CONTINUATION_SHA = "017a8e08c1c50d7199c0be5e93daa139c30a01e70cd966608de4eacae3488a51"
DEADLINE = datetime(2026, 11, 16, 3, 55, tzinfo=timezone.utc)
RUNTIME_CONFIG = {"global_concurrency": 1, "completion_delay_seconds": 4.0,
    "rate_limit_cooldown_seconds": 65.0, "max_retries": 2, "timeout_seconds": 180.0}
RETRY_POLICY = {"only_http_status": 429, "max_retries": 2,
    "minimum_cooldown_seconds": 65.0, "backoff": "max(65 seconds, Retry-After), after every 429 attempt completes",
    "flood_stop": None, "unknown_attempt_bound_retained": True, "quota_verified": False}
TRANSPORT_FAILURE_POLICY = {
    "origin": "transport_iterator_anext_only", "retry": False, "retain_full_bound": True,
    "post_header_allowed_types": ["aiohttp.client_exceptions.ServerDisconnectedError",
        "aiohttp.client_exceptions.ClientPayloadError", "aiohttp.client_exceptions.ClientConnectionResetError",
        "builtins.ConnectionResetError"],
    "allowed_statuses": "200 with text/event-stream; 408; 429; 500..599",
    "other_transport_exceptions": "global", "outer_180_second_timeout": "per_slot",
    "exception_messages_recorded": False,
}


def exception_name(exc):
    name = type(exc).__module__ + "." + type(exc).__qualname__
    return name if len(name) <= 160 and all(c.isascii() and (c.isalnum() or c in "._") for c in name) else "unprintable_exception_type"


def admitted_read_exception(exc):
    allowed = [ConnectionResetError]
    try:
        from aiohttp import client_exceptions as ce
        allowed.extend(getattr(ce, name) for name in
            ("ServerDisconnectedError", "ClientPayloadError", "ClientConnectionResetError") if hasattr(ce, name))
    except ImportError:
        pass  # Stdlib-only offline reproduction; live CLI requires pinned aiohttp.
    return type(exc) in allowed


class TransportOriginFailure(Exception):
    def __init__(self, exc, *, after_headers, admissible):
        self.exception_type = exception_name(exc)
        self.stage = "response_body" if after_headers else "before_validated_headers"
        self.admissible = admissible
        super().__init__("transport_origin_failure")


class InnerOperationTimeout(Exception):
    """An inner TimeoutError is distinct from the enclosing fixed deadline."""
    def __init__(self, exc):
        self.exception_type = exception_name(exc)
        super().__init__("inner_operation_timeout")


async def separate_inner_timeout(awaitable):
    try:
        return await awaitable
    except asyncio.TimeoutError as exc:
        raise InnerOperationTimeout(exc) from None


async def guard_transport(events, header_state):
    """Tag only exceptions raised while awaiting transport bytes, not consumers.

    Header admission is set by the frozen consumer's validated-header callback.
    Parser, journal, close/finalization and arbitrary exception failures cannot
    become transient merely because response headers previously arrived.
    """
    async with aclosing(events):
        iterator = events.__aiter__()
        while True:
            try:
                item = await iterator.__anext__()
            except StopAsyncIteration:
                return
            except Exception as exc:
                status = header_state["status"]
                known = header_state["validated"]
                eligible = known and (status == 200 and header_state["content_type"] == "text/event-stream"
                    or status in (408, 429) or type(status) is int and 500 <= status <= 599)
                raise TransportOriginFailure(exc, after_headers=known,
                    admissible=bool(eligible and admitted_read_exception(exc))) from None
            yield item


def verify_prior_ledger(path):
    """Carry all closed j commitments; no original global failure is rescued."""
    earlier = verify_original_i(ROOT / I_LEDGER)
    require(earlier["carry_credits"] == "47.653269434", "historical_i_carry")
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == BASELINE_SHA256 and raw.endswith(b"\n"), "prior_ledger_changed")
    previous = "0" * 64; accounted = nano("47.653269434"); attempts = {}; halts = set(); rows = []
    for seq, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        row = strict_event_json(line); rows.append(row)
        require(row["seq"] == seq and row["previous_sha256"] == previous, "prior_chain")
        require(row["sha256"] == digest({k: v for k, v in row.items() if k != "sha256"}), "prior_hash")
        previous = row["sha256"]; e = row["event"]; kind = e["kind"]
        if kind == "initialize":
            require(seq == 1 and e["historical_credits"] == "47.653269434" and e["cap_credits"] == "250", "prior_initialize")
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
            require(not a["settled"] and not a["retained_unknown"] and e["reason"] in
                {"timeout", "http_502", "http_504", "network_or_transport_failure"}, "prior_retention")
            a["retained_unknown"] = True
        elif kind == "halt":
            require(e["reason"] == "network_or_transport_failure" and e["attempt_id"] in attempts, "prior_halt")
            halts.add(e["attempt_id"])
        else: require(kind in ("run_started", "run_closed"), "prior_event")
        require(accounted <= CAP, "prior_cap")
    unknown = {k for k, a in attempts.items() if a["retained_unknown"]}
    require(len(rows) == 418 and previous == BASELINE_CHAIN and accounted == nano(BASELINE), "prior_carry")
    require(len(attempts) == 207 and sum(a["settled"] for a in attempts.values()) == 160
        and halts <= unknown and len(halts) == 1 and len(unknown) == 47, "prior_accounting_counts")
    require(rows[-1]["event"]["kind"] == "run_closed" and rows[-1]["event"]["status"] == "stopped", "prior_not_closed")
    return {"file_sha256": BASELINE_SHA256, "chain_sha256": previous, "carry_credits": BASELINE,
        "issued_attempts": 207, "settled_attempts": 160, "unknown_operational_attempts_retained": 47,
        "earlier_frozen_ledger": earlier,
        "cumulative_inherited_unsettled_attempts": earlier["cumulative_inherited_unsettled_attempts"] + 47,
        "authorization": "Prospective continuation of never-issued, nonfinalized slots; all definitive original i/j outcomes and unknown bounds remain unchanged."}


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
                    "cap_credits": "250", "authorization": "User-directed v6k continuation; no prior reservation released"})
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


def derive_carry(slots, receipt, contents):
    """Pure reconstruction from hash-authenticated prior segment bytes.

    Definitive observations and dependency skips are retained. Only never-issued
    global-stop placeholders are eligible for continuation. No gold is consulted.
    """
    index = {s["slot_id"]: s for s in slots}
    require(len(index) == len(slots), "duplicate_original_slot")
    finals = {}; completed = {}; bindings = []; issued_ids = []; last_model = None; run_ids = []
    for seg in receipt["source_segments"]:
        paths = seg["paths"]
        def obj(role): return strict_event_json(contents[paths[role]].decode("utf-8"))
        def rows(role):
            raw = contents[paths[role]]
            require(raw.endswith(b"\n"), "prior_partial_journal")
            return [strict_event_json(x.decode("utf-8")) for x in raw.splitlines()]
        run = obj("run_manifest"); summary = obj("summary"); audit = obj("audit")
        requests = rows("requests"); responses = rows("responses"); outcomes = rows("outcomes")
        run_ids.append(seg["run_id"])
        require(run["run_id"] == summary["run_id"] == seg["run_id"]
            and run["slots"] == slots and run["sessions_sha256"] == digest(slots), "prior_run_binding")
        require(summary["status"] == audit["schedule_status"] == "stopped"
            and audit["passed"] is True and audit["final_closed"] is True, "prior_not_audited_closed")
        expected_ids = set(index) - set(finals)
        require(len(outcomes) == len(expected_ids) and {r["slot_id"] for r in outcomes} == expected_ids,
            "prior_outcome_inventory")
        qmap = {r["attempt_id"]: r for r in requests}; rmap = {r["attempt_id"]: r for r in responses}
        require(len(qmap) == len(requests) == len(rmap) == len(responses)
            and set(qmap) == set(rmap), "prior_attempt_inventory")
        by_slot = {}
        for q in requests:
            sid = q["slot_id"]
            require(sid in expected_ids, "carried_slot_reissued")
            by_slot.setdefault(sid, []).append(q)
            require(q["request_sha256"] == digest(q["request"]), "prior_request_hash")
            last_model = q["request"]["model"]
        require(len(by_slot) == seg["issued_slots"] == summary["issued_slots"], "prior_issued_count")
        before = len(finals)
        for number, final in enumerate(outcomes, 1):
            sid = final["slot_id"]; slot = index[sid]
            require(final["run_id"] == seg["run_id"] and final.get("slot_final") is True, "prior_final_identity")
            if final["model_outcome"] == "not_issued_global_stop":
                require(final["issued"] is False and final["attempts_issued"] == 0
                    and sid not in by_slot and not final.get("output_text"), "nondefinitive_observation")
                continue
            require(sid not in finals, "duplicate_carried_final")
            if final["issued"]:
                qs = by_slot[sid]; aid = final["attempt_id"]; r = rmap[aid]
                require(aid == qs[-1]["attempt_id"] and final["attempts_issued"] == len(qs)
                    and final["first_attempt_id"] == qs[0]["attempt_id"]
                    and all(final.get(k) == v for k, v in r.items()), "carried_final_response_binding")
                body = build_body(slot, completed)
                for n, q in enumerate(qs, 1):
                    rr = rmap[q["attempt_id"]]
                    require(q["request"] == body and rr["slot_id"] == sid and rr["run_id"] == seg["run_id"]
                        and q["attempt_number"] == rr["attempt_number"] == n
                        and rr["first_attempt"] is (n == 1), "carried_actual_history_binding")
                    if n < len(qs): require(rr["model_outcome"] == "http_429", "non429_prior_retry")
                if r["model_outcome"] == "completed":
                    terminal = strict_event_json(r["raw_response"])
                    expected_model = slot["model"] if seg["segment"] == "i" else OBSERVED_RESPONSE_MODELS.get(slot["model"], slot["model"])
                    require(r["terminal_valid"] is True and r["error"] is None
                        and r["response_status"] == terminal["status"] == "completed"
                        and terminal["model"] == expected_model and response_text(terminal) == r["output_text"], "carried_completion_invalid")
                    completed[sid] = {"actual_input": body["input"][-1]["content"], "output_text": r["output_text"]}
                else:
                    require(r["model_outcome"] in {"operational_failure", "truncated_max_output_tokens", "http_429"}
                        and not r["output_text"], "carried_failure_not_rescued")
                issued_ids.append(sid)
            else:
                blocked = [d for d in slot_dependencies(slot) if d in finals and d not in completed]
                require(final["model_outcome"] == "not_issued_dependency_failed" and final["attempts_issued"] == 0
                    and final.get("first_attempt_id") is None and sid not in by_slot
                    and blocked and final["blocked_dependencies"] == blocked and not final["output_text"], "carried_dependency_skip_invalid")
            finals[sid] = deepcopy(final)
            bindings.append({"segment": seg["segment"], "slot_id": sid, "source_path": paths["outcomes"],
                "source_line_one_based": number, "row_sha256": digest(final), "attempt_id": final.get("attempt_id"),
                "model_outcome": final["model_outcome"]})
        require(len(finals) - before == seg["definitive_final_slots"], "prior_definitive_count")
    require(bindings == receipt["carried_final_outcomes"] and list(finals) == receipt["permanently_excluded_final_slot_ids"]
        and issued_ids == receipt["permanently_excluded_issued_slot_ids"], "carryover_selection_changed")
    continuation_ids = [s["slot_id"] for s in slots if s["slot_id"] not in finals]
    require(continuation_ids == receipt["continuation_slot_ids"] and len(continuation_ids) == receipt["continuation_slots"]
        and len(finals) == receipt["carried_final_slots"] and len(issued_ids) == receipt["carried_issued_slots"], "continuation_selection_changed")
    unavailable = set(finals) - set(completed); descendants = []
    for slot in slots:
        if slot["slot_id"] not in finals and any(d in unavailable for d in slot_dependencies(slot)):
            unavailable.add(slot["slot_id"]); descendants.append(slot["slot_id"])
    require(descendants == receipt["failed_producer_descendant_slot_ids"], "failed_descendants_changed")
    closure = strict_event_json(contents[receipt["baseline_snapshot_path"]].splitlines()[-1].decode("utf-8"))
    require(closure["event"]["kind"] == "run_closed" and run_ids == receipt["original_run_ids"]
        and run_ids[0] == receipt["original_run_id"], "prior_closure_order")
    return {"finals": finals, "completed": completed, "issued_slot_ids": issued_ids, "final_slot_ids": list(finals),
        "continuation_slot_ids": continuation_ids, "bindings": bindings, "failed_descendant_slot_ids": descendants,
        "last_issued_model": last_model, "original_run_id": run_ids[0], "original_run_ids": run_ids,
        "earliest_next_admission_utc": (datetime.fromisoformat(closure["at"]) + timedelta(seconds=4)).isoformat(),
        "continuation_path": CONTINUATION, "continuation_sha256": CONTINUATION_SHA}


def verify_continuation(slots, continuation_path=None, continuation_sha256=CONTINUATION_SHA):
    path = Path(continuation_path) if continuation_path is not None else ROOT / CONTINUATION
    require(path.resolve() == (ROOT / CONTINUATION).resolve(), "continuation_path_mismatch")
    raw = path.read_bytes()
    require(continuation_sha256 == CONTINUATION_SHA and hashlib.sha256(raw).hexdigest() == CONTINUATION_SHA, "continuation_hash")
    receipt = strict_event_json(raw.decode("utf-8"))
    require(receipt["schema"] == "retrace.frontier-v6k-continuation.v1"
        and receipt["prior_freeze_path"] == "data/frontier-v6j-freeze.json"
        and receipt["prior_freeze_sha256"] == "6fffc08ce31ac6aa19079be690a244a0e9b649d4a6281f7df8d53038c3811ea0"
        and receipt["observed_response_models"] == OBSERVED_RESPONSE_MODELS, "continuation_contract")
    require(receipt["baseline_snapshot_path"] == BASELINE_LEDGER and receipt["baseline_snapshot_sha256"] == BASELINE_SHA256
        and receipt["historical_conservative_carry_credits"] == BASELINE and receipt["cumulative_cap_credits"] == "250", "continuation_budget")
    require(len(slots) == receipt["full_planned_slots"] == 1800 and receipt["sessions_sha256"] == digest(slots)
        and receipt["sessions_path"] == "data/frontier-v6i-sessions.json", "original_schedule_changed")
    require([x["segment"] for x in receipt["source_segments"]] == ["i", "j"]
        and receipt["carried_issued_slots"] == 213 and receipt["carried_final_slots"] == 224
        and receipt["continuation_slots"] == 1576, "continuation_boundary")
    def checked(name, expected):
        target = ROOT / name
        require(isinstance(name, str) and not Path(name).is_absolute() and ".." not in Path(name).parts
            and target.resolve().is_relative_to(ROOT.resolve()), "prior_path_escape")
        data = target.read_bytes(); require(hashlib.sha256(data).hexdigest() == expected, "prior_journal_changed")
        return data
    contents = {name: checked(name, sha) for name, sha in receipt["prior_journal_files"].items()}
    for seg in receipt["source_segments"]:
        checked(seg["freeze_path"], seg["freeze_sha256"])
        require(set(seg["paths"]) == set(seg["sha256"]) == {"run_manifest", "requests", "responses", "outcomes", "summary", "audit", "ledger"}, "prior_roles")
        for role, name in seg["paths"].items():
            require(receipt["prior_journal_files"].get(name) == seg["sha256"][role], "prior_segment_hash_binding")
    require(receipt["prior_journal_files"].get(BASELINE_LEDGER) == BASELINE_SHA256, "prior_snapshot_binding")
    return derive_carry(slots, receipt, contents)


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
    manifest = {"schema": "retrace.adaption-v6k-run.v1", "run_id": run_id, "created_at": now(),
        "endpoint": ENDPOINT, "sessions_sha256": digest(slots), "slots": slots,
        "original_planned": len(slots), "planned": len(continuation_slots),
        "carryover_slot_ids": carry["final_slot_ids"], "carryover_issued_slot_ids": carry["issued_slot_ids"], "continuation_slot_ids": continuation_ids,
        "carryover_bindings": carry["bindings"], "original_run_id": carry["original_run_id"], "original_run_ids": carry["original_run_ids"],
        "continuation_path": carry["continuation_path"], "continuation_sha256": carry["continuation_sha256"],
        "observed_response_models": OBSERVED_RESPONSE_MODELS,
        "earliest_next_admission_utc": carry["earliest_next_admission_utc"],
        "model_route_scope": "Observed provider route for future diagnostic requests only; not a vendor-verified alias or full-precision identity. Original mismatch remains failed.",
        "execution_manifest_path": str(execution_manifest_path), "execution_manifest_sha256": execution_manifest_sha256,
        "runtime_config": deepcopy(RUNTIME_CONFIG), "deadline_utc": DEADLINE.isoformat(),
        "transport_failure_policy": deepcopy(TRANSPORT_FAILURE_POLICY),
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
            header_state = {"validated": False, "status": None, "content_type": None}
            transport_exception_type = None; transport_failure_stage = None; exception_type = None
            awaiting_outer_deadline = False
            def observe(headers):
                nonlocal observed_429
                integer(headers["http_status"], 100, 599, "stream_invalid_headers")
                header_state.update(validated=True, status=headers["http_status"],
                    content_type=headers["content_type"].split(";", 1)[0].strip().lower())
                if headers["http_status"] == 429: observed_429 = retry_delay(headers.get("retry_after"), utc_now=utcnow())
            try:
                journal = StreamJournal(directory / "streams" / (hashlib.sha256(aid.encode()).hexdigest() + ".sse"), api_key)
                events = transport(body)
                awaiting_outer_deadline = True
                status, raw = await asyncio.wait_for(separate_inner_timeout(
                    consume_stream(guard_transport(events, header_state), journal, decoder, observe)), timeout=180)
                awaiting_outer_deadline = False
                require(scrub(raw) == raw, "credential_echo_detected")
                parsed = strict_event_json(raw)
                require(parsed.get("model") == OBSERVED_RESPONSE_MODELS.get(slot["model"], slot["model"]), "response_model_mismatch")
                cost = usage_cost(slot["model"], parsed.get("usage"), slot["max_output_tokens"])
                require(cost <= bound, "reservation_bound_breached"); text = response_text(parsed)
                outcome = "completed" if parsed["status"] == "completed" else "truncated_max_output_tokens"
            except TransportOriginFailure as exc:
                transport_exception_type = exception_type = exc.exception_type; transport_failure_stage = exc.stage
                error = "post_headers_transport_read_failure" if exc.admissible else "network_or_transport_failure"
            except InnerOperationTimeout as exc:
                error = "network_or_transport_failure"; exception_type = exc.exception_type
            except asyncio.TimeoutError as exc:
                error = "timeout" if awaiting_outer_deadline else "network_or_transport_failure"
                exception_type = exception_name(exc)
            except UnicodeError as exc: error = "stream_invalid_utf8"; exception_type = exception_name(exc)
            except ValueError as exc:
                exception_type = exception_name(exc)
                code = str(exc); error = code if code in KNOWN_ERRORS or (code.startswith("http_") and len(code) == 8 and code[5:].isdigit()) else "invalid_response"
            except Exception as exc: error = "network_or_transport_failure"; exception_type = exception_name(exc)
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
            transient = error in ("timeout", "post_headers_transport_read_failure") or (error == "http_" + str(status) and type(status) is int and (status == 408 or 500 <= status <= 599))
            scope = None if error is None else "slot" if (is_429 or transient) else "global"
            delay = max(observed_429 or 0, retry_delay(getattr(journal, "retry_after", None), utc_now=utcnow())) if status == 429 else None
            row = {"run_id": run_id, "attempt_id": aid, "attempt_number": number, "first_attempt": number == 1,
                "slot_id": slot["slot_id"], "case_id": slot["case_id"], "model": slot["model"], "condition": slot["condition"], "phase": slot["phase"],
                "issued": True, "terminal_valid": error is None, "model_outcome": outcome if error is None else "http_429" if is_429 else "operational_failure",
                "failure_scope": scope, "response_status": parsed.get("status") if isinstance(parsed, dict) else None,
                "requested_model": slot["model"], "returned_model": parsed.get("model") if isinstance(parsed, dict) else None,
                "model_identity_policy": "prospectively_pinned_observed_route_not_verified_alias" if slot["model"] in OBSERVED_RESPONSE_MODELS else "exact_model_id",
                "http_status": status, "error": error, "raw_response": scrub(raw) if isinstance(raw, str) else None,
                "exception_type": exception_type, "transport_exception_type": transport_exception_type,
                "transport_failure_stage": transport_failure_stage,
                "transport_headers_validated": header_state["validated"], "transport_content_type": header_state["content_type"],
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
        summary = {"schema": "retrace.adaption-v6k-summary.v1", "run_id": run_id, "status": "stopped" if stopped else "completed",
            "transport_revision": "serial_completion_paced_v6k_v1", "runtime_config": deepcopy(RUNTIME_CONFIG), "stream": True,
            "planned": len(continuation_slots), "original_planned": len(slots), "carried_over_slots": len(carry_ids),
            "carryover_slot_ids": carry["final_slot_ids"], "carryover_issued_slot_ids": carry["issued_slot_ids"], "continuation_slot_ids": continuation_ids,
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
            "transport_failure_policy": deepcopy(TRANSPORT_FAILURE_POLICY),
            "completion_definition": "Continuation scheduling closure only; all definitive original i/j outcomes remain unchanged in their separately stopped segments.", "actual_billed_credits": None}
        summary["slot_outcomes"] = len(new_finals)
        ledger.record({"kind": "run_closed", "run_id": run_id, "status": summary["status"], "issued_attempts": len(issued),
            "issued_slots": summary["issued_slots"], "unissued_slots": len(summary["unissued_slot_ids"]), "administrative": any(s.startswith("administrative_") for s in stop_reasons)})
        summary["budget"] = ledger.snapshot()
        sf = DurableJSONL(directory / "summary.json", scrub=scrub); files.append(sf); sf.write(summary)
        return summary
    finally:
        for f in files: f.close()
