"""Independent infrastructure audit of a CLOSED v6l continuation; no provider/semantic calls.

Independent whole-stream parsing, decimal accounting and body reconstruction.
This file is additive and does not alter the prospective scientific scorer.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path, PureWindowsPath
import argparse
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_frontier_v6f_run import parse_sse, strict_json, output_text

CAP = 750_000_000_000
CONFIG = {"global_concurrency": 1, "completion_delay_seconds": 4.0,
          "rate_limit_cooldown_seconds": 65.0, "max_retries": 2, "timeout_seconds": 180.0}
DEADLINE = datetime(2026, 11, 16, 3, 55, tzinfo=timezone.utc)
PRICES = {
    "deepseek-v4-flash": ("0.045", "0.14", 1048576),
    "gemma-4-31b-it": ("0.09", "0.34", 256000),
    "glm-5.3-flash": ("0.15", "0.50", 1048576),
    "qwen3.8-27b": ("0.039", "1.25", 262144),
    "glm-5.2": ("1.40", "4.40", 1048575),
    "qwen3.5-397b": ("0.55", "3.50", 131072),
}


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value): return sha256(canon(value)).hexdigest()
def credits(n): return format(Decimal(n) / 1_000_000_000, "f")
def stamp(s): return datetime.fromisoformat(s)


def nano(value):
    x = Decimal(str(value)) * 1_000_000_000
    if not x.is_finite() or x < 0 or x != x.to_integral_value():
        raise ValueError("invalid exact nanocredit amount")
    return int(x)


def bound(slot):
    i, o, context = PRICES[slot["model"]]
    return int(((Decimal(i) * context + Decimal(o) * slot["max_output_tokens"]) * 1000).to_integral_value(rounding=ROUND_CEILING))


def cost(slot, usage):
    if not isinstance(usage, dict): raise ValueError("missing usage")
    i, o, context = PRICES[slot["model"]]
    it, ot = usage.get("input_tokens"), usage.get("output_tokens")
    if type(it) is not int or type(ot) is not int or not 0 <= it <= context or not 0 <= ot <= slot["max_output_tokens"]:
        raise ValueError("usage bounds")
    if "total_tokens" in usage and (type(usage["total_tokens"]) is not int or usage["total_tokens"] != it + ot):
        raise ValueError("usage total")
    for key, field, ceiling in (("input_tokens_details", "cached_tokens", it), ("output_tokens_details", "reasoning_tokens", ot)):
        details = usage.get(key)
        if details is not None:
            if not isinstance(details, dict): raise ValueError("usage details")
            if field in details and (type(details[field]) is not int or not 0 <= details[field] <= ceiling): raise ValueError("usage detail bound")
    return int(((Decimal(i) * it + Decimal(o) * ot) * 1000).to_integral_value(rounding=ROUND_CEILING))


def jsonl(raw):
    if raw and not raw.endswith(b"\n"): raise ValueError("partial JSONL line")
    if any(not line.strip() for line in raw.splitlines()): raise ValueError("blank JSONL line")
    return [strict_json(line) for line in raw.splitlines()]


def dependencies(slot):
    return slot.get("history_from", []) + ([slot["input_from"]["slot_id"]] if slot.get("input_from") else [])


def completed(row):
    return row.get("issued") is True and row.get("terminal_valid") is True and row.get("model_outcome") == "completed" and row.get("response_status") == "completed" and row.get("error") is None


def expected_body(slot, final, request_index):
    messages = []
    for dep in slot.get("history_from", []):
        prior = final[dep]
        if not completed(prior): raise ValueError("unsuccessful history dependency")
        messages.extend(({"role": "user", "content": request_index[prior["attempt_id"]]["request"]["input"][-1]["content"]},
                         {"role": "assistant", "content": prior["output_text"]}))
    current = slot["input"]
    if slot.get("input_from"):
        d = slot["input_from"]; prior = final[d["slot_id"]]
        if not completed(prior): raise ValueError("unsuccessful projection dependency")
        if d["mode"] == "assistant_output_only": current = prior["output_text"]
        elif d["mode"] == "assistant_output_with_fixed_prefix": current += "\n\n" + prior["output_text"]
        else: raise ValueError("unknown projection mode")
    messages.append({"role": "user", "content": current})
    return {"model": slot["model"], "instructions": slot["instructions"], "input": messages,
            "max_output_tokens": slot["max_output_tokens"], "temperature": slot.get("temperature", 1.0),
            "store": False, "previous_response_id": None, "agentic_memory": False, "tools": [], "tool_choice": "none", "stream": True}



from scripts import audit_frontier_v6i_runtime as original_audit
from scripts import audit_frontier_v6k_runtime as prior_k_audit
ROUTE = {"qwen3.5-397b": "qwen3.5-397b-a17b-nvfp4"}
POSTHEADER_TYPES = frozenset({
    "aiohttp.client_exceptions.ServerDisconnectedError",
    "aiohttp.client_exceptions.ClientPayloadError",
    "aiohttp.client_exceptions.ClientConnectionResetError",
    "builtins.ConnectionResetError",
})
TRANSPORT_POLICY = {
    "origin":"transport_iterator_anext_only", "retry":False, "retain_full_bound":True,
    "post_header_allowed_types":["aiohttp.client_exceptions.ServerDisconnectedError", "aiohttp.client_exceptions.ClientPayloadError",
        "aiohttp.client_exceptions.ClientConnectionResetError", "builtins.ConnectionResetError"],
    "allowed_statuses":"200 with text/event-stream; 408; 429; 500..599",
    "other_transport_exceptions":"global", "outer_180_second_timeout":"per_slot", "exception_messages_recorded":False,
}


def check_transport_classification(row):
    """Validate logged policy inputs, without inventing a terminal from a prefix.

    These unsigned fields cannot independently prove a Python exception identity;
    the frozen transport wrapper and captured prefix provide separate evidence.
    """
    keys = {"transport_headers_validated", "transport_content_type", "transport_exception_type", "transport_failure_stage", "exception_type"}
    if not keys <= set(row): raise ValueError("explicit transport classification fields required")
    valid = row["transport_headers_validated"]; content = row["transport_content_type"]
    typ = row["transport_exception_type"]; stage = row["transport_failure_stage"]
    if type(valid) is not bool: raise ValueError("transport header validation boolean")
    if content is not None and (not isinstance(content,str) or content != content.strip().lower() or len(content)>512):
        raise ValueError("normalized bounded transport content type")
    if typ is not None and (not isinstance(typ,str) or not typ or len(typ)>160 or not all(c.isascii() and (c.isalnum() or c in "._") for c in typ)):
        raise ValueError("sanitized exception class only")
    outer = row["exception_type"]
    if outer is not None and (not isinstance(outer,str) or not outer or len(outer)>160 or not all(c.isascii() and (c.isalnum() or c in "._") for c in outer)):
        raise ValueError("sanitized outer exception class only")
    if typ is not None and row["exception_type"] != typ: raise ValueError("original transport exception class preserved")
    if stage not in (None,"response_body","before_validated_headers") or (typ is None)!=(stage is None):
        raise ValueError("transport exception stage binding")
    if stage == "response_body" and not valid: raise ValueError("body exception requires validated headers")
    if stage == "before_validated_headers" and valid: raise ValueError("preheader exception cannot have validated headers")
    if row["terminal_valid"] and (not valid or content!="text/event-stream" or typ is not None or stage is not None or outer is not None):
        raise ValueError("successful terminal requires validated SSE headers and no exception")
    status = row["http_status"]
    eligible_status = (status == 200 and content=="text/event-stream") or (
        type(status) is int and (status in (408,429) or 500<=status<=599))
    postheader = row["error"] == "post_headers_transport_read_failure"
    if row["error"] == "timeout" and (typ is not None or stage is not None or outer!="builtins.TimeoutError"):
        raise ValueError("only outer timeout classification can be per-slot")
    if row["error"] == "network_or_transport_failure" and typ in POSTHEADER_TYPES and stage=="response_body" and valid and eligible_status:
        raise ValueError("eligible typed body exception must follow prospective local policy")
    if postheader and not (typ in POSTHEADER_TYPES and stage=="response_body" and valid and eligible_status):
        raise ValueError("postheader failure outside exact prospective whitelist")
    if postheader and (row["terminal_valid"] is not False or row["settled_credits"] is not None or row["usage"] is not None
        or row["raw_response"] is not None or row["response_status"] is not None or row["partial_output_text"] != ""):
        raise ValueError("postheader failure retains full bound and no inferred terminal")
    return postheader

def audit_evidence(slots, manifest, requests, responses, finals, summary, ledger, read_stream, *, historical, carryover=None, original_requests=None, original_responses=None, allow_test_hooks=False):
    """Pure closed-run replay. Test hooks allowed only by explicit fixture callers."""
    checks = 0
    def check(ok, why):
        nonlocal checks
        checks += 1
        if not ok: raise ValueError(why)
    def number(value):
        check(type(value) in (int, float) and math.isfinite(value), "finite monotonic timestamp")
        return value
    check(isinstance(historical, dict) and set(historical)=={"carry_credits","ledger_sha256","inherited_unsettled_attempts"}, "exact authenticated historical proof")
    carry = historical["carry_credits"]; prior_sha = historical["ledger_sha256"]
    inherited = historical["inherited_unsettled_attempts"]
    check(isinstance(carry,str) and 0 <= nano(carry) <= 250_000_000_000, "old cap250 carry remains within its own boundary")
    check(isinstance(prior_sha,str) and len(prior_sha)==64 and all(c in "0123456789abcdef" for c in prior_sha), "prior snapshot hash")
    check(type(inherited) is int and inherited>=64, "all inherited unknown attempts retained")
    index = {s["slot_id"]: s for s in slots}; rid = manifest["run_id"]
    carryover = carryover or {}; original_requests = original_requests or []; original_responses = original_responses or []
    pending = [s for s in slots if s["slot_id"] not in carryover]
    check(set(carryover) <= set(index), "carryover within original plan")
    check(manifest["carryover_slot_ids"] == list(carryover) and manifest["continuation_slot_ids"] == [s["slot_id"] for s in pending], "exact carried and pending manifest")
    check(manifest["original_planned"] == len(slots) and manifest["planned"] == len(pending) and manifest["observed_response_models"] == ROUTE, "segmented manifest counts/routes")
    check(all(r["slot_id"] not in carryover for r in requests+responses+finals), "no carried slot reissued or rewritten")
    check(len(index) == len(slots), "unique scheduled slots")
    check(manifest["schema"] == "retrace.adaption-v6l-run.v1" and manifest["slots"] == slots and manifest["sessions_sha256"] == digest(slots), "run schedule binding")
    check(manifest["runtime_config"] == CONFIG and stamp(manifest["deadline_utc"]) == DEADLINE, "runtime policy binding")
    check(manifest["transport_failure_policy"] == TRANSPORT_POLICY, "exact prospective transport failure policy")
    check(all(type(manifest["runtime_config"][k]) in (int, float) for k in CONFIG), "numeric runtime policy")
    check(manifest["endpoint"] == "https://api.prod.adaptionlabs.ai/api/v1/responses", "declared provider endpoint")
    check(manifest["ready_model_order"] == "deterministic_round_robin_first_appearance; preserve eligible slot order within model", "ready-model scheduling contract")
    check(manifest["test_hooks"] is False or allow_test_hooks, "live run cannot use test hooks")
    check(manifest["store"] is False and manifest["previous_response_id"] is None and manifest["agentic_memory"] is False and manifest["tools"] is False and manifest["stream"] is True, "stateless run contract")
    for model, (i, o, c) in PRICES.items():
        p = manifest["models_pricing"][model]
        check((p["input"], p["output"], p["context"]) == (i, o, c), "frozen prices")
    final = {f["slot_id"]: f for f in finals}
    check(len(final) == len(finals) == len(pending) and set(final) == {s["slot_id"] for s in pending}, "all planned continuation final outcomes")
    final.update(carryover)
    old_rq = {r["attempt_id"]: r for r in original_requests}; old_rp = {r["attempt_id"]: r for r in original_responses}
    check(not set(old_rq) & {r["attempt_id"] for r in requests}, "attempt IDs cannot cross segments")
    rq, rp, by_slot, raw_counts = {}, {}, defaultdict(list), Counter()
    for q in requests:
        aid, sid, n = q["attempt_id"], q["slot_id"], q["attempt_number"]
        check(sid in index and aid not in rq and type(n) is int and 1 <= n <= 3, "request identity")
        check(aid == rid + ":" + sid + ":attempt-" + str(n) and q["first_attempt"] is (n == 1), "request attempt identity")
        check(q["request_sha256"] == digest(q["request"]) and nano(q["reserved_credits"]) == bound(index[sid]), "request body hash/reservation")
        check(stamp(manifest["created_at"]) <= stamp(q["at"]) < DEADLINE, "request admitted outside run/deadline")
        rq[aid] = q
    for r in responses:
        aid = r["attempt_id"]
        check(aid in rq and aid not in rp, "response identity")
        q = rq[aid]; s = index[q["slot_id"]]
        check(r["run_id"] == rid and all(r[k] == s[k] for k in ("slot_id", "case_id", "model", "condition", "phase")), "response slot binding")
        check(r["attempt_number"] == q["attempt_number"] and r["first_attempt"] is q["first_attempt"] and r["issued"] is True, "response attempt binding")
        check(type(r["terminal_valid"]) is bool and nano(r["reserved_credits"]) == bound(s), "response terminal/bound")
        check(r.get("requested_model") == s["model"] and r.get("model_identity_policy") == ("prospectively_pinned_observed_route_not_verified_alias" if s["model"] in ROUTE else "exact_model_id"), "explicit observed route policy")
        expected_return = strict_json(r["raw_response"]).get("model") if r["raw_response"] is not None else (strict_json(read_stream(sha256(aid.encode()).hexdigest()+".sse")).get("model") if r["http_status"] == 429 and r["settled_credits"] is not None else None)
        check(r.get("returned_model") == expected_return, "returned model preserves actual parsed identity")
        m = r.get("stream_evidence")
        check(isinstance(m, dict), "missing raw stream evidence")
        name = sha256(aid.encode()).hexdigest() + ".sse"
        check(PureWindowsPath(m["raw_stream_path"]).name == name, "raw stream filename")
        raw = read_stream(name)
        check(m["closed"] is True and m["credential_redacted"] is False and m["received_bytes"] == len(raw), "raw stream capture length/closure")
        check(m["received_sha256"] == m["saved_sha256"] == sha256(raw).hexdigest() and m["http_status"] == r["http_status"], "raw stream hash/status")
        postheader = check_transport_classification(r)
        # Frozen StreamJournal metadata does not duplicate HTTP headers; the
        # response's logged Retry-After is bound through the ledger digest.
        if r["terminal_valid"]:
            check(r["http_status"] == 200 and r["error"] is None and r["failure_scope"] is None, "successful terminal classification")
            parsed = parse_sse(raw); terminal = parsed["response"]
            check(terminal == strict_json(r["raw_response"]) and terminal["model"] == ROUTE.get(s["model"], s["model"]) and terminal["usage"] == r["usage"], "whole-stream terminal binding")
            check(parsed["event_count"] == r["stream_event_count"] and parsed["terminal"] == r["stream_terminal_event"], "SSE count/terminal")
            text = output_text(terminal)
            nested = "".join(c["text"] for item in terminal.get("output", []) if item.get("type") == "message" and item.get("role") == "assistant" for c in item.get("content", []) if c.get("type") == "output_text")
            check(not nested or nested == text, "duplicate terminal text agreement")
            outcome = "completed" if terminal["status"] == "completed" else "truncated_max_output_tokens"
            check(r["response_status"] == terminal["status"] and r["model_outcome"] == outcome, "terminal outcome binding")
            check(r["output_text"] == (text if outcome == "completed" else "") and r["partial_output_text"] == (text if outcome != "completed" else ""), "returned output binding")
            check(nano(r["settled_credits"]) == cost(s, r["usage"]), "independent usage settlement")
            raw_counts[outcome] += 1
        else:
            check(r["output_text"] == "" and isinstance(r["error"], str), "failed attempt has no repaired output")
            explicit429 = r["http_status"] == 429 and r["error"] == "http_429"
            transient = postheader or r["error"] == "timeout" or (type(r["http_status"]) is int and (r["http_status"] == 408 or 500 <= r["http_status"] <= 599) and r["error"] == "http_" + str(r["http_status"]))
            check(r["failure_scope"] == ("slot" if explicit429 or transient else "global"), "failure scope policy")
            check(r["model_outcome"] == ("http_429" if explicit429 else "operational_failure"), "failed outcome policy")
            if transient:
                check(r["raw_response"] is None and r["response_status"] is None and r["usage"] is None and r["partial_output_text"] == "", "ordinary failed attempt cannot invent terminal/usage")
            if r["raw_response"] is not None and r["http_status"] == 200:
                parsed = parse_sse(raw); terminal = parsed["response"]
                check(terminal == strict_json(r["raw_response"]) and terminal.get("usage") == r["usage"] and terminal.get("status") == r["response_status"], "failed protocol terminal preserves raw status/usage")
                check(parsed["event_count"] == r["stream_event_count"] and parsed["terminal"] == r["stream_terminal_event"], "failed protocol SSE binding")
                if r["error"] == "response_model_mismatch": check(terminal.get("model") != ROUTE.get(s["model"], s["model"]), "observed route mismatch cannot be rescued")
            if r["settled_credits"] is not None:
                check(explicit429, "only explicit429 can settle a failed attempt")
                payload = strict_json(raw)
                check(payload.get("model", ROUTE.get(s["model"], s["model"])) == ROUTE.get(s["model"], s["model"]) and payload.get("usage") == r["usage"], "429 explicit usage source")
                check(nano(r["settled_credits"]) == cost(s, payload["usage"]), "429 usage settlement")
            raw_counts["http_429" if explicit429 else "retained_operational_failure"] += 1
        if r["http_status"] == 429:
            delay = r["retry_cooldown_seconds"]
            check(type(delay) in (int, float) and math.isfinite(delay) and delay >= 65, "any429 minimum cooldown")
            header = r.get("retry_after")
            if isinstance(header, str) and header.strip().isdigit(): check(delay >= float(header.strip()), "numeric Retry-After honored")
            elif isinstance(header, str):
                try: dt = parsedate_to_datetime(header)
                except (ValueError, TypeError, OverflowError): dt = None
                if dt is not None:
                    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                    check(delay + 1e-6 >= max(65, (dt - stamp(r["at"])).total_seconds()), "date Retry-After lower bound")
        else: check(r["retry_cooldown_seconds"] is None, "no invented cooldown")
        start, finish, admit = number(r["attempt_started_monotonic"]), number(r["transport_finished_monotonic"]), number(q["admitted_monotonic"])
        check(admit <= start <= finish and type(r["latency_ms"]) in (int, float) and 0 <= r["latency_ms"] <= (finish-start)*1000 + .001, "attempt monotonic interval")
        rp[aid] = r; by_slot[r["slot_id"]].append(r)
    check(set(rq) == set(rp), "closed run has orphan request/response")
    check([r["attempt_id"] for r in responses] == [q["attempt_id"] for q in requests], "serial response ordering")
    # Reconstruct the ready queues using only outputs already received at each
    # admission. Final outcomes are never used to make future dependencies ready.
    order = list(dict.fromkeys(s["model"] for s in slots))
    cursor = (order.index(original_responses[-1]["model"])+1) % len(order) if original_responses else 0
    queues = {m: [s for s in slots if s["model"] == m] for m in order}
    done = set(carryover); good = {sid for sid, row in carryover.items() if completed(row)}
    def ready_slot():
        for model in order[cursor:] + order[:cursor]:
            for s in queues[model]:
                sid = s["slot_id"]
                if sid in done: continue
                ds = dependencies(s); bad = [d for d in ds if d in done and d not in good]
                if bad:
                    check(final[sid]["model_outcome"] == "not_issued_dependency_failed" and final[sid]["blocked_dependencies"] == bad, "ready-queue failed dependency finalization")
                    done.add(sid); continue
                if any(d not in good for d in ds): continue
                return s
        return None
    for q in requests:
        chosen = ready_slot()
        check(chosen is not None and chosen["slot_id"] == q["slot_id"], "fair ready-model rotation/eligible order")
        cursor = (order.index(chosen["model"]) + 1) % len(order)
        r = rp[q["attempt_id"]]
        if completed(r): good.add(q["slot_id"])
        if not (r["model_outcome"] == "http_429" and r["attempt_number"] < 3): done.add(q["slot_id"])
    if summary["status"] == "completed":
        check(ready_slot() is None and len(done) == len(slots), "completed schedule leaves no pending retry or eligible slot")
    timing = []
    for i, q in enumerate(requests):
        r = rp[q["attempt_id"]]
        if i == 0:
            check(q["previous_attempt_finished_monotonic"] is None, "first request has no same-process predecessor")
            check(stamp(q["at"]) >= stamp(manifest["earliest_next_admission_utc"]), "cross-segment closure gap")
        else:
            prev = rp[requests[i-1]["attempt_id"]]
            closed_at = number(q["previous_attempt_finished_monotonic"])
            delay = max(4, prev["retry_cooldown_seconds"] or 0)
            gap = q["admitted_monotonic"] - closed_at
            check(closed_at >= prev["transport_finished_monotonic"], "finalized completion precedes transport completion")
            check(gap + 1e-9 >= delay, "completion-to-admission gap/cooldown")
            check(r["attempt_started_monotonic"] >= prev["transport_finished_monotonic"], "global nonoverlap")
            timing.append({"attempt_id": q["attempt_id"], "required_seconds": delay, "actual_seconds": gap})
        check(q["request"] == expected_body(index[q["slot_id"]], final, {**old_rq, **rq}), "actual source/history/projection body")
        ds = dependencies(index[q["slot_id"]])
        wanted = [{"slot_id": d, "final_attempt_id": final[d].get("attempt_id"), "output_sha256": sha256(final[d]["output_text"].encode()).hexdigest()} for d in ds]
        check(q["dependency_bindings"] == wanted, "actual dependency binding")
        for dep in ds:
            if dep in carryover: check(stamp(old_rp[final[dep]["attempt_id"]]["at"]) <= stamp(q["at"]), "carried dependency predates admission")
            else: check(rp[final[dep]["attempt_id"]]["transport_finished_monotonic"] <= q["admitted_monotonic"], "dependency occurs before admission")
    for sid, rows in by_slot.items():
        check([r["attempt_number"] for r in rows] == list(range(1, len(rows) + 1)), "attempt prefix")
        for a, b in zip(rows, rows[1:]):
            check(a["model_outcome"] == "http_429" and a["http_status"] == 429 and a["error"] == "http_429", "no non429 retry")
            check(rq[a["attempt_id"]]["request"] == rq[b["attempt_id"]]["request"], "retry body unchanged")
    for f in finals:
        sid = f["slot_id"]
        s = index[sid]
        check(f["slot_final"] is True and all(f[k] == s[k] for k in ("slot_id", "case_id", "model", "condition", "phase")), "final identity")
        if sid in by_slot:
            rows = by_slot[sid]; last = rows[-1]
            check(f["issued"] is True and all(f.get(k) == v for k, v in last.items()) and f["attempts_issued"] == len(rows) and f["first_attempt_id"] == rows[0]["attempt_id"], "final preserves last/first attempts")
        else:
            check(f["issued"] is False and f["terminal_valid"] is False and f["output_text"] == "" and f["attempts_issued"] == 0 and f["first_attempt_id"] is None, "unissued outcome cannot succeed")
            check(f["model_outcome"] in ("not_issued_dependency_failed", "not_issued_global_stop"), "unissued reason")
            if f["model_outcome"] == "not_issued_dependency_failed":
                blocked = f["blocked_dependencies"]
                check(bool(blocked) and set(blocked) <= set(dependencies(s)) and all(not completed(final[d]) for d in blocked), "genuine failed dependency")
    # Independent integer ledger replay, including every retained full bound.
    account, chain, events, halts, started, closed = nano(carry), "0" * 64, {}, [], False, False
    max_account = account
    for n, row in enumerate(ledger, 1):
        check(row["seq"] == n and row["previous_sha256"] == chain and row["sha256"] == digest({k: v for k, v in row.items() if k != "sha256"}), "ledger chain")
        chain = row["sha256"]; e = row["event"]; kind = e["kind"]
        if n == 1: check(kind == "initialize" and e["historical_credits"] == carry and e["historical_sha256"] == prior_sha and e["cap_credits"] == "750", "full old carry initialization")
        elif kind == "run_started":
            check(not started and not closed and e["run_id"] == rid and e["planned"] == len(pending) and e["sessions_sha256"] == digest(slots), "ledger one run start")
            check(e["execution_manifest_sha256"] == manifest["execution_manifest_sha256"] and e["continuation_sha256"] == manifest["continuation_sha256"], "ledger execution/continuation binding")
            started = True
        elif kind == "reserve":
            aid = e["attempt_id"]
            check(started and not closed and not halts and aid in rq and aid not in events, "reservation in active unhalted run")
            q = rq[aid]; s = index[q["slot_id"]]
            check(e["run_id"] == rid and e["slot_id"] == s["slot_id"] and e["model"] == s["model"] and e["attempt_number"] == q["attempt_number"] and e["bound_nanocredits"] == bound(s), "ledger reservation identity/bound")
            check(stamp(row["at"]) < DEADLINE and stamp(row["at"]) <= stamp(q["at"]), "reservation before request/deadline")
            check(all(v["kind"] is not None for v in events.values()), "serial prior attempt accounted before next reservation")
            events[aid] = {"bound": e["bound_nanocredits"], "kind": None, "reserve_seq": n}; account += e["bound_nanocredits"]
        elif kind in ("settle", "retain_429", "retain_unknown"):
            aid = e["attempt_id"]
            check(started and not closed and aid in events and events[aid]["kind"] is None and e["response_sha256"] == digest(rp[aid]), "one accounting event binds raw response")
            a = events[aid]; r = rp[aid]; a["kind"] = kind
            if kind == "settle":
                check(r["settled_credits"] is not None and e["accounted_nanocredits"] == nano(r["settled_credits"]) <= a["bound"], "ledger exact settlement")
                account += e["accounted_nanocredits"] - a["bound"]
            elif kind == "retain_429": check(r["model_outcome"] == "http_429" and r["settled_credits"] is None, "full429 retention")
            else: check(r["model_outcome"] == "operational_failure" and r["settled_credits"] is None and e["reason"] == r["error"], "full operational retention")
        elif kind == "halt":
            check(started and not closed and e["run_id"] == rid, "halt scope")
            halts.append(e["reason"])
        elif kind == "run_closed":
            check(started and not closed and e["run_id"] == rid and e["status"] == summary["status"] and e["issued_attempts"] == len(requests) and e["issued_slots"] == len(by_slot) and e["unissued_slots"] == len(pending)-len(by_slot), "ledger closure counts")
            closed = True
        else: raise ValueError("unknown/repeated ledger event")
        check(0 <= account <= CAP, "cumulative cap respected")
        max_account = max(max_account, account)
    check(started and closed and ledger[-1]["event"]["kind"] == "run_closed" and set(events) == set(rq) and all(a["kind"] is not None for a in events.values()), "closed fully accounted ledger")
    global_failures = [r for r in responses if r.get("failure_scope") == "global"]
    for r in global_failures:
        check(r["error"] in halts, "global failure requires its recorded halt")
        check(responses[-1]["attempt_id"] == r["attempt_id"], "no admission after global failure")
    global_skips = any(f["model_outcome"] == "not_issued_global_stop" for f in finals)
    check(not global_skips or bool(halts), "global-stop outcome requires a recorded halt")
    check(not (global_failures or global_skips) or summary["status"] == "stopped", "global failure/skip cannot be a completed schedule")
    check(summary["schema"] == "retrace.adaption-v6l-summary.v1" and summary["run_id"] == rid and summary["runtime_config"] == CONFIG, "summary identity/policy")
    check(summary["transport_failure_policy"] == TRANSPORT_POLICY, "summary transport failure policy")
    check(summary["original_planned"] == len(slots) and summary["carried_over_slots"] == len(carryover) and summary["carryover_slot_ids"] == list(carryover) and summary["continuation_slot_ids"] == [s["slot_id"] for s in pending] and summary["observed_response_models"] == ROUTE and summary["continuation_sha256"] == manifest["continuation_sha256"], "summary segmented cohort/route binding")
    check(summary["models"] == dict(Counter(s["model"] for s in pending)) and summary["max_retries_per_slot"] == 2 and summary["actual_billed_credits"] is None, "summary model/retry/accounting contract")
    check(summary["status"] == ("stopped" if halts else "completed") and summary["stop_reasons"] == list(dict.fromkeys(halts)), "closure is separate from success")
    first = [r for r in responses if r["first_attempt"]]
    counts = {"planned": len(pending), "issued_attempts": len(requests), "issued_slots": len(by_slot), "responses": len(responses), "slot_outcomes": len(finals),
              "completed": sum(completed(f) for f in finals), "eventual_completed": sum(completed(f) for f in finals),
              "first_attempt_completed": sum(completed(r) for r in first), "first_attempt_valid_terminal_records": sum(r["terminal_valid"] for r in first),
              "first_attempt_truncated": sum(r["model_outcome"] == "truncated_max_output_tokens" for r in first), "first_attempt_http_429": sum(r["model_outcome"] == "http_429" for r in first),
              "valid_terminal_records": sum(r["terminal_valid"] for r in responses), "eventual_terminal_slots": sum(f["terminal_valid"] for f in finals),
              "truncated": sum(f["model_outcome"] == "truncated_max_output_tokens" for f in finals), "http_429_attempts": sum(r["model_outcome"] == "http_429" for r in responses),
              "issued_operational_failures": sum(r["model_outcome"] == "operational_failure" for r in responses),
              "per_slot_operational_failures": sum(r["model_outcome"] == "operational_failure" and r["failure_scope"] == "slot" for r in responses),
              "dependency_skips": sum(f["model_outcome"] == "not_issued_dependency_failed" for f in finals), "retries": len(requests) - len(by_slot)}
    check(all(summary.get(k) == v for k, v in counts.items()), "recomputed first/eventual/denominator counts")
    check(summary["unissued_slot_ids"] == [s["slot_id"] for s in pending if s["slot_id"] not in by_slot] and summary["issued_without_outcome_attempt_ids"] == [] and summary["all_scheduled_outcomes_recorded"] is True, "all slots accounted without hidden requests")
    b = summary["budget"]; kinds = Counter(a["kind"] for a in events.values())
    expected = {"accounted_credits": credits(account), "remaining_credits": credits(CAP-account), "historical_carry_credits": carry,
                "cumulative_cap_credits": "750", "ledger_sha256": chain, "attempt_reservations": len(events), "settled_attempts": kinds["settle"],
                "unsettled_attempts": len(events)-kinds["settle"], "unknown_429_attempts_retained": kinds["retain_429"],
                "unknown_operational_attempts_retained": kinds["retain_unknown"], "halted": bool(halts), "actual_billed_credits": None}
    check(all(b.get(k) == v for k, v in expected.items()), "independent budget snapshot")
    check(b["cumulative_inherited_unsettled_attempts"] == inherited and manifest["budget_before"]["accounted_credits"] == carry and manifest["budget_before"]["cumulative_cap_credits"] == "750", "earlier unknowns remain carried")
    old_by_slot = defaultdict(list)
    for row in original_responses: old_by_slot[row["slot_id"]].append(row)
    first_pipeline, eventual_pipeline = {}, {}
    for slot in slots:
        sid = slot["slot_id"]
        if sid not in carryover: continue
        earlier = old_by_slot.get(sid, [])
        first_pipeline[sid] = bool(earlier and completed(earlier[0]) and all(first_pipeline.get(d,False) for d in dependencies(slot)))
        eventual_pipeline[sid] = bool(completed(carryover[sid]) and all(eventual_pipeline.get(d,False) for d in dependencies(slot)))
    for s in pending:
        sid = s["slot_id"]; rows = by_slot.get(sid, [])
        first_pipeline[sid] = bool(rows and completed(rows[0]) and all(first_pipeline.get(d, False) for d in dependencies(s)))
        eventual_pipeline[sid] = completed(final[sid]) and all(eventual_pipeline.get(d, False) for d in dependencies(s))
    return {"passed": True, "final_closed": True, "all_scheduled_outcomes_accounted": True, "planned_slots": len(pending), "original_planned_slots": len(slots), "carried_over_slots": len(carryover), "historical_carry_credits": carry,
            "budget_cap_credits": "750", "inherited_unsettled_attempts": inherited, "checks": checks, "schedule_status": summary["status"], "counts": counts, "raw_stream_counts": dict(raw_counts),
            "first_attempt_dependency_eligible_completed": sum(first_pipeline[s["slot_id"]] for s in pending),
            "eventual_dependency_eligible_completed": sum(eventual_pipeline[s["slot_id"]] for s in pending),
            "cumulative_accounted_credits": credits(account), "maximum_accounted_credits": credits(max_account), "ledger_entries": len(ledger), "ledger_chain_sha256": chain,
            "known_run_usage_credits": credits(sum(nano(r["settled_credits"]) for r in responses if r["settled_credits"] is not None)),
            "retained_run_bounds_credits": credits(sum(a["bound"] for a in events.values() if a["kind"] != "settle")),
            "minimum_completion_gap_seconds": min((r["actual_seconds"] for r in timing), default=None),
            "minimum_cooldown_margin_seconds": min((r["actual_seconds"]-r["required_seconds"] for r in timing if r["required_seconds"] >= 65), default=None),
            "observed_peak_transports": 1 if requests else 0, "timing_checks": timing}


ALLOWED_ALIAS = original_audit.ALLOWED_ALIAS
I_FREEZE_SHA = "156173e0dabc3a6f88c4301847f892f16bd6d0d73fd7c83c6d3dfc64b3a3a600"
J_FREEZE_SHA = "6fffc08ce31ac6aa19079be690a244a0e9b649d4a6281f7df8d53038c3811ea0"
K_FREEZE_SHA = "274d3101ed47e3ca918ee1e2273c0cdd269b43c60567e3fa4e121f6a7b9efa40"
PREFIXES = {"i":"results/frontier-v6i/primary/", "j":"results/frontier-v6j/continuation/", "k":"results/frontier-v6k/continuation/"}
ROLE_NAMES = {"run_manifest":"run.json", "requests":"requests.jsonl", "responses":"responses.jsonl",
              "outcomes":"slot-outcomes.jsonl", "summary":"summary.json", "audit":"runtime-audit.json"}
BASELINE = "data/frontier-v6k-ledger-after-continuation.jsonl"


def audit(root, freeze_sha256, *, frozen_aliases=None, ledger_snapshot=None):
    """Authenticate three closed historical segments, then replay only the fourth.

    The exact k audit independently preserves the older 250-credit boundary.
    Only its budget-stop closure authorizes the new 750-credit ledger. All
    dynamic counts and retained unknowns come from that authenticated closure.
    """
    root=Path(root).resolve(); aliases=dict(frozen_aliases or {}); bindings={}
    if aliases and aliases != ALLOWED_ALIAS: raise ValueError("only the exact inert historical lock alias is allowed")
    substitutes=dict(aliases)
    def relative(name):
        if not isinstance(name,str) or not name or Path(name).is_absolute() or PureWindowsPath(name).is_absolute() or ":" in name or any(p in ("",".","..") for p in name.replace("\\","/").split("/")):
            raise ValueError("unambiguous relative artifact path required")
        return name.replace("\\","/")
    def safe(name):
        name=relative(name); p=(root/relative(substitutes.get(name,name))).resolve()
        if not p.is_relative_to(root) or not p.is_file(): raise ValueError("missing/escaping artifact path")
        return p
    def hashed(name):
        p=safe(name); h=sha256()
        with p.open("rb") as f:
            for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
        value={"sha256":h.hexdigest(),"bytes":p.stat().st_size}
        if name in bindings and bindings[name]!=value: raise ValueError("artifact changed during audit")
        bindings[name]=value; return value["sha256"]
    def read(name):
        expected=hashed(name); raw=safe(name).read_bytes()
        if sha256(raw).hexdigest()!=expected: raise ValueError("artifact changed during read")
        return raw
    def obj(name): return strict_json(read(name))
    fname="data/frontier-v6l-freeze.json"
    if hashed(fname)!=freeze_sha256: raise ValueError("new execution freeze hash")
    freeze=obj(fname); inventory={}
    if (freeze["schema"]!="retrace.frontier-v6l-freeze.v1" or freeze["cumulative_cap_credits"]!="750"
        or freeze["previous_cumulative_cap_credits"]!="250" or freeze["runtime_config"]!=CONFIG
        or any(type(freeze["runtime_config"][key]) not in (int,float) for key in CONFIG)
        or stamp(freeze["deadline_utc"])!=DEADLINE): raise ValueError("new freeze schema/cap750/unchanged policy")
    for row in freeze["files"]:
        name=relative(row["path"])
        if name in inventory or hashed(name)!=row["sha256"]: raise ValueError("changed/duplicate frozen file")
        if "bytes" in row and bindings[name]["bytes"]!=row["bytes"]: raise ValueError("frozen byte length")
        inventory[name]=row["sha256"]
    if inventory.get("scripts/audit_frontier_v6l_runtime.py")!=sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError("executed independent auditor is not in the execution freeze")
    if not set(aliases)<=set(inventory): raise ValueError("historical alias not frozen")
    for key,path in (("authorization","data/frontier-v6l-authorization.json"),("continuation","data/frontier-v6l-continuation.json")):
        if freeze[key+"_path"]!=path or hashed(path)!=freeze[key+"_sha256"] or inventory.get(path)!=freeze[key+"_sha256"]:
            raise ValueError("frozen new "+key+" binding")
    auth=obj(freeze["authorization_path"]); receipt=obj(freeze["continuation_path"])
    if auth["schema"]!="retrace.frontier-v6l-authorization.v1" or receipt["schema"]!="retrace.frontier-v6l-continuation.v1":
        raise ValueError("four-segment authorization/receipt schemas")
    if auth["prior_status"]!="stopped" or auth["prior_stop_reason"]!="cumulative_budget_stop": raise ValueError("authorization only for prior budget stop")
    for value in (auth,receipt):
        if (value["prior_freeze_path"]!="data/frontier-v6k-freeze.json" or value["prior_freeze_sha256"]!=K_FREEZE_SHA
            or value["previous_cumulative_cap_credits"]!="250" or value["cumulative_cap_credits"]!="750"
            or stamp(value["deadline_utc"])!=DEADLINE):
            raise ValueError("prospective cap750 only; old cap250 and deadline unchanged")
    if hashed("data/frontier-v6k-freeze.json")!=K_FREEZE_SHA: raise ValueError("exact old k freeze")
    oldfreeze=obj("data/frontier-v6k-freeze.json")
    protected=auth["protected"]
    if not isinstance(protected,dict) or not protected or auth["protected_v5_file_count"]!=402:
        raise ValueError("historical protected inventory and v5 count")
    if protected.get("data/frontier-v6k-freeze.json")!=K_FREEZE_SHA or any(protected.get(r["path"])!=r["sha256"] for r in oldfreeze["files"]):
        raise ValueError("all old k frozen bytes remain protected")
    if any(inventory.get(name)!=expected for name,expected in protected.items()): raise ValueError("historical pin not frozen")
    if any(value["baseline_snapshot_path"]!=BASELINE for value in (auth,receipt)) or freeze["baseline_path"]!=BASELINE:
        raise ValueError("canonical closed-k snapshot")
    prior_sha=hashed(BASELINE)
    if any(value["baseline_snapshot_sha256"]!=prior_sha for value in (auth,receipt)) or freeze["baseline_sha256"]!=prior_sha or inventory.get(BASELINE)!=prior_sha:
        raise ValueError("immutable old full-carry snapshot")
    # No historical active process can be relabeled as a closed prior segment.
    if (root/"results/frontier-v6k/budget/active.lock").exists(): raise ValueError("prior k segment still active")
    canonical_prior="results/frontier-v6k/budget/ledger.jsonl"
    if (root/canonical_prior).exists() and hashed(canonical_prior)!=prior_sha: raise ValueError("closed-k ledger differs from its snapshot")
    substitutes[canonical_prior]=BASELINE
    prior_k=prior_k_audit.audit(root,K_FREEZE_SHA,frozen_aliases=aliases,ledger_snapshot=BASELINE)
    priors={"i":prior_k["prior_segment_audits"]["i"],"j":prior_k["prior_segment_audits"]["j"],"k":prior_k}
    for name,prior in priors.items():
        if (obj(PREFIXES[name]+"runtime-audit.json")!=prior or prior.get("passed") is not True
            or prior.get("final_closed") is not True or prior.get("all_scheduled_outcomes_accounted") is not True or prior["schedule_status"]!="stopped"):
            raise ValueError("prior stopped segment independent replay differs")
        for member,binding in prior["input_bindings"].items():
            if hashed(member)!=binding["sha256"] or bindings[member]["bytes"]!=binding["bytes"]: raise ValueError("prior source binding changed")
    carry=prior_k["cumulative_accounted_credits"]
    prior_summary=obj(PREFIXES["k"]+"summary.json"); prior_budget=prior_summary["budget"]
    if prior_summary["status"]!="stopped" or prior_summary["stop_reasons"]!=["cumulative_budget_stop"]:
        raise ValueError("only the authenticated k cumulative_budget_stop authorizes l")
    if prior_budget["cumulative_cap_credits"]!="250" or prior_budget["accounted_credits"]!=carry or nano(carry)>250_000_000_000:
        raise ValueError("old k budget remains capped at250")
    if any(type(prior_budget[key]) is not int or prior_budget[key]<0 for key in ("cumulative_inherited_unsettled_attempts","unsettled_attempts")):
        raise ValueError("integer historical unknown counts")
    inherited=prior_budget["cumulative_inherited_unsettled_attempts"]+prior_budget["unsettled_attempts"]
    if type(inherited) is not int or inherited<64 or any(type(value["inherited_unsettled_attempts"]) is not int or value["inherited_unsettled_attempts"]!=inherited for value in (auth,receipt)):
        raise ValueError("all dynamic prior unknown reservations retained")
    if any(value["historical_conservative_carry_credits"]!=carry for value in (freeze,auth,receipt)) or freeze["observed_response_models"]!=ROUTE or receipt["observed_response_models"]!=ROUTE:
        raise ValueError("authenticated dynamic carry/unchanged route")
    slots=obj(freeze["sessions_path"])
    if (freeze["sessions_path"]!="data/frontier-v6i-sessions.json" or receipt["sessions_path"]!=freeze["sessions_path"]
        or len(slots)!=1800 or digest(slots)!=freeze["sessions_sha256"] or digest(slots)!=receipt["sessions_sha256"]
        or hashed(freeze["sessions_path"])!=freeze["sessions_file_sha256"]):
        raise ValueError("unchanged1800 slots and exact source bodies")
    for name,expected in receipt["prior_journal_files"].items():
        if hashed(name)!=expected or inventory.get(name)!=expected: raise ValueError("frozen prior journal pin")
    source_segments=receipt["source_segments"]
    if [s["segment"] for s in source_segments]!=["i","j","k"]: raise ValueError("exact ordered prior segments")
    values={}; oldq=[]; oldr=[]; definitive={}; run_ids=[]
    for entry in source_segments:
        name=entry["segment"]; expected={r:PREFIXES[name]+file for r,file in ROLE_NAMES.items()}
        expected["ledger"]="results/frontier-v6"+name+"/budget/ledger.jsonl"
        if entry["paths"]!=expected or set(entry["sha256"])!=set(expected): raise ValueError("canonical prior segment roles")
        if entry["freeze_path"]!="data/frontier-v6"+name+"-freeze.json" or entry["freeze_sha256"]!={"i":I_FREEZE_SHA,"j":J_FREEZE_SHA,"k":K_FREEZE_SHA}[name]: raise ValueError("prior segment freeze")
        for role,path in expected.items():
            if hashed(path)!=entry["sha256"][role] or receipt["prior_journal_files"].get(path)!=entry["sha256"][role]:
                raise ValueError("prior segment exact frozen bytes")
        rows={role:jsonl(read(expected[role])) for role in ("requests","responses","outcomes")}
        summary=obj(expected["summary"]); manifest=obj(expected["run_manifest"])
        if summary["run_id"]!=entry["run_id"] or manifest["run_id"]!=entry["run_id"] or summary["status"]!="stopped": raise ValueError("prior run identity/status")
        selected=[r for r in rows["outcomes"] if r["issued"] or r["model_outcome"]=="not_issued_dependency_failed"]
        issued=sum(r["issued"] is True for r in selected)
        if len({r["slot_id"] for r in selected})!=len(selected) or entry["definitive_final_slots"]!=len(selected) or entry["issued_slots"]!=issued:
            raise ValueError("dynamic definitive prior count")
        if (len(rows["requests"])!=priors[name]["counts"]["issued_attempts"] or len(rows["responses"])!=len(rows["requests"])
            or issued!=priors[name]["counts"]["issued_slots"] or len(selected)-issued!=priors[name]["counts"]["dependency_skips"]):
            raise ValueError("prior attempt/final counts")
        if name in ("i","j"):
            stop="response_model_mismatch" if name=="i" else "network_or_transport_failure"
            if summary["stop_reasons"]!=[stop] or issued!={"i":6,"j":207}[name] or len(selected)!={"i":6,"j":218}[name] or summary["retries"]!=0:
                raise ValueError("original i/j interruption retained")
            failed=[r for r in rows["responses"] if r.get("failure_scope")=="global"]
            if len(failed)!=1 or failed[0]["error"]!=stop or failed[0]["terminal_valid"] is not False or failed[0] is not rows["responses"][-1]:
                raise ValueError("old global failure preserved")
        elif summary["stop_reasons"]!=["cumulative_budget_stop"] or any(r.get("failure_scope")=="global" for r in rows["responses"]):
            raise ValueError("k continuation trigger cannot hide another interruption")
        values[name]=rows; definitive[name]={r["slot_id"]:r for r in selected}
        oldq.extend(rows["requests"]); oldr.extend(rows["responses"]); run_ids.append(entry["run_id"])
    if len(set(run_ids))!=3 or receipt["original_run_ids"]!=run_ids or receipt["original_run_id"]!=run_ids[0]: raise ValueError("distinct prior run IDs")
    carried={}; carry_segments=Counter()
    for ref in receipt["carried_final_outcomes"]:
        name=ref["segment"]; line=ref["source_line_one_based"]
        if name not in values or ref["source_path"]!=PREFIXES[name]+"slot-outcomes.jsonl" or type(line) is not int or not 1<=line<=len(values[name]["outcomes"]): raise ValueError("valid carryover source index")
        row=values[name]["outcomes"][line-1]; sid=row["slot_id"]
        if (sid in carried or sid!=ref["slot_id"] or digest(row)!=ref["row_sha256"] or row.get("attempt_id")!=ref["attempt_id"]
            or row["model_outcome"]!=ref["model_outcome"] or definitive[name].get(sid)!=row): raise ValueError("exact definitive carried row")
        carried[sid]=row; carry_segments[name]+=1
    issued_ids=[sid for sid,row in carried.items() if row["issued"]]
    pending=[s["slot_id"] for s in slots if s["slot_id"] not in carried]
    expected_segments={name:len(definitive[name]) for name in PREFIXES}
    expected_ids=set().union(*(set(rows) for rows in definitive.values()))
    if (dict(carry_segments)!=expected_segments or len(expected_ids)!=sum(expected_segments.values()) or set(carried)!=expected_ids
        or list(carried)!=receipt["permanently_excluded_final_slot_ids"] or issued_ids!=receipt["permanently_excluded_issued_slot_ids"]):
        raise ValueError("all prior definitive rows retained once")
    if not pending or pending!=receipt["continuation_slot_ids"]: raise ValueError("nonempty untouched complement only")
    expected_counts={"full_planned_slots":1800,"carried_issued_slots":len(issued_ids),"carried_final_slots":len(carried),"continuation_slots":len(pending)}
    if any(type(receipt.get(k)) is not int or receipt[k]!=v for k,v in expected_counts.items()): raise ValueError("dynamic receipt cohort sizes")
    freeze_counts={"scheduled_slots":1800,"carried_issued_slots":len(issued_ids),"carried_final_slots":len(carried),"continuation_slots":len(pending)}
    if any(type(freeze.get(k)) is not int or freeze[k]!=v for k,v in freeze_counts.items()): raise ValueError("dynamic freeze cohort sizes")
    # Recompute the transitive failed-producer descendants rather than trusting
    # a receipt-maintained list to silently exclude or admit dependent calls.
    blocked={sid for sid,row in carried.items() if not completed(row)}; descendant=[]
    for slot in slots:
        if slot["slot_id"] not in carried and any(d in blocked for d in dependencies(slot)):
            blocked.add(slot["slot_id"]); descendant.append(slot["slot_id"])
    if descendant!=receipt["failed_producer_descendant_slot_ids"]: raise ValueError("exact failed-producer descendants")
    run=freeze["output_path"].rstrip("/"); ledgerdir=freeze["ledger_path"].rstrip("/")
    if run!="results/frontier-v6l/continuation" or ledgerdir!="results/frontier-v6l/budget": raise ValueError("canonical new segment paths")
    if (root/ledgerdir/"active.lock").exists(): raise ValueError("continuation still active")
    if ledger_snapshot is not None:
        snapshot=relative(ledger_snapshot)
        if snapshot in inventory or snapshot==BASELINE: raise ValueError("new ledger snapshot cannot substitute a historical artifact")
        canonical=ledgerdir+"/ledger.jsonl"
        if (root/canonical).exists() and hashed(canonical)!=sha256(safe(snapshot).read_bytes()).hexdigest(): raise ValueError("new closed ledger differs from immutable snapshot")
        substitutes[canonical]=snapshot
    manifest=obj(run+"/run.json")
    if manifest["execution_manifest_sha256"]!=freeze_sha256 or stamp(manifest["created_at"])<stamp(freeze["created_at"]) or manifest["run_id"] in run_ids: raise ValueError("prospective distinct new run")
    if manifest["continuation_sha256"]!=freeze["continuation_sha256"] or manifest["continuation_path"]!=freeze["continuation_path"] or manifest["carryover_bindings"]!=receipt["carried_final_outcomes"]: raise ValueError("manifest authenticated carry")
    prior_rows=jsonl(read(BASELINE))
    if prior_rows[-1]["sha256"]!=prior_k["ledger_chain_sha256"] or prior_rows[-1]["event"]["kind"]!="run_closed": raise ValueError("authenticated prior terminal chain")
    earliest=stamp(prior_rows[-1]["at"])+__import__("datetime").timedelta(seconds=4)
    if stamp(manifest["earliest_next_admission_utc"])!=earliest: raise ValueError("cross-process earliest admission")
    finals=jsonl(read(run+"/slot-outcomes.jsonl")); fidx={r["slot_id"]:r for r in finals}; summary=obj(run+"/summary.json")
    if summary["status"]=="completed":
        for sid in descendant:
            if fidx[sid]["model_outcome"]!="not_issued_dependency_failed" or fidx[sid]["issued"]: raise ValueError("failed producer cannot be reused")
    result=audit_evidence(slots,manifest,jsonl(read(run+"/requests.jsonl")),jsonl(read(run+"/responses.jsonl")),finals,summary,
        jsonl(read(ledgerdir+"/ledger.jsonl")),lambda name:read(run+"/streams/"+name),carryover=carried,original_requests=oldq,original_responses=oldr,
        historical={"carry_credits":carry,"ledger_sha256":prior_sha,"inherited_unsettled_attempts":inherited})
    for name in list(bindings): hashed(name)
    result.update(schema="retrace.frontier-v6l-runtime-independent-audit.v1",
        audit_scope="Four-segment infrastructure replay. Prior i/j/k statuses, failures and cap250 are preserved. Only the unchanged unissued complement is admitted under the separately authorized cumulative cap750.",
        frozen_files=len(inventory),protected_historical_files=len(protected),protected_v5_files=402,input_bindings=bindings,
        prior_segment_audits=priors,auditor_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        limits=["Local hashes/timestamps and exception-class fields are unsigned execution evidence, not provider signatures or independently proven Python exception identity.",
                "Closed accounting does not imply a completed scientific schedule or successful responses.",
                "Every inherited unknown reservation remains in the full carry; only new accepted usage settles. Actual billing is unavailable.",
                "The observed diagnostic response route is not verified weight, precision or price equivalence."])
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=ROOT);p.add_argument("--freeze-sha256",required=True)
    p.add_argument("--aliases",type=Path);p.add_argument("--ledger-snapshot")
    p.add_argument("--output",type=Path,required=True);p.add_argument("--markdown",type=Path,required=True)
    a=p.parse_args()
    if a.output.resolve()==a.markdown.resolve() or a.output.exists() or a.markdown.exists(): raise ValueError("exclusive new outputs required")
    aliases=strict_json(a.aliases.read_bytes()) if a.aliases else None
    result=audit(a.root,a.freeze_sha256,frozen_aliases=aliases,ledger_snapshot=a.ledger_snapshot)
    with a.output.open("x",encoding="utf-8",newline="\n") as f: json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False); f.write("\n")
    with a.markdown.open("x",encoding="utf-8",newline="\n") as f:
        f.write("# Independent v6l continuation audit\n\n"+result["audit_scope"]+"\n\nStatus: "+result["schedule_status"]+"; scheduled continuation slots: "+str(result["counts"]["planned"])+". Conservative cumulative credits: "+result["cumulative_accounted_credits"]+" / 750.\n")
    print(json.dumps({k:result[k] for k in ("passed","checks","schedule_status","counts","cumulative_accounted_credits","budget_cap_credits")}))


if __name__=="__main__": main()

