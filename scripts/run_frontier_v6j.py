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
from retrace.adaption_v6j import (AiohttpTransport, BASELINE, BASELINE_LEDGER,
    DEADLINE, RUNTIME_CONFIG, RollingLedger, digest, require, run_slots,
    verify_execution_manifest, verify_prior_ledger)
from retrace.frontier_v6i_eval import design as validate_design
from scripts.build_frontier_v6i_sessions import build, SOURCE_PATHS
from scripts.run_frontier_v6h import verify_corpus
from scripts.score_frontier_v6h import local_dependencies

AUTH = 'data/frontier-v6j-authorization.json'
AUTH_SHA = 'ee99ff30ae9befb44692da7a6d04b7f2010c40174275b81068348d7df4593770'
FREEZE = 'data/frontier-v6j-freeze.json'
SESSIONS = 'data/frontier-v6i-sessions.json'
DESIGN = 'data/frontier-v6i-design.json'
CONTINUATION = 'data/frontier-v6j-continuation.json'
CONTINUATION_SHA = '89310028826c19aee5393e4f38ba236062aaeb0db8dc434306164997ff00eba4'
OBSERVED_ROUTES = {'qwen3.5-397b': 'qwen3.5-397b-a17b-nvfp4'}
BASE = 'results/frontier-v6j'
OUTPUT = BASE + '/continuation'
LEDGER = BASE + '/budget'
TESTS = ('tests.test_adaption_v6j', 'tests.test_frontier_v6i_sessions',
    'tests.test_frontier_v6j_eval', 'tests.test_frontier_v6j_driver',
    'tests.test_frontier_v6j_runtime_audit', 'tests.test_frontier_v6i_runtime_audit',
    'tests.test_frontier_v6i_eval', 'tests.test_score_frontier_v6j')
NEW_FILES = (AUTH, SESSIONS, DESIGN, CONTINUATION, 'requirements-v6j.txt',
    'scripts/authorize_frontier_v6j.py', 'scripts/build_frontier_v6i_sessions.py',
    'scripts/run_frontier_v6j.py', 'scripts/score_frontier_v6j.py',
    'tests/test_score_frontier_v6j.py',
    'retrace/adaption_v6j.py', 'retrace/frontier_v6j_eval.py',
    'scripts/audit_frontier_v6j_runtime.py', 'scripts/audit_frontier_v6i_runtime.py',
    'tests/test_frontier_v6j_runtime_audit.py', 'tests/test_frontier_v6i_runtime_audit.py',
    'tests/test_adaption_v6j.py', 'tests/test_frontier_v6i_sessions.py',
    'tests/test_frontier_v6j_eval.py', 'tests/test_frontier_v6j_driver.py',
    'research/frontier-v6j-continuation-protocol.md', 'research/frontier-v6j-report-amendment.md',
    'research/frontier-v6j-runtime-review.md', 'research/frontier-v6j-scoring-review.md')


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
    require(len(auth['protected']) == 1035 and auth['protected_v5_file_count'] == 402,
        'historical_inventory_changed')
    require(auth['cumulative_cap_credits'] == '250' and
        auth['historical_conservative_carry_credits'] == BASELINE, 'authorization_budget')
    for relative, expected in auth['protected'].items():
        require(sha(checked_path(relative)) == expected, 'historical_dependency_changed: ' + relative)
    require(not (ROOT / 'results/frontier-v6h/budget/active.lock').exists(), 'old_ledger_locked')
    require(not (ROOT / 'results/frontier-v6i/budget/active.lock').exists(), 'interrupted_ledger_locked')
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
    issued = receipt['permanently_excluded_issued_slot_ids']
    require(len(issued) == len(set(issued)) == 6, 'carryover_six_unique_slots')
    remaining = [s['slot_id'] for s in slots if s['slot_id'] not in issued]
    require(len(remaining) == 1794 and remaining == receipt['continuation_slot_ids'], 'unissued_only_continuation')
    for name, expected in receipt['prior_journal_files'].items():
        require(sha(checked_path(name)) == expected, 'carryover_journal_changed')
    final_path = ROOT / 'results/frontier-v6i/primary/slot-outcomes.jsonl'
    finals = [json.loads(line) for line in final_path.read_text(encoding='utf-8').splitlines()]
    selected = [row for row in finals if row['issued']]
    require([row['slot_id'] for row in selected] == issued, 'carryover_issued_selection')
    require(len(receipt['carryover_rows']) == 6, 'carryover_source_count')
    require([binding['slot_id'] for binding in receipt['carryover_rows']] == issued,
        'carryover_binding_order_or_duplicate')
    for binding in receipt['carryover_rows']:
        require(binding['source_path'] == 'results/frontier-v6i/primary/slot-outcomes.jsonl', 'carryover_source_path')
        require(type(binding['source_line_one_based']) is int and
            1 <= binding['source_line_one_based'] <= len(finals), 'carryover_positive_source_line')
        row = finals[binding['source_line_one_based'] - 1]
        require(row['issued'] is True and row['slot_id'] == binding['slot_id'] and digest(row) == binding['row_sha256'], 'carryover_source_row_changed')
    require(len(receipt['failed_producer_descendant_slot_ids']) == 2, 'failed_producer_skip_contract')
    return receipt


def freeze():
    require(not (ROOT / FREEZE).exists(), 'freeze_already_exists')
    require(datetime.now(timezone.utc) < DEADLINE, 'delivery_buffer_reached')
    fresh_destination()
    auth = historical_integrity()
    slots = scientific_integrity()
    continuation_integrity(slots)
    paths = {checked_path(name) for name in (*auth['protected'], *NEW_FILES)}
    paths |= local_dependencies([ROOT / 'scripts/run_frontier_v6j.py',
        ROOT / 'scripts/score_frontier_v6j.py'])
    before = {path: sha(path) for path in paths}
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromNames(TESTS))
    preflight = ROOT / f'results/frontier-v6j-preflight-{uuid.uuid4().hex}.json'
    write_new(preflight, {'schema': 'retrace.frontier-v6j-preflight.v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'passed': result.wasSuccessful(),
        'tests_run': result.testsRun, 'tests': list(TESTS), 'paid_calls': 0,
        'python': sys.version, 'aiohttp': importlib.metadata.version('aiohttp'),
        'log': capture.getvalue(),
        'scope': 'Continuation runtime, lossless composite closure, driver and unchanged scientific grading regressions. Original stopped segment remains stopped.'})
    require(result.wasSuccessful(), 'preflight_failed: ' + str(preflight))
    for path, expected in before.items():
        require(sha(path) == expected, 'dependency_changed_during_preflight')
    historical_integrity(); fresh_destination()
    paths.add(preflight)
    files = [{'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p), 'bytes': p.stat().st_size}
        for p in sorted(paths)]
    manifest = {'schema': 'retrace.frontier-v6j-freeze.v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'files': files,
        'sessions_path': SESSIONS, 'sessions_sha256': digest(slots),
        'sessions_file_sha256': sha(ROOT / SESSIONS), 'study_path': DESIGN,
        'scheduled_slots': 1800, 'continuation_slots': 1794, 'carried_issued_slots': 6,
        'continuation_path': CONTINUATION, 'continuation_sha256': CONTINUATION_SHA,
        'observed_response_models': OBSERVED_ROUTES, 'runtime_config': RUNTIME_CONFIG,
        'deadline_utc': DEADLINE.isoformat(), 'output_path': OUTPUT, 'ledger_path': LEDGER,
        'baseline_path': BASELINE_LEDGER, 'baseline_sha256': sha(ROOT / BASELINE_LEDGER),
        'historical_conservative_carry_credits': BASELINE, 'cumulative_cap_credits': '250',
        'authorization_path': AUTH, 'authorization_sha256': AUTH_SHA,
        'preflight_path': preflight.relative_to(ROOT).as_posix(),
        'scope': 'Explicit continuation amendment after observed provider route mismatch. Same 1800 scientific slots; six issued originals excluded permanently, 1794 continuation outcomes. No original failure is rescued and no halted ledger is reopened.'}
    write_new(ROOT / FREEZE, manifest)
    verify_execution_manifest(ROOT / FREEZE, sha(ROOT / FREEZE), slots)
    return {'path': FREEZE, 'sha256': sha(ROOT / FREEZE), 'files': len(files),
        'offline_tests': result.testsRun, 'planned_slots': len(slots), 'paid_calls': 0}


def verify_frozen(expected):
    require(sha(ROOT / FREEZE) == expected, 'freeze_changed')
    frozen = read(ROOT / FREEZE)
    require(frozen['schema'] == 'retrace.frontier-v6j-freeze.v1', 'freeze_schema')
    fixed = {'sessions_path': SESSIONS, 'study_path': DESIGN, 'output_path': OUTPUT,
        'ledger_path': LEDGER, 'baseline_path': BASELINE_LEDGER, 'scheduled_slots': 1800,
        'continuation_path': CONTINUATION, 'continuation_sha256': CONTINUATION_SHA,
        'observed_response_models': OBSERVED_ROUTES, 'continuation_slots': 1794, 'carried_issued_slots': 6,
        'authorization_path': AUTH, 'authorization_sha256': AUTH_SHA,
        'cumulative_cap_credits': '250', 'historical_conservative_carry_credits': BASELINE}
    require(all(frozen.get(k) == v for k, v in fixed.items()), 'freeze_fixed_contract')
    require(len({r['path'] for r in frozen['files']}) == len(frozen['files']), 'duplicate_frozen_file')
    inventory = {row['path']: row for row in frozen['files']}
    auth = historical_integrity()
    require(set(auth['protected']) | set(NEW_FILES) <= set(inventory), 'incomplete_freeze_inventory')
    needed = local_dependencies([ROOT / 'scripts/run_frontier_v6j.py', ROOT / 'scripts/score_frontier_v6j.py'])
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
