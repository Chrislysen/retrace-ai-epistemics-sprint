import copy
import json
from pathlib import Path
import unittest

from retrace.core import analyze
from retrace.prose_eval import CONDITIONS, gold_for
from retrace.prose_sessions import (
    DECISION_INSTRUCTIONS, EXTRACTION_INSTRUCTIONS,
    build_manifest, final_case, make_prose_sessions, packet,
)


CORPUS = Path(__file__).resolve().parents[1] / "data" / "prose-holdout.json"


def sent_text(session):
    """Only these fields become model-facing instructions/user messages."""
    return session["instructions"] + "\n" + "\n".join(step["input"] for step in session["steps"])


class ProseSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads(CORPUS.read_text(encoding="utf-8"))

    def test_each_case_has_six_requests_and_only_prespecified_phases(self):
        sessions = make_prose_sessions(self.corpus)
        self.assertEqual(len(sessions), 24 * 5)
        self.assertEqual(sum(len(session["steps"]) for session in sessions), 24 * 6)
        for entry in self.corpus:
            with self.subTest(case=entry["id"]):
                rows = [session for session in sessions if session["case_id"] == entry["id"]]
                self.assertEqual({s["condition"]: tuple(step["phase"] for step in s["steps"])
                                  for s in rows}, CONDITIONS)
                for session in rows:
                    self.assertEqual(set(session["decision_ids"]),
                                     {decision["id"] for decision in entry["decision_questions"]})

    def test_prose_prompts_do_not_depend_on_reference_rules_or_review_metadata(self):
        entry = copy.deepcopy(self.corpus[0])
        baseline = {s["condition"]: sent_text(s) for s in make_prose_sessions([entry])}
        marker = "PRIVATE_ORACLE_SENTINEL_54732"
        entry["family"] = marker
        entry["domain"] = marker
        entry["review_notes"] = {"expected_final": marker}
        entry["case"]["title"] = marker
        entry["case"]["claims"][0]["supports"] = [[marker]]
        entry["case"]["evidence"][0]["label"] = marker
        entry["case"]["decisions"][0]["requires"] = [marker]
        changed_sessions = {s["condition"]: s for s in make_prose_sessions([entry])}
        changed = {condition: sent_text(s) for condition, s in changed_sessions.items()}
        self.assertIn(marker, changed["formal_fresh"])
        for condition in CONDITIONS:
            if condition == "formal_fresh":
                continue
            with self.subTest(condition=condition):
                self.assertEqual(changed[condition], baseline[condition])
                self.assertNotIn(marker, changed[condition])
                for step in changed_sessions[condition]["steps"]:
                    self.assertNotIn('"supports":', step["input"])

    def test_final_case_changes_only_explicit_local_withdrawals_without_mutation(self):
        original = copy.deepcopy(self.corpus)
        active_descendant_found = False
        for entry in self.corpus:
            with self.subTest(case=entry["id"]):
                graph = final_case(entry)
                self.assertEqual(set(graph), {"evidence", "claims", "decisions"})
                self.assertEqual(graph, gold_for(entry)["final_graph"])
                self.assertEqual(graph["claims"], entry["case"]["claims"])
                self.assertEqual(graph["decisions"], entry["case"]["decisions"])
                before = {node["id"]: node for node in entry["case"]["evidence"]}
                after = analyze(graph)
                for node in graph["evidence"]:
                    expected = copy.deepcopy(before[node["id"]])
                    if node["id"] in entry["case"]["revoke"]:
                        expected["active"] = False
                    self.assertEqual(node, expected)
                    if (node.get("kind") == "copy" and node.get("active", True)
                            and not after["evidence"][node["id"]]["usable"]):
                        active_descendant_found = True
                # Independently compare explicit withdrawal with final local flags.
                self.assertEqual(after["supported_decisions"],
                                 analyze(entry["case"], entry["case"]["revoke"])["supported_decisions"])
                graph["claims"][0]["label"] = "mutated returned copy"
        self.assertTrue(active_descendant_found, "Corpus must exercise local activity versus inherited usability")
        self.assertEqual(self.corpus, original)

    def test_history_and_no_commitment_expose_same_original_update(self):
        for entry in self.corpus:
            sessions = {s["condition"]: s for s in make_prose_sessions([entry])}
            history = sessions["prose_history"]
            no_commitment = sessions["prose_no_commitment"]
            with self.subTest(case=entry["id"]):
                self.assertEqual(history["instructions"], no_commitment["instructions"])
                self.assertEqual(history["instructions"], DECISION_INSTRUCTIONS)
                self.assertTrue(history["steps"][0]["input"].startswith(packet(entry)))
                self.assertNotIn(entry["event_text"], history["steps"][0]["input"])
                self.assertIn(entry["event_text"], history["steps"][1]["input"])
                self.assertNotIn(packet(entry), history["steps"][1]["input"])
                self.assertEqual(len(no_commitment["steps"]), 1)
                self.assertIn(packet(entry), no_commitment["steps"][0]["input"])
                self.assertIn(entry["event_text"], no_commitment["steps"][0]["input"])
                self.assertNotIn("AUTHORITATIVE CURRENT-ELIGIBILITY SNAPSHOT", sent_text(history))
                self.assertNotIn("AUTHORITATIVE CURRENT-ELIGIBILITY SNAPSHOT", sent_text(no_commitment))

    def test_extraction_and_direct_fresh_use_identical_final_packet(self):
        for entry in self.corpus:
            sessions = {s["condition"]: s for s in make_prose_sessions([entry])}
            direct, extraction = sessions["prose_fresh"], sessions["prose_extract"]
            with self.subTest(case=entry["id"]):
                direct_packet = direct["steps"][0]["input"].removesuffix("\n\nReturn the current decision-support map.")
                extract_packet = extraction["steps"][0]["input"].removesuffix("\n\nExtract the full direct support graph at the current snapshot.")
                self.assertEqual(direct_packet, extract_packet)
                self.assertTrue(direct_packet.startswith(packet(entry)))
                self.assertIn("AUTHORITATIVE CURRENT-ELIGIBILITY SNAPSHOT", direct_packet)
                for revoked in entry["case"]["revoke"]:
                    self.assertIn(revoked, direct_packet.split("AUTHORITATIVE CURRENT-ELIGIBILITY SNAPSHOT")[1])
                self.assertEqual(extraction["instructions"], EXTRACTION_INSTRUCTIONS)
                self.assertEqual(extraction["response_kind"], "graph")

    def test_formal_payload_contains_only_the_final_unsolved_graph(self):
        for entry in self.corpus:
            formal = next(s for s in make_prose_sessions([entry]) if s["condition"] == "formal_fresh")
            payload = json.loads(formal["steps"][0]["input"].split("\n", 1)[1])
            self.assertEqual(payload, final_case(entry))
            self.assertNotIn("review_notes", payload)
            self.assertNotIn("revoke", payload)
            self.assertNotIn("supported_decisions", payload)

    def test_manifest_is_reproducible_and_hash_changes_with_prompt_content(self):
        first = build_manifest(self.corpus)
        second = build_manifest(self.corpus)
        self.assertEqual(first, second)
        self.assertEqual(first["request_count"], 144)
        altered = copy.deepcopy(self.corpus)
        altered[0]["documents"][0]["text"] += " Extra declared context."
        self.assertNotEqual(first["sha256"], build_manifest(altered)["sha256"])
        different_order = build_manifest(self.corpus, seed=first["seed"] + 1)
        self.assertNotEqual(first["sha256"], different_order["sha256"])
        self.assertEqual({(s["case_id"], s["condition"]) for s in first["sessions"]},
                         {(s["case_id"], s["condition"]) for s in different_order["sessions"]})


if __name__ == "__main__":
    unittest.main()
