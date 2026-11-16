"""Reproduce the frozen prose scores; no network or answer repair."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.prose_eval import score_prose


def main():
    freeze = json.loads((ROOT / "data/prose-freeze.json").read_text(encoding="utf-8"))
    for item in freeze["files"]:
        if hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Frozen file changed: " + item["path"])
    corpus = json.loads((ROOT / "data/prose-holdout.json").read_text(encoding="utf-8"))
    models = []
    for model in freeze["models"]:
        directories = [ROOT / "results/prose-heldout" / model]
        if model == "gemma-4-31b-it":
            directories.append(ROOT / "results/prose-continuation" / model)
        records, segments = [], []
        for directory in directories:
            log = directory / "responses.jsonl"
            if log.exists():
                records.extend(json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line)
            summary_path = directory / "summary.json"
            if summary_path.exists():
                segments.append(json.loads(summary_path.read_text()))
        complete = len(records) == freeze["requests_per_model"]
        operational = sum(bool(r.get("error")) for r in records)
        summary = {"status": "completed_with_operational_failures" if complete and operational else "completed" if complete else "incomplete",
                   "scheduled_requests": freeze["requests_per_model"], "recorded_responses": len(records),
                   "unissued_requests": freeze["requests_per_model"] - len(records),
                   "operational_failures": operational, "segments": segments,
                   "note": "Segment failures remain scored. Gemma continuation contains only never-issued frozen sessions; no issued response was retried."}
        scores = score_prose(corpus, records)
        resources = {}
        for condition in sorted({r["condition"] for r in records}):
            selected = [r for r in records if r["condition"] == condition]
            latencies = [r["latency_ms"] for r in selected if isinstance(r.get("latency_ms"), (int, float))]
            completed_latencies = [r["latency_ms"] for r in selected if not r.get("error") and isinstance(r.get("latency_ms"), (int, float))]
            usages = [r["usage"] for r in selected if isinstance(r.get("usage"), dict)]
            resources[condition] = {"received_responses": len(selected), "operational_failures": sum(bool(r.get("error")) for r in selected),
                "median_latency_ms_all": median(latencies) if latencies else None,
                "median_latency_ms_completed": median(completed_latencies) if completed_latencies else None,
                "input_tokens_known": sum(u.get("input_tokens", 0) for u in usages),
                "output_tokens_known": sum(u.get("output_tokens", 0) for u in usages),
                "reported_reasoning_tokens_known": sum((u.get("output_tokens_details") or {}).get("reasoning_tokens") or 0 for u in usages),
                "known_token_cost_credits_uncached": sum(r.get("observed_token_cost_credits_uncached") or 0 for r in selected),
                "missing_usage": len(selected) - len(usages),
                "note": "Per-response latency, not paired workflow wall time. Output tokens include reported reasoning where supplied; zero reported reasoning is not proof of no internal computation. History includes initial and withdrawn calls. No verified billing."}
        # Descriptive strata retain the original four-template/six-domain design.
        strata = {}
        for dimension in ("family", "domain"):
            strata[dimension] = {}
            for value in sorted({entry[dimension] for entry in corpus}):
                subset = [entry for entry in corpus if entry[dimension] == value]
                ids = {entry["id"] for entry in subset}
                subscore = score_prose(subset, [r for r in records if r["case_id"] in ids], bootstrap_repeats=1)
                strata[dimension][value] = subscore["groups"]
        models.append({"model": model, "run_status": summary["status"] if records else "not_started",
                       "run": summary, "scores": scores, "strata": strata, "resources": resources})
    report = {"schema": "retrace.prose-report.v1", "generated_at": datetime.now(timezone.utc).isoformat(),
              "case_count": len(corpus), "freeze_verified": True, "models": models,
              "note": "24 controlled fictional packets, six domains and four composed templates. Prespecified outer-fence normalization; strict format separately reported. No claim of real-document performance or an improvement in human decisions."}
    (ROOT / "results/prose-summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"freeze_verified": True, "models": [{"model": m["model"], "status": m["run_status"],
        "groups": {k: {f: g[f] for f in ("received", "semantic_valid", "exact", "strict_valid", "graph_exact")}
                   for k, g in m["scores"]["groups"].items()}} for m in models]}, indent=2))


if __name__ == "__main__":
    main()
