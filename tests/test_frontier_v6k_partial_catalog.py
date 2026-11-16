"""Constructed fixtures only; interrupted product exports cannot claim completion."""
from copy import deepcopy
from hashlib import sha256
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from tests.test_frontier_v6k_catalog import fixture,bind
from scripts import export_frontier_v6k_partial_catalog as export
from retrace.server_v6k import EvidenceCatalog
from retrace.server_v6k_partial import PartialEvidenceCatalog,HandlerPartial


def data_with_censored_slot():
    data=fixture(full=True);_,_,_,audits,merged=data
    merged['requests'].pop(0);merged['responses'].pop(0)
    merged['outcomes'][0].update(issued=False,attempt_id=None,model_outcome='not_issued_global_stop',
        terminal_valid=False,output_text='',raw_response=None,response_status=None)
    audits[0].update(record_observed=False,provider_completed=False,eligible_completed=False,
        schema_valid=False,strict_bare_json=False,compilation=None,error='unissued',correct=False)
    bind(merged);return data


class PartialCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=data_with_censored_slot();cls.catalog=export.project(*cls.data)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def save_fixture(self):
        value=deepcopy(self.catalog)
        value['authentication']={'source_freeze_sha256':export.FREEZE_SHA256}
        with patch.object(export,'verify_plan'):
            manifest=export.write_catalog(self.root,value)
        return manifest

    def test_public_only_all300_and_censored_not_repaired(self):
        before=deepcopy(self.data);value=export.project(*self.data)
        self.assertEqual(self.data,before);self.assertEqual(len(value['index']['entries']),300)
        self.assertEqual(value['index']['counts']['not_issued'],1)
        row=value['index']['entries'][0];entry=value['entries'][row['entry_path']]
        self.assertIsNone(entry['brief']);self.assertIsNone(entry['metadata']['attempt_id'])
        self.assertEqual(entry['metadata']['model_outcome'],'not_issued_global_stop')
        self.assertTrue(entry['scope'].startswith('INTERRUPTED STUDY.'))
        self.assertEqual(sha256(export.encode(entry)).hexdigest(),row['entry_sha256'])
        self.assertNotIn('HIDDEN_GOLD',json.dumps(value));self.assertNotIn('HIDDEN_FAMILY',json.dumps(value))
        self.assertNotIn('HIDDEN_SEED',json.dumps(value))
        self.assertTrue(all(name.startswith(export.DIRECTORY+'/') for name in value['entries']))

    def test_no_unexplained_independent_unissued_extraction(self):
        data=deepcopy(self.data);data[4]['outcomes'][0]['model_outcome']='not_issued_dependency_failed';bind(data[4])
        with self.assertRaisesRegex(ValueError,'stop-censored'):export.project(*data)

    def test_readers_remain_separate_and_first_raw_bytes_unchanged(self):
        manifest=self.save_fixture();reader=PartialEvidenceCatalog(self.root);index=reader.index()
        self.assertEqual(index['study_status'],export.STATUS);self.assertFalse(index['schedule_complete'])
        self.assertFalse(index['inference_available']);self.assertEqual(len(index['entries']),300)
        self.assertFalse(EvidenceCatalog(self.root).index()['available'])
        censored=index['entries'][0]
        with self.assertRaises(FileNotFoundError):reader.entry(censored['key'],bundle=True)
        row=index['entries'][1];entry=json.loads(reader.entry(row['key']))
        self.assertEqual(entry['raw_output_text'],self.data[4]['responses'][0]['output_text'])
        self.assertEqual(json.loads(reader.entry(row['key'],bundle=True)),entry['brief'])
        class WrongCompleteReader(EvidenceCatalog):directory=export.DIRECTORY
        with self.assertRaisesRegex(ValueError,'status'):WrongCompleteReader(self.root).index()

    def test_partial_schema_cannot_advertise_completion(self):
        manifest=self.save_fixture();path=self.root/export.DIRECTORY/'manifest.json'
        for field,value in (('status','complete_amended_primary'),('schedule_complete',True),('inference_available',True)):
            changed={**manifest,field:value};path.write_bytes(export.encode(changed))
            with self.assertRaises(ValueError):PartialEvidenceCatalog(self.root).index()

    def test_active_run_rejects_before_computation(self):
        lock=self.root/'results/frontier-v6k/budget/active.lock';lock.parent.mkdir(parents=True);lock.write_text('fixture')
        with patch.object(export.partial,'compute') as compute:
            with self.assertRaisesRegex(ValueError,'Live study'):
                export.run(self.root,export.FREEZE_SHA256,'i','j','k','snapshot','sha')
            compute.assert_not_called()

    def test_source_mutation_before_manifest_leaves_no_published_catalog(self):
        value=deepcopy(self.catalog);value['authentication']={'source_freeze_sha256':export.FREEZE_SHA256}
        with patch.object(export,'verify_plan',side_effect=[None,ValueError('source changed')]):
            with self.assertRaisesRegex(ValueError,'source changed'):export.write_catalog(self.root,value)
        self.assertFalse((self.root/export.DIRECTORY/'manifest.json').exists())
        self.assertFalse(PartialEvidenceCatalog(self.root).index()['available'])

    def test_diagnostic_http_banner_and_missing_catalog_are_explicit(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),HandlerPartial)
        server.evidence_catalog=PartialEvidenceCatalog(self.root)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            conn=HTTPConnection('127.0.0.1',server.server_port);conn.request('GET','/')
            response=conn.getresponse();html=response.read().decode();self.assertEqual(response.status,200)
            self.assertIn('INTERRUPTED-STUDY VIEW — DIAGNOSTIC EVIDENCE ONLY',html)
            self.assertIn('censored, not observed model errors',html)
            conn.request('GET','/api/v6k/catalog');response=conn.getresponse();data=json.loads(response.read())
            self.assertFalse(data['available']);self.assertEqual(data['study_status'],export.STATUS)
            conn.close()
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
