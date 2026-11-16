"""Aggregate immutable journals; never call a model or edit its saved response."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.experiment import score_records


def summarize(run_root, cases_path, output):
    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    models = []
    for path in sorted(Path(run_root).resolve().glob("*/responses.jsonl")):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        run = json.loads((path.parent / "run.json").read_text(encoding="utf-8"))
        summary_path = path.parent / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {"status": "running"}
        strict = score_records(cases, records)
        sensitivity = score_records(cases, records, allow_outer_fence=True)
        models.append({"model": run["model"], "run_status": summary["status"], "run": summary,
                       "scores": strict, "fence_normalized_sensitivity": sensitivity,
                       "raw_responses": str(path.relative_to(ROOT))})
    report = {"status": "completed" if models and all(m["run_status"] == "completed" for m in models) else "partial",
              "case_count": len(cases), "models": models,
              "note": "Exploratory, fixed synthetic graph pilot. Primary scores require strict JSON; the separately labeled post-hoc sensitivity strips only a single enclosing Markdown code fence. Interrupted preliminary runs are retained separately, not pooled.",
              "limitations": ["Small convenience set; no inferential significance claim.", "Declared provenance and exact rules supplied.", "Fixed condition order, single sample per final run.", "No natural-document extraction or user study.", "Token-derived estimates are not a verified account debit."]}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "models": [{"model": m["model"], "strict": m["scores"]["groups"], "sensitivity": m["fence_normalized_sensitivity"]["groups"]} for m in models]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default="results/pilot-paced")
    parser.add_argument("--cases", default="data/pilot-cases.json")
    parser.add_argument("--output", default="results/pilot-summary.json")
    args = parser.parse_args()
    summarize(args.runs, args.cases, args.output)
