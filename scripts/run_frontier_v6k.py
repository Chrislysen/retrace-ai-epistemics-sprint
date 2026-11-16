"""Freeze or execute the prospective continuation of the interrupted 1,800-slot study.

Only --execute-sha256 performs inference. Credentials arrive on stdin, never in
arguments or files. Existing runs, ledgers and freezes cannot be overwritten.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.adaption_v6k import (AiohttpTransport, BASELINE, BASELINE_LEDGER,
    DEADLINE, RUNTIME_CONFIG, RollingLedger, digest, require, run_slots,
    verify_execution_manifest, verify_prior_ledger)
from retrace.frontier_v6i_eval import design as validate_design
from retrace.adaption_v6k import verify_continuation
from scripts.build_frontier_v6i_sessions import build, SOURCE_PATHS
from scripts.run_frontier_v6h import verify_corpus
from scripts.score_frontier_v6h import local_dependencies

AUTH = 'data/frontier-v6k-authorization.json'
AUTH_SHA = '360e09fefd705139cf73d2cd10da12109a6a64f35e76f27050f5693e64c136ef'
FREEZE = 'data/frontier-v6k-freeze.json'
SESSIONS = 'data/frontier-v6i-sessions.json'
DESIGN = 'data/frontier-v6i-design.json'
CONTINUATION = 'data/frontier-v6k-continuation.json'
CONTINUATION_SHA = '017a8e08c1c50d7199c0be5e93daa139c30a01e70cd966608de4eacae3488a51'
OBSERVED_ROUTES = {'qwen3.5-397b': 'qwen3.5-397b-a17b-nvfp4'}
BASE = 'results/frontier-v6k'
OUTPUT = BASE + '/continuation'
LEDGER = BASE + '/budget'
TESTS = ('tests.test_adaption_v6k', 'tests.test_frontier_v6i_sessions',
    'tests.test_frontier_v6k_eval', 'tests.test_frontier_v6k_driver',
    'tests.test_frontier_v6k_runtime_audit', 'tests.test_frontier_v6i_runtime_audit', 'tests.test_frontier_v6j_runtime_audit',
    'tests.test_frontier_v6i_eval', 'tests.test_score_frontier_v6k')
NEW_FILES = (AUTH, SESSIONS, DESIGN, CONTINUATION, 'requirements-v6k.txt',
    'scripts/authorize_frontier_v6k.py', 'scripts/build_frontier_v6i_sessions.py',
    'scripts/run_frontier_v6k.py', 'scripts/score_frontier_v6k.py',
    'tests/test_score_frontier_v6k.py',
    'retrace/adaption_v6k.py', 'retrace/frontier_v6k_eval.py',
    'scripts/audit_frontier_v6k_runtime.py', 'scripts/audit_frontier_v6i_runtime.py',
    'tests/test_frontier_v6k_runtime_audit.py', 'tests/test_frontier_v6i_runtime_audit.py',
    'tests/test_adaption_v6k.py', 'tests/test_frontier_v6i_sessions.py',
    'tests/test_frontier_v6k_eval.py', 'tests/test_frontier_v6k_driver.py',
    'research/frontier-v6k-continuation-protocol.md', 'research/frontier-v6k-report-amendment.md',
    'research/frontier-v6k-runtime-review.md', 'research/frontier-v6k-scoring-review.md')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def checked_path(relative):
    path = (ROOT / relative).resolve()
    require(path.is_relative_to(ROOT.resolve()) and path.is_file(), 'invalid_frozen_path')
    return path


def historical_integrity():
    require(sha(ROOT / AUTH) == AUTH_SHA, 'authorization_changed')
    auth = read(ROOT / AUTH)
    require(len(auth['protected']) == 1301 and auth['protected_v5_file_count'] == 402,
        'historical_inventory_changed')
    require(auth['cumulative_cap_credits'] == '250' and
        auth['historical_conservative_carry_credits'] == BASELINE, 'authorization_budget')
    for relative, expected in auth['protected'].items():
        require(sha(checked_path(relative)) == expected, 'historical_dependency_changed: ' + relative)
    require(not (ROOT / 'results/frontier-v6h/budget/active.lock').exists(), 'old_ledger_locked')
    require(not (ROOT / 'results/frontier-v6i/budget/active.lock').exists(), 'interrupted_ledger_locked')
    require(not (ROOT / 'results/frontier-v6j/budget/active.lock').exists(), 'second_interrupted_ledger_locked')
    verify_prior_ledger(ROOT / BASELINE_LEDGER)
    return auth


def fresh_destination():
    for relative in ('results', BASE, OUTPUT, LEDGER, BASE + '/STOP'):
        resolved = (ROOT / relative).resolve()
        require(resolved.is_relative_to(ROOT.resolve()) and resolved == ROOT.resolve() / relative,
            'noncanonical_destination')
    require(not (ROOT / OUTPUT).exists(), 'study_already_exists')
    require(not (ROOT / LEDGER).exists(), 'ledger_already_exists')
    require(not (ROOT / BASE / 'STOP').exists(), 'stop_file_present')


def scientific_integrity():
    corpus, dossiers, old = [read(ROOT / name) for name in SOURCE_PATHS[:3]]
    hashes = {name: sha(ROOT / name) for name in SOURCE_PATHS}
    study, slots = build(corpus, old, source_hashes=hashes)
    require(study == read(ROOT / DESIGN), 'design_not_reproducible')
    require(slots == read(ROOT / SESSIONS), 'sessions_not_reproducible')
    validate_design(corpus, dossiers, study, slots, True)
    verify_corpus(ROOT / SOURCE_PATHS[0], hashes[SOURCE_PATHS[0]])
    return slots


def continuation_integrity(slots):
    require(sha(ROOT / CONTINUATION) == CONTINUATION_SHA, 'continuation_receipt_changed')
    receipt = read(ROOT / CONTINUATION)
    require(receipt['sessions_sha256'] == digest(slots) and receipt['full_planned_slots'] == 1800,
        'continuation_scientific_schedule_changed')
    require(receipt['observed_response_models'] == OBSERVED_ROUTES, 'observed_route_changed')
    carry = verify_continuation(slots, ROOT / CONTINUATION, CONTINUATION_SHA)
    require(len(carry['finals']) == 224 and len(carry['issued_slot_ids']) == 213,
        'exact_prior_definitive_outcomes_required')
    require(carry['continuation_slot_ids'] == receipt['continuation_slot_ids'] and
        len(carry['continuation_slot_ids']) == 1576, 'unissued_only_continuation')
    require(set(carry['finals']).isdisjoint(carry['continuation_slot_ids']), 'no_reissued_final')
    return receipt


def freeze():
    require(not (ROOT / FREEZE).exists(), 'freeze_already_exists')
    require(datetime.now(timezone.utc) < DEADLINE, 'delivery_buffer_reached')
    fresh_destination()
    auth = historical_integrity()
    slots = scientific_integrity()
    continuation_integrity(slots)
    paths = {checked_path(name) for name in (*auth['protected'], *NEW_FILES)}
    paths |= local_dependencies([ROOT / 'scripts/run_frontier_v6k.py',
        ROOT / 'scripts/score_frontier_v6k.py'])
    before = {path: sha(path) for path in paths}
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromNames(TESTS))
    preflight = ROOT / f'results/frontier-v6k-preflight-{uuid.uuid4().hex}.json'
    write_new(preflight, {'schema': 'retrace.frontier-v6k-preflight.v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'passed': result.wasSuccessful(),
        'tests_run': result.testsRun, 'tests': list(TESTS), 'paid_calls': 0,
        'python': sys.version, 'aiohttp': importlib.metadata.version('aiohttp'),
        'log': capture.getvalue(),
        'scope': 'Continuation runtime, lossless composite closure, driver and unchanged scientific grading regressions. Both original stopped segments remain stopped; scientific grading unchanged.'})
    require(result.wasSuccessful(), 'preflight_failed: ' + str(preflight))
    for path, expected in before.items():
        require(sha(path) == expected, 'dependency_changed_during_preflight')
    historical_integrity(); fresh_destination()
    paths.add(preflight)
    files = [{'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p), 'bytes': p.stat().st_size}
        for p in sorted(paths)]
    manifest = {'schema': 'retrace.frontier-v6k-freeze.v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'files': files,
        'sessions_path': SESSIONS, 'sessions_sha256': digest(slots),
        'sessions_file_sha256': sha(ROOT / SESSIONS), 'study_path': DESIGN,
        'scheduled_slots': 1800, 'continuation_slots': 1576, 'carried_issued_slots': 213, 'carried_final_slots': 224,
        'continuation_path': CONTINUATION, 'continuation_sha256': CONTINUATION_SHA,
        'observed_response_models': OBSERVED_ROUTES, 'runtime_config': RUNTIME_CONFIG,
        'deadline_utc': DEADLINE.isoformat(), 'output_path': OUTPUT, 'ledger_path': LEDGER,
        'baseline_path': BASELINE_LEDGER, 'baseline_sha256': sha(ROOT / BASELINE_LEDGER),
        'historical_conservative_carry_credits': BASELINE, 'cumulative_cap_credits': '250',
        'authorization_path': AUTH, 'authorization_sha256': AUTH_SHA,
        'preflight_path': preflight.relative_to(ROOT).as_posix(),
        'scope': 'Prospective continuation after two closed interrupted segments. Same1800 scientific slots;224 definitive outcomes (213 issued and11 dependency skips) permanently excluded,1576 untouched outcomes remain. Only typed future post-header transport disconnections are per-slot; original global failures remain unchanged. No halted ledger is reopened.'}
    write_new(ROOT / FREEZE, manifest)
    verify_execution_manifest(ROOT / FREEZE, sha(ROOT / FREEZE), slots)
    return {'path': FREEZE, 'sha256': sha(ROOT / FREEZE), 'files': len(files),
        'offline_tests': result.testsRun, 'planned_slots': len(slots), 'paid_calls': 0}


def verify_frozen(expected):
    require(sha(ROOT / FREEZE) == expected, 'freeze_changed')
    frozen = read(ROOT / FREEZE)
    require(frozen['schema'] == 'retrace.frontier-v6k-freeze.v1', 'freeze_schema')
    fixed = {'sessions_path': SESSIONS, 'study_path': DESIGN, 'output_path': OUTPUT,
        'ledger_path': LEDGER, 'baseline_path': BASELINE_LEDGER, 'scheduled_slots': 1800,
        'continuation_path': CONTINUATION, 'continuation_sha256': CONTINUATION_SHA,
        'observed_response_models': OBSERVED_ROUTES, 'continuation_slots': 1576, 'carried_issued_slots': 213, 'carried_final_slots': 224,
        'authorization_path': AUTH, 'authorization_sha256': AUTH_SHA,
        'cumulative_cap_credits': '250', 'historical_conservative_carry_credits': BASELINE}
    require(all(frozen.get(k) == v for k, v in fixed.items()), 'freeze_fixed_contract')
    require(len({r['path'] for r in frozen['files']}) == len(frozen['files']), 'duplicate_frozen_file')
    inventory = {row['path']: row for row in frozen['files']}
    auth = historical_integrity()
    require(set(auth['protected']) | set(NEW_FILES) <= set(inventory), 'incomplete_freeze_inventory')
    needed = local_dependencies([ROOT / 'scripts/run_frontier_v6k.py', ROOT / 'scripts/score_frontier_v6k.py'])
    require({p.relative_to(ROOT).as_posix() for p in needed} <= set(inventory), 'missing_execution_dependency')
    require(frozen['preflight_path'] in inventory and read(checked_path(frozen['preflight_path']))['passed'] is True,
        'passed_preflight_required')
    for row in frozen['files']:
        path = checked_path(row['path'])
        require(path.stat().st_size == row['bytes'] and sha(path) == row['sha256'],
            'frozen_dependency_changed: ' + row['path'])
    slots = read(ROOT / SESSIONS)
    require(len(slots) == 1800 and sha(ROOT / SESSIONS) == frozen['sessions_file_sha256'], 'sessions_changed')
    require(sha(ROOT / BASELINE_LEDGER) == frozen['baseline_sha256'], 'baseline_changed')
    continuation_integrity(slots)
    verify_execution_manifest(ROOT / FREEZE, expected, slots)
    return slots


async def execute(expected):
    require(datetime.now(timezone.utc) < DEADLINE, 'delivery_buffer_reached')
    slots = verify_frozen(expected)
    fresh_destination()
    key = sys.stdin.readline().strip()
    require(isinstance(key, str) and len(key) >= 8 and not any(c.isspace() for c in key), 'invalid_credential')
    require(datetime.now(timezone.utc) < DEADLINE, 'delivery_buffer_reached')
    # Reauthenticate after stdin wait. The exclusive new budget directory prevents
    # two launchers from passing freshness checks and opening separate runs.
    verify_frozen(expected); fresh_destination()
    (ROOT / LEDGER).mkdir(parents=True, exist_ok=False)
    ledger = None
    try:
        ledger = RollingLedger(ROOT / LEDGER, baseline_path=ROOT / BASELINE_LEDGER)
        async with AiohttpTransport(key, 180, 1) as transport:
            return await run_slots(slots, api_key=key, output_dir=ROOT / OUTPUT,
                ledger=ledger, transport=transport, execution_manifest_path=ROOT / FREEZE,
                execution_manifest_sha256=expected, timeout_seconds=180,
                stop_file=ROOT / BASE / 'STOP')
    finally:
        if ledger is not None:
            ledger.close()
        key = None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--freeze', action='store_true')
    action.add_argument('--execute-sha256')
    args = parser.parse_args()
    if args.freeze:
        output = freeze()
    elif args.execute_sha256:
        output = asyncio.run(execute(args.execute_sha256))
    else:
        output = {'planned_slots': 1800, 'runtime': RUNTIME_CONFIG, 'paid_calls': 0}
    print(json.dumps(output, ensure_ascii=False, indent=2))
