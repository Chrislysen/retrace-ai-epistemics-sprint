import copy
import itertools
import json
import unittest
from pathlib import Path

from retrace.stress import analyze_stress


def demo():
    path = Path(__file__).resolve().parents[1] / "data" / "stress-demo.json"
    return json.loads(path.read_text(encoding="utf-8"))


def small(active=True, allowed=None):
    return {"id": "small", "candidates": [{"id": "only", "graph": {
        "evidence": [{"id": "e", "kind": "root", "active": active, "parents": []}],
        "claims": [{"id": "c", "supports": [["e"]]}],
        "decisions": [{"id": "d", "requires": ["c"]}]}}], "questions": [],
        **({"allowed_withdrawals": allowed} if allowed is not None else {})}


class StressTests(unittest.TestCase):
    def test_constructed_demo_separates_three_kinds_of_witness(self):
        brief = demo()
        result = analyze_stress(brief)
        row = result["decision_witnesses"]["display"]
        self.assertEqual(row["minimum_break_any"]["withdraw"], ["A", "B", "C"])
        self.assertEqual(row["minimum_distinguishing"]["k"], 3)
        self.assertEqual(row["minimum_break_all"]["withdraw"], ["A", "B", "C", "D"])
        self.assertEqual(row["minimum_distinguishing"]["outcomes"], {
            "candidate-a": False, "candidate-b": False, "candidate-c": True, "candidate-d": True})
        for count in (1, 2):
            for withdrawn in itertools.combinations(brief["allowed_withdrawals"], count):
                current = analyze_stress(brief, {"scenario_withdrawals": list(withdrawn)})
                self.assertEqual(current["decision_states"]["display"]["state"], "robust_supported")
        disputed = result["decision_witnesses"]["circulate"]
        self.assertEqual(disputed["minimum_distinguishing"]["k"], 0)
        self.assertFalse(disputed["break_applicable"])
        self.assertIsNone(disputed["minimum_break_any"])

    def test_one_candidate_and_zero_variables_have_explicit_null_results(self):
        result = analyze_stress(small())
        self.assertEqual(result["decision_witnesses"]["d"]["minimum_break_all"]["withdraw"], ["e"])
        self.assertIsNone(result["decision_witnesses"]["d"]["minimum_distinguishing"])
        self.assertTrue(result["interventions"]["all_decisions_equivalent_within_scope"])
        result = analyze_stress(small(allowed=[]))
        self.assertEqual(result["coverage"]["states_checked_per_candidate"], 1)
        self.assertTrue(result["decision_witnesses"]["d"]["break_applicable"])
        self.assertIsNone(result["decision_witnesses"]["d"]["minimum_break_any"])
        self.assertEqual(result["coverage"]["fixed_evidence_ids"], ["e"])

    def test_baseline_unsupported_is_not_a_zero_cost_break_or_revocation(self):
        result = analyze_stress(small(False), {"revoked_passages": ["e"]})
        self.assertEqual(result["decision_states"]["d"]["classification"], "unsupported")
        self.assertFalse(result["decision_witnesses"]["d"]["break_applicable"])
        self.assertIsNone(result["decision_witnesses"]["d"]["minimum_break_all"])
        self.assertEqual(result["decision_states"]["d"]["revoked_candidate_ids"], [])
        self.assertFalse(analyze_stress(small(False))["revocation_flags"]["e"]["by_candidate"]["only"]["effective_active"])

    def test_document_passage_and_scenario_vetoes_restore_independently(self):
        brief = small()
        brief["documents"] = [{"id": "doc1", "label": "First document", "evidence_ids": ["e"]},
                              {"id": "doc2", "label": "Second document", "evidence_ids": ["e"]}]
        blocked = analyze_stress(brief, {"revoked_documents": ["doc1", "doc2"],
                                        "revoked_passages": ["e"], "scenario_withdrawals": ["e"]})
        self.assertEqual(blocked["decision_states"]["d"]["classification"], "revoked")
        self.assertEqual(blocked["revocation_flags"]["e"]["revoked_documents"], ["doc1", "doc2"])
        for state in ({"revoked_documents": ["doc2"]}, {"revoked_passages": ["e"]},
                      {"scenario_withdrawals": ["e"]}):
            self.assertFalse(analyze_stress(brief, state)["revocation_flags"]["e"]["by_candidate"]["only"]["effective_active"])
        self.assertTrue(analyze_stress(brief, {})["revocation_flags"]["e"]["by_candidate"]["only"]["effective_active"])

    def test_shared_document_veto_is_not_a_single_record_intervention(self):
        result = analyze_stress(demo(), {"revoked_documents": ["inspectionPacket"]})
        self.assertEqual(result["decision_states"]["display"]["state"], "needs_review")
        self.assertEqual(result["decision_witnesses"]["display"]["minimum_distinguishing"]["k"], 0)
        self.assertTrue(all(result["revocation_flags"][eid]["document_veto"] for eid in ["A", "B", "C"]))
        self.assertFalse(result["revocation_flags"]["D"]["document_veto"])

    def test_copy_local_activity_and_inherited_unusability_stay_distinct(self):
        result = analyze_stress(demo())
        self.assertTrue(result["revocation_flags"]["N"]["by_candidate"]["candidate-a"]["effective_active"])
        self.assertFalse(result["decision_witnesses"]["circulate"]["current_outcomes"]["candidate-a"])
        self.assertTrue(result["decision_witnesses"]["circulate"]["current_outcomes"]["candidate-c"])

    def test_apply_witness_uses_cumulative_scenario_without_mutating_inputs(self):
        brief = demo()
        state = {"scenario_withdrawals": ["A"], "revoked_passages": ["V"]}
        previous = copy.deepcopy((brief, state))
        result = analyze_stress(brief, state)
        witness = result["decision_witnesses"]["display"]["minimum_distinguishing"]
        self.assertEqual(witness["withdraw"], ["B", "C"])
        self.assertEqual(witness["scenario_withdrawals"], ["A", "B", "C"])
        after = analyze_stress(brief, {**state, "scenario_withdrawals": witness["scenario_withdrawals"]})
        self.assertEqual(after["decision_witnesses"]["display"]["current_outcomes"], witness["outcomes"])
        self.assertEqual((brief, state), previous)

    def test_planner_uses_effective_graphs_and_stops_before_full_identification(self):
        brief = demo()
        brief["target_decisions"] = ["display"]
        self.assertIsNone(analyze_stress(brief)["next_question"])
        state = {"scenario_withdrawals": ["A", "B", "C"]}
        result = analyze_stress(brief, state)
        self.assertEqual(result["next_question"]["id"], "packetRevision")
        self.assertEqual(result["next_question"]["worst_case_cost"], 1)
        result = analyze_stress(brief, {**state, "answers": {"packetRevision": True}})
        self.assertEqual(result["candidate_ids"], ["candidate-a", "candidate-b"])
        self.assertIsNone(result["next_question"])
        self.assertEqual(result["decision_states"]["display"]["classification"], "revoked")

    def test_unknown_answers_retain_and_contradictory_answers_reject(self):
        brief = demo()
        self.assertEqual(len(analyze_stress(brief, {"answers": {"packetRevision": None}})["candidate_ids"]), 4)
        duplicate_fact = copy.deepcopy(brief["questions"][0])
        duplicate_fact["id"] = "sameFact"
        brief["questions"].append(duplicate_fact)
        with self.assertRaisesRegex(ValueError, "contradict all"):
            analyze_stress(brief, {"answers": {"packetRevision": True, "sameFact": False}})

    def test_validate_entire_universe_before_answer_filtering(self):
        brief = demo()
        brief["candidates"][2]["graph"]["evidence"][0]["parents"] = ["missing"]
        with self.assertRaises(ValueError):
            analyze_stress(brief, {"answers": {"packetRevision": True}})
        brief = demo()
        del brief["questions"][1]["answers"]["candidate-c"]
        with self.assertRaisesRegex(ValueError, "every supplied candidate"):
            analyze_stress(brief, {"answers": {"packetRevision": True}})

    def test_explicit_node_fields_prevent_default_root_or_activity(self):
        for field in ("kind", "active", "parents"):
            brief = small()
            del brief["candidates"][0]["graph"]["evidence"][0][field]
            with self.assertRaisesRegex(ValueError, "require explicit"):
                analyze_stress(brief)
        brief = small()
        brief["candidates"][0]["graph"]["evidence"][0]["parent"] = "typo"
        with self.assertRaises(ValueError):
            analyze_stress(brief)

    def test_source_constraints_flag_missing_paths_without_discarding_candidates(self):
        brief = demo()
        brief["provenance_constraints"] = [{"id": "externalLineage", "child": "N", "ancestor": "O",
                                             "source_quote": "For this test, the source explicitly says N copied O."}]
        result = analyze_stress(brief, {"answers": {"packetRevision": True}})
        check = result["provenance_checks"][0]
        self.assertEqual(check["violating_candidate_ids"], ["candidate-c", "candidate-d"])
        self.assertEqual(check["by_candidate"]["candidate-a"]["path"], ["N", "O"])
        self.assertEqual(check["by_candidate"]["candidate-c"]["reason"], "missing_ancestor_path")
        self.assertEqual(len(check["by_candidate"]), 4)
        self.assertEqual(result["coverage"]["status"], "no_supplied_constraint_conflict")
        self.assertEqual(result["coverage"]["retained_constraint_violations_count"], 0)
        result = analyze_stress(brief)
        self.assertEqual(len(result["candidate_ids"]), 4)
        self.assertEqual(result["coverage"]["status"], "source_constraint_conflict")
        self.assertEqual(result["coverage"]["retained_constraint_violations_count"], 2)
        self.assertEqual(result["coverage"]["hidden_ancestor_coverage"], "unknown")
        del brief["provenance_constraints"]
        self.assertEqual(analyze_stress(brief)["coverage"]["provenance_constraint_coverage"], "unknown_no_external_constraints")
        self.assertEqual(analyze_stress(brief)["coverage"]["status"], "unknown_no_constraints")

    def test_externally_declared_ancestor_missing_from_every_graph_is_flagged_not_invented(self):
        brief = small()
        brief["provenance_constraints"] = [{"id": "sharedOmission", "child": "e", "ancestor": "sourceOrigin",
                                             "source_quote": "The packet explicitly names sourceOrigin as the source of e."}]
        before = copy.deepcopy(brief)
        result = analyze_stress(brief)
        check = result["provenance_checks"][0]["by_candidate"]["only"]
        self.assertEqual(check, {"satisfied": False, "path": None, "reason": "missing_ancestor_node"})
        self.assertEqual(result["coverage"]["status"], "source_constraint_conflict")
        self.assertEqual(result["coverage"]["retained_constraint_violations_count"], 1)
        self.assertEqual(result["decision_states"]["d"]["state"], "robust_supported")
        self.assertNotIn("sourceOrigin", result["revocation_flags"])
        self.assertEqual(brief, before)

    def test_fingerprint_binds_prose_documents_constraints_and_normalized_state(self):
        brief = demo()
        original = analyze_stress(brief)["audit_fingerprint"]
        for mutate in (lambda item: item.update(prose=item["prose"] + " amended"),
                       lambda item: item["documents"][0].update(label="New label"),
                       lambda item: item["provenance_constraints"][0].update(source_quote="Updated quote")):
            changed = copy.deepcopy(brief)
            mutate(changed)
            self.assertNotEqual(analyze_stress(changed)["audit_fingerprint"], original)
        a = analyze_stress(brief, {"scenario_withdrawals": ["B", "A"]})
        b = analyze_stress(brief, {"scenario_withdrawals": ["A", "B"]})
        self.assertEqual(a["audit_fingerprint"], b["audit_fingerprint"])
        self.assertNotEqual(a["audit_fingerprint"], original)

    def test_maximum_exact_space_and_limit_enforcement(self):
        brief = small()
        graph = brief["candidates"][0]["graph"]
        names = [f"e{index:02}" for index in range(16)]
        graph["evidence"] = [{"id": name, "kind": "root", "active": True, "parents": []} for name in names]
        graph["claims"][0]["supports"] = [[name] for name in names]
        result = analyze_stress(brief)
        self.assertEqual(result["coverage"]["states_checked_per_candidate"], 65536)
        self.assertEqual(result["decision_witnesses"]["d"]["minimum_break_all"]["withdraw"], names)
        graph["evidence"].append({"id": "extra", "kind": "root", "active": True, "parents": []})
        with self.assertRaisesRegex(ValueError, "at most 16"):
            analyze_stress(brief)
        brief["allowed_withdrawals"] = names
        self.assertEqual(analyze_stress(brief)["coverage"]["fixed_evidence_ids"], ["extra"])

    def test_minimum_ties_use_lexicographic_ids(self):
        brief = small()
        graph = brief["candidates"][0]["graph"]
        graph["evidence"] = [{"id": name, "kind": "root", "active": True, "parents": []} for name in ["z", "b", "a"]]
        graph["claims"][0]["supports"] = [["z", "b", "a"]]
        self.assertEqual(analyze_stress(brief)["decision_witnesses"]["d"]["minimum_break_any"]["withdraw"], ["a"])

    def test_invalid_state_and_nonempty_event_are_not_silently_ignored(self):
        for state in ({"answers": {"unknown": True}}, {"revoked_passages": ["missing"]},
                      {"revoked_documents": ["missing"]}, {"scenario_withdrawals": ["e", "e"]},
                      {"scenario_withdrawal": ["e"]}):
            with self.assertRaises(ValueError):
                analyze_stress(small(), state)
        brief = small()
        brief["candidates"][0]["graph"]["revoke"] = ["e"]
        with self.assertRaisesRegex(ValueError, "encode current active flags first"):
            analyze_stress(brief)


if __name__ == "__main__":
    unittest.main()
