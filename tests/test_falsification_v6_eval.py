"""Evaluation boundaries and complete denominators for the offline v6 plan."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from retrace.falsification_v6 import verify_counter_reading
from retrace.falsification_v6_eval import (
    ARMS, CASE_IDS, CORPUS_SHA256, MODELS, PHASE, POSITIVE_IDS,
    ARM_INSTRUCTIONS, COMMON_INSTRUCTIONS, build_sessions, build_study,
    graph_key, score_responses,
)

ROOT = Path(__file__).resolve().parents[1]


class FalsificationStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / "data/conservation-v6-cases.json").read_bytes()
        cls.corpus = json.loads(cls.raw)
        cls.study = build_study(cls.corpus, hashlib.sha256(cls.raw).hexdigest())
        cls.sessions = build_sessions(cls.study)
        cls.cases = {c["case_id"]: c for c in cls.study["cases"]}

    def session(self, cid, model=MODELS[0], arm=ARMS[0]):
        return next(s for s in self.sessions if (s["case_id"], s["model"], s["condition"]) == (cid, model, arm))

    def response(self, session, proposal=None, **updates):
        row = {k: session[k] for k in ("case_id", "model", "condition")}
        row.update(phase=PHASE, response_status="completed", error=None,
                   output_text=json.dumps(proposal or {"status": "no_counter_reading"}))
        row.update(updates)
        return row

    def single(self, cid, proposal, **updates):
        summary = score_responses(self.study, [self.response(self.session(cid), proposal, **updates)])
        return next(r for r in summary["outcomes"] if r["received"]), summary

    def proposal(self, cid, target, replacement, document=1):
        case = self.cases[cid]
        source = case["public"]["source_documents"][document]
        return {"status": "counter_reading", "seed_candidate_id": case["public"]["candidates"][0]["id"],
                "changes": [{"target": target, "replacement": replacement,
                             "sources": [{"document_id": source["id"], "quote": source["text"]}]}]}

    def test_locked_source_and_deterministic_generated_artifacts(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), CORPUS_SHA256)
        self.assertEqual(json.loads((ROOT / "data/falsification-v6-study.json").read_text(encoding="utf-8")), self.study)
        self.assertEqual(json.loads((ROOT / "data/falsification-v6-sessions.json").read_text(encoding="utf-8")), self.sessions)
        with self.assertRaises(ValueError):
            build_study(self.corpus, "0" * 64)

    def test_fixed_balanced_slots_and_public_only_arm_difference(self):
        self.assertEqual(len(self.sessions), 32)
        identities = {(s["model"], s["case_id"], s["condition"]) for s in self.sessions}
        self.assertEqual(len(identities), 32)
        self.assertEqual([s["slot_index"] for s in self.sessions], list(range(1, 33)))
        self.assertEqual(Counter((s["model"], s["condition"]) for s in self.sessions),
                         Counter({(m, a): 8 for m in MODELS for a in ARMS}))
        first = self.sessions[::4]
        self.assertEqual(Counter((s["model"], s["condition"]) for s in first),
                         Counter({(m, a): 2 for m in MODELS for a in ARMS}))
        for cid in CASE_IDS:
            block = [s for s in self.sessions if s["case_id"] == cid]
            self.assertEqual(len({s["steps"][0]["input"] for s in block}), 1)
            for session in block:
                self.assertEqual(session["instructions"], COMMON_INSTRUCTIONS + "\n\n" + ARM_INSTRUCTIONS[session["condition"]])
                self.assertEqual(session["response_kind"], "graph")
                self.assertEqual(session["family"], "authored_diagnostic")
                self.assertEqual(len(session["steps"]), 1)
                self.assertEqual(session["steps"][0]["phase"], PHASE)
                payload = json.loads(session["steps"][0]["input"])
                self.assertEqual(set(payload), {"source_documents", "candidates", "registry"})

    def test_hidden_poison_does_not_change_any_request(self):
        corpus = deepcopy(self.corpus)
        for case in corpus["cases"]:
            case["evaluation"] = {"poison": "GOLD_SECRET_DO_NOT_SERIALIZE"}
            case["public"]["evaluation"] = "GOLD_SECRET_DO_NOT_SERIALIZE"
        study = build_study(corpus)
        self.assertEqual(build_sessions(study), self.sessions)
        for case in study["cases"]:
            case["evaluation"] = {"poison": "GOLD_SECRET_DO_NOT_SERIALIZE"}
            case["public"]["gold"] = "GOLD_SECRET_DO_NOT_SERIALIZE"
        self.assertEqual(build_sessions(study), self.sessions)
        self.assertNotIn("GOLD_SECRET", json.dumps(build_sessions(study)))

    def test_decimal_budget_is_projection_without_reservation(self):
        budget = self.study["budget"]
        self.assertEqual(budget["status"], "projected_only_not_reserved")
        self.assertEqual(Decimal(budget["per_request_credits"][MODELS[0]]), Decimal(".02443264"))
        self.assertEqual(Decimal(budget["per_request_credits"][MODELS[1]]), Decimal(".1593344"))
        self.assertEqual(Decimal(budget["projected_additional_credits"]), Decimal("2.94027264"))
        self.assertEqual(Decimal(budget["projected_cumulative_credits"]), Decimal("43.92853488"))
        self.assertEqual(Decimal(budget["projected_remaining_credits"]), Decimal("6.07146512"))
        prior = ROOT / budget["previous_ledger"]
        self.assertEqual(hashlib.sha256(prior.read_bytes()).hexdigest(), budget["previous_ledger_sha256"])

    def test_authored_reference_families_recover_all_positive_slots(self):
        responses = [self.response(s, self.cases[s["case_id"]]["evaluation"]["reference_proposal"])
                     for s in self.sessions]
        summary = score_responses(self.study, responses)
        total = summary["aggregates"]
        self.assertEqual(total["scheduled"], 32)
        self.assertEqual(total["provider_completed"], 32)
        self.assertEqual(total["consequential_faithful_recoveries"], 16)
        self.assertEqual(total["clean_control_abstentions"], 16)
        self.assertEqual(total["unsupported_countergraphs_on_controls"], 0)
        for model in MODELS:
            for arm in ARMS:
                aggregate = summary["by_model_arm"][model][arm]
                self.assertEqual((aggregate["scheduled_positive"], aggregate["scheduled_control"]), (4, 4))
                self.assertEqual(aggregate["consequential_faithful_recoveries"], 4)
        for outcome in summary["outcomes"]:
            self.assertFalse(outcome["mechanical_result"]["semantic_verified"])
            self.assertFalse(outcome["mechanical_result"]["auto_applied"])

    def test_partial_positive_repair_does_not_get_full_family_credit(self):
        proposal = deepcopy(self.cases[CASE_IDS[0]]["evaluation"]["reference_proposal"])
        proposal["changes"].pop()
        outcome, _ = self.single(CASE_IDS[0], proposal)
        self.assertTrue(outcome["mechanically_checked"])
        self.assertTrue(outcome["witness_exists"])
        self.assertFalse(outcome["exact_source_family"])
        self.assertFalse(outcome["consequential_faithful_recovery"])

    def test_exact_negative_quote_cannot_certify_false_copy_relation(self):
        proposal = self.proposal("conservation-v6-09", "T4J4CGN", {"kind": "copy", "parents": ["5775EZ6"]})
        outcome, summary = self.single("conservation-v6-09", proposal)
        self.assertTrue(outcome["mechanically_checked"])
        self.assertTrue(outcome["witness_exists"])
        self.assertFalse(outcome["exact_source_family"])
        self.assertTrue(outcome["unsupported_countergraph"])
        self.assertEqual(summary["aggregates"]["unsupported_countergraphs_on_controls"], 1)
        self.assertEqual(summary["aggregates"]["control_counter_reading_attempts_including_invalid"], 1)

    def test_unadopted_question_does_not_make_new_route_faithful(self):
        proposal = self.proposal("conservation-v6-11", "VG7L3SW", {"supports": [["V2HDZ9M", "PR7FMQD"]]}, 2)
        outcome, _ = self.single("conservation-v6-11", proposal)
        self.assertTrue(outcome["mechanically_checked"])
        self.assertTrue(outcome["witness_exists"])
        self.assertFalse(outcome["exact_source_family"])

    def test_other_seed_member_is_faithful_but_not_new_coverage(self):
        proposal = self.proposal("conservation-v6-12", "4FM9WYM", {"kind": "root", "parents": []})
        outcome, _ = self.single("conservation-v6-12", proposal)
        self.assertTrue(outcome["exact_source_family"])
        self.assertTrue(outcome["witness_exists"])
        self.assertTrue(outcome["already_represented_proposal"])
        self.assertFalse(outcome["novel_to_seed_pool"])
        self.assertFalse(outcome["consequential_faithful_recovery"])

    def test_runtime_verifier_never_receives_reference_or_repaired_candidate(self):
        cid = CASE_IDS[0]
        public = self.cases[cid]["public"]
        seen = []
        def guarded(argument, proposal):
            self.assertEqual(set(argument), {"source_documents", "candidates", "registry"})
            self.assertEqual(argument, public)
            self.assertNotIn("source_families", argument)
            seen.append(deepcopy(argument))
            return verify_counter_reading(argument, proposal)
        with patch("retrace.falsification_v6_eval.verify_counter_reading", side_effect=guarded):
            outcome, _ = self.single(cid, self.cases[cid]["evaluation"]["reference_proposal"])
        self.assertEqual(len(seen), 1)
        self.assertTrue(outcome["consequential_faithful_recovery"])
        self.assertEqual(self.cases[cid]["public"], public)

    def test_empty_and_missing_rows_keep_every_scheduled_denominator(self):
        summary = score_responses(self.study, [])
        self.assertEqual(len(summary["outcomes"]), 32)
        self.assertEqual(summary["aggregates"]["status_counts"], {"unissued_or_missing": 32})
        for model in MODELS:
            for arm in ARMS:
                group = summary["by_model_arm"][model][arm]
                self.assertEqual(group["scheduled"], 8)
                self.assertEqual(group["recovery_rate_all_positive_slots"], 0)
        self.assertTrue(all(pair["complete_pair_recovery_difference"] is None for pair in summary["paired_comparisons"]))

    def test_operational_failure_stops_all_models_without_dropping_slots(self):
        rows = [self.response(s) for s in self.sessions[:3]]
        rows.append(self.response(self.sessions[3], response_status="incomplete"))
        summary = score_responses(self.study, rows)
        self.assertEqual(summary["outcomes"][3]["status"], "operational_failure")
        self.assertFalse(summary["outcomes"][3]["mechanically_checked"])
        self.assertEqual(summary["aggregates"]["scheduled"], 32)
        self.assertEqual(summary["aggregates"]["status_counts"]["unissued_or_missing"], 28)
        compliance = summary["protocol_compliance"]
        self.assertEqual(compliance["first_observed_operational_failure_slot"], 4)
        self.assertTrue(compliance["global_stop_compliant_given_observed_responses"])
        rows.append(self.response(self.sessions[4]))
        compliance = score_responses(self.study, rows)["protocol_compliance"]
        self.assertFalse(compliance["global_stop_compliant_given_observed_responses"])
        self.assertEqual(compliance["received_slots_after_required_global_stop"], [5])

    def test_missing_prefix_without_observed_failure_is_indeterminate(self):
        rows = [self.response(self.sessions[i]) for i in (0, 2)]
        summary = score_responses(self.study, rows)
        compliance = summary["protocol_compliance"]
        self.assertIsNone(compliance["global_stop_compliant_given_observed_responses"])
        self.assertEqual(compliance["missing_received_prefix_slots"], [2])
        self.assertEqual(compliance["last_received_slot"], 3)
        self.assertFalse(compliance["received_prefix_complete"])
        self.assertEqual(compliance["assessment"], "indeterminate_missing_prefix")
        self.assertEqual(summary["aggregates"]["received"], 2)
        self.assertEqual(summary["outcomes"][1]["status"], "unissued_or_missing")
        self.assertEqual(summary["outcomes"][2]["status"], "no_counter_reading")
        self.assertEqual(len(summary["outcomes"]), 32)

    def test_missing_response_before_terminal_is_not_certified(self):
        rows = [self.response(self.sessions[0]),
                self.response(self.sessions[2], response_status="incomplete")]
        summary = score_responses(self.study, rows)
        compliance = summary["protocol_compliance"]
        self.assertEqual(compliance["first_observed_operational_failure_slot"], 3)
        self.assertEqual(compliance["missing_received_prefix_slots"], [2])
        self.assertEqual(compliance["received_slots_after_required_global_stop"], [])
        self.assertIsNone(compliance["global_stop_compliant_given_observed_responses"])
        self.assertEqual(summary["outcomes"][2]["status"], "operational_failure")

    def test_hole_after_terminal_does_not_hide_later_received_violation(self):
        rows = [self.response(self.sessions[0], response_status="incomplete"),
                self.response(self.sessions[2])]
        summary = score_responses(self.study, rows)
        compliance = summary["protocol_compliance"]
        self.assertEqual(compliance["missing_received_prefix_slots"], [2])
        self.assertEqual(compliance["received_slots_after_required_global_stop"], [3])
        self.assertFalse(compliance["global_stop_compliant_given_observed_responses"])
        self.assertEqual(compliance["assessment"], "observed_stop_violation")
        self.assertEqual(summary["outcomes"][2]["status"], "no_counter_reading")

    def test_contiguous_prefix_and_terminal_trailing_absence_are_consistent(self):
        for terminal in (False, True):
            rows = [self.response(s) for s in self.sessions[:3]]
            if terminal:
                rows[-1]["response_status"] = "incomplete"
            # Journal input ordering does not change scheduled-prefix checking.
            with self.subTest(terminal=terminal):
                summary = score_responses(self.study, list(reversed(rows)))
                compliance = summary["protocol_compliance"]
                self.assertEqual(compliance["missing_received_prefix_slots"], [])
                self.assertEqual(compliance["unissued_or_missing_slots"], list(range(4, 33)))
                self.assertTrue(compliance["received_prefix_complete"])
                self.assertTrue(compliance["global_stop_compliant_given_observed_responses"])
                self.assertTrue(compliance["request_journal_audit_required"])
                self.assertEqual(summary["aggregates"]["received"], 3)

    def test_later_single_response_exposes_leading_holes(self):
        summary = score_responses(self.study, [self.response(self.sessions[3])])
        compliance = summary["protocol_compliance"]
        self.assertEqual(compliance["missing_received_prefix_slots"], [1, 2, 3])
        self.assertIsNone(compliance["global_stop_compliant_given_observed_responses"])

    def test_invalid_outputs_retained_including_false_control_attempts(self):
        cid = "conservation-v6-09"
        bad = self.proposal(cid, "T4J4CGN", {"kind": "copy", "parents": ["5775EZ6"]})
        bad["changes"][0]["sources"][0]["quote"] = "This quote was fabricated."
        outcome, summary = self.single(cid, bad)
        self.assertEqual(outcome["status"], "invalid_proposal")
        self.assertFalse(outcome["unsupported_countergraph"])
        self.assertEqual(summary["aggregates"]["control_counter_reading_attempts_including_invalid"], 1)
        for text in ('{"status":"counter_reading","status":"no_counter_reading"}', "not JSON", "\ud800"):
            outcome, _ = self.single(cid, None, output_text=text)
            self.assertEqual(outcome["status"], "invalid_proposal")
            self.assertTrue(outcome["provider_completed"])

    def test_unknown_duplicate_or_wrong_phase_journals_reject(self):
        row = self.response(self.sessions[0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            score_responses(self.study, [row, row])
        for key, value in (("model", "unknown"), ("phase", "prose_extract"), ("case_id", "other"), ("condition", "other")):
            malformed = deepcopy(row)
            malformed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Unknown"):
                score_responses(self.study, [malformed])

    def test_paired_difference_marks_censored_partner(self):
        cid = CASE_IDS[0]
        session = self.session(cid, arm=ARMS[1])
        proposal = self.cases[cid]["evaluation"]["reference_proposal"]
        summary = score_responses(self.study, [self.response(session, proposal)])
        pair = next(p for p in summary["paired_comparisons"] if p["model"] == MODELS[0] and p["case_id"] == cid)
        self.assertEqual(pair["all_scheduled_recovery_difference"], 1)
        self.assertIsNone(pair["complete_pair_recovery_difference"])
        self.assertFalse(pair["both_provider_completed"])

    def test_family_normalization_only_removes_ordering(self):
        graph = deepcopy(self.cases[CASE_IDS[1]]["evaluation"]["source_families"][0])
        permuted = deepcopy(graph)
        permuted["evidence"].reverse()
        permuted["claims"][0]["supports"][0].reverse()
        self.assertEqual(graph_key(graph), graph_key(permuted))
        permuted["evidence"][0]["active"] = False
        self.assertNotEqual(graph_key(graph), graph_key(permuted))


if __name__ == "__main__":
    unittest.main()
