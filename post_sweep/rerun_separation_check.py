#!/usr/bin/env python3
"""Rerun the project's separation check (Appendix B of the paper) in process and compare it with the saved certificate.

Sprint addition, written with AI assistance on Monday 16 November 2026. No model call. Nothing is written into the
project's own folders: scripts/check_frontier_v6j_separation.py is imported and only its check() function is called.

    python post_sweep/rerun_separation_check.py

Output: post_sweep/out/separation_rerun.json (also printed).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_frontier_v6j_separation as separation  # noqa: E402


def main():
    fresh = json.loads(json.dumps(separation.check()))   # through JSON, so tuples compare as the lists that were saved
    saved = json.loads((ROOT / "results/frontier-v6j-offline/separation-certificate.json").read_text(encoding="utf-8"))
    differing = sorted(k for k in set(fresh) | set(saved) if fresh.get(k) != saved.get(k))
    for key in differing:
        a, b = fresh.get(key), saved.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            for sub in sorted(set(a) | set(b)):
                if a.get(sub) != b.get(sub):
                    print(f"differs: {key}.{sub}: fresh {json.dumps(a.get(sub))[:300]} | saved {json.dumps(b.get(sub))[:300]}")
        else:
            print(f"differs: {key}: fresh {json.dumps(a)[:300]} | saved {json.dumps(b)[:300]}")
    out = {"passed": fresh["passed"],
           "scalar_graph_state_comparisons": fresh["scalar_graph_state_comparisons"],
           "higher_order_k_values": [row["k"] for row in fresh["higher_order"]],
           "comparisons_higher_order": sum(row["scalar_graph_state_comparisons"] for row in fresh["higher_order"]),
           "comparisons_masked": fresh["masked_prerequisite"]["scalar_graph_state_comparisons"],
           "masked_truth_table": fresh["masked_prerequisite"]["truth_table"],
           "identical_to_saved_certificate": fresh == saved,
           "top_level_keys_that_differ": differing,
           "input_hashes_identical": fresh.get("input_sha256") == saved.get("input_sha256")}
    (ROOT / "post_sweep" / "out" / "separation_rerun.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8",
                                                                       newline="\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
