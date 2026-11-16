"""Constructed fixtures only; no live primary responses are read."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts.audit_natural_ensembles_v6 import audit_ensembles, challenge, signature
from retrace.refuter_impact_v6 import compare_readings


def candidate(routes, name="g", parents=None):
    parents = parents or {}
    return {"id": name, "graph": {
        "evidence": [{"id": eid, "active": eid != "P", "kind": "copy" if parents.get(eid) else "root", "parents": parents.get(eid, [])} for eid in "ABCDP"],
        "claims": [{"id": "C0", "supports": routes}], "decisions": [{"id": "D0", "requires": ["C0"]}]}}


def fixture(gold, draws, ir):
    case = {"id": "constructed-case", "family": "fixture-family",
            "public": {"registry": {"evidence": list("ABCDP"), "claims": ["C0"], "decisions": ["D0"]}},
            "events": {"document_groups": [{"id": "docA", "evidence_ids": ["A"]}], "states": {
                "initial": {"revoked_documents": [], "revoked_passages": []},
                "withdrawn": {"revoked_documents": ["docA"], "revoked_passages": []},
                "restored": {"revoked_documents": [], "revoked_passages": ["B"]}}},
            "evaluation": {"source_family": gold}, "authored_seed_pool": "NEVER_READ_THIS_POISON"}
    slots, audits = [], []
    for number in range(11):
        condition = "sample_graph" if number < 10 else "source_ir"
        phase = f"draw_{number+1:02d}" if number < 10 else "extract"
        slot = {"slot_id": f"slot{number}", "model": "fixture-model", "case_id": case["id"], "condition": condition, "phase": phase}
        slots.append(slot)
        values = [draws[number]] if number < 10 and number < len(draws) and draws[number] is not None else ir if number == 10 else []
        audits.append({**slot, "schema_valid": bool(values), "executable": bool(values), "record_observed": bool(values),
                       "status": "valid" if values else "missing_or_invalid", "candidates": deepcopy(values)})
    audits.append({"schema": "retrace.frontier-v6d-k10-union.v1", "condition": "k10_union", "model": "fixture-model", "case_id": case["id"],
                   "scheduled_draws": 10, "valid_draws": sum(x is not None for x in draws)})
    return {"cases": [case]}, slots, audits


def run(args): return audit_ensembles(*args, require_primary=False)


class NaturalEnsembleTests(unittest.TestCase):
    def test_actual_shared_lineage_omission_and_state_specific_source_aligned_alarm(self):
        wrong = candidate([["B"], ["C"]])
        correct = candidate([["B"], ["C"]], parents={"B": ["A"], "C": ["A"]})
        args = fixture([correct], [wrong] * 10, [correct]); pristine = deepcopy(args)
        report = run(args); row = report["rows"][0]
        self.assertEqual(row["valid_k10_draws"], 10)
        self.assertEqual(row["k10_family"]["duplicate_graphs"], 9)
        self.assertGreater(row["k10_shared_feature_omissions"]["count"], 0)
        warning = row["states"]["initial"]["ir_addition_challenge"]["warnings"][0]
        self.assertEqual(warning["witness"]["withdraw"], ["A"])
        self.assertEqual(warning["evaluation_only"]["grade"], "source_aligned_challenge")
        self.assertFalse(warning["evaluation_only"]["augmented_consensus_matches_authored"])
        self.assertEqual(row["states"]["withdrawn"]["k10"]["false_unanimity_decisions"], ["D0"])
        self.assertEqual(row["states"]["withdrawn"]["ir_addition_challenge"]["warnings"][0]["witness"]["k"], 0)
        self.assertEqual(args, pristine)
        self.assertEqual(report["current_state_alias"], "initial")
        self.assertEqual(set(row["states"]), {"initial", "withdrawn", "restored"})

    def test_missing_ambiguity_can_be_exposed_without_claiming_truth(self):
        both = candidate([["A", "B"]]); either = candidate([["A"], ["B"]])
        report = run(fixture([both, either], [both] * 10, [either]))
        warning = report["rows"][0]["states"]["initial"]["ir_addition_challenge"]["warnings"][0]
        self.assertEqual(warning["witness"]["withdraw"], ["A"])
        self.assertEqual(warning["evaluation_only"]["authored_consensus_at_witness"], "disputed")
        self.assertTrue(warning["evaluation_only"]["augmented_consensus_matches_authored"])

    def test_spurious_proposal_against_faithful_union_is_false_alarm(self):
        faithful = candidate([["A"], ["B"]]); wrong = candidate([["A", "B"]])
        report = run(fixture([faithful], [faithful] * 10, [wrong]))
        warning = report["rows"][0]["states"]["initial"]["ir_addition_challenge"]["warnings"][0]
        self.assertEqual(warning["evaluation_only"]["grade"], "false_alarm_at_witness")
        self.assertEqual(report["summary"]["false_alarm_at_witness_in_any_state"]["numerator"], 1)

    def test_correct_novel_graph_does_not_hide_wrong_extra_proposal(self):
        old = candidate([["A"], ["B"]]); correct = candidate([["A"], ["C"]], "correct")
        wrong = candidate([["A"], ["D"]], "wrong")
        result = challenge([old], [correct, wrong], [old, correct], ["D0"], [])
        warning = result["warnings"][0]
        self.assertEqual(warning["witness"]["withdraw"], ["A", "B"])
        self.assertEqual(warning["evaluation_only"]["grade"], "unlicensed_or_mixed_proposal_challenge")
        self.assertFalse(warning["evaluation_only"]["all_novel_proposed_graphs_in_authored_family"])

    def test_partial_and_empty_draws_keep_full_scheduled_denominators(self):
        graph = candidate([["A"]])
        report = run(fixture([graph], [graph] + [None] * 9, []))
        self.assertEqual(report["summary"]["planned_pairs"], 1)
        self.assertEqual(report["summary"]["availability_strata"], {"partial1to9/ir_unavailable": 1})
        self.assertEqual(report["summary"]["ir_exact_family"]["denominator"], 1)
        self.assertIsNone(report["summary"]["states"]["initial"]["source_aligned_warning_selective_precision"]["rate"])
        empty = run(fixture([graph], [None] * 10, []))
        row = empty["rows"][0]
        self.assertEqual(row["states"]["initial"]["k10"]["unavailable_decisions"], ["D0"])
        self.assertEqual(row["states"]["initial"]["k10"]["false_unanimity_decisions"], [])
        self.assertFalse(row["k10_shared_feature_omissions"]["available"])
        self.assertFalse(row["k10_family"]["exact"])

    def test_gold_and_authored_seeds_never_enter_reference_free_comparison(self):
        old = candidate([["A"]], "old"); proposed = candidate([["B"]], "proposed"); unseen_gold = candidate([["C"]], "gold")
        calls = []
        def checked(current, extra, **kwargs):
            calls.append((deepcopy(current), deepcopy(extra)))
            return compare_readings(current, extra, **kwargs)
        args = fixture([unseen_gold], [old] * 10, [proposed])
        with patch('scripts.audit_natural_ensembles_v6.compare_readings', checked): first = run(args)
        self.assertEqual(len(calls), 3)
        for current, extra in calls:
            self.assertEqual({signature(x["graph"]) for x in current}, {signature(old["graph"])})
            self.assertEqual({signature(x["graph"]) for x in extra}, {signature(proposed["graph"])})
        args[0]["cases"][0]["authored_seed_pool"] = {"candidates": [unseen_gold]}
        self.assertEqual(run(args), first)

    def test_original_inactivity_and_document_veto_are_never_cleared(self):
        old = candidate([["P"]]); new = candidate([["A"]])
        result = challenge([old], [new], [new], ["D0"], ["A"])
        self.assertEqual(result["warnings"], [])
        self.assertNotIn("A", result["reference_free_detection"]["withdrawal_variables"])

    def test_registry_mismatch_is_unavailable_and_not_a_silent_partial_comparison(self):
        old = candidate([["A"]]); proposed = candidate([["B"]])
        proposed["graph"]["evidence"] = [row for row in proposed["graph"]["evidence"] if row["id"] != "P"]
        result = challenge([old], [proposed], [old], ["D0"], [])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["warnings"], [])

    def test_audit_duplicates_unknowns_union_mismatch_and_bad_admission_reject(self):
        graph = candidate([["A"]])
        for mode in ("duplicate", "unknown", "union", "candidate"):
            args = fixture([graph], [graph] * 10, [graph])
            if mode == "duplicate": args[2].append(deepcopy(args[2][0]))
            elif mode == "unknown": args[2][0]["slot_id"] = "not-scheduled"
            elif mode == "union": args[2][-1]["valid_draws"] = 9
            else: args[2][0]["schema_valid"] = False
            with self.assertRaises(ValueError): run(args)
        with self.assertRaises(ValueError): audit_ensembles(*fixture([graph], [graph] * 10, [graph]))


if __name__ == "__main__": unittest.main()
