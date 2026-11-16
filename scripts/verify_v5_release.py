"""Read-only offline release verification. Never invoke experiment entry points.

Default: hashes, saved journals, frozen-session replay, ledger arithmetic, and
pure in-memory scoring. --tests also uses temporary fixtures and loopback HTTP;
it never sends model requests or overwrites released artifacts.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FREEZES = ["data/prose-freeze.json", "data/extraction-v2-freeze.json", "data/ambiguity-v3-freeze.json",
           "data/ambiguity-v4-freeze.json", "data/eligibility-v5-freeze.json"]
PRESERVATIONS = ["data/ambiguity-v4-cycle-preservation.json", "data/eligibility-v5-preservation.json"]
SESSION_FILES = ["data/pilot-sessions.json", "data/prose-sessions.json", "data/prose-continuation-gemma.json",
                 "data/extraction-v2-sessions.json", "data/ambiguity-v3-sessions.json",
                 "data/ambiguity-v4-sessions.json", "data/eligibility-v5-paired-sessions.json"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Nonfinite JSON constant")


def path(name):
    target = (ROOT / name).resolve()
    require(target.is_relative_to(ROOT), "Manifest path escapes the release root")
    return target


def read(name):
    return json.loads(path(name).read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=reject_constant)


def digest(name):
    return hashlib.sha256(path(name).read_bytes()).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def canonical_json(value):
    return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))


def compare(actual, expected, label):
    require(canonical_json(actual) == expected, label + " differs from the preserved result")


def journal(name):
    data = path(name).read_bytes()
    require(not data or data.endswith(b"\n"), "Unterminated journal: " + name)
    return [json.loads(line, object_pairs_hook=unique, parse_constant=reject_constant)
            for line in data.decode("utf-8").splitlines() if line.strip()]


def verify_hash(name, expected, inventory=None):
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
            "Invalid hash declaration: " + name)
    require(digest(name) == expected, "Hash mismatch: " + name)
    if inventory is not None:
        require(name not in inventory or inventory[name] == expected, "Conflicting preserved hash: " + name)
        inventory[name] = expected


def verify_manifest(name, inventory):
    document = read(name)
    files = document.get("files")
    require(isinstance(files, list) and files, "Manifest has no file inventory: " + name)
    require(len({item["path"] for item in files}) == len(files), "Repeated manifest path: " + name)
    for item in files:
        verify_hash(item["path"], item["sha256"], inventory)
    return {"path": name, "files": len(files), "sha256": digest(name)}


def verify_extraction_amendment():
    current = read("data/extraction-v2-freeze.json")
    original = read("data/extraction-v2-freeze-original.json")
    amendments = current.get("amendments", [])
    require(len(amendments) == 1, "Unexpected extraction-v2 amendment count")
    change = amendments[0]
    verify_hash(change["original_freeze"], change["original_freeze_sha256"])
    prior = {item["path"]: item["sha256"] for item in original["files"]}
    revised = {item["path"]: item["sha256"] for item in current["files"]}
    differences = {name for name in set(prior) | set(revised) if prior.get(name) != revised.get(name)}
    require(differences == {"tests/test_intervention_audit.py"} == {change["path"]},
            "Extraction-v2 amendment changed more than the disclosed test")
    require(prior[change["path"]] == change["original_sha256"] and revised[change["path"]] == change["amended_sha256"],
            "Extraction-v2 amendment hash record mismatch")
    verify_hash("research/extraction-v2-frozen-intervention-test.txt", change["original_sha256"])
    return {"test_only_amendment_verified": True, "runtime_and_scorer_unchanged": True}


def provider_text(body):
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    return "".join(part["text"] for message in body.get("output", [])
                   if message.get("type") == "message" and message.get("role") == "assistant"
                   for part in message.get("content", [])
                   if part.get("type") == "output_text" and isinstance(part.get("text"), str))


def session_lookup():
    manifests = {}
    for name in SESSION_FILES:
        document = read(name)
        sessions = document.get("sessions") if isinstance(document, dict) else document
        signature = hashlib.sha256(compact(sessions).encode("utf-8")).hexdigest()
        manifests[signature] = (name, sessions, document.get("instructions") if isinstance(document, dict) else None)
        if name == "data/pilot-sessions.json":
            # The historical dispatcher added the public decision-ID registry,
            # which affects the session hash but adds no reference answers.
            registry = {case["id"]: [d["id"] for d in case["decisions"]] for case in read("data/pilot-cases.json")}
            submitted = [{**session, "decision_ids": registry[session["case_id"]]} for session in sessions]
            submitted_hash = hashlib.sha256(compact(submitted).encode("utf-8")).hexdigest()
            manifests[submitted_hash] = (name + " + public decision IDs from data/pilot-cases.json", submitted, document["instructions"])
    return manifests


def verify_journals(inventory):
    manifests = session_lookup()
    requests_total = responses_total = grounded = raw_bodies = unknown_usage = 0
    reserved_nanocredits = 0
    known_usage = Decimal(0)
    run_ids = set()
    runs = []
    paths = sorted((ROOT / "results").rglob("requests.jsonl"))
    require(paths, "No released request journals")
    for request_path in paths:
        folder = request_path.parent.relative_to(ROOT).as_posix()
        request_name, response_name = folder + "/requests.jsonl", folder + "/responses.jsonl"
        require(request_name in inventory and response_name in inventory,
                "Journal is not covered by the preservation/release hashes: " + folder)
        requests, responses = journal(request_name), journal(response_name)
        run = read(folder + "/run.json")
        require(run["run_id"] not in run_ids, "Duplicate run ID")
        run_ids.add(run["run_id"])
        require(len(requests) == len(responses), "Request/response count mismatch: " + folder)
        by_number = {q["request_number"]: q for q in requests}
        require(len(by_number) == len(requests) and sorted(by_number) == list(range(1, len(requests) + 1)),
                "Request ordinals are missing or repeated: " + folder)
        require(len({(q["session_index"], q["step_index"]) for q in requests}) == len(requests),
                "Repeated session step within a run: " + folder)
        by_step, seen_responses = {}, set()
        for response in responses:
            number = response["request_number"]
            require(number in by_number and number not in seen_responses, "Unexpected response ordinal: " + folder)
            seen_responses.add(number)
            request = by_number[number]
            for key in ("run_id", "model", "case_id", "condition", "phase", "session_index", "step_index", "request", "request_sha256"):
                require(response[key] == request[key], "Request/response identity mismatch: " + folder)
            by_step[(response["session_index"], response["step_index"])] = response
            raw = response.get("raw_response")
            require(not response.get("raw_response_redacted"), "Unexpected redacted live provider body: " + folder)
            if raw is None:
                require(bool(response.get("error")), "Missing successful provider body: " + folder)
            else:
                require(isinstance(raw, str), "Provider body is not retained text: " + folder)
                raw_bodies += 1
                try:
                    body = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
                except (ValueError, RuntimeError):
                    require(bool(response.get("error")), "Malformed successful provider response: " + folder)
                else:
                    if not response.get("error") or response.get("response_status") in ("completed", "incomplete"):
                        # The frozen runner deliberately excludes incomplete/error text
                        # from scoring while retaining the original HTTP body intact.
                        expected_text = "" if response.get("error") else provider_text(body)
                        require(isinstance(body, dict) and expected_text == response["output_text"],
                                "Stored output text differs from provider body: " + folder)
                        require(body.get("status") == response.get("response_status"), "Provider status mismatch: " + folder)
                        require(body.get("model") == response.get("response_model"), "Provider model alias mismatch: " + folder)
                        require(body.get("usage") == response.get("usage"), "Provider usage mismatch: " + folder)
            usage = response.get("usage") or {}
            if all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens")):
                known_usage += (Decimal(usage["input_tokens"]) * Decimal(str(run["pricing"]["input"]))
                                + Decimal(usage["output_tokens"]) * Decimal(str(run["pricing"]["output"]))) / 1000000
            else:
                unknown_usage += 1
        manifest = manifests.get(run["sessions_sha256"])
        for request in requests:
            body = request["request"]
            require(request["run_id"] == run["run_id"] and body["model"] == request["model"] == run["model"],
                    "Requested model/run mismatch: " + folder)
            require(hashlib.sha256(compact(body).encode("utf-8")).hexdigest() == request["request_sha256"],
                    "Serialized request-body hash mismatch: " + folder)
            if manifest is not None:
                source, sessions, instructions = manifest
                session = sessions[request["session_index"]]
                step = session["steps"][request["step_index"]]
                require((request["case_id"], request["condition"], request["phase"]) ==
                        (session["case_id"], session["condition"], step["phase"]), "Request differs from frozen session identity: " + folder)
                expected_input = []
                for i in range(request["step_index"] + 1):
                    expected_input.append({"role": "user", "content": session["steps"][i]["input"]})
                    if i < request["step_index"]:
                        previous = by_step.get((request["session_index"], i))
                        require(previous is not None, "Missing assistant history step: " + folder)
                        expected_input.append({"role": "assistant", "content": previous["output_text"]})
                require(body["input"] == expected_input and body["instructions"] == session.get("instructions", instructions),
                        "Provider input/instructions differ from saved session or actual assistant history: " + folder)
                grounded += 1
        if path(folder + "/summary.json").exists():
            summary = read(folder + "/summary.json")
            require(summary["issued_requests"] == len(requests) and summary["recorded_responses"] == len(responses),
                    "Run summary count mismatch: " + folder)
        reserved_nanocredits += len(requests) * run["reserve_nanocredits_per_request"]
        requests_total += len(requests)
        responses_total += len(responses)
        runs.append({"folder": folder, "requests": len(requests), "responses": len(responses),
                     "session_manifest": manifest[0] if manifest else "historical smoke: journal hashes only"})
    require(requests_total == responses_total == 503, "Release must contain exactly 503 issued requests and responses")
    require(grounded == 500, "Unexpected count of session-grounded requests (three historical smoke calls excluded)")
    return {"requests": requests_total, "responses": responses_total, "runs": runs,
            "session_and_actual_history_verified_requests": grounded, "historical_smoke_calls": requests_total - grounded,
            "raw_provider_bodies_retained": raw_bodies, "unknown_usage_attempts": unknown_usage,
            "issued_full_context_bound_credits": str(Decimal(reserved_nanocredits) / 1000000000),
            "known_usage_uncached_estimate_credits": str(known_usage)}


def verify_budget(accounting):
    ledger = read("results/eligibility-v5-budget-final.json")
    previous = read("results/ambiguity-v4-budget-final.json")
    earlier = read("results/ambiguity-v3-budget-final.json")
    verify_hash("results/ambiguity-v4-budget-final.json", ledger["previous_ledger_sha256"])
    verify_hash("results/ambiguity-v3-budget-final.json", previous["previous_ledger_sha256"])
    verify_hash("results/eligibility-v5-summary.json", ledger["summary_sha256"])
    verify_hash("results/ambiguity-v4-summary.json", previous["summary_sha256"])
    total = Decimal(ledger["current_conservative_reserved_credits"])
    require(total == Decimal("40.98826224") == Decimal(accounting["issued_full_context_bound_credits"]),
            "Full-context issued reservation arithmetic mismatch")
    require(total == Decimal(previous["current_conservative_reserved_credits"]) + Decimal("0.19546112"), "Eight-slot budget addition mismatch")
    require(Decimal(previous["current_conservative_reserved_credits"]) == Decimal(earlier["current_conservative_reserved_credits"]) + Decimal("0.24432640"),
            "Ten-slot budget addition mismatch")
    require(Decimal(ledger["approved_cap_credits"]) == 50 and total < 50
            and Decimal(ledger["remaining_credits"]) == 50 - total, "Budget cap or remainder mismatch")
    require(ledger["total_issued_requests"] == accounting["requests"]
            and ledger["historical_unknown_usage_attempts"] == accounting["unknown_usage_attempts"] == 2,
            "Ledger issued/unknown-usage counts mismatch")
    require(Decimal(ledger["cumulative_known_usage_estimate_credits"]) == Decimal(accounting["known_usage_uncached_estimate_credits"]),
            "Known token-cost estimate mismatch")
    require(ledger["actual_billed_credits"] is None, "Do not substitute an estimate for observed billing")
    return {"conservative_reserved_credits": str(total), "cap_credits": "50", "remaining_credits": str(50 - total),
            "actual_billed_credits": None, "known_usage_estimate_credits": accounting["known_usage_uncached_estimate_credits"]}


def reproduce_scores():
    from retrace.ambiguity_v4_eval import score_responses as score_v4, evaluate_compilation, _aggregate
    from retrace.compact_v5 import compile_ambiguity
    from retrace.eligibility_v5_eval import score_responses as score_fresh
    from scripts.summarize_eligibility_v5 import audit_run as audit_fresh
    # Only the latest read-only audit has the authorized global 503-call scope.
    # Never call the earlier v4 audit_run, which intentionally retains its old count.
    fresh_responses, fresh_integrity = audit_fresh(ROOT, path("data/eligibility-v5-execution.json"), path("data/eligibility-v5-freeze.json"))
    packets = read("data/ambiguity-v3-staged.json")
    raw = journal("results/ambiguity-v4/gemma-4-31b-it/responses.jsonl")
    stored_v4 = read("results/ambiguity-v4-summary.json")
    recalculated_v4 = score_v4(packets, raw, read("results/ambiguity-v3-summary.json"))
    compare(recalculated_v4, {k: v for k, v in stored_v4.items() if k not in ("generated_at", "integrity")}, "Frozen v4 primary score")
    original = {row["case_id"]: row for row in recalculated_v4["outcomes"]}
    replay = read("results/ambiguity-v5-posthoc-replay.json")
    for name, signature in replay["input_hashes"].items():
        verify_hash(name, signature)
    rows = []
    for packet in packets:
        cid, old = packet["public"]["id"], original[packet["public"]["id"]]
        raw_text = old.get("raw_row_audit", {}).get("output_text")
        row = {"case_id": cid, "primary_v4_status": old["status"], "received": old["received"],
               "provider_completed": old["provider_completed"], "strict_bare": False, "status": "unissued_or_missing",
               "original_output_text": raw_text,
               "original_output_sha256": hashlib.sha256(raw_text.encode()).hexdigest() if isinstance(raw_text, str) else None}
        if old["provider_completed"]:
            try:
                compiled = compile_ambiguity(raw_text, packet["public"]["registry"])
            except (ValueError, TypeError) as exc:
                row.update(status="syntax_or_branch_failure", error=str(exc))
            else:
                row.update(status="admitted", strict_bare=compiled["strict_bare"], compilation=compiled,
                           evaluation=evaluate_compilation(packet, compiled))
        elif old["received"]:
            row["status"] = "operational_failure"
        rows.append(row)
    compare(rows, replay["outcomes"], "V5 post-hoc row/compiled-family/evaluation replay")
    compare(_aggregate(rows, packets), replay["aggregates"], "V5 post-hoc aggregates")
    require(replay["new_model_calls"] == 0 and replay["fresh_evaluation"] is False
            and replay["primary_v4_results_replaced"] is False, "Post-hoc replay mislabeled")
    fresh = read("results/eligibility-v5-summary.json")
    calculated_fresh = score_fresh(read("data/eligibility-v5-paired-staged.json"), fresh_responses)
    compare(calculated_fresh, {k: v for k, v in fresh.items() if k not in ("generated_at", "integrity")}, "Prospective eight-packet scores")
    compare(fresh_integrity, fresh["integrity"], "Fresh execution integrity record")
    return {"v4_primary": stored_v4["aggregates"], "v5_posthoc": replay["aggregates"], "fresh_v5": fresh["aggregates"]}


def verify_catalog():
    catalog = read("results/retrace-v5-catalog.json")
    rows = catalog["briefs"]
    require(len(rows) == len({b["id"] for b in rows}) == 20, "Release catalog must have twenty unique entries")
    counts = Counter()
    fresh = {r["case_id"]: r for r in read("results/eligibility-v5-summary.json")["outcomes"]}
    prior = {r["id"]: r for r in read("results/ambiguity-v5-live-briefs.json")["briefs"]}
    for brief in rows:
        kinds = [key for key in ("fresh_confirmation", "post_hoc_replay", "reference_comparison") if brief.get(key)]
        require(len(kinds) == 1, "Catalog provenance class missing or ambiguous")
        counts[kinds[0]] += 1
        if kinds[0] == "fresh_confirmation":
            score = fresh[brief["id"]]
            compare(brief["candidates"], score["compilation"]["candidates"], "Fresh catalog candidates")
            require(brief["compact_v5"] == score["raw_row_audit"]["output_text"], "Fresh catalog replaces raw model text")
        else:
            compare(brief, prior[brief["id"]], "Preserved replay/reference catalog entry")
    require(counts == {"fresh_confirmation": 8, "post_hoc_replay": 10, "reference_comparison": 2}, "Catalog provenance counts changed")
    return dict(counts)


def verify_supplemental_audit():
    """Compare the retained independent implementation's report; never execute its writer."""
    audit = read("results/eligibility-v5-independent-audit.json")
    primary = read("results/eligibility-v5-summary.json")
    verify_hash("results/eligibility-v5-summary.json", audit["summary_sha256"])
    verify_hash("data/eligibility-v5-freeze.json", audit["freeze_sha256"])
    verify_hash("results/eligibility-v5/gemma-4-31b-it/responses.jsonl", audit["raw_response_sha256"])
    outcomes = {row["case_id"]: row for row in primary["outcomes"]}
    require(len(audit["casefacts"]) == len(outcomes) == 8, "Supplemental audit case count mismatch")
    require(len({row["case_id"] for row in audit["casefacts"]}) == 8, "Supplemental audit duplicate case")
    for fact in audit["casefacts"]:
        row = outcomes[fact["case_id"]]
        current = row["evaluation"]["current"]
        compare(fact["vectors"], current["candidate_decision_vectors"], "Independent decision-vector comparison")
        require(fact["branches"] == len(row["compilation"]["candidates"]), "Independent branch count mismatch")
        require(fact["request_number"] == row["raw_row_audit"]["request_number"], "Independent request identity mismatch")
        require(fact["questions_requested"] == current["clarification"]["requested_count"], "Independent question-count mismatch")
        compare(sorted(fact["retained_after_oracle"]), sorted(current["clarification"]["retained_candidate_ids"]),
                "Independent retained-candidate comparison")
        compare(sorted(fact["disputed"]), sorted(k for k, v in current["agreement"]["states"].items() if v == "needs_review"),
                "Independent disagreement comparison")
    agg = primary["aggregates"]
    expected = {"admitted": agg["admitted"], "exact_families": agg["exact_family_recovery_cases"],
                "invariant_pairs": agg["specification_invariant_pairs"], "branches": agg["assignment_branches"],
                "cases_with_disagreement": agg["cases_with_current_disagreement"],
                "requested_question_cases": agg["planner_requested_case_count"],
                "requested_questions_total": sum(f["questions_requested"] for f in audit["casefacts"]),
                "answered_decisions": agg["selective"]["answered_decisions"],
                "wrong_answered_decisions": agg["selective"]["wrong_answered_decisions"]}
    compare(audit["summary"], expected, "Independent summary comparison")
    require(audit["global_requests"] == 503 and audit["request_count"] == 8, "Independent accounting mismatch")
    require(Decimal(audit["cumulative_reservation_credits"]) == Decimal("40.98826224"), "Independent budget mismatch")
    return {"report": "results/eligibility-v5-independent-audit.json", "reported_checks": audit["checks_passed"],
            "case_results_compared": 8, "report_writer_executed": False,
            "scope": "Computationally independent implementation; same author as corpus/scorer, not blind human review."}


def optional_tests():
    commands = [("python", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"]),
                ("node", ["node", "--test", "--test-reporter=tap", "tests/test_runner.mjs"]),
                ("javascript_syntax", ["node", "--check", "web/v5/app.js"])]
    outcomes = {}
    for name, command in commands:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        require(completed.returncode == 0, name + " checks failed: " + (completed.stderr or completed.stdout)[-1600:])
        combined = completed.stdout + completed.stderr
        if name == "python":
            matched = re.search(r"Ran (\d+) tests?", combined)
            require(matched is not None, "Python test count not reported")
            outcomes[name] = {"passed": True, "tests": int(matched.group(1))}
        elif name == "node":
            matched = re.search(r"# tests (\d+)", combined)
            require(matched is not None and int(matched.group(1)) == 13, "Expected thirteen mocked runner tests")
            outcomes[name] = {"passed": True, "tests": 13}
        else:
            outcomes[name] = {"passed": True}
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", action="store_true", help="Also run offline tests; temporary fixtures and loopback servers only")
    args = parser.parse_args()
    result = {"schema": "retrace.v5-release-verification.v1", "status": "checking",
              "model_calls": 0, "writes_release_artifacts": False}
    inventory = {}
    try:
        result["study_freezes"] = [verify_manifest(name, inventory) for name in FREEZES]
        result["v4_scorer_checkpoint"] = verify_manifest("data/ambiguity-v4-scorer-checkpoint.json", inventory)
        result["extraction_v2_amendment"] = verify_extraction_amendment()
        result["cycle_preservations"] = []
        for name in PRESERVATIONS:
            manifest = read(name)
            for filename, expected in {**manifest["protected"], **manifest["all_prior_results"]}.items():
                verify_hash(filename, expected, inventory)
            result["cycle_preservations"].append({"path": name, "protected": len(manifest["protected"]),
                                                  "prior_results": len(manifest["all_prior_results"]),
                                                  "previous_request_count": manifest["previous_request_count"]})
        for version, folder in (("ambiguity-v4", "results/ambiguity-v4/gemma-4-31b-it"),
                                ("eligibility-v5", "results/eligibility-v5/gemma-4-31b-it")):
            ledger = read(f"results/{version}-budget-final.json")
            for filename, expected in ledger["raw_files_sha256"].items():
                verify_hash(folder + "/" + filename, expected, inventory)
        result["release_freezes"] = []
        for name in ("data/v5-release-freeze.json", "data/release-v5-freeze.json"):
            if path(name).exists():
                result["release_freezes"].append(verify_manifest(name, inventory))
        if not result["release_freezes"]:
            result["release_freeze_note"] = "Not present: study freezes verified; final packaging manifest not yet available."
        result["accounting"] = verify_journals(inventory)
        result["budget"] = verify_budget(result["accounting"])
        result["scores"] = reproduce_scores()
        result["catalog"] = verify_catalog()
        result["supplemental_audit"] = verify_supplemental_audit()
        if args.tests:
            before = {name: digest(name) for name in inventory}
            result["tests"] = optional_tests()
            require(all(digest(name) == expected for name, expected in before.items()), "Tests changed a preserved release artifact")
        else:
            result["tests"] = "not requested; use --tests"
        result["preserved_files_verified"] = len(inventory)
        result["status"] = "passed"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = type(exc).__name__ + ": " + str(exc)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
