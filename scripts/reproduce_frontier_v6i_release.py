"""Read-only, offline reproduction of a completed v6i release.

Never loads credentials, calls a provider, repairs outputs, or rewrites evidence.
The manifest authenticates local content, not external authorship or truth.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import io
from pathlib import Path, PureWindowsPath
import re
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.reproduce_frontier_v6h_release import canonical, load, require, safe_path, scan_credentials, sha

SCHEMA = "retrace.frontier-v6i-completed-release.v1"
FREEZE = "data/frontier-v6i-freeze.json"
FREEZE_SHA = "156173e0dabc3a6f88c4301847f892f16bd6d0d73fd7c83c6d3dfc64b3a3a600"
FROZEN_COUNT = 1018
BASE = "results/frontier-v6i"
RUN = BASE + "/primary"
LEDGER = BASE + "/budget/ledger.jsonl"
SNAPSHOT = "data/frontier-v6i-ledger-after-study.jsonl"
SCORE = RUN + "/score.json"
SCORE_AUDITS = RUN + "/score-audits.json"
RUNTIME_AUDIT = RUN + "/runtime-audit.json"
AUDITOR = "scripts/audit_frontier_v6i_runtime.py"
REPORT = "report/v6i-study"
REPORT_RECEIPT = REPORT + "/release-evidence.json"
MANIFEST_NAME = "release-manifest-v6i.json"
LOCK = "results/frontier-v6f/budget/active.lock"
LOCK_ALIAS = "provenance/frozen-locks/" + LOCK + ".txt"
DATA = {"corpus": "data/frontier-v6h-corpus.json", "dossiers": "data/frontier-v6h-dossiers.json",
    "study": "data/frontier-v6i-design.json", "sessions": "data/frontier-v6i-sessions.json"}
RAW = {"outcomes": RUN + "/slot-outcomes.jsonl", "attempts": RUN + "/responses.jsonl",
    "requests": RUN + "/requests.jsonl", "run_summary": RUN + "/summary.json"}
REQUIRED_EVIDENCE = {FREEZE, SCORE, SCORE_AUDITS, RUNTIME_AUDIT, RUN + "/run.json", *RAW.values()}
SYMBOLIC_TESTS = (
    "tests.test_tiered_v6h", "tests.test_source_ir_v6h", "tests.test_impact_v6h",
    "tests.test_typed_interventions_v6h", "tests.test_refuter_gate_v6h",
    "tests.test_calibration_v6h", "tests.test_frontier_v6h_canary",
    "tests.test_frontier_v6h_ecological", "tests.test_frontier_v6h_polar_cases",
    "tests.test_frontier_v6i_sessions", "tests.test_frontier_v6i_eval",
    "tests.test_frontier_v6i_driver", "tests.test_frontier_v6i_runtime_audit",
    "tests.test_frontier_v6i_release",
)
ADDITIONS = (
    "scripts/assemble_frontier_v6i_release.py", "scripts/reproduce_frontier_v6i_release.py",
    "tests/test_frontier_v6i_release.py", AUDITOR, "tests/test_frontier_v6i_runtime_audit.py",
    "README-V6I.md", "REPRODUCE-V6I.md", "START-V6I.ps1", "SOURCE-NOTICES-V6.md",
    "retrace/server_v6h.py", "web/v6h/index.html", "web/v6h/app.js", "web/v6h/style.css",
)


def strict_rows(path):
    from scripts.audit_frontier_v6f_run import strict_json
    result = []
    with Path(path).open("rb") as stream:
        for line in stream:
            require(line.endswith(b"\n") and line.strip(), "Incomplete or blank journal line")
            result.append(strict_json(line))
    return result


def entry(root, name):
    p = safe_path(root, name)
    return {"path": name, "sha256": sha(p), "bytes": p.stat().st_size}


def entries_index(root, rows):
    require(isinstance(rows, list) and rows, "Nonempty inventory required")
    indexed = {}; seen = set()
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"path", "sha256", "bytes"}, "Inventory entry schema")
        name = row["path"]; path = safe_path(root, name)
        require(name.casefold() not in seen, "Duplicate case-folded path")
        require(isinstance(row["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", row["sha256"]), "Invalid digest")
        require(type(row["bytes"]) is int and row["bytes"] >= 0, "Invalid size")
        require(path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], "Inventory bytes changed: " + name)
        seen.add(name.casefold()); indexed[name] = row
    return indexed


def completed_gate(score, audit, runtime):
    """Availability failures may remain; a global stop cannot be a final study."""
    require(audit.get("schema") == "retrace.frontier-v6i-runtime-independent-audit.v1"
        and audit.get("passed") is True and audit.get("final_closed") is True
        and audit.get("all_scheduled_outcomes_accounted") is True
        and audit.get("schedule_status") == "completed", "Completed independent runtime audit required")
    require(runtime.get("schema") == "retrace.adaption-v6i-summary.v1" and runtime.get("status") == "completed"
        and runtime.get("stop_reasons") == [] and runtime.get("planned") == 1800
        and runtime.get("slot_outcomes") == 1800 and runtime.get("all_scheduled_outcomes_recorded") is True
        and runtime.get("issued_without_outcome_attempt_ids") == [], "Full scheduled runtime closure required")
    require(score.get("schema") == "retrace.frontier-v6i-evaluation.v1"
        and score.get("status") == "complete_primary" and score.get("test_design") is False
        and score.get("schedule_complete") is True and score.get("planned_slots") == 1800
        and score.get("base_cases") == 60 and score.get("primary_holm_family_size") == 21
        and score.get("scheduled_final_outcomes_observed") == 1800
        and score.get("missing_final_slot_ids") == [], "Authenticated complete 1800-slot score required")


def validate_score_file_evidence(root, saved):
    evidence = saved.get("file_evidence")
    require(isinstance(evidence, dict) and set(evidence) == {"freeze", "raw_files"}, "Scorer authentication receipt required")
    require(set(evidence["freeze"]) == {"path", "sha256"} and evidence["freeze"]["sha256"] == FREEZE_SHA, "Scorer freeze receipt")
    def location(original, expected):
        parts = PureWindowsPath(original).parts
        require(parts[-len(expected.split("/")):] == tuple(expected.split("/")), "Wrong original evidence path")
    location(evidence["freeze"]["path"], FREEZE)
    require(set(evidence["raw_files"]) == set(RAW), "Exact raw scoring roles required")
    for role, name in RAW.items():
        row = evidence["raw_files"][role]
        require(set(row) == {"path", "sha256"}, "Raw role receipt schema")
        location(row["path"], name)
        require(row["sha256"] == sha(safe_path(root, name)), "Stale scoring input: " + role)


def replay_score(root):
    """Pure frozen evaluator; retains first/eventual outcomes and all failures."""
    saved = load(safe_path(root, SCORE)); validate_score_file_evidence(root, saved)
    values = {k: load(safe_path(root, v)) for k, v in DATA.items()}
    runtime = load(safe_path(root, RAW["run_summary"]))
    finals, attempts, requests = (strict_rows(safe_path(root, RAW[k])) for k in ("outcomes", "attempts", "requests"))
    evaluate = importlib.import_module("retrace.frontier_v6i_eval").evaluate
    result = evaluate(values["corpus"], values["dossiers"], values["study"], values["sessions"],
        finals, attempts, requests, runtime, 10000)
    require({k: v for k, v in saved.items() if k != "file_evidence"} == result["summary"], "Pure score replay mismatch")
    require(load(safe_path(root, SCORE_AUDITS)) == result["audits"], "Per-slot scientific audit replay mismatch")
    return {"schema": saved["schema"], "status": saved["status"], "planned_slots": saved["planned_slots"],
        "base_cases": saved["base_cases"], "primary_holm_family_size": saved["primary_holm_family_size"],
        "bootstrap_repeats": 10000, "input_hashes": saved["input_hashes"],
        "score_sha256": sha(safe_path(root, SCORE)), "audits_sha256": sha(safe_path(root, SCORE_AUDITS))}


def report_files(root):
    """Verify finalized report receipt, every page and exact final-study inputs."""
    receipt = load(safe_path(root, REPORT_RECEIPT))
    require(receipt.get("schema") == "retrace.v6i-report-release-evidence.v1"
        and receipt.get("status") == "verified" and receipt.get("study_status") == "complete_primary", "Final report receipt required")
    main = receipt.get("main_pages"); total = receipt.get("total_pages")
    require(type(main) is int and 4 <= main <= 8 and type(total) is int and main <= total <= 100, "Report page limits")
    indexed = entries_index(root, receipt.get("files")); names = set(indexed)
    require(REPORT_RECEIPT not in names, "Report receipt cannot hash itself")
    artifacts = receipt.get("artifacts")
    required = {"markdown", "docx", "pdf", "build_manifest", "render_manifest", "verification", "visual_review"}
    require(isinstance(artifacts, dict) and required <= set(artifacts), "Report artifact roles")
    require(all(isinstance(p, str) and p.startswith(REPORT + "/") and p in names for p in artifacts.values()), "Report role outside inventory")
    require(len({p.casefold() for p in artifacts.values()}) == len(artifacts), "Duplicate report role file")
    for kind, ext in (("markdown", ".md"), ("docx", ".docx"), ("pdf", ".pdf")):
        require(artifacts[kind].endswith(ext), "Report role extension")
    evidence = receipt.get("evidence_inputs")
    require(isinstance(evidence, dict) and REQUIRED_EVIDENCE <= set(evidence), "Report must bind every final evidence role")
    for name, expected in evidence.items():
        require(sha(safe_path(root, name)) == expected, "Report evidence changed: " + name)
    read = lambda role: load(safe_path(root, artifacts[role]))
    build = read("build_manifest"); render = read("render_manifest"); verification = read("verification"); visual = read("visual_review")
    docx = indexed[artifacts["docx"]]["sha256"]; pdf = indexed[artifacts["pdf"]]["sha256"]
    require(build.get("scientific_placeholders_remaining") == 0
        and build.get("output_sha256") == docx and isinstance(build.get("evidence_inputs"), dict)
        and all(build["evidence_inputs"].get(p) == h for p, h in evidence.items()), "Report build/evidence binding")
    require(verification.get("status") == "passed" and visual.get("status") == "passed", "Report technical/visual verification required")
    require(render.get("docx_sha256") == visual.get("docx_sha256") == docx
        and render.get("pdf_sha256") == visual.get("pdf_sha256") == pdf, "Report output/render/visual binding")
    require(render.get("main_pages_including_title") == main and render.get("total_pages") == total, "Report layout counts")
    pages = receipt.get("pages"); sequence = list(range(1, total + 1))
    require(isinstance(pages, list) and [p.get("page") for p in pages] == sequence, "Ordered complete page list")
    require(render.get("pages") == pages and visual.get("inspected_pages") == sequence
        and visual.get("unresolved_visual_issues") == [], "All current pages must be visually reviewed")
    page_hashes = {}
    for page in pages:
        require(set(page) == {"page", "path", "sha256"}, "Page entry schema")
        path = page["path"]
        require(path.startswith(REPORT + "/") and path.lower().endswith(".png") and path in indexed, "Page missing from report inventory")
        require(path.casefold() not in {p.casefold() for p in page_hashes}, "Duplicate page path")
        require(page["sha256"] == indexed[path]["sha256"], "Page digest mismatch")
        page_hashes[path] = page["sha256"]
    require(visual.get("page_sha256_by_path") == page_hashes, "Visual review does not bind all page images")
    require(isinstance(visual.get("review_method"), str) and visual["review_method"].strip(), "Explicit visual review method")
    human = receipt.get("human_review_complete"); submission = receipt.get("submission_ready")
    require(type(human) is bool and type(submission) is bool and visual.get("human_review_complete") is human, "Human review provenance")
    require(not submission or human, "Submission-ready cannot imply unperformed human review")
    names |= set(evidence) | {REPORT_RECEIPT}
    return names, {"receipt_path": REPORT_RECEIPT, "receipt_sha256": sha(safe_path(root, REPORT_RECEIPT)),
        "main_pages": main, "total_pages": total, "pdf_sha256": pdf, "docx_sha256": docx,
        "human_review_complete": human, "submission_ready": submission}


def verify_inventory(root, manifest):
    require(manifest.get("schema") == SCHEMA and manifest.get("status") == "completed_study", "Completed release schema/status")
    require(manifest.get("planned_slots") == 1800 and manifest.get("base_cases") == 60
        and manifest.get("primary_holm_family_size") == 21, "Exact scientific design scope")
    require(manifest.get("freeze") == {"path": FREEZE, "sha256": FREEZE_SHA}, "Unexpected execution freeze")
    indexed = entries_index(root, manifest.get("files"))
    require(hashlib.sha256(canonical(manifest["files"]).encode()).hexdigest() == manifest.get("file_set_sha256"), "Inventory digest")
    require(set(ADDITIONS) | {FREEZE, LEDGER, SNAPSHOT, SCORE, SCORE_AUDITS, RUNTIME_AUDIT, REPORT_RECEIPT} <= set(indexed), "Required release inputs missing")
    require(indexed[FREEZE]["sha256"] == FREEZE_SHA, "Pinned freeze absent")
    frozen = load(safe_path(root, FREEZE)); aliases = manifest.get("frozen_aliases", {})
    require(aliases == {LOCK: LOCK_ALIAS}, "Only the exact historical inert lock alias is permitted")
    seen = set()
    for row in frozen["files"]:
        name = row["path"]; require(name not in seen, "Duplicate frozen entry"); seen.add(name)
        archived = aliases.get(name, name)
        require(archived in indexed and indexed[archived]["sha256"] == row["sha256"]
            and indexed[archived]["bytes"] == row["bytes"], "Frozen member missing or changed: " + name)
    require(len(seen) == FROZEN_COUNT and set(aliases) <= seen, "Complete 1018-file freeze required")
    require(not (Path(root) / LOCK).exists(), "Inert lock must not be installed as an active lock")
    require(not (Path(root) / BASE / "budget/active.lock").exists(), "Study ledger is active")
    require(sha(safe_path(root, LEDGER)) == sha(safe_path(root, SNAPSHOT)), "Closed canonical ledger/snapshot mismatch")
    for path in (Path(root) / BASE).rglob("*"):
        if path.is_file(): require(path.relative_to(root).as_posix() in indexed, "Uninventoried v6i artifact")
    for name in (*RAW.values(), RUN + "/run.json"):
        require(name in indexed, "Missing closed run artifact")
    report_names, report = report_files(root)
    require(report_names <= set(indexed) and report == manifest.get("report"), "Report manifest mismatch")
    require(manifest.get("symbolic_test_modules") == list(SYMBOLIC_TESTS), "Symbolic test scope changed")
    return {"files_verified": len(indexed), "frozen_files_verified": len(seen), "inert_lock_aliases": aliases}


def symbolic_tests():
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(SYMBOLIC_TESTS))
    require(result.wasSuccessful() and not result.skipped, "Offline symbolic tests failed:\n" + stream.getvalue())
    return {"tests_run": result.testsRun, "passed": True, "model_calls": 0,
        "scope": "Selected deterministic symbolic and synthetic tests; not new model experiments."}


def replay_runtime(root, aliases):
    audit = importlib.import_module("scripts.audit_frontier_v6i_runtime").audit(root, FREEZE_SHA,
        frozen_aliases=aliases, ledger_snapshot=SNAPSHOT)
    saved = load(safe_path(root, RUNTIME_AUDIT))
    require(saved == audit, "Independent runtime audit replay mismatch")
    return audit


def verify(root, manifest, *, run_tests=True):
    root = Path(root).resolve()
    require(root == ROOT, "Run this script from the extracted release, not another checkout")
    before = verify_inventory(root, manifest)
    runtime = replay_runtime(root, manifest["frozen_aliases"])
    score = load(safe_path(root, SCORE)); run = load(safe_path(root, RAW["run_summary"]))
    completed_gate(score, runtime, run)
    require(runtime == manifest.get("runtime_audit"), "Release runtime evidence changed")
    scientific = replay_score(root)
    require(scientific == manifest.get("scientific_replay"), "Release scientific evidence changed")
    tests = symbolic_tests() if run_tests else {"not_run": True}
    verify_inventory(root, manifest)
    return {"schema": "retrace.frontier-v6i-offline-reproduction.v1", "status": "verified_completed_study",
        **before, "scientific_replay": scientific, "runtime_audit": runtime,
        "report": manifest["report"], "symbolic_tests": tests, "model_calls_made": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / MANIFEST_NAME)
    parser.add_argument("--manifest-sha256", help="Optional independently obtained expected digest")
    parser.add_argument("--hashes-only", action="store_true", help="Inventory only; does not claim score/runtime reproduction")
    args = parser.parse_args()
    if args.manifest_sha256: require(sha(args.manifest) == args.manifest_sha256, "Manifest digest changed")
    manifest = load(args.manifest)
    result = verify_inventory(ROOT, manifest) if args.hashes_only else verify(ROOT, manifest)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__": main()
