#!/usr/bin/env python3
"""Every number quoted in the sections added to paper v1 (Section 4.4, Section 5 note, Appendix G), in one file.

Sprint addition, written with AI assistance on Monday 16 November 2026. No model call.
Reads the frozen corpus, and the outputs of zero_call_analyses.py, extra_counts.py and recompute_prose24.py.

    python post_sweep/v1_numbers.py

Output: post_sweep/out/v1_numbers.json (also printed).
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_sweep import PRIMARY, read_json  # noqa: E402
from zero_call_analyses import (PHASES, STATES, compare, downstream_classes, family_classes, naive_gate_classes,  # noqa: E402
                                strip_lineage)


def main():
    corpus = {c["id"]: c for c in read_json("data/frontier-v6h-corpus.json")["cases"]}
    zero = read_json("post_sweep/out/zero_call.json")
    extra = read_json("post_sweep/out/extra_counts.json")
    out = {}

    # 1. simpler rules against the engine on the authored families: pairs and cases by kind of difference
    pairs, cases = defaultdict(Counter), defaultdict(lambda: defaultdict(set))
    for cid, case in corpus.items():
        graphs = [x["graph"] for x in case["evaluation"]["source_family"]]
        for s in STATES:
            gold = family_classes(graphs, case, s)
            methods = {"no_lineage": family_classes([strip_lineage(g) for g in graphs], case, s),
                       "withdraw_downstream": downstream_classes(graphs, case, s),
                       "single_reading": family_classes(graphs[:1], case, s),
                       "naive_gate": naive_gate_classes(graphs, case, s)}
            for name, verdicts in methods.items():
                for d, g in gold.items():
                    result = compare(verdicts[d], g)
                    pairs[name]["pairs"] += 1
                    pairs[name][result] += 1
                    pairs[name][f"state_{s}_{result}"] += 1
                    if result != "agree":
                        cases[name][result].add(cid)
                        cases[name]["any"].add(cid)
    out["simpler_rules"] = {name: {"pairs": dict(pairs[name]),
                                   "cases_with": {k: len(v) for k, v in sorted(cases[name].items())},
                                   "bridge_cases_with_any": sorted(c for c in cases[name]["any"]
                                                                   if corpus[c]["partition"] == "ecological")}
                            for name in pairs}
    saved = zero["A4_baselines_on_authored_families"]
    out["simpler_rules_match_saved_run"] = all(
        {k: v for k, v in pairs[name].items() if not k.startswith("state_")} == saved[name] for name in pairs)
    out["corpus_structure"] = zero["A5_static"]
    out["engine_checks"] = zero["A7_engine_checks"]

    # 2. direct answers pooled over the six temporal phases (12 cases, 58 decisions per phase)
    direct = {}
    for model in PRIMARY:
        rows = zero["A2_direct_vs_pipeline"][model]
        t = Counter()
        for phase in PHASES:
            row = rows[f"commitment/{phase}"]
            for key in ("pairs", "direct_agree", "direct_unsafe", "direct_over_cautious", "direct_other_difference",
                        "direct_cases_answered", "direct_cases_fully_right_by_class"):
                t[key] += row.get(key, 0)
        e = extra["direct_answers_six_phases"][model]
        direct[model] = {**t, "slots": e["slots"], "usable_answers": e["usable_answers"],
                         "answered_pairs": e["answered_pairs"], "answered_agree": e["answered_agree"],
                         "answered_authored_assert": e["answered_authored_assert"],
                         "answered_authored_not_assert": e["answered_authored_not_assert"],
                         "consistent": (t["direct_agree"] == e["answered_agree"]
                                        and t["direct_agree"] + t["direct_unsafe"] + t["direct_over_cautious"]
                                        + t["direct_other_difference"] == e["answered_pairs"]),
                         "pipeline_no_verdict_of_58": rows["commitment/hist_init"]["pipeline_no_verdict"],
                         "pipeline_unsafe_all_phases": sum(rows[f"commitment/{p}"].get("pipeline_unsafe", 0) for p in PHASES)}
        for arm in ("oracle_ir_consumption", "symbolic_assistance"):
            row = rows[f"{arm}/fresh_withdrawn"]
            direct[model][arm] = {k: row.get(k, 0) for k in ("direct_cases_answered", "direct_unsafe", "direct_over_cautious",
                                                             "direct_other_difference", "direct_agree", "gold_ASSERT", "pairs")}
    out["direct_answers"] = direct

    # 3. strict source IR per model: counts and the two codings of unavailable outcomes
    strict = {}
    for model in PRIMARY:
        a = zero["A1_pipeline"][model]
        bare, fenced = a.get("slot_admitted_bare", 0), a.get("slot_admitted_fenced", 0)
        missing, rejected = a.get("slot_missing", 0), a.get("slot_rejected", 0)
        strict[model] = {"slots": a["slots"], "admitted_bare": bare, "admitted_fenced": fenced, "rejected": rejected,
                         "unavailable": missing, "sum_check": bare + fenced + missing + rejected == a["slots"],
                         "admitted_exact": a["admitted_and_exact"], "admitted_not_exact": a["admitted_not_exact"],
                         "bare_range_percent": [round(100 * bare / a["slots"], 1), round(100 * (bare + missing) / a["slots"], 1)],
                         "admitted_range_percent": [round(100 * (bare + fenced) / a["slots"], 1),
                                                    round(100 * (bare + fenced + missing) / a["slots"], 1)],
                         "unavailable_share_percent": round(100 * missing / a["slots"], 1),
                         "unsafe_of_gold_not_assert": a["unsafe_of_gold_not_assert"],
                         "asserted_of_gold_assert": a["asserted_of_gold_assert"]}
    out["strict_ir"] = strict
    out["strict_ir_totals"] = extra["strict_ir"]
    out["compiled_families_by_arm"] = zero["compiled_families_by_arm"]
    out["friday_extraction"] = extra["friday"]

    # 4. the 24-case experiment of the first day
    friday = read_json("post_sweep/out/prose24_recompute.json")
    out["friday_keys"] = sorted(friday)

    (ROOT / "post_sweep" / "out" / "v1_numbers.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                                                 encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
