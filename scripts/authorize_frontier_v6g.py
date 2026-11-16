"""Record the authorized250-credit continuation after the disclosed f stop.

No provider access, credential handling, old-file mutation or reservation release.
The runner independently replays accounting before every execution phase.
"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    destination = ROOT / 'data/frontier-v6g-authorization.json'
    if destination.exists():
        raise ValueError('Authorization already exists')
    previous = json.loads((ROOT / 'data/frontier-v6f-primary-freeze.json').read_text(encoding='utf-8'))
    protected = {}
    for row in previous['files']:
        relative = row['path']
        if sha(ROOT / relative) != row['sha256']:
            raise ValueError('Frozen historical file changed: ' + relative)
        protected[relative] = row['sha256']
    closure_path = 'data/frontier-v6f-manual-closure.json'
    closure = json.loads((ROOT / closure_path).read_text(encoding='utf-8'))
    if (closure['issued_primary_requests'] != 0 or closure['outstanding_reservations_before_stop'] != 0
            or closure['issued_regression_requests'] != 38 or closure['recorded_responses'] != 38
            or closure['journals_unchanged_after_stop'] is not True):
        raise ValueError('Historical idle closure differs')
    for row in closure['preserved'].values():
        if sha(ROOT / row['path']) != row['sha256']:
            raise ValueError('Closed journal changed')
    paths = {
        closure_path, 'data/frontier-v6f-primary-freeze.json',
        'scripts/close_idle_frontier_v6f.py', 'data/natural-ensemble-v6-freeze.json',
        'data/natural-ensemble-v6-dispatch-prefix.jsonl',
    }
    paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'results/frontier-v6f').rglob('*') if p.is_file())
    supplement = json.loads((ROOT / 'data/natural-ensemble-v6-freeze.json').read_text(encoding='utf-8'))
    for row in supplement['files']:
        if sha(ROOT / row['path']) != row['sha256']:
            raise ValueError('Frozen supplemental analysis changed')
        paths.add(row['path'])
    for relative in sorted(paths):
        observed = sha(ROOT / relative)
        if relative in protected and protected[relative] != observed:
            raise ValueError('Historical preservation conflict')
        protected[relative] = observed
    earlier = []
    for version, expected in [
        ('c', 'b176a2b610f4ac21fcdbb3202a0aa5bf3cc9a58159258c0fa33bcd982d4e5d76'),
        ('d', '5b3c4c99fcc373c998e2e93def456eb29864ecf65786974a42dbb7c5b5c35439'),
        ('e', '7e49f85ab98be0e694a4835c7814484e8ad58b701b6b18e502ec4918199da5ff'),
    ]:
        relative = f'results/frontier-v6{version}/budget/ledger.jsonl'
        if sha(ROOT / relative) != expected:
            raise ValueError('Earlier ledger changed')
        earlier.append({'path': relative, 'sha256': expected})
    carry = '43.633207445'
    value = {
        'schema': 'retrace.frontier-v6g-authorization.v1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'cumulative_cap_credits': '250', 'historical_conservative_carry_credits': carry,
        'remaining_before_new_calls_credits': str(Decimal('250') - Decimal(carry)),
        'user_reported_account_balance_credits': '2249.838', 'balance_verified': False,
        'prior_ledger_path': closure['preserved']['ledger']['path'],
        'prior_ledger_sha256': closure['preserved']['ledger']['sha256'],
        'manual_closure_path': closure_path, 'manual_closure_sha256': sha(ROOT / closure_path),
        'earlier_ledgers': earlier,
        'inherited_unknown_full_reservations_retained': 7,
        'historical_primary_calls': 0, 'historical_f_regression_calls': 38,
        'note': 'The user authorized250 cumulative credits. All prior issued outcomes and seven unknown full bounds are retained. The f primary was never issued; its administrative closure is explicit and is not a normal runner completion. New g canary and development regression precede a separately frozen primary schedule.',
        'protected': dict(sorted(protected.items())),
    }
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'path': destination.relative_to(ROOT).as_posix(), 'sha256': sha(destination),
                      'protected_files': len(protected), 'carry': carry}))


if __name__ == '__main__':
    main()
