"""Offline-only deterministic study builder; exclusive writes, no dispatch."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.falsification_v6_eval import build_study, build_sessions


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Compare deterministic artifacts without writing")
    args = parser.parse_args()
    source = ROOT / "data/conservation-v6-cases.json"
    raw = source.read_bytes()
    study = build_study(json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest())
    sessions = build_sessions(study)
    outputs = {ROOT / "data/falsification-v6-study.json": encoded(study),
               ROOT / "data/falsification-v6-sessions.json": encoded(sessions)}
    if args.check_only:
        for path, text in outputs.items():
            if path.read_text(encoding="utf-8") != text:
                raise ValueError(f"Generated artifact differs: {path.name}")
    else:
        if any(path.exists() for path in outputs):
            raise FileExistsError("Refusing to overwrite existing study/session artifacts; use --check-only")
        for path, text in outputs.items():
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
    print(json.dumps({"status": "checked" if args.check_only else "prepared_offline",
                      "cases": len(study["cases"]), "slots": len(sessions),
                      "projected_additional_credits": study["budget"]["projected_additional_credits"],
                      "reservation_created": False, "model_calls": 0,
                      "sha256": {str(p.relative_to(ROOT)): hashlib.sha256(t.encode("utf-8")).hexdigest() for p,t in outputs.items()}}, indent=2))


if __name__ == "__main__":
    main()
