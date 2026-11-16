"""Independent small-space fixed-point oracle; no use of RETRACE core evaluator."""
import copy
import itertools
import random
import unittest

from retrace.stress import analyze_stress


def oracle(graph, withdrawn):
    values = {r["id"]: False for group in ("evidence", "claims", "decisions") for r in graph[group]}
    for _ in range(len(values) + 1):
        updated = dict(values)
        for row in graph["evidence"]:
            updated[row["id"]] = (row["active"] and row["id"] not in withdrawn
                                  and (row["kind"] == "root" or all(values[p] for p in row["parents"])))
        for row in graph["claims"]:
            updated[row["id"]] = any(all(values[p] for p in clause) for clause in row["supports"])
        for row in graph["decisions"]:
            updated[row["id"]] = all(values[p] for p in row["requires"])
        if updated == values:
            break
        values = updated
    else:
        raise AssertionError("fixed-point oracle failed to converge")
    return {r["id"]: values[r["id"]] for r in graph["decisions"]}


class StressOracleTests(unittest.TestCase):
    def test_random_candidates_all_states_minimality_and_no_mutation(self):
        rng = random.Random(2026111303)
        for case in range(60):
            ids = [f"e{i}" for i in range(5)]
            candidates = []
            for index in range(3):
                evidence = []
                for i, name in enumerate(ids):
                    parents = rng.sample(ids[:i], rng.randrange(1, min(i, 2) + 1)) if i and rng.random() < .4 else []
                    evidence.append({"id": name, "kind": "copy" if parents else "root",
                                     "active": rng.random() > .1, "parents": parents})
                claims = []
                for i in range(2):
                    pool = ids + (["c0"] if i else [])
                    clauses = [rng.sample(pool, rng.randint(1, 2)) for _ in range(rng.randint(0, 4))]
                    claims.append({"id": f"c{i}", "supports": clauses})
                candidates.append({"id": f"g{index}", "graph": {"evidence": evidence, "claims": claims,
                                   "decisions": [{"id": "d0", "requires": ["c0"]}, {"id": "d1", "requires": ["c1"]}]}})
            item = {"id": str(case), "candidates": candidates, "questions": [], "allowed_withdrawals": ids}
            prior = copy.deepcopy(item)
            state = {"revoked_passages": ["e4"]} if case % 2 else {}
            fixed = set(state.get("revoked_passages", []))
            result = analyze_stress(item, state)
            self.assertEqual(item, prior)
            expected = {c["id"]: oracle(c["graph"], fixed) for c in candidates}
            self.assertEqual(result["consensus"]["candidate_decision_vectors"], expected)
            subsets = [set(combo) for k in range(6) for combo in itertools.combinations(ids, k)]
            for decision in ["d0", "d1"]:
                current = [v[decision] for v in expected.values()]
                disagreements, any_break, all_break = [], [], []
                for subset in subsets:
                    vector = [oracle(c["graph"], fixed | subset)[decision] for c in candidates]
                    if len(set(vector)) > 1:
                        disagreements.append(subset)
                    if all(current) and not all(vector):
                        any_break.append(subset)
                    if all(current) and not any(vector):
                        all_break.append(subset)
                row = result["decision_witnesses"][decision]
                for field, possibilities in [("minimum_distinguishing", disagreements),
                                             ("minimum_break_any", any_break), ("minimum_break_all", all_break)]:
                    actual = row[field]
                    if not possibilities:
                        self.assertIsNone(actual, (case, decision, field))
                    else:
                        self.assertEqual(actual["k"], len(possibilities[0]), (case, decision, field))
                        self.assertEqual(set(actual["withdraw"]), possibilities[0])
                        for candidate in candidates:
                            self.assertEqual(actual["outcomes"][candidate["id"]],
                                             oracle(candidate["graph"], fixed | set(actual["withdraw"]))[decision])


if __name__ == "__main__":
    unittest.main()
