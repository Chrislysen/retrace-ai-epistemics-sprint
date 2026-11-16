import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from retrace.server_v6 import HandlerV6


class V6APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), HandlerV6)
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
        status, raw = response.status, response.read()
        client.close()
        return status, raw

    def test_demo_exposes_shared_omission_without_changing_graph_agreement(self):
        brief = json.loads(self.request('/api/stress-demo')[1])
        status, raw = self.request('/api/v6/analyze', {'brief': brief})
        self.assertEqual(status, 200, raw)
        result = json.loads(raw)
        self.assertTrue(result['source_review']['review_required'])
        self.assertEqual(result['decision_states']['D']['display_label'], 'Supported under declared links')
        self.assertEqual(result['provenance']['status'], 'matched_constructed_demonstration')

    def test_routes_and_boundary_validation(self):
        status, root = self.request('/')
        self.assertEqual(status, 200)
        self.assertEqual(root, self.request('/lab')[1])
        self.assertIn(b'id="conservation-panel"', root)
        self.assertIn(b'id="counter-proposal"', root)
        self.assertEqual(self.request('/api/v6/analyze', '{"brief":{},"brief":{}}')[0], 400)
        self.assertEqual(self.request('/api/v6/analyze', {}, {'Origin': 'https://other.example'})[0], 403)

    def test_counter_reading_abstention_is_explicit_and_preserves_review_gate(self):
        brief = json.loads(self.request('/api/stress-demo')[1])
        status, raw = self.request('/api/v6/counter-reading', {
            'brief': brief, 'proposal': '{"status":"no_counter_reading"}'})
        self.assertEqual(status, 200, raw)
        result = json.loads(raw)
        self.assertEqual(result['proposal_status'], 'no_counter_reading')
        self.assertFalse(result['semantic_verified'])
        self.assertTrue(result['source_review_unchanged']['review_required'])
        self.assertEqual(self.request('/api/v6/counter-reading', {
            'brief': brief, 'proposal': '{"status":"counter_reading","status":"no_counter_reading"}'})[0], 400)


if __name__ == '__main__':
    unittest.main()
