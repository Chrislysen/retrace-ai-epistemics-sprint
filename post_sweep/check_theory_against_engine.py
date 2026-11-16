#!/usr/bin/env python3
"""
Checks three formal statements about RETRACE against the released engine code itself.

Usage:   python3 check_theory_against_engine.py <path-to-extracted-artifact>
Needs:   Python 3.11+, standard library only. No network, no model calls.
Exit:    0 if every check passes, 1 otherwise.

It imports the engine modules from the artifact (retrace/argumentation_v6h.py,
retrace/tiered_v6h.py, retrace/impact_v6h.py) and compares their output with
independent brute-force computations written here.

P1  Rebuttal fragment collapses: no argument is ever labelled OUT, and an argument is IN
    exactly when no argument concludes the opposite of any of its subconclusions.
P2  Minimum consequential withdrawal equals minimum vertex cover on the reduction
    instances, for both compare_families (a proposed counter-reading) and
    withdrawal_robustness (one reading). So the search problem is NP-hard in general.
P3  Withdrawal blindness: in monotone (Tier A) families, if no reading supports the
    decision at the baseline, no withdrawal makes a proposed reading consequential.
"""
import itertools
import json
import random
import sys

SEED = 20261116


def load_engine(root):
    sys.path.insert(0, root)
    from retrace import argumentation_v6h, impact_v6h, tiered_v6h  # noqa: E402
    return argumentation_v6h, impact_v6h, tiered_v6h


# ----------------------------------------------------------------------------- P1
def random_arguments(rng):
    n = rng.randint(1, 12)
    claims = ["c%d" % i for i in range(rng.randint(1, 4))]
    rows = []
    for i in range(n):
        earlier = [r["id"] for r in rows]
        k = rng.randint(0, min(3, len(earlier)))
        rows.append({"id": "a%d" % i, "claim": rng.choice(claims),
                     "polarity": rng.choice(["positive", "negative"]),
                     "subarguments": sorted(rng.sample(earlier, k))})
    return rows


def conflict_free_set(rows):
    """Independent computation: arguments none of whose subconclusions is opposed by anyone."""
    index = {r["id"]: r for r in rows}

    def closure(ident):
        found = {ident}
        for child in index[ident]["subarguments"]:
            found |= closure(child)
        return found

    signed = {(r["claim"], r["polarity"]) for r in rows}
    flip = {"positive": "negative", "negative": "positive"}
    return {r["id"] for r in rows
            if not any((index[s]["claim"], flip[index[s]["polarity"]]) in signed for s in closure(r["id"]))}


def check_p1(arg, trials=20000):
    rng = random.Random(SEED)
    out_seen = mismatches = attacked = total = 0
    for _ in range(trials):
        rows = random_arguments(rng)
        labels = arg.rebuttal_arbiter(rows)
        total += len(rows)
        out_seen += len(labels["out"])
        expect_in = conflict_free_set(rows)
        attacked += len(rows) - len(expect_in)
        if set(labels["in"]) != expect_in or set(labels["undecided"]) != {r["id"] for r in rows} - expect_in:
            mismatches += 1
    return {"name": "P1 rebuttal fragment collapses to conflict-freeness",
            "pass": out_seen == 0 and mismatches == 0,
            "detail": "%d random argument sets, %d arguments (%d attacked): %d labelled OUT, %d sets where IN differs from the conflict-free set"
                      % (trials, total, attacked, out_seen, mismatches)}


# ----------------------------------------------------------------------------- P2
def tier_graph(tiered, evidence, positive):
    return {"schema": tiered.SCHEMA,
            "evidence": [{"id": e, "kind": "root", "active": True, "parents": []} for e in evidence],
            "claims": [{"id": "C", "positive": positive, "negative": {"const": False}}],
            "decisions": [{"id": "D", "requires": ["C"]}]}


def any_of(terms):
    return terms[0] if len(terms) == 1 else {"any": terms}


def min_vertex_cover(vertices, edges):
    for size in range(len(vertices) + 1):
        for subset in itertools.combinations(vertices, size):
            chosen = set(subset)
            if all(u in chosen or v in chosen for u, v in edges):
                return size
    return None


def check_p2(impact, tiered, trials=400):
    rng = random.Random(SEED + 1)
    bad_compare = bad_robust = 0
    sizes = []
    for _ in range(trials):
        n = rng.randint(3, 9)
        vertices = ["v%d" % i for i in range(n)]
        pairs = list(itertools.combinations(vertices, 2))
        edges = rng.sample(pairs, rng.randint(1, min(len(pairs), 12)))
        terms = [{"all": [{"ref": u}, {"ref": v}]} for u, v in edges]
        evidence = vertices + ["Q"]
        reading_a = tier_graph(tiered, evidence, any_of(terms))
        reading_b = tier_graph(tiered, evidence, {"any": terms + [{"ref": "Q"}]})
        cover = min_vertex_cover(vertices, edges)
        sizes.append(cover)
        got = impact.compare_families([reading_a], [reading_b])["decisions"][0]["minimum_k"]
        if got != cover:
            bad_compare += 1
        robust = impact.withdrawal_robustness([reading_a])["decisions"][0]["minimum_k"]
        if robust != cover:
            bad_robust += 1
    return {"name": "P2 minimum consequential withdrawal equals minimum vertex cover",
            "pass": bad_compare == 0 and bad_robust == 0,
            "detail": "%d random graphs (3-9 vertices, cover sizes %d-%d): %d mismatches for compare_families, %d for withdrawal_robustness"
                      % (trials, min(sizes), max(sizes), bad_compare, bad_robust)}


# ----------------------------------------------------------------------------- P3
def random_monotone(rng, evidence):
    terms = []
    for _ in range(rng.randint(1, 4)):
        refs = rng.sample(evidence, rng.randint(1, 3))
        terms.append({"ref": refs[0]} if len(refs) == 1 else {"all": [{"ref": r} for r in refs]})
    return any_of(terms)


def check_p3(impact, tiered, trials=1500):
    rng = random.Random(SEED + 2)
    silent_cases = violations = spoken = 0
    for _ in range(trials):
        evidence = ["e%d" % i for i in range(rng.randint(3, 7))]
        current = [tier_graph(tiered, evidence, random_monotone(rng, evidence)) for _ in range(rng.randint(1, 3))]
        proposed = [tier_graph(tiered, evidence, random_monotone(rng, evidence))]
        locked = sorted(rng.sample(evidence, rng.randint(0, len(evidence) - 1)))
        base = tiered.family_supervaluation(current + proposed, scenario_withdrawals=locked)["decisions"]["D"]
        result = impact.compare_families(current, proposed, locked=locked)["decisions"][0]
        if not base["diamond_supported"]:
            silent_cases += 1
            if result["minimum_k"] is not None:
                violations += 1
        elif result["minimum_k"] is not None:
            spoken += 1
    return {"name": "P3 withdrawal blindness below the support frontier (monotone families)",
            "pass": violations == 0 and silent_cases > 0,
            "detail": "%d random monotone families: %d had no supporting reading at the baseline, and in %d of those a withdrawal witness was reported; %d other cases did have a witness"
                      % (trials, silent_cases, violations, spoken)}


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    arg, impact, tiered = load_engine(sys.argv[1])
    results = [check_p1(arg), check_p2(impact, tiered), check_p3(impact, tiered)]
    for row in results:
        print("[%s] %s\n       %s" % ("PASS" if row["pass"] else "FAIL", row["name"], row["detail"]))
    ok = all(row["pass"] for row in results)
    print("\n%d of %d checks passed (seed %d, Python %s)" % (sum(r["pass"] for r in results), len(results), SEED, sys.version.split()[0]))
    print(json.dumps({"seed": SEED, "results": results}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
