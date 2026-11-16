"""Prepare offline extraction review artifacts. No new calls or output repair.

Counterfactual comparisons are post-hoc engineering diagnostics, not outcomes
added to the frozen model protocol. No reference information enters inference.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.prose_eval import parse_json, parse_extracted_graph
from retrace.prose_sessions import final_case
from retrace.graph_review import review_graphs


def main():
    corpus = json.loads((ROOT / "data/prose-holdout.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "results/prose-summary.json").read_text(encoding="utf-8"))
    models = [m["model"] for m in summary["models"]]
    entries = []
    logs = {}
    for model in models:
        paths = [ROOT / "results/prose-heldout" / model / "responses.jsonl"]
        if model == "gemma-4-31b-it":
            paths.append(ROOT / "results/prose-continuation" / model / "responses.jsonl")
        logs[model] = {}
        for path in paths:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r["condition"] == "prose_extract":
                    if r["case_id"] in logs[model]:
                        raise ValueError("Duplicate extraction response")
                    logs[model][r["case_id"]] = r
    for item in corpus:
        reference = final_case(item)
        row = {k: item[k] for k in ("id", "title", "documents", "event_text")}
        row.update(reference=reference, extractions={})
        for model in models:
            record = logs[model].get(item["id"])
            if not record:
                row["extractions"][model] = {"status": "not_received"}
                continue
            result = {"status": "invalid", "raw_output": record["output_text"],
                      "request_sha256": record["request_sha256"], "error": record.get("error")}
            if not record.get("error"):
                try:
                    scored = parse_extracted_graph(record["output_text"], reference)
                    graph, _ = parse_json(record["output_text"])
                    result.update(status="valid", graph=graph, score=scored,
                                  review=review_graphs(reference, graph, max_interventions=2))
                except (ValueError, TypeError, KeyError, RecursionError) as exc:
                    result["error"] = str(exc)
            row["extractions"][model] = result
        entries.append(row)
    report = {"schema": "retrace.prose-review.v1", "models": models, "cases": entries,
              "scope": "Saved model extractions from controlled fictional prose. Model graphs are unreviewed by humans. Reference comparisons and bounded counterfactuals are evaluation aids, not provenance authentication.",
              "post_hoc": "Counterfactual comparisons were added after early prose outputs were seen. They are offline engineering diagnostics on the same cases, not fresh held-out evidence of an improved model."}
    (ROOT / "results/prose-review.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(entries), "models": models,
                      "valid_extractions": sum(r["status"] == "valid" for c in entries for r in c["extractions"].values())}))


if __name__ == "__main__":
    main()
