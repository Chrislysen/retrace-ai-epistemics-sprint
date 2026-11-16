import copy
import itertools
import random
import unittest

from retrace.coverage_v4 import ASSUMPTION, WARNING_LABEL, analyze_root_coverage


def graph(routes, active=None, copies=None):
    active = active or {name: True for route in routes for name in route}
    copies = copies or {}
    return {
        "evidence": [{"id": name, "kind": "root", "active": value, "parents": []} for name, value in active.items()]
                    + [{"id": name, "kind": "copy", "active": True, "parents": parents} for name, parents in copies.items()],
        "claims": [{"id": "p", "supports": routes}],
        "decisions": [{"id": "d", "label": "Release", "requires": ["p"]}],
    }


def candidates(*graphs):
    return [{"id": f"candidate-{i}", "graph": g} for i, g in enumerate(graphs)]


def scalar(graph, withdrawn=()):
    """Separate synchronous fixed point plus successful-route root propagation."""
    values = {row["id"]: False for kind in ("evidence", "claims", "decisions") for row in graph[kind]}
    roots = {name: set() for name in values}
    for _ in range(len(values) + 2):
        after, sources = {}, {}
        for row in graph["evidence"]:
            name = row["id"]
            active = row.get("active", True) and name not in withdrawn
            if row.get("kind", "root") == "root":
                after[name] = active
                sources[name] = {name} if active else set()
            else:
                after[name] = active and all(values[parent] for parent in row["parents"])
                sources[name] = set().union(*(roots[parent] for parent in row["parents"])) if after[name] else set()
        for kind, key in (("claims", "supports"), ("decisions", "requires")):
            for row in graph[kind]:
                clauses = row[key] if kind == "claims" else [row[key]]
                valid = [route for route in clauses if all(values[ref] for ref in route)]
                after[row["id"]] = bool(valid)
                sources[row["id"]] = {root for route in valid for ref in route for root in roots[ref]}
        if after == values and sources == roots:
            return after, sources
        values, roots = after, sources
    raise AssertionError("Synchronous reference did not converge")


class RootCoverageTests(unittest.TestCase):
    def test_two_alternative_roots_have_joint_only_failure(self):
        g = graph([["a"], ["b"]])
        result = analyze_root_coverage(candidates(g))
        self.assertTrue(result["warning"])
        self.assertEqual(result["warning_label"], WARNING_LABEL)
        self.assertFalse(result["merge_only_changes_current_support"])
        self.assertEqual(result["assumption"], ASSUMPTION)
        decision = result["decisions"]["d"]
        witness = decision["witnesses"][0]
        self.assertEqual(witness["roots"], ["a", "b"])
        self.assertEqual(witness["single_withdrawal_support"], {"a": True, "b": True})
        self.assertTrue(witness["original_support"])
        self.assertFalse(witness["joint_withdrawal_support"])
        self.assertTrue(witness["pair_only_failure"])
        self.assertEqual(decision["pair_counts"]["joint_only_failure_candidate_pairs"], 1)

    def test_and_roots_warn_without_claiming_single_failure_protection(self):
        result = analyze_root_coverage(candidates(graph([["a", "b"]])))
        witness = result["decisions"]["d"]["witnesses"][0]
        self.assertEqual(witness["single_withdrawal_support"], {"a": False, "b": False})
        self.assertTrue(witness["single_failure_already_present"])
        self.assertFalse(witness["pair_only_failure"])
        self.assertEqual(result["decisions"]["d"]["pair_counts"]["single_failure_already_present_candidate_pairs"], 1)

    def test_three_alternatives_are_safe_only_within_the_pair_scope(self):
        result = analyze_root_coverage(candidates(graph([["a"], ["b"], ["c"]])))
        self.assertFalse(result["warning"])
        self.assertIsNone(result["warning_label"])
        self.assertEqual(result["decisions"]["d"]["pair_counts"]["tested_candidate_pairs"], 3)
        self.assertEqual(result["decisions"]["d"]["pair_counts"]["nonbreaking_candidate_pairs"], 3)
        self.assertEqual(result["coverage"]["higher_order_common_causes"], "not tested")
        self.assertEqual(result["coverage"]["candidate_completeness"], "unknown")

    def test_copies_and_failed_route_roots_are_not_independent_sources(self):
        g = graph([["x"], ["y"], ["b", "off"]], {"a": True, "b": True, "off": False}, {"x": ["a"], "y": ["a"]})
        result = analyze_root_coverage(candidates(g))
        self.assertFalse(result["warning"])
        self.assertEqual(result["decisions"]["d"]["currently_supporting_root_ids"], {"candidate-0": ["a"]})
        self.assertEqual(result["coverage"]["eligible_decision_candidate_pairs"], 0)

    def test_inactive_copy_hides_its_otherwise_available_parent(self):
        g = graph([["x"], ["b"]], {"a": True, "b": True}, {"x": ["a"]})
        g["evidence"][-1]["active"] = False
        result = analyze_root_coverage(candidates(g))
        self.assertEqual(result["decisions"]["d"]["currently_supporting_root_ids"]["candidate-0"], ["b"])
        self.assertFalse(result["warning"])

    def test_not_unanimously_supported_is_inapplicable_not_a_negative_proof(self):
        a = graph([["a"], ["b"]])
        b = copy.deepcopy(a)
        for row in b["evidence"]:
            row["active"] = False
        result = analyze_root_coverage(candidates(a, b))
        self.assertFalse(result["decisions"]["d"]["applicable"])
        self.assertEqual(result["decisions"]["d"]["current_outcomes"], {"candidate-0": True, "candidate-1": False})
        self.assertEqual(result["coverage"]["applicable_decision_count"], 0)
        self.assertEqual(result["coverage"]["basis_state_count"], 1)

    def test_candidate_scoped_attestation_exempts_only_its_pair(self):
        a = graph([["a"], ["b"]])
        declaration = [{"roots": ["b", "a"], "basis": "Separate source production records.", "candidate_ids": ["candidate-0"]}]
        result = analyze_root_coverage(candidates(a, copy.deepcopy(a)), declaration)
        counts = result["decisions"]["d"]["pair_counts"]
        self.assertEqual(counts["eligible_candidate_pairs"], 2)
        self.assertEqual(counts["attested_candidate_pairs"], 1)
        self.assertEqual(counts["tested_candidate_pairs"], 1)
        self.assertEqual(result["decisions"]["d"]["witnesses"][0]["candidate_id"], "candidate-1")
        all_candidates = [{"roots": ["a", "b"], "basis": "Two independently observed source records."}]
        self.assertFalse(analyze_root_coverage(candidates(a, a), all_candidates)["warning"])

    def test_disjoint_attestations_allowed_but_overlaps_conflicts_rejected(self):
        rows = candidates(graph([["a"], ["b"]]), graph([["a"], ["b"]]))
        first = {"roots": ["a", "b"], "basis": "First record.", "candidate_ids": ["candidate-0"]}
        second = {"roots": ["b", "a"], "basis": "Other record.", "candidate_ids": ["candidate-1"]}
        self.assertFalse(analyze_root_coverage(rows, [first, second])["warning"])
        for duplicate in (first, {**first, "basis": "Conflicting basis."}, {"roots": ["b", "a"], "basis": "All candidates."}):
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, "Repeated or conflicting"):
                analyze_root_coverage(rows, [first, duplicate])

    def test_attestation_validation_is_strict(self):
        rows = candidates(graph([["a"], ["b"], ["x"]], {"a": True, "b": True}, {"x": ["a"]}))
        invalid = [None, {}, {"roots": ["a", "a"], "basis": "record"}, {"roots": ["a", "b", "x"], "basis": "record"},
                   {"roots": ["a", "b"], "basis": " "}, {"roots": ["a", "missing"], "basis": "record"},
                   {"roots": ["a", "x"], "basis": "record"}, {"roots": ["a", "b"], "basis": "record", "candidate_ids": []},
                   {"roots": ["a", "b"], "basis": "record", "candidate_ids": ["unknown"]},
                   {"roots": ["a", "b"], "basis": "record", "candidate_ids": ["candidate-0", "candidate-0"]},
                   {"roots": ["a", "b"], "basis": "record", "verified": True}]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                analyze_root_coverage(rows, [item])
        with self.assertRaises(ValueError):
            analyze_root_coverage(rows, {"roots": ["a", "b"], "basis": "record"})

    def test_candidate_root_kind_variation_and_attestation_scope(self):
        a = graph([["a"], ["b"], ["c"]])
        b = copy.deepcopy(a)
        b["evidence"][1].update(kind="copy", parents=["a"])
        result = analyze_root_coverage(candidates(a, b))
        self.assertTrue(result["warning"])
        self.assertEqual(result["decisions"]["d"]["witnesses"][0]["roots"], ["a", "c"])
        with self.assertRaisesRegex(ValueError, "root evidence"):
            analyze_root_coverage(candidates(a, b), [{"roots": ["a", "b"], "basis": "Record."}])
        analyze_root_coverage(candidates(a, b), [{"roots": ["a", "b"], "basis": "Record.", "candidate_ids": ["candidate-0"]}])

    def test_witnesses_include_joint_only_example_when_first_pair_already_fails_singly(self):
        g = graph([["a", "b"], ["a", "c"]])
        result = analyze_root_coverage(candidates(g))
        witnesses = result["decisions"]["d"]["witnesses"]
        self.assertEqual(witnesses[0]["roots"], ["a", "b"])
        self.assertFalse(witnesses[0]["pair_only_failure"])
        self.assertEqual(witnesses[1]["roots"], ["b", "c"])
        self.assertTrue(witnesses[1]["pair_only_failure"])
        self.assertEqual(result["decisions"]["d"]["pair_counts"]["joint_failure_candidate_pairs"], 3)

    def test_inputs_remain_unchanged_and_order_is_deterministic(self):
        rows = candidates(graph([["b"], ["a"]]), graph([["a", "b"]]))
        attestations = [{"roots": ["b", "a"], "basis": " Source record. ", "candidate_ids": ["candidate-1"]}]
        original = copy.deepcopy((rows, attestations))
        result = analyze_root_coverage(rows, attestations)
        self.assertEqual((rows, attestations), original)
        reversed_rows = copy.deepcopy(rows[::-1])
        for row in reversed_rows:
            for kind in ("evidence", "claims", "decisions"):
                row["graph"][kind].reverse()
        self.assertEqual(result, analyze_root_coverage(reversed_rows, attestations))

    def test_graph_admission_bounds_cycles_duplicates_and_metadata(self):
        good = candidates(graph([["a"], ["b"]]))
        for bad in ([], None, good * 17, [good[0], good[0]], [{"id": "x", "graph": {}}]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                analyze_root_coverage(bad)
        bad_graphs = []
        duplicate = copy.deepcopy(good[0]["graph"]); duplicate["evidence"].append(copy.deepcopy(duplicate["evidence"][0])); bad_graphs.append(duplicate)
        cycle = copy.deepcopy(good[0]["graph"]); cycle["claims"][0]["supports"] = [["p"]]; bad_graphs.append(cycle)
        missing = copy.deepcopy(good[0]["graph"]); missing["claims"][0]["supports"] = [["unknown"]]; bad_graphs.append(missing)
        revoke = copy.deepcopy(good[0]["graph"]); revoke["revoke"] = ["a"]; bad_graphs.append(revoke)
        large = graph([["r0"]], {f"r{i}": True for i in range(249)}); bad_graphs.append(large)
        for g in bad_graphs:
            with self.subTest(g=g), self.assertRaises(ValueError):
                analyze_root_coverage(candidates(g))
        mismatch = graph([["a"], ["c"]])
        with self.assertRaisesRegex(ValueError, "same IDs"):
            analyze_root_coverage([good[0], {"id": "other", "graph": mismatch}])

    def test_empty_graph_and_zero_or_one_supporting_root(self):
        self.assertFalse(analyze_root_coverage(candidates({"evidence": [], "claims": [], "decisions": []}))["warning"])
        self.assertFalse(analyze_root_coverage(candidates(graph([["a"]])))["warning"])
        self.assertFalse(analyze_root_coverage(candidates(graph([], {"a": True})))["decisions"]["d"]["applicable"])

    def test_available_common_ancestor_preserves_all_positive_dag_outputs(self):
        # Constructive induction check, distinct from the hypothetical withdrawal.
        rng = random.Random(2026111401)
        for _ in range(150):
            g = graph([["a"], ["b", "c"]], {"a": True, "b": True, "c": bool(rng.getrandbits(1))})
            g["evidence"].append({"id": "x", "kind": "copy", "active": bool(rng.getrandbits(1)), "parents": ["a", "b"]})
            g["claims"][0]["supports"] = [rng.sample(["a", "b", "c", "x"], rng.randint(1, 3)) for _ in range(3)]
            g["claims"].append({"id": "q", "supports": [["p", "b"], ["c"]]})
            g["decisions"].append({"id": "e", "requires": ["p", "q"]})
            changed = copy.deepcopy(g)
            changed["evidence"].append({"id": "hypothetical_common", "kind": "root", "active": True, "parents": []})
            for row in changed["evidence"]:
                if row["id"] in ("a", "b"):
                    row.update(kind="copy", parents=["hypothetical_common"])
            original, _ = scalar(g)
            merged, _ = scalar(changed)
            self.assertEqual(original, {name: merged[name] for name in original})
            withdrawn, _ = scalar(g, {"a", "b"})
            common_lost, _ = scalar(changed, {"hypothetical_common"})
            self.assertEqual(withdrawn, {name: common_lost[name] for name in withdrawn})

    def test_random_dags_match_exhaustive_scalar_pair_enumeration(self):
        rng = random.Random(2026111402)
        for trial in range(120):
            gs = []
            for _ in range(rng.randint(1, 4)):
                roots = {name: bool(rng.randrange(4)) for name in "abcfg"}
                g = graph([["a"]], roots, {"x": rng.sample(list(roots), rng.randint(1, 3))})
                g["claims"][0]["supports"] = [rng.sample(list(roots) + ["x"], rng.randint(1, 3)) for _ in range(rng.randint(0, 4))]
                g["claims"].append({"id": "q", "supports": [["p", "a"], ["g"]]})
                g["decisions"].append({"id": "e_decision", "requires": ["q"]})
                gs.append(g)
            result = analyze_root_coverage(candidates(*gs))
            baselines = [scalar(g) for g in gs]
            for did in ("d", "e_decision"):
                row = result["decisions"][did]
                applicable = all(values[did] for values, _ in baselines)
                self.assertEqual(row["applicable"], applicable)
                eligible = failed = joint_only = 0
                if applicable:
                    for g, (values, rootsets) in zip(gs, baselines):
                        for pair in itertools.combinations(sorted(rootsets[did]), 2):
                            eligible += 1
                            pair_fails = not scalar(g, pair)[0][did]
                            failed += pair_fails
                            joint_only += pair_fails and all(scalar(g, [root])[0][did] for root in pair)
                self.assertEqual(row["pair_counts"]["eligible_candidate_pairs"], eligible, trial)
                self.assertEqual(row["pair_counts"]["joint_failure_candidate_pairs"], failed, trial)
                self.assertEqual(row["pair_counts"]["joint_only_failure_candidate_pairs"], joint_only, trial)
                for witness in row["witnesses"]:
                    g = gs[int(witness["candidate_id"].split("-")[-1])]
                    self.assertEqual(witness["joint_withdrawal_support"], scalar(g, witness["roots"])[0][did])
                    self.assertEqual(witness["single_withdrawal_support"], {root: scalar(g, [root])[0][did] for root in witness["roots"]})

    def test_maximum_node_graph_is_exact_without_root_truncation(self):
        roots = {f"root-{i:03}": True for i in range(248)}
        g = graph([[name] for name in roots], roots)
        result = analyze_root_coverage(candidates(g))
        self.assertEqual(result["coverage"]["basis_state_count"], 1 + 248 + 248 * 247 // 2)
        self.assertEqual(result["coverage"]["eligible_decision_candidate_pairs"], 248 * 247 // 2)
        self.assertTrue(result["coverage"]["all_eligible_pairs_checked"])
        self.assertFalse(result["coverage"]["root_truncation"])
        self.assertFalse(result["warning"])


if __name__ == "__main__":
    unittest.main()
