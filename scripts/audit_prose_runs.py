"""Offline journal and fixed-point audit, independent of the frozen scorer/engine.

Reads append-only logs and never dispatches model requests. Run after
summarize_prose.py for a final comparison; a live snapshot stays incomplete.
Author/reviewer: a separate AI agent, not independent human validation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("evidence", "claims", "decisions")
PHASES = {"formal_fresh": ("final",), "prose_fresh": ("final",),
          "prose_history": ("initial", "withdrawn"),
          "prose_no_commitment": ("final",), "prose_extract": ("final",)}


def require(value, explanation):
    if not value:
        raise ValueError(explanation)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def decode(text):
    return json.loads(text, object_pairs_hook=unique_object)


def read(path):
    return decode(path.read_text(encoding="utf-8"))


def digest(value, *, sorted_keys=False):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=sorted_keys,
                                    separators=(",", ":")).encode()).hexdigest()


def journal(path):
    """Ignore only a physically incomplete last append, and disclose it."""
    if not path.exists():
        return [], False, None
    saved = path.read_bytes()
    text = saved.decode("utf-8")
    partial = bool(text) and not text.endswith("\n")
    lines = text.splitlines()
    if partial:
        lines = lines[:-1]
    return [decode(line) for line in lines if line], partial, {"sha256": hashlib.sha256(saved).hexdigest(), "bytes": len(saved)}


def graph_index(graph, reference=None):
    require(isinstance(graph, dict), "Graph must be an object")
    if reference is not None:
        require(set(graph) == set(CATEGORIES), "Unexpected top-level graph fields")
    permitted = {"evidence": {"id", "label", "kind", "active", "parents"},
                 "claims": {"id", "label", "supports"},
                 "decisions": {"id", "label", "requires"}}
    nodes, kinds, dependencies = {}, {}, {}
    for category in CATEGORIES:
        require(isinstance(graph.get(category), list), "Graph category must be an array")
        for row in graph[category]:
            require(isinstance(row, dict), "Graph row must be an object")
            if reference is not None:
                require(set(row) <= permitted[category], "Unexpected graph node field")
            identifier = row.get("id")
            require(isinstance(identifier, str) and identifier and identifier not in nodes,
                    "Node IDs must be unique nonempty strings")
            require(isinstance(row.get("label", identifier), str), "Node label must be text")
            nodes[identifier], kinds[identifier] = row, category
        if reference is not None:
            require({r["id"] for r in graph[category]} == {r["id"] for r in reference[category]},
                    "Graph category IDs differ from task")

    def refs(values, nonempty=False):
        require(isinstance(values, list), "References must be arrays")
        require(not nonempty or bool(values), "Reference array cannot be empty")
        require(all(isinstance(v, str) and v for v in values), "References must be nonempty strings")
        require(len(values) == len(set(values)), "Duplicate reference")
        return set(values)

    for identifier, row in nodes.items():
        category = kinds[identifier]
        if category == "evidence":
            kind = row.get("kind", "root")
            require(kind in ("root", "copy"), "Unknown evidence kind")
            require(type(row.get("active", True)) is bool, "Activity must be boolean")
            parents = refs(row.get("parents", []), kind == "copy")
            require(kind != "root" or not parents, "Root has parents")
            allowed = {"evidence"}
        elif category == "claims":
            clauses = row.get("supports")
            require(isinstance(clauses, list), "Supports must be an array")
            parents = set()
            for clause in clauses:
                parents |= refs(clause, True)
            allowed = {"evidence", "claims"}
        else:
            parents = refs(row.get("requires"), True)
            allowed = {"claims"}
        require(all(parent in nodes and kinds[parent] in allowed for parent in parents),
                "Missing or wrong-category dependency")
        dependencies[identifier] = parents
    # Independent topological elimination, rather than the engine's recursive DFS.
    remaining, removed = set(nodes), set()
    while remaining:
        ready = {identifier for identifier in remaining if dependencies[identifier] <= removed}
        require(bool(ready), "Cyclic graph")
        removed |= ready
        remaining -= ready
    return nodes, dependencies


def fixed_point(graph, withdrawn=()):
    """Synchronous least fixed point; no RETRACE evaluator is imported."""
    nodes, _ = graph_index(graph)
    withdrawn = set(withdrawn)
    require(withdrawn <= {row["id"] for row in graph["evidence"]}, "Withdrawal is not evidence")
    state = {identifier: False for identifier in nodes}
    for _ in range(len(nodes) + 1):
        updated = {}
        for row in graph["evidence"]:
            active = row.get("active", True) and row["id"] not in withdrawn
            dependencies_ok = row.get("kind", "root") == "root" or all(state[p] for p in row["parents"])
            updated[row["id"]] = bool(active and dependencies_ok)
        for row in graph["claims"]:
            updated[row["id"]] = any(all(state[p] for p in clause) for clause in row["supports"])
        for row in graph["decisions"]:
            updated[row["id"]] = all(state[p] for p in row["requires"])
        if updated == state:
            return {row["id"]: state[row["id"]] for row in graph["decisions"]}
        state = updated
    raise ValueError("Fixed point did not converge")


def final_graph(entry):
    graph = {category: copy.deepcopy(entry["case"][category]) for category in CATEGORIES}
    for row in graph["evidence"]:
        if row["id"] in entry["case"]["revoke"]:
            row["active"] = False
    return graph


def canonical(graph):
    result = {}
    for row in graph["evidence"]:
        result[row["id"]] = ("evidence", row.get("kind", "root"), row.get("active", True),
                              frozenset(row.get("parents", [])))
    for row in graph["claims"]:
        result[row["id"]] = ("claims", frozenset(frozenset(c) for c in row["supports"]))
    for row in graph["decisions"]:
        result[row["id"]] = ("decisions", frozenset(row["requires"]))
    return result


def edges(graph):
    found = set()
    for category, relation, field in (("evidence", "parent", "parents"),
                                      ("decisions", "requires", "requires")):
        found |= {(row["id"], relation, parent) for row in graph[category] for parent in row.get(field, [])}
    found |= {(row["id"], "support", parent) for row in graph["claims"]
              for clause in row["supports"] for parent in clause}
    return found


def content(text, condition, reference, *, normalize):
    require(isinstance(text, str), "Missing output text")
    match = re.fullmatch(r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", text, re.DOTALL)
    stripped = bool(normalize and match is not None and "```" not in match.group(1))
    value = decode(match.group(1) if stripped else text)
    if condition != "prose_extract":
        require(isinstance(value, dict) and set(value) == {"decisions"}, "Wrong decision object")
        prediction = value["decisions"]
        require(isinstance(prediction, dict) and set(prediction) == {r["id"] for r in reference["decisions"]},
                "Decision IDs differ from task")
        require(all(type(v) is bool for v in prediction.values()), "Decision value is not boolean")
        return {"predictions": prediction, "outer_fence_removed": stripped}
    graph_index(value, reference)
    actual, gold = canonical(value), canonical(reference)
    predicted_edges, gold_edges = edges(value), edges(reference)
    return {"predictions": fixed_point(value), "outer_fence_removed": stripped,
            "extraction": {"graph_exact": actual == gold,
                           "correct_nodes": sum(actual[k] == v for k, v in gold.items()),
                           "total_nodes": len(gold),
                           "edge_true_positive": len(predicted_edges & gold_edges),
                           "edge_false_positive": len(predicted_edges - gold_edges),
                           "edge_false_negative": len(gold_edges - predicted_edges)}}


def explicit_field_gaps(text):
    """Diagnostic only: optional semantic defaults are not a strict field contract."""
    match = re.fullmatch(r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", text, re.DOTALL)
    value = decode(match.group(1) if match is not None and "```" not in match.group(1) else text)
    gaps = []
    for category, required in {"evidence": {"id", "kind", "active", "parents"},
                               "claims": {"id", "supports"}, "decisions": {"id", "requires"}}.items():
        for row in value[category]:
            missing = required - set(row)
            if missing:
                gaps.append({"category": category, "id": row["id"], "missing_fields": sorted(missing)})
    return gaps


def eligibility(entry):
    case = entry["case"]
    initial, final = fixed_point(case), fixed_point(case, case["revoke"])
    require(final == fixed_point(final_graph(entry)), "Event/snapshot reference mismatch")
    _, dependencies = graph_index(case)
    affected = set(case["revoke"])
    while True:
        expanded = affected | {identifier for identifier, parents in dependencies.items() if parents & affected}
        if expanded == affected:
            break
        affected = expanded
    preserved = {k for k in initial if initial[k] and final[k]}
    return {"initial": initial, "final": final, "lost": {k for k in initial if initial[k] and not final[k]},
            "preserved": preserved, "protected": preserved & affected,
            "unaffected": preserved - affected, "initially_unsupported": {k for k in initial if not initial[k]}}


def independent_scores(corpus, records):
    by_key = {(r["case_id"], r["condition"], r["phase"]): r for r in records}
    require(len(by_key) == len(records), "Duplicate response condition/phase")
    groups, outcomes = defaultdict(Counter), {}
    for entry in corpus:
        truth = eligibility(entry)
        reference = final_graph(entry)
        for condition, phases in PHASES.items():
            for phase in phases:
                key = (entry["id"], condition, phase)
                row = by_key.get(key)
                group = groups[condition + "/" + phase]
                expected = truth["initial" if phase == "initial" else "final"]
                group["expected"] += 1
                group["decision_targets_all"] += len(expected)
                result = {"strict_valid": False, "semantic_valid": False, "exact": False,
                          "predictions": None, "decision_error_fraction_all_scheduled": 1.0}
                parsed = None
                if row is not None:
                    group["received"] += 1
                    operational = bool(row.get("error") or row.get("response_status", "completed") not in (None, "completed"))
                    group["operational_failures"] += operational
                    if not operational:
                        for normalize in (False, True):
                            try:
                                candidate = content(row.get("output_text"), condition, reference, normalize=normalize)
                                if normalize:
                                    parsed = candidate
                                else:
                                    result["strict_valid"] = True
                                    group["strict_valid"] += 1
                            except (ValueError, KeyError, TypeError, RecursionError):
                                pass
                if parsed is None:
                    group["decision_errors_all_scheduled"] += len(expected)
                else:
                    errors = sum(parsed["predictions"][k] != v for k, v in expected.items())
                    result.update(parsed, semantic_valid=True, exact=not errors,
                                  decision_error_fraction_all_scheduled=errors / len(expected))
                    group.update({"semantic_valid": 1, "exact": int(not errors),
                                  "outer_fences_removed": int(parsed["outer_fence_removed"]),
                                  "decision_targets_valid": len(expected), "decision_errors_valid": errors,
                                  "decision_errors_all_scheduled": errors})
                    if phase != "initial":
                        for denominator, numerator, target, wrong in (
                            ("required_retractions", "missed_retractions", "lost", True),
                            ("preserved_targets", "collateral_errors", "preserved", False),
                            ("protected_targets", "protected_collateral_errors", "protected", False),
                            ("unaffected_targets", "unaffected_errors", "unaffected", False),
                            ("initially_unsupported_targets", "initially_unsupported_accepted", "initially_unsupported", True),
                        ):
                            group[denominator] += len(truth[target])
                            group[numerator] += sum(parsed["predictions"][k] == wrong for k in truth[target])
                    if "extraction" in parsed:
                        detail = parsed["extraction"]
                        group.update({"graph_exact": int(detail["graph_exact"]),
                                      "graph_nodes_correct": detail["correct_nodes"], "graph_nodes_total": detail["total_nodes"]})
                        for field in ("edge_true_positive", "edge_false_positive", "edge_false_negative"):
                            group[field] += detail[field]
                outcomes[key] = result
    return groups, outcomes


def reconstruct_packet(entry):
    parts = ["Fictional packet: " + entry["title"]]
    parts += ["DOCUMENT " + d["id"] + " — " + d["title"] + "\n" + d["text"] for d in entry["documents"]]
    parts += ["DECISIONS TO EVALUATE\n" + "\n".join(d["id"] + ": " + d["text"] for d in entry["decision_questions"])]
    return "\n\n".join(parts)


def verify_manifest(corpus, manifest):
    sessions = manifest["sessions"]
    require(digest({"instructions": manifest["instructions"], "sessions": sessions}, sorted_keys=True) == manifest["sha256"],
            "Canonical session manifest hash mismatch")
    expected = {(e["id"], c) for e in corpus for c in PHASES}
    require({(s["case_id"], s["condition"]) for s in sessions} == expected and len(sessions) == len(expected),
            "Manifest does not contain exactly the planned sessions")
    by_id = {e["id"]: e for e in corpus}
    extraction_instructions = {s["instructions"] for s in sessions if s["condition"] == "prose_extract"}
    require(len(extraction_instructions) == 1, "Extraction instructions vary by case")
    extraction_instruction = next(iter(extraction_instructions))
    for session in sessions:
        entry = by_id[session["case_id"]]
        condition = session["condition"]
        if condition.startswith("prose_"):
            if condition != "prose_extract":
                require(session["instructions"] == manifest["instructions"], "Direct prose instructions vary by case")
            require(entry["id"] not in session["instructions"] and entry["family"] not in session["instructions"],
                    "Hidden case identity/family appears in prose instructions")
            require(not any(row["id"] in session["instructions"] for group in CATEGORIES for row in entry["case"][group]),
                    "Case-specific reference ID appears in prose instructions")
        require(tuple(s["phase"] for s in session["steps"]) == PHASES[condition], "Session phase mismatch")
        packet = reconstruct_packet(entry)
        snapshot = ("AUTHORITATIVE CURRENT-ELIGIBILITY SNAPSHOT\nThe following records are locally ineligible: "
                    + ", ".join(entry["case"]["revoke"])
                    + ". This overrides earlier local-eligibility statements for these exact IDs only. "
                    + "All other local eligibility and all support rules remain as in the packet. "
                    + "Copies still depend on their parents. This removes warrants, not the truth of propositions.")
        allowed = {
            "prose_fresh": [packet + "\n\n" + snapshot + "\n\nReturn the current decision-support map."],
            "prose_extract": [packet + "\n\n" + snapshot + "\n\nExtract the full direct support graph at the current snapshot."],
            "prose_history": [packet + "\n\nReturn the decision-support map before any later update.",
                              "AUTHORITATIVE UPDATE\n" + entry["event_text"] + "\nRe-evaluate every decision using the current eligible support."],
            "prose_no_commitment": [packet + "\n\nAUTHORITATIVE UPDATE\n" + entry["event_text"]
                                    + "\n\nApply the update and return the current decision-support map. No earlier answer has been made."],
        }
        if condition == "formal_fresh":
            require(decode(session["steps"][0]["input"].split("\n", 1)[1]) == final_graph(entry), "Formal snapshot mismatch")
        else:
            require([s["input"] for s in session["steps"]] == allowed[condition], "Prose payload contains unexpected material")
            for step in session["steps"]:
                require(not any(token in step["input"] for token in ('"review_notes"', '"supports":', '"family":')),
                        "Private structured metadata in prose payload")
    require('"supports"' in extraction_instruction and '"requires"' in extraction_instruction,
            "Extraction schema instruction absent")
    return sessions


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def provider_text(raw):
    if isinstance(raw.get("output_text"), str):
        return raw["output_text"]
    return "".join(part["text"] for message in raw.get("output", [])
                   if message.get("type") == "message" and message.get("role") == "assistant"
                   for part in message.get("content", [])
                   if part.get("type") == "output_text" and isinstance(part.get("text"), str))


def self_check():
    """Known-answer checks for the separate audit implementation, no model output."""
    graph = {"evidence": [{"id": "A", "active": False}, {"id": "B", "active": True},
                          {"id": "P", "kind": "copy", "parents": ["A"], "active": True}],
             "claims": [{"id": "C", "supports": [["P"], ["B"]]}, {"id": "L", "supports": [["P"]]}],
             "decisions": [{"id": "D", "requires": ["C"]}, {"id": "E", "requires": ["L"]}]}
    require(fixed_point(graph) == {"D": True, "E": False}, "Audit self-check: alternative/copy semantics")
    parsed = content(json.dumps(graph), "prose_extract", graph, normalize=True)
    require(parsed["extraction"]["graph_exact"] and parsed["predictions"] == {"D": True, "E": False},
            "Audit self-check: graph parsing/evaluation")
    wrong = copy.deepcopy(graph)
    wrong["claims"][0]["supports"] = [["P", "B"]]
    require(edges(wrong) == edges(graph) and canonical(wrong) != canonical(graph)
            and fixed_point(wrong) == {"D": False, "E": False}, "Audit self-check: AND/OR grouping")
    cycle = copy.deepcopy(graph)
    cycle["claims"][0]["supports"] = [["C"]]
    try:
        graph_index(cycle, graph)
    except ValueError:
        pass
    else:
        raise ValueError("Audit self-check: cycle was accepted")
    bare = '{"decisions":{"D":true,"E":false}}'
    fenced = "```json\n" + bare + "\n```"
    require(content(fenced, "prose_fresh", graph, normalize=True)["outer_fence_removed"],
            "Audit self-check: fence normalization")
    for bad in ("Answer: " + bare, bare.replace('"D":true', '"D":true,"D":false'), fenced):
        try:
            content(bad, "prose_fresh", graph, normalize=False)
        except ValueError:
            pass
        else:
            raise ValueError("Audit self-check: malformed strict decision was accepted")
    return ["surviving alternative", "copy local activity versus usability", "AND/OR grouping despite identical edges",
            "cycle rejection", "prospective fence handling", "surrounding prose and duplicate-key rejection"]


def audit_segment(directory, model, sessions, instructions, freeze, earliest):
    flat = [(i, j, session, step) for i, session in enumerate(sessions) for j, step in enumerate(session["steps"])]
    issues = []
    run = read(directory / "run.json")
    completion = read(directory / "summary.json") if (directory / "summary.json").exists() else None
    # Read responses first: later request snapshot necessarily contains their requests.
    responses, partial_response, response_snapshot = journal(directory / "responses.jsonl")
    requests, partial_request, request_snapshot = journal(directory / "requests.jsonl")
    require(run["model"] == model and run["sessions_sha256"] == digest(sessions), "Run model/session hash mismatch")
    require(run["sessions"] == [{"case_id": s["case_id"], "family": s["family"], "condition": s["condition"],
                                  "phases": [step["phase"] for step in s["steps"]]} for s in sessions],
            "Run session identity inventory mismatch")
    require(timestamp(run["started_at"]) >= timestamp(earliest), "Run predates freeze")
    for field in ("max_output_tokens", "timeout_ms", "min_interval_ms"):
        require(run[field] == freeze[field], "Run setting mismatch: " + field)
    require(run["concurrency"] == 1 and run["retries"] == 0 and run["planned_requests"] == len(flat), "Run plan mismatch")
    require(run["instructions"] == instructions, "Run default instructions mismatch")
    require(run["actual_prior_assistant_text_replayed"] and not any(run[k] for k in ("tools", "store", "agentic_memory")),
            "Run memory/tool/history settings mismatch")
    price = run["pricing"]
    reserve_per_call = (Decimal(price["context"]) * Decimal(str(price["input"])) * 1000
                        + Decimal(freeze["max_output_tokens"]) * Decimal(str(price["output"])) * 1000).to_integral_value(rounding=ROUND_CEILING)
    reserve = reserve_per_call * len(flat) / Decimal(10**9)
    require(reserve == Decimal(str(run["max_reserved_credits"])), "Reservation arithmetic mismatch")
    request_index = {r["request_number"]: r for r in requests}
    response_index = {r["request_number"]: r for r in responses}
    require(list(request_index) == list(range(1, len(requests) + 1)), "Missing/duplicate/request-order numbers")
    require(len(request_index) == len(requests) and len(response_index) == len(responses), "Duplicate journal number")
    require(set(response_index) <= set(request_index), "Response without a journaled request")
    require(len(requests) <= len(flat), "Unplanned extra call")
    previous_outputs = {(r["session_index"], r["step_index"]): r["output_text"] for r in responses}
    min_interval = None
    for number, request_row in request_index.items():
        session_i, step_i, session, step = flat[number - 1]
        for field, value in {"session_index": session_i, "step_index": step_i, "model": model,
                             "run_id": run["run_id"], "case_id": session["case_id"], "family": session["family"],
                             "condition": session["condition"], "phase": step["phase"],
                             "response_kind": session.get("response_kind", "decisions")}.items():
            require(request_row[field] == value, "Journal request identity mismatch: " + field)
        inputs = []
        for previous in range(step_i + 1):
            inputs.append({"role": "user", "content": session["steps"][previous]["input"]})
            if previous < step_i:
                require((session_i, previous) in previous_outputs, "History dispatched without earlier response")
                inputs.append({"role": "assistant", "content": previous_outputs[(session_i, previous)]})
        expected_request = {"model": model, "instructions": session.get("instructions", instructions),
                            "input": inputs, "max_output_tokens": freeze["max_output_tokens"], "temperature": 0,
                            "store": False, "agentic_memory": False, "tools": [], "tool_choice": "none"}
        require(request_row["request"] == expected_request, "Request differs from frozen payload or actual assistant replay")
        require(digest(request_row["request"]) == request_row["request_sha256"], "Request digest mismatch")
        require(timestamp(request_row["started_at"]) >= timestamp(run["started_at"]), "Request predates run")
        if number > 1:
            interval = (timestamp(request_row["started_at"]) - timestamp(request_index[number - 1]["started_at"])).total_seconds() * 1000
            min_interval = interval if min_interval is None else min(min_interval, interval)
            require(interval >= freeze["min_interval_ms"] - 5, "Request start pacing violated")
    unknown_usage, operational, provider_flags = [], [], []
    model_cost = Decimal(0)
    for number, row in response_index.items():
        request = request_index[number]
        for field in ("request", "request_sha256", "run_id", "model", "session_index", "step_index", "phase", "case_id", "condition", "response_kind"):
            require(row[field] == request[field], "Response/request mismatch: " + field)
        require(timestamp(row["finished_at"]) >= timestamp(request["started_at"]), "Response predates request")
        if row.get("error"):
            require(row.get("output_text") == "", "Operational failure exposed a completed prediction")
            raw_failure = None
            try:
                raw_failure = decode(row.get("raw_response"))
            except (ValueError, TypeError):
                pass
            if isinstance(raw_failure, dict):
                require(raw_failure.get("status") == row.get("response_status") and raw_failure.get("model") == row.get("response_model"),
                        "Failed raw provider envelope differs from journal")
                require(raw_failure.get("usage") == row.get("usage"), "Failed raw usage differs from journal")
                require(raw_failure.get("model") in (None, model), "Failed response returned a different model")
                if row["error"] == "response_not_completed":
                    require(raw_failure.get("status") != "completed", "Wrong incomplete-response error flag")
            operational.append({"request": number, "case_id": row["case_id"], "condition": row["condition"],
                                "phase": row["phase"], "error": row["error"], "http_status": row.get("http_status"),
                                "response_status": row.get("response_status"),
                                "incomplete_details": raw_failure.get("incomplete_details") if isinstance(raw_failure, dict) else None})
        else:
            require(type(row.get("http_status")) is int and 200 <= row["http_status"] < 300,
                    "Non-success HTTP response not marked operational failure")
            require(row.get("response_status") == "completed", "Incomplete response unmarked by runner")
            require(row.get("response_model") == model, "Provider-returned model differs from requested endpoint")
            raw = decode(row["raw_response"])
            require(isinstance(raw, dict), "Provider response envelope is not an object")
            require(raw.get("status") == row["response_status"] and raw.get("model") == row["response_model"],
                    "Raw provider status/model differs from journal")
            require(raw.get("usage") == row.get("usage"), "Raw provider usage differs from journal")
            require(provider_text(raw) == row["output_text"], "Output text differs from raw provider response")
            flags = []
            if raw.get("error") is not None:
                flags.append("non-null error in completed raw envelope")
            if raw.get("incomplete_details") is not None:
                flags.append("non-null incomplete_details in completed raw envelope")
            for message in raw.get("output", []):
                if message.get("type") == "message" and message.get("status") not in (None, "completed"):
                    flags.append("non-completed output message status")
            if flags:
                provider_flags.append({"request": number, "flags": flags})
                issues.append(model + ": unhandled provider flags at request " + str(number))
        usage = row.get("usage")
        usable_usage = isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens"))
        if usable_usage:
            cost = (Decimal(usage["input_tokens"]) * Decimal(str(price["input"]))
                    + Decimal(usage["output_tokens"]) * Decimal(str(price["output"]))) / Decimal(10**6)
            require(row.get("observed_token_cost_credits_uncached") is not None and
                    abs(cost - Decimal(str(row["observed_token_cost_credits_uncached"]))) < Decimal("1e-12"), "Token estimate differs from usage")
            require(usage["input_tokens"] <= price["context"] and usage["output_tokens"] <= freeze["max_output_tokens"],
                    "Token usage exceeds reserved bound")
            model_cost += cost
        else:
            unknown_usage.append(number)
            require(row.get("observed_token_cost_credits_uncached") is None, "Invalid usage treated as known cost")
    complete = bool(completion and completion["status"] == "completed" and len(requests) == len(responses) == len(flat)
                    and not partial_request and not partial_response)
    if completion:
        require(completion["issued_requests"] == len(requests) and completion["recorded_responses"] == len(responses), "Final run counts differ from journals")
        require(completion["responses_missing_usage"] == len(unknown_usage), "Unknown-usage total mismatch")
        require(abs(model_cost - Decimal(str(completion["observed_token_cost_credits_uncached"]))) < Decimal("1e-12"), "Run token total mismatch")
    detail = {"path": str(directory.relative_to(ROOT)), "status": completion["status"] if completion else "running",
              "settled": completion is not None and not partial_request and not partial_response,
              "segment_completed": complete, "planned": len(flat), "issued": len(requests), "responses": len(responses),
              "run_id": run["run_id"], "sessions_sha256": run["sessions_sha256"],
              "run_manifest_sha256": hashlib.sha256((directory / "run.json").read_bytes()).hexdigest(),
              "request_journal_snapshot": request_snapshot, "response_journal_snapshot": response_snapshot,
              "journal_payload_hashes_and_history_replay": "passed", "minimum_start_interval_ms": min_interval,
              "partial_last_append": partial_request or partial_response,
              "operational_failures": operational, "provider_flags": provider_flags,
              "unknown_usage_requests": unknown_usage, "known_token_estimate_credits": str(model_cost),
              "reserved_credits": str(reserve)}
    return detail, responses, requests, reserve, model_cost, issues


def audit():
    started = datetime.now(timezone.utc).isoformat()
    self_checks = self_check()
    freeze = read(ROOT / "data/prose-freeze.json")
    files = []
    for item in freeze["files"]:
        actual = hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
        require(actual == item["sha256"], "Frozen file changed: " + item["path"])
        files.append({**item, "verified": True})
    helper_path = ROOT / "retrace/experiment.py"
    helper_hash = hashlib.sha256(helper_path.read_bytes()).hexdigest()
    archive_path = ROOT / "results/archive/formal-pilot-artifact-manifest.json"
    archived_inventory = read(archive_path)
    prior_helper_hash = next(row["sha256"] for row in archived_inventory["files"] if row["path"] == "retrace/experiment.py")
    require(helper_hash == prior_helper_hash, "Imported parser helper differs from previously inventoried build")
    helper_dependency = {"path": "retrace/experiment.py", "sha256": helper_hash,
                         "matches_prior_artifact_inventory": True, "included_in_primary_freeze": False,
                         "prior_inventory_path": str(archive_path.relative_to(ROOT)),
                         "prior_inventory_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                         "recorded_here_after_model_outputs_started": True}
    corpus = read(ROOT / "data/prose-holdout.json")
    manifest = read(ROOT / "data/prose-sessions.json")
    sessions = verify_manifest(corpus, manifest)
    flat = [(i, j, session, step) for i, session in enumerate(sessions) for j, step in enumerate(session["steps"])]
    require(len(flat) == freeze["requests_per_model"] == manifest["request_count"], "Planned count mismatch")
    summary_path = ROOT / "results/prose-summary.json"
    score_snapshot = summary_path.read_bytes() if summary_path.exists() else None
    scored = decode(score_snapshot.decode("utf-8")) if score_snapshot is not None else None
    scored_by_model = {m["model"]: m for m in scored["models"]} if scored else {}
    models, issues, pending = {}, [], []
    reservation = Decimal(str(freeze["previous_conservative_reservations"]))
    known_cost = Decimal(0)
    amendments = []
    for model in freeze["models"]:
        segments = [(ROOT / "results/prose-heldout" / model, sessions, freeze["created_at"])]
        continuation_path = ROOT / "data/prose-continuation-gemma.json"
        continuation = read(continuation_path) if model == "gemma-4-31b-it" and continuation_path.exists() else None
        if continuation is not None:
            require(continuation.get("model", "gemma-4-31b-it") == model, "Continuation model mismatch")
            require(continuation.get("instructions", manifest["instructions"]) == manifest["instructions"], "Continuation instructions changed")
            subset = continuation["sessions"]
            require(sum(len(s["steps"]) for s in subset) == continuation["request_count"], "Continuation count mismatch")
            require(continuation["parent_manifest_sha256"] == hashlib.sha256((ROOT / "data/prose-sessions.json").read_bytes()).hexdigest(),
                    "Continuation parent manifest hash mismatch")
            primary_run = read(ROOT / "results/prose-heldout" / model / "run.json")
            primary_end = read(ROOT / "results/prose-heldout" / model / "summary.json")
            require(primary_run["run_id"] == continuation["parent_run_id"], "Continuation parent run mismatch")
            require(primary_end["status"] == "halted" and timestamp(continuation["created_at"]) >= timestamp(primary_end["finished_at"]),
                    "Continuation did not follow a recorded halt")
            for setting in ("max_output_tokens", "temperature", "min_interval_ms", "timeout_ms"):
                require(continuation[setting] == freeze[setting], "Continuation changed frozen setting")
            original = {(session["case_id"], session["condition"]): session for session in sessions}
            require(all(session == original.get((session["case_id"], session["condition"])) for session in subset),
                    "Continuation changed frozen sessions")
            positions = [sessions.index(session) for session in subset]
            require(positions == sorted(set(positions)), "Continuation duplicates or reorders sessions")
            segments.append((ROOT / "results/prose-continuation" / model, subset, continuation["created_at"]))
            amendments.append({"path": str(continuation_path.relative_to(ROOT)),
                               "sha256": hashlib.sha256(continuation_path.read_bytes()).hexdigest(),
                               "created_at": continuation["created_at"], "model": model,
                               "note": "Prospective for continuation only; authored after original-run outcomes."})
        responses, requests, segment_details = [], [], []
        for directory, segment_sessions, earliest in segments:
            if not (directory / "run.json").exists():
                pending.append(str(directory.relative_to(ROOT)) + ": not started")
                segment_details.append({"path": str(directory.relative_to(ROOT)), "status": "not_started", "settled": False})
                continue
            detail, segment_responses, segment_requests, reserve, model_cost, segment_issues = audit_segment(
                directory, model, segment_sessions, manifest["instructions"], freeze, earliest)
            responses.extend(segment_responses)
            requests.extend(segment_requests)
            segment_details.append(detail)
            reservation += reserve
            known_cost += model_cost
            issues.extend(segment_issues)
        identity = lambda row: (row["case_id"], row["condition"], row["phase"])
        expected_keys = {(s["case_id"], s["condition"], step["phase"]) for s in sessions for step in s["steps"]}
        requested_keys = {identity(r) for r in requests}
        response_keys = {identity(r) for r in responses}
        require(len(requested_keys) == len(requests) and len(response_keys) == len(responses), "Repeated request/response across segments")
        require(requested_keys <= expected_keys and response_keys <= requested_keys, "Unexpected segmented request")
        if continuation is not None:
            primary_requests, _, _ = journal(ROOT / "results/prose-heldout" / model / "requests.jsonl")
            continuation_keys = {(s["case_id"], s["condition"], step["phase"]) for s in continuation["sessions"] for step in s["steps"]}
            require(continuation_keys == expected_keys - {identity(r) for r in primary_requests},
                    "Continuation is not exactly the previously unissued frozen requests")
        complete = response_keys == expected_keys and all(s["settled"] for s in segment_details)
        if not complete:
            pending.append(model + ": condition coverage incomplete or segment still running")
        groups, independent = independent_scores(corpus, responses)
        valid_extractions, schema_gaps = 0, []
        for row in responses:
            if row["condition"] == "prose_extract" and independent[identity(row)]["semantic_valid"]:
                valid_extractions += 1
                gaps = explicit_field_gaps(row["output_text"])
                if gaps:
                    schema_gaps.append({"case_id": row["case_id"], "nodes": gaps})
        score = scored_by_model.get(model, {}).get("scores")
        current = bool(score and all(score["groups"][k]["received"] == value["received"] for k, value in groups.items()))
        comparison = "not_current_or_missing"
        if current:
            score_keys = [(r["case_id"], r["condition"], r["phase"]) for r in score["outcomes"]]
            require(len(score_keys) == len(independent) and set(score_keys) == set(independent), "Scorer outcome identity coverage mismatch")
            require(set(score["groups"]) == set(groups), "Scorer condition groups mismatch")
            for outcome in score["outcomes"]:
                key = (outcome["case_id"], outcome["condition"], outcome["phase"])
                observed = independent[key]
                for field, expected in observed.items():
                    require(outcome.get(field) == expected, "Independent outcome disagrees with scorer: " + repr(key) + "/" + field)
            count_fields = [key for key, value in next(iter(score["groups"].values())).items() if type(value) is int]
            for name, counters in groups.items():
                for field in count_fields:
                    require(score["groups"][name][field] == counters[field], "Independent group count disagrees: " + name + "/" + field)
            comparison = "all_outcomes_and_integer_group_counts_match"
        else:
            pending.append(model + ": scorer summary is absent or older than journal snapshot")
        models[model] = {"status": "design_covered" if complete else "incomplete", "complete": complete,
                         "planned_unique_requests": len(flat), "issued": len(requests), "responses": len(responses),
                         "manual_continuation": continuation is not None, "segments": segment_details,
                         "failed_attempts_retained": sum(bool(r.get("error")) for r in responses),
                         "valid_extractions_checked_for_explicit_fields": valid_extractions,
                         "valid_extractions_with_omitted_instruction_fields": schema_gaps,
                         "duplicate_requests_across_segments": 0, "scorer_comparison": comparison,
                         "independent_groups": {k: dict(v) for k, v in groups.items()}}
    require(reservation <= Decimal(str(freeze["approved_total_credit_cap"])), "Total reservation exceeds user cap")
    return {"schema": "retrace.prose-independent-audit.v1", "generated_at": started,
            "status": "failed" if issues else "incomplete" if pending else "passed",
            "meaning_of_pass": "Integrity and independent scoring agreement, not perfect model accuracy or absence of operational failures.",
            "reviewer": "Separate AI agent; not independent human validation",
            "self_checks_passed": self_checks,
            "method": "Offline journal verification, independent schema validation and synchronous least fixed point. No imports from RETRACE engine/scorer/session code and no API calls.",
            "frozen_files": files, "unfrozen_transitive_dependency": helper_dependency,
            "freeze_time_utc": freeze["created_at"], "case_count": len(corpus),
            "model_order": freeze["models"], "execution_amendments": amendments, "models": models, "issues": issues, "pending": pending,
            "previous_plus_started_run_reservations_credits": str(reservation),
            "known_new_run_token_estimate_credits": str(known_cost), "approved_cap_credits": freeze["approved_total_credit_cap"],
            "actual_billed_credits": None,
            "audit_implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "scorer_summary_sha256": hashlib.sha256(score_snapshot).hexdigest() if score_snapshot is not None else None,
            "limitations": ["Authored synthetic packets and shared declared semantics; no independent human annotation or real-world evidence validation.",
                            "Local hashes/timestamps demonstrate recorded consistency, not an externally timestamped preregistration or provider attestation.",
                            "The primary freeze omitted retrace/experiment.py, which supplies two parser helpers. Its observed hash matches the earlier artifact inventory, but this audit hash is recorded after outputs began; not every transitive scoring dependency was prospectively frozen.",
                            "Gemma continuation is a documented manual execution amendment for previously unissued sessions; it is not a retry of the failed output. Original unused reservations remain charged to the conservative cap.",
                            "Returned endpoint model names are checked; undisclosed provider routing or model-weight versions cannot be verified.",
                            "Checks every journaled attempt; cannot rule out requests made outside these run journals.",
                            "Usage costs are uncached token estimates, not verified account charges. Unknown usage remains explicitly reserved.",
                            "Frozen runner checks top-level completed status and HTTP success but does not independently reject non-null error/incomplete details inside an otherwise completed envelope; this audit checks those fields.",
                            "Independent comparison covers case outcomes and integer aggregate counts, not independent bootstrap reproduction.",
                            "Frozen extraction validation permits default root kind, active=true, and empty root parents when omitted. Explicit field omissions are separately reported; semantic validity must not be described as enforcing every instruction field.",
                            "An incomplete live snapshot may have one request in flight and a scorer summary from an earlier snapshot."]}


if __name__ == "__main__":
    destination = ROOT / "results/prose-independent-audit.json"
    try:
        result = audit()
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError, OSError) as exc:
        result = {"schema": "retrace.prose-independent-audit.v1", "status": "failed",
                  "generated_at": datetime.now(timezone.utc).isoformat(), "error": str(exc),
                  "method": "Offline audit; no model API calls"}
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "error": result.get("error"),
                      "pending": result.get("pending", []), "output": str(destination)}))
    raise SystemExit(1 if result["status"] == "failed" else 0)
