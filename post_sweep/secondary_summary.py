#!/usr/bin/env python3
"""Secondary sweep summaries: failure classes per arm, refuter, K10, preference probes, long context, timing.

Sprint addition, written with AI assistance on Sunday 15 November 2026. Reads post_sweep/out/sweep_tables.json,
the rerun score in post_sweep/out/sweep_frozen/score.json (identical to the project's saved score) and the launch
journals. Writes paper_build/tables/sweep_secondary.md and post_sweep/out/sweep_secondary.json.

    python post_sweep/secondary_summary.py
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "post_sweep"))
from recompute_sweep import LAUNCHES, PRIMARY, DIAGNOSTIC, read_json, read_jsonl  # noqa: E402


def rate(x):
    return f"{x['numerator']} of {x['denominator']}" if isinstance(x, dict) and "numerator" in x else str(x)


def main():
    tables = read_json("post_sweep/out/sweep_tables.json")
    score = read_json("post_sweep/out/sweep_frozen/score.json")
    amended = score["amended_recovered_complete"]
    first = amended["views"]["first_attempt"]
    out = {}
    lines = ["# Secondary sweep summaries", "",
             "Produced by `post_sweep/secondary_summary.py` from the rerun of the project's frozen scorer and the launch journals.", ""]

    # failure classes per model and condition
    arms = tables["accounting_by_model_and_condition"]
    conditions = sorted({k.split("|")[1] for k in arms})
    lines += ["## Slot outcomes by model and condition", "",
              "Each cell: completed / truncated at the token cap / provider or transport failure / not issued or interrupted.", "",
              "| Condition | " + " | ".join(PRIMARY + [DIAGNOSTIC]) + " |", "|---|" + "---|" * (len(PRIMARY) + 1)]
    for cond in conditions:
        row = [cond]
        for model in PRIMARY + [DIAGNOSTIC]:
            c = Counter(arms.get(f"{model}|{cond}", {}))
            total = sum(c.values())
            row.append("-" if not total else f"{c['completed']} / {c['truncated']} / {c['operational'] + c['rate_limited']} / "
                       f"{c['not_issued_dependency'] + c['host_interruption']}")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # refuter
    lines += ["## Adversarial refuter (60 cases per model: 30 faithful seeds, 30 deficient seeds)", "",
              "| Model | Faithful seed: abstained (correct) | Faithful seed: located objection | Deficient seed: source-aligned consequential proposal (correct) | Located proposals | Located but semantically wrong |",
              "|---|---|---|---|---|---|"]
    out["refuter"] = {}
    for model in PRIMARY:
        r = first["primary_models"][model]["refuter"]
        out["refuter"][model] = r
        lines.append(f"| {model} | {rate(r['controls']['faithful']['correct'])} | {rate(r['controls']['faithful']['located_objection'])} | "
                     f"{rate(r['controls']['deficient']['correct'])} | {r['located_proposals']} | {r['located_semantically_wrong_objections']} |")
    lines.append("")

    # Gemma-only diagnostics: print whatever blocks exist, compactly
    gemma = first["primary_models"]["gemma-4-31b-it"]
    extra = {k: v for k, v in gemma.items() if k not in ("scheduled_slots", "conditions", "family_recovery", "refuter", "calibration", "partition_summaries")}
    out["gemma_extra_keys"] = sorted(extra)
    lines += ["## Gemma-only diagnostics (keys present in the score)", "", ", ".join(sorted(extra)) or "none", ""]
    for key, value in extra.items():
        text = json.dumps(value, ensure_ascii=False)
        lines += [f"### {key}", "", "```", text[:1800] + (" ..." if len(text) > 1800 else ""), "```", ""]
    qwen = first.get("qwen3_5_397b_diagnostic_only", {})
    lines += ["## Qwen 3.5 diagnostic", "", "```", json.dumps({k: v for k, v in qwen.items() if k != "conditions"}, ensure_ascii=False)[:1200], "```", ""]
    for name, cell in sorted(qwen.get("conditions", {}).items()):
        lines.append(f"- {name}: correct {rate(cell.get('correct'))}; completed {rate(cell.get('provider_completed'))}")
    lines.append("")

    # family recovery blocks for every model
    lines += ["## Family recovery as reported by the frozen scorer", "",
              "| Model | Arm | Strict exact family | Exact family incl. fenced | Mean precision | Mean recall | Three-state fidelity |", "|---|---|---|---|---|---|---|"]
    for model in PRIMARY:
        for arm, block in first["primary_models"][model]["family_recovery"].items():
            if block.get("scheduled_cases"):
                lines.append(f"| {model} | {arm} | {rate(block['strict_exact_family'])} | {rate(block['semantic_admission_sensitivity'])} | "
                             f"{block['mean_precision']:.3f} | {block['mean_recall']:.3f} | {rate(block['strict_actual_three_state_fidelity'])} |")
    lines.append("")

    # timing and tokens from the journals
    timing = {}
    usage = defaultdict(Counter)
    for name, folder in LAUNCHES:
        rows = read_jsonl(f"{folder}/responses.jsonl")
        stamps = sorted(r["at"] for r in rows if r.get("at"))
        timing[name] = {"responses": len(rows), "first": stamps[0] if stamps else None, "last": stamps[-1] if stamps else None}
        for r in rows:
            u = r.get("usage") or {}
            usage[r["model"]]["responses"] += 1
            usage[r["model"]]["input_tokens"] += u.get("input_tokens") or 0
            usage[r["model"]]["output_tokens"] += u.get("output_tokens") or 0
            usage[r["model"]]["latency_ms_total"] += r.get("latency_ms") or 0
    out["timing"] = timing
    out["usage"] = {m: dict(c) for m, c in usage.items()}
    lines += ["## Launches", "", "| Launch | Response records | First record (UTC) | Last record (UTC) |", "|---|---|---|---|"]
    for name, t in timing.items():
        lines.append(f"| v6{name} | {t['responses']} | {t['first']} | {t['last']} |")
    lines += ["", "## Tokens and latency by model (all recorded responses)", "",
              "| Model | Responses | Input tokens | Output tokens | Mean latency (s) |", "|---|---|---|---|---|"]
    for model in PRIMARY + [DIAGNOSTIC]:
        c = usage[model]
        mean = c["latency_ms_total"] / c["responses"] / 1000 if c["responses"] else 0
        lines.append(f"| {model} | {c['responses']} | {c['input_tokens']:,} | {c['output_tokens']:,} | {mean:.1f} |")
    lines.append("")
    out["request_accounting"] = score["request_accounting"]
    out["status"] = {"recovered": score["status"], "frozen_diagnostic": score["frozen_diagnostic"]["status"],
                     "amended": amended["status"], "confirmatory_status": amended["confirmatory_status"],
                     "finalized_slot_operational_failures": amended["finalized_slot_operational_failures"]}

    (ROOT / "post_sweep" / "out" / "sweep_secondary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "paper_build" / "tables" / "sweep_secondary.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("\n".join(lines))
    print(json.dumps(out["status"], indent=1))


if __name__ == "__main__":
    main()
