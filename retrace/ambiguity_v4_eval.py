"""Prospective-to-v4 scoring; authored structural oracles are scoring-only.

No output repair, reference insertion, branch pruning at admission, probability
interpretation of branch counts, or inference API calls occur in this module.
"""
from __future__ import annotations

import copy
import hashlib
from collections import Counter

from .ambiguity_v4_sessions import ABSTENTION, CONDITION
from .compact_graph import serialize_compact
from .compact_v4 import compile_ambiguity
from .core import analyze
from .coverage_v4 import analyze_root_coverage
from .stress import analyze_stress

PRIMARY_SUBSET = ("ambiguity-v3-01", "ambiguity-v3-02", "ambiguity-v3-04")


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


def _actual(packet):
    hidden = packet["hidden"]
    return hidden["allowed_interpretations"][hidden["author_actual_interpretation_index"]]


def family_metrics(packet, candidates):
    family = {serialize_compact(graph) for graph in packet["hidden"]["allowed_interpretations"]}
    forms = [serialize_compact(row["graph"]) for row in candidates]
    distinct = set(forms)
    covered, outside = family & distinct, distinct - family
    return {
        "candidate_count": len(candidates), "distinct_graph_count": len(distinct),
        "duplicate_assignment_branches": len(candidates) - len(distinct),
        "outside_family_branches": sum(form not in family for form in forms),
        "outside_family_distinct_graphs": len(outside),
        "all_candidates_source_defensible": bool(candidates) and not outside,
        "reference_family_size": len(family), "covered_author_interpretation_count": len(covered),
        "family_coverage_fraction": _rate(len(covered), len(family)),
        "full_family_covered": family <= distinct,
        "exact_family_recovery": bool(candidates) and distinct == family,
        "actual_graph_covered": serialize_compact(_actual(packet)) in distinct,
        "overgeneration": bool(outside),
        "branch_count_interpretation": "Declared assignments, never frequencies or probabilities.",
    }


def _body(record):
    if "supports" in record:
        return ("claim", tuple(sorted(tuple(sorted(route)) for route in record["supports"])))
    return ("evidence", record["kind"], tuple(sorted(record["parents"])))


def ground_questions(packet, compilation):
    """Match full structural target bodies; activity and support are irrelevant.

    Exactly one option must match the withheld author-selected source reading.
    Neither/both matches leave the factual answer unknown. This is an authored
    structural oracle diagnostic, not human verification or an inferred answer.
    """
    actual = {row["id"]: row for kind in ("evidence", "claims", "decisions") for row in _actual(packet)[kind]}
    family_targets = [{row["id"]: row for kind in ("evidence", "claims", "decisions") for row in graph[kind]}
                      for graph in packet["hidden"]["allowed_interpretations"]]
    question_tables = {row["id"]: row for row in compilation["questions"]}
    result = []
    for operator in compilation["operators"]:
        target = operator["target"]
        bodies = [_body(option["replacement"]) for option in operator["options"]]
        matching = [option["answer"] for option, body in zip(operator["options"], bodies) if body == _body(actual[target])]
        consistent = True
        for candidate in compilation["candidates"]:
            record = next(row for kind in ("evidence", "claims") for row in candidate["graph"][kind] if row["id"] == target)
            answer = candidate["assignment"][operator["id"]]
            consistent &= (_body(record) == bodies[int(answer)]
                           and question_tables[operator["id"]]["answers"][candidate["id"]] is answer)
        result.append({
            "id": operator["id"], "kind": operator["kind"], "target": target,
            "label": operator["question_label"], "branch_assignment_semantics_consistent": bool(consistent),
            "actual_target_matches_exactly_one_option": len(matching) == 1,
            "grounded_answer": matching[0] if len(matching) == 1 else None,
            "grounding_status": "authored_structural_fact" if len(matching) == 1 else "ungroundable",
            "option_in_author_family": {str(option["answer"]).lower(): any(body == _body(graph[target]) for graph in family_targets)
                                        for option, body in zip(operator["options"], bodies)},
            "grounding_basis": "Exact complete target-body match in author-selected source interpretation; no activity/decision outcome test.",
            "semantic_scope": "Literal compiler-choice semantics checked; no independent natural-language validation or human answer observed.",
        })
    return result


def _brief(packet, compilation, constraints=True):
    return {"id": packet["public"]["id"], "candidates": compilation["candidates"],
            "questions": compilation["questions"], "target_decisions": packet["public"]["registry"]["decisions"],
            "allowed_withdrawals": packet["public"]["registry"]["evidence"],
            "documents": packet["source_context"]["documents"],
            "provenance_constraints": packet["source_context"]["provenance_constraints"] if constraints else []}


def _agreement(result, expected):
    states = {did: row["state"] for did, row in result["decision_states"].items()}
    answers = {did: value == "robust_supported" for did, value in states.items() if value != "needs_review"}
    correct = sum(value == expected[did] for did, value in answers.items())
    return {"states": states, "unanimous_labels": answers, "unanimous_correct": correct,
            "unanimous_wrong": len(answers) - correct, "disputed": len(states) - len(answers),
            "target_count": len(expected), "all_targets_correct_unanimous": correct == len(expected)}


def _relevance(compilation, vectors):
    """Change one assignment bit while holding all other declared bits fixed."""
    result = {}
    for question in compilation["questions"]:
        qid, groups = question["id"], {}
        for candidate in compilation["candidates"]:
            others = tuple(sorted((key, value) for key, value in candidate["assignment"].items() if key != qid))
            groups.setdefault(others, set()).add(tuple(sorted(vectors[candidate["id"]].items())))
        result[qid] = any(len(values) > 1 for values in groups.values())
    return result


def _clarify(packet, compilation, initial, withdrawals, expected, grounding, relevance):
    by_question = {row["id"]: row for row in grounding}
    result, answers, steps = initial, {}, []
    stop = "already_agreed"
    for _ in range(len(compilation["questions"]) + 1):
        question = result["next_question"]
        if question is None:
            stop = "decision_agreement" if result["consensus"]["clarification"]["possible"] else "unresolvable_with_declared_questions"
            break
        qid = question["id"]
        fact = by_question[qid]
        answer = fact["grounded_answer"]
        steps.append({"question_id": qid, "label": question["label"], "declared_cost": question["cost"],
                      "grounding_status": fact["grounding_status"], "answer": answer,
                      "initial_decision_relevance": relevance[qid], "candidates_before": result["candidate_ids"]})
        if answer is None:
            stop = "ungroundable_requested_question"
            break
        answers[qid] = answer
        try:
            result = analyze_stress(_brief(packet, compilation), {"scenario_withdrawals": withdrawals, "answers": answers})
        except ValueError as exc:
            if "contradict all supplied candidates" not in str(exc):
                raise
            return {"status": "candidate_set_exhausted", "steps": steps, "requested_count": len(steps),
                    "answered_count": len(answers), "retained_candidate_ids": [], "agreement": None,
                    "correct_resolution_after_requested_question": False}
        steps[-1]["candidates_after"] = result["candidate_ids"]
    else:
        raise AssertionError("Clarification did not terminate within the declared question bound")
    agreement = _agreement(result, expected)
    return {"status": stop, "steps": steps, "requested_count": len(steps), "answered_count": len(answers),
            "answered_declared_cost": sum(step["declared_cost"] for step in steps if step["answer"] is not None),
            "retained_candidate_ids": result["candidate_ids"], "agreement": agreement,
            "irrelevant_requested_question_count": sum(not step["initial_decision_relevance"] for step in steps),
            "correct_resolution_after_requested_question": bool(steps) and agreement["all_targets_correct_unanimous"],
            "note": "Only planner-requested questions with externally grounded structural answers prune this trajectory; no graph is inserted."}


def _stage(packet, compilation, withdrawals, grounding):
    expected = {did: row["usable"] for did, row in analyze(_actual(packet), withdrawals)["decisions"].items()}
    result = analyze_stress(_brief(packet, compilation), {"scenario_withdrawals": withdrawals})
    without = analyze_stress(_brief(packet, compilation, False), {"scenario_withdrawals": withdrawals})
    assert result["consensus"]["candidate_decision_vectors"] == without["consensus"]["candidate_decision_vectors"]
    relevance = _relevance(compilation, result["consensus"]["candidate_decision_vectors"])
    effective = copy.deepcopy(compilation["candidates"])
    for candidate in effective:
        for evidence in candidate["graph"]["evidence"]:
            evidence["active"] = result["revocation_flags"][evidence["id"]]["by_candidate"][candidate["id"]]["effective_active"]
    coverage = analyze_root_coverage(effective)
    grounded = {row["id"]: row["grounded_answer"] for row in grounding if row["grounded_answer"] is not None}
    forced = analyze_stress(_brief(packet, compilation), {"scenario_withdrawals": withdrawals, "answers": grounded})
    return {
        "withdrawals": list(withdrawals), "reference_labels_scoring_only": expected,
        "candidate_decision_vectors": result["consensus"]["candidate_decision_vectors"],
        "agreement": _agreement(result, expected),
        "minimum_distinguishing": {did: row["minimum_distinguishing"] for did, row in result["decision_witnesses"].items()},
        "question_relevance": relevance,
        "irrelevant_emitted_question_ids": [qid for qid, relevant in relevance.items() if not relevant],
        "planner_initial_worst_case_cost": result["consensus"]["clarification"]["worst_case_cost"],
        "clarification": _clarify(packet, compilation, result, withdrawals, expected, grounding, relevance),
        "forced_grounded_answer_diagnostic": {
            "applied_answers": grounded, "unanswered_question_ids": [row["id"] for row in grounding if row["grounded_answer"] is None],
            "retained_candidate_ids": forced["candidate_ids"], "agreement": _agreement(forced, expected),
            "note": "All available authored structural answers applied, including unrequested ones; this is not planner behavior or human verification."},
        "source_constraints": {"checks": result["provenance_checks"], "with_constraints": result["coverage"],
                               "without_constraints": without["coverage"]},
        "hypothetical_pair_vulnerability": coverage,
        "guard_interpretation": "Warnings describe hypothetical joint-root withdrawal vulnerability, not detection of an actual omitted ancestor.",
    }


def evaluate_compilation(packet, compilation):
    grounding = ground_questions(packet, compilation)
    return {"family": family_metrics(packet, compilation["candidates"]),
            "uncertainty_count": compilation["uncertainty_count"],
            "expected_candidate_count": compilation["expected_candidate_count"],
            "question_grounding": grounding,
            "current": _stage(packet, compilation, [], grounding),
            "challenge": _stage(packet, compilation, packet["hidden"]["challenge_withdrawals"], grounding)}


def _aggregate(rows, packets):
    admitted = [row for row in rows if row["status"] == "admitted"]
    scheduled_decisions = sum(len(packet["public"]["registry"]["decisions"]) for packet in packets)
    stages = {}
    for stage in ("current", "challenge"):
        views = [row["evaluation"][stage] for row in admitted]
        answered = sum(view["agreement"]["unanimous_correct"] + view["agreement"]["unanimous_wrong"] for view in views)
        wrong = sum(view["agreement"]["unanimous_wrong"] for view in views)
        requested = [view for view in views if view["clarification"]["requested_count"]]
        stages[stage] = {
            "scheduled_cases": len(rows), "cases_with_candidates": len(admitted),
            "cases_with_decision_disagreement": sum(view["agreement"]["disputed"] > 0 for view in views),
            "disputed_decisions": sum(view["agreement"]["disputed"] for view in views),
            "cases_with_wrong_unanimity": sum(view["agreement"]["unanimous_wrong"] > 0 for view in views),
            "cases_all_targets_correct_unanimous": sum(view["agreement"]["all_targets_correct_unanimous"] for view in views),
            "selective": {"scheduled_decisions": scheduled_decisions, "answered_decisions": answered,
                          "wrong_answered_decisions": wrong, "coverage": _rate(answered, scheduled_decisions),
                          "risk": _rate(wrong, answered),
                          "policy": "Answer only unanimous declared-graph decisions; source/guard warnings do not alter this diagnostic policy."},
            "planner_requested_case_count": len(requested),
            "correct_resolution_after_requested_case_count": sum(view["clarification"]["correct_resolution_after_requested_question"] for view in requested),
            "requested_question_count": sum(view["clarification"]["requested_count"] for view in views),
            "answered_question_count": sum(view["clarification"]["answered_count"] for view in views),
            "ungroundable_requested_case_count": sum(view["clarification"]["status"] == "ungroundable_requested_question" for view in views),
            "irrelevant_emitted_question_count": sum(len(view["irrelevant_emitted_question_ids"]) for view in views),
            "irrelevant_requested_question_count": sum(view["clarification"].get("irrelevant_requested_question_count", 0) for view in views),
            "source_constraint_conflict_cases": sum(view["source_constraints"]["with_constraints"]["status"] == "source_constraint_conflict" for view in views),
            "hypothetical_vulnerability_warning_cases": sum(view["hypothetical_pair_vulnerability"]["warning"] for view in views),
        }
    return {
        "scheduled": len(rows), "status_counts": dict(Counter(row["status"] for row in rows)),
        "received": sum(row["received"] for row in rows), "provider_completed": sum(row["provider_completed"] for row in rows),
        "admitted": len(admitted), "strict_bare_admitted": sum(row["strict_bare"] for row in admitted),
        "exact_family_recovery_cases": sum(row["evaluation"]["family"]["exact_family_recovery"] for row in admitted),
        "full_family_covered_cases": sum(row["evaluation"]["family"]["full_family_covered"] for row in admitted),
        "all_candidates_source_defensible_cases": sum(row["evaluation"]["family"]["all_candidates_source_defensible"] for row in admitted),
        "actual_graph_covered_cases": sum(row["evaluation"]["family"]["actual_graph_covered"] for row in admitted),
        "overgeneration_cases": sum(row["evaluation"]["family"]["overgeneration"] for row in admitted),
        "assignment_branches": sum(row["evaluation"]["family"]["candidate_count"] for row in admitted),
        "distinct_graphs_summed_within_cases": sum(row["evaluation"]["family"]["distinct_graph_count"] for row in admitted),
        "duplicate_assignment_branches": sum(row["evaluation"]["family"]["duplicate_assignment_branches"] for row in admitted),
        "outside_family_branches": sum(row["evaluation"]["family"]["outside_family_branches"] for row in admitted),
        "emitted_questions": sum(len(row["evaluation"]["question_grounding"]) for row in admitted),
        "groundable_questions": sum(q["grounding_status"] == "authored_structural_fact" for row in admitted for q in row["evaluation"]["question_grounding"]),
        "stages": stages,
    }


def _baseline_pairs(packets, rows, baseline):
    if baseline is None:
        return None
    prior = {row["case_id"]: row for row in baseline["observed_candidate_audits"]}
    by_case = {packet["public"]["id"]: packet for packet in packets}
    result = []
    for row in rows:
        cid, packet = row["case_id"], by_case[row["case_id"]]
        admitted = [{"id": item["condition"], "graph": item["graph"]} for item in baseline["outcomes"] if item["case_id"] == cid and item["valid"]]
        old = {}
        for name in ("earlier_sparse", "later_joint", "union"):
            candidates = admitted if name == "union" else [candidate for candidate in admitted if candidate["id"] == name]
            views = prior[cid]["union"] if name == "union" else prior[cid]["singleton_baselines"].get(name)
            old[name] = {"candidate_count": len(candidates), "family": family_metrics(packet, candidates),
                         "current": views["current"]["with_source_constraints"]["agreement"] if candidates else None,
                         "challenge": views["challenge"]["with_source_constraints"]["agreement"] if candidates else None}
        result.append({"case_id": cid, "post_hoc_primary_subset": cid in PRIMARY_SUBSET, "v4_status": row["status"],
                       "v4_family": row.get("evaluation", {}).get("family"),
                       "v4_current": row["evaluation"]["current"]["agreement"] if row["status"] == "admitted" else None,
                       "v4_challenge": row["evaluation"]["challenge"]["agreement"] if row["status"] == "admitted" else None,
                       "v3": old})
    return result


def score_responses(packets, responses, baseline_summary=None):
    """Score all ten scheduled cases, including failures and explicit abstention."""
    if len(packets) != 10 or len({p["public"]["id"] for p in packets}) != 10:
        raise ValueError("This paired diagnostic requires the ten distinct authored packets")
    known = {packet["public"]["id"] for packet in packets}
    seen = {}
    for response in responses:
        cid = response.get("case_id")
        if cid not in known or cid in seen or response.get("condition") != CONDITION or response.get("phase", "final") != "final":
            raise ValueError("Unknown, duplicate, wrong-condition or wrong-phase response")
        seen[cid] = response
    rows = []
    for packet in packets:
        cid = packet["public"]["id"]
        response = seen.get(cid)
        completed = response is not None and response.get("response_status") == "completed" and not response.get("error")
        row = {"case_id": cid, "received": response is not None, "provider_completed": completed,
               "strict_bare": False, "status": "unissued_or_missing"}
        if response is not None:
            text = response.get("output_text")
            row["raw_row_audit"] = {"request_number": response.get("request_number"), "response_status": response.get("response_status"),
                                    "error": response.get("error"), "output_text": text,
                                    "raw_response_sha256": hashlib.sha256(response["raw_response"].encode()).hexdigest() if isinstance(response.get("raw_response"), str) else None}
            if not completed:
                row.update(status="operational_failure", error=response.get("error") or "response_not_completed")
            elif isinstance(text, str) and text.strip() == ABSTENTION:
                row.update(status="explicit_abstention", error=None)
            else:
                try:
                    compilation = compile_ambiguity(text, packet["public"]["registry"])
                except (ValueError, TypeError) as exc:
                    row.update(status="syntax_or_branch_failure", error=str(exc), error_code=getattr(exc, "code", None))
                else:
                    row.update(status="admitted", strict_bare=compilation["strict_bare"], compilation=compilation,
                               evaluation=evaluate_compilation(packet, compilation))
        rows.append(row)
    primary_rows = [row for row in rows if row["case_id"] in PRIMARY_SUBSET]
    primary_packets = [packet for packet in packets if packet["public"]["id"] in PRIMARY_SUBSET]
    return {"schema": "retrace.ambiguity-v4-scores.v1", "scheduled": 10, "received": len(seen), "outcomes": rows,
            "aggregates": _aggregate(rows, packets),
            "post_hoc_primary_subset": {"case_ids": list(PRIMARY_SUBSET), "selected_after_v3_results": True,
                                         "aggregates": _aggregate(primary_rows, primary_packets)},
            "paired_v3_baselines": _baseline_pairs(packets, rows, baseline_summary),
            "probability_calibration": {"applicable": False, "ece": None, "brier": None,
                                        "reason": "No probabilities are emitted; assignment counts are not probabilities. Report selective risk and coverage instead."},
            "scope": [
                "Ten reused authored packets, not a new held-out sample; subset01/02/04 was selected after v3 findings.",
                "One v4 call plus exhaustive expansion is compared with two v3 directed calls; prompts, representation and call counts differ.",
                "All scheduled cases remain in denominators. Exact family soundness, coverage, actual coverage and decision correctness are distinct.",
                "Question grounding is an authored exact structural oracle diagnostic, never human verification; ungroundable answers retain uncertainty.",
                "Minimax costs are conditional on accurate available binary answers and declared integer costs. Unknown answers retain candidates; they are not a third adversarial branch in that planner.",
                "Current and challenge views reuse the same cases. Forced answer checks are separate from planner-requested clarification.",
                "Source-constraint conflicts concern supplied requirements; root-coverage warnings are hypothetical vulnerabilities, not actual omission detections. No independence attestations are automatically inferred from prose, and warning rates are not detection precision or recall.",
            ]}
