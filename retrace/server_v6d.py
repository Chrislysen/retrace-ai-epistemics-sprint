"""Standalone loopback v6d workbench on8768. No network calls or persistence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from .server import Handler, ROOT, unique_object, reject_constant
from .engine_v6d import analyze_v6d, demo_brief, preview_exposure, preview_refuter, declaration_fingerprint
from .source_ir_v6d import model_source
from .source_ir_v6e_prompt import IR_V6E_INSTRUCTIONS

MAX_BODY_BYTES = 2_097_152
CATALOG_ROOT = ROOT / "results/catalog-v6"
CATALOG_ENTRY_LIMIT = 32 * 1024 * 1024


def _catalog_bytes(path, limit, expected_size=None):
    size = path.stat().st_size
    if size > limit or (expected_size is not None and size != expected_size):
        raise ValueError("Catalog hash or size bound changed")
    with path.open("rb") as stream: raw = stream.read(limit + 1)
    if len(raw) > limit or len(raw) != size: raise ValueError("Catalog hash or size bound changed")
    return raw


def catalog_manifest(directory=None):
    directory = (directory or CATALOG_ROOT).resolve()
    path = directory / "manifest.json"
    if not path.exists(): return None
    raw = _catalog_bytes(path, 4_194_304)
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if not isinstance(value, dict) or value.get("schema") != "retrace.recorded-catalog.v6": raise ValueError("Invalid catalog manifest")
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) > 2000 or value.get("scheduled_catalog_slots") != len(entries): raise ValueError("Invalid catalog inventory")
    seen = set()
    for row in entries:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not re.fullmatch(r"[0-9a-f]{24}", row["id"]): raise ValueError("Invalid catalog ID")
        if row["id"] in seen or row.get("path") != f"entries/{row['id']}.json": raise ValueError("Unsafe or duplicate catalog path")
        seen.add(row["id"])
        if not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]): raise ValueError("Invalid catalog hash")
        if type(row.get("bytes")) is not int or not 0 < row["bytes"] <= CATALOG_ENTRY_LIMIT: raise ValueError("Invalid catalog entry bound")
        if row.get("bundle_fingerprint") is not None and (not isinstance(row["bundle_fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["bundle_fingerprint"])):
            raise ValueError("Invalid catalog declaration fingerprint")
    if value.get("status_counts") != dict(Counter(row["status"] for row in entries)): raise ValueError("Catalog denominators disagree with inventory")
    return {**value, "manifest_sha256": hashlib.sha256(raw).hexdigest()}


def catalog_entry(identifier, directory=None, manifest=None):
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{24}", identifier): raise ValueError("Invalid catalog entry ID")
    directory = (directory or CATALOG_ROOT).resolve()
    manifest = manifest or catalog_manifest(directory)
    if manifest is None: return None
    row = next((item for item in manifest["entries"] if item["id"] == identifier), None)
    if row is None: return None
    path = (directory / row["path"]).resolve()
    if not path.is_relative_to(directory): raise ValueError("Catalog path escapes its directory")
    raw = _catalog_bytes(path, CATALOG_ENTRY_LIMIT, row["bytes"])
    if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]: raise ValueError("Catalog entry hash or size changed")
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if value.get("schema") != "retrace.recorded-catalog-entry.v6" or value.get("id") != identifier: raise ValueError("Entry differs from catalog identity")
    if any(value["provenance"].get(key) != row.get(key) for key in ("slot_id", "case_id", "model", "condition", "phase")) or value["outcome"].get("status") != row.get("status"):
        raise ValueError("Catalog index differs from the recorded entry")
    if (declaration_fingerprint(value["bundle"]) if value.get("bundle") else None) != row["bundle_fingerprint"]: raise ValueError("Catalog bundle fingerprint changed")
    return {**value, "catalog_provenance": {"manifest_sha256": manifest["manifest_sha256"], "entry_sha256": row["sha256"],
                                            "catalog_kind": manifest.get("catalog_kind"), "scope": "Local hash-bound recorded artifact; not external provider authentication or source truth."}}


def recorded_provenance(brief):
    manifest = catalog_manifest()
    if manifest is None: return None
    digest = declaration_fingerprint(brief)
    matches = [row for row in manifest["entries"] if row["bundle_fingerprint"] == digest]
    if not matches: return None
    entry = catalog_entry(matches[0]["id"], manifest=manifest)
    return {"status": "matched_recorded_catalog_declaration", "entry_id": entry["id"],
            **{key: entry["provenance"][key] for key in ("slot_id", "model", "case_id", "condition", "response_status")},
            **entry["catalog_provenance"]}


class HandlerV6d(Handler):
    def do_GET(self):
        if not self.local_host(): return self.send(403, {"error": "Use the local workbench address"})
        route = urlsplit(self.path).path
        assets = {"/": ("index.html", "text/html; charset=utf-8"), "/lab": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
        if route in assets:
            name, mime = assets[route]
            return self.send(200, (ROOT / "web/v6d" / name).read_bytes(), mime)
        if route == "/api/v6d/demo": return self.send(200, demo_brief())
        if route == "/api/v6d/catalog" or route.startswith("/api/v6d/catalog/"):
            try:
                if route == "/api/v6d/catalog":
                    manifest = catalog_manifest()
                    return self.send(200, manifest if manifest is not None else {"status": "not_built", "entries": [], "scope": "No recorded-output catalog has been published. The default example remains constructed."})
                match = re.fullmatch(r"/api/v6d/catalog/([0-9a-f]{24})", route)
                if not match: return self.send(404, {"error": "Unknown catalog entry"})
                entry = catalog_entry(match.group(1))
                return self.send(200, entry) if entry is not None else self.send(404, {"error": "Unknown catalog entry"})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                return self.send(409, {"error": "Catalog integrity check failed: " + str(exc)})
        return self.send(404, {"error": "Not found"})

    def do_POST(self):
        if not self.local_host(): return self.send(403, {"error": "Use the local workbench address"})
        route = urlsplit(self.path).path
        if route not in ("/api/v6d/analyze", "/api/v6d/source", "/api/v6d/refuter-preview", "/api/v6d/exposure-preview"):
            return self.send(404, {"error": "Not found"})
        origin = self.headers.get("Origin")
        if origin and origin != f'http://{self.headers.get("Host")}':
            return self.send(403, {"error": "Cross-origin request rejected"})
        try:
            if self.headers.get("Transfer-Encoding"): raise ValueError("Transfer-Encoding is not accepted")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not 0 < int(lengths[0]) <= MAX_BODY_BYTES:
                raise ValueError("Exactly one bounded Content-Length is required")
            raw = self.rfile.read(int(lengths[0]))
            if len(raw) != int(lengths[0]): raise ValueError("Incomplete request body")
            body = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
            if not isinstance(body, dict): raise ValueError("Request must be an object")
            allowed = {"brief", "state", "expected_declaration_fingerprint", "proposed_ir", "enable", "withdraw"}
            if set(body) - allowed: raise ValueError("Unknown request fields")
            brief = body.get("brief")
            if route == "/api/v6d/source":
                if not isinstance(brief, dict): raise ValueError("Supply a source bundle")
                result = {"source": model_source(brief.get("source_documents"), brief.get("registry")), "instructions": IR_V6E_INSTRUCTIONS,
                          "scope": "Source spans are locations only. No model request was made."}
            elif route == "/api/v6d/analyze":
                result = analyze_v6d(brief, body.get("state"), body.get("expected_declaration_fingerprint"))
                result["recorded_provenance"] = recorded_provenance(brief)
            elif route == "/api/v6d/refuter-preview":
                result = preview_refuter(brief, body.get("proposed_ir"), body.get("state"), body.get("expected_declaration_fingerprint"))
            else:
                result = preview_exposure(brief, body.get("state"), body.get("enable"), body.get("withdraw"), body.get("expected_declaration_fingerprint"))
            return self.send(200, result)
        except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
            return self.send(400, {"error": str(exc), "code": getattr(exc, "code", "invalid_input")})


def serve(port=8768):
    server = ThreadingHTTPServer(("127.0.0.1", port), HandlerV6d)
    print(f"RETRACE source review v6d: http://127.0.0.1:{server.server_port}", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8768)
    serve(parser.parse_args().port)
