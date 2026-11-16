"""Offline generated fixtures; never writes canary sessions or calls providers."""
from copy import deepcopy
import json
import unittest

from retrace.core import analyze
from retrace.frontier_v6c_io import family_score
from retrace.refuter_impact_v6 import compare_readings
from retrace.source_ir_v6d import compile_cited_ir
from scripts.build_frontier_v6g_canary import build, source_cases, expected_family, supplied_candidates, reference_ir
from scripts.score_frontier_v6g_canary import evaluate


def records():
    return [{**{k: slot[k] for k in ("slot_id", "model", "case_id", "condition", "phase")},
             "http_status": 200, "response_status": "completed", "terminal_valid": True,
             "error": None, "output_text": json.dumps(reference_ir()),
             "usage": {"input_tokens": 100, "output_tokens": 100, "total_tokens": 200}}
            for slot in build()]


class ContractCanaryTests(unittest.TestCase):
    def test_manual_family_matches_cited_fixture_and_shared_source(self):
        docs, registry = source_cases(); compiled = compile_cited_ir(reference_ir(), docs, registry)
        self.assertEqual(compiled["assignment_count"], 2)
        self.assertTrue(family_score(compiled["candidates"], expected_family())["exact_family"])
        for graph in expected_family():
            baseline = analyze(graph)
            self.assertTrue(all(row["usable"] for row in baseline["decisions"].values()))
            withdrawn = analyze(graph, ["L61"])
            self.assertFalse(withdrawn["evidence"]["M62"]["usable"])
            self.assertFalse(withdrawn["evidence"]["N63"]["usable"])
            self.assertFalse(withdrawn["evidence"]["P64"]["usable"])
            self.assertTrue(withdrawn["decisions"]["U69"]["usable"])

    def test_deficient_seed_has_real_whole_family_witness(self):
        seed = supplied_candidates(); gold = [{"id": f"gold-{i}", "graph": graph} for i, graph in enumerate(expected_family())]
        self.assertFalse(family_score(seed, expected_family())["exact_family"])
        result = compare_readings(seed, gold)
        self.assertEqual(result["decisions"]["S67"]["minimum_consensus_loss"]["withdraw"], ["N63"])
        self.assertEqual(result["decisions"]["S67"]["minimum_consensus_loss"]["current_family_state"], "unanimous_supported")

    def test_public_projection_two_formats_no_hidden_gold_or_answer_labels(self):
        slots = build(); self.assertEqual(len(slots), 10)
        self.assertEqual({s["temperature"] for s in slots}, {1.0})
        self.assertEqual({s["max_output_tokens"] for s in slots}, {65536})
        self.assertEqual(len({s["model"] for s in slots}), 5)
        for slot in slots:
            payload = json.loads(slot["input"])
            self.assertEqual(set(payload), {"source_segments", "registry", "segment_semantics"} | ({"supplied_candidates"} if slot["condition"] == "canary_adversarial_refuter" else set()))
            self.assertNotIn("expected_family", slot["input"])
            self.assertNotIn("reference_ir", slot["input"])
            self.assertNotIn("deficient", slot["input"])
            self.assertNotIn("evaluation", slot["input"])

    def test_exact_output_passes_all_ten_and_missing_calls_remain_failures(self):
        rows = records(); result = evaluate(build(), rows)
        self.assertTrue(result["passed"]); self.assertEqual(result["passed_slots"], 10)
        result = evaluate(build(), rows[:-1]); self.assertEqual(result["planned"], 10)
        self.assertEqual(result["passed_slots"], 9); self.assertFalse(result["passed"])

    def test_missing_binding_is_reported_even_when_graphs_are_exact(self):
        ir = reference_ir()
        ir["bindings"] = [b for b in ir["bindings"] if b["id"] != "ledger_reference"]
        for p in ir["propositions"]: p["bindings"] = [b for b in p["bindings"] if b != "ledger_reference"]
        rows = records(); rows[0]["output_text"] = json.dumps(ir)
        result = evaluate(build(), rows)
        self.assertTrue(result["results"][0]["exact_family"])
        self.assertFalse(result["results"][0]["explicit_master_binding"])
        self.assertEqual(result["passed_slots"], 9)
        self.assertEqual(evaluate(build(), rows, require_binding=False)["passed_slots"], 10)

    def test_known_bad_evidence_sufficient_route_remains_rejected(self):
        ir = reference_ir(); prop = deepcopy(next(p for p in ir["propositions"] if p["target"] == "P64" and p["kind"] == "origin"))
        prop.update(id="invalidExtra", kind="dependency", polarity="deny", body={"relation": "sufficient_route", "refs": ["M62"]})
        ir["propositions"].append(prop)
        rows = records(); rows[0]["output_text"] = json.dumps(ir)
        result = evaluate(build(), rows)
        self.assertEqual(result["passed_slots"], 9)
        self.assertIn("Sufficient route target must be claim", result["results"][0]["failure"])

    def test_abstention_truncation_and_mismatched_identity_fail(self):
        rows = records(); rows[1]["output_text"] = '{"status":"no_counter_reading"}'
        rows[2]["response_status"] = "incomplete"
        rows[3]["phase"] = "wrong"
        result = evaluate(build(), rows)
        self.assertEqual(result["passed_slots"], 7)
        self.assertEqual(result["results"][1]["failure"], "abstention_on_deficient_supplied_family")

    def test_terminal_and_usage_integrity_required_even_with_valid_ir(self):
        rows = records(); rows[0]["terminal_valid"] = False
        rows[1]["usage"]["input_tokens"] = True
        rows[2]["usage"]["total_tokens"] = 1
        self.assertEqual(evaluate(build(), rows)["passed_slots"], 7)

    def test_duplicate_or_unknown_responses_and_modified_source_reject(self):
        rows = records()
        with self.assertRaises(ValueError): evaluate(build(), rows + rows[:1])
        rows[0]["slot_id"] = "unknown"
        with self.assertRaises(ValueError): evaluate(build(), rows)
        slots = build(); slots[0]["input"] = '{}'
        with self.assertRaises(ValueError): evaluate(slots, [])


if __name__ == "__main__": unittest.main()
