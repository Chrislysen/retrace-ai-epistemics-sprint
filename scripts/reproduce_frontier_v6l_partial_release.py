"""Read-only, offline reproduction of an explicitly INTERRUPTED v6l release.

Never loads credentials, calls a provider, repairs outputs, or rewrites evidence.
The manifest authenticates local content, not external authorship or truth.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
from pathlib import Path, PureWindowsPath
import re
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.reproduce_frontier_v6h_release import canonical, load, require, safe_path, scan_credentials, sha
from scripts.reproduce_frontier_v6l_release import (
    json_value, strict_rows, entry, freeze_binding, entries_index, replay_runtime,
    ADDITIONS as COMPLETE_ADDITIONS, SYMBOLIC_TESTS as COMPLETE_SYMBOLIC_TESTS)
from retrace.frontier_v6k_partial import diagnostic_only
from scripts.reproduce_frontier_v6l_refuters import refuter_catalog_files

SCHEMA = "retrace.frontier-v6l-partial-release.v1"
FREEZE = "data/frontier-v6l-freeze.json"
BASE = "results/frontier-v6l"
RUN = BASE + "/continuation"
ORIGINAL = "results/frontier-v6i/primary"
MIDDLE = "results/frontier-v6j/continuation"
THIRD = "results/frontier-v6k/continuation"
COMPOSITE = BASE + "/partial-diagnostic"
CATALOG = BASE + "/partial-catalog"
CATALOG_MANIFEST = CATALOG + "/manifest.json"
LEDGER = BASE + "/budget/ledger.jsonl"
SNAPSHOT = "data/frontier-v6l-ledger-after-continuation.jsonl"
SCORE = COMPOSITE + "/score.json"
SCORE_AUDITS = COMPOSITE + "/score-audits.json"
COMPOSITE_MANIFEST = COMPOSITE + "/partial-manifest.json"
SOURCE_MAPPING = COMPOSITE + "/source-provenance.json"
DERIVED_CLOSURE = COMPOSITE + "/interrupted-closure.json"
CONTINUATION = "data/frontier-v6l-continuation.json"
RUNTIME_AUDIT = RUN + "/runtime-audit.json"
ORIGINAL_AUDIT = ORIGINAL + "/runtime-audit.json"
MIDDLE_AUDIT = MIDDLE + "/runtime-audit.json"
THIRD_AUDIT = THIRD + "/runtime-audit.json"
AUDITOR = "scripts/audit_frontier_v6l_runtime.py"
REPORT = "report/v6l-partial-study"
REPORT_RECEIPT = REPORT + "/release-evidence.json"
TEMPLATE = "report/template-reference.docx"
TEMPLATE_SHA = "0fd7b50198a1b002fa6544df936189538a6c2c55ab0865606139b4127932dda9"
PDF_BYTES_LIMIT = 25_000_000  # Conservative decimal interpretation of the 25 MB submission ceiling.
MANIFEST_NAME = "release-manifest-v6l-partial.json"
LOCK = "results/frontier-v6f/budget/active.lock"
LOCK_ALIAS = "provenance/frozen-locks/" + LOCK + ".txt"
DATA = {"corpus": "data/frontier-v6h-corpus.json", "dossiers": "data/frontier-v6h-dossiers.json",
    "study": "data/frontier-v6i-design.json", "sessions": "data/frontier-v6i-sessions.json"}
RAW = {"outcomes": RUN + "/slot-outcomes.jsonl", "attempts": RUN + "/responses.jsonl",
    "requests": RUN + "/requests.jsonl", "run_summary": RUN + "/summary.json"}
VIEWS = {"requests": COMPOSITE + "/requests.jsonl", "responses": COMPOSITE + "/responses.jsonl",
    "outcomes": COMPOSITE + "/slot-outcomes.jsonl"}
SEGMENT_FILES = {prefix + "/" + name for prefix in (ORIGINAL, MIDDLE, THIRD, RUN)
    for name in ("requests.jsonl", "responses.jsonl", "slot-outcomes.jsonl", "summary.json", "run.json")}
REQUIRED_EVIDENCE = {FREEZE, CONTINUATION, SCORE, SCORE_AUDITS, RUNTIME_AUDIT, ORIGINAL_AUDIT, MIDDLE_AUDIT, THIRD_AUDIT,
    SOURCE_MAPPING, DERIVED_CLOSURE, COMPOSITE_MANIFEST, SNAPSHOT, *VIEWS.values(), *SEGMENT_FILES}
REFUTER_MANIFEST = BASE + '/partial-refuter-catalog/manifest.json'
REQUIRED_PRODUCT = {CATALOG_MANIFEST, REFUTER_MANIFEST}
SYMBOLIC_TESTS = COMPLETE_SYMBOLIC_TESTS + ("tests.test_frontier_v6l_partial_release",)
ADDITIONS = COMPLETE_ADDITIONS + (
    "scripts/assemble_frontier_v6l_partial_release.py", "scripts/reproduce_frontier_v6l_partial_release.py",
    "tests/test_frontier_v6l_partial_release.py", "README-V6L-PARTIAL.md", "REPRODUCE-V6L-PARTIAL.md", "START-V6L-PARTIAL.ps1",
)


def symbolic_tests():
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(SYMBOLIC_TESTS))
    require(result.wasSuccessful() and not result.skipped,"Offline symbolic tests failed:\n"+stream.getvalue())
    return {"tests_run":result.testsRun,"passed":True,"model_calls":0,
        "scope":"Selected symbolic and invented-fixture tests; no model or primary inferential experiment."}


def interrupted_gate(score, audit, runtime, receipt):
    """All four segments stay stopped; accounting must still be fully audited."""
    prior = audit.get("prior_segment_audits", {})
    require(set(prior) == {"i", "j", "k"}, "All three prior interrupted audits required")
    for name in ("i", "j", "k"):
        old = prior[name]
        require(old.get("passed") is True and old.get("final_closed") is True
            and old.get("all_scheduled_outcomes_accounted") is True and old.get("schedule_status") == "stopped",
            "Historical segments must remain independently audited and stopped")
    require(prior["i"].get("counts", {}).get("issued_attempts") == 6
        and prior["j"].get("counts", {}).get("issued_attempts") == 207
        and prior["j"]["counts"].get("dependency_skips") == 11, "Original interruptions retained")
    require(prior["j"].get("original_audit") == prior["i"]
        and prior["k"].get("prior_segment_audits") == {"i":prior["i"], "j":prior["j"]}, "Nested historical proofs differ")
    kcounts = prior["k"].get("counts", {})
    require(type(kcounts.get("issued_slots")) is int and type(kcounts.get("dependency_skips")) is int
        and kcounts["issued_slots"] >= 0 and kcounts["dependency_skips"] >= 0, "Dynamic k definitive counts")
    retained = {"i":6, "j":218, "k":kcounts["issued_slots"] + kcounts["dependency_skips"]}
    carried = sum(retained.values()); issued = 213 + kcounts["issued_slots"]; pending = 1800-carried
    require(0 < pending < 1800 and receipt.get("schema") == "retrace.frontier-v6l-continuation.v1"
        and receipt.get("full_planned_slots") == 1800 and receipt.get("carried_final_slots") == carried
        and receipt.get("carried_issued_slots") == issued and receipt.get("continuation_slots") == pending
        and receipt.get("previous_cumulative_cap_credits") == "250" and receipt.get("cumulative_cap_credits") == "750",
        "Exact dynamic continuation receipt required")
    require(audit.get("schema") == "retrace.frontier-v6l-runtime-independent-audit.v1"
        and audit.get("passed") is True and audit.get("final_closed") is True
        and audit.get("all_scheduled_outcomes_accounted") is True and audit.get("schedule_status") == "stopped"
        and audit.get("planned_slots") == pending and audit.get("counts",{}).get("planned") == pending
        and audit.get("original_planned_slots") == 1800 and audit.get("carried_over_slots") == carried
        and audit.get("budget_cap_credits") == "750"
        and audit.get("historical_carry_credits") == prior["k"].get("cumulative_accounted_credits")
        == receipt.get("historical_conservative_carry_credits"), "Stopped independent runtime audit required")
    reasons=runtime.get('stop_reasons')
    require(isinstance(reasons,list) and reasons and all(isinstance(v,str) and v for v in reasons), 'Actual stop reasons required')
    require(runtime.get("schema") == "retrace.adaption-v6l-summary.v1" and runtime.get("status") == "stopped"
        and runtime.get("planned") == pending
        and runtime.get("original_planned") == 1800 and runtime.get("carried_over_slots") == carried
        and runtime.get("slot_outcomes") == pending and runtime.get("all_scheduled_outcomes_recorded") is True
        and runtime.get("issued_without_outcome_attempt_ids") == []
        and runtime.get("budget",{}).get("cumulative_cap_credits") == "750", "Fully audited stopped accounting without orphan attempts required")
    require(score.get("schema") == "retrace.frontier-v6l-partial-evaluation.v1"
        and score.get("status") == "interrupted_amended_diagnostic" and score.get("test_design") is False
        and score.get("schedule_complete") is False and score.get("planned_slots") == 1800
        and score.get("base_cases") == 60 and score.get("primary_holm_family_size") == 21
        and score.get("scheduled_final_outcomes_observed") == 1800
        and score.get("missing_final_slot_ids") == [] and diagnostic_only(score), "Authenticated 1800-slot diagnostic with21 null comparisons required")
    coverage=score.get('coverage',{});categories=coverage.get('slot_categories',{})
    require(coverage.get('planned_slots')==1800 and coverage.get('stop_reasons')==reasons
        and set(categories)=={'issued','definitive_dependency_skip','unissued_censored_by_stop'}
        and all(type(n) is int and n>=0 for n in categories.values()) and sum(categories.values())==1800,
        'Issued, dependency-failed and censored outcomes must partition all1800 slots')
    require(score.get('operational_summary',{}).get('stop_reasons')==reasons, 'Stop disclosure differs from actual runtime')
    amendment = score.get("amendment", {})
    require(amendment.get("historical_global_failures_preserved") is True
        and amendment.get("source_rows_changed") is False and amendment.get('closure_override') is False
        and amendment.get("carried_issued_slots") == issued
        and amendment.get("carried_final_slots") == carried and amendment.get("carried_dependency_failed_slots") == carried-issued
        and amendment.get("retained_by_segment") == retained and amendment.get("continuation_planned_slots") == pending
        and amendment.get("prior_segment_statuses") == dict.fromkeys(("i","j","k"),"interrupted")
        and amendment.get("previous_cumulative_cap_credits") == "250" and amendment.get("cumulative_cap_credits") == "750"
        and amendment.get("observed_response_models") == {"qwen3.5-397b":"qwen3.5-397b-a17b-nvfp4"}
        and amendment.get("vendor_alias_mapping_documented") is False
        and amendment.get("weight_identity_verified") is False, "Explicit four-segment amendment required")
    return {"retained_by_segment":retained, "carried_final_slots":carried, "carried_issued_slots":issued,
            "carried_dependency_failed_slots":carried-issued, "continuation_slots":pending,'stop_reasons':list(reasons)}

def validate_score_file_evidence(root, saved, freeze_sha256):
    freeze_binding(root,freeze_sha256)
    evidence = saved.get("file_evidence")
    require(isinstance(evidence, dict) and evidence.get("execution_freeze") == {"path": FREEZE, "sha256": freeze_sha256}, "Scorer freeze receipt")
    require(evidence.get("runtime_audits_replayed") is True
        and evidence.get("runtime_input_bindings_rechecked_after_score") is True, "Authenticated scoring receipt required")
    require(evidence.get("frozen_aliases") in ({}, {LOCK: LOCK_ALIAS}), "Unknown scoring relocation alias")
    require(evidence.get("ledger_snapshot") == {"path": SNAPSHOT, "sha256": sha(safe_path(root, SNAPSHOT))}, "Immutable final ledger receipt")
    expected = set(DATA.values()) | {CONTINUATION, FREEZE, SNAPSHOT, ORIGINAL_AUDIT, MIDDLE_AUDIT, THIRD_AUDIT, RUNTIME_AUDIT} | SEGMENT_FILES | set(load(safe_path(root, CONTINUATION))['prior_journal_files'])
    sources = evidence.get("source_files")
    require(isinstance(sources, dict) and set(sources) == expected, "Exact composite source-file roles")
    for name, row in sources.items():
        require(row == {"sha256": sha(safe_path(root, name)), "bytes": safe_path(root, name).stat().st_size}, "Stale composite source: " + name)


def replay_score(root, aliases, freeze_sha256):
    """Frozen composite replay includes all four independent runtime audits."""
    saved = load(safe_path(root, SCORE)); validate_score_file_evidence(root, saved, freeze_sha256)
    compute = importlib.import_module("scripts.score_frontier_v6l").compute
    result, views = compute(root, freeze_sha256, sha(safe_path(root, ORIGINAL_AUDIT)),
        sha(safe_path(root, MIDDLE_AUDIT)), sha(safe_path(root, THIRD_AUDIT)), sha(safe_path(root, RUNTIME_AUDIT)), SNAPSHOT, sha(safe_path(root, SNAPSHOT)), frozen_aliases=aliases, diagnostic=True)
    result = json_value(result)
    # Only the declared local lock alias may differ across relocation.
    reconstructed = result["summary"]
    produced_evidence = reconstructed["file_evidence"]
    expected_evidence = dict(saved["file_evidence"]); expected_evidence["frozen_aliases"] = dict(aliases)
    require(produced_evidence == expected_evidence, "Replayed authentication receipt mismatch")
    require({k: v for k, v in saved.items() if k != "file_evidence"} ==
        {k: v for k, v in reconstructed.items() if k != "file_evidence"}, "Pure score replay mismatch")
    require(load(safe_path(root, SCORE_AUDITS)) == result["audits"], "Per-slot scientific audit replay mismatch")
    require(load(safe_path(root, SOURCE_MAPPING)) == result["merged_evidence"]["source_provenance"], "Lossless source mapping mismatch")
    require(load(safe_path(root, DERIVED_CLOSURE)) == reconstructed["operational_summary"], "Derived closure mismatch")
    require(set(views) == set(VIEWS), "Exact derived view roles")
    for role, name in VIEWS.items():
        require(safe_path(root, name).read_bytes() == views[role], "Derived view differs from original source bytes: " + role)
    composite = load(safe_path(root, COMPOSITE_MANIFEST))
    cohort = interrupted_gate(saved, load(safe_path(root, RUNTIME_AUDIT)), load(safe_path(root, RAW["run_summary"])), load(safe_path(root, CONTINUATION)))
    members = {SCORE, SCORE_AUDITS, SOURCE_MAPPING, DERIVED_CLOSURE, *VIEWS.values()}
    require(composite.get("schema") == "retrace.frontier-v6l-partial-artifacts.v1"
        and composite.get("status") == "interrupted_amended_diagnostic"
        and composite.get("planned_slots") == 1800
        and all(composite.get(key) == value for key,value in cohort.items() if key != "stop_reasons")
        and composite.get("schedule_complete") is False and composite.get("inference_available") is False
        and composite.get("source_rows_changed") is False
        and composite.get("selected_jsonl_source_bytes_preserved") is True, "Interrupted composite manifest scope")
    require(composite.get("files") == {n: {"sha256": sha(safe_path(root, n)), "bytes": safe_path(root, n).stat().st_size} for n in members}
        and composite.get("source_bindings") == result["merged_evidence"]["source_bindings"]
        and composite.get("file_evidence") == saved["file_evidence"]
        and composite.get("writer_sha256") == sha(safe_path(root, "scripts/score_frontier_v6l.py")), "Composite manifest binding")
    _, catalog_replay = catalog_files(root, aliases, freeze_sha256=freeze_sha256, result=result)
    _, refuter_replay = refuter_catalog_files(root, aliases, freeze_sha256=freeze_sha256, result=result, diagnostic=True)
    return {"schema": saved["schema"], "status": saved["status"], "planned_slots": saved["planned_slots"],
        "base_cases": saved["base_cases"], "primary_holm_family_size": saved["primary_holm_family_size"],
        "inference_performed": False, "planned_bootstrap_repeats": 10000, "input_hashes": saved["input_hashes"],
        "score_sha256": sha(safe_path(root, SCORE)), "audits_sha256": sha(safe_path(root, SCORE_AUDITS)),
        "source_mapping_sha256": sha(safe_path(root, SOURCE_MAPPING)), "composite_manifest_sha256": sha(safe_path(root, COMPOSITE_MANIFEST)),
        "all_four_runtime_audits_replayed": True, "stop_reasons":cohort["stop_reasons"], "source_view_bytes_verified": True,
        "catalog_replay": catalog_replay, "controlled_seed_refuter_replay":refuter_replay}


def catalog_files(root, aliases=None, *, freeze_sha256, result=None):
    """Require the real catalog and optionally rebuild it from replayed evidence.

    Hash-only inventory verification does not claim scientific reconstruction.
    The result argument is supplied only by the authenticated replay_score path.
    """
    from retrace.server_v6l import EvidenceCatalog
    from retrace.evidence_catalog_v6l import encode
    from scripts.export_frontier_v6l_catalog import SOURCES, project
    aliases = dict(aliases or {})
    require(aliases in ({}, {LOCK: LOCK_ALIAS}), "Only the inert historical alias is allowed")
    manifest = load(safe_path(root, CATALOG_MANIFEST))
    require(manifest.get('schema')=='retrace.evidence-catalog.v6l-partial.v1'
        and manifest.get('status')=='interrupted_amended_diagnostic'
        and manifest.get('schedule_complete') is False and manifest.get('inference_available') is False,
        "Explicit interrupted l catalog only; no complete-status substitution")
    reader = EvidenceCatalog(root, expected_manifest_sha256=sha(safe_path(root, CATALOG_MANIFEST)), expected_freeze_sha256=freeze_sha256, diagnostic=True)
    index = reader.index()
    require(index['available'] is True, "Real interrupted extraction catalog required")
    names = {CATALOG_MANIFEST, *manifest['files']}
    for name, expected in manifest['files'].items():
        path = safe_path(root, name)
        require(expected == {'sha256': sha(path), 'bytes': path.stat().st_size}, "Catalog member changed")
    expected_artifacts = {n: {'sha256': sha(safe_path(root, n)), 'bytes': safe_path(root, n).stat().st_size}
        for n in (SCORE, SCORE_AUDITS, SOURCE_MAPPING, DERIVED_CLOSURE, COMPOSITE_MANIFEST, *VIEWS.values())}
    require(manifest.get('authenticated_input_bindings') == expected_artifacts, "Catalog binds a different final composite")
    evidence = load(safe_path(root, SCORE))['file_evidence']
    expected_sources = dict(evidence['source_files'])
    for name, binding in evidence['runtime_input_bindings'].items():
        name = SNAPSHOT if name == LEDGER else name
        require(name not in expected_sources or expected_sources[name] == binding, "Contradictory runtime source binding")
        expected_sources[name] = binding
    require(manifest.get('authenticated_source_bindings') == expected_sources, "Catalog source inventory differs from authenticated score")
    require(manifest.get('frozen_aliases') in ({}, {LOCK: LOCK_ALIAS}), "Unknown catalog relocation alias")
    for name, expected in expected_sources.items():
        path = safe_path(root, aliases.get(name, name))
        require(expected == {'sha256': sha(path), 'bytes': path.stat().st_size}, "Catalog source changed")
    require(manifest.get('exporter_source_bindings') == {name: {'sha256':sha(safe_path(root, name)),
        'bytes':safe_path(root,name).stat().st_size} for name in SOURCES},
            "Catalog exporter source changed")
    if result is not None:
        rebuilt = project(load(safe_path(root, DATA['corpus'])), load(safe_path(root, DATA['study'])),
            load(safe_path(root, DATA['sessions'])), result['audits'], result['merged_evidence'], diagnostic=True)
        payloads = {CATALOG+'/index.json': encode(rebuilt['index'])}
        payloads.update({name: encode(value) for name, value in rebuilt['entries'].items()})
        payloads.update({name: encode(value) for name, value in rebuilt['bundles'].items()})
        require(set(payloads) == set(manifest['files']), "Recomputed catalog member inventory differs")
        for name, raw in payloads.items():
            require(safe_path(root, name).read_bytes() == raw, "Catalog differs from authenticated first-attempt projection: "+name)
    return names, {'manifest_sha256': sha(safe_path(root, CATALOG_MANIFEST)),
        'index_sha256': sha(safe_path(root, CATALOG+'/index.json')), 'scheduled_slots': 300,
        'selection_view': 'first_attempt', 'source_freeze_sha256': freeze_sha256,
        'recomputed_from_authenticated_first_attempts': result is not None,
        'scope': 'Derived public-only observation view, not an additional scientific endpoint or source-truth certificate.'}


def report_files(root, freeze_sha256):
    """Verify finalized report receipt, every page and exact final-study inputs."""
    receipt = load(safe_path(root, REPORT_RECEIPT))
    require(receipt.get("schema") == "retrace.v6l-partial-report-release-evidence.v1"
        and receipt.get("status") == "verified" and receipt.get("study_status") == "interrupted_amended_diagnostic", "Final interrupted report receipt required")
    main = receipt.get("main_pages"); total = receipt.get("total_pages")
    require(type(main) is int and 4 <= main <= 8 and type(total) is int and main <= total <= 100, "Report page limits")
    indexed = entries_index(root, receipt.get("files")); names = set(indexed)
    require(REPORT_RECEIPT not in names, "Report receipt cannot hash itself")
    artifacts = receipt.get("artifacts")
    required = {"markdown", "docx", "pdf", "build_manifest", "render_manifest", "verification", "visual_review",
        "builder", "source_manifest", "authoring_evidence", "layout", "references", "author_metadata"}
    require(isinstance(artifacts, dict) and required <= set(artifacts), "Report artifact roles")
    require(all(isinstance(p, str) and p.startswith(REPORT + "/") and p in names for p in artifacts.values()), "Report role outside inventory")
    require(len({p.casefold() for p in artifacts.values()}) == len(artifacts), "Duplicate report role file")
    for kind, ext in (("markdown", ".md"), ("docx", ".docx"), ("pdf", ".pdf")):
        require(artifacts[kind].endswith(ext), "Report role extension")
    require(indexed[artifacts['pdf']]['bytes'] < PDF_BYTES_LIMIT, 'Submission PDF must be smaller than 25,000,000 bytes')
    evidence = receipt.get("evidence_inputs")
    require(isinstance(evidence, dict) and REQUIRED_EVIDENCE <= set(evidence), "Report must bind every final evidence role")
    require(evidence[FREEZE] == freeze_sha256, "Report binds another execution freeze")
    for name, expected in evidence.items():
        require(sha(safe_path(root, name)) == expected, "Report evidence changed: " + name)
    read = lambda role: load(safe_path(root, artifacts[role]))
    author=read("author_metadata")
    require(isinstance(author.get("authors"),list) and len(author["authors"])==1, "Sole author metadata required")
    expected_author={"full_name":"Christian Lysenstøen","affiliation":"Inland Norway University of Applied Sciences",
        "academic_status":"Undergraduate Student","country":"Norway",
        "display_affiliation":"Undergraduate Student, Inland Norway University of Applied Sciences, Norway"}
    require(all(author["authors"][0].get(key)==value for key,value in expected_author.items()), "Exact supplied author and printed affiliation required")
    build = read("build_manifest"); render = read("render_manifest"); verification = read("verification"); visual = read("visual_review")
    docx = indexed[artifacts["docx"]]["sha256"]; pdf = indexed[artifacts["pdf"]]["sha256"]
    require(build.get("scientific_placeholders_remaining") == 0
        and build.get("output_sha256") == docx and isinstance(build.get("evidence_inputs"), dict)
        and all(build["evidence_inputs"].get(p) == h for p, h in evidence.items()), "Report build/evidence binding")
    source_inputs = build.get("source_inputs")
    required_sources = {artifacts[role] for role in ("markdown", "builder", "source_manifest", "authoring_evidence", "layout", "references", "author_metadata")} | {TEMPLATE}
    require(isinstance(source_inputs, dict) and required_sources <= set(source_inputs), "Report must bind current authored source dependencies")
    require(source_inputs[TEMPLATE] == TEMPLATE_SHA, "Official report template binding changed")
    for name, expected in source_inputs.items():
        require(sha(safe_path(root, name)) == expected, "Report source changed after build: " + name)
    require(verification.get("status") == "passed" and visual.get("status") == "passed", "Report technical/visual verification required")
    require(verification.get("docx_sha256") == docx and verification.get("pdf_sha256") == pdf,
        "Technical verification must bind current report outputs")
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
    require(type(author.get('human_manuscript_review_completed')) is bool
        and author['human_manuscript_review_completed'] is human, 'Author metadata and report human-review record must agree')
    if 'build_authentication' in artifacts:
        require(read('build_authentication').get('human_review_complete') is human,
            'Build authentication and report human-review record must agree')
    require(not submission or human, "Submission-ready cannot imply unperformed human review")
    names |= set(evidence) | set(source_inputs) | {REPORT_RECEIPT}
    return names, {"receipt_path": REPORT_RECEIPT, "receipt_sha256": sha(safe_path(root, REPORT_RECEIPT)),
        "main_pages": main, "total_pages": total, "pdf_sha256": pdf, "docx_sha256": docx,
        "human_review_complete": human, "submission_ready": submission}


def verify_inventory(root, manifest, freeze_sha256):
    frozen=freeze_binding(root,freeze_sha256)
    require(manifest.get("schema") == SCHEMA and manifest.get("status") == "interrupted_amended_diagnostic", "Explicit interrupted release schema/status")
    require(manifest.get('schedule_complete') is False and manifest.get('inference_available') is False,
        'Interrupted release cannot claim schedule completion or inference')
    require(manifest.get("planned_slots") == 1800 and manifest.get("base_cases") == 60
        and manifest.get("primary_holm_family_size") == 21, "Exact scientific design scope")
    require(manifest.get("freeze") == {"path": FREEZE, "sha256": freeze_sha256}, "Unexpected execution freeze")
    indexed = entries_index(root, manifest.get("files"))
    require(hashlib.sha256(canonical(manifest["files"]).encode()).hexdigest() == manifest.get("file_set_sha256"), "Inventory digest")
    require(set(ADDITIONS) | REQUIRED_EVIDENCE | REQUIRED_PRODUCT | {LEDGER, REPORT_RECEIPT} <= set(indexed), "Required release inputs missing")
    require(indexed[FREEZE]["sha256"] == freeze_sha256, "Pinned freeze absent")
    aliases = manifest.get("frozen_aliases", {})
    require(aliases == {LOCK: LOCK_ALIAS}, "Only the exact historical inert lock alias is permitted")
    seen = set()
    for row in frozen["files"]:
        name = row["path"]; require(name not in seen, "Duplicate frozen entry"); seen.add(name)
        archived = aliases.get(name, name)
        require(archived in indexed and indexed[archived]["sha256"] == row["sha256"]
            and indexed[archived]["bytes"] == row["bytes"], "Frozen member missing or changed: " + name)
    require(len(seen) > 0 and manifest.get("frozen_file_count") == len(seen) and set(aliases) <= seen, "Complete pinned execution freeze required")
    require(not (Path(root) / LOCK).exists(), "Inert lock must not be installed as an active lock")
    require(not (Path(root) / BASE / "budget/active.lock").exists(), "Study ledger is active")
    require(sha(safe_path(root, LEDGER)) == sha(safe_path(root, SNAPSHOT)), "Closed canonical ledger/snapshot mismatch")
    for base in (BASE, "results/frontier-v6i", "results/frontier-v6j", "results/frontier-v6k"):
        require(not (Path(root)/base/"budget/active.lock").exists(), "No historical/current study worker may be active")
        for path in (Path(root) / base).rglob("*"):
            if path.is_file(): require(path.relative_to(root).as_posix() in indexed, "Uninventoried study artifact")
    for name in (*RAW.values(), RUN + "/run.json"):
        require(name in indexed, "Missing closed run artifact")
    report_names, report = report_files(root, freeze_sha256)
    require(report_names <= set(indexed) and report == manifest.get("report"), "Report manifest mismatch")
    catalog_names, _ = catalog_files(root, aliases, freeze_sha256=freeze_sha256)
    require(catalog_names <= set(indexed), "Required catalog members missing from release")
    refuter_names, _ = refuter_catalog_files(root, aliases, freeze_sha256=freeze_sha256, diagnostic=True)
    require(refuter_names <= set(indexed), "Required controlled-seed refuter members missing from interrupted release")
    require(manifest.get("symbolic_test_modules") == list(SYMBOLIC_TESTS), "Symbolic test scope changed")
    return {"files_verified": len(indexed), "frozen_files_verified": len(seen), "inert_lock_aliases": aliases}






def verify(root, manifest, freeze_sha256, *, run_tests=True):
    root = Path(root).resolve()
    require(root == ROOT, "Run this script from the extracted release, not another checkout")
    before = verify_inventory(root, manifest, freeze_sha256)
    runtime = load(safe_path(root, RUNTIME_AUDIT))
    score = load(safe_path(root, SCORE)); run = load(safe_path(root, RAW["run_summary"]))
    cohort=interrupted_gate(score, runtime, run, load(safe_path(root, CONTINUATION)))
    require(manifest.get('cohort') == cohort, 'Release cohort differs from authenticated segment closure')
    require(runtime == manifest.get("runtime_audit"), "Release runtime evidence changed")
    # compute() independently replays all four runtime segments before scoring.
    scientific = replay_score(root, manifest["frozen_aliases"], freeze_sha256)
    require(scientific == manifest.get("scientific_replay"), "Release scientific evidence changed")
    tests = symbolic_tests() if run_tests else {"not_run": True}
    verify_inventory(root, manifest, freeze_sha256)
    return {"schema": "retrace.frontier-v6l-partial-offline-reproduction.v1", "status": "verified_interrupted_amended_diagnostic",
        **before, "scientific_replay": scientific, "runtime_audit": runtime,
        "report": manifest["report"], "symbolic_tests": tests, "model_calls_made": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / MANIFEST_NAME)
    parser.add_argument("--freeze-sha256", required=True, help="Externally retained exact prospective l freeze digest")
    parser.add_argument("--manifest-sha256", help="Optional independently obtained expected digest")
    parser.add_argument("--hashes-only", action="store_true", help="Inventory only; does not claim score/runtime reproduction")
    args = parser.parse_args()
    if args.manifest_sha256: require(sha(args.manifest) == args.manifest_sha256, "Manifest digest changed")
    manifest = load(args.manifest)
    result = verify_inventory(ROOT, manifest, args.freeze_sha256) if args.hashes_only else verify(ROOT, manifest, args.freeze_sha256)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__": main()
