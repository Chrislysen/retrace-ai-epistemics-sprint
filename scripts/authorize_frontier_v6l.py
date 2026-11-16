"""Admit only untouched slots after an audited v6k cumulative-budget stop.

Read-only until the CLI exclusively creates the two new authorization files.
The explicit 750-credit authorization never changes the running k ledger.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_frontier_v6k_runtime import audit as replay_k

PRIOR_FREEZE = 'data/frontier-v6k-freeze.json'
PRIOR_FREEZE_SHA = '274d3101ed47e3ca918ee1e2273c0cdd269b43c60567e3fa4e121f6a7b9efa40'
SNAPSHOT = 'data/frontier-v6k-ledger-after-continuation.jsonl'
AUDIT = 'results/frontier-v6k/continuation/runtime-audit.json'
SESSIONS = 'data/frontier-v6i-sessions.json'
AUTH = 'data/frontier-v6l-authorization.json'
RECEIPT = 'data/frontier-v6l-continuation.json'
DEADLINE = '2026-11-16T03:55:00+00:00'


def check(ok, reason):
    if not ok: raise ValueError(reason)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def path(name):
    p = (ROOT / name).resolve()
    check(p.is_relative_to(ROOT.resolve()) and p.is_file(), 'invalid protected path: '+name)
    return p


def read(name): return json.loads(path(name).read_text(encoding='utf-8'))


def hash_file(name):
    h = sha256()
    with path(name).open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''): h.update(chunk)
    return h.hexdigest()


def rows(name):
    raw = path(name).read_bytes()
    check(not raw or raw.endswith(b'\n'), 'partial journal: '+name)
    return [json.loads(line) for line in raw.splitlines()]


def verify_preservation(protected, prior_files, proof):
    """Recheck the same bytes after receipt construction and before publication."""
    for name, expected in protected.items():
        check(hash_file(name) == expected, 'protected changed before publication: '+name)
    for name, expected in prior_files.items():
        check(protected.get(name) == expected and hash_file(name) == expected,
            'journal not preserved by authorization: '+name)
    for name, binding in proof['input_bindings'].items():
        check(path(name).stat().st_size == binding['bytes'] and hash_file(name) == binding['sha256'],
            'audited input changed before publication: '+name)


def collect_segments(slots, specifications):
    """Derive the fixed complement; preserve retries and definitive skips."""
    index = {s['slot_id']: s for s in slots}
    check(len(index) == len(slots) == 1800, 'scientific denominator')
    segments = []; bindings = []; issued = []; finals = {}; completed = set(); prior_files = {}
    for version, directory, expected_reason in specifications:
        paths = {role: directory+'/'+name for role, name in {
            'run_manifest':'run.json', 'requests':'requests.jsonl', 'responses':'responses.jsonl',
            'outcomes':'slot-outcomes.jsonl', 'summary':'summary.json', 'audit':'runtime-audit.json'}.items()}
        paths['ledger'] = f'results/frontier-v6{version}/budget/ledger.jsonl'
        hashes = {role: hash_file(name) for role, name in paths.items()}
        prior_files.update({name: hashes[role] for role, name in paths.items()})
        summary, audit = read(paths['summary']), read(paths['audit'])
        check(summary['status'] == 'stopped' and summary['stop_reasons'] == [expected_reason], 'unauthorized prior stop')
        check(audit['passed'] is True and audit['final_closed'] is True and audit['schedule_status'] == 'stopped', 'closed audited segment required')
        requests, responses, outcomes = [rows(paths[role]) for role in ('requests', 'responses', 'outcomes')]
        qids, rids = [r['attempt_id'] for r in requests], [r['attempt_id'] for r in responses]
        check(len(qids) == len(set(qids)) == len(rids) == len(set(rids)) == summary['issued_attempts'] and qids == rids, 'closed request response pairing')
        segment_issued = list(dict.fromkeys(r['slot_id'] for r in requests))
        check(len(segment_issued) == summary['issued_slots'] and not set(segment_issued)&set(issued), 'duplicate issued slot')
        check(len(requests)-len(segment_issued) == summary['retries'], 'attempt count')
        pending = set(index)-set(finals)
        check(len(outcomes) == len(pending) and {r['slot_id'] for r in outcomes} == pending, 'old outcome inventory')
        issued.extend(segment_issued); selected = 0
        for line, row in enumerate(outcomes, 1):
            sid = row['slot_id']
            if row['model_outcome'] == 'not_issued_global_stop':
                check(row['issued'] is False and row['attempts_issued'] == 0 and sid not in segment_issued, 'issued placeholder forbidden')
                continue
            check(row['issued'] is True or (row['issued'] is False and row['model_outcome'] == 'not_issued_dependency_failed' and row['attempts_issued'] == 0), 'invalid definitive outcome')
            check((sid in segment_issued) == row['issued'], 'final issued mismatch')
            finals[sid] = row; selected += 1
            if row['model_outcome'] == 'completed' and row['terminal_valid'] is True: completed.add(sid)
            bindings.append({'segment':version, 'slot_id':sid, 'source_path':paths['outcomes'],
                'source_line_one_based':line, 'row_sha256':digest(row), 'attempt_id':row.get('attempt_id'), 'model_outcome':row['model_outcome']})
        freeze_path = f'data/frontier-v6{version}-freeze.json'
        segments.append({'segment':version, 'run_id':summary['run_id'], 'freeze_path':freeze_path,
            'freeze_sha256':hash_file(freeze_path), 'paths':paths, 'sha256':hashes,
            'definitive_final_slots':selected, 'issued_slots':len(segment_issued)})
    remaining = [s['slot_id'] for s in slots if s['slot_id'] not in finals]
    unavailable = set(finals)-completed; descendants = []
    for s in slots:
        deps = s.get('history_from', []) + ([s['input_from']['slot_id']] if s.get('input_from') else [])
        if s['slot_id'] not in finals and any(d in unavailable for d in deps):
            unavailable.add(s['slot_id']); descendants.append(s['slot_id'])
    check(remaining and len(remaining)+len(finals) == 1800, 'nonempty untouched complement required')
    return segments, bindings, issued, finals, remaining, descendants, prior_files


def build(*, snapshot_sha256, audit_sha256):
    for version in ('h','i','j','k'):
        check(not (ROOT/f'results/frontier-v6{version}/budget/active.lock').exists(), 'prior worker still active')
    check(datetime.now(timezone.utc) < datetime.fromisoformat(DEADLINE), 'delivery buffer reached')
    check(hash_file(PRIOR_FREEZE) == PRIOR_FREEZE_SHA, 'prior freeze changed')
    check(hash_file(SNAPSHOT) == snapshot_sha256 == hash_file('results/frontier-v6k/budget/ledger.jsonl'), 'closed snapshot changed')
    check(hash_file(AUDIT) == audit_sha256, 'closed audit changed')
    summary = read('results/frontier-v6k/continuation/summary.json')
    check(summary['status'] == 'stopped' and summary['stop_reasons'] == ['cumulative_budget_stop'], '750 authorization requires exact cumulative_budget_stop')
    proof = replay_k(ROOT, PRIOR_FREEZE_SHA, ledger_snapshot=SNAPSHOT)
    check(proof == read(AUDIT), 'independent k audit replay mismatch')
    budget = summary['budget']; carry = budget['accounted_credits']
    check(Decimal('80.145946577') <= Decimal(carry) <= Decimal('250') and proof['cumulative_accounted_credits'] == carry, 'conservative carry mismatch')
    check(budget['attempt_reservations'] == budget['settled_attempts'] + budget['unknown_429_attempts_retained'] + budget['unknown_operational_attempts_retained'], 'unresolved prior reservation')
    inherited = budget['cumulative_inherited_unsettled_attempts'] + budget['unsettled_attempts']
    protected = {r['path']:r['sha256'] for r in read(PRIOR_FREEZE)['files']}
    protected.update({PRIOR_FREEZE:PRIOR_FREEZE_SHA, SNAPSHOT:snapshot_sha256})
    candidates = []
    for base in (ROOT/'results/frontier-v6k', ROOT/'report/v6k-study', ROOT/'report/v6k-partial-study', ROOT/'web/v6k', ROOT/'web/v6k-partial'):
        if base.exists(): candidates.extend(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    for pattern in ('scripts/*v6k*.py','retrace/*v6k*.py','tests/*v6k*','research/*v6k*.md','README-V6K.md','REPRODUCE-V6K.md','START-V6K.ps1'):
        candidates.extend(p for p in ROOT.glob(pattern) if p.is_file())
    for p in candidates:
        name = p.relative_to(ROOT).as_posix(); actual = hash_file(name)
        check(name not in protected or protected[name] == actual, 'closed bytes changed: '+name)
        protected[name] = actual
    for name, expected in protected.items(): check(hash_file(name) == expected, 'protected changed: '+name)
    slots = read(SESSIONS)
    segments, bindings, issued, finals, remaining, descendants, prior_files = collect_segments(slots, (
        ('i','results/frontier-v6i/primary','response_model_mismatch'),
        ('j','results/frontier-v6j/continuation','network_or_transport_failure'),
        ('k','results/frontier-v6k/continuation','cumulative_budget_stop')))
    for name in ('data/frontier-v6i-ledger-after-study.jsonl','data/frontier-v6j-ledger-after-continuation.jsonl',SNAPSHOT): prior_files[name] = hash_file(name)
    common = {'created_at':datetime.now(timezone.utc).isoformat(), 'prior_freeze_path':PRIOR_FREEZE,
        'prior_freeze_sha256':PRIOR_FREEZE_SHA, 'baseline_snapshot_path':SNAPSHOT,
        'baseline_snapshot_sha256':snapshot_sha256, 'historical_conservative_carry_credits':carry,
        'previous_cumulative_cap_credits':'250', 'cumulative_cap_credits':'750',
        'inherited_unsettled_attempts':inherited, 'deadline_utc':DEADLINE}
    receipt = {'schema':'retrace.frontier-v6l-continuation.v1', **common,
        'sessions_path':SESSIONS, 'sessions_sha256':digest(slots), 'original_run_id':segments[0]['run_id'],
        'original_run_ids':[s['run_id'] for s in segments], 'full_planned_slots':1800,
        'carried_issued_slots':len(issued), 'carried_final_slots':len(finals), 'continuation_slots':len(remaining),
        'source_segments':segments, 'carried_final_outcomes':bindings,
        'permanently_excluded_issued_slot_ids':issued, 'permanently_excluded_final_slot_ids':list(finals),
        'continuation_slot_ids':remaining, 'failed_producer_descendant_slot_ids':descendants,
        'prior_journal_files':prior_files, 'observed_response_models':{'qwen3.5-397b':'qwen3.5-397b-a17b-nvfp4'},
        'scope':'Only never-issued nonfinalized slots continue after the audited k budget stop. All prior issued outcomes, definitive dependency skips, unknown costs and original scientific slots remain unchanged.'}
    auth = {'schema':'retrace.frontier-v6l-authorization.v1', **common,
        'protected_v5_file_count':402, 'protected':dict(sorted(protected.items())),
        'prior_status':'stopped', 'prior_stop_reason':'cumulative_budget_stop',
        'prior_issued_attempts':summary['issued_attempts'], 'prior_settled_attempts':budget['settled_attempts'],
        'prior_retained_attempts':budget['unsettled_attempts'],
        'authorization_basis':'The user expanded authorization to use what is needed from an approximately2000-credit account while preserving a buffer. The prospective cumulative ceiling is conservatively set to750, leaving1250 of that reported amount; this is not a verified balance. Only remaining unissued frozen slots after the unchanged k250-credit budget stop are admitted. The earlier unissued500-cap proposal is archived. Prior failures and unknown costs are never retried, replaced or released.',
        'scope':'Separate additive continuation freeze; unchanged serial pacing, deadlines, retry policy and scientific grading.'}
    verify_preservation(protected, prior_files, proof)
    return auth, receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot-sha256', required=True); p.add_argument('--audit-sha256', required=True)
    args = p.parse_args()
    check(not any((ROOT/name).exists() for name in (AUTH,RECEIPT)), 'exclusive new authorization required')
    auth, receipt = build(snapshot_sha256=args.snapshot_sha256, audit_sha256=args.audit_sha256)
    verify_preservation(auth['protected'], receipt['prior_journal_files'], read(AUDIT))
    for name, value in ((AUTH,auth),(RECEIPT,receipt)):
        with (ROOT/name).open('x',encoding='utf-8',newline='\n') as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False); f.write('\n')
    print(json.dumps({'files':{name:hash_file(name) for name in (AUTH,RECEIPT)},
        'protected_files':len(auth['protected']), 'carried_final_slots':receipt['carried_final_slots'],
        'continuation_slots':receipt['continuation_slots'], 'paid_calls':0}))


if __name__ == '__main__': main()
