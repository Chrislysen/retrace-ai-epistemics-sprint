"""Offline catalog integrity and loopback route tests using invented fixtures."""
from copy import deepcopy
from hashlib import sha256
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest

from retrace import server_v6l as server
FREEZE_SHA = "a"*64
from retrace.workbench_v6h import demo_brief


def encode(value): return (json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n').encode()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.files = {}; self.rows = []

    def put(self,name,value):
        raw = value if isinstance(value,bytes) else encode(value)
        p=self.root/name; p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        self.files[name]={'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}
        return raw

    def fixture(self):
        # All data below are invented for serving tests, never empirical files.
        demo=demo_brief();docs=[{'id':d['id'],'text':d['text']} for d in demo['source_documents']];registry=demo['registry']
        for case in range(60):
            for model in server.PRIMARY_MODELS:
                sid=f'fixture::{case}::{model}';key=sha256(sid.encode()).hexdigest()
                admitted=case==0;status='admitted' if admitted else 'provider_failure'
                brief={'id':sid,'title':'Invented server fixture','source_documents':deepcopy(docs),'registry':deepcopy(registry),'source_ir':deepcopy(demo['source_ir'])} if admitted else None
                output=json.dumps(demo['source_ir']) if admitted else ''
                meta={'key':key,'slot_id':sid,'case_id':f'fixture-{case:02d}','model':model,'status':status,
                    'provider_completed':admitted,'strict_bare_json':admitted,'candidate_count':8 if admitted else 0,
                    'registry_coverage_gaps':[] if admitted else None,'condition':'strict_source_ir','phase':'extract','selection_view':'first_attempt','loadable':admitted,
                    'schema_valid':admitted,'compiler_admitted':admitted,'attempt_id':sid+':first','attempts_observed':1,
                    'model_outcome':'completed' if admitted else 'operational_failure','failure_scope':None if admitted else 'slot',
                    'error_code':None if admitted else 'http_504','requested_model':model,'returned_model':model if admitted else None,
                    'response_status':'completed' if admitted else None,'warning_label':None,'source_entailment_verified':False,'source_completeness':'unknown'}
                provenance={'selected_first_attempt':{'request':None,'response':None,'final_outcome':None},
                    'public_source_sha256':server.object_hash({'source_documents':docs,'registry':registry}),
                    'scheduled_input_sha256':'0'*64,'raw_output_text_sha256':sha256(output.encode()).hexdigest(),
                    'partial_output_text_sha256':sha256(b'').hexdigest(),'raw_provider_response_sha256':None,
                    'original_ir_sha256':server.object_hash(demo['source_ir']) if admitted else None,'scope':'INVENTED TEMP TEST FIXTURE ONLY'}
                entry={'schema':'retrace.evidence-entry.v6k.v1','metadata':meta,'source_documents':deepcopy(docs),'registry':deepcopy(registry),'raw_output_text':output, 'partial_output_text':'','brief':brief,'provenance':provenance,'scope':'INVENTED HTTP TEST FIXTURE ONLY'}
                ep=server.BASE+'/entries/'+key+'.json';raw=self.put(ep,entry)
                bp=server.BASE+'/bundles/'+key+'.json' if admitted else None
                if bp:self.put(bp,brief)
                self.rows.append({'key':key,'slot_id':sid,'case_id':f'fixture-{case:02d}','model':model,'status':status,
                    'provider_completed':admitted,'strict_bare_json':admitted,'candidate_count':8 if admitted else 0,'registry_coverage_gaps':[] if admitted else None,
                    'entry_path':ep,'entry_sha256':sha256(raw).hexdigest(),'bundle_path':bp,'bundle_sha256':self.files[bp]['sha256'] if bp else None})
        index={'schema':'retrace.evidence-index.v6k.v1','scheduled_slots':300,'selection_view':'first_attempt',
            'test_fixture':False,'case_order':[f'fixture-{i:02d}' for i in range(60)],'model_order':list(server.PRIMARY_MODELS),
            'counts':{status:sum(r['status']==status for r in self.rows) for status in server.STATUSES},'entries':self.rows,'scope':'INVENTED TEMP TEST FIXTURE ONLY'}
        self.put(server.BASE+'/index.json',index)
        self.manifest={'schema':'retrace.evidence-catalog.v6l.v1','schedule_complete':True,'inference_available':True,'status':'complete_amended_primary','scheduled_slots':300,'selection_view':'first_attempt','source_freeze_sha256':FREEZE_SHA,'index_path':server.BASE+'/index.json','files':deepcopy(self.files)}
        self.put(server.BASE+'/manifest.json',self.manifest)
        return server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA)

    def rewrite_index(self):
        path=server.BASE+'/index.json';value=json.loads((self.root/path).read_bytes());value['entries']=self.rows
        self.put(path,value);self.manifest['files'][path]=self.files[path];self.put(server.BASE+'/manifest.json',self.manifest)

    def rejected_fixture(self):
        self.fixture();row=self.rows[0];old_bundle=row['bundle_path'];path=row['entry_path']
        value=json.loads((self.root/path).read_bytes())
        value['raw_output_text']='```json\n'+value['raw_output_text']+'```'
        value['brief']=None;value['provenance']['original_ir_sha256']=None
        value['provenance']['raw_output_text_sha256']=sha256(value['raw_output_text'].encode()).hexdigest()
        changes={'status':'invalid_ir','strict_bare_json':False,'candidate_count':0,'registry_coverage_gaps':None}
        value['metadata'].update(changes,schema_valid=False,compiler_admitted=False,loadable=False,error_code='invalid_ValueError')
        row.update(changes,bundle_path=None,bundle_sha256=None)
        raw=self.put(path,value);row['entry_sha256']=sha256(raw).hexdigest()
        self.manifest['files'][path]=self.files[path];self.manifest['files'].pop(old_bundle)
        index=json.loads((self.root/server.BASE/'index.json').read_bytes());index['entries']=self.rows
        index['counts']={status:sum(r['status']==status for r in self.rows) for status in server.STATUSES}
        self.put(server.BASE+'/index.json',index);self.manifest['files'][server.BASE+'/index.json']=self.files[server.BASE+'/index.json']
        self.put(server.BASE+'/manifest.json',self.manifest)
        return server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA),value

    def test_rejection_diagnosis_binds_original_bytes_without_admission(self):
        reader,original=self.rejected_fixture()
        http=ThreadingHTTPServer(('127.0.0.1',0),server.HandlerV6l);http.evidence_catalog=reader
        thread=Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            connection=HTTPConnection('127.0.0.1',http.server_port)
            connection.request('GET','/api/v6l/catalog/'+self.rows[0]['key']+'/diagnosis')
            response=connection.getresponse();value=json.loads(response.read());self.assertEqual(response.status,200)
            self.assertFalse(value['compile_admitted']);self.assertEqual(value['localization_status'],'localized')
            self.assertEqual(value['raw_text_sha256'],original['provenance']['raw_output_text_sha256'])
            self.assertEqual(value['source_packet_sha256'],original['provenance']['public_source_sha256'])
            self.assertEqual(value['slot_id'],self.rows[0]['slot_id']);self.assertNotIn('graph',value)
            self.assertEqual(json.loads(reader.entry(self.rows[0]['key'])),original)
            with self.assertRaises(FileNotFoundError):reader.entry(self.rows[0]['key'],bundle=True)
            for row in (self.rows[1],self.rows[-1]):
                connection.request('GET','/api/v6l/catalog/'+row['key']+'/diagnosis')
                response=connection.getresponse();response.read();self.assertEqual(response.status,409)
            connection.close()
        finally:http.shutdown();http.server_close();thread.join()

    def test_missing_catalog_is_explicit_and_never_fabricates_entries(self):
        reader=server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA)
        self.assertFalse(reader.index()['available']);self.assertEqual(reader.index()['entries'],[])
        with self.assertRaises(FileNotFoundError):reader.entry('0'*64)
        with self.assertRaisesRegex(ValueError,'Pinned catalog'):
            server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA,expected_manifest_sha256='0'*64).index()

    def test_every_model_case_and_failure_remains_and_bytes_are_exact(self):
        reader=self.fixture();index=reader.index()
        self.assertTrue(index['available']);self.assertEqual(len(index['entries']),300)
        self.assertEqual(sum(r['status']=='provider_failure' for r in index['entries']),295)
        for row in (self.rows[0],self.rows[-1]):
            self.assertEqual(reader.entry(row['key']),(self.root/row['entry_path']).read_bytes())
        self.assertEqual(reader.entry(self.rows[0]['key'],bundle=True),(self.root/self.rows[0]['bundle_path']).read_bytes())
        with self.assertRaises(FileNotFoundError):reader.entry(self.rows[-1]['key'],bundle=True)

    def test_manifest_is_pinned_and_changed_entry_bytes_fail_closed(self):
        reader=self.fixture();reader.index();name=self.rows[0]['entry_path'];self.put(name,b'{"tampered":true}\n')
        with self.assertRaisesRegex(ValueError,'hash changed'):reader.entry(self.rows[0]['key'])
        self.manifest['files'][name]=self.files[name];self.put(server.BASE+'/manifest.json',self.manifest)
        with self.assertRaisesRegex(ValueError,'manifest changed'):reader.index()

    def test_explicit_expected_manifest_hash_is_enforced(self):
        reader=self.fixture();expected=sha256((self.root/server.BASE/'manifest.json').read_bytes()).hexdigest()
        self.assertTrue(server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA,expected_manifest_sha256=expected).index()['available'])
        with self.assertRaisesRegex(ValueError,'manifest changed'):
            server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA,expected_manifest_sha256='0'*64).index()

    def test_omitted_failure_and_repeated_model_cannot_pass_complete_index(self):
        self.fixture();self.rows.pop();self.rewrite_index()
        with self.assertRaisesRegex(ValueError,'All300'):server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA).index()
        self.rows.append(deepcopy(self.rows[-1]));self.rewrite_index()
        with self.assertRaisesRegex(ValueError,'Unique slot'):server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA).index()

    def test_no_private_file_paths_or_query_injection(self):
        reader=self.fixture()
        for key in ('../manifest.json','%2e%2e%2fmanifest','a'*64+'/bundle','A'*64,'a'*63):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError,'Invalid catalog key'):reader.entry(key)
        for name in ('data/frontier-v6h-corpus.json',server.BASE+'/../secrets.txt',server.BASE+'\\entries\\x.json'):
            with self.assertRaises(ValueError):reader._path(name)

    def test_failed_row_cannot_be_promoted_to_bundle(self):
        self.fixture();self.rows[-1]['bundle_path']=self.rows[0]['bundle_path'];self.rows[-1]['bundle_sha256']=self.rows[0]['bundle_sha256'];self.rewrite_index()
        with self.assertRaisesRegex(ValueError,'Unavailable interpretation'):server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA).index()

    def test_duplicate_json_keys_and_nonfinite_values_rejected(self):
        for raw in (b'{"schema":"x","schema":"y"}',b'{"score":NaN}'):
            with self.assertRaises(ValueError):server.strict(raw)

    def test_extra_unlisted_catalog_members_cannot_be_served(self):
        self.fixture();extra=server.BASE+'/private.json';self.put(extra,{'not_public':True});self.manifest['files'][extra]=self.files[extra];self.put(server.BASE+'/manifest.json',self.manifest)
        with self.assertRaisesRegex(ValueError,'Undeclared'):server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA).index()

    def test_entry_cannot_claim_another_model_even_after_rehashing(self):
        self.fixture();row=self.rows[0];entry=json.loads((self.root/row['entry_path']).read_bytes())
        entry['metadata']['model']=server.PRIMARY_MODELS[1];self.put(row['entry_path'],entry)
        row['entry_sha256']=self.files[row['entry_path']]['sha256'];self.manifest['files'][row['entry_path']]=self.files[row['entry_path']]
        self.rewrite_index()
        with self.assertRaisesRegex(ValueError,'indexed observation'):server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA).entry(row['key'])

    def test_case_events_or_reference_answers_cannot_enter_workbench_bundle(self):
        self.fixture();row=self.rows[0];entry=json.loads((self.root/row['entry_path']).read_bytes())
        entry['brief']['events']={'hidden_reference_state':True};self.put(row['entry_path'],entry)
        row['entry_sha256']=self.files[row['entry_path']]['sha256'];self.manifest['files'][row['entry_path']]=self.files[row['entry_path']]
        self.rewrite_index()
        with self.assertRaisesRegex(ValueError,'only the matching public'):server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA).entry(row['key'])

    def test_nested_document_or_registry_annotations_are_not_served(self):
        self.fixture();row=self.rows[0];original=json.loads((self.root/row['entry_path']).read_bytes())
        for target in ('document','registry','metadata','provenance'):
            entry=deepcopy(original)
            if target=='document':
                entry['source_documents'][0]['oracle_answer']='hidden';entry['brief']['source_documents']=entry['source_documents']
            elif target=='registry':
                entry['registry']['gold']=True;entry['brief']['registry']=entry['registry']
            else:entry[target]['oracle_answer']='hidden'
            self.put(row['entry_path'],entry);row['entry_sha256']=self.files[row['entry_path']]['sha256']
            self.manifest['files'][row['entry_path']]=self.files[row['entry_path']];self.rewrite_index()
            with self.subTest(target=target):
                with self.assertRaises(ValueError):server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA).entry(row['key'])

    def test_nonobject_containers_raise_explicit_integrity_errors(self):
        self.fixture();self.put(server.BASE+'/manifest.json',[])
        with self.assertRaises(ValueError):server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA).index()

    def test_loaded_ir_cannot_be_repaired_independently_of_raw_output(self):
        self.fixture();row=self.rows[0];entry=json.loads((self.root/row['entry_path']).read_bytes())
        entry['brief']['source_ir']['propositions'][0]['body']['active']=False
        entry['provenance']['original_ir_sha256']=server.object_hash(entry['brief']['source_ir'])
        self.put(row['entry_path'],entry);row['entry_sha256']=self.files[row['entry_path']]['sha256']
        self.manifest['files'][row['entry_path']]=self.files[row['entry_path']];self.rewrite_index()
        with self.assertRaisesRegex(ValueError,'unrepaired model text'):server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA).entry(row['key'])

    def test_http_preserves_old_assets_and_enforces_local_host(self):
        reader=self.fixture()
        class Quiet(server.HandlerV6l):
            def log_message(self,*_):pass
        http=ThreadingHTTPServer(('127.0.0.1',0),Quiet);http.evidence_catalog=reader
        thread=Thread(target=http.serve_forever,daemon=True);thread.start()
        def request(path,host=None):
            conn=HTTPConnection('127.0.0.1',http.server_port,timeout=5)
            headers={'Host':host} if host else {}
            conn.request('GET',path,headers=headers);response=conn.getresponse();body=response.read();result=(response.status,dict(response.getheaders()),body);conn.close();return result
        try:
            status,headers,body=request('/app.js');self.assertEqual(status,200)
            self.assertEqual(body,(server.ROOT/'web/v6h/app.js').read_bytes())
            self.assertEqual(request('/style.css')[2],(server.ROOT/'web/v6h/style.css').read_bytes())
            self.assertIn(b'/evidence.js',request('/')[2]);self.assertNotIn(b'<script>not executable</script>',request('/')[2])
            status,headers,body=request('/api/v6l/catalog');self.assertEqual(status,200);self.assertEqual(len(json.loads(body)['entries']),300)
            self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
            self.assertEqual(request('/api/v6l/catalog',host='external.example')[0],403)
            self.assertEqual(request('/api/v6l/catalog/'+self.rows[-1]['key']+'/bundle')[0],404)
            self.assertEqual(request('/api/v6l/catalog/../../data')[0],404)
            self.assertEqual(request('/api/v6l/catalog/'+self.rows[0]['key'])[2],(self.root/self.rows[0]['entry_path']).read_bytes())
        finally:http.shutdown();http.server_close();thread.join(timeout=2)


    def test_existing_catalog_requires_explicit_execution_freeze_pin(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError,'Explicit execution freeze'):
            server.EvidenceCatalog(self.root).index()
        with self.assertRaisesRegex(ValueError,'study status'):
            server.EvidenceCatalog(self.root,expected_freeze_sha256='b'*64).index()

    def test_diagnostic_never_falls_back_to_completed_catalog(self):
        self.fixture()
        reader=server.EvidenceCatalog(self.root,expected_freeze_sha256=FREEZE_SHA,diagnostic=True)
        self.assertFalse(reader.index()['available'])
        # A complete manifest merely copied into the diagnostic folder fails.
        import shutil
        shutil.copytree(self.root/server.BASE,self.root/server.PARTIAL_BASE)
        with self.assertRaises(ValueError):reader.index()


if __name__=='__main__':unittest.main()

