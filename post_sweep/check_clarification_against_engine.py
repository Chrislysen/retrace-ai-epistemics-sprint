#!/usr/bin/env python3
"""
Checks Proposition B.4 (clarification planning) against the released engine code.

Usage:   python3 check_clarification_against_engine.py <path-to-extracted-artifact>
Needs:   Python 3.11+, standard library only. No network, no model calls.

It calls retrace/workbench_v6h.py:minimax_clarification on random instances and compares it with
an independent exhaustive search written here. Three statements are checked:
  (a) the planner's worst-case cost equals the true minimum over all adaptive question orders;
  (b) settling is possible exactly when no two candidates with different status vectors give the
      same answer to every supplied question (no "blocking pair");
  (c) when settling is possible and m distinct status vectors remain, the cost is at least
      ceil(log2 m) times the cheapest question cost.
"""
import math
import random
import sys

SEED = 20261116
STATES = ["supported", "not_supported", "contested", "insufficient_provenance"]


def brute(signatures, answers, costs, members):
    """Independent exhaustive minimax. Returns the minimum worst-case cost, or None if impossible."""
    if len({signatures[i] for i in members}) <= 1:
        return 0
    best = None
    for q in range(len(costs)):
        yes = frozenset(i for i in members if answers[q][i])
        no = members - yes
        if not yes or not no:
            continue
        left = brute(signatures, answers, costs, yes)
        right = brute(signatures, answers, costs, no)
        if left is None or right is None:
            continue
        value = costs[q] + max(left, right)
        if best is None or value < best:
            best = value
    return best


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    sys.path.insert(0, sys.argv[1])
    from retrace.workbench_v6h import minimax_clarification
    rng = random.Random(SEED)
    trials = 3000
    cost_mismatch = possible_mismatch = bound_violations = 0
    possible_count = impossible_count = trivial = 0
    for _ in range(trials):
        n = rng.randint(2, 7)
        decisions = ["d%d" % i for i in range(rng.randint(1, 3))]
        palette = rng.sample(STATES, rng.randint(1, 3))
        ids = ["c%d" % i for i in range(n)]
        vectors = {cid: {d: rng.choice(palette) for d in decisions} for cid in ids}
        k = rng.randint(0, 5)
        questions = [{"id": "q%d" % j, "label": "question %d" % j, "cost": rng.randint(1, 5),
                      "answers": {cid: rng.random() < 0.5 for cid in ids}} for j in range(k)]
        result = minimax_clarification(vectors, questions)

        signatures = [tuple(vectors[cid][d] for d in sorted(decisions)) for cid in ids]
        answers = [[q["answers"][cid] for cid in ids] for q in questions]
        costs = [q["cost"] for q in questions]
        truth = brute(signatures, answers, costs, frozenset(range(n)))

        if result["worst_case_cost"] != truth:
            cost_mismatch += 1
        blocking = any(signatures[i] != signatures[j] and all(a[i] == a[j] for a in answers)
                       for i in range(n) for j in range(i + 1, n))
        if result["possible"] != (not blocking):
            possible_mismatch += 1
        if truth is None:
            impossible_count += 1
        else:
            possible_count += 1
            m = len(set(signatures))
            if m == 1:
                trivial += 1
            elif truth < math.ceil(math.log2(m)) * min(costs):
                bound_violations += 1
    ok = cost_mismatch == 0 and possible_mismatch == 0 and bound_violations == 0
    print("[%s] B.4 clarification planning" % ("PASS" if ok else "FAIL"))
    print("       %d random instances (2-7 candidates, 0-5 questions): %d settleable (%d already in agreement), %d not settleable"
          % (trials, possible_count, trivial, impossible_count))
    print("       cost differs from exhaustive minimum: %d; 'possible' differs from the no-blocking-pair test: %d; lower bound violated: %d"
          % (cost_mismatch, possible_mismatch, bound_violations))
    print("       seed %d, Python %s" % (SEED, sys.version.split()[0]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
