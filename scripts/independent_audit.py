"""Offline audit using a separate fixed-point evaluator; no RETRACE imports/API.

Run: python scripts/independent_audit.py
This was authored by a second AI agent, not a human annotator. It checks the
saved formal cases and journals; it does not establish real-world validity.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode(text):
    return json.loads(text, object_pairs_hook=unique_pairs)


def read(path):
    return decode(path.read_text(encoding="utf-8"))


def rows(path):
    return [decode(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def derive(case, withdrawn):
    """Least fixed-point Boolean evaluation on the supplied acyclic fixtures."""
    revoked = set(withdrawn)
    nodes = [node for group in ("evidence", "claims", "decisions") for node in case[group]]
    state = {node["id"]: False for node in nodes}
    require(len(state) == len(nodes), "duplicate fixture node")
    for _ in range(len(state) + 1):
        before = state.copy()
        for node in case["evidence"]:
            usable = node.get("active", True) and node["id"] not in revoked
            if node.get("kind", "root") == "copy":
                usable = usable and all(state[parent] for parent in node["parents"])
            state[node["id"]] = bool(usable)
        for node in case["claims"]:
            state[node["id"]] = any(all(state[parent] for parent in clause) for clause in node["supports"])
        for node in case["decisions"]:
            state[node["id"]] = all(state[parent] for parent in node["requires"])
        if state == before:
            return {node["id"]: state[node["id"]] for node in case["decisions"]}
    raise ValueError("fixture did not converge")


def prediction(text, expected):
    value = decode(text)
    require(isinstance(value, dict) and set(value) == {"decisions"}, "invalid prediction top level")
    result = value["decisions"]
    require(isinstance(result, dict) and set(result) == set(expected), "invalid decision IDs")
    require(all(type(value) is bool for value in result.values()), "non-boolean prediction")
    return result


def audit():
    cases = read(ROOT / "data/pilot-cases.json")
    index = {case["id"]: case for case in cases}
    require(len(index) == len(cases), "duplicate case IDs")
    models = {}
    for model in ("gemma-4-31b-it", "glm-53-flash"):
        records = rows(ROOT / "results/pilot-paced" / model / "responses.jsonl")
        stats = Counter()
        groups = defaultdict(Counter)
        identities = set()
        for record in records:
            identity = (record["case_id"], record["condition"], record["phase"])
            require(identity not in identities, "duplicate model response")
            identities.add(identity)
            require(record["response_status"] == "completed" and record["http_status"] == 200,
                    "incomplete response in completed model run")
            stats["completed"] += 1
            case = index[record["case_id"]]
            expected = derive(case, case["revoke"] if record["phase"] == "withdrawn" else [])
            raw = record["output_text"]
            try:
                strict = prediction(raw, expected)
            except (ValueError, TypeError):
                strict = None
            stats["strict_valid"] += strict is not None
            stats["strict_exact"] += strict == expected
            match = re.fullmatch(r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", raw, re.DOTALL)
            fenced = match is not None and "```" not in match.group(1)
            normalized = match.group(1) if fenced else raw
            stats["outer_fences_removed"] += fenced
            parsed = prediction(normalized, expected)
            exact = parsed == expected
            stats["normalized_exact"] += exact
            group = groups[record["condition"] + "/" + record["phase"]]
            group["outputs"] += 1
            group["normalized_exact"] += exact
        expected_identities = {(case["id"], condition, phase) for case in cases
                               for condition, phase in (("history", "initial"), ("history", "withdrawn"),
                                                        ("history", "restored"), ("fresh", "withdrawn"))}
        require(identities == expected_identities, "missing or unexpected completed model output")
        models[model] = {"counts": dict(stats), "groups": dict(groups)}

    reserve = Decimal(0)
    known = Decimal(0)
    issued = 0
    unknown = []
    runs = []
    for path in sorted((ROOT / "results").rglob("run.json")):
        directory = path.parent
        run, summary = read(path), read(directory / "summary.json")
        requests, responses = rows(directory / "requests.jsonl"), rows(directory / "responses.jsonl")
        require(len(requests) == summary["issued_requests"], "issued count mismatch")
        require(len(responses) == summary["recorded_responses"], "response count mismatch")
        issued += len(requests)
        reserve += Decimal(str(run["max_reserved_credits"]))
        request_index = {record["request_number"]: record for record in requests}
        response_index = {(r["case_id"], r["condition"], r["step_index"]): r for r in responses}
        require(len(request_index) == len(requests), "duplicate journal request number")
        require(len(response_index) == len(responses), "duplicate journal session step")
        for record in responses:
            request = request_index[record["request_number"]]
            require(request["request"] == record["request"], "journal body mismatch")
            require(request["request_sha256"] == record["request_sha256"], "journal hash mismatch")
            canonical = json.dumps(record["request"], ensure_ascii=False, separators=(",", ":"))
            require(hashlib.sha256(canonical.encode()).hexdigest() == record["request_sha256"],
                    "request digest does not match body")
            previous = [response_index[(record["case_id"], record["condition"], step)]["output_text"]
                        for step in range(record["step_index"])]
            replay = [message["content"] for message in record["request"]["input"]
                      if message["role"] == "assistant"]
            require(replay == previous, "actual assistant replay mismatch")
            usage = record.get("usage")
            if usage is None:
                unknown.append({"run": str(directory.relative_to(ROOT)), "request": record["request_number"],
                                "error": record["error"], "http_status": record["http_status"]})
            else:
                known += (Decimal(usage["input_tokens"]) * Decimal(str(run["pricing"]["input"]))
                          + Decimal(usage["output_tokens"]) * Decimal(str(run["pricing"]["output"]))) / Decimal(1000000)
        runs.append({"path": str(directory.relative_to(ROOT)), "issued": len(requests),
                     "recorded": len(responses), "sessions_sha256": run["sessions_sha256"],
                     "reserved_credits": run["max_reserved_credits"]})

    budget = read(ROOT / "results/budget-audit.json")
    require(issued == budget["issued_requests"], "aggregate request count mismatch")
    require(reserve == Decimal(str(budget["conservative_reserved_credits"])), "aggregate reserve mismatch")
    require(abs(known - Decimal(str(budget["observed_token_cost_credits_uncached"]))) < Decimal("1e-12"),
            "aggregate token estimate mismatch")
    require(len(unknown) == budget["responses_missing_usage"], "missing usage count mismatch")
    require(reserve <= Decimal(str(budget["approved_credit_cap"])), "reservation exceeds cap")
    return {
        "schema": "retrace.independent-audit.v1", "status": "passed",
        "reviewer": "Second AI agent; no human annotation or independent human validation",
        "method": "Offline fixed-point evaluator; no imports from retrace.core or retrace.experiment; no API calls",
        "limitations": "Given acyclic formal fixtures only. Shared declared semantics; not evidence of real-world validity or verified billing.",
        "case_count": len(cases), "families": dict(Counter(case["family"] for case in cases)),
        "models": models, "journal_alignment": "All request bodies, digests and prior assistant replays matched",
        "issued_requests": issued, "known_usage_token_estimate_credits": str(known),
        "conservative_reserved_credits": str(reserve), "actual_billed_credits": None,
        "unknown_usage_attempts": unknown, "runs": runs,
        "traced_examples": [{"case_id": case["id"], "family": case["family"], "revoked": case["revoke"],
                             "before": derive(case, []), "after": derive(case, case["revoke"])}
                            for case in cases if case["family"] in ("redundant", "partial_retraction")],
        "input_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (ROOT / "data/pilot-cases.json", ROOT / "results/pilot-summary.json",
                                      ROOT / "results/budget-audit.json")},
    }


if __name__ == "__main__":
    result = audit()
    output = ROOT / "results/independent-audit.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "case_count": result["case_count"],
                      "issued_requests": result["issued_requests"], "output": str(output)}))
