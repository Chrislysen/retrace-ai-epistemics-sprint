#!/usr/bin/env python3
"""Session files for the extension of the scaling run (prereg/scale_extension_rules.md). No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026.

    python post_sweep/scale_ext_sessions.py

Reads post_sweep/out/scale/sessions.json (the main run's 108 sessions) and writes, under post_sweep/out/scale/ext/:
  sessions_working.json         the 36 prose packets with an instruction that asks for visible working first
  sessions_stream_extract.json  the 36 compilation sessions, unchanged, for the streamed re-issue
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retrace.prose_sessions import DECISION_INSTRUCTIONS  # noqa: E402

ANSWER_ONLY = ('Return ONLY {"decisions":{"EXACT_ID":true}} with every requested decision exactly once, JSON booleans,\n'
               'and no explanation. Do not use Markdown fences.')
WORKING_FIRST = ('First work through the packet in plain text, step by step: say which evidence records are usable now, '
                 'then which claims are supported, then each decision.\n'
                 'Then end your answer with one final line that contains only {"decisions":{"EXACT_ID":true}} with every '
                 'requested decision exactly once and JSON booleans. Do not use Markdown fences.')


def working_instructions():
    if DECISION_INSTRUCTIONS.count(ANSWER_ONLY) != 1:
        raise SystemExit("the first-day instruction text is not as expected")
    return DECISION_INSTRUCTIONS.replace(ANSWER_ONLY, WORKING_FIRST)


def derive(manifest):
    """The two derived session lists for one manifest of first-day sessions."""
    text = working_instructions()
    working = [{**s, "condition": "prose_working", "response_kind": "working", "instructions": text}
               for s in manifest["sessions"] if s["condition"] == "prose_fresh"]
    extract = [s for s in manifest["sessions"] if s["condition"] == "prose_extract"]
    return text, working, extract


def write(path, payload):
    body = json.dumps(payload, ensure_ascii=False) + "\n"
    path.write_text(body, encoding="utf-8", newline="\n")
    print(f"{path.relative_to(ROOT).as_posix()}: {len(payload['sessions'])} sessions, sha256 {hashlib.sha256(body.encode('utf-8')).hexdigest()}")


def main():
    scale = ROOT / "post_sweep" / "out" / "scale"
    ext = scale / "ext"
    ext.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((scale / "sessions.json").read_text(encoding="utf-8"))
    text, working, extract = derive(manifest)
    write(ext / "sessions_working.json", {"instructions": text, "sessions": working})
    write(ext / "sessions_stream_extract.json", {"instructions": manifest["instructions"], "sessions": extract})
    print("--- instruction for visible working ---")
    print(text)


if __name__ == "__main__":
    main()
