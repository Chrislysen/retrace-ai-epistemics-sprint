"""Prospective serial v6n host-interruption recovery transport. No network or credential access at import.

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
    AiohttpTransport, ENDPOINT, KNOWN_ERRORS, MODEL_PRICING, PRICING_URL,
    VERIFIED_DATE, DurableJSONL, StreamJournal, SSEDecoder, build_body,
    consume_stream, credits, digest, encoded, integer, nano, now,
    request_bound, require, response_text, slot_dependencies, strict_event_json,
    usage_cost, validate_slots,
)
from . import recovery_v6n as recovery
from contextlib import aclosing

ROOT = Path(__file__).resolve().parents[1]
CAP = 750_000_000_000
PREVIOUS_CAP = 750_000_000_000
BASELINE_LEDGER = "data/frontier-v6m-ledger-after-interruption.jsonl"
OBSERVED_RESPONSE_MODELS = {"qwen3.5-397b": "qwen3.5-397b-a17b-nvfp4"}
ORIGINAL_FREEZE = "data/frontier-v6i-freeze.json"
ORIGINAL_FREEZE_SHA = "156173e0dabc3a6f88c4301847f892f16bd6d0d73fd7c83c6d3dfc64b3a3a600"
CONTINUATION = "data/frontier-v6n-continuation.json"
DEADLINE = datetime(2026, 11, 16, 6, 56, tzinfo=timezone.utc)
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


def read_continuation(path, expected_sha256):
    return recovery.read_receipt(path, expected_sha256)


def verify_prior_ledger(path, *, continuation_path, continuation_sha256):
    return recovery.verify_prior_ledger(path, continuation_path=continuation_path,
        continuation_sha256=continuation_sha256)


class RollingLedger:
    """Independent exclusive 750-credit ledger; never changes frozen globals."""
    def __init__(self, directory, *, baseline_path, continuation_path, continuation_sha256):
        self.prior_evidence = verify_prior_ledger(baseline_path, continuation_path=continuation_path,
            continuation_sha256=continuation_sha256)
        self.baseline = self.prior_evidence["carry_credits"]
        self.baseline_sha256 = self.prior_evidence["file_sha256"]
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.directory / "active.lock"; self.lock_fd = None; self.file = None
        self.attempts = {}; self.accounted = nano(self.baseline); self.halted = False
        self.started = False; self.closed = False; self.run_id = None; self.seq = 0; self.last_hash = "0" * 64
        require(0 <= self.accounted <= PREVIOUS_CAP, "invalid_prior_cap")
        try:
            path = self.directory / "ledger.jsonl"; require(not path.exists(), "ledger_must_be_new")
            self.lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            self.file = DurableJSONL(path)
            self.record({"kind": "initialize", "historical_credits": self.baseline, "historical_sha256": self.baseline_sha256,
                "cap_credits": "750", "authorization": "Prospective750 cumulative ceiling selected within expanded user authorization while preserving a buffer; after independently authenticated unclosed k and m prefixes; both orphans failed without retry and all prior reservations retained"})
        except BaseException:
            self.close(); raise

    def _apply(self, event):
        kind = event["kind"]
        require(not self.closed, "ledger_already_closed")
        if kind == "initialize":
            require(self.seq == 0 and event["historical_sha256"] == self.baseline_sha256
                and event["historical_credits"] == self.baseline and event["cap_credits"] == "750", "invalid_initial_ledger")
        elif kind == "run_started":
            require(not self.started and not self.halted, "ledger_already_started")
            self.started = True; self.run_id = event["run_id"]
        elif kind == "reserve":
            require(self.started and not self.halted and event["run_id"] == self.run_id, "ledger_reserve_state")
            key = event["attempt_id"]; bound = event["bound_nanocredits"]
            integer(bound, 1, CAP, "invalid_reservation"); require(key not in self.attempts, "duplicate_reservation")
            require(self.accounted + bound <= CAP, "cumulative_cap_exceeded")
            self.attempts[key] = {"bound": bound, "kind": None, "cost": None}; self.accounted += bound
        elif kind in ("settle", "retain_unknown", "retain_429"):
            item = self.attempts[event["attempt_id"]]
            require(item["kind"] is None, "retained_attempt_cannot_settle")
            require(isinstance(event.get("response_sha256"), str) and len(event["response_sha256"]) == 64, "response_binding")
            if kind == "settle":
                cost = event["accounted_nanocredits"]; integer(cost, 0, item["bound"], "invalid_settlement")
                self.accounted += cost - item["bound"]; item["cost"] = cost
            else: require(isinstance(event.get("reason"), str) and bool(event["reason"]), "unknown_retention_evidence")
            item["kind"] = kind
        elif kind == "halt":
            require(self.started and event["run_id"] == self.run_id, "halt_run_binding"); self.halted = True
        elif kind == "run_closed":
            require(self.started and event["run_id"] == self.run_id and event["status"] == ("stopped" if self.halted else "completed")
                and (self.halted or all(a["kind"] is not None for a in self.attempts.values())), "unresolved_or_misclassified_closure")
            self.closed = True
        else: raise ValueError("unknown_ledger_event")
        require(0 <= self.accounted <= CAP, "cumulative_cap_exceeded")

    def record(self, event):
        names = ("attempts", "accounted", "halted", "started", "closed", "run_id")
        before = deepcopy({n: getattr(self, n) for n in names})
        try:
            self._apply(event); after = deepcopy({n: getattr(self, n) for n in names})
        finally:
            for n, value in before.items(): setattr(self, n, value)
        row = {"seq": self.seq + 1, "previous_sha256": self.last_hash, "at": now(), "event": event}
        row["sha256"] = digest(row); self.file.write(row)
        for n, value in after.items(): setattr(self, n, value)
        self.seq += 1; self.last_hash = row["sha256"]

    def snapshot(self):
        kinds = Counter(a["kind"] for a in self.attempts.values())
        return {"cumulative_cap_credits": "750", "historical_carry_credits": self.baseline,
            "accounted_credits": credits(self.accounted), "remaining_credits": credits(CAP-self.accounted),
            "attempt_reservations": len(self.attempts), "settled_attempts": kinds["settle"],
            "unsettled_attempts": len(self.attempts)-kinds["settle"], "unknown_429_attempts_retained": kinds["retain_429"],
            "unknown_operational_attempts_retained": kinds["retain_unknown"],
            "cumulative_inherited_unsettled_attempts": self.prior_evidence["cumulative_inherited_unsettled_attempts"],
            "ledger_sha256": self.last_hash, "halted": self.halted, "actual_billed_credits": None}

    def close(self):
        if self.file is not None: self.file.close(); self.file = None
        if self.lock_fd is not None:
            os.close(self.lock_fd); self.lock_fd = None; self.lock_path.unlink()


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


def verify_continuation(slots, continuation_path, continuation_sha256):
    return recovery.verify_continuation(slots, continuation_path, continuation_sha256)


def verify_execution_manifest(path, expected_sha256, slots):
    raw = Path(path).read_bytes()
    require(isinstance(expected_sha256, str) and len(expected_sha256) == 64
        and hashlib.sha256(raw).hexdigest() == expected_sha256, "execution_manifest_hash")
    value = strict_event_json(raw.decode("utf-8"))
    require(value.get("sessions_sha256") == digest(slots), "execution_sessions_mismatch")
    require(value.get("runtime_config") == RUNTIME_CONFIG
        and all(type(value["runtime_config"][k]) in (int, float) and type(value["runtime_config"][k]) is not bool for k in RUNTIME_CONFIG), "execution_policy_mismatch")
    require(datetime.fromisoformat(value.get("deadline_utc", "")) == DEADLINE, "execution_deadline_mismatch")
    require(value.get("continuation_path") == CONTINUATION and isinstance(value.get("continuation_sha256"), str)
        and value.get("observed_response_models") == OBSERVED_RESPONSE_MODELS, "execution_continuation_policy")
    require(value.get("cumulative_cap_credits") == "750", "execution_budget_mismatch")
    receipt = read_continuation(ROOT / CONTINUATION, value["continuation_sha256"])
    require(receipt["sessions_sha256"] == digest(slots), "original_schedule_changed")
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
    require(ledger.prior_evidence["continuation_sha256"] == execution["continuation_sha256"]
        and ledger.prior_evidence["continuation_path"] == execution["continuation_path"], "ledger_continuation_mismatch")
    clock = _clock or time.monotonic; sleep = _sleep or asyncio.sleep
    utcnow = _utcnow or (lambda: datetime.now(timezone.utc))
    scrub = lambda text: text.replace(api_key, "[REDACTED_CREDENTIAL]").replace(json.dumps(api_key)[1:-1], "[REDACTED_CREDENTIAL]")
    directory = Path(output_dir); directory.mkdir(parents=True, exist_ok=False); (directory / "streams").mkdir()
    run_id = uuid.uuid4().hex; files = []
    manifest = {"schema": "retrace.adaption-v6n-run.v1", "run_id": run_id, "created_at": now(),
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
        summary = {"schema": "retrace.adaption-v6n-summary.v1", "run_id": run_id, "status": "stopped" if stopped else "completed",
            "transport_revision": "serial_completion_paced_v6n_v1", "runtime_config": deepcopy(RUNTIME_CONFIG), "stream": True,
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
            "completion_definition": "Continuation scheduling closure only; all definitive observations remain unchanged in the original i/j stopped segments and the unclosed k and m prefixes. Both unanswered issued attempts are separate derived failures, not a provider response.", "actual_billed_credits": None}
        summary["slot_outcomes"] = len(new_finals)
        ledger.record({"kind": "run_closed", "run_id": run_id, "status": summary["status"], "issued_attempts": len(issued),
            "issued_slots": summary["issued_slots"], "unissued_slots": len(summary["unissued_slot_ids"]), "administrative": any(s.startswith("administrative_") for s in stop_reasons)})
        summary["budget"] = ledger.snapshot()
        sf = DurableJSONL(directory / "summary.json", scrub=scrub); files.append(sf); sf.write(summary)
        return summary
    finally:
        for f in files: f.close()
