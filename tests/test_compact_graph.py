import copy
import random
import unittest

from retrace.compact_graph import (
    CompactGraphError, MAX_NODES, MAX_TEXT_CHARS,
    parse_compact, parse_compact_output, serialize_compact, validate_explicit_graph,
)
from retrace.core import analyze


PACKET = """E root_A R 0 -
E root_B R 1 -
E copy_P C 1 root_A
C protected copy_P|root_B
C lost copy_P
C empty -
D keep protected
D remove lost
D never empty
END"""


def registry(graph):
    return {kind: [row["id"] for row in graph[kind]] for kind in ("evidence", "claims", "decisions")}


def decisions(graph, revoked=None):
    return {identifier: node["usable"] for identifier, node in analyze(graph, revoked)["decisions"].items()}


def structural_signature(graph):
    """Set-based comparison retaining support grouping and local eligibility."""
    return (
        frozenset((row["id"], row.get("kind", "root"), row.get("active", True), frozenset(row.get("parents", [])))
                  for row in graph["evidence"]),
        frozenset((row["id"], frozenset(frozenset(clause) for clause in row["supports"])) for row in graph["claims"]),
        frozenset((row["id"], frozenset(row["requires"])) for row in graph["decisions"]),
    )


def random_dag(rng, number):
    evidence = []
    for index in range(rng.randint(4, 12)):
        parent_ids = [row["id"] for row in evidence]
        is_copy = bool(parent_ids) and rng.random() < .55
        parents = rng.sample(parent_ids, rng.randint(1, min(3, len(parent_ids)))) if is_copy else []
        evidence.append({"id": f"e{number}_{index}", "kind": "copy" if is_copy else "root",
                         "active": rng.random() < .75, "parents": parents})
    claims = []
    for index in range(rng.randint(3, 9)):
        possible = [row["id"] for row in evidence + claims]
        clauses = set()
        if rng.random() >= .15:
            for _ in range(rng.randint(1, 4)):
                clauses.add(tuple(sorted(rng.sample(possible, rng.randint(1, min(3, len(possible)))))))
        claims.append({"id": f"c{number}_{index}", "supports": [list(clause) for clause in sorted(clauses)]})
    choices = [row["id"] for row in claims]
    decision_rows = [{"id": f"d{number}_{index}", "requires": rng.sample(choices, rng.randint(1, min(3, len(choices))))}
                     for index in range(rng.randint(2, 6))]
    return {"evidence": evidence, "claims": claims, "decisions": decision_rows}


class CompactGraphTests(unittest.TestCase):
    def assert_rejected(self, text, code=None, line=None, supplied_registry=None):
        with self.assertRaises(CompactGraphError) as caught:
            parse_compact(text, supplied_registry)
        if code is not None:
            self.assertEqual(caught.exception.code, code)
        if line is not None:
            self.assertEqual(caught.exception.line_number, line)
            self.assertIn(f"Line {line}:", str(caught.exception))

    def test_local_activity_copy_eligibility_alternatives_and_zero_routes(self):
        graph = parse_compact(PACKET)
        self.assertEqual(decisions(graph), {"keep": True, "never": False, "remove": False})
        self.assertTrue(next(row for row in graph["evidence"] if row["id"] == "copy_P")["active"])
        self.assertFalse(analyze(graph)["evidence"]["copy_P"]["usable"])
        self.assertEqual(next(row for row in graph["claims"] if row["id"] == "empty")["supports"], [])
        self.assertEqual(decisions(graph, ["root_B"])["keep"], False)

    def test_joint_routes_are_not_alternatives_and_copies_require_every_parent(self):
        joint = "E A R 0 -\nE B R 1 -\nE P C 1 A,B\nC Q A+B\nC S A|B\nC T P\nD D1 Q\nD D2 S\nD D3 T\nEND"
        self.assertEqual(decisions(parse_compact(joint)), {"D1": False, "D2": True, "D3": False})
        changed = joint.replace("C Q A+B", "C Q A|B")
        self.assertTrue(decisions(parse_compact(changed))["D1"])

    def test_records_and_members_can_be_permuted_without_changing_logic(self):
        first = "E A R 1 -\nE B R 1 -\nE P C 1 A,B\nC Q A+B|P\nC S B\nD X Q+S\nEND"
        reordered = "D X S+Q\nC S B\nC Q P|B+A\nE P C 1 B,A\nE B R 1 -\nE A R 1 -\nEND"
        self.assertEqual(parse_compact(first), parse_compact(reordered))
        self.assertEqual(serialize_compact(parse_compact(first)), serialize_compact(parse_compact(reordered)))

    def test_bare_and_prespecified_whole_fences_preserve_original_source(self):
        examples = [(PACKET, False), ("\n \t\n" + PACKET + "\n\t", False)]
        examples += [("\n```" + language + "\r\n" + PACKET.replace("\n", "\r\n") + "\r\n```\n", True)
                     for language in ("", "text", "plaintext")]
        for source, fenced in examples:
            with self.subTest(fenced=fenced, source=source[:30]):
                result = parse_compact_output(source)
                self.assertEqual(result["graph"], parse_compact(PACKET))
                self.assertEqual(result["source_text"], source)
                self.assertEqual(result["outer_fence_removed"], fenced)
                self.assertEqual(result["strict_bare"], not fenced)

    def test_end_is_required_and_content_after_end_is_never_discarded(self):
        for text in (PACKET.removesuffix("\nEND"), "", " \n\t", "E A R 1 -\nEN", "E A R 1 -\nEND extra"):
            with self.subTest(text=text):
                self.assert_rejected(text)
        self.assert_rejected(PACKET + "\nEND", "trailing_content", 11)
        self.assert_rejected(PACKET + "\nExplanation", "trailing_content", 11)
        self.assert_rejected("```text\n" + PACKET, "invalid_fence", 1)

    def test_no_prose_json_fence_nested_fence_or_block_repair(self):
        for text in ("Here is the graph:\n" + PACKET, "```json\n" + PACKET + "\n```",
                     "```python\n" + PACKET + "\n```", "```TEXT\n" + PACKET + "\n```",
                     "```text\n" + PACKET + "\n```\ncomment",
                     "```text\n" + PACKET + "\n```\n```text\nEND\n```",
                     "```text\n```\n" + PACKET + "\n```", "E A R 1 - # comment\nEND"):
            with self.subTest(text=text[:40]):
                self.assert_rejected(text)

    def test_errors_keep_physical_source_lines_including_blank_lines_and_fence(self):
        self.assert_rejected("\n```plaintext\nE A R 1 -\nC Q A+\nEND\n```\n", "invalid_id", 4)
        self.assert_rejected("\n\nE A R 1 -\nC Q absent\nEND", "unknown_reference", 4)

    def test_no_implicit_fields_or_defaults_in_model_output(self):
        malformed = {"E A R 1\nEND": "field_count", "E A R -\nEND": "field_count",
                     "E A root 1 -\nEND": "invalid_kind", "E A R true -\nEND": "invalid_activity",
                     "E A R 2 -\nEND": "invalid_activity", "E A C 1 -\nEND": "invalid_parents",
                     "E A R 1 B\nE B R 1 -\nEND": "invalid_parents",
                     "C Q\nEND": "field_count", "D D\nEND": "field_count", "D D -\nEND": "invalid_id"}
        for text, code in malformed.items():
            with self.subTest(text=text):
                self.assert_rejected(text, code, 1)

    def test_empty_clauses_members_and_unsupported_punctuation_are_rejected(self):
        for field in ("A|", "|A", "A||B", "A+", "+A", "A++B", "A|B+", "A,B", "-+A", "-|A", "A + B"):
            with self.subTest(field=field):
                self.assert_rejected("E A R 1 -\nE B R 1 -\nC Q " + field + "\nEND")
        for parents in (",A", "A,", "A,,B", "A+B", "A|B"):
            with self.subTest(parents=parents):
                self.assert_rejected("E A R 1 -\nE B R 1 -\nE P C 1 " + parents + "\nEND")

    def test_ids_are_conservative_ascii_and_dash_is_reserved(self):
        for identifier in ("-", "a.b", "a:b", "a/b", "a+b", "a|b", "a,b", '"A"', "é", "Ａ"):
            with self.subTest(identifier=identifier):
                self.assert_rejected("E " + identifier + " R 1 -\nEND")
        good = parse_compact("E _valid-2 R 1 -\nC END _valid-2\nD D END\nEND")
        self.assertTrue(decisions(good)["D"])
        for character in ("\x00", "\x0b", "\x0c", "\x7f", "\u00a0", "\ufeff"):
            self.assert_rejected("E A R 1 -" + character + "\nEND", "unsupported_character", 1)
        self.assert_rejected("E A R 1 -\rEND", "unsupported_character", 1)

    def test_duplicate_nodes_references_and_equivalent_routes_are_rejected(self):
        bad = [("E A R 1 -\nC A -\nEND", "duplicate_id"),
               ("E A R 1 -\nE P C 1 A,A\nEND", "duplicate_reference"),
               ("E A R 1 -\nC Q A+A\nEND", "duplicate_reference"),
               ("E A R 1 -\nC Q A|A\nEND", "duplicate_clause"),
               ("E A R 1 -\nE B R 1 -\nC Q A+B|B+A\nEND", "duplicate_clause"),
               ("C Q -\nD D Q+Q\nEND", "duplicate_reference")]
        for text, code in bad:
            with self.subTest(code=code):
                self.assert_rejected(text, code)

    def test_missing_wrong_category_and_cyclic_references_are_rejected(self):
        cases = [("C Q absent\nEND", "unknown_reference"),
                 ("C Q -\nE P C 1 Q\nEND", "reference_category"),
                 ("E A R 1 -\nD D A\nEND", "reference_category"),
                 ("C Q D\nD D Q\nEND", "reference_category"),
                 ("E A C 1 B\nE B C 1 A\nEND", "dependency_cycle"),
                 ("C A B\nC B A\nEND", "dependency_cycle"),
                 ("C A A\nEND", "dependency_cycle")]
        for text, code in cases:
            with self.subTest(code=code):
                self.assert_rejected(text, code)

    def test_exact_typed_registry_catches_omissions_inventions_and_category_swaps(self):
        graph = parse_compact(PACKET)
        supplied = registry(graph)
        self.assertEqual(parse_compact(PACKET, supplied), graph)
        self.assert_rejected(PACKET.replace("C empty -\n", "").replace("D never empty\n", ""), "registry_mismatch", supplied_registry=supplied)
        self.assert_rejected(PACKET.replace("END", "E invented R 1 -\nEND"), "registry_mismatch", supplied_registry=supplied)
        swapped = copy.deepcopy(supplied)
        swapped["evidence"].remove("root_B")
        swapped["claims"].append("root_B")
        self.assert_rejected(PACKET, "registry_mismatch", supplied_registry=swapped)
        self.assertEqual(supplied, registry(graph))

    def test_registry_itself_must_be_complete_unique_and_well_typed(self):
        for supplied in ({}, {"evidence": [], "claims": []}, {"evidence": "A", "claims": [], "decisions": []},
                         {"evidence": ["A", "A"], "claims": [], "decisions": []},
                         {"evidence": ["A"], "claims": ["A"], "decisions": []},
                         {"evidence": [], "claims": [], "decisions": [], "gold": True}):
            with self.subTest(supplied=supplied):
                self.assert_rejected("END", "invalid_registry", supplied_registry=supplied)

    def test_empty_graph_requires_explicit_end_and_empty_registry(self):
        empty = {"evidence": [], "claims": [], "decisions": []}
        self.assertEqual(parse_compact("END"), empty)
        self.assertEqual(parse_compact("END", empty), empty)
        self.assertEqual(serialize_compact(empty), "END")
        self.assert_rejected("END", "registry_mismatch", 1, {"evidence": ["A"], "claims": [], "decisions": []})

    def test_source_and_node_limits_are_enforced_at_boundaries(self):
        graph_at_limit = "\n".join(f"E e{number} R 1 -" for number in range(MAX_NODES)) + "\nEND"
        self.assertEqual(len(parse_compact(graph_at_limit)["evidence"]), MAX_NODES)
        too_many = graph_at_limit.replace("\nEND", "\nE extra R 1 -\nEND")
        self.assert_rejected(too_many, "node_limit", MAX_NODES + 1)
        exact_text_limit = " " * (MAX_TEXT_CHARS - 3) + "END"
        self.assertEqual(parse_compact(exact_text_limit), {"evidence": [], "claims": [], "decisions": []})
        self.assert_rejected(" " + exact_text_limit, "text_limit", 1)
        too_many_ids = {"evidence": [f"e{i}" for i in range(MAX_NODES + 1)], "claims": [], "decisions": []}
        self.assert_rejected("END", "node_limit", supplied_registry=too_many_ids)

    def test_serializer_is_explicit_nonmutating_and_does_not_fix_duplicate_routes(self):
        graph = {"id": "description-only", "evidence": [{"id": "A", "label": "A descriptive label"}],
                 "claims": [{"id": "Q", "supports": [["A"]]}], "decisions": [{"id": "D", "requires": ["Q"]}]}
        original = copy.deepcopy(graph)
        self.assertEqual(serialize_compact(graph), "E A R 1 -\nC Q A\nD D Q\nEND")
        self.assertEqual(graph, original)
        unknown_field = copy.deepcopy(graph)
        unknown_field["evidence"][0]["confidence"] = .9
        with self.assertRaises(CompactGraphError) as unknown:
            serialize_compact(unknown_field)
        self.assertEqual(unknown.exception.code, "unexpected_field")
        graph["claims"][0]["supports"].append(["A"])
        with self.assertRaises(CompactGraphError) as caught:
            serialize_compact(graph)
        self.assertEqual(caught.exception.code, "duplicate_clause")

    def test_shared_explicit_validator_rejects_defaults_labels_and_structural_failures(self):
        graph = parse_compact(PACKET)
        self.assertEqual(validate_explicit_graph(graph, registry(graph)), graph)
        variants = []
        for field in ("kind", "active", "parents"):
            missing = copy.deepcopy(graph)
            del missing["evidence"][0][field]
            variants.append(missing)
        labeled = copy.deepcopy(graph); labeled["claims"][0]["label"] = "extra"; variants.append(labeled)
        duplicate = copy.deepcopy(graph); duplicate["claims"][1]["supports"] *= 2; variants.append(duplicate)
        unknown = copy.deepcopy(graph); unknown["decisions"][0]["requires"] = ["missing"]; variants.append(unknown)
        cycle = copy.deepcopy(graph); cycle["claims"][0]["supports"] = [[cycle["claims"][0]["id"]]]; variants.append(cycle)
        oversized = copy.deepcopy(graph); oversized["evidence"][0]["id"] = "x" * MAX_TEXT_CHARS; variants.append(oversized)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(CompactGraphError):
                validate_explicit_graph(value)
        self.assertEqual(validate_explicit_graph({"evidence": [], "claims": [], "decisions": []}),
                         {"evidence": [], "claims": [], "decisions": []})

    def test_750_generated_dags_roundtrip_grouping_permutations_and_revocations(self):
        rng = random.Random(2026111407)
        for number in range(750):
            graph = random_dag(rng, number)
            with self.subTest(number=number):
                original = copy.deepcopy(graph)
                serialized = serialize_compact(graph)
                compiled = parse_compact(serialized, registry(graph))
                self.assertEqual(structural_signature(compiled), structural_signature(graph))
                self.assertEqual(validate_explicit_graph(graph, registry(graph)), compiled)
                self.assertEqual(serialize_compact(compiled), serialized)
                self.assertEqual(graph, original)
                lines = serialized.splitlines()[:-1]
                rng.shuffle(lines)
                self.assertEqual(parse_compact("\n".join(lines + ["END"])), compiled)
                self.assertEqual(decisions(compiled), decisions(graph))
                evidence_ids = [row["id"] for row in graph["evidence"]]
                for _ in range(2):
                    revoked = rng.sample(evidence_ids, rng.randint(0, min(4, len(evidence_ids))))
                    self.assertEqual(decisions(compiled, revoked), decisions(graph, revoked))


if __name__ == "__main__":
    unittest.main()
