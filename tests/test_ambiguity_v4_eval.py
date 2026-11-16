"""Authored fixtures only: implemented before any live v4 output is read."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retrace.ambiguity_v4_eval import evaluate_compilation, family_metrics, ground_questions, score_responses
from retrace.ambiguity_v4_sessions import ABSTENTION, CONDITION
from retrace.compact_graph import serialize_compact
from retrace.compact_v4 import compile_ambiguity

ROOT = Path(__file__).resolve().parents[1]


def packets():
    return json.loads((ROOT / "data/ambiguity-v3-staged.json").read_text(encoding="utf-8"))


def authored_text(number):
    packet = packets()[number - 1]
    base = serialize_compact(packet["hidden"]["allowed_interpretations"][0])
    operators = {
        1: ("C R01004", "C R01004 ?", "AMBIGUOUS_QUALIFIER(R01004: R01001, R01002, R01003)"),
        2: ("E R02002", "E R02002 ? 1 -", "UNVERIFIED_INDEPENDENCE(R02002, R02001)"),
        3: ("E R03003", "E R03003 ? 1 -", "UNSPECIFIED_CHOICE(R03003: R03001, R03002)"),
        4: ("C R04005", "C R04005 ?", "UNSPECIFIED_CHOICE(R04005: R04003, R04004)"),
        5: ("C R05004", "C R05004 ?", "UNSPECIFIED_CHOICE(R05004: R05001, R05002)"),
        6: ("C R06005", "C R06005 ?", "OPTIONAL_ROUTE(R06005: R06001, R06002, R06003; R06004)"),
    }
    if number not in operators:
        return base
    prefix, declaration, operator = operators[number]
    lines = [declaration if line.startswith(prefix + " ") else line for line in base.splitlines()[:-1]]
    return "\n".join(lines + [operator, "END"])


def response(number, text=None, **overrides):
    return {"case_id": f"ambiguity-v3-{number:02}", "condition": CONDITION, "phase": "final",
            "response_status": "completed", "output_text": authored_text(number) if text is None else text,
            "error": None, **overrides}


class AmbiguityV4EvaluationTests(unittest.TestCase):
    def test_all_authored_families_recovered_without_live_outputs(self):
        scored = score_responses(packets(), [response(number) for number in range(1, 11)])
        aggregate = scored["aggregates"]
        self.assertEqual(aggregate["admitted"], 10)
        self.assertEqual(aggregate["exact_family_recovery_cases"], 10)
        self.assertEqual(aggregate["assignment_branches"], 16)
        self.assertEqual(aggregate["distinct_graphs_summed_within_cases"], 16)
        self.assertEqual(aggregate["overgeneration_cases"], 0)
        self.assertEqual(aggregate["stages"]["current"]["cases_with_decision_disagreement"], 4)
        self.assertEqual(aggregate["stages"]["challenge"]["cases_with_decision_disagreement"], 5)
        self.assertEqual(aggregate["stages"]["current"]["correct_resolution_after_requested_case_count"], 4)
        self.assertEqual(aggregate["stages"]["challenge"]["correct_resolution_after_requested_case_count"], 5)
        self.assertFalse(scored["probability_calibration"]["applicable"])
        self.assertIsNone(scored["probability_calibration"]["ece"])
        self.assertIsNone(scored["probability_calibration"]["brier"])

    def test_failures_abstention_and_missing_slots_remain_in_ten_case_denominator(self):
        rows = [response(1), response(2, ABSTENTION), response(3, response_status="incomplete"), response(4, "END")]
        scored = score_responses(packets(), rows)
        aggregate = scored["aggregates"]
        self.assertEqual(scored["scheduled"], 10)
        self.assertEqual(aggregate["status_counts"], {"admitted": 1, "explicit_abstention": 1,
                         "operational_failure": 1, "syntax_or_branch_failure": 1, "unissued_or_missing": 6})
        self.assertEqual(aggregate["stages"]["current"]["selective"]["scheduled_decisions"], 11)
        self.assertEqual(aggregate["stages"]["current"]["selective"]["coverage"], 0)
        self.assertIsNone(aggregate["stages"]["current"]["selective"]["risk"])

    def test_wrong_extra_branch_does_not_count_as_sound_or_exact_recovery(self):
        packet = packets()[1]
        text = serialize_compact(packet["hidden"]["allowed_interpretations"][1])
        text = text.replace("C R02003 R02002", "C R02003 ?").removesuffix("END") + "UNSPECIFIED_SOURCE(R02003: R02002)\nEND"
        scored = score_responses(packets(), [response(2, text)])
        family = scored["outcomes"][1]["evaluation"]["family"]
        self.assertTrue(family["actual_graph_covered"])
        self.assertTrue(family["overgeneration"])
        self.assertEqual(family["outside_family_branches"], 1)
        self.assertFalse(family["all_candidates_source_defensible"])
        self.assertFalse(family["exact_family_recovery"])
        self.assertFalse(family["full_family_covered"])

    def test_ungroundable_new_choice_retains_candidates_and_never_invents_an_answer(self):
        text = authored_text(4).replace("UNSPECIFIED_CHOICE", "AMBIGUOUS_GATE")
        row = score_responses(packets(), [response(4, text)])["outcomes"][3]["evaluation"]
        question = row["question_grounding"][0]
        self.assertTrue(question["branch_assignment_semantics_consistent"])
        self.assertEqual(question["grounding_status"], "ungroundable")
        self.assertIsNone(question["grounded_answer"])
        trajectory = row["current"]["clarification"]
        self.assertEqual(trajectory["status"], "ungroundable_requested_question")
        self.assertEqual(trajectory["requested_count"], 1)
        self.assertEqual(trajectory["answered_count"], 0)
        self.assertEqual(len(trajectory["retained_candidate_ids"]), 2)
        self.assertEqual(row["current"]["forced_grounded_answer_diagnostic"]["applied_answers"], {})

    def test_grounded_answer_does_not_repair_wrong_local_flag_elsewhere(self):
        text = authored_text(2).replace("E R02001 R 0 -", "E R02001 R 1 -")
        scored = score_responses(packets(), [response(2, text)])
        row = scored["outcomes"][1]["evaluation"]
        self.assertFalse(row["family"]["actual_graph_covered"])
        self.assertEqual(row["question_grounding"][0]["grounded_answer"], False)
        current = row["current"]
        self.assertEqual(current["agreement"]["unanimous_wrong"], 1)
        self.assertEqual(current["clarification"]["requested_count"], 0)
        self.assertFalse(current["clarification"]["correct_resolution_after_requested_question"])
        self.assertEqual(current["forced_grounded_answer_diagnostic"]["agreement"]["unanimous_wrong"], 1)
        self.assertEqual(scored["aggregates"]["stages"]["current"]["selective"]["risk"], 1)

    def test_irrelevant_emitted_question_is_not_requested_and_challenge_is_separate(self):
        scored = score_responses(packets(), [response(5), response(6)])
        irrelevant = scored["outcomes"][4]["evaluation"]
        self.assertEqual(irrelevant["current"]["irrelevant_emitted_question_ids"], ["resolve_R05004"])
        self.assertEqual(irrelevant["current"]["clarification"]["requested_count"], 0)
        latent = scored["outcomes"][5]["evaluation"]
        self.assertEqual(latent["current"]["clarification"]["requested_count"], 0)
        self.assertEqual(latent["challenge"]["clarification"]["requested_count"], 1)
        self.assertEqual(latent["current"]["minimum_distinguishing"]["R06006"]["k"], 3)

    def test_grounding_is_structural_not_activity_or_support_and_unknown_stays_unknown(self):
        packet = packets()[0]
        compiled = compile_ambiguity(authored_text(1))
        before = ground_questions(packet, compiled)
        altered = copy.deepcopy(packet)
        for graph in altered["hidden"]["allowed_interpretations"]:
            for evidence in graph["evidence"]:
                evidence["active"] = not evidence["active"]
        self.assertEqual(ground_questions(altered, compiled), before)
        self.assertEqual(before[0]["grounded_answer"], False)

    def test_family_metrics_keep_assignments_distinct_from_unique_graphs(self):
        packet = packets()[1]
        graph = packet["hidden"]["allowed_interpretations"][0]
        rows = [{"id": f"assignment-{i}", "graph": copy.deepcopy(graph)} for i in range(16)]
        metrics = family_metrics(packet, rows)
        self.assertEqual(metrics["candidate_count"], 16)
        self.assertEqual(metrics["distinct_graph_count"], 1)
        self.assertEqual(metrics["duplicate_assignment_branches"], 15)
        self.assertFalse(metrics["actual_graph_covered"])

    def test_source_constraints_and_hypothetical_guard_have_separate_meaning(self):
        scored = score_responses(packets(), [response(9), response(10)])
        for row in scored["outcomes"][8:]:
            for stage in ("current", "challenge"):
                view = row["evaluation"][stage]
                self.assertEqual(view["source_constraints"]["with_constraints"]["retained_constraint_violations_count"], 0)
                self.assertEqual(view["hypothetical_pair_vulnerability"]["attestations"], [])
                self.assertIn("not detection", view["guard_interpretation"])

    def test_actual_frozen_v3_baseline_schema_is_paired_without_changing_it(self):
        baseline_path = ROOT / "results/ambiguity-v3-summary.json"
        original = baseline_path.read_bytes()
        baseline = json.loads(original)
        scored = score_responses(packets(), [response(2)], baseline)
        pair = scored["paired_v3_baselines"][1]
        self.assertEqual(len(scored["paired_v3_baselines"]), 10)
        self.assertEqual(pair["v3"]["union"]["candidate_count"], 2)
        self.assertEqual(pair["v3"]["union"]["current"]["unanimous_wrong"], 1)
        self.assertEqual(pair["v4_current"]["disputed"], 1)
        self.assertTrue(pair["v4_family"]["exact_family_recovery"])
        self.assertEqual(baseline_path.read_bytes(), original)
        self.assertEqual(scored["post_hoc_primary_subset"]["aggregates"]["scheduled"], 3)

    def test_wrong_condition_duplicate_unknown_and_fenced_abstention_fail_closed(self):
        for rows in ([response(1), response(1)], [response(1, condition="other")], [response(99, "END")]):
            with self.assertRaises(ValueError):
                score_responses(packets(), rows)
        scored = score_responses(packets(), [response(1, "```text\n" + ABSTENTION + "\n```")])
        self.assertEqual(scored["outcomes"][0]["status"], "syntax_or_branch_failure")

    def test_detector_never_receives_authored_candidate_insertion(self):
        import retrace.ambiguity_v4_eval as module
        real = module.analyze_stress
        passed = []
        def spy(brief, state=None):
            passed.append(copy.deepcopy(brief["candidates"]))
            return real(brief, state)
        text = authored_text(2).replace("E R02001 R 0 -", "E R02001 R 1 -")
        compiled = compile_ambiguity(text)
        with patch.object(module, "analyze_stress", side_effect=spy):
            evaluate_compilation(packets()[1], compiled)
        self.assertTrue(passed)
        self.assertTrue(all(rows == compiled["candidates"] for rows in passed))

    def test_raw_journal_helpers_reject_duplicate_keys_and_partial_lines(self):
        path = ROOT / "scripts/summarize_ambiguity_v4.py"
        spec = importlib.util.spec_from_file_location("summary_v4_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(ValueError):
            json.loads('{"x":1,"x":2}', object_pairs_hook=module.unique)
        with tempfile.TemporaryDirectory() as folder:
            journal = Path(folder) / "journal.jsonl"
            journal.write_text('{"x":1}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                module.journal(journal)
            journal.write_text('{"x":1}\n', encoding="utf-8")
            self.assertEqual(module.journal(journal), [{"x": 1}])


if __name__ == "__main__":
    unittest.main()
