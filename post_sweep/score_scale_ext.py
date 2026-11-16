#!/usr/bin/env python3
"""Score the extension of the scaling run (prereg/scale_extension_rules.md and its addendum). No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026.

    python post_sweep/score_scale_ext.py

Parts scored here (part E1, the second model on the main run's sessions, is scored by post_sweep/score_scale.py):
  working            E2: direct answers from prose with visible working, main run's 36 cases
  stream             E3: the reasoning models' compilations, issued again with streamed responses
  copyshare          E4: 24 cases with 40 records and 0 or 80 percent copies, three first-day conditions
  copyshare_working  E4: the same cases with visible working

Every answer is scored with the frozen first-day scorer and with the independent evaluator, as in the main run.
For a visible-working answer the scored answer is the last JSON object in the output whose only key is "decisions".

Outputs: post_sweep/out/scale/ext/score_ext.json, paper_build/tables/scale_ext.md
"""
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_prose24 import independent_rows, supported  # noqa: E402
from retrace.prose_eval import score_prose  # noqa: E402

SCALE = ROOT / "post_sweep" / "out" / "scale"
EXT = SCALE / "ext"
NAMES = {"gemma-4-31b-it": "Gemma", "gemma-4-26b-a4b-it": "Gemma-26B", "qwen3.8-27b": "Qwen27B",
         "deepseek-v4-flash": "DeepSeek", "glm-53-flash": "GLM-Flash"}
LABEL = {"formal_fresh": "Direct, formal ledger", "prose_fresh": "Direct, from prose", "prose_extract": "Compiled from prose",
         "prose_working": "Direct, from prose, visible working"}


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def slots(folder):
    """Requests sent and one answer record per slot: the last that is not an HTTP 429, else the last."""
    requests, responses = [], []
    for seg in sorted(folder.glob("seg-*")) if folder.exists() else []:
        requests += jsonl(seg / "requests.jsonl")
        responses += jsonl(seg / "responses.jsonl")
    by_slot = {}
    for r in responses:
        key = (r["case_id"], r["condition"])
        if key not in by_slot or r.get("http_status") != 429 or by_slot[key].get("http_status") == 429:
            by_slot[key] = r
    return requests, responses, by_slot


def last_decisions_object(text):
    """The last JSON object in `text` whose only key is "decisions", as a string, or None."""
    for match in reversed(list(re.finditer(r'\{\s*"decisions"\s*:', text or ""))):
        depth, in_string, escape = 0, False, False
        for position in range(match.start(), len(text)):
            ch = text[position]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[match.start():position + 1]
                    try:
                        value = json.loads(candidate)
                    except ValueError:
                        break
                    if isinstance(value, dict) and list(value) == ["decisions"]:
                        return candidate
                    break
    return None


def as_direct(record):
    """A visible-working record rewritten so that both scorers read its final answer as a direct answer from prose."""
    out = dict(record, condition="prose_fresh")
    if not record.get("error"):
        found = last_decisions_object(record.get("output_text"))
        out["output_text"] = found if found is not None else "no final decisions object"
        out["working_answer_found"] = found is not None
    return out


def copies_as_records(case):
    flat = {name: [dict(row) for row in case[name]] for name in ("evidence", "claims", "decisions")}
    for row in flat["evidence"]:
        row["kind"], row["parents"] = "root", []
    return flat


def kinds_of(corpus):
    """(case, decision) -> "copy_mediated" or "direct", for every decision without support after the withdrawal."""
    out = {}
    for item in corpus:
        case = item["case"]
        after, flat_after = supported(case, case["revoke"]), supported(copies_as_records(case), case["revoke"])
        for d in after:
            if not after[d]:
                out[(item["id"], d)] = "copy_mediated" if flat_after[d] else "direct"
    return out


def score(corpus, records, conditions, group_of, sent_keys):
    """Cells per group and condition, with the frozen scorer cross-checked against the independent evaluator."""
    frozen = {(r["case_id"], r["condition"]): r for r in score_prose(corpus, records, bootstrap_repeats=10)["outcomes"] if r["phase"] == "final"}
    mine = {(k[0], k[1]): v for k, v in independent_rows(corpus, records).items() if k[2] == "final"}
    kinds = kinds_of(corpus)
    by_key = {(r["case_id"], r["condition"]): r for r in records}
    cells, disagreements, effort = {}, 0, {}
    for item in corpus:
        for condition in conditions:
            key = (item["id"], condition)
            a, b = frozen[key], mine[key]
            if (a["semantic_valid"], a["exact"]) != (b["semantic_valid"], b["exact"]):
                disagreements += 1
            name = f"{group_of(item)}|{condition}"
            cell = cells.setdefault(name, Counter())
            cell["cases"] += 1
            cell["issued"] += key in sent_keys
            cell["provider_failures"] += bool(b["operational_failure"]) or (key in sent_keys and key not in by_key)
            cell["usable"] += b["semantic_valid"]
            cell["fully_correct"] += b["exact"]
            cell["decisions"] += b["targets"]
            cell["errors_all_scheduled"] += b["errors"]
            if b["semantic_valid"]:
                cell["decisions_usable"] += b["targets"]
                cell["errors_usable"] += b["errors"]
                cell["unsafe"] += b.get("missed", 0) + b.get("never_accepted", 0)
                cell["unsafe_of"] += b["class_sizes"]["lost"] + b["class_sizes"]["never"]
                cell["dropped"] += b.get("protected_dropped", 0) + b.get("unaffected_dropped", 0)
                cell["dropped_of"] += b["class_sizes"]["protected"] + b["class_sizes"]["unaffected"]
                if condition == "prose_extract":
                    cell["graph_exact"] += bool(b["graph_exact"])
                for (case_id, decision), which in kinds.items():
                    if case_id == item["id"]:
                        cell[f"{which}_of"] += 1
                        cell[f"{which}_asserted"] += bool(b["predictions"][decision])
                record = by_key.get(key)
                if record and record.get("usage"):
                    effort.setdefault(name, []).append((record["usage"].get("output_tokens") or 0, (record.get("latency_ms") or 0) / 1000))
    for name, values in effort.items():
        cells[name]["median_output_tokens"] = int(statistics.median(v[0] for v in values))
        cells[name]["median_seconds_x10"] = int(round(10 * statistics.median(v[1] for v in values)))
    return {k: dict(v) for k, v in cells.items()}, disagreements


def line(cell, condition):
    secs = cell.get("median_seconds_x10")
    text = (f"usable {cell['usable']:2d}/{cell['cases']} fully correct {cell['fully_correct']:2d} | wrong {cell.get('errors_usable', 0)} of "
            f"{cell.get('decisions_usable', 0)} (unsafe {cell.get('unsafe', 0)} of {cell.get('unsafe_of', 0)}, dropped {cell.get('dropped', 0)} of "
            f"{cell.get('dropped_of', 0)}) | asserted: copy-mediated {cell.get('copy_mediated_asserted', 0)} of {cell.get('copy_mediated_of', 0)}, "
            f"direct {cell.get('direct_asserted', 0)} of {cell.get('direct_of', 0)} | provider failures {cell['provider_failures']}, not issued "
            f"{cell['cases'] - cell['issued']} | tokens {cell.get('median_output_tokens', '-')}, seconds {'-' if secs is None else secs / 10}")
    if condition == "prose_extract":
        text += f" | graph exact {cell.get('graph_exact', 0)}"
    return text


def main():
    main_corpus = json.loads((SCALE / "corpus.json").read_text(encoding="utf-8"))
    size_of = lambda item: item["review_notes"]["size"]  # noqa: E731
    share_corpus_path = EXT / "corpus_copyshare.json"
    share_corpus = json.loads(share_corpus_path.read_text(encoding="utf-8")) if share_corpus_path.exists() else []
    set_of = lambda item: item["review_notes"]["set"]  # noqa: E731
    out = {"parts": {}, "scorer_disagreements": 0, "requests": Counter()}
    lines = ["# Extension of the scaling run", "",
             "Produced by `post_sweep/score_scale_ext.py`. Rules: `prereg/scale_extension_rules.md` and its addendum.", ""]

    xl_corpus_path = EXT / "corpus_xl.json"
    xl_corpus = json.loads(xl_corpus_path.read_text(encoding="utf-8")) if xl_corpus_path.exists() else []
    first_day = ["formal_fresh", "prose_fresh", "prose_extract"]
    plan = [("working", main_corpus, ["prose_working"], size_of, "E2 visible working, main run's 36 cases"),
            ("stream", main_corpus, ["prose_extract"], size_of, "E3 compilations with streamed responses"),
            ("copyshare", share_corpus, first_day, set_of, "E4 copy share, first-day conditions"),
            ("copyshare_working", share_corpus, ["prose_working"], set_of, "E4 copy share, visible working"),
            ("repeat", main_corpus, first_day, size_of, "E7 second run of the main design"),
            ("xl", xl_corpus, first_day, set_of, "E8 80 records, first-day conditions"),
            ("xl_working", xl_corpus, ["prose_working"], set_of, "E8 80 records, visible working")]
    for part, corpus, conditions, group_of, title in plan:
        folder = EXT / part
        if not folder.exists() or not corpus:
            continue
        lines += [f"## {title}", ""]
        for model_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
            model = model_dir.name
            requests, responses, by_slot = slots(model_dir)
            if not requests:
                continue
            records = list(by_slot.values())
            scored_conditions = conditions
            no_final_answer = 0
            if conditions == ["prose_working"]:
                records = [as_direct(r) for r in records]
                no_final_answer = sum(r.get("working_answer_found") is False for r in records)
                scored_conditions = ["prose_fresh"]
            sent_keys = {(r["case_id"], "prose_fresh" if r["condition"] == "prose_working" else r["condition"]) for r in requests}
            cells, disagreements = score(corpus, records, scored_conditions, group_of, sent_keys)
            if conditions == ["prose_working"]:
                cells = {k.replace("|prose_fresh", "|prose_working"): v for k, v in cells.items()}
            errors = Counter(f"{r.get('error')} {r.get('http_status') or ''}".strip() for r in by_slot.values() if r.get("error"))
            out["parts"].setdefault(part, {})[model] = {
                "requests_sent": len(requests), "rejected_with_429": sum(r.get("http_status") == 429 for r in responses),
                "slots_with_a_record": len(by_slot), "errors": dict(errors), "no_final_answer_object": no_final_answer,
                "scorer_disagreements": disagreements, "cells": cells,
                "observed_cost_credits": round(sum(r.get("observed_token_cost_credits_uncached") or 0 for r in responses), 4)}
            out["scorer_disagreements"] += disagreements
            out["requests"]["sent"] += len(requests)
            out["requests"]["http_429"] += sum(r.get("http_status") == 429 for r in responses)
            out["requests"]["http_504"] += sum(r.get("http_status") == 504 for r in responses)
            out["requests"]["cost_x10000"] += round(10000 * sum(r.get("observed_token_cost_credits_uncached") or 0 for r in responses))
            lines += [f"### {NAMES.get(model, model)} ({model})", "",
                      f"Requests sent {len(requests)}, slots with a record {len(by_slot)}, errors {dict(errors)}, outputs without a final answer "
                      f"object {no_final_answer}, scorer disagreements {disagreements}.", "", "```"]
            for name in sorted(cells, key=lambda k: (["S", "M", "L", "C0", "C8", "XL"].index(k.split("|")[0]), k.split("|")[1])):
                group, condition = name.split("|")
                lines.append(f"{group:3s} {LABEL[condition]:37s} {line(cells[name], condition)}")
            lines += ["```", ""]
            if part == "repeat":
                # run 1 of the same sessions: the main run for Gemma, part E1 for Gemma-26B
                first_dir = SCALE / "runs" / model if (SCALE / "runs" / model).exists() else EXT / "main" / model
                _, _, first_slots = slots(first_dir)
                one = {(k[0], k[1]): v for k, v in independent_rows(corpus, list(first_slots.values())).items() if k[2] == "final"}
                two = {(k[0], k[1]): v for k, v in independent_rows(corpus, records).items() if k[2] == "final"}
                compare = {}
                for condition in conditions:
                    c = Counter()
                    for item in corpus:
                        a, b = one[(item["id"], condition)], two[(item["id"], condition)]
                        c["slots"] += 1
                        c["usable_in_both"] += a["semantic_valid"] and b["semantic_valid"]
                        c["usable_in_first_only"] += a["semantic_valid"] and not b["semantic_valid"]
                        c["usable_in_second_only"] += b["semantic_valid"] and not a["semantic_valid"]
                        c["usable_in_neither"] += not a["semantic_valid"] and not b["semantic_valid"]
                        if a["semantic_valid"] and b["semantic_valid"]:
                            differing = sum(bool(a["predictions"][d]) != bool(b["predictions"][d]) for d in a["predictions"])
                            c["decisions_in_both"] += len(a["predictions"])
                            c["decisions_that_differ"] += differing
                            c["slots_with_a_difference"] += differing > 0
                            c["fully_correct_in_both"] += a["exact"] and b["exact"]
                            c["fully_correct_in_first_only"] += a["exact"] and not b["exact"]
                            c["fully_correct_in_second_only"] += b["exact"] and not a["exact"]
                            c["errors_first"] += a["errors"]
                            c["errors_second"] += b["errors"]
                    compare[condition] = dict(c)
                    lines.append(f"run 1 against run 2, {LABEL[condition]}: " + json.dumps(compare[condition]))
                out["parts"][part][model]["comparison_with_first_run"] = compare
                lines.append("")
    # part E1 is scored with the main run; its requests are counted here so that the extension has one total
    for model_dir in sorted(p for p in (EXT / "main").iterdir() if p.is_dir()) if (EXT / "main").exists() else []:
        requests, responses, _ = slots(model_dir)
        out["requests"]["sent"] += len(requests)
        out["requests"]["http_429"] += sum(r.get("http_status") == 429 for r in responses)
        out["requests"]["http_504"] += sum(r.get("http_status") == 504 for r in responses)
        out["requests"]["cost_x10000"] += round(10000 * sum(r.get("observed_token_cost_credits_uncached") or 0 for r in responses))
    out["requests"] = dict(out["requests"])
    lines += ["## Requests of the whole extension, part E1 included", "", json.dumps(out["requests"]), "",
              f"Scorer disagreements in the parts scored here: {out['scorer_disagreements']}", ""]
    (EXT / "score_ext.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "paper_build" / "tables" / "scale_ext.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
