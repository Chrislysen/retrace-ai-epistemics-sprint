"""Additive loopback workbench for source conservation; no model dispatch route."""
import argparse
import json
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from .server import ROOT, MAX_BODY_BYTES, unique_object, reject_constant
from .server_v5 import HandlerV5
from .catalog_v6 import catalog_v6, provenance_v6


class HandlerV6(HandlerV5):
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
            return self.send(200, (ROOT / 'web/v6' / name).read_bytes(), mime)
        if route == '/api/stress-demo':
            from .engine_v6b import demonstration
            return self.send(200, demonstration())
        if route == '/api/stress-benchmark':
            from .engine_v6b import demonstration
            return self.send(200, catalog_v6(demonstration))
        return super().do_GET()

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in ('/api/v6/analyze', '/api/v6/counter-reading'):
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
            from .engine_v6b import analyze_v6, demonstration
            result = analyze_v6(body.get('brief'), body.get('state'))
            if route == '/api/v6/counter-reading':
                from .counter_preview_v6 import preview_counter_reading
                result = preview_counter_reading(result, body.get('proposal'))
            else:
                result['provenance'] = provenance_v6(result['compiled_brief'], demonstration)
            return self.send(200, result)
        except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
            return self.send(400, {'error': str(exc), 'code': getattr(exc, 'code', 'invalid_input')})


def serve(port=8767):
    server = ThreadingHTTPServer(('127.0.0.1', port), HandlerV6)
    print(f'RETRACE v6 source-conservation workbench: http://127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8767)
    serve(parser.parse_args().port)
