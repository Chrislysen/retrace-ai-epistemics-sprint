"""Constructed offline tests; no model requests or benchmark outcome reads."""
from copy import deepcopy
from functools import lru_cache
import http.client
from http.server import ThreadingHTTPServer
import json
import random
import threading
import unittest
from unittest.mock import patch

from retrace.workbench_v6h import analyze_workbench, demo_brief, preview_refuter, minimax_clarification
from retrace.source_ir_v6d import source_segments
from retrace.server_v6h import HandlerV6h


def proposal(brief, ir=None):
    return {"status": "objection", "ir": deepcopy(ir if ir is not None else brief["source_ir"]),
            "objection_spans": [source_segments(brief["source_documents"])[2]["span_id"]], "warning_score": .6}


class WorkbenchV6hTests(unittest.TestCase):
    def test_demo_preserves_four_states_and_exact_three_way_withdrawal(self):
        result = analyze_workbench(demo_brief())
        self.assertEqual(result["provenance"], "constructed_offline_demo")
        self.assertEqual(len(result["candidate_ids"]), 8)
        self.assertEqual(result["planner"]["next_question"]["id"], "polarity")
        self.assertEqual(result["planner"]["worst_case_cost"], 1)
        self.assertEqual(result["decisions"]["SAFE_D"]["state"], "supported")
        self.assertEqual(result["decisions"]["UNKNOWN_D"]["state"], "insufficient_provenance")
        self.assertEqual(result["decisions"]["DORMANT_D"]["state"], "not_supported")
        self.assertTrue(result["decisions"]["DEBATE_D"]["interpretations_disagree_on_status"])
        witness = next(row for row in result["robustness"]["decisions"] if row["decision"] == "RELEASE_D")
        self.assertEqual(witness["withdraw"], ["A", "B", "C"])
        self.assertTrue(witness["survives_all_k1"]); self.assertTrue(witness["survives_all_k2"])

    def test_unknown_retains_candidates_and_answer_stops_before_irrelevant_choices(self):
        brief = demo_brief(); first = analyze_workbench(brief); digest = first["declaration_fingerprint"]
        unknown = analyze_workbench(brief, {"answers": {"polarity": None}}, digest)
        answered = analyze_workbench(brief, {"answers": {"polarity": True}}, digest)
        self.assertEqual(len(unknown["candidate_ids"]), 8)
        self.assertEqual(len(answered["candidate_ids"]), 4)
        self.assertIsNone(answered["planner"]["next_question"])
        self.assertEqual(answered["decisions"]["DEBATE_D"]["state"], "contested")
        self.assertEqual(answered["decisions"]["UNKNOWN_D"]["state"], "insufficient_provenance")

    def test_document_passage_and_scenario_locks_are_separate(self):
        brief = demo_brief(); first = analyze_workbench(brief); digest = first["declaration_fingerprint"]
        state = {"revoked_documents": ["demo-source-1"], "revoked_passages": ["A"], "scenario_withdrawals": ["B"]}
        blocked = analyze_workbench(brief, state, digest)
        self.assertTrue(blocked["record_flags"]["A"]["document_veto"])
        state["revoked_documents"] = []
        restored = analyze_workbench(brief, state, digest)
        self.assertFalse(restored["record_flags"]["A"]["document_veto"])
        self.assertTrue(restored["record_flags"]["A"]["passage_veto"])
        self.assertTrue(restored["record_flags"]["B"]["scenario_veto"])
        self.assertTrue(all(not row["effective_active"] for row in restored["record_flags"]["Z"]["by_candidate"].values()))
        self.assertNotIn("A", restored["allowed_withdrawals"])

    def test_state_requires_fingerprint_and_changed_source_invalidates_it(self):
        brief = demo_brief(); first = analyze_workbench(brief)
        with self.assertRaisesRegex(ValueError, "fingerprint"): analyze_workbench(brief, {"answers": {"polarity": True}})
        brief["title"] = "Changed declaration"
        with self.assertRaisesRegex(ValueError, "changed"): analyze_workbench(brief, first["state"], first["declaration_fingerprint"])
        self.assertEqual(analyze_workbench(brief)["provenance"], "supplied_unverified_interpretation")

    def test_latent_choice_becomes_relevant_after_three_way_scenario(self):
        brief = demo_brief(); first = analyze_workbench(brief)
        result = analyze_workbench(brief, {"answers": {"polarity": False}, "scenario_withdrawals": ["A", "B", "C"]}, first["declaration_fingerprint"])
        self.assertEqual(result["planner"]["next_question"]["id"], "route")
        self.assertTrue(result["decisions"]["RELEASE_D"]["interpretations_disagree_on_status"])

    def test_hamming2_is_a_preview_and_preserves_original_inactive_flag(self):
        brief = demo_brief(); before = deepcopy(brief); result = analyze_workbench(brief)
        witness = next(w for w in result["hamming2"]["witnesses"] if w["decision"] == "DORMANT_D")
        self.assertEqual((witness["enable"], witness["withdraw"]), ("Z", "A"))
        self.assertTrue(witness["hypothetical_activation"])
        self.assertEqual(brief, before)
        self.assertEqual(result["decisions"]["DORMANT_D"]["state"], "not_supported")

    def test_registry_gap_withholds_decisions_but_explicit_nonoperational_clears_inventory(self):
        brief = demo_brief()
        brief["source_documents"].append({"id": "old-source", "text": "OLD is an archived evidence identifier only, outside the current operational rules."})
        brief["registry"]["evidence"].append("OLD")
        gap = analyze_workbench(brief)
        self.assertEqual(gap["status"], "inventory_gap"); self.assertEqual(gap["decisions"], {})
        span = source_segments(brief["source_documents"])[-1]["span_id"]
        brief["source_ir"]["entities"].append({"id": "OLD", "type": "evidence", "operational": False, "citations": [span]})
        result = analyze_workbench(brief)
        self.assertTrue(result["ready"]); self.assertFalse(result["source_entailment_verified"])
        self.assertEqual(result['typed_veto_release']['status'],'evaluated')

    def test_typed_veto_release_is_hypothetical_and_keeps_passage_lock(self):
        brief=demo_brief();first=analyze_workbench(brief)
        state={'revoked_documents':['demo-source-1'],'revoked_passages':['A']}
        before=deepcopy(state)
        result=analyze_workbench(brief,state,first['declaration_fingerprint'])
        self.assertEqual(result['typed_veto_release']['status'],'evaluated')
        self.assertTrue(result['typed_veto_release']['witnesses'])
        self.assertEqual(state,before)
        self.assertTrue(result['record_flags']['A']['passage_veto'])
        self.assertTrue(result['record_flags']['A']['document_veto'])
        self.assertTrue(all(not r['effective_active'] for r in result['record_flags']['Z']['by_candidate'].values()))

    def test_invalid_refuter_span_is_rejected_before_any_current_analysis(self):
        brief = demo_brief(); proposed = proposal(brief); proposed["objection_spans"] = ["fabricated-span"]
        with patch('retrace.workbench_v6h.analyze_workbench', side_effect=AssertionError("No comparison before citation gate")):
            with self.assertRaisesRegex(ValueError, "exact existing"): preview_refuter(brief, proposed)
        proposed = proposal(brief); proposed["ir"]["propositions"][0]["citations"] = ["fabricated-span"]
        with patch('retrace.workbench_v6h.analyze_workbench', side_effect=AssertionError("No comparison before branch admission")):
            with self.assertRaises(ValueError): preview_refuter(brief, proposed)

    def test_refuter_abstention_and_answered_choices_never_mutate_current(self):
        brief = demo_brief(); first = analyze_workbench(brief); state = {"answers": {"polarity": False}}; before = deepcopy((brief, state))
        result = preview_refuter(brief, proposal(brief), state, first["declaration_fingerprint"])
        self.assertEqual(result["status"], "unavailable"); self.assertIn("Reset", result["reason"])
        abstained = preview_refuter(brief, {"status": "no_counter_reading", "ir": None, "objection_spans": [], "warning_score": .3})
        self.assertEqual(abstained["status"], "abstained"); self.assertFalse(abstained["proposal_applied"])
        self.assertEqual((brief, state), before)

    def test_record_usability_bounds_keep_unknown_origin_separate_from_eligibility(self):
        result = analyze_workbench(demo_brief())
        for row in result["record_flags"]["X"]["by_candidate"].values():
            self.assertTrue(row["original_active"]); self.assertTrue(row["effective_active"])
            self.assertFalse(row["usable_in_all_ancestry_completions"]); self.assertTrue(row["usable_in_some_ancestry_completions"])

    def test_empty_malformed_state_rejected_even_when_inventory_is_incomplete(self):
        brief = demo_brief(); brief["registry"]["evidence"].append("OMITTED")
        for state in ({"unknown_field": []}, {"answers": False}, {"revoked_passages": {}}, []):
            with self.subTest(state=state), self.assertRaises(ValueError): analyze_workbench(brief, state)

    def test_contradictory_answers_to_coupled_choices_cannot_select_empty_family(self):
        brief = demo_brief(); brief["source_ir"]["combination"]["mode"] = "listed"
        brief["source_ir"]["combination"]["assignments"] = [
            {"route": "three", "polarity": "no_objection", "decoration": "root"},
            {"route": "four", "polarity": "objection", "decoration": "copied"}]
        first = analyze_workbench(brief)
        with self.assertRaisesRegex(ValueError, "contradict"):
            analyze_workbench(brief, {"answers": {"route": True, "polarity": False}}, first["declaration_fingerprint"])

    def test_source_located_proposal_addition_exposes_k3_without_applying(self):
        brief = demo_brief(); proposed = proposal(brief)
        # A structurally admitted but incomplete supplied family: only four-route reading.
        ir = brief["source_ir"]; ir["choices"] = [q for q in ir["choices"] if q["id"] != "route"]
        ir["propositions"] = [p for p in ir["propositions"] if p["when"].get("route") != "three"]
        for p in ir["propositions"]: p["when"].pop("route", None)
        brief["clarifications"] = [q for q in brief["clarifications"] if q["choice_id"] != "route"]
        brief["target_decisions"] = ["RELEASE_D"]; brief["allowed_withdrawals"] = ["A", "B", "C", "D"]
        before = deepcopy((brief, proposed)); first = analyze_workbench(brief)
        result = preview_refuter(brief, proposed, first["state"], first["declaration_fingerprint"])
        witness = result["decision_impact"]["decisions"][0]
        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(witness["withdraw"], ["A", "B", "C"])
        self.assertTrue(witness["current"]["box_supported"])
        self.assertFalse(witness["augmented"]["box_supported"])
        self.assertFalse(result["proposal_applied"]); self.assertFalse(result["source_entailment_verified"])
        self.assertEqual(result["original_state"], first["state"])
        self.assertEqual((brief, proposed), before)


class MinimaxTests(unittest.TestCase):
    def test_unresolved_status_agreement_is_not_support(self):
        result = minimax_clarification({"a": {"D": "insufficient_provenance"}, "b": {"D": "insufficient_provenance"}}, [])
        self.assertEqual(result["worst_case_cost"], 0)
        self.assertTrue(result["status_vectors_agree"])

    def test_200_small_problems_match_independent_remaining_question_recurrence(self):
        rng = random.Random(876901)
        for _ in range(200):
            ids = [str(i) for i in range(rng.randint(1, 6))]
            vectors = {cid: {"D": rng.choice(["supported", "not_supported", "contested", "insufficient_provenance"])} for cid in ids}
            questions = [{"id": f"q{j}", "label": f"Question {j}", "cost": rng.randint(1, 4), "answers": {cid: bool(rng.getrandbits(1)) for cid in ids}} for j in range(rng.randint(0, 4))]
            @lru_cache(maxsize=None)
            def oracle(members, remaining):
                if len({vectors[cid]["D"] for cid in members}) == 1: return 0
                costs = []
                for qi in remaining:
                    yes = tuple(cid for cid in members if questions[qi]["answers"][cid]); no = tuple(cid for cid in members if cid not in yes)
                    if not yes or not no: continue
                    rest = tuple(q for q in remaining if q != qi)
                    left, right = oracle(yes, rest), oracle(no, rest)
                    if left is not None and right is not None: costs.append(questions[qi]["cost"] + max(left, right))
                return min(costs) if costs else None
            self.assertEqual(minimax_clarification(vectors, questions)["worst_case_cost"], oracle(tuple(ids), tuple(range(len(questions)))))


class WorkbenchHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), HandlerV6h)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
    def request(self, route, value=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request("GET" if value is None else "POST", route, body=json.dumps(value) if isinstance(value, dict) else value, headers=headers or {})
        response = connection.getresponse(); status, body = response.status, response.read(); connection.close()
        return status, json.loads(body)
    def test_demo_analyze_and_invalid_proposal_return_no_warning_payload(self):
        status, brief = self.request("/api/v6h/demo"); self.assertEqual(status, 200)
        status, result = self.request("/api/v6h/analyze", {"brief": brief}); self.assertEqual(status, 200)
        proposed = proposal(brief); proposed["objection_spans"] = ["absent"]
        status, result = self.request("/api/v6h/refuter-preview", {"brief": brief, "proposal": proposed})
        self.assertEqual(status, 400); self.assertEqual(set(result), {"error", "code"})
    def test_cross_origin_duplicate_json_and_old_api_rejected(self):
        self.assertEqual(self.request("/api/v6h/analyze", {"brief": demo_brief()}, {"Origin": "https://elsewhere.invalid"})[0], 403)
        self.assertEqual(self.request("/api/v6h/analyze", '{"brief":{},"brief":{}}')[0], 400)
        self.assertEqual(self.request("/api/v6d/demo")[0], 404)

    def test_http_fingerprint_lock_restore_and_clarification_flow(self):
        brief = demo_brief(); brief["allowed_withdrawals"] = ["A", "B", "C", "D"]
        status, first = self.request("/api/v6h/analyze", {"brief": brief}); self.assertEqual(status, 200)
        state = {"answers": {"polarity": True}, "revoked_documents": ["demo-source-1"], "revoked_passages": ["A"], "scenario_withdrawals": ["B"]}
        status, blocked = self.request("/api/v6h/analyze", {"brief": brief, "state": state, "expected_fingerprint": first["declaration_fingerprint"]})
        self.assertEqual(status, 200); self.assertEqual(len(blocked["candidate_ids"]), 4)
        state["revoked_documents"] = []
        status, restored = self.request("/api/v6h/analyze", {"brief": brief, "state": state, "expected_fingerprint": first["declaration_fingerprint"]})
        self.assertEqual(status, 200); self.assertTrue(restored["record_flags"]["A"]["passage_veto"])
        self.assertTrue(restored["record_flags"]["B"]["scenario_veto"])
        self.assertTrue(all(not r["effective_active"] for r in restored["record_flags"]["Z"]["by_candidate"].values()))
        brief["source_documents"][0]["text"] += " Changed source."
        status, rejected = self.request("/api/v6h/analyze", {"brief": brief, "state": state, "expected_fingerprint": first["declaration_fingerprint"]})
        self.assertEqual(status, 400); self.assertEqual(set(rejected), {"error", "code"})

    def test_http_assets_and_unicode_source_spans(self):
        for route, mime in (("/lab", "text/html"), ("/app.js", "text/javascript"), ("/style.css", "text/css")):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
            connection.request("GET", route); response = connection.getresponse()
            self.assertEqual(response.status, 200); self.assertIn(mime, response.getheader("Content-Type")); self.assertTrue(response.read()); connection.close()
        docs = [{"id": "unicode", "text": "\U0001f4da Evidence A is an original.\n\nClaim C uses A."}]
        status, prepared = self.request("/api/v6h/source", {"brief": {"source_documents": docs, "registry": {"evidence": ["A"], "claims": ["C"], "decisions": []}}})
        self.assertEqual(status, 200)
        self.assertIn("retrace.source-ir.v6h", prepared["instructions"])
        spans = source_segments(docs)
        for span in spans: self.assertEqual(docs[0]["text"][span["start"]:span["end"]], span["text"])
        self.assertEqual(spans[1]["start"], len("\U0001f4da Evidence A is an original.\n\n"))

    def test_http_nonfinite_and_unknown_state_return_only_input_error(self):
        status, result = self.request("/api/v6h/analyze", '{"brief":NaN}')
        self.assertEqual(status, 400); self.assertEqual(set(result), {"error", "code"})
        status, result = self.request("/api/v6h/analyze", {"brief": demo_brief(), "state": {"invented": []}})
        self.assertEqual(status, 400); self.assertEqual(set(result), {"error", "code"})


if __name__ == "__main__": unittest.main()
