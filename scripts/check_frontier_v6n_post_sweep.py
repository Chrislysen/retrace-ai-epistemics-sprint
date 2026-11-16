"""Offline software checks after authenticated n closure; never model inference.

The workbench has no incremental evaluation kernel. This checks its successive
normalized session states against clean state reconstruction and direct tiered
evaluation. It makes no speedup, source-entailment or model-performance claim.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import sys
import tokenize

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = "results/frontier-v6n/post-sweep"
AUDIT = "results/frontier-v6n/continuation/runtime-audit.json"
FREEZE = "data/frontier-v6n-freeze.json"
SNAPSHOT = "data/frontier-v6n-ledger-after-continuation.jsonl"
SELF = "scripts/check_frontier_v6n_post_sweep.py"
TEST = "tests/test_frontier_v6n_post_sweep.py"
ALLOWED_ALIASES = {
    "results/frontier-v6f/budget/active.lock": "provenance/frozen-locks/results/frontier-v6f/budget/active.lock.txt",
    "results/frontier-v6k/budget/active.lock": "provenance/frozen-locks/results/frontier-v6k/budget/active.lock.txt",
    "results/frontier-v6m/budget/active.lock": "provenance/frozen-locks/results/frontier-v6m/budget/active.lock.txt",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def normalized(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def binding(data):
    return {"sha256": sha256(data).hexdigest(), "bytes": len(data)}


def file_binding(path):
    digest = sha256()
    length = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            length += len(block)
    return {"sha256": digest.hexdigest(), "bytes": length}


def relative(name):
    require(isinstance(name, str) and "\\" not in name and ":" not in name, "Canonical relative path required")
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts and str(path) not in ("", "."), "Bounded relative path required")
    return path


def process_alive(pid):
    require(type(pid) is int and pid > 0, "Recorded worker PID required")
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, 0, pid)
        if handle:
            kernel.CloseHandle(handle)
            return True
        require(ctypes.get_last_error() == 87, "Cannot establish worker absence")
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def empty_state():
    return {"answers": {}, "revoked_documents": [], "revoked_passages": [], "scenario_withdrawals": []}


def transition(previous, action):
    """An explicit UI-style edit to the previous normalized state, no engine cache."""
    result = deepcopy(previous)
    field, identifier, value = action
    if field == "answers":
        require(value is None or type(value) is bool, "Boolean or Unknown clarification")
        result[field][identifier] = value
    else:
        require(field in ("revoked_documents", "revoked_passages", "scenario_withdrawals") and type(value) is bool,
                "Explicit typed veto action required")
        if value and identifier not in result[field]:
            result[field].append(identifier)
        if not value:
            result[field] = [item for item in result[field] if item != identifier]
    return result


def fresh_state(actions):
    """Rebuild from last assignments, independently of prior normalized outputs."""
    final = {}
    for field, identifier, value in actions:
        final[field, identifier] = value
    result = empty_state()
    for (field, identifier), value in sorted(final.items()):
        if field == "answers":
            result[field][identifier] = value
        elif value:
            result[field].append(identifier)
    return result


def event_sequence_checks():
    from retrace.workbench_v6h import analyze_workbench, demo_brief
    from retrace.tiered_v6h import family_supervaluation

    brief = demo_brief()
    original = deepcopy(brief)
    initial = analyze_workbench(brief)
    digest = initial["declaration_fingerprint"]
    compiled = initial["compilation"]
    sequence = [
        ("revoked_documents", "demo-source-1", True),
        ("revoked_passages", "A", True),
        ("scenario_withdrawals", "B", True),
        ("revoked_documents", "demo-source-1", False),
        ("answers", "polarity", True),
        ("answers", "polarity", None),
        ("scenario_withdrawals", "B", False),
        ("revoked_passages", "A", False),
        ("scenario_withdrawals", "A", True),
        ("scenario_withdrawals", "B", True),
        ("scenario_withdrawals", "C", True),
        ("answers", "route", True),
        ("answers", "route", False),
        ("answers", "route", None),
        ("scenario_withdrawals", "A", False),
        ("scenario_withdrawals", "B", False),
        ("scenario_withdrawals", "C", False),
    ]
    previous = initial
    rows = []
    true_options = {row["choice_id"]: row["true_option"] for row in brief["clarifications"]}
    groups = {row["id"]: row["evidence_ids"] for row in brief["documents"]}
    for number, action in enumerate(sequence, 1):
        session_input = transition(previous["state"], action)
        clean_input = fresh_state(sequence[:number])
        snapshot = deepcopy((brief, session_input, clean_input))
        actual = analyze_workbench(brief, session_input, digest)
        clean = analyze_workbench(deepcopy(original), clean_input, digest)
        require(normalized(actual) == normalized(clean), "Session replay differs from clean state reconstruction")
        require((brief, session_input, clean_input) == snapshot, "Analysis mutated caller inputs")
        kept = [row for row in compiled["candidates"] if all(value is None or
                (row["assignment"][key] == true_options[key]) == value
                for key, value in clean_input["answers"].items())]
        document_records = sorted({eid for name in clean_input["revoked_documents"] for eid in groups[name]})
        direct = family_supervaluation([deepcopy(row["graph"]) for row in kept],
            document_vetoes=document_records, passage_vetoes=clean_input["revoked_passages"],
            scenario_withdrawals=clean_input["scenario_withdrawals"])
        require(normalized(actual["family"]) == normalized(direct), "Wrapper/direct tiered evaluation differs")
        require(actual["candidate_ids"] == [row["id"] for row in kept], "Clarification filtering differs")
        require(all(not row["effective_active"] for row in actual["record_flags"]["Z"]["by_candidate"].values()),
                "An originally ineligible record was activated by restoring a veto")
        if number == 4:
            require(actual["record_flags"]["A"]["passage_veto"] and not actual["record_flags"]["A"]["document_veto"]
                    and actual["record_flags"]["B"]["scenario_veto"], "Veto channels leaked during document restoration")
        rows.append({"step": number, "action": {"field": action[0], "id": action[1], "value": action[2]},
                     "state": actual["state"], "candidate_count": len(kept),
                     "decision_states": {key: row["state"] for key, row in actual["decisions"].items()},
                     "session_equals_fresh": True, "wrapper_equals_direct": True})
        previous = actual
    require(brief == original, "Source declaration mutated")
    require(normalized(previous["family"]) == normalized(initial["family"]), "Full restoration failed to return the original family state")
    changed = deepcopy(brief)
    changed["title"] += " (edited)"
    try:
        analyze_workbench(changed, previous["state"], digest)
    except ValueError as error:
        require("changed" in str(error), "Unexpected stale-declaration rejection")
    else:
        raise ValueError("Changed source accepted stale session state")
    return {"passed": True, "kind": "event_sequence_vs_fresh", "incremental_kernel_present": False,
            "constructed_only": True, "steps": rows, "stale_declaration_rejected": True,
            "scope": "One explicit constructed workbench sequence; same frozen semantic kernel, independently rebuilt state and direct wrapper cross-check. No incremental-algorithm or performance comparison; no empirical model claim."}


def syntax_checks(source_bytes):
    files = []
    whitespace = []
    for name, data in sorted(source_bytes.items()):
        if not name.endswith(".py"):
            continue
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        text = data.decode(encoding)
        ast.parse(text, filename=name)
        files.append(name)
        lines = [number for number, line in enumerate(text.splitlines(), 1) if line.rstrip(" \t") != line]
        if lines:
            whitespace.append({"path": name, "trailing_whitespace_lines": lines})
    return {"passed": True, "python_ast_files": files, "python_ast_file_count": len(files),
            "trailing_whitespace": whitespace, "whitespace_is_informational": True,
            "scope": "Python parsing and trailing whitespace inventory only; no Ruff, type checker, code execution or semantic lint certification."}


def run(root, freeze_sha256, runtime_audit_sha256, *, frozen_aliases=None):
    """Compute only after an exact saved closed audit reproduces; no output writes."""
    root = Path(root).resolve()
    aliases = frozen_aliases or {}
    require(isinstance(aliases, dict) and all(ALLOWED_ALIASES.get(k) == v for k, v in aliases.items()), "Only exact inert historical-lock aliases")
    bindings = {}
    python_sources = {}
    def capture(name, keep=False):
        target = root / relative(aliases.get(name, name))
        require(target.resolve().is_relative_to(root), "Source escaped workspace")
        current = file_binding(target)
        if name in bindings:
            require(current == bindings[name], "Input changed during checks: " + name)
        bindings[name] = current
        if keep or name.endswith(".py"):
            data = target.read_bytes()
            require(binding(data) == current, "Input changed while reading: " + name)
            if name.endswith(".py"):
                python_sources[name] = data
            return data
        return current
    require(not (root / "results/frontier-v6n/budget/active.lock").exists(), "Recovery is still active")
    host = json.loads(capture("results/frontier-v6n/host-guard.json", True))
    require(not process_alive(host["pid"]), "Worker PID still exists; wait for actual exit")
    freeze_bytes = capture(FREEZE, True)
    require(binding(freeze_bytes)["sha256"] == freeze_sha256, "Exact recovery freeze required")
    freeze = json.loads(freeze_bytes)
    require(freeze.get("schema") == "retrace.frontier-v6n-freeze.v1", "Recovery freeze schema")
    for row in freeze["files"]:
        capture(row["path"])
        require(bindings[row["path"]]["sha256"] == row["sha256"], "Frozen file changed: " + row["path"])
    audit_bytes = capture(AUDIT, True)
    require(binding(audit_bytes)["sha256"] == runtime_audit_sha256, "Saved runtime audit hash")
    saved = json.loads(audit_bytes)
    require(saved.get("passed") is True and saved.get("final_closed") is True
            and saved.get("schedule_status") in ("completed", "stopped"), "Authenticated closed recovery required")
    capture(SELF); capture(TEST); capture(SNAPSHOT)
    from scripts.audit_frontier_v6n_runtime import audit
    replay = audit(root, freeze_sha256, frozen_aliases=aliases, ledger_snapshot=SNAPSHOT)
    require(normalized(replay) == saved, "Saved independent runtime audit did not reproduce")
    for name, expected in saved["input_bindings"].items():
        capture(name)
        require(bindings[name] == expected, "Audited source binding changed: " + name)
    syntax = syntax_checks(python_sources)
    from retrace.benchmark import generate_cases, run_benchmarks
    cases = generate_cases(seed=1729, count=120)
    baselines = run_benchmarks(cases)
    require(baselines["kind"] == "deterministic_synthetic_rule_baselines"
            and baselines["policies"]["oracle"]["exact_match_rate"] == 1, "Authored rule-baseline invariant failed")
    events = event_sequence_checks()
    for name in list(bindings):
        capture(name)
    require(not (root / "results/frontier-v6n/budget/active.lock").exists() and not process_alive(host["pid"]), "Worker became active")
    return {"schema": "retrace.frontier-v6n-post-sweep-plan.v1", "source_bindings": dict(sorted(bindings.items())),
            "frozen_aliases": aliases, "source_freeze_sha256": freeze_sha256, "runtime_audit_sha256": runtime_audit_sha256,
            "runtime_schedule_status": saved["schedule_status"], "frozen_files_checked": len(freeze["files"]),
            "syntax_checks": syntax, "cases": cases, "baselines": baselines, "event_sequence_vs_fresh": events}


def publish(root, plan):
    root = Path(root).resolve()
    require(plan.get("schema") == "retrace.frontier-v6n-post-sweep-plan.v1", "Validated check plan required")
    def recheck():
        for name, expected in plan["source_bindings"].items():
            path = root / relative(plan["frozen_aliases"].get(name, name))
            require(path.resolve().is_relative_to(root) and file_binding(path) == expected, "Source changed before/after publication: " + name)
        require(not (root / "results/frontier-v6n/budget/active.lock").exists(), "Recovery active at publication")
        host_path = root / "results/frontier-v6n/host-guard.json"
        if host_path.exists():
            require(not process_alive(json.loads(host_path.read_bytes())["pid"]), "Worker PID exists at publication")
    destination = root / OUTPUT
    require(not destination.exists(), "Exclusive new post-sweep directory required")
    recheck()
    outputs = {"rule-baseline-cases.json": plan["cases"], "rule-baselines.json": plan["baselines"],
               "event-sequence-vs-fresh.json": plan["event_sequence_vs_fresh"]}
    files = {OUTPUT + "/" + name: binding(encoded(value)) for name, value in outputs.items()}
    receipt = {"schema": "retrace.frontier-v6n-post-sweep-checks.v1", "passed": True,
               "created_at": datetime.now(timezone.utc).isoformat(), "provider_calls": 0,
               "network_used": False, "servers_started": False, "model_experiment": False,
               "source_bindings": plan["source_bindings"], "files": files,
               "source_freeze_sha256": plan["source_freeze_sha256"], "runtime_audit_sha256": plan["runtime_audit_sha256"],
               "runtime_schedule_status": plan["runtime_schedule_status"],
               "frozen_integrity": {"passed": True, "files_checked": plan["frozen_files_checked"]},
               "syntax_checks": plan["syntax_checks"],
               "zero_call_baselines": {"kind": plan["baselines"]["kind"], "cases": len(plan["cases"]),
                   "scope": "Legacy authored synthetic rule policies, not model or human performance."},
               "event_sequence_vs_fresh": {k: v for k, v in plan["event_sequence_vs_fresh"].items() if k != "steps"},
               "event_steps_checked": len(plan["event_sequence_vs_fresh"]["steps"]),
               "scope": "Post-sweep software checks outside the 21 scientific comparisons. No new inference, evidence repair, empirical regrading or claim of an incremental kernel."}
    destination.mkdir(parents=True, exist_ok=False)
    for name, value in outputs.items():
        with (destination / name).open("xb") as stream:
            stream.write(encoded(value))
    for name, expected in files.items():
        require(file_binding(root / name) == expected, "New check artifact changed during publication")
    recheck()
    with (destination / "checks.json").open("xb") as stream:
        stream.write(encoded(receipt))
    recheck()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--runtime-audit-sha256", required=True)
    parser.add_argument("--aliases", type=Path)
    args = parser.parse_args()
    aliases = json.loads(args.aliases.read_bytes()) if args.aliases else None
    plan = run(args.root, args.freeze_sha256, args.runtime_audit_sha256, frozen_aliases=aliases)
    result = publish(args.root, plan)
    print(json.dumps({"passed": result["passed"], "receipt": OUTPUT + "/checks.json", "event_steps_checked": result["event_steps_checked"]}))


if __name__ == "__main__":
    main()
