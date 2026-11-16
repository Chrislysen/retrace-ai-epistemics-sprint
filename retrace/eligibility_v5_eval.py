"""Prospective eight-case eligibility-pair scoring; no provider calls or repairs."""
from __future__ import annotations

import copy
import hashlib
from collections import Counter

from .ambiguity_v4_eval import evaluate_compilation
from .ambiguity_v4_sessions import ABSTENTION
from .compact_graph import serialize_compact
from .compact_v5 import compile_ambiguity

CONDITION = "node_local_v5"


def _rate(n, d):
    return n / d if d else None


def _normalized_form(graph, designated=None, all_activity=False):
    graph = copy.deepcopy(graph)
    for evidence in graph["evidence"]:
        if all_activity or evidence["id"] == designated:
            evidence["active"] = True
    return serialize_compact(graph)


def _eligibility(graph):
    return {row["id"]: row["active"] for row in graph["evidence"]}


def _packet_view(packet):
    result = copy.deepcopy(packet)
    result.setdefault("source_context", {"documents": [], "provenance_constraints": []})
    result["hidden"].setdefault("challenge_withdrawals", [])
    return result


def _validate_packets(packets):
    if (not isinstance(packets, list) or len(packets) != 8
            or len({row["id"] for row in packets}) != 8):
        raise ValueError("Exactly eight distinct scheduled packets are required")
    pairs = {}
    for packet in packets:
        pairs.setdefault(packet["pair_id"], []).append(packet)
    if len(pairs) != 4 or any(len(rows) != 2 for rows in pairs.values()):
        raise ValueError("Exactly four complete authored pairs are required")
    for pair in pairs.values():
        changed = {row["hidden"]["changed_evidence_id"] for row in pair}
        flags = {row["hidden"]["changed_local_active"] for row in pair}
        if len(changed) != 1 or flags != {False, True}:
            raise ValueError("Paired packets must name the same single changed bit and opposite conditions")
    return pairs


def evaluate_packet(packet, compilation):
    evaluated = evaluate_compilation(_packet_view(packet), compilation)
    # Frozen v4's empty challenge equals current. It is not a new intervention
    # and must not be exposed or counted as a second paired observation.
    evaluated.pop("challenge")
    evaluated["challenge_evaluated"] = False
    expected = _eligibility(packet["hidden"]["allowed_interpretations"][0])
    mismatches = {}
    for candidate in compilation["candidates"]:
        actual = _eligibility(candidate["graph"])
        mismatches[candidate["id"]] = [identifier for identifier in sorted(expected) if actual[identifier] != expected[identifier]]
    evaluated["eligibility"] = {
        "expected_flags_scoring_only": expected,
        "all_branches_faithful": all(not ids for ids in mismatches.values()),
        "mismatched_ids_by_candidate": mismatches,
        "designated_evidence_id": packet["hidden"]["changed_evidence_id"],
        "designated_expected_active": packet["hidden"]["changed_local_active"],
    }
    return evaluated


def _pair_rows(packets, outcomes):
    indexed = {row["case_id"]: row for row in outcomes}
    result = []
    for pair_id, members in sorted(_validate_packets(packets).items()):
        members = sorted(members, key=lambda packet: packet["hidden"]["changed_local_active"])
        rows = [indexed[packet["id"]] for packet in members]
        changed = members[0]["hidden"]["changed_evidence_id"]
        both = all(row["status"] == "admitted" for row in rows)
        record = {"pair_id": pair_id, "case_ids_ineligible_then_eligible": [packet["id"] for packet in members],
                  "changed_evidence_id": changed, "both_admitted": both,
                  "specification_sets_invariant": None, "topology_sets_invariant": None,
                  "both_source_exact": False, "both_eligibility_faithful": False,
                  "invariant_and_source_exact": False}
        if both:
            graphs = [[candidate["graph"] for candidate in row["compilation"]["candidates"]] for row in rows]
            normalized = [{_normalized_form(graph, changed) for graph in group} for group in graphs]
            topologies = [{_normalized_form(graph, all_activity=True) for graph in group} for group in graphs]
            exact = all(row["evaluation"]["family"]["exact_family_recovery"] for row in rows)
            record.update(specification_sets_invariant=normalized[0] == normalized[1],
                          topology_sets_invariant=topologies[0] == topologies[1], both_source_exact=exact,
                          both_eligibility_faithful=all(row["evaluation"]["eligibility"]["all_branches_faithful"] for row in rows),
                          invariant_and_source_exact=exact and normalized[0] == normalized[1],
                          assignment_counts=[len(group) for group in graphs],
                          distinct_specification_counts=[len(group) for group in normalized],
                          ineligible_only_normalized_specification_count=len(normalized[0] - normalized[1]),
                          eligible_only_normalized_specification_count=len(normalized[1] - normalized[0]))
        result.append(record)
    return result


def score_responses(packets, responses):
    _validate_packets(packets)
    known = {row["id"] for row in packets}
    seen = {}
    for response in responses:
        cid = response.get("case_id")
        if cid not in known or cid in seen or response.get("condition") != CONDITION or response.get("phase", "final") != "final":
            raise ValueError("Unknown, duplicate, wrong-condition or wrong-phase response")
        seen[cid] = response
    outcomes = []
    for packet in packets:
        response = seen.get(packet["id"])
        completed = response is not None and response.get("response_status") == "completed" and not response.get("error")
        row = {"case_id": packet["id"], "pair_id": packet["pair_id"], "eligibility_condition": packet["eligibility_condition"],
               "received": response is not None, "provider_completed": completed, "strict_bare": False,
               "status": "unissued_or_missing"}
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
                    compiled = compile_ambiguity(text, packet["public"]["registry"])
                except (ValueError, TypeError) as exc:
                    row.update(status="syntax_or_branch_failure", error=str(exc), error_code=getattr(exc, "code", None))
                else:
                    row.update(status="admitted", strict_bare=compiled["strict_bare"], compilation=compiled,
                               evaluation=evaluate_packet(packet, compiled))
        outcomes.append(row)
    pairs = _pair_rows(packets, outcomes)
    admitted = [row for row in outcomes if row["status"] == "admitted"]
    current = [row["evaluation"]["current"] for row in admitted]
    decisions = sum(len(packet["public"]["registry"]["decisions"]) for packet in packets)
    answered = sum(view["agreement"]["unanimous_correct"] + view["agreement"]["unanimous_wrong"] for view in current)
    wrong = sum(view["agreement"]["unanimous_wrong"] for view in current)
    both = sum(row["both_admitted"] for row in pairs)
    invariant = sum(row["specification_sets_invariant"] is True for row in pairs)
    aggregate = {
        "scheduled_cases": 8, "scheduled_pairs": 4, "received": len(seen),
        "provider_completed": sum(row["provider_completed"] for row in outcomes),
        "status_counts": dict(Counter(row["status"] for row in outcomes)), "admitted": len(admitted),
        "strict_bare_admitted": sum(row["strict_bare"] for row in admitted),
        "exact_family_recovery_cases": sum(row["evaluation"]["family"]["exact_family_recovery"] for row in admitted),
        "actual_graph_covered_cases": sum(row["evaluation"]["family"]["actual_graph_covered"] for row in admitted),
        "overgeneration_cases": sum(row["evaluation"]["family"]["overgeneration"] for row in admitted),
        "eligibility_faithful_cases": sum(row["evaluation"]["eligibility"]["all_branches_faithful"] for row in admitted),
        "assignment_branches": sum(row["evaluation"]["family"]["candidate_count"] for row in admitted),
        "distinct_graphs_summed_within_cases": sum(row["evaluation"]["family"]["distinct_graph_count"] for row in admitted),
        "both_admitted_pairs": both, "specification_invariant_pairs": invariant,
        "topology_only_invariant_pairs": sum(row["topology_sets_invariant"] is True for row in pairs),
        "both_source_exact_pairs": sum(row["both_source_exact"] for row in pairs),
        "invariant_and_source_exact_pairs": sum(row["invariant_and_source_exact"] for row in pairs),
        "invariance_rate_all_scheduled_pairs": invariant / 4,
        "invariance_rate_among_both_admitted": _rate(invariant, both),
        "cases_with_current_disagreement": sum(view["agreement"]["disputed"] > 0 for view in current),
        "cases_with_wrong_current_unanimity": sum(view["agreement"]["unanimous_wrong"] > 0 for view in current),
        "planner_requested_case_count": sum(view["clarification"]["requested_count"] > 0 for view in current),
        "correct_resolution_after_requested_case_count": sum(view["clarification"]["correct_resolution_after_requested_question"] for view in current),
        "selective": {"scheduled_decisions": decisions, "answered_decisions": answered, "wrong_answered_decisions": wrong,
                      "coverage": _rate(answered, decisions), "risk": _rate(wrong, answered)},
    }
    return {"schema": "retrace.eligibility-v5-paired-scores.v1", "scheduled": 8, "outcomes": outcomes,
            "pairs": pairs, "aggregates": aggregate,
            "scope": [
                "Eight prospective targeted authored packets and four pairs, not natural or population-independent observations.",
                "Primary invariance normalizes only the designated eligibility bit. Topology-only invariance separately normalizes all activity flags.",
                "A consistently wrong pair may be invariant. Both source-exact recovery and eligibility fidelity are separately required for semantic success.",
                "All eight cases and four pairs remain in denominators, including absence, abstention and failures. No gold graph is inserted.",
                "No new challenge scenario is evaluated; repeated empty-challenge results from the reused evaluator are omitted.",
                "Clarification uses only uniquely grounded authored structural facts, not observed human answers. Unknown answers retain candidates.",
                "Guard warnings are hypothetical root-withdrawal vulnerabilities, not empirical omission detection. Branch counts are not probabilities; ECE/Brier are inapplicable.",
            ]}
