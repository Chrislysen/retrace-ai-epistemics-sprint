"""Record this user's authorized v4 execution without altering its offline freeze."""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORER = ['retrace/ambiguity_v4_eval.py', 'scripts/summarize_ambiguity_v4.py', 'tests/test_ambiguity_v4_eval.py']


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    destinations = ['data/ambiguity-v4-execution.json', 'data/ambiguity-v4-cycle-preservation.json',
                    'data/ambiguity-v4-scorer-checkpoint.json', 'results/ambiguity-v4-reservation.json']
    require(not any((ROOT / p).exists() for p in destinations), 'Execution preparation already exists; do not reserve twice')
    require(not (ROOT / 'results/ambiguity-v4').exists(), 'A v4 run already exists; never resume implicitly')
    prior_freezes = ['data/prose-freeze.json', 'data/extraction-v2-freeze.json', 'data/ambiguity-v3-freeze.json',
                     'data/ambiguity-v4-freeze.json']
    protected = {}
    for name in prior_freezes:
        protected[name] = digest(name)
        for row in read(name)['files']:
            require(digest(row['path']) == row['sha256'], 'Frozen input changed: ' + row['path'])
            protected[row['path']] = row['sha256']
    results = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((ROOT / 'results').rglob('*')) if p.is_file()}
    count = sum(len([l for l in p.read_bytes().splitlines() if l.strip()]) for p in (ROOT / 'results').rglob('requests.jsonl'))
    require(count == 485, 'Unexpected request count before new run')
    config = read('data/ambiguity-v4-config.json')
    ledger = read('results/ambiguity-v3-budget-final.json')
    sessions = read('data/ambiguity-v4-sessions.json')
    require(len(sessions) == 10 and all(len(s['steps']) == 1 for s in sessions), 'Wrong call count')
    require(config['max_requests'] == 10 and config['retries'] == 0 and config['concurrency'] == 1, 'Wrong fixed execution limits')
    base = Decimal(ledger['current_conservative_reserved_credits'])
    reserve = Decimal('0.24432640')
    require(base == Decimal('40.54847472'), 'Prior credit ledger changed')
    require(base + reserve == Decimal(config['cost_projection']['projected_cumulative_bound_credits']) < Decimal('41'), 'Budget projection mismatch')
    require(base + reserve < Decimal('50'), 'Credit cap exceeded')
    scorer_before = {p: digest(p) for p in SCORER}
    completed = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_ambiguity_v4_eval.py', '-v'],
                               cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    require(completed.returncode == 0, completed.stdout + completed.stderr)
    require(scorer_before == {p: digest(p) for p in SCORER}, 'Scorer changed during preflight')
    stamp = datetime.now(timezone.utc).isoformat()
    execution = {'schema': 'retrace.ambiguity-v4-authorized-execution.v1', 'created_at': stamp,
                 'authorization': 'User explicitly instructed: Run the frozen ambiguity-v4 evaluation; full autonomy within cumulative50-credit cap; no silent retries or cherry-picking.',
                 'config_sha256': digest('data/ambiguity-v4-config.json'),
                 'offline_freeze_sha256': digest('data/ambiguity-v4-freeze.json'),
                 'sessions_file_sha256': digest('data/ambiguity-v4-sessions.json'),
                 'sessions_json_sha256': hashlib.sha256(json.dumps(sessions, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(),
                 'runner_sha256': digest('scripts/run_adaption.mjs'),
                 'runner_entry_sha256': digest('scripts/run_ambiguity_v4.mjs'),
                 'scorer_checkpoint': 'data/ambiguity-v4-scorer-checkpoint.json',
                 'model': 'gemma-4-31b-it', 'planned_requests': 10, 'max_output_tokens': 4096,
                 'concurrency': 1, 'min_interval_ms': 3100, 'timeout_ms': 120000, 'retries': 0,
                 'output_directory': 'results/ambiguity-v4/gemma-4-31b-it',
                 'reservation_id': 'ambiguity-v4-gemma-10-v1', 'reserve_nanocredits_per_request': 24432640,
                 'prior_conservative_credits': str(base), 'reserved_credits': str(reserve),
                 'cumulative_conservative_credits': str(base + reserve), 'approved_cap_credits': '50',
                 'pricing_reverified': '2026-11-13; official Adaption model page fetched; Gemma input0.09/output0.34 unchanged',
                 'deadline_utc': '2026-11-16T11:59:00Z', 'internal_artifact_target_utc': '2026-11-15T18:00:00Z',
                 'deadline_note': 'Internal target leaves17h59m for review/packaging/submission; no submission is performed by this script.',
                 'status': 'authorized_once', 'scope': 'Separate execution authorization; does not rewrite frozen projected-only config.'}
    checkpoint = {'schema': 'retrace.ambiguity-v4-scorer-checkpoint.v1', 'created_at': stamp,
                  'files': [{'path': p, 'sha256': h} for p, h in scorer_before.items()],
                  'tests': {'exit_code': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr},
                  'prospective_to_v4_calls': True, 'post_hoc_to_v3_findings': True,
                  'scope': 'No new model outputs existed when scorer was implemented and checked. Later changes require a new audit version.'}
    preservation = {'schema': 'retrace.v4-cycle-preservation.v1', 'created_at': stamp,
                    'protected': protected, 'all_prior_results': results, 'previous_request_count': count,
                    'prior_freezes': prior_freezes}
    reservation = {'schema': 'retrace.ambiguity-v4-reservation.v1', 'created_at': stamp,
                   'reservation_id': execution['reservation_id'], 'request_limit': 10,
                   'baseline_ledger_sha256': digest('results/ambiguity-v3-budget-final.json'),
                   'baseline_conservative_credits': str(base), 'fresh_reserved_credits': str(reserve),
                   'cumulative_conservative_reserved_credits': str(base + reserve),
                   'remaining_under_50_credits': str(Decimal('50') - base - reserve),
                   'issued_attempt_refunds': False, 'status': 'reserved_before_dispatch', 'actual_billed_credits': None}
    for name, value in zip(destinations, (execution, preservation, checkpoint, reservation)):
        with (ROOT / name).open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'reserved': str(reserve), 'total_bound': str(base + reserve), 'planned_calls': 10,
                      'prior_results_preserved': len(results), 'frozen_paths_preserved': len(protected),
                      'scorer_checkpoint': digest(destinations[2])}))


if __name__ == '__main__':
    main()
