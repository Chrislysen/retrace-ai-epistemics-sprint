"""Loopback epistemic stress tester. No persistence, inference or external calls."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .core import analyze
from .compact_graph import parse_compact_output

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY_BYTES = 512_000


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field: " + key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON constant is not accepted: " + value)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def local_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.local_host():
            return self.send(403, {"error": "Use the local stress-tester address"})
        route = urlsplit(self.path).path
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/lab": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if route in assets:
            filename, mime = assets[route]
            return self.send(200, (ROOT / "web" / filename).read_bytes(), mime)
        if route == "/api/v4/demo":
            return self.send(200, {
                "id": "typed-ambiguity-v4-example", "title": "Typed ambiguity: enumerate the unresolved choices",
                "artificial_demonstration": True,
                "prose": "Constructed offline example. The compact program declares unresolved dependency choices explicitly. Every binary assignment is retained; source truth and real-world completeness are not inferred. Root independence has not been externally verified. The source editor below shows the exact declarations.",
                "compact_v4": (ROOT / "data/ambiguity-v4-demo.txt").read_text(encoding="utf-8"),
            })
        data_routes = {"/api/demo": "data/demo.json",
                       "/api/stress-demo": "data/stress-demo.json",
                       "/api/stress-benchmark": "results/ambiguity-v3-live-briefs.json",
                       "/api/uncertainty-demo": "data/uncertainty-demo.json",
                       "/api/benchmark": "results/rule-baselines.json",
                       "/api/pilot": "results/pilot-summary.json",
                       "/api/prose": "results/prose-summary.json",
                       "/api/prose-review": "results/prose-review.json",
                       "/api/extraction-v2": "results/extraction-v2-summary.json",
                       "/api/ambiguity-v3": "results/ambiguity-v3-summary.json"}
        if route in data_routes:
            path = ROOT / data_routes[route]
            return self.send(200, json.loads(path.read_text(encoding="utf-8")) if path.exists()
                             else {"status": "not_run"})
        return self.send(404, {"error": "Not found"})

    def do_POST(self):
        if not self.local_host():
            return self.send(403, {"error": "Use the local stress-tester address"})
        route = urlsplit(self.path).path
        if route not in ("/api/analyze", "/api/compile", "/api/uncertainty", "/api/interventions", "/api/stress", "/api/v4/analyze", "/api/v4/compile"):
            return self.send(404, {"error": "Not found"})
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return self.send(403, {"error": "Cross-origin request rejected"})
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Transfer-Encoding is not accepted")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                raise ValueError("Exactly one Content-Length is required")
            size = int(lengths[0])
            if not 0 < size <= MAX_BODY_BYTES:
                raise ValueError(f"Request must be between 1 and {MAX_BODY_BYTES} bytes")
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("Incomplete request body")
            body = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
            if not isinstance(body, dict):
                raise ValueError("Request must be an object")
            if route == "/api/v4/analyze":
                from .engine_v4 import analyze_v4
                return self.send(200, analyze_v4(body.get("brief"), body.get("state")))
            if route == "/api/v4/compile":
                from .compact_v4 import compile_ambiguity
                return self.send(200, compile_ambiguity(body.get("source"), body.get("registry")))
            if route == "/api/stress":
                from .stress import analyze_stress
                return self.send(200, analyze_stress(body.get("brief"), body.get("state")))
            if route == "/api/compile":
                compiled = parse_compact_output(body.get("source"), body.get("registry"))
                return self.send(200, {**compiled, "snapshot": analyze(compiled["graph"])})
            if route == "/api/uncertainty":
                from .uncertainty import analyze_uncertainty
                return self.send(200, analyze_uncertainty(body.get("candidates"), body.get("questions"), body.get("target_decisions")))
            if route == "/api/interventions":
                from .intervention_audit import audit_interventions
                return self.send(200, audit_interventions(body.get("graphs"), body.get("allowed_withdrawals")))
            case = body.get("case")
            if (not isinstance(case, dict)
                    or any(not isinstance(case.get(k), list) for k in ("evidence", "claims", "decisions"))
                    or sum(len(case[k]) for k in ("evidence", "claims", "decisions")) > 250):
                raise ValueError("Case must be an object with at most 250 nodes")
            return self.send(200, analyze(case, body.get("revoked", [])))
        except (ValueError, OSError, TypeError, KeyError, RecursionError) as exc:
            return self.send(400, {"error": str(exc), "code": getattr(exc, "code", "invalid_input"),
                                   "line_number": getattr(exc, "line_number", None)})

    def log_message(self, *_args):
        pass


def serve(port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"RETRACE epistemic stress tester: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
