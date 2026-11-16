"""Offline corpus integrity, independent truth tables and source-IR checks.

These checks cannot establish that English entails the authored graphs. The
separate public-first source review is required before the study is frozen.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import itertools
import json
from pathlib import Path
import re
import unittest

from retrace.core import analyze, validate_case
from retrace.source_ir_v6c import compile_source_ir
from scripts.build_frontier_v6c_cases import build_corpus, FAMILIES, PHASES

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/frontier-v6c-staged.json"


def canonical(graph):
    normalized = {}
    for category in ("evidence", "claims", "decisions"):
        rows = copy.deepcopy(graph[category])
        for row in rows:
            if category == "evidence": row["parents"].sort()
            elif category == "claims": row["supports"] = sorted(sorted(route) for route in row["supports"])
            else: row["requires"].sort()
        normalized[category] = sorted(rows, key=lambda row: row["id"])
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def truth_tables(graph):
    """All withdrawal states, recursive bitsets independent of builder gold."""
    evidence = sorted(row["id"] for row in graph["evidence"])
    position = {identifier: n for n, identifier in enumerate(evidence)}
    width = 1 << len(evidence)
    universe = (1 << width) - 1
    nodes = {row["id"]: (category, row) for category in graph for row in graph[category]}
    cache = {}

    def visit(identifier):
        if identifier in cache: return cache[identifier]
        category, row = nodes[identifier]
        if category == "evidence":
            bits = sum(1 << mask for mask in range(width) if not mask & (1 << position[identifier])) if row["active"] else 0
            for parent in row["parents"]: bits &= visit(parent)
        elif category == "claims":
            bits = 0
            for clause in row["supports"]:
                route = universe
                for parent in clause: route &= visit(parent)
                bits |= route
        else:
            bits = universe
            for parent in row["requires"]: bits &= visit(parent)
        cache[identifier] = bits
        return bits

    for identifier in nodes: visit(identifier)
    return evidence, cache


def excluded(case, state):
    return set(state["revoked_passages"]) | {
        eid for doc in case["events"]["document_groups"] if doc["id"] in state["revoked_documents"] for eid in doc["evidence_ids"]
    }


class FrontierV6cCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        cls.cases = cls.corpus["cases"]

    def test_deterministic_authoring_and_archived_first_draft(self):
        authored = json.loads(json.dumps(build_corpus()))
        self.assertEqual(authored, self.corpus)
        draft = ROOT / "data/frontier-v6c-draft-before-source-audit.json"
        self.assertEqual(hashlib.sha256(draft.read_bytes()).hexdigest(), "307e0358faf07159e000abde0d48f04ea45e195f337b28aae2424d6ee2acb426")
        old = json.loads(draft.read_text(encoding="utf-8"))
        self.assertEqual([c["evaluation"]["source_family"] for c in old["cases"]], [c["evaluation"]["source_family"] for c in self.cases])

    def test_balanced_cases_seed_counts_and_long_subset(self):
        self.assertEqual(len(self.cases), 48)
        self.assertEqual(Counter(c["family"] for c in self.cases), {family: 8 for family in FAMILIES})
        self.assertEqual(len(self.corpus["long_context_subset_ids"]), 24)
        for family in FAMILIES:
            rows = [c for c in self.cases if c["family"] == family]
            self.assertEqual(Counter(c["evaluation"]["seed_kind"] for c in rows), {"deficient": 4, "faithful_complete": 4})
            selected = [c for c in rows if c["long_context_selected"]]
            self.assertEqual(Counter(c["evaluation"]["seed_kind"] for c in selected), {"deficient": 2, "faithful_complete": 2})
        for position in range(1, 9):
            self.assertEqual(Counter(c["evaluation"]["seed_kind"] for c in self.cases if c["within_family_index"] == position), {"deficient": 3, "faithful_complete": 3})
        for case in self.cases:
            self.assertEqual(len(case["authored_seed_pool"]["candidates"]), max(2, len(case["evaluation"]["source_family"])))
            self.assertEqual([x["id"] for x in case["authored_seed_pool"]["candidates"]], [f"authored-seed-{n+1:02d}" for n in range(len(case["authored_seed_pool"]["candidates"]))])

    def test_main_public_projection_has_no_gold_or_control_labels(self):
        forbidden = {"source_family", "reference_ir", "state_gold", "seed_kind", "source_recipe", "semantic_key_ids", "evaluation", "authored_seed_pool", "family"}
        all_identifiers = set()
        for case in self.cases:
            self.assertEqual(set(case["public"]), {"source_documents", "registry"})
            def check_keys(value):
                if isinstance(value, dict):
                    self.assertFalse(set(value) & forbidden)
                    for item in value.values(): check_keys(item)
                elif isinstance(value, list):
                    for item in value: check_keys(item)
            check_keys(case["public"])
            text = json.dumps(case["public"], ensure_ascii=False)
            for forbidden_text in (case["id"], case["family"], "protected summary", "authored-seed", "counterfactual", "benchmark"):
                self.assertNotIn(forbidden_text, text)
            for doc in case["public"]["source_documents"]:
                self.assertRegex(doc["id"], r"^doc[0-9a-f]{18}$")
            for category in case["public"]["registry"]:
                for identifier in case["public"]["registry"][category]:
                    self.assertRegex(identifier, r"^[A-HJ-NP-Z2-9]{8}$")
                    self.assertNotIn(identifier, all_identifiers)
                    all_identifiers.add(identifier)

    def test_every_graph_is_typed_acyclic_explicit_and_bounded(self):
        total = 0
        for case in self.cases:
            public = case["public"]; all_text = "\n".join(d["text"] for d in public["source_documents"])
            for identifier in itertools.chain.from_iterable(public["registry"].values()):
                self.assertRegex(all_text, r"(?<![A-Za-z0-9])" + re.escape(identifier) + r"(?![A-Za-z0-9])")
            for row in case["evaluation"]["source_family"] + case["authored_seed_pool"]["candidates"]:
                graph = row["graph"]; validate_case(graph)
                for category in public["registry"]:
                    self.assertEqual(set(public["registry"][category]), {n["id"] for n in graph[category]})
                for node in graph["evidence"]: self.assertEqual(set(node), {"id", "kind", "active", "parents"})
                for node in graph["claims"]: self.assertEqual(set(node), {"id", "supports"})
                for node in graph["decisions"]: self.assertEqual(set(node), {"id", "requires"})
                self.assertLessEqual(len(graph["evidence"]), 12)
                self.assertLessEqual(sum(n["kind"] == "root" for n in graph["evidence"]), 8)
            total += len(case["evaluation"]["source_family"])
        self.assertEqual(total, 201)

    def test_source_citations_and_cross_sentence_bindings_are_exact(self):
        for case in self.cases:
            docs = {d["id"]: d["text"] for d in case["public"]["source_documents"]}
            def walk(value):
                if isinstance(value, dict):
                    if {"document_id", "quote"} <= set(value):
                        source = docs[value["document_id"]]
                        if "start" in value: self.assertEqual(source[value["start"]:value["end"]], value["quote"])
                        else: self.assertEqual(source.count(value["quote"]), 1)
                    for item in value.values(): walk(item)
                elif isinstance(value, list):
                    for item in value: walk(item)
            walk(case["evaluation"]["reference_ir"])
            walk(case["evaluation"]["grounded_citations"])
            ir = case["evaluation"]["reference_ir"]
            self.assertEqual(len(ir["bindings"]), 1)
            self.assertTrue(any(p["scope"] == "current" and p["polarity"] == "deny" for p in ir["propositions"]))
            self.assertEqual(sum(p["scope"] != "current" for p in ir["propositions"]), 1)
            binding = ir["bindings"][0]
            self.assertIn(binding["entity"], binding["antecedent"]["quote"])
            self.assertNotIn(binding["entity"], binding["mention"]["quote"])

    def test_all_binary_worlds_are_preserved_and_high_u_is_exposed(self):
        high = [c for c in self.cases if c["family"] == "high_multiplicity"]
        self.assertEqual(Counter(c["evaluation"]["uncertainty_count"] for c in high), {3: 2, 4: 3, 5: 3})
        for case in self.cases:
            evaluation = case["evaluation"]; u = evaluation["uncertainty_count"]
            self.assertEqual(len(evaluation["source_family"]), 2 ** u)
            self.assertEqual(len({canonical(x["graph"]) for x in evaluation["source_family"]}), 2 ** u)
            self.assertEqual(len({json.dumps(x["assignment"], sort_keys=True) for x in evaluation["source_family"]}), 2 ** u)
            if u > 1:
                text = " ".join(c["quote"] for c in evaluation["reference_ir"]["combination"]["citations"])
                self.assertIn("every combination", text)
                self.assertIn("no hidden coupling", text)
        for case in high:
            e = case["evaluation"]; did = e["semantic_key_ids"]["decision_main"]
            self.assertEqual(e["state_gold"]["initial"]["decision_consensus"][did], "supported")
            self.assertEqual(e["state_gold"]["withdrawn"]["decision_consensus"][did], "disputed")

    def test_reference_ir_compiles_to_exact_authored_families_without_source_mutation(self):
        for case in self.cases:
            ir = case["evaluation"]["reference_ir"]; public = case["public"]
            before = copy.deepcopy((ir, public))
            compiled = compile_source_ir(ir, public["source_documents"], public["registry"])
            self.assertEqual(compiled["status"], "compiled", case["id"])
            self.assertEqual(compiled["candidate_count"], len(case["evaluation"]["source_family"]))
            self.assertEqual(Counter(canonical(x["graph"]) for x in compiled["candidates"]), Counter(canonical(x["graph"]) for x in case["evaluation"]["source_family"]), case["id"])
            self.assertEqual((ir, public), before)

    def test_gold_matches_independent_exhaustive_tables_and_frozen_core(self):
        for case in self.cases:
            for reading in case["evaluation"]["source_family"]:
                evidence, table = truth_tables(reading["graph"])
                position = {identifier: n for n, identifier in enumerate(evidence)}
                for name, state in case["events"]["states"].items():
                    vetoes = excluded(case, state); mask = sum(1 << position[x] for x in vetoes)
                    actual = {identifier: bool(bits & (1 << mask)) for identifier, bits in table.items()}
                    gold = case["evaluation"]["state_gold"][name]["candidate_states"][reading["id"]]
                    self.assertEqual(gold["all_nodes"], actual)
                    core = analyze(reading["graph"], sorted(vetoes))
                    self.assertEqual(actual, {identifier: node["usable"] for category in ("evidence", "claims", "decisions") for identifier, node in core[category].items()})

    def test_state_transitions_restore_only_named_vetoes_and_never_local_flags(self):
        for case in self.cases:
            states = case["events"]["states"]; initial, withdrawn, restored = [states[x] for x in ("initial", "withdrawn", "restored")]
            event, restore = case["events"]["withdrawal"], case["events"]["restoration"]
            for field, add, clear in (("revoked_documents", "add_document_vetoes", "clear_document_vetoes"), ("revoked_passages", "add_passage_vetoes", "clear_passage_vetoes")):
                self.assertEqual(set(withdrawn[field]), set(initial[field]) | set(event[add]))
                self.assertTrue(set(restore[clear]) <= set(withdrawn[field]))
                self.assertEqual(set(restored[field]), set(withdrawn[field]) - set(restore[clear]))
            self.assertTrue(restored["revoked_documents"] or restored["revoked_passages"])
            self.assertNotEqual(withdrawn, restored)
            for phase, name in PHASES.items(): self.assertEqual(case["phases"][phase], {"state_name": name, "state": states[name]})
            eid = case["evaluation"]["semantic_key_ids"]["dead"]
            for reading in case["evaluation"]["source_family"]:
                self.assertFalse(next(n for n in reading["graph"]["evidence"] if n["id"] == eid)["active"])
                for state in case["evaluation"]["state_gold"].values(): self.assertFalse(state["candidate_states"][reading["id"]]["all_nodes"][eid])

    def test_faithful_and_deficient_seeds_are_classified_by_unique_graph_sets(self):
        for case in self.cases:
            supplied = {canonical(x["graph"]) for x in case["authored_seed_pool"]["candidates"]}
            source = {canonical(x["graph"]) for x in case["evaluation"]["source_family"]}
            if case["evaluation"]["seed_kind"] == "faithful_complete": self.assertEqual(supplied, source)
            else: self.assertNotEqual(supplied, source, case["id"])
            active = {n["id"]: n["active"] for n in case["evaluation"]["source_family"][0]["graph"]["evidence"]}
            for seed in case["authored_seed_pool"]["candidates"]: self.assertEqual(active, {n["id"]: n["active"] for n in seed["graph"]["evidence"]})

    def test_dormant_defects_are_masked_initially_and_exposed_by_partial_restoration(self):
        for case in self.cases:
            if case["family"] != "dormant_prerequisite_masking" or case["evaluation"]["seed_kind"] != "deficient": continue
            e = case["evaluation"]; did = e["semantic_key_ids"]["decision_main"]
            graph = case["authored_seed_pool"]["candidates"][0]["graph"]
            for name in ("initial", "withdrawn"):
                actual = analyze(graph, sorted(excluded(case, case["events"]["states"][name])))["decisions"][did]["usable"]
                self.assertFalse(actual)
                self.assertEqual(e["state_gold"][name]["decision_consensus"][did], "unsupported")
            actual = analyze(graph, sorted(excluded(case, case["events"]["states"]["restored"])))["decisions"][did]["usable"]
            self.assertFalse(actual)
            self.assertEqual(e["state_gold"]["restored"]["decision_consensus"][did], "supported")

    def test_control_decisions_and_partial_multiparent_lock_examples(self):
        for case in self.cases:
            e = case["evaluation"]; ids = e["semantic_key_ids"]
            for state in e["state_gold"].values():
                self.assertEqual(state["decision_consensus"][ids["decision_stable"]], "supported")
                self.assertEqual(state["decision_consensus"][ids["decision_protected"]], "supported")
                self.assertEqual(state["decision_consensus"][ids["decision_unavailable"]], "unsupported")
            self.assertNotEqual(e["state_gold"]["withdrawn"]["decision_consensus"][ids["decision_auxiliary"]], e["state_gold"]["restored"]["decision_consensus"][ids["decision_auxiliary"]])
        rows = [c for c in self.cases if c["family"] == "partial_multiparent_restoration"]
        grouped = rows[4]
        self.assertEqual(sorted(len(g["evidence_ids"]) for g in grouped["events"]["document_groups"]).count(2), 1)
        overlap = rows[7]; ids = overlap["evaluation"]["semantic_key_ids"]
        self.assertEqual(overlap["events"]["states"]["restored"]["revoked_documents"], [])
        self.assertIn(ids["a"], overlap["events"]["states"]["restored"]["revoked_passages"])
        self.assertEqual(overlap["evaluation"]["state_gold"]["restored"]["decision_consensus"][ids["decision_main"]], "unsupported")


if __name__ == "__main__":
    unittest.main()
