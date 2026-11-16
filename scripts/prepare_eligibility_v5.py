"""Freeze and reserve the eight-call prospective eligibility-pair diagnostic."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    names = ['data/eligibility-v5-execution.json', 'data/eligibility-v5-freeze.json',
             'data/eligibility-v5-preservation.json', 'results/eligibility-v5-reservation.json']
    require(not any((ROOT / n).exists() for n in names) and not (ROOT / 'results/eligibility-v5').exists(), 'Preparation or run already exists')
    protected = {}
    for name in ('data/prose-freeze.json', 'data/extraction-v2-freeze.json', 'data/ambiguity-v3-freeze.json', 'data/ambiguity-v4-freeze.json'):
        protected[name] = digest(name)
        for row in read(name)['files']:
            require(digest(row['path']) == row['sha256'], 'Prior frozen artifact changed: ' + row['path'])
            protected[row['path']] = row['sha256']
    checkpoint = read('data/ambiguity-v4-scorer-checkpoint.json')
    for row in checkpoint['files']:
        require(digest(row['path']) == row['sha256'], 'V4 primary scorer changed')
        protected[row['path']] = row['sha256']
    protected['data/ambiguity-v4-scorer-checkpoint.json'] = digest('data/ambiguity-v4-scorer-checkpoint.json')
    results = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((ROOT / 'results').rglob('*')) if p.is_file()}
    count = sum(len([line for line in p.read_bytes().splitlines() if line.strip()]) for p in (ROOT / 'results').rglob('requests.jsonl'))
    require(count == 495, 'Unexpected prior request count')
    paths = ['data/eligibility-v5-paired-staged.json', 'data/eligibility-v5-paired-sessions.json',
             'retrace/compact_v5.py', 'retrace/exposure_v5.py', 'retrace/eligibility_v5_eval.py',
             'scripts/summarize_eligibility_v5.py', 'scripts/prepare_eligibility_v5.py', 'scripts/run_eligibility_v5.mjs',
             'tests/test_compact_v5.py', 'tests/test_exposure_v5.py', 'tests/test_eligibility_v5_pairs.py', 'tests/test_eligibility_v5_eval.py',
             'research/eligibility-v5-paired-protocol.md', 'research/eligibility-v5-independent-review.md']
    before = {name: digest(name) for name in paths}
    checks = []
    for command in [[sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                    ['node', '--test', 'tests/test_runner.mjs'], ['node', '--check', 'web/v5/app.js']]:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        checks.append({'command': command, 'exit_code': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr})
        require(completed.returncode == 0, completed.stdout + completed.stderr)
    require(before == {name: digest(name) for name in paths}, 'A prospective dependency changed during tests')
    for name, expected in {**protected, **results}.items():
        require(digest(name) == expected, 'Prior artifact changed during tests: ' + name)
    old = read('results/ambiguity-v4-budget-final.json')
    base = Decimal(old['current_conservative_reserved_credits'])
    extra = Decimal('0.19546112')
    require(base == Decimal('40.79280112') and base + extra < Decimal('41'), 'Budget baseline changed')
    sessions = read('data/eligibility-v5-paired-sessions.json')
    require(len(sessions) == 8 and all(len(s['steps']) == 1 for s in sessions), 'Wrong call count')
    stamp = datetime.now(timezone.utc).isoformat()
    execution = {'schema': 'retrace.eligibility-v5-authorized-execution.v1', 'created_at': stamp,
                 'status': 'authorized_once', 'authorization': 'User delegated remaining-cycle experimental decisions within50-credit cumulativecap, preserving freezes and all outputs.',
                 'model': 'gemma-4-31b-it', 'planned_requests': 8, 'max_output_tokens': 4096,
                 'concurrency': 1, 'min_interval_ms': 3100, 'timeout_ms': 120000, 'retries': 0,
                 'output_directory': 'results/eligibility-v5/gemma-4-31b-it',
                 'sessions_file_sha256': digest('data/eligibility-v5-paired-sessions.json'),
                 'sessions_json_sha256': hashlib.sha256(json.dumps(sessions, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(),
                 'runner_sha256': digest('scripts/run_adaption.mjs'), 'runner_entry_sha256': digest('scripts/run_eligibility_v5.mjs'),
                 'reserve_nanocredits_per_request': 24432640, 'reservation_id': 'eligibility-v5-gemma-8-v1',
                 'reserved_credits': str(extra), 'prior_conservative_credits': str(base),
                 'cumulative_conservative_credits': str(base + extra), 'approved_cap_credits': '50',
                 'price_basis': 'Official Gemma input0.09/output0.34 credits per million; reverified in this cycle. Full256000context+4096output bound, no cache discount.',
                 'design': 'Prospective-to-calls targeted synthetic diagnostic:8packets/4pairedstructures; not8independent generalization units.'}
    reservation = {'schema': 'retrace.eligibility-v5-reservation.v1', 'created_at': stamp,
                   'reservation_id': execution['reservation_id'], 'status': 'reserved_before_dispatch', 'request_limit': 8,
                   'baseline_ledger_sha256': digest('results/ambiguity-v4-budget-final.json'),
                   'baseline_conservative_credits': str(base), 'fresh_reserved_credits': str(extra),
                   'cumulative_conservative_reserved_credits': str(base + extra),
                   'remaining_under_50_credits': str(Decimal(50) - base - extra), 'actual_billed_credits': None}
    preservation = {'schema': 'retrace.eligibility-v5-preservation.v1', 'created_at': stamp,
                    'protected': protected, 'all_prior_results': results, 'previous_request_count': count}
    for name, value in [(names[0], execution), (names[2], preservation), (names[3], reservation)]:
        with (ROOT / name).open('x', encoding='utf-8') as output:
            output.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    frozen_paths = sorted(set(paths) | set(protected) | {names[0], names[2], names[3]})
    freeze = {'schema': 'retrace.eligibility-v5-freeze.v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'files': [{'path': name, 'sha256': digest(name)} for name in frozen_paths], 'checks': checks,
              'scope': 'Local prospective integrity freeze before eight new calls; all prior results preserved; no model call made by preparation.'}
    with (ROOT / names[1]).open('x', encoding='utf-8') as output:
        output.write(json.dumps(freeze, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'frozen_files': len(frozen_paths), 'reserved': str(extra), 'total_bound': str(base + extra),
                      'prior_results_preserved': len(results), 'python_check': checks[0]['stderr'], 'node_check': checks[1]['exit_code']}))


if __name__ == '__main__':
    main()
