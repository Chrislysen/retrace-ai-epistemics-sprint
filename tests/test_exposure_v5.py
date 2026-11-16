import copy
import itertools
import math
import random
import unittest

from retrace.exposure_v5 import audit_exposure


def graph(flags, routes, copies=None):
    copies = copies or {}
    return {"evidence": [{"id": eid, "kind": "copy" if eid in copies else "root",
                           "active": active, "parents": copies.get(eid, [])} for eid, active in flags.items()],
            "claims": [{"id": "claim", "supports": routes}],
            "decisions": [{"id": "decision", "label": "Release", "requires": ["claim"]}]}


def candidates(*graphs):
    return [{"id": f"candidate-{i}", "graph": g} for i, g in enumerate(graphs)]


def scalar_fixed_point(g, flags):
    """Independent synchronous iteration; no production support helpers."""
    values = {r["id"]: False for category in ("evidence", "claims", "decisions") for r in g[category]}
    for _ in range(len(values) + 2):
        after = {}
        for r in g["evidence"]:
            after[r["id"]] = flags[r["id"]] and (
                r.get("kind", "root") == "root" or all(values[p] for p in r["parents"]))
        for r in g["claims"]:
            after[r["id"]] = any(all(values[p] for p in route) for route in r["supports"])
        for r in g["decisions"]:
            after[r["id"]] = all(values[p] for p in r["requires"])
        if values == after:
            return {r["id"]: after[r["id"]] for r in g["decisions"]}
        values = after
    raise AssertionError("Independent finite fixed point failed to converge")


class ExposureTests(unittest.TestCase):
    def test_masked_gate_needs_enable_and_one_withdrawal(self):
        flags = {"gate": False, "a": True, "b": True, "x": True, "y": True}
        copies = {"x": ["gate", "a"], "y": ["gate", "b"]}
        result = audit_exposure(candidates(graph(flags, [["x"], ["y"]], copies),
                                           graph(flags, [["x", "y"]], copies)))
        d = result["decisions"]["decision"]
        self.assertEqual(d["current_outcomes"], {"candidate-0": False, "candidate-1": False})
        self.assertIsNone(d["minimum_without_enabling"])
        self.assertEqual([(p["enable_count"], p["withdraw_count"], p["state_count"]) for p in d["frontier"]], [(1, 1, 4)])
        self.assertEqual(d["minimum"]["enable"], ["gate"])
        self.assertEqual(d["minimum"]["total_changes"], 2)
        self.assertEqual(d["minimum"]["outcomes"], {"candidate-0": True, "candidate-1": False})
        self.assertEqual(d["distinguishing_state_count"], 6)
        self.assertEqual(d["total_change_histogram"][:2], [0, 0])
        self.assertEqual(d["minimality"]["states_with_fewer_changes"], 6)

    def test_passage_loss_exposes_same_original_grouping(self):
        flags = {"a": True, "x": True, "y": True, "z": True}
        copies = {"x": ["a"], "y": ["a"]}
        ref, alt = graph(flags, [["x"], ["y"]], copies), graph(flags, [["x", "y"]], copies)
        for g, second_routes in ((ref, [["x"], ["y"], ["z"]]), (alt, [["x", "y"], ["z"]])):
            g["claims"].append({"id": "second", "supports": second_routes})
            g["decisions"].append({"id": "backup", "requires": ["second"]})
        rows = candidates(ref, alt)
        result = audit_exposure(rows)
        self.assertEqual(result["decisions"]["decision"]["minimum_without_enabling"]["withdraw_count"], 1)
        self.assertEqual(result["decisions"]["backup"]["minimum_without_enabling"]["withdraw_count"], 2)
        self.assertEqual(result["decisions"]["decision"]["distinguishing_state_count"], 4)
        self.assertEqual(result["decisions"]["backup"]["distinguishing_state_count"], 2)
        roots_only = audit_exposure(rows, allowed_changes=["a", "z"])
        self.assertTrue(all(not d["exposure_exists"] for d in roots_only["decisions"].values()))

    def test_inactive_copy_enable_does_not_bypass_inactive_parent(self):
        flags = {"a": False, "b": True, "x": False}
        ref = graph(flags, [["x"]], {"x": ["a"]})
        alt = graph(flags, [], {"x": ["a"]})
        result = audit_exposure(candidates(ref, alt))
        w = result["decisions"]["decision"]["minimum"]
        self.assertEqual(w["enable"], ["a", "x"])
        self.assertEqual(w["withdraw"], [])
        restricted = audit_exposure(candidates(ref, alt), allowed_changes=["x"])
        self.assertFalse(restricted["decisions"]["decision"]["exposure_exists"])

    def test_locked_exclusion_cannot_be_enabled_or_cleared(self):
        flags = {"gate": False, "a": True, "b": True}
        ref = graph(flags, [["gate", "a"], ["gate", "b"]])
        alt = graph(flags, [["gate", "a", "b"]])
        result = audit_exposure(candidates(ref, alt), locked_exclusions=["gate"])
        self.assertFalse(result["decisions"]["decision"]["exposure_exists"])
        self.assertEqual(result["coverage"]["allowed_but_locked_ids"], ["gate"])
        self.assertEqual(result["coverage"]["states_checked_per_candidate"], 4)
        flags["gate"] = True
        result = audit_exposure(candidates(graph(flags, [["gate"]]), graph(flags, [])), locked_exclusions=["gate"])
        self.assertFalse(result["decisions"]["decision"]["exposure_exists"])

    def test_disagreement_at_baseline_has_zero_change_witness(self):
        result = audit_exposure(candidates(graph({"a": True}, [["a"]]), graph({"a": True}, [])))
        d = result["decisions"]["decision"]
        self.assertEqual(d["minimum"]["total_changes"], 0)
        self.assertEqual(d["minimum_without_enabling"]["total_changes"], 0)
        self.assertEqual([(p["enable_count"], p["withdraw_count"]) for p in d["frontier"]], [(0, 0)])

    def test_pareto_frontier_preserves_enabling_withdrawal_tradeoff(self):
        flags = {"gate": False, "u": False, "a": True, "b": True, "c": True, "d": True}
        ref = graph(flags, [["gate", "a", "b", "c"], ["gate", "a", "b", "d"],
                            ["gate", "a", "c", "d"], ["gate", "u"]])
        alt = graph(flags, [["gate", "a", "b"], ["gate", "a", "c"], ["gate", "a", "d"]])
        result = audit_exposure(candidates(ref, alt))
        d = result["decisions"]["decision"]
        self.assertEqual([(p["enable_count"], p["withdraw_count"]) for p in d["frontier"]], [(1, 2), (2, 1)])
        self.assertEqual(d["minimum"]["total_changes"], 3)
        self.assertEqual(d["minimum"]["enable_count"], 1)
        self.assertIsNone(d["minimum_without_enabling"])

    def test_inputs_immutable_fingerprint_bound_and_order_stable(self):
        rows = candidates(graph({"a": True, "b": False}, [["a"], ["b"]]),
                          graph({"a": True, "b": False}, [["a", "b"]]))
        saved = copy.deepcopy(rows)
        first = audit_exposure(rows)
        self.assertEqual(rows, saved)
        permuted = copy.deepcopy(rows[::-1])
        for row in permuted:
            row["graph"]["evidence"].reverse()
            row["graph"]["claims"][0]["supports"].reverse()
        self.assertEqual(first, audit_exposure(permuted, allowed_changes=["b", "a"]))
        for kwargs in ({"allowed_changes": ["a"]}, {"locked_exclusions": ["b"]}, {"target_decisions": []}):
            self.assertNotEqual(first["input_fingerprint"], audit_exposure(rows, **kwargs)["input_fingerprint"])
        for row in rows:
            row["graph"]["evidence"][0]["active"] = False
        self.assertNotEqual(first["input_fingerprint"], audit_exposure(rows)["input_fingerprint"])

    def test_single_candidate_empty_scope_and_core_defaults(self):
        g = {"evidence": [{"id": "a"}], "claims": [{"id": "c", "supports": [["a"]]}],
             "decisions": [{"id": "d", "requires": ["c"]}]}
        r = audit_exposure(candidates(g), allowed_changes=[])
        self.assertEqual(r["coverage"]["states_checked_per_candidate"], 1)
        self.assertFalse(r["decisions"]["d"]["exposure_exists"])
        self.assertTrue(r["baseline_outcomes"]["candidate-0"]["d"])
        self.assertEqual(audit_exposure(candidates(g), target_decisions=[])["decisions"], {})
        empty = {"evidence": [], "claims": [], "decisions": []}
        self.assertEqual(audit_exposure(candidates(empty))["coverage"]["states_checked_per_candidate"], 1)

    def test_invalid_contracts_reject(self):
        g = graph({"a": True, "b": True}, [["a"]])
        rows = candidates(g, copy.deepcopy(g))
        cases = [([], {}), (rows * 9, {}), ([rows[0], rows[0]], {}),
                 (rows, {"allowed_changes": ["a", "a"]}),
                 (rows, {"allowed_changes": ["missing"]}),
                 (rows, {"allowed_changes": ["claim"]}),
                 (rows, {"locked_exclusions": ["a", "a"]}),
                 (rows, {"locked_exclusions": ["missing"]}),
                 (rows, {"locked_exclusions": "a"}),
                 (rows, {"target_decisions": ["a"]}),
                 (rows, {"target_decisions": ["decision", "decision"]})]
        for arguments, kwargs in cases:
            with self.subTest(kwargs=kwargs, count=len(arguments)), self.assertRaises(ValueError):
                audit_exposure(arguments, **kwargs)
        for mutation in ("flags", "typed", "cycle", "revoke", "active_type"):
            bad = copy.deepcopy(rows)
            if mutation == "flags":
                bad[1]["graph"]["evidence"][0]["active"] = False
            elif mutation == "typed":
                bad[1]["graph"]["evidence"][1]["id"] = "other"
            elif mutation == "cycle":
                bad[1]["graph"]["evidence"][0].update(kind="copy", parents=["a"])
            elif mutation == "revoke":
                bad[1]["graph"]["revoke"] = ["a"]
            else:
                bad[1]["graph"]["evidence"][0]["active"] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit_exposure(bad)

    def test_bounds_and_exact_sixteen_variable_enumeration(self):
        flags = {f"e{i:02}": True for i in range(17)}
        ref, alt = graph(flags, [[e] for e in flags if e != "e16"]), graph(flags, [[e for e in flags if e != "e16"]])
        with self.assertRaisesRegex(ValueError, "At most 16"):
            audit_exposure(candidates(ref, alt))
        result = audit_exposure(candidates(ref, alt), locked_exclusions=["e16"])
        self.assertEqual(result["coverage"]["states_checked_per_candidate"], 65536)
        d = result["decisions"]["decision"]
        self.assertEqual(d["distinguishing_state_count"], 65534)
        self.assertEqual(d["total_change_histogram"], [0] + [math.comb(16, k) for k in range(1, 16)] + [0])
        too_large = graph({f"e{i}": True for i in range(249)}, [["e0"]])
        with self.assertRaisesRegex(ValueError, "250"):
            audit_exposure(candidates(too_large), allowed_changes=[])

    def test_random_dags_match_independent_scalar_every_state_and_frontier(self):
        rng = random.Random(53501)
        for iteration in range(200):
            names = [f"e{i}" for i in range(rng.randint(1, 6))]
            initial = {n: rng.choice([False, True]) for n in names}
            rows = []
            for ci in range(rng.randint(1, 4)):
                evidence = []
                for i, eid in enumerate(names):
                    parents = rng.sample(names[:i], rng.randint(1, min(i, 2))) if i and rng.random() < .45 else []
                    evidence.append({"id": eid, "kind": "copy" if parents else "root", "active": initial[eid], "parents": parents})
                claims = []
                for j in range(3):
                    available = names + [c["id"] for c in claims]
                    routes = [rng.sample(available, rng.randint(1, min(3, len(available)))) for _ in range(rng.randint(0, 3))]
                    claims.append({"id": f"c{j}", "supports": routes})
                decisions = [{"id": f"d{j}", "requires": rng.sample([c["id"] for c in claims], rng.randint(1, 3))} for j in range(2)]
                rows.append({"id": f"candidate-{ci}", "graph": {"evidence": evidence, "claims": claims, "decisions": decisions}})
            allowed = rng.sample(names, rng.randint(0, len(names)))
            locked = rng.sample(names, rng.randint(0, len(names)))
            result = audit_exposure(rows, allowed, locked)
            variables = sorted(set(allowed) - set(locked))
            expected = {did: {} for did in ("d0", "d1")}
            totals = {did: [0] * (len(variables) + 1) for did in expected}
            for values in itertools.product([False, True], repeat=len(variables)):
                final = {eid: active and eid not in locked for eid, active in initial.items()}
                final.update(dict(zip(variables, values)))
                enable = [eid for eid in variables if final[eid] and not initial[eid]]
                withdraw = [eid for eid in variables if not final[eid] and initial[eid]]
                pair = (len(enable), len(withdraw))
                outputs = {r["id"]: scalar_fixed_point(r["graph"], final) for r in rows}
                for did in expected:
                    if len({v[did] for v in outputs.values()}) > 1:
                        expected[did][pair] = expected[did].get(pair, 0) + 1
                        totals[did][sum(pair)] += 1
            for did, counts in expected.items():
                actual = result["decisions"][did]
                self.assertEqual(actual["total_change_histogram"], totals[did], (iteration, did))
                self.assertEqual(actual["distinguishing_state_count"], sum(counts.values()))
                frontier = sorted(p for p in counts if not any(q != p and q[0] <= p[0] and q[1] <= p[1] for q in counts))
                self.assertEqual([(p["enable_count"], p["withdraw_count"]) for p in actual["frontier"]], frontier)
                self.assertEqual(actual["minimum"]["total_changes"] if actual["minimum"] else None,
                                 min(map(sum, counts)) if counts else None)
                for w in [actual["minimum"], actual["minimum_without_enabling"]] + [p["witness"] for p in actual["frontier"]]:
                    if w is None:
                        continue
                    final = {eid: active and eid not in locked for eid, active in initial.items()}
                    final.update({eid: True for eid in w["enable"]})
                    final.update({eid: False for eid in w["withdraw"]})
                    self.assertFalse(set(w["enable"]) & set(locked))
                    self.assertEqual(w["outcomes"], {r["id"]: scalar_fixed_point(r["graph"], final)[did] for r in rows})
                    self.assertEqual(len(set(w["outcomes"].values())), 2)


if __name__ == "__main__":
    unittest.main()
