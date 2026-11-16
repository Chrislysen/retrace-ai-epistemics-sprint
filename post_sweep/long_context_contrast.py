#!/usr/bin/env python3
"""The 12 long-document cases of the sweep (Gemma only): direct verdicts against compiled declarations, with short and
with long documents, at the same state (after the withdrawal). Existing data, no model call.

Sprint addition, written with AI assistance on Monday 16 November 2026. This contrast was noticed after the sweep
outcomes had been seen; it is not among the analyses fixed in prereg/post_sweep_rules.md and is labelled post hoc.

    python post_sweep/long_context_contrast.py

Output: post_sweep/out/long_context_contrast.json, paper_build/tables/long_context.md
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_sweep import mcnemar_exact, read_json  # noqa: E402
from zero_call_analyses import compare, family_classes, klass  # noqa: E402

MODEL, STATE = "gemma-4-31b-it", "withdrawn"
ARMS = {"direct_short": ("commitment", "fresh_withdrawn"), "direct_long": ("long_commitment", "fresh_withdrawn"),
        "compiled_short": ("strict_source_ir", "extract"), "compiled_long": ("long_source_ir", "extract")}


def main():
    corpus = {c["id"]: c for c in read_json("data/frontier-v6h-corpus.json")["cases"]}
    audits = read_json("post_sweep/out/sweep_frozen/score-audits.json")
    first = {(r["case_id"], r["condition"], r["phase"]): r for r in audits
             if r.get("view") == "first_attempt" and "slot_id" in r and r["model"] == MODEL}
    cases = sorted(cid for (cid, cond, _phase) in first if cond == "long_commitment")
    out = {"model": MODEL, "state": STATE, "cases": cases, "arms": {}, "per_case": {}}
    right = {}
    for arm, (condition, phase) in ARMS.items():
        t = Counter()
        right[arm] = {}
        for cid in cases:
            case = corpus[cid]
            gold = family_classes([x["graph"] for x in case["evaluation"]["source_family"]], case, STATE)
            row = first[(cid, condition, phase)]
            verdict = None
            if arm.startswith("direct"):
                if row.get("eligible_completed") and row.get("schema_valid") and row.get("parsed"):
                    verdict = {d: klass(a["box_supported"], a["diamond_supported"]) for d, a in row["parsed"]["decisions"].items()}
            elif row.get("schema_valid") and row.get("candidates"):
                verdict = family_classes([c["graph"] for c in row["candidates"]], case, STATE)
                t["exact_family"] += bool(row.get("semantic_correct"))
            t["cases"] += 1
            t["pairs"] += len(gold)
            t["pairs_asserted_by_reference"] += sum(g == "ASSERT" for g in gold.values())
            if verdict is None:
                t["no_verdict_cases"] += 1
                t["no_verdict_pairs"] += len(gold)
                right[arm][cid] = False
                out["per_case"].setdefault(cid, {})[arm] = "no verdict"
                continue
            results = [compare(verdict[d], g) for d, g in gold.items()]
            t["verdict_cases"] += 1
            t["fully_right_cases"] += all(r == "agree" for r in results)
            for r in results:
                t["pair_" + r] += 1
            right[arm][cid] = all(r == "agree" for r in results)
            out["per_case"].setdefault(cid, {})[arm] = "right" if right[arm][cid] else "wrong (" + ", ".join(
                f"{n} {k}" for k, n in sorted(Counter(r for r in results if r != "agree").items())) + ")"
        out["arms"][arm] = dict(t)
    for pair in (("compiled_long", "direct_long"), ("compiled_short", "direct_short"), ("direct_long", "direct_short"),
                 ("compiled_long", "compiled_short")):
        a_only = sum(right[pair[0]][c] and not right[pair[1]][c] for c in cases)
        b_only = sum(right[pair[1]][c] and not right[pair[0]][c] for c in cases)
        out.setdefault("paired", {})["_vs_".join(pair)] = {
            "first_right_second_not": a_only, "second_right_first_not": b_only, "exact_mcnemar_p_post_hoc": mcnemar_exact(a_only, b_only)}
    lines = ["# Long documents: direct verdicts against compiled declarations (Gemma, 12 cases, state after the withdrawal)", "",
             "Produced by `post_sweep/long_context_contrast.py` from the sweep's graded records. Post hoc; one model; 12 cases.",
             "A compiled declaration counts when the validator admits it, fenced or bare. Right = every decision matches the reference.", "",
             "| Arm | Cases with a verdict /12 | All decisions right /12 | Pairs matching | Unsafe pairs | Dropped pairs | Other | Pairs without a verdict |",
             "|---|---|---|---|---|---|---|---|"]
    names = {"direct_short": "Direct verdict, short documents", "direct_long": "Direct verdict, long documents",
             "compiled_short": "Compiled declaration, short documents", "compiled_long": "Compiled declaration, long documents"}
    for arm in ARMS:
        t = Counter(out["arms"][arm])
        lines.append(f"| {names[arm]} | {t['verdict_cases']} | {t['fully_right_cases']} | {t['pair_agree']} of {t['pairs']} | {t['pair_unsafe']} | "
                     f"{t['pair_over_cautious']} | {t['pair_other_difference']} | {t['no_verdict_pairs']} |")
    lines += ["", "| Comparison (cases right) | First only | Second only | Exact McNemar p (post hoc) |", "|---|---|---|---|"]
    for name, row in out["paired"].items():
        lines.append(f"| {name.replace('_', ' ')} | {row['first_right_second_not']} | {row['second_right_first_not']} | {row['exact_mcnemar_p_post_hoc']:.4f} |")
    lines += ["", "| Case | " + " | ".join(names[a] for a in ARMS) + " |", "|---|" + "---|" * len(ARMS)]
    for cid in cases:
        lines.append(f"| {cid} | " + " | ".join(out["per_case"][cid][a] for a in ARMS) + " |")
    (ROOT / "post_sweep" / "out" / "long_context_contrast.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "paper_build" / "tables" / "long_context.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
