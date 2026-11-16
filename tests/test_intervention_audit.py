import copy
import itertools
import random
import unittest

from retrace.core import analyze
from retrace.intervention_audit import audit_interventions


def graph():
    return {"evidence": [{"id": k, "kind": "root", "active": True, "parents": []} for k in "abcd"],
            "claims": [{"id": "p", "supports": [[k] for k in "abcd"]}],
            "decisions": [{"id": "d1", "requires": ["p"]}]}


def fixed_point_decisions(candidate, withdrawn):
    """Separate synchronous Boolean evaluator, with no core evaluation call."""
    rows = [row for kind in ("evidence", "claims", "decisions") for row in candidate[kind]]
    state = {row["id"]: False for row in rows}
    withdrawn = set(withdrawn)
    for _ in range(len(rows) + 1):
        new = {}
        for row in candidate["evidence"]:
            new[row["id"]] = bool(row.get("active", True) and row["id"] not in withdrawn
                                  and (row.get("kind", "root") == "root" or all(state[p] for p in row["parents"])))
        for row in candidate["claims"]:
            new[row["id"]] = any(all(state[p] for p in clause) for clause in row["supports"])
        for row in candidate["decisions"]:
            new[row["id"]] = all(state[p] for p in row["requires"])
        if new == state:
            return {row["id"]: state[row["id"]] for row in candidate["decisions"]}
        state = new
    raise AssertionError("Acyclic fixture failed to converge")


class InterventionAuditTests(unittest.TestCase):
    def test_three_withdrawals_needed_despite_pairwise_agreement(self):
        a = graph()
        b = copy.deepcopy(a)
        b["claims"][0]["supports"] = [[k] for k in "abc"]
        result = audit_interventions({"four_routes": a, "missing_route": b})
        decision = result["decisions"]["d1"]
        self.assertEqual(decision["current_outcomes"], {"four_routes": True, "missing_route": True})
        self.assertEqual(decision["disagreement_state_count"], 1)
        self.assertEqual(decision["minimum_withdrawal_witness"]["withdraw"], list("abc"))
        self.assertEqual(result["states_checked_per_candidate"], 16)

    def test_no_restoration_of_initially_inactive_source(self):
        a = graph(); a["evidence"][3]["active"] = False
        b = copy.deepcopy(a); b["claims"][0]["supports"].pop()
        self.assertTrue(audit_interventions({"a": a, "b": b})["all_decisions_equivalent_within_scope"])

    def test_scope_is_explicit_and_bounds_fail_closed(self):
        a = graph(); b = copy.deepcopy(a); b["claims"][0]["supports"].pop()
        r = audit_interventions({"a": a, "b": b}, ["a", "b"])
        self.assertTrue(r["all_decisions_equivalent_within_scope"])
        self.assertEqual(r["fixed_evidence_ids"], ["c", "d"])
        with self.assertRaises(ValueError): audit_interventions({"a": a, "b": b}, ["missing"])
        with self.assertRaises(ValueError): audit_interventions({"a": a, "b": b}, ["a", "a"])
        a["evidence"] += [{"id": "r"+str(i)} for i in range(17)]
        with self.assertRaises(ValueError): audit_interventions({"a": a, "b": a})

    def test_bitsets_against_independent_per_state_core(self):
        rng = random.Random(9123)
        for _ in range(100):
            a = graph()
            a["evidence"] += [{"id": "copy", "kind": "copy", "active": rng.choice([True, False]), "parents": rng.sample(list("abcd"), 2)}]
            refs = list("abcd") + ["copy"]
            a["claims"][0]["supports"] = [rng.sample(refs, rng.randint(1, 3)) for _ in range(3)]
            b = copy.deepcopy(a); b["claims"][0]["supports"] = [rng.sample(refs, rng.randint(1, 3)) for _ in range(2)]
            result = audit_interventions({"a": a, "b": b})
            disagreements = []
            for n in range(len(refs)+1):
                for revoked in itertools.combinations(refs, n):
                    left = analyze(a, list(revoked))["decisions"]["d1"]["usable"]
                    right = analyze(b, list(revoked))["decisions"]["d1"]["usable"]
                    if left != right: disagreements.append(revoked)
            row = result["decisions"]["d1"]
            self.assertEqual(row["disagreement_state_count"], len(disagreements))
            self.assertEqual(row["equivalent_within_scope"], not disagreements)
            if disagreements:
                self.assertEqual(len(row["minimum_withdrawal_witness"]["withdraw"]), min(map(len, disagreements)))

    def test_zero_variable_scope_and_current_disagreement_have_empty_witness(self):
        a = graph()
        b = copy.deepcopy(a)
        b["claims"][0]["supports"] = []
        result = audit_interventions({"supported": a, "unsupported": b}, [])
        self.assertEqual(result["states_checked_per_candidate"], 1)
        self.assertEqual(result["allowed_withdrawals"], [])
        self.assertEqual(result["fixed_evidence_ids"], list("abcd"))
        self.assertEqual(result["decisions"]["d1"]["minimum_withdrawal_witness"],
                         {"withdraw": [], "outcomes": {"supported": True, "unsupported": False}})
        self.assertEqual(result["decisions"]["d1"]["disagreement_state_count"], 1)

    def test_minimum_witness_is_stable_under_candidate_variable_and_record_order(self):
        a = graph(); a["claims"][0]["supports"] = [["a"], ["b"]]
        b = graph(); b["claims"][0]["supports"] = [["a", "b"]]
        original = copy.deepcopy({"or": a, "and": b})
        left = audit_interventions(original, list("dcba"))
        reordered = copy.deepcopy({"and": b, "or": a})
        for candidate in reordered.values():
            for rows in candidate.values():
                rows.reverse()
        right = audit_interventions(reordered, list("abcd"))
        self.assertEqual(left["decisions"]["d1"], right["decisions"]["d1"])
        self.assertEqual(left["decisions"]["d1"]["minimum_withdrawal_witness"]["withdraw"], ["a"])
        self.assertEqual(original, {"or": a, "and": b})

    def test_multi_candidate_and_multi_decision_counts_match_fixed_point_enumeration(self):
        rng = random.Random(2026111409)
        for trial in range(60):
            initial = {"evidence": [{"id": name, "kind": "root", "active": rng.choice([True, True, False]), "parents": []} for name in "abc"],
                       "claims": [], "decisions": []}
            initial["evidence"] += [{"id": "copy", "kind": "copy", "active": True, "parents": rng.sample(list("abc"), 2)},
                                    {"id": "copy2", "kind": "copy", "active": rng.choice([True, False]), "parents": ["copy", "b"]}]
            previous = list("abc") + ["copy", "copy2"]
            for number in range(3):
                initial["claims"].append({"id": "p" + str(number),
                                          "supports": [rng.sample(previous, rng.randint(1, min(3, len(previous)))) for _ in range(rng.randint(0, 3))]})
                previous.append("p" + str(number))
            initial["decisions"] = [{"id": "d1", "requires": ["p0"]}, {"id": "d2", "requires": ["p1", "p2"]}]
            second = copy.deepcopy(initial); second["claims"][1]["supports"] = [["p0", "a"], ["b"]]
            third = copy.deepcopy(initial); third["evidence"][3]["parents"] = ["c"]
            candidates = {"first": initial, "second": second, "third": third}
            variables = sorted(row["id"] for row in initial["evidence"])
            if trial % 2:
                variables = variables[:3]
            result = audit_interventions(candidates, variables)
            for decision in ("d1", "d2"):
                disagreements = []
                for size in range(len(variables) + 1):
                    for withdrawn in itertools.combinations(variables, size):
                        outcomes = {name: fixed_point_decisions(candidate, withdrawn)[decision] for name, candidate in candidates.items()}
                        if len(set(outcomes.values())) > 1:
                            disagreements.append((list(withdrawn), outcomes))
                observed = result["decisions"][decision]
                self.assertEqual(observed["disagreement_state_count"], len(disagreements))
                self.assertEqual(observed["equivalent_within_scope"], not disagreements)
                expected_witness = {"withdraw": disagreements[0][0], "outcomes": disagreements[0][1]} if disagreements else None
                self.assertEqual(observed["minimum_withdrawal_witness"], expected_witness)

    def test_graph_metadata_revocation_is_not_an_unstated_initial_intervention(self):
        a = graph()
        a["revoke"] = list("abcd")
        b = graph()
        with self.assertRaisesRegex(ValueError, "current active flags"):
            audit_interventions({"with_metadata": a, "without_metadata": b})

    def test_empty_decision_set_reports_only_vacuous_scoped_equivalence(self):
        empty = {"evidence": [], "claims": [], "decisions": []}
        result = audit_interventions({"empty1": empty, "empty2": empty})
        self.assertEqual(result["states_checked_per_candidate"], 1)
        self.assertEqual(result["decisions"], {})
        self.assertTrue(result["all_decisions_equivalent_within_scope"])

    def test_sixteen_variable_boundary_and_candidate_registry_guards(self):
        a = graph()
        a["evidence"] += [{"id": "extra" + str(i), "kind": "root", "active": True, "parents": []} for i in range(12)]
        result = audit_interventions({"one": a, "two": copy.deepcopy(a)})
        self.assertEqual(result["states_checked_per_candidate"], 65536)
        self.assertTrue(result["all_decisions_equivalent_within_scope"])
        with self.assertRaises(ValueError): audit_interventions({"only": a})
        with self.assertRaises(ValueError): audit_interventions({str(i): a for i in range(17)})
        with self.assertRaises(ValueError): audit_interventions({"": a, "valid": a})
        wrong_registry = copy.deepcopy(a); wrong_registry["claims"][0]["id"] = "different"
        wrong_registry["decisions"][0]["requires"] = ["different"]
        with self.assertRaises(ValueError): audit_interventions({"original": a, "changed": wrong_registry})
        oversized = graph()
        oversized["evidence"] += [{"id": "large" + str(i), "kind": "root", "active": True, "parents": []} for i in range(245)]
        with self.assertRaises(ValueError): audit_interventions({"one": oversized, "two": oversized}, [])


if __name__ == "__main__": unittest.main()
