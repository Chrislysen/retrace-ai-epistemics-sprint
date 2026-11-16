"""Preserve interrupted v6i and declare only never-issued continuation slots."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FREEZE = 'data/frontier-v6i-freeze.json'
FREEZE_SHA = '156173e0dabc3a6f88c4301847f892f16bd6d0d73fd7c83c6d3dfc64b3a3a600'
RUN = 'results/frontier-v6i/primary'
SNAPSHOT = 'data/frontier-v6i-ledger-after-study.jsonl'
PINS = {
    SNAPSHOT: '899d54ea6c6780ecf4474abef51ba97b3b7068483c998f7babfa8dd8c44185d1',
    'results/frontier-v6i/budget/ledger.jsonl': '899d54ea6c6780ecf4474abef51ba97b3b7068483c998f7babfa8dd8c44185d1',
    RUN+'/run.json': 'd80059a34ca4f339e2ec4609d58dd131d9c9a8fc26cf979fc09eaf0d54f613ec',
    RUN+'/requests.jsonl': '60de2aaad489dc4fb605e5b8d988566bac86758ff8bec8c9641c9f057ccd9664',
    RUN+'/responses.jsonl': 'aae4b303b3058fce795d3dd567f96e626f975359b294bb37c80b184eb01af0fc',
    RUN+'/slot-outcomes.jsonl': '996921f104f96e105b5326d1f7112e96203ef8e23e4474ca14aef023d243356e',
    RUN+'/summary.json': '6c81a01452243f45246dd65fc7b1e2c8cd4d7eed91d1ff9cd335f8e6d094dc14',
}


def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))


def hash_file(path):
    h = sha256()
    with (ROOT/path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def check(ok, reason):
    if not ok:
        raise ValueError(reason)


def build():
    check(hash_file(FREEZE) == FREEZE_SHA, 'prior freeze changed')
    frozen = read(FREEZE)
    protected = {row['path']: row['sha256'] for row in frozen['files']}
    protected[FREEZE] = FREEZE_SHA
    protected.update(PINS)
    for path in (ROOT/RUN).rglob('*'):
        if path.is_file():
            name = path.relative_to(ROOT).as_posix()
            expected = hash_file(name)
            check(name not in protected or protected[name] == expected, 'closed journal changed')
            protected[name] = expected
    protected['results/frontier-v6i/console.log'] = hash_file('results/frontier-v6i/console.log')
    for name, expected in protected.items():
        target = (ROOT/name).resolve()
        check(target.is_relative_to(ROOT.resolve()) and target.is_file(), 'escaping prior path')
        check(hash_file(name) == expected, 'protected bytes changed: '+name)
    check(not (ROOT/'results/frontier-v6i/budget/active.lock').exists(), 'prior worker still active')
    summary = read(RUN+'/summary.json')
    audit = read(RUN+'/runtime-audit.json')
    check(audit['passed'] is True and audit['final_closed'] is True and audit['schedule_status'] == 'stopped', 'closed stopped audit required')
    check(summary['status'] == 'stopped' and summary['stop_reasons'] == ['response_model_mismatch'], 'unexpected interruption')
    check(summary['issued_attempts'] == summary['issued_slots'] == 6 and summary['completed'] == 5 and summary['retries'] == 0, 'fixed initial observations')
    check(summary['budget']['accounted_credits'] == '47.653269434', 'full conservative carry changed')
    rows = lambda name: [json.loads(line) for line in (ROOT/RUN/name).read_text(encoding='utf-8').splitlines()]
    requests, responses, outcomes = [rows(name) for name in ('requests.jsonl', 'responses.jsonl', 'slot-outcomes.jsonl')]
    issued = [row['slot_id'] for row in requests]
    check(len(set(issued)) == 6 and [r['slot_id'] for r in responses] == issued, 'six unique observations required')
    bad = [r for r in responses if r['error'] is not None]
    check(len(bad) == 1 and bad[0]['model'] == 'qwen3.5-397b' and bad[0]['error'] == 'response_model_mismatch', 'unexpected failed endpoint')
    observed = json.loads(bad[0]['raw_response'])
    check(observed['model'] == 'qwen3.5-397b-a17b-nvfp4' and observed['status'] == 'completed', 'unexpected observed route')
    slots = read(frozen['sessions_path'])
    remaining = [s['slot_id'] for s in slots if s['slot_id'] not in issued]
    check(len(slots) == 1800 and len(remaining) == 1794, 'continuation denominator')
    carry_rows = [{'slot_id': row['slot_id'], 'source_path': RUN+'/slot-outcomes.jsonl',
        'source_line_one_based': i, 'row_sha256': digest(row), 'attempt_id': row['attempt_id'],
        'model_outcome': row['model_outcome']} for i, row in enumerate(outcomes, 1) if row['issued']]
    check(len(carry_rows) == 6 and [r['slot_id'] for r in carry_rows] == issued, 'carryover source binding')
    blocked = {bad[0]['slot_id']}
    descendants = []
    for slot in slots:
        dependencies = slot.get('history_from', []) + ([slot['input_from']['slot_id']] if slot.get('input_from') else [])
        if slot['slot_id'] in remaining and any(d in blocked for d in dependencies):
            blocked.add(slot['slot_id']); descendants.append(slot['slot_id'])
    check(len(descendants) == 2, 'failed producer descendants changed')
    common = {'created_at': datetime.now(timezone.utc).isoformat(),
        'prior_freeze_path': FREEZE, 'prior_freeze_sha256': FREEZE_SHA,
        'baseline_snapshot_path': SNAPSHOT, 'baseline_snapshot_sha256': PINS[SNAPSHOT],
        'historical_conservative_carry_credits': '47.653269434', 'cumulative_cap_credits': '250',
        'deadline_utc': '2026-11-16T03:55:00+00:00'}
    continuation = {'schema': 'retrace.frontier-v6j-continuation.v1', **common,
        'sessions_path': frozen['sessions_path'], 'sessions_sha256': digest(slots),
        'original_run_id': summary['run_id'], 'full_planned_slots': 1800,
        'carried_issued_slots': 6, 'continuation_slots': 1794,
        'permanently_excluded_issued_slot_ids': issued, 'continuation_slot_ids': remaining,
        'failed_producer_descendant_slot_ids': descendants, 'carryover_rows': carry_rows,
        'prior_journal_files': PINS,
        'observed_response_models': {'qwen3.5-397b': 'qwen3.5-397b-a17b-nvfp4'},
        'route_evidence': {'requested_model': 'qwen3.5-397b', 'reported_model': observed['model'],
            'original_attempt_id': bad[0]['attempt_id'], 'original_response_row_sha256': digest(bad[0]),
            'vendor_alias_mapping_documented': False, 'weight_identity_verified': False,
            'scope': 'Observed provider route, pinned prospectively only. Original mismatch remains failed, unrescored, fully reserved and never retried.',
            'api_field_documentation': 'https://docs.adaptionlabs.ai/api/resources/responses/methods/create',
            'related_quantized_checkpoint_card': 'https://huggingface.co/nvidia/Qwen3.5-397B-A17B-NVFP4',
            'checkpoint_attribution': 'The named public checkpoint demonstrates NVFP4 is a distinct quantized variant; it does not identify the provider implementation or vendor.'},
        'scope': 'Same scientific cohort and prompts. Only never-issued slots may be dispatched. Both source segments remain immutable; a separately identified composite view preserves all issued observations and failures.'}
    auth = {'schema': 'retrace.frontier-v6j-authorization.v1', **common,
        'protected_v5_file_count': 402, 'protected': dict(sorted(protected.items())),
        'prior_status': 'stopped', 'prior_stop_reason': 'response_model_mismatch',
        'prior_issued_attempts': 6, 'prior_settled_attempts': 5, 'prior_retained_attempts': 1,
        'inherited_unsettled_attempts': 17,
        'authorization_basis': 'User authorized autonomous completion, reduced secondary coverage within1800, no silent retries, unchanged historical files and cumulative250-credit cap. This transport correction does not reissue any prior observation or change scientific inputs.',
        'scope': 'New separately frozen execution amendment; no resumption or mutation of halted ledgers and no claim that originalv6i completed.'}
    return auth, continuation


if __name__ == '__main__':
    values = build()
    paths = ['data/frontier-v6j-authorization.json', 'data/frontier-v6j-continuation.json']
    check(not any((ROOT/name).exists() for name in paths), 'exclusive new authorization required')
    for name, value in zip(paths, values):
        with (ROOT/name).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'files': {name: hash_file(name) for name in paths},
        'protected_files': len(values[0]['protected']), 'carried_issued': 6, 'continuation_slots': 1794,
        'expected_failed_producer_skips': 2, 'paid_calls': 0}))
