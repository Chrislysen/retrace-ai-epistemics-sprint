"""Versioned instrumentation correction: alias two fields, preserve raw audits.

No detector logic, source corpus, graph, annotation, or frozen score calculation
is changed. The original failed diagnostic remains a separate immutable result.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_conservation_v6 import CORPUS_SHA256, evaluate_corpus

FIELD_ALIASES = {"unresolved": "unresolved_cues", "suppressed": "suppressed_cues"}
INITIAL_FREEZE = "data/conservation-v6-initial-freeze.json"
INITIAL_RESULT = "results/v6/conservation-offline-primary.json"


def adapt_result(raw):
    """Add only scorer-facing aliases on a copy; leave the original untouched."""
    if not isinstance(raw, dict):
        raise ValueError("Auditor result must be an object")
    adapted = copy.deepcopy(raw)
    for original, alias in FIELD_ALIASES.items():
        if original not in raw:
            raise ValueError("Auditor result lacks stable API field: " + original)
        if alias in raw and raw[alias] != raw[original]:
            raise ValueError("Conflicting result-field aliases: " + original + " / " + alias)
        adapted[alias] = copy.deepcopy(raw[original])
    return adapted


def evaluate_compatible(corpus, auditor):
    """Invoke the frozen scorer with public-only calls and separately log raw results."""
    raw_audits = []
    def compatible_auditor(**kwargs):
        try:
            raw = auditor(**kwargs)
        except Exception as exc:
            raw_audits.append({"raw_result": None, "error": f"{type(exc).__name__}: {exc}"})
            raise
        raw_audits.append({"raw_result": copy.deepcopy(raw), "error": None})
        return adapt_result(raw)
    scored = evaluate_corpus(corpus, compatible_auditor)
    if len(raw_audits) != len(scored["rows"]):
        raise ValueError("Raw audit count does not match the frozen scorer call order")
    for row, raw in zip(scored["rows"], raw_audits):
        raw.update(case_id=row["case_id"], variant=row["variant"])
    return {**scored, "schema": "retrace.conservation-offline-compatible.v1",
            "raw_audits": raw_audits,
            "instrumentation_correction": {
                "field_aliases": FIELD_ALIASES.copy(),
                "original_result": INITIAL_RESULT,
                "detector_logic_changed": False, "corpus_changed": False, "score_logic_changed": False,
                "scope": "Two stable auditor field names are aliased for the frozen scorer. Raw audits remain separate and unchanged; the initial schema-failure result is preserved.",
            }}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_manifest(path):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if _digest(ROOT / item["path"]) != item["sha256"]:
            raise ValueError("Frozen input changed: " + item["path"])
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", required=True, help="New adapter freeze with files[{path,sha256}] and created_at")
    parser.add_argument("--output", default="results/v6/conservation-offline-compatible.json")
    args = parser.parse_args()
    destination = ROOT / args.output
    if destination.exists():
        raise FileExistsError("Refusing to overwrite a conservation result")
    initial = _verify_manifest(ROOT / INITIAL_FREEZE)
    frozen = _verify_manifest(ROOT / args.freeze)
    required = {"scripts/evaluate_conservation_v6_compatible.py", "tests/test_conservation_v6_adapter.py",
                INITIAL_FREEZE, INITIAL_RESULT}
    if not required <= {item["path"] for item in frozen["files"]}:
        raise ValueError("Adapter freeze must protect adapter, tests, initial freeze and initial failed result")
    original_required = {"data/conservation-v6-cases.json", "research/conservation-v6-offline-protocol.md",
                         "scripts/evaluate_conservation_v6.py", "tests/test_conservation_v6_cases.py", "retrace/conservation_v6.py"}
    if not original_required <= {item["path"] for item in initial["files"]}:
        raise ValueError("Initial freeze omits required original dependencies")
    corpus_path = ROOT / "data/conservation-v6-cases.json"
    if _digest(corpus_path) != CORPUS_SHA256:
        raise ValueError("Locked corpus changed")
    started = datetime.now(timezone.utc)
    for manifest in (initial, frozen):
        if started <= datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00")):
            raise ValueError("Replay must follow both freezes")
    from retrace.conservation_v6 import audit_conservation
    scored = evaluate_compatible(json.loads(corpus_path.read_text(encoding="utf-8")), audit_conservation)
    scored.update(generated_at=started.isoformat(), corpus_sha256=CORPUS_SHA256,
                  initial_freeze_sha256=_digest(ROOT / INITIAL_FREEZE),
                  initial_result_sha256=_digest(ROOT / INITIAL_RESULT),
                  adapter_freeze_path=args.freeze, adapter_freeze_sha256=_digest(ROOT / args.freeze))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(scored, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(destination), "base": scored["base"], "metamorphic": scored["metamorphic"]}, indent=2))


if __name__ == "__main__":
    main()
