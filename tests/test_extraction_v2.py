"""Offline v2 contract checks using invented fixtures, never the held-out corpus."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from retrace.compact_graph import MAX_NODES, MAX_TEXT_CHARS, serialize_compact
from retrace.extraction_v2_eval import parse_output, score
from retrace.extraction_v2_sessions import COMMON, INSTRUCTIONS, build_manifest, public_packet


def fixture(identifier="v2-fixture"):
    graph = {"id": identifier,
             "evidence": [{"id": "A", "kind": "root", "active": True, "parents": []},
                          {"id": "B", "kind": "root", "active": True, "parents": []},
                          {"id": "P", "kind": "copy", "active": True, "parents": ["A"]},
                          {"id": "X", "kind": "root", "active": False, "parents": []}],
             "claims": [{"id": "K", "supports": [["P"], ["B"]]},
                        {"id": "L", "supports": [["P"]]}, {"id": "N", "supports": [["X"]]}],
             "decisions": [{"id": "keep", "requires": ["K"]}, {"id": "lose", "requires": ["L"]},
                           {"id": "never", "requires": ["N"]}], "revoke": ["A"]}
    return {"id": identifier, "family": "offline-fixture", "title": "Fictional fixture only",
            "documents": [{"id": "doc_fixture", "title": "Declared rules",
                           "text": "A and B are available originals; X is unavailable. P is an available copy of A. K needs P or B; L needs P; N needs X. keep needs K; lose needs L; never needs N."}],
            "decision_questions": [{"id": d["id"], "text": "Is this decision supported?"} for d in graph["decisions"]],
            "event_text": "Withdraw A only; every other local flag and all dependencies stay unchanged.",
            "case": graph, "review_notes": {"private": "DO_NOT_SEND_REFERENCE_8723"}}


def final_graph(entry=None):
    entry = fixture() if entry is None else entry
    graph = {k: copy.deepcopy(entry["case"][k]) for k in ("evidence", "claims", "decisions")}
    for row in graph["evidence"]:
        if row["id"] in entry["case"]["revoke"]:
            row["active"] = False
    return graph


def registry(graph):
    return {kind: [row["id"] for row in nodes] for kind, nodes in graph.items()}


def response(condition="json_v2", entry=None, graph=None, text=None, **overrides):
    entry = fixture() if entry is None else entry
    graph = final_graph(entry) if graph is None else graph
    if text is None:
        text = json.dumps(graph) if condition == "json_v2" else serialize_compact(graph)
    return {"case_id": entry["id"], "condition": condition, "phase": "final", "model": "offline-test-model",
            "output_text": text, "response_status": "completed", "error": None, **overrides}


class NoPrivateReads(dict):
    def __getitem__(self, key):
        if key in {"case", "family", "review_notes", "domain"}:
            raise AssertionError("Private field read by public_packet: " + key)
        return super().__getitem__(key)


class ExtractionV2Tests(unittest.TestCase):
    def test_public_packet_never_reads_gold_or_review_metadata(self):
        entry = fixture()
        baseline = public_packet(NoPrivateReads(entry))
        poisoned = copy.deepcopy(entry)
        poison = "PRIVATE_GOLD_SENTINEL_54289"
        poisoned["case"] = poison
        poisoned["review_notes"] = poison
        poisoned["family"] = poison
        poisoned["domain"] = poison
        self.assertEqual(public_packet(poisoned), baseline)
        self.assertNotIn(poison, baseline)
        self.assertNotIn("DO_NOT_SEND_REFERENCE", baseline)
        self.assertIn(entry["event_text"], baseline)
        # The public prose update, not an oracle revoke list, determines the packet.
        original = copy.deepcopy(entry)
        original["case"]["revoke"] = ["B"]
        self.assertEqual(public_packet(original), baseline)

    def test_paired_sessions_share_exact_user_packet_and_common_instructions(self):
        entry = fixture()
        manifest = build_manifest([entry])
        self.assertEqual((manifest["case_count"], manifest["request_count"]), (1, 2))
        sessions = {s["condition"]: s for s in manifest["sessions"]}
        self.assertEqual(set(sessions), {"json_v2", "compact_v2"})
        self.assertEqual(sessions["json_v2"]["steps"], sessions["compact_v2"]["steps"])
        for condition, session in sessions.items():
            self.assertEqual(session["response_kind"], "graph")
            self.assertEqual(session["steps"], [{"phase": "final", "input": public_packet(entry)}])
            self.assertEqual(session["instructions"], INSTRUCTIONS[condition])
            self.assertTrue(session["instructions"].startswith(COMMON + "\n"))
            self.assertNotIn(entry["family"], session["instructions"] + session["steps"][0]["input"])
            self.assertEqual(session["decision_ids"], [d["id"] for d in entry["decision_questions"]])

    def test_manifest_hash_reproducibly_binds_both_format_prompts(self):
        manifest = build_manifest([fixture()])
        repeated = build_manifest([fixture()])
        self.assertEqual(manifest, repeated)
        payload = {k: v for k, v in manifest.items() if k != "sha256"}
        self.assertEqual(manifest["sha256"], hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                                                      separators=(",", ":")).encode()).hexdigest())
        changed = fixture()
        changed["event_text"] += " Extra explicit condition."
        self.assertNotEqual(build_manifest([changed])["sha256"], manifest["sha256"])

    def test_format_illustrations_encode_the_same_complete_graph(self):
        illustrations = {condition: instructions.split("Illustration output:\n", 1)[1].split("\nNow extract ONLY", 1)[0]
                         for condition, instructions in INSTRUCTIONS.items()}
        parsed = {condition: parse_output(text, condition) for condition, text in illustrations.items()}
        self.assertEqual(parsed["json_v2"]["graph"], parsed["compact_v2"]["graph"])
        graph = parsed["json_v2"]["graph"]
        self.assertEqual(sum(len(rows) for rows in graph.values()), 7)
        self.assertTrue(all(row["id"].startswith("ex_") for rows in graph.values() for row in rows))
        copy_node = next(row for row in graph["evidence"] if row["id"] == "ex_copy")
        self.assertEqual(copy_node, {"id": "ex_copy", "kind": "copy", "active": True, "parents": ["ex_a", "ex_c"]})
        self.assertFalse(next(row for row in graph["evidence"] if row["id"] == "ex_c")["active"])
        self.assertEqual(next(row for row in graph["claims"] if row["id"] == "ex_p")["supports"], [["ex_a"], ["ex_b", "ex_copy"]])

    def test_both_formats_preserve_source_and_accept_matched_explicit_structure(self):
        graph = final_graph()
        for condition, text in (("json_v2", json.dumps(graph)), ("compact_v2", serialize_compact(graph))):
            with self.subTest(condition=condition):
                parsed = parse_output(text, condition, registry(graph))
                self.assertEqual(parsed["source_text"], text)
                self.assertTrue(parsed["strict_bare"])
                self.assertFalse(parsed["outer_fence_removed"])
                self.assertTrue(next(row for row in parsed["graph"]["evidence"] if row["id"] == "P")["active"])
        self.assertEqual(parse_output(json.dumps(graph), "json_v2")["graph"],
                         parse_output(serialize_compact(graph), "compact_v2")["graph"])

    def test_json_requires_explicit_fields_and_does_not_invoke_offline_serializer(self):
        graph = final_graph()
        for field in ("kind", "active", "parents"):
            missing = copy.deepcopy(graph)
            del missing["evidence"][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_output(json.dumps(missing), "json_v2")
        extra = copy.deepcopy(graph)
        extra["claims"][0]["label"] = "not permitted in matched contract"
        with self.assertRaises(ValueError):
            parse_output(json.dumps(extra), "json_v2")
        with patch("retrace.compact_graph.serialize_compact", side_effect=AssertionError("offline serializer called")):
            parsed = parse_output(json.dumps(graph), "json_v2")
            self.assertTrue(parsed["strict_bare"])

    def test_fence_normalization_is_condition_specific_and_strictness_stays_separate(self):
        graph = final_graph()
        for condition, language, text in (("json_v2", "json", json.dumps(graph)),
                                          ("compact_v2", "text", serialize_compact(graph)),
                                          ("compact_v2", "plaintext", serialize_compact(graph))):
            raw = "```" + language + "\n" + text + "\n```"
            parsed = parse_output(raw, condition)
            self.assertTrue(parsed["outer_fence_removed"])
            self.assertFalse(parsed["strict_bare"])
            self.assertEqual(parsed["source_text"], raw)
            group = score([fixture()], [response(condition, text=raw)])["groups"][condition]
            self.assertEqual((group["valid"], group["strict_valid"], group["graph_exact"]), (1, 0, 1))
        with self.assertRaises(ValueError): parse_output("```text\n" + json.dumps(graph) + "\n```", "json_v2")
        with self.assertRaises(ValueError): parse_output("```json\n" + serialize_compact(graph) + "\n```", "compact_v2")

    def test_equal_structural_constraints_reject_cycles_duplicates_and_unknowns(self):
        graph = final_graph()
        variants = []
        duplicate = copy.deepcopy(graph); duplicate["claims"][0]["supports"] *= 2; variants.append(duplicate)
        cycle = copy.deepcopy(graph); cycle["claims"][0]["supports"] = [["K"]]; variants.append(cycle)
        unknown = copy.deepcopy(graph); unknown["claims"][0]["supports"] = [["unknown"]]; variants.append(unknown)
        wrong_category = copy.deepcopy(graph); wrong_category["decisions"][0]["requires"] = ["A"]; variants.append(wrong_category)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_output(json.dumps(value), "json_v2")
        for text in ("C K K\nEND", "C K unknown\nEND", "E A R 1 -\nC K A|A\nEND", "E A R 1 -\nD D A\nEND"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_output(text, "compact_v2")
        for condition in ("json_v2", "compact_v2"):
            with self.assertRaises(ValueError): parse_output("x" * (MAX_TEXT_CHARS + 1), condition)
        too_many = {"evidence": [{"id": f"n{i}", "kind": "root", "active": True, "parents": []} for i in range(MAX_NODES + 1)],
                    "claims": [], "decisions": []}
        with self.assertRaises(ValueError): parse_output(json.dumps(too_many), "json_v2")

    def test_graph_exact_and_downstream_exact_are_different_outcomes(self):
        altered = final_graph()
        altered["claims"][0]["supports"] = [["B"]]  # Drops a failed route, but same current decisions.
        report = score([fixture()], [response(graph=altered)])
        group = report["groups"]["json_v2"]
        self.assertEqual((group["valid"], group["graph_exact"], group["decision_exact"]), (1, 0, 1))
        self.assertEqual(group["correct_decisions_all_scheduled"], 3)
        self.assertEqual(report["outcomes"][0]["predictions"], {"keep": True, "lose": False, "never": False})

    def test_all_scheduled_counts_keep_invalid_and_missing_outputs(self):
        first, second = fixture(), fixture("v2-fixture-two")
        altered = final_graph(first)
        altered["claims"][0]["supports"] = [["P"]]  # Incorrectly loses protected support.
        rows = [response(entry=first), response(entry=second, text="not JSON"),
                response("compact_v2", entry=first, graph=altered), response("compact_v2", entry=second)]
        report = score([first, second], rows)
        left, right = report["groups"]["json_v2"], report["groups"]["compact_v2"]
        self.assertEqual((left["expected"], left["received"], left["valid"], left["decision_targets"]), (2, 2, 1, 6))
        self.assertEqual((left["correct_decisions_all_scheduled"], left["decision_targets_valid"]), (3, 3))
        self.assertEqual((right["valid"], right["graph_exact"], right["decision_exact"], right["correct_decisions_all_scheduled"]), (2, 1, 1, 5))
        self.assertEqual(report["contrasts"]["valid"]["compact_minus_json"], .5)
        self.assertEqual(report["contrasts"]["graph_exact"]["compact_minus_json"], 0)
        missing = score([first], [])
        self.assertEqual(missing["groups"]["json_v2"]["decision_targets"], 3)
        self.assertEqual(missing["groups"]["json_v2"]["correct_decisions_all_scheduled"], 0)

    def test_operational_failure_never_uses_valid_looking_body(self):
        row = response(error="response_not_completed", response_status="incomplete",
                       usage={"input_tokens": 12, "output_tokens": 9, "output_tokens_details": {"reasoning_tokens": 2}}, latency_ms=80)
        group = score([fixture()], [row])["groups"]["json_v2"]
        self.assertEqual((group["operational_failures"], group["valid"], group["decision_exact"]), (1, 0, 0))
        self.assertEqual((group["input_tokens"], group["output_tokens"], group["reasoning_tokens"]), (12, 9, 2))
        self.assertEqual(group["median_latency_ms"], 80)

    def test_provider_null_reasoning_details_are_not_a_scoring_crash(self):
        for details in (None, {}, {"reasoning_tokens": None}):
            with self.subTest(details=details):
                row = response(usage={"input_tokens": 12, "output_tokens": 9, "output_tokens_details": details})
                group = score([fixture()], [row])["groups"]["json_v2"]
                self.assertEqual(group["valid"], 1)
                self.assertEqual(group["reasoning_tokens"], 0)

    def test_duplicate_unexpected_and_mixed_model_records_are_rejected(self):
        with self.assertRaises(ValueError): score([fixture(), fixture()], [])
        with self.assertRaises(ValueError): score([fixture()], [response(), response()])
        with self.assertRaises(ValueError): score([fixture()], [response(phase="initial")])
        with self.assertRaises(ValueError): score([fixture()], [response(condition="unknown", text="END")])
        with self.assertRaises(ValueError): score([fixture()], [response(), response("compact_v2", model="other-model")])

    def test_empty_corpus_has_no_invented_performance(self):
        with self.assertRaises(ValueError):
            score([], [])


if __name__ == "__main__":
    unittest.main()
