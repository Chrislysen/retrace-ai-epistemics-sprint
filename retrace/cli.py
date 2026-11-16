from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .benchmark import generate_cases, run_benchmarks
from .core import analyze
from .experiment import manifest, score_records


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(path.resolve())


def main():
    parser = argparse.ArgumentParser(description="RETRACE declared-support stress tester")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Open the local evidence viewer")
    serve.add_argument("--port", type=int, default=8765)
    bench = sub.add_parser("benchmark", help="Run deterministic rule policies, not LLMs")
    bench.add_argument("--count", type=int, default=120)
    bench.add_argument("--seed", type=int, default=1729)
    bench.add_argument("--output", default="results/rule-baselines.json")
    bench.add_argument("--cases", default="data/benchmark.json")
    export = sub.add_parser("export", help="Export answer-free sessions for model evaluation")
    export.add_argument("--count", type=int, default=12)
    export.add_argument("--seed", type=int, default=20261113)
    export.add_argument("--output", default="data/pilot-sessions.json")
    export.add_argument("--cases", default="data/pilot-cases.json")
    score = sub.add_parser("score", help="Score a single model's saved JSONL responses")
    score.add_argument("records")
    score.add_argument("--cases", default="data/pilot-cases.json")
    score.add_argument("--output", default="results/model-scores.json")
    inspect = sub.add_parser("analyze")
    inspect.add_argument("case")
    inspect.add_argument("--revoke", nargs="*", default=[])
    compile_cmd = sub.add_parser("compile", help="Validate a complete compact graph and export explicit JSON locally")
    compile_cmd.add_argument("source")
    compile_cmd.add_argument("--output", required=True)
    compile_cmd.add_argument("--registry", help="Optional JSON object with exact evidence/claims/decisions ID arrays")
    uncertain = sub.add_parser("uncertainty", help="Audit support and plan source clarification within an explicit candidate set")
    uncertain.add_argument("bundle")
    uncertain.add_argument("--output", required=True)
    interventions = sub.add_parser("interventions", help="Compare all allowed withdrawal subsets of named graphs")
    interventions.add_argument("bundle")
    interventions.add_argument("--output", required=True)
    stress = sub.add_parser("stress", help="Unify candidate consensus, clarification and minimal withdrawal witnesses")
    stress.add_argument("brief")
    stress.add_argument("--state", help="Optional JSON answers and separate revocation flags")
    stress.add_argument("--output", help="Optional audit JSON path; otherwise print to stdout")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import serve
        serve(args.port)
    elif args.command == "stress":
        from .stress import analyze_stress
        from .server import unique_object, reject_constant
        def read_strict(path):
            return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                              parse_constant=reject_constant)
        result = analyze_stress(read_strict(args.brief), read_strict(args.state) if args.state else None)
        if args.output:
            write(args.output, result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=True))
    elif args.command == "benchmark":
        cases = generate_cases(seed=args.seed, count=args.count)
        write(args.cases, cases)
        write(args.output, run_benchmarks(cases))
    elif args.command == "export":
        cases = generate_cases(seed=args.seed, count=args.count)
        write(args.cases, cases)
        write(args.output, manifest(cases, args.seed))
    elif args.command == "score":
        cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
        records = [json.loads(line) for line in Path(args.records).read_text(encoding="utf-8").splitlines() if line.strip()]
        write(args.output, score_records(cases, records))
    elif args.command == "uncertainty":
        from .uncertainty import analyze_uncertainty
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        write(args.output, analyze_uncertainty(bundle["candidates"], bundle.get("questions"), bundle.get("target_decisions")))
    elif args.command == "interventions":
        from .intervention_audit import audit_interventions
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        write(args.output, audit_interventions(bundle["graphs"], bundle.get("allowed_withdrawals")))
    elif args.command == "compile":
        from .compact_graph import CompactGraphError, parse_compact_output
        try:
            source = Path(args.source).read_text(encoding="utf-8")
            registry = json.loads(Path(args.registry).read_text(encoding="utf-8")) if args.registry else None
            compiled = parse_compact_output(source, registry)
            write(args.output, compiled["graph"])
            write(str(args.output) + ".audit.json", {**compiled,
                  "note": "Format and graph consistency validated. Source fidelity and withdrawal authority require review."})
        except (OSError, ValueError) as exc:
            print(json.dumps({"error": str(exc), "code": getattr(exc, "code", "invalid_input"),
                              "line_number": getattr(exc, "line_number", None)}), file=sys.stderr)
            raise SystemExit(2)
    else:
        print(json.dumps(analyze(json.loads(Path(args.case).read_text(encoding="utf-8")), args.revoke), indent=2))


if __name__ == "__main__":
    main()
