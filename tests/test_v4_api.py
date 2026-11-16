"""Real loopback HTTP integration; no external network or model requests."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from retrace.server import Handler

SOURCE = 'E a R 1 -\nE b R 0 -\nC c ?\nD d c\nAMBIGUOUS_GATE(c: a, b)\nEND'


class V4APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(2)

    def request(self, method, path, body=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        if isinstance(body, dict):
            body = json.dumps(body)
        client.request(method, path, body)
        response = client.getresponse()
        status, data = response.status, json.loads(response.read())
        client.close()
        return status, data

    def test_demo_compilation_and_live_pruning(self):
        status, brief = self.request('GET', '/api/v4/demo')
        self.assertEqual(status, 200)
        status, result = self.request('POST', '/api/v4/analyze', {'brief': brief})
        self.assertEqual(status, 200, result)
        self.assertEqual(len(result['candidate_ids']), 8)
        question = result['next_question']['id']
        status, after = self.request('POST', '/api/v4/analyze', {'brief': result['compiled_brief'], 'state': {'answers': {question: True}}})
        self.assertEqual(status, 200, after)
        self.assertEqual(len(after['candidate_ids']), 4)

    def test_compiler_endpoint_and_legacy_version_isolation(self):
        status, result = self.request('POST', '/api/v4/compile', {'source': SOURCE})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['candidate_count'], 2)
        self.assertEqual(self.request('POST', '/api/compile', {'source': SOURCE})[0], 400)
        status, result = self.request('POST', '/api/v4/analyze', {'brief': {'compact_v4': SOURCE}})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['schema'], 'retrace.stress.v4')

    def test_rejections_are_atomic_and_server_recovers(self):
        bad = [None, [], '', SOURCE + '\njunk', SOURCE.replace('a, b)', 'c, b)'),
               '\n'.join(['E a R 1 -', 'E b R 1 -'] + [f'C c{i} ?' for i in range(5)] + ['D d c0'] +
                         [f'AMBIGUOUS_GATE(c{i}: a, b)' for i in range(5)] + ['END'])]
        for source in bad:
            with self.subTest(source=source):
                self.assertEqual(self.request('POST', '/api/v4/analyze', {'brief': {'compact_v4': source}})[0], 400)
        self.assertEqual(self.request('POST', '/api/v4/analyze', {'brief': {'compact_v4': SOURCE}})[0], 200)

    def test_duplicate_json_and_nonfinite_rejected_at_v4_boundary(self):
        for raw in ('{"source":"x","source":"y"}', '{"source":NaN}', '[]'):
            self.assertEqual(self.request('POST', '/api/v4/compile', raw)[0], 400)


if __name__ == '__main__':
    unittest.main()
