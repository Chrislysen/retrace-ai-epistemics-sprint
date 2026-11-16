"""Create an immutable, public-only recorded-outcome catalog. No inference.

Every scheduled source-IR, refuter and long-IR slot is retained. Source-family
gold and evaluation annotations are never projected into product entries.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.frontier_v6c_io import parse_object
from retrace.source_ir_v6d import compile_cited_ir, source_segments

ARMS = {"source_ir", "adversarial_refuter", "long_source_ir"}
ENTRY_LIMIT = 32 * 1024 * 1024


def loads(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise ValueError("Duplicate JSON field")
            out[key] = value
        return out
    def invalid(_): raise ValueError("Nonfinite JSON number")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _read(path, root, role, jsonl=False):
    path = Path(path).resolve()
    if not path.is_relative_to(root): raise ValueError("Catalog inputs must stay within the declared workspace root")
    raw = path.read_bytes(); text = raw.decode("utf-8")
    value = [loads(line) for line in text.splitlines() if line.strip()] if jsonl else loads(text)
    return value, {"role": role, "path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _freeze(paths, root, required):
    inputs, covered = [], set()
    for path in paths:
        value, metadata = _read(path, root, "freeze")
        rows = value.get("files")
        if not isinstance(rows, list) or not rows: raise ValueError("Freeze must contain a nonempty files list")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or not {"path", "sha256"} <= set(row): raise ValueError("Invalid freeze entry")
            target = (root / row["path"]).resolve()
            if not target.is_relative_to(root) or target in seen: raise ValueError("Unsafe or duplicate freeze path")
            seen.add(target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != row["sha256"]: raise ValueError("Frozen input changed: " + row["path"])
        covered |= seen; inputs.append(metadata)
    if paths and not set(required) <= covered: raise ValueError("Corpus, dossiers and sessions must all be covered by the supplied freezes")
    return inputs


def _valid_usage(value):
    if not isinstance(value, dict): return False
    if any(type(value.get(key)) is not int or value[key] < 0 for key in ("input_tokens", "output_tokens")): return False
    return "total_tokens" not in value or (type(value["total_tokens"]) is int and value["total_tokens"] == value["input_tokens"] + value["output_tokens"])


def _classify(record, documents, registry, arm, requested, requests_complete, run_closed):
    out = {"status": "no_response_record", "loadable_ir": False, "executable_ir": False,
           "strict_bare_json": False, "parsed_output": None, "source_ir": None, "compiler_error": None,
           "candidate_count": None, "missing_disposition_ids": []}
    if record is None:
        out["status"] = ("issued_missing_response" if requested else "unissued") if run_closed else (
            "pending_or_missing_response" if requested else "pending_or_unissued_or_missing_response")
        return out
    if record.get("issued") is False:
        out["status"] = "unissued_dependency"; return out
    if record.get("error") is not None or record.get("http_status") != 200 or record.get("terminal_valid") is False or not _valid_usage(record.get("usage")):
        out["status"] = "operational_or_accounting_failure"; return out
    if record.get("response_status") == "incomplete":
        out["status"] = "truncated"; return out
    if record.get("response_status") != "completed" or not isinstance(record.get("output_text"), str):
        out["status"] = "noncompleted_response"; return out
    try:
        parsed, strict = parse_object(record["output_text"])
    except (ValueError, TypeError, RecursionError) as exc:
        out.update(status="invalid_json_object", compiler_error={"code": "output_parse", "message": str(exc)})
        return out
    out.update(parsed_output=deepcopy(parsed), strict_bare_json=strict)
    if arm == "adversarial_refuter" and parsed == {"status": "no_counter_reading"}:
        out["status"] = "abstention"; return out
    try:
        compilation = compile_cited_ir(parsed, documents, registry)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        out.update(status="invalid_ir", compiler_error={"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)})
        return out
    missing = [row["id"] for row in compilation["registry_disposition"] if row["status"] == "absent_from_ir"]
    executable = compilation["status"] == "compiled"
    out.update(status="unresolved_structure" if not executable else "compiled_inventory_gap" if missing else "compiled_ir",
               source_ir=deepcopy(parsed), loadable_ir=True, executable_ir=executable,
               candidate_count=compilation["candidate_count"], missing_disposition_ids=missing)
    return out


def build_catalog(corpus_path, dossiers_path, sessions_path, response_paths, output_directory, *,
                  request_paths=(), requests_complete=False, run_closed=False, freeze_paths=(), workspace_root=ROOT, require_primary=True):
    root = Path(workspace_root).resolve(); output = Path(output_directory).resolve()
    if not output.is_relative_to(root) or output.exists(): raise ValueError("Catalog output must be a new directory within the workspace")
    if requests_complete and not request_paths: raise ValueError("Complete request coverage requires explicit journal files, even when empty")
    if run_closed and not requests_complete: raise ValueError("A closed-run catalog requires complete supplied request journals")
    corpus, cmeta = _read(corpus_path, root, "corpus")
    dossiers, dmeta = _read(dossiers_path, root, "dossiers")
    slots, smeta = _read(sessions_path, root, "sessions")
    inputs = [cmeta, dmeta, smeta]
    if require_primary and not freeze_paths: raise ValueError("Primary catalog requires verified source/session freeze manifests")
    inputs += _freeze(freeze_paths, root, [Path(p).resolve() for p in (corpus_path, dossiers_path, sessions_path)])
    cases = {case["id"]: case for case in corpus["cases"]}
    long_cases = {case["case_id"]: case for case in dossiers["cases"]}
    if len(cases) != len(corpus["cases"]) or len(long_cases) != len(dossiers["cases"]): raise ValueError("Duplicate source case IDs")
    if not set(long_cases) <= set(cases): raise ValueError("Dossier case not present in source corpus")
    if require_primary and (len(cases) != 48 or len(long_cases) != 24 or len(slots) != 4560): raise ValueError("Primary catalog requires the frozen48-case/24-dossier/4560-slot schedule")
    schedule = {}; identities = set()
    for slot in slots:
        sid = slot["slot_id"]; identity = tuple(slot[k] for k in ("model", "case_id", "condition", "phase"))
        if sid in schedule or identity in identities or slot["case_id"] not in cases: raise ValueError("Duplicate or unknown scheduled slot")
        schedule[sid] = slot; identities.add(identity)
    records, record_locations, requests = {}, {}, {}
    for path in response_paths:
        rows, metadata = _read(path, root, "responses", True); inputs.append(metadata)
        for number, record in enumerate(rows, 1):
            sid = record.get("slot_id")
            if sid not in schedule or sid in records: raise ValueError("Duplicate or unknown response; no best retry may be selected")
            if any(record.get(key) != schedule[sid][key] for key in ("case_id", "model", "condition", "phase")): raise ValueError("Response differs from scheduled identity")
            if "issued" in record and type(record["issued"]) is not bool: raise ValueError("Response issued flag must be Boolean")
            records[sid] = record
            record_locations[sid] = {"input_path": metadata["path"], "nonempty_jsonl_record": number, "record_sha256_canonical": fingerprint(record)}
    for path in request_paths:
        rows, metadata = _read(path, root, "requests", True); inputs.append(metadata)
        for request in rows:
            sid = request.get("slot_id")
            if sid not in schedule or sid in requests: raise ValueError("Duplicate or unknown request slot")
            requests[sid] = request
    if request_paths and any(sid not in requests for sid, record in records.items() if record.get("issued", True)):
        raise ValueError("Issued response lacks a supplied request journal entry")
    if any(sid in requests for sid, record in records.items() if record.get("issued") is False): raise ValueError("Not-issued outcome conflicts with request journal")
    entries, index = [], []
    for order, slot in enumerate(slots):
        if slot["condition"] not in ARMS: continue
        case = cases[slot["case_id"]]; public = case["public"]
        docs = deepcopy(long_cases[case["id"]]["source_documents"] if slot["condition"] == "long_source_ir" else public["source_documents"])
        base = {d["id"]: d["text"] for d in public["source_documents"]}
        if any(next((d["text"] for d in docs if d["id"] == identifier), None) != text for identifier, text in base.items()):
            raise ValueError("Dossier does not preserve the exact corresponding source")
        payload = loads(slot["input"])
        if payload.get("source_segments") != source_segments(docs) or payload.get("registry") != public["registry"]:
            raise ValueError("Scheduled model input does not match the declared public source")
        eid = hashlib.sha256(slot["slot_id"].encode()).hexdigest()[:24]
        if any(row["id"] == eid for row in index): raise ValueError("Catalog ID collision")
        record = records.get(slot["slot_id"])
        outcome = _classify(record, docs, public["registry"], slot["condition"], slot["slot_id"] in requests, requests_complete, run_closed)
        source_bundle = {"id": "recorded-" + eid, "title": f"{slot['model']} · {case['id']} · {slot['condition']}",
                         "source_documents": docs, "registry": deepcopy(public["registry"]),
                         "documents": deepcopy(case.get("events", {}).get("document_groups", []))}
        bundle = {**deepcopy(source_bundle), "source_ir": deepcopy(outcome["source_ir"])} if outcome["loadable_ir"] else None
        provenance = {key: deepcopy(slot[key]) for key in ("slot_id", "case_id", "model", "condition", "phase", "max_output_tokens")}
        provenance.update(schedule_position=order, record_observed=record is not None, request_observed=slot["slot_id"] in requests,
                          record_location=record_locations.get(slot["slot_id"]), input_sha256=hashlib.sha256(slot["input"].encode()).hexdigest(),
                          instructions_sha256=hashlib.sha256(slot["instructions"].encode()).hexdigest(),
                          source_binding_sha256=fingerprint({"documents": docs, "registry": public["registry"]}),
                          request_journals_declared_complete=bool(requests_complete), run_declared_closed=bool(run_closed))
        for key in ("attempt_id", "run_id", "at", "issued", "terminal_valid", "model_outcome", "http_status", "response_status", "error", "usage", "latency_ms", "reserved_credits", "settled_credits"):
            provenance[key] = deepcopy(record.get(key)) if record is not None else None
        raw = {key: deepcopy(record.get(key)) if record is not None else None for key in
               ("output_text", "partial_output_text", "raw_response", "stream_terminal_event", "stream_evidence", "stream_event_count", "blocked_dependencies")}
        entry = {"schema": "retrace.recorded-catalog-entry.v6", "id": eid, "source_bundle": source_bundle, "bundle": bundle,
                 "outcome": outcome, "provenance": provenance, "raw": raw,
                 "scope": ["Recorded model output, not a reference graph or proof of textual entailment.",
                           "No output repair, retry selection, expected source family, hidden annotation or adjudicated truth is included.",
                           "Formal admission does not establish source completeness. Failed and unissued scheduled slots remain visible.",
                           "Refuter output is a proposed counter-reading and must be previewed explicitly; loading or viewing does not commit a correction."]}
        data = encoded(entry)
        if len(data) > ENTRY_LIMIT: raise ValueError("Catalog entry exceeds its explicit32MB bound; no output was truncated")
        metadata = {"id": eid, "path": f"entries/{eid}.json", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                    "bundle_fingerprint": fingerprint(bundle) if bundle else None,
                    **{key: provenance[key] for key in ("slot_id", "case_id", "model", "condition", "phase")},
                    **{key: outcome[key] for key in ("status", "loadable_ir", "executable_ir", "candidate_count")},
                    "record_observed": record is not None, "request_observed": slot["slot_id"] in requests,
                    "response_status": provenance["response_status"], "usage": provenance["usage"]}
        entries.append((metadata["path"], data)); index.append(metadata)
    if require_primary and len(index) != 600: raise ValueError("Expected all600 scheduled primary IR/refuter/long-IR outcomes")
    groups = lambda key: {value: {"scheduled": sum(row[key] == value for row in index),
                                 "statuses": dict(Counter(row["status"] for row in index if row[key] == value))}
                           for value in sorted({row[key] for row in index})}
    manifest = {"schema": "retrace.recorded-catalog.v6", "created_at": datetime.now(timezone.utc).isoformat(),
                "catalog_kind": "recorded_primary_schedule" if require_primary else "test_fixture_only",
                "publication_status": "closed_run_snapshot" if run_closed else "provisional_snapshot",
                "inputs": inputs, "full_schedule_slots": len(slots), "scheduled_catalog_slots": len(index),
                "included_conditions": sorted(ARMS), "request_journals_declared_complete": bool(requests_complete),
                "status_counts": dict(Counter(row["status"] for row in index)), "by_model": groups("model"), "by_arm": groups("condition"),
                "entries": index, "scope": "Every scheduled source-IR, refuter and long-IR outcome is listed. These are recorded outputs, not source-truth or accuracy scores. Inputs and entries are hash-bound; this local manifest is not external authentication."}
    def unchanged():
        for item in inputs:
            if hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() != item["sha256"]: raise ValueError("Input changed while building the catalog")
    unchanged()
    output.mkdir(parents=True, exist_ok=False); (output / "entries").mkdir()
    for relative, data in entries:
        with (output / relative).open("xb") as stream: stream.write(data)
    unchanged()
    temporary = output / "manifest-writing.json"
    with temporary.open("xb") as stream: stream.write(encoded(manifest))
    os.replace(temporary, output / "manifest.json")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/frontier-v6c-staged.json")
    parser.add_argument("--dossiers", type=Path, default=ROOT / "data/frontier-v6d-dossiers.json")
    parser.add_argument("--sessions", type=Path, default=ROOT / "data/frontier-v6f-sessions.json")
    parser.add_argument("--responses", nargs="+", type=Path, required=True)
    parser.add_argument("--requests", nargs="*", type=Path, default=[])
    parser.add_argument("--requests-complete", action="store_true")
    parser.add_argument("--run-closed", action="store_true", help="Only after run closure; requires complete request journals")
    parser.add_argument("--freeze", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results/catalog-v6")
    args = parser.parse_args()
    result = build_catalog(args.corpus, args.dossiers, args.sessions, args.responses, args.output,
                           request_paths=args.requests, requests_complete=args.requests_complete, run_closed=args.run_closed, freeze_paths=args.freeze)
    print(json.dumps({"scheduled_catalog_slots": result["scheduled_catalog_slots"], "status_counts": result["status_counts"], "output": str(args.output)}, indent=2))


if __name__ == "__main__": main()
