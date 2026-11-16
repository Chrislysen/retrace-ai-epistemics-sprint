import unittest

from retrace.benchmark import FAMILIES, POLICIES, baseline_predictions, evaluate_predictions, generate_cases, run_benchmarks
from retrace.core import analyze


class BenchmarkTests(unittest.TestCase):
    def test_reproducible_varied_dataset(self):
        cases = generate_cases(42, 140)
        self.assertEqual(cases, generate_cases(42, 140))
        self.assertNotEqual(cases, generate_cases(43, 140))
        self.assertEqual({case["family"] for case in cases}, set(FAMILIES))
        for family in FAMILIES:
            structures = {(len(case["evidence"]), len(case["claims"])) for case in cases if case["family"] == family}
            self.assertGreater(len(structures), 1)
        for case in cases:
            self.assertNotIn("answer", case)
            self.assertNotIn("expected", case)
            analyze(case, case["revoke"])

    def test_known_scoring_confusion_matrix(self):
        case = {
            "id": "score-check",
            "evidence": [{"id": "a", "kind": "root"}, {"id": "b", "kind": "root"}],
            "claims": [{"id": "ca", "supports": [["a"]]}, {"id": "cb", "supports": [["b"]]}],
            "decisions": [{"id": "da", "requires": ["ca"]}, {"id": "db", "requires": ["cb"]}],
            "revoke": ["a"],
        }
        wrong = evaluate_predictions(case, {"da": True, "db": False})
        self.assertEqual(wrong["under_retraction"], 1)
        self.assertEqual(wrong["over_retraction"], 1)
        self.assertEqual(wrong["decision_accuracy"], 0)
        self.assertEqual(wrong["lost_support_recovered"], 0)
        correct = evaluate_predictions(case, {"da": False, "db": True})
        self.assertTrue(correct["exact_match"])
        self.assertEqual(correct["supported_precision"], 1)
        self.assertEqual(correct["supported_recall"], 1)
        with self.assertRaises(ValueError):
            evaluate_predictions(case, {"da": False})
        with self.assertRaises(ValueError):
            evaluate_predictions(case, {"da": 0, "db": True})

    def test_rule_baselines_expose_distinct_failure_modes(self):
        cases = generate_cases(1729, 70)
        report = run_benchmarks(cases)
        self.assertEqual(report["kind"], "deterministic_synthetic_rule_baselines")
        self.assertEqual(set(report["policies"]), set(POLICIES))
        self.assertEqual(report["policies"]["oracle"]["exact_match_rate"], 1)
        self.assertGreater(report["policies"]["stale_before"]["under_retraction"], 0)
        self.assertGreater(report["policies"]["blanket_retract"]["over_retraction"], 0)
        self.assertGreater(report["policies"]["string_only"]["under_retraction"], 0)
        self.assertGreater(report["policies"]["descendant_flood"]["over_retraction"], 0)
        self.assertEqual(report["policies"]["descendant_flood"]["under_retraction"], 0)
        self.assertEqual(report["policies"]["oracle"]["decision_count"], sum(len(case["decisions"]) for case in cases))

    def test_controls_are_preserved_by_appropriate_rule_policies(self):
        for case in generate_cases(9, 21):
            if case["family"] in ("irrelevant", "no_op"):
                for policy in ("oracle", "stale_before", "descendant_flood", "string_only"):
                    self.assertTrue(evaluate_predictions(case, baseline_predictions(case, policy))["exact_match"])

    def test_mini_pilot_has_both_root_and_local_copy_withdrawals(self):
        cases = generate_cases(1729, 14)
        partial = [case for case in cases if case["family"] == "partial_retraction"]
        self.assertEqual(len(partial), 2)
        kinds = [{record["id"]: record["kind"] for record in case["evidence"]}[case["revoke"][0]] for case in partial]
        self.assertEqual(kinds, ["root", "copy"])
        for case in cases:
            if case["family"] == "no_op":
                self.assertEqual(case["revoke"], [])
                self.assertEqual(case["event_history"], [])

    def test_empty_dataset_undefined_rates_are_null(self):
        result = run_benchmarks([])
        self.assertIsNone(result["policies"]["oracle"]["decision_accuracy"])
        self.assertIsNone(result["policies"]["oracle"]["exact_match_rate"])
        with self.assertRaises(ValueError):
            generate_cases(count=-1)
        with self.assertRaises(ValueError):
            baseline_predictions(generate_cases(count=1)[0], "imaginary")

    def test_required_retractions_exclude_preunsupported_controls(self):
        case = {
            "evidence": [{"id": "a", "kind": "root"}, {"id": "unavailable", "kind": "root", "active": False}],
            "claims": [{"id": "ca", "supports": [["a"]]}, {"id": "cu", "supports": [["unavailable"]]}],
            "decisions": [{"id": "da", "requires": ["ca"]}, {"id": "du", "requires": ["cu"]}],
            "revoke": ["a"],
        }
        stale = evaluate_predictions(case, {"da": True, "du": False})
        self.assertEqual(stale["required_retractions"], 1)
        self.assertEqual(stale["missed_retractions"], 1)
        self.assertEqual(stale["missed_retraction_rate"], 1)
        self.assertEqual(stale["unsupported_acceptance_rate"], 0.5)
        self.assertEqual(stale["under_retraction_rate"], stale["unsupported_acceptance_rate"])
        control_error = evaluate_predictions(case, {"da": False, "du": True})
        self.assertEqual(control_error["missed_retraction_rate"], 0)
        self.assertEqual(control_error["unsupported_acceptance_rate"], 0.5)
        no_event = evaluate_predictions(case, {"da": True, "du": False}, revoked=[])
        self.assertEqual(no_event["required_retractions"], 0)
        self.assertIsNone(no_event["missed_retraction_rate"])
        self.assertEqual(no_event["unsupported_acceptance_rate"], 0)
        aggregate = run_benchmarks([case])["policies"]["stale_before"]
        self.assertEqual(aggregate["required_retractions"], 1)
        self.assertEqual(aggregate["missed_retraction_rate"], 1)
        self.assertEqual(aggregate["by_family"]["unclassified"]["missed_retraction_rate"], 1)


if __name__ == "__main__":
    unittest.main()
