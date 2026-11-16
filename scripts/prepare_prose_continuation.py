"""Create a separately reserved segment containing only never-issued sessions.

This is an explicit operational amendment, not an automatic retry. A session
with any issued step is never included, even if it failed. Mid-history failures
therefore require separate handling rather than replaying a fabricated answer.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "data/prose-sessions.json").read_text(encoding="utf-8"))
directory = ROOT / "results/prose-heldout/gemma-4-31b-it"
summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
requests = [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines() if line]
responses = [json.loads(line) for line in (directory / "responses.jsonl").read_text(encoding="utf-8").splitlines() if line]
if summary["status"] != "halted" or len(requests) != len(responses):
    raise ValueError("Expected a halted, fully journaled segment")
issued = {(r["case_id"], r["condition"]) for r in requests}
pending = [s for s in manifest["sessions"] if (s["case_id"], s["condition"]) not in issued]
count = sum(len(s["steps"]) for s in pending)
if count != summary["unissued_requests"]:
    raise ValueError("A partially issued session needs explicit handling")
continuation = {"schema": "retrace.prose-continuation.v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "instructions": manifest["instructions"], "sessions": pending, "request_count": count,
                "parent_manifest_sha256": hashlib.sha256((ROOT / "data/prose-sessions.json").read_bytes()).hexdigest(),
                "parent_run_id": summary["run_id"], "max_output_tokens": 4096, "temperature": 0,
                "min_interval_ms": 3100, "timeout_ms": 120000,
                "policy": "Only previously unissued complete sessions. No failed request retried, no output repaired, no primary freeze changed. Prior unused reservations are not refunded."}
with (ROOT / "data/prose-continuation-gemma.json").open("x", encoding="utf-8") as f:
    json.dump(continuation, f, indent=2, ensure_ascii=False)
    f.write("\n")
print(json.dumps({"sessions": len(pending), "requests": count, "original_issued": len(requests)}))
