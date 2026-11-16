#!/usr/bin/env python3
"""Check of the search task's reference and scoring (parts E5 and E6) against the first-day engine. No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026, after part E5 had been scored.

    python post_sweep/check_withdrawal_reference.py

The reference of the search task (the smallest further withdrawal for every decision) and the validity of the sets
that models named were computed with the independent evaluator's support function, as the addendum says. This script
repeats both with the project's own engine (retrace.core.analyze): the smallest size for every decision by exhaustive
search, and the support of every decision after every set a model named. It reports how often the two agree. It
changes no score.

Output: post_sweep/out/scale/ext/withdrawal_reference_check.json
"""
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_prose24 import supported  # noqa: E402
from retrace.core import analyze  # noqa: E402
from score_withdrawal_task import EXT, SUITES, last_object, slots  # noqa: E402



def engine_supported(case, revoked):
    on = set(analyze(case, sorted(set(revoked)))["supported_decisions"])
    return {row["id"]: row["id"] in on for row in case["decisions"]}


def engine_smallest(case, revoked, limit):
    """decision -> smallest number of further records whose withdrawal leaves it without support (engine, exhaustive)."""
    revoked = list(revoked)
    now = engine_supported(case, revoked)
    out = {d: 0 for d, ok in now.items() if not ok}
    open_decisions = [d for d, ok in now.items() if ok]
    candidates = [row["id"] for row in case["evidence"] if row.get("active", True) and row["id"] not in revoked]
    for k in range(1, limit + 1):
        if not open_decisions:
            break
        for subset in itertools.combinations(candidates, k):
            after = engine_supported(case, revoked + list(subset))
            for d in [d for d in open_decisions if not after[d]]:
                out[d] = k
                open_decisions.remove(d)
            if not open_decisions:
                break
    for d in open_decisions:
        out[d] = None
    return out


def check(suite):
    corpus = json.loads(suite["corpus"].read_text(encoding="utf-8"))
    saved = json.loads(suite["reference"].read_text(encoding="utf-8"))
    reference, limit = saved["cases"], saved["limit"]
    sizes = {"decisions": 0, "same_smallest_size": 0, "different": []}
    examples = {"sets": 0, "leave_no_support_in_engine": 0}
    for item in corpus:
        case = item["case"]
        mine = engine_smallest(case, case["revoke"], limit)
        for d, row in reference[item["id"]].items():
            sizes["decisions"] += 1
            if mine.get(d) == row["k"]:
                sizes["same_smallest_size"] += 1
            else:
                sizes["different"].append({"case": item["id"], "decision": d, "reference": row["k"], "engine": mine.get(d)})
            if row["k"]:
                examples["sets"] += 1
                examples["leave_no_support_in_engine"] += not engine_supported(case, list(case["revoke"]) + list(row["example"]))[d]
    named = {"answers": 0, "sets_of_records_of_the_case": 0, "decision_states_compared": 0, "decision_states_equal": 0, "different": []}
    per_run = {}
    for part, _ in suite["parts"]:
        folder = EXT / part
        for model_dir in sorted(p for p in folder.iterdir() if p.is_dir()) if folder.exists() else []:
            _, _, by_case = slots(model_dir)
            run = per_run.setdefault(f"{part}/{model_dir.name}", {"answers": 0, "sets": 0})
            for item in corpus:
                record = by_case.get(item["id"])
                if record is None or record.get("error"):
                    continue
                answer = last_object(record.get("output_text"), "withdrawals")
                if answer is None:
                    continue
                named["answers"] += 1
                run["answers"] += 1
                case = item["case"]
                record_ids = {row["id"] for row in case["evidence"]}
                for d, value in answer.items():
                    if not (isinstance(value, list) and value and all(isinstance(x, str) for x in value) and set(value) <= record_ids):
                        continue
                    named["sets_of_records_of_the_case"] += 1
                    run["sets"] += 1
                    revoked = list(case["revoke"]) + list(value)
                    a, b = supported(case, revoked), engine_supported(case, revoked)
                    for decision in b:
                        named["decision_states_compared"] += 1
                        if a[decision] == b[decision]:
                            named["decision_states_equal"] += 1
                        else:
                            named["different"].append({"run": f"{part}/{model_dir.name}", "case": item["id"], "set": value, "decision": decision})
    ok = (not sizes["different"] and examples["sets"] == examples["leave_no_support_in_engine"] and not named["different"])
    return {"smallest_sizes": sizes, "reference_example_sets": examples, "sets_named_by_models": named, "per_run": per_run}, ok


def main():
    out, all_ok = {}, True
    for suite in SUITES:
        if not (suite["corpus"].exists() and suite["reference"].exists()):
            continue
        name = suite["json"].stem.replace("score_withdrawal", "cases") or "cases"
        out[name], ok = check(suite)
        all_ok = all_ok and ok
    # the main run's 36 cases keep their place at the top level, as in the first version of this file
    flat = dict(out.get("cases", {}))
    if "cases_xl" in out:
        flat["cases_with_80_records"] = out["cases_xl"]
    (EXT / "withdrawal_reference_check.json").write_text(json.dumps(flat, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(flat, indent=1))
    print("RESULT:", "the engine and the independent evaluator agree on every size and every named set" if all_ok else "DIFFERENCES FOUND")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
