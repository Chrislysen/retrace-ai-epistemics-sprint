"""Consolidate credit reservations, including failed and unissued attempts."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runs = []
for path in sorted((ROOT / "results").rglob("run.json")):
    manifest = json.loads(path.read_text())
    summary_path = path.parent / "summary.json"
    if not summary_path.exists():
        raise RuntimeError(f"Run is not complete: {path.parent}")
    summary = json.loads(summary_path.read_text())
    runs.append({"path": str(path.parent.relative_to(ROOT)), "model": manifest["model"],
                 "status": summary["status"], "halt_reason": summary["halt_reason"],
                 "reserved_credits": manifest["max_reserved_credits"],
                 "issued_requests": summary["issued_requests"],
                 "recorded_responses": summary["recorded_responses"],
                 "observed_token_cost_credits_uncached": summary["observed_token_cost_credits_uncached"],
                 "responses_missing_usage": summary["responses_missing_usage"]})
report = {"generated_at": datetime.now(timezone.utc).isoformat(), "approved_credit_cap": 50,
          "conservative_reserved_credits": sum(r["reserved_credits"] for r in runs),
          "observed_token_cost_credits_uncached": sum(r["observed_token_cost_credits_uncached"] for r in runs),
          "responses_missing_usage": sum(r["responses_missing_usage"] for r in runs),
          "issued_requests": sum(r["issued_requests"] for r in runs), "runs": runs,
          "actual_billed_credits": None,
          "note": "Reservations include unissued calls and do not refund errors. Unknown-usage attempts remain covered by reservations. Token estimates use snapshotted official uncached prices; actual account debit was not verified."}
if report["conservative_reserved_credits"] > 50:
    raise RuntimeError("Reservation exceeds approved cap")
(ROOT / "results" / "budget-audit.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "runs"}, indent=2))
