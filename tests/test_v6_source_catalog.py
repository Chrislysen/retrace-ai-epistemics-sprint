import copy
import json
from pathlib import Path
import unittest

from retrace.catalog_v6 import catalog_v6, provenance_v6
from retrace.engine_v6 import demonstration

ROOT = Path(__file__).resolve().parents[1]


class SourceCatalogTests(unittest.TestCase):
    def test_conservation_uses_public_documents_without_benchmark_commentary(self):
        catalog = catalog_v6(demonstration)
        self.assertEqual(len(catalog['briefs']), 21)
        for row in catalog['briefs'][1:]:
            self.assertTrue(row['source_documents'])
            for doc in row['source_documents']:
                self.assertEqual(set(doc), {'id', 'text'})
                self.assertNotIn('PROSPECTIVE CONFIRMATION:', doc['text'])
                self.assertNotIn('BENCHMARK COMPARISON:', doc['text'])
                self.assertNotIn('Unchanged model output:', doc['text'])
            self.assertNotIn('hidden', row)

    def test_attaching_source_does_not_change_any_saved_candidate(self):
        prior = json.loads((ROOT / 'results/retrace-v5-catalog.json').read_text(encoding='utf-8'))
        old = {row['id']: row for row in prior['briefs']}
        for row in catalog_v6(demonstration)['briefs'][1:]:
            self.assertEqual(row['candidates'], old[row['id']]['candidates'])

    def test_provenance_binds_the_actual_audited_source(self):
        row = catalog_v6(demonstration)['briefs'][1]
        self.assertEqual(provenance_v6(row, demonstration)['status'], 'matched_saved_catalog')
        edited = copy.deepcopy(row)
        edited['source_documents'][0]['text'] += ' Edited.'
        self.assertEqual(provenance_v6(edited, demonstration)['status'], 'unverified_supplied_brief')


if __name__ == '__main__':
    unittest.main()
