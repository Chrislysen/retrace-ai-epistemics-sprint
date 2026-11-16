"""Additive v6h Adaption transport: bounded rolling ledger and explicit 429-only retry.

No network request occurs at import or planning time. Historical reservations
are never released. New completed calls settle at uncached reported-token cost;
transport failures retain their full bound; only explicit HTTP 429 may retry. A final
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
from retrace.adaption_v6f import verify_prior_ledger as verify_v6e_ledger
from email.utils import parsedate_to_datetime
import random

ENDPOINT = "https://api.prod.adaptionlabs.ai/api/v1/responses"
PRICING_URL = "https://docs.adaptionlabs.ai/inference-stacks/models/"
VERIFIED_DATE = "2026-11-14"
BASELINE = "43.633207445"
BASELINE_LEDGER = "results/frontier-v6f/budget/ledger.jsonl"
BASELINE_SHA256 = "d114f75380177a5ecb370b05c6bfc3acac19012d023090cab55e5109ad9afde2"
PRIOR_CARRY = "42.997746364"
V6C_LEDGER = "results/frontier-v6c/budget/ledger.jsonl"
V6C_LEDGER_SHA256 = "b176a2b610f4ac21fcdbb3202a0aa5bf3cc9a58159258c0fa33bcd982d4e5d76"
V6D_LEDGER = "results/frontier-v6d/budget/ledger.jsonl"
V6D_LEDGER_SHA256 = "5b3c4c99fcc373c998e2e93def456eb29864ecf65786974a42dbb7c5b5c35439"
V6E_LEDGER = "results/frontier-v6e/budget/ledger.jsonl"
V6E_LEDGER_SHA256 = "7e49f85ab98be0e694a4835c7814484e8ad58b701b6b18e502ec4918199da5ff"
MANUAL_CLOSURE = "data/frontier-v6f-manual-closure.json"
MANUAL_CLOSURE_SHA256 = "693c6c77531647578eba554db22698d63cb9a932e120b481a3cbe35cefb85fe1"
PRIMARY_MODELS = ("deepseek-v4-flash", "gemma-4-31b-it", "glm-5.3-flash", "qwen3.8-27b", "glm-5.2")
RETRY_POLICY = {"only_http_status":429,"max_retries":2,"minimum_cooldown_seconds":60,
    "backoff":"max(Retry-After, 60 * 2^retry_index) + Uniform(0, 5) seconds",
    "flood_stop": "10 consecutive HTTP 429 outcomes or 20 total HTTP 429 outcomes per run",
    "unknown_attempt_bound_retained":True,"quota_verified":False}
ADMISSION_POLICY = {"per_model_start_interval_seconds":2.0,"default_per_model_concurrency":8,
    "max_per_model_concurrency":64,"default_primary_global_concurrency":40,"max_global_concurrency":384,
    "global_429_cooldown":True,"quota_verified":False,
    "under_one_hour_guaranteed":False}
SCALE = Decimal(1_000_000_000)
CAP = 250_000_000_000
MODEL_PRICING = {
    "qwen3.5-397b": {"input": "0.55", "output": "3.50", "context": 131072},
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
    """Replay f's 48 settled attempts and bind its explicit idle manual closure.

    Frozen f recursively verifies c/d/e; all seven old unknown bounds remain
    inside the whole historical carry. No old attempt is retrospectively settled.
    """
    root = Path(__file__).resolve().parents[1]
    earlier = verify_v6e_ledger(root / V6E_LEDGER)
    require(earlier["carry_credits"] == PRIOR_CARRY, "earlier_carry_mismatch")
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == BASELINE_SHA256 and raw.endswith(b"\n"), "prior_ledger_changed")
    previous, accounted, attempts = "0"*64, nano(PRIOR_CARRY), {}
    for seq, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        row = json.loads(line)
        require(row["seq"] == seq and row["previous_sha256"] == previous, "prior_ledger_chain")
        require(row["sha256"] == digest({k:v for k,v in row.items() if k != "sha256"}), "prior_ledger_hash")
        previous = row["sha256"]; e = row["event"]; kind = e["kind"]
        if kind == "initialize":
            require(seq == 1 and e["historical_credits"] == PRIOR_CARRY and e["cap_credits"] == "250", "prior_ledger_initial")
        elif kind == "reserve":
            key, bound = e["attempt_id"], e["bound_nanocredits"]
            require(key not in attempts and type(bound) is int and bound > 0, "prior_reservation_invalid")
            attempts[key] = {"bound":bound,"settled":False}; accounted += bound
        elif kind == "settle":
            a = attempts[e["attempt_id"]]; cost = e["accounted_nanocredits"]
            require(not a["settled"] and type(cost) is int and 0 <= cost <= a["bound"], "prior_settlement_invalid")
            accounted += cost-a["bound"]; a["settled"] = True
        else:
            require(kind in ("run_started","run_closed"), "prior_event_unexpected")
        require(accounted <= CAP, "prior_cap_breach")
    require(len(attempts)==48 and all(a["settled"] for a in attempts.values()) and accounted==nano(BASELINE), "prior_carry_mismatch")
    closure_raw=(root/MANUAL_CLOSURE).read_bytes()
    require(hashlib.sha256(closure_raw).hexdigest()==MANUAL_CLOSURE_SHA256,"manual_closure_changed")
    closure=json.loads(closure_raw)
    require(closure["issued_regression_requests"]==38 and closure["recorded_responses"]==38
            and closure["issued_primary_requests"]==0 and closure["outstanding_reservations_before_stop"]==0
            and closure["journals_unchanged_after_stop"] is True,"manual_closure_invalid")
    for entry in closure["preserved"].values():
        target=(root/entry["path"]).resolve()
        require(target.is_relative_to(root) and hashlib.sha256(target.read_bytes()).hexdigest()==entry["sha256"],"manual_closure_evidence_changed")
    return {"file_sha256":BASELINE_SHA256,"chain_sha256":previous,"carry_credits":credits(accounted),
        "issued_attempts":48,"settled_attempts":48,"unknown_full_bounds_retained":0,
        "manual_closure_sha256":MANUAL_CLOSURE_SHA256,"primary_calls_in_interrupted_run":0,
        "earlier_frozen_ledger":earlier,"cumulative_inherited_unsettled_attempts":earlier["cumulative_inherited_unsettled_attempts"]}


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


def slot_dependencies(slot):
    return slot.get("history_from", []) + ([slot["input_from"]["slot_id"]] if slot.get("input_from") else [])


def validate_slots(slots, *, canary=False):
    require(isinstance(slots,list) and bool(slots),"empty_slots")
    require(len(slots)<=10000,"slot_ceiling_exceeded")
    seen={}
    required={"slot_id","case_id","model","condition","phase","instructions","input","max_output_tokens"}
    allowed=required|{"temperature","history_from","input_from","metadata"}
    for slot in slots:
        require(isinstance(slot,dict) and required <= set(slot) <= allowed,"invalid_slot_fields")
        for key in required-{"max_output_tokens","input"}:
            require(isinstance(slot[key],str) and bool(slot[key].strip()),"invalid_slot_string")
        require(isinstance(slot["input"],str),"invalid_slot_input")
        require(slot["model"] in MODEL_PRICING,"unverified_model_id")
        require(slot["slot_id"] not in seen,"duplicate_slot_id")
        integer(slot["max_output_tokens"],8192 if slot["model"]!="qwen3.5-397b" else 16384,65536,"invalid_output_limit")
        require(type(slot.get("temperature",1.0)) in (float,int) and slot.get("temperature",1.0)==1.0,"invalid_temperature")
        history=slot.get("history_from",[])
        require(isinstance(history,list) and all(isinstance(x,str) for x in history) and len(set(history))==len(history),"invalid_history")
        if "input_from" in slot:
            d=slot["input_from"]
            require(not history and isinstance(d,dict) and set(d)=={"slot_id","mode"},"invalid_input_dependency")
            require(d["mode"] in ("assistant_output_only","assistant_output_with_fixed_prefix"),"invalid_input_dependency_mode")
            require(isinstance(d["slot_id"],str),"invalid_input_dependency")
            require((d["mode"]=="assistant_output_only" and slot["input"]=="") or (d["mode"]=="assistant_output_with_fixed_prefix" and bool(slot["input"].strip())),"dependency_prefix_mismatch")
        else:
            require(bool(slot["input"].strip()),"empty_static_input")
        for dep in slot_dependencies(slot):
            require(dep in seen,"dependency_not_earlier")
            require(seen[dep]["model"]==slot["model"] and seen[dep]["case_id"]==slot["case_id"],"dependency_scope_mismatch")
        if "metadata" in slot: require(isinstance(slot["metadata"],dict),"invalid_metadata")
        seen[slot["slot_id"]]=slot
    encoded(slots)
    if canary:
        require(len(slots)==10 and Counter(s["model"] for s in slots)==Counter({m:2 for m in PRIMARY_MODELS}),"canary_requires_two_per_primary_model")
        require(all(not slot_dependencies(s) for s in slots),"canary_must_be_independent")
    return deepcopy(slots)


def plan(slots, *, canary=False):
    slots=validate_slots(slots,canary=canary)
    bounds={m:sum(request_bound(m,s["max_output_tokens"]) for s in slots if s["model"]==m) for m in MODEL_PRICING}
    return {"schema":"retrace.adaption-v6h-plan.v1","planned_slots":len(slots),"canary":canary,
        "sessions_sha256":digest(slots),"models":dict(Counter(s["model"] for s in slots)),
        "historical_carry_credits":BASELINE,"cumulative_cap_credits":"250",
        "first_attempt_full_plan_no_settlement_bound_credits":credits(sum(bounds.values())),
        "three_attempt_full_plan_no_settlement_bound_credits":credits(3*sum(bounds.values())),
        "full_plan_bound_by_model":{m:credits(n) for m,n in bounds.items()},
        "rolling_reservation":True,"completion_of_entire_plan_not_guaranteed":True,
        "actual_billed_credits":None,"reservation_created":False,"retry_policy":deepcopy(RETRY_POLICY),
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
                require(all(a["settled"] or a.get("retained_429") for a in self.attempts.values()), "ledger_has_unresolved_attempt")
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
        elif kind == "retain_429":
            attempt = self.attempts[event["attempt_id"]]
            require(not attempt["settled"] and not attempt.get("retained_429"), "invalid_429_retention")
            attempt["retained_429"] = True
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
                "unknown_429_attempts_retained":sum(bool(a.get("retained_429")) for a in self.attempts.values()),
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



KNOWN_ERRORS = {'invalid_total_usage', 'missing_usage', 'stream_unaccepted_incomplete_reason', 'stream_unproven_done', 'stream_completed_with_error', 'reservation_bound_breached', 'non_json_response', 'stream_missing_terminal_event', 'stream_invalid_terminal_response', 'stream_nonobject_event', 'invalid_or_excess_output_usage', 'stream_wrong_content_type', 'stream_invalid_sequence', 'response_not_terminal', 'stream_duplicate_json_key', 'response_not_completed', 'provider_response_error', 'stream_invalid_delta', 'stream_text_mismatch', 'stream_response_id_changed', 'non_object_response', 'credential_echo_detected', 'missing_output_text', 'stream_missing_response_id', 'stream_event_limit', 'stream_sequence_not_increasing', 'non_text_response', 'stream_size_limit', 'stream_invalid_json', 'inconsistent_total_usage', 'invalid_http_status', 'stream_missing_type', 'stream_invalid_headers', 'stream_frame_limit', 'stream_event_after_terminal', 'stream_terminal_error', 'stream_truncated_frame', 'stream_line_limit', 'stream_bytes_before_headers', 'stream_nonfinite_json', 'response_size_limit', 'stream_event_type_mismatch', 'stream_text_limit', 'stream_duplicate_event_field', 'response_model_mismatch', 'invalid_stream_chunk', 'invalid_usage_details', 'invalid_or_excess_input_usage', 'invalid_usage_detail_count'}


def retry_delay(retry_after, retry_index, *, utc_now=None, jitter=None):
    """Honor either Retry-After form, with >=60s exponential global cooldown."""
    integer(retry_index,0,2,"invalid_retry_index")
    delay=60.0*(2**retry_index)
    if isinstance(retry_after,str):
        try:
            if retry_after.strip().isdigit():
                delay=max(delay,float(retry_after.strip()))
            else:
                dt=parsedate_to_datetime(retry_after)
                if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
                current=datetime.now(timezone.utc) if utc_now is None else utc_now
                delay=max(delay,(dt-current).total_seconds())
        except (ValueError,TypeError,OverflowError):
            pass  # Unparseable headers never shorten the conservative cooldown.
    extra=random.SystemRandom().uniform(0,5) if jitter is None else jitter
    require(type(extra) in (int,float) and 0<=extra<=5,"invalid_retry_jitter")
    return delay+extra


async def consume_stream(events,journal,decoder,on_headers=None):
    status=None; content_type=None
    async with aclosing(events):
        async for item in events:
            if isinstance(item,dict):
                require(status is None and {"http_status","content_type"}<=set(item)<={"http_status","content_type","retry_after"},"stream_invalid_headers")
                status=item["http_status"]; journal.http_status=status
                require(type(status) is int and isinstance(item["content_type"],str),"stream_invalid_headers")
                journal.retry_after=item.get("retry_after")
                require(journal.retry_after is None or (isinstance(journal.retry_after,str) and len(journal.retry_after)<=256),"stream_invalid_headers")
                content_type=item["content_type"].split(";",1)[0].strip().lower()
                if on_headers is not None:on_headers(item)
                continue
            require(status is not None,"stream_bytes_before_headers")
            journal.feed(item)
            if status==200 and content_type=="text/event-stream":decoder.feed(item)
    require(status==200,"http_"+str(status) if type(status) is int else "invalid_http_status")
    require(content_type=="text/event-stream","stream_wrong_content_type")
    return status,encoded(decoder.finish())


class AiohttpTransport:
    """Only the allowlisted HTTPS endpoint; no implicit retries or redirects."""
    def __init__(self,api_key,timeout_seconds=180,connection_limit=48):
        self.api_key=api_key;self.timeout_seconds=timeout_seconds;self.connection_limit=connection_limit;self.session=None

    async def __aenter__(self):
        import aiohttp
        self.session=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(),connector=aiohttp.TCPConnector(limit=self.connection_limit))
        if hasattr(self.session,"_retry_connection"):self.session._retry_connection=False
        return self

    async def __aexit__(self,*_):
        await self.session.close()

    async def __call__(self,body):
        async with self.session.post(ENDPOINT,json=body,allow_redirects=False,
                headers={"Authorization":"Bearer "+self.api_key,"Accept":"text/event-stream"}) as response:
            yield {"http_status":response.status,"content_type":response.headers.get("Content-Type",""),
                   "retry_after":response.headers.get("Retry-After")}
            async for chunk in response.content.iter_chunked(65536):yield chunk


def build_body(slot,completed):
    """Resolve only explicit actual-output dependencies; never substitute gold."""
    messages=[]
    for dep in slot.get("history_from",[]):
        prior=completed[dep]
        messages.extend([{"role":"user","content":prior["actual_input"]},{"role":"assistant","content":prior["output_text"]}])
    current=slot["input"]
    if slot.get("input_from"):
        d=slot["input_from"]; prior=completed[d["slot_id"]]["output_text"]
        current=prior if d["mode"]=="assistant_output_only" else current+"\n\n"+prior
    messages.append({"role":"user","content":current})
    return {"model":slot["model"],"instructions":slot["instructions"],"input":messages,
        "max_output_tokens":slot["max_output_tokens"],"temperature":slot.get("temperature",1.0),
        "store":False,"previous_response_id":None,"agentic_memory":False,"tools":[],"tool_choice":"none","stream":True}


async def run_slots(slots,*,api_key,output_dir,ledger,transport,canary=False,model_interval=2.0,
                    per_model_concurrency=8,concurrency=48,timeout_seconds=180,stop_file=None,
                    _clock=None,_sleep=None,_jitter=None):
    """Concurrent DAG scheduler. Explicit 429 attempts are retained and bounded.

    Request intent/reservation precede transport. Every issued attempt has its
    own response row; slot-outcomes has one final scheduled outcome per slot.
    Neither final-output selection nor retries overwrite the first attempt.
    """
    clock=time.monotonic if _clock is None else _clock
    sleep=asyncio.sleep if _sleep is None else _sleep
    slots=validate_slots(slots,canary=canary)
    require(isinstance(api_key,str) and len(api_key)>=8 and not any(c.isspace() for c in api_key),"invalid_credential")
    require(api_key not in encoded(slots) and api_key not in str(output_dir),"credential_in_configuration")
    integer(concurrency,1,384,"invalid_concurrency");integer(per_model_concurrency,1,64,"invalid_model_concurrency")
    require(0<=model_interval<=60 and 0<timeout_seconds<=180,"invalid_timing")
    require(not ledger.halted,"ledger_halted")
    scrub=lambda text:text.replace(api_key,"[REDACTED_CREDENTIAL]").replace(json.dumps(api_key)[1:-1],"[REDACTED_CREDENTIAL]")
    directory=Path(output_dir);directory.mkdir(parents=True,exist_ok=False);(directory/"streams").mkdir()
    run_id=uuid.uuid4().hex
    manifest={**plan(slots,canary=canary),"run_id":run_id,"created_at":now(),"endpoint":ENDPOINT,
        "models_pricing":MODEL_PRICING,"pricing_source":PRICING_URL,"pricing_verified_date":VERIFIED_DATE,
        "model_interval_seconds":model_interval,"per_model_concurrency":per_model_concurrency,"concurrency":concurrency,
        "timeout_seconds":timeout_seconds,"max_retries":2,"store":False,"previous_response_id":None,
        "agentic_memory":False,"tools":False,"stream":True,"budget_before":ledger.snapshot(),"slots":slots,
        "prior_ledger_replay":ledger.prior_evidence,"stop_file":str(stop_file) if stop_file else None,
        "test_hooks":any(x is not None for x in (_clock,_sleep,_jitter))}
    files=[]
    try:
        for name in ("run.json","requests.jsonl","responses.jsonl","slot-outcomes.jsonl"):
            files.append(DurableJSONL(directory/name,scrub=scrub))
        manifest_file,requests,responses,slot_file=files;manifest_file.write(manifest)
        ledger.record({"kind":"run_started","run_id":run_id,"sessions_sha256":digest(slots),"planned":len(slots)})
        stopped=False;stop_reasons=[];cooldown_until=0.0;consecutive_429=0;total_429=0
        completed={};finals={};attempt_rows=[];issued_ids=[];active={};counts=Counter();last_start={}
        states={s["slot_id"]:{"attempts":0,"not_before":0.0,"status":"pending"} for s in slots}

        def stop(reason,attempt_id=None):
            nonlocal stopped
            stopped=True
            if reason not in stop_reasons:
                stop_reasons.append(reason)
                try:ledger.record({"kind":"halt","run_id":run_id,"reason":reason,"attempt_id":attempt_id})
                except Exception:
                    if "ledger_write_failure" not in stop_reasons:stop_reasons.append("ledger_write_failure")

        def check_stop_file():
            if stop_file and Path(stop_file).exists():stop("administrative_stop_file")

        def finalize(slot,row):
            key=slot["slot_id"]
            require(key not in finals,"duplicate_slot_outcome")
            out={**row,"slot_final":True,"attempts_issued":states[key]["attempts"],
                "first_attempt_id":next((r["attempt_id"] for r in attempt_rows if r["slot_id"]==key),None)}
            slot_file.write(out);finals[key]=out;states[key]["status"]="done"

        def skipped(slot,reason,blocked=()):
            return {"run_id":run_id,"slot_id":slot["slot_id"],"case_id":slot["case_id"],"model":slot["model"],
                "condition":slot["condition"],"phase":slot["phase"],"issued":False,"terminal_valid":False,
                "model_outcome":reason,"error":reason,"response_status":None,"output_text":"",
                "blocked_dependencies":list(blocked),"at":now()}

        async def attempt(slot,body,attempt_id,bound,attempt_number):
            nonlocal cooldown_until,consecutive_429,total_429
            started=clock();raw=None;parsed=None;cost=None;text="";error=None;status=None;model_outcome=None
            journal=None;decoder=SSEDecoder();model=slot["model"]
            header_delay=None
            def observe_headers(headers):
                nonlocal cooldown_until,header_delay
                if headers["http_status"]==429:
                    header_delay=retry_delay(headers.get("retry_after"),attempt_number-1,jitter=_jitter() if _jitter else None)
                    cooldown_until=max(cooldown_until,clock()+header_delay)
            try:
                journal=StreamJournal(directory/"streams"/(hashlib.sha256(attempt_id.encode()).hexdigest()+".sse"),api_key)
                status,raw=await asyncio.wait_for(consume_stream(transport(body),journal,decoder,observe_headers),timeout=timeout_seconds)
                require(scrub(raw)==raw,"credential_echo_detected")
                parsed=strict_event_json(raw)
                require(parsed.get("model")==model,"response_model_mismatch")
                cost=usage_cost(model,parsed.get("usage"),slot["max_output_tokens"])
                require(cost<=bound,"reservation_bound_breached")
                text=response_text(parsed)
                model_outcome="completed" if parsed["status"]=="completed" else "truncated_max_output_tokens"
            except asyncio.TimeoutError:error="timeout"
            except UnicodeError:error="stream_invalid_utf8"
            except ValueError as exc:
                code=str(exc)
                error=code if code in KNOWN_ERRORS or (code.startswith("http_") and len(code)==8 and code[5:].isdigit()) else "invalid_response"
            except Exception:error="network_or_transport_failure"
            finally:
                if journal:
                    try:journal.close()
                    except Exception:error="stream_journal_failure"
            status=status if status is not None else journal.http_status if journal else None
            is_429=error=="http_429" and status==429
            # A 429 can settle only if its exact complete JSON body contains
            # bounded, internally consistent usage. No absent usage is guessed.
            if is_429 and journal and not journal.redacted:
                try:
                    error_body=strict_event_json(journal.path.read_text(encoding="utf-8"))
                    require(error_body.get("model",model)==model,"response_model_mismatch")
                    candidate_cost=usage_cost(model,error_body.get("usage"),slot["max_output_tokens"])
                    require(candidate_cost<=bound,"reservation_bound_breached")
                    parsed=error_body;cost=candidate_cost
                except (ValueError,UnicodeError,OSError):cost=None
            delay=None
            if is_429:
                total_429+=1;consecutive_429+=1
                delay=header_delay if header_delay is not None else retry_delay(getattr(journal,"retry_after",None),attempt_number-1,jitter=_jitter() if _jitter else None)
                cooldown_until=max(cooldown_until,clock()+delay)
            elif error is None:
                consecutive_429=0
            row={"run_id":run_id,"attempt_id":attempt_id,"attempt_number":attempt_number,"first_attempt":attempt_number==1,
                "slot_id":slot["slot_id"],"case_id":slot["case_id"],"model":model,"condition":slot["condition"],"phase":slot["phase"],
                "issued":True,"terminal_valid":error is None,"model_outcome":model_outcome if error is None else "http_429" if is_429 else "operational_failure",
                "response_status":parsed.get("status") if isinstance(parsed,dict) else None,"http_status":status,"error":error,
                "raw_response":scrub(raw) if isinstance(raw,str) else None,"stream_evidence":journal.metadata() if journal else None,
                "stream_terminal_event":decoder.terminal,"stream_event_count":decoder.event_count,
                "output_text":text if error is None and model_outcome=="completed" else "",
                "partial_output_text":text if error is None and model_outcome=="truncated_max_output_tokens" else "",
                "usage":parsed.get("usage") if isinstance(parsed,dict) else None,"latency_ms":round((clock()-started)*1000,3),
                "at":now(),"reserved_credits":credits(bound),"settled_credits":credits(cost) if cost is not None and (error is None or is_429) else None,
                "retry_after":getattr(journal,"retry_after",None),"retry_cooldown_seconds":delay}
            try:
                responses.write(row);attempt_rows.append(row)
                if cost is not None and (error is None or is_429):
                    ledger.record({"kind":"settle","attempt_id":attempt_id,"accounted_nanocredits":cost,"response_sha256":digest(row),
                        "basis":"explicit_bounded_usage_uncached_no_double_reasoning","model_outcome":row["model_outcome"]})
                elif is_429:
                    ledger.record({"kind":"retain_429","attempt_id":attempt_id,"response_sha256":digest(row),"basis":"explicit_429_no_valid_usage_full_bound_retained"})
                if is_429 and (consecutive_429>=10 or total_429>=20):stop("rate_limit_flood_stop",attempt_id)
                elif error is not None and not is_429:stop(error,attempt_id)
                if is_429 and attempt_number<3 and not stopped:
                    states[slot["slot_id"]].update(status="pending",not_before=cooldown_until)
                else:
                    if error is None and model_outcome=="completed":
                        completed[slot["slot_id"]]={"actual_input":body["input"][-1]["content"],"output_text":text}
                    finalize(slot,row)
            except Exception:stop("response_or_settlement_journal_failure",attempt_id)

        async def guarded_attempt(*args):
            try:await attempt(*args)
            except BaseException:stop("unexpected_attempt_failure",args[2])

        async def scheduler():
            while True:
                check_stop_file()
                for task,(slot,_) in list(active.items()):
                    if task.done():
                        await task;counts[slot["model"]]-=1;del active[task]
                if not stopped:
                    for slot in slots:
                        key=slot["slot_id"];state=states[key]
                        if state["status"]!="pending":continue
                        deps=slot_dependencies(slot)
                        bad=[d for d in deps if d in finals and d not in completed]
                        if bad:
                            finalize(slot,skipped(slot,"not_issued_dependency_failed",bad));continue
                        if any(d not in completed for d in deps):continue
                        tick=clock();model=slot["model"]
                        if len(active)>=concurrency:break
                        if counts[model]>=per_model_concurrency or tick<max(cooldown_until,state["not_before"],last_start.get(model,-1e20)+model_interval):continue
                        check_stop_file()
                        if stopped:break
                        body=build_body(slot,completed);bound=request_bound(model,slot["max_output_tokens"])
                        if ledger.accounted+bound>CAP:
                            # Active reservations may settle below their full
                            # bounds. Drain them before declaring exhaustion;
                            # cheaper ready attempts may still fit meanwhile.
                            if active:continue
                            stop("cumulative_budget_stop");break
                        number=state["attempts"]+1;attempt_id=run_id+":"+key+":attempt-"+str(number)
                        try:
                            ledger.record({"kind":"reserve","attempt_id":attempt_id,"run_id":run_id,"slot_id":key,
                                "attempt_number":number,"model":model,"bound_nanocredits":bound})
                            requests.write({"attempt_id":attempt_id,"slot_id":key,"attempt_number":number,"first_attempt":number==1,"at":now(),
                                "request":body,"request_sha256":digest(body),"reserved_credits":credits(bound),
                                "dependency_bindings":[{"slot_id":d,"final_attempt_id":finals[d].get("attempt_id"),"output_sha256":hashlib.sha256(completed[d]["output_text"].encode()).hexdigest()} for d in deps]})
                        except Exception:stop("reservation_or_request_journal_failure",attempt_id);break
                        state.update(attempts=number,status="running");issued_ids.append(key);last_start[model]=clock();counts[model]+=1
                        task=asyncio.create_task(guarded_attempt(slot,body,attempt_id,bound,number));active[task]=(slot,attempt_id)
                if not active:
                    if stopped or all(s["status"]=="done" for s in states.values()):break
                    # An earlier-only dependency graph cannot deadlock unless
                    # local bookkeeping failed. Waiting for pacing is allowed.
                    pending=[s for s in slots if states[s["slot_id"]]["status"]=="pending"]
                    if not any(all(d in completed for d in slot_dependencies(s)) for s in pending):
                        stop("dependency_scheduler_deadlock");break
                await sleep(.05)
        task=asyncio.create_task(scheduler())
        try:await asyncio.shield(task)
        except asyncio.CancelledError:
            stop("administrative_run_cancelled");await asyncio.shield(task)
        except BaseException:
            stop("unexpected_scheduler_failure")
        if active:
            await asyncio.shield(asyncio.gather(*active,return_exceptions=True))
        # One durable scheduled outcome for every slot, including administrative
        # closure, exhausted retries, and slots not issued because of a failure.
        for slot in slots:
            key=slot["slot_id"]
            if key in finals:continue
            rows=[r for r in attempt_rows if r["slot_id"]==key]
            if rows:finalize(slot,{**rows[-1],"retry_abandoned_due_global_stop":rows[-1]["model_outcome"]=="http_429"})
            else:finalize(slot,skipped(slot,"issued_without_response" if states[key]["attempts"] else "not_issued_global_stop"))
        first=[r for r in attempt_rows if r["first_attempt"]]
        summary={"schema":"retrace.adaption-v6h-summary.v1","run_id":run_id,"status":"stopped" if stopped else "completed",
            "canary":canary,"stream":True,"models":dict(Counter(s["model"] for s in slots)),"planned":len(slots),
            "issued_attempts":len(issued_ids),"issued_slots":len(set(issued_ids)),"responses":len(attempt_rows),
            "slot_outcomes":len(finals),"completed":len(completed),"stop_reasons":stop_reasons,
            "first_attempt_completed":sum(r["model_outcome"]=="completed" for r in first),
            "first_attempt_valid_terminal_records":sum(r["terminal_valid"] for r in first),
            "first_attempt_truncated":sum(r["model_outcome"]=="truncated_max_output_tokens" for r in first),
            "first_attempt_http_429":sum(r["model_outcome"]=="http_429" for r in first),
            "eventual_completed":len(completed),"valid_terminal_records":sum(r["terminal_valid"] for r in attempt_rows),
            "eventual_terminal_slots":sum(r["terminal_valid"] for r in finals.values()),
            "truncated":sum(r["model_outcome"]=="truncated_max_output_tokens" for r in finals.values()),
            "http_429_attempts":total_429,"issued_operational_failures":sum(r["model_outcome"]=="operational_failure" for r in attempt_rows),
            "dependency_skips":sum(r["model_outcome"]=="not_issued_dependency_failed" for r in finals.values()),
            "unissued_slot_ids":[s["slot_id"] for s in slots if not states[s["slot_id"]]["attempts"]],
            "issued_without_outcome_attempt_ids":[],
            "retries":len(issued_ids)-len(set(issued_ids)),"max_retries_per_slot":2,"retry_policy":deepcopy(RETRY_POLICY),
            "all_scheduled_outcomes_recorded":len(finals)==len(slots),"budget":ledger.snapshot(),"actual_billed_credits":None,
            "completion_definition":"Scheduling closure; first attempts, retries, truncations and final slot outcomes remain separate."}
        # Derive actual orphan attempt IDs from request ledger, not slot counts.
        run_attempts={a for a in ledger.attempts if a.startswith(run_id+":")}
        summary["issued_without_outcome_attempt_ids"]=sorted(run_attempts-{r["attempt_id"] for r in attempt_rows})
        ledger.record({"kind":"run_closed","run_id":run_id,"status":summary["status"],"issued_attempts":len(issued_ids),
            "issued_slots":len(set(issued_ids)),"unissued_slots":len(summary["unissued_slot_ids"]),"administrative":any(r.startswith("administrative_") for r in stop_reasons)})
        summary["budget"]=ledger.snapshot()
        sf=DurableJSONL(directory/"summary.json",scrub=scrub);files.append(sf);sf.write(summary)
        return summary
    finally:
        for file in files:file.close()
