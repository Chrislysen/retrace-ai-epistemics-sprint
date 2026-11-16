import copy
import json
import unittest

from retrace.core import analyze
from retrace.benchmark import generate_cases
from retrace.experiment import make_sessions, parse_predictions, score_records, strip_outer_fence


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.case = {"id": "x", "family": "alternative", "evidence": [
            {"id": "a", "kind": "root"}, {"id": "b", "kind": "root"},
            {"id": "p", "kind": "copy", "parents": ["a"]}],
            "claims": [{"id": "c", "supports": [["p"], ["b"]]}, {"id": "e", "supports": [["p"]]}],
            "decisions": [{"id": "d", "requires": ["c"]}, {"id": "f", "requires": ["e"]}], "revoke": ["a"]}

    def test_fresh_snapshot_matches_withdrawal(self):
        sessions = make_sessions([self.case])
        fresh = json.loads(sessions[1]["steps"][0]["input"].split("\n", 1)[1])
        expected = analyze(self.case, ["a"])["supported_decisions"]
        self.assertEqual(analyze(fresh)["supported_decisions"], expected)
        self.assertNotIn("revoke", fresh)
        self.assertNotIn("family", fresh)

    def test_strict_predictions(self):
        for invalid in ({"decisions": {"d": 1}}, {"decisions": {}}, {"decisions": {"d": True}, "explanation": "x"}):
            with self.assertRaises(ValueError):
                parse_predictions(invalid, {"d"})

    def test_missing_is_not_perfect(self):
        report = score_records([self.case], [])
        self.assertEqual(report["groups"]["history/withdrawn"]["exact_rate_all_expected"], 0)
        self.assertEqual(len(report["errors"]), 4)

    def test_different_models_cannot_be_pooled(self):
        rows = [{"model": "model-a", "case_id": "x", "condition": "history", "phase": "initial"},
                {"model": "model-b", "case_id": "x", "condition": "fresh", "phase": "withdrawn"}]
        with self.assertRaises(ValueError):
            score_records([self.case], rows)

    def test_duplicate_rejected(self):
        row = {"case_id": "x", "condition": "history", "phase": "withdrawn", "output_text": '{"decisions":{"d":true,"f":false}}'}
        with self.assertRaises(ValueError):
            score_records([self.case], [row, row])

    def test_separate_collateral_and_stale_errors(self):
        row = {"case_id": "x", "condition": "history", "phase": "withdrawn", "output_text": '{"decisions":{"d":false,"f":true}}'}
        group = score_records([self.case], [row])["groups"]["history/withdrawn"]
        self.assertEqual(group["over_retractions"], 1)
        self.assertEqual(group["under_retractions"], 1)

    def test_duplicate_json_keys_rejected_at_every_level(self):
        for text in ('{"decisions":{"d":false,"d":true}}',
                     '{"decisions":{"d":false},"decisions":{"d":true}}'):
            with self.assertRaises(ValueError):
                parse_predictions(text, {"d"})

    def test_duplicate_case_ids_rejected(self):
        with self.assertRaises(ValueError):
            score_records([self.case, copy.deepcopy(self.case)], [])

    def test_invalid_output_is_nonexact_without_fabricated_class_error(self):
        row = {"case_id": "x", "condition": "history", "phase": "withdrawn",
               "output_text": '{"decisions":{"d":"true","f":false}}'}
        report = score_records([self.case], [row])
        group = report["groups"]["history/withdrawn"]
        self.assertEqual(group["received"], 1)
        self.assertEqual(group["valid"], 0)
        self.assertEqual(group["exact_rate_all_expected"], 0)
        self.assertIsNone(group["under_retraction_rate_valid_only"])
        self.assertIsNone(group["over_retraction_rate_valid_only"])
        self.assertIsNone(report["pairs"][0]["same_final_support_predictions"])

    def test_consistency_does_not_imply_correctness(self):
        rows = [{"case_id": "x", "condition": condition, "phase": phase,
                 "output_text": '{"decisions":{"d":false,"f":true}}'}
                for condition, phase in (("history", "withdrawn"), ("fresh", "withdrawn"))]
        report = score_records([self.case], rows)
        self.assertTrue(report["pairs"][0]["same_final_support_predictions"])
        self.assertEqual(report["groups"]["history/withdrawn"]["exact_rate_all_expected"], 0)
        self.assertEqual(report["groups"]["fresh/withdrawn"]["exact_rate_all_expected"], 0)

    def test_pilot_controls_contain_unsupported_decision(self):
        for case in generate_cases(1729, 14):
            before = analyze(case)
            self.assertLess(len(before["supported_decisions"]), len(case["decisions"]))
            sessions = make_sessions([case])
            fresh = json.loads(sessions[1]["steps"][0]["input"].split("\n", 1)[1])
            self.assertEqual(analyze(fresh)["supported_decisions"], analyze(case, case["revoke"])["supported_decisions"])

    def test_fence_sensitivity_is_opt_in_and_preserves_raw_response(self):
        answer = '{"decisions":{"d":true,"f":false}}'
        for fenced in (f"```json\n{answer}\n```", f" \r\n```\r\n{answer}\r\n```\t "):
            with self.subTest(fenced=fenced):
                row = {"case_id": "x", "condition": "history", "phase": "withdrawn",
                       "output_text": fenced}
                unchanged = copy.deepcopy(row)
                strict = score_records([self.case], [row])
                normalized = score_records([self.case], [row], allow_outer_fence=True)
                self.assertEqual(strict["parsing_mode"], "strict")
                self.assertEqual(strict["groups"]["history/withdrawn"]["valid"], 0)
                self.assertEqual(normalized["parsing_mode"], "outer_fence_sensitivity")
                group = normalized["groups"]["history/withdrawn"]
                self.assertEqual(group["outer_fences_removed"], 1)
                self.assertEqual(group["valid"], 1)
                self.assertEqual(group["exact"], 1)
                self.assertEqual(row, unchanged)

    def test_fence_sensitivity_never_extracts_json_from_other_text(self):
        answer = '{"decisions":{"d":true,"f":false}}'
        invalid = (
            f"Here is the answer:\n```json\n{answer}\n```",
            f"```json\n{answer}\n```\nAll done.",
            f"```python\n{answer}\n```",
            f"```json {answer}```",
            f"```json\n{answer}\n```\n```json\n{answer}\n```",
            f"```json\n```json\n{answer}\n```\n```",
        )
        for text in invalid:
            with self.subTest(text=text):
                row = {"case_id": "x", "condition": "history", "phase": "withdrawn",
                       "output_text": text}
                group = score_records([self.case], [row], allow_outer_fence=True)["groups"]["history/withdrawn"]
                self.assertEqual(group["valid"], 0)
                self.assertEqual(group["exact"], 0)

    def test_strip_outer_fence_requires_one_whole_response_block(self):
        answer = '{"decisions":{"d":true,"f":false}}'
        self.assertEqual(strip_outer_fence(answer), (answer, False))
        self.assertEqual(strip_outer_fence(f"```json\n{answer}\n```"), (answer, True))
        for text in (
            f"prefix\n```json\n{answer}\n```",
            f"```json\n{answer}\n```\nsuffix",
            f"```json\n{answer}\n```\n```json\n{answer}\n```",
            f"```json\n```json\n{answer}\n```\n```",
        ):
            with self.subTest(text=text):
                self.assertEqual(strip_outer_fence(text), (text, False))

    def test_fence_sensitivity_does_not_repair_invalid_answer_schema(self):
        for answer in (
            '{"decisions":{"d":false,"d":true,"f":false}}',
            '{"decisions":{"d":false,"f":false},"decisions":{"d":true,"f":false}}',
            '{"decisions":{"d":"true","f":false}}',
            '{"decisions":{"d":true}}',
            '{"decisions":{"d":true,"f":false},"explanation":"trust me"}',
        ):
            with self.subTest(answer=answer):
                row = {"case_id": "x", "condition": "history", "phase": "withdrawn",
                       "output_text": f"```json\n{answer}\n```"}
                group = score_records([self.case], [row], allow_outer_fence=True)["groups"]["history/withdrawn"]
                self.assertEqual(group["valid"], 0)
                self.assertEqual(group["exact_rate_all_expected"], 0)

    def test_protected_alternative_denominator_excludes_controls(self):
        case = copy.deepcopy(self.case)
        case["evidence"].extend([{"id": "u", "kind": "root"},
                                 {"id": "z", "kind": "root", "active": False}])
        case["claims"].extend([{"id": "unrelated", "supports": [["u"]]},
                               {"id": "never", "supports": [["a", "z"]]}])
        case["decisions"].extend([{"id": "control", "requires": ["unrelated"]},
                                  {"id": "initially_out", "requires": ["never"]}])
        # d survives through b; f loses its sole route. control is unrelated.
        # initially_out touches the event but was never supported because z is inactive.
        row = {"case_id": "x", "condition": "history", "phase": "withdrawn",
               "predictions": {"decisions": {"d": False, "f": False,
                                              "control": False, "initially_out": True}}}
        group = score_records([case], [row])["groups"]["history/withdrawn"]
        self.assertEqual(group["supported_targets"], 2)
        self.assertEqual(group["unsupported_targets"], 2)
        self.assertEqual(group["over_retractions"], 2)
        self.assertEqual(group["protected_supported_targets"], 1)
        self.assertEqual(group["protected_collateral_errors"], 1)
        self.assertEqual(group["protected_collateral_rate_valid_only"], 1.0)
        self.assertEqual(group["required_retractions"], 1)
        self.assertEqual(group["missed_retractions"], 0)
        self.assertEqual(group["under_retractions"], 1)
        self.assertEqual(group["unsupported_acceptance_rate_valid_only"], 0.5)

    def test_protected_rate_uses_only_valid_withdrawal_outputs(self):
        rows = [{"case_id": "x", "condition": "history", "phase": phase,
                 "output_text": '{"decisions":{"d":false,"f":false}}'}
                for phase in ("initial", "restored")]
        rows.append({"case_id": "x", "condition": "history", "phase": "withdrawn",
                     "output_text": '{"decisions":{"d":"false","f":false}}'})
        report = score_records([self.case], rows)
        for phase in ("initial", "withdrawn", "restored"):
            group = report["groups"][f"history/{phase}"]
            self.assertEqual(group["protected_supported_targets"], 0)
            self.assertIsNone(group["protected_collateral_rate_valid_only"])


if __name__ == "__main__":
    unittest.main()
