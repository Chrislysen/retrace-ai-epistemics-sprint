#!/usr/bin/env python3
"""Scaling run: which withdrawn-support decisions the direct answers still assert. No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026. Written after the scaling run's results had
been seen; exploratory, not part of prereg/scale_rules.md.

    python post_sweep/scale_error_paths.py

A decision "loses support" when it is supported before the withdrawal and not after it. Such a decision is called
copy-mediated here when it would still be supported if every copy counted as a record of its own (usable whenever the
copy itself is active and not withdrawn), that is, when seeing the loss requires following a copy back to a withdrawn
source. Otherwise the loss is direct: it shows without following any copy link.

Inputs: post_sweep/out/scale/corpus.json and the run journals. Output: post_sweep/out/scale/error_paths.json
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_prose24 import independent_rows, reference, supported  # noqa: E402

MODELS = ["gemma-4-31b-it", "gemma-4-26b-a4b-it", "qwen3.8-27b", "deepseek-v4-flash", "glm-53-flash"]
CONDITIONS = ["formal_fresh", "prose_fresh", "prose_extract"]


def copies_as_records(case):
    """The same graph with every copy turned into a root: its parents no longer matter."""
    flat = {name: [dict(row) for row in case[name]] for name in ("evidence", "claims", "decisions")}
    for row in flat["evidence"]:
        row["kind"], row["parents"] = "root", []
    return flat


def main():
    scale = ROOT / "post_sweep" / "out" / "scale"
    corpus = json.loads((scale / "corpus.json").read_text(encoding="utf-8"))
    kind, sizes, kind_all = {}, {}, {}
    census, census_all = Counter(), Counter()
    for item in corpus:
        case, size = item["case"], item["review_notes"]["size"]
        sizes[item["id"]] = size
        ref = reference(item)
        before, after = supported(case), supported(case, case["revoke"])
        lost = sorted(d for d in before if before[d] and not after[d])
        assert lost == sorted(ref["lost"]), item["id"]
        flat_after = supported(copies_as_records(case), case["revoke"])
        for d in lost:
            kind[(item["id"], d)] = "copy_mediated" if flat_after[d] else "direct"
            census[f"{size}|{kind[(item['id'], d)]}"] += 1
        # the same split for every decision without support after the withdrawal, never-supported ones included
        # (a copy of a record that was unavailable from the start is unusable too)
        for d in after:
            if not after[d]:
                kind_all[(item["id"], d)] = "copy_mediated" if flat_after[d] else "direct"
                census_all[f"{size}|{kind_all[(item['id'], d)]}"] += 1
    out = {"definition": "copy_mediated: the decision loses support only because a copy's source was withdrawn; "
                         "direct: the loss shows without following a copy link",
           "decisions_that_lose_support": dict(sorted(census.items())),
           "decisions_without_support_after_the_withdrawal": dict(sorted(census_all.items())), "models": {}}
    print("decisions that lose support, by size and kind:", dict(sorted(census.items())))
    print("decisions without support after the withdrawal, by size and kind:", dict(sorted(census_all.items())))
    for model in MODELS:
        base = scale / "runs" / model
        if not base.exists():   # part E1 of the extension: the second model without a reasoning phase
            base = scale / "ext" / "main" / model
        responses = []
        for seg in sorted(base.glob("seg-*")) if base.exists() else []:
            path = seg / "responses.jsonl"
            if path.exists():
                responses += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not responses:
            continue
        by_slot = {}
        for r in responses:  # one record per slot, as in score_scale.py
            slot = (r["case_id"], r["condition"])
            if slot not in by_slot or r.get("http_status") != 429 or by_slot[slot].get("http_status") == 429:
                by_slot[slot] = r
        rows = {(k[0], k[1]): v for k, v in independent_rows(corpus, list(by_slot.values())).items() if k[2] == "final"}
        cells = Counter()
        for (case_id, decision), which in kind.items():
            for condition in CONDITIONS:
                row = rows[(case_id, condition)]
                if not row["semantic_valid"]:
                    continue
                for scope in (sizes[case_id], "all"):
                    cells[f"{condition}|{scope}|{which}|answered"] += 1
                    cells[f"{condition}|{scope}|{which}|still_asserted"] += bool(row["predictions"][decision])
        for (case_id, decision), which in kind_all.items():
            for condition in CONDITIONS:
                row = rows[(case_id, condition)]
                if not row["semantic_valid"]:
                    continue
                for scope in (sizes[case_id], "all"):
                    cells[f"{condition}|{scope}|unsupported_{which}|answered"] += 1
                    cells[f"{condition}|{scope}|unsupported_{which}|asserted"] += bool(row["predictions"][decision])
        out["models"][model] = dict(sorted(cells.items()))
        print(f"== {model}")
        for condition in CONDITIONS:
            for scope in ("S", "M", "L", "all"):
                parts = [f"{which} {cells[f'{condition}|{scope}|{which}|still_asserted']} of {cells[f'{condition}|{scope}|{which}|answered']}"
                         for which in ("direct", "copy_mediated")]
                both = [f"{which} {cells[f'{condition}|{scope}|unsupported_{which}|asserted']} of {cells[f'{condition}|{scope}|unsupported_{which}|answered']}"
                        for which in ("direct", "copy_mediated")]
                print(f"   {condition:13s} {scope:3s} lost support, still asserted: " + "; ".join(parts) + "   | every unsupported decision, asserted: " + "; ".join(both))
    # The same split on the first-day experiment of 13 November: 24 authored cases, answers that already existed.
    first = json.loads((ROOT / "data" / "prose-holdout.json").read_text(encoding="utf-8"))
    first_kind = {}
    for item in first:
        case = item["case"]
        after, flat_after = supported(case, case["revoke"]), supported(copies_as_records(case), case["revoke"])
        for d in after:
            if not after[d]:
                first_kind[(item["id"], d)] = "copy_mediated" if flat_after[d] else "direct"
    out["first_day"] = {"unsupported_decisions": dict(Counter(first_kind.values())), "models": {}}
    print("first-day experiment, unsupported decisions by kind:", dict(Counter(first_kind.values())))
    cells_of_interest = [("formal_fresh", "final"), ("prose_fresh", "final"), ("prose_history", "withdrawn"), ("prose_no_commitment", "final")]
    for model in ("gemma-4-31b-it", "glm-53-flash"):
        folders = [ROOT / "results" / "prose-heldout" / model]
        if model == "gemma-4-31b-it":
            folders.append(ROOT / "results" / "prose-continuation" / model)
        records = []
        for folder in folders:
            log = folder / "responses.jsonl"
            if log.exists():
                records += [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
        rows = independent_rows(first, records)
        cells = Counter()
        for (case_id, decision), which in first_kind.items():
            for condition, phase in cells_of_interest:
                row = rows.get((case_id, condition, phase))
                if not row or not row["semantic_valid"]:
                    continue
                cells[f"{condition}|{which}|answered"] += 1
                cells[f"{condition}|{which}|asserted"] += bool(row["predictions"][decision])
        out["first_day"]["models"][model] = dict(sorted(cells.items()))
        print(f"== first day, {model}")
        for condition, phase in cells_of_interest:
            print(f"   {condition:20s} asserted: " + "; ".join(
                f"{which} {cells[f'{condition}|{which}|asserted']} of {cells[f'{condition}|{which}|answered']}" for which in ("direct", "copy_mediated")))
    (scale / "error_paths.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
