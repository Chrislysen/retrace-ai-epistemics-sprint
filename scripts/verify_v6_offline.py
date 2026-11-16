"""Read-only reproduction of the failed v6 offline gates; never dispatches models."""
import sys
sys.dont_write_bytecode = True

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def compare(actual, expected, message):
    require(json.loads(json.dumps(actual)) == expected, message)


def verify():
    preservation = read('data/v6-baseline-preservation.json')
    protected = dict(preservation['protected'])
    for manifest in ('data/conservation-v6-initial-freeze.json',
                     'data/conservation-v6-adapter-freeze.json', 'data/conservation-v6b-freeze.json',
                     'data/v6-offline-experimental-freeze.json'):
        if not (ROOT / manifest).exists():
            require(manifest.endswith('v6-offline-experimental-freeze.json'), 'Missing study freeze')
            continue
        for row in read(manifest)['files']:
            require(row['path'] not in protected or protected[row['path']] == row['sha256'], 'Conflicting preservation hashes')
            protected[row['path']] = row['sha256']
    for name, expected in protected.items():
        require(digest(name) == expected, 'Changed protected file: ' + name)
    from retrace.conservation_v6 import audit_conservation as initial
    from retrace.conservation_v6b import audit_conservation as revised
    from scripts.evaluate_conservation_v6 import evaluate_corpus
    from scripts.evaluate_conservation_v6_compatible import evaluate_compatible
    from scripts.evaluate_conservation_v6b import evaluate_holdout, assess_gate
    corpus = read('data/conservation-v6-cases.json')
    primary = evaluate_corpus(corpus, initial)
    saved = read('results/v6/conservation-offline-primary.json')
    for key, value in primary.items():
        compare(value, saved[key], 'Initial instrument-failure replay differs: ' + key)
    compatible = evaluate_compatible(corpus, initial)
    saved = read('results/v6/conservation-offline-compatible.json')
    for key, value in compatible.items():
        compare(value, saved[key], 'Compatible initial replay differs: ' + key)
    fresh = evaluate_holdout(read('data/conservation-v6b-holdout-reviewed.json'), revised)
    saved = read('results/v6b/conservation-v6b-primary.json')
    compare(fresh, saved['fresh_holdout'], 'Fresh v6b results differ')
    compare(evaluate_compatible(corpus, revised), saved['development_replay'], 'Development replay differs')
    gate = assess_gate(fresh, read('data/conservation-v6b-quality-gate.json'), True)
    compare(gate, saved['quality_gate'], 'Quality gate changed')
    require(gate['passed'] is False, 'This experimental checkpoint records a failed gate')
    requests = sum(len([line for line in path.read_bytes().splitlines() if line.strip()])
                   for path in (ROOT / 'results').rglob('requests.jsonl'))
    require(requests == preservation['previous_requests'] == 503, 'Unexpected paid request since offline checkpoint')
    for path in ('data/falsification-v6-execution.json', 'results/v6/falsification-dispatch.jsonl',
                 'results/v6/falsification-reservation.json'):
        require(not (ROOT / path).exists(), 'A paid v6 execution artifact exists')
    slots = read('data/falsification-v6-sessions.json')
    require(len(slots) == 32 and Counter(s['model'] for s in slots) == {'gemma-4-31b-it': 16, 'glm-53-flash': 16},
            'Prepared study inventory changed')
    return {'schema': 'retrace.v6-offline-verification.v1', 'status': 'passed',
            'v5_baseline_files_unchanged': len(preservation['protected']),
            'all_protected_files_checked': len(protected), 'all_offline_results_exactly_reproduced': True,
            'fresh_quality_gate_passed': False, 'fresh_gate_checks': gate['checks'],
            'paid_v6_requests': 0, 'total_issued_requests': requests,
            'conservative_commitment_credits': preservation['conservative_commitment_credits'],
            'remaining_headroom_credits': preservation['remaining_headroom_credits'],
            'prepared_but_unissued_slots': 32,
            'release_status': 'Experimental only; retain protected v5 competition deliverable.'}, protected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tests', action='store_true')
    args = parser.parse_args()
    try:
        result, protected = verify()
        if args.tests:
            commands = [
                ('python', [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q']),
                ('node', ['node', '--test', '--test-reporter=tap', 'tests/test_runner.mjs', 'tests/test_v6_coordinator.mjs']),
                ('javascript', ['node', '--check', 'web/v6/app.js'])]
            result['tests'] = {}
            for name, command in commands:
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                           encoding='utf-8', errors='replace', timeout=180)
                require(completed.returncode == 0, name + ': ' + (completed.stdout + completed.stderr)[-2000:])
                match = re.search(r'Ran (\d+) tests?' if name == 'python' else r'# tests (\d+)',
                                  completed.stdout + completed.stderr)
                result['tests'][name] = {'passed': True, 'count': int(match.group(1)) if match else None}
            require(all(digest(path) == expected for path, expected in protected.items()), 'Tests changed a protected artifact')
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}, indent=2))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
