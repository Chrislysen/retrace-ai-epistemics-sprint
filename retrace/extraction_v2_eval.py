"""Frozen prospective paired format evaluation. No completion or answer repair."""
import json
import statistics

from .compact_graph import MAX_NODES, MAX_TEXT_CHARS, parse_compact_output, validate_explicit_graph
from .core import analyze
from .prose_eval import canonical_graph, gold_for, parse_json, _bootstrap

CONDITIONS = ("json_v2", "compact_v2")
FIELDS = {"evidence": {"id", "kind", "active", "parents"},
          "claims": {"id", "supports"}, "decisions": {"id", "requires"}}


def parse_output(text, condition, registry=None):
    if condition == "compact_v2":
        return parse_compact_output(text, registry)
    if condition != "json_v2":
        raise ValueError("Unknown extraction condition")
    if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
        raise ValueError("Output must be text within the character bound")
    graph, fenced = parse_json(text)
    if set(graph) != set(FIELDS):
        raise ValueError("Expected exactly evidence, claims and decisions")
    for category, fields in FIELDS.items():
        if not isinstance(graph[category], list):
            raise ValueError("Graph categories must be arrays")
        if any(not isinstance(row, dict) or set(row) != fields for row in graph[category]):
            raise ValueError("All and only explicit fields required: " + category)
    if sum(len(graph[k]) for k in FIELDS) > MAX_NODES:
        raise ValueError("Node limit exceeded")
    # Shared explicit semantic constraints; no serialization or default insertion.
    compiled = validate_explicit_graph(graph, registry)
    return {"graph": compiled, "outer_fence_removed": fenced,
            "strict_bare": not fenced, "source_text": text}


def score(corpus, records):
    cases = {c["id"]: c for c in corpus}
    if not cases or len(cases) != len(corpus):
        raise ValueError("Corpus must contain unique nonempty cases")
    if len({r["model"] for r in records}) > 1:
        raise ValueError("Score one model at a time")
    by_key = {}
    for r in records:
        key = r["case_id"], r["condition"]
        if key in by_key or key[0] not in cases or key[1] not in CONDITIONS or r["phase"] != "final":
            raise ValueError("Duplicate or unexpected response")
        by_key[key] = r
    outcomes, groups = [], {}
    for condition in CONDITIONS:
        group = dict(expected=len(corpus), received=0, valid=0, strict_valid=0,
                     graph_exact=0, decision_exact=0, decision_targets=0,
                     correct_decisions_all_scheduled=0, correct_decisions_valid=0,
                     decision_targets_valid=0, operational_failures=0,
                     input_tokens=0, output_tokens=0, reasoning_tokens=0, usage_records=0)
        latency = []
        for entry in corpus:
            gold = gold_for(entry)
            reference = gold["final_graph"]
            registry = {k: [r["id"] for r in reference[k]] for k in FIELDS}
            truth = gold["final"]
            group["decision_targets"] += len(truth)
            row = dict(case_id=entry["id"], condition=condition, valid=False, strict_valid=False,
                       graph_exact=False, decision_exact=False, correct_decisions=0,
                       decision_targets=len(truth), predictions=None, error="missing_response")
            record = by_key.get((entry["id"], condition))
            if record:
                group["received"] += 1
                if isinstance(record.get("latency_ms"), (int, float)):
                    latency.append(record["latency_ms"])
                usage = record.get("usage")
                if usage:
                    group["usage_records"] += 1
                    group["input_tokens"] += usage.get("input_tokens") or 0
                    group["output_tokens"] += usage.get("output_tokens") or 0
                    group["reasoning_tokens"] += (usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0
                if record.get("error") or record.get("response_status") not in (None, "completed"):
                    row["error"] = record.get("error") or "incomplete_provider_response"
                    group["operational_failures"] += 1
                else:
                    try:
                        parsed = parse_output(record.get("output_text"), condition, registry)
                        predictions = {k: v["usable"] for k, v in analyze(parsed["graph"])["decisions"].items()}
                        correct = sum(predictions[k] == v for k, v in truth.items())
                        exact = canonical_graph(parsed["graph"]) == canonical_graph(reference)
                        row.update(valid=True, strict_valid=parsed["strict_bare"], graph_exact=exact,
                                   decision_exact=correct == len(truth), correct_decisions=correct,
                                   predictions=predictions, error=None, graph=parsed["graph"])
                        for field in ("valid", "strict_valid", "graph_exact", "decision_exact"):
                            group[field] += int(row[field])
                        group["correct_decisions_all_scheduled"] += correct
                        group["correct_decisions_valid"] += correct
                        group["decision_targets_valid"] += len(truth)
                    except (ValueError, TypeError, KeyError, RecursionError) as exc:
                        row["error"] = str(exc)
            outcomes.append(row)
        group["median_latency_ms"] = statistics.median(latency) if latency else None
        groups[condition] = group
    pairs = {(r["case_id"], r["condition"]): r for r in outcomes}
    contrasts = {}
    for metric in ("valid", "graph_exact", "decision_exact"):
        differences = [int(pairs[(c, "compact_v2")][metric]) - int(pairs[(c, "json_v2")][metric]) for c in cases]
        contrasts[metric] = {"compact_minus_json": sum(differences) / len(differences),
                             "case_resampling_95_stability_interval": _bootstrap(differences, 2026111319, 2000),
                             "compact_only": differences.count(1), "json_only": differences.count(-1)}
    return {"schema": "retrace.extraction-v2-scores", "groups": groups, "contrasts": contrasts,
            "outcomes": outcomes,
            "note": "Missing/invalid outputs fail all-scheduled outcomes. Valid-only counts are conditional; 12 cases share four topologies. Intervals are descriptive case-resampling stability intervals."}
