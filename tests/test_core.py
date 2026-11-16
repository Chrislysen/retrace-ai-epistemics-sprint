import copy
import itertools
import unittest

from retrace.core import analyze, validate_case


def fixture():
    return {
        "id": "hand-checked",
        "evidence": [
            {"id": "a", "kind": "root", "active": True},
            {"id": "b", "kind": "root", "active": True},
            {"id": "c", "kind": "copy", "parents": ["a"], "active": True},
            {"id": "d", "kind": "copy", "parents": ["c"], "active": True},
            {"id": "unused", "kind": "root", "active": True},
        ],
        "claims": [
            {"id": "only_a", "supports": [["d"]]},
            {"id": "either", "supports": [["d"], ["b"]]},
            {"id": "both", "supports": [["a", "b"]]},
        ],
        "decisions": [
            {"id": "withdraw", "requires": ["only_a"]},
            {"id": "preserve", "requires": ["either"]},
            {"id": "withdraw_and", "requires": ["both"]},
        ],
    }


class CoreTests(unittest.TestCase):
    def test_selective_retraction_preserves_independent_support(self):
        result = analyze(fixture(), ["a"])
        self.assertEqual(result["supported_decisions"], ["preserve"])
        self.assertEqual(result["impacted_decisions"], ["withdraw", "withdraw_and"])
        self.assertEqual(result["claims"]["either"]["valid_supports"], [["b"]])
        self.assertEqual(result["claims"]["either"]["supporting_roots"], ["b"])
        self.assertEqual(result["claims"]["either"]["invalidation_causes"], [])
        self.assertFalse(result["evidence"]["c"]["usable"])
        self.assertFalse(result["evidence"]["d"]["usable"])
        self.assertEqual(result["decisions"]["withdraw"]["invalidation_causes"], ["a"])
        self.assertEqual(result["decisions"]["withdraw"]["dependency_paths"]["a"], ["withdraw", "only_a", "d", "c", "a"])

    def test_irrelevant_revocation_has_no_decision_effect(self):
        result = analyze(fixture(), ["unused"])
        self.assertEqual(result["impacted_decisions"], [])
        self.assertEqual(result["invalidated_ids"], ["unused"])

    def test_local_copy_withdrawal_does_not_withdraw_origin(self):
        result = analyze(fixture(), ["c"])
        self.assertTrue(result["evidence"]["a"]["usable"])
        self.assertTrue(result["claims"]["both"]["usable"])
        self.assertEqual(result["impacted_decisions"], ["withdraw"])

    def test_initially_unavailable_and_restoration(self):
        case = fixture()
        case["evidence"][1]["active"] = False
        baseline = analyze(case)
        self.assertFalse(baseline["decisions"]["withdraw_and"]["usable"])
        self.assertEqual(analyze(case, ["a"])["impacted_decisions"], ["preserve", "withdraw"])
        self.assertEqual(analyze(case, []), baseline)

    def test_explicit_event_and_input_not_mutated(self):
        case = fixture()
        case["revoke"] = ["a"]
        original = copy.deepcopy(case)
        self.assertEqual(len(analyze(case)["supported_decisions"]), 3)
        analyze(case, case["revoke"])
        self.assertEqual(case, original)

    def test_truth_table_for_mixed_and_or_and_copy(self):
        case = {
            "evidence": [{"id": name, "kind": "root"} for name in ("a", "b", "c")]
            + [{"id": "copy", "kind": "copy", "parents": ["a", "b"]}],
            "claims": [{"id": "claim", "supports": [["copy"], ["c"]]}],
            "decisions": [{"id": "decision", "requires": ["claim"]}],
        }
        for a, b, c in itertools.product((False, True), repeat=3):
            revoked = [name for name, active in zip(("a", "b", "c"), (a, b, c)) if not active]
            self.assertEqual(analyze(case, revoked)["decisions"]["decision"]["usable"], (a and b) or c)

    def test_unfounded_claim_is_not_supported(self):
        case = {"evidence": [], "claims": [{"id": "c", "supports": []}], "decisions": [{"id": "d", "requires": ["c"]}]}
        self.assertEqual(analyze(case)["supported_decisions"], [])

    def test_missing_reference_cycle_and_type_validation(self):
        invalid = fixture()
        invalid["claims"][0]["supports"] = [["missing"]]
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_case(invalid)
        invalid = fixture()
        invalid["evidence"][2]["parents"] = ["d"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_case(invalid)
        invalid = fixture()
        invalid["evidence"][0]["active"] = "false"
        with self.assertRaisesRegex(ValueError, "boolean"):
            validate_case(invalid)
        for revoked in (["missing"], ["only_a"], ["a", "a"], "a"):
            with self.assertRaises(ValueError):
                analyze(fixture(), revoked)

    def test_reject_empty_clause_duplicate_ids_and_wrong_reference_type(self):
        invalid = fixture()
        invalid["claims"][0]["supports"] = [[]]
        with self.assertRaisesRegex(ValueError, "empty"):
            validate_case(invalid)
        invalid = fixture()
        invalid["claims"][0]["id"] = "a"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_case(invalid)
        invalid = fixture()
        invalid["decisions"][0]["requires"] = ["a"]
        with self.assertRaisesRegex(ValueError, "cannot depend"):
            validate_case(invalid)


if __name__ == "__main__":
    unittest.main()
