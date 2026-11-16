"""Synthetic closed exports in temp directories; no real outputs or provider."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from retrace.refuter_catalog_v6l import encode
from retrace.refuter_reader_v6l import RefuterCatalog
from scripts import export_frontier_v6l_refuters as exporter
from tests.test_refuter_catalog_v6l import fixture


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.freeze='a'*64

    def publish(self,diagnostic=False):
        data=fixture(True);value=exporter.project(*data,diagnostic=diagnostic)
        value['authentication']={'source_freeze_sha256':self.freeze,'authenticated_input_bindings':{},
            'authenticated_source_bindings':{},'exporter_source_bindings':{},'frozen_aliases':{},
            'study_status':exporter.branch(diagnostic)[1],'diagnostic':diagnostic}
        with patch.object(exporter,'verify_plan'):
            manifest=exporter.write_catalog(self.root,value,diagnostic=diagnostic)
        return value,manifest

    def reader(self,diagnostic=False):return RefuterCatalog(self.root,expected_freeze_sha256=self.freeze,diagnostic=diagnostic)

    def test_full_catalog_pins_and_replays_every_selected_raw(self):
        value,manifest=self.publish();reader=self.reader();index=reader.index()
        self.assertEqual(len(index['entries']),300);key=index['entries'][0]['key']
        raw=reader.entry(key);saved=json.loads(raw)
        self.assertEqual(saved,value['entries'][index['entries'][0]['entry_path']])
        self.assertEqual(saved['inspection']['preview']['comparison'],'G versus G union P')
        with self.assertRaises(ValueError):reader.entry(key,bundle=True)
        with patch.object(exporter,'verify_plan'):
            with self.assertRaisesRegex(ValueError,'Exclusive'):exporter.write_catalog(self.root,value)

    def test_changed_member_and_manifest_reject_without_repaired_response(self):
        value,manifest=self.publish();reader=self.reader();index=reader.index();row=index['entries'][0]
        path=self.root/row['entry_path'];path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'hash changed'):reader.entry(row['key'])
        manifestpath=self.root/exporter.DIRECTORY/'manifest.json';manifestpath.write_bytes(manifestpath.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'manifest changed'):reader.index()

    def test_rehashed_fake_inspection_still_fails_raw_replay(self):
        value,manifest=self.publish();row=value['index']['entries'][0];name=row['entry_path']
        bad=deepcopy(value['entries'][name]);bad['inspection']['semantic_entailment_verified']=True
        raw=encode(bad);(self.root/name).write_bytes(raw);digest=sha256(raw).hexdigest()
        row['entry_sha256']=digest;manifest['files'][name]={'sha256':digest,'bytes':len(raw)}
        indexraw=encode(value['index']);(self.root/manifest['index_path']).write_bytes(indexraw)
        manifest['files'][manifest['index_path']]={'sha256':sha256(indexraw).hexdigest(),'bytes':len(indexraw)}
        (self.root/exporter.DIRECTORY/'manifest.json').write_bytes(encode(manifest))
        with self.assertRaisesRegex(ValueError,'raw replay'):self.reader().entry(row['key'])

    def test_unknown_freeze_and_incompatible_branch_are_not_fallbacks(self):
        self.publish()
        with self.assertRaisesRegex(ValueError,'Explicit'):RefuterCatalog(self.root).index()
        with self.assertRaisesRegex(ValueError,'freeze'):RefuterCatalog(self.root,expected_freeze_sha256='b'*64).index()
        self.assertFalse(self.reader(True).index()['available'])

    def test_explicit_diagnostic_branch_keeps_scope_and_no_complete_claim(self):
        value,manifest=self.publish(True);index=self.reader(True).index()
        self.assertFalse(index['schedule_complete']);self.assertFalse(index['inference_available'])
        self.assertTrue(index['scope'].startswith('INTERRUPTED STUDY.'))
        row=index['entries'][0];self.reader(True).entry(row['key'])
        self.assertFalse(self.reader().index()['available'])

    def test_source_publication_gate_rechecks_every_bound_code_and_raw_file(self):
        path=self.root/'bound.txt';path.write_text('original',encoding='utf-8')
        binding=exporter.binding(path)
        auth={'diagnostic':False,'study_status':'complete_amended_primary','frozen_aliases':{},'source_freeze_sha256':self.freeze,
            'exporter_source_bindings':{name:{} for name in exporter.SOURCES},'authenticated_input_bindings':{'bound.txt':binding},
            'authenticated_source_bindings':{}}
        # The bound input is checked before the invented code bindings.
        path.write_text('changed',encoding='utf-8')
        with patch.object(exporter,'verify_inventory'):
            with self.assertRaisesRegex(ValueError,'changed before'):exporter.verify_plan(self.root,auth)

    def test_http_reader_returns_original_entry_and_refuses_corruption(self):
        from retrace.server_v6l import HandlerV6l
        value,_=self.publish();row=value['index']['entries'][0]
        handler=object.__new__(HandlerV6l);handler.server=SimpleNamespace(refuter_catalog=self.reader())
        handler.local_host=lambda:True;handler.send=lambda *args:args
        handler.path='/api/v6l/refuters';status,index=handler.do_GET()
        self.assertEqual(status,200);self.assertEqual(len(index['entries']),300)
        handler.path='/api/v6l/refuters/'+row['key'];status,raw=handler.do_GET()
        self.assertEqual(status,200);self.assertEqual(json.loads(raw),value['entries'][row['entry_path']])
        (self.root/row['entry_path']).write_bytes(b'{}')
        status,error=handler.do_GET();self.assertEqual(status,409);self.assertNotIn('inspection',error)

    def test_export_requires_real_closed_saved_composite_before_replay(self):
        args=(self.root,self.freeze,*(['b'*64]*4),'data/final-snapshot.jsonl','c'*64)
        for diagnostic in (False,True):
            with self.subTest(diagnostic=diagnostic),patch.object(exporter,'compute') as compute,patch.object(exporter,'authenticated_inputs') as replay:
                with self.assertRaisesRegex(ValueError,'Saved authenticated closed'):exporter.run(*args,diagnostic=diagnostic)
                compute.assert_not_called();replay.assert_not_called()


if __name__=='__main__':unittest.main()
