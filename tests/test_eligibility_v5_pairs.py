"""Offline consistency checks for the authored prospective eligibility pairs."""
import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path

from retrace.compact_v5 import compile_ambiguity

ROOT = Path(__file__).resolve().parents[1]


def corpus():
    return json.loads((ROOT / "data/eligibility-v5-paired-staged.json").read_text(encoding="utf-8"))


def signature(graph, changed=None):
    return (frozenset((r["id"], r["kind"], True if r["id"] == changed else r["active"], frozenset(r["parents"])) for r in graph["evidence"]),
            frozenset((r["id"], frozenset(frozenset(clause) for clause in r["supports"])) for r in graph["claims"]),
            frozenset((r["id"], frozenset(r["requires"])) for r in graph["decisions"]))


def source_encoding(row):
    """Hand-written forms of the four public source structures, using registry IDs."""
    registry = row["public"]["registry"]
    e, c, d = (registry[k] for k in ("evidence", "claims", "decisions"))
    active = int(row["hidden"]["changed_local_active"])
    family = row["hidden"]["family"]
    if family == "shared_gate_alternatives":
        lines = [f"E {e[0]} R {active} -", f"E {e[1]} R 1 -", f"E {e[2]} R 1 -",
                 f"E {e[3]} C 1 {e[1]},{e[0]}", f"E {e[4]} C 1 {e[2]},{e[0]}",
                 f"C {c[0]} {e[3]}|{e[4]}", f"D {d[0]} {c[0]}"]
    elif family == "copies_and_independent_alternative":
        lines = [f"E {e[0]} R {active} -", f"E {e[1]} C 1 {e[0]}", f"E {e[2]} C 1 {e[0]}", f"E {e[3]} R 1 -",
                 f"C {c[0]} {e[1]}|{e[2]}", f"C {c[1]} {e[1]}|{e[2]}|{e[3]}",
                 f"D {d[0]} {c[0]}", f"D {d[1]} {c[1]}"]
    elif family == "fixed_unknown_designation":
        lines = [f"E {e[0]} R {active} -", f"E {e[1]} R 1 -", f"E {e[2]} R 1 -",
                 f"C {c[0]} {e[0]}+{e[2]}", f"C {c[1]} {e[1]}",
                 f"C {c[2]} UNSPECIFIED_CHOICE({c[0]}, {c[1]})", f"D {d[0]} {c[2]}"]
    else:
        lines = [f"E {e[0]} R 1 -", f"E {e[1]} R 1 -", f"E {e[2]} R {active} -",
                 f"E {e[3]} R 0 -", f"E {e[4]} R 1 -",
                 f"C {c[0]} AMBIGUOUS_QUALIFIER({e[0]}, {e[1]}, {e[2]})",
                 f"C {c[1]} UNSPECIFIED_CHOICE({e[3]}, {e[4]})",
                 f"D {d[0]} {c[0]}", f"D {d[1]} {c[1]}"]
    return "\n".join(lines + ["END"])


def fixed_point(graph, revoked=()):
    values = {r["id"]: False for kind in ("evidence", "claims", "decisions") for r in graph[kind]}
    for _ in range(len(values) + 1):
        updated = {}
        for r in graph["evidence"]:
            updated[r["id"]] = r["active"] and r["id"] not in revoked and (r["kind"] == "root" or all(values[p] for p in r["parents"]))
        for r in graph["claims"]:
            updated[r["id"]] = any(all(values[p] for p in route) for route in r["supports"])
        for r in graph["decisions"]:
            updated[r["id"]] = all(values[p] for p in r["requires"])
        if updated == values:
            return tuple(values[r["id"]] for r in graph["decisions"])
        values = updated
    raise AssertionError("Non-convergent authored source graph")


class EligibilityV5PairTests(unittest.TestCase):
    def test_public_pair_diff_is_exactly_one_eligibility_sentence(self):
        rows = corpus()
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({row["id"] for row in rows}), 8)
        self.assertEqual(len({row["pair_id"] for row in rows}), 4)
        for offset in range(0, 8, 2):
            left, right = rows[offset:offset + 2]
            self.assertEqual(left["pair_id"], right["pair_id"])
            self.assertEqual(left["hidden"]["changed_evidence_id"], right["hidden"]["changed_evidence_id"])
            self.assertFalse(left["hidden"]["changed_local_active"])
            self.assertTrue(right["hidden"]["changed_local_active"])
            normalized = []
            for row in (left, right):
                public = copy.deepcopy(row["public"])
                text, sentence = public["documents"][0]["text"], row["hidden"]["eligibility_sentence"]
                self.assertEqual(text.count(sentence), 1)
                public["documents"][0]["text"] = text.replace(sentence, "<ELIGIBILITY>")
                normalized.append(public)
            self.assertEqual(*normalized)

    def test_all_relationships_families_and_actual_indices_are_pair_invariant(self):
        rows = corpus()
        for offset in range(0, 8, 2):
            left, right = rows[offset:offset + 2]
            changed = left["hidden"]["changed_evidence_id"]
            self.assertEqual(left["hidden"]["author_actual_interpretation_index"], right["hidden"]["author_actual_interpretation_index"])
            self.assertEqual([signature(g, changed) for g in left["hidden"]["allowed_interpretations"]],
                             [signature(g, changed) for g in right["hidden"]["allowed_interpretations"]])
            for row in (left, right):
                for graph in row["hidden"]["allowed_interpretations"]:
                    self.assertEqual(next(e["active"] for e in graph["evidence"] if e["id"] == changed), row["hidden"]["changed_local_active"])

    def test_generic_v5_source_encodings_match_all_authored_families(self):
        for row in corpus():
            compiled = compile_ambiguity(source_encoding(row), row["public"]["registry"])
            expected = {signature(graph) for graph in row["hidden"]["allowed_interpretations"]}
            self.assertEqual({signature(candidate["graph"]) for candidate in compiled["candidates"]}, expected)
            self.assertEqual(compiled["candidate_count"], len(expected))
            self.assertLessEqual(compiled["uncertainty_count"], 2)

    def test_independent_outcomes_change_without_changing_source_ambiguities(self):
        expected = [{(False,)}, {(True,)}, {(False, True)}, {(True, True)},
                    {(False,), (True,)}, {(True,)}, {(False, False), (False, True), (True, False), (True, True)},
                    {(True, False), (True, True)}]
        for row, outcomes in zip(corpus(), expected):
            self.assertEqual({fixed_point(graph) for graph in row["hidden"]["allowed_interpretations"]}, outcomes)

    def test_shared_gate_and_copy_alternatives_are_not_joint_routes(self):
        rows = corpus()
        first = rows[1]["hidden"]["allowed_interpretations"][0]
        e = rows[1]["public"]["registry"]["evidence"]
        self.assertEqual(fixed_point(first, [e[3]]), (True,))
        self.assertEqual(fixed_point(first, [e[4]]), (True,))
        self.assertEqual(fixed_point(first, [e[0]]), (False,))
        second = rows[3]["hidden"]["allowed_interpretations"][0]
        e = rows[3]["public"]["registry"]["evidence"]
        self.assertEqual(fixed_point(second, [e[1]]), (True, True))
        self.assertEqual(fixed_point(second, [e[0]]), (False, True))

    def test_sessions_contain_only_public_source_and_identical_generic_instructions(self):
        sessions = json.loads((ROOT / "data/eligibility-v5-paired-sessions.json").read_text(encoding="utf-8"))
        rows = {row["id"]: row for row in corpus()}
        self.assertEqual(len(sessions), 8)
        self.assertEqual({s["case_id"] for s in sessions}, set(rows))
        self.assertEqual(len({s["instructions"] for s in sessions}), 1)
        for session in sessions:
            self.assertEqual(len(session["steps"]), 1)
            self.assertEqual(session["steps"][0]["phase"], "final")
            source = json.loads(session["steps"][0]["input"])
            self.assertEqual(source, rows[session["case_id"]]["public"])
            self.assertEqual(set(source), {"id", "title", "documents", "registry"})
            self.assertNotIn(session["case_id"], session["steps"][0]["input"])
            for row in rows.values():
                self.assertNotIn(row["id"], session["instructions"])
                for node in sum(list(row["public"]["registry"].values()), []):
                    self.assertNotIn(node, session["instructions"])
            self.assertIn("C TARGET AMBIGUOUS_GATE(A, B)", session["instructions"])
            self.assertIn("E CHILD ? 1 UNVERIFIED_INDEPENDENCE(PARENT)", session["instructions"])

    def test_projected_bound_is_exact_and_protocol_is_not_dispatch_authorization(self):
        one = (Decimal(256000) * Decimal('0.09') + Decimal(4096) * Decimal('0.34')) / Decimal(1000000)
        self.assertEqual(one * 8, Decimal('0.19546112'))
        total = Decimal('40.79280112') + one * 8
        self.assertEqual(total, Decimal('40.98826224'))
        self.assertLess(total, Decimal(41))
        protocol = (ROOT / "research/eligibility-v5-paired-protocol.md").read_text(encoding="utf-8")
        self.assertIn("offline preparation only", protocol)
        self.assertIn("No requests, credits or reservations", protocol)
        self.assertIn("not a natural-document sample", protocol)


if __name__ == "__main__":
    unittest.main()
