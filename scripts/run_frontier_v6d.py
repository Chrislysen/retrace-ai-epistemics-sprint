"""Offline plan by default. Explicit execution requires frozen file hashes.

Credential is read from a hidden terminal prompt or one transient stdin line;
never pass a key as an argument or persist it to this workspace.
"""
import argparse
import asyncio
import getpass
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.adaption_v6d import AiohttpTransport, BASELINE, BASELINE_LEDGER, BASELINE_SHA256, MODEL_PRICING, RollingLedger, plan, require, run_slots


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integrity(authorization, models):
    require(authorization["cumulative_cap_credits"] == "250", "authorization_cap_mismatch")
    require(authorization["historical_conservative_carry_credits"] == BASELINE, "authorization_carry_mismatch")
    require(authorization["prior_ledger_path"] == BASELINE_LEDGER
            and authorization["prior_ledger_sha256"] == BASELINE_SHA256, "authorization_prior_ledger_mismatch")
    protected = authorization["protected"]
    for relative, expected in protected.items():
        path = (ROOT / relative).resolve()
        require(path.is_relative_to(ROOT), "invalid_protected_path")
        require(sha(path) == expected, "protected_artifact_changed")
    records = {r["id"]: r for r in models["models"]}
    require(models["http_status"] == 200, "model_availability_unverified")
    for model, pricing in MODEL_PRICING.items():
        require(model in records, "model_not_available")
        require(records[model]["max_input_tokens"] <= pricing["context"], "model_input_bound_changed")
        require(records[model]["max_output_tokens"] >= 16384, "model_output_bound_too_small")
    return len(protected)


def verify_freeze(freeze_path, expected_hash, sessions_path):
    require(expected_hash == sha(freeze_path), "freeze_hash_mismatch")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    entries = freeze.get("files")
    require(isinstance(entries, list) and bool(entries), "invalid_freeze_entries")
    seen = set()
    for entry in entries:
        require(isinstance(entry, dict) and {"path", "sha256"} <= set(entry), "invalid_freeze_entry")
        target = (ROOT / entry["path"]).resolve()
        require(target.is_relative_to(ROOT) and target not in seen, "invalid_freeze_path")
        require(sha(target) == entry["sha256"], "frozen_dependency_changed")
        seen.add(target)
    required = {sessions_path, Path(__file__).resolve(), ROOT / "retrace/adaption_v6d.py",
                ROOT / "data/frontier-v6d-authorization.json", ROOT / "data/frontier-v6c-model-availability.json",
                ROOT / BASELINE_LEDGER}
    require(required <= seen, "required_runtime_file_not_frozen")
    return len(seen)


async def execute(args, slots):
    authorization_path = ROOT / "data/frontier-v6d-authorization.json"
    model_path = ROOT / "data/frontier-v6c-model-availability.json"
    verify_freeze(Path(args.freeze).resolve(), args.freeze_sha256, Path(args.sessions).resolve())
    require(args.model_interval >= 3.1 and args.global_interval >= 3.1, "live_pacing_below_verified_policy")
    require(args.authorization_sha256 == sha(authorization_path), "authorization_hash_mismatch")
    require(args.models_sha256 == sha(model_path), "models_hash_mismatch")
    integrity(json.loads(authorization_path.read_text(encoding="utf-8")), json.loads(model_path.read_text(encoding="utf-8")))
    if not args.canary:
        require(args.canary_summary and args.canary_summary_sha256, "missing_completed_canary")
        canary_path = Path(args.canary_summary).resolve()
        require(sha(canary_path) == args.canary_summary_sha256, "canary_summary_hash_mismatch")
        canary = json.loads(canary_path.read_text(encoding="utf-8"))
        require(canary.get("schema") == "retrace.adaption-v6d-summary.v1" and canary.get("stream") is True
                and canary.get("canary") is True and canary.get("status") == "completed"
                and all(canary.get(k) == 10 for k in ("planned", "issued", "completed", "responses"))
                and canary.get("models") == {m: 2 for m in MODEL_PRICING}, "canary_not_complete")
    output, ledger_path = Path(args.output).resolve(), Path(args.ledger).resolve()
    require(output.is_relative_to(ROOT / "results") and ledger_path.is_relative_to(ROOT / "results"), "output_outside_results")
    require(ledger_path == (ROOT / "results/frontier-v6d/budget").resolve(), "noncanonical_phase_ledger")
    api_key = sys.stdin.readline().strip() if args.key_stdin else getpass.getpass("Adaption key (hidden): ")
    ledger = RollingLedger(ledger_path, baseline_path=ROOT / BASELINE_LEDGER)
    try:
        async with AiohttpTransport(api_key, args.timeout) as transport:
            return await run_slots(slots, api_key=api_key, output_dir=output, ledger=ledger, transport=transport,
                                   canary=args.canary, model_interval=args.model_interval, global_interval=args.global_interval,
                                   concurrency=args.concurrency, timeout_seconds=args.timeout)
    finally:
        ledger.close()
        api_key = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", required=True)
    parser.add_argument("--sessions-sha256")
    parser.add_argument("--authorization-sha256")
    parser.add_argument("--models-sha256")
    parser.add_argument("--freeze")
    parser.add_argument("--freeze-sha256")
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--canary-summary")
    parser.add_argument("--canary-summary-sha256")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--key-stdin", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--ledger")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--model-interval", type=float, default=3.1)
    parser.add_argument("--global-interval", type=float, default=3.1)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    path = Path(args.sessions).resolve()
    slots = json.loads(path.read_text(encoding="utf-8"))
    prepared = plan(slots, canary=args.canary)
    if not args.execute:
        print(json.dumps(prepared, indent=2))
        return
    require(args.sessions_sha256 == sha(path), "sessions_hash_mismatch")
    require(all((args.output, args.ledger, args.authorization_sha256, args.models_sha256, args.freeze, args.freeze_sha256)), "missing_execution_parameters")
    print(json.dumps(asyncio.run(execute(args, slots)), indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print exception text/arguments that might contain input or keys.
        print(json.dumps({"status": "aborted", "error_type": type(exc).__name__, "details": "See durable local journals; no retry was made."}))
        sys.exit(1)
