"""Independent infrastructure audit of a CLOSED v6j continuation; no provider/semantic calls.

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

CAP = 250_000_000_000
CARRY = "47.653269434"
PRIOR_SHA = "899d54ea6c6780ecf4474abef51ba97b3b7068483c998f7babfa8dd8c44185d1"
PRIOR_CHAIN = "0d7bde3bb481f594683d543822c6ca112deb7c4c0df55aaabb41a287bd8b7773"
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
ROUTE = {"qwen3.5-397b": "qwen3.5-397b-a17b-nvfp4"}

def audit_evidence(slots, manifest, requests, responses, finals, summary, ledger, read_stream, *, carryover=None, original_requests=None, original_responses=None, allow_test_hooks=False):
    """Pure closed-run replay. Test hooks allowed only by explicit fixture callers."""
    checks = 0
    def check(ok, why):
        nonlocal checks
        checks += 1
        if not ok: raise ValueError(why)
    def number(value):
        check(type(value) in (int, float) and math.isfinite(value), "finite monotonic timestamp")
        return value
    index = {s["slot_id"]: s for s in slots}; rid = manifest["run_id"]
    carryover = carryover or {}; original_requests = original_requests or []; original_responses = original_responses or []
    pending = [s for s in slots if s["slot_id"] not in carryover]
    check(set(carryover) <= set(index), "carryover within original plan")
    check(manifest["carryover_slot_ids"] == list(carryover) and manifest["continuation_slot_ids"] == [s["slot_id"] for s in pending], "exact carried and pending manifest")
    check(manifest["original_planned"] == len(slots) and manifest["planned"] == len(pending) and manifest["observed_response_models"] == ROUTE, "segmented manifest counts/routes")
    check(all(r["slot_id"] not in carryover for r in requests+responses+finals), "no carried slot reissued or rewritten")
    check(len(index) == len(slots), "unique scheduled slots")
    check(manifest["schema"] == "retrace.adaption-v6j-run.v1" and manifest["slots"] == slots and manifest["sessions_sha256"] == digest(slots), "run schedule binding")
    check(manifest["runtime_config"] == CONFIG and stamp(manifest["deadline_utc"]) == DEADLINE, "runtime policy binding")
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
            transient = r["error"] == "timeout" or (type(r["http_status"]) is int and (r["http_status"] == 408 or 500 <= r["http_status"] <= 599) and r["error"] == "http_" + str(r["http_status"]))
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
    account, chain, events, halts, started, closed = nano(CARRY), "0" * 64, {}, [], False, False
    max_account = account
    for n, row in enumerate(ledger, 1):
        check(row["seq"] == n and row["previous_sha256"] == chain and row["sha256"] == digest({k: v for k, v in row.items() if k != "sha256"}), "ledger chain")
        chain = row["sha256"]; e = row["event"]; kind = e["kind"]
        if n == 1: check(kind == "initialize" and e["historical_credits"] == CARRY and e["historical_sha256"] == PRIOR_SHA and e["cap_credits"] == "250", "full old carry initialization")
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
    check(summary["schema"] == "retrace.adaption-v6j-summary.v1" and summary["run_id"] == rid and summary["runtime_config"] == CONFIG, "summary identity/policy")
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
    expected = {"accounted_credits": credits(account), "remaining_credits": credits(CAP-account), "historical_carry_credits": CARRY,
                "cumulative_cap_credits": "250", "ledger_sha256": chain, "attempt_reservations": len(events), "settled_attempts": kinds["settle"],
                "unsettled_attempts": len(events)-kinds["settle"], "unknown_429_attempts_retained": kinds["retain_429"],
                "unknown_operational_attempts_retained": kinds["retain_unknown"], "halted": bool(halts), "actual_billed_credits": None}
    check(all(b.get(k) == v for k, v in expected.items()), "independent budget snapshot")
    check(b["cumulative_inherited_unsettled_attempts"] == 17 and manifest["budget_before"]["accounted_credits"] == CARRY, "earlier unknowns remain carried")
    first_pipeline = {sid: completed(f) for sid,f in carryover.items()}; eventual_pipeline = dict(first_pipeline)
    for s in pending:
        sid = s["slot_id"]; rows = by_slot.get(sid, [])
        first_pipeline[sid] = bool(rows and completed(rows[0]) and all(first_pipeline.get(d, False) for d in dependencies(s)))
        eventual_pipeline[sid] = completed(final[sid]) and all(eventual_pipeline.get(d, False) for d in dependencies(s))
    return {"passed": True, "final_closed": True, "all_scheduled_outcomes_accounted": True, "planned_slots": len(pending), "original_planned_slots": len(slots), "carried_over_slots": len(carryover), "historical_carry_credits": CARRY,
            "checks": checks, "schedule_status": summary["status"], "counts": counts, "raw_stream_counts": dict(raw_counts),
            "first_attempt_dependency_eligible_completed": sum(first_pipeline[s["slot_id"]] for s in pending),
            "eventual_dependency_eligible_completed": sum(eventual_pipeline[s["slot_id"]] for s in pending),
            "cumulative_accounted_credits": credits(account), "maximum_accounted_credits": credits(max_account), "ledger_entries": len(ledger), "ledger_chain_sha256": chain,
            "known_run_usage_credits": credits(sum(nano(r["settled_credits"]) for r in responses if r["settled_credits"] is not None)),
            "retained_run_bounds_credits": credits(sum(a["bound"] for a in events.values() if a["kind"] != "settle")),
            "minimum_completion_gap_seconds": min((r["actual_seconds"] for r in timing), default=None),
            "minimum_cooldown_margin_seconds": min((r["actual_seconds"]-r["required_seconds"] for r in timing if r["required_seconds"] >= 65), default=None),
            "observed_peak_transports": 1 if requests else 0, "timing_checks": timing}


ALLOWED_ALIAS = original_audit.ALLOWED_ALIAS
ORIGINAL_FREEZE_SHA = "156173e0dabc3a6f88c4301847f892f16bd6d0d73fd7c83c6d3dfc64b3a3a600"
RECEIPT_SHA = "89310028826c19aee5393e4f38ba236062aaeb0db8dc434306164997ff00eba4"


def audit(root, freeze_sha256, *, frozen_aliases=None, ledger_snapshot=None):
    """Authenticate both raw segments; return root-independent evidence.

    Original i remains a separately authenticated stopped run. A completed j
    result certifies only1794 continuation finals, never retroactive success.
    """
    root = Path(root).resolve(); aliases = dict(frozen_aliases or {}); bindings = {}
    if aliases and aliases != ALLOWED_ALIAS: raise ValueError("only the exact inert historical lock alias is allowed")
    substitutes = dict(aliases)
    def safe(name):
        if not isinstance(name,str) or Path(name).is_absolute() or PureWindowsPath(name).is_absolute() or ".." in name.replace("\\", "/").split("/"): raise ValueError("relative artifact path required")
        p = (root/substitutes.get(name,name)).resolve()
        if not p.is_relative_to(root) or not p.is_file(): raise ValueError("missing/escaping artifact path")
        return p
    def hashed(name):
        p = safe(name); h = sha256()
        with p.open("rb") as f:
            for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
        value = {"sha256":h.hexdigest(),"bytes":p.stat().st_size}
        if name in bindings and bindings[name] != value: raise ValueError("artifact changed during audit")
        bindings[name] = value; return value["sha256"]
    def read(name):
        expected = hashed(name); raw = safe(name).read_bytes()
        if sha256(raw).hexdigest()!=expected: raise ValueError("artifact changed during read")
        return raw
    def obj(name): return strict_json(read(name))
    fname = "data/frontier-v6j-freeze.json"
    if hashed(fname)!=freeze_sha256: raise ValueError("new execution freeze hash")
    freeze = obj(fname); inventory = {}
    if freeze["schema"]!="retrace.frontier-v6j-freeze.v1": raise ValueError("new freeze schema")
    for row in freeze["files"]:
        name=row["path"]
        if name in inventory or hashed(name)!=row["sha256"]: raise ValueError("changed/duplicate frozen file")
        inventory[name]=row["sha256"]
    auth=obj(freeze["authorization_path"])
    if hashed(freeze["authorization_path"])!=freeze["authorization_sha256"] or len(auth["protected"])!=1035 or auth["protected_v5_file_count"]!=402: raise ValueError("1035-file protected inventory")
    if any(inventory.get(name)!=expected for name,expected in auth["protected"].items()): raise ValueError("historical pin not frozen")
    if not set(aliases)<=set(inventory): raise ValueError("historical alias not frozen")
    receipt=obj(freeze["continuation_path"])
    if freeze["continuation_sha256"]!=RECEIPT_SHA or hashed(freeze["continuation_path"])!=RECEIPT_SHA: raise ValueError("pinned continuation receipt")
    if freeze["baseline_path"]!=receipt["baseline_snapshot_path"] or hashed(freeze["baseline_path"])!=PRIOR_SHA or freeze["baseline_sha256"]!=PRIOR_SHA: raise ValueError("old carry snapshot")
    if freeze["historical_conservative_carry_credits"]!=CARRY or receipt["historical_conservative_carry_credits"]!=CARRY or freeze["observed_response_models"]!=ROUTE: raise ValueError("carry/route policy")
    # Independent complete original audit, not a trusted saved boolean.
    old = original_audit.audit(root, ORIGINAL_FREEZE_SHA, frozen_aliases=aliases, ledger_snapshot=receipt["baseline_snapshot_path"])
    saved_old=obj("results/frontier-v6i/primary/runtime-audit.json")
    if old!=saved_old or old["schedule_status"]!="stopped" or old["cumulative_accounted_credits"]!=CARRY: raise ValueError("original independent replay differs")
    for name,binding in old["input_bindings"].items():
        if hashed(name)!=binding["sha256"]: raise ValueError("original source binding changed")
    slots=obj(freeze["sessions_path"])
    if len(slots)!=1800 or digest(slots)!=freeze["sessions_sha256"] or digest(slots)!=receipt["sessions_sha256"] or hashed(freeze["sessions_path"])!=freeze["sessions_file_sha256"]: raise ValueError("unchanged1800 slots")
    old_paths = {"requests":"results/frontier-v6i/primary/requests.jsonl", "responses":"results/frontier-v6i/primary/responses.jsonl", "outcomes":"results/frontier-v6i/primary/slot-outcomes.jsonl", "summary":"results/frontier-v6i/primary/summary.json", "run":"results/frontier-v6i/primary/run.json"}
    for name,expected in receipt["prior_journal_files"].items():
        if hashed(name)!=expected: raise ValueError("original journal pin")
    oldq=jsonl(read(old_paths["requests"])); oldr=jsonl(read(old_paths["responses"])); oldf=jsonl(read(old_paths["outcomes"])); olds=obj(old_paths["summary"])
    if olds["stop_reasons"]!=["response_model_mismatch"] or olds["issued_attempts"]!=6 or olds["retries"]!=0: raise ValueError("only pinned interruption authorized")
    carry={}
    for ref in receipt["carryover_rows"]:
        if ref["source_path"]!=old_paths["outcomes"]: raise ValueError("carry source path")
        row=oldf[ref["source_line_one_based"]-1]
        if digest(row)!=ref["row_sha256"] or row["slot_id"]!=ref["slot_id"] or row.get("attempt_id")!=ref["attempt_id"] or row["model_outcome"]!=ref["model_outcome"] or not row["issued"]: raise ValueError("exact carryover row")
        if row["slot_id"] in carry: raise ValueError("duplicate carry")
        carry[row["slot_id"]]=row
    ids=receipt["permanently_excluded_issued_slot_ids"]; pending=[s["slot_id"] for s in slots if s["slot_id"] not in carry]
    if list(carry)!=ids or len(carry)!=6 or pending!=receipt["continuation_slot_ids"] or len(pending)!=1794 or {r["slot_id"] for r in oldq}!=set(carry): raise ValueError("six issued plus ordered complement")
    failures=[r for r in oldr if r.get("failure_scope")=="global"]
    if len(failures)!=1 or failures[0]["error"]!="response_model_mismatch" or failures[0]["terminal_valid"] or digest(failures[0])!=receipt["route_evidence"]["original_response_row_sha256"]: raise ValueError("original rejected route preserved")
    run=freeze["output_path"].rstrip("/"); ledgerdir=freeze["ledger_path"].rstrip("/")
    if (root/ledgerdir/"active.lock").exists(): raise ValueError("continuation still active")
    if ledger_snapshot is not None:
        snapshot=Path(ledger_snapshot)
        if snapshot.is_absolute() or not (root/snapshot).resolve().is_relative_to(root): raise ValueError("root-relative snapshot required")
        substitutes[ledgerdir+"/ledger.jsonl"]=snapshot.as_posix()
    manifest=obj(run+"/run.json")
    if manifest["execution_manifest_sha256"]!=freeze_sha256 or stamp(manifest["created_at"])<stamp(freeze["created_at"]): raise ValueError("prospective freeze timing")
    if manifest["continuation_sha256"]!=RECEIPT_SHA or manifest["continuation_path"]!=freeze["continuation_path"] or manifest["original_run_id"]!=receipt["original_run_id"] or manifest["carryover_bindings"]!=receipt["carryover_rows"]: raise ValueError("manifest authenticated carry")
    prior_rows=jsonl(read(receipt["baseline_snapshot_path"]))
    earliest=stamp(prior_rows[-1]["at"])+__import__("datetime").timedelta(seconds=4)
    if stamp(manifest["earliest_next_admission_utc"])!=earliest: raise ValueError("cross-process earliest admission")
    finals=jsonl(read(run+"/slot-outcomes.jsonl")); fidx={r["slot_id"]:r for r in finals}
    summary=obj(run+"/summary.json")
    if summary["status"]=="completed":
        for sid in receipt["failed_producer_descendant_slot_ids"]:
            if fidx[sid]["model_outcome"]!="not_issued_dependency_failed" or fidx[sid]["issued"]: raise ValueError("failed producer cannot be reused")
    result=audit_evidence(slots,manifest,jsonl(read(run+"/requests.jsonl")),jsonl(read(run+"/responses.jsonl")),finals,summary,jsonl(read(ledgerdir+"/ledger.jsonl")),lambda name:read(run+"/streams/"+name),carryover=carry,original_requests=oldq,original_responses=oldr)
    for name in list(bindings): hashed(name)
    result.update(schema="retrace.frontier-v6j-runtime-independent-audit.v1",audit_scope="Independent continuation infrastructure replay. Original six outcomes remain in their interrupted run; observed diagnostic route is not verified weight/precision equivalence.",frozen_files=len(inventory),protected_historical_files=1035,protected_v5_files=402,input_bindings=bindings,original_audit=old,auditor_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),limits=["Local timestamps/hashes are not provider signatures or quota proof.","A closed continuation does not mean every endpoint succeeded.","Original global route failure remains failed and retains its full reserved bound.","Unknown costs are conservatively retained; actual billing is unavailable."])
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=ROOT);p.add_argument("--freeze-sha256",required=True)
    p.add_argument("--aliases",type=Path);p.add_argument("--ledger-snapshot")
    p.add_argument("--output",type=Path,required=True);p.add_argument("--markdown",type=Path,required=True)
    a=p.parse_args()
    if a.output.resolve()==a.markdown.resolve() or a.output.exists() or a.markdown.exists():raise ValueError("exclusive new outputs required")
    aliases=strict_json(a.aliases.read_bytes()) if a.aliases else None
    result=audit(a.root,a.freeze_sha256,frozen_aliases=aliases,ledger_snapshot=a.ledger_snapshot)
    with a.output.open("x",encoding="utf-8",newline="\n") as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write("\n")
    with a.markdown.open("x",encoding="utf-8",newline="\n") as f:f.write("# Independent v6j continuation audit\n\n"+result["audit_scope"]+"\n\nStatus: "+result["schedule_status"]+"; scheduled continuation slots: "+str(result["counts"]["planned"])+". Cumulative conservative credits: "+result["cumulative_accounted_credits"]+".\n")
    print(json.dumps({k:result[k] for k in ("passed","checks","schedule_status","counts","cumulative_accounted_credits")}))

if __name__=="__main__":main()
