#!/usr/bin/env python3
"""Run the independent evaluator and the project's engine side by side on every authored reading.

Sprint addition, written with AI assistance on Monday 16 November 2026. No model call.

    python post_sweep/compare_independent_evaluator.py

Compared, per decision:
  1. every authored reading at the three case states (initial, withdrawn, restored): state, Box and Diamond;
  2. every authored reading under 25 random withdrawal sets (seed 20261116; each record withdrawn with probability 0.3);
  3. every authored family at the three case states: Box and Diamond (the 768 pairs of the paper).
Output: post_sweep/out/independent_evaluator.json (also printed).
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

import independent_evaluator as mine  # noqa: E402
from retrace import tiered_v6h  # noqa: E402

STATES = ("initial", "withdrawn", "restored")
SEED, DRAWS, RATE = 20261116, 25, 0.3


def excluded_at(case, state_name):
    state = case["events"]["states"][state_name]
    groups = {g["id"]: g["evidence_ids"] for g in case["events"]["document_groups"]}
    return sorted({e for d in state["revoked_documents"] for e in groups[d]} | set(state["revoked_passages"]))


def main():
    corpus = json.loads((ROOT / "data/frontier-v6h-corpus.json").read_text(encoding="utf-8"))["cases"]
    rng = random.Random(SEED)
    t = Counter()
    differences = []
    for case in corpus:
        graphs = [row["graph"] for row in case["evaluation"]["source_family"]]
        t["cases"] += 1
        t["readings"] += len(graphs)
        for name in STATES:
            excluded = excluded_at(case, name)
            for number, graph in enumerate(graphs):
                theirs = tiered_v6h.analyze(graph, scenario_withdrawals=excluded)["decisions"]
                ours = mine.reading(graph, excluded)
                for d, row in theirs.items():
                    t["reading_state_decisions"] += 1
                    t["state_" + row["state"]] += 1
                    same = (ours[d]["state"], ours[d]["box"], ours[d]["diamond"]) == (
                        row["state"], row["box_supported"], row["diamond_supported"])
                    t["reading_state_agree"] += same
                    if not same:
                        differences.append([case["id"], name, number, d, row["state"], ours[d]["state"]])
            theirs = tiered_v6h.family_supervaluation(graphs, scenario_withdrawals=excluded)["decisions"]
            ours = mine.family(graphs, excluded)
            for d, row in theirs.items():
                t["family_pairs"] += 1
                same = (ours[d]["box"], ours[d]["diamond"]) == (row["box_supported"], row["diamond_supported"])
                t["family_pairs_agree"] += same
                if not same:
                    differences.append([case["id"], name, "family", d])
        for number, graph in enumerate(graphs):
            records = sorted(r["id"] for r in graph["evidence"])
            for _ in range(DRAWS):
                excluded = [r for r in records if rng.random() < RATE]
                theirs = tiered_v6h.analyze(graph, scenario_withdrawals=excluded)["decisions"]
                ours = mine.reading(graph, excluded)
                for d, row in theirs.items():
                    t["random_state_decisions"] += 1
                    t["random_" + row["state"]] += 1
                    same = (ours[d]["state"], ours[d]["box"], ours[d]["diamond"]) == (
                        row["state"], row["box_supported"], row["diamond_supported"])
                    t["random_state_agree"] += same
                    if not same:
                        differences.append([case["id"], "random", number, d, row["state"], ours[d]["state"]])
    out = {"seed": SEED, "random_draws_per_reading": DRAWS, "withdrawal_rate": RATE, **t,
           "differences": differences[:40], "difference_count": len(differences),
           "evaluator_lines": len((ROOT / "post_sweep/independent_evaluator.py").read_text(encoding="utf-8").splitlines()),
           "evaluator_imports_from_retrace": "retrace" in (ROOT / "post_sweep/independent_evaluator.py").read_text(
               encoding="utf-8").split('"""', 2)[2]}
    (ROOT / "post_sweep" / "out" / "independent_evaluator.json").write_text(json.dumps(out, indent=1) + "\n",
                                                                            encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
