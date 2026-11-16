"""HTTP boundary tests: no persistent store and no external model calls."""
import copy
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from retrace.server import Handler, MAX_BODY_BYTES


def brief():
    graph = {"evidence": [{"id": "a", "kind": "root", "active": True, "parents": []}],
             "claims": [{"id": "c", "supports": [["a"]]}],
             "decisions": [{"id": "d", "requires": ["c"]}]}
    return {"id": "api-test", "candidates": [{"id": "one", "graph": graph}],
            "questions": [], "documents": [{"id": "doc", "label": "Source", "evidence_ids": ["a"]}]}


class StressAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(2)

    def request(self, method, path, body=None, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        if isinstance(body, dict):
            body = json.dumps(body)
        client.request(method, path, body=body, headers=headers or {})
        response = client.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        client.close()
        return result

    def test_entry_is_direct_stress_tester_and_crud_is_absent(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"/app.js", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", "/api/workspaces")[0], 404)
        self.assertEqual(self.request("POST", "/api/workspaces", {"title": "bad"})[0], 404)

    def test_stateless_roundtrip_and_separate_revocations(self):
        item = brief()
        original = copy.deepcopy(item)
        def run(state):
            status, _, body = self.request("POST", "/api/stress", {"brief": item, "state": state})
            self.assertEqual(status, 200, body)
            return json.loads(body)
        result = run({"revoked_documents": ["doc"], "revoked_passages": ["a"]})
        self.assertFalse(result["consensus"]["candidate_decision_vectors"]["one"]["d"])
        result = run({"revoked_documents": [], "revoked_passages": ["a"]})
        self.assertFalse(result["consensus"]["candidate_decision_vectors"]["one"]["d"])
        self.assertFalse(result["revocation_flags"]["a"]["document_veto"])
        self.assertTrue(result["revocation_flags"]["a"]["passage_veto"])
        result = run({})
        self.assertTrue(result["consensus"]["candidate_decision_vectors"]["one"]["d"])
        self.assertEqual(item, original)

    def test_rebinding_cross_origin_and_invalid_json_fail_closed(self):
        self.assertEqual(self.request("GET", "/", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/stress", {}, {"Origin": "https://attacker.example"})[0], 403)
        for raw in ['{"brief":{},"brief":{}}', '{"brief":NaN}', '[]', 'null', '{']:
            with self.subTest(raw=raw):
                self.assertEqual(self.request("POST", "/api/stress", raw)[0], 400)
        self.assertEqual(self.request("POST", "/api/stress", "x", {"Content-Length": str(MAX_BODY_BYTES + 1)})[0], 400)

    def test_bad_graph_input_rejects_without_server_failure(self):
        for item in [None, [], {}, {"candidates": []}, {"candidates": [{"id": "one", "graph": None}]}]:
            with self.subTest(item=item):
                self.assertEqual(self.request("POST", "/api/stress", {"brief": item})[0], 400)
        status, _, body = self.request("POST", "/api/stress?view=test", {"brief": brief()})
        self.assertEqual(status, 200, body)


if __name__ == "__main__":
    unittest.main()
