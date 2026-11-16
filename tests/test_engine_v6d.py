"""Offline product checks: source binding, complete branches, previews and HTTP."""
from copy import deepcopy
import http.client
from http.server import ThreadingHTTPServer
import itertools
import json
import threading
import unittest

from retrace.core import analyze
from retrace.engine_v6d import analyze_v6d, demo_brief, preview_exposure, preview_refuter
from retrace.server_v6d import HandlerV6d
from retrace.source_ir_v6d import source_segments


def five_choices():
    brief = demo_brief()
    old = source_segments(brief["source_documents"])[-1]["span_id"]
    brief["source_documents"][-1]["text"] = brief["source_documents"][-1]["text"].replace("All three", "All five")
    new = source_segments(brief["source_documents"])[-1]["span_id"]
    def replace(value):
        if isinstance(value, dict): return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list): return [replace(v) for v in value]
        return new if value == old else value
    brief["source_ir"] = replace(brief["source_ir"])
    for number in (1, 2):
        eid, qid, docid = f"Z{number}", f"extra{number}", f"extra-source{number}"
        brief["source_documents"].append({"id": docid, "text": f"{eid} is locally eligible evidence. Its origin is independently either an original without parents, or a copy with sole parent A. Both readings are admitted. No decision uses it."})
        sid = source_segments(brief["source_documents"])[-1]["span_id"]
        brief["registry"]["evidence"].append(eid)
        brief["source_ir"]["entities"].append({"id": eid, "type": "evidence", "operational": True, "citations": [sid]})
        brief["source_ir"]["choices"].append({"id": qid, "options": ["original", "copy"], "citations": [sid]})
        def prop(kind, body, when=None):
            return {"id": eid + kind + str(len(brief["source_ir"]["propositions"])), "kind": kind, "target": eid, "body": body,
                    "scope": "current", "polarity": "assert", "when": when or {}, "citations": [sid], "bindings": []}
        brief["source_ir"]["propositions"].append(prop("eligibility", {"active": True}))
        brief["source_ir"]["propositions"].append(prop("origin", {"kind": "root", "parents": []}, {qid: "original"}))
        brief["source_ir"]["propositions"].append(prop("origin", {"kind": "copy", "parents": ["A"]}, {qid: "copy"}))
    brief.pop("clarifications")
    return brief


class WorkbenchTests(unittest.TestCase):
    def test_constructed_demo_current_cost_and_exact_three_way_witness(self):
        result = analyze_v6d(demo_brief())
        self.assertEqual(result["provenance"], "constructed_offline_demonstration")
        self.assertEqual(result["compilation"]["candidate_count"], 8)
        stress = result["stress"]
        self.assertEqual(stress["next_question"]["id"], "lineage")
        self.assertEqual(stress["next_question"]["worst_case_cost"], 1)
        release = stress["decision_witnesses"]["RELEASE"]
        self.assertEqual(release["minimum_distinguishing"]["withdraw"], ["A", "B", "C"])
        self.assertEqual(release["minimum_break_any"]["k"], 3)
        self.assertEqual(release["minimum_break_all"]["k"], 4)
        self.assertEqual(stress["decision_states"]["LEGACY"]["classification"], "unsupported")

    def test_unknown_preserves_all_candidates_known_answer_stops_early(self):
        brief = demo_brief()
        unknown = analyze_v6d(brief, {"answers": {"lineage": None}})
        known = analyze_v6d(brief, {"answers": {"lineage": True}})
        self.assertEqual(len(unknown["stress"]["candidate_ids"]), 8)
        self.assertEqual(len(known["stress"]["candidate_ids"]), 4)
        self.assertIsNone(known["stress"]["next_question"])
        self.assertEqual(known["stress"]["consensus"]["clarification"]["worst_case_cost"], 0)

    def test_scenario_exposes_latent_question_without_rewriting_baseline(self):
        brief = demo_brief(); before = deepcopy(brief)
        result = analyze_v6d(brief, {"answers": {"lineage": True}, "scenario_withdrawals": ["A", "B", "C"]})
        self.assertEqual(result["stress"]["next_question"]["id"], "route")
        self.assertEqual(result["stress"]["decision_states"]["RELEASE"]["classification"], "needs_review")
        self.assertEqual(brief, before)

    def test_document_and_passage_vetoes_remain_independent(self):
        brief = demo_brief()
        first = analyze_v6d(brief, {"revoked_documents": ["source-2"], "revoked_passages": ["X"]})
        cleared = analyze_v6d(brief, {"revoked_documents": [], "revoked_passages": ["X"]})
        self.assertTrue(first["stress"]["revocation_flags"]["X"]["document_veto"])
        self.assertFalse(cleared["stress"]["revocation_flags"]["X"]["document_veto"])
        self.assertTrue(cleared["stress"]["revocation_flags"]["X"]["passage_veto"])
        self.assertTrue(all(not item["usable"] for item in cleared["record_states"]["X"]["by_candidate"].values()))
        self.assertEqual(cleared["stress"]["decision_states"]["LINEAGE"]["classification"], "revoked")

    def test_inherited_unusability_is_not_local_ineligibility(self):
        result = analyze_v6d(demo_brief(), {"answers": {"lineage": False}})
        for row in result["record_states"]["X"]["by_candidate"].values():
            self.assertTrue(row["original_active"]); self.assertTrue(row["effective_active"]); self.assertFalse(row["usable"])

    def test_source_change_rejects_reused_state_and_old_span(self):
        brief = demo_brief(); result = analyze_v6d(brief)
        brief["title"] = "Edited declaration"
        with self.assertRaisesRegex(ValueError, "changed"):
            analyze_v6d(brief, result["state"], result["declaration_fingerprint"])
        self.assertEqual(analyze_v6d(brief)["provenance"], "supplied_unverified_interpretation")
        brief["source_documents"][0]["text"] += " Changed."
        with self.assertRaisesRegex(ValueError, "Unknown source span"):
            analyze_v6d(brief)

    def test_refuter_comparison_is_unlicensed_only_relative_to_declaration(self):
        brief = demo_brief(); before = deepcopy(brief); proposed = deepcopy(brief["source_ir"])
        row = next(p for p in proposed["propositions"] if p["kind"] == "support" and p["target"] == "M")
        row["body"] = {"expr": {"ref": "A"}}
        preview = preview_refuter(brief, proposed, {"answers": {"lineage": True}})
        self.assertEqual(preview["status"], "gap_and_unlicensed_worlds")
        self.assertFalse(preview["automatic_commit"])
        self.assertEqual(preview["semantic_entailment"], "not_certified")
        self.assertEqual(preview["original_state"]["answers"], {"lineage": True})
        self.assertEqual(preview["decision_impact"]["status"], "unavailable")
        self.assertIn("Reset answered", preview["decision_impact"]["reason"])
        self.assertEqual(brief, before)
        self.assertEqual(analyze_v6d(brief)["stress"]["decision_states"]["LINEAGE"]["classification"], "needs_review")

    def test_refuter_addition_exact_impact_preserves_vetoes_and_current_state(self):
        brief = demo_brief()
        selected = {"lineage": "original", "decoration": "root", "route": "four"}
        ir = brief["source_ir"]
        ir["propositions"] = [p for p in ir["propositions"] if all(selected[k] == v for k, v in p["when"].items())]
        for p in ir["propositions"]: p["when"] = {}
        ir["choices"] = []; brief["clarifications"] = []
        proposed = deepcopy(ir)
        row = next(p for p in proposed["propositions"] if p["kind"] == "support" and p["target"] == "L")
        row["body"] = {"expr": {"any": [{"ref": x} for x in "ABC"]}}
        before = deepcopy((brief, proposed))
        result = preview_refuter(brief, proposed)
        impact = result["decision_impact"]
        self.assertEqual(impact["decisions"]["RELEASE"]["minimum_consensus_loss"]["withdraw"], ["A", "B", "C"])
        self.assertEqual(impact["augmented_distinct_graphs"], 2)
        locked = preview_refuter(brief, proposed, {"revoked_passages": ["A"]})["decision_impact"]
        self.assertEqual(locked["locked_exclusions"], ["A"])
        self.assertEqual(locked["decisions"]["RELEASE"]["minimum_consensus_loss"]["withdraw"], ["B", "C"])
        self.assertEqual((brief, proposed), before)
        self.assertEqual(analyze_v6d(brief)["stress"]["decision_states"]["RELEASE"]["classification"], "supported")

    def test_refuter_unknown_answers_and_incomplete_or_different_inventory(self):
        brief = demo_brief()
        result = preview_refuter(brief, brief["source_ir"], {"answers": {"lineage": None}})
        self.assertEqual(result["decision_impact"]["status"], "evaluated")
        proposed = deepcopy(brief["source_ir"])
        proposed["choices"] = [q for q in proposed["choices"] if q["id"] != "decoration"]
        proposed["propositions"] = [p for p in proposed["propositions"] if p["target"] != "Y"]
        entity = next(e for e in proposed["entities"] if e["id"] == "Y")
        entity["operational"] = False
        different = preview_refuter(brief, proposed)
        self.assertEqual(different["decision_impact"]["status"], "unavailable")
        self.assertIn("identical typed", different["decision_impact"]["reason"])
        proposed["entities"].remove(entity)
        gap = preview_refuter(brief, proposed)
        self.assertEqual(gap["proposal_missing_disposition_ids"], ["Y"])
        self.assertIsNone(gap["against_current_declaration"])
        self.assertEqual(gap["decision_impact"]["status"], "unavailable")

    def test_unknown_ancestry_withholds_all_decisions_instead_of_partial_family(self):
        brief = demo_brief()
        ir = brief["source_ir"]
        ir["choices"] = [q for q in ir["choices"] if q["id"] != "lineage"]
        ir["propositions"] = [p for p in ir["propositions"] if not (p["kind"] == "origin" and p["target"] == "X")]
        cite = next(e for e in ir["entities"] if e["id"] == "X")["citations"]
        ir["propositions"].append({"id": "unknownX", "kind": "unknown_ancestry", "target": "X", "body": {"description": "Unidentified origin asserted by supplied interpretation"},
                                   "scope": "current", "polarity": "assert", "when": {}, "citations": cite, "bindings": []})
        brief["clarifications"] = [q for q in brief["clarifications"] if q["choice_id"] != "lineage"]
        result = analyze_v6d(brief)
        self.assertEqual(result["status"], "unresolved_structure")
        self.assertIsNone(result["stress"])
        self.assertEqual(result["compilation"]["candidates"], [])
        with self.assertRaises(ValueError): analyze_v6d(brief, {"unexpected": []})

    def test_all32_branches_and_decision_irrelevant_choices_are_retained(self):
        result = analyze_v6d(five_choices())
        self.assertEqual(result["compilation"]["candidate_count"], 32)
        self.assertEqual(len(result["stress"]["candidate_ids"]), 32)
        self.assertEqual(result["stress"]["next_question"]["id"], "lineage")
        self.assertEqual(result["exposure"]["candidate_count"], 32)

    def test_exposure_preview_never_clears_locks_or_mutates_actual_status(self):
        brief = demo_brief(); state = {"answers": {"lineage": False}, "revoked_passages": ["A"]}; before = deepcopy((brief, state))
        preview = preview_exposure(brief, state, ["P"], [])
        self.assertTrue(all(outcomes["LINEAGE"] for outcomes in preview["outcomes"].values()))
        actual = analyze_v6d(brief, state)
        self.assertEqual(actual["stress"]["decision_states"]["LINEAGE"]["classification"], "unsupported")
        self.assertEqual((brief, state), before)
        with self.assertRaises(ValueError): preview_exposure(brief, state, [], ["A"])
        with self.assertRaises(ValueError): preview_exposure(brief, state, ["A"], [])

    def test_exposure_counts_match_scalar_enumeration_with_locked_parent(self):
        result = analyze_v6d(demo_brief(), {"revoked_passages": ["A"]})
        audit = result["exposure"]; variables = audit["changeable_evidence_ids"]
        counts = {did: 0 for did in audit["decisions"]}; minima = {did: None for did in counts}
        for bits in itertools.product((False, True), repeat=len(variables)):
            changed = {eid for eid, bit in zip(variables, bits) if bit}; outcomes = {did: set() for did in counts}
            for candidate in result["compilation"]["candidates"]:
                graph = deepcopy(candidate["graph"])
                for row in graph["evidence"]:
                    if row["id"] in changed: row["active"] = not row["active"]
                    if row["id"] == "A": row["active"] = False
                snapshot = analyze(graph)
                for did in outcomes: outcomes[did].add(snapshot["decisions"][did]["usable"])
            for did, values in outcomes.items():
                if len(values) == 2:
                    counts[did] += 1
                    minima[did] = len(changed) if minima[did] is None else min(minima[did], len(changed))
        for did, row in audit["decisions"].items():
            self.assertEqual(row["disagreement_state_count"], counts[did])
            self.assertEqual(row["minimum_changes"]["total_changes"] if row["minimum_changes"] else None, minima[did])

    def test_invalid_doc_mapping_metadata_and_question_override_are_rejected(self):
        brief = demo_brief(); brief["documents"][0]["id"] = "not-a-source"
        with self.assertRaises(ValueError): analyze_v6d(brief)
        brief = demo_brief(); brief["fresh_confirmation"] = True
        with self.assertRaises(ValueError): analyze_v6d(brief)
        brief = demo_brief(); brief["clarifications"][0]["answers"] = {}
        with self.assertRaises(ValueError): analyze_v6d(brief)

    def test_known_unused_id_requires_explicit_disposition_without_semantic_claim(self):
        brief = demo_brief()
        brief["source_documents"].append({"id": "archived-note", "text": "OLDX names an archived evidence record only; it is not part of current operations."})
        brief["registry"]["evidence"].append("OLDX")
        result = analyze_v6d(brief)
        self.assertEqual(result["registry_coverage"]["warning_label"], "Reference-Free Coverage Gap")
        self.assertEqual(result["registry_coverage"]["missing_disposition_ids"], ["OLDX"])
        self.assertFalse(result["ready_for_conditional_decision_review"])
        self.assertIsNone(result["stress"])
        sid = source_segments(brief["source_documents"])[-1]["span_id"]
        brief["source_ir"]["entities"].append({"id": "OLDX", "type": "evidence", "operational": False, "citations": [sid]})
        declared = analyze_v6d(brief)
        self.assertTrue(declared["ready_for_conditional_decision_review"])
        self.assertEqual(declared["registry_coverage"]["missing_disposition_ids"], [])
        self.assertEqual(declared["source_completeness"], "unknown")
        self.assertEqual(declared["semantic_entailment"], "not_certified")


class WorkbenchHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), HandlerV6d)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def request(self, route, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        raw = json.dumps(body) if isinstance(body, dict) else body
        connection.request("GET" if body is None else "POST", route, body=raw, headers=headers or {})
        response = connection.getresponse(); status, value, mime = response.status, response.read(), response.getheader("Content-Type")
        connection.close(); return status, value, mime

    def test_standalone_assets_demo_and_analyze(self):
        status, html, _ = self.request("/"); self.assertEqual(status, 200); self.assertIn(b"Proposed interpretation", html)
        status, body, _ = self.request("/api/v6d/demo"); self.assertEqual(status, 200)
        brief = json.loads(body)
        status, body, _ = self.request("/api/v6d/analyze", {"brief": brief})
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)["compilation"]["candidate_count"], 8)
        self.assertEqual(self.request("/api/v5/evaluation")[0], 404)

    def test_cross_origin_and_duplicate_fields_fail_closed(self):
        self.assertEqual(self.request("/api/v6d/analyze", {"brief": demo_brief()}, {"Origin": "https://other.example"})[0], 403)
        self.assertEqual(self.request("/api/v6d/analyze", '{"brief":{},"brief":{}}')[0], 400)


if __name__ == "__main__": unittest.main()
