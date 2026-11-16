#!/usr/bin/env python3
"""Score the scaling run (prereg/scale_rules.md) twice: with the project's frozen first-day scorer and with the
independent evaluator of recompute_prose24.py. No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026.

    python post_sweep/score_scale.py

Inputs: post_sweep/out/scale/corpus.json and post_sweep/out/scale/runs/<model>/seg-*/{requests,responses}.jsonl
Outputs: post_sweep/out/scale/score.json, paper_build/tables/scale.md
"""
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_prose24 import independent_rows  # noqa: E402
from retrace.prose_eval import score_prose  # noqa: E402

MODELS = ["gemma-4-31b-it", "gemma-4-26b-a4b-it", "qwen3.8-27b", "deepseek-v4-flash", "glm-53-flash"]
# gemma-4-26b-a4b-it is part E1 of the extension (prereg/scale_extension_rules.md): same sessions, journals under ext/main
MAIN_RUN = ["gemma-4-31b-it", "qwen3.8-27b", "deepseek-v4-flash", "glm-53-flash"]
CONDITIONS = ["formal_fresh", "prose_fresh", "prose_extract"]
LABEL = {"formal_fresh": "Direct, formal ledger", "prose_fresh": "Direct, from prose", "prose_extract": "Compiled from prose, then computed"}
SIZES = ["S", "M", "L"]
SEED, DRAWS = 20261116, 5000


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def interval(deltas, rng):
    if not deltas:
        return None
    means = sorted(sum(rng.choices(deltas, k=len(deltas))) / len(deltas) for _ in range(DRAWS))
    return [round(100 * means[int(.025 * (DRAWS - 1))], 1), round(100 * means[int(.975 * (DRAWS - 1))], 1)]


def main():
    scale = ROOT / "post_sweep" / "out" / "scale"
    corpus = json.loads((scale / "corpus.json").read_text(encoding="utf-8"))
    size_of = {item["id"]: item["review_notes"]["size"] for item in corpus}
    out = {"seed": SEED, "draws": DRAWS, "models": {}, "scorer_disagreements": 0}
    lines = ["# Scaling run: direct answers and compiled declarations at three case sizes", "",
             "Produced by `post_sweep/score_scale.py` from `post_sweep/out/scale/`. Rules: `prereg/scale_rules.md`. "
             "12 cases per size and model. Unusable = provider failure, invalid output or rejected graph.", ""]
    pooled = defaultdict(Counter)
    for model in MODELS:
        base = scale / "runs" / model if model in MAIN_RUN else scale / "ext" / "main" / model
        requests, responses = [], []
        for seg in sorted(base.glob("seg-*")) if base.exists() else []:
            requests += jsonl(seg / "requests.jsonl")
            responses += jsonl(seg / "responses.jsonl")
        if not requests:
            continue
        keys = Counter((r["case_id"], r["condition"]) for r in requests)
        issued_twice = sum(v > 1 for v in keys.values())
        # One record per slot. A request rejected with HTTP 429 never reached a model and was issued again
        # (amendment 2): the answer that counts is the last one that is not a 429, else the last one.
        rejected_429 = sum(r.get("http_status") == 429 for r in responses)
        by_slot = {}
        for r in responses:
            slot = (r["case_id"], r["condition"])
            if slot not in by_slot or r.get("http_status") != 429 or by_slot[slot].get("http_status") == 429:
                by_slot[slot] = r
        all_responses, responses = responses, list(by_slot.values())
        frozen = score_prose(corpus, responses, bootstrap_repeats=200)
        frozen_rows = {(r["case_id"], r["condition"]): r for r in frozen["outcomes"] if r["phase"] == "final"}
        mine = {(k[0], k[1]): v for k, v in independent_rows(corpus, responses).items() if k[2] == "final"}
        answered = {(r["case_id"], r["condition"]) for r in responses}
        cells, per_case = {}, defaultdict(dict)
        disagreements = 0
        for item in corpus:
            for condition in CONDITIONS:
                key = (item["id"], condition)
                a, b = frozen_rows[key], mine[key]
                if (a["semantic_valid"], a["exact"], a["strict_valid"]) != (b["semantic_valid"], b["exact"], b["strict_valid"]):
                    disagreements += 1
                cell = cells.setdefault(f"{size_of[item['id']]}|{condition}", Counter())
                cell["cases"] += 1
                cell["issued"] += key in keys
                cell["answered"] += key in answered
                cell["provider_failures"] += bool(b["operational_failure"]) or (key in keys and key not in answered)
                cell["usable"] += b["semantic_valid"]
                cell["bare_json"] += b["strict_valid"]
                cell["fully_correct"] += b["exact"]
                cell["decisions"] += b["targets"]
                cell["errors_all_scheduled"] += b["errors"]
                if b["semantic_valid"]:
                    cell["decisions_usable"] += b["targets"]
                    cell["errors_usable"] += b["errors"]
                    cell["unsafe"] += b.get("missed", 0) + b.get("never_accepted", 0)
                    cell["dropped"] += b.get("protected_dropped", 0) + b.get("unaffected_dropped", 0)
                    cell["unsupported_targets"] += b["class_sizes"]["lost"] + b["class_sizes"]["never"]
                    cell["supported_targets"] += b["class_sizes"]["protected"] + b["class_sizes"]["unaffected"]
                    # the four kinds of wrong decision, each over the decisions of its class in usable answers
                    for name, size in (("missed", "lost"), ("protected_dropped", "protected"),
                                       ("unaffected_dropped", "unaffected"), ("never_accepted", "never")):
                        cell[name] += b.get(name, 0)
                        cell[name + "_of"] += b["class_sizes"][size]
                    if condition == "prose_extract":
                        cell["graph_exact"] += bool(b["graph_exact"])
                        cell["accepted_graph_wrong_decision"] += not b["exact"]
                per_case[item["id"]][condition] = b
        for name, cell in cells.items():
            for k, v in cell.items():
                pooled[name][k] += v
        rng = random.Random(SEED)
        contrasts = {}
        for size in SIZES:
            ids = [i["id"] for i in corpus if size_of[i["id"]] == size]
            deltas = [(per_case[i]["prose_fresh"]["errors"] - per_case[i]["prose_extract"]["errors"]) / per_case[i]["prose_fresh"]["targets"]
                      for i in ids]
            contrasts[size] = {
                "cases": len(ids),
                "fully_correct_prose": sum(per_case[i]["prose_fresh"]["exact"] for i in ids),
                "fully_correct_compiled": sum(per_case[i]["prose_extract"]["exact"] for i in ids),
                "compiled_right_prose_wrong": sum(per_case[i]["prose_extract"]["exact"] and not per_case[i]["prose_fresh"]["exact"] for i in ids),
                "prose_right_compiled_wrong": sum(per_case[i]["prose_fresh"]["exact"] and not per_case[i]["prose_extract"]["exact"] for i in ids),
                "accuracy_difference_points_all_scheduled": round(100 * sum(deltas) / len(deltas), 1),
                "interval_95": interval(deltas, rng)}
            # Second comparison of the rules: only cases where both conditions gave a usable answer, unsafe decisions only.
            both = [i for i in ids if per_case[i]["prose_fresh"]["semantic_valid"] and per_case[i]["prose_extract"]["semantic_valid"]]
            unsafe = lambda row: row.get("missed", 0) + row.get("never_accepted", 0)  # noqa: E731
            contrasts[size]["both_usable"] = {
                "cases": len(both),
                "unsupported_decisions": sum(per_case[i]["prose_fresh"]["class_sizes"]["lost"] + per_case[i]["prose_fresh"]["class_sizes"]["never"] for i in both),
                "unsafe_prose": sum(unsafe(per_case[i]["prose_fresh"]) for i in both),
                "unsafe_compiled": sum(unsafe(per_case[i]["prose_extract"]) for i in both),
                "cases_with_unsafe_prose": sum(unsafe(per_case[i]["prose_fresh"]) > 0 for i in both),
                "cases_with_unsafe_compiled": sum(unsafe(per_case[i]["prose_extract"]) > 0 for i in both),
                "fully_correct_prose": sum(per_case[i]["prose_fresh"]["exact"] for i in both),
                "fully_correct_compiled": sum(per_case[i]["prose_extract"]["exact"] for i in both)}
        usage = defaultdict(list)
        for r in responses:
            if not r.get("error") and r.get("usage"):
                usage[f"{size_of[r['case_id']]}|{r['condition']}"].append((r["usage"].get("output_tokens") or 0, (r.get("latency_ms") or 0) / 1000))
        effort = {k: {"answers": len(v), "median_output_tokens": sorted(x[0] for x in v)[len(v) // 2],
                      "median_seconds": round(sorted(x[1] for x in v)[len(v) // 2], 1)} for k, v in usage.items()}
        out["models"][model] = {"requests_issued": len(requests), "responses": len(all_responses), "slots_issued_twice": issued_twice,
                                "requests_rejected_with_429": rejected_429, "slots_with_an_answer_record": len(responses),
                                "effort": effort,
                                "segments": len(list(base.glob("seg-*"))), "scorer_disagreements": disagreements,
                                "response_models": dict(Counter(str(r.get("response_model")) for r in responses)),
                                "errors": dict(Counter(f"{r.get('error')} {r.get('http_status') or ''}".strip() for r in responses if r.get("error"))),
                                "observed_cost_credits": round(sum(r.get("observed_token_cost_credits_uncached") or 0 for r in all_responses), 4),
                                "cells": {k: dict(v) for k, v in cells.items()}, "compiled_minus_prose": contrasts}
        out["scorer_disagreements"] += disagreements
        lines += [f"## {model}", "",
                  f"Requests sent {len(requests)} ({rejected_429} rejected with HTTP 429 before inference), slots with an answer record "
                  f"{len(responses)} of 108, of which failed or cut off {sum(1 for r in responses if r.get('error'))}; "
                  f"frozen scorer and independent evaluator differ on {disagreements} slots.", "",
                  "| Size | Condition | Usable /12 | Fully correct /12 | Decision errors, all scheduled | Unsafe (usable) | Dropped (usable) | Graph exact /12 |",
                  "|---|---|---|---|---|---|---|---|"]
        for size in SIZES:
            for condition in CONDITIONS:
                c = cells[f"{size}|{condition}"]
                lines.append(f"| {size} | {LABEL[condition]} | {c['usable']} | {c['fully_correct']} | {c['errors_all_scheduled']} of {c['decisions']} | "
                             f"{c['unsafe']} of {c['unsupported_targets']} | {c['dropped']} of {c['supported_targets']} | "
                             f"{c['graph_exact'] if condition == 'prose_extract' else ''} |")
        lines += ["", "| Size | Condition | Withdrawn support still asserted | Never supported, asserted | Surviving alternative dropped | "
                  "Untouched decision dropped | Median output tokens | Median seconds |", "|---|---|---|---|---|---|---|---|"]
        for size in SIZES:
            for condition in CONDITIONS:
                c = cells[f"{size}|{condition}"]
                e = effort.get(f"{size}|{condition}", {})
                lines.append(f"| {size} | {LABEL[condition]} | {c['missed']} of {c['missed_of']} | {c['never_accepted']} of {c['never_accepted_of']} | "
                             f"{c['protected_dropped']} of {c['protected_dropped_of']} | {c['unaffected_dropped']} of {c['unaffected_dropped_of']} | "
                             f"{e.get('median_output_tokens', '')} | {e.get('median_seconds', '')} |")
        lines += ["", "| Size | Fully correct: prose | Fully correct: compiled | Compiled right, prose wrong | Prose right, compiled wrong | "
                  "Accuracy difference, points [95% interval] |", "|---|---|---|---|---|---|"]
        for size in SIZES:
            c = contrasts[size]
            lines.append(f"| {size} | {c['fully_correct_prose']} | {c['fully_correct_compiled']} | {c['compiled_right_prose_wrong']} | "
                         f"{c['prose_right_compiled_wrong']} | {c['accuracy_difference_points_all_scheduled']:+.1f} {c['interval_95']} |")
        lines += ["", "| Size | Cases usable in both | Unsafe decisions: prose | Unsafe decisions: compiled | Fully correct: prose | Fully correct: compiled |",
                  "|---|---|---|---|---|---|"]
        for size in SIZES:
            u = contrasts[size]["both_usable"]
            lines.append(f"| {size} | {u['cases']} | {u['unsafe_prose']} of {u['unsupported_decisions']} | {u['unsafe_compiled']} of {u['unsupported_decisions']} | "
                         f"{u['fully_correct_prose']} | {u['fully_correct_compiled']} |")
        lines.append("")
    out["pooled"] = {k: dict(v) for k, v in pooled.items()}
    # Every request this run sent, the four connection tests under smoke/ included.
    sent = Counter()
    for folder in ("runs", "smoke"):
        for path in sorted((scale / folder).glob("*/seg-*/responses.jsonl")):
            for r in jsonl(path):
                sent[folder + "_responses"] += 1
                sent[folder + "_http_429"] += r.get("http_status") == 429
                sent[folder + "_http_504"] += r.get("http_status") == 504
                sent[folder + "_other_errors"] += bool(r.get("error")) and r.get("http_status") not in (429, 504)
                sent[folder + "_observed_cost_credits_x10000"] += round(10000 * (r.get("observed_token_cost_credits_uncached") or 0))
        for path in sorted((scale / folder).glob("*/seg-*/requests.jsonl")):
            sent[folder + "_requests"] += len(jsonl(path))
    out["requests"] = dict(sent)
    lines += ["## Requests", "", f"Scheduled runs: {sent['runs_requests']} requests written to the journals, {sent['runs_responses']} answer records "
              f"({sent['runs_http_429']} HTTP 429, {sent['runs_http_504']} HTTP 504, {sent['runs_other_errors']} other errors). "
              f"Connection tests: {sent['smoke_requests']} requests. Observed token cost {(sent['runs_observed_cost_credits_x10000'] + sent['smoke_observed_cost_credits_x10000']) / 10000:.4f} credits.", ""]
    if pooled:
        lines += [f"## All models pooled ({len(out['models'])} models)", "",
                  "| Size | Condition | Slots | Usable | Fully correct | Decision errors, all scheduled | Unsafe (usable) | Dropped (usable) | Graph exact |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for size in SIZES:
            for condition in CONDITIONS:
                c = pooled[f"{size}|{condition}"]
                lines.append(f"| {size} | {LABEL[condition]} | {c['cases']} | {c['usable']} | {c['fully_correct']} | "
                             f"{c['errors_all_scheduled']} of {c['decisions']} | {c['unsafe']} of {c['unsupported_targets']} | "
                             f"{c['dropped']} of {c['supported_targets']} | {c['graph_exact'] if condition == 'prose_extract' else ''} |")
    (scale / "score.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "paper_build" / "tables" / "scale.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
