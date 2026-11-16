"""Small reproducible timing check, separate from scientific model results."""
import json
import platform
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.core import analyze

cases = json.loads((ROOT / "data" / "benchmark.json").read_text())
times = []
for _ in range(10):
    for case in cases:
        started = perf_counter_ns()
        analyze(case, case["revoke"])
        times.append((perf_counter_ns() - started) / 1_000_000)
times.sort()
report = {"kind": "local_implementation_timing", "created_at": datetime.now(timezone.utc).isoformat(),
          "python": platform.python_version(), "case_count": len(cases), "repeats": 10,
          "median_ms_per_analysis": statistics.median(times), "p95_ms_per_analysis": times[int(.95 * (len(times)-1))],
          "total_analysis_calls": len(times),
          "scope": "Includes validation, original and withdrawn graph evaluation, and explanatory paths; excludes UI, HTTP, disk loading and model inference. Warm sequential process; hardware-dependent, not a comparative performance study."}
(ROOT / "results" / "core-timing.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
