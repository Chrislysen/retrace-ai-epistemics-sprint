"""Local pre-inference lock/freeze. Exclusive writes prevent silent replacement."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOCKED = ["retrace/extraction_v2_sessions.py", "retrace/compact_graph.py"]
FROZEN = LOCKED + [
    "retrace/__init__.py", "retrace/extraction_v2_eval.py", "retrace/core.py",
    "retrace/prose_eval.py", "retrace/experiment.py", "scripts/run_adaption.mjs",
    "scripts/freeze_extraction_v2.py", "scripts/summarize_extraction_v2.py",
    "tests/test_compact_graph.py", "tests/test_extraction_v2.py",
    "research/extraction-v2-protocol.md", "research/extraction-v2-case-design.md",
    "research/extraction-v2-audit.md", "report/audit_extraction_v2_cases.py",
    "data/extraction-v2-prompt-lock.json", "data/extraction-v2-holdout.json",
    "data/extraction-v2-sessions.json", "data/extraction-v2-plan.json",
    "report/extraction-v2-audit-checks.json",
    "retrace/uncertainty.py", "retrace/intervention_audit.py",
    "tests/test_uncertainty.py", "tests/test_intervention_audit.py",
    "scripts/build_uncertainty_review.py",
]


def hashes(paths):
    return [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in paths]


def verify(path):
    manifest = json.loads((ROOT / path).read_text(encoding="utf-8"))
    for row in manifest["files"]:
        if hashes([row["path"]])[0]["sha256"] != row["sha256"]:
            raise ValueError("Frozen file changed: " + row["path"])
    return manifest


def exclusive(path, value):
    with (ROOT / path).open("x", encoding="utf-8") as target:
        target.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["lock", "sessions", "freeze", "verify"])
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).isoformat()
    if args.stage == "lock":
        exclusive("data/extraction-v2-prompt-lock.json", {"created_at": stamp, "files": hashes(LOCKED),
                  "note": "Prompt/codec developers have not inspected the fresh holdout corpus."})
    elif args.stage == "sessions":
        verify("data/extraction-v2-prompt-lock.json")
        from retrace.extraction_v2_sessions import build_manifest
        corpus = json.loads((ROOT / "data/extraction-v2-holdout.json").read_text(encoding="utf-8"))
        if isinstance(corpus, dict):
            corpus = corpus["cases"]
        if len(corpus) != 12:
            raise ValueError("Protocol requires exactly 12 cases")
        exclusive("data/extraction-v2-sessions.json", build_manifest(corpus))
    elif args.stage == "freeze":
        verify("data/extraction-v2-prompt-lock.json")
        exclusive("data/extraction-v2-freeze.json", {"created_at": stamp, "files": hashes(FROZEN),
                  "models": ["gemma-4-31b-it", "glm-53-flash"], "requests_per_model": 24,
                  "max_output_tokens": 4096, "temperature": 0, "timeout_ms": 120000,
                  "concurrency": 1, "min_interval_ms": 3100, "automatic_retries": 0})
    else:
        verify("data/extraction-v2-freeze.json")
    print(json.dumps({"stage": args.stage, "status": "passed", "at": stamp}))


if __name__ == "__main__":
    main()
