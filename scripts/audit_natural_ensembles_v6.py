"""Exploratory offline audit of actual K10 ensembles versus one-pass source IR.

No model access, authored seeds, output repair, primary rescoring or p-values.
The reference-free detector is called before gold-only witness grading.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.compact_graph import validate_explicit_graph
from retrace.core import analyze
from retrace.refuter_impact_v6 import compare_readings
from retrace.uncertainty_v6c import _canonical

STATES = ("initial", "withdrawn", "restored")
TARGET_CONDITIONS = {"sample_graph", "source_ir"}


def load(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise ValueError("Duplicate JSON field")
            out[key] = value
        return out
    def invalid(_): raise ValueError("Nonfinite JSON value")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def signature(graph):
    return json.dumps(_canonical(graph), sort_keys=True, separators=(",", ":"))


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def family_metrics(candidates, expected):
    predicted = {signature(c["graph"]) for c in candidates}
    gold = {signature(c["graph"]) for c in expected}
    return {"available": bool(candidates), "candidate_count": len(candidates),
            "distinct_graphs": len(predicted), "duplicate_graphs": len(candidates) - len(predicted),
            "source_distinct_graphs": len(gold), "missing_graphs": len(gold - predicted),
            "spurious_graphs": len(predicted - gold), "exact": bool(candidates) and predicted == gold,
            "sound_nonempty": bool(candidates) and predicted <= gold}


def features(graph):
    """Explicit syntactic facts, not inferred ancestry or source-truth claims."""
    result = set()
    for category in ("evidence", "claims", "decisions"):
        for row in graph[category]:
            result.add(("node", category, row["id"]))
            if category == "evidence":
                result.add(("origin_group", row["id"], row["kind"], tuple(sorted(row["parents"]))))
                for parent in row["parents"]: result.add(("direct_parent", row["id"], parent))
            elif category == "claims":
                for route in row["supports"]: result.add(("complete_support_route", row["id"], tuple(sorted(route))))
            else:
                result.add(("decision_requirement_group", row["id"], tuple(sorted(row["requires"]))))
    return result


def shared_feature_omissions(candidates, expected):
    if not candidates: return {"available": False, "count": None, "features": []}
    certain = set.intersection(*(features(c["graph"]) for c in expected))
    represented = set.union(*(features(c["graph"]) for c in candidates))
    absent = sorted(certain - represented)
    return {"available": True, "count": len(absent), "features": absent,
            "scope": "Authored-family facts present in every reference interpretation and absent from every actual ensemble graph. Exact node/origin/route/requirement syntax only; not automatic semantic omission detection."}


def locked_exclusions(case, state_name):
    state = case["events"]["states"][state_name]
    groups = {row["id"]: row["evidence_ids"] for row in case["events"]["document_groups"]}
    locked = set(state["revoked_passages"])
    for document in state["revoked_documents"]:
        if document not in groups: raise ValueError("Unknown event document group")
        locked.update(groups[document])
    known = set(case["public"]["registry"]["evidence"])
    if not locked <= known: raise ValueError("Unknown event evidence ID")
    return sorted(locked)


def consensus(candidates, targets, locked):
    snapshots = [analyze(c["graph"], [eid for eid in locked if eid in {n["id"] for n in c["graph"]["evidence"]}]) for c in candidates]
    result = {}
    for did in targets:
        values = [snapshot["decisions"].get(did, {}).get("usable") for snapshot in snapshots]
        result[did] = ("unavailable" if not values or any(type(v) is not bool for v in values) else
                       "unanimous_supported" if all(values) else "disputed" if any(values) else "unanimous_unsupported")
    return result


def state_score(candidates, expected, targets, locked):
    prediction = consensus(candidates, targets, locked)
    gold = consensus(expected, targets, locked)
    unanimous = [did for did in targets if prediction[did].startswith("unanimous_")]
    false = [did for did in unanimous if prediction[did] != gold[did]]
    return {"prediction": prediction, "authored_consensus": gold,
            "exact_vector": bool(candidates) and prediction == gold,
            "unanimous_decisions": unanimous, "false_unanimity_decisions": false,
            "opposite_unanimity_decisions": [did for did in false if gold[did].startswith("unanimous_")],
            "unacknowledged_source_ambiguity_decisions": [did for did in false if gold[did] == "disputed"],
            "unavailable_decisions": [did for did in targets if prediction[did] == "unavailable"]}


def challenge(actual_k10, actual_ir, expected, targets, locked):
    if not actual_k10 or not actual_ir:
        return {"status": "unavailable", "reason": "An executable actual K10 ensemble and one-pass IR family are both required", "warnings": []}
    # Only emitted graphs and public interventions enter this call. No expected
    # graph is inserted, proposed, selected or used to choose a witness.
    try:
        detected = compare_readings(actual_k10, actual_ir, locked_exclusions=locked, target_decisions=targets)
    except ValueError as exc:
        return {"status": "unavailable", "reason": str(exc), "warnings": []}
    old = {signature(c["graph"]) for c in actual_k10}
    gold = {signature(c["graph"]) for c in expected}
    novel = {signature(c["graph"]) for c in actual_ir} - old
    novel_sound = bool(novel) and novel <= gold
    warnings = []
    for did, row in detected["decisions"].items():
        witness = row["minimum_consensus_loss"]
        if witness is None: continue
        # Evaluation-side grading follows the detector's already-fixed witness.
        truth = consensus(expected, [did], sorted(set(locked) | set(witness["withdraw"])))[did]
        before = witness["current_family_state"]
        grade = ("source_aligned_challenge" if novel_sound and truth != before else
                 "false_alarm_at_witness" if truth == before else "unlicensed_or_mixed_proposal_challenge")
        warnings.append({"decision_id": did, "witness": witness, "evaluation_only": {
            "all_novel_proposed_graphs_in_authored_family": novel_sound,
            "authored_consensus_at_witness": truth, "k10_consensus_wrong_at_witness": truth != before,
            "augmented_consensus_matches_authored": witness["augmented_family_state"] == truth,
            "grade": grade}})
    return {"status": "evaluated", "reference_free_detection": detected, "warnings": warnings,
            "evaluation_only": {"novel_ir_graphs": len(novel), "all_novel_ir_graphs_source_aligned": novel_sound},
            "scope": "Actual one-pass IR is added to the actual sampled union, never to authored seeds. Warning absence is not a success or a completeness certificate. Grading is retrospective against the authored family."}


def admitted(row, condition):
    if row is None: return []
    if row.get("schema_valid") is not True or row.get("executable") is not True:
        if row.get("candidates"): raise ValueError("Nonexecutable audit row contains executable candidates")
        return []
    candidates = row.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= (1 if condition == "sample_graph" else 32):
        raise ValueError("Admitted audit row has invalid candidate count")
    ids = set(); result = []
    for candidate in candidates:
        if not isinstance(candidate.get("id"), str) or candidate["id"] in ids: raise ValueError("Invalid or duplicate candidate ID")
        ids.add(candidate["id"])
        result.append({"id": candidate["id"], "graph": validate_explicit_graph(deepcopy(candidate["graph"]))})
    return result


def summarize(rows):
    n = len(rows)
    result = {"planned_pairs": n, "availability_strata": dict(Counter(r["availability_stratum"] for r in rows)),
              "k10_complete10": rate(sum(r["valid_k10_draws"] == 10 for r in rows), n),
              "ir_executable": rate(sum(r["ir_executable"] for r in rows), n),
              "k10_exact_family": rate(sum(r["k10_family"]["exact"] for r in rows), n),
              "ir_exact_family": rate(sum(r["ir_family"]["exact"] for r in rows), n),
              "k10_shared_feature_omission": rate(sum((r["k10_shared_feature_omissions"]["count"] or 0) > 0 for r in rows), n),
              "states": {}}
    all_warnings = lambda row: [warning for state in row["states"].values() for warning in state["ir_addition_challenge"]["warnings"]]
    result["any_actual_state_k10_false_unanimity"] = rate(sum(any(s["k10"]["false_unanimity_decisions"] for s in r["states"].values()) for r in rows), n)
    result["any_withdrawal_warning_from_an_actual_state"] = rate(sum(bool(all_warnings(r)) for r in rows), n)
    for grade in ("source_aligned_challenge", "false_alarm_at_witness", "unlicensed_or_mixed_proposal_challenge"):
        result[grade + "_in_any_state"] = rate(sum(any(w["evaluation_only"]["grade"] == grade for w in all_warnings(r)) for r in rows), n)
    for state_name in STATES:
        states = [r["states"][state_name] for r in rows]
        targets = sum(len(s["k10"]["prediction"]) for s in states)
        warnings = [w for s in states for w in s["ir_addition_challenge"]["warnings"]]
        result["states"][state_name] = {
            "planned_pairs": n, "planned_decisions": targets,
            "k10_exact_vector": rate(sum(s["k10"]["exact_vector"] for s in states), n),
            "ir_exact_vector": rate(sum(s["source_ir"]["exact_vector"] for s in states), n),
            "k10_false_unanimity_all_decisions": rate(sum(len(s["k10"]["false_unanimity_decisions"]) for s in states), targets),
            "k10_false_unanimity_among_unanimous": rate(sum(len(s["k10"]["false_unanimity_decisions"]) for s in states), sum(len(s["k10"]["unanimous_decisions"]) for s in states)),
            "k10_unavailable_decisions": sum(len(s["k10"]["unavailable_decisions"]) for s in states),
            "ir_unavailable_decisions": sum(len(s["source_ir"]["unavailable_decisions"]) for s in states),
            "detector_evaluable": rate(sum(s["ir_addition_challenge"]["status"] == "evaluated" for s in states), n),
            "warnings_all_decisions": rate(len(warnings), targets),
            "warning_grades": dict(Counter(w["evaluation_only"]["grade"] for w in warnings)),
            "source_aligned_warning_selective_precision": rate(sum(w["evaluation_only"]["grade"] == "source_aligned_challenge" for w in warnings), len(warnings)),
            "scope": "One smallest witness per decision and event state; warning grades can differ between decisions. State repetitions are not independent observations."}
    return result


def audit_ensembles(corpus, sessions, audits, *, require_primary=True):
    cases = {case["id"]: case for case in corpus["cases"]}
    if len(cases) != len(corpus["cases"]): raise ValueError("Duplicate source case")
    scheduled = {}; plan = {}
    for slot in sessions:
        sid = slot["slot_id"]
        if sid in scheduled: raise ValueError("Duplicate scheduled slot")
        scheduled[sid] = slot
        if slot["condition"] not in TARGET_CONDITIONS: continue
        key = slot["model"], slot["case_id"]
        if slot["case_id"] not in cases: raise ValueError("Unknown source case")
        role = slot["condition"], slot["phase"]
        if role in plan.setdefault(key, {}): raise ValueError("Duplicate model/case/role")
        plan[key][role] = sid
    roles = {("sample_graph", f"draw_{i:02d}") for i in range(1, 11)} | {("source_ir", "extract")}
    if any(set(value) != roles for value in plan.values()): raise ValueError("Every model/case pair needs ten planned draws and one IR slot")
    models = sorted({key[0] for key in plan})
    if set(plan) != {(m, c) for m in models for c in cases}: raise ValueError("Incomplete planned model/case grid")
    if require_primary and (len(cases) != 48 or len(models) != 5 or len(plan) != 240 or len(sessions) != 4560):
        raise ValueError("Primary supplement requires the full48-case/five-model/240-pair/4560-slot schedule")
    observed = {}; union_rows = {}
    for row in audits:
        if row.get("condition") == "k10_union":
            key = row.get("model"), row.get("case_id")
            if key not in plan or key in union_rows: raise ValueError("Unknown or duplicate union audit")
            union_rows[key] = row; continue
        sid = row.get("slot_id")
        if sid not in scheduled or sid in observed: raise ValueError("Unknown or duplicate slot audit")
        if any(row.get(k) != scheduled[sid][k] for k in ("model", "case_id", "condition", "phase")):
            raise ValueError("Audit identity differs from schedule")
        observed[sid] = row
    rows = []
    for (model, cid), tasks in sorted(plan.items()):
        case = cases[cid]; expected = case["evaluation"]["source_family"]
        if not expected: raise ValueError("Authored family is empty")
        actual = []; valid = 0; statuses = Counter(); observed_draws = 0
        for number in range(1, 11):
            phase = f"draw_{number:02d}"; record = observed.get(tasks[("sample_graph", phase)])
            candidates = admitted(record, "sample_graph")
            if candidates:
                valid += 1; actual.append({"id": phase, "graph": candidates[0]["graph"]})
            statuses[record.get("status", "unspecified") if record else "missing_audit_row"] += 1
            observed_draws += bool(record and record.get("record_observed"))
        if (model, cid) in union_rows and union_rows[(model, cid)].get("valid_draws") != valid:
            raise ValueError("Reconstructed valid-draw count differs from frozen primary union audit")
        ir_row = observed.get(tasks[("source_ir", "extract")]); proposed = admitted(ir_row, "source_ir")
        targets = sorted(case["public"]["registry"]["decisions"])
        states = {}
        for name in STATES:
            locked = locked_exclusions(case, name)
            states[name] = {"locked_exclusions": locked, "k10": state_score(actual, expected, targets, locked),
                            "source_ir": state_score(proposed, expected, targets, locked),
                            "ir_addition_challenge": challenge(actual, proposed, expected, targets, locked)}
        k10_class = "complete10" if valid == 10 else "partial1to9" if valid else "empty0"
        rows.append({"model": model, "case_id": cid, "family": case["family"], "planned_k10_draws": 10,
                     "observed_k10_draws": observed_draws, "valid_k10_draws": valid, "draw_status_counts": dict(statuses),
                     "ir_status": ir_row.get("status", "unspecified") if ir_row else "missing_audit_row",
                     "ir_executable": bool(proposed), "availability_stratum": k10_class + "/" + ("ir_executable" if proposed else "ir_unavailable"),
                     "k10_family": family_metrics(actual, expected), "ir_family": family_metrics(proposed, expected),
                     "k10_shared_feature_omissions": shared_feature_omissions(actual, expected), "states": states})
    return {"schema": "retrace.natural-ensemble-audit.v6", "analysis_role": "exploratory_secondary_no_new_p_values",
            "current_state_alias": "initial", "summary": summarize(rows),
            "by_model": {model: summarize([r for r in rows if r["model"] == model]) for model in models},
            "by_family": {family: summarize([r for r in rows if r["family"] == family]) for family in sorted({r["family"] for r in rows})},
            "by_availability": {name: summarize([r for r in rows if r["availability_stratum"] == name]) for name in sorted({r["availability_stratum"] for r in rows})},
            "by_capacity": {name: summarize([r for r in rows if (r["k10_family"]["source_distinct_graphs"] <= 10) == feasible])
                            for name, feasible in (("at_most10_source_graphs", True), ("more_than10_source_graphs", False))},
            "rows": rows, "scope": [
                "All scheduled model/case pairs remain denominators. Empty or invalid outputs are unavailable, not evidence of agreement or successful warning absence.",
                "K10 uses only actual emitted sample graphs. The one-pass IR was not conditioned on this ensemble; this is an offline cross-arm comparison, not a live adaptive refuter experiment.",
                "Source-family gold appears only in evaluation-side fidelity, structural features and fixed-witness grading. No authored seed pool enters the detector.",
                "A source-aligned challenge requires every novel IR graph to belong to the authored family and the prior K10 unanimity to differ from authored consensus at the detector-selected witness.",
                "Adding readings cannot remove spurious K10 readings or establish truth. A valid warning can require review without restoring the exact authored consensus.",
                "Exact withdrawal search preserves original eligibility and actual vetoes. It cannot activate dormant evidence, and no warning outside this finite scope is inferred.",
                "The fixed authored cases, ten prompted samples and model outputs are not an IID natural-document sample. No new significance tests, calibration probabilities or generalization claim is made."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/frontier-v6c-staged.json")
    parser.add_argument("--sessions", type=Path, default=ROOT / "data/frontier-v6f-sessions.json")
    parser.add_argument("--audits", type=Path, required=True)
    parser.add_argument("--primary-summary", type=Path, required=True)
    parser.add_argument("--run-closed", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): raise ValueError("Supplement output must be new")
    inputs = {}
    def read(path):
        raw = path.read_bytes(); inputs[str(path.resolve())] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        return load(raw)
    corpus = read(args.corpus); sessions = read(args.sessions); primary = read(args.primary_summary)
    audits = []; digest = hashlib.sha256(); size = 0
    with args.audits.open("rb") as stream:
        for line in stream:
            digest.update(line); size += len(line)
            if not line.strip(): raise ValueError("Empty audit JSONL record")
            row = load(line)
            # Keep only fields used in this audit, avoiding duplicate IR payloads.
            audits.append({k: row[k] for k in ("slot_id", "case_id", "model", "condition", "phase", "candidates", "schema_valid", "executable", "record_observed", "status", "valid_draws") if k in row})
    inputs[str(args.audits.resolve())] = {"sha256": digest.hexdigest(), "bytes": size}
    result = audit_ensembles(corpus, sessions, audits)
    result.update(created_at=datetime.now(timezone.utc).isoformat(), inputs=inputs,
                  run_declared_closed=True, primary_status=primary.get("status"),
                  primary_all_planned_final_outcomes=primary.get("all_planned_final_outcomes"))
    result["implementation_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for path, metadata in inputs.items():
        with Path(path).open("rb") as stream: current = hashlib.file_digest(stream, "sha256").hexdigest()
        if current != metadata["sha256"]: raise ValueError("Input changed during offline analysis")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__": main()
