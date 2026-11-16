"""Offline release admission/tamper tests; synthetic files live only in temp dirs.

Scoring and transport mathematics are tested by their frozen suites. These tests
check the packaging boundary, including byte-preserving views and report binds.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import reproduce_frontier_v6k_release as r
from scripts import assemble_frontier_v6k_release as a


def gate_values():
    old = {"passed": True, "final_closed": True, "schedule_status": "stopped", "counts": {"issued_attempts": 6}}
    middle = {"passed": True, "final_closed": True, "schedule_status": "stopped", "counts": {"issued_attempts": 207, "dependency_skips": 11}}
    audit = {"schema": "retrace.frontier-v6k-runtime-independent-audit.v1", "passed": True,
        "final_closed": True, "all_scheduled_outcomes_accounted": True, "schedule_status": "completed",
        "planned_slots": 1576, "original_planned_slots": 1800, "carried_over_slots": 224, "prior_segment_audits": {"i": old, "j": middle}}
    runtime = {"schema": "retrace.adaption-v6k-summary.v1", "status": "completed", "stop_reasons": [],
        "planned": 1576, "original_planned": 1800, "carried_over_slots": 224, "slot_outcomes": 1576,
        "all_scheduled_outcomes_recorded": True, "issued_without_outcome_attempt_ids": []}
    score = {"schema": "retrace.frontier-v6k-composite-evaluation.v1", "status": "complete_amended_primary",
        "test_design": False, "schedule_complete": True, "planned_slots": 1800, "base_cases": 60,
        "primary_holm_family_size": 21, "scheduled_final_outcomes_observed": 1800, "missing_final_slot_ids": [],
        "amendment": {"historical_global_failures_preserved": True, "source_rows_changed": False,
            "carried_issued_slots": 213, "carried_final_slots": 224, "carried_dependency_failed_slots": 11,
            "retained_by_segment": {"i": 6, "j": 218}, "continuation_planned_slots": 1576,
            "observed_response_models": {"qwen3.5-397b": "qwen3.5-397b-a17b-nvfp4"},
            "vendor_alias_mapping_documented": False, "weight_identity_verified": False}}
    return score, audit, runtime


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, value):
        path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, allow_nan=False)+"\n").encode())
        return path

    def binding(self, name):
        p = self.root/name
        return {"sha256": r.sha(p), "bytes": p.stat().st_size}

    def report_fixture(self):
        for name in r.REQUIRED_EVIDENCE: self.put(name, b"synthetic final evidence\n")
        artifacts = {role: r.REPORT+"/"+name for role, name in {
            "markdown": "research-draft.md", "docx": "report.docx", "pdf": "report.pdf",
            "build_manifest": "build.json", "render_manifest": "render.json", "verification": "verify.json",
            "visual_review": "visual.json", "builder": "build_docx.py", "source_manifest": "sources.json",
            "authoring_evidence": "authoring.json", "layout": "layout.json", "references": "references.bib",
            "author_metadata": "author-metadata.json"}.items()}
        for role, name in artifacts.items(): self.put(name, ("synthetic "+role).encode())
        evidence = {name: r.sha(self.root/name) for name in r.REQUIRED_EVIDENCE}
        sources = {artifacts[k]: r.sha(self.root/artifacts[k]) for k in ("markdown", "builder", "source_manifest", "authoring_evidence", "layout", "references", "author_metadata")}
        self.put(r.TEMPLATE, b"synthetic official template fixture\n")
        sources[r.TEMPLATE] = r.sha(self.root/r.TEMPLATE)
        template_patch = patch.object(r, "TEMPLATE_SHA", sources[r.TEMPLATE]); template_patch.start(); self.addCleanup(template_patch.stop)
        docx = r.sha(self.root/artifacts["docx"]); pdf = r.sha(self.root/artifacts["pdf"])
        pages = []
        for n in range(1, 6):
            name = r.REPORT+f"/pages/page-{n}.png"; self.put(name, f"synthetic image {n}".encode())
            pages.append({"page": n, "path": name, "sha256": r.sha(self.root/name)})
        self.put(artifacts["build_manifest"], {"scientific_placeholders_remaining": 0,
            "output_sha256": docx, "evidence_inputs": evidence, "source_inputs": sources})
        self.put(artifacts["render_manifest"], {"docx_sha256": docx, "pdf_sha256": pdf,
            "main_pages_including_title": 4, "total_pages": 5, "pages": pages})
        self.put(artifacts["verification"], {"status": "passed", "docx_sha256": docx, "pdf_sha256": pdf})
        self.put(artifacts["visual_review"], {"status": "passed", "docx_sha256": docx, "pdf_sha256": pdf,
            "inspected_pages": list(range(1, 6)), "unresolved_visual_issues": [],
            "page_sha256_by_path": {p["path"]: p["sha256"] for p in pages},
            "review_method": "Synthetic test evidence only", "human_review_complete": False})
        names = set(artifacts.values()) | {p["path"] for p in pages}
        receipt = {"schema": "retrace.v6k-report-release-evidence.v1", "status": "verified",
            "study_status": "complete_amended_primary", "main_pages": 4, "total_pages": 5,
            "files": [{"path": n, **self.binding(n)} for n in sorted(names)], "artifacts": artifacts,
            "evidence_inputs": evidence, "pages": pages, "human_review_complete": False, "submission_ready": False}
        self.put(r.REPORT_RECEIPT, receipt)
        return receipt

    def rewrite_receipt(self, receipt):
        # Rehash changed report files to ensure tests exercise deeper bindings.
        for row in receipt["files"]: row.update(self.binding(row["path"]))
        self.put(r.REPORT_RECEIPT, receipt)

    def score_fixture(self):
        sources = set(r.DATA.values()) | {r.CONTINUATION, r.FREEZE, r.SNAPSHOT, r.ORIGINAL_AUDIT, r.MIDDLE_AUDIT, r.RUNTIME_AUDIT} | r.SEGMENT_FILES
        for name in sources: self.put(name, b"synthetic source bytes\n")
        self.put(r.CONTINUATION, {"prior_journal_files": {}})
        self.put("scripts/score_frontier_v6k.py", b"# synthetic frozen scorer marker\n")
        summary = gate_values()[0]
        summary.update(input_hashes={"synthetic": "value"}, operational_summary={"state": "amended"})
        summary["file_evidence"] = {"execution_freeze": {"path": r.FREEZE, "sha256": r.FREEZE_SHA},
            "source_files": {n: self.binding(n) for n in sources}, "runtime_audits_replayed": True,
            "runtime_input_bindings_rechecked_after_score": True, "frozen_aliases": {},
            "ledger_snapshot": {"path": r.SNAPSHOT, "sha256": r.sha(self.root/r.SNAPSHOT)}, "scope": "Synthetic fixture"}
        result = {"summary": deepcopy(summary), "audits": [{"tuple_serialization": (True, False)}],
            "merged_evidence": {"source_provenance": {"requests": [{"segment": "original", "source_line_one_based": 1}]},
                "source_bindings": {"synthetic": {"sha256": "a"*64, "bytes": 3}}}}
        views = {key: (' {"kind": "'+key+'" }\r\n').encode() for key in r.VIEWS}
        self.put(r.SCORE, summary); self.put(r.SCORE_AUDITS, result["audits"])
        self.put(r.SOURCE_MAPPING, result["merged_evidence"]["source_provenance"])
        self.put(r.DERIVED_CLOSURE, summary["operational_summary"])
        for role, name in r.VIEWS.items(): self.put(name, views[role])
        members = {r.SCORE, r.SCORE_AUDITS, r.SOURCE_MAPPING, r.DERIVED_CLOSURE, *r.VIEWS.values()}
        self.put(r.COMPOSITE_MANIFEST, {"schema": "retrace.frontier-v6k-composite-artifacts.v1",
            "status": "complete_amended_primary", "planned_slots": 1800, "carried_issued_slots": 213,
            "carried_final_slots": 224, "carried_dependency_failed_slots": 11, "retained_by_segment": {"i": 6, "j": 218},
            "continuation_slots": 1576, "source_rows_changed": False, "selected_jsonl_source_bytes_preserved": True,
            "files": {n: self.binding(n) for n in members}, "source_bindings": result["merged_evidence"]["source_bindings"],
            "file_evidence": summary["file_evidence"], "writer_sha256": r.sha(self.root/"scripts/score_frontier_v6k.py")})
        def compute(*args, **kwargs):
            reconstructed = deepcopy(result)
            reconstructed["summary"]["file_evidence"]["frozen_aliases"] = kwargs.get("frozen_aliases", {})
            return reconstructed, views
        return compute, result, views

    def test_completed_amendment_preserves_old_interruption(self):
        score, audit, runtime = gate_values(); r.completed_gate(score, audit, runtime)
        audit["prior_segment_audits"]["i"]["schedule_status"] = "completed"
        with self.assertRaisesRegex(ValueError, "Original interruption"): r.completed_gate(score, audit, runtime)

    def test_no_missing_global_stop_or_repaired_old_failure_can_release(self):
        for object_name, key, value in (("score", "missing_final_slot_ids", ["lost"]),
            ("runtime", "status", "stopped"), ("runtime", "slot_outcomes", 1575),
            ("audit", "passed", False)):
            score, audit, runtime = gate_values(); {"score": score, "audit": audit, "runtime": runtime}[object_name][key] = value
            with self.subTest(object=object_name, key=key), self.assertRaises(ValueError): r.completed_gate(score, audit, runtime)
        score, audit, runtime = gate_values(); score["amendment"]["historical_global_failures_preserved"] = False
        with self.assertRaises(ValueError): r.completed_gate(score, audit, runtime)

    def test_route_alias_claim_and_primary_scope_drift_reject(self):
        for field in ("vendor_alias_mapping_documented", "weight_identity_verified"):
            score, audit, runtime = gate_values(); score["amendment"][field] = True
            with self.assertRaises(ValueError): r.completed_gate(score, audit, runtime)
        score, audit, runtime = gate_values(); score["primary_holm_family_size"] = 20
        with self.assertRaises(ValueError): r.completed_gate(score, audit, runtime)

    def test_missing_results_fail_before_replay_or_output(self):
        with patch.object(a, "ROOT", self.root), patch.object(a, "replay_score") as replay:
            with self.assertRaises(ValueError): a.plan(self.root)
            replay.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_report_all_current_pages_and_sources_pass(self):
        receipt = self.report_fixture(); names, info = r.report_files(self.root)
        self.assertTrue(set(receipt["evidence_inputs"]) <= names)
        self.assertEqual(info["main_pages"], 4); self.assertFalse(info["human_review_complete"])

    def test_report_stale_results_cannot_be_hidden_by_new_inventory(self):
        receipt = self.report_fixture(); self.put(r.SCORE, b"different final score\n")
        self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "Report evidence changed"): r.report_files(self.root)

    def test_report_edited_manuscript_after_build_rejects(self):
        receipt = self.report_fixture(); self.put(receipt["artifacts"]["markdown"], b"edited manuscript\n")
        self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "source changed after build"): r.report_files(self.root)

    def test_report_missing_dependency_and_self_hash_reject(self):
        receipt = self.report_fixture(); path = receipt["artifacts"]["build_manifest"]
        build = r.load(self.root/path); build["source_inputs"].pop(receipt["artifacts"]["layout"]); self.put(path, build)
        self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "source dependencies"): r.report_files(self.root)

    def test_report_duplicate_page_and_missing_visual_page_reject(self):
        receipt = self.report_fixture(); receipt["pages"][1]["path"] = receipt["pages"][0]["path"]
        path = receipt["artifacts"]["render_manifest"]; render = r.load(self.root/path); render["pages"] = receipt["pages"]; self.put(path, render)
        self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "Duplicate page path"): r.report_files(self.root)
        receipt = self.report_fixture(); path = receipt["artifacts"]["visual_review"]
        visual = r.load(self.root/path); visual["inspected_pages"].pop(); self.put(path, visual); self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "All current pages"): r.report_files(self.root)

    def test_report_page_cap_and_unperformed_human_review_reject(self):
        receipt = self.report_fixture(); receipt["main_pages"] = 9; self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "page limits"): r.report_files(self.root)
        receipt = self.report_fixture(); receipt["submission_ready"] = True; self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "unperformed human"): r.report_files(self.root)

    def test_stale_technical_verification_cannot_be_reused(self):
        receipt = self.report_fixture(); path = receipt["artifacts"]["verification"]
        review = r.load(self.root/path); review["pdf_sha256"] = "0"*64; self.put(path, review); self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "Technical verification"): r.report_files(self.root)

    def test_omitted_author_or_template_binding_rejects(self):
        for key in ("author_metadata", "template"):
            receipt = self.report_fixture(); path = receipt["artifacts"]["build_manifest"]
            build = r.load(self.root/path)
            build["source_inputs"].pop(r.TEMPLATE if key == "template" else receipt["artifacts"][key])
            self.put(path, build); self.rewrite_receipt(receipt)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "source dependencies"): r.report_files(self.root)

    def test_documented_judge_walkthrough_matches_frozen_engine(self):
        from retrace.workbench_v6h import demo_brief, analyze_workbench
        brief = demo_brief(); first = analyze_workbench(brief)
        fingerprint = first["declaration_fingerprint"]
        self.assertEqual((len(first["candidate_ids"]), first["planner"]["next_question"]["id"]), (8, "polarity"))
        state = {"answers": {"polarity": False}}
        pruned = analyze_workbench(brief, state, fingerprint)
        witness = next(row for row in pruned["robustness"]["decisions"] if row["decision"] == "RELEASE_D")
        self.assertEqual(len(pruned["candidate_ids"]), 4)
        self.assertEqual((witness["minimum_k"], witness["withdraw"], witness["survives_all_k1"], witness["survives_all_k2"]), (3, ["A", "B", "C"], True, True))
        state["scenario_withdrawals"] = witness["withdraw"]
        exposed = analyze_workbench(brief, state, fingerprint)
        self.assertEqual(exposed["planner"]["next_question"]["id"], "route")
        self.assertTrue(exposed["decisions"]["RELEASE_D"]["interpretations_disagree_on_status"])
        state["answers"]["route"] = True
        settled = analyze_workbench(brief, state, fingerprint)
        self.assertEqual(len(settled["candidate_ids"]), 2); self.assertIsNone(settled["planner"]["next_question"])
        state["scenario_withdrawals"] = []; state["revoked_documents"] = ["demo-source-1"]
        before = deepcopy(state); preview = analyze_workbench(brief, state, fingerprint)
        typed = next(row for row in preview["typed_veto_release"]["witnesses"] if row["decision"] == "SAFE_D")
        self.assertEqual(typed["release"], {"kind": "document", "id": "demo-source-1"})
        self.assertEqual(typed["withdraw"], "B")
        self.assertEqual((tuple(typed["baseline"]), tuple(typed["release_only"]), tuple(typed["joint"])), ((False, False), (True, True), (False, False)))
        self.assertEqual(state, before); self.assertFalse(preview["typed_veto_release"]["state_mutated"])
        self.assertTrue(all(not row["original_active"] for row in preview["record_flags"]["Z"]["by_candidate"].values()))

    def test_exact_replay_accepts_json_tuple_projection_and_relocation_alias(self):
        compute, _, _ = self.score_fixture()
        with patch.object(r.importlib, "import_module", return_value=SimpleNamespace(compute=compute)), \
             patch.object(r, "catalog_files", return_value=(set(), {'fixture': 'separately tested'})) as catalog:
            out = r.replay_score(self.root, {r.LOCK: r.LOCK_ALIAS})
        self.assertTrue(out["all_three_runtime_audits_replayed"]); self.assertTrue(out["source_view_bytes_verified"])
        self.assertIsNotNone(catalog.call_args.kwargs['result'])

    def test_equivalent_json_reformatting_of_journal_view_rejects(self):
        compute, _, _ = self.score_fixture()
        self.put(r.VIEWS["requests"], b'{"kind":"requests"}\n')
        with patch.object(r.importlib, "import_module", return_value=SimpleNamespace(compute=compute)):
            with self.assertRaisesRegex(ValueError, "original source bytes"): r.replay_score(self.root, {})

    def test_source_mapping_and_score_tamper_reject(self):
        compute, _, _ = self.score_fixture(); self.put(r.SOURCE_MAPPING, {"invented": []})
        with patch.object(r.importlib, "import_module", return_value=SimpleNamespace(compute=compute)):
            with self.assertRaisesRegex(ValueError, "source mapping"): r.replay_score(self.root, {})
        compute, _, _ = self.score_fixture(); saved = r.load(self.root/r.SCORE); saved["primary_holm_family_size"] = 20; self.put(r.SCORE, saved)
        with patch.object(r.importlib, "import_module", return_value=SimpleNamespace(compute=compute)):
            with self.assertRaisesRegex(ValueError, "Pure score"): r.replay_score(self.root, {})

    def test_stale_source_receipt_and_unexpected_alias_reject(self):
        self.score_fixture(); saved = r.load(self.root/r.SCORE)
        self.put(r.SNAPSHOT, b"changed ledger\n")
        with self.assertRaisesRegex(ValueError, "ledger receipt"): r.validate_score_file_evidence(self.root, saved)
        self.score_fixture(); saved = r.load(self.root/r.SCORE); saved["file_evidence"]["frozen_aliases"] = {"x": "y"}
        with self.assertRaisesRegex(ValueError, "Unknown scoring"): r.validate_score_file_evidence(self.root, saved)

    def test_zip_roundtrip_exact_bytes_and_exclusive_output(self):
        source = self.put("raw/line.jsonl", b' { "x" : 1 }\r\n')
        row = {"path": "raw/line.jsonl", **self.binding("raw/line.jsonl")}
        manifest = {"schema": r.SCHEMA, "status": "complete_amended_primary", "files": [row]}
        output = self.root/"new.zip"; a.write_zip(output, manifest, {row["path"]: source})
        with ZipFile(output) as archive:
            self.assertEqual(archive.read(row["path"]), source.read_bytes())
            self.assertEqual(json.loads(archive.read(r.MANIFEST_NAME)), manifest)
        before = output.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"): a.write_zip(output, manifest, {row["path"]: source})
        self.assertEqual(output.read_bytes(), before)

    def test_zip_source_mutation_and_case_collision_reject(self):
        p = self.put("raw/a.txt", b"first")
        row = {"path": "raw/a.txt", **self.binding("raw/a.txt")}
        manifest = {"schema": r.SCHEMA, "status": "complete_amended_primary", "files": [row]}
        p.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Input changed"): a.write_zip(self.root/"x.zip", manifest, {row["path"]: p})
        manifest["files"].append({**row, "path": "RAW/A.txt"})
        with self.assertRaisesRegex(ValueError, "Duplicate archive"): a.write_zip(self.root/"y.zip", manifest, {row["path"]: p})

    def test_safe_paths_inventory_and_credentials(self):
        for name in ("../escape", "C:/secret", ".env", "x/__pycache__/x.py", "raw/active.lock", "raw//x"):
            with self.subTest(name=name), self.assertRaises(ValueError): r.safe_path(self.root, name, exists=False)
        p = self.put("safe/a.txt", b"safe"); row = {"path": "safe/a.txt", **self.binding("safe/a.txt")}
        with self.assertRaisesRegex(ValueError, "Duplicate case-folded"): r.entries_index(self.root, [row, row])
        # Constructed synthetic credential-like text, never a real secret.
        p.write_bytes(b"pt_"+b"live_"+b"A"*20)
        with self.assertRaisesRegex(ValueError, "Credential pattern"): r.scan_credentials(p)

    def test_full_release_requires_immutable_freeze_inventory(self):
        manifest = {"schema": r.SCHEMA, "status": "complete_amended_primary", "planned_slots": 1800,
            "base_cases": 60, "primary_holm_family_size": 21, "freeze": {"path": r.FREEZE, "sha256": r.FREEZE_SHA},
            "files": [{"path": "unrelated.txt", "sha256": "0"*64, "bytes": 1}]}
        self.put("unrelated.txt", b"x")
        with self.assertRaises(ValueError): r.verify_inventory(self.root, manifest)

    def inventory_fixture(self):
        names = set(r.ADDITIONS) | r.REQUIRED_EVIDENCE | r.REQUIRED_PRODUCT | {r.LEDGER, r.REPORT_RECEIPT}
        names.discard(r.FREEZE)
        for name in names: self.put(name, b"synthetic inventory fixture\n")
        self.put(r.LOCK_ALIAS, b"preserved inert lock bytes\n")
        names.add(r.LOCK_ALIAS)
        n = 0
        while len(names) < r.FROZEN_COUNT:
            name = f"historical/fixture-{n:04d}.txt"; self.put(name, b"protected\n"); names.add(name); n += 1
        frozen_rows = [{"path": r.LOCK if name == r.LOCK_ALIAS else name, **self.binding(name)} for name in sorted(names)]
        self.put(r.FREEZE, {"files": frozen_rows})
        freeze_sha = r.sha(self.root/r.FREEZE); names.add(r.FREEZE)
        rows = [{"path": name, **self.binding(name)} for name in sorted(names)]
        report = {"fixture": "report checked separately"}
        manifest = {"schema": r.SCHEMA, "status": "complete_amended_primary", "planned_slots": 1800,
            "base_cases": 60, "primary_holm_family_size": 21, "freeze": {"path": r.FREEZE, "sha256": freeze_sha},
            "files": rows, "file_set_sha256": hashlib.sha256(r.canonical(rows).encode()).hexdigest(),
            "frozen_aliases": {r.LOCK: r.LOCK_ALIAS}, "report": report, "symbolic_test_modules": list(r.SYMBOLIC_TESTS)}
        return manifest, freeze_sha, report

    def test_all_1320_frozen_inputs_and_only_inert_lock_alias(self):
        manifest, digest, report = self.inventory_fixture()
        with patch.object(r, "FREEZE_SHA", digest), patch.object(r, "report_files", return_value=({r.REPORT_RECEIPT}, report)), \
             patch.object(r, 'catalog_files', return_value=({r.CATALOG_MANIFEST}, {'fixture': 'separately tested'})):
            checked = r.verify_inventory(self.root, manifest)
            self.assertEqual(checked["frozen_files_verified"], 1320)
            bad = deepcopy(manifest)
            bad["files"] = [x for x in bad["files"] if x["path"] != "historical/fixture-0000.txt"]
            bad["file_set_sha256"] = hashlib.sha256(r.canonical(bad["files"]).encode()).hexdigest()
            with self.assertRaisesRegex(ValueError, "Frozen member missing"): r.verify_inventory(self.root, bad)
            self.put(r.LOCK, b"preserved inert lock bytes\n")
            with self.assertRaisesRegex(ValueError, "must not be installed"): r.verify_inventory(self.root, manifest)

    def test_uninventoried_raw_stream_is_not_silently_excluded(self):
        manifest, digest, report = self.inventory_fixture()
        self.put(r.RUN+"/streams/unlisted.sse", b"retained raw bytes\n")
        with patch.object(r, "FREEZE_SHA", digest), patch.object(r, "report_files", return_value=({r.REPORT_RECEIPT}, report)):
            with self.assertRaisesRegex(ValueError, "Uninventoried study artifact"): r.verify_inventory(self.root, manifest)

    def test_both_historical_audits_and_definitive_skip_counts_are_required(self):
        for alteration in ('missing_j','j_completed','skips','retained'):
            score,audit,runtime=gate_values()
            if alteration=='missing_j':audit['prior_segment_audits'].pop('j')
            if alteration=='j_completed':audit['prior_segment_audits']['j']['schedule_status']='completed'
            if alteration=='skips':audit['prior_segment_audits']['j']['counts']['dependency_skips']=10
            if alteration=='retained':score['amendment']['retained_by_segment']['j']=217
            with self.subTest(alteration=alteration),self.assertRaises(ValueError):r.completed_gate(score,audit,runtime)

    def test_receipt_bound_historical_ledger_is_required_in_score_evidence(self):
        self.score_fixture();name='results/frontier-v6j/budget/ledger.jsonl';self.put(name,b'immutable historical ledger\n')
        self.put(r.CONTINUATION,{'prior_journal_files':{name:r.sha(self.root/name)}})
        score=r.load(self.root/r.SCORE);sources=score['file_evidence']['source_files'];sources[r.CONTINUATION]=self.binding(r.CONTINUATION);sources[name]=self.binding(name)
        r.validate_score_file_evidence(self.root,score)
        sources.pop(name)
        with self.assertRaisesRegex(ValueError,'Exact composite source-file roles'):r.validate_score_file_evidence(self.root,score)

    def catalog_fixture(self):
        from tests.test_frontier_v6k_catalog import fixture, build
        from scripts import export_frontier_v6k_catalog as exporter
        data = fixture(full=True); corpus, study, slots, audits, merged = data
        for role, value in (('corpus', corpus), ('study', study), ('sessions', slots)):
            self.put(r.DATA[role], value)
        self.put(r.SNAPSHOT, b'fixture final snapshot\n')
        sources = {name: self.binding(name) for name in (r.DATA['corpus'], r.DATA['study'], r.DATA['sessions'], r.SNAPSHOT)}
        self.put(r.SCORE, {'file_evidence': {'source_files': sources}})
        artifact_names = (r.SCORE, r.SCORE_AUDITS, r.SOURCE_MAPPING, r.DERIVED_CLOSURE, r.COMPOSITE_MANIFEST, *r.VIEWS.values())
        for name in artifact_names:
            if name != r.SCORE: self.put(name, b'fixture authenticated artifact\n')
        for name in exporter.SOURCES: self.put(name, b'# invented fixture exporter bytes\n')
        value = build(data, full=True)
        value['authentication'] = {'source_freeze_sha256': r.FREEZE_SHA,
            'authenticated_input_bindings': {name: self.binding(name) for name in artifact_names},
            'authenticated_source_bindings': sources, 'exporter_source_sha256': {name: r.sha(self.root/name) for name in exporter.SOURCES},
            'frozen_aliases': {}}
        exporter.write_catalog(self.root, value)
        return {'audits': audits, 'merged_evidence': merged}

    def test_catalog_recomputed_from_all300_authenticated_first_attempts(self):
        result = self.catalog_fixture()
        names, info = r.catalog_files(self.root, {}, result=result)
        self.assertEqual(len(names), 602); self.assertEqual(info['scheduled_slots'], 300)
        self.assertTrue(info['recomputed_from_authenticated_first_attempts'])
        _, inventory_only = r.catalog_files(self.root, {r.LOCK:r.LOCK_ALIAS})
        self.assertFalse(inventory_only['recomputed_from_authenticated_first_attempts'])

    def test_required_real_catalog_cannot_be_replaced_by_missing_or_different_source(self):
        with self.assertRaises(ValueError): r.catalog_files(self.root)
        self.catalog_fixture(); self.put(r.DATA['sessions'], [])
        with self.assertRaisesRegex(ValueError, 'Catalog source changed'): r.catalog_files(self.root)

    def test_rehashed_changed_raw_output_fails_catalog_recomputation(self):
        from retrace.evidence_catalog_v6k import encode
        result = self.catalog_fixture(); manifest = r.load(self.root/r.CATALOG_MANIFEST)
        index_path = r.CATALOG+'/index.json'; index = r.load(self.root/index_path); first = index['entries'][0]
        changed = r.load(self.root/first['entry_path']); changed['raw_output_text'] += '\n altered model output'
        self.put(first['entry_path'], encode(changed)); first['entry_sha256'] = r.sha(self.root/first['entry_path'])
        self.put(index_path, encode(index))
        for name in (first['entry_path'], index_path): manifest['files'][name] = self.binding(name)
        self.put(r.CATALOG_MANIFEST, encode(manifest))
        # Internally consistent local hashes cannot substitute for raw-source replay.
        r.catalog_files(self.root)
        with self.assertRaisesRegex(ValueError, 'authenticated first-attempt projection'):
            r.catalog_files(self.root, {}, result=result)

    def test_catalog_wrong_freeze_and_removed_first_attempt_reject(self):
        result = self.catalog_fixture(); path = self.root/r.CATALOG_MANIFEST; original = path.read_bytes()
        manifest = r.load(path); manifest['source_freeze_sha256'] = '0'*64; self.put(r.CATALOG_MANIFEST, manifest)
        with self.assertRaisesRegex(ValueError, 'Catalog.*first-attempt'): r.catalog_files(self.root, {}, result=result)
        path.write_bytes(original); result['audits'].pop()
        with self.assertRaisesRegex(ValueError, 'Complete first-attempt'): r.catalog_files(self.root, {}, result=result)


if __name__ == "__main__": unittest.main()
