#!/usr/bin/env python3
"""Requests of the extension of the scaling run, counted from its journals. No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026.

    python post_sweep/scale_ext_requests.py

Output: paper_build/tables/scale_ext_requests.txt
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "post_sweep" / "out" / "scale" / "ext"
NAMES = {"gemma-4-31b-it": "Gemma", "gemma-4-26b-a4b-it": "Gemma-26B", "qwen3.8-27b": "Qwen27B",
         "deepseek-v4-flash": "DeepSeek", "glm-53-flash": "GLM-Flash"}


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def main():
    total = {"requests": 0, "answer_records": 0, "http_429": 0, "http_504": 0, "cut_off_at_output_limit": 0, "other_errors": 0}
    reserved = cost = 0.0
    per_part, per_model, errors_by = {}, {}, {}
    first = last = None
    for req in sorted(EXT.glob("*/*/seg-*/requests.jsonl")):
        part, model = req.parts[-4], req.parts[-3]
        requests, responses = jsonl(req), jsonl(req.with_name("responses.jsonl"))
        per_part[(part, model)] = per_part.get((part, model), 0) + len(requests)
        per_model[model] = per_model.get(model, 0) + len(requests)
        total["requests"] += len(requests)
        total["answer_records"] += len(responses)
        reserved += sum(r.get("reserved_credits") or 0 for r in requests)
        cost += sum(r.get("observed_token_cost_credits_uncached") or 0 for r in responses)
        for r in requests:
            first = min(first or r["started_at"], r["started_at"])
        for r in responses:
            last = max(last or r["finished_at"], r["finished_at"])
            kind = None
            if r.get("http_status") == 429:
                kind = "http_429"
            elif r.get("http_status") == 504:
                kind = "http_504"
            elif r.get("error") == "response_not_completed":
                kind = "cut_off_at_output_limit"
            elif r.get("error"):
                kind = "other_errors"
            if kind:
                total[kind] += 1
                errors_by[(kind, part, model)] = errors_by.get((kind, part, model), 0) + 1
    lines = ["Requests of the extension (prereg/scale_extension_rules.md and its addenda), from post_sweep/out/scale/ext", ""]
    for (part, model), n in sorted(per_part.items()):
        lines.append(f"{part:20s} {NAMES.get(model, model):10s} {n:4d} requests")
    lines += ["", "per model: " + ", ".join(f"{NAMES.get(m, m)} {n}" for m, n in sorted(per_model.items())),
              "totals: " + json.dumps(total),
              f"requests without an answer record: {total['requests'] - total['answer_records']}",
              "failures by kind, part and model: " + "; ".join(f"{k[0]} {k[1]} {NAMES.get(k[2], k[2])} x{n}" for k, n in sorted(errors_by.items())),
              f"reservation {reserved:.2f} credits (ceiling 80); observed token cost {cost:.2f} credits; requests of at most 1,000 (900 until addendum 5)",
              f"first request {first}, last answer {last} (UTC)"]
    (ROOT / "paper_build" / "tables" / "scale_ext_requests.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()