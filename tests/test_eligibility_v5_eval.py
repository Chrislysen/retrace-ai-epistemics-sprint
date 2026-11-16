"""Authored response fixtures only; finalized before prospective paid outputs."""
import copy
import unittest
from unittest.mock import patch

from retrace.ambiguity_v4_sessions import ABSTENTION
from retrace.eligibility_v5_eval import CONDITION, score_responses
from tests.test_eligibility_v5_pairs import corpus, source_encoding


def response(packet, text=None, **updates):
    return {"case_id": packet["id"], "condition": CONDITION, "phase": "final", "response_status": "completed",
            "output_text": source_encoding(packet) if text is None else text, "error": None, **updates}


class EligibilityV5EvaluationTests(unittest.TestCase):
    def test_all_correct_pairs_recover_families_and_preserve_primary_invariant(self):
        packets = corpus()
        scored = score_responses(packets, [response(packet) for packet in packets])
        aggregate = scored["aggregates"]
        self.assertEqual(aggregate["scheduled_cases"], 8)
        self.assertEqual(aggregate["scheduled_pairs"], 4)
        self.assertEqual(aggregate["exact_family_recovery_cases"], 8)
        self.assertEqual(aggregate["specification_invariant_pairs"], 4)
        self.assertEqual(aggregate["invariant_and_source_exact_pairs"], 4)
        self.assertEqual(aggregate["eligibility_faithful_cases"], 8)
        self.assertEqual(aggregate["assignment_branches"], 16)
        self.assertEqual(aggregate["selective"]["scheduled_decisions"], 12)
        self.assertEqual(aggregate["cases_with_current_disagreement"], 3)
        for row in scored["outcomes"]:
            self.assertNotIn("challenge", row["evaluation"])
            self.assertFalse(row["evaluation"]["challenge_evaluated"])

    def test_invariant_wrong_topology_is_not_semantic_success(self):
        packets = corpus()
        answers = []
        for packet in packets[:2]:
            e, c = packet["public"]["registry"]["evidence"], packet["public"]["registry"]["claims"]
            text = source_encoding(packet).replace(f"C {c[0]} {e[3]}|{e[4]}", f"C {c[0]} {e[3]}+{e[4]}")
            answers.append(response(packet, text))
        scored = score_responses(packets, answers)
        pair = scored["pairs"][0]
        self.assertTrue(pair["both_admitted"])
        self.assertTrue(pair["specification_sets_invariant"])
        self.assertTrue(pair["topology_sets_invariant"])
        self.assertFalse(pair["both_source_exact"])
        self.assertFalse(pair["invariant_and_source_exact"])
        self.assertEqual(scored["aggregates"]["cases_with_wrong_current_unanimity"], 0)

    def test_unrelated_flag_change_breaks_primary_but_not_topology_invariance(self):
        packets = corpus()
        other = packets[1]["public"]["registry"]["evidence"][1]
        wrong = source_encoding(packets[1]).replace(f"E {other} R 1 -", f"E {other} R 0 -")
        scored = score_responses(packets, [response(packets[0]), response(packets[1], wrong)])
        pair = scored["pairs"][0]
        self.assertFalse(pair["specification_sets_invariant"])
        self.assertTrue(pair["topology_sets_invariant"])
        self.assertFalse(pair["both_eligibility_faithful"])

    def test_wrong_designated_flag_is_not_hidden_by_invariance_normalization(self):
        packets = corpus()
        changed = packets[1]["hidden"]["changed_evidence_id"]
        wrong = source_encoding(packets[1]).replace(f"E {changed} R 1 -", f"E {changed} R 0 -")
        scored = score_responses(packets, [response(packets[0]), response(packets[1], wrong)])
        self.assertTrue(scored["pairs"][0]["specification_sets_invariant"])
        self.assertFalse(scored["pairs"][0]["both_eligibility_faithful"])
        self.assertFalse(scored["pairs"][0]["both_source_exact"])

    def test_failures_and_abstention_keep_all_eight_and_four_denominators(self):
        packets = corpus()
        rows = [response(packets[0]), response(packets[1], ABSTENTION), response(packets[2], "END"),
                response(packets[3], response_status="incomplete")]
        scored = score_responses(packets, rows)
        aggregate = scored["aggregates"]
        self.assertEqual(aggregate["status_counts"], {"admitted": 1, "explicit_abstention": 1,
                         "syntax_or_branch_failure": 1, "operational_failure": 1, "unissued_or_missing": 4})
        self.assertEqual(aggregate["scheduled_cases"], 8)
        self.assertEqual(aggregate["scheduled_pairs"], 4)
        self.assertEqual(aggregate["both_admitted_pairs"], 0)
        self.assertEqual(aggregate["invariance_rate_all_scheduled_pairs"], 0)
        self.assertIsNone(aggregate["invariance_rate_among_both_admitted"])
        self.assertTrue(all(pair["specification_sets_invariant"] is None for pair in scored["pairs"]))

    def test_ambiguity_collapse_changes_normalized_family_even_with_same_current_outcome(self):
        packets = corpus()
        packet = packets[5]
        c = packet["public"]["registry"]["claims"]
        wrong = source_encoding(packet).replace(f"C {c[2]} UNSPECIFIED_CHOICE({c[0]}, {c[1]})", f"C {c[2]} {c[0]}")
        scored = score_responses(packets, [response(packets[4]), response(packet, wrong)])
        self.assertFalse(scored["pairs"][2]["specification_sets_invariant"])
        self.assertFalse(scored["pairs"][2]["both_source_exact"])
        self.assertTrue(scored["outcomes"][5]["evaluation"]["current"]["agreement"]["all_targets_correct_unanimous"])

    def test_wrong_condition_duplicate_unknown_and_phase_fail_closed(self):
        packets = corpus()
        good = response(packets[0])
        for rows in ([good, copy.deepcopy(good)], [{**good, "condition": "other"}],
                     [{**good, "case_id": "not-a-case"}], [{**good, "phase": "history"}]):
            with self.assertRaises(ValueError):
                score_responses(packets, rows)

    def test_detector_receives_only_compiled_candidates_not_authored_family(self):
        import retrace.ambiguity_v4_eval as reused
        packets = corpus()
        packet = packets[4]
        c = packet["public"]["registry"]["claims"]
        text = source_encoding(packet).replace(f"C {c[2]} UNSPECIFIED_CHOICE({c[0]}, {c[1]})", f"C {c[2]} {c[0]}")
        seen, original = [], reused.analyze_stress
        def spy(brief, state=None):
            seen.append(len(brief["candidates"]))
            return original(brief, state)
        with patch.object(reused, "analyze_stress", side_effect=spy):
            score_responses(packets, [response(packet, text)])
        self.assertTrue(seen)
        self.assertEqual(set(seen), {1})


if __name__ == "__main__":
    unittest.main()
