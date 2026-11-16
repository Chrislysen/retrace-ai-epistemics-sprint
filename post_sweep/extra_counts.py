#!/usr/bin/env python3
"""Counts the paper quotes that the other scripts do not print directly.

Sprint addition, written with AI assistance on Sunday 15 November 2026. No model call.

    python post_sweep/extra_counts.py

Output: post_sweep/out/extra_counts.json (also printed).
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

import recompute_prose24 as prose  # noqa: E402
from recompute_sweep import PRIMARY, DIAGNOSTIC, is_missing, merge_launches, read_json, root_cause, same_function, slot_class  # noqa: E402
from zero_call_analyses import STATES, PHASES, compare, family_classes, klass  # noqa: E402


def graph_differences(model_graph, gold_graph):
    notes = []
    ge = {r["id"]: r for r in gold_graph["evidence"]}
    for r in model_graph["evidence"]:
        g = ge.get(r["id"])
        if g is None:
            notes.append(f"evidence {r['id']}: not in the authored graph")
        elif (r["kind"], r["active"], sorted(r["parents"])) != (g["kind"], g["active"], sorted(g["parents"])):
            notes.append(f"evidence {r['id']}: {r['kind']}/{r['active']}/{sorted(r['parents'])} vs authored {g['kind']}/{g['active']}/{sorted(g['parents'])}")
    gc = {r["id"]: r for r in gold_graph["claims"]}
    for r in model_graph["claims"]:
        g = gc.get(r["id"])
        if g is None:
            notes.append(f"claim {r['id']}: not in the authored graph")
            continue
        for side in ("positive", "negative"):
            if not same_function(r[side], g[side]):
                notes.append(f"claim {r['id']} {side}: {json.dumps(r[side])} vs authored {json.dumps(g[side])}")
    gd = {r["id"]: sorted(r["requires"]) for r in gold_graph["decisions"]}
    for r in model_graph["decisions"]:
        if sorted(r["requires"]) != gd.get(r["id"]):
            notes.append(f"decision {r['id']}: requires {sorted(r['requires'])} vs authored {gd.get(r['id'])}")
    return notes


def main():
    out = {}

    # Friday experiment: cases with an accepted extraction
    corpus24 = json.loads((ROOT / "data/prose-holdout.json").read_text(encoding="utf-8"))
    freeze = json.loads((ROOT / "data/prose-freeze.json").read_text(encoding="utf-8"))
    accepted = Counter()
    wrong = 0
    for model in freeze["models"]:
        folders = [ROOT / "results/prose-heldout" / model]
        if model == "gemma-4-31b-it":
            folders.append(ROOT / "results/prose-continuation" / model)
        records = [json.loads(line) for folder in folders for line in (folder / "responses.jsonl").read_text(encoding="utf-8").splitlines() if line]
        rows = prose.independent_rows(corpus24, records)
        for (case_id, condition, _), row in rows.items():
            if condition == "prose_extract" and row["semantic_valid"]:
                accepted[case_id] += 1
                wrong += not (row["exact"] and row["graph_exact"])
    out["friday"] = {"cases": len(corpus24), "accepted_extractions": sum(accepted.values()), "accepted_and_wrong": wrong,
                     "cases_with_an_accepted_extraction": len(accepted), "cases_accepted_for_both_models": sum(v == 2 for v in accepted.values())}

    # Sweep
    corpus = {c["id"]: c for c in read_json("data/frontier-v6h-corpus.json")["cases"]}
    slots = read_json("data/frontier-v6i-sessions.json")
    audits = read_json("post_sweep/out/sweep_frozen/score-audits.json")
    first = {(r["model"], r["case_id"], r["condition"], r["phase"]): r for r in audits if r.get("view") == "first_attempt" and "slot_id" in r}
    finals, _, _ = merge_launches(slots)
    classes = {sid: slot_class(row) for sid, row in finals.items()}
    causes = {sid: root_cause(sid, finals, classes) for sid in finals}
    sid_of = {(s["model"], s["case_id"], s["condition"], s["phase"]): s["slot_id"] for s in slots}

    strict = Counter()
    cases_admitted, per_case_models = set(), Counter()
    for (model, cid, cond, phase), row in first.items():
        if cond != "strict_source_ir":
            continue
        group = "primary" if model in PRIMARY else "diagnostic"
        strict[group + "_slots"] += 1
        if is_missing(causes[sid_of[(model, cid, cond, phase)]]):
            strict[group + "_missing"] += 1
        elif row.get("candidates") and row.get("schema_valid"):
            strict[group + ("_admitted_bare" if row.get("strict_bare_json") else "_admitted_fenced")] += 1
            strict[group + "_admitted_exact"] += bool(row["family"]["exact_family"])
            cases_admitted.add(cid)
            per_case_models[cid] += 1
        else:
            strict[group + "_rejected"] += 1
            strict[group + "_rejected_" + str(row.get("error"))] += 1
    out["strict_ir"] = {**strict, "distinct_cases_with_an_admitted_compilation": len(cases_admitted),
                        "cases_admitted_by_all_five_primary_models": sum(1 for cid in cases_admitted if sum(
                            1 for m in PRIMARY if (first[(m, cid, "strict_source_ir", "extract")].get("candidates")
                                                   and first[(m, cid, "strict_source_ir", "extract")].get("schema_valid"))) == 5)}

    # every compiled family that is not exact, in any compilation arm
    odd = []
    for (model, cid, cond, phase), row in first.items():
        if cond in ("strict_source_ir", "nl_projection", "long_source_ir") and row.get("candidates") and not row["family"]["exact_family"]:
            case = corpus[cid]
            gold_graphs = [x["graph"] for x in case["evaluation"]["source_family"]]
            mine = [x["graph"] for x in row["candidates"]]
            verdicts = Counter()
            for s in STATES:
                got, want = family_classes(mine, case, s), family_classes(gold_graphs, case, s)
                for d in want:
                    verdicts[compare(got[d], want[d])] += 1
            odd.append({"model": model, "case": cid, "arm": cond, "bare_json": bool(row.get("strict_bare_json")),
                        "family": {k: row["family"][k] for k in ("expected_distinct", "predicted_distinct", "correct_distinct", "missing_distinct", "spurious_distinct")},
                        "registry_gaps": (row.get("compilation") or {}).get("registry_coverage_gaps"),
                        "pairs_at_the_three_states": dict(verdicts),
                        "differences_first_graph": graph_differences(mine[0], gold_graphs[0])[:8]})
    out["compiled_but_not_exact"] = odd
    out["compiled_totals"] = dict(Counter(cond for (m, c, cond, p), row in first.items()
                                          if cond in ("strict_source_ir", "nl_projection", "long_source_ir") and row.get("candidates")))

    # direct answers, pooled over the six commitment phases
    direct = {}
    gold = {cid: {s: family_classes([x["graph"] for x in c["evaluation"]["source_family"]], c, s) for s in STATES}
            for cid, c in corpus.items() if any(k[1] == cid and k[2] == "commitment" for k in first)}
    for model in PRIMARY + [DIAGNOSTIC]:
        arm = "commitment" if model in PRIMARY else "diagnostic_commitment"
        t = Counter()
        for cid in gold:
            for phase in PHASES:
                row = first[(model, cid, arm, phase)]
                state = corpus[cid]["phases"][phase]["state_name"]
                t["slots"] += 1
                usable = row.get("eligible_completed") and row.get("schema_valid")
                t["usable_answers"] += bool(usable)
                t["exactly_right"] += row.get("correct") is True
                t["error_" + str(row.get("error"))] += not usable
                for d, g in gold[cid][state].items():
                    t["pairs"] += 1
                    if g == "ASSERT":
                        t["authored_assert_pairs"] += 1
                    else:
                        t["authored_not_assert_pairs"] += 1
                    if usable:
                        a = row["parsed"]["decisions"][d]
                        result = compare(klass(a["box_supported"], a["diamond_supported"]), g)
                        t["answered_pairs"] += 1
                        t["answered_" + result] += 1
                        t["answered_authored_assert"] += g == "ASSERT"
                        t["answered_authored_not_assert"] += g != "ASSERT"
        direct[model] = dict(t)
    out["direct_answers_six_phases"] = direct

    (ROOT / "post_sweep" / "out" / "extra_counts.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
