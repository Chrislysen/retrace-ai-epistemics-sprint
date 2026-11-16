"""Supplemental offline resource/paired-bootstrap audit; no model API calls.

Reads the completed journals and stable summary, never regenerates scores.
Uses the independent fixed-point audit module, not RETRACE's frozen scorer.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from audit_prose_runs import independent_scores, require

ROOT = Path(__file__).resolve().parents[1]


def checked_file(relative):
    content = (ROOT / relative).read_bytes()
    return content, hashlib.sha256(content).hexdigest()


def audit():
    summary_bytes, summary_hash = checked_file("results/prose-summary.json")
    corpus_bytes, corpus_hash = checked_file("data/prose-holdout.json")
    _, scorer_hash = checked_file("retrace/prose_eval.py")
    _, helper_hash = checked_file("scripts/audit_prose_runs.py")
    freeze = json.loads((ROOT / "data/prose-freeze.json").read_text(encoding="utf-8"))
    require(scorer_hash == next(f["sha256"] for f in freeze["files"] if f["path"] == "retrace/prose_eval.py"),
            "Frozen scorer hash changed")
    report, corpus = json.loads(summary_bytes), json.loads(corpus_bytes)
    results, inputs = {}, []
    for model in report["models"]:
        records = []
        for prefix in ("prose-heldout", "prose-continuation"):
            relative = f"results/{prefix}/{model['model']}/responses.jsonl"
            if not (ROOT / relative).exists():
                continue
            saved, sha = checked_file(relative)
            records += [json.loads(line) for line in saved.decode("utf-8").splitlines() if line]
            inputs.append({"path": relative, "sha256": sha})
        require(len(records) == 144, "Supplemental audit requires final full coverage")
        _, outcomes = independent_scores(corpus, records)
        resource_counts = {}
        for condition, observed in model["resources"].items():
            selected = [row for row in records if row["condition"] == condition]
            require(len(selected) == (48 if condition == "prose_history" else 24), "Resource condition denominator mismatch")
            all_times = sorted(row["latency_ms"] for row in selected)
            completed_times = sorted(row["latency_ms"] for row in selected if not row.get("error"))
            median = lambda values: (values[(len(values) - 1) // 2] + values[len(values) // 2]) / 2
            require(observed["received_responses"] == len(selected), "Resource received count mismatch")
            require(observed["operational_failures"] == len(all_times) - len(completed_times), "Resource failure count mismatch")
            require(observed["median_latency_ms_all"] == median(all_times), "All-response latency median mismatch")
            require(observed["median_latency_ms_completed"] == median(completed_times), "Completed-response latency median mismatch")
            for key in ("input_tokens", "output_tokens"):
                require(all(type(row["usage"][key]) is int and row["usage"][key] >= 0 for row in selected), "Invalid token usage")
                require(observed[key + "_known"] == sum(row["usage"][key] for row in selected), "Resource token total mismatch")
            reasoning = sum((row["usage"].get("output_tokens_details") or {}).get("reasoning_tokens") or 0 for row in selected)
            require(observed["reported_reasoning_tokens_known"] == reasoning, "Reported reasoning-token total mismatch")
            require(observed["missing_usage"] == 0, "Unexpected missing usage")
            cost = sum((Decimal(str(row["observed_token_cost_credits_uncached"])) for row in selected), Decimal(0))
            require(abs(cost - Decimal(str(observed["known_token_cost_credits_uncached"]))) < Decimal("1e-12"), "Resource cost total mismatch")
            resource_counts[condition] = {"all_response_latency_n": len(all_times),
                                          "completed_response_latency_n": len(completed_times), "known_usage_n": len(selected),
                                          "all_reported_medians_and_totals_match": True}

        require(model["scores"]["bootstrap_seed"] == 2026111302 and model["scores"]["bootstrap_repeats"] == 2000,
                "Prespecified bootstrap settings changed")
        contrast = model["scores"]["contrasts"][4]
        require(contrast["name"] == "prose_extract_minus_prose_fresh", "Extraction contrast order changed")
        deltas = [outcomes[(entry["id"], "prose_fresh", "final")]["decision_error_fraction_all_scheduled"]
                  - outcomes[(entry["id"], "prose_extract", "final")]["decision_error_fraction_all_scheduled"] for entry in corpus]
        sample_size, repeats, seed = len(deltas), 2000, 2026111306
        rng = random.Random(seed)
        # Uniform draws via random/floor, independent of the scorer's choices call.
        samples = sorted(sum(deltas[math.floor(rng.random() * sample_size)] for _ in range(sample_size)) / sample_size
                         for _ in range(repeats))
        interval = [samples[math.floor(.025 * (repeats - 1))], samples[math.floor(.975 * (repeats - 1))]]
        mean = sum(deltas) / sample_size
        require(all(abs(a - b) < 1e-12 for a, b in zip(interval, contrast["case_bootstrap_stability_interval_95"])),
                "Independent bootstrap interval differs from saved scorer")
        require(abs(mean - contrast["mean_accuracy_delta_all_scheduled"]) < 1e-12, "Independent paired mean differs from saved scorer")
        results[model["model"]] = {"resources": resource_counts, "contrast": contrast["name"],
                                   "paired_cases": sample_size, "seed": seed, "resamples": repeats,
                                   "mean_decision_accuracy_delta_all_scheduled": mean,
                                   "resampling_stability_interval_95": interval,
                                   "exact_match_with_saved_scorer_within_tolerance": True,
                                   "case_accuracy_deltas": [{"case_id": entry["id"], "delta": delta} for entry, delta in zip(corpus, deltas)]}
    require((ROOT / "results/prose-summary.json").read_bytes() == summary_bytes, "Summary changed while audit ran")
    return {"schema": "retrace.prose-secondary-audit.v1", "status": "passed",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "method": "Separate AI agent; offline standard-library resource accounting and 2,000 paired bootstrap resamples. Graph decisions use the independent fixed-point audit, never the frozen evaluator. No API calls or score regeneration.",
            "main_audit": "results/prose-independent-audit.json",
            "scope": "Supplement to the main audit: resource denominators/totals/medians and the one prespecified extraction-minus-prose-fresh bootstrap contrast for each model.",
            "scorer_sha256": scorer_hash, "stable_summary_sha256": summary_hash, "corpus_sha256": corpus_hash,
            "independent_evaluator_sha256": helper_hash,
            "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "journal_inputs": inputs, "models": results,
            "limitations": ["Resampling stability over 24 authored cases, not population confidence, causal identification, or proof of equivalence.",
                            "Mean decision accuracy differs from all-decisions-exact case accuracy. Invalid/incomplete outputs count as all six labels wrong in the all-scheduled contrast.",
                            "Completed latency includes semantically invalid outputs and excludes only operationally failed calls. History pools initial and withdrawn calls; latency is per response, not whole workflow wall time.",
                            "Token totals include the failed attempt where usage is available. Credit figures are estimates rather than verified account billing.",
                            "The remaining four bootstrap contrasts were not independently reproduced by this supplemental script."]}


if __name__ == "__main__":
    result = audit()
    destination = ROOT / "results/prose-secondary-audit.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "models_checked": list(result["models"]), "output": str(destination)}))
