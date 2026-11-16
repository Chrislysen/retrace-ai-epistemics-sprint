#!/usr/bin/env python3
"""Rerun the project's frozen scorer on the raw sweep journals, in process, writing nothing into results/.

Sprint addition, written with AI assistance on Sunday 15 November 2026 (pre-registration item R3).
It calls scripts/score_frontier_v6n.compute(), which authenticates the freeze, replays the runtime audit and
evaluates all 1,800 slots, and then compares the outcome with the files the project saved in
results/frontier-v6n/composite/. Outputs go to post_sweep/out/sweep_frozen/ (large, kept out of git) and a
small comparison record to post_sweep/out/sweep_reproduction.json.

    python post_sweep/rerun_frozen_scorer.py

In a fresh extraction of the release archive the three historical budget locks that the execution freeze lists are
present only under their archived names (provenance/frozen-locks/...). The scorer accepts exactly these aliases
(scripts/score_frontier_v6n.ALIASES), and this script passes them when a lock is absent, as the project's own release
verifier does. The saved score then differs from the rerun in one evidence field, the list of aliases used, which is
set equal before the comparison and recorded. (Added on 16 November after running the supplement in a fresh extraction.)
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.score_frontier_v6n import ALIASES, AUDIT, FREEZE, OUTPUT, PREFIX_PROOF, SNAPSHOT, compute  # noqa: E402


def sha_file(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def canonical(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def first_difference(a, b, path=""):
    if type(a) is not type(b):
        return f"{path}: type {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}/{key}: present on one side only"
            found = first_difference(a[key], b[key], f"{path}/{key}")
            if found:
                return found
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} vs {len(b)}"
        for index, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f"{path}[{index}]")
            if found:
                return found
    elif a != b:
        return f"{path}: {a!r} vs {b!r}"
    return None


def main():
    started = time.time()
    aliases = {name: alias for name, alias in ALIASES.items() if not (ROOT / name).exists() and (ROOT / alias).exists()}
    pins = {"freeze": sha_file(FREEZE), "prefix_proof": sha_file(PREFIX_PROOF), "runtime_audit": sha_file(AUDIT),
            "ledger_snapshot": sha_file(SNAPSHOT)}
    result, views = compute(ROOT, pins["freeze"], pins["prefix_proof"], pins["runtime_audit"], SNAPSHOT,
                            pins["ledger_snapshot"], frozen_aliases=aliases)
    mine = {"score.json": canonical(result["summary"]), "score-audits.json": canonical(result["audits"])}
    out = ROOT / "post_sweep" / "out" / "sweep_frozen"
    out.mkdir(parents=True, exist_ok=True)
    record = {"pins": pins, "seconds": None, "status": mine["score.json"].get("status"), "comparisons": {}}
    if aliases:
        record["archived_lock_names_used"] = aliases
    for name, value in mine.items():
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                encoding="utf-8", newline="\n")
        saved = json.loads((ROOT / OUTPUT / name).read_text(encoding="utf-8"))
        if aliases and name == "score.json" and isinstance(saved.get("file_evidence"), dict):
            saved["file_evidence"]["frozen_aliases"] = aliases
        record["comparisons"][name] = {"equal": saved == value, "first_difference": first_difference(saved, value),
                                       "saved_sha256": sha_file(f"{OUTPUT}/{name}")}
    for role, name in (("requests", "requests.jsonl"), ("responses", "responses.jsonl"), ("outcomes", "slot-outcomes.jsonl")):
        (out / name).write_bytes(views[role])
        record["comparisons"][name] = {"equal": hashlib.sha256(views[role]).hexdigest() == sha_file(f"{OUTPUT}/{name}"),
                                       "lines": views[role].count(b"\n")}
    record["seconds"] = round(time.time() - started, 1)
    (ROOT / "post_sweep" / "out" / "sweep_reproduction.json").write_text(json.dumps(record, indent=1) + "\n",
                                                                       encoding="utf-8", newline="\n")
    print(json.dumps(record, indent=1))


if __name__ == "__main__":
    main()
