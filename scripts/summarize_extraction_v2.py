"""Score the separate v2 run without modifying original prose results."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.extraction_v2_eval import score


def main():
    from freeze_extraction_v2 import verify
    verify("data/extraction-v2-freeze.json")
    corpus = json.loads((ROOT / "data/extraction-v2-holdout.json").read_text(encoding="utf-8"))
    if isinstance(corpus, dict):
        corpus = corpus["cases"]
    models = {}
    for model in ("gemma-4-31b-it", "glm-53-flash"):
        path = ROOT / "results/extraction-v2" / model / "responses.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line] if path.exists() else []
        models[model] = score(corpus, records)
    result = {"schema": "retrace.extraction-v2-summary", "models": models}
    (ROOT / "results/extraction-v2-summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({m: {"groups": s["groups"], "contrasts": s["contrasts"]} for m, s in models.items()}, indent=2))


if __name__ == "__main__":
    main()
