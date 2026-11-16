"""Freeze preservation and exact untouched-slot complement after two closed segments."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIOR_FREEZE = 'data/frontier-v6j-freeze.json'
PRIOR_FREEZE_SHA = '6fffc08ce31ac6aa19079be690a244a0e9b649d4a6281f7df8d53038c3811ea0'
SNAPSHOT = 'data/frontier-v6j-ledger-after-continuation.jsonl'
SNAPSHOT_SHA = '92b06e40498d0a4a8950d3976e8933ad39e3c563a56b32d544a8e7e59558d6e0'
BASELINE = '80.145946577'


def read(name): return json.loads((ROOT / name).read_text(encoding='utf-8'))
def digest(value): return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
def check(ok, reason):
    if not ok: raise ValueError(reason)


def hash_file(name):
    p = (ROOT / name).resolve()
    check(p.is_relative_to(ROOT.resolve()) and p.is_file(), 'invalid protected path')
    h = sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''): h.update(chunk)
    return h.hexdigest()


def build():
    check(hash_file(PRIOR_FREEZE) == PRIOR_FREEZE_SHA, 'prior freeze changed')
    check(hash_file(SNAPSHOT) == SNAPSHOT_SHA, 'closed snapshot changed')
    frozen = read(PRIOR_FREEZE)
    protected = {r['path']: r['sha256'] for r in frozen['files']}
    protected.update({PRIOR_FREEZE: PRIOR_FREEZE_SHA, SNAPSHOT: SNAPSHOT_SHA})
    # Every prior result, raw stream and additive offline/release scaffold is
    # preserved before any future inference. No old path is an output target.
    extras = [ROOT/'results/frontier-v6j', ROOT/'results/frontier-v6j-offline', ROOT/'report/v6j-study']
    for base in extras:
        if base.exists():
            for p in base.rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:
                    name = p.relative_to(ROOT).as_posix(); actual = hash_file(name)
                    check(name not in protected or protected[name] == actual, 'closed bytes changed')
                    protected[name] = actual
    for pattern in ('scripts/*v6j*.py', 'retrace/*v6j*.py', 'tests/*v6j*.py', 'research/*v6j*.md', 'README-V6J.md', 'REPRODUCE-V6J.md', 'START-V6J.ps1'):
        for p in ROOT.glob(pattern):
            name = p.relative_to(ROOT).as_posix(); actual = hash_file(name)
            check(name not in protected or protected[name] == actual, 'protected helper changed')
            protected[name] = actual
    for name, expected in protected.items(): check(hash_file(name) == expected, 'protected changed: '+name)
    for version in ('i', 'j'):
        check(not (ROOT/f'results/frontier-v6{version}/budget/active.lock').exists(), 'prior worker still active')
    slots = read('data/frontier-v6i-sessions.json'); index = {s['slot_id']: s for s in slots}
    check(len(slots) == len(index) == 1800, 'scientific denominator')
    segments = []; bindings = []; issued = []; finals = {}; completed = set(); prior_files = {}
    for version, directory, expected_finals, expected_issued, expected_reason in (
        ('i', 'results/frontier-v6i/primary', 6, 6, 'response_model_mismatch'),
        ('j', 'results/frontier-v6j/continuation', 218, 207, 'network_or_transport_failure')):
        paths = {role: directory+'/'+name for role, name in {
            'run_manifest':'run.json', 'requests':'requests.jsonl', 'responses':'responses.jsonl',
            'outcomes':'slot-outcomes.jsonl', 'summary':'summary.json', 'audit':'runtime-audit.json'}.items()}
        paths['ledger'] = f'results/frontier-v6{version}/budget/ledger.jsonl'
        hashes = {role: hash_file(name) for role, name in paths.items()}
        prior_files.update({name: hashes[role] for role, name in paths.items()})
        summary = read(paths['summary']); audit = read(paths['audit'])
        check(summary['status'] == 'stopped' and summary['stop_reasons'] == [expected_reason], 'prior closure changed')
        check(audit['passed'] is True and audit['final_closed'] is True and audit['schedule_status'] == 'stopped', 'closed audited segment required')
        rows = lambda role: [json.loads(x) for x in (ROOT/paths[role]).read_text(encoding='utf-8').splitlines()]
        requests, responses, outcomes = [rows(role) for role in ('requests','responses','outcomes')]
        check(len(requests) == len(responses) == summary['issued_attempts'] == summary['issued_slots'] == expected_issued and summary['retries'] == 0, 'fixed observed attempt counts')
        check([r['slot_id'] for r in requests] == [r['slot_id'] for r in responses], 'closed request response pairing')
        segment_issued = [r['slot_id'] for r in requests]
        check(len(set(segment_issued)) == expected_issued and not set(segment_issued)&set(issued), 'duplicate issued slot')
        issued.extend(segment_issued)
        selected = 0
        for line, row in enumerate(outcomes, 1):
            sid = row['slot_id']
            check(sid in index and sid not in finals, 'overlapping or unknown old outcome')
            if row['model_outcome'] == 'not_issued_global_stop':
                check(row['issued'] is False and row['attempts_issued'] == 0, 'invalid administrative placeholder')
                continue
            check(row['issued'] is True or (row['issued'] is False and row['model_outcome'] == 'not_issued_dependency_failed' and row['attempts_issued'] == 0), 'invalid definitive outcome')
            finals[sid] = row; selected += 1
            if row['model_outcome'] == 'completed' and row['terminal_valid'] is True: completed.add(sid)
            bindings.append({'segment': version, 'slot_id': sid, 'source_path': paths['outcomes'],
                'source_line_one_based': line, 'row_sha256': digest(row), 'attempt_id': row.get('attempt_id'), 'model_outcome': row['model_outcome']})
        check(selected == expected_finals, 'fixed definitive count')
        old_freeze = f'data/frontier-v6{version}-freeze.json'
        segments.append({'segment': version, 'run_id': summary['run_id'], 'freeze_path': old_freeze,
            'freeze_sha256': hash_file(old_freeze), 'paths': paths, 'sha256': hashes,
            'definitive_final_slots': selected, 'issued_slots': expected_issued})
    check(len(finals) == 224 and len(issued) == 213, 'combined old denominator')
    remaining = [s['slot_id'] for s in slots if s['slot_id'] not in finals]
    unavailable = set(finals)-completed; descendants = []
    # Fixed schedule is topological; retain all already-finalized skips and
    # propagate unavailable producer outcomes without using partial output.
    for s in slots:
        deps = s.get('history_from', []) + ([s['input_from']['slot_id']] if s.get('input_from') else [])
        if s['slot_id'] not in finals and any(d in unavailable for d in deps):
            unavailable.add(s['slot_id']); descendants.append(s['slot_id'])
    check(len(remaining) == 1576, 'untouched complement')
    check(read(segments[-1]['paths']['summary'])['budget']['accounted_credits'] == BASELINE, 'conservative carry')
    prior_files[SNAPSHOT] = SNAPSHOT_SHA
    prior_files['data/frontier-v6i-ledger-after-study.jsonl'] = hash_file('data/frontier-v6i-ledger-after-study.jsonl')
    check(hash_file(segments[-1]['paths']['ledger']) == SNAPSHOT_SHA, 'snapshot and journal differ')
    common = {'created_at': datetime.now(timezone.utc).isoformat(), 'prior_freeze_path': PRIOR_FREEZE,
        'prior_freeze_sha256': PRIOR_FREEZE_SHA, 'baseline_snapshot_path': SNAPSHOT,
        'baseline_snapshot_sha256': SNAPSHOT_SHA, 'historical_conservative_carry_credits': BASELINE,
        'cumulative_cap_credits':'250', 'deadline_utc':'2026-11-16T03:55:00+00:00'}
    receipt = {'schema':'retrace.frontier-v6k-continuation.v1', **common,
        'sessions_path':'data/frontier-v6i-sessions.json', 'sessions_sha256':digest(slots),
        'original_run_id':segments[0]['run_id'], 'original_run_ids':[s['run_id'] for s in segments],
        'full_planned_slots':1800, 'carried_issued_slots':213, 'carried_final_slots':224, 'continuation_slots':1576,
        'source_segments':segments, 'carried_final_outcomes':bindings,
        'permanently_excluded_issued_slot_ids':issued, 'permanently_excluded_final_slot_ids':list(finals),
        'continuation_slot_ids':remaining, 'failed_producer_descendant_slot_ids':descendants,
        'prior_journal_files':prior_files, 'observed_response_models':{'qwen3.5-397b':'qwen3.5-397b-a17b-nvfp4'},
        'scope':'Only untouched slots continue. All issued outcomes and finalized dependency failures remain byte-exact. The original generic transport failure stays global in its original segment; its exception class is unknown. No source response or scientific estimand is revised.'}
    auth = {'schema':'retrace.frontier-v6k-authorization.v1', **common,
        'protected_v5_file_count':402, 'protected':dict(sorted(protected.items())),
        'prior_status':'stopped', 'prior_stop_reason':'network_or_transport_failure',
        'prior_issued_attempts':207, 'prior_settled_attempts':160, 'prior_retained_attempts':47,
        'inherited_unsettled_attempts':64,
        'authorization_basis':'User authorized autonomous completion within1800 scientific slots, single global paced worker, unchanged historical files, no silent retries and250-credit cumulative cap. Prospective typed post-header transport failures do not reissue old calls or reinterpret the prior generic failure.',
        'scope':'Separate additive continuation freeze; historical stopped ledgers remain stopped.'}
    return auth, receipt


if __name__ == '__main__':
    paths = ['data/frontier-v6k-authorization.json', 'data/frontier-v6k-continuation.json']
    check(not any((ROOT/name).exists() for name in paths), 'exclusive new authorization required')
    auth, receipt = build()
    for name, value in zip(paths, (auth, receipt)):
        with (ROOT/name).open('x', encoding='utf-8', newline='\n') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False); f.write('\n')
    print(json.dumps({'files':{name:hash_file(name) for name in paths}, 'protected_files':len(auth['protected']),
        'carried_final_slots':224,'carried_issued_slots':213,'continuation_slots':1576,
        'expected_failed_producer_skips':len(receipt['failed_producer_descendant_slot_ids']), 'paid_calls':0}))
