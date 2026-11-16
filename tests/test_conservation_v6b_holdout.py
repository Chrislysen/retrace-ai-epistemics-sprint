"""Prospective v6b corpus/scorer checks using constructed auditors only."""
import copy
import hashlib
import json
import unittest
from pathlib import Path

from scripts.evaluate_conservation_v6 import transformed_case, _rename
from scripts.evaluate_conservation_v6b import PUBLIC_SHA256, assess_gate, evaluate_holdout, source_alignment
from tests.test_conservation_v6_adapter import constructed_corpus, raw_empty

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def fixed_point(graph):
    values = {r["id"]: False for k in ("evidence", "claims", "decisions") for r in graph[k]}
    for _ in range(len(values) + 2):
        new = {}
        for r in graph["evidence"]:
            new[r["id"]] = r["active"] and (r["kind"] == "root" or all(values[p] for p in r["parents"]))
        for r in graph["claims"]:
            new[r["id"]] = any(all(values[p] for p in route) for route in r["supports"])
        for r in graph["decisions"]:
            new[r["id"]] = all(values[p] for p in r["requires"])
        if new == values:
            return {r["id"]: new[r["id"]] for r in graph["decisions"]}
        values = new
    raise AssertionError("Nonconvergent source fixture")


def alignment_fixture(kind):
    text = "Target T has the source group P and Q."
    annotation = {"kind": kind, "target_ids": ["T"], "referenced_ids": ["P", "Q"],
                  "source": {"document_id": "source", "start": 0, "end": len(text), "quote": text}}
    item = {"id": "o", "kind": "mandatory", "representation_type": "mandatory_conjunction", "status": "gap",
            "target_ids": ["T"], "referenced_ids": ["P", "Q"],
            "source_span": {"document_id": "source", "start": 0, "end": len(text), "text": text}}
    result = {"obligations": [item], "gaps": [item], "unresolved_cues": []}
    return annotation, result, {"source": text}


class ConservationV6bHoldoutTests(unittest.TestCase):
    def test_original_preserved_and_only_declared_evaluation_labels_change(self):
        original = read("data/conservation-v6b-holdout.json")
        reviewed = read("data/conservation-v6b-holdout-reviewed.json")
        amendment = read("data/conservation-v6b-annotation-amendment.json")
        self.assertEqual(hashlib.sha256((ROOT / "data/conservation-v6b-holdout.json").read_bytes()).hexdigest(),
                         "def8ce84d19c4d4af9dde71adc5e73a44599f3fe07c8c1b79e98665132dd09ef")
        self.assertEqual(hashlib.sha256((ROOT / amendment["reviewed_path"]).read_bytes()).hexdigest(), amendment["reviewed_sha256"])
        expected = copy.deepcopy(original)
        self.assertEqual(len(amendment["changes"]), 4)
        for change in amendment["changes"]:
            case = next(c for c in expected["cases"] if c["id"] == change["case_id"])
            annotation = case["evaluation"]["source_obligations"][change["annotation_index"]]
            self.assertEqual(annotation["kind"], change["before"])
            annotation["kind"] = change["after"]
        self.assertEqual(expected, reviewed)
        old_public = [c["public"] for c in original["cases"]]
        self.assertEqual(old_public, [c["public"] for c in reviewed["cases"]])
        self.assertEqual(hashlib.sha256(json.dumps(old_public, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), PUBLIC_SHA256)

    def test_eight_balanced_cases_exact_spans_and_current_unanimity(self):
        cases = read("data/conservation-v6b-holdout-reviewed.json")["cases"]
        self.assertEqual(len(cases), 8)
        self.assertEqual(sum(c["evaluation"]["semantic_omission"] for c in cases), 4)
        self.assertEqual(sum(len(c["evaluation"]["source_obligations"]) for c in cases), 15)
        self.assertEqual(sum(a["exact_edge_recovery_expected"] for c in cases for a in c["evaluation"]["source_obligations"]), 10)
        for case in cases:
            self.assertEqual(set(case["public"]), {"prose", "registry", "candidates"})
            documents = {d["id"]: d["text"] for d in case["public"]["prose"]}
            for a in case["evaluation"]["source_obligations"]:
                s = a["source"]
                self.assertEqual(documents[s["document_id"]][s["start"]:s["end"]], s["quote"])
            candidates = case["public"]["candidates"]
            first = fixed_point(candidates[0]["graph"])
            self.assertTrue(all(fixed_point(c["graph"]) == first for c in candidates))
        self.assertEqual(len(cases[-1]["public"]["candidates"]), 4)

    def test_metamorphic_source_and_decision_vectors_are_preserved(self):
        for case in read("data/conservation-v6b-holdout-reviewed.json")["cases"]:
            transformed = transformed_case(case)
            inverse = {v: k for k, v in case["evaluation"]["metamorphic"]["id_map"].items()}
            restored = _rename(transformed["public"], inverse)
            self.assertEqual({d["id"]: d["text"] for d in restored["prose"]}, {d["id"]: d["text"] for d in case["public"]["prose"]})
            originals = {c["id"]: c["graph"] for c in case["public"]["candidates"]}
            for candidate in restored["candidates"]:
                self.assertEqual(fixed_point(candidate["graph"]), fixed_point(originals[candidate["id"]]))

    def test_mandatory_inputs_do_not_claim_direct_transcription_recovery(self):
        annotation, result, documents = alignment_fixture("evidence_prerequisite")
        scored = source_alignment(annotation, result, documents)
        self.assertTrue(scored["aligned_declared_relation_gap"])
        self.assertTrue(scored["aligned_mandatory_dependency_group"])
        self.assertFalse(scored["aligned_direct_parent_relation"])
        annotation["kind"] = "copy_source"
        scored = source_alignment(annotation, result, documents)
        self.assertFalse(scored["aligned_declared_relation"])
        self.assertTrue(scored["aligned_source_implied_dependency_gap"])
        self.assertFalse(scored["aligned_direct_parent_relation"])

    def test_sufficient_alternative_is_not_a_mandatory_group(self):
        annotation, result, documents = alignment_fixture("sufficient_conjunction")
        self.assertFalse(source_alignment(annotation, result, documents)["aligned_source_implied_dependency_gap"])
        result["obligations"][0].update(kind="sufficient", representation_type="sufficient_conjunction")
        self.assertTrue(source_alignment(annotation, result, documents)["aligned_declared_relation_gap"])
        result["obligations"][0]["referenced_ids"] = ["P"]
        self.assertFalse(source_alignment(annotation, result, documents)["aligned_declared_relation_gap"])

    def test_public_only_constructed_calls_preserve_raw_outputs_and_denominators(self):
        data = constructed_corpus()
        data["cases"] = data["cases"][:8]
        calls = []
        def auditor(**kwargs):
            self.assertEqual(set(kwargs), {"prose", "candidates", "registry", "compilation"})
            self.assertIsNone(kwargs["compilation"])
            self.assertNotIn("evaluation", kwargs)
            calls.append(kwargs)
            return raw_empty()
        result = evaluate_holdout(data, auditor)
        self.assertEqual(len(calls), 16)
        self.assertEqual(result["base"]["scheduled"], 8)
        self.assertEqual(result["base"]["completed"], 8)
        self.assertEqual(result["metamorphic"]["semantic_profiles_invariant"], 8)
        self.assertTrue(all("unresolved_cues" not in row["raw_result"] for row in result["raw_audits"]))
        def failing(**kwargs):
            raise RuntimeError("constructed outage")
        failed = evaluate_holdout(data, failing)
        self.assertEqual(failed["base"]["auditor_failures"], 8)
        self.assertEqual(len(failed["raw_audits"]), 16)

    def test_declared_gate_rejects_no_detection_and_every_control_warning(self):
        data = constructed_corpus()
        data["cases"] = data["cases"][:8]
        for case in data["cases"][:4]:
            case["evaluation"]["semantic_omission"] = True
        result = evaluate_holdout(data, lambda **kwargs: raw_empty())
        declared = read("data/conservation-v6b-quality-gate.json")
        gate = assess_gate(result, declared, True)
        self.assertFalse(gate["passed"])
        self.assertFalse(gate["checks"]["positive_cases_with_annotation_aligned_structural_gap_at_least"])
        modified = copy.deepcopy(result)
        modified["source_alignment_base"].update(positive_cases_with_annotation_aligned_structural_gap=2,
                                                positive_cases_with_annotation_overlapping_gap_or_unresolved=3,
                                                controls_with_any_source_review_block=1)
        gate = assess_gate(modified, declared, True)
        self.assertFalse(gate["passed"])
        self.assertFalse(gate["checks"]["controls_with_any_source_review_block_at_most"])


if __name__ == "__main__":
    unittest.main()
