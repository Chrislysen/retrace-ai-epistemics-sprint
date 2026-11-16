"""Local browser QA with invented observations only; never an empirical catalog.

No provider, credentials, live logs, or authenticated catalog publication. This
harness exercises the production rendering and mechanisms, not release readers.
"""
from copy import deepcopy
import json
from http.server import ThreadingHTTPServer

from retrace.server_v6l import HandlerV6l, EvidenceCatalog
from retrace.refuter_catalog_v6l import build_catalog, encode
from retrace.refuter_gate_v6h import validate_refuter
from retrace.source_ir_v6d import model_source
from tests.test_refuter_catalog_v6l import fixture, bind
from tests.test_refuter_inspector_v6l import DOCS, REG, graph, candidates, envelope


def observations():
    data = fixture(True)
    corpus, study, slots, audits, merged = data
    for i, (slot, request, response, outcome, audit) in enumerate(zip(
            slots, merged['requests'], merged['responses'], merged['outcomes'], audits)):
        mode = i % 6
        seed = graph({'any': [{'ref': 'A'}, {'ref': 'B'}]})
        proposal = envelope(graph({'all': [{'ref': 'A'}, {'ref': 'B'}]}))
        if mode == 1:
            seed = graph({'ref': 'B'}, False)
            proposal = envelope(graph({'all': [{'ref': 'A'}, {'ref': 'B'}]}, False))
        elif mode == 2:
            proposal['objection_spans'] = ['invented-invalid-span']
        elif mode == 3:
            proposal = {'status': 'no_counter_reading', 'ir': None,
                        'objection_spans': [], 'warning_score': 0.1}
        packet = {**model_source(DOCS, REG), 'supplied_candidates': candidates(seed)}
        slot['input'] = json.dumps(packet)
        request['request']['input'][-1]['content'] = slot['input']
        raw = json.dumps(proposal)
        response['output_text'] = raw
        if mode == 4:
            response.update(error='http_504', response_status=None,
                            model_outcome='provider_error', terminal_valid=False, output_text='')
        elif mode == 5:
            response.update(response_status='incomplete', model_outcome='truncated_max_output_tokens',
                            output_text='', partial_output_text=raw)
        outcome.clear()
        outcome.update(deepcopy(response))
        if mode in (4, 5):
            audit.update(provider_completed=False, eligible_completed=False,
                         schema_valid=False, refuter_gate=None)
        else:
            try: audit['refuter_gate'] = validate_refuter(raw, DOCS, REG)
            except ValueError: audit.update(refuter_gate=None, schema_valid=False)
    bind(merged)
    return build_catalog(*data, require_full_design=True)


class ConstructedCatalog:
    def __init__(self): self.value = observations()

    def index(self):
        return {**self.value['index'], 'available': True,
                'scope': 'CONSTRUCTED BROWSER QA. No empirical observations.'}

    def entry(self, key):
        row = next((r for r in self.value['index']['entries'] if r['key'] == key), None)
        if row is None: raise FileNotFoundError(key)
        value = deepcopy(self.value['entries'][row['entry_path']])
        value['scope'] = 'CONSTRUCTED BROWSER QA. Invented inputs and outputs; no empirical result. ' + value['scope']
        return encode(value)


class ConstructedHandler(HandlerV6l):
    def send(self, status, body, content_type='application/json; charset=utf-8'):
        if content_type.startswith('text/html') and isinstance(body, bytes):
            body = body.replace(b'<body>', b'<body><aside style="padding:16px;background:#ffe9a8;color:#241900;font-weight:bold">CONSTRUCTED BROWSER QA ONLY. Invented cases and responses. No live study results.</aside>', 1)
        return super().send(status, body, content_type)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 8774), ConstructedHandler)
    server.evidence_catalog = EvidenceCatalog()
    server.refuter_catalog = ConstructedCatalog()
    print('CONSTRUCTED browser QA only: http://127.0.0.1:8774', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
