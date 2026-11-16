"""Constructed compatibility tests; never read the locked conservation corpus."""
import copy
import unittest

from scripts.evaluate_conservation_v6_compatible import adapt_result, evaluate_compatible


def constructed_corpus():
    cases = []
    for number in range(12):
        evidence, claim, decision = f"A{number}", f"B{number}", f"C{number}"
        graph = {"evidence": [{"id": evidence, "kind": "root", "active": True, "parents": []}],
                 "claims": [{"id": claim, "supports": [[evidence]]}],
                 "decisions": [{"id": decision, "requires": [claim]}]}
        cases.append({"id": f"constructed-{number}", "public": {
            "prose": [{"id": "source", "text": f"Evidence {evidence} is an eligible original."}],
            "candidates": [{"id": "candidate", "graph": graph}],
            "registry": {"evidence": [evidence], "claims": [claim], "decisions": [decision]}},
            "evaluation": {"semantic_omission": False, "limitation_category": "constructed_adapter_test",
                           "source_obligations": [], "metamorphic": {"id_map": {
                               evidence: f"X{number}", claim: f"Y{number}", decision: f"Z{number}"}}}})
    return {"cases": cases}


def raw_empty():
    return {"schema": "constructed-stable-api", "status": "no_gap_detected_in_recognized_cues",
            "obligations": [], "gaps": [], "unresolved": [], "suppressed": [],
            "extra_metadata": {"sentinel": "unchanged"}}


class ConservationAdapterTests(unittest.TestCase):
    def test_only_two_aliases_added_and_original_is_unchanged(self):
        raw = raw_empty()
        raw["unresolved"] = [{"reason": "constructed review cue"}]
        raw["suppressed"] = [{"reason": "constructed historical context"}]
        before = copy.deepcopy(raw)
        adapted = adapt_result(raw)
        self.assertEqual(raw, before)
        self.assertEqual(set(adapted) - set(raw), {"unresolved_cues", "suppressed_cues"})
        self.assertEqual({key: adapted[key] for key in raw}, raw)
        self.assertEqual(adapted["unresolved_cues"], raw["unresolved"])
        self.assertEqual(adapted["suppressed_cues"], raw["suppressed"])
        adapted["unresolved_cues"][0]["reason"] = "mutated copy"
        self.assertEqual(raw, before)

    def test_missing_or_conflicting_fields_reject_without_repair(self):
        for bad in (None, {}, {**raw_empty(), "unresolved_cues": [{"not": "same"}]},
                    {**raw_empty(), "suppressed_cues": [{"not": "same"}]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                adapt_result(bad)

    def test_frozen_scorer_composition_keeps_raw_results_separate(self):
        data = constructed_corpus()
        before = copy.deepcopy(data)
        raw = raw_empty()
        calls = []
        def auditor(**kwargs):
            self.assertEqual(set(kwargs), {"prose", "candidates", "registry", "compilation"})
            self.assertIsNone(kwargs["compilation"])
            self.assertNotIn("evaluation", kwargs)
            calls.append(copy.deepcopy(kwargs))
            return raw
        result = evaluate_compatible(data, auditor)
        self.assertEqual(data, before)
        self.assertEqual(len(calls), 24)
        self.assertEqual(result["base"]["completed"], 12)
        self.assertEqual(result["derived"]["completed"], 12)
        self.assertEqual(result["metamorphic"]["semantic_profiles_invariant"], 12)
        self.assertEqual(len(result["raw_audits"]), 24)
        for stored, scored in zip(result["raw_audits"], result["rows"]):
            self.assertEqual(stored["raw_result"], raw)
            self.assertNotIn("unresolved_cues", stored["raw_result"])
            self.assertEqual((stored["case_id"], stored["variant"]), (scored["case_id"], scored["variant"]))
            self.assertEqual(scored["result"]["unresolved_cues"], raw["unresolved"])
        self.assertFalse(result["instrumentation_correction"]["score_logic_changed"])

    def test_auditor_errors_keep_all_raw_slots_and_failure_denominators(self):
        def failing(**kwargs):
            raise RuntimeError("constructed failure")
        result = evaluate_compatible(constructed_corpus(), failing)
        self.assertEqual(len(result["raw_audits"]), 24)
        self.assertEqual(result["base"]["auditor_failures"], 12)
        self.assertTrue(all(row["raw_result"] is None and "constructed failure" in row["error"] for row in result["raw_audits"]))


if __name__ == "__main__":
    unittest.main()
