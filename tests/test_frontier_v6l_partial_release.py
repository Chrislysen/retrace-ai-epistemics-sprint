"""Invented stopped evidence only; no live journals, providers or final artifacts."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from scripts import reproduce_frontier_v6l_partial_release as r
from scripts import assemble_frontier_v6l_partial_release as a
from tests.test_frontier_v6l_release import gate_values as complete_values


def gate_values(k_issued=30,k_skipped=2,reason="submission_deadline"):
    score,audit,runtime,receipt=complete_values(k_issued,k_skipped)
    audit["schedule_status"]="stopped";runtime.update(status="stopped",stop_reasons=[reason])
    score.update(schema="retrace.frontier-v6l-partial-evaluation.v1",status="interrupted_amended_diagnostic",
        schedule_complete=False,cluster_intervals=[],paired_comparisons=[{"primary_family_member":True,"view":"first_attempt",
            "p_two_sided_exact":None,"holm_adjusted_p":None} for _ in range(21)],
        operational_summary={"stop_reasons":[reason]})
    score["amendment"]["closure_override"]=False
    issued=score["amendment"]["carried_issued_slots"]+20;skips=score["amendment"]["carried_dependency_failed_slots"]+3
    score["coverage"]={"planned_slots":1800,"stop_reasons":[reason],"slot_categories":{
        "issued":issued,"definitive_dependency_skip":skips,"unissued_censored_by_stop":1800-issued-skips}}
    return score,audit,runtime,receipt


class PartialReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.freeze_sha="a"*64

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
        self.put(artifacts["author_metadata"], {"human_manuscript_review_completed":False,"authors":[{"full_name":"Christian Lysenst\u00f8en",
            "academic_status":"Undergraduate Student","affiliation":"Inland Norway University of Applied Sciences",
            "country":"Norway","display_affiliation":"Undergraduate Student, Inland Norway University of Applied Sciences, Norway"}]})
        self.freeze_sha=r.sha(self.root/r.FREEZE)
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
        receipt = {"schema": "retrace.v6l-partial-report-release-evidence.v1", "status": "verified",
            "study_status": "interrupted_amended_diagnostic", "main_pages": 4, "total_pages": 5,
            "files": [{"path": n, **self.binding(n)} for n in sorted(names)], "artifacts": artifacts,
            "evidence_inputs": evidence, "pages": pages, "human_review_complete": False, "submission_ready": False}
        self.put(r.REPORT_RECEIPT, receipt)
        return receipt

    def rewrite_receipt(self, receipt):
        # Rehash changed report files to ensure tests exercise deeper bindings.
        for row in receipt["files"]: row.update(self.binding(row["path"]))
        self.put(r.REPORT_RECEIPT, receipt)

    def score_fixture(self):
        sources = set(r.DATA.values()) | {r.CONTINUATION,r.FREEZE,r.SNAPSHOT,r.ORIGINAL_AUDIT,r.MIDDLE_AUDIT,r.THIRD_AUDIT,r.RUNTIME_AUDIT} | r.SEGMENT_FILES
        for name in sources:self.put(name,b"invented source bytes\n")
        score,audit,runtime,receipt=gate_values()
        self.put(r.CONTINUATION,receipt);self.put(r.RUNTIME_AUDIT,audit);self.put(r.RAW["run_summary"],runtime)
        for name,path in (("i",r.ORIGINAL_AUDIT),("j",r.MIDDLE_AUDIT),("k",r.THIRD_AUDIT)):
            self.put(path,audit["prior_segment_audits"][name])
        writer="scripts/score_frontier_v6l.py";self.put(writer,b"# invented writer marker\n")
        self.put(r.FREEZE,{"schema":"retrace.frontier-v6l-freeze.v1","scheduled_slots":1800,
            "previous_cumulative_cap_credits":"250","cumulative_cap_credits":"750",
            "files":[{"path":writer,**self.binding(writer)}]})
        self.freeze_sha=r.sha(self.root/r.FREEZE)
        score.update(input_hashes={"invented":"value"})
        score["file_evidence"]={"execution_freeze":{"path":r.FREEZE,"sha256":self.freeze_sha},
            "source_files":{name:self.binding(name) for name in sources},"runtime_input_bindings":{},
            "runtime_audits_replayed":True,"runtime_input_bindings_rechecked_after_score":True,"frozen_aliases":{},
            "ledger_snapshot":{"path":r.SNAPSHOT,"sha256":r.sha(self.root/r.SNAPSHOT)}}
        result={"summary":deepcopy(score),"audits":[{"tuple_serialization":(True,False)}],
            "merged_evidence":{"source_provenance":{"requests":[{"segment":"l","source_line_one_based":1}]},
                "source_bindings":{"invented":{"sha256":"a"*64,"bytes":3}}}}
        views={key:(' {"kind": "'+key+'" }\r\n').encode() for key in r.VIEWS}
        self.put(r.SCORE,score);self.put(r.SCORE_AUDITS,result["audits"])
        self.put(r.SOURCE_MAPPING,result["merged_evidence"]["source_provenance"]);self.put(r.DERIVED_CLOSURE,score["operational_summary"])
        for role,name in r.VIEWS.items():self.put(name,views[role])
        members={r.SCORE,r.SCORE_AUDITS,r.SOURCE_MAPPING,r.DERIVED_CLOSURE,*r.VIEWS.values()}
        self.put(r.COMPOSITE_MANIFEST,{"schema":"retrace.frontier-v6l-partial-artifacts.v1","status":"interrupted_amended_diagnostic",
            "planned_slots":1800,**{k:v for k,v in r.interrupted_gate(score,audit,runtime,receipt).items() if k!="stop_reasons"},"schedule_complete":False,"inference_available":False,
            "source_rows_changed":False,"selected_jsonl_source_bytes_preserved":True,
            "files":{n:self.binding(n) for n in members},"source_bindings":result["merged_evidence"]["source_bindings"],
            "file_evidence":score["file_evidence"],"writer_sha256":r.sha(self.root/writer)})
        def compute(*args,**kwargs):
            self.assertEqual(len(args),8);self.assertEqual(args[1],self.freeze_sha);self.assertIs(kwargs.get("diagnostic"),True)
            reconstructed=deepcopy(result);reconstructed["summary"]["file_evidence"]["frozen_aliases"]=kwargs.get("frozen_aliases",{})
            return reconstructed,views
        return compute,result,views

    def catalog_fixture(self):
        from tests.test_frontier_v6l_catalog import fixture, build
        from scripts import export_frontier_v6l_catalog as exporter
        data = fixture(full=True); corpus, study, slots, audits, merged = data
        for role, value in (('corpus', corpus), ('study', study), ('sessions', slots)):
            self.put(r.DATA[role], value)
        self.put(r.SNAPSHOT, b'fixture final snapshot\n')
        sources = {name: self.binding(name) for name in (r.DATA['corpus'], r.DATA['study'], r.DATA['sessions'], r.SNAPSHOT)}
        self.put(r.SCORE, {'file_evidence': {'source_files': sources, 'runtime_input_bindings': {}}})
        artifact_names = (r.SCORE, r.SCORE_AUDITS, r.SOURCE_MAPPING, r.DERIVED_CLOSURE, r.COMPOSITE_MANIFEST, *r.VIEWS.values())
        for name in artifact_names:
            if name != r.SCORE: self.put(name, b'fixture authenticated artifact\n')
        for name in exporter.SOURCES: self.put(name, b'# invented fixture exporter bytes\n')
        value = exporter.project(*data, diagnostic=True)
        value['authentication'] = {'source_freeze_sha256': self.freeze_sha,
            'authenticated_input_bindings': {name: self.binding(name) for name in artifact_names},
            'authenticated_source_bindings': sources, 'exporter_source_bindings': {name: self.binding(name) for name in exporter.SOURCES},
            'frozen_aliases': {}, 'study_status':'interrupted_amended_diagnostic','diagnostic':True}
        with patch.object(exporter,'verify_plan'): exporter.write_catalog(self.root, value,diagnostic=True)
        return {'audits': audits, 'merged_evidence': merged}

    def test_stopped_reasons_are_preserved_without_whitelist_laundering(self):
        for reason in ('cumulative_budget_stop','submission_deadline','administrative_stop','unsafe_accounting_failure'):
            values=gate_values(reason=reason);out=r.interrupted_gate(*values)
            self.assertEqual(out['stop_reasons'],[reason]);self.assertEqual(out['continuation_slots'],1544)

    def test_complete_status_and_unaudited_orphan_failure_reject(self):
        with self.assertRaises(ValueError):r.interrupted_gate(*complete_values())
        for which,key,value in ((1,'schedule_status','completed'),(1,'passed',False),(2,'status','completed'),
                                (2,'issued_without_outcome_attempt_ids',['orphan']),(2,'stop_reasons',[])):
            values=gate_values();values[which][key]=value
            with self.subTest(which=which,key=key),self.assertRaises(ValueError):r.interrupted_gate(*values)

    def test_all21_null_tests_no_intervals_and_no_closure_override(self):
        for mutation in ('p','holm','ci','missing_test','override','complete'):
            values=gate_values();score=values[0]
            if mutation=='p':score['paired_comparisons'][0]['p_two_sided_exact']=.01
            if mutation=='holm':score['paired_comparisons'][0]['holm_adjusted_p']=.1
            if mutation=='ci':score['cluster_intervals']=[{'interval':[0,1]}]
            if mutation=='missing_test':score['paired_comparisons'].pop()
            if mutation=='override':score['amendment']['closure_override']=True
            if mutation=='complete':score['schedule_complete']=True
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):r.interrupted_gate(*values)

    def test_coverage_cannot_drop_or_relabel_stop_censoring(self):
        for mutation in ('denominator','category','reason','negative'):
            values=gate_values();coverage=values[0]['coverage']
            if mutation=='denominator':coverage['planned_slots']=100
            if mutation=='category':coverage['slot_categories'].pop('unissued_censored_by_stop')
            if mutation=='reason':coverage['stop_reasons']=['a different event']
            if mutation=='negative':coverage['slot_categories']['issued']=-1
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):r.interrupted_gate(*values)

    def test_exact_partial_replay_passes_diagnostic_selector_and_lossless_bytes(self):
        compute,_,_=self.score_fixture()
        with patch.object(r.importlib,'import_module',return_value=SimpleNamespace(compute=compute)),\
             patch.object(r,'catalog_files',return_value=(set(),{'separately_tested':True})),\
             patch.object(r,'refuter_catalog_files',return_value=(set(),{})) as refuters:
            result=r.replay_score(self.root,{r.LOCK:r.LOCK_ALIAS},self.freeze_sha)
        self.assertFalse(result['inference_performed']);self.assertTrue(result['all_four_runtime_audits_replayed'])
        self.assertEqual(result['stop_reasons'],['submission_deadline'])
        self.assertIs(refuters.call_args.kwargs['diagnostic'], True)
        self.assertIsNotNone(refuters.call_args.kwargs['result'])

    def test_reformatted_selected_journal_is_not_lossless(self):
        compute,_,_=self.score_fixture();self.put(r.VIEWS['requests'],b'{"kind":"requests"}\n')
        with patch.object(r.importlib,'import_module',return_value=SimpleNamespace(compute=compute)):
            with self.assertRaisesRegex(ValueError,'original source bytes'):r.replay_score(self.root,{},self.freeze_sha)

    def test_report_requires_partial_scope_and_same_current_review_sources(self):
        receipt=self.report_fixture();names,info=r.report_files(self.root,self.freeze_sha)
        self.assertIn(r.REPORT_RECEIPT,names);self.assertFalse(info['human_review_complete'])
        receipt['study_status']='complete_amended_primary';self.rewrite_receipt(receipt)
        with self.assertRaises(ValueError):r.report_files(self.root,self.freeze_sha)

    def test_partial_report_human_review_and_size_gates_remain_strict(self):
        receipt=self.report_fixture();path=receipt['artifacts']['visual_review'];visual=r.load(self.root/path)
        visual['human_review_complete']=True;self.put(path,visual)
        receipt.update(human_review_complete=True,submission_ready=True);self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError,'Author metadata'):r.report_files(self.root,self.freeze_sha)
        receipt=self.report_fixture();indexed={row['path']:row for row in receipt['files']}
        indexed[receipt['artifacts']['pdf']]['bytes']=25_000_000
        with patch.object(r,'entries_index',return_value=indexed):
            with self.assertRaisesRegex(ValueError,'25,000,000'):r.report_files(self.root,self.freeze_sha)

    def test_partial_catalog_recomputes_all300_with_explicit_banner(self):
        result=self.catalog_fixture();names,info=r.catalog_files(self.root,freeze_sha256=self.freeze_sha,result=result)
        self.assertEqual(info['scheduled_slots'],300);self.assertEqual(len(names),602)
        index=r.load(self.root/(r.CATALOG+'/index.json'));self.assertTrue(index['scope'].startswith('INTERRUPTED STUDY.'))

    def test_complete_catalog_cannot_be_substituted(self):
        self.catalog_fixture();manifest=r.load(self.root/r.CATALOG_MANIFEST)
        manifest.update(schema='retrace.evidence-catalog.v6l.v1',status='complete_amended_primary',schedule_complete=True,inference_available=True)
        self.put(r.CATALOG_MANIFEST,manifest)
        with self.assertRaisesRegex(ValueError,'no complete-status'):r.catalog_files(self.root,freeze_sha256=self.freeze_sha)

    def test_rehashed_raw_output_cannot_change_catalog_content(self):
        result=self.catalog_fixture();manifest=r.load(self.root/r.CATALOG_MANIFEST);index_name=r.CATALOG+'/index.json'
        index=r.load(self.root/index_name);row=index['entries'][0];entry=r.load(self.root/row['entry_path'])
        entry['raw_output_text']+='\n altered';self.put(row['entry_path'],entry);row['entry_sha256']=r.sha(self.root/row['entry_path'])
        self.put(index_name,index)
        for name in (index_name,row['entry_path']):manifest['files'][name]=self.binding(name)
        self.put(r.CATALOG_MANIFEST,manifest)
        with self.assertRaisesRegex(ValueError,'authenticated first-attempt projection'):
            r.catalog_files(self.root,freeze_sha256=self.freeze_sha,result=result)

    def test_missing_evidence_writes_nothing(self):
        with patch.object(a,'ROOT',self.root),patch.object(a,'replay_score') as replay:
            with self.assertRaises(ValueError):a.plan(self.root,'a'*64)
            replay.assert_not_called()
        self.assertEqual(list(self.root.iterdir()),[])

    def test_partial_zip_is_exclusive_and_has_distinct_manifest(self):
        p=self.put('raw/x.jsonl',b' {"unaltered":true} \r\n');row={'path':'raw/x.jsonl',**self.binding('raw/x.jsonl')}
        manifest={'schema':r.SCHEMA,'status':'interrupted_amended_diagnostic','files':[row]};output=self.root/'partial.zip'
        a.write_zip(output,manifest,{row['path']:p})
        with ZipFile(output) as archive:
            self.assertEqual(archive.read(row['path']),p.read_bytes());self.assertIn('release-manifest-v6l-partial.json',archive.namelist())
        with self.assertRaises(ValueError):a.write_zip(output,manifest,{row['path']:p})
        self.assertEqual(a.TARGET,'deliverables/v6l-partial/retrace-v6-sprint-artifact.zip')


    def inventory_fixture(self):
        names = set(r.ADDITIONS) | r.REQUIRED_EVIDENCE | r.REQUIRED_PRODUCT | {r.LEDGER, r.REPORT_RECEIPT}
        names.discard(r.FREEZE)
        for name in names: self.put(name, b"synthetic inventory fixture\n")
        self.put(r.LOCK_ALIAS, b"preserved inert lock bytes\n")
        names.add(r.LOCK_ALIAS)
        n = 0
        while len(names) < 180:
            name = f"historical/fixture-{n:04d}.txt"; self.put(name, b"protected\n"); names.add(name); n += 1
        frozen_rows = [{"path": r.LOCK if name == r.LOCK_ALIAS else name, **self.binding(name)} for name in sorted(names)]
        self.put(r.FREEZE, {"schema":"retrace.frontier-v6l-freeze.v1","scheduled_slots":1800,
            "previous_cumulative_cap_credits":"250","cumulative_cap_credits":"750","files": frozen_rows})
        freeze_sha = r.sha(self.root/r.FREEZE); names.add(r.FREEZE)
        rows = [{"path": name, **self.binding(name)} for name in sorted(names)]
        report = {"fixture": "report checked separately"}
        manifest = {"schema": r.SCHEMA, "status": "interrupted_amended_diagnostic", "schedule_complete":False,"inference_available":False,"planned_slots": 1800,
            "base_cases": 60, "primary_holm_family_size": 21, "freeze": {"path": r.FREEZE, "sha256": freeze_sha},
            "frozen_file_count":len(frozen_rows), "files": rows, "file_set_sha256": hashlib.sha256(r.canonical(rows).encode()).hexdigest(),
            "frozen_aliases": {r.LOCK: r.LOCK_ALIAS}, "report": report, "symbolic_test_modules": list(r.SYMBOLIC_TESTS)}
        return manifest, freeze_sha, report

    def test_dynamic_full_inventory_and_inert_alias_are_required_for_partial_too(self):
        manifest,digest,report=self.inventory_fixture()
        with patch.object(r,'report_files',return_value=({r.REPORT_RECEIPT},report)),\
             patch.object(r,'catalog_files',return_value=({r.CATALOG_MANIFEST},{})),\
             patch.object(r,'refuter_catalog_files',return_value=({r.REFUTER_MANIFEST},{})):
            checked=r.verify_inventory(self.root,manifest,digest)
            self.assertEqual(checked['frozen_files_verified'],180)
            bad=deepcopy(manifest);bad['inference_available']=True
            with self.assertRaisesRegex(ValueError,'cannot claim'):r.verify_inventory(self.root,bad,digest)
            self.put(r.LOCK,b'preserved inert lock bytes\n')
            with self.assertRaisesRegex(ValueError,'must not be installed'):r.verify_inventory(self.root,manifest,digest)

    def test_partial_catalog_must_retain_censored_rows_without_creating_graphs(self):
        from tests.test_frontier_v6l_catalog import fixture,bind
        from scripts.export_frontier_v6l_catalog import project
        data=fixture(full=True);corpus,study,slots,audits,merged=data
        slot=slots[0];sid=slot['slot_id']
        merged['requests']=[r for r in merged['requests'] if r['slot_id']!=sid]
        merged['responses']=[r for r in merged['responses'] if r['slot_id']!=sid]
        row=merged['outcomes'][0]
        for key in ('attempt_id','attempt_number','first_attempt','raw_response'):row.pop(key,None)
        row.update(issued=False,terminal_valid=False,model_outcome='not_issued_global_stop',error='global_stop',output_text='',partial_output_text='',response_status=None)
        audits[0].update(record_observed=False,provider_completed=False,eligible_completed=False,schema_valid=False,strict_bare_json=False,compilation=None,correct=False,error='unavailable')
        bind(merged);value=project(corpus,study,slots,audits,merged,diagnostic=True)
        entry=value['entries'][value['index']['entries'][0]['entry_path']]
        self.assertEqual(value['index']['scheduled_slots'],300);self.assertEqual(entry['metadata']['status'],'not_issued')
        self.assertIsNone(entry['brief']);self.assertEqual(entry['raw_output_text'],'')

if __name__=='__main__':unittest.main()
