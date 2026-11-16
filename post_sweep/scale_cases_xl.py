#!/usr/bin/env python3
"""Cases for part E8 of the extension (prereg/scale_extension_addendum_5.md): twelve cases with 80 records. No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026.

    python post_sweep/scale_cases_xl.py

The main run stops at 40 records. This script generates twelve cases at the next step of its size ladder (80 records,
40 claims, 12 decisions, 4 records withdrawn) with post_sweep/scale_cases.py itself: the same graph builder with its
40 percent copies, the same acceptance filter, prose templates, reference engine and independent check. Two things
differ and are stated here: the size entry "XL" is added to that script's table at run time, and its list of 24 claim
topics is doubled with a "phase two" variant of each, because 40 claims need 40 distinct topics. The main run's files
are not touched.

Output, under post_sweep/out/scale/ext/:
  corpus_xl.json, sessions_xl.json (three first-day conditions), sessions_xl_working.json (visible working, part E2)
  withdrawal_reference_xl.json, sessions_xl_withdrawal_answer.json, sessions_xl_withdrawal_working.json (search task)
  cases_xl_summary.json
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

import scale_cases as base  # noqa: E402
import scale_withdrawal_task as search  # noqa: E402
from recompute_prose24 import supported  # noqa: E402
from scale_ext_sessions import derive  # noqa: E402

SEED = 2026111603
CASES = 12
SIZE = "XL"
SEARCH_LIMIT = 3   # the largest smallest set in the main run's cases has three records

base.SIZES[SIZE] = {"records": 80, "claims": 40, "decisions": 12, "revoke": 4, "min_lost": 2}
base.TOPICS = list(base.TOPICS) + [f"{topic} phase two" for topic in base.TOPICS]


def copies_as_records(case):
    flat = {name: [dict(row) for row in case[name]] for name in ("evidence", "claims", "decisions")}
    for row in flat["evidence"]:
        row["kind"], row["parents"] = "root", []
    return flat


def main():
    master = random.Random(SEED)
    corpus, tries = [], {}
    for number in range(1, CASES + 1):
        domain = base.DOMAINS[number - 1]
        for attempt in range(1, 20001):
            rng = random.Random(master.getrandbits(64))
            case = base.build_graph(rng, SIZE)
            ident = f"scale-{SIZE}-{number:02d}"
            item = {"id": ident, "family": f"size_{SIZE}", "title": f"{domain}: review packet {SIZE}{number}", "case": case,
                    "domain": domain}
            try:
                keep = base.interesting(item, SIZE)
            except ValueError:
                keep = False
            if keep:
                break
        else:
            raise SystemExit(f"no acceptable case for {ident}")
        tries[ident] = attempt
        used = {row["id"] for kind in ("evidence", "claims", "decisions") for row in case[kind]}
        item["documents"], item["event_text"] = base.prose(rng, case, domain, used)
        item["decision_questions"] = [{"id": d["id"], "text": f"Is the decision to {d['label']} currently supported under this packet?"}
                                      for d in case["decisions"]]
        words = sum(len(doc["text"].split()) for doc in item["documents"])
        item["review_notes"] = {"synthetic": True, "design_seed": SEED, "size": SIZE, "set": SIZE, "prose_word_count": words,
                                "limitations": "Fictional generated prose from sentence templates; not natural documents."}
        corpus.append(item)

    summary = {"seed": SEED, "cases": len(corpus), "generation_attempts": tries, "evaluator_disagreements": 0,
               "prose_structure_problems": [], "words": [], "copies": 0, "decisions": 0, "supported_after": 0, "lost": 0,
               "protected": 0, "never_supported": 0, "unsupported_copy_mediated": 0, "unsupported_direct": 0}
    for item in corpus:
        gold, mine = base.gold_for(item), base.independent_reference(item)
        if gold["initial"] != mine["initial"] or gold["final"] != mine["final"] or gold["lost"] != mine["lost"] \
                or gold["protected"] != mine["protected"]:
            summary["evaluator_disagreements"] += 1
        text = " ".join(doc["text"] for doc in item["documents"])
        for row in item["case"]["evidence"]:
            if text.count(f"Record {row['id']}") != 1:
                summary["prose_structure_problems"].append([item["id"], row["id"]])
        for row in item["case"]["claims"]:
            if text.count(f"laim {row['id']}") + text.count(f"identifier {row['id']}") < 1:
                summary["prose_structure_problems"].append([item["id"], row["id"]])
        for row in item["case"]["decisions"]:
            if text.count(f"ecision {row['id']}") != 1:
                summary["prose_structure_problems"].append([item["id"], row["id"]])
        case = item["case"]
        after, flat_after = supported(case, case["revoke"]), supported(copies_as_records(case), case["revoke"])
        summary["words"].append(item["review_notes"]["prose_word_count"])
        summary["copies"] += sum(row["kind"] == "copy" for row in case["evidence"])
        summary["decisions"] += len(gold["final"])
        summary["supported_after"] += sum(gold["final"].values())
        summary["lost"] += len(gold["lost"])
        summary["protected"] += len(gold["protected"])
        summary["never_supported"] += len(gold["initially_unsupported"])
        summary["unsupported_copy_mediated"] += sum((not after[d]) and flat_after[d] for d in after)
        summary["unsupported_direct"] += sum((not after[d]) and not flat_after[d] for d in after)
    summary["words_min_max"] = [min(summary["words"]), max(summary["words"])]
    del summary["words"]
    if summary["evaluator_disagreements"] or summary["prose_structure_problems"]:
        print(json.dumps(summary, indent=1))
        raise SystemExit("case set rejected")

    sessions = [s for s in base.make_prose_sessions(corpus) if s["condition"] in base.KEEP_CONDITIONS]
    manifest = {"instructions": base.DECISION_INSTRUCTIONS, "sessions": sessions}
    text, working, _ = derive(manifest)

    # the search task: reference by exhaustive search up to SEARCH_LIMIT records, and the two instructions of part E5
    reference, by_size = {}, {}
    for item in corpus:
        case = item["case"]
        reference[item["id"]] = search.smallest_withdrawals(case, case["revoke"], limit=SEARCH_LIMIT)
        for row in reference[item["id"]].values():
            key = "above_limit" if row["k"] is None else str(row["k"])
            by_size[key] = by_size.get(key, 0) + 1
    summary["search_reference_by_smallest_size"] = by_size
    search_sessions = {}
    for name, tail, condition in (("sessions_xl_withdrawal_answer.json", search.ANSWER_ONLY, "withdrawal_answer"),
                                  ("sessions_xl_withdrawal_working.json", search.WORKING_FIRST, "withdrawal_working")):
        instruction = search.instructions(tail)
        rows = []
        for s in sessions:
            if s["condition"] != "prose_fresh":
                continue
            step = s["steps"][0]
            if not step["input"].endswith(search.OLD_TASK_LINE):
                raise SystemExit("unexpected task line in " + s["case_id"])
            new_step = {**step, "input": step["input"][:-len(search.OLD_TASK_LINE)] + search.NEW_TASK_LINE}
            rows.append({**s, "condition": condition, "response_kind": "working", "instructions": instruction, "steps": [new_step]})
        search_sessions[name] = json.dumps({"instructions": instruction, "sessions": rows}, ensure_ascii=False) + "\n"

    out = ROOT / "post_sweep" / "out" / "scale" / "ext"
    texts = {"corpus_xl.json": json.dumps(corpus, indent=1, ensure_ascii=False) + "\n",
             "sessions_xl.json": json.dumps(manifest, ensure_ascii=False) + "\n",
             "sessions_xl_working.json": json.dumps({"instructions": text, "sessions": working}, ensure_ascii=False) + "\n",
             "withdrawal_reference_xl.json": json.dumps({"limit": SEARCH_LIMIT, "by_smallest_size": by_size, "cases": reference}, indent=1) + "\n",
             **search_sessions}
    for name, body in texts.items():
        (out / name).write_text(body, encoding="utf-8", newline="\n")
        summary[name + "_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    summary["sessions"] = len(sessions)
    summary["working_sessions"] = len(working)
    summary["longest_prompt_chars"] = max(len(s["steps"][0]["input"]) for s in sessions)
    (out / "cases_xl_summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
