import copy
import json
import unittest

from retrace.prose_eval import canonical_graph, gold_for, parse_extracted_graph, parse_json, score_prose


def fixture():
    return {"id": "heldout-a", "family": "mixed", "case": {
        "id": "heldout-a", "evidence": [
            {"id": "r-a", "kind": "root", "active": True},
            {"id": "r-b", "kind": "root", "active": True},
            {"id": "r-u", "kind": "root", "active": True},
            {"id": "r-x", "kind": "root", "active": False},
            {"id": "p-z", "kind": "copy", "parents": ["r-a"], "active": True}],
        "claims": [
            {"id": "c-p", "supports": [["p-z"], ["r-b"]]},
            {"id": "c-l", "supports": [["p-z"]]},
            {"id": "c-u", "supports": [["r-u"]]},
            {"id": "c-x", "supports": [["r-x"]]}],
        "decisions": [
            {"id": "d-p", "requires": ["c-p"]},
            {"id": "d-l", "requires": ["c-l"]},
            {"id": "d-u", "requires": ["c-u"]},
            {"id": "d-x", "requires": ["c-x"]}],
        "revoke": ["r-a"]}}


def record(condition="prose_fresh", phase="final", predictions=None, text=None, **kwargs):
    return {"case_id": "heldout-a", "condition": condition, "phase": phase,
            "output_text": text if text is not None else json.dumps({"decisions": predictions or {"d-p": True, "d-l": False, "d-u": True, "d-x": False}}),
            **kwargs}


class ProseScoreTests(unittest.TestCase):
    def test_eligibility_separates_newly_lost_protected_unrelated_and_preunsupported(self):
        gold = gold_for(fixture())
        self.assertEqual(gold["lost"], {"d-l"})
        self.assertEqual(gold["protected"], {"d-p"})
        self.assertEqual(gold["unaffected_supported"], {"d-u"})
        self.assertEqual(gold["initially_unsupported"], {"d-x"})
        copy_node = next(node for node in gold["final_graph"]["evidence"] if node["id"] == "p-z")
        self.assertTrue(copy_node["active"])

    def test_fences_are_prespecified_semantic_acceptance_but_strict_failure(self):
        row = record()
        row["output_text"] = "```json\n" + row["output_text"] + "\n```"
        group = score_prose([fixture()], [row], bootstrap_repeats=20)["groups"]["prose_fresh/final"]
        self.assertEqual((group["strict_valid"], group["semantic_valid"], group["exact"]), (0, 1, 1))
        self.assertEqual(group["outer_fences_removed"], 1)
        self.assertIsNone(group["graph_exact_rate_all_scheduled"])

    def test_no_fence_or_json_repair(self):
        good = record()["output_text"]
        bad = ["Answer: " + good, "```json\n" + good + "\n```\nextra",
               "```json\n" + good + "\n```\n```json\n" + good + "\n```",
               '{"decisions":{"d-p":true,"d-p":false}}']
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_json(text)

    def test_missing_and_operational_errors_do_not_become_reasoning_errors(self):
        row = record(error="timeout", response_status=None)
        group = score_prose([fixture()], [row], bootstrap_repeats=20)["groups"]["prose_fresh/final"]
        self.assertEqual(group["operational_failures"], 1)
        self.assertEqual(group["decision_errors_all_scheduled"], 4)
        self.assertEqual(group["decision_targets_valid"], 0)
        self.assertIsNone(group["missed_retraction_rate_valid_only"])

    def test_selective_metrics_do_not_dilute_with_unaffected_controls(self):
        row = record(predictions={"d-p": False, "d-l": True, "d-u": True, "d-x": False})
        group = score_prose([fixture()], [row], bootstrap_repeats=20)["groups"]["prose_fresh/final"]
        self.assertEqual(group["missed_retraction_rate_valid_only"], 1)
        self.assertEqual(group["protected_collateral_rate_valid_only"], 1)
        self.assertEqual(group["unaffected_error_rate_valid_only"], 0)

    def test_extraction_canonicalization_ignores_order_and_labels(self):
        gold = gold_for(fixture())["final_graph"]
        prediction = copy.deepcopy(gold)
        for category in prediction:
            prediction[category].reverse()
            for node in prediction[category]:
                node["label"] = "Different harmless wording"
        prediction["claims"][-1]["supports"].reverse()
        parsed = parse_extracted_graph(json.dumps(prediction), gold)
        self.assertTrue(parsed["graph_exact"])
        self.assertEqual(parsed["predictions"], gold_for(fixture())["final"])

    def test_graph_logic_scored_separately_from_ungrouped_edges(self):
        gold = gold_for(fixture())["final_graph"]
        altered = copy.deepcopy(gold)
        altered["claims"][0]["supports"] = [["p-z", "r-b"]]
        parsed = parse_extracted_graph(json.dumps(altered), gold)
        self.assertFalse(parsed["graph_exact"])
        self.assertFalse(parsed["predictions"]["d-p"])
        self.assertEqual(parsed["edge_false_positive"], 0)
        self.assertEqual(parsed["edge_false_negative"], 0)

    def test_extracted_graph_cannot_add_ids_or_cycles_or_unauthorized_fields(self):
        gold = gold_for(fixture())["final_graph"]
        variants = []
        extra = copy.deepcopy(gold); extra["claims"].append({"id": "invented", "supports": []}); variants.append(extra)
        cycle = copy.deepcopy(gold); cycle["claims"][0]["supports"] = [["c-p"]]; variants.append(cycle)
        field = copy.deepcopy(gold); field["evidence"][0]["trusted"] = True; variants.append(field)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_extracted_graph(json.dumps(value), gold)

    def test_extraction_is_evaluated_from_predicted_not_gold_structure(self):
        gold = gold_for(fixture())["final_graph"]
        wrong = copy.deepcopy(gold)
        wrong["claims"][0]["supports"] = [["p-z"]]
        row = record(condition="prose_extract", text=json.dumps(wrong))
        group = score_prose([fixture()], [row], bootstrap_repeats=20)["groups"]["prose_extract/final"]
        self.assertEqual(group["semantic_valid"], 1)
        self.assertEqual(group["exact"], 0)
        self.assertEqual(group["protected_collateral_errors"], 1)
        self.assertEqual(group["graph_exact"], 0)

    def test_paired_deltas_retain_case_and_missing_denominators(self):
        rows = [record(condition="formal_fresh"), record(condition="prose_fresh", predictions={"d-p": False,"d-l":False,"d-u":True,"d-x":False})]
        report = score_prose([fixture()], rows, bootstrap_repeats=20)
        contrast = report["contrasts"][0]
        self.assertEqual(contrast["base_cases"], 1)
        self.assertEqual(contrast["both_valid_cases"], 1)
        self.assertEqual(contrast["mean_accuracy_delta_all_scheduled"], -.25)
        self.assertEqual(contrast["case_bootstrap_stability_interval_95"], [-.25, -.25])

    def test_duplicate_cases_records_and_mixed_models_rejected(self):
        with self.assertRaises(ValueError): score_prose([fixture(), fixture()], [])
        with self.assertRaises(ValueError): score_prose([fixture()], [record(), record()])
        with self.assertRaises(ValueError): score_prose([fixture()], [record(model="a"), record(condition="formal_fresh", model="b")])

    def test_empty_corpus_has_no_fabricated_performance(self):
        report = score_prose([], [])
        self.assertEqual(report["groups"], {})
        self.assertIsNone(report["contrasts"][0]["mean_accuracy_delta_all_scheduled"])


if __name__ == "__main__":
    unittest.main()
