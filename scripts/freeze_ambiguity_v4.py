"""Freeze the offline v4 extension; never imports or dispatches a paid runner.

Run once to capture the complete local suite, preserved evidence, and projected
config. --verify only checks the existing freeze and preservation commitments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.ambiguity_v4_sessions import build_config, build_public_corpus, build_sessions

PATHS = [
    'retrace/compact_v4.py', 'retrace/coverage_v4.py', 'retrace/engine_v4.py',
    'retrace/ambiguity_v4_sessions.py', 'retrace/server.py', 'retrace/cli.py',
    'retrace/core.py', 'retrace/compact_graph.py', 'retrace/stress.py', 'retrace/uncertainty.py',
    'retrace/__init__.py', 'web/index.html', 'web/app.js', 'web/style.css',
    'data/ambiguity-v4-demo.txt', 'data/ambiguity-v4-public.json',
    'data/ambiguity-v4-sessions.json', 'data/ambiguity-v4-config.json',
    'data/ambiguity-v4-preservation.json', 'research/ambiguity-v4-protocol.md',
    'tests/test_compact_v4.py', 'tests/test_coverage_v4.py', 'tests/test_engine_v4.py',
    'tests/test_v4_api.py', 'tests/test_ambiguity_v4_protocol.py',
    'scripts/freeze_ambiguity_v4.py', 'results/retrace-v4-preview.png', 'README.md',
]


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def preservation():
    baseline = read('data/ambiguity-v4-preservation.json')
    for collection in ('protected', 'all_prior_results'):
        for name, expected in baseline[collection].items():
            require(digest(name) == expected, 'Preserved file changed: ' + name)
    originals = read('results/stress-product-validation.json')['original_results']['hashes']
    require(len(originals) == baseline['original_result_count'] == 78, 'Original result inventory mismatch')
    for name, expected in originals.items():
        require(baseline['protected'].get(name) == expected, 'Original result missing from protection: ' + name)
    freezes = {}
    for name in ('data/prose-freeze.json', 'data/extraction-v2-freeze.json', 'data/ambiguity-v3-freeze.json'):
        rows = read(name)['files']
        for row in rows:
            require(digest(row['path']) == row['sha256'], 'Prior freeze dependency changed: ' + row['path'])
        freezes[name] = {'sha256': digest(name), 'dependencies_verified': len(rows)}
    journals = sorted((ROOT / 'results').rglob('requests.jsonl'))
    count = 0
    for path in journals:
        content = path.read_bytes()
        require(not content or content.endswith(b'\n'), 'Partial request journal: ' + str(path))
        count += len([line for line in content.splitlines() if line.strip()])
    require(count == baseline['previous_request_count'] == 485, 'Request count changed during offline v4 work')
    return {'all_match': True, 'original_results': len(originals),
            'all_prior_results': len(baseline['all_prior_results']), 'protected_paths': len(baseline['protected']),
            'prior_freezes': freezes, 'issued_requests_before': 485, 'issued_requests_after': count,
            'new_model_requests': 0,
            'scope': 'Local byte-integrity and request-journal checks; not provider billing verification.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    freeze_name = 'data/ambiguity-v4-freeze.json'
    validation_name = 'results/ambiguity-v4-offline-validation.json'
    if args.verify:
        preserved = preservation()
        manifest = read(freeze_name)
        for row in manifest['files']:
            require(digest(row['path']) == row['sha256'], 'V4 frozen artifact changed: ' + row['path'])
        print(json.dumps({'v4_files_verified': len(manifest['files']), 'preservation': preserved}))
        return
    require(not (ROOT / freeze_name).exists() and not (ROOT / validation_name).exists(),
            'Refusing to overwrite an existing freeze or validation result; use --verify')
    preservation()
    public = build_public_corpus(read('data/ambiguity-v3-staged.json'))
    sessions = build_sessions(public)
    config = build_config(ROOT, public, sessions)
    for name, expected in [('data/ambiguity-v4-public.json', public),
                           ('data/ambiguity-v4-sessions.json', sessions), ('data/ambiguity-v4-config.json', config)]:
        require(read(name) == expected, 'Prepared v4 input differs from tested builder: ' + name)
    require(config['dispatch_authorized'] is False and config['reservation_created'] is False,
            'The offline freeze cannot authorize dispatch or create a reservation')
    # Include every suite input so subsequent verification describes the exact
    # suite that ran, not merely the newly added modules.
    names = sorted(set(PATHS) | {p.relative_to(ROOT).as_posix() for p in (ROOT / 'tests').glob('test_*') if p.is_file()})
    before = {name: digest(name) for name in names}
    commands = [[sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                ['node', '--test', 'tests/test_runner.mjs'], ['node', '--check', 'web/app.js']]
    checks = []
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        row = {'command': command, 'exit_code': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr}
        checks.append(row)
        require(completed.returncode == 0, 'Preflight failed:\n' + completed.stdout + completed.stderr)
    require(before == {name: digest(name) for name in names}, 'A freeze input changed during preflight')
    preserved = preservation()
    python_count = int(re.search(r'Ran (\d+) tests', checks[0]['stderr']).group(1))
    node_count = int(re.search(r'(?:#|ℹ) tests (\d+)', checks[1]['stdout']).group(1))
    validation = {'schema': 'retrace.ambiguity-v4-offline-validation.v1',
                  'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'passed',
                  'python_tests': python_count, 'node_runner_tests': node_count, 'javascript_syntax': 'passed',
                  'checks': checks, 'preservation': preserved, 'cost_projection': config['cost_projection'],
                  'model_extraction_improvement_measured': False,
                  'browser_checks': ['Typed example: 3 declarations enumerate 8 assignments',
                                     'Unknown preserves 8; Yes prunes to 4; focus on resolved decision stops irrelevant questions',
                                     'Root-pair warning shown with exact hypothetical-withdrawal qualification',
                                     'Apply joint withdrawal changes supported decision to Revoked — falsity not asserted',
                                     'Degenerate same-source choice rejected without replacing current analysis',
                                     'Final demo shows compiled branches, disputed decisions, invariant supported decision and coverage warning',
                                     'No captured browser console errors'],
                  'browser_capture': 'results/retrace-v4-preview.png',
                  'scope': 'Engineering controls and reused synthetic diagnostics; no live v4 model output, source verification or empirical extraction gain.'}
    with (ROOT / validation_name).open('x', encoding='utf-8') as output:
        output.write(json.dumps(validation, ensure_ascii=False, indent=2) + '\n')
    before[validation_name] = digest(validation_name)
    manifest = {'schema': 'retrace.ambiguity-v4-offline-freeze.v1',
                'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'offline_prepared',
                'dispatch_authorized': False, 'reservation_created': False, 'config': config,
                'files': [{'path': name, 'sha256': value} for name, value in sorted(before.items())],
                'scope': 'Local integrity freeze, not external timestamping. No paid runner is invoked.'}
    with (ROOT / freeze_name).open('x', encoding='utf-8') as output:
        output.write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'freeze': freeze_name, 'sha256': digest(freeze_name), 'frozen_files': len(before),
                      'python_tests': python_count, 'node_runner_tests': node_count,
                      'preservation': preserved, 'cost_projection': config['cost_projection']}, indent=2))


if __name__ == '__main__':
    main()
