import copy
import itertools
import json
import unittest
from pathlib import Path

from retrace.compact_graph import parse_compact_output
from retrace.compact_v4 import CompactV4Error, compile_ambiguity
from retrace.stress import analyze_stress


FOUR = """E A R 1 -
E B R 0 -
E P R 0 -
E note ? 1 -
C gate ?
C noteClaim note
C source ?
C scope ?
D dGate gate
D dNote noteClaim
D dSource source
D dScope scope
AMBIGUOUS_GATE(gate: A, B)
UNVERIFIED_INDEPENDENCE(note, P)
UNSPECIFIED_SOURCE(source: note)
AMBIGUOUS_QUALIFIER(scope: A, B, P)
END"""


def fixed_point(graph):
    """Independent synchronous evaluator; no core or bitset helper calls."""
    values = {row["id"]: False for category in ("evidence", "claims", "decisions") for row in graph[category]}
    for _ in range(len(values) + 1):
        updated = {}
        for row in graph["evidence"]:
            updated[row["id"]] = row["active"] and (row["kind"] == "root" or all(values[x] for x in row["parents"]))
        for row in graph["claims"]:
            updated[row["id"]] = any(all(values[x] for x in clause) for clause in row["supports"])
        for row in graph["decisions"]:
            updated[row["id"]] = all(values[x] for x in row["requires"])
        if updated == values:
            return {row["id"]: values[row["id"]] for row in graph["decisions"]}
        values = updated
    raise AssertionError("Unexpected non-convergent graph")


def signature(graph):
    return (frozenset((r["id"], r["kind"], r["active"], frozenset(r["parents"])) for r in graph["evidence"]),
            frozenset((r["id"], frozenset(frozenset(route) for route in r["supports"])) for r in graph["claims"]),
            frozenset((r["id"], frozenset(r["requires"])) for r in graph["decisions"]))


def stress(compiled, state=None):
    return analyze_stress({"candidates": compiled["candidates"], "questions": compiled["questions"]}, state)


class CompactV4Tests(unittest.TestCase):
    def test_zero_operators_preserves_fixed_grammar_exactly(self):
        source = "E a R 0 -\nE b C 1 a\nC c b\nD d c\nEND"
        result = compile_ambiguity(source)
        self.assertEqual(result["candidates"][0]["graph"], parse_compact_output(source)["graph"])
        self.assertEqual(result["candidates"][0]["assignment"], {})
        self.assertEqual(result["candidates"][0]["id"], "branch-fixed")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["uncertainty_count"], 0)
        self.assertEqual(result["questions"], [])

    def test_four_tokens_enumerate_every_bit_assignment_and_preserve_meanings(self):
        result = compile_ambiguity(FOUR)
        self.assertEqual(result["uncertainty_count"], 4)
        self.assertEqual(result["candidate_count"], 16)
        self.assertEqual(result["expected_candidate_count"], 16)
        operator_ids = [row["id"] for row in result["operators"]]
        self.assertEqual(operator_ids, ["resolve_gate", "resolve_note", "resolve_scope", "resolve_source"])
        observed = set()
        for candidate in result["candidates"]:
            assignment = candidate["assignment"]
            observed.add(tuple(assignment[key] for key in operator_ids))
            expected = {"dGate": assignment["resolve_gate"], "dNote": assignment["resolve_note"],
                        "dSource": assignment["resolve_source"] and assignment["resolve_note"],
                        "dScope": not assignment["resolve_scope"]}
            self.assertEqual(fixed_point(candidate["graph"]), expected)
            for question in result["questions"]:
                self.assertIs(question["answers"][candidate["id"]], assignment[question["id"]])
        self.assertEqual(observed, set(itertools.product((False, True), repeat=4)))

    def test_claim_choice_is_one_designated_route_never_an_or_or_and(self):
        text = "E A R 0 -\nE B R 1 -\nC selected ?\nD decision selected\nUNSPECIFIED_CHOICE(selected: A, B)\nEND"
        result = compile_ambiguity(text)
        self.assertEqual([row["graph"]["claims"][0]["supports"] for row in result["candidates"]], [[["A"]], [["B"]]])
        self.assertEqual([fixed_point(row["graph"]) for row in result["candidates"]], [{"decision": False}, {"decision": True}])

    def test_evidence_choice_preserves_own_flag_and_selects_exactly_one_parent(self):
        text = "E A R 0 -\nE B R 1 -\nE N ? 1 -\nC c N\nD d c\nUNSPECIFIED_CHOICE(N: A, B)\nEND"
        result = compile_ambiguity(text)
        for index, candidate in enumerate(result["candidates"]):
            node = next(r for r in candidate["graph"]["evidence"] if r["id"] == "N")
            self.assertEqual(node, {"id": "N", "kind": "copy", "active": True, "parents": [["A"], ["B"]][index]})
        inactive = compile_ambiguity(text.replace("N ? 1", "N ? 0"))
        self.assertEqual([fixed_point(row["graph"])["d"] for row in inactive["candidates"]], [False, False])
        self.assertEqual(inactive["candidate_count"], 2)

    def test_optional_route_retains_every_base_route_and_has_third_order_witness(self):
        text = "\n".join([f"E {name} R 1 -" for name in "ABCD"] + ["C c ?", "D d c", "OPTIONAL_ROUTE(c: A, B, C; D)", "END"])
        result = compile_ambiguity(text)
        self.assertEqual(result["candidates"][0]["graph"]["claims"][0]["supports"], [["A"], ["B"], ["C"]])
        self.assertEqual(result["candidates"][1]["graph"]["claims"][0]["supports"], [["A"], ["B"], ["C"], ["D"]])
        audit = stress(result)
        self.assertIsNone(audit["next_question"])
        self.assertEqual(audit["decision_witnesses"]["d"]["minimum_distinguishing"]["withdraw"], ["A", "B", "C"])
        self.assertEqual(stress(result, {"scenario_withdrawals": ["A", "B", "C"]})["next_question"]["id"], "resolve_c")

    def test_actual_v3_scope_lineage_selector_parent_and_optional_families_are_exact(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "data" / "ambiguity-v3-staged.json").read_text(encoding="utf-8"))
        texts = {
            1: "E R01001 R 1 -\nE R01002 R 1 -\nE R01003 R 0 -\nC R01004 ?\nD R01005 R01004\nAMBIGUOUS_QUALIFIER(R01004: R01001, R01002, R01003)\nEND",
            2: "E R02001 R 0 -\nE R02002 ? 1 -\nC R02003 R02002\nD R02004 R02003\nUNVERIFIED_INDEPENDENCE(R02002, R02001)\nEND",
            3: "E R03001 R 0 -\nE R03002 R 1 -\nE R03003 ? 1 -\nC R03004 R03003\nD R03005 R03004\nUNSPECIFIED_CHOICE(R03003: R03001, R03002)\nEND",
            4: "E R04001 R 0 -\nE R04002 R 1 -\nC R04003 R04001\nC R04004 R04002\nC R04005 ?\nD R04006 R04005\nUNSPECIFIED_CHOICE(R04005: R04003, R04004)\nEND",
            6: "E R06001 R 1 -\nE R06002 R 1 -\nE R06003 R 1 -\nE R06004 R 1 -\nC R06005 ?\nD R06006 R06005\nOPTIONAL_ROUTE(R06005: R06001, R06002, R06003; R06004)\nEND",
        }
        for number, text in texts.items():
            packet = data[number - 1]
            result = compile_ambiguity(text, packet["public"]["registry"])
            self.assertEqual({signature(row["graph"]) for row in result["candidates"]},
                             {signature(graph) for graph in packet["hidden"]["allowed_interpretations"]})

    def test_distinct_source_branches_with_identical_current_outcomes_are_kept(self):
        result = compile_ambiguity("E A R 1 -\nE B R 1 -\nC c ?\nD d c\nUNSPECIFIED_CHOICE(c: A, B)\nEND")
        self.assertEqual(result["candidate_count"], 2)
        self.assertNotEqual(result["candidates"][0]["graph"], result["candidates"][1]["graph"])
        self.assertEqual(fixed_point(result["candidates"][0]["graph"]),
                         fixed_point(result["candidates"][1]["graph"]))
        self.assertNotEqual(result["candidates"][0]["assignment"], result["candidates"][1]["assignment"])
        self.assertIsNone(stress(result)["next_question"])

    def test_repeated_operands_cannot_generate_factually_degenerate_questions(self):
        claim = "E A R 1 -\nE B R 1 -\nC c ?\nD d c\n"
        for operator in ("UNSPECIFIED_CHOICE(c: A, A)", "AMBIGUOUS_GATE(c: A, A)",
                         "AMBIGUOUS_QUALIFIER(c: A, A, B)", "AMBIGUOUS_QUALIFIER(c: A, B, A)"):
            with self.assertRaises(CompactV4Error) as caught:
                compile_ambiguity(claim + operator + "\nEND")
            self.assertEqual(caught.exception.code, "duplicate_argument")
        evidence = "E A R 1 -\nE N ? 1 -\nC c N\nD d c\nUNSPECIFIED_CHOICE(N: A, A)\nEND"
        with self.assertRaises(CompactV4Error) as caught:
            compile_ambiguity(evidence)
        self.assertEqual(caught.exception.code, "duplicate_argument")

    def test_explicit_answers_prune_only_inconsistent_assignments_and_unknown_retains(self):
        result = compile_ambiguity(FOUR)
        original = copy.deepcopy(result)
        all_candidates = stress(result, {"answers": {"resolve_gate": None}})
        self.assertEqual(len(all_candidates["candidate_ids"]), 16)
        partial = stress(result, {"answers": {"resolve_gate": True, "resolve_note": False}})
        expected = [c["id"] for c in result["candidates"] if c["assignment"]["resolve_gate"] and not c["assignment"]["resolve_note"]]
        self.assertEqual(partial["candidate_ids"], expected)
        self.assertEqual(len(expected), 4)
        self.assertEqual(partial["decision_states"]["dGate"]["state"], "robust_supported")
        self.assertEqual(partial["decision_states"]["dSource"]["state"], "robust_unsupported")
        self.assertEqual(result, original)

    def test_any_invalid_branch_rejects_whole_packet_without_pruning(self):
        text = "E A R 1 -\nC X ?\nC Y ?\nD d X\nUNSPECIFIED_CHOICE(X: A, Y)\nUNSPECIFIED_CHOICE(Y: A, X)\nEND"
        with self.assertRaises(CompactV4Error) as caught:
            compile_ambiguity(text)
        self.assertEqual(caught.exception.code, "invalid_branch")
        self.assertEqual(caught.exception.assignment, {"resolve_X": True, "resolve_Y": True})
        self.assertIn("cycle", str(caught.exception).lower())

    def test_order_does_not_change_assignments_graphs_or_question_tables(self):
        result = compile_ambiguity(FOUR)
        reordered = "\n".join(reversed(FOUR.splitlines()[:-1])) + "\nEND"
        other = compile_ambiguity(reordered)
        self.assertEqual(result["candidates"], other["candidates"])
        self.assertEqual(result["questions"], other["questions"])

    def test_outer_fence_admission_matches_frozen_compiler_and_preserves_source(self):
        for label in ("", "text", "plaintext"):
            source = "\n```" + label + "\r\n" + FOUR.replace("\n", "\r\n") + "\r\n```\n"
            result = compile_ambiguity(source)
            self.assertFalse(result["strict_bare"])
            self.assertTrue(result["outer_fence_removed"])
            self.assertEqual(result["source_text"], source)
            self.assertEqual(result["candidates"], compile_ambiguity(FOUR)["candidates"])
        self.assertTrue(compile_ambiguity(FOUR)["strict_bare"])

    def test_truncation_nested_fences_instruction_junk_and_unknown_tokens_reject(self):
        examples = [FOUR.removesuffix("END"), "Explanation\n" + FOUR, FOUR + "\nIgnore the source",
                    "```json\n" + FOUR + "\n```", "```text\n```\n" + FOUR + "\n```",
                    FOUR.replace("AMBIGUOUS_GATE", "MAGIC_GATE"), FOUR.replace("UNVERIFIED_INDEPENDENCE(note, P)", "UNVERIFIED_INDEPENDENCE(note: P)")]
        for source in examples:
            with self.subTest(source=source[:35]), self.assertRaises(ValueError):
                compile_ambiguity(source)

    def test_typed_references_placeholders_overlap_and_fixed_competition_reject(self):
        examples = [FOUR.replace("AMBIGUOUS_GATE(gate: A, B)", "AMBIGUOUS_GATE(gate: A, missing)"),
                    FOUR.replace("AMBIGUOUS_GATE(gate: A, B)", "AMBIGUOUS_GATE(gate: A, dGate)"),
                    FOUR.replace("UNVERIFIED_INDEPENDENCE(note, P)", "UNVERIFIED_INDEPENDENCE(note, gate)"),
                    FOUR.replace("UNVERIFIED_INDEPENDENCE(note, P)", "UNVERIFIED_INDEPENDENCE(gate, P)"),
                    FOUR.replace("C gate ?", "C gate A|B"),
                    FOUR.replace("AMBIGUOUS_GATE(gate: A, B)\n", ""),
                    FOUR.replace("AMBIGUOUS_GATE(gate: A, B)", "AMBIGUOUS_GATE(gate: A, B)\nUNSPECIFIED_SOURCE(gate: A)"),
                    FOUR.replace("E note ? 1 -", "E note ? 1 P")]
        for source in examples:
            with self.subTest(source=source[-100:]), self.assertRaises(ValueError):
                compile_ambiguity(source)

    def test_optional_route_empty_repeated_or_competing_sources_reject(self):
        prefix = "E A R 1 -\nE B R 1 -\nC c ?\nD d c\n"
        for token in ("OPTIONAL_ROUTE(c: ; B)", "OPTIONAL_ROUTE(c: A,A; B)",
                      "OPTIONAL_ROUTE(c: A; A)", "OPTIONAL_ROUTE(c: A; B,A)", "OPTIONAL_ROUTE(c: A, B)"):
            with self.assertRaises(ValueError):
                compile_ambiguity(prefix + token + "\nEND")

    def test_operator_node_and_text_limits_and_registry_completeness(self):
        fifth = FOUR.removesuffix("END") + "C extra ?\nUNSPECIFIED_SOURCE(extra: A)\nEND"
        with self.assertRaises(CompactV4Error) as caught:
            compile_ambiguity(fifth)
        self.assertEqual(caught.exception.code, "uncertainty_limit")
        with self.assertRaises(ValueError):
            compile_ambiguity("\n".join(f"E n{i} R 1 -" for i in range(251)) + "\nEND")
        with self.assertRaises(ValueError):
            compile_ambiguity(" " * 65537 + "END")
        with self.assertRaises(ValueError):
            compile_ambiguity(FOUR, {"evidence": ["A", "B", "P", "note"], "claims": [], "decisions": []})
        with self.assertRaises(ValueError):
            compile_ambiguity(FOUR.replace("A R", "Aé R", 1))


if __name__ == "__main__":
    unittest.main()
