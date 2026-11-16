"""Public-interface tests; no benchmark gold, model calls or learned fixtures."""
from copy import deepcopy
import itertools
import random
import unittest

from retrace.conservation_v6 import audit_conservation


def graph(parents=None, routes=None, labels=None):
    parents = parents or {}
    result = {"evidence": [{"id": name, "kind": "copy" if parents.get(name) else "root",
                            "active": True, "parents": list(parents.get(name, []))} for name in ("A", "B", "X")],
              "claims": [{"id": "C", "supports": routes if routes is not None else [["A"], ["B"]]}],
              "decisions": [{"id": "D", "requires": ["C"]}]}
    for category in result:
        for node in result[category]:
            if labels and node["id"] in labels:
                node["label"] = labels[node["id"]]
    return result


def candidate(value=None, name="one"):
    return {"id": name, "graph": value if value is not None else graph()}


def structural_gaps(result):
    return [gap for gap in result["gaps"] if gap["representation_type"] != "node_presence"]


class ConservationV6Tests(unittest.TestCase):
    def test_id_presence_is_not_lineage(self):
        result = audit_conservation("Evidence X is copied from evidence A.", [candidate()])
        self.assertEqual(result["warning_label"], "Reference-Free Coverage Gap")
        self.assertEqual(len(structural_gaps(result)), 1)
        gap = structural_gaps(result)[0]
        self.assertEqual((gap["target_ids"], gap["referenced_ids"]), (["X"], ["A"]))
        self.assertFalse(any(g["kind"] == "source_node_mention" for g in result["gaps"]))

    def test_union_requires_real_witness_not_all_candidates(self):
        rows = [candidate(name="missing"), candidate(graph({"X": ["A"]}), "represented")]
        result = audit_conservation("X was transcribed from A.", rows)
        relation = [o for o in result["obligations"] if o["kind"] == "lineage_direct"][0]
        self.assertEqual(relation["represented_candidate_ids"], ["represented"])
        self.assertEqual(relation["representations"][0]["parent_edges"], [["X", "A"]])
        self.assertFalse(result["gaps"])

    def test_direct_parent_and_ancestry_are_distinct(self):
        rows = [candidate(graph({"B": ["A"], "X": ["B"]}))]
        derived = audit_conservation("X is derived from A.", rows)
        copied = audit_conservation("X is copied from A.", rows)
        self.assertFalse(derived["gaps"])
        self.assertEqual(len(structural_gaps(copied)), 1)
        witness = next(o for o in derived["obligations"] if o["kind"] == "lineage_ancestor")["representations"][0]
        self.assertEqual(witness["paths"], [["X", "B", "A"]])

    def test_conjunction_cannot_be_assembled_across_candidates(self):
        rows = [candidate(graph(routes=[["A"]]), "a"), candidate(graph(routes=[["B"]]), "b")]
        result = audit_conservation("C requires both A and B.", rows)
        self.assertEqual(len(structural_gaps(result)), 1)
        good = audit_conservation("C requires both A and B.", rows + [candidate(graph(routes=[["A", "B"]]), "joint")])
        self.assertFalse(good["gaps"])

    def test_or_routes_need_same_graph_not_two_selected_branches(self):
        rows = [candidate(graph(routes=[["A"]]), "a"), candidate(graph(routes=[["B"]]), "b")]
        result = audit_conservation("C is supported by either A or B.", rows)
        self.assertEqual(len(structural_gaps(result)), 1)
        self.assertFalse(audit_conservation("C is supported by either A or B.", [candidate()])["gaps"])

    def test_required_conjunction_is_not_just_one_available_route(self):
        value = graph(routes=[["A", "B"], ["X"]])
        value["evidence"][-1]["active"] = False
        result = audit_conservation("C is supported only if A and B are usable.", [candidate(value)])
        self.assertEqual(len(structural_gaps(result)), 1)
        self.assertFalse(audit_conservation("C is supported if A and B are usable.", [candidate(value)])["gaps"])

    def test_mandatory_transitive_requirement_and_decision(self):
        value = graph(routes=[["X"]], parents={"X": ["A", "B"]})
        result = audit_conservation("Claim C requires A and B. Decision D requires claim C.", [candidate(value)])
        self.assertFalse(result["gaps"])
        self.assertFalse(result["unresolved"])

    def test_factorized_sufficiency_remains_literal_gap_with_limit(self):
        value = graph(routes=[["X"]], parents={"X": ["A", "B"]})
        result = audit_conservation("C is supported by A and B.", [candidate(value)])
        self.assertTrue(structural_gaps(result))
        self.assertTrue(any("equivalent factorings" in item for item in result["scope"]))

    def test_implicit_ancestor_yields_alignment_review_not_invented_edge(self):
        result = audit_conservation("X is copied from the same worksheet.", [candidate()])
        self.assertFalse(result["gaps"])
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["unresolved"][0]["kind"], "unaligned_lineage")
        self.assertEqual(result["unresolved"][0]["source_dependency"], "the same worksheet")
        self.assertEqual(result["coverage"]["reference_graph_used"], False)

    def test_exact_labels_and_explicit_aliases_can_align(self):
        value = graph({"X": ["A"]}, labels={"A": "master worksheet"})
        self.assertFalse(audit_conservation("X is copied from the master worksheet.", [candidate(value)])["unresolved"])
        result = audit_conservation('Evidence A is called "master worksheet". X is copied from the master worksheet.', [candidate(graph({"X": ["A"]}))])
        self.assertFalse(result["unresolved"])
        self.assertFalse(result["gaps"])

    def test_ambiguous_labels_and_hypothetical_aliases_are_not_guessed(self):
        value = graph({"X": ["A"]}, labels={"A": "worksheet", "B": "worksheet"})
        self.assertTrue(audit_conservation("X is copied from the worksheet.", [candidate(value)])["unresolved"])
        result = audit_conservation('Suppose evidence A is called "sheet". X is copied from the sheet.', [candidate(graph({"X": ["A"]}))])
        self.assertTrue(result["unresolved"])
        self.assertEqual(result["suppressed"][0]["reason"], "hypothetical_statement")

    def test_negation_hypothetical_and_archived_quote_controls(self):
        prose = 'X is not copied from A. Suppose X is copied from B. Archived quotation: "X is copied from A." C is supported by either A or B.'
        result = audit_conservation(prose, [candidate()])
        self.assertFalse(result["gaps"])
        self.assertFalse(result["unresolved"])
        self.assertEqual(len(result["suppressed"]), 3)

    def test_actual_quoted_policy_is_audited_but_unknown_authority_abstains(self):
        actual = audit_conservation('The current policy states: "C requires A and B."', [candidate()])
        self.assertTrue(structural_gaps(actual))
        quoted = audit_conservation('A commentator wrote "C requires A and B."', [candidate()])
        self.assertFalse(quoted["gaps"])
        self.assertEqual(quoted["unresolved"][0]["reason"], "quotation_authority_or_scope_unresolved")

    def test_unframed_multiline_quotation_does_not_escape_its_context(self):
        text = 'A commentator wrote "\nX is copied from A\nC requires A and B\n". C is supported by A or B.'
        result = audit_conservation(text, [candidate()])
        self.assertFalse(result["gaps"])
        self.assertEqual(len(result["unresolved"]), 2)

    def test_unresolved_boolean_grouping_and_pronouns_abstain(self):
        for prose in ("C is supported by A or B and X.", "It is copied from A.", "C requires either A or B."):
            result = audit_conservation(prose, [candidate()])
            self.assertTrue(result["unresolved"], prose)
            self.assertFalse(result["gaps"], prose)

    def test_exclusive_unknown_selection_needs_both_singleton_branches(self):
        text = "C requires exactly one of A or B, but which is unknown."
        fixed_or = audit_conservation(text, [candidate()])
        self.assertEqual(len(structural_gaps(fixed_or)), 2)
        one = audit_conservation(text, [candidate(graph(routes=[["A"]]))])
        self.assertEqual(len(structural_gaps(one)), 1)
        both = audit_conservation(text, [candidate(graph(routes=[["A"]]), "a"), candidate(graph(routes=[["B"]]), "b")])
        self.assertFalse(both["gaps"])

    def test_source_offsets_unicode_crlf_duplicates_and_documents(self):
        text = "🌱 Notes\r\nX is copied from A.\r\nX is copied from A."
        docs = [{"id": "first", "text": text}, {"id": "second", "text": "C is supported by A."}]
        result = audit_conservation(docs, [candidate(graph(routes=[["A"]]))])
        gaps = structural_gaps(result)
        self.assertEqual(len(gaps), 2)
        self.assertNotEqual(gaps[0]["source_span"]["start"], gaps[1]["source_span"]["start"])
        source = {d["id"]: d["text"] for d in docs}
        for obligation in result["obligations"]:
            span = obligation["source_span"]
            self.assertEqual(source[span["document_id"]][span["start"]:span["end"]], span["text"])

    def test_registry_missing_source_node_and_identifier_boundaries(self):
        registry = {"evidence": ["A", "B", "X", "OLD"], "claims": ["C"], "decisions": ["D"]}
        result = audit_conservation("Evidence OLD exists. C is supported by A.", [candidate(graph(routes=[["A"]]))], registry)
        self.assertEqual([g["target_ids"] for g in result["gaps"]], [["OLD"]])
        self.assertFalse(audit_conservation('Historical quotation: "OLD is copied from A." C is supported by A.', [candidate(graph(routes=[["A"]]))], registry)["gaps"])
        result = audit_conservation("AXIS and BETA are names.", [candidate()])
        self.assertEqual(result["mentions"], [])

    def test_metadata_alone_cannot_clear_gap(self):
        metadata = {"operators": [{"id": "op", "kind": "UNVERIFIED_INDEPENDENCE", "target": "X", "options": [
            {"answer": False, "replacement": {"kind": "copy", "parents": ["A"]}},
            {"answer": True, "replacement": {"kind": "root", "parents": []}}]}]}
        result = audit_conservation("X is copied from A.", [candidate()], compilation=metadata)
        self.assertTrue(structural_gaps(result))
        self.assertFalse(result["compiler_annotations"][0]["all_options_present"])

    def test_order_paraphrase_and_no_input_mutation(self):
        rows = [candidate(graph({"X": ["A"]}), "b"), candidate(name="a")]
        before = deepcopy(rows)
        for text in ("X was copied from A.", "Evidence X is a copy of evidence A.", "X was transcribed from A."):
            self.assertFalse(audit_conservation(text, rows)["gaps"])
        self.assertEqual(rows, before)
        self.assertEqual(audit_conservation("X is copied from A.", rows), audit_conservation("X is copied from A.", list(reversed(rows))))

    def test_explicit_bounds_and_malformed_inputs_fail_without_partial_result(self):
        bad = graph(); bad["evidence"][0]["active"] = 1
        cyclic = graph({"A": ["X"], "X": ["A"]})
        for rows in ([], [candidate()]*17, [candidate(), candidate()], [candidate(bad)], [candidate(cyclic)]):
            with self.assertRaises(ValueError): audit_conservation("X is copied from A.", rows)
        for prose in ("x"*65_537, [{"id": "d", "text": "x", "gold": []}], [{"id": "d", "text": "x"}]*2,
                      [{"id": str(i), "text": "x"} for i in range(33)], "\ud800", "A. "*2_049):
            with self.assertRaises(ValueError): audit_conservation(prose, [candidate()])
        with self.assertRaises(ValueError):
            audit_conservation("A.", [candidate()], {"evidence": ["A", "A"], "claims": [], "decisions": []})
        with self.assertRaises(ValueError):
            audit_conservation("A.", [candidate()], {"evidence": ["A"*129], "claims": [], "decisions": []})

    def test_mandatory_requirements_against_independent_truth_tables(self):
        randomizer = random.Random(614271)
        for trial in range(80):
            roots = ["A", "B", "X"]
            clauses = lambda ids: randomizer.sample([list(c) for size in range(1, len(ids)+1) for c in itertools.combinations(ids, size)], randomizer.randint(1, 3))
            value = graph(routes=clauses(roots))
            value["claims"].append({"id": "K", "supports": clauses(roots + ["C"])})
            value["decisions"][0]["requires"] = ["K"]
            for required in roots:
                counterexample = False
                for bits in itertools.product([False, True], repeat=3):
                    truth = dict(zip(roots, bits))
                    for node in value["claims"]:
                        truth[node["id"]] = any(all(truth[x] for x in route) for route in node["supports"])
                    counterexample |= truth["K"] and not truth[required]
                result = audit_conservation(f"K requires {required}.", [candidate(value)])
                self.assertEqual(bool(structural_gaps(result)), counterexample, (trial, required, value))


if __name__ == "__main__":
    unittest.main()
