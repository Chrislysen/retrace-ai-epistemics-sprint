#!/usr/bin/env python3
"""Part E5 of the extension (prereg/scale_extension_addendum_3.md): the smallest further withdrawal. No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026.

    python post_sweep/scale_withdrawal_task.py

The main run asks which decisions are supported. This part asks a search question on the same 36 cases, in the state
after the withdrawal: for each decision, name a smallest set of further records whose withdrawal would leave it without
support. Finding a smallest such set is the problem of Proposition B.1; checking a named set takes one evaluation.

Writes, under post_sweep/out/scale/ext/:
  withdrawal_reference.json           the smallest size for every decision, by exhaustive search over record subsets
  sessions_withdrawal_answer.json     the 36 prose packets, answer only
  sessions_withdrawal_working.json    the same packets, working shown first
"""
import hashlib
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_prose24 import supported  # noqa: E402
from retrace.prose_sessions import DECISION_INSTRUCTIONS  # noqa: E402

LIMIT = 5
OLD_TASK_LINE = "\n\nReturn the current decision-support map."
NEW_TASK_LINE = "\n\nFor each decision, name a smallest set of further records to withdraw so that it has no support."
TASK = ("For every requested decision, name a smallest set of further evidence records whose withdrawal would leave the "
        "decision without support. A withdrawn record also disables every copy that needs it. Use only records that are "
        "available now. If the decision has no support now, the set is empty.\n")
ANSWER_ONLY = (TASK + 'Return ONLY {"withdrawals":{"EXACT_DECISION_ID":["RECORD_ID"]}} with every requested decision exactly '
               "once, and no explanation. Do not use Markdown fences.")
WORKING_FIRST = (TASK + "First work through the packet in plain text, step by step: which evidence records are usable now, "
                 "which claims are supported and through which routes, then for each decision which records its remaining "
                 "routes need.\n"
                 'Then end your answer with one final line that contains only {"withdrawals":{"EXACT_DECISION_ID":["RECORD_ID"]}} '
                 "with every requested decision exactly once. Do not use Markdown fences.")


def instructions(tail):
    cut = DECISION_INSTRUCTIONS.index("Return ONLY")
    return DECISION_INSTRUCTIONS[:cut] + tail


def available(case, revoked):
    return [row["id"] for row in case["evidence"] if row.get("active", True) and row["id"] not in revoked]


def smallest_withdrawals(case, revoked, limit=LIMIT):
    """decision -> {"k": smallest size or None above the limit, "example": one smallest set}. Exhaustive by size."""
    revoked = list(revoked)
    now = supported(case, revoked)
    out = {d: {"k": 0, "example": []} for d, ok in now.items() if not ok}
    open_decisions = [d for d, ok in now.items() if ok]
    candidates = available(case, revoked)
    for k in range(1, limit + 1):
        if not open_decisions:
            break
        for subset in itertools.combinations(candidates, k):
            after = supported(case, revoked + list(subset))
            for d in [d for d in open_decisions if not after[d]]:
                out[d] = {"k": k, "example": list(subset)}
                open_decisions.remove(d)
            if not open_decisions:
                break
    for d in open_decisions:
        out[d] = {"k": None, "example": None}
    return out


def main():
    scale = ROOT / "post_sweep" / "out" / "scale"
    ext = scale / "ext"
    corpus = json.loads((scale / "corpus.json").read_text(encoding="utf-8"))
    manifest = json.loads((scale / "sessions.json").read_text(encoding="utf-8"))
    reference, sizes = {}, {}
    for item in corpus:
        case = item["case"]
        reference[item["id"]] = smallest_withdrawals(case, case["revoke"])
        sizes[item["id"]] = item["review_notes"]["size"]
    summary = {}
    for case_id, per in reference.items():
        s = summary.setdefault(sizes[case_id], {"decisions": 0, "supported_now": 0, "by_smallest_size": {}})
        for d, row in per.items():
            s["decisions"] += 1
            s["supported_now"] += row["k"] != 0
            key = "above_limit" if row["k"] is None else str(row["k"])
            s["by_smallest_size"][key] = s["by_smallest_size"].get(key, 0) + 1
    body = json.dumps({"limit": LIMIT, "by_size": summary, "cases": reference}, indent=1) + "\n"
    (ext / "withdrawal_reference.json").write_text(body, encoding="utf-8", newline="\n")
    print("withdrawal_reference.json sha256", hashlib.sha256(body.encode("utf-8")).hexdigest())
    print(json.dumps(summary, indent=1))

    for name, tail, condition in (("sessions_withdrawal_answer.json", ANSWER_ONLY, "withdrawal_answer"),
                                  ("sessions_withdrawal_working.json", WORKING_FIRST, "withdrawal_working")):
        text = instructions(tail)
        sessions = []
        for s in manifest["sessions"]:
            if s["condition"] != "prose_fresh":
                continue
            step = s["steps"][0]
            if not step["input"].endswith(OLD_TASK_LINE):
                raise SystemExit("unexpected task line in " + s["case_id"])
            new_step = {**step, "input": step["input"][:-len(OLD_TASK_LINE)] + NEW_TASK_LINE}
            sessions.append({**s, "condition": condition, "response_kind": "working", "instructions": text, "steps": [new_step]})
        payload = json.dumps({"instructions": text, "sessions": sessions}, ensure_ascii=False) + "\n"
        (ext / name).write_text(payload, encoding="utf-8", newline="\n")
        print(f"{name}: {len(sessions)} sessions, sha256 {hashlib.sha256(payload.encode('utf-8')).hexdigest()}")
    print("--- instruction, answer only ---")
    print(instructions(ANSWER_ONLY))


if __name__ == "__main__":
    main()
