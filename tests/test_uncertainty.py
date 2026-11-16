import copy
import json
import unittest
from pathlib import Path

from retrace.uncertainty import analyze_uncertainty, candidate_set_fingerprint


def graph(main=True, unrelated=True):
    return {"evidence": [{"id": "a", "active": main}, {"id": "b", "active": unrelated},
                         {"id": "z", "active": False}],
            "claims": [{"id": "c", "supports": [["a"]]}, {"id": "u", "supports": [["b"]]},
                       {"id": "x", "supports": [["z"]]}],
            "decisions": [{"id": "d", "requires": ["c"]}, {"id": "keep", "requires": ["u"]},
                          {"id": "never", "requires": ["x"]}]}


def candidate(identifier, main=True, unrelated=True):
    return {"id": identifier, "graph": graph(main, unrelated)}


def question(identifier, answers, cost=1):
    return {"id": identifier, "label": "Resolve declared fact " + identifier,
            "cost": cost, "answers": answers}


class UncertaintyTests(unittest.TestCase):
    def test_preserves_settled_decisions_and_returns_conflicting_witnesses(self):
        result = analyze_uncertainty([candidate("one"), candidate("two", False)])
        self.assertEqual(result["decision_states"]["keep"]["state"], "robust_supported")
        self.assertEqual(result["decision_states"]["never"]["state"], "robust_unsupported")
        self.assertEqual(result["decision_states"]["d"]["state"], "needs_review")
        self.assertEqual(result["decision_states"]["d"]["conflicting_witnesses"],
                         {"supported": "one", "unsupported": "two"})
        self.assertFalse(result["clarification"]["possible"])
        self.assertEqual(result["clarification"]["blocking_pairs"][0]["differing_target_decisions"], ["d"])

    def test_copy_uncertainty_after_withdrawal_is_not_silently_resolved(self):
        independent = graph()
        independent["evidence"][1]["active"] = False
        copied = copy.deepcopy(independent)
        copied["evidence"][0].update(kind="copy", parents=["b"])
        result = analyze_uncertainty([{"id": "copy", "graph": copied}, {"id": "original", "graph": independent}],
                                    [question("lineage", {"copy": True, "original": False})])
        self.assertEqual(result["decision_states"]["d"]["state"], "needs_review")
        self.assertEqual(result["clarification"]["worst_case_cost"], 1)
        self.assertFalse(result["clarification"]["tree"]["branches"]["yes"]["decisions"]["d"])

    def test_uncertain_and_or_grouping_changes_only_the_dependent_decision(self):
        either = graph(False, True)
        either["claims"][0]["supports"] = [["a"], ["b"]]
        both = copy.deepcopy(either)
        both["claims"][0]["supports"] = [["a", "b"]]
        result = analyze_uncertainty([{"id": "either", "graph": either}, {"id": "both", "graph": both}],
                                    [question("joint_requirement", {"either": False, "both": True})])
        self.assertEqual(result["decision_states"]["d"]["state"], "needs_review")
        self.assertEqual(result["decision_states"]["keep"]["state"], "robust_supported")
        self.assertEqual(result["clarification"]["tree"]["question_id"], "joint_requirement")

    def test_target_agreement_stops_before_identifying_graph(self):
        candidates = [candidate("a", True, True), candidate("b", True, False), candidate("c", False, True)]
        questions = [question("material", {"a": True, "b": True, "c": False}),
                     question("irrelevant", {"a": True, "b": False, "c": True})]
        result = analyze_uncertainty(candidates, questions, ["d"])
        self.assertEqual(result["clarification"]["worst_case_cost"], 1)
        branch = result["clarification"]["tree"]["branches"]["yes"]
        self.assertEqual(branch["kind"], "decision_agreement")
        self.assertEqual(branch["remaining_candidates"], ["a", "b"])
        settled = analyze_uncertainty(candidates, questions, ["never"])
        self.assertEqual(settled["clarification"]["worst_case_cost"], 0)

    def test_minimax_chooses_two_cheap_questions_over_one_expensive_question(self):
        candidates = [candidate("a", False), candidate("b", False), candidate("c", False), candidate("d", True)]
        questions = [question("expensive", {"a": False, "b": False, "c": False, "d": True}, 3),
                     question("first", {"a": False, "b": False, "c": True, "d": True}),
                     question("second", {"a": False, "b": True, "c": False, "d": True})]
        result = analyze_uncertainty(candidates, questions, ["d"])
        tree = result["clarification"]["tree"]
        self.assertEqual(tree["question_id"], "first")
        self.assertEqual(tree["worst_case_cost"], 2)
        self.assertEqual(tree["branches"]["no"]["kind"], "decision_agreement")
        self.assertEqual(tree["branches"]["yes"]["question_id"], "second")

    def test_joint_vector_may_need_more_questions_than_individual_decision(self):
        candidates = [candidate("a", False, False), candidate("b", False, True),
                      candidate("c", True, False), candidate("d", True, True)]
        questions = [question("main", {"a": False, "b": False, "c": True, "d": True}),
                     question("other", {"a": False, "b": True, "c": False, "d": True})]
        self.assertEqual(analyze_uncertainty(candidates, questions, ["d"])["clarification"]["worst_case_cost"], 1)
        self.assertEqual(analyze_uncertainty(candidates, questions)["clarification"]["worst_case_cost"], 2)

    def test_unanswerable_distinction_has_no_fabricated_finite_tree(self):
        candidates = [candidate("a", False), candidate("b", True), candidate("c", True)]
        result = analyze_uncertainty(candidates, [question("only", {"a": False, "b": False, "c": True})])
        self.assertFalse(result["clarification"]["possible"])
        self.assertIsNone(result["clarification"]["tree"])
        self.assertIsNone(result["clarification"]["worst_case_cost"])
        self.assertEqual(result["clarification"]["blocking_pairs"][0]["candidate_ids"], ["a", "b"])

    def test_fingerprints_invalidate_stale_certificates_and_ignore_presentation(self):
        candidates = [candidate("one")]
        original = copy.deepcopy(candidates)
        fingerprint = candidate_set_fingerprint(candidates)
        candidates[0]["graph"]["evidence"].reverse()
        candidates[0]["graph"]["claims"][0]["label"] = "Display name"
        self.assertEqual(candidate_set_fingerprint(candidates), fingerprint)
        candidates[0]["graph"]["evidence"][-1]["active"] = False
        self.assertNotEqual(candidate_set_fingerprint(candidates), fingerprint)
        self.assertNotEqual(candidate_set_fingerprint(original + [candidate("two", False)]), fingerprint)
        a = analyze_uncertainty(original, [question("q", {"one": True})])
        b = analyze_uncertainty(original, [question("q", {"one": False})])
        self.assertEqual(a["candidate_set_fingerprint"], b["candidate_set_fingerprint"])
        self.assertNotEqual(a["analysis_fingerprint"], b["analysis_fingerprint"])

    def test_deterministic_ties_order_and_no_input_mutation(self):
        candidates = [candidate("b", False), candidate("a")]
        questions = [question("z", {"a": True, "b": False}), question("a", {"a": True, "b": False})]
        before = copy.deepcopy((candidates, questions))
        result = analyze_uncertainty(candidates, questions)
        self.assertEqual(result["clarification"]["tree"]["question_id"], "a")
        self.assertEqual((candidates, questions), before)
        self.assertEqual(analyze_uncertainty(candidates[::-1], questions[::-1]), result)

    def test_rejects_invalid_graphs_ids_questions_costs_and_resource_bounds(self):
        candidates = [candidate("one"), candidate("two", False)]
        missing = copy.deepcopy(candidates)
        missing[1]["graph"]["decisions"].pop()
        with self.assertRaisesRegex(ValueError, "same IDs"):
            analyze_uncertainty(missing)
        cyclic = copy.deepcopy(candidates)
        cyclic[0]["graph"]["claims"][0]["supports"] = [["c"]]
        with self.assertRaisesRegex(ValueError, "cycle"):
            analyze_uncertainty(cyclic)
        for value in ([], [candidate(str(i)) for i in range(17)], [candidate("same"), candidate("same")]):
            with self.assertRaises(ValueError): analyze_uncertainty(value)
        for cost in (0, -1, True, 1.5, float("inf")):
            with self.assertRaises(ValueError):
                analyze_uncertainty(candidates, [question("q", {"one": True, "two": False}, cost)])
        for answers in ({"one": True}, {"one": True, "two": None}, {"one": 1, "two": False}):
            with self.assertRaises(ValueError): analyze_uncertainty(candidates, [question("q", answers)])
        with self.assertRaises(ValueError):
            analyze_uncertainty(candidates, [question(str(i), {"one": True, "two": False}) for i in range(21)])
        with self.assertRaises(ValueError): analyze_uncertainty(candidates, target_decisions=["missing"])
        too_large = {"evidence": [{"id": str(i)} for i in range(251)], "claims": [], "decisions": []}
        with self.assertRaisesRegex(ValueError, "250 nodes"):
            analyze_uncertainty([{"id": "large", "graph": too_large}])

    def test_rejects_unapplied_withdrawals_instead_of_ignoring_them(self):
        current = candidate("one")
        current["graph"]["revoke"] = ["a"]
        with self.assertRaisesRegex(ValueError, "encode current active flags first"):
            analyze_uncertainty([current])
        with self.assertRaisesRegex(ValueError, "encode current active flags first"):
            candidate_set_fingerprint([current])
        current["graph"]["revoke"] = []
        current["graph"]["evidence"][0]["active"] = False
        self.assertEqual(analyze_uncertainty([current])["decision_states"]["d"]["state"], "robust_unsupported")

    def test_artificial_demo_needs_one_question_for_decisions_but_two_for_graph(self):
        path = Path(__file__).resolve().parents[1] / "data" / "uncertainty-demo.json"
        demo = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(demo["artificial_demonstration"])
        result = analyze_uncertainty(demo["candidates"], demo["questions"], demo["target_decisions"])
        self.assertEqual(result["clarification"]["worst_case_cost"], 1)
        tree = result["clarification"]["tree"]
        self.assertEqual(tree["question_id"], "record_lineage")
        self.assertEqual({row["state"] for row in result["decision_states"].values()},
                         {"robust_supported", "robust_unsupported", "needs_review"})
        for branch in tree["branches"].values():
            self.assertEqual(branch["kind"], "decision_agreement")
            self.assertEqual(len(branch["remaining_candidates"]), 2)
        # Each single question leaves two distinct graphs; both answer bits
        # distinguish all four, so unit-cost full identification needs two.
        signatures = {tuple(q["answers"][c["id"]] for q in demo["questions"]) for c in demo["candidates"]}
        self.assertEqual(len(signatures), 4)
        for q in demo["questions"]:
            self.assertEqual(sum(q["answers"].values()), 2)
        self.assertEqual(len({candidate_set_fingerprint([c]) for c in demo["candidates"]}), 4)


if __name__ == "__main__":
    unittest.main()
