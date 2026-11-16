"""Candidate-only secondary audit; references score coverage, never fill candidates."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.prose_eval import canonical_graph, gold_for
from retrace.intervention_audit import audit_interventions
from retrace.uncertainty import analyze_uncertainty
from freeze_extraction_v2 import verify


def main():
    verify("data/extraction-v2-freeze.json")
    corpus = json.loads((ROOT / "data/extraction-v2-holdout.json").read_text(encoding="utf-8"))
    if isinstance(corpus, dict): corpus = corpus["cases"]
    scores = json.loads((ROOT / "results/extraction-v2-summary.json").read_text(encoding="utf-8"))
    rows = []
    for entry in corpus:
        candidates = []
        for model, result in scores["models"].items():
            for output in result["outcomes"]:
                if output["case_id"] == entry["id"] and output["valid"]:
                    candidates.append({"id": model + "/" + output["condition"], "graph": output["graph"]})
        gold = gold_for(entry)
        canonical = [canonical_graph(c["graph"]) for c in candidates]
        row = {"case_id": entry["id"], "candidate_count": len(candidates),
               "distinct_graph_count": len({json.dumps(g, sort_keys=True) for g in canonical}),
               "reference_in_candidate_set": canonical_graph(gold["final_graph"]) in canonical,
               "reference_decisions_for_scoring_only": gold["final"]}
        if candidates:
            row["current_candidate_audit"] = analyze_uncertainty(candidates)
        if len(candidates) >= 2:
            try:
                row["future_withdrawal_audit"] = audit_interventions({c["id"]: c["graph"] for c in candidates})
            except ValueError as exc:
                row["future_withdrawal_audit"] = {"status": "not_evaluated", "reason": str(exc)}
        rows.append(row)
    result = {"schema": "retrace.extraction-v2-uncertainty-review", "cases": rows,
              "note": "Only admitted model outputs are candidate graphs. Repeated graphs are not independent corroboration. Reference coverage is evaluation-only. Candidate agreement does not prove completeness or truth."}
    (ROOT / "results/extraction-v2-uncertainty-review.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(rows), "with_candidates": sum(r["candidate_count"] > 0 for r in rows),
                      "with_multiple_structures": sum(r["distinct_graph_count"] > 1 for r in rows),
                      "reference_covered": sum(r["reference_in_candidate_set"] for r in rows)}))


if __name__ == "__main__": main()
