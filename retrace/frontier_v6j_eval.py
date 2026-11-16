"""Lossless, explicitly amended closure over interrupted i + unissued-only j.

No source row is normalized, repaired or reclassified. The frozen scientific
evaluator is reused with an isolated closure predicate; its module is unchanged.
"""
from copy import deepcopy
from hashlib import sha256
import json
from types import FunctionType

from . import frontier_v6i_eval as frozen
from .adaption_v6h import digest

SCHEMA = "retrace.frontier-v6j-composite-evaluation.v1"
ROUTE = {"qwen3.5-397b": "qwen3.5-397b-a17b-nvfp4"}


def require(ok, why):
    if not ok: raise ValueError(why)


def _strict(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, "duplicate JSON key")
            out[k] = v
        return out
    def bad(_): raise ValueError("nonfinite JSON")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def json_value(value):
    return _strict(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _rows(raw, path):
    require(isinstance(raw, bytes) and (not raw or raw.endswith(b"\n")), "complete source JSONL bytes required")
    file_sha = sha256(raw).hexdigest(); rows = []; pointers = []
    for n, line in enumerate(raw.splitlines(keepends=True), 1):
        require(bool(line.strip()), "blank source JSONL row")
        row = _strict(line)
        require(isinstance(row, dict), "source row must be an object")
        rows.append(row)
        pointers.append({"source_path": path, "source_line_one_based": n,
                         "source_file_sha256": file_sha, "source_line_sha256": sha256(line).hexdigest(),
                         "row_sha256": digest(row)})
    return rows, pointers


def assemble_views(slots, receipt, original, continuation):
    """Segments contain paths, raw JSONL bytes and an unchanged raw summary.

    Required keys: paths{requests,responses,outcomes,summary,run_manifest},
    requests/responses/outcomes/summary_bytes/manifest_bytes as bytes, summary
    and manifest as dicts. This function does not authenticate files;
    the CLI and independent segment auditors do so before complete inference.
    """
    require(receipt["schema"] == "retrace.frontier-v6j-continuation.v1", "continuation receipt schema")
    require(len(slots) == 1800 and receipt["full_planned_slots"] == 1800 and receipt["carried_issued_slots"] == 6 and receipt["continuation_slots"] == 1794, "fixed amended cohort")
    require(receipt["sessions_sha256"] == digest(slots) and receipt["observed_response_models"] == ROUTE, "unchanged cohort and exact future route policy")
    index = {s["slot_id"]: s for s in slots}
    require(len(index) == 1800, "unique original slots")
    carried = receipt["permanently_excluded_issued_slot_ids"]
    pending = receipt["continuation_slot_ids"]
    require(len(set(carried)) == 6 and set(carried) <= set(index), "six permanently excluded issued slots")
    require(pending == [s["slot_id"] for s in slots if s["slot_id"] not in carried], "ordered1794-slot complement")
    values = {}; sources = {}; bindings = {}
    for name, segment in (("original", original), ("continuation", continuation)):
        values[name] = {}; sources[name] = {}
        prefix = "results/frontier-v6i/primary/" if name == "original" else "results/frontier-v6j/continuation/"
        expected_paths = {"requests": prefix+"requests.jsonl", "responses": prefix+"responses.jsonl", "outcomes": prefix+"slot-outcomes.jsonl", "summary": prefix+"summary.json", "run_manifest": prefix+"run.json"}
        require(segment["paths"] == expected_paths, "exact canonical segment role paths required")
        require(segment["manifest"]["run_id"] == segment["summary"]["run_id"], "segment manifest/summary run identity")
        for key in ("requests", "responses", "outcomes"):
            path = segment["paths"][key]
            require(isinstance(path, str) and not path.startswith(("/", "\\")) and ":" not in path and ".." not in path.replace("\\", "/").split("/"), "relative segment provenance path")
            rows, pointers = _rows(segment[key], path)
            values[name][key] = rows; sources[name][key] = pointers
            bindings[path] = {"sha256": sha256(segment[key]).hexdigest(), "bytes": len(segment[key])}
            if name == "original": require(receipt["prior_journal_files"].get(path) == bindings[path]["sha256"], "original journal changed")
        values[name]["summary"] = deepcopy(segment["summary"])
        for key, raw_key, value_key in (("summary", "summary_bytes", "summary"), ("run_manifest", "manifest_bytes", "manifest")):
            raw = segment[raw_key]; path = segment["paths"][key]
            require(isinstance(raw, bytes) and _strict(raw) == segment[value_key], "exact raw segment metadata required")
            bindings[path] = {"sha256": sha256(raw).hexdigest(), "bytes": len(raw)}
            if name == "original": require(receipt["prior_journal_files"].get(path) == bindings[path]["sha256"], "original metadata changed")
    a, b = values["original"], values["continuation"]
    require(a["summary"]["run_id"] != b["summary"]["run_id"], "segments require distinct run IDs")
    for segment in (a, b):
        require(all(r.get("run_id") == segment["summary"]["run_id"] for r in segment["responses"]+segment["outcomes"]), "source rows bind their segment run identity")
    require(a["summary"]["schema"] == "retrace.adaption-v6i-summary.v1" and a["summary"]["status"] == "stopped" and a["summary"]["stop_reasons"] == ["response_model_mismatch"], "only the pinned original interruption is authorized")
    require(a["summary"]["run_id"] == receipt["original_run_id"] and a["summary"]["issued_attempts"] == 6 and a["summary"]["retries"] == 0, "original six attempts unchanged")
    af = {r["slot_id"]: r for r in a["outcomes"]}
    require(len(a["outcomes"]) == len(af) == 1800 and set(af) == set(index), "original1800 final records preserved")
    require({r["slot_id"] for r in a["outcomes"] if r["issued"]} == set(carried), "issued carry set exact")
    require(len(a["requests"]) == len(a["responses"]) == 6 and {r["slot_id"] for r in a["requests"]} == set(carried) and {r["slot_id"] for r in a["responses"]} == set(carried), "no original issued attempt omitted")
    for sid in pending:
        require(af[sid]["issued"] is False and af[sid]["model_outcome"] == "not_issued_global_stop" and af[sid]["attempts_issued"] == 0, "continuation only replaces unissued placeholders")
    pointers = {row["slot_id"]: p for row, p in zip(a["outcomes"], sources["original"]["outcomes"])}
    require({r["slot_id"] for r in receipt["carryover_rows"]} == set(carried), "carryover receipt pointers")
    for ref in receipt["carryover_rows"]:
        sid = ref["slot_id"]
        require(all(ref[k] == pointers[sid][k] for k in ("source_path", "source_line_one_based", "row_sha256")), "original carryover line/hash unchanged")
        require(ref["attempt_id"] == af[sid]["attempt_id"] and ref["model_outcome"] == af[sid]["model_outcome"], "carryover identity/outcome unchanged")
    failures = [r for r in a["responses"] if r.get("failure_scope") == "global"]
    require(len(failures) == 1 and failures[0]["error"] == "response_model_mismatch" and failures[0]["model"] == "qwen3.5-397b" and failures[0]["terminal_valid"] is False, "original global Qwen failure must remain failed")
    require(failures[0]["attempt_id"] == receipt["route_evidence"]["original_attempt_id"] and digest(failures[0]) == receipt["route_evidence"]["original_response_row_sha256"], "route evidence cannot be rescored or normalized")
    bf = {r["slot_id"]: r for r in b["outcomes"]}
    require(len(b["outcomes"]) == len(bf) == 1794 and set(bf) == set(pending), "complete1794 continuation final outcomes")
    require(all(r["slot_id"] in pending for r in b["requests"]+b["responses"]), "carried slot must never be reissued")
    require(not {r["attempt_id"] for r in a["requests"]} & {r["attempt_id"] for r in b["requests"]}, "attempt IDs cannot cross segments")
    for sid in receipt["failed_producer_descendant_slot_ids"]:
        require(sid in bf and bf[sid]["issued"] is False and bf[sid]["model_outcome"] == "not_issued_dependency_failed", "failed original producer cannot feed history")
    for r in b["responses"]:
        expected = ROUTE.get(r["model"], r["model"])
        require(r.get("requested_model") == r["model"], "future requested model binding")
        if r["terminal_valid"]: require(r.get("returned_model") == expected, "future exact observed route binding")
    merged_outcomes = [af[s["slot_id"]] if s["slot_id"] in carried else bf[s["slot_id"]] for s in slots]
    merged_requests = a["requests"] + b["requests"]; merged_responses = a["responses"] + b["responses"]
    # Frozen journal validation is retained, including actual-output bodies and
    # failed dependencies. It permits the original declared global failure.
    frozen.records(slots, merged_outcomes, merged_responses, merged_requests)
    by_cont = {row["slot_id"]: p for row, p in zip(b["outcomes"], sources["continuation"]["outcomes"])}
    provenance = {
        "outcomes": [{"slot_id": s["slot_id"], "segment": "original" if s["slot_id"] in carried else "continuation", **(pointers[s["slot_id"]] if s["slot_id"] in carried else by_cont[s["slot_id"]])} for s in slots],
        "requests": [{"attempt_id": r["attempt_id"], "segment": name, **p} for name in ("original", "continuation") for r, p in zip(values[name]["requests"], sources[name]["requests"])],
        "responses": [{"attempt_id": r["attempt_id"], "segment": name, **p} for name in ("original", "continuation") for r, p in zip(values[name]["responses"], sources[name]["responses"])],
    }
    return {"outcomes": merged_outcomes, "requests": merged_requests, "responses": merged_responses,
            "source_provenance": provenance, "source_bindings": bindings,
            "original_summary": a["summary"], "continuation_summary": b["summary"],
            "unissued_original_placeholders_not_in_composite": pending,
            "source_rows_changed": False}


def validate_segment_proofs(merged, receipt, audits):
    require(set(audits) == {"original", "continuation"}, "both independent segment audits required")
    for name, audit in audits.items():
        require(audit.get("passed") is True and audit.get("final_closed") is True and audit.get("all_scheduled_outcomes_accounted") is True, "closed accounted segment proof required")
        require(audit["schedule_status"] == ("stopped" if name == "original" else "completed"), "continuation global stop cannot become amended completion")
        expected = 1800 if name == "original" else 1794
        require(audit["counts"]["planned"] == expected, "segment audit denominator")
        prefix = "results/frontier-v6i/primary/" if name == "original" else "results/frontier-v6j/continuation/"
        for key, binding in merged["source_bindings"].items():
            if key.startswith(prefix): require(audit["input_bindings"].get(key) == binding, "segment proof binds different source bytes")
    require(audits["original"]["cumulative_accounted_credits"] == receipt["historical_conservative_carry_credits"] == "47.653269434", "no original reservation released")
    require(audits["continuation"]["historical_carry_credits"] == receipt["historical_conservative_carry_credits"], "continuation carry mismatch")
    b = merged["continuation_summary"]
    require(b["schema"] == "retrace.adaption-v6j-summary.v1" and b["status"] == "completed" and b["stop_reasons"] == [] and b["planned"] == 1794 and b["original_planned"] == 1800 and b["carried_over_slots"] == 6, "explicit segmented closure summary")
    require(b["issued_without_outcome_attempt_ids"] == [] and b["all_scheduled_outcomes_recorded"] is True, "continuation has no orphan/missing final")
    require(not any(r.get("failure_scope") == "global" for r in merged["responses"] if r["run_id"] == b["run_id"]), "new global failure cannot be waived")


def evaluate_composite(corpus, dossiers, study, slots, receipt, original, continuation, segment_audits):
    """Full frozen21-test computation under one explicit authenticated closure.

    Callers must independently replay and compare both saved runtime audits.
    The pure API binds their returned source hashes again before inference.
    """
    merged = assemble_views(slots, receipt, original, continuation)
    validate_segment_proofs(merged, receipt, segment_audits)
    counts = {"planned": 1800, "issued_attempts": len(merged["requests"]),
              "slot_outcomes": 1800, "carried_issued_slots": 6, "continuation_slots": 1794}
    operational = {"schema": "retrace.frontier-v6j-derived-closure.v1", "status": "closed_under_prospective_amendment", **counts,
                   "original_segment": deepcopy(merged["original_summary"]),
                   "continuation_segment": deepcopy(merged["continuation_summary"]),
                   "scope": "Derived segmented closure, not a rewritten original runtime summary. Original global failure remains a failed endpoint."}
    expected = {"slots": digest(slots), "finals": digest(merged["outcomes"]), "attempts": digest(merged["responses"]), "requests": digest(merged["requests"]), "summary": digest(operational)}
    def amended_closed(summary, selected_slots, finals, attempts, requests):
        actual = {"slots": digest(selected_slots), "finals": digest(list(finals.values())), "attempts": digest(attempts), "requests": digest(requests), "summary": digest(summary)}
        require(actual == expected, "closure override is bound to exact audited merged records")
        return True
    # No monkeypatch: one function object receives a separate global dictionary.
    # Its bytecode, semantic helpers, subset definitions and statistics are frozen.
    scope = dict(frozen.evaluate.__globals__)
    scope["closed_summary"] = amended_closed
    run = FunctionType(frozen.evaluate.__code__, scope, "evaluate_authenticated_v6j", frozen.evaluate.__defaults__, frozen.evaluate.__closure__)
    run.__kwdefaults__ = deepcopy(frozen.evaluate.__kwdefaults__)
    result = run(corpus, dossiers, study, slots, merged["outcomes"], merged["responses"], merged["requests"], operational, 10000, require_full_design=True)
    summary = result["summary"]
    require(summary["status"] == "complete_primary" and summary["primary_holm_family_size"] == 21, "frozen scientific computation completed")
    summary["schema"] = SCHEMA; summary["status"] = "complete_amended_primary"
    for row in summary["paired_comparisons"]:
        if row["status"] == "complete_primary": row["status"] = "complete_amended_primary"
    summary["amendment"] = {"receipt_sha256_canonical": digest(receipt), "original_study_status": "interrupted",
        "original_global_failure_preserved": True, "source_rows_changed": False, "carried_issued_slots": 6,
        "continuation_planned_slots": 1794, "observed_response_models": deepcopy(ROUTE),
        "vendor_alias_mapping_documented": False, "weight_identity_verified": False,
        "resource_estimate_scope": "Frozen resource summaries may estimate usage cost at requested-ID rates even for rejected responses. These are not accepted settlements or actual billing; the original failed route keeps its full reserved bound, and the observed route does not establish price or weight equivalence.",
        "closure_override": "Only closed_summary in an isolated FunctionType globals copy; frozen evaluator module and source records unchanged.",
        "scope": "A prospectively frozen transport/observed-route amendment after six issued observations. Do not label the original v6i run complete or the observed route precision-equivalent."}
    summary["segment_runtime_audits"] = deepcopy(segment_audits)
    summary["source_bindings"] = deepcopy(merged["source_bindings"])
    result["merged_evidence"] = merged
    return result
