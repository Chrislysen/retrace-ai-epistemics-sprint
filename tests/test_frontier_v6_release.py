"""Offline packaging integrity tests; never creates a real release or model call."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import assemble_frontier_v6_release as release


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def inventory(root,names):
    entries=[{"path":name,"sha256":release.sha(root/name)} for name in names]
    digest=hashlib.sha256(release.canonical(sorted(entries,key=lambda x:x['path'])).encode()).hexdigest()
    return {"schema":release.SCHEMA,"files":entries,
            "content_review":{"reviewed":True,"file_set_sha256":digest,"reviewer":"Synthetic test reviewer",
                              "scope":"Synthetic fixture only; no human review claim"}}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/"README.md").write_text("Historical bytes must stay unchanged.\n",encoding="utf-8")
        (self.root/"README-V6-FRONTIER.md").write_text("New entrypoint.\n",encoding="utf-8")

    def test_exact_inventory_and_bound_content_review(self):
        inv=inventory(self.root,["README.md","README-V6-FRONTIER.md"])
        indexed,_=release.validate_files(self.root,inv)
        self.assertEqual(len(indexed),2)
        changed=deepcopy(inv);changed['content_review']['file_set_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'content_review'):release.validate_files(self.root,changed)

    def test_changed_file_and_case_alias_duplicate_rejected(self):
        inv=inventory(self.root,["README.md"])
        (self.root/"README.md").write_text("changed",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'file_changed'):release.validate_files(self.root,inv)
        inv=inventory(self.root,["README.md"]);inv['files'].append(deepcopy(inv['files'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate_inventory'):release.validate_files(self.root,inv)

    def test_traversal_absolute_and_private_roots_rejected(self):
        for name in ("../README.md","C:/secret.txt","/etc/passwd","data/../README.md","data\\private.txt",".env","attachments/paste.txt"):
            with self.subTest(name=name),self.assertRaises(ValueError):release.safe_path(self.root,name)

    def test_credential_split_across_read_boundary_is_rejected(self):
        path=self.root/"research/sample.txt";path.parent.mkdir()
        # Synthetic marker only: never reads or uses a real credential.
        marker=b'pt_' + b'live_' + b'Z'*32
        path.write_bytes(b'a'*(1024*1024-4)+marker)
        with self.assertRaisesRegex(ValueError,'credential_pattern'):release.scan_credentials(path)

    def test_docx_compressed_xml_is_scanned(self):
        path=self.root/"report/sample.docx";path.parent.mkdir()
        with ZipFile(path,'w') as doc:doc.writestr('word/document.xml',b'pt_'+b'live_'+b'Z'*32)
        with self.assertRaisesRegex(ValueError,'credential_pattern'):release.scan_credentials(path)

    def test_embedded_provider_identifier_is_not_a_standalone_key(self):
        path=self.root/'README.md'
        path.write_bytes(b'opaqueIdentifier'+b'sk-'+b'Z'*32)
        release.scan_credentials(path)
        path.write_bytes(b'"'+b'sk-'+b'Z'*32+b'"')
        with self.assertRaisesRegex(ValueError,'credential_pattern'):release.scan_credentials(path)

    def test_archive_preserves_workspace_and_does_not_overwrite(self):
        inv=inventory(self.root,["README.md","README-V6-FRONTIER.md"])
        before=(self.root/"README.md").read_bytes();output=self.root/"deliverables/release.zip"
        result=release.assemble(self.root,inv,output,{"status":"synthetic_fixture_only"})
        with ZipFile(output) as archive:
            self.assertEqual(archive.read('artifact/README.md'),before)
            self.assertIn(b'artifact/README-V6-FRONTIER.md',archive.read('README.md'))
            self.assertEqual(len(archive.namelist()),4)
        self.assertEqual((self.root/"README.md").read_bytes(),before)
        self.assertFalse(result['submitted'])
        with self.assertRaisesRegex(ValueError,'new_deliverable'):release.assemble(self.root,inv,output,{})

    def test_changed_bytes_between_validation_and_assembly_are_not_published(self):
        inv=inventory(self.root,["README.md"])
        (self.root/"README.md").write_text('changed after review')
        output=self.root/"deliverables/release.zip"
        with self.assertRaisesRegex(ValueError,'changed_during_assembly'):release.assemble(self.root,inv,output,{})
        self.assertFalse(output.exists())

    def test_live_or_unclosed_audit_refuses_release(self):
        with patch.object(release,'validate_files',return_value=({},'synthetic')):
            with patch('scripts.audit_frontier_v6f_run.audit_workspace',side_effect=ValueError('final_closure_required_but_run_incomplete')):
                with self.assertRaisesRegex(ValueError,'closure_required'):release.validate_release(release.ROOT,{})

    def test_closed_but_censored_audit_is_not_complete_study(self):
        evidence={'integrity':'passed_captured_evidence','final_closed':True,'all_scheduled_outcomes_recorded':False}
        with patch.object(release,'validate_files',return_value=({},'synthetic')):
            with patch('scripts.audit_frontier_v6f_run.audit_workspace',return_value=evidence):
                with self.assertRaisesRegex(ValueError,'study_incomplete'):release.validate_release(release.ROOT,{})

    def test_real_working_manuscript_cannot_pass_final_report_gate(self):
        folder=release.ROOT/'report/v6-cycle';layout=release.load(folder/'layout.json')
        if layout['release_status']!='working_draft_pending_primary_results':self.skipTest('Manuscript is no longer a working draft')
        names={'research-draft.md','author-metadata.json','layout.json','build-manifest.json','render-manifest.json','visual-review.json',
               layout['output_stem']+'.docx',layout['output_stem']+'.pdf','build_report.py','render_report.ps1','render_pdf_pages.py',
               'verify_report.py','artifact.md','README.md','references.bib'}
        indexed={'report/v6-cycle/'+name:release.sha(folder/name) for name in names}
        with self.assertRaisesRegex(ValueError,'report_still_draft'):release.validate_report(release.ROOT,indexed,{})

    def view_fixture(self):
        files={};mapping=[];source_hashes={};view_rows={};view_hashes={}
        for study,sid in [('primary','P'),('regression','R')]:
            path=self.root/('data/frontier-v6f-'+('sessions' if study=='primary' else 'regression-sessions')+'.json')
            write(path,[{'slot_id':sid}]);source_hashes[study+'_sessions']=release.sha(path)
        for kind in ('requests','responses'):
            lines=[(json.dumps({'slot_id':sid,'content':'Exact 🧭 bytes'},ensure_ascii=False)+'\n').encode() for sid in ('R','P')]
            path=self.root/'results/frontier-v6f/combined'/(kind+'.jsonl');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b''.join(lines))
            source_hashes[kind]=release.sha(path)
            for i,(study,sid,line) in enumerate(zip(('regression','primary'),('R','P'),lines),1):
                dest=self.root/'results/frontier-v6f/study-views'/(study+'-'+kind+'.jsonl');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(line)
                view_hashes[(study,kind)]=release.sha(dest)
                mapping.append({'journal':kind,'source_line':i,'study':study,'view_line':1,'slot_id':sid,'line_sha256':release.sha(dest)})
        return {'schema':'retrace.frontier-v6f-lossless-study-views.v1','planned':{'primary':1,'regression':1},
                'sources':{key:{'sha256':value} for key,value in source_hashes.items()},'line_mapping':mapping,
                'files':[{'path':study+'-'+kind+'.jsonl','sha256':view_hashes[(study,kind)],'records':1,'study':study,'journal':kind}
                         for study in ('primary','regression') for kind in ('requests','responses')]}

    def test_lossless_views_reject_semantically_equal_reformatted_lines(self):
        manifest=self.view_fixture();release.verify_views(self.root,manifest)
        path=self.root/'results/frontier-v6f/study-views/primary-responses.jsonl'
        path.write_text(json.dumps(json.loads(path.read_text(encoding='utf-8')),separators=(',',':'))+'\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'view_line_changed'):release.verify_views(self.root,manifest)

    def test_view_mapping_and_unlogged_extra_lines_rejected(self):
        manifest=self.view_fixture();changed=deepcopy(manifest);changed['line_mapping'][0]['source_line']=99
        with self.assertRaisesRegex(ValueError,'manifest_mismatch'):release.verify_views(self.root,changed)
        path=self.root/'results/frontier-v6f/study-views/regression-responses.jsonl'
        with path.open('ab') as stream:stream.write(b'{"slot_id":"extra"}\n')
        with self.assertRaisesRegex(ValueError,'extra_lines'):release.verify_views(self.root,manifest)

    def test_supplement_closed_assertion_cannot_replace_exact_input_and_replay_binding(self):
        gates={'primary_summary':'results/primary.json','primary_audits':'results/audits.jsonl',
               'natural_ensemble_summary':'results/natural.json'}
        names=['data/frontier-v6c-staged.json','data/frontier-v6f-sessions.json',gates['primary_summary'],gates['primary_audits'],
               'scripts/audit_natural_ensembles_v6.py']
        for name in names:write(self.root/name,[])
        freeze={'files':[{'path':'scripts/audit_natural_ensembles_v6.py','sha256':release.sha(self.root/names[-1])}]}
        write(self.root/release.NATURAL_FREEZE,freeze)
        core={'schema':'retrace.natural-ensemble-audit.v6','summary':{'observed':0}}
        result={**core,'run_declared_closed':True,'primary_status':'complete_records','primary_all_planned_final_outcomes':True,
                'implementation_sha256':freeze['files'][0]['sha256'],
                'inputs':{str((self.root/name).resolve()):{'sha256':release.sha(self.root/name),'bytes':(self.root/name).stat().st_size}
                          for name in names[:4]}}
        write(self.root/gates['natural_ensemble_summary'],result)
        indexed={name:release.sha(self.root/name) for name in names+[release.NATURAL_FREEZE,gates['natural_ensemble_summary']]}
        class SyntheticAnalyzer:
            @staticmethod
            def audit_ensembles(*_):return core
        with patch.object(release,'NATURAL_FREEZE_SHA256',indexed[release.NATURAL_FREEZE]),patch.object(release.importlib,'import_module',return_value=SyntheticAnalyzer):
            release.verify_natural(self.root,indexed,gates,[])
            changed=deepcopy(result);changed['inputs'][str((self.root/gates['primary_audits']).resolve())]['sha256']='0'*64
            write(self.root/gates['natural_ensemble_summary'],changed)
            with self.assertRaisesRegex(ValueError,'input_binding'):release.verify_natural(self.root,indexed,gates,[])
            changed=deepcopy(result);changed['summary']['observed']=1
            write(self.root/gates['natural_ensemble_summary'],changed)
            with self.assertRaisesRegex(ValueError,'replay_mismatch'):release.verify_natural(self.root,indexed,gates,[])

    def test_final_report_must_bind_each_selected_result_not_merely_some_evidence(self):
        gates={key:'results/'+key+'.json' for key in ('primary_summary','primary_audits','regression_summary','split_manifest','natural_ensemble_summary')}
        indexed={path:str(i)*64 for i,path in enumerate(gates.values())}
        build={'evidence_inputs':dict(indexed)}
        release.verify_report_result_bindings(build,indexed,gates)
        for name in gates.values():
            with self.subTest(missing=name):
                changed=deepcopy(build);changed['evidence_inputs'].pop(name)
                with self.assertRaisesRegex(ValueError,'not_built_against_final'):release.verify_report_result_bindings(changed,indexed,gates)
            with self.subTest(stale=name):
                changed=deepcopy(build);changed['evidence_inputs'][name]='f'*64
                with self.assertRaisesRegex(ValueError,'not_built_against_final'):release.verify_report_result_bindings(changed,indexed,gates)

    def test_page_count_cannot_hide_duplicate_missing_or_unreviewed_pages(self):
        render={'total_pages':2,'pages':[{'page':1,'path':'render/page-1.png'},{'page':2,'path':'render/page-2.png'}]}
        visual={'inspected_pages':[1,2],'unresolved_visual_issues':[],'page_hashes':{'1':'a'*64,'2':'b'*64}}
        release.verify_page_inventory(render,visual)
        changed=deepcopy(render);changed['pages'][1]=deepcopy(changed['pages'][0])
        with self.assertRaisesRegex(ValueError,'page_sequence'):release.verify_page_inventory(changed,visual)
        changed=deepcopy(render);changed['pages'][1]['path']='RENDER/PAGE-1.PNG'
        with self.assertRaisesRegex(ValueError,'duplicate_page_path'):release.verify_page_inventory(changed,visual)
        changed=deepcopy(visual);changed['page_hashes'].pop('2')
        with self.assertRaisesRegex(ValueError,'hash_page_keys'):release.verify_page_inventory(render,changed)


if __name__=='__main__':unittest.main()
