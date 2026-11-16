"""Corpus and scorer checks; deliberately no conservation recognizer imports."""
import copy
import hashlib
import json
import re
import unittest
from pathlib import Path

from scripts.evaluate_conservation_v6 import (
    CORPUS_SHA256, _rename, evaluate_case, evaluate_corpus, transformed_case,
)

ROOT = Path(__file__).resolve().parents[1]


def corpus():
    return json.loads((ROOT / "data/conservation-v6-cases.json").read_text(encoding="utf-8"))


def fixed_point(graph):
    values = {row["id"]: False for key in ("evidence", "claims", "decisions") for row in graph[key]}
    for _ in range(len(values) + 2):
        after = {}
        for row in graph["evidence"]:
            after[row["id"]] = row["active"] and (row["kind"] == "root" or all(values[parent] for parent in row["parents"]))
        for row in graph["claims"]:
            after[row["id"]] = any(all(values[item] for item in route) for route in row["supports"])
        for row in graph["decisions"]:
            after[row["id"]] = all(values[item] for item in row["requires"])
        if after == values:
            return {row["id"]: after[row["id"]] for row in graph["decisions"]}
        values = after
    raise AssertionError("Source fixture did not converge")


def canonical(graph):
    return (
        sorted((row["id"], row["kind"], row["active"], tuple(sorted(row["parents"]))) for row in graph["evidence"]),
        sorted((row["id"], tuple(sorted(tuple(sorted(route)) for route in row["supports"]))) for row in graph["claims"]),
        sorted((row["id"], tuple(sorted(row["requires"]))) for row in graph["decisions"]),
    )


def empty_result():
    return {"schema": "stub", "status": "no_gap_detected_in_recognized_cues",
            "obligations": [], "gaps": [], "unresolved_cues": [], "suppressed_cues": []}


class ConservationCorpusTests(unittest.TestCase):
    def test_locked_bytes_balanced_design_and_public_projection(self):
        path = ROOT / "data/conservation-v6-cases.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), CORPUS_SHA256)
        data = corpus()
        self.assertEqual(len(data["cases"]), 12)
        self.assertEqual(sum(row["evaluation"]["semantic_omission"] for row in data["cases"]), 6)
        self.assertEqual(sum(len(row["evaluation"]["source_obligations"]) for row in data["cases"]), 17)
        for row in data["cases"]:
            self.assertEqual(set(row["public"]), {"prose", "candidates", "registry"})
            self.assertTrue(row["evaluation"]["fictional"])
            self.assertNotIn("evaluation", json.dumps(row["public"]))

    def test_exact_annotation_spans_and_opaque_id_maps(self):
        for case in corpus()["cases"]:
            public, expected = case["public"], case["evaluation"]
            documents = {doc["id"]: doc["text"] for doc in public["prose"]}
            for obligation in expected["source_obligations"]:
                source = obligation["source"]
                self.assertEqual(documents[source["document_id"]][source["start"]:source["end"]], source["quote"])
            ids = [item for group in public["registry"].values() for item in group]
            mapping = expected["metamorphic"]["id_map"]
            self.assertEqual(set(mapping), set(ids))
            self.assertEqual(len(set(mapping.values())), len(ids))
            self.assertFalse(set(mapping) & set(mapping.values()))
            self.assertTrue(all(re.fullmatch(r"[A-Z2-9]{7}", item) for item in ids + list(mapping.values())))

    def test_candidate_graphs_are_valid_unanimous_and_do_not_supply_gold(self):
        for case in corpus()["cases"]:
            public = case["public"]
            graphs = [candidate["graph"] for candidate in public["candidates"]]
            previous = None
            for graph in graphs:
                categories = {category: {row["id"] for row in graph[category]} for category in graph}
                self.assertEqual(sum(map(len, categories.values())), len(set.union(*categories.values())))
                if previous is not None:
                    self.assertEqual(categories, previous)
                previous = categories
                for row in graph["evidence"]:
                    self.assertIs(type(row["active"]), bool)
                    self.assertLessEqual(set(row["parents"]), categories["evidence"])
                    self.assertEqual(row["kind"] == "root", not row["parents"])
                for row in graph["claims"]:
                    for route in row["supports"]:
                        self.assertLessEqual(set(route), categories["evidence"] | categories["claims"])
                for row in graph["decisions"]:
                    self.assertLessEqual(set(row["requires"]), categories["claims"])
                self.assertEqual(fixed_point(graph), fixed_point(graphs[0]))
            self.assertEqual(canonical(graphs[0]) == canonical(graphs[1]), case["id"] != "conservation-v6-12")
        rows = corpus()["cases"]
        self.assertFalse(next(iter(fixed_point(rows[6]["public"]["candidates"][0]["graph"]).values())))

    def test_manual_missing_relations_and_faithful_controls(self):
        cases = corpus()["cases"]
        # A missing named source differs from IDs present without lineage.
        second = cases[1]["public"]
        self.assertEqual(len(second["registry"]["evidence"]) - len(second["candidates"][0]["graph"]["evidence"]), 1)
        third = cases[2]["public"]["candidates"][0]["graph"]
        self.assertEqual(len(third["evidence"]), len(cases[2]["public"]["registry"]["evidence"]))
        self.assertTrue(all(row["kind"] == "root" for row in third["evidence"]))
        fourth = cases[3]["public"]["candidates"][0]["graph"]
        self.assertEqual([len(route) for route in fourth["claims"][0]["supports"]], [1, 1])
        fifth = cases[4]["public"]["candidates"][0]["graph"]
        self.assertEqual([row["kind"] for row in fifth["evidence"]], ["root", "root", "copy"])
        sixth = cases[5]["public"]["candidates"][0]["graph"]
        self.assertEqual((len(sixth["claims"]), len(sixth["decisions"][0]["requires"])), (2, 1))
        faithful = cases[7]["public"]["candidates"][0]["graph"]
        self.assertEqual([len(route) for route in faithful["claims"][0]["supports"]], [2])
        self.assertEqual(cases[0]["evaluation"]["source_obligations"][0]["desired_disposition"], "review_unresolved")
        self.assertFalse(cases[0]["evaluation"]["source_obligations"][0]["exact_edge_recovery_expected"])

    def test_metamorphic_transform_preserves_source_and_graph_semantics(self):
        for case in corpus()["cases"]:
            saved = copy.deepcopy(case)
            transformed = transformed_case(case)
            inverse = {value: key for key, value in case["evaluation"]["metamorphic"]["id_map"].items()}
            restored = _rename(transformed["public"], inverse)
            self.assertEqual(case, saved)
            self.assertEqual({doc["id"]: doc["text"] for doc in restored["prose"]},
                             {doc["id"]: doc["text"] for doc in case["public"]["prose"]})
            before = {candidate["id"]: candidate["graph"] for candidate in case["public"]["candidates"]}
            for candidate in restored["candidates"]:
                self.assertEqual(canonical(candidate["graph"]), canonical(before[candidate["id"]]))
                self.assertEqual(fixed_point(candidate["graph"]), fixed_point(before[candidate["id"]]))
            documents = {doc["id"]: doc["text"] for doc in transformed["public"]["prose"]}
            for annotation in transformed["evaluation"]["source_obligations"]:
                span = annotation["source"]
                self.assertEqual(documents[span["document_id"]][span["start"]:span["end"]], span["quote"])

    def test_scorer_calls_only_public_arguments_and_never_inserts_a_reference(self):
        data = corpus()
        saved = copy.deepcopy(data)
        calls = []
        def auditor(**kwargs):
            self.assertEqual(set(kwargs), {"prose", "candidates", "registry", "compilation"})
            self.assertIsNone(kwargs["compilation"])
            self.assertEqual(len(kwargs["candidates"]), 2)
            self.assertNotIn("semantic_omission", json.dumps(kwargs))
            self.assertNotIn("desired_disposition", json.dumps(kwargs))
            calls.append(kwargs)
            kwargs["candidates"].clear()  # The detector cannot mutate the corpus.
            return empty_result()
        result = evaluate_corpus(data, auditor)
        self.assertEqual(data, saved)
        self.assertEqual(len(calls), 24)
        self.assertEqual(result["base"]["semantic_omission_cases"]["scheduled"], 6)
        self.assertEqual(result["base"]["semantic_omission_cases"]["cases_with_either"], 0)
        self.assertEqual(result["metamorphic"]["semantic_profiles_invariant"], 12)

    def test_unresolved_is_not_automatic_exact_recovery_or_gap_success(self):
        case = corpus()["cases"][5]
        span = case["evaluation"]["source_obligations"][0]["source"]
        item = {"id": "u", "kind": "unparsed_structural_cue", "status": "unresolved", "representation_type": "unresolved",
                "source_span": {"document_id": span["document_id"], "start": span["start"], "end": span["end"], "text": span["quote"]}}
        response = {**empty_result(), "status": "unresolved", "obligations": [item], "unresolved_cues": [item]}
        row = evaluate_case(case, lambda **kwargs: response)
        self.assertTrue(row["has_unresolved_review"])
        self.assertFalse(row["has_structural_gap"])
        self.assertFalse(row["annotation_results"][0]["recognized_annotated_relation_or_node"])
        self.assertEqual(row["annotation_results"][0]["overlapping_unresolved_count"], 1)

    def test_exact_alignment_requires_kind_ids_and_valid_source_citation(self):
        case = corpus()["cases"][5]
        annotation = case["evaluation"]["source_obligations"][0]
        span = annotation["source"]
        item = {"id": "g", "kind": "mandatory", "status": "gap", "representation_type": "mandatory_conjunction",
                "target_ids": annotation["target_ids"], "referenced_ids": annotation["referenced_ids"],
                "represented_candidate_ids": [], "representations": [],
                "source_span": {"document_id": span["document_id"], "start": span["start"], "end": span["end"], "text": span["quote"]}}
        for mutation, expected in ((None, True), ("kind", False), ("ids", False), ("quote", False)):
            changed = copy.deepcopy(item)
            if mutation == "kind":
                changed["representation_type"] = "sufficient_conjunction"
            elif mutation == "ids":
                changed["referenced_ids"] = changed["referenced_ids"][:1]
            elif mutation == "quote":
                changed["source_span"]["text"] = "fabricated citation"
            response = {**empty_result(), "status": "gap_detected", "obligations": [changed], "gaps": [changed]}
            row = evaluate_case(case, lambda **kwargs: response)
            self.assertEqual(row["annotation_results"][0]["aligned_gap_reported"], expected)
            self.assertEqual(row["every_returned_citation_valid"], mutation != "quote")

    def test_failures_preserve_base_and_paired_denominators(self):
        def failing(**kwargs):
            raise ValueError("intentionally unavailable")
        result = evaluate_corpus(corpus(), failing)
        self.assertEqual(result["base"]["scheduled"], 12)
        self.assertEqual(result["base"]["auditor_failures"], 12)
        self.assertEqual(result["base"]["scheduled_annotations"], 17)
        self.assertEqual(result["base"]["scheduled_node_presence_annotations"], 1)
        self.assertEqual(result["base"]["scheduled_exact_relation_annotations"], 9)
        self.assertEqual(result["base"]["semantic_omission_cases"]["scheduled"], 6)
        self.assertEqual(result["base"]["controls"]["scheduled"], 6)
        self.assertEqual(result["metamorphic"], {"scheduled_pairs": 12, "both_completed": 0, "semantic_profiles_invariant": 0})
        self.assertTrue(all(row["semantic_profiles_invariant"] is None for row in result["metamorphic_pairs"]))


if __name__ == "__main__":
    unittest.main()
