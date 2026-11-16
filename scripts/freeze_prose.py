"""Freeze corpus, prompts, scorer, protocol and audit before paid outcome inspection."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.prose_sessions import build_manifest
from retrace.core import analyze

corpus_path = ROOT / "data" / "prose-holdout.json"
if (ROOT / "data" / "prose-freeze.json").exists():
    raise ValueError("Freeze already exists; do not replace frozen sessions")
corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
if len(corpus) != 24 or len({e["id"] for e in corpus}) != 24:
    raise ValueError("Exactly 24 distinct cases expected")
for entry in corpus:
    analyze(entry["case"], entry["case"]["revoke"])
    if set(d["id"] for d in entry["decision_questions"]) != set(d["id"] for d in entry["case"]["decisions"]):
        raise ValueError("Decision registry mismatch")
manifest = build_manifest(corpus)
session_path = ROOT / "data" / "prose-sessions.json"
session_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
files = ["data/prose-holdout.json", "data/prose-sessions.json", "retrace/prose_sessions.py", "retrace/prose_eval.py", "retrace/core.py",
         "research/prose-protocol.md", "research/prose-audit.md", "scripts/run_adaption.mjs"]
freeze = {"schema": "retrace.freeze.v1", "created_at": datetime.now(timezone.utc).isoformat(),
          "description": "Local pre-inference freeze, not an externally registered preregistration.",
          "case_count": 24, "requests_per_model": manifest["request_count"],
          "models": ["gemma-4-31b-it", "glm-53-flash"], "max_output_tokens": 4096,
          "temperature": 0, "min_interval_ms": 3100, "timeout_ms": 120000,
          "previous_conservative_reservations": 16.021788, "approved_total_credit_cap": 50,
          "files": [{"path": f, "sha256": hashlib.sha256((ROOT / f).read_bytes()).hexdigest()} for f in files]}
path = ROOT / "data" / "prose-freeze.json"
with path.open("x", encoding="utf-8") as f:
    json.dump(freeze, f, indent=2)
    f.write("\n")
print(json.dumps(freeze, indent=2))
