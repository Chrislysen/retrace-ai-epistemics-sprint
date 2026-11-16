"""All300 invented first attempts; no empirical outputs, ledgers, or network."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import reproduce_frontier_v6l_refuters as r
from scripts import export_frontier_v6l_refuters as exporter
from retrace.refuter_catalog_v6l import encode
from tests.test_refuter_catalog_v6l import fixture, bind


class RefuterReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.freeze='a'*64

    def put(self,name,value):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else encode(value))

    def publish(self,diagnostic=False,*,censored=False):
        data=fixture(True)
        if censored:
            data[4]['requests'].pop(0);data[4]['responses'].pop(0)
            data[4]['outcomes'][0].update(issued=False,attempt_id=None,model_outcome='not_issued_global_stop',output_text='')
            data[3][0].update(record_observed=False,provider_completed=False,eligible_completed=False,schema_valid=False,refuter_gate=None)
            bind(data[4])
        for role,value in zip(('corpus','study','sessions'),data[:3]):self.put(r.DATA[role],value)
        # Only file bindings are mocked: the projection, reader and replay run normally.
        for name in exporter.SOURCES:self.put(name,b'# invented bound exporter dependency\n')
        stream='results/frontier-v6l/continuation/streams/invented.sse'
        self.put(stream,b'data: invented transport binding\n\n');self.put(r.SNAPSHOT,b'{"invented_ledger":true}\n')
        self.put(r.LOCK_ALIAS,b'inert historical fixture\n')
        source_files={name:r.binding(self.root,name) for name in r.DATA.values()}
        runtime={stream:r.binding(self.root,stream),r.LEDGER:r.binding(self.root,r.SNAPSHOT),r.LOCK:r.binding(self.root,r.LOCK_ALIAS)}
        sources={**source_files,**{r.SNAPSHOT if n==r.LEDGER else n:v for n,v in runtime.items()}}
        prefix='results/frontier-v6l/'+('partial-diagnostic' if diagnostic else 'composite')
        names=('score.json','score-audits.json','source-provenance.json','requests.jsonl','responses.jsonl','slot-outcomes.jsonl',
               'interrupted-closure.json' if diagnostic else 'derived-closure.json',
               'partial-manifest.json' if diagnostic else 'composite-manifest.json')
        for name in names:self.put(prefix+'/'+name,{'fixture':name})
        self.put(prefix+'/score.json',{'file_evidence':{'source_files':source_files,'runtime_input_bindings':runtime}})
        value=exporter.project(*data,diagnostic=diagnostic)
        value['authentication']={'source_freeze_sha256':self.freeze,
            'authenticated_input_bindings':{prefix+'/'+name:r.binding(self.root,prefix+'/'+name) for name in names},
            'authenticated_source_bindings':sources,'exporter_source_bindings':{name:r.binding(self.root,name) for name in exporter.SOURCES},
            'frozen_aliases':{r.LOCK:r.LOCK_ALIAS},'study_status':exporter.branch(diagnostic)[1],'diagnostic':diagnostic}
        with patch.object(exporter,'verify_plan'):
            manifest=exporter.write_catalog(self.root,value,diagnostic=diagnostic)
        result={'audits':data[3],'merged_evidence':data[4]}
        return data,result,value,manifest

    def verify(self,diagnostic=False,result=None):
        return r.refuter_catalog_files(self.root,{r.LOCK:r.LOCK_ALIAS},freeze_sha256=self.freeze,result=result,diagnostic=diagnostic)

    def test_both_branches_rebuild_all300_without_graph_bundles(self):
        for diagnostic in (False,True):
            with self.subTest(diagnostic=diagnostic):
                _,result,value,_=self.publish(diagnostic)
                names,info=self.verify(diagnostic,result)
                self.assertEqual(len(names),302);self.assertEqual(info['catalog_payload_members'],301)
                self.assertEqual(info['scheduled_slots'],300);self.assertTrue(info['recomputed_from_authenticated_first_attempts'])
                self.assertEqual(value['bundles'],{})
                self.assertEqual(info['study_status'],exporter.branch(diagnostic)[1])

    def test_missing_catalog_cannot_be_replaced_by_other_product(self):
        self.put('results/frontier-v6l/catalog/manifest.json',{'fixture':'IR alone'})
        with self.assertRaises(ValueError):self.verify()

    def test_other_branch_and_freeze_are_not_fallbacks(self):
        self.publish()
        with self.assertRaises(ValueError):self.verify(True)
        with self.assertRaisesRegex(ValueError,'freeze'):
            r.refuter_catalog_files(self.root,{r.LOCK:r.LOCK_ALIAS},freeze_sha256='b'*64)

    def test_all8_composite_bindings_and_raw_sse_are_required(self):
        self.publish();self.verify()
        self.put('results/frontier-v6l/continuation/streams/invented.sse',b'changed')
        with self.assertRaisesRegex(ValueError,'raw/source evidence'):self.verify()

    def test_changed_exporter_or_composite_rejects(self):
        _,_,_,manifest=self.publish()
        first=exporter.SOURCES[0];original=(self.root/first).read_bytes();self.put(first,b'changed')
        with self.assertRaisesRegex(ValueError,'exporter code'):self.verify()
        self.put(first,original);self.put('results/frontier-v6l/composite/score-audits.json',{'changed':True})
        with self.assertRaisesRegex(ValueError,'different authenticated composite'):self.verify()

    def test_rehashed_changed_raw_output_fails_authenticated_rebuild(self):
        _,result,value,manifest=self.publish();directory=exporter.branch(False)[0]
        row=value['index']['entries'][0];name=row['entry_path'];bad=deepcopy(value['entries'][name])
        # Whitespace is semantically innocuous, but the original provider text is immutable.
        bad['raw_output_text']+=' ';self.put(name,bad)
        row['entry_sha256']=r.binding(self.root,name)['sha256'];manifest['files'][name]=r.binding(self.root,name)
        self.put(directory+'/index.json',value['index']);manifest['files'][directory+'/index.json']=r.binding(self.root,directory+'/index.json')
        self.put(directory+'/manifest.json',manifest)
        self.verify()  # Hash-only mode makes no semantic/raw-byte replay claim.
        with self.assertRaisesRegex(ValueError,'differs from original first-attempt'):self.verify(result=result)

    def test_removed_first_attempt_grade_cannot_shrink_denominator(self):
        _,result,_,_=self.publish();result['audits'].pop()
        with self.assertRaises(ValueError):self.verify(result=result)

    def test_partial_censored_entry_stays_unavailable_among_all300(self):
        _,result,value,_=self.publish(True,censored=True)
        names,info=self.verify(True,result);first=value['entries'][value['index']['entries'][0]['entry_path']]
        self.assertEqual(first['metadata']['status'],'not_issued');self.assertIsNone(first['inspection'])
        self.assertTrue(value['index']['scope'].startswith('INTERRUPTED STUDY.'))
        self.assertEqual((len(names),info['scheduled_slots']),(302,300))

    def test_complete_and_partial_release_require_separate_refuter_manifests(self):
        from scripts import reproduce_frontier_v6l_release as complete
        from scripts import reproduce_frontier_v6l_partial_release as partial
        self.assertIn('results/frontier-v6l/refuter-catalog/manifest.json',complete.REQUIRED_PRODUCT)
        self.assertIn('results/frontier-v6l/partial-refuter-catalog/manifest.json',partial.REQUIRED_PRODUCT)
        self.assertNotEqual(complete.REFUTER_MANIFEST,partial.REFUTER_MANIFEST)


if __name__=='__main__':unittest.main()
