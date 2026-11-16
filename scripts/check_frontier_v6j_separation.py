"""Offline illustrative separation certificates; not a model evaluation.

Checks explicit scalar formulas against the frozen engine. No corpus, gold
graphs, model answers, network access, or inference selection are used.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.impact_v6h import compare_families, withdrawal_robustness
from retrace.tiered_v6h import SCHEMA, family_supervaluation
from retrace.typed_interventions_v6h import restore_then_withdraw_impact
from retrace.workbench_v6h import minimax_clarification


def require(value, message):
    if not value:
        raise AssertionError(message)


def subsets(ids):
    for k in range(len(ids) + 1):
        yield from combinations(ids, k)


def graph(ids, positive):
    return {"schema": SCHEMA,
            "evidence": [{"id": x, "kind": "root", "active": True, "parents": []} for x in ids],
            "claims": [{"id": "C", "positive": positive, "negative": {"const": False}}],
            "decisions": [{"id": "D", "requires": ["C"]}]}


def state(g, withdrawals=(), document_vetoes=(), passage_vetoes=()):
    row = family_supervaluation([g], scenario_withdrawals=list(withdrawals),
                               document_vetoes=list(document_vetoes),
                               passage_vetoes=list(passage_vetoes))["decisions"]["D"]
    require(row["box_supported"] == row["diamond_supported"], "Singleton positive graph must agree")
    return row["box_supported"]


def plan(a, b):
    vectors = {"G": {"D": "supported" if a else "not_supported"},
               "H": {"D": "supported" if b else "not_supported"}}
    question = {"id": "reading", "label": "Does the declared reading use H's dependency structure?",
                "cost": 1, "answers": {"G": False, "H": True}}
    return minimax_clarification(vectors, [question])


def higher_order(k):
    routes = [f"R{i:02}" for i in range(1, k + 1)]
    ids = routes + ["Q"]
    current = graph(ids, {"ref": routes[0]} if k == 1 else {"any": [{"ref": x} for x in routes]})
    proposed = graph(ids, {"any": [{"ref": x} for x in ids]})
    mismatch = []; scalar_checks = 0; small_equal = 0
    for withdrawal in subsets(ids):
        w = set(withdrawal)
        a = any(x not in w for x in routes)
        b = a or "Q" not in w
        require((state(current, withdrawal), state(proposed, withdrawal)) == (a, b),
                "Engine/scalar disagreement in higher-order construction")
        scalar_checks += 2
        if len(w) < k:
            require(a == b, "A sub-k distinction exists")
            small_equal += 1
        if a != b:
            mismatch.append(list(withdrawal))
    require(mismatch == [routes], "Exact unique distinguishing withdrawal is all k routes")
    contrast = compare_families([current], [proposed])["decisions"][0]
    robust = withdrawal_robustness([current])["decisions"][0]
    require(contrast["minimum_k"] == robust["minimum_k"] == k, "Wrong minimum k")
    require(contrast["withdraw"] == robust["withdraw"] == routes, "Wrong witness")
    require(robust["survives_all_k1"] == (k > 1) and robust["survives_all_k2"] == (k > 2),
            "Wrong robustness boundary")
    initial_plan = plan(True, True)
    witness_plan = plan(False, True)
    require(initial_plan["worst_case_cost"] == 0 and initial_plan["next_question"] is None,
            "Initially irrelevant ambiguity should not cause a question")
    require(witness_plan["worst_case_cost"] == 1 and witness_plan["next_question"]["id"] == "reading",
            "Witness should make the declared question decision-relevant")
    return {"k": k, "evidence_ids": ids, "all_withdrawal_subsets_checked": 2 ** len(ids),
            "sub_k_subsets_agree": small_equal, "scalar_graph_state_comparisons": scalar_checks,
            "unique_distinguishing_withdrawal": routes, "engine_minimum_k": contrast["minimum_k"],
            "robustness": robust, "clarification_cost_before": 0, "clarification_cost_at_witness": 1}


def masked_prerequisite():
    current = graph(["P", "Q"], {"ref": "P"})
    proposed = graph(["P", "Q"], {"all": [{"ref": "P"}, {"ref": "Q"}]})
    originals = deepcopy((current, proposed))
    table = []; checks = 0
    # Exhaust the Cartesian product: one typed document-veto state x all
    # withdrawal subsets. Local flags stay true and no other veto is released.
    for release in (False, True):
        for withdrawal in subsets(["P", "Q"]):
            veto = () if release else ("P",)
            a = release and "P" not in withdrawal
            b = a and "Q" not in withdrawal
            require((state(current, withdrawal, veto), state(proposed, withdrawal, veto)) == (a, b),
                    "Engine/scalar disagreement in masked construction")
            checks += 2
            table.append({"release_document_P": release, "withdraw": list(withdrawal),
                          "G_supported": a, "H_supported": b, "different": a != b})
    require(not any(r["different"] for r in table if not r["release_document_P"]),
            "Pure withdrawal must be observationally silent at every order")
    differing = [r for r in table if r["different"]]
    require(differing == [{"release_document_P": True, "withdraw": ["Q"],
                          "G_supported": True, "H_supported": False, "different": True}],
            "Wrong typed distinction")
    release = restore_then_withdraw_impact([current], [proposed],
        document_groups=[{"id": "paper_P", "evidence_ids": ["P"]}], revoked_documents=["paper_P"])
    require(len(release["witnesses"]) == 1, "Exact single typed pair required")
    witness = release["witnesses"][0]
    require(witness["release"] == {"kind": "document", "id": "paper_P"}
            and witness["withdraw"] == "Q" and witness["proper_subsets_of_this_pair_silent"],
            "Wrong typed pair or irreducibility")
    locked = compare_families([current], [proposed], locked={"P"})
    require(locked["decisions"][0]["withdraw"] is None, "Frozen veto should mask pure-withdrawal impact")
    overlap = restore_then_withdraw_impact([current], [proposed],
        document_groups=[{"id": "paper_P", "evidence_ids": ["P"]}],
        revoked_documents=["paper_P"], revoked_passages=["P"])
    require(overlap["witnesses"] == [], "Releasing one veto must preserve the overlapping veto")
    require((current, proposed) == originals, "Preview mutated graph inputs")
    require(plan(False, False)["worst_case_cost"] == 0
            and plan(True, False)["worst_case_cost"] == 1, "Wrong action-scoped clarification")
    return {"truth_table": table, "scalar_graph_state_comparisons": checks,
            "all_pure_withdrawal_subsets_agree": True, "typed_witness": witness,
            "minimum_typed_actions_within_this_explicit_alphabet": 2,
            "overlapping_document_and_passage_veto_has_no_two_action_witness": True,
            "clarification_cost_before": 0, "clarification_cost_at_typed_witness": 1,
            "original_local_flags_unchanged": True}


def check():
    high = [higher_order(k) for k in range(1, 7)]
    masked = masked_prerequisite()
    names = ["scripts/check_frontier_v6j_separation.py", "retrace/impact_v6h.py",
             "retrace/tiered_v6h.py", "retrace/typed_interventions_v6h.py", "retrace/workbench_v6h.py"]
    return {"schema": "retrace.v6j-illustrative-separation.v1", "passed": True,
            "kind": "authored formal illustration and independent scalar/engine cross-check",
            "model_experiment": False, "primary_benchmark_changed": False, "api_calls": 0,
            "higher_order": high, "masked_prerequisite": masked,
            "scalar_graph_state_comparisons": sum(r["scalar_graph_state_comparisons"] for r in high)
                + masked["scalar_graph_state_comparisons"],
            "input_sha256": {n: sha256((ROOT / n).read_bytes()).hexdigest() for n in names},
            "scope": "Explicit positive Boolean graphs and named action alphabets only. Mathematical constructions, not empirical detection rates, source entailment, or a claim that the underlying ideas are new. The general statements require their separate proofs; finite checks cover k=1..6."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check()
    if args.output:
        output = args.output.resolve()
        require(output.is_relative_to(ROOT), "New local output required")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"path": str(output), "sha256": sha256(output.read_bytes()).hexdigest(),
                          "passed": True, "scalar_graph_state_comparisons": result["scalar_graph_state_comparisons"]}))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
