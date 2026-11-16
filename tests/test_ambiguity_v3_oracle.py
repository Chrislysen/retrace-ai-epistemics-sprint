"""Independent source reconstruction and finite-space oracle for staged v3.

Expected graphs below were hand reconstructed from all ten public packets.
Support evaluation uses synchronous fixed points, not RETRACE's evaluator or
truth-table compiler. These are authored-task controls, not model outcomes.
"""
import copy
import itertools
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from retrace.ambiguity_v3_eval import candidate_brief, evaluate_case, factual_answer, score_responses
from retrace.ambiguity_v3_sessions import CONDITIONS, build_sessions
from retrace.compact_graph import serialize_compact
from retrace.stress import analyze_stress


ROOT = Path(__file__).resolve().parents[1]


def packets():
    return json.loads((ROOT / "data" / "ambiguity-v3-staged.json").read_text(encoding="utf-8"))


def manual_graph(number, evidence_count, active, parents, claims, decisions):
    identifier = lambda suffix: f"R{number:02}{suffix:03}"
    return {
        "evidence": [{"id": identifier(n), "kind": "copy" if n in parents else "root",
                      "active": n in active, "parents": [identifier(p) for p in parents.get(n, [])]}
                     for n in range(1, evidence_count + 1)],
        "claims": [{"id": identifier(n), "supports": [[identifier(p) for p in clause] for clause in clauses]}
                   for n, clauses in claims.items()],
        "decisions": [{"id": identifier(n), "requires": [identifier(p) for p in refs]}
                      for n, refs in decisions.items()],
    }


def manual_interpretations(number):
    if number == 1:
        return [manual_graph(1, 3, {1, 2}, {}, {4: routes}, {5: [4]})
                for routes in ([[1, 3], [2, 3]], [[1], [2, 3]])]
    if number == 2:
        return [manual_graph(2, 2, {2}, parents, {3: [[2]]}, {4: [3]})
                for parents in ({}, {2: [1]})]
    if number == 3:
        return [manual_graph(3, 3, {2, 3}, {3: [parent]}, {4: [[3]]}, {5: [4]}) for parent in (1, 2)]
    if number == 4:
        return [manual_graph(4, 2, {2}, {}, {3: [[1]], 4: [[2]], 5: [[selected]]}, {6: [5]})
                for selected in (3, 4)]
    if number == 5:
        return [manual_graph(5, 3, {2, 3}, {}, {4: [[selected]], 5: [[3]]}, {6: [5]})
                for selected in (1, 2)]
    if number == 6:
        return [manual_graph(6, 4, {1, 2, 3, 4}, {}, {5: [[p] for p in routes]}, {6: [5]})
                for routes in ([1, 2, 3], [1, 2, 3, 4])]
    if number == 7:
        return [manual_graph(7, 4, {2, 3, 4}, {2: [1], 3: [2], 4: [2]}, {5: [[3], [4]]}, {6: [5]})]
    if number == 8:
        return [manual_graph(8, 5, {2, 3, 4, 5}, {4: [1, 2], 5: [1, 3]}, {6: [[4], [5]]}, {7: [6]})]
    if number == 9:
        return [manual_graph(9, 4, {1, 2, 3, 4}, {2: [1], 3: [1]},
                             {5: [[2], [3]], 6: [[2], [3], [4]]}, {7: [5], 8: [6]})]
    if number == 10:
        return [manual_graph(10, 5, {1, 2, 3, 4, 5}, {2: [1], 3: [1], 5: [4]},
                             {6: [[2], [5]]}, {7: [6]})]
    raise AssertionError(number)


def canonical(graph):
    return {
        "evidence": sorted((r["id"], r["kind"], r["active"], tuple(sorted(r["parents"]))) for r in graph["evidence"]),
        "claims": sorted((r["id"], tuple(sorted(tuple(sorted(clause)) for clause in r["supports"]))) for r in graph["claims"]),
        "decisions": sorted((r["id"], tuple(sorted(r["requires"]))) for r in graph["decisions"]),
    }


def fixed_point(graph, vetoes=()):
    vetoes = set(vetoes)
    values = {row["id"]: False for category in ("evidence", "claims", "decisions") for row in graph[category]}
    for _ in range(len(values) + 1):
        update = {}
        for evidence in graph["evidence"]:
            update[evidence["id"]] = evidence["active"] and evidence["id"] not in vetoes and (
                evidence["kind"] == "root" or all(values[parent] for parent in evidence["parents"]))
        for claim in graph["claims"]:
            update[claim["id"]] = any(all(values[ref] for ref in clause) for clause in claim["supports"])
        for decision in graph["decisions"]:
            update[decision["id"]] = all(values[ref] for ref in decision["requires"])
        if update == values:
            return {decision["id"]: update[decision["id"]] for decision in graph["decisions"]}
        values = update
    raise AssertionError("Independent fixed point failed to converge")


def source_fact(graph, predicate):
    rows = {row["id"]: row for category in ("evidence", "claims", "decisions") for row in graph[category]}
    kind = predicate["kind"]
    if kind == "direct_parent":
        return predicate["parent"] in rows[predicate["child"]]["parents"]
    if kind == "all_routes_contain":
        clauses = rows[predicate["claim"]]["supports"]
        return bool(clauses) and all(predicate["item"] in clause for clause in clauses)
    if kind == "exact_route":
        return any(set(route) == set(predicate["items"]) for route in rows[predicate["claim"]]["supports"])
    if kind == "ancestor":
        dependencies = {r["id"]: r["parents"] for r in graph["evidence"]}
        dependencies.update({r["id"]: [p for route in r["supports"] for p in route] for r in graph["claims"]})
        dependencies.update({r["id"]: r["requires"] for r in graph["decisions"]})
        reached, pending = set(), list(dependencies[predicate["child"]])
        while pending:
            current = pending.pop()
            if current == predicate["ancestor"]:
                return True
            if current not in reached:
                reached.add(current)
                pending.extend(dependencies[current])
        return False
    raise AssertionError(kind)


def brief_for(packet, graphs, constraints=True):
    candidates = [{"id": f"manual-{index}", "graph": graph} for index, graph in enumerate(graphs)]
    oracle = packet["hidden"]["author_clarification_oracle"]
    return {"id": packet["public"]["id"], "candidates": candidates,
            "questions": [{"id": oracle["question_id"], "label": oracle["question"], "cost": oracle["cost"],
                           "answers": {row["id"]: source_fact(row["graph"], oracle["factual_predicate"]) for row in candidates}}],
            "documents": packet["source_context"]["documents"],
            "provenance_constraints": packet["source_context"]["provenance_constraints"] if constraints else []}


class AmbiguityV3OracleTests(unittest.TestCase):
    def test_all_ten_gold_sets_match_independent_public_source_reconstruction(self):
        data = packets()
        self.assertEqual(len(data), 10)
        for number, packet in enumerate(data, 1):
            with self.subTest(number=number):
                expected = [canonical(graph) for graph in manual_interpretations(number)]
                actual = [canonical(graph) for graph in packet["hidden"]["allowed_interpretations"]]
                self.assertEqual(actual, expected)
                for graph in manual_interpretations(number):
                    self.assertEqual({category: [row["id"] for row in graph[category]] for category in graph},
                                     packet["public"]["registry"])

    def test_all_source_factual_answers_match_author_selected_graph_without_support_queries(self):
        expected_indices = [1, 1, 1, 0, 0, 1, 0, 0, 0, 0]
        for number, (packet, expected_index) in enumerate(zip(packets(), expected_indices), 1):
            oracle = packet["hidden"]["author_clarification_oracle"]
            self.assertEqual(packet["hidden"]["author_actual_interpretation_index"], expected_index)
            graphs = manual_interpretations(number)
            self.assertEqual(source_fact(graphs[expected_index], oracle["factual_predicate"]), oracle["actual_answer"])
            # Changing every eligibility flag may alter support, never the
            # declared factual relationship to which this oracle refers.
            for graph in graphs:
                flipped = copy.deepcopy(graph)
                for evidence in flipped["evidence"]:
                    evidence["active"] = not evidence["active"]
                self.assertEqual(source_fact(flipped, oracle["factual_predicate"]),
                                 source_fact(graph, oracle["factual_predicate"]))

    def test_every_withdrawal_subset_and_exact_minimal_witness_against_fixed_point(self):
        for number, packet in enumerate(packets(), 1):
            graphs = manual_interpretations(number)
            brief = brief_for(packet, graphs)
            variables = sorted(packet["public"]["registry"]["evidence"])
            subsets = [list(subset) for size in range(len(variables) + 1)
                       for subset in itertools.combinations(variables, size)]
            for fixed in ([], packet["hidden"]["challenge_withdrawals"]):
                result = analyze_stress(brief, {"scenario_withdrawals": fixed})
                outcomes = {tuple(subset): [fixed_point(graph, set(fixed) | set(subset)) for graph in graphs]
                            for subset in subsets}
                for did in packet["public"]["registry"]["decisions"]:
                    baseline = [item[did] for item in outcomes[()]]
                    row = result["decision_witnesses"][did]
                    self.assertEqual(list(row["current_outcomes"].values()), baseline)
                    conditions = {
                        "minimum_distinguishing": lambda vector: len(set(vector)) > 1,
                        "minimum_break_any": lambda vector: all(baseline) and not all(vector),
                        "minimum_break_all": lambda vector: all(baseline) and not any(vector),
                    }
                    for field, condition in conditions.items():
                        expected = next((subset for subset in subsets
                                         if condition([item[did] for item in outcomes[tuple(subset)]])), None)
                        actual = row[field]
                        if expected is None:
                            self.assertIsNone(actual, (number, fixed, did, field))
                        else:
                            self.assertEqual(actual["withdraw"], expected, (number, fixed, did, field))
                            self.assertEqual(actual["k"], len(expected))
                            self.assertEqual(list(actual["outcomes"].values()),
                                             [item[did] for item in outcomes[tuple(expected)]])

    def test_irrelevant_ambiguity_stops_and_latent_third_order_case_needs_scenario(self):
        irrelevant = packets()[4]
        result = analyze_stress(brief_for(irrelevant, manual_interpretations(5)))
        self.assertIsNone(result["next_question"])
        self.assertEqual(result["consensus"]["clarification"]["worst_case_cost"], 0)
        self.assertIsNone(result["decision_witnesses"]["R05006"]["minimum_distinguishing"])
        latent = packets()[5]
        brief = brief_for(latent, manual_interpretations(6))
        before = analyze_stress(brief)
        self.assertIsNone(before["next_question"])
        self.assertEqual(before["decision_witnesses"]["R06006"]["minimum_distinguishing"]["withdraw"],
                         ["R06001", "R06002", "R06003"])
        after = analyze_stress(brief, {"scenario_withdrawals": latent["hidden"]["challenge_withdrawals"]})
        self.assertEqual(after["next_question"]["id"], "clarify-1")
        self.assertEqual(after["next_question"]["worst_case_cost"], 1)

    def test_complete_source_graphs_are_constraint_negative_controls(self):
        for number, packet in enumerate(packets(), 1):
            source_text = "\n".join(document["text"] for document in packet["public"]["documents"])
            for constraint in packet["source_context"]["provenance_constraints"]:
                self.assertIn(constraint["source_quote"], source_text)
            result = analyze_stress(brief_for(packet, manual_interpretations(number)))
            self.assertEqual(result["coverage"]["retained_constraint_violations_count"], 0)
            expected_status = "unknown_no_constraints" if number <= 6 else "no_supplied_constraint_conflict"
            self.assertEqual(result["coverage"]["status"], expected_status)

    def test_constructed_shared_omissions_are_flagged_without_becoming_observed_candidates(self):
        for number, packet in enumerate(packets(), 1):
            mutant = packet["hidden"]["constructed_common_omission_graph"]
            if mutant is None:
                self.assertLessEqual(number, 6)
                continue
            self.assertGreaterEqual(number, 7)
            self.assertEqual(len(packet["hidden"]["allowed_interpretations"]), 1)
            self.assertNotEqual(canonical(mutant), canonical(manual_interpretations(number)[0]))
            with_constraints = analyze_stress(brief_for(packet, [mutant, copy.deepcopy(mutant)]))
            without_constraints = analyze_stress(brief_for(packet, [mutant, copy.deepcopy(mutant)], constraints=False))
            self.assertEqual(with_constraints["coverage"]["status"], "source_constraint_conflict")
            self.assertEqual(with_constraints["coverage"]["retained_constraint_violations_count"], 4)
            self.assertEqual(with_constraints["consensus"]["candidate_decision_vectors"],
                             without_constraints["consensus"]["candidate_decision_vectors"])
            self.assertEqual(with_constraints["candidate_ids"], ["manual-0", "manual-1"])
            self.assertTrue(without_constraints["interventions"]["all_decisions_equivalent_within_scope"])

    def test_document_groups_preserve_independent_route_and_veto_precedence(self):
        packet = packets()[8]
        brief = brief_for(packet, manual_interpretations(9))
        result = analyze_stress(brief, {"revoked_documents": ["SOURCE-A"]})
        self.assertEqual(result["decision_states"]["R09007"]["classification"], "revoked")
        self.assertEqual(result["decision_states"]["R09008"]["classification"], "supported")
        self.assertFalse(result["revocation_flags"]["R09002"]["passage_veto"])
        self.assertFalse(result["revocation_flags"]["R09002"]["by_candidate"]["manual-0"]["effective_active"])
        packet = packets()[9]
        result = analyze_stress(brief_for(packet, manual_interpretations(10)), {"revoked_documents": ["first-note"]})
        self.assertEqual(result["decision_states"]["R10007"]["classification"], "supported")
        self.assertFalse(result["revocation_flags"]["R10004"]["document_veto"])
        self.assertFalse(result["revocation_flags"]["R10005"]["document_veto"])

    def test_factual_projection_matches_independent_ast_check_and_rejects_vacuous_route_truth(self):
        for number, packet in enumerate(packets(), 1):
            predicate = packet["hidden"]["author_clarification_oracle"]["factual_predicate"]
            for graph in manual_interpretations(number):
                self.assertEqual(factual_answer(graph, predicate), source_fact(graph, predicate))
        empty = manual_interpretations(1)[0]
        empty["claims"][0]["supports"] = []
        predicate = packets()[0]["hidden"]["author_clarification_oracle"]["factual_predicate"]
        self.assertFalse(factual_answer(empty, predicate))

    def test_public_sessions_cannot_change_when_hidden_gold_or_constraints_change(self):
        original = packets()
        edited = copy.deepcopy(original)
        for packet in edited:
            packet["hidden"] = {"adversarial_gold_marker": "PRIVATE GOLD MUST NEVER ENTER A REQUEST"}
            packet["source_context"] = {"unexpected": "PRIVATE SOURCE-CONTEXT METADATA"}
        self.assertEqual(build_sessions(original), build_sessions(edited))
        sessions = build_sessions(original)
        self.assertEqual(len(sessions), 20)
        self.assertEqual({session["condition"] for session in sessions}, set(CONDITIONS))
        for session in sessions:
            body = json.loads(session["steps"][0]["input"])
            self.assertEqual(set(body), {"id", "title", "documents", "registry"})

    def test_missing_invalid_and_operational_slots_remain_in_all_scheduled_denominator(self):
        data = packets()
        completed = lambda number, condition, text: {
            "case_id": f"ambiguity-v3-{number:02}", "condition": condition,
            "phase": "final", "response_status": "completed", "output_text": text, "error": None}
        responses = [completed(1, CONDITIONS[0], serialize_compact(manual_interpretations(1)[1])),
                     completed(1, CONDITIONS[1], "A plausible-looking sentence is not a graph."),
                     {**completed(2, CONDITIONS[0], serialize_compact(manual_interpretations(2)[1])), "error": "timeout"},
                     completed(3, CONDITIONS[0], "```text\n" + serialize_compact(manual_interpretations(3)[1]) + "\n```")]
        result = score_responses(data, responses)
        self.assertEqual(result["scheduled"], 20)
        self.assertEqual(result["received"], 4)
        self.assertEqual(len(result["outcomes"]), 20)
        self.assertEqual(sum(row["valid"] for row in result["outcomes"]), 2)
        self.assertEqual(sum(row["strict_valid"] for row in result["outcomes"]), 1)
        statuses = [row["status"] for row in result["outcomes"]]
        self.assertEqual(statuses.count("operational_failure"), 1)
        self.assertEqual(statuses.count("schema_invalid"), 1)
        self.assertEqual(statuses.count("unissued_or_missing"), 16)
        self.assertEqual([result["groups"][condition]["scheduled"] for condition in CONDITIONS], [10, 10])
        self.assertEqual(len(result["observed_candidate_audits"]), 10)
        self.assertEqual(result["observed_candidate_audits"][1]["union"]["current"]["status"], "no_admitted_candidates")

    def test_admitted_wrong_family_graph_remains_and_unanimity_is_not_called_correct(self):
        data = packets()
        wrong = manual_interpretations(2)[1]
        wrong["evidence"][0]["active"] = True  # A factual lineage answer alone cannot repair this flag.
        response = {"case_id": "ambiguity-v3-02", "condition": CONDITIONS[0], "phase": "final",
                    "response_status": "completed", "error": None, "output_text": serialize_compact(wrong)}
        scored = score_responses(data, [response])
        admitted = next(row for row in scored["outcomes"] if row["received"])
        self.assertTrue(admitted["valid"])
        self.assertFalse(admitted["allowed_interpretation"])
        self.assertFalse(admitted["oracle_graph_exact"])
        current = scored["observed_candidate_audits"][1]["union"]["current"]
        self.assertEqual(current["candidate_count"], 1)
        self.assertEqual(current["with_source_constraints"]["agreement"]["unanimous_wrong"], 1)
        self.assertIsNone(current["with_source_constraints"]["next_question"])
        followup = current["oracle_answer_check"]
        self.assertFalse(followup["was_question_requested"])
        self.assertEqual(followup["status"], "retained_candidates")
        self.assertEqual(followup["agreement"]["unanimous_wrong"], 1)
        self.assertEqual(followup["agreement"]["unanimous_correct"], 0)
        self.assertFalse(followup["oracle_graph_covered"])

    def test_missing_actual_interpretation_exhausts_instead_of_inserting_gold(self):
        packet = packets()[1]
        predicted = [{"id": "only-model-output", "graph": manual_interpretations(2)[0]}]
        result = evaluate_case(packet, predicted)["union"]["current"]
        self.assertFalse(result["oracle_graph_covered"])
        self.assertEqual(result["oracle_answer_check"]["status"], "candidate_set_exhausted")
        self.assertEqual(result["oracle_answer_check"]["retained_ids"], [])
        self.assertFalse(result["oracle_answer_check"]["was_question_requested"])

    def test_detector_inputs_contain_only_passed_candidates_not_author_actual_graph(self):
        packet = packets()[1]
        candidates = [{"id": "observed-output", "graph": manual_interpretations(2)[0]}]
        seen = []

        def spy(brief, state=None):
            seen.append(copy.deepcopy(brief["candidates"]))
            return analyze_stress(brief, state)

        with patch("retrace.ambiguity_v3_eval.analyze_stress", side_effect=spy):
            evaluate_case(packet, candidates)
        self.assertTrue(seen)
        self.assertTrue(all(rows == candidates for rows in seen))
        before = candidate_brief(packet, candidates)
        poisoned = copy.deepcopy(packet)
        poisoned["hidden"]["allowed_interpretations"] = []
        poisoned["hidden"]["author_actual_interpretation_index"] = 999
        poisoned["hidden"]["author_clarification_oracle"]["actual_answer"] = False
        self.assertEqual(candidate_brief(poisoned, candidates), before)

    def test_duplicate_unknown_or_wrong_phase_journal_records_reject(self):
        response = {"case_id": "ambiguity-v3-01", "condition": CONDITIONS[0], "phase": "final", "error": "timeout"}
        for rows in ([response, copy.deepcopy(response)], [{**response, "case_id": "unexpected"}],
                     [{**response, "phase": "history"}]):
            with self.assertRaises(ValueError):
                score_responses(packets(), rows)

    def test_aggregate_resolution_counts_requested_correct_targets_only(self):
        # These journal rows are constructed unit-test fixtures, not observations.
        data = packets()
        responses = []
        for number in range(1, 11):
            graphs = manual_interpretations(number)
            for index, condition in enumerate(CONDITIONS):
                responses.append({"case_id": f"ambiguity-v3-{number:02}", "condition": condition,
                                  "phase": "final", "response_status": "completed", "error": None,
                                  "output_text": serialize_compact(graphs[min(index, len(graphs) - 1)])})
        aggregates = score_responses(data, responses)["aggregates"]
        self.assertEqual(aggregates["both_admitted_cases"], 10)
        self.assertEqual(aggregates["both_admitted_graph_disagreement_cases"], 6)
        current, challenge = (aggregates["union"][key] for key in ("current", "challenge"))
        self.assertEqual(current["case_denominator"], 10)
        self.assertEqual(current["planner_requested_question_cases"], 4)
        self.assertEqual(current["correct_full_target_resolution_after_requested_question"], 4)
        self.assertEqual(current["forced_unrequested_oracle_checks"], 6)
        self.assertEqual(challenge["planner_requested_question_cases"], 5)
        self.assertEqual(challenge["correct_full_target_resolution_after_requested_question"], 5)
        omission = aggregates["observed_shared_omission"]
        self.assertEqual(omission["both_admitted_source_cases"], 4)
        self.assertEqual(omission["common_omission_cases"], 0)
        self.assertIsNone(omission["with_source_constraint_detection_rate"])
        self.assertIsNone(omission["without_source_constraint_detection_rate"])

    def test_requested_answer_that_retains_wrong_unanimity_is_not_a_resolution(self):
        yes_but_wrong = manual_interpretations(2)[1]
        yes_but_wrong["evidence"][0]["active"] = True
        no_and_wrong = manual_interpretations(2)[0]
        no_and_wrong["evidence"][1]["active"] = False
        responses = [{"case_id": "ambiguity-v3-02", "condition": condition, "phase": "final", "error": None,
                      "response_status": "completed", "output_text": serialize_compact(graph)}
                     for condition, graph in zip(CONDITIONS, [yes_but_wrong, no_and_wrong])]
        result = score_responses(packets(), responses)
        aggregate = result["aggregates"]["union"]["current"]
        self.assertEqual(aggregate["planner_requested_question_cases"], 1)
        self.assertEqual(aggregate["correct_full_target_resolution_after_requested_question"], 0)
        self.assertEqual(aggregate["resolution_rate_among_requested"], 0)
        followup = result["observed_candidate_audits"][1]["union"]["current"]["oracle_answer_check"]
        self.assertTrue(followup["was_question_requested"])
        self.assertEqual(followup["agreement"]["unanimous_wrong"], 1)

    def test_shared_omission_requires_same_constraint_not_merely_two_defective_graphs(self):
        data = packets()
        graphs = [manual_interpretations(7)[0], manual_interpretations(7)[0]]
        for graph, evidence_index in zip(graphs, [2, 3]):
            graph["evidence"][evidence_index].update(kind="root", parents=[])
        responses = [{"case_id": "ambiguity-v3-07", "condition": condition, "phase": "final", "error": None,
                      "response_status": "completed", "output_text": serialize_compact(graph)}
                     for condition, graph in zip(CONDITIONS, graphs)]
        result = score_responses(data, responses)
        aggregate = result["aggregates"]["observed_shared_omission"]
        self.assertEqual(aggregate["both_admitted_source_cases"], 1)
        self.assertEqual(aggregate["common_omission_cases"], 0)
        self.assertIsNone(aggregate["with_source_constraint_detection_rate"])
        self.assertTrue(aggregate["details"][0]["current_wrong_unanimity"])
        mutant = data[6]["hidden"]["constructed_common_omission_graph"]
        for row in responses:
            row["output_text"] = serialize_compact(mutant)
        aggregate = score_responses(data, responses)["aggregates"]["observed_shared_omission"]
        self.assertEqual(aggregate["common_omission_cases"], 1)
        self.assertEqual(aggregate["with_source_constraint_detected_cases"], 1)
        self.assertEqual(aggregate["without_source_constraint_detected_cases"], 0)
        self.assertEqual(aggregate["with_source_constraint_detection_rate"], 1)

    def test_incomplete_provider_response_cannot_be_admitted_even_if_graph_looks_complete(self):
        response = {"case_id": "ambiguity-v3-01", "condition": CONDITIONS[0], "phase": "final", "error": None,
                    "response_status": "incomplete", "output_text": serialize_compact(manual_interpretations(1)[1])}
        result = score_responses(packets(), [response])
        received = next(row for row in result["outcomes"] if row["received"])
        self.assertEqual(received["status"], "operational_failure")
        self.assertFalse(received["valid"])
        self.assertEqual(result["aggregates"]["union"]["current"]["cases_with_candidates"], 0)


if __name__ == "__main__":
    unittest.main()
