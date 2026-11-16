"""Invented 300-row k-only fixtures. Never reads the active empirical study."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from retrace.refuter_product_v6k import KRefuterCatalog
from retrace.refuter_catalog_v6l import build_catalog,encode
from scripts import export_frontier_v6k_refuters_product as ex
from scripts import reproduce_frontier_v6k_refuters_product as rep
from tests.test_refuter_catalog_v6l import fixture as shared_fixture
from tests.test_frontier_v6l_catalog import bind


def fixture():
    data=shared_fixture(True);merged=data[4];merged['segment_summaries']={p:{'fixture':True} for p in ('i','j','k')}
    # Source byte bindings are synthetic; there is no l execution segment.
    merged['source_bindings']={p.replace('frontier-v6l','frontier-v6k'):v for p,v in merged['source_bindings'].items()}
    for rows in merged['source_provenance'].values():
        for row in rows:row['segment']='k';row['source_path']=row['source_path'].replace('frontier-v6l','frontier-v6k')
    return data


def publish(root,data,diagnostic=False):
    value=ex.project(*data,diagnostic=diagnostic)
    auth={'scientific_execution':'v6k','scientific_segments':['i','j','k'],'source_freeze_sha256':ex.FREEZE_SHA,
        'authenticated_input_bindings':{},'authenticated_source_bindings':{},'exporter_source_bindings':{},
        'frozen_aliases':{},'diagnostic':diagnostic,'study_status':ex.branch(diagnostic)[1],
        'replay_arguments':{'freeze':ex.FREEZE_SHA,'i':'a'*64,'j':'b'*64,'k':'c'*64,'snapshot':ex.SNAPSHOT,'snapshot_sha':'d'*64}}
    value['authentication']=auth
    with patch.object(ex,'verify_plan'):manifest=ex.write_catalog(root,value,diagnostic=diagnostic)
    return value,manifest,sha256((root/ex.branch(diagnostic)[0]/'manifest.json').read_bytes()).hexdigest()


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_exact_shared_projection_all300_and_no_gold_or_fourth_segment(self):
        data=fixture();before=deepcopy(data);shared=build_catalog(*data);value=ex.project(*data)
        self.assertEqual(data,before);self.assertEqual(len(value['entries']),300)
        for old,new in zip(shared['index']['entries'],value['index']['entries']):
            self.assertEqual(shared['entries'][old['entry_path']],value['entries'][new['entry_path']])
        text=json.dumps(value)
        for label in ('HIDDEN_GOLD','HIDDEN_SEED','HIDDEN_FAMILY','source_exact_family','"correct":','"segment": "l"'):
            self.assertNotIn(label,text)
        self.assertEqual(value['bundles'],{});self.assertIn('three segments i/j/k',value['index']['scope'])

    def test_rejects_fourth_segment_and_forged_source_pointer(self):
        for edit in ('summary','pointer'):
            data=fixture()
            if edit=='summary':data[4]['segment_summaries']['l']={}
            else:data[4]['source_provenance']['requests'][0]['segment']='l'
            with self.subTest(edit=edit),self.assertRaises(ValueError):ex.project(*data)

    def test_explicit_complete_and_diagnostic_reader_branches(self):
        for diagnostic in (False,True):
            value,m,pin=publish(self.root,fixture(),diagnostic)
            reader=KRefuterCatalog(self.root,expected_manifest_sha256=pin,diagnostic=diagnostic)
            index=reader.index();self.assertEqual(len(index['entries']),300)
            self.assertEqual(index['scientific_segments'],['i','j','k'])
            self.assertEqual(index['schedule_complete'],not diagnostic)
            row=index['entries'][0];self.assertEqual(json.loads(reader.entry(row['key'])),value['entries'][row['entry_path']])
            with self.assertRaises(ValueError):reader.entry(row['key'],bundle=True)

    def test_reader_rejects_rehashed_false_scientific_provenance(self):
        _,m,_=publish(self.root,fixture());m['scientific_segments'].append('l')
        p=self.root/ex.branch(False)[0]/'manifest.json';p.write_bytes(encode(m))
        with self.assertRaisesRegex(ValueError,'three-segment'):KRefuterCatalog(self.root).index()

    def test_unissued_and_failed_first_attempt_never_become_new_calls_or_replacements(self):
        data=fixture();response=data[4]['responses'][0]
        response.update(error='http_503',response_status=None,model_outcome='provider_error',terminal_valid=False,output_text='')
        data[4]['outcomes'][0]=deepcopy(response);data[3][0].update(provider_completed=False,eligible_completed=False,schema_valid=False,refuter_gate=None)
        bind(data[4]);data[4]['source_bindings']={p.replace('frontier-v6l','frontier-v6k'):v for p,v in data[4]['source_bindings'].items()}
        for rows in data[4]['source_provenance'].values():
            for row in rows:row['segment']='k';row['source_path']=row['source_path'].replace('frontier-v6l','frontier-v6k')
        value=ex.project(*data,diagnostic=True);first=value['entries'][value['index']['entries'][0]['entry_path']]
        self.assertEqual(first['metadata']['status'],'provider_failure');self.assertIsNone(first['inspection'])
        self.assertEqual(len(value['entries']),300)

    def test_export_missing_or_active_study_fails_before_compute(self):
        args=(self.root,ex.FREEZE_SHA,'a'*64,'b'*64,'c'*64,ex.SNAPSHOT,'d'*64)
        for diagnostic in (False,True):
            with patch.object(ex.full,'compute') as complete,patch.object(ex.partial,'compute') as partial:
                with self.assertRaisesRegex(ValueError,'Saved closed'):ex.authenticated(*args,diagnostic=diagnostic)
                complete.assert_not_called();partial.assert_not_called()
        lock=self.root/ex.LOCK;lock.parent.mkdir(parents=True);lock.write_text('fixture')
        with patch.object(ex.full,'compute') as compute:
            with self.assertRaisesRegex(ValueError,'Live k'):ex.authenticated(*args)
            compute.assert_not_called()

    def test_wrong_freeze_or_uncanonical_snapshot_fails_before_replay(self):
        for freeze,snapshot in (('f'*64,ex.SNAPSHOT),(ex.FREEZE_SHA,'invented.jsonl')):
            with self.assertRaisesRegex(ValueError,'Exact k'):ex.authenticated(self.root,freeze,'a','b','c',snapshot,'d')

    def test_authentication_uses_actual_k_audit_sse_inventory_in_both_branches(self):
        for diagnostic in (False,True):
            prefix=ex.partial.OUTPUT if diagnostic else ex.full.OUTPUT
            def put(name,value):
                p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(encode(value));return ex.full.binding(p)
            put(prefix+('/partial-manifest.json' if diagnostic else '/composite-manifest.json'),{})
            raw=put('streams/invented.sse',{'fixture':True});snapshot=put(ex.SNAPSHOT,{'closed':'fixture'})
            runtime={'passed':True,'final_closed':True,'schedule_status':'stopped' if diagnostic else 'completed',
                'input_bindings':{'streams/invented.sse':raw,ex.full.LEDGER:snapshot}}
            audit=put(ex.full.AUDITS['k'],runtime)
            evidence={'source_files':{ex.full.AUDITS['k']:audit},'frozen_aliases':{}}
            if diagnostic:evidence['runtime_input_bindings']=runtime['input_bindings']
            result={'summary':{'status':ex.branch(diagnostic)[1],'file_evidence':evidence}}
            put(prefix+'/score.json',result['summary'])
            for name in ('corpus','study','sessions'):put(ex.full.INPUTS[name],{})
            computer=ex.partial if diagnostic else ex.full
            with patch.object(computer,'compute',return_value=(result,{})) as compute,patch.object(ex,'verify_partial',return_value={}),patch.object(ex,'verify_complete',return_value={}):
                _,_,sources,_=ex.authenticated(self.root,ex.FREEZE_SHA,'a'*64,'b'*64,audit['sha256'],ex.SNAPSHOT,snapshot['sha256'],diagnostic=diagnostic)
                self.assertEqual(sources['streams/invented.sse'],raw)
                self.assertEqual(sources[ex.SNAPSHOT],snapshot);self.assertNotIn(ex.full.LEDGER,sources)
                self.assertEqual(compute.call_count,1)
                with self.assertRaisesRegex(ValueError,'audit binding'):
                    ex.authenticated(self.root,ex.FREEZE_SHA,'a'*64,'b'*64,'f'*64,ex.SNAPSHOT,snapshot['sha256'],diagnostic=diagnostic)

    def test_publication_rechecks_raw_sse_and_code_without_mutating_frozen_modules(self):
        path=self.root/'raw.sse';path.write_bytes(b'original');bound=ex.full.binding(path)
        auth={'scientific_execution':'v6k','scientific_segments':['i','j','k'],'source_freeze_sha256':ex.FREEZE_SHA,
            'diagnostic':False,'study_status':ex.branch(False)[1],'frozen_aliases':{},
            'exporter_source_bindings':dict.fromkeys(ex.SOURCES,{}),'authenticated_input_bindings':{},'authenticated_source_bindings':{'raw.sse':bound}}
        path.write_bytes(b'changed')
        with patch.object(ex.full,'verify_inventory'):
            with self.assertRaisesRegex(ValueError,'source changed'):ex.verify_plan(self.root,auth)

    def test_http_routes_reuse_shared_view_with_k_readers_only(self):
        from retrace.server_v6k_inspector import Handler
        value,_,pin=publish(self.root,fixture());h=object.__new__(Handler)
        h.server=SimpleNamespace(refuter_catalog=KRefuterCatalog(self.root,expected_manifest_sha256=pin),diagnostic=False)
        h.local_host=lambda:True;h.send=lambda *args:args;h.path='/api/v6l/refuters'
        status,index=h.do_GET();self.assertEqual(status,200);self.assertEqual(index['scientific_execution'],'v6k')
        h.path='/api/v6l/refuters/'+index['entries'][0]['key'];status,raw=h.do_GET();self.assertEqual(status,200)
        self.assertEqual(json.loads(raw),value['entries'][index['entries'][0]['entry_path']])

    def test_reproducer_exact_bytes_rejects_semantically_equal_changed_catalog(self):
        data=fixture();value,m,pin=publish(self.root,data)
        result={'audits':data[3],'merged_evidence':data[4]};sources={};artifacts={}
        shaped={'corpus':data[0],'study':data[1],'sessions':data[2]}
        with patch.object(ex,'authenticated',return_value=(result,artifacts,sources,shaped)),patch.object(ex,'verify_plan'),patch.object(ex,'SOURCES',()):
            out=rep.verify(self.root,pin);self.assertTrue(out['passed']);self.assertEqual(out['payload_members'],301)
            row=value['index']['entries'][0];p=self.root/row['entry_path'];p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'Byte-exact'):rep.verify(self.root,pin)


if __name__=='__main__':unittest.main()
