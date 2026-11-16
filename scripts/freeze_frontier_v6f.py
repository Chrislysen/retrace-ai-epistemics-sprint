"""Create the primary freeze once, after the completed diagnostic and reviews."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_frontier_v6f import integrity, verify_canary


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    destination = ROOT / 'data/frontier-v6f-primary-freeze.json'
    if destination.exists() or (ROOT / 'results/frontier-v6f/combined').exists():
        raise ValueError('Primary freeze or inference already exists')
    authorization = json.loads((ROOT / 'data/frontier-v6f-authorization.json').read_text())
    models = json.loads((ROOT / 'data/frontier-v6c-model-availability.json').read_text())
    protected_count = integrity(authorization, models)
    previous = json.loads((ROOT / 'data/frontier-v6f-canary-freeze.json').read_text())
    paths = set(authorization['protected'])
    for entry in previous['files']:
        if sha(ROOT / entry['path']) != entry['sha256']:
            raise ValueError('Canary dependency changed')
        paths.add(entry['path'])
    summary = json.loads((ROOT / 'results/frontier-v6f/canary/summary.json').read_text())
    verify_canary(summary)
    ledger = ROOT / 'results/frontier-v6f/budget/ledger.jsonl'
    if (ledger.parent / 'active.lock').exists():
        raise ValueError('Canary ledger still active')
    snapshot = ROOT / 'data/frontier-v6f-canary-ledger.jsonl'
    if snapshot.exists():
        raise ValueError('Ledger snapshot already exists')
    paths.update('''
data/frontier-v6f-canary-freeze.json
data/frontier-v6f-canary-ledger.jsonl
data/frontier-v6c-staged.json
data/frontier-v6d-dossiers.json
data/frontier-v6f-sessions.json
data/frontier-v6f-regression.json
data/frontier-v6f-regression-sessions.json
data/frontier-v6f-combined-sessions.json
data/frontier-v6f-combined-design.json
scripts/freeze_frontier_v6f.py
scripts/build_frontier_v6c_cases.py
scripts/audit_frontier_v6c_source.py
scripts/build_frontier_v6d_dossiers.py
scripts/build_frontier_v6f_sessions.py
scripts/build_frontier_v6f_regression.py
scripts/build_frontier_v6f_combined.py
scripts/split_frontier_v6f.py
scripts/score_frontier_v6f_regression.py
scripts/score_frontier_v6d.py
retrace/frontier_v6d_eval.py
retrace/frontier_v6c_stats.py
research/frontier-v6f-protocol.md
research/frontier-v6f-preflight-audit.md
research/frontier-v6f-combined-audit.md
research/frontier-v6c-case-audit.md
research/frontier-v6c-independent-audit.md
results/frontier-v6c-source-audit.json
results/frontier-v6f/canary-evaluation.json
tests/test_frontier_v6c_cases.py
tests/test_frontier_v6c_stats.py
tests/test_frontier_v6d_eval.py
tests/test_dossier_v6d.py
tests/test_frontier_v6f_projection.py
tests/test_frontier_v6f_views.py
'''.split())
    paths.update(p.relative_to(ROOT).as_posix()
                 for p in (ROOT / 'results/frontier-v6f/canary').rglob('*') if p.is_file())
    # Check all inputs before creating either exclusive output.
    for relative in paths - {snapshot.relative_to(ROOT).as_posix()}:
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Missing or invalid freeze input: ' + relative)
    with snapshot.open('xb') as stream:
        stream.write(ledger.read_bytes())
    freeze = {
        'schema': 'retrace.frontier-v6f-primary-freeze.v1',
        'frozen_at': datetime.now(timezone.utc).isoformat(),
        'primary_calls_before_freeze': 0,
        'development_regression_calls_before_freeze': 0,
        'planned_slots': 4640, 'primary_slots': 4560, 'development_regression_slots': 80,
        'concurrency': 5, 'timeout_seconds': 1200, 'retries': 0,
        'protected_files_verified': protected_count,
        'canary': {'valid_terminal_records': 10, 'task_passes': 9,
                   'ir_exact_family_passes': 4, 'ir_planned': 5,
                   'semantic_failure_retained': 'qwen3.8-27b malformed JSON'},
        'initial_budget': summary['budget'],
        'ledger_prefix_snapshot': snapshot.relative_to(ROOT).as_posix(),
        'live_ledger_note': 'Canonical ledger appends after this prefix; it is deliberately not frozen as a whole.',
        'independent_reviews': ['research/frontier-v6f-preflight-audit.md',
                                'research/frontier-v6f-combined-audit.md'],
        'files': [{'path': relative, 'sha256': sha(ROOT / relative)} for relative in sorted(paths)],
    }
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(freeze, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'path': destination.relative_to(ROOT).as_posix(),
                      'sha256': sha(destination), 'frozen_files': len(paths),
                      'protected_files': protected_count, 'planned_slots': 4640}))


if __name__ == '__main__':
    main()
