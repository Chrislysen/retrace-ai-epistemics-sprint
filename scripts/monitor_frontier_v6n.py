"""Provisional, metadata-only n monitoring. No writes, provider calls or actions.

Reads only newly completed journal lines, projects away all generated content,
and reports operational indications. This is not a runtime or scientific audit.
"""
import argparse
from collections import Counter, defaultdict
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.status_frontier_v6k import strict, projection, finite
from scripts.status_frontier_v6l import accounting


class PrefixReader:
    def __init__(self, path, role):
        self.path, self.role = path, role
        self.offset = 0
        self.rows = []
        self.identity = None

    def read(self):
        if not self.path.exists():
            if self.offset:
                raise ValueError("Previously observed journal disappeared")
            return self.rows
        with self.path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            identity = stat.st_dev, stat.st_ino
            if self.identity is not None and self.identity != identity:
                raise ValueError("Journal identity changed")
            self.identity = identity
            if stat.st_size < self.offset:
                raise ValueError("Journal shrank")
            stream.seek(self.offset)
            remaining = stat.st_size - self.offset
            while remaining:
                raw = stream.readline(remaining)
                remaining -= len(raw)
                if not raw.endswith(b"\n"):
                    break
                if not raw.strip():
                    raise ValueError("Blank completed journal line")
                value = strict(raw)
                if not isinstance(value, dict):
                    raise ValueError("Journal object required")
                self.rows.append(projection(self.role, value))
                self.offset += len(raw)
        return self.rows


def process_state(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetExitCodeProcess.restype = ctypes.c_int
    handle = kernel.OpenProcess(0x1000, 0, pid)
    if not handle:
        return False if ctypes.get_last_error() == 87 else None
    try:
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def monitor(root, expected_pid):
    root = Path(root).resolve()
    base = root / "results/frontier-v6n"
    launch = strict((base / "launch-receipt.json").read_bytes())
    if (launch.get("schema") != "retrace.frontier-v6n-launch.v1"
            or type(expected_pid) is not int or expected_pid <= 0
            or launch.get("worker_pid") != expected_pid):
        raise ValueError("Exact direct-worker PID and launch receipt required")
    receipt = strict((root / "data/frontier-v6n-continuation.json").read_bytes())
    index = {row["slot_id"]: row["model"] for row in strict((root / "data/frontier-v6i-sessions.json").read_bytes())}
    if len(index) != 1800 or receipt["carried_final_slots"] + receipt["continuation_slots"] != 1800:
        raise ValueError("Fixed original schedule required")
    readers = {role: PrefixReader(base / path, role) for role, path in {
        "requests": "continuation/requests.jsonl", "responses": "continuation/responses.jsonl",
        "outcomes": "continuation/slot-outcomes.jsonl", "ledger": "budget/ledger.jsonl"}.items()}
    seen = set()
    next_progress = 50
    began = time.monotonic()
    cutoff_warning = datetime(2026, 11, 16, 6, 55, tzinfo=timezone.utc)
    cutoff = datetime(2026, 11, 16, 6, 56, tzinfo=timezone.utc)
    hard = datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc)
    def output(value):
        print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)
    output({"monitor": "started", "worker_pid": expected_pid, "poll_seconds": 55,
            "carried_final_slots": receipt["carried_final_slots"], "continuation_slots": receipt["continuation_slots"],
            "mode": "new complete lines; metadata only; no automatic actions"})
    while True:
        now = datetime.now(timezone.utc)
        alive = process_state(expected_pid)
        deadline_alerts = []
        for name, boundary in (("hard_cutoff_warning_0655", cutoff_warning), ("admission_cutoff_0656", cutoff), ("user_hard_cutoff_0700", hard)):
            if alive is not False and now >= boundary and name not in seen:
                seen.add(name)
                deadline_alerts.append(name)
        try:
            data = {role: reader.read() for role, reader in readers.items()}
            host = base / "host-guard.json"
            if host.exists() and strict(host.read_bytes()).get("pid") != expected_pid:
                raise ValueError("Actual host-guard PID differs from direct worker")
            account = accounting(data["ledger"], receipt["historical_conservative_carry_credits"], receipt["baseline_snapshot_sha256"])
            requests = {row["attempt_id"]: row for row in data["requests"]}
            responses = {row["attempt_id"]: row for row in data["responses"]}
            finals = [row for row in data["outcomes"] if row["model_outcome"] != "not_issued_global_stop"]
            per = defaultdict(Counter)
            for row in data["responses"]:
                per[index[row["slot_id"]]]["finished"] += 1
                per[index[row["slot_id"]]][row["model_outcome"]] += 1
            for row in finals:
                per[index[row["slot_id"]]]["definitive"] += 1
            violations = 0
            for before, after in zip(data["requests"], data["requests"][1:]):
                response = responses.get(before["attempt_id"])
                finish, admit = after.get("previous_attempt_finished_monotonic"), after.get("admitted_monotonic")
                if response and finite(finish) and finite(admit):
                    minimum = max(4.0, response.get("retry_cooldown_seconds") or 0, 65.0 if response.get("http_status") == 429 else 0)
                    violations += admit - finish + 1e-9 < minimum
            conditions = {
                "first_request": bool(requests), "first_429": any(r.get("http_status") == 429 for r in data["responses"]),
                "global_failure": any(r.get("failure_scope") == "global" for r in data["responses"]),
                "recorded_halt": account["recorded_halt"], "recorded_closure": account["recorded_run_closed"],
                "pacing_violation": bool(violations), "headroom_below_10": float(account["remaining_conservative_credits"]) < 10,
                "headroom_below_2": float(account["remaining_conservative_credits"]) < 2,
                "worker_absent_or_exited": alive is False, "process_status_unavailable": alive is None,
                "preflight_over_10min": not requests and time.monotonic() - began > 600,
                "request_at_or_after_cutoff": any(datetime.fromisoformat(q["at"]) >= cutoff for q in data["requests"]),
            }
            for model, counts in per.items():
                conditions["first_provider_completed:" + model] = bool(counts["completed"])
            alerts = deadline_alerts + [key for key, value in conditions.items() if value and key not in seen]
            seen.update(alerts)
            if len(finals) >= next_progress:
                alerts.append("progress_milestone")
                next_progress = (len(finals) // 50 + 1) * 50
            lock = (base / "budget/active.lock").exists()
            summary = (base / "continuation/summary.json").exists()
            if alerts:
                inflight = [row for aid, row in requests.items() if aid not in responses]
                output({"at": now.isoformat(), "alerts": alerts, "worker_pid": expected_pid, "process_alive": alive,
                    "lock": lock, "summary_present": summary, "new_definitive": len(finals),
                    "full_accounted_finals_including_two_derived_orphans": receipt["carried_final_slots"] + len(finals),
                    "not_yet_finalized": receipt["continuation_slots"] - len(finals), "new_issued": len(requests),
                    "new_finished": len(responses), "inflight": len(inflight),
                    "inflight_age_seconds": [(now - datetime.fromisoformat(q["at"])).total_seconds() for q in inflight],
                    "per_model": {model: dict(counts) for model, counts in per.items()}, "accounting": account,
                    "pacing_violations": violations, "provisional": True, "final_audit_performed": False})
            if alive is False:
                output({"monitor": "stopped", "reason": "worker absent or exited",
                        "closed_metadata": bool(summary and account["recorded_run_closed"] and not lock),
                        "no_automatic_transition": True})
                return
        except Exception as error:
            output({"at": now.isoformat(), "monitor": "metadata_read_error", "type": type(error).__name__,
                    "deadline_alerts": deadline_alerts, "no_sensitive_exception_text": True})
            if alive is False:
                output({"monitor": "stopped", "reason": "worker absent with unreadable metadata", "no_automatic_transition": True})
                return
        time.sleep(55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--worker-pid", type=int, required=True)
    args = parser.parse_args()
    monitor(args.root, args.worker_pid)
