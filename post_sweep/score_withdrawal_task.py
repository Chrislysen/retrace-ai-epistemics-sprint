#!/usr/bin/env python3
"""Score part E5 of the extension (prereg/scale_extension_addendum_3.md): the smallest further withdrawal. No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026.

    python post_sweep/score_withdrawal_task.py

An answer names, for each decision, a set of further records to withdraw. For a decision that is supported in the
reference state the set is valid when it consists of records of the case and the decision has no support after their
withdrawal, and smallest when it is valid and has the reference size. For a decision without support the empty set is
correct. The compiled route makes no call: each model's accepted declaration from the main run is searched by the
program that produced the reference, and the set it finds is scored like an answer.

Outputs: post_sweep/out/scale/ext/score_withdrawal.json, paper_build/tables/scale_withdrawal.md
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
from scale_withdrawal_task import smallest_withdrawals  # noqa: E402

SCALE = ROOT / "post_sweep" / "out" / "scale"
EXT = SCALE / "ext"
NAMES = {"gemma-4-31b-it": "Gemma", "gemma-4-26b-a4b-it": "Gemma-26B", "qwen3.8-27b": "Qwen27B",
         "deepseek-v4-flash": "DeepSeek", "glm-53-flash": "GLM-Flash"}
PARTS = [("withdrawal_answer", "Named by the model, answer only"), ("withdrawal_working", "Named by the model, working first")]


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def slots(folder):
    requests, responses = [], []
    for seg in sorted(folder.glob("seg-*")) if folder.exists() else []:
        requests += jsonl(seg / "requests.jsonl")
        responses += jsonl(seg / "responses.jsonl")
    by_case = {}
    for r in responses:
        if r["case_id"] not in by_case or r.get("http_status") != 429 or by_case[r["case_id"]].get("http_status") == 429:
            by_case[r["case_id"]] = r
    return requests, responses, by_case


def last_object(text, key):
    """The last JSON object in `text` whose only key is `key`, parsed, or None."""
    for match in reversed(list(re.finditer(r'\{\s*"' + key + r'"\s*:', text or ""))):
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
                    try:
                        value = json.loads(text[match.start():position + 1])
                    except ValueError:
                        break
                    if isinstance(value, dict) and list(value) == [key] and isinstance(value[key], dict):
                        return value[key]
                    break
    return None


def grade(case, reference, named):
    """Counters for one case, given the sets named per decision (a dict) or None for an unusable answer."""
    out = Counter()
    record_ids = {row["id"] for row in case["evidence"]}
    all_smallest = named is not None
    for decision, ref in reference.items():
        k = ref["k"]
        if k is None:   # smallest set above the search limit: not scored
            out["decisions_above_limit"] += 1
            continue
        group = "none" if k == 0 else "one" if k == 1 else "more"
        out[f"decisions_{group}"] += 1
        if named is None:
            continue
        out[f"answered_{group}"] += 1
        value = named.get(decision)
        is_list = isinstance(value, list) and all(isinstance(x, str) for x in value)
        if k == 0:
            ok = is_list and len(value) == 0
            out["empty_correct"] += ok
            all_smallest = all_smallest and ok
            continue
        valid = bool(is_list and value and set(value) <= record_ids
                     and not supported(case, list(case["revoke"]) + list(value))[decision])
        smallest = valid and len(set(value)) == k
        out[f"valid_{group}"] += valid
        out[f"smallest_{group}"] += smallest
        if valid and not smallest:
            out[f"valid_but_larger_{group}"] += 1
            # an oversized set is "padded" when one of its own records (for a one-record decision) would have been enough
            if k == 1 and any(not supported(case, list(case["revoke"]) + [x])[decision] for x in set(value)):
                out["padded_one"] += 1
        all_smallest = all_smallest and smallest
    out["cases"] += 1
    out["usable"] += named is not None
    out["cases_all_smallest"] += all_smallest
    return out


def parse_declaration(text):
    body = (text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*\n(.*)\n```$", body, re.S)
    if fenced:
        body = fenced.group(1)
    return json.loads(body)


TABLES = ROOT / "paper_build" / "tables"
SUITES = [
    {"corpus": SCALE / "corpus.json", "reference": EXT / "withdrawal_reference.json", "parts": PARTS,
     "compiled": lambda model: (SCALE / "runs" / model) if (SCALE / "runs" / model).exists() else EXT / "main" / model,
     "scopes": ("S", "M", "L", "all"), "json": EXT / "score_withdrawal.json", "md": TABLES / "scale_withdrawal.md",
     "title": "# Extension, parts E5 and E6: the smallest further withdrawal", "rules": "prereg/scale_extension_addendum_3.md and _4.md",
     "of": 12},
    {"corpus": EXT / "corpus_xl.json", "reference": EXT / "withdrawal_reference_xl.json",
     "parts": [("xl_withdrawal_answer", PARTS[0][1]), ("xl_withdrawal_working", PARTS[1][1])],
     "compiled": lambda model: EXT / "xl" / model,
     "scopes": ("XL", "all"), "json": EXT / "score_withdrawal_xl.json", "md": TABLES / "scale_withdrawal_xl.md",
     "title": "# Extension, part E8: the smallest further withdrawal at 80 records", "rules": "prereg/scale_extension_addendum_5.md",
     "of": 12},
]


def run(suite):
    corpus = json.loads(suite["corpus"].read_text(encoding="utf-8"))
    size_of = {item["id"]: item["review_notes"]["size"] for item in corpus}
    reference = json.loads(suite["reference"].read_text(encoding="utf-8"))["cases"]
    out = {"rows": [], "requests": Counter()}
    lines = [suite["title"], "",
             f"Produced by `post_sweep/score_withdrawal_task.py`. Rules: `{suite['rules']}`. "
             f"Per model, route and case size: usable answers of {suite['of']}; of the supported decisions in usable answers, sets that are valid and "
             "sets that are smallest, for decisions whose smallest set has one record and for those that need more.", ""]

    def add(model, label, per_case, extra):
        for scope in suite["scopes"]:
            total = Counter()
            for case_id, counters in per_case.items():
                if scope in ("all", size_of[case_id]):
                    total.update(counters)
            row = {"model": model, "route": label, "size": scope, **{k: int(v) for k, v in total.items()}, **extra}
            out["rows"].append(row)
            g = lambda key: total.get(key, 0)  # noqa: E731
            lines.append(f"| {NAMES.get(model, model)} | {label} | {scope} | {g('usable')} of {g('cases')} | "
                         f"{g('valid_one')} / {g('smallest_one')} of {g('answered_one')} | "
                         f"{g('valid_more')} / {g('smallest_more')} of {g('answered_more')} | "
                         f"{g('empty_correct')} of {g('answered_none')} | {g('cases_all_smallest')} |")

    lines += ["| Model | Route | Size | Usable answers | One record needed: valid / smallest of answered | "
              "More needed: valid / smallest of answered | No support: empty set given | Cases with every set smallest |",
              "|---|---|---|---|---|---|---|---|"]
    for part, label in suite["parts"]:
        folder = EXT / part
        for model_dir in sorted(p for p in folder.iterdir() if p.is_dir()) if folder.exists() else []:
            requests, responses, by_case = slots(model_dir)
            if not requests:
                continue
            per_case, tokens, seconds, no_object = {}, [], [], 0
            sent = {r["case_id"] for r in requests}
            for item in corpus:
                record = by_case.get(item["id"])
                named = None
                if record is not None and not record.get("error"):
                    named = last_object(record.get("output_text"), "withdrawals")
                    no_object += named is None
                    if record.get("usage"):
                        tokens.append(record["usage"].get("output_tokens") or 0)
                        seconds.append((record.get("latency_ms") or 0) / 1000)
                counters = grade(item["case"], reference[item["id"]], named)
                counters["issued"] += item["id"] in sent
                per_case[item["id"]] = counters
            errors = Counter(f"{r.get('error')} {r.get('http_status') or ''}".strip() for r in by_case.values() if r.get("error"))
            add(model_dir.name, label, per_case, {
                "requests_sent": len(requests), "errors": dict(errors), "outputs_without_the_object": no_object,
                "median_output_tokens": int(statistics.median(tokens)) if tokens else None,
                "median_seconds": round(statistics.median(seconds), 1) if seconds else None})
            out["requests"]["sent"] += len(requests)
            out["requests"]["http_429"] += sum(r.get("http_status") == 429 for r in responses)
            out["requests"]["http_504"] += sum(r.get("http_status") == 504 for r in responses)
            out["requests"]["cost_x10000"] += round(10000 * sum(r.get("observed_token_cost_credits_uncached") or 0 for r in responses))

    # the compiled route: search each model's accepted declaration of the same cases (no call)
    for model in ("gemma-4-31b-it", "gemma-4-26b-a4b-it", "qwen3.8-27b", "deepseek-v4-flash", "glm-53-flash"):
        base = suite["compiled"](model)
        responses = []
        for seg in sorted(base.glob("seg-*")) if base.exists() else []:
            responses += jsonl(seg / "responses.jsonl")
        if not responses:
            continue
        by_slot = {}
        for r in responses:
            key = (r["case_id"], r["condition"])
            if key not in by_slot or r.get("http_status") != 429 or by_slot[key].get("http_status") == 429:
                by_slot[key] = r
        rows = {(k[0], k[1]): v for k, v in independent_rows(corpus, list(by_slot.values())).items() if k[2] == "final"}
        per_case = {}
        for item in corpus:
            named = None
            if rows[(item["id"], "prose_extract")]["semantic_valid"]:
                declared = parse_declaration(by_slot[(item["id"], "prose_extract")]["output_text"])
                graph = {name: declared[name] for name in ("evidence", "claims", "decisions")}
                found = smallest_withdrawals(graph, [])
                named = {d: (row["example"] or []) for d, row in found.items()}
            per_case[item["id"]] = grade(item["case"], reference[item["id"]], named)
        add(model, "Searched in the model's accepted declaration (no call)", per_case, {})
    out["requests"] = dict(out["requests"])
    lines += ["", "Requests of this part: " + json.dumps(out["requests"]), ""]
    suite["json"].write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    suite["md"].write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


def main():
    for suite in SUITES:
        if suite["corpus"].exists() and suite["reference"].exists():
            run(suite)


if __name__ == "__main__":
    main()
