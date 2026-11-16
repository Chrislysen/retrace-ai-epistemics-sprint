"""Versioned loopback workbench. Preserves the frozen v4 server and assets."""
import argparse
import copy
import hashlib
import json
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from .server import Handler, ROOT, MAX_BODY_BYTES, unique_object, reject_constant


def provenance_fingerprint(brief):
    """Bind source declarations; compiled fields and decision focus are derived."""
    declaration = copy.deepcopy(brief)
    declaration.pop('target_decisions', None)
    if 'compact_v5' in declaration:
        declaration.pop('compact_v4', None)
    if 'compact_v5' in declaration or 'compact_v4' in declaration:
        declaration.pop('candidates', None)
        declaration.pop('questions', None)
    encoded = json.dumps(declaration, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def catalog_provenance(brief):
    fingerprint = provenance_fingerprint(brief)
    result = {'status': 'unverified_supplied_brief', 'fingerprint': fingerprint,
              'declared_reference_comparison': bool(brief.get('reference_comparison')),
              'scope': 'A local catalog match is not external authentication or source truth.'}
    catalog = json.loads((ROOT / 'results/retrace-v5-catalog.json').read_text(encoding='utf-8'))
    for saved in catalog['briefs']:
        if provenance_fingerprint(saved) != fingerprint:
            continue
        kinds = [name for name in ('reference_comparison', 'fresh_confirmation', 'post_hoc_replay')
                 if saved.get(name)]
        if len(kinds) == 1:
            result.update(status='matched_saved_catalog', kind=kinds[0], catalog_id=saved['id'])
        break
    return result


class HandlerV5(Handler):
    def do_GET(self):
        if not self.local_host():
            return self.send(403, {'error': 'Use the local workbench address'})
        route = urlsplit(self.path).path
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/lab': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if route in assets:
            name, mime = assets[route]
            return self.send(200, (ROOT / 'web/v5' / name).read_bytes(), mime)
        if route == '/api/stress-benchmark':
            return self.send(200, json.loads((ROOT / 'results/retrace-v5-catalog.json').read_text(encoding='utf-8')))
        if route == '/api/v5/evaluation':
            return self.send(200, {'primary': json.loads((ROOT / 'results/ambiguity-v4-summary.json').read_text(encoding='utf-8'))['aggregates'],
                                   'posthoc': json.loads((ROOT / 'results/ambiguity-v5-posthoc-replay.json').read_text(encoding='utf-8'))['aggregates']})
        return super().do_GET()

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in ('/api/v5/analyze', '/api/v5/compile', '/api/v5/exposure-preview'):
            return super().do_POST()
        if not self.local_host():
            return self.send(403, {'error': 'Use the local workbench address'})
        origin = self.headers.get('Origin')
        if origin and origin != f'http://{self.headers.get("Host")}':
            return self.send(403, {'error': 'Cross-origin request rejected'})
        try:
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Transfer-Encoding is not accepted')
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not 0 < int(lengths[0]) <= MAX_BODY_BYTES:
                raise ValueError('Exactly one valid bounded Content-Length is required')
            raw = self.rfile.read(int(lengths[0]))
            if len(raw) != int(lengths[0]):
                raise ValueError('Incomplete request body')
            body = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
            if not isinstance(body, dict):
                raise ValueError('Request must be an object')
            if route == '/api/v5/compile':
                from .compact_v5 import compile_ambiguity
                result = compile_ambiguity(body.get('source'), body.get('registry'))
            else:
                from .engine_v5 import analyze_v5, preview_exposure
                result = (analyze_v5(body.get('brief'), body.get('state')) if route == '/api/v5/analyze'
                          else preview_exposure(body.get('brief'), body.get('state'), body.get('enable'), body.get('withdraw')))
                if route == '/api/v5/analyze':
                    result['provenance'] = catalog_provenance(result['compiled_brief'])
            return self.send(200, result)
        except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
            return self.send(400, {'error': str(exc), 'code': getattr(exc, 'code', 'invalid_input')})


def serve(port=8766):
    server = ThreadingHTTPServer(('127.0.0.1', port), HandlerV5)
    print(f'RETRACE v5 workbench: http://127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    serve(parser.parse_args().port)
