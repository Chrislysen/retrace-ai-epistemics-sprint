"""Frozen scoring rules for the held-out, synthetic prose transfer experiment.

Content scoring permits exactly one enclosing Markdown fence, a rule fixed from
the earlier pilot. Strict formatting remains a separately reported outcome.
No model output is repaired, completed, or replaced with a reference answer.
"""
from __future__ import annotations

import copy
import json
import random
from collections import defaultdict
from typing import Any

from .core import analyze, validate_case
from .experiment import parse_predictions, strip_outer_fence

CONDITIONS = {
    "formal_fresh": ("final",),
    "prose_fresh": ("final",),
    "prose_history": ("initial", "withdrawn"),
    "prose_no_commitment": ("final",),
    "prose_extract": ("final",),
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(text: str, *, allow_outer_fence: bool = True) -> tuple[dict, bool]:
    if not isinstance(text, str):
        raise ValueError("Model output must be text")
    normalized, stripped = strip_outer_fence(text) if allow_outer_fence else (text, False)
    value = json.loads(normalized, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("Model output must be a JSON object")
    return value, stripped


def _rows(corpus):
    rows = corpus.get("cases") if isinstance(corpus, dict) else corpus
    if not isinstance(rows, list):
        raise ValueError("Corpus must be a list or an object containing cases")
    ids = [row.get("id") for row in rows]
    if any(not isinstance(identifier, str) or not identifier for identifier in ids) or len(set(ids)) != len(ids):
        raise ValueError("Case IDs must be unique nonempty strings")
    return rows


def gold_for(item: dict) -> dict:
    """Return before/final states and event-specific eligibility sets."""
    case = item["case"]
    if case.get("id", item["id"]) != item["id"]:
        raise ValueError("Outer and graph case IDs must agree")
    validate_case(case)
    before = analyze(case)
    after = analyze(case, case["revoke"])
    final_graph = {key: copy.deepcopy(case[key]) for key in ("evidence", "claims", "decisions")}
    for record in final_graph["evidence"]:
        if record["id"] in case["revoke"]:
            record["active"] = False
    # This invariant catches mismatches between an explicit event and final flags.
    final_snapshot = analyze(final_graph)
    if final_snapshot["supported_decisions"] != after["supported_decisions"]:
        raise ValueError("Final snapshot does not match the withdrawal event")
    dependencies = {}
    for node in case["evidence"]:
        dependencies[node["id"]] = node.get("parents", [])
    for node in case["claims"]:
        dependencies[node["id"]] = [ref for clause in node["supports"] for ref in clause]
    for node in case["decisions"]:
        dependencies[node["id"]] = node["requires"]
    memo = {}
    def touched(identifier):
        if identifier not in memo:
            memo[identifier] = identifier in case["revoke"] or any(touched(ref) for ref in dependencies[identifier])
        return memo[identifier]
    initial = {key: value["usable"] for key, value in before["decisions"].items()}
    final = {key: value["usable"] for key, value in after["decisions"].items()}
    lost = {key for key in initial if initial[key] and not final[key]}
    preserved = {key for key in initial if initial[key] and final[key]}
    protected = {key for key in preserved if touched(key)}
    return {"initial": initial, "final": final, "lost": lost, "preserved": preserved,
            "protected": protected, "unaffected_supported": preserved - protected,
            "initially_unsupported": {key for key, value in initial.items() if not value},
            "final_graph": final_graph}


def canonical_graph(graph: dict) -> dict:
    """Ignore labels and ordering, retaining AND/OR grouping and active flags."""
    return {
        "evidence": {row["id"]: (row.get("kind", "root"), row.get("active", True),
                                  tuple(sorted(row.get("parents", [])))) for row in graph["evidence"]},
        "claims": {row["id"]: tuple(sorted(set(tuple(sorted(clause)) for clause in row["supports"])))
                   for row in graph["claims"]},
        "decisions": {row["id"]: tuple(sorted(row["requires"])) for row in graph["decisions"]},
    }


def _edges(graph):
    edges = set()
    for record in graph["evidence"]:
        edges.update((record["id"], "parent", ref) for ref in record.get("parents", []))
    for record in graph["claims"]:
        edges.update((record["id"], "support", ref) for clause in record["supports"] for ref in clause)
    for record in graph["decisions"]:
        edges.update((record["id"], "requires", ref) for ref in record["requires"])
    return edges


def parse_extracted_graph(text: str, reference: dict, *, allow_outer_fence=True) -> dict:
    graph, stripped = parse_json(text, allow_outer_fence=allow_outer_fence)
    if set(graph) != {"evidence", "claims", "decisions"}:
        raise ValueError("Extracted graph must have exactly evidence, claims, and decisions")
    allowed = {
        "evidence": {"id", "label", "kind", "parents", "active"},
        "claims": {"id", "label", "supports"},
        "decisions": {"id", "label", "requires"},
    }
    for category in allowed:
        if not isinstance(graph[category], list):
            raise ValueError(f"{category} must be a list")
        for record in graph[category]:
            if not isinstance(record, dict) or set(record) - allowed[category]:
                raise ValueError(f"Unexpected fields in extracted {category}")
        if {row.get("id") for row in graph[category]} != {row["id"] for row in reference[category]}:
            raise ValueError(f"Extracted {category} IDs do not match the task")
    validate_case(graph)
    current = analyze(graph)
    predicted = {key: value["usable"] for key, value in current["decisions"].items()}
    actual_canonical = canonical_graph(graph)
    reference_canonical = canonical_graph(reference)
    correct_nodes = sum(actual_canonical[category][key] == value
                        for category, nodes in reference_canonical.items() for key, value in nodes.items())
    total_nodes = sum(len(nodes) for nodes in reference_canonical.values())
    actual_edges, reference_edges = _edges(graph), _edges(reference)
    return {"predictions": predicted, "outer_fence_removed": stripped,
            "graph_exact": actual_canonical == reference_canonical,
            "correct_nodes": correct_nodes, "total_nodes": total_nodes,
            "edge_true_positive": len(actual_edges & reference_edges),
            "edge_false_positive": len(actual_edges - reference_edges),
            "edge_false_negative": len(reference_edges - actual_edges)}


def _parse(text, condition, gold, *, allow_outer_fence):
    if condition == "prose_extract":
        return parse_extracted_graph(text, gold["final_graph"], allow_outer_fence=allow_outer_fence)
    value, stripped = parse_json(text, allow_outer_fence=allow_outer_fence)
    predictions = parse_predictions(value, set(gold["final"]))
    return {"predictions": predictions, "outer_fence_removed": stripped}


def _mean(values):
    return sum(values) / len(values) if values else None


def _bootstrap(values, seed, repeats=2000):
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(repeats))
    return [means[int(.025 * (repeats - 1))], means[int(.975 * (repeats - 1))]]


def score_prose(corpus, records: list[dict], *, bootstrap_seed=2026111302, bootstrap_repeats=2000) -> dict:
    if not isinstance(bootstrap_repeats, int) or bootstrap_repeats < 1:
        raise ValueError("bootstrap_repeats must be positive")
    cases = _rows(corpus)
    if len({record.get("model") for record in records if record.get("model")}) > 1:
        raise ValueError("Score one model at a time")
    gold = {item["id"]: gold_for(item) for item in cases}
    expected = {(item["id"], condition, phase) for item in cases
                for condition, phases in CONDITIONS.items() for phase in phases}
    actual, unexpected = {}, []
    for record in records:
        key = (record.get("case_id"), record.get("condition"), record.get("phase"))
        if key not in expected:
            unexpected.append(list(key))
            continue
        if key in actual:
            raise ValueError(f"Duplicate record: {key}")
        actual[key] = record
    groups = defaultdict(lambda: {"expected": 0, "received": 0, "operational_failures": 0,
                                  "strict_valid": 0, "semantic_valid": 0, "exact": 0,
                                  "outer_fences_removed": 0, "decision_targets_all": 0,
                                  "decision_errors_all_scheduled": 0, "decision_targets_valid": 0,
                                  "decision_errors_valid": 0, "required_retractions": 0,
                                  "missed_retractions": 0, "preserved_targets": 0,
                                  "collateral_errors": 0, "protected_targets": 0,
                                  "protected_collateral_errors": 0, "unaffected_targets": 0,
                                  "unaffected_errors": 0, "initially_unsupported_targets": 0,
                                  "initially_unsupported_accepted": 0,
                                  "graph_exact": 0, "graph_nodes_correct": 0, "graph_nodes_total": 0,
                                  "edge_true_positive": 0, "edge_false_positive": 0, "edge_false_negative": 0})
    outcomes = {}
    for key in sorted(expected):
        case_id, condition, phase = key
        reference = gold[case_id]
        truth = reference["initial"] if phase == "initial" else reference["final"]
        group = groups[f"{condition}/{phase}"]
        group["expected"] += 1
        group["decision_targets_all"] += len(truth)
        row = {"case_id": case_id, "condition": condition, "phase": phase,
               "strict_valid": False, "semantic_valid": False, "exact": False,
               "error": None, "decision_error_fraction_all_scheduled": 1.0,
               "predictions": None}
        record = actual.get(key)
        parsed = None
        if record is None:
            row["error"] = "missing_response"
        else:
            group["received"] += 1
            if record.get("error") or record.get("response_status", "completed") not in (None, "completed"):
                group["operational_failures"] += 1
                row["error"] = record.get("error") or "incomplete_provider_response"
            else:
                try:
                    _parse(record.get("output_text"), condition, reference, allow_outer_fence=False)
                    row["strict_valid"] = True
                    group["strict_valid"] += 1
                except (ValueError, TypeError, KeyError, RecursionError):
                    pass
                try:
                    parsed = _parse(record.get("output_text"), condition, reference, allow_outer_fence=True)
                except (ValueError, TypeError, KeyError, RecursionError) as exc:
                    row["error"] = str(exc)
        if parsed is None:
            group["decision_errors_all_scheduled"] += len(truth)
        else:
            predictions = parsed["predictions"]
            errors = sum(predictions[identifier] != value for identifier, value in truth.items())
            row.update(semantic_valid=True, exact=errors == 0, predictions=predictions,
                       decision_error_fraction_all_scheduled=errors / len(truth) if truth else 0.0,
                       outer_fence_removed=parsed["outer_fence_removed"])
            group["semantic_valid"] += 1
            group["outer_fences_removed"] += parsed["outer_fence_removed"]
            group["exact"] += errors == 0
            group["decision_targets_valid"] += len(truth)
            group["decision_errors_valid"] += errors
            group["decision_errors_all_scheduled"] += errors
            if phase != "initial":
                for target_key, numerator_key, ids, error_value in (
                    ("required_retractions", "missed_retractions", reference["lost"], True),
                    ("preserved_targets", "collateral_errors", reference["preserved"], False),
                    ("protected_targets", "protected_collateral_errors", reference["protected"], False),
                    ("unaffected_targets", "unaffected_errors", reference["unaffected_supported"], False),
                    ("initially_unsupported_targets", "initially_unsupported_accepted", reference["initially_unsupported"], True),
                ):
                    group[target_key] += len(ids)
                    group[numerator_key] += sum(predictions[identifier] == error_value for identifier in ids)
            if condition == "prose_extract":
                row["extraction"] = {k: v for k, v in parsed.items() if k not in {"predictions", "outer_fence_removed"}}
                group["graph_exact"] += parsed["graph_exact"]
                group["graph_nodes_correct"] += parsed["correct_nodes"]
                group["graph_nodes_total"] += parsed["total_nodes"]
                for field in ("edge_true_positive", "edge_false_positive", "edge_false_negative"):
                    group[field] += parsed[field]
        outcomes[key] = row
    for group_name, group in groups.items():
        for output, numerator, denominator in (
            ("strict_format_rate", "strict_valid", "expected"),
            ("semantic_coverage", "semantic_valid", "expected"),
            ("exact_rate_all_scheduled", "exact", "expected"),
            ("decision_error_rate_all_scheduled", "decision_errors_all_scheduled", "decision_targets_all"),
            ("decision_error_rate_valid_only", "decision_errors_valid", "decision_targets_valid"),
            ("missed_retraction_rate_valid_only", "missed_retractions", "required_retractions"),
            ("collateral_rate_valid_only", "collateral_errors", "preserved_targets"),
            ("protected_collateral_rate_valid_only", "protected_collateral_errors", "protected_targets"),
            ("unaffected_error_rate_valid_only", "unaffected_errors", "unaffected_targets"),
            ("initially_unsupported_acceptance_rate_valid_only", "initially_unsupported_accepted", "initially_unsupported_targets"),
            ("graph_exact_rate_all_scheduled", "graph_exact", "expected"),
            ("graph_node_accuracy_valid_only", "graph_nodes_correct", "graph_nodes_total"),
        ):
            group[output] = group[numerator] / group[denominator] if group[denominator] else None
        if not group_name.startswith("prose_extract/"):
            group["graph_exact_rate_all_scheduled"] = None
    contrasts = []
    pairs = [("prose_fresh", "formal_fresh"), ("prose_history", "prose_fresh"),
             ("prose_history", "prose_no_commitment"), ("prose_no_commitment", "prose_fresh"),
             ("prose_extract", "prose_fresh")]
    for number, (left, right) in enumerate(pairs):
        deltas, valid_deltas, paired_rows = [], [], []
        for item in cases:
            identifier = item["id"]
            left_row = outcomes[(identifier, left, "withdrawn" if left == "prose_history" else "final")]
            right_row = outcomes[(identifier, right, "final")]
            # Difference in decision accuracy: positive means left performed better.
            delta = right_row["decision_error_fraction_all_scheduled"] - left_row["decision_error_fraction_all_scheduled"]
            deltas.append(delta)
            both_valid = left_row["semantic_valid"] and right_row["semantic_valid"]
            if both_valid:
                valid_deltas.append(delta)
            paired_rows.append({"case_id": identifier, "both_valid": both_valid, "accuracy_delta": delta,
                                "same_decisions": left_row["predictions"] == right_row["predictions"] if both_valid else None})
        contrasts.append({"name": f"{left}_minus_{right}", "base_cases": len(deltas),
                          "both_valid_cases": len(valid_deltas),
                          "mean_accuracy_delta_all_scheduled": _mean(deltas),
                          "mean_accuracy_delta_both_valid": _mean(valid_deltas),
                          "case_bootstrap_stability_interval_95": _bootstrap(deltas, bootstrap_seed + number, bootstrap_repeats),
                          "pairs": paired_rows})
    return {"schema_version": "retrace.prose-scores.v1", "case_count": len(cases),
            "semantic_parser": "prespecified single whole outer fence allowed; strict format reported separately",
            "groups": dict(groups), "outcomes": list(outcomes.values()), "contrasts": contrasts,
            "unexpected_records": unexpected, "bootstrap_seed": bootstrap_seed, "bootstrap_repeats": bootstrap_repeats,
            "interpretation": ["Synthetic, authored prose; not real document extraction accuracy.",
                               "Missing, incomplete and invalid replies score non-exact in all-scheduled summaries; these are not automatically reasoning errors.",
                               "Conditional class-error denominators include only semantically valid outputs.",
                               "Bootstrap intervals describe resampling stability over these constructed cases, not population-level confidence or proof of no effect.",
                               "Same edge set can encode different AND/OR logic; exact normalized clauses are scored separately.",
                               "Extraction plus recomputation uses model-extracted structure, not the gold graph; errors can remain or compound."]}
