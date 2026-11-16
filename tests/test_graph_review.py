import copy
import json
import unittest

from retrace.graph_review import review_graphs


def alternative_graph():
    return {
        "evidence": [{"id": identifier, "kind": "root", "active": True}
                     for identifier in ("a", "b", "c")],
        "claims": [{"id": "claim", "supports": [["a"], ["b"], ["c"]]}],
        "decisions": [{"id": "decision", "requires": ["claim"]}],
    }


class GraphReviewTests(unittest.TestCase):
    def test_order_labels_and_repeated_clauses_do_not_create_differences(self):
        reference = alternative_graph()
        predicted = copy.deepcopy(reference)
        predicted["evidence"].reverse()
        predicted["claims"][0]["supports"].reverse()
        predicted["claims"][0]["supports"].append(["a"])
        predicted["decisions"][0]["label"] = "Different label"
        original_reference, original_predicted = copy.deepcopy(reference), copy.deepcopy(predicted)
        result = review_graphs(reference, predicted)
        self.assertTrue(result["graph_exact"])
        self.assertTrue(result["relationship_agreement"])
        self.assertIsNone(result["witness"])
        self.assertEqual(result["search"]["tested_subsets"], 6)
        self.assertEqual(result["search"]["divergent_subsets"], 0)
        self.assertEqual(reference, original_reference)
        self.assertEqual(predicted, original_predicted)
        json.dumps(result)

    def test_pair_witness_exposes_missing_backup_while_all_singletons_agree(self):
        reference = alternative_graph()
        predicted = copy.deepcopy(reference)
        predicted["claims"][0]["supports"] = [["a"], ["b"]]
        one = review_graphs(reference, predicted, max_interventions=1)
        self.assertTrue(one["current"]["agreement"])
        self.assertFalse(one["graph_exact"])
        self.assertIsNone(one["witness"])
        two = review_graphs(reference, predicted)
        self.assertEqual(two["witness"]["cardinality"], 2)
        self.assertEqual(two["witness"]["actions"], [
            {"id": "a", "action": "withdraw", "active": False},
            {"id": "b", "action": "withdraw", "active": False},
        ])
        self.assertEqual(two["witness"]["reference_decisions"], {"decision": True})
        self.assertEqual(two["witness"]["predicted_decisions"], {"decision": False})
        self.assertEqual(two["search"]["by_cardinality"], [
            {"cardinality": 1, "possible_subsets": 3, "tested_subsets": 3, "divergent_subsets": 0},
            {"cardinality": 2, "possible_subsets": 3, "tested_subsets": 3, "divergent_subsets": 1},
        ])

    def test_restoration_exposes_local_flag_confused_with_inherited_unusability(self):
        reference = {
            "evidence": [{"id": "origin", "kind": "root", "active": False},
                         {"id": "copy", "kind": "copy", "parents": ["origin"], "active": True}],
            "claims": [{"id": "claim", "supports": [["copy"]]}],
            "decisions": [{"id": "decision", "requires": ["claim"]}],
        }
        predicted = copy.deepcopy(reference)
        predicted["evidence"][1]["active"] = False
        result = review_graphs(reference, predicted)
        self.assertTrue(result["current"]["agreement"])
        self.assertTrue(result["relationship_agreement"])
        self.assertEqual(result["local_eligibility_mismatches"], [{
            "id": "copy", "reference_active": True, "predicted_active": False,
            "reference_usable": False, "predicted_usable": False,
        }])
        self.assertEqual(result["witness"]["actions"], [
            {"id": "origin", "action": "restore", "active": True},
        ])
        self.assertEqual(result["witness"]["differing_decisions"], ["decision"])
        self.assertTrue(result["witness"]["reference_decisions"]["decision"])
        self.assertFalse(result["witness"]["predicted_decisions"]["decision"])

    def test_mixed_restore_withdraw_pair_is_searched(self):
        reference = {
            "evidence": [{"id": "a", "active": False}, {"id": "b", "active": True}],
            "claims": [{"id": "claim", "supports": [["a"], ["b"]]}],
            "decisions": [{"id": "decision", "requires": ["claim"]}],
        }
        predicted = copy.deepcopy(reference)
        predicted["claims"][0]["supports"] = [["b"]]
        self.assertIsNone(review_graphs(reference, predicted, max_interventions=1)["witness"])
        result = review_graphs(reference, predicted)
        self.assertEqual(result["witness"]["actions"], [
            {"id": "a", "action": "restore", "active": True},
            {"id": "b", "action": "withdraw", "active": False},
        ])
        self.assertEqual(result["total_interventions_tested"], 3)

    def test_actions_set_same_flags_in_both_graphs_instead_of_inverting_each(self):
        reference = {
            "evidence": [{"id": "a", "active": True}],
            "claims": [{"id": "claim", "supports": [["a"]]}],
            "decisions": [{"id": "decision", "requires": ["claim"]}],
        }
        predicted = copy.deepcopy(reference)
        predicted["evidence"][0]["active"] = False
        result = review_graphs(reference, predicted)
        self.assertEqual(result["witness"]["cardinality"], 0)
        self.assertEqual(result["witness"]["kind"], "current_disagreement")
        # Withdrawal sets both flags false, so no counterfactual difference.
        self.assertEqual(result["search"]["tested_subsets"], 1)
        self.assertEqual(result["search"]["divergent_subsets"], 0)
        reference["evidence"][0]["active"], predicted["evidence"][0]["active"] = False, True
        restored = review_graphs(reference, predicted)
        self.assertEqual(restored["candidate_toggles"], [{"id": "a", "action": "restore", "active": True}])
        self.assertEqual(restored["search"]["divergent_subsets"], 0)

    def test_and_or_grouping_is_retained_and_first_witness_is_deterministic(self):
        reference = alternative_graph()
        predicted = copy.deepcopy(reference)
        predicted["claims"][0]["supports"] = [["a", "b", "c"]]
        result = review_graphs(reference, predicted)
        self.assertEqual(result["node_differences"][0]["fields"], ["supports"])
        self.assertEqual(result["witness"]["actions"], [{"id": "a", "action": "withdraw", "active": False}])
        self.assertEqual(result["search"]["divergent_subsets"], 6)
        for graph in (reference, predicted):
            graph["evidence"].reverse()
            graph["claims"][0]["supports"].reverse()
        self.assertEqual(review_graphs(reference, predicted), result)

    def test_supplied_root_copy_types_are_preserved(self):
        reference = {
            "evidence": [{"id": "a", "active": True}, {"id": "b", "active": True}],
            "claims": [{"id": "claim", "supports": [["b"]]}],
            "decisions": [{"id": "decision", "requires": ["claim"]}],
        }
        predicted = copy.deepcopy(reference)
        predicted["evidence"][1].update(kind="copy", parents=["a"])
        result = review_graphs(reference, predicted)
        self.assertFalse(result["relationship_agreement"])
        self.assertEqual(result["node_differences"][0]["fields"], ["kind", "parents"])
        self.assertEqual(result["witness"]["actions"], [{"id": "a", "action": "withdraw", "active": False}])

    def test_no_witness_does_not_hide_structurally_wrong_unused_node(self):
        reference = alternative_graph()
        reference["claims"].append({"id": "unused", "supports": [["a"]]})
        predicted = copy.deepcopy(reference)
        predicted["claims"][1]["supports"] = [["b"]]
        result = review_graphs(reference, predicted)
        self.assertFalse(result["graph_exact"])
        self.assertIsNone(result["witness"])
        self.assertTrue(any("not graph correctness" in line for line in result["scope"]))

    def test_rejects_missing_ids_category_mismatch_invalid_graph_and_excess_size(self):
        reference = alternative_graph()
        invalid = copy.deepcopy(reference)
        invalid["evidence"].append({"id": "extra"})
        with self.assertRaisesRegex(ValueError, "evidence IDs must match"):
            review_graphs(reference, invalid)
        invalid = copy.deepcopy(reference)
        invalid["claims"].append({"id": "extra", "supports": []})
        with self.assertRaisesRegex(ValueError, "claims IDs must match"):
            review_graphs(reference, invalid)
        invalid = copy.deepcopy(reference)
        invalid["claims"][0]["supports"] = [["claim"]]
        with self.assertRaisesRegex(ValueError, "cycle"):
            review_graphs(reference, invalid)
        oversized = {"evidence": [{"id": str(i)} for i in range(25)], "claims": [], "decisions": []}
        with self.assertRaisesRegex(ValueError, "at most 24"):
            review_graphs(oversized, oversized)
        for bound in (True, -1, 3, 1.5, "2"):
            with self.subTest(bound=bound), self.assertRaises(ValueError):
                review_graphs(reference, reference, max_interventions=bound)

    def test_current_only_empty_graphs_and_explicit_final_flag_contract(self):
        graph = alternative_graph()
        graph["revoke"] = ["a", "b", "c"]
        result = review_graphs(graph, graph, max_interventions=0)
        self.assertTrue(result["current"]["reference_decisions"]["decision"])
        self.assertEqual(result["search"]["tested_subsets"], 0)
        empty = review_graphs({"evidence": [], "claims": [], "decisions": []},
                              {"evidence": [], "claims": [], "decisions": []})
        self.assertTrue(empty["graph_exact"])
        self.assertIsNone(empty["witness"])
        self.assertEqual(empty["search"]["tested_subsets"], 0)


if __name__ == "__main__":
    unittest.main()
