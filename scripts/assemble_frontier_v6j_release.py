"""Assemble a NEW completed-study release only after all final evidence gates.

All writes are exclusive. This script has no provider or credential operation.
It must not be run while the study, scoring, audit or report review is unfinished.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.reproduce_frontier_v6j_release import (
    ADDITIONS, AUDITOR, BASE, DATA, FREEZE, FREEZE_SHA, FROZEN_COUNT, LEDGER,
    LOCK, LOCK_ALIAS, MANIFEST_NAME, RAW, REPORT_RECEIPT, RUNTIME_AUDIT, RUN, REQUIRED_EVIDENCE,
    SCHEMA, SCORE, SCORE_AUDITS, SNAPSHOT, SYMBOLIC_TESTS, canonical,
    completed_gate, load, replay_runtime, replay_score, report_files, require,
    safe_path, scan_credentials, sha, symbolic_tests,
)

TARGET = "deliverables/v6j/retrace-v6-sprint-artifact.zip"
MANIFEST_TARGET = "deliverables/v6j/release-manifest-v6j.json"


def plan(root, extras=()):
    root = Path(root).resolve()
    require(root == ROOT, "Assemble from this authenticated workspace")
    # Fail before scanning or test execution when final evidence does not exist.
    score = load(safe_path(root, SCORE)); runtime = load(safe_path(root, RUNTIME_AUDIT))
    run = load(safe_path(root, RAW["run_summary"]))
    completed_gate(score, runtime, run)
    require(not (root / BASE / "budget/active.lock").exists(), "Cannot package an active study")
    require(sha(safe_path(root, FREEZE)) == FREEZE_SHA, "Execution freeze changed")
    frozen = load(safe_path(root, FREEZE))
    require(len(frozen["files"]) == FROZEN_COUNT, "Full execution freeze required")
    sources = {}; aliases = {}; seen = set()
    for row in frozen["files"]:
        name = row["path"]
        require(name.casefold() not in seen, "Duplicate frozen name"); seen.add(name.casefold())
        source = safe_path(root, name, allow_lock=name == LOCK)
        require(source.stat().st_size == row["bytes"] and sha(source) == row["sha256"], "Frozen input changed: " + name)
        archive_name = name
        if name == LOCK: archive_name = LOCK_ALIAS; aliases[name] = archive_name
        safe_path(root, archive_name, exists=False)
        sources[archive_name] = source
    require(aliases == {LOCK: LOCK_ALIAS}, "Exactly one known inert historical lock alias")
    require(sha(safe_path(root, LEDGER)) == sha(safe_path(root, SNAPSHOT)), "Closed ledger/snapshot mismatch")
    report_names, report = report_files(root)
    additions = set(ADDITIONS) | REQUIRED_EVIDENCE | {LEDGER, REPORT_RECEIPT} | set(extras) | report_names
    for base in (BASE, "results/frontier-v6i"):
        for path in (root / base).rglob("*"):
            if path.is_file(): additions.add(path.relative_to(root).as_posix())
    # Cover post-freeze static dependencies as well as every frozen input.
    from scripts.score_frontier_v6h import local_dependencies
    starts = [root / p for p in (*ADDITIONS, *report_names) if p.endswith(".py")]
    additions |= {p.relative_to(root).as_posix() for p in local_dependencies(starts)}
    for name in sorted(additions):
        require(name not in (MANIFEST_NAME, TARGET, MANIFEST_TARGET), "Reserved/current output cannot become its own input")
        source = safe_path(root, name)
        if name in sources: require(sources[name] == source, "Archive name collision")
        sources[name] = source
    require(len({n.casefold() for n in sources}) == len(sources), "Duplicate case-folded archive path")
    entries = []
    for name, path in sorted(sources.items()):
        scan_credentials(path)
        entries.append({"path": name, "sha256": sha(path), "bytes": path.stat().st_size})
    # These replay the real finalized raw records; no outcome-dependent repair.
    scientific = replay_score(root, {})
    actual_runtime = load(safe_path(root, RUNTIME_AUDIT))
    require(actual_runtime == runtime, "Runtime changed during assembly")
    tests = symbolic_tests()
    for row in entries:
        source = sources[row["path"]]
        require(sha(source) == row["sha256"] and source.stat().st_size == row["bytes"], "Assembly input changed during replay")
    manifest = {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(), "status": "complete_amended_primary",
        "planned_slots": 1800, "base_cases": 60, "primary_holm_family_size": 21,
        "freeze": {"path": FREEZE, "sha256": FREEZE_SHA}, "files": entries,
        "file_set_sha256": hashlib.sha256(canonical(entries).encode()).hexdigest(), "frozen_aliases": aliases,
        "runtime_audit": actual_runtime, "scientific_replay": scientific, "report": report,
        "symbolic_test_modules": list(SYMBOLIC_TESTS), "symbolic_tests_at_assembly": tests,
        "scope": "An amended complete 1,800-slot study: six original issued outcomes plus 1,794 continuation outcomes. The original interrupted segment remains stopped; its failed diagnostic remains failed.",
        "content_scope": "Local research artifact. Third-party source notices and original licenses remain applicable; no new redistribution rights are granted.",
        "limitations": [
            "Only direct IR and refutation cover all 60 cases across five primary models. Secondary comparisons use their frozen smaller subsets.",
            "Authored synthetic cases and ecological administrative policies do not establish natural-document or clinical accuracy.",
            "A verified source citation location and an accepted graph do not establish textual entailment or source completeness.",
            "Known usage and retained full reservations are conservative accounting, not a verified provider invoice.",
            "The prospectively pinned diagnostic response route is an observed provider identifier, not a vendor-verified alias or verified precision/weight equivalence.",
            "Hashes authenticate local bytes, not a signed provider transcript or independent human scientific review.",
            "All historical failed runs, freezes and older ZIPs remain distinct evidence. The v6j report and README-V6J.md are the current entrypoints.",
        ]}
    return manifest, sources


def write_zip(output, manifest, sources):
    output = Path(output)
    require(not output.exists(), "Refusing to overwrite an archive")
    require(manifest.get("schema") == SCHEMA and manifest.get("status") == "complete_amended_primary", "Wrong release type")
    rows = manifest["files"]; expected = {r["path"]: r for r in rows}
    require(len(expected) == len(rows) and len({n.casefold() for n in expected}) == len(rows), "Duplicate archive member")
    require(MANIFEST_NAME not in expected and set(sources) == set(expected), "Archive inventory/source mismatch")
    for name in expected: safe_path(ROOT, name, exists=False)
    with ZipFile(output, "x", compression=ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for name, source in sorted(sources.items()):
            row = expected[name]
            require(sha(source) == row["sha256"] and Path(source).stat().st_size == row["bytes"], "Input changed before ZIP write")
            archive.write(source, name)
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    with ZipFile(output) as archive:
        names = archive.namelist()
        require(archive.testzip() is None, "ZIP CRC failure")
        require(len(names) == len(set(names)) and set(names) == set(expected) | {MANIFEST_NAME}, "ZIP inventory mismatch")
        for name, row in expected.items():
            h = hashlib.sha256(); size = 0
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""): size += len(block); h.update(block)
            require(size == row["bytes"] and h.hexdigest() == row["sha256"], "ZIP decompressed bytes mismatch")
        require(json.loads(archive.read(MANIFEST_NAME)) == manifest, "Packaged manifest mismatch")
    return {"path": str(output.resolve()), "sha256": sha(output), "bytes": output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / MANIFEST_TARGET)
    parser.add_argument("--zip", type=Path, default=ROOT / TARGET)
    parser.add_argument("--include", action="append", default=[], help="Additional reviewed root-relative artifact")
    args = parser.parse_args()
    require(not args.manifest.exists() and not args.zip.exists() and args.manifest.resolve() != args.zip.resolve(), "Distinct new outputs required")
    expected_dir = (ROOT / "deliverables/v6j").resolve()
    require(expected_dir.is_relative_to(ROOT.resolve())
        and expected_dir.relative_to(ROOT.resolve()).as_posix() == "deliverables/v6j"
        and args.manifest.resolve().parent == expected_dir
        and args.zip.resolve().parent == expected_dir, "Outputs must stay in the new v6j deliverables directory")
    manifest, sources = plan(ROOT, args.include)
    expected_dir.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write("\n")
    archive = write_zip(args.zip, manifest, sources)
    print(json.dumps({"manifest": str(args.manifest.resolve()), "manifest_sha256": sha(args.manifest),
        "status": manifest["status"], "files": len(sources), "archive": archive}, indent=2))


if __name__ == "__main__": main()
