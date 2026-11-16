"""Audit the separately authorized v4 execution, then write a new result once."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.ambiguity_v4_eval import score_responses


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def read(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def journal(path):
    raw = path.read_bytes()
    require(not raw or raw.endswith(b"\n"), "Incomplete journal line: " + str(path))
    return [json.loads(line, object_pairs_hook=unique) for line in raw.decode("utf-8").splitlines() if line.strip()]


def provider_text(raw):
    if isinstance(raw.get("output_text"), str):
        return raw["output_text"]
    return "".join(part["text"] for entry in raw.get("output", [])
                   if entry.get("type") == "message" and entry.get("role") == "assistant"
                   for part in entry.get("content", [])
                   if part.get("type") == "output_text" and isinstance(part.get("text"), str))


def audit_run(root, execution_path, checkpoint_path):
    execution = read(execution_path)
    checkpoint = read(checkpoint_path)
    preservation = read(root / "data/ambiguity-v4-cycle-preservation.json")
    for name, expected in {**preservation["protected"], **preservation["all_prior_results"]}.items():
        require(digest(root / name) == expected, "Prior frozen evidence changed: " + name)
    required_scorer = {"retrace/ambiguity_v4_eval.py", "scripts/summarize_ambiguity_v4.py", "tests/test_ambiguity_v4_eval.py"}
    require({item["path"] for item in checkpoint["files"]} == required_scorer, "Scorer checkpoint does not cover the complete primary scorer")
    require(checkpoint["tests"]["exit_code"] == 0 and checkpoint["prospective_to_v4_calls"], "Scorer preflight did not pass prospectively")
    for item in checkpoint["files"]:
        require(digest(root / item["path"]) == item["sha256"], "Primary scorer changed after checkpoint: " + item["path"])
    for path, field in (("data/ambiguity-v4-config.json", "config_sha256"),
                        ("data/ambiguity-v4-freeze.json", "offline_freeze_sha256"),
                        ("data/ambiguity-v4-sessions.json", "sessions_file_sha256"),
                        ("scripts/run_adaption.mjs", "runner_sha256")):
        require(digest(root / path) == execution[field], "Authorized execution dependency changed: " + path)
    sessions = read(root / "data/ambiguity-v4-sessions.json")
    require(hashlib.sha256(json.dumps(sessions, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            == execution["sessions_json_sha256"], "Frozen session serialization changed")
    require(execution["status"] == "authorized_once" and execution["planned_requests"] == 10
            and execution["retries"] == 0 and execution["concurrency"] == 1, "Wrong authorized run settings")
    folder = root / execution["output_directory"]
    run, summary = read(folder / "run.json"), read(folder / "summary.json")
    requests, responses = journal(folder / "requests.jsonl"), journal(folder / "responses.jsonl")
    start = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
    require(start > datetime.fromisoformat(checkpoint["created_at"])
            and start > datetime.fromisoformat(execution["created_at"]), "Run predates prospective scorer checkpoint or authorization")
    require(run["sessions_sha256"] == execution["sessions_json_sha256"] and run["model"] == execution["model"], "Wrong model or frozen sessions")
    require(run["planned_requests"] == summary["planned_requests"] == 10
            and run["reserve_nanocredits_per_request"] == execution["reserve_nanocredits_per_request"] == 24432640
            and run["run_id"] == summary["run_id"] and summary["status"] in ("completed", "halted")
            and len(requests) == len(responses) == summary["issued_requests"] == summary["recorded_responses"]
            and summary["unissued_requests"] == 10 - len(requests), "Run accounting mismatch")
    require(Decimal(str(summary["max_reserved_credits"])) == Decimal(execution["reserved_credits"]), "Reservation bound mismatch")
    expected_sessions = {(s["case_id"], s["condition"]): s for s in sessions}
    by_number, pairs = {}, set()
    for request in requests:
        number, pair = request["request_number"], (request["case_id"], request["condition"])
        require(number not in by_number and pair in expected_sessions and pair not in pairs, "Unexpected or repeated request")
        by_number[number] = request
        pairs.add(pair)
        session = expected_sessions[pair]
        body = {"model": execution["model"], "instructions": session["instructions"],
                "input": [{"role": "user", "content": session["steps"][0]["input"]}],
                "max_output_tokens": 4096, "temperature": 0, "store": False,
                "agentic_memory": False, "tools": [], "tool_choice": "none"}
        require(request["request"] == body and request["phase"] == "final" and request["run_id"] == run["run_id"], "Provider payload differs from frozen public session")
        require(hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                == request["request_sha256"], "Request digest mismatch")
    require(sorted(by_number) == list(range(1, len(requests) + 1)), "Missing request ordinal")
    seen = set()
    for response in responses:
        number = response["request_number"]
        require(number not in seen and number in by_number, "Unexpected response ordinal")
        seen.add(number)
        request = by_number[number]
        require(all(response[key] == request[key] for key in ("run_id", "case_id", "condition", "phase", "request", "request_sha256")), "Response identity differs from issued request")
        if not response.get("error"):
            raw = json.loads(response["raw_response"], object_pairs_hook=unique)
            require(response["http_status"] == 200 and response["response_status"] == raw["status"] == "completed", "Incomplete response marked successful")
            require(provider_text(raw) == response["output_text"], "Scoring text differs from raw provider text")
    total_requests = sum(len([line for line in path.read_bytes().splitlines() if line.strip()])
                         for path in (root / "results").rglob("requests.jsonl"))
    require(total_requests == preservation["previous_request_count"] + len(requests), "Unexpected calls outside the separately authorized run")
    return responses, {"execution": execution, "checkpoint_sha256": digest(checkpoint_path),
                       "execution_sha256": digest(execution_path), "run_status": summary["status"],
                       "prior_evidence_unchanged": True, "scorer_predates_run": True,
                       "raw_files_sha256": {name: digest(folder / name) for name in ("requests.jsonl", "responses.jsonl", "run.json", "summary.json")},
                       "issued_requests": len(requests), "provider_responses": len(responses),
                       "observed_token_cost_credits_uncached": summary["observed_token_cost_credits_uncached"],
                       "actual_billed_credits": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution", default="data/ambiguity-v4-execution.json")
    parser.add_argument("--checkpoint", default="data/ambiguity-v4-scorer-checkpoint.json")
    parser.add_argument("--output", default="results/ambiguity-v4-summary.json")
    args = parser.parse_args()
    destination = ROOT / args.output
    require(not destination.exists(), "Refusing to overwrite any prior summary")
    responses, integrity = audit_run(ROOT, ROOT / args.execution, ROOT / args.checkpoint)
    packets = read(ROOT / "data/ambiguity-v3-staged.json")
    baseline = read(ROOT / "results/ambiguity-v3-summary.json")
    scored = score_responses(packets, responses, baseline)
    result = {**scored, "generated_at": datetime.now(timezone.utc).isoformat(), "integrity": integrity}
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(destination), "aggregates": result["aggregates"],
                      "primary_subset": result["post_hoc_primary_subset"]}, indent=2))


if __name__ == "__main__":
    main()
