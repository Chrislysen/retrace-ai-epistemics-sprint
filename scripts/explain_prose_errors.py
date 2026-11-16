"""Export every scored error with reference support witnesses, without API calls."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.core import analyze
from retrace.prose_eval import gold_for

corpus = json.loads((ROOT / "data/prose-holdout.json").read_text(encoding="utf-8"))
cases = {c["id"]: c for c in corpus}
summary = json.loads((ROOT / "results/prose-summary.json").read_text(encoding="utf-8"))
errors = []
for model in summary["models"]:
    for outcome in model["scores"]["outcomes"]:
        if outcome["exact"]:
            continue
        entry = cases[outcome["case_id"]]
        row = {"model": model["model"], **{k: outcome[k] for k in ("case_id", "condition", "phase", "semantic_valid", "error")},
               "family": entry["family"], "domain": entry["domain"], "decision_errors": []}
        if outcome["semantic_valid"]:
            gold = gold_for(entry)
            initial = outcome["phase"] == "initial"
            truth = gold["initial"] if initial else gold["final"]
            state = analyze(entry["case"], [] if initial else entry["case"]["revoke"])
            for identifier, predicted in outcome["predictions"].items():
                if truth[identifier] == predicted:
                    continue
                category = "initial_state_error" if initial else (
                    "missed_required_retraction" if identifier in gold["lost"] else
                    "protected_alternative_discarded" if identifier in gold["protected"] else
                    "unaffected_support_discarded" if identifier in gold["unaffected_supported"] else
                    "initially_unsupported_accepted")
                decision = state["decisions"][identifier]
                row["decision_errors"].append({"id": identifier, "label": decision["label"], "type": category,
                                               "reference": truth[identifier], "predicted": predicted,
                                               "reference_supporting_roots": decision["supporting_roots"],
                                               "reference_valid_supports": decision["valid_supports"],
                                               "reference_invalidation_causes": decision["invalidation_causes"],
                                               "reference_claims": {c: state["claims"][c] for clause in decision["valid_supports"] for c in clause}})
        errors.append(row)
report = {"schema": "retrace.prose-errors.v1", "case_order": "lexicographic from frozen scorer; every non-exact outcome included",
          "note": "Reference witnesses explain the authored support rules, not the model's internal reasoning. Missing and invalid outcomes remain separate from semantic decision errors.",
          "outcomes": errors}
(ROOT / "results/prose-errors.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"non_exact_outcomes": len(errors), "valid_decision_errors": sum(len(e["decision_errors"]) for e in errors)}))
