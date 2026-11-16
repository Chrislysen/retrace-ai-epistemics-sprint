"""Prepared invented product fixtures. No inference/API or empirical journals."""
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import frontier_v6m_products as p
from retrace import evidence_catalog_v6m as evidence
from retrace import refuter_catalog_v6m as refuters
from retrace.server_v6m import EvidenceCatalog
from retrace.refuter_reader_v6m import RefuterCatalog
from tests.test_frontier_v6l_catalog import fixture as ir_fixture,entry
from tests.test_refuter_catalog_v6l import fixture as refuter_fixture

ROOT=Path(__file__).resolve().parents[1]


def data(kind,full=False):
    value=ir_fixture(full=full) if kind=='catalog' else refuter_fixture(full=full)
    merged=value[4]
    merged['source_bindings']={name.replace('v6l','v6m'):b for name,b in merged['source_bindings'].items()}
    for pointers in merged['source_provenance'].values():
        for pointer in pointers:
            pointer['source_path']=pointer['source_path'].replace('v6l','v6m');pointer['segment']='m'
    return value


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def publish(self,kind,diagnostic=False):
        value=p.project(kind,*data(kind,True),diagnostic=diagnostic)
        value['authentication']={'source_freeze_sha256':'a'*64,'authenticated_input_bindings':{},
            'authenticated_source_bindings':{},'exporter_source_bindings':{},'frozen_aliases':{},
            'study_status':p.branch(kind,diagnostic)[1],'diagnostic':diagnostic}
        with patch.object(p,'verify_plan'):manifest=p.write_catalog(kind,self.root,value,diagnostic=diagnostic)
        return value,manifest

    def test_ir_projection_functions_unchanged_except_provenance_segment(self):
        def functions(path):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse((ROOT/path).read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        before=functions('retrace/evidence_catalog_v6l.py');after=functions('retrace/evidence_catalog_v6m.py')
        self.assertEqual(set(before),set(after))
        self.assertEqual({k:v for k,v in before.items() if k!='_pointer'},{k:v for k,v in after.items() if k!='_pointer'})
        before=functions('retrace/refuter_catalog_v6l.py');after=functions('retrace/refuter_catalog_v6m.py')
        self.assertEqual(before,after)

    def test_all300_both_products_and_no_gold_leak(self):
        for kind in p.KINDS:
            original=data(kind,True);before=deepcopy(original);value=p.project(kind,*original)
            self.assertEqual(original,before);self.assertEqual(len(value['entries']),300)
            text=json.dumps(value)
            for forbidden in ('HIDDEN_GOLD','HIDDEN_FAMILY','HIDDEN_SEED','source_exact_family','correct_decisions'):
                self.assertNotIn(forbidden,text)
            self.assertTrue(value['index']['scope'].startswith('HOST-RECOVERED STUDY.'))
            if kind=='refuter-catalog':self.assertEqual(value['bundles'],{})

    def test_m_pointer_admitted_but_unexecuted_l_rejected(self):
        for kind,builder in (('catalog',evidence),('refuter-catalog',refuters)):
            value=data(kind);out=builder.build_catalog(*value,require_full_design=False)
            self.assertEqual(entry(out)['provenance']['selected_first_attempt']['request']['segment'],'m')
            value[4]['source_provenance']['requests'][0]['segment']='l'
            with self.assertRaises(ValueError):builder.build_catalog(*value,require_full_design=False)

    def test_recovered_manifest_never_claims_original_inference(self):
        for kind,reader_type in (('catalog',EvidenceCatalog),('refuter-catalog',RefuterCatalog)):
            value,manifest=self.publish(kind)
            self.assertFalse(manifest['inference_available']);self.assertTrue(manifest['amended_sensitivity_available'])
            reader=reader_type(self.root,expected_freeze_sha256='a'*64)
            index=reader.index();self.assertTrue(index['schedule_complete']);self.assertFalse(index['inference_available'])
            self.assertEqual(index['study_status'],'complete_host_recovered_schedule')
            raw=reader.entry(index['entries'][0]['key']);self.assertTrue(raw)

    def test_stopped_and_recovered_are_separate_no_fallback(self):
        value,manifest=self.publish('refuter-catalog',True)
        reader=RefuterCatalog(self.root,expected_freeze_sha256='a'*64,diagnostic=True)
        index=reader.index();self.assertFalse(index['schedule_complete']);self.assertFalse(index['amended_sensitivity_available'])
        self.assertTrue(index['scope'].startswith('INTERRUPTED STUDY.'))
        self.assertFalse(RefuterCatalog(self.root,expected_freeze_sha256='a'*64).index()['available'])

    def test_tamper_after_pin_is_rejected(self):
        _,manifest=self.publish('refuter-catalog');reader=RefuterCatalog(self.root,expected_freeze_sha256='a'*64)
        row=reader.index()['entries'][0];path=self.root/row['entry_path'];path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'hash changed'):reader.entry(row['key'])

    def test_forged_inference_flag_rejected_even_when_manifest_rehashed(self):
        _,manifest=self.publish('refuter-catalog');manifest['inference_available']=True
        name=p.branch('refuter-catalog',False)[0]+'/manifest.json';(self.root/name).write_bytes(evidence.encode(manifest))
        with self.assertRaisesRegex(ValueError,'branch/freeze'):RefuterCatalog(self.root,expected_freeze_sha256='a'*64).index()

    def test_controlled_seed_cannot_be_promoted(self):
        self.publish('refuter-catalog');reader=RefuterCatalog(self.root,expected_freeze_sha256='a'*64)
        key=reader.index()['entries'][0]['key']
        with self.assertRaisesRegex(ValueError,'silently loaded'):reader.entry(key,bundle=True)

    def test_active_worker_blocks_before_authentication(self):
        lock=self.root/p.score.LOCK;lock.parent.mkdir(parents=True);lock.write_bytes(b'')
        with patch.object(p.score,'compute') as compute:
            with self.assertRaisesRegex(ValueError,'Active'):p.authenticated(self.root,*['a'*64]*5)
            compute.assert_not_called()

    def test_no_saved_final_composite_blocks_before_authentication(self):
        with patch.object(p.score,'compute') as compute:
            with self.assertRaisesRegex(ValueError,'Saved final'):p.authenticated(self.root,*['a'*64]*5)
            compute.assert_not_called()


if __name__=='__main__':unittest.main()
