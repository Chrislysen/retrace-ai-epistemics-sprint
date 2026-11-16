#!/usr/bin/env python3
"""How deep the agreement goes in the authored cases (a property of the cases, not a model result).

Sprint addition, written with AI assistance on Monday 16 November 2026. No model call. Uses the project's own
functions: the frozen grader's _impact and _typed_impact (retrace/frontier_v6h_eval.py) and withdrawal_robustness
(retrace/impact_v6h.py), called exactly as the grader calls them.

  1. For each authored family at its initial state: the smallest number of further withdrawals that destroys the
     support every reading gives a decision (withdrawal robustness), per supported decision.
  2. For each seed pool against its complete authored family: the smallest consequential witness. Scored scope =
     the scope the refuter endpoint uses (initial vetoes ignored); the second scope keeps the case's initial vetoes.

    python post_sweep/agreement_depth.py

Output: post_sweep/out/agreement_depth.json (also printed).
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retrace import frontier_v6h_eval as grader  # noqa: E402
from retrace.impact_v6h import withdrawal_robustness  # noqa: E402


def smallest(impact):
    """Class of the smallest witness in one _impact result."""
    if not impact.get("available"):
        return "not_available"
    sizes = [row["minimum_k"] for row in impact["withdrawal"]["decisions"] if row["minimum_k"] is not None]
    if sizes:
        k = min(sizes)
        return "no_withdrawal_needed" if k == 0 else "one_withdrawal" if k == 1 else "two_or_more_withdrawals"
    if impact["hamming2_consequential"]:
        return "only_activation_plus_withdrawal"
    return "none"


def main():
    corpus = json.loads((ROOT / "data/frontier-v6h-corpus.json").read_text(encoding="utf-8"))["cases"]
    cache = {}
    out = {"seed_kinds": dict(Counter(c["evaluation"]["seed_kind"] for c in corpus))}
    robustness, outside = Counter(), []
    witness = {}
    typed = Counter()
    detail = []
    for case in corpus:
        seed = [r["graph"] for r in case["authored_seed_pool"]["candidates"]]
        source = [r["graph"] for r in case["evaluation"]["source_family"]]
        x = grader.exclusions(case, "initial")
        locked = set(x["document_vetoes"] + x["passage_vetoes"])
        try:
            for row in withdrawal_robustness(source, locked=locked)["decisions"]:
                if not row["applicable"]:
                    robustness["decisions_without_unanimous_support"] += 1
                else:
                    k = row["minimum_k"]
                    robustness["supported_decisions"] += 1
                    robustness["k_none" if k is None else "k_1" if k == 1 else "k_2" if k == 2 else "k_3_or_more"] += 1
        except ValueError as exc:
            outside.append([case["id"], str(exc)])
        kind = case["evaluation"]["seed_kind"]
        scored = grader._impact(seed, source, set(), cache)
        with_vetoes = grader._impact(seed, source, locked, cache)
        release = grader._typed_impact(seed, source, case, cache)
        a, b = smallest(scored), smallest(with_vetoes)
        witness.setdefault(kind, {"scored_scope": Counter(), "with_initial_vetoes": Counter()})
        witness[kind]["scored_scope"][a] += 1
        witness[kind]["with_initial_vetoes"][b] += 1
        typed[(kind, bool(release.get("consequential")))] += 1
        detail.append({"case": case["id"], "seed_kind": kind, "readings": len(source), "seed_readings": len(seed),
                       "initial_vetoes": len(locked), "scored_scope": a, "with_initial_vetoes": b,
                       "typed_release": bool(release.get("consequential")),
                       "consequential_scored": scored.get("consequential")})
    out["withdrawal_robustness_initial_state"] = dict(robustness)
    out["families_outside_the_search_scope"] = outside
    out["smallest_witness"] = {k: {s: dict(v) for s, v in d.items()} for k, d in witness.items()}
    out["typed_release_consequential"] = {f"{k}|{v}": n for (k, v), n in sorted(typed.items())}
    out["cases"] = detail
    (ROOT / "post_sweep" / "out" / "agreement_depth.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8",
                                                                      newline="\n")
    print(json.dumps({k: v for k, v in out.items() if k != "cases"}, indent=1))
    silent = [row["case"] for row in detail if row["seed_kind"] != "faithful" and "deficient" in str(row["seed_kind"])
              and row["with_initial_vetoes"] in ("none", "only_activation_plus_withdrawal")]
    print("deficient seeds with no withdrawal witness under the initial vetoes:", silent)


if __name__ == "__main__":
    main()
