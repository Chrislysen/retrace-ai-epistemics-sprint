"""Prospective prompt-contract checks with invented EX fixtures; no model calls."""
from copy import deepcopy
import json
import unittest

from retrace.core import analyze
from retrace.source_ir_v6c import SourceIRError
from retrace.source_ir_v6d import compile_cited_ir, source_segments
from retrace.source_ir_v6g_prompt import CONTRACT, IR_V6G_INSTRUCTIONS, binding_example


def add(ir, kind, target, body, **extra):
    row = {"id": "test-p" + str(len(ir["propositions"])), "kind": kind, "target": target,
           "body": body, "scope": "current", "polarity": "assert", "when": {},
           "citations": ir["entities"][0]["citations"], "bindings": []}
    row.update(extra)
    ir["propositions"].append(row)
    return row


def row(ir, kind, target):
    return next(p for p in ir["propositions"] if p["kind"] == kind and p["target"] == target)


def recite(documents, ir, index, text):
    old = source_segments(documents)[index]["span_id"]
    documents[index]["text"] = text
    new = source_segments(documents)[index]["span_id"]
    def walk(value):
        if isinstance(value, dict): return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list): return [walk(v) for v in value]
        return new if value == old else value
    return walk(ir)


def choices_fixture():
    docs, registry, ir = binding_example()
    ir = recite(docs, ir, 1, "EXC has two possible complete direct-input readings: EXA alone or EXB alone. "
                 "EXR likewise accepts EXC alone or EXB alone; all four combinations are admitted independently. "
                 "EXD requires EXR. This certificate is the EXC named earlier.")
    cite = [source_segments(docs)[1]["span_id"]]
    ir["choices"] = [{"id": name, "options": ["left", "right"], "citations": cite} for name in ("EX-u", "EX-v")]
    ir["combination"]["citations"] = cite
    origin = row(ir, "origin", "EXC"); origin["when"] = {"EX-u": "left"}; origin["body"]["parents"] = ["EXA"]
    add(ir, "origin", "EXC", {"kind": "copy", "parents": ["EXB"]}, when={"EX-u": "right"}, citations=cite)
    support = row(ir, "support", "EXR"); support["when"] = {"EX-v": "left"}
    add(ir, "support", "EXR", {"expr": {"ref": "EXB"}}, when={"EX-v": "right"}, citations=cite)
    return docs, registry, ir


class SourceIRV6GPromptTests(unittest.TestCase):
    def test_complete_model_visible_binding_example_compiles_without_mutation(self):
        docs, registry, ir = binding_example(); before = deepcopy((docs, registry, ir))
        result = compile_cited_ir(ir, docs, registry)
        self.assertEqual(result["status"], "compiled")
        self.assertEqual(result["candidate_count"], 1)
        graph = result["candidates"][0]["graph"]
        self.assertEqual(next(n["parents"] for n in graph["evidence"] if n["id"] == "EXC"), ["EXA", "EXB"])
        self.assertFalse(analyze(graph)["decisions"]["EXD"]["usable"])
        self.assertEqual(row(ir, "origin", "EXC")["bindings"], ["EX-bind-cert"])
        self.assertEqual((docs, registry, ir), before)
        self.assertIn(json.dumps(ir, ensure_ascii=False, separators=(",", ":")), IR_V6G_INSTRUCTIONS)
        self.assertNotIn('"kind":"dependency"', json.dumps(ir, separators=(",", ":")))

    def test_every_dependency_predicate_and_both_polarities(self):
        docs, registry, ir = binding_example()
        for relation, target, refs in [("parent", "EXC", ["EXA", "EXB"]), ("ancestor", "EXC", ["EXA"]),
                                       ("necessary", "EXD", ["EXA", "EXR"]), ("sufficient_route", "EXR", ["EXC"])]:
            add(ir, "dependency", target, {"relation": relation, "refs": refs})
        for relation, target, refs in [("parent", "EXA", ["EXB"]), ("ancestor", "EXA", ["EXB"]),
                                       ("necessary", "EXA", ["EXB"]), ("sufficient_route", "EXR", ["EXA", "EXB"])]:
            add(ir, "dependency", target, {"relation": relation, "refs": refs}, polarity="deny")
        checks = compile_cited_ir(ir, docs, registry)["worlds"][0]["constraint_checks"]
        self.assertEqual(len(checks), 8)
        self.assertTrue(all(x["status"] == "verified" for x in checks))

    def test_relation_target_and_reference_types_remain_strict(self):
        forbidden = [("sufficient_route", "EXC", ["EXA"]), ("sufficient_route", "EXD", ["EXR"]),
                     ("parent", "EXR", ["EXA"]), ("ancestor", "EXD", ["EXA"]),
                     ("parent", "EXC", ["EXR"]), ("necessary", "EXR", ["EXD"])]
        for relation, target, refs in forbidden:
            with self.subTest(relation=relation, target=target, refs=refs):
                docs, registry, ir = binding_example()
                add(ir, "dependency", target, {"relation": relation, "refs": refs}, polarity="deny", scope="historical")
                with self.assertRaises(SourceIRError): compile_cited_ir(ir, docs, registry)

    def test_exact_direct_clause_is_not_upstream_or_superset_sufficiency(self):
        for refs in (["EXA", "EXB"], ["EXC", "EXA"]):
            docs, registry, ir = binding_example()
            prop = add(ir, "dependency", "EXR", {"relation": "sufficient_route", "refs": refs})
            with self.assertRaisesRegex(SourceIRError, "constraint_conflict"): compile_cited_ir(ir, docs, registry)
            prop["polarity"] = "deny"
            self.assertEqual(compile_cited_ir(ir, docs, registry)["status"], "compiled")

    def test_parent_and_transitive_ancestor_differ(self):
        docs, registry, ir = binding_example()
        row(ir, "origin", "EXB")["body"] = {"kind": "copy", "parents": ["EXA"]}
        row(ir, "origin", "EXC")["body"] = {"kind": "copy", "parents": ["EXB"]}
        add(ir, "dependency", "EXC", {"relation": "ancestor", "refs": ["EXA"]})
        add(ir, "dependency", "EXC", {"relation": "parent", "refs": ["EXA"]}, polarity="deny")
        self.assertEqual(compile_cited_ir(ir, docs, registry)["status"], "compiled")

    def test_necessity_ignores_local_inactivity_but_is_nonvacuous(self):
        docs, registry, ir = binding_example()
        p = add(ir, "dependency", "EXD", {"relation": "necessary", "refs": ["EXA"]})
        self.assertEqual(compile_cited_ir(ir, docs, registry)["status"], "compiled")
        row(ir, "support", "EXR")["body"] = {"expr": {"none": True}}
        with self.assertRaisesRegex(SourceIRError, "constraint_conflict"): compile_cited_ir(ir, docs, registry)
        p["polarity"] = "deny"
        self.assertEqual(compile_cited_ir(ir, docs, registry)["status"], "compiled")

    def test_group_denial_is_not_individual_negation(self):
        docs, registry, ir = binding_example()
        row(ir, "origin", "EXC")["body"]["parents"] = ["EXA"]
        p = add(ir, "dependency", "EXC", {"relation": "parent", "refs": ["EXA", "EXB"]}, polarity="deny")
        compile_cited_ir(ir, docs, registry)
        p["body"]["refs"] = ["EXA"]
        with self.assertRaisesRegex(SourceIRError, "constraint_conflict"): compile_cited_ir(ir, docs, registry)

    def test_binding_objects_unknown_ids_and_wrong_mentions_reject(self):
        for mode in ("object", "unknown", "wrong_entity", "wrong_mention"):
            docs, registry, ir = binding_example(); origin = row(ir, "origin", "EXC")
            if mode == "object": origin["bindings"] = [deepcopy(ir["bindings"][0])]
            elif mode == "unknown": origin["bindings"] = ["missing-binding"]
            elif mode == "wrong_entity": ir["bindings"][0]["entity"] = "EXD"
            else: origin["citations"] = ir["entities"][0]["citations"]
            with self.subTest(mode=mode), self.assertRaises(SourceIRError): compile_cited_ir(ir, docs, registry)

    def test_unknown_ancestry_without_invented_reference_or_partial_output(self):
        for retain_known_copy in (False, True):
            docs, registry, ir = binding_example()
            if not retain_known_copy:
                ir["propositions"] = [p for p in ir["propositions"] if not (p["kind"] == "origin" and p["target"] == "EXC")]
            add(ir, "unknown_ancestry", "EXC", {"description": "An upstream worksheet is unnamed."})
            result = compile_cited_ir(ir, docs, registry)
            self.assertEqual(result["status"], "unresolved_structure")
            self.assertEqual(result["candidates"], [])
        row(ir, "origin", "EXC")["body"] = {"kind": "root", "parents": []}
        with self.assertRaisesRegex(SourceIRError, "unknown_root_conflict"): compile_cited_ir(ir, docs, registry)

    def test_unknown_does_not_excuse_missing_eligibility_or_other_definition(self):
        for missing in (("eligibility", "EXC"), ("support", "EXR")):
            docs, registry, ir = binding_example()
            ir["propositions"] = [p for p in ir["propositions"] if (p["kind"], p["target"]) != missing]
            add(ir, "unknown_ancestry", "EXC", {"description": "Unnamed source"})
            with self.assertRaisesRegex(SourceIRError, "missing_definition"): compile_cited_ir(ir, docs, registry)

    def test_all_noncurrent_scopes_still_typed_but_do_not_define_graph(self):
        docs, registry, ir = binding_example()
        for scope in ("historical", "hypothetical", "proposed"):
            add(ir, "origin", "EXC", {"kind": "root", "parents": []}, scope=scope)
        result = compile_cited_ir(ir, docs, registry)
        self.assertEqual(next(e["kind"] for e in result["candidates"][0]["graph"]["evidence"] if e["id"] == "EXC"), "copy")

    def test_nonoperational_entity_can_be_denied_but_not_used_by_positive_rule(self):
        docs, registry, ir = binding_example()
        ir = recite(docs, ir, 0, docs[0]["text"] + " Historical evidence EXH was unrelated to the current certificate.")
        cite = [source_segments(docs)[0]["span_id"]]
        ir["entities"].append({"id": "EXH", "type": "evidence", "operational": False, "citations": cite})
        add(ir, "origin", "EXH", {"kind": "root", "parents": []}, scope="historical", citations=cite)
        for relation, target in (("parent", "EXC"), ("ancestor", "EXC"), ("necessary", "EXD"), ("sufficient_route", "EXR")):
            p = add(ir, "dependency", target, {"relation": relation, "refs": ["EXH"]}, polarity="deny", citations=cite)
        result = compile_cited_ir(ir, docs, registry)
        self.assertNotIn("EXH", [e["id"] for e in result["candidates"][0]["graph"]["evidence"]])
        p["polarity"] = "assert"
        with self.assertRaisesRegex(SourceIRError, "nonoperational_reference"): compile_cited_ir(ir, docs, registry)

    def test_expanded_citation_payload_not_just_compact_wire_has_a_bound(self):
        docs, registry, ir = binding_example()
        ir = recite(docs, ir, 0, docs[0]["text"] + " " + "z" * 3800)
        for _ in range(140):
            add(ir, "origin", "EXA", {"kind": "root", "parents": []}, scope="historical")
        self.assertLess(len(json.dumps(ir)), 524288)
        with self.assertRaisesRegex(SourceIRError, "json_limit"): compile_cited_ir(ir, docs, registry)

    def test_all_expression_constructors_preserve_nested_qualifier(self):
        docs, registry, ir = binding_example()
        row(ir, "support", "EXR")["body"] = {"expr": {"all": [{"any": [{"ref": "EXA"}, {"ref": "EXC"}]}, {"ref": "EXB"}]}}
        graph = compile_cited_ir(ir, docs, registry)["candidates"][0]["graph"]
        self.assertEqual(graph["claims"][0]["supports"], [["EXA", "EXB"], ["EXB", "EXC"]])
        row(ir, "support", "EXR")["body"] = {"expr": {"none": True}}
        self.assertEqual(compile_cited_ir(ir, docs, registry)["candidates"][0]["graph"]["claims"][0]["supports"], [])

    def test_cartesian_and_coupled_listed_policies(self):
        docs, registry, ir = choices_fixture()
        self.assertEqual(compile_cited_ir(ir, docs, registry)["candidate_count"], 4)
        ir["combination"]["mode"] = "listed"
        ir["combination"]["assignments"] = [{"EX-u": "left", "EX-v": "left"}, {"EX-u": "right", "EX-v": "right"}]
        self.assertEqual(compile_cited_ir(ir, docs, registry)["candidate_count"], 2)
        ir["combination"]["assignments"].pop()
        with self.assertRaisesRegex(SourceIRError, "unused_option"): compile_cited_ir(ir, docs, registry)

    def test_conditional_definitions_must_be_unique_and_complete(self):
        for mode in ("overlap", "missing", "false_constraint"):
            docs, registry, ir = choices_fixture()
            if mode == "overlap": row(ir, "origin", "EXC")["when"] = {}
            elif mode == "missing": ir["propositions"] = [p for p in ir["propositions"] if not (p["kind"] == "origin" and p["when"].get("EX-u") == "right")]
            else: add(ir, "dependency", "EXC", {"relation": "parent", "refs": ["EXA"]})
            with self.subTest(mode=mode), self.assertRaises(SourceIRError): compile_cited_ir(ir, docs, registry)

    def test_self_reference_duplicate_reference_extra_fields_and_cycles_reject(self):
        for mode in ("self", "duplicate", "extra", "cycle", "unknown_id", "empty_decision"):
            docs, registry, ir = binding_example()
            if mode == "self": row(ir, "origin", "EXC")["body"]["parents"].append("EXC")
            elif mode == "duplicate": row(ir, "origin", "EXC")["body"]["parents"].append("EXA")
            elif mode == "extra": row(ir, "origin", "EXC")["body"]["comment"] = "extra"
            elif mode == "cycle": row(ir, "origin", "EXA")["body"] = {"kind": "copy", "parents": ["EXC"]}
            elif mode == "unknown_id": row(ir, "origin", "EXC")["body"]["parents"] = ["UNKNOWN"]
            else: row(ir, "requirement", "EXD")["body"]["requires"] = []
            with self.subTest(mode=mode), self.assertRaises(ValueError): compile_cited_ir(ir, docs, registry)

    def test_instruction_exports_are_standalone_and_name_every_contract_type(self):
        for token in ("eligibility:", "origin:", "support:", "requirement:", "unknown_ancestry:", "parent:", "ancestor:", "necessary:", "sufficient_route:",
                      "historical", "hypothetical", "proposed", "Cartesian", "Listed", "binding ID STRINGS", "CLAIM target ONLY", "EXACTLY one direct clause", "524,288"):
            self.assertIn(token, CONTRACT)
        self.assertNotIn("retrace.source-ir.v6g", IR_V6G_INSTRUCTIONS)
        self.assertIn('"schema":"retrace.source-ir.v6d"', IR_V6G_INSTRUCTIONS)


if __name__ == "__main__": unittest.main()
