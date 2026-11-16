"""Independent behavioral checks for exact cited counter-reading proposals."""
import copy
import hashlib
import itertools
import json
import unittest

from retrace.falsification_v6 import parse_counter_reading, verify_counter_reading


QUOTE = "Either signed card A or signed card B is enough."


def fixture():
    graph = {
        "evidence": [{"id": "a", "kind": "root", "active": True, "parents": []},
                     {"id": "b", "kind": "root", "active": True, "parents": []}],
        "claims": [{"id": "c", "supports": [["a"], ["b"]]},
                   {"id": "other", "supports": [["b"]]}],
        "decisions": [{"id": "d", "requires": ["c"]}],
    }
    public = {"source_documents": [{"id": "doc", "text": "🙂 Cafe\u0301 note. " + QUOTE + " A and B are independent observations."}],
              "registry": {k: [r["id"] for r in graph[k]] for k in ("evidence", "claims", "decisions")},
              "candidates": [{"id": "first", "graph": graph}]}
    proposal = {"status": "counter_reading", "changes": [
        {"target": "c", "replacement": {"supports": [["a", "b"]]},
         "sources": [{"document_id": "doc", "quote": QUOTE}]}]}
    return public, proposal


def scalar(graph, flags):
    """Independent fixed-point oracle; does not import production evaluators."""
    values = {r["id"]: False for category in ("evidence", "claims", "decisions") for r in graph[category]}
    for _ in range(len(values) + 2):
        nxt = {}
        for node in graph["evidence"]:
            nxt[node["id"]] = flags[node["id"]] and all(values[p] for p in node.get("parents", []))
        for node in graph["claims"]:
            nxt[node["id"]] = any(all(values[p] for p in route) for route in node["supports"])
        for node in graph["decisions"]:
            nxt[node["id"]] = all(values[p] for p in node["requires"])
        if nxt == values:
            return {node["id"]: nxt[node["id"]] for node in graph["decisions"]}
        values = nxt
    raise AssertionError("Finite acyclic scalar evaluation did not converge")


class CounterReadingTests(unittest.TestCase):
    def test_unique_quote_computes_unicode_codepoint_offsets_and_hash(self):
        public, proposal = fixture()
        result = verify_counter_reading(public, proposal)
        source = public["source_documents"][0]["text"]
        span = result["source_spans"][0]
        self.assertEqual(span["start"], source.index(QUOTE))
        self.assertEqual(span["end"], source.index(QUOTE) + len(QUOTE))
        self.assertEqual(source[span["start"]:span["end"]], QUOTE)
        self.assertEqual(span["source_text_sha256"], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(span["resolution"], "unique_exact_quote")
        self.assertEqual(span["index_unit"], "unicode_code_point")
        self.assertTrue(span["end_exclusive"])

    def test_repeated_and_overlapping_quotes_need_exact_disambiguation(self):
        for text, quote, offset in [(QUOTE + " " + QUOTE, QUOTE, len(QUOTE) + 1), ("aaa", "aa", 1)]:
            public, proposal = fixture()
            public["source_documents"][0]["text"] = text
            citation = proposal["changes"][0]["sources"][0]
            citation["quote"] = quote
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "multiple exact"):
                    verify_counter_reading(public, proposal)
                citation.update(start=offset, end=offset + len(quote))
                result = verify_counter_reading(public, proposal)
                self.assertEqual(result["source_spans"][0]["start"], offset)
                self.assertEqual(result["source_spans"][0]["resolution"], "explicit_exact_offsets")

    def test_mismatch_normalization_and_partial_offsets_are_not_repaired(self):
        for mutation in ("case", "normalized", "offset", "one_offset", "boolean", "empty", "hash"):
            public, proposal = fixture()
            citation = proposal["changes"][0]["sources"][0]
            if mutation == "case": citation["quote"] = QUOTE.lower()
            elif mutation == "normalized": citation["quote"] = "Café"
            elif mutation == "offset": citation.update(start=0, end=len(QUOTE))
            elif mutation == "one_offset": citation["start"] = 0
            elif mutation == "boolean": citation.update(start=False, end=4)
            elif mutation == "empty": citation["quote"] = ""
            else: citation["source_text_sha256"] = "invented"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify_counter_reading(public, proposal)

    def test_source_binding_changes_even_when_same_quote_still_exists(self):
        public, proposal = fixture()
        first = verify_counter_reading(public, proposal)
        public["source_documents"][0]["text"] = "New prefix. " + public["source_documents"][0]["text"]
        second = verify_counter_reading(public, proposal)
        self.assertNotEqual(first["public_input_sha256"], second["public_input_sha256"])
        self.assertNotEqual(first["source_spans"][0]["source_text_sha256"], second["source_spans"][0]["source_text_sha256"])
        self.assertGreater(second["source_spans"][0]["start"], first["source_spans"][0]["start"])

    def test_all_citations_returned_with_target_binding(self):
        public, proposal = fixture()
        proposal["changes"][0]["sources"].append({"document_id": "doc", "quote": "independent observations"})
        result = verify_counter_reading(public, proposal)
        self.assertEqual(len(result["source_spans"]), 2)
        self.assertEqual({s["target"] for s in result["source_spans"]}, {"c"})
        self.assertEqual(len(result["changes"][0]["sources"]), 2)

    def test_quote_and_counterexample_do_not_verify_entailment(self):
        public, proposal = fixture()
        # This exact quote says OR; the proposed AND is not licensed by it.
        # The mechanical checker must not pretend to decide that semantic fact.
        result = verify_counter_reading(public, proposal)
        self.assertEqual(result["status"], "mechanically_checked_semantically_unverified")
        self.assertFalse(result["semantic_verified"])
        self.assertFalse(result["auto_applied"])
        self.assertFalse(result["reference_graph_used"])
        self.assertTrue(result["consequential_within_scope"])

    def test_no_mutation_on_success_or_rejection(self):
        public, proposal = fixture()
        before_public, before_proposal = copy.deepcopy(public), copy.deepcopy(proposal)
        result = verify_counter_reading(public, proposal)
        self.assertEqual(public, before_public)
        self.assertEqual(proposal, before_proposal)
        result["counter_graph"]["evidence"][0]["active"] = False
        result["original_candidates"][0]["graph"]["claims"][0]["supports"] = []
        self.assertEqual(public, before_public)
        bad = copy.deepcopy(proposal)
        bad["changes"][0]["replacement"] = {"supports": [["c"]]}
        with self.assertRaises(ValueError): verify_counter_reading(public, bad)
        self.assertEqual(public, before_public)

    def test_independent_scalar_enumeration_matches_witness_and_minimum(self):
        public, proposal = fixture()
        result = verify_counter_reading(public, proposal)
        original, counter = result["original_graph"], result["counter_graph"]
        initial = {r["id"]: r["active"] for r in original["evidence"]}
        distinguishing = []
        for bits in itertools.product((False, True), repeat=2):
            flags = dict(zip(sorted(initial), bits))
            if scalar(original, flags)["d"] != scalar(counter, flags)["d"]:
                distinguishing.append(sum(flags[e] != initial[e] for e in initial))
        d = result["exposure"]["decisions"]["d"]
        self.assertEqual(d["distinguishing_state_count"], len(distinguishing))
        self.assertEqual(d["minimum"]["total_changes"], min(distinguishing))
        w = d["minimum"]
        flags = {e: e not in w["withdraw"] for e in initial}
        self.assertEqual(w["outcomes"], {"seed": scalar(original, flags)["d"], "counter_reading": scalar(counter, flags)["d"]})

    def test_masked_gate_requires_enable_plus_withdrawal_and_locked_gate_blocks(self):
        public, proposal = fixture()
        graph = public["candidates"][0]["graph"]
        graph["evidence"].append({"id": "gate", "kind": "root", "active": False, "parents": []})
        public["registry"]["evidence"].append("gate")
        graph["claims"][0]["supports"] = [["gate", "a"], ["gate", "b"]]
        proposal["changes"][0]["replacement"]["supports"] = [["gate", "a", "b"]]
        result = verify_counter_reading(public, proposal)
        w = result["exposure"]["decisions"]["d"]["minimum"]
        self.assertEqual((w["enable_count"], w["withdraw_count"]), (1, 1))
        self.assertEqual(w["enable"], ["gate"])
        original, changed = result["original_graph"], result["counter_graph"]
        counts = []
        initial = {r["id"]: r["active"] for r in original["evidence"]}
        for bits in itertools.product((False, True), repeat=3):
            flags = dict(zip(sorted(initial), bits))
            if scalar(original, flags) != scalar(changed, flags):
                counts.append((sum(flags[e] and not initial[e] for e in initial),
                               sum(initial[e] and not flags[e] for e in initial)))
        self.assertEqual(min(counts), (1, 1))
        public["locked_exclusions"] = ["gate"]
        locked = verify_counter_reading(public, proposal)
        self.assertFalse(locked["consequential_within_scope"])
        self.assertEqual(locked["exposure"]["coverage"]["locked_exclusions"], ["gate"])

    def test_evidence_kind_parent_and_decision_body_replacements(self):
        for target, body in [("b", {"kind": "copy", "parents": ["a"]}), ("d", {"requires": ["other"]})]:
            public, proposal = fixture()
            proposal["changes"][0].update(target=target, replacement=body)
            result = verify_counter_reading(public, proposal)
            self.assertTrue(result["consequential_within_scope"])
            self.assertEqual({r["id"]: r["active"] for r in result["original_graph"]["evidence"]},
                             {r["id"]: r["active"] for r in result["counter_graph"]["evidence"]})

    def test_two_edits_are_validated_simultaneously(self):
        public, proposal = fixture()
        g = public["candidates"][0]["graph"]
        g["claims"][0]["supports"] = [["a"]]
        g["claims"][1]["supports"] = [["c"]]
        citation = {"document_id": "doc", "quote": QUOTE}
        proposal["changes"] = [
            {"target": "c", "replacement": {"supports": [["other"]]}, "sources": [citation]},
            {"target": "other", "replacement": {"supports": [["b"]]}, "sources": [citation]}]
        result = verify_counter_reading(public, proposal)
        self.assertEqual(len(result["changes"]), 2)
        self.assertTrue(result["consequential_within_scope"])

    def test_irrelevant_edit_has_no_target_witness(self):
        public, proposal = fixture()
        proposal["changes"][0].update(target="other", replacement={"supports": [["a"]]})
        result = verify_counter_reading(public, proposal)
        self.assertFalse(result["consequential_within_scope"])
        self.assertIsNone(result["exposure"]["decisions"]["d"]["minimum"])
        self.assertFalse(result["semantic_verified"])

    def test_different_unanimous_seeds_require_explicit_selection(self):
        public, proposal = fixture()
        second = copy.deepcopy(public["candidates"][0])
        second["id"] = "second"
        second["graph"]["claims"][0]["supports"] = [["a", "b"]]
        public["candidates"].append(second)
        with self.assertRaisesRegex(ValueError, "Select seed"):
            verify_counter_reading(public, proposal)
        proposal["seed_candidate_id"] = "first"
        result = verify_counter_reading(public, proposal)
        self.assertTrue(result["seed_pool_unanimous"])
        self.assertTrue(result["already_in_seed_pool"])
        self.assertEqual(result["seed_candidate_id"], "first")

    def test_nonunanimous_or_different_local_baseline_rejected(self):
        for change_flag in (False, True):
            public, proposal = fixture()
            second = copy.deepcopy(public["candidates"][0])
            second["id"] = "second"
            if change_flag: second["graph"]["evidence"][0]["active"] = False
            else: second["graph"]["claims"][0]["supports"] = []
            public["candidates"].append(second)
            with self.subTest(change_flag=change_flag), self.assertRaises(ValueError):
                verify_counter_reading(public, proposal)

    def test_no_counter_reading_is_not_completeness_evidence(self):
        public, _ = fixture()
        result = verify_counter_reading(public, {"status": "no_counter_reading"})
        self.assertEqual(result["proposal_status"], "no_counter_reading")
        self.assertEqual(result["status"], "mechanically_checked_semantically_unverified")
        self.assertFalse(result["semantic_verified"])
        self.assertIsNone(result["counter_graph"])
        self.assertEqual(result["source_spans"], [])
        self.assertIsNone(result["exposure"])

    def test_strict_json_duplicate_keys_fences_and_nonfinite_rejected(self):
        invalid = ['{"status":"no_counter_reading","status":"counter_reading"}',
                   '{"changes":[{"target":"c","target":"a"}]}',
                   '{"status":"no_counter_reading","changes":NaN}',
                   '```json\n{"status":"no_counter_reading"}\n```', '[]']
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError): parse_counter_reading(text)
        public, proposal = fixture()
        result = verify_counter_reading(json.dumps(public), json.dumps(proposal))
        self.assertTrue(result["consequential_within_scope"])
        duplicate_public = '{"candidates":[],"candidates":[],"registry":{}}'
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            verify_counter_reading(duplicate_public, proposal)

    def test_unknown_fields_gold_metadata_and_changed_eligibility_rejected(self):
        for mutation in ("hidden", "gold", "eligibility", "label", "new_id", "wrong_type", "revoke", "schema_extra"):
            public, proposal = fixture()
            if mutation in ("hidden", "gold"): public[mutation] = {"reference": "not allowed"}
            elif mutation == "eligibility": proposal["changes"][0].update(target="b", replacement={"kind": "root", "parents": [], "active": False})
            elif mutation == "label": proposal["changes"][0]["replacement"]["label"] = "renamed"
            elif mutation == "new_id": proposal["changes"][0]["target"] = "invented"
            elif mutation == "wrong_type": proposal["changes"][0].update(target="d", replacement={"requires": ["a"]})
            elif mutation == "revoke": public["candidates"][0]["graph"]["revoke"] = ["a"]
            else: proposal["rationale"] = "not part of schema"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify_counter_reading(public, proposal)

    def test_zero_three_duplicate_uncited_noop_and_cyclic_changes_rejected(self):
        for mutation in ("zero", "three", "duplicate", "uncited", "noop", "cycle", "bad_parent", "duplicate_route", "unknown_doc", "duplicate_citation"):
            public, proposal = fixture()
            change = proposal["changes"][0]
            if mutation == "zero": proposal["changes"] = []
            elif mutation == "three": proposal["changes"] *= 3
            elif mutation == "duplicate": proposal["changes"] *= 2
            elif mutation == "uncited": change["sources"] = []
            elif mutation == "noop": change["replacement"] = {"supports": [["b"], ["a"]]}
            elif mutation == "cycle": change["replacement"] = {"supports": [["c"]]}
            elif mutation == "bad_parent": change.update(target="b", replacement={"kind": "copy", "parents": ["c"]})
            elif mutation == "duplicate_route": change["replacement"] = {"supports": [["a"], ["a"]]}
            elif mutation == "unknown_doc": change["sources"][0]["document_id"] = "other"
            else: change["sources"] *= 2
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify_counter_reading(public, proposal)

    def test_documents_alias_supported_but_ambiguous_aliases_reject(self):
        public, proposal = fixture()
        public["documents"] = public.pop("source_documents")
        self.assertEqual(len(verify_counter_reading(public, proposal)["source_spans"]), 1)
        public["source_documents"] = copy.deepcopy(public["documents"])
        with self.assertRaises(ValueError): verify_counter_reading(public, proposal)

    def test_null_seed_and_padded_noop_edit_are_rejected(self):
        public, proposal = fixture()
        proposal["seed_candidate_id"] = None
        with self.assertRaises(ValueError): verify_counter_reading(public, proposal)
        proposal.pop("seed_candidate_id")
        proposal["changes"].append({"target": "other", "replacement": {"supports": [["b"]]},
                                    "sources": [{"document_id": "doc", "quote": QUOTE}]})
        with self.assertRaisesRegex(ValueError, "Every listed change"):
            verify_counter_reading(public, proposal)


if __name__ == "__main__":
    unittest.main()
