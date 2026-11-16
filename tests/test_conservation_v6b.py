"""Offline clause-parser controls; fresh v6b holdout is never opened here."""
from copy import deepcopy
import itertools
import random
import unittest

from retrace.conservation_v6b import audit_conservation


def candidates(parents=None, routes=None, requires=None):
    parents = parents or {}
    return [{"id": "one", "graph": {
        "evidence": [{"id": key, "kind": "copy" if key in parents else "root", "active": True,
                      "parents": list(parents.get(key, []))} for key in ("E1", "E2", "E3")],
        "claims": [{"id": "C1", "supports": routes if routes is not None else [["E1"], ["E2"]]},
                   {"id": "C2", "supports": [["E3"]]}],
        "decisions": [{"id": "D1", "requires": requires if requires is not None else ["C1"]}]}}]


def structural(result):
    return [item for item in result["gaps"] if item["representation_type"] != "node_presence"]


class ConservationV6bTests(unittest.TestCase):
    def test_ids_inside_noun_phrases_and_appositive_decision(self):
        text = "The checkout-card copy E3 was copied from the original ledger E1. Decision D1, display the card publicly, requires only signed review C1."
        result = audit_conservation(text, candidates())
        self.assertEqual([(g["target_ids"], g["referenced_ids"]) for g in structural(result)], [(["E3"], ["E1"])])
        self.assertFalse(result["unresolved"])

    def test_explicit_source_id_missing_from_registry_and_graph_is_detected(self):
        rows = candidates()
        registry = {category: [node["id"] for node in rows[0]["graph"][category]] for category in rows[0]["graph"]}
        before = deepcopy((rows, registry))
        text = "Evidence Z9 is the original attendance sheet. Card E3 was copied from record Z9."
        result = audit_conservation(text, rows, registry)
        self.assertTrue(any(g["representation_type"] == "node_presence" and g["target_ids"] == ["Z9"] for g in result["gaps"]))
        self.assertTrue(any(g["target_ids"] == ["E3"] and g["referenced_ids"] == ["Z9"] for g in structural(result)))
        self.assertTrue(any(d["node_id"] == "Z9" and d["category"] == "evidence" for d in result["source_declared_entities"]))
        self.assertEqual((rows, registry), before)

    def test_historical_hypothetical_and_incidental_words_do_not_declare_missing_nodes(self):
        text = ('Historical quotation: "Record Z9 was copied from OLD8." '
                'Suppose evidence FAKE7 is an original. Record Keeping is the heading on a binder. '
                'A commentator wrote "Evidence QUOTED7 is an original." Review C1 accepts E1 alone or E2 alone.')
        result = audit_conservation(text, candidates())
        self.assertFalse(result["gaps"])
        self.assertFalse({"Z9", "OLD8", "FAKE7", "Keeping", "QUOTED7"} & {d["node_id"] for d in result["source_declared_entities"]})
        self.assertTrue(result["unresolved"])

    def test_conflicting_explicit_source_type_remains_review(self):
        result = audit_conservation("Claim E1 requires E2.", candidates())
        self.assertTrue(any(item["kind"] == "source_type_conflict" for item in result["unresolved"]))

    def test_coordinated_copy_clauses_are_not_one_conjunction(self):
        text = "Copy E2 was copied from E1, and copy E3 was copied from E1."
        result = audit_conservation(text, candidates({"E2": ["E1"]}))
        self.assertEqual([g["target_ids"] for g in structural(result)], [["E3"]])
        self.assertFalse(result["unresolved"])

    def test_coordinated_review_and_decision_clause(self):
        result = audit_conservation("Review C1 accepts E1 alone, and decision D1 requires review C1 alone.", candidates(routes=[["E1"]]))
        self.assertFalse(result["gaps"])
        self.assertFalse(result["unresolved"])

    def test_production_verb_frames_preserve_lineage_direction(self):
        texts = ("The production ledger states that E2 takes all its recorded readings from E1.",
                 "The entry says E2 is a second transcription of original tally E1.",
                 "Working document E2 was produced by retyping the dated source E1 line for line.")
        for text in texts:
            result = audit_conservation(text, candidates())
            self.assertEqual([(g["target_ids"], g["referenced_ids"]) for g in structural(result)], [(["E2"], ["E1"])], text)

    def test_joint_requirement_is_not_or_and_only_does_not_break_alignment(self):
        for text in ("The release review C1 clears only on the joint warrant of E1 and E2.",
                     "Review C1 requires both check E1 and check E2 together as its only sufficient route."):
            self.assertTrue(structural(audit_conservation(text, candidates())))
            self.assertFalse(structural(audit_conservation(text, candidates(routes=[["E1", "E2"]]))))
        self.assertTrue(structural(audit_conservation("Posting decision D1 requires both review C1 and review C2.", candidates())))

    def test_alone_alternative_route_group_is_checked_in_one_graph(self):
        text = "Review C1 has two sufficient routes: E1 alone, or E2 alone."
        self.assertFalse(audit_conservation(text, candidates())["gaps"])
        rows = candidates(routes=[["E1"]]) + [{**candidates(routes=[["E2"]])[0], "id": "two"}]
        self.assertEqual(len(structural(audit_conservation(text, rows))), 1)

    def test_mixed_scope_is_unresolved_unless_grouping_is_explicit(self):
        ambiguous = audit_conservation("Review C1 accepts E1 or E2 and E3.", candidates())
        self.assertTrue(ambiguous["unresolved"])
        self.assertFalse(ambiguous["gaps"])
        rows = candidates(routes=[["E1"], ["E2", "E3"]])
        for text in ("Review C1 accepts E1 alone or both E2 and E3 together.",
                     "Review C1 accepts E1 or (E2 and E3)."):
            result = audit_conservation(text, rows)
            self.assertFalse(result["gaps"])
            self.assertFalse(result["unresolved"])
        self.assertTrue(audit_conservation("Review C1 accepts (E1 or E2) and E3.", rows)["unresolved"])

    def test_real_quoted_rule_and_superseded_draft_have_different_scope(self):
        registry = {"evidence": ["E1", "E2", "E3", "OLD"], "claims": ["C1", "C2"], "decisions": ["D1"]}
        text = ('The signed operating rule is authoritative: "Review C1 requires both E1 and E2 together." '
                'For historical discussion, the archivist quotes a superseded draft: "E2 was copied from OLD." '
                'The historical identifier OLD has no role in the present register.')
        result = audit_conservation(text, candidates(routes=[["E1", "E2"]]), registry)
        self.assertFalse(result["gaps"])
        self.assertFalse(result["unresolved"])
        self.assertEqual(len(result["suppressed"]), 2)

    def test_question_negation_and_counterfactual_do_not_create_edges(self):
        text = ('Record E2 was not copied from E1. A future meeting question asks: "Should C1 require E1 and E2?" '
                'A training handout poses a counterfactual: "If E2 were copied from E1, it would need E1." '
                'Current review C1 accepts E1 alone or E2 alone.')
        result = audit_conservation(text, candidates())
        self.assertFalse(result["gaps"])
        self.assertFalse(result["unresolved"])
        self.assertEqual(len(result["suppressed"]), 3)

    def test_bookkeeping_is_visible_not_a_generic_dependency_warning(self):
        text = "Evidence E1 is locally ineligible. E2 and E3 are independent original records. Both have no parents. No additional support routes are specified."
        result = audit_conservation(text, candidates())
        self.assertFalse(result["unresolved"])
        self.assertGreaterEqual(len(result["accounted"]), 3)
        self.assertTrue(any("outside this audit" in str(item) for item in result["accounted"]))

    def test_implicit_ancestor_still_requires_alignment(self):
        result = audit_conservation("Both operators transcribed the same unnumbered field book.", candidates())
        self.assertFalse(result["gaps"])
        self.assertTrue(result["unresolved"])
        self.assertEqual(result["unresolved"][0]["kind"], "unaligned_lineage")
        self.assertFalse(result["unresolved"][0]["referenced_ids"])

    def test_uncertain_origin_checks_both_branches_without_asserting_copy(self):
        text = ("The provenance note for E2 is missing. It could be a copy of E1, with E1 as its sole required parent, "
                "or it could be an independent original with no parents.")
        rows = candidates({"E2": ["E1"]}) + [{**candidates()[0], "id": "two"}]
        result = audit_conservation(text, rows)
        self.assertFalse(result["gaps"])
        self.assertFalse(result["unresolved"])
        self.assertTrue(audit_conservation(text, candidates())["gaps"])
        self.assertTrue(audit_conservation("The provenance note for E2 is missing.", candidates())["unresolved"])

    def test_unbound_modal_and_unknown_authority_remain_unresolved(self):
        for text in ('It could be a copy of E1 or an independent original.',
                     'Someone wrote "Review C1 requires E1 and E2."',
                     'It is unknown whether record E2 was copied from E1.',
                     'Record E2 is either an original or was copied from E1.',
                     'Review C1 relies upon the uncertified worksheet.'):
            result = audit_conservation(text, candidates())
            self.assertTrue(result["unresolved"], text)
            self.assertFalse(structural(result), text)

    def test_codepoint_spans_and_inputs_are_unchanged(self):
        source = [{"id": "u", "text": '🌿 Header\r\nThe rule is authoritative: "Review C1 accepts E1 alone or E2 alone."'}]
        rows = candidates(); before = deepcopy((source, rows))
        result = audit_conservation(source, rows)
        for item in result["obligations"] + result["accounted"] + result["unresolved"]:
            span = item["source_span"]
            self.assertEqual(source[0]["text"][span["start"]:span["end"]], span["text"])
        self.assertEqual((source, rows), before)

    def test_unknown_new_dependency_is_not_erased_by_bookkeeping(self):
        result = audit_conservation("Record E3 fuses the original records E1 and E2 into one shared source.", candidates())
        self.assertTrue(result["unresolved"])
        self.assertFalse(result["gaps"])

    def test_unnamed_operands_and_qualifiers_are_not_dropped(self):
        for text in ("Review C1 accepts E1 and the unnumbered permit.",
                     "Review C1 accepts the unnumbered permit and E1.",
                     "Review C1 accepts E1 and an unnamed authorization and E2.",
                     "Review C1 accepts E1 when the unnumbered permit is valid."):
            result = audit_conservation(text, candidates(routes=[["E1"]]))
            self.assertTrue(result["unresolved"], text)
            self.assertFalse(structural(result), text)

    def test_anaphoric_restatement_requires_prior_recognized_group(self):
        present = audit_conservation("Review C1 accepts E1 alone or E2 alone; either is a complete sufficient route.", candidates())
        self.assertFalse(present["unresolved"])
        self.assertTrue(any(item["reason"] == "anaphoric_alternative_restatement" for item in present["accounted"]))
        self.assertTrue(audit_conservation("Either is a complete sufficient route.", candidates())["unresolved"])

    def test_bounds_fail_without_partial_audit(self):
        for text in ("x" * 65_537, "E1. " * 2_049):
            with self.assertRaises(ValueError): audit_conservation(text, candidates())
        with self.assertRaises(ValueError): audit_conservation("E1.", candidates()*17)

    def test_id_renaming_and_candidate_row_order_invariance(self):
        text = "Public card E3 was copied from original tally E1. Review C1 requires both E1 and E2."
        first = audit_conservation(text, candidates())
        mapping = {"E1": "N7", "E2": "N8", "E3": "N9", "C1": "K7", "C2": "K8", "D1": "Q7"}
        import json
        changed = json.dumps(candidates())
        for old, new in mapping.items():
            changed = changed.replace('"'+old+'"', '"'+new+'"')
            text = text.replace(old, new)
        rows = json.loads(changed)
        for category in rows[0]["graph"]:
            rows[0]["graph"][category].reverse()
        second = audit_conservation(text, rows)
        self.assertEqual(len(structural(first)), len(structural(second)))
        self.assertEqual(first["status"], second["status"])

    def test_conditional_requirements_against_independent_small_truth_tables(self):
        rng = random.Random(66197)
        all_routes = [list(c) for n in (1,2,3) for c in itertools.combinations(("E1","E2","E3"), n)]
        for _ in range(50):
            routes = rng.sample(all_routes, rng.randint(1, len(all_routes)))
            for ref in ("E1", "E2", "E3"):
                counterexample = any(any(all(dict(zip(("E1","E2","E3"), bits))[x] for x in route) for route in routes)
                                     and not dict(zip(("E1","E2","E3"), bits))[ref]
                                     for bits in itertools.product((False,True), repeat=3))
                result = audit_conservation(f"The signed review C1 is supported only while record {ref} is usable.", candidates(routes=routes))
                self.assertEqual(bool(structural(result)), counterexample)


if __name__ == "__main__":
    unittest.main()
