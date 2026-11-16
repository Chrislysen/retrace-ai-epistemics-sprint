import http.client
import copy
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from retrace.server_v5 import HandlerV5


class V5APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), HandlerV5)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(2)

    def request(self, path, body=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        if isinstance(body, dict):
            body = json.dumps(body)
        client.request('POST' if body is not None else 'GET', path, body, headers or {})
        response = client.getresponse()
        status, data = response.status, response.read()
        client.close()
        return status, data

    def test_catalog_distinguishes_replays_and_authored_comparisons(self):
        status, data = self.request('/api/stress-benchmark')
        self.assertEqual(status, 200)
        catalog = json.loads(data)
        self.assertEqual(sum(bool(b.get('post_hoc_replay')) for b in catalog['briefs']), 10)
        comparison = next(b for b in catalog['briefs'] if b.get('reference_comparison'))
        self.assertIn('authored reference', comparison['prose'])
        status, data = self.request('/api/v5/analyze', {'brief': comparison})
        self.assertEqual(status, 200, data)
        analysis = json.loads(data)
        witness = next(row['minimum'] for row in analysis['exposure']['decisions'].values() if row['minimum'])
        status, data = self.request('/api/v5/exposure-preview', {'brief': comparison, 'state': {}, 'enable': witness['enable'], 'withdraw': witness['withdraw']})
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)['status'], 'hypothetical_source_amendment')

    def test_boundary_rejects_duplicate_json_nonfinite_and_cross_origin(self):
        for body in ('{"brief":{},"brief":{}}', '{"brief":NaN}', '[]'):
            self.assertEqual(self.request('/api/v5/analyze', body)[0], 400)
        self.assertEqual(self.request('/api/v5/analyze', {}, {'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(self.request('/', headers={'Host': 'other.example'})[0], 403)

    def test_versioned_syntax_does_not_change_legacy_admission(self):
        body = {'source': 'E a R 1 -\nE b R 0 -\nC c AMBIGUOUS_GATE(a,b)\nD d c\nEND'}
        self.assertEqual(self.request('/api/v5/compile', body)[0], 200)
        self.assertEqual(self.request('/api/v4/compile', body)[0], 400)

    def test_lab_and_root_serve_the_same_v5_document(self):
        root_status, root = self.request('/')
        lab_status, lab = self.request('/lab')
        self.assertEqual((root_status, lab_status), (200, 200))
        self.assertEqual(root, lab)
        self.assertIn(b'id="exposure-preview"', lab)

    def test_catalog_provenance_survives_derived_exports_and_focus(self):
        catalog = json.loads(self.request('/api/stress-benchmark')[1])
        brief = next(b for b in catalog['briefs'] if b.get('fresh_confirmation'))
        status, data = self.request('/api/v5/analyze', {'brief': brief})
        first = json.loads(data)
        self.assertEqual(status, 200, data)
        self.assertEqual(first['provenance']['kind'], 'fresh_confirmation')
        exported = first['compiled_brief']
        exported['target_decisions'] = [next(iter(first['decision_states']))]
        exported['candidates'] = []  # The unchanged program is authoritative.
        status, data = self.request('/api/v5/analyze', {'brief': exported})
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)['provenance']['status'], 'matched_saved_catalog')

    def test_changed_source_or_forged_flags_cannot_claim_catalog_provenance(self):
        catalog = json.loads(self.request('/api/stress-benchmark')[1])
        fresh = next(b for b in catalog['briefs'] if b.get('fresh_confirmation'))
        altered = copy.deepcopy(fresh)
        altered['compact_v5'] += '\n'  # Even equivalent edits lose exact provenance.
        forged = copy.deepcopy(fresh)
        forged['reference_comparison'] = True
        for brief in (altered, forged):
            status, data = self.request('/api/v5/analyze', {'brief': brief})
            self.assertEqual(status, 200, data)
            self.assertEqual(json.loads(data)['provenance']['status'], 'unverified_supplied_brief')
        self.assertTrue(json.loads(data)['provenance']['declared_reference_comparison'])


if __name__ == '__main__':
    unittest.main()
