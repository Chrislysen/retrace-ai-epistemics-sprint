"""Invented release admission fixtures. Execute only after the live sweep closes."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import reproduce_frontier_v6n_release as r
from scripts import assemble_frontier_v6n_release as a

class ReleaseTests(unittest.TestCase):
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
            "academic_status":"Undergraduate Student","affiliation":"University of Inland Norway",
            "country":"Norway","display_affiliation":"Undergraduate Student, University of Inland Norway, Norway"}]})
        self.freeze_sha=r.sha(self.root/r.FREEZE)
        evidence = {name: r.sha(self.root/name) for name in r.REQUIRED_EVIDENCE}
        sources = {artifacts[k]: r.sha(self.root/artifacts[k]) for k in ("markdown", "builder", "source_manifest", "authoring_evidence", "layout", "references", "author_metadata")}
        self.put(r.TEMPLATE, b"synthetic official template fixture\n")
        sources[r.TEMPLATE] = r.sha(self.root/r.TEMPLATE)
        template_patch = patch.object(r, "TEMPLATE_SHA", sources[r.TEMPLATE]); template_patch.start(); self.addCleanup(template_patch.stop)
        docx = r.sha(self.root/artifacts["docx"]); pdf = r.sha(self.root/artifacts["pdf"])
        pages = []
        for n in range(1, 9):
            name = r.REPORT+f"/pages/page-{n}.png"; self.put(name, f"synthetic image {n}".encode())
            pages.append({"page": n, "path": name, "sha256": r.sha(self.root/name)})
        self.put(artifacts["build_manifest"], {"scientific_placeholders_remaining": 0,
            "output_sha256": docx, "evidence_inputs": evidence, "source_inputs": sources})
        self.put(artifacts["render_manifest"], {"docx_sha256": docx, "pdf_sha256": pdf,
            "main_pages_including_title": 7, "total_pages": 8, "pages": pages})
        self.put(artifacts["verification"], {"status": "passed", "docx_sha256": docx, "pdf_sha256": pdf})
        self.put(artifacts["visual_review"], {"status": "passed", "docx_sha256": docx, "pdf_sha256": pdf,
            "inspected_pages": list(range(1, 9)), "unresolved_visual_issues": [],
            "page_sha256_by_path": {p["path"]: p["sha256"] for p in pages},
            "review_method": "Synthetic test evidence only", "human_review_complete": False})
        names = set(artifacts.values()) | {p["path"] for p in pages}
        receipt = {"schema": "retrace.v6n-report-release-evidence.v1", "status": "verified",
            "study_status": "complete_host_recovered_schedule", "main_pages": 7, "total_pages": 8,
            "files": [{"path": n, **self.binding(n)} for n in sorted(names)], "artifacts": artifacts,
            "evidence_inputs": evidence, "pages": pages, "human_review_complete": False, "submission_ready": False}
        self.put(r.REPORT_RECEIPT, receipt)
        return receipt

    def rewrite_receipt(self, receipt):
        # Rehash changed report files to ensure tests exercise deeper bindings.
        for row in receipt["files"]: row.update(self.binding(row["path"]))
        self.put(r.REPORT_RECEIPT, receipt)

    def test_seven_main_pages_and_supplied_author_pass(self):
        self.report_fixture();_,value=r.report_files(self.root,self.freeze_sha)
        self.assertEqual(value['main_pages'],7);self.assertFalse(value['human_review_complete'])

    def test_page_count_or_old_branch_reject(self):
        for key,value in (('main_pages',8),('main_pages',6),('study_status','complete_amended_primary')):
            receipt=self.report_fixture();receipt[key]=value;self.rewrite_receipt(receipt)
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):r.report_files(self.root,self.freeze_sha)

    def test_stale_manuscript_and_missing_author_binding_reject(self):
        receipt=self.report_fixture();self.put(receipt['artifacts']['markdown'],b'changed source');self.rewrite_receipt(receipt)
        with self.assertRaises(ValueError):r.report_files(self.root,self.freeze_sha)
        receipt=self.report_fixture();build=r.load(self.root/receipt['artifacts']['build_manifest'])
        del build['source_inputs'][receipt['artifacts']['author_metadata']]
        self.put(receipt['artifacts']['build_manifest'],build);self.rewrite_receipt(receipt)
        with self.assertRaises(ValueError):r.report_files(self.root,self.freeze_sha)

    def test_duplicate_page_cannot_stand_in_for_missing_page(self):
        receipt=self.report_fixture();receipt['pages'][1]=deepcopy(receipt['pages'][0]);self.rewrite_receipt(receipt)
        with self.assertRaises(ValueError):r.report_files(self.root,self.freeze_sha)

    def test_obsolete_display_or_fake_human_review_reject(self):
        receipt=self.report_fixture();author=r.load(self.root/receipt['artifacts']['author_metadata'])
        author['authors'][0]['display_affiliation']='Undergraduate Student, Obsolete University, Norway'
        self.put(receipt['artifacts']['author_metadata'],author);self.rewrite_receipt(receipt)
        with self.assertRaises(ValueError):r.report_files(self.root,self.freeze_sha)
        receipt=self.report_fixture();receipt['human_review_complete']=True;receipt['submission_ready']=True;self.rewrite_receipt(receipt)
        with self.assertRaises(ValueError):r.report_files(self.root,self.freeze_sha)

    def test_pdf_decimal_size_boundary(self):
        receipt=self.report_fixture();size=(self.root/receipt['artifacts']['pdf']).stat().st_size
        with patch.object(r,'PDF_BYTES_LIMIT',size),self.assertRaises(ValueError):r.report_files(self.root,self.freeze_sha)

    def test_no_fake_k_or_m_closure_required_and_three_inert_aliases(self):
        self.assertNotIn('results/frontier-v6k/continuation/summary.json',r.REQUIRED_EVIDENCE)
        self.assertNotIn('results/frontier-v6k/continuation/runtime-audit.json',r.REQUIRED_EVIDENCE)
        self.assertNotIn('results/frontier-v6m/continuation/summary.json',r.REQUIRED_EVIDENCE)
        self.assertNotIn('results/frontier-v6m/continuation/runtime-audit.json',r.REQUIRED_EVIDENCE)
        self.assertIn('results/frontier-v6m-recovery/k-prefix-proof.json',r.REQUIRED_EVIDENCE)
        self.assertIn('results/frontier-v6n-recovery/m-prefix-proof.json',r.REQUIRED_EVIDENCE)
        self.assertEqual(set(r.ALIASES),{f'results/frontier-v6{x}/budget/active.lock' for x in ('f','k','m')})

    def test_changed_archive_source_and_overwrite_reject(self):
        source=self.put('member.txt',b'invented bytes')
        manifest={'schema':r.SCHEMA,'status':r.STATUS,'files':[{'path':'member.txt',**self.binding('member.txt')}]}
        output=self.root/'new.zip';a.write_zip(output,manifest,{'member.txt':source})
        with self.assertRaises(ValueError):a.write_zip(output,manifest,{'member.txt':source})
        source.write_bytes(b'changed')
        with self.assertRaises(ValueError):a.write_zip(self.root/'changed.zip',manifest,{'member.txt':source})

    def test_complete_release_never_accepts_interrupted_branch(self):
        manifest={'schema':r.SCHEMA,'status':'interrupted_recovery_diagnostic','files':[]}
        with self.assertRaises(ValueError):a.write_zip(self.root/'bad.zip',manifest,{})


if __name__=='__main__':unittest.main()

