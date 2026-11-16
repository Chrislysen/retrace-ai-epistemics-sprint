"""Audit the separately frozen eight-request eligibility study and score once."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.eligibility_v5_eval import score_responses
from scripts.summarize_ambiguity_v4 import digest, journal, provider_text, read, require, unique


def audit_run(root, execution_path, freeze_path):
    execution, frozen = read(execution_path), read(freeze_path)
    preservation = read(root / "data/eligibility-v5-preservation.json")
    for path, expected in {**preservation["protected"], **preservation["all_prior_results"]}.items():
        require(digest(root / path) == expected, "Prior immutable evidence changed: " + path)
    required_files = {"retrace/eligibility_v5_eval.py", "scripts/summarize_eligibility_v5.py", "tests/test_eligibility_v5_eval.py",
                      "data/eligibility-v5-paired-staged.json", "data/eligibility-v5-paired-sessions.json",
                      "data/eligibility-v5-execution.json", "retrace/compact_v5.py"}
    require(required_files <= {item["path"] for item in frozen["files"]}, "Freeze omits primary extraction/scoring dependencies")
    for item in frozen["files"]:
        require(digest(root / item["path"]) == item["sha256"], "Frozen study dependency changed: " + item["path"])
    require(execution["status"] == "authorized_once" and execution["planned_requests"] == 8
            and execution["model"] == "gemma-4-31b-it" and execution["max_output_tokens"] == 4096
            and execution["concurrency"] == 1 and execution["retries"] == 0, "Wrong authorized study settings")
    require(Decimal(execution["reserved_credits"]) == Decimal("0.19546112")
            and Decimal(execution["prior_conservative_credits"]) == Decimal("40.79280112")
            and Decimal(execution["cumulative_conservative_credits"]) == Decimal("40.98826224")
            and Decimal(execution["cumulative_conservative_credits"]) < Decimal(execution["approved_cap_credits"]),
            "Prospective reservation arithmetic differs from the frozen protocol")
    session_path = root / "data/eligibility-v5-paired-sessions.json"
    sessions = read(session_path)
    require(digest(session_path) == execution["sessions_file_sha256"], "Frozen session file changed")
    require(hashlib.sha256(json.dumps(sessions, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            == execution["sessions_json_sha256"], "Frozen provider session serialization changed")
    require(digest(root / "scripts/run_adaption.mjs") == execution["runner_sha256"], "Frozen runner changed")
    folder = root / execution["output_directory"]
    run, summary = read(folder / "run.json"), read(folder / "summary.json")
    requests, responses = journal(folder / "requests.jsonl"), journal(folder / "responses.jsonl")
    start = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
    require(start > datetime.fromisoformat(frozen["created_at"])
            and start > datetime.fromisoformat(execution["created_at"]), "Run predates prospective study freeze or authorization")
    require(run["sessions_sha256"] == execution["sessions_json_sha256"] and run["model"] == execution["model"], "Wrong model or session set")
    require(run["planned_requests"] == summary["planned_requests"] == 8
            and run["reserve_nanocredits_per_request"] == execution["reserve_nanocredits_per_request"] == 24432640
            and run["run_id"] == summary["run_id"] and summary["status"] in ("completed", "halted")
            and len(requests) == len(responses) == summary["issued_requests"] == summary["recorded_responses"]
            and summary["unissued_requests"] == 8 - len(requests), "Journal accounting mismatch")
    require(Decimal(str(summary["max_reserved_credits"])) == Decimal(execution["reserved_credits"]), "Run reservation mismatch")
    expected = {(session["case_id"], session["condition"]): session for session in sessions}
    require(len(sessions) == len(expected) == 8, "Wrong frozen session count or repeated session")
    by_number, seen_pairs = {}, set()
    for request in requests:
        number, pair = request["request_number"], (request["case_id"], request["condition"])
        require(number not in by_number and pair in expected and pair not in seen_pairs, "Unexpected or repeated issued request")
        by_number[number] = request
        seen_pairs.add(pair)
        session = expected[pair]
        body = {"model": execution["model"], "instructions": session["instructions"],
                "input": [{"role": "user", "content": session["steps"][0]["input"]}],
                "max_output_tokens": 4096, "temperature": 0, "store": False,
                "agentic_memory": False, "tools": [], "tool_choice": "none"}
        require(request["request"] == body and request["phase"] == "final" and request["run_id"] == run["run_id"], "Provider payload differs from frozen public session")
        require(hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                == request["request_sha256"], "Provider request digest mismatch")
    require(sorted(by_number) == list(range(1, len(requests) + 1)), "Missing request ordinal")
    seen = set()
    for response in responses:
        number = response["request_number"]
        require(number in by_number and number not in seen, "Unexpected response ordinal")
        seen.add(number)
        request = by_number[number]
        require(all(response[key] == request[key] for key in ("run_id", "case_id", "condition", "phase", "request", "request_sha256")), "Response identity differs from issued request")
        if not response.get("error"):
            raw = json.loads(response["raw_response"], object_pairs_hook=unique)
            require(response["http_status"] == 200 and response["response_status"] == raw["status"] == "completed", "Incomplete response marked successful")
            require(provider_text(raw) == response["output_text"], "Scoring text differs from original provider text")
    total = sum(len([line for line in path.read_bytes().splitlines() if line.strip()]) for path in (root / "results").rglob("requests.jsonl"))
    require(preservation["previous_request_count"] == 495 and total == 495 + len(requests), "Unexpected requests beyond this authorized eight-slot study")
    return responses, {
        "execution_sha256": digest(execution_path), "freeze_sha256": digest(freeze_path),
        "run_status": summary["status"], "prior_evidence_unchanged": True, "primary_scorer_predates_run": True,
        "issued_requests": len(requests), "unissued_requests": 8 - len(requests),
        "raw_files_sha256": {name: digest(folder / name) for name in ("requests.jsonl", "responses.jsonl", "run.json", "summary.json")},
        "fresh_reserved_credits": execution["reserved_credits"],
        "cumulative_conservative_credits": execution["cumulative_conservative_credits"],
        "observed_token_cost_credits_uncached": summary["observed_token_cost_credits_uncached"],
        "actual_billed_credits": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution", default="data/eligibility-v5-execution.json")
    parser.add_argument("--freeze", default="data/eligibility-v5-freeze.json")
    parser.add_argument("--output", default="results/eligibility-v5-summary.json")
    args = parser.parse_args()
    destination = ROOT / args.output
    require(not destination.exists(), "Refusing to overwrite an earlier result")
    responses, integrity = audit_run(ROOT, ROOT / args.execution, ROOT / args.freeze)
    scored = score_responses(read(ROOT / "data/eligibility-v5-paired-staged.json"), responses)
    result = {**scored, "generated_at": datetime.now(timezone.utc).isoformat(), "integrity": integrity}
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(destination), "aggregates": result["aggregates"], "pairs": result["pairs"]}, indent=2))


if __name__ == "__main__":
    main()
