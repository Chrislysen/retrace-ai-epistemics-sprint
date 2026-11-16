"""Prepared saved-result boundary tests; only invented temporary artifacts."""
from copy import deepcopy
import json
import unittest
from scripts import frontier_v6m_products as product
from scripts import score_frontier_v6m as score
from tests import test_score_frontier_v6m as score_fixtures


class SavedProductEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.base=score_fixtures.RecoveryCliTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.root=self.base.root
    def prepare(self,diagnostic=False):
        self.base.fixture(diagnostic=diagnostic);result,views=self.base.compute()
        writer='scripts/score_frontier_v6m.py'
        result['summary']['file_evidence']['runtime_input_bindings'][writer]=score.binding(self.root/writer)
        score.write_outputs(self.root,result,views,diagnostic=diagnostic)
        return result,views
    def verify(self,result,views,diagnostic=False):
        return product.verify_saved(self.root,result,views,aliases={},ledger_snapshot=score.SNAPSHOT,diagnostic=diagnostic)

    def test_exact_saved_eight_artifacts_and_both_scientific_views(self):
        result,views=self.prepare();bindings=self.verify(result,views)
        self.assertEqual(len(bindings),8)
        for field in ('frozen_diagnostic','amended_recovered_complete'):
            bad=deepcopy(result);bad['summary'][field]['invented_change']=True
            with self.assertRaisesRegex(ValueError,'Both saved scientific'):self.verify(bad,views)

    def test_raw_view_requires_identical_bytes_not_json_equivalence(self):
        result,views=self.prepare();changed=dict(views)
        changed['requests']=(json.dumps(json.loads(views['requests']))+'\n').encode()
        self.assertEqual(json.loads(changed['requests']),json.loads(views['requests']))
        self.assertNotEqual(changed['requests'],views['requests'])
        with self.assertRaisesRegex(ValueError,'raw source lines'):self.verify(result,changed)

    def test_rehashed_manifest_writer_cannot_change(self):
        result,views=self.prepare();path=self.root/score.OUTPUT/'composite-manifest.json'
        value=json.loads(path.read_bytes());value['writer_sha256']='0'*64
        path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Writer'):self.verify(result,views)

    def test_missing_or_duplicate_inventory_entry_rejects(self):
        result,views=self.prepare();path=self.root/score.OUTPUT/'composite-manifest.json'
        original=json.loads(path.read_bytes())
        for files in (original['files'][:-1],original['files']+[original['files'][0]]):
            value=deepcopy(original);value['files']=files;path.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'seven-file'):self.verify(result,views)

    def test_partial_saved_results_cannot_satisfy_complete_product(self):
        result,views=self.prepare(diagnostic=True)
        self.assertEqual(len(self.verify(result,views,True)),8)
        with self.assertRaisesRegex(ValueError,'branch'):self.verify(result,views,False)


if __name__=='__main__':unittest.main()
