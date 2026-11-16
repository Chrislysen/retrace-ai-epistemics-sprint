"""Prospective corpus integrity and independently specified event expectations."""
from collections import Counter
from copy import deepcopy
import json
import unittest

from scripts.build_frontier_v6h_polar_cases import build, build_cases
from retrace.graph_identity_v6h import family_score, graph_key
from retrace.source_ir_v6h import compile_ir
from retrace.source_ir_v6d import source_segments
from retrace.tiered_v6h import analyze


class PolarCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.data = build(); cls.cases = cls.data["cases"]

    def test_counts_inventory_choices_and_seed_balance(self):
        self.assertEqual(len(self.cases), 8)
        self.assertEqual({case["partition"] for case in self.cases}, {"synthetic"})
        self.assertEqual({case["family_id"] for case in self.cases}, {"F5"})
        self.assertEqual(Counter(case["evaluation"]["seed_kind"] for case in self.cases), {"deficient": 4, "faithful_complete": 4})
        self.assertEqual([len(case["evaluation"]["source_family"]) for case in self.cases], [1, 1, 1, 1, 2, 1, 1, 2])
        self.assertEqual(sum(bool(case["evaluation"]["unknown_ancestry_ids"]) for case in self.cases), 1)
        self.assertEqual(self.data["long_context_subset_ids"], ["V6H-F5-01", "V6H-F5-04", "V6H-F5-05", "V6H-F5-08"])
        for case in self.cases:
            self.assertLessEqual(len(case["public"]["registry"]["evidence"]), 8)
            self.assertEqual(len(case["authored_seed_pool"]["candidates"]), 2)
            source_ids = {doc["id"] for doc in case["public"]["source_documents"]}
            self.assertEqual(len(source_ids), len(case["public"]["source_documents"]))
            self.assertTrue(all(group["id"] in source_ids for group in case["events"]["document_groups"]))

    def test_reference_ir_cites_public_source_and_compiles_exact_manual_family(self):
        for case in self.cases:
            public, gold = case["public"], case["evaluation"]
            result = compile_ir(gold["reference_ir"], public["source_documents"], public["registry"])
            self.assertEqual(result["registry_coverage_gaps"], [])
            self.assertTrue(family_score(result["candidates"], gold["source_family"])["exact_family"])
            refs = {row["span_id"] for row in source_segments(public["source_documents"])}
            for row in gold["reference_ir"]["entities"] + gold["reference_ir"]["propositions"]:
                self.assertTrue(set(row["citations"]) <= refs)

    def test_seed_faithfulness_is_exactly_counterbalanced(self):
        for case in self.cases:
            score = family_score(case["authored_seed_pool"]["candidates"], case["evaluation"]["source_family"])
            self.assertEqual(score["exact_family"], case["evaluation"]["seed_kind"] == "faithful_complete")
            if case["evaluation"]["seed_kind"] == "deficient": self.assertGreater(score["spurious_distinct"], 0)

    def test_manual_main_decision_event_vectors(self):
        expected = [
            [("supported",), ("supported",), ("not_supported",)],
            [("not_supported",), ("supported",), ("not_supported",)],
            [("contested",), ("supported",), ("contested",)],
            [("supported",), ("supported",), ("supported",)],
            [("supported", "supported"), ("not_supported", "not_supported"), ("supported", "not_supported")],
            [("not_supported",), ("insufficient_provenance",), ("not_supported",)],
            [("supported",), ("contested",), ("supported",)],
            [("supported", "not_supported"), ("supported", "supported"), ("not_supported", "not_supported")],
        ]
        for case, expected_states in zip(self.cases, expected):
            gold = case["evaluation"]; decision = gold["semantic_key_ids"]["D"]
            actual = [tuple(row[decision]["state"] for row in gold["state_gold"][state]["candidate_decisions"].values()) for state in ("initial", "withdrawn", "restored")]
            self.assertEqual(actual, expected_states, case["id"])

    def test_unrelated_and_inactive_controls_hold_across_every_event_and_reading(self):
        for case in self.cases:
            ids = case["evaluation"]["semantic_key_ids"]
            for state in case["evaluation"]["state_gold"].values():
                for decisions in state["candidate_decisions"].values():
                    self.assertEqual(decisions[ids["K"]]["state"], "supported")
                    self.assertEqual(decisions[ids["H"]]["state"], "not_supported")
            original = [{e["id"]: e["active"] for e in row["graph"]["evidence"]} for row in case["evaluation"]["source_family"]]
            self.assertTrue(all(not values[ids["F"]] for values in original))

    def test_document_restoration_never_clears_the_separate_passage_veto(self):
        phases = {"hist_init": "initial", "hist_withdrawn": "withdrawn", "hist_restored": "restored", "evt_no_commit": "withdrawn", "fresh_withdrawn": "withdrawn", "fresh_restored": "restored"}
        for case in self.cases:
            events = case["events"]
            self.assertEqual(events["restoration"]["clear_passage_vetoes"], [])
            self.assertEqual(events["states"]["restored"]["revoked_documents"], [])
            self.assertEqual(events["states"]["restored"]["revoked_passages"], events["states"]["withdrawn"]["revoked_passages"])
            self.assertTrue(events["states"]["restored"]["revoked_passages"])
            for phase, state in phases.items(): self.assertEqual(case["phases"][phase], {"state_name": state, "state": events["states"][state]})

    def test_signed_rebuttal_is_not_withdrawal_and_positive_backup_survives(self):
        polar = self.cases[2]; ids = polar["evaluation"]["semantic_key_ids"]
        graph = polar["evaluation"]["source_family"][0]["graph"]
        result = analyze(graph)
        self.assertTrue(result["concrete"]["evidence_usable"][ids["P"]])
        self.assertTrue(result["concrete"]["evidence_usable"][ids["N"]])
        self.assertEqual(result["claims"][ids["C"]]["state"], "contested")
        backup = self.cases[3]; ids = backup["evaluation"]["semantic_key_ids"]
        result = analyze(backup["evaluation"]["source_family"][0]["graph"])
        self.assertEqual(result["claims"][ids["C"]]["state"], "contested")
        self.assertEqual(result["claims"][ids["R"]]["state"], "supported")

    def test_unknown_is_preserved_and_masked_without_inventing_a_root(self):
        case = self.cases[5]; ids = case["evaluation"]["semantic_key_ids"]
        for family in (case["evaluation"]["source_family"], case["authored_seed_pool"]["candidates"]):
            self.assertTrue(all(next(e for e in row["graph"]["evidence"] if e["id"] == ids["X"])["kind"] == "unknown" for row in family))
        exposed = case["evaluation"]["state_gold"]["withdrawn"]["family_decisions"][ids["D"]]
        self.assertFalse(exposed["box_supported"]); self.assertTrue(exposed["diamond_supported"])

    def test_public_only_fields_and_deterministic_build(self):
        self.assertEqual(build(), self.data)
        for case in self.cases:
            self.assertEqual(set(case["public"]), {"source_documents", "registry"})
            text = json.dumps(case["public"])
            for hidden in ("source_family", "seed_kind", "state_gold", "reference_ir", "authored-seed", "V6H-F5-"):
                self.assertNotIn(hidden, text)
            for identifiers in case["public"]["registry"].values():
                for ident in identifiers: self.assertRegex(ident, r"^x[0-9a-f]{9}$")


if __name__ == "__main__": unittest.main()
