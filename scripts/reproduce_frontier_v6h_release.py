"""Read-only, offline reproduction of a relocated diagnostic v6h release.

No credential loading, provider requests, output repair, or historical mutation.
The manifest is a content-integrity record, not an external digital signature.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCHEMA = "retrace.frontier-v6h-diagnostic-release.v1"
FREEZE = "data/frontier-v6h-canary-freeze.json"
FREEZE_SHA = "6e7cec65992f4f3cc8012fe06d7d8dfbe9de472357ef6fdf6af95c8414e6f8ec"
RUN = "results/frontier-v6h/canary"
LEDGER = "data/frontier-v6h-ledger-after-canary.jsonl"
SYMBOLIC_TESTS = (
    "tests.test_tiered_v6h", "tests.test_source_ir_v6h", "tests.test_impact_v6h",
    "tests.test_typed_interventions_v6h", "tests.test_refuter_gate_v6h",
    "tests.test_calibration_v6h", "tests.test_frontier_v6h_canary",
    "tests.test_frontier_v6h_ecological", "tests.test_frontier_v6h_polar_cases",
)
ADDITIONS = (
    "scripts/assemble_frontier_v6h_release.py", "scripts/reproduce_frontier_v6h_release.py",
    "tests/test_frontier_v6h_release.py", "scripts/audit_frontier_v6h_runtime.py",
    "research/frontier-v6h-runtime-audit.md", "README-V6.md", "REPRODUCE-V6.md",
    "START-V6.ps1", "SOURCE-NOTICES-V6.md",
    "web/v6h/index.html", "web/v6h/app.js", "web/v6h/style.css",
    "results/v6h-ui-verification/workbench.jpg", "research/frontier-v6h-release-ui-evidence.md",
)
SECRET = re.compile(rb"(?:pt_live_[A-Za-z0-9_-]{16,}|(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
REPORT = "report/v6-unified"
REPORT_NAMES = (
    "artifact.md", "author-metadata.json", "build_report.py", "build-manifest.json", "claim-map.md",
    "layout.json", "README.md", "render_pdf_pages.py", "render_report.ps1", "render-manifest.json",
    "render-route.json", "research-draft.md", "verification.json", "visual-review.json",
    "canary-evidence-check.json", "worked-example-check.json", "typed-restoration-check.json",
    "verify_report.py", "verify_report_evidence.py", "verify_worked_example.py", "verify_typed_restoration.py",
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "Duplicate JSON key")
            result[k] = v
        return result
    def reject(_):
        raise ValueError("Nonfinite JSON")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=reject)


def rows(path):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "Duplicate journal key")
            result[k] = v
        return result
    def reject(_):
        raise ValueError("Nonfinite journal value")
    return [json.loads(line, object_pairs_hook=pairs, parse_constant=reject)
            for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def safe_path(root, name, *, exists=True, allow_lock=False):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name, "Invalid relative path")
    parts = PurePosixPath(name).parts
    require(name == "/".join(parts) and not name.startswith("/") and all(p not in (".", "..", "") for p in parts), "Unsafe path")
    forbidden = {".git", ".env", "attachments", "__pycache__", "node_modules"}
    require(not any(p.lower() in forbidden or p.lower().startswith(".venv") for p in parts), "Private/runtime directory")
    require(not name.lower().endswith((".pyc", ".pyo")), "Compiled cache excluded")
    require(allow_lock or not name.lower().endswith(".lock"), "Active lock excluded")
    root = Path(root).resolve()
    target = root.joinpath(*parts)
    require(not any(p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(root)), "Symlink excluded")
    target = target.resolve()
    require(target.is_relative_to(root), "Path escapes root")
    require(not exists or target.is_file(), "Missing release file: " + name)
    return target


def scan_credentials(path):
    tail = b""
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            require(SECRET.search(tail + block) is None, "Credential pattern in release input")
            tail = block[-256:]


def report_files(root):
    """Bind the reviewed draft and current pages, while preserving original paths."""
    def read(name): return load(safe_path(root, REPORT + "/" + name))
    layout=read("layout.json");build=read("build-manifest.json");render=read("render-manifest.json")
    visual=read("visual-review.json");review=read("verification.json");author=read("author-metadata.json")
    require(layout["release_status"] == "working_draft_closed_canary_main_unissued", "Report scope must stay diagnostic")
    require(build["draft_mode"] is True and build["scientific_placeholders_remaining"] == 0, "Report is not the complete diagnostic draft")
    require(review["status"] == "passed" and review["submission_ready"] is False, "Report verification/submission scope")
    require(6 <= render["main_pages_including_title"] <= 8 and render["total_pages"] == 13, "Report page scope")
    require(visual["main_study_unissued"] is True and visual["submission_ready"] is False, "Report claims an issued study")
    require(author["author_count"] == 1 and author["authors"][0]["full_name"] == "Christian Lysenst\u00f8en"
            and author["authors"][0]["affiliation"] == "Inland Norway University of Applied Sciences", "Author identity changed")
    require(author["human_manuscript_review_completed"] is False, "Human review status changed; review release scope")
    stem=layout["output_stem"]
    require(re.fullmatch(r"[A-Za-z0-9._-]+",stem) is not None, "Invalid report stem")
    files={REPORT+"/"+n for n in REPORT_NAMES}|{REPORT+"/"+stem+e for e in (".docx",".pdf")}
    for key,name in (("markdown_sha256","research-draft.md"),("layout_sha256","layout.json"),
                     ("author_metadata_sha256","author-metadata.json"),("builder_sha256","build_report.py")):
        require(build[key] == sha(safe_path(root,REPORT+"/"+name)), "Report input changed")
    require(build["reference_sha256"] == sha(safe_path(root,"report/template-reference.docx")), "Official template changed")
    for ext,key in ((".docx","docx_sha256"),(".pdf","pdf_sha256")):
        digest=sha(safe_path(root,REPORT+"/"+stem+ext))
        require(render[key] == visual[key] == digest,"Report output/visual binding changed")
        if ext==".docx":require(build["output_sha256"] == digest,"Report build output changed")
    pages=render["pages"];sequence=list(range(1,render["total_pages"]+1))
    require([p["page"] for p in pages] == sequence and visual["inspected_pages"] == sequence
            and visual["unresolved_visual_issues"] == [], "All ordered report pages must be reviewed")
    directory=visual["render_directory"]
    require(re.fullmatch(r"render-[A-Za-z0-9]+",directory) is not None,"Unexpected render directory")
    require(PureWindowsPath(render["render_directory"]).name == directory,"Render directory binding")
    for page in pages:
        name="page-"+str(page["page"])+".png"
        require(PureWindowsPath(page["path"]).parts[-2:] == (directory,name),"Unexpected original page path")
        relative=REPORT+"/"+directory+"/"+name
        require(sha(safe_path(root,relative)) == page["sha256"],"Rendered page changed");files.add(relative)
    files.add(REPORT+"/"+directory+"/page-text.txt")
    log=PureWindowsPath(render["canonical_log"]).name
    require(re.fullmatch(r"canonical-[A-Za-z0-9]+\.log",log) is not None,"Invalid render log")
    files.add(REPORT+"/"+log)
    must_bind={RUN+"/"+name for name in ("summary.json","semantic-score.json","requests.jsonl","responses.jsonl","slot-outcomes.jsonl")}
    require(must_bind <= set(build["evidence_inputs"]),"Report not bound to final canary evidence")
    for name,expected in build["evidence_inputs"].items():
        require(sha(safe_path(root,name)) == expected,"Report evidence changed");files.add(name)
    return files,{"folder":REPORT,"main_pages":render["main_pages_including_title"],"total_pages":render["total_pages"],
        "docx_sha256":render["docx_sha256"],"pdf_sha256":render["pdf_sha256"],"human_review_complete":False,"submission_ready":False}


def verify_inventory(root, manifest):
    require(manifest.get("schema") == SCHEMA, "Release schema")
    require(manifest.get("status") == "diagnostic_primary_unissued", "Only a diagnostic release is supported")
    require(manifest.get("primary_study_complete") is False and manifest.get("primary_calls") == 0, "Primary scope changed")
    require(manifest.get("freeze") == {"path": FREEZE, "sha256": FREEZE_SHA}, "Unexpected scientific freeze")
    entries = manifest.get("files")
    require(isinstance(entries, list) and entries, "Empty release inventory")
    seen = set(); indexed = {}
    for entry in entries:
        require(set(entry) == {"path", "sha256", "bytes"}, "File entry schema")
        name = entry["path"]
        path = safe_path(root, name)
        require(name.casefold() not in seen, "Duplicate release path")
        require(re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) is not None, "Invalid hash")
        require(type(entry["bytes"]) is int and entry["bytes"] >= 0, "Invalid byte count")
        require(path.stat().st_size == entry["bytes"] and sha(path) == entry["sha256"], "Release file changed: " + name)
        seen.add(name.casefold()); indexed[name] = entry["sha256"]
    require(hashlib.sha256(canonical(entries).encode()).hexdigest() == manifest.get("file_set_sha256"), "Inventory digest mismatch")
    require(set(ADDITIONS) <= set(indexed), "Reproduction code/docs missing")
    require(indexed.get(FREEZE) == FREEZE_SHA, "Freeze missing from inventory")
    aliases = manifest.get("frozen_aliases", {})
    require(isinstance(aliases, dict), "Alias mapping")
    frozen = load(safe_path(root, FREEZE)); frozen_names = set()
    for entry in frozen["files"]:
        name = entry["path"]; frozen_names.add(name)
        archived_name = aliases.get(name, name)
        if name in aliases:
            require(name.endswith("/active.lock") and archived_name == "provenance/frozen-locks/" + name + ".txt", "Only an inert historical lock alias is allowed")
        require(indexed.get(archived_name) == entry["sha256"], "Frozen dependency absent or changed: " + name)
    require(set(aliases) <= frozen_names, "Alias not in original freeze")
    require(len(frozen_names) == len(frozen["files"]) == 844, "Scientific freeze inventory count")
    require(not (Path(root) / "results/frontier-v6h/budget/active.lock").exists(), "An extracted release must not contain an active lock")
    for name in ("run.json", "requests.jsonl", "responses.jsonl", "slot-outcomes.jsonl", "summary.json", "semantic-score.json"):
        require(RUN + "/" + name in indexed, "Closed canary evidence missing")
    require(LEDGER in indexed, "Closed ledger missing")
    slots = load(safe_path(root, "data/frontier-v6h-canary-sessions.json"))
    by_slot = {s["slot_id"]: s for s in slots}
    require(len(by_slot) == len(slots) == 10 and all(s["condition"] in ("canary_source_ir", "canary_refuter") for s in slots), "Canary-only schedule required")
    for path in (Path(root) / "results/frontier-v6h").rglob("requests.jsonl"):
        require(path.relative_to(Path(root)).as_posix() in indexed, "Uninventoried request journal")
        # Request rows intentionally do not duplicate every slot field. The
        # independent runtime audit below authenticates each reconstructed body.
        require(all(row.get("slot_id") in by_slot for row in rows(path)), "Primary or unknown calls present")
    require(manifest.get("symbolic_test_modules") == list(SYMBOLIC_TESTS), "Symbolic test scope altered")
    if manifest.get("report") is not None:
        required_report,report = report_files(root)
        require(required_report <= set(indexed) and report == manifest["report"],"Reviewed report absent or changed")
    return {"files_verified": len(indexed), "frozen_files_verified": 844, "inert_lock_aliases": aliases}


def replay_canary(root):
    slots = load(Path(root) / "data/frontier-v6h-canary-sessions.json")
    run = Path(root) / RUN
    evaluate = importlib.import_module("scripts.score_frontier_v6h_canary").evaluate
    result = evaluate(slots, rows(run / "slot-outcomes.jsonl"), rows(run / "responses.jsonl"))
    saved = load(run / "semantic-score.json")
    require(all(saved.get(k) == v for k, v in result.items()), "Canary semantic replay mismatch")
    paths = {"sessions": Path(root) / "data/frontier-v6h-canary-sessions.json", "outcomes": run / "slot-outcomes.jsonl", "attempts": run / "responses.jsonl"}
    require(saved.get("input_sha256") == {k: sha(p) for k, p in paths.items()}, "Canary score input bindings mismatch")
    return {k: result[k] for k in ("planned", "observed_attempts", "final_operational_completed", "final_schema_accepted", "final_exact_family", "first_attempt_exact_family")}


def symbolic_tests():
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames(SYMBOLIC_TESTS)
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    require(result.wasSuccessful() and not result.skipped, "Symbolic offline tests failed:\n" + stream.getvalue())
    return {"tests_run": result.testsRun, "passed": True, "provider_calls": 0, "scope": "Selected stdlib symbolic tests; not unfiltered historical discovery or model accuracy."}


def verify(root, manifest, *, run_tests=True):
    root = Path(root).resolve()
    require(root == ROOT, "Run the script from the extracted release, not another checkout")
    before = verify_inventory(root, manifest)
    audit = importlib.import_module("scripts.audit_frontier_v6h_runtime").audit(root, frozen_aliases=manifest.get("frozen_aliases", {}))
    require(audit.get("final_closed") is True and audit.get("primary_requests") == 0, "Runtime closure/primary boundary not verified")
    require(audit.get("passed") is True, "Independent runtime audit did not pass")
    expected = manifest.get("runtime_audit")
    require(audit == expected, "Runtime audit differs from packaged evidence")
    result = {"schema": "retrace.frontier-v6h-offline-reproduction.v1", "status": "verified_diagnostic_primary_unissued", **before,
              "primary_complete": False, "primary_calls": 0, "canary": replay_canary(root), "runtime_audit": audit,
              "symbolic_tests": symbolic_tests() if run_tests else {"not_run": True}, "model_calls_made": 0}
    verify_inventory(root, manifest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "release-manifest-v6h.json")
    parser.add_argument("--manifest-sha256", help="Optional independently supplied expected digest")
    parser.add_argument("--hashes-only", action="store_true", help="Integrity only; does not claim reproduction")
    args = parser.parse_args()
    if args.manifest_sha256:
        require(sha(args.manifest) == args.manifest_sha256, "Manifest digest mismatch")
    manifest = load(args.manifest)
    result = verify_inventory(ROOT, manifest) if args.hashes_only else verify(ROOT, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
