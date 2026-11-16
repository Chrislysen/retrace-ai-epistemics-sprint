"""Standalone local v6h source-review workbench on8769; no provider calls."""
import argparse
import json
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from .server import Handler, ROOT, unique_object, reject_constant
from .workbench_v6h import analyze_workbench, preview_refuter, demo_brief, prepared_source
from .prompts_v6h import IR_INSTRUCTIONS

MAX_BODY_BYTES = 2_097_152


class HandlerV6h(Handler):
    def do_GET(self):
        if not self.local_host(): return self.send(403, {"error": "Use the local workbench address"})
        route = urlsplit(self.path).path
        assets = {"/": ("index.html", "text/html; charset=utf-8"), "/lab": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
        if route in assets:
            name, mime = assets[route]
            return self.send(200, (ROOT / "web/v6h" / name).read_bytes(), mime)
        if route == "/api/v6h/demo": return self.send(200, demo_brief())
        return self.send(404, {"error": "Not found"})

    def do_POST(self):
        if not self.local_host(): return self.send(403, {"error": "Use the local workbench address"})
        route = urlsplit(self.path).path
        if route not in ("/api/v6h/analyze", "/api/v6h/source", "/api/v6h/refuter-preview"):
            return self.send(404, {"error": "Not found"})
        origin = self.headers.get("Origin")
        if origin and origin != f'http://{self.headers.get("Host")}': return self.send(403, {"error": "Cross-origin request rejected"})
        try:
            if self.headers.get("Transfer-Encoding"): raise ValueError("Transfer-Encoding is not accepted")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not 0 < int(lengths[0]) <= MAX_BODY_BYTES: raise ValueError("Exactly one bounded Content-Length is required")
            raw = self.rfile.read(int(lengths[0]))
            if len(raw) != int(lengths[0]): raise ValueError("Incomplete request body")
            body = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
            if not isinstance(body, dict) or set(body) - {"brief", "state", "expected_fingerprint", "proposal"}: raise ValueError("Unknown request fields")
            if route == "/api/v6h/source":
                result = {"source": prepared_source(body.get("brief")), "instructions": IR_INSTRUCTIONS,
                          "scope": "Prepared locally; no model request was made. Review before sharing source text elsewhere."}
            elif route == "/api/v6h/analyze":
                result = analyze_workbench(body.get("brief"), body.get("state"), body.get("expected_fingerprint"))
            else:
                result = preview_refuter(body.get("brief"), body.get("proposal"), body.get("state"), body.get("expected_fingerprint"))
            return self.send(200, result)
        except (ValueError, TypeError, KeyError, OSError, RecursionError, OverflowError) as exc:
            return self.send(400, {"error": str(exc), "code": "invalid_declaration_or_state"})


def serve(port=8769):
    server = ThreadingHTTPServer(("127.0.0.1", port), HandlerV6h)
    print(f"RETRACE four-state workbench: http://127.0.0.1:{server.server_port}", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8769)
    serve(parser.parse_args().port)
