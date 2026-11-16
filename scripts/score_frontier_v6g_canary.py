"""All-scheduled v6g contract diagnostic; no retries or old-study rescoring."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.frontier_v6c_io import parse_object, family_score
from retrace.source_ir_v6d import compile_cited_ir, model_source
from scripts.build_frontier_v6g_canary import source_cases, expected_family, supplied_candidates, CASE_ID, MODELS


def binding_check(compiled):
    bindings = {b["id"]: b for b in compiled["bindings"]}
    return any(p["kind"] == "origin" and p["target"] == "N63" and
               any(bindings[b]["entity"] == "L61" and bindings[b]["mention"]["document_id"] == "duplicate-note"
                   for b in p["bindings"]) for p in compiled["propositions"])


def valid_usage(record):
    usage = record.get("usage")
    return (isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0 for key in ("input_tokens", "output_tokens"))
            and ("total_tokens" not in usage or type(usage["total_tokens"]) is int and usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]))


def evaluate(slots, records, *, require_binding=True):
    documents, registry = source_cases(); source = model_source(documents, registry)
    planned = {}; identities = set()
    for slot in slots:
        sid = slot["slot_id"]; identity = slot["model"], slot["condition"]
        if sid in planned or identity in identities or slot["case_id"] != CASE_ID or slot["phase"] != "probe": raise ValueError("Invalid planned canary identity")
        expected = {**source, **({"supplied_candidates": supplied_candidates()} if slot["condition"] == "canary_adversarial_refuter" else {})}
        if json.loads(slot["input"]) != expected: raise ValueError("Canary input differs from reviewed public source")
        planned[sid] = slot; identities.add(identity)
    if identities != {(model, condition) for model in MODELS for condition in ("canary_source_ir", "canary_adversarial_refuter")}:
        raise ValueError("Canary needs exactly five models by two IR formats")
    rows = {}
    for record in records:
        sid = record["slot_id"]
        if sid in rows or sid not in planned: raise ValueError("Duplicate or unexpected result")
        rows[sid] = record
    results = []
    for slot in slots:
        record = rows.get(slot["slot_id"])
        result = {key: slot[key] for key in ("slot_id", "model", "condition")}
        result.update(passed=False, exact_family=False, explicit_master_binding=False, inventory_complete=False, strict_bare_json=False)
        if record is None: result["failure"] = "unissued_or_unreceived"
        elif any(record.get(key) != slot[key] for key in ("model", "case_id", "condition", "phase")): result["failure"] = "response_identity_mismatch"
        elif record.get("error") or record.get("http_status") != 200 or record.get("response_status") != "completed" or record.get("terminal_valid") is not True or not valid_usage(record):
            result["failure"] = "provider_transport_or_truncation_failure"
        else:
            try:
                parsed, strict = parse_object(record["output_text"]); result["strict_bare_json"] = strict
                if parsed == {"status": "no_counter_reading"}:
                    result["failure"] = "abstention_on_deficient_supplied_family"
                else:
                    compiled = compile_cited_ir(parsed, documents, registry)
                    score = family_score(compiled["candidates"], expected_family())
                    complete = all(row["status"] != "absent_from_ir" for row in compiled["registry_disposition"])
                    bound = binding_check(compiled)
                    result.update(exact_family=score["exact_family"], explicit_master_binding=bound, inventory_complete=complete,
                                  assignment_count=compiled["assignment_count"], candidate_count=compiled["candidate_count"], family_score=score,
                                  binding_count=len(compiled["bindings"]), proposition_count=len(compiled["propositions"]),
                                  passed=compiled["status"] == "compiled" and score["exact_family"] and complete and (bound or not require_binding))
                    if not result["passed"]: result["failure"] = "family_inventory_or_binding_mismatch"
            except (ValueError, TypeError, KeyError, RecursionError) as exc:
                result["failure"] = f"{type(exc).__name__}: {exc}"
        if record:
            for key in ("usage", "latency_ms", "response_status", "http_status", "model_outcome"):
                result[key] = record.get(key)
        results.append(result)
    return {"schema": "retrace.frontier-v6g-canary-score.v1", "planned": 10, "received": len(records),
            "passed_slots": sum(row["passed"] for row in results), "passed": all(row["passed"] for row in results),
            "binding_required_for_pass": require_binding, "results": results,
            "scope": "Prospective format/contract feasibility diagnostic targeted to a disclosed prior prompt defect. One new fictional source, two admitted worlds, ten scheduled calls. Deficient refuter seeds require full-family recovery; abstention fails here. No fresh-population generalization, causal isolation, output repair, favorable retry selection or pooled prior-canary success rate."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, default=ROOT / "data/frontier-v6g-canary-sessions.json")
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = {"sessions": args.sessions.read_bytes(), "responses": args.responses.read_bytes()}
    def load(raw):
        def unique(items):
            out = {}
            for key, value in items:
                if key in out: raise ValueError("Duplicate JSON field")
                out[key] = value
            return out
        def invalid(_): raise ValueError("Nonfinite JSON value")
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    result = evaluate(load(files["sessions"]), [load(line) for line in files["responses"].splitlines() if line.strip()])
    result["inputs_sha256"] = {key: hashlib.sha256(value).hexdigest() for key, value in files.items()}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2); stream.write("\n")
    print(json.dumps({key: result[key] for key in ("planned", "received", "passed_slots", "passed")}, indent=2))


if __name__ == "__main__": main()
