#!/usr/bin/env python3
"""Verdicts for one authored case at its three states, under the engine and under two simple rules.

Sprint addition, written with AI assistance on Sunday 15 November 2026. Used for the worked example on page 1.

    python post_sweep/example_case.py ECO-07
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_sweep import read_json  # noqa: E402
from zero_call_analyses import STATES, downstream_classes, exclusions, family_classes, strip_lineage  # noqa: E402


def main():
    cid = sys.argv[1] if len(sys.argv) > 1 else "ECO-07"
    case = next(c for c in read_json("data/frontier-v6h-corpus.json")["cases"] if c["id"] == cid)
    graphs = [x["graph"] for x in case["evaluation"]["source_family"]]
    decisions = [r["id"] for r in graphs[0]["decisions"]]
    lines = [f"# Worked example: {cid}, {case['title']}", "",
             "Produced by `post_sweep/example_case.py`. Classes: ASSERT (supported in every reading), SPLIT, WITHHOLD.", "",
             "| State | Withdrawn records | " + " | ".join(f"Engine {d}" for d in decisions) + " | "
             + " | ".join(f"No lineage {d}" for d in decisions) + " | " + " | ".join(f"Withdraw downstream {d}" for d in decisions) + " |",
             "|---|---|" + "---|" * (3 * len(decisions))]
    for s in STATES:
        x = exclusions(case, s)
        engine = family_classes(graphs, case, s)
        bare = family_classes([strip_lineage(g) for g in graphs], case, s)
        flood = downstream_classes(graphs, case, s)
        lines.append(f"| {s} | {', '.join(x['document_vetoes'] + x['passage_vetoes']) or 'none'} | "
                     + " | ".join(engine[d] for d in decisions) + " | " + " | ".join(bare[d] for d in decisions) + " | "
                     + " | ".join(flood[d] for d in decisions) + " |")
    lines.append("")
    text = "\n".join(lines)
    (ROOT / "paper_build" / "tables" / f"example_{cid}.md").write_text(text, encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
