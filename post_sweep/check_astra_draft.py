#!/usr/bin/env python3
"""Numbers quoted in Astra's draft (report/v6n-study/revisions/r4/research-draft.md) that the other scripts
do not print, recomputed here from the launch journals, the frozen corpus and the per-slot grades.

Sprint addition, written with AI assistance on Sunday 15 November 2026. No model call.

    python post_sweep/check_astra_draft.py

Output: post_sweep/out/astra_draft_check.json (also printed).
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "post_sweep"))
from recompute_sweep import PRIMARY, is_missing, merge_launches, read_json, root_cause, slot_class  # noqa: E402


def main():
    corpus = {c["id"]: c for c in read_json("data/frontier-v6h-corpus.json")["cases"]}
    design = read_json("data/frontier-v6i-design.json")
    slots = read_json("data/frontier-v6i-sessions.json")
    score = read_json("post_sweep/out/sweep_frozen/score.json")
    audits = read_json("post_sweep/out/sweep_frozen/score-audits.json")
    first = {(r["model"], r["case_id"], r["condition"], r["phase"]): r for r in audits if r.get("view") == "first_attempt" and "slot_id" in r}
    finals, _, _ = merge_launches(slots)
    classes = {sid: slot_class(row) for sid, row in finals.items()}
    causes = {sid: root_cause(sid, finals, classes) for sid in finals}
    sid_of = {(s["model"], s["case_id"], s["condition"], s["phase"]): s["slot_id"] for s in slots}
    out = {}

    # corpus structure
    readings = Counter(len(c["evaluation"]["source_family"]) for c in corpus.values())
    out["corpus"] = {"cases": len(corpus), "authored_readings": sum(k * v for k, v in readings.items()),
                     "single_reading_cases": readings[1], "multiplicities": dict(sorted(readings.items())),
                     "seed_kinds": dict(Counter(c["evaluation"].get("seed_kind") for c in corpus.values())),
                     "seed_kinds_by_partition": dict(Counter((c["partition"], c["evaluation"].get("seed_kind")) .__str__()
                                                             for c in corpus.values())),
                     "k10_families_over_ten": sum(len(corpus[cid]["evaluation"]["source_family"]) > 10
                                                  for cid in design["k10_ambiguity_case_ids"] + design["k10_single_family_control_ids"])}

    # strict IR by partition
    by_partition = {}
    for model in PRIMARY:
        t = Counter()
        for cid, case in corpus.items():
            row = first[(model, cid, "strict_source_ir", "extract")]
            t[case["partition"] + "_cases"] += 1
            t[case["partition"] + "_bare_exact"] += row.get("correct") is True
            t[case["partition"] + "_admitted_exact"] += bool(row.get("semantic_correct"))
        by_partition[model] = dict(t)
    out["strict_ir_by_partition"] = by_partition

    # the 119 strict-IR slots that are not admitted
    t = Counter()
    for model in PRIMARY:
        for cid in corpus:
            key = (model, cid, "strict_source_ir", "extract")
            row = first[key]
            if row.get("semantic_correct"):
                t["admitted_exact"] += 1
            else:
                c = classes[sid_of[key]]
                t["truncated" if c == "truncated" else "operational_or_host" if is_missing(causes[sid_of[key]]) else
                  "completed_invalid" if c == "completed" else c] += 1
    out["strict_ir_slot_breakdown"] = dict(t)

    # refuter
    t = Counter()
    for model in PRIMARY:
        for cid in corpus:
            key = (model, cid, "adversarial_refuter", "counter_read")
            row, c = first[key], classes[sid_of[key]]
            t["slots"] += 1
            t["class_" + c.split(":")[0]] += 1
            t["completed_invalid"] += c == "completed" and str(row.get("error")).startswith("invalid")
            t["source_located"] += bool(row.get("source_locations_valid"))
            t["located_and_exact_family"] += bool(row.get("source_locations_valid")) and bool(row.get("source_exact_family"))
            t["located_on_faithful_seed"] += bool(row.get("source_locations_valid")) and bool(row.get("seed_exact_evaluation_only"))
            t["correct_on_" + ("faithful" if row.get("seed_exact_evaluation_only") else "deficient")] += row.get("correct") is True
            t["seed_" + ("faithful" if row.get("seed_exact_evaluation_only") else "deficient")] += 1
    out["refuter"] = dict(t)

    # Qwen 3.8 on the 30 cases of the two-stage route
    cases30 = design["subsets"]["nl_projection"]
    t = Counter()
    lower = upper = 0
    for cid in cases30:
        a_key, s_key, p_key = [("qwen3.8-27b", cid, c, p) for c, p in
                               (("strict_source_ir", "extract"), ("nl_source", "extract"), ("nl_projection", "project"))]
        t["nl_source_" + classes[sid_of[s_key]]] += 1
        t["nl_projection_" + classes[sid_of[p_key]]] += 1
        a, b = first[a_key].get("correct") is True, first[p_key].get("correct") is True
        a_missing, b_missing = is_missing(causes[sid_of[a_key]]), is_missing(causes[sid_of[p_key]])
        t["a_correct"] += a
        t["b_correct"] += b
        t["a_missing"] += a_missing
        t["b_missing"] += b_missing
        lower += (0 if b_missing else b) - (1 if a_missing else a)
        upper += (1 if b_missing else b) - (0 if a_missing else a)
    out["qwen_two_stage"] = {**t, "difference_range_if_missing_free": [lower, upper], "cases": len(cases30)}

    # saved interval and accounting values
    amended = score["amended_recovered_complete"]
    out["qwen_interval_rows"] = [row for row in amended["cluster_intervals"]
                                 if "qwen3.8-27b" in json.dumps(row)[:4000] and "nl_projection" in json.dumps(row)][:1]
    if out["qwen_interval_rows"]:
        row = out["qwen_interval_rows"][0]
        out["qwen_interval_rows"] = {k: v for k, v in row.items() if k != "case_ids" and len(json.dumps(v)) < 1500}
    segment = score["operational_summary"]["new_segment"]
    out["budget"] = {k: segment["budget"].get(k) for k in segment["budget"]} if isinstance(segment.get("budget"), dict) else segment.get("budget")
    out["request_accounting"] = {k: v for k, v in score["request_accounting"].items() if k != "orphan_attempt_ids"}

    (ROOT / "post_sweep" / "out" / "astra_draft_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                                                       encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=1, ensure_ascii=False)[:9000])


if __name__ == "__main__":
    main()
