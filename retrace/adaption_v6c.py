"""Additive Adaption transport: bounded rolling ledger, no retries or repair.

No network request occurs at import or planning time. Historical reservations
are never released. New completed calls settle at uncached reported-token cost;
all failures retain their full bound and stop dispatch globally.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

ENDPOINT = "https://api.prod.adaptionlabs.ai/api/v1/responses"
PRICING_URL = "https://docs.adaptionlabs.ai/inference-stacks/models/"
VERIFIED_DATE = "2026-11-14"
BASELINE = "40.98826224"
BASELINE_LEDGER = "results/eligibility-v5-budget-final.json"
BASELINE_SHA256 = "2fdf8a1494df6ececd4f22939a6e65528026e8b6817fd4b44053ef1e83fd1f90"
SCALE = Decimal(1_000_000_000)
CAP = 250_000_000_000
MODEL_PRICING = {
    "deepseek-v4-flash": {"input": "0.045", "output": "0.14", "context": 1048576},
    "gemma-4-31b-it": {"input": "0.09", "output": "0.34", "context": 256000},
    "glm-5.3-flash": {"input": "0.15", "output": "0.50", "context": 1048576,
                      "pricing_table_alias": "glm-53-flash"},
    "qwen3.8-27b": {"input": "0.039", "output": "1.25", "context": 262144},
    "glm-5.2": {"input": "1.40", "output": "4.40", "context": 1048575,
                "documentation_combined_context": 786432, "reservation_uses_larger_authenticated_input_limit": True},
}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def integer(value, low, high, code):
    require(type(value) is int and low <= value <= high, code)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def nano(value):
    return int((Decimal(str(value)) * SCALE).to_integral_value(rounding=ROUND_CEILING))


def credits(value):
    return format(Decimal(value) / SCALE, "f")


def request_bound(model, maximum):
    p = MODEL_PRICING[model]
    return nano((Decimal(p["context"]) * Decimal(p["input"]) + Decimal(maximum) * Decimal(p["output"])) / Decimal(1_000_000))


def usage_cost(model, usage, maximum):
    require(isinstance(usage, dict), "missing_usage")
    p = MODEL_PRICING[model]
    integer(usage.get("input_tokens"), 0, p["context"], "invalid_or_excess_input_usage")
    integer(usage.get("output_tokens"), 0, maximum, "invalid_or_excess_output_usage")
    if "total_tokens" in usage:
        integer(usage["total_tokens"], 0, p["context"] + maximum, "invalid_total_usage")
        require(usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"], "inconsistent_total_usage")
    # Reasoning/cache details are retained but never added again or discounted.
    for key, field, limit in (("input_tokens_details", "cached_tokens", usage["input_tokens"]),
                              ("output_tokens_details", "reasoning_tokens", usage["output_tokens"])):
        if usage.get(key) is not None:
            require(isinstance(usage[key], dict), "invalid_usage_details")
            if field in usage[key]:
                integer(usage[key][field], 0, limit, "invalid_usage_detail_count")
    return nano((Decimal(usage["input_tokens"]) * Decimal(p["input"]) + Decimal(usage["output_tokens"]) * Decimal(p["output"])) / Decimal(1_000_000))


def validate_slots(slots, *, canary=False):
    require(isinstance(slots, list) and bool(slots), "empty_slots")
    require(len(slots) <= 4650, "slot_ceiling_exceeded")
    seen = {}
    required = {"slot_id", "case_id", "model", "condition", "phase", "instructions", "input", "max_output_tokens"}
    allowed = required | {"temperature", "history_from", "metadata"}
    for slot in slots:
        require(isinstance(slot, dict) and required <= set(slot) <= allowed, "invalid_slot_fields")
        for key in required - {"max_output_tokens"}:
            require(isinstance(slot[key], str) and bool(slot[key].strip()), "invalid_slot_string")
        require(slot["model"] in MODEL_PRICING, "unverified_model_id")
        require(slot["slot_id"] not in seen, "duplicate_slot_id")
        integer(slot["max_output_tokens"], 1, 16384, "invalid_output_limit")
        temp = slot.get("temperature", 0)
        require(type(temp) in (int, float) and 0 <= temp <= 2, "invalid_temperature")
        dependencies = slot.get("history_from", [])
        require(isinstance(dependencies, list) and all(isinstance(x, str) for x in dependencies)
                and len(set(dependencies)) == len(dependencies), "invalid_history")
        for dependency in dependencies:
            require(isinstance(dependency, str) and dependency in seen, "history_not_earlier")
            prior = seen[dependency]
            require(prior["model"] == slot["model"] and prior["case_id"] == slot["case_id"], "history_scope_mismatch")
        if "metadata" in slot:
            require(isinstance(slot["metadata"], dict), "invalid_metadata")
        seen[slot["slot_id"]] = slot
    encoded(slots).encode("utf-8")
    if canary:
        require(len(slots) == 10 and Counter(s["model"] for s in slots) == Counter({m: 2 for m in MODEL_PRICING}), "canary_requires_two_per_model")
        require(all(not s.get("history_from") for s in slots), "canary_must_be_independent")
    return deepcopy(slots)


def plan(slots, *, canary=False):
    slots = validate_slots(slots, canary=canary)
    bounds = {m: sum(request_bound(m, s["max_output_tokens"]) for s in slots if s["model"] == m) for m in MODEL_PRICING}
    return {"schema": "retrace.adaption-v6c-plan.v1", "planned_slots": len(slots), "canary": canary,
            "sessions_sha256": digest(slots), "models": dict(Counter(s["model"] for s in slots)),
            "historical_carry_credits": BASELINE, "cumulative_cap_credits": "250",
            "full_plan_no_settlement_bound_credits": credits(sum(bounds.values())),
            "full_plan_bound_by_model": {m: credits(n) for m, n in bounds.items()},
            "rolling_reservation": True, "completion_of_entire_plan_not_guaranteed": True,
            "actual_billed_credits": None, "reservation_created": False}


class DurableJSONL:
    def __init__(self, path, *, append=False, scrub=lambda x: x):
        self.stream = Path(path).open("a" if append else "x", encoding="utf-8", newline="\n")
        self.scrub = scrub

    def write(self, value):
        self.stream.write(self.scrub(encoded(value)) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self):
        self.stream.close()


class RollingLedger:
    """Exclusive process lock plus hash-chained append-only new-phase accounting."""
    def __init__(self, directory, *, baseline_path):
        require(hashlib.sha256(Path(baseline_path).read_bytes()).hexdigest() == BASELINE_SHA256, "historical_ledger_changed")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.directory / "active.lock"
        self.lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self.file = None
        self.attempts = {}
        self.accounted = nano(BASELINE)
        self.halted = False
        self.seq, self.last_hash = 0, "0" * 64
        try:
            path = self.directory / "ledger.jsonl"
            exists = path.exists()
            if exists:
                raw = path.read_bytes()
                require(raw.endswith(b"\n") and bool(raw), "ledger_truncated")
                for line in raw.decode("utf-8").splitlines():
                    row = json.loads(line)
                    require(row["seq"] == self.seq + 1 and row["previous_sha256"] == self.last_hash, "ledger_chain_invalid")
                    require(row["sha256"] == digest({k:v for k,v in row.items() if k != "sha256"}), "ledger_hash_invalid")
                    self._apply(row["event"])
                    self.seq, self.last_hash = row["seq"], row["sha256"]
                require(not self.halted, "ledger_previously_halted")
                require(all(a["settled"] for a in self.attempts.values()), "ledger_has_unresolved_attempt")
            self.file = DurableJSONL(path, append=exists)
            if not exists:
                self.record({"kind": "initialize", "historical_credits": BASELINE, "historical_sha256": BASELINE_SHA256,
                             "cap_credits": "250", "authorization": "user raised cumulative cap; historical commitments preserved"})
        except Exception:
            self.close()
            raise

    def _apply(self, event):
        kind = event["kind"]
        if kind == "initialize":
            require(self.seq == 0 and event["historical_sha256"] == BASELINE_SHA256 and event["historical_credits"] == BASELINE and event["cap_credits"] == "250", "invalid_initial_ledger")
        elif kind == "reserve":
            key = event["attempt_id"]
            require(key not in self.attempts, "duplicate_reservation")
            bound = event["bound_nanocredits"]
            integer(bound, 1, CAP, "invalid_reservation")
            require(self.accounted + bound <= CAP, "cumulative_cap_exceeded")
            self.accounted += bound
            self.attempts[key] = {"bound": bound, "settled": False}
        elif kind == "settle":
            attempt = self.attempts[event["attempt_id"]]
            cost = event["accounted_nanocredits"]
            require(not attempt["settled"], "double_settlement")
            integer(cost, 0, attempt["bound"], "invalid_settlement")
            self.accounted += cost - attempt["bound"]
            attempt.update(settled=True, cost=cost)
        elif kind == "halt":
            self.halted = True
        elif kind not in ("run_started", "run_closed"):
            raise ValueError("unknown_ledger_event")

    def record(self, event):
        # Validate against a copy before writing; publish state only after fsync.
        before = deepcopy((self.attempts, self.accounted, self.halted))
        self._apply(event)
        after = deepcopy((self.attempts, self.accounted, self.halted))
        self.attempts, self.accounted, self.halted = before
        row = {"seq": self.seq + 1, "previous_sha256": self.last_hash, "at": now(), "event": event}
        row["sha256"] = digest(row)
        self.file.write(row)
        self.attempts, self.accounted, self.halted = after
        self.seq, self.last_hash = row["seq"], row["sha256"]

    def snapshot(self):
        return {"cumulative_cap_credits": "250", "historical_carry_credits": BASELINE,
                "accounted_credits": credits(self.accounted), "remaining_credits": credits(CAP-self.accounted),
                "attempt_reservations": len(self.attempts), "settled_attempts": sum(a["settled"] for a in self.attempts.values()),
                "unsettled_attempts": sum(not a["settled"] for a in self.attempts.values()),
                "ledger_sha256": self.last_hash, "halted": self.halted, "actual_billed_credits": None}

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
            self.lock_path.unlink()


def response_text(response):
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    require(isinstance(response.get("output"), list), "missing_output_text")
    pieces = []
    for item in response["output"]:
        if isinstance(item, dict) and item.get("type") == "message" and item.get("role") == "assistant":
            for part in item.get("content", []):
                if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    pieces.append(part["text"])
    return "".join(pieces)


class AiohttpTransport:
    """Fixed HTTPS destination, no redirects/proxies/cookies/retries."""
    def __init__(self, api_key, timeout_seconds=120):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.session = None

    async def __aenter__(self):
        import aiohttp
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
            trust_env=False, cookie_jar=aiohttp.DummyCookieJar(), connector=aiohttp.TCPConnector(limit=5))
        # aiohttp may retry an idempotent broken connection; POST is not in that
        # set. Disable the general retry hook too when exposed by this version.
        if hasattr(self.session, "_retry_connection"):
            self.session._retry_connection = False
        return self

    async def __aexit__(self, *_):
        await self.session.close()

    async def __call__(self, body):
        async with self.session.post(ENDPOINT, json=body, allow_redirects=False,
                                     headers={"Authorization": "Bearer " + self.api_key}) as response:
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                require(size <= 8_000_000, "response_size_limit")
                chunks.append(chunk)
            raw = b"".join(chunks)
            return response.status, raw.decode("utf-8", errors="strict")


async def run_slots(slots, *, api_key, output_dir, ledger, transport, canary=False,
                    model_interval=3.1, global_interval=3.1, concurrency=1, timeout_seconds=120):
    slots = validate_slots(slots, canary=canary)
    require(isinstance(api_key, str) and len(api_key) >= 8 and not any(c.isspace() for c in api_key), "invalid_credential")
    require(api_key not in encoded(slots) and api_key not in str(output_dir), "credential_in_configuration")
    integer(concurrency, 1, 5, "invalid_concurrency")
    require(0 <= model_interval <= 60 and 0 <= global_interval <= 60 and 0 < timeout_seconds <= 300, "invalid_timing")
    require(not ledger.halted, "ledger_halted")
    scrub = lambda text: text.replace(api_key, "[REDACTED_CREDENTIAL]").replace(json.dumps(api_key)[1:-1], "[REDACTED_CREDENTIAL]")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    run_id = uuid.uuid4().hex
    manifest = {**plan(slots, canary=canary), "run_id": run_id, "created_at": now(),
                "endpoint": ENDPOINT, "models_pricing": MODEL_PRICING, "pricing_source": PRICING_URL,
                "pricing_verified_date": VERIFIED_DATE, "model_interval_seconds": model_interval,
                "global_interval_seconds": global_interval, "concurrency": concurrency,
                "timeout_seconds": timeout_seconds, "retries": 0, "tools": False, "store": False,
                "agentic_memory": False, "budget_before": ledger.snapshot(), "slots": slots}
    files = []
    try:
        manifest_file = DurableJSONL(directory / "run.json", scrub=scrub); files.append(manifest_file)
        requests = DurableJSONL(directory / "requests.jsonl", scrub=scrub); files.append(requests)
        responses = DurableJSONL(directory / "responses.jsonl", scrub=scrub); files.append(responses)
        manifest_file.write(manifest)
        ledger.record({"kind": "run_started", "run_id": run_id, "sessions_sha256": digest(slots), "planned": len(slots)})
        stopped = asyncio.Event()
        dispatch_lock = asyncio.Lock()
        capacity = asyncio.Semaphore(concurrency)
        last_global = [None]
        completed = {}
        outcomes = []
        issued = []
        stop_reasons = []

        def stop(reason, attempt_id=None):
            stopped.set()
            if reason not in stop_reasons:
                stop_reasons.append(reason)
                try:
                    ledger.record({"kind": "halt", "run_id": run_id, "reason": reason, "attempt_id": attempt_id})
                except Exception:
                    if "ledger_write_failure" not in stop_reasons:
                        stop_reasons.append("ledger_write_failure")

        async def wait_until(deadline):
            # Windows event-loop timers can wake one clock tick early.
            while time.monotonic() < deadline and not stopped.is_set():
                await asyncio.sleep(max(0, deadline-time.monotonic()))

        async def worker(model):
            last_model = None
            for slot in (s for s in slots if s["model"] == model):
                if stopped.is_set():
                    return
                if last_model is not None:
                    await wait_until(last_model + model_interval)
                async with capacity:
                    async with dispatch_lock:
                        if stopped.is_set():
                            return
                        if last_global[0] is not None:
                            await wait_until(last_global[0] + global_interval)
                        if stopped.is_set():
                            return
                        messages = []
                        for dependency in slot.get("history_from", []):
                            if dependency not in completed:
                                stop("history_dependency_unavailable")
                                return
                            prior = completed[dependency]
                            messages.extend([{"role": "user", "content": prior["input"]}, {"role": "assistant", "content": prior["output_text"]}])
                        messages.append({"role": "user", "content": slot["input"]})
                        body = {"model": model, "instructions": slot["instructions"], "input": messages,
                                "max_output_tokens": slot["max_output_tokens"], "temperature": slot.get("temperature", 0),
                                "store": False, "agentic_memory": False, "tools": [], "tool_choice": "none"}
                        attempt_id = run_id + ":" + slot["slot_id"]
                        bound = request_bound(model, slot["max_output_tokens"])
                        if ledger.accounted + bound > CAP:
                            stop("cumulative_budget_stop")
                            return
                        try:
                            ledger.record({"kind": "reserve", "attempt_id": attempt_id, "run_id": run_id,
                                           "slot_id": slot["slot_id"], "model": model, "bound_nanocredits": bound})
                            requests.write({"attempt_id": attempt_id, "slot_id": slot["slot_id"], "at": now(),
                                            "request": body, "request_sha256": digest(body), "reserved_credits": credits(bound)})
                        except Exception:
                            stop("reservation_or_request_journal_failure", attempt_id)
                            return
                        last_global[0] = last_model = time.monotonic()
                        issued.append(slot["slot_id"])
                    started = time.monotonic()
                    raw, status, parsed, cost, text, error = None, None, None, None, "", None
                    try:
                        status, raw = await asyncio.wait_for(transport(body), timeout=timeout_seconds)
                        require(isinstance(raw, str), "non_text_response")
                        require(scrub(raw) == raw, "credential_echo_detected")
                        require(status == 200, "http_" + str(status) if type(status) is int else "invalid_http_status")
                        try:
                            parsed = json.loads(raw)
                        except (json.JSONDecodeError, ValueError):
                            raise ValueError("non_json_response")
                        require(isinstance(parsed, dict), "non_object_response")
                        require(parsed.get("status") == "completed", "response_not_completed")
                        require(not parsed.get("error"), "provider_response_error")
                        require(parsed.get("model") in (None, model), "response_model_mismatch")
                        cost = usage_cost(model, parsed.get("usage"), slot["max_output_tokens"])
                        require(cost <= bound, "reservation_bound_breached")
                        text = response_text(parsed)
                    except asyncio.TimeoutError:
                        error = "timeout"
                    except ValueError as exc:
                        # Only locally generated codes are exposed; provider raw
                        # error bodies remain scrubbed in their dedicated field.
                        known = {"non_text_response", "credential_echo_detected", "invalid_http_status", "non_json_response",
                                 "non_object_response", "response_not_completed", "provider_response_error", "response_model_mismatch",
                                 "missing_usage", "invalid_or_excess_input_usage", "invalid_or_excess_output_usage", "invalid_total_usage",
                                 "inconsistent_total_usage", "invalid_usage_details", "invalid_usage_detail_count",
                                 "reservation_bound_breached", "missing_output_text", "response_size_limit"}
                        code = str(exc)
                        error = code if code in known or (code.startswith("http_") and len(code) == 8 and code[5:].isdigit()) else "invalid_response"
                    except Exception:
                        error = "network_or_transport_failure"
                    if error:
                        stop(error, attempt_id)
                    row = {"run_id": run_id, "attempt_id": attempt_id, "slot_id": slot["slot_id"],
                           "case_id": slot["case_id"], "model": model, "condition": slot["condition"], "phase": slot["phase"],
                           "response_status": parsed.get("status") if isinstance(parsed, dict) else None,
                           "http_status": status, "error": error, "raw_response": scrub(raw) if isinstance(raw, str) else None,
                           "output_text": text if error is None else "", "usage": parsed.get("usage") if isinstance(parsed, dict) else None,
                           "latency_ms": round((time.monotonic()-started)*1000, 3), "at": now(),
                           "reserved_credits": credits(bound), "settled_credits": credits(cost) if error is None else None}
                    try:
                        responses.write(row)
                        if error is None:
                            ledger.record({"kind": "settle", "attempt_id": attempt_id, "accounted_nanocredits": cost,
                                           "response_sha256": digest(row), "basis": "completed_reported_usage_uncached_no_double_reasoning"})
                            completed[slot["slot_id"]] = {"input": slot["input"], "output_text": text}
                    except Exception:
                        stop("response_or_settlement_journal_failure", attempt_id)
                    outcomes.append(row)
                    if stopped.is_set():
                        return

        async def guarded_worker(model):
            try:
                await worker(model)
            except asyncio.CancelledError:
                stop("worker_cancelled")
            except BaseException:
                # Includes errors outside the HTTP block, e.g. dispatch/pacing
                # or local bookkeeping. Other workers must finish before files
                # close; an issued orphan retains its unresolved reservation.
                stop("unexpected_worker_failure")

        group = asyncio.gather(*(guarded_worker(m) for m in MODEL_PRICING if any(s["model"] == m for s in slots)), return_exceptions=True)
        try:
            await asyncio.shield(group)
        except asyncio.CancelledError:
            stop("run_cancelled")
            # Do not cancel an in-flight paid HTTP request and lose its response.
            # The per-request timeout still bounds this drain.
            await asyncio.shield(group)
        summary = {"schema": "retrace.adaption-v6c-summary.v1", "run_id": run_id,
                   "status": "stopped" if stopped.is_set() else "completed", "canary": canary,
                   "models": dict(Counter(s["model"] for s in slots)), "planned": len(slots), "issued": len(issued),
                   "responses": len(outcomes), "completed": len(completed), "stop_reasons": stop_reasons,
                   "issued_slot_ids": issued, "unissued_slot_ids": [s["slot_id"] for s in slots if s["slot_id"] not in issued],
                   "budget": ledger.snapshot(), "actual_billed_credits": None, "retries": 0}
        ledger.record({"kind": "run_closed", "run_id": run_id, "status": summary["status"], "issued": len(issued)})
        summary_file = DurableJSONL(directory / "summary.json", scrub=scrub); files.append(summary_file)
        summary_file.write(summary)
        return summary
    finally:
        for file in files:
            file.close()
