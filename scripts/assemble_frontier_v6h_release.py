"""Create a NEW diagnostic-release manifest/ZIP only after closed canary audit.

All writes are exclusive. No model calls, source mutation, or final-primary claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.reproduce_frontier_v6h_release import (
    ADDITIONS, FREEZE, FREEZE_SHA, LEDGER, RUN, SCHEMA, SYMBOLIC_TESTS,
    canonical, load, replay_canary, report_files, require, safe_path, scan_credentials, sha, symbolic_tests,
)


def plan(root, extras=(), *, with_report=False):
    root = Path(root).resolve()
    require(sha(root / FREEZE) == FREEZE_SHA, "Scientific freeze mismatch")
    freeze = load(root / FREEZE)
    # A later, separately identified provider probe may be running. This release
    # binds the immutable canary ledger snapshot and its independently closed run.
    source_by_archive = {}; aliases = {}
    for entry in freeze["files"]:
        name = entry["path"]
        source = safe_path(root, name, allow_lock=True)
        require(sha(source) == entry["sha256"], "Frozen file changed: " + name)
        archive_name = name
        if name.endswith("/active.lock"):
            archive_name = "provenance/frozen-locks/" + name + ".txt"
            aliases[name] = archive_name
        safe_path(root, archive_name, exists=False)
        source_by_archive[archive_name] = source
    additions = set(ADDITIONS) | {FREEZE, LEDGER} | set(extras)
    report=None
    if with_report:
        report_additions,report=report_files(root);additions.update(report_additions)
    for path in (root / RUN).rglob("*"):
        if path.is_file():
            additions.add(path.relative_to(root).as_posix())
    for name in sorted(additions):
        source_by_archive[name] = safe_path(root, name)
    names = list(source_by_archive)
    require(len({n.casefold() for n in names}) == len(names), "Duplicate archive path")
    entries = []
    for name, path in sorted(source_by_archive.items()):
        scan_credentials(path)
        entries.append({"path": name, "sha256": sha(path), "bytes": path.stat().st_size})
    audit = importlib.import_module("scripts.audit_frontier_v6h_runtime").audit(root)
    require(audit.get("passed") is True and audit.get("final_closed") is True and audit.get("primary_requests") == 0, "Closed diagnostic runtime audit required")
    semantic = replay_canary(root)
    tests = symbolic_tests()
    manifest = {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "diagnostic_primary_unissued", "primary_study_complete": False, "primary_calls": 0,
        "planned_primary_and_diagnostic_slots": 8148, "freeze": {"path": FREEZE, "sha256": FREEZE_SHA},
        "files": entries, "file_set_sha256": hashlib.sha256(canonical(entries).encode()).hexdigest(),
        "frozen_aliases": aliases, "runtime_audit": audit, "canary_score": semantic,
        "report":report,
        "symbolic_test_modules": list(SYMBOLIC_TESTS), "symbolic_tests_at_assembly": tests,
        "fallback": {"path": "deliverables/retrace-v5-sprint-artifact.zip", "scope": "Unchanged earlier completed v5 study; separate evidence, not v6h primary results."},
        "content_scope": "Local research reproducibility package. Mixed third-party licenses retained; this manifest grants no new redistribution rights. No credentials or environment folders included. Credential-pattern scanning is heuristic, not proof of absence.",
        "limitations": ["Canary feasibility failures are retained; a scheduling-completed canary is not a successful primary gate.",
            "The 8148-slot primary/diagnostic plan was frozen but unissued. No primary model comparison is claimed.",
            "Compiled source fidelity is not certified by exact span matching or symbolic correctness.",
            "Human manuscript review and submission are separate from artifact integrity.",
            "Historical reports and README.md are preserved evidence; README-V6.md is the current entrypoint."]}
    return manifest, source_by_archive


def write_zip(output, manifest, sources):
    output = Path(output)
    require(not output.exists(), "Refusing to overwrite an archive")
    expected = {row["path"]: row for row in manifest["files"]}
    require(len(expected) == len(manifest["files"]), "Duplicate manifest member")
    require("release-manifest-v6h.json" not in expected, "Manifest name is reserved")
    require(set(expected) == set(sources), "Archive sources differ from manifest")
    with ZipFile(output, "x", compression=ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for name, source in sorted(sources.items()):
            entry = expected[name]
            require(sha(source) == entry["sha256"] and source.stat().st_size == entry["bytes"], "Input changed before packaging")
            archive.write(source, name)
        archive.writestr("release-manifest-v6h.json", json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    # Check every decompressed member against the manifest, not only ZIP CRCs.
    with ZipFile(output) as archive:
        require(archive.testzip() is None, "Archive CRC failure")
        require(len(archive.namelist()) == len(set(archive.namelist())), "Duplicate ZIP member")
        require(set(archive.namelist()) == set(expected) | {"release-manifest-v6h.json"}, "Archive inventory mismatch")
        for name, entry in expected.items():
            h = hashlib.sha256(); count = 0
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    count += len(block); h.update(block)
            require(count == entry["bytes"] and h.hexdigest() == entry["sha256"], "Packaged bytes changed")
    return {"path": str(output.resolve()), "sha256": sha(output), "bytes": output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="NEW manifest path")
    parser.add_argument("--zip", type=Path, help="Optional NEW ZIP; omit for reviewed inventory only")
    parser.add_argument("--include", action="append", default=[], help="Additional reviewed relative file, e.g. a finalized paper")
    parser.add_argument("--with-report",action="store_true",help="Include the reviewed diagnostic draft and only its 13 current page images")
    args = parser.parse_args()
    require(not args.manifest.exists() and (not args.zip or not args.zip.exists()), "Exclusive outputs required")
    require(not args.zip or args.manifest.resolve() != args.zip.resolve(), "Distinct outputs required")
    manifest, sources = plan(ROOT, args.include, with_report=args.with_report)
    with args.manifest.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write("\n")
    archive = write_zip(args.zip, manifest, sources) if args.zip else None
    print(json.dumps({"manifest": str(args.manifest.resolve()), "manifest_sha256": sha(args.manifest),
        "status": manifest["status"], "files": len(sources), "archive": archive}, indent=2))


if __name__ == "__main__":
    main()
