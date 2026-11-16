"""Additive Adaption transport: bounded rolling ledger, no retries or repair.

No network request occurs at import or planning time. Historical reservations
are never released. New completed calls settle at uncached reported-token cost;
transport failures retain their full bound and stop dispatch globally. A final
max-output-token truncation with valid usage is an observed failed model outcome,
settled separately without retry or conversion to a complete answer.
"""
from __future__ import annotations

import asyncio
import codecs
from contextlib import aclosing
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
from retrace.adaption_v6e import verify_prior_ledger as verify_v6d_ledger
from retrace.pacing_v6f import (AdmissionWindow, estimate_request, WINDOW_SECONDS,
    TOKEN_BUDGET, MAX_STARTS, SOLO_LIMIT)

ENDPOINT = "https://api.prod.adaptionlabs.ai/api/v1/responses"
PRICING_URL = "https://docs.adaptionlabs.ai/inference-stacks/models/"
VERIFIED_DATE = "2026-11-14"
BASELINE = "42.997746364"
BASELINE_LEDGER = "results/frontier-v6e/budget/ledger.jsonl"
BASELINE_SHA256 = "7e49f85ab98be0e694a4835c7814484e8ad58b701b6b18e502ec4918199da5ff"
PRIOR_CARRY = "42.940083848"
V6C_LEDGER = "results/frontier-v6c/budget/ledger.jsonl"
V6C_LEDGER_SHA256 = "b176a2b610f4ac21fcdbb3202a0aa5bf3cc9a58159258c0fa33bcd982d4e5d76"
V6D_LEDGER = "results/frontier-v6d/budget/ledger.jsonl"
V6D_LEDGER_SHA256 = "5b3c4c99fcc373c998e2e93def456eb29864ecf65786974a42dbb7c5b5c35439"
ADMISSION_POLICY = {"window_seconds":WINDOW_SECONDS,"reference_token_budget":TOKEN_BUDGET,
    "max_starts":MAX_STARTS,"solo_weight_limit":SOLO_LIMIT,"initial_cooldown_seconds":61.0,
    "quota_verified":False,"basis":"Conservative local policy; provider quota is not documented."}
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


def verify_prior_ledger(path):
    """Replay all three stopped ledgers; never settle historical failures."""
    v6d = verify_v6d_ledger(Path(__file__).resolve().parents[1] / V6D_LEDGER)
    require(v6d["carry_credits"] == PRIOR_CARRY, "earlier_carry_mismatch")
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == BASELINE_SHA256, "prior_ledger_changed")
    require(raw.endswith(b"\n"), "prior_ledger_truncated")
    previous, accounted, attempts, halted = "0"*64, nano(PRIOR_CARRY), {}, False
    for seq, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        row = json.loads(line)
        require(row["seq"] == seq and row["previous_sha256"] == previous, "prior_ledger_chain")
        require(row["sha256"] == digest({k:v for k,v in row.items() if k != "sha256"}), "prior_ledger_hash")
        previous = row["sha256"]
        event = row["event"]
        if event["kind"] == "initialize":
            require(seq == 1 and event["historical_credits"] == PRIOR_CARRY and event["cap_credits"] == "250", "prior_ledger_initial")
        elif event["kind"] == "reserve":
            key, bound = event["attempt_id"], event["bound_nanocredits"]
            require(key not in attempts and type(bound) is int and bound > 0, "prior_reservation_invalid")
            attempts[key] = {"bound":bound,"settled":False}; accounted += bound
        elif event["kind"] == "settle":
            attempt = attempts[event["attempt_id"]]; cost = event["accounted_nanocredits"]
            require(not attempt["settled"] and type(cost) is int and 0 <= cost <= attempt["bound"], "prior_settlement_invalid")
            accounted += cost-attempt["bound"]; attempt["settled"] = True
        elif event["kind"] == "halt": halted = True
        else: require(event["kind"] in ("run_started","run_closed"), "prior_event_unknown")
        require(accounted <= CAP, "prior_cap_breach")
    unknown = [a for a in attempts.values() if not a["settled"]]
    require(halted and len(attempts) == 7 and len(unknown) == 1 and accounted == nano(BASELINE), "prior_carry_mismatch")
    return {"file_sha256":BASELINE_SHA256,"chain_sha256":previous,"carry_credits":credits(accounted),
            "issued_attempts":len(attempts),"settled_attempts":len(attempts)-len(unknown),
            "unknown_full_bounds_retained":len(unknown),
            "unknown_bound_credits":credits(sum(a["bound"] for a in unknown)),
            "earlier_frozen_ledger":v6d,
            "cumulative_inherited_unsettled_attempts":len(unknown)+v6d["cumulative_inherited_unsettled_attempts"]}


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
        integer(slot["max_output_tokens"], 1, 65536, "invalid_output_limit")
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
    return {"schema": "retrace.adaption-v6f-plan.v1", "planned_slots": len(slots), "canary": canary,
            "sessions_sha256": digest(slots), "models": dict(Counter(s["model"] for s in slots)),
            "historical_carry_credits": BASELINE, "cumulative_cap_credits": "250",
            "full_plan_no_settlement_bound_credits": credits(sum(bounds.values())),
            "full_plan_bound_by_model": {m: credits(n) for m, n in bounds.items()},
            "rolling_reservation": True, "completion_of_entire_plan_not_guaranteed": True,
            "actual_billed_credits": None, "reservation_created": False,
            "admission_policy":deepcopy(ADMISSION_POLICY)}


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
        self.prior_evidence = verify_prior_ledger(baseline_path)
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


class StreamJournal:
    """Durable received-byte evidence with cross-chunk exact-key redaction."""
    MAX_BYTES = 32_000_000
    def __init__(self, path, api_key):
        self.path = Path(path)
        self.file = self.path.open("xb")
        self.key = api_key.encode("utf-8")
        self.buffer = b""
        self.received = 0
        self.original_hash = hashlib.sha256()
        self.saved_hash = hashlib.sha256()
        self.redacted = False
        self.closed = False
        self.http_status = None

    def _save(self, value):
        if value:
            self.file.write(value); self.file.flush(); os.fsync(self.file.fileno())
            self.saved_hash.update(value)

    def feed(self, chunk):
        require(isinstance(chunk, bytes), "invalid_stream_chunk")
        self.received += len(chunk); self.original_hash.update(chunk)
        self.buffer += chunk
        while self.key in self.buffer:
            where = self.buffer.index(self.key)
            self._save(self.buffer[:where] + b"[REDACTED_CREDENTIAL]")
            self.buffer = self.buffer[where+len(self.key):]
            self.redacted = True
        # Keep enough suffix to detect a credential split across network chunks.
        safe = max(0, len(self.buffer)-len(self.key)+1)
        self._save(self.buffer[:safe]); self.buffer = self.buffer[safe:]
        require(self.received <= self.MAX_BYTES, "stream_size_limit")
        require(not self.redacted, "credential_echo_detected")

    def close(self):
        if not self.closed:
            try:
                self._save(self.buffer); self.buffer=b""
            finally:
                self.file.close(); self.closed=True

    def metadata(self):
        return {"raw_stream_path":str(self.path),"received_bytes":self.received,
                "received_sha256":self.original_hash.hexdigest(),"saved_sha256":self.saved_hash.hexdigest(),
                "credential_redacted":self.redacted,"closed":self.closed,"http_status":self.http_status}


def strict_event_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result, "stream_duplicate_json_key")
            result[key]=value
        return result
    def nonfinite(_): raise ValueError("stream_nonfinite_json")
    try:
        value=json.loads(text,object_pairs_hook=pairs,parse_constant=nonfinite)
    except json.JSONDecodeError as exc:
        raise ValueError("stream_invalid_json") from exc
    require(isinstance(value,dict),"stream_nonobject_event")
    return value


class SSEDecoder:
    """Strict terminal response; deltas alone never prove completion/truncation."""
    def __init__(self):
        self.decoder=codecs.getincrementaldecoder("utf-8")("strict")
        self.buffer="";self.data=[];self.event_name=None;self.frame_started=False
        self.event_count=0;self.terminal=None;self.done=False;self.final_response=None
        self.last_sequence=None;self.response_id=None;self.deltas=[];self.delta_chars=0

    def _event(self):
        if not self.data:
            self.event_name=None;self.frame_started=False
            return
        payload="\n".join(self.data)
        self.data=[];self.frame_started=False
        event_name=self.event_name;self.event_name=None
        if payload == "[DONE]":
            require(self.terminal in ("response.completed","response.incomplete") and self.final_response is not None and not self.done,"stream_unproven_done")
            self.done=True
            return
        require(self.terminal is None and not self.done,"stream_event_after_terminal")
        event=strict_event_json(payload)
        kind=event.get("type")
        require(isinstance(kind,str) and bool(kind),"stream_missing_type")
        require(event_name in (None,"message",kind),"stream_event_type_mismatch")
        self.event_count += 1
        require(self.event_count <= 100000,"stream_event_limit")
        if "sequence_number" in event:
            sequence=event["sequence_number"]
            integer(sequence,0,10**9,"stream_invalid_sequence")
            require(self.last_sequence is None or sequence > self.last_sequence,"stream_sequence_not_increasing")
            self.last_sequence=sequence
        response=event.get("response")
        if isinstance(response,dict) and isinstance(response.get("id"),str):
            ident=response["id"]
            require(self.response_id in (None,ident),"stream_response_id_changed")
            self.response_id=ident
        if kind == "response.output_text.delta":
            require(isinstance(event.get("delta"),str),"stream_invalid_delta")
            self.deltas.append(event["delta"])
            self.delta_chars += len(event["delta"])
            require(self.delta_chars <= 2_000_000,"stream_text_limit")
        if kind in ("error","response.failed","response.cancelled"):
            self.terminal=kind
            raise ValueError("stream_terminal_error")
        if kind in ("response.completed","response.incomplete"):
            self.terminal=kind
            require(isinstance(response,dict),"stream_invalid_terminal_response")
            status=response.get("status")
            if status == "incomplete":
                require(isinstance(response.get("incomplete_details"),dict)
                        and response["incomplete_details"].get("reason") == "max_output_tokens",
                        "stream_unaccepted_incomplete_reason")
            else:
                require(status == "completed" and kind == "response.completed","stream_invalid_terminal_response")
            require(isinstance(response.get("id"),str) and bool(response["id"]),"stream_missing_response_id")
            require(not response.get("error"),"stream_completed_with_error")
            text=response_text(response)
            if self.deltas:
                require("".join(self.deltas) == text,"stream_text_mismatch")
            self.final_response=deepcopy(response)

    def _line(self,line):
        if line == "": self._event();return
        if line.startswith(":"): return
        self.frame_started=True
        field,sep,value=line.partition(":")
        if value.startswith(" "): value=value[1:]
        if field == "data": self.data.append(value if sep else "")
        elif field == "event":
            require(self.event_name is None,"stream_duplicate_event_field")
            self.event_name=value
        # Other SSE transport fields are retained in raw bytes, never executed.
        require(sum(len(x) for x in self.data) <= 2_000_000,"stream_frame_limit")

    def feed(self,chunk):
        self.buffer += self.decoder.decode(chunk,final=False)
        while True:
            positions=[p for p in (self.buffer.find("\n"),self.buffer.find("\r")) if p >= 0]
            if not positions: break
            pos=min(positions)
            if self.buffer[pos] == "\r" and pos == len(self.buffer)-1: break
            size=2 if self.buffer[pos:pos+2] == "\r\n" else 1
            line,self.buffer=self.buffer[:pos],self.buffer[pos+size:]
            self._line(line)
        require(len(self.buffer) <= 2_000_000,"stream_line_limit")

    def finish(self):
        self.buffer += self.decoder.decode(b"",final=True)
        # A final CR can terminate a line, but not invent a missing blank frame.
        if self.buffer.endswith("\r"):
            self._line(self.buffer[:-1]);self.buffer=""
        require(not self.buffer and not self.data and not self.frame_started,"stream_truncated_frame")
        require(self.terminal in ("response.completed","response.incomplete") and self.final_response is not None,"stream_missing_terminal_event")
        return deepcopy(self.final_response)


async def consume_stream(events, journal, decoder):
    status=None; content_type=None
    async with aclosing(events):
        async for item in events:
            if isinstance(item,dict):
                require(status is None and set(item) == {"http_status","content_type"},"stream_invalid_headers")
                status=item["http_status"]
                journal.http_status=status
                content_type=item["content_type"].split(";",1)[0].strip().lower()
                continue
            require(status is not None,"stream_bytes_before_headers")
            journal.feed(item)
            if status == 200 and content_type == "text/event-stream": decoder.feed(item)
    require(status == 200,"http_"+str(status) if type(status) is int else "invalid_http_status")
    require(content_type == "text/event-stream","stream_wrong_content_type")
    return status, encoded(decoder.finish())


class AiohttpTransport:
    """Fixed HTTPS SSE destination, no redirects/proxies/cookies/retries."""
    def __init__(self, api_key, timeout_seconds=1200):
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
                                     headers={"Authorization": "Bearer " + self.api_key,"Accept":"text/event-stream"}) as response:
            yield {"http_status":response.status,"content_type":response.headers.get("Content-Type","")}
            async for chunk in response.content.iter_chunked(65536):
                yield chunk


async def run_slots(slots, *, api_key, output_dir, ledger, transport, canary=False,
                    model_interval=3.1, global_interval=3.1, concurrency=1, timeout_seconds=1200,
                    _clock=None, _sleep=None):
    # These two dependency-injection hooks are for offline clock tests only;
    # the execution CLI cannot override them or the initial cooldown policy.
    clock = time.monotonic if _clock is None else _clock
    sleep = asyncio.sleep if _sleep is None else _sleep
    slots = validate_slots(slots, canary=canary)
    require(isinstance(api_key, str) and len(api_key) >= 8 and not any(c.isspace() for c in api_key), "invalid_credential")
    require(api_key not in encoded(slots) and api_key not in str(output_dir), "credential_in_configuration")
    integer(concurrency, 1, 5, "invalid_concurrency")
    require(0 <= model_interval <= 60 and 0 <= global_interval <= 60 and 0 < timeout_seconds <= 1200, "invalid_timing")
    require(not ledger.halted, "ledger_halted")
    scrub = lambda text: text.replace(api_key, "[REDACTED_CREDENTIAL]").replace(json.dumps(api_key)[1:-1], "[REDACTED_CREDENTIAL]")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "streams").mkdir(exist_ok=False)
    run_id = uuid.uuid4().hex
    manifest = {**plan(slots, canary=canary), "run_id": run_id, "created_at": now(),
                "endpoint": ENDPOINT, "models_pricing": MODEL_PRICING, "pricing_source": PRICING_URL,
                "pricing_verified_date": VERIFIED_DATE, "model_interval_seconds": model_interval,
                "global_interval_seconds": global_interval, "concurrency": concurrency,
                "timeout_seconds": timeout_seconds, "retries": 0, "tools": False, "store": False,
                "agentic_memory": False, "stream":True, "budget_before": ledger.snapshot(), "slots": slots,
                "prior_ledger_replay":ledger.prior_evidence,"admission_policy":deepcopy(ADMISSION_POLICY),
                "clock_test_hooks":_clock is not None or _sleep is not None}
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
        admission = AdmissionWindow()
        initial_deadline = clock() + ADMISSION_POLICY["initial_cooldown_seconds"]
        last_global = [None]
        completed = {}
        blocked_history = set()
        dependency_skips = []
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
            while clock() < deadline and not stopped.is_set():
                await sleep(max(0, deadline-clock()))

        async def admit(slot, model, last_model, body, estimate):
            """Return a reserved request holding capacity, or None on stop.

            Both the lock and in-flight capacity are released before every
            pacing wait. A smaller request can therefore use available weight.
            The full policy is rechecked under one shared lock before any
            reservation. No requested-token estimates enter the provider body.
            """
            while not stopped.is_set():
                await capacity.acquire()
                retained_capacity = False
                try:
                    async with dispatch_lock:
                        if stopped.is_set(): return None
                        tick = clock()
                        delay = max(0, initial_deadline-tick,
                            (last_global[0]+global_interval-tick) if last_global[0] is not None else 0,
                            (last_model+model_interval-tick) if last_model is not None else 0,
                            admission.delay(tick, estimate["weight"]))
                        if delay == 0:
                            attempt_id = run_id + ":" + slot["slot_id"]
                            bound = request_bound(model, slot["max_output_tokens"])
                            if ledger.accounted + bound > CAP:
                                stop("cumulative_budget_stop");return None
                            try:
                                ledger.record({"kind":"reserve","attempt_id":attempt_id,"run_id":run_id,
                                    "slot_id":slot["slot_id"],"model":model,"bound_nanocredits":bound})
                                requests.write({"attempt_id":attempt_id,"slot_id":slot["slot_id"],"at":now(),
                                    "request":body,"request_sha256":digest(body),"reserved_credits":credits(bound),
                                    "admission_estimate":estimate,"admission_policy":deepcopy(ADMISSION_POLICY)})
                                # No await separates the policy recheck, durable
                                # reservation, request intent, and recorded start.
                                start = clock()
                                admission.record(start, estimate["weight"])
                            except Exception:
                                stop("reservation_or_request_journal_failure",attempt_id);return None
                            last_global[0] = start
                            issued.append(slot["slot_id"])
                            retained_capacity = True
                            return attempt_id, bound, start
                finally:
                    if not retained_capacity: capacity.release()
                await wait_until(tick + delay)
            return None

        async def worker(model):
            last_model = None
            for slot in (s for s in slots if s["model"] == model):
                if stopped.is_set():
                    return
                messages = []
                if any(dependency in blocked_history for dependency in slot.get("history_from", [])):
                    row={"run_id":run_id,"slot_id":slot["slot_id"],"case_id":slot["case_id"],
                         "model":model,"condition":slot["condition"],"phase":slot["phase"],
                         "model_outcome":"not_issued_dependency_truncated","error":"history_dependency_truncated",
                         "issued":False,"terminal_valid":False,"response_status":None,"output_text":"",
                         "blocked_dependencies":[x for x in slot.get("history_from",[]) if x in blocked_history],"at":now()}
                    try: responses.write(row)
                    except Exception:
                        stop("dependency_outcome_journal_failure");return
                    blocked_history.add(slot["slot_id"]);dependency_skips.append(slot["slot_id"]);outcomes.append(row)
                    continue
                for dependency in slot.get("history_from", []):
                    if dependency not in completed:
                        stop("history_dependency_unavailable");return
                    prior = completed[dependency]
                    messages.extend([{"role":"user","content":prior["input"]},{"role":"assistant","content":prior["output_text"]}])
                messages.append({"role":"user","content":slot["input"]})
                body = {"model":model,"instructions":slot["instructions"],"input":messages,
                        "max_output_tokens":slot["max_output_tokens"],"temperature":slot.get("temperature",0),
                        "store":False,"agentic_memory":False,"tools":[],"tool_choice":"none","stream":True}
                try:
                    estimate = estimate_request(body["instructions"],body["input"],body["max_output_tokens"])
                except Exception:
                    stop("admission_estimation_failure");return
                admitted = await admit(slot,model,last_model,body,estimate)
                if admitted is None: return
                attempt_id,bound,last_model = admitted
                try:
                    started = clock()
                    raw, status, parsed, cost, text, error = None, None, None, None, "", None
                    model_outcome = None
                    stream_journal, decoder = None, SSEDecoder()
                    try:
                        stream_name=hashlib.sha256(attempt_id.encode()).hexdigest()+".sse"
                        stream_journal=StreamJournal(directory/"streams"/stream_name,api_key)
                        status, raw = await asyncio.wait_for(consume_stream(transport(body),stream_journal,decoder), timeout=timeout_seconds)
                        require(isinstance(raw, str), "non_text_response")
                        require(scrub(raw) == raw, "credential_echo_detected")
                        require(status == 200, "http_" + str(status) if type(status) is int else "invalid_http_status")
                        try:
                            parsed = json.loads(raw)
                        except (json.JSONDecodeError, ValueError):
                            raise ValueError("non_json_response")
                        require(isinstance(parsed, dict), "non_object_response")
                        require(parsed.get("status") in ("completed","incomplete"), "response_not_terminal")
                        require(not parsed.get("error"), "provider_response_error")
                        require(parsed.get("model") == model, "response_model_mismatch")
                        cost = usage_cost(model, parsed.get("usage"), slot["max_output_tokens"])
                        require(cost <= bound, "reservation_bound_breached")
                        text = response_text(parsed)
                        model_outcome = "completed" if parsed["status"] == "completed" else "truncated_max_output_tokens"
                    except asyncio.TimeoutError:
                        error = "timeout"
                    except UnicodeError:
                        error = "stream_invalid_utf8"
                    except ValueError as exc:
                        # Only locally generated codes are exposed; provider raw
                        # error bodies remain scrubbed in their dedicated field.
                        known = {"non_text_response", "credential_echo_detected", "invalid_http_status", "non_json_response",
                                 "non_object_response", "response_not_completed", "provider_response_error", "response_model_mismatch",
                                 "missing_usage", "invalid_or_excess_input_usage", "invalid_or_excess_output_usage", "invalid_total_usage",
                                 "inconsistent_total_usage", "invalid_usage_details", "invalid_usage_detail_count",
                                 "reservation_bound_breached", "missing_output_text", "response_size_limit",
                                 "invalid_stream_chunk","stream_size_limit","stream_duplicate_json_key","stream_nonfinite_json",
                                 "stream_invalid_json","stream_nonobject_event","stream_unproven_done","stream_event_after_terminal",
                                 "stream_missing_type","stream_event_type_mismatch","stream_event_limit","stream_invalid_sequence",
                                 "stream_sequence_not_increasing","stream_response_id_changed","stream_invalid_delta","stream_text_limit",
                                 "stream_terminal_error","stream_invalid_terminal_response","stream_unaccepted_incomplete_reason","stream_missing_response_id","stream_completed_with_error",
                                 "stream_text_mismatch","stream_duplicate_event_field","stream_frame_limit","stream_line_limit",
                                 "stream_truncated_frame","stream_missing_terminal_event","stream_invalid_headers","stream_bytes_before_headers",
                                 "stream_wrong_content_type","response_not_terminal"}
                        code = str(exc)
                        error = code if code in known or (code.startswith("http_") and len(code) == 8 and code[5:].isdigit()) else "invalid_response"
                    except Exception:
                        error = "network_or_transport_failure"
                    finally:
                        if stream_journal is not None:
                            try: stream_journal.close()
                            except Exception: error="stream_journal_failure"
                    if error:
                        stop(error, attempt_id)
                    row = {"run_id": run_id, "attempt_id": attempt_id, "slot_id": slot["slot_id"],
                           "case_id": slot["case_id"], "model": model, "condition": slot["condition"], "phase": slot["phase"],
                           "issued":True,"terminal_valid":error is None,"model_outcome":model_outcome if error is None else "operational_failure",
                           "response_status": parsed.get("status") if isinstance(parsed, dict) else None,
                           "http_status": status if status is not None else stream_journal.http_status if stream_journal else None,
                           "error": error, "raw_response": scrub(raw) if isinstance(raw, str) else None,
                           "stream_evidence":stream_journal.metadata() if stream_journal else None,
                           "stream_terminal_event":decoder.terminal,"stream_event_count":decoder.event_count,
                           "output_text": text if error is None and model_outcome == "completed" else "",
                           "partial_output_text":text if error is None and model_outcome == "truncated_max_output_tokens" else "",
                           "usage": parsed.get("usage") if isinstance(parsed, dict) else None,
                           "latency_ms": round((clock()-started)*1000, 3), "at": now(),
                           "reserved_credits": credits(bound), "settled_credits": credits(cost) if error is None else None}
                    try:
                        responses.write(row)
                        if error is None:
                            ledger.record({"kind": "settle", "attempt_id": attempt_id, "accounted_nanocredits": cost,
                                           "response_sha256": digest(row), "basis": "valid_terminal_reported_usage_uncached_no_double_reasoning",
                                           "model_outcome":model_outcome})
                            if model_outcome == "completed":
                                completed[slot["slot_id"]] = {"input": slot["input"], "output_text": text}
                            else: blocked_history.add(slot["slot_id"])
                    except Exception:
                        stop("response_or_settlement_journal_failure", attempt_id)
                    outcomes.append(row)
                    if stopped.is_set():
                        return
                finally:
                    capacity.release()

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
        summary = {"schema": "retrace.adaption-v6f-summary.v1", "run_id": run_id,
                   "status": "stopped" if stopped.is_set() else "completed", "canary": canary, "stream": True,
                   "models": dict(Counter(s["model"] for s in slots)), "planned": len(slots), "issued": len(issued),
                   "responses": len(outcomes), "completed": len(completed), "stop_reasons": stop_reasons,
                   "valid_terminal_records":sum(r.get("terminal_valid") is True for r in outcomes),
                   "truncated":sum(r.get("model_outcome") == "truncated_max_output_tokens" for r in outcomes),
                   "issued_operational_failures":sum(r.get("model_outcome") == "operational_failure" for r in outcomes),
                   "dependency_skips":len(dependency_skips),"dependency_skipped_slot_ids":dependency_skips,
                   "unissued_due_global_halt_slot_ids":[s["slot_id"] for s in slots if s["slot_id"] not in issued and s["slot_id"] not in dependency_skips],
                   "issued_without_outcome_slot_ids":[s for s in issued if not any(r["slot_id"] == s for r in outcomes)],
                   "completion_definition":"Run status completed means scheduling closed without an operational halt; inspect completed/truncated separately",
                   "issued_slot_ids": issued, "unissued_slot_ids": [s["slot_id"] for s in slots if s["slot_id"] not in issued],
                   "budget": ledger.snapshot(), "actual_billed_credits": None, "retries": 0,
                   "admission_policy":deepcopy(ADMISSION_POLICY),"admission_starts":len(admission.records)}
        ledger.record({"kind": "run_closed", "run_id": run_id, "status": summary["status"], "issued": len(issued)})
        summary["budget"] = ledger.snapshot()
        summary_file = DurableJSONL(directory / "summary.json", scrub=scrub); files.append(summary_file)
        summary_file.write(summary)
        return summary
    finally:
        for file in files:
            file.close()
