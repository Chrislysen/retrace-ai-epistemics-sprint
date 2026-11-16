"""Bind unchanged historical artifacts and the user-authorized serial revision."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'data/frontier-v6i-authorization.json'
BASES={
 'data/frontier-v6h-canary-freeze.json':'6e7cec65992f4f3cc8012fe06d7d8dfbe9de472357ef6fdf6af95c8414e6f8ec',
 'data/frontier-v6h-paced-canary-freeze.json':'7fafe5ed48ad64c415800cf2a4fb9530e251867936db8a70e61ba2875ec517f6',
 'deliverables/retrace-v6h-release-manifest.json':'1704937500b9cabd6555b87eadb07170a120adc8d50fdd5c020af7f4054783b3',
 'deliverables/retrace-v6-transport-manifest.json':'49aa854080ec33d83c5de1fbb85c0562ae691586be72aa5d6fb80b80c28d613b',
}
PINS={
 'data/frontier-v6h-ledger-after-paced-canary.jsonl':'0f8e54bbe0a13fbf56f50e3c40b43578e63200ab02bba130b7f8c4eb704057f6',
 'results/frontier-v6h/budget/ledger.jsonl':'0f8e54bbe0a13fbf56f50e3c40b43578e63200ab02bba130b7f8c4eb704057f6',
 'deliverables/retrace-v5-sprint-artifact.zip':'dea620ccea3ca7afb7896c6d7a9ffa403c6186bda20035037997d86f3193a035',
 'deliverables/retrace-v6-sprint-artifact.zip':'3353795e3b379202bb3bf073648882e00831c884c8116a7e27fcc91a70097cfb',
 'deliverables/retrace-v6-transport-diagnostics.zip':'861efb6d593763112b711158b17d6d555d8dc01de9572990204791dfa9c7d2b9',
 'report/v4-cycle/RETRACE-research-draft.pdf':'387974d290d2aabbf3c4185399475b681a232ca0de5ce8ba27a60ad979be7f64',
 'report/v6-unified/RETRACE-v6h-unified-draft.pdf':'1f4f2dc44a2965aadc8c821a56bf7f810ea383ced893cd50085ac0b61414ecf1',
}

def digest(path):return sha256(Path(path).read_bytes()).hexdigest()
def checked_path(relative):
    target=(ROOT/relative).resolve()
    if not target.is_relative_to(ROOT.resolve()) or not target.is_file():raise ValueError('Invalid historical path: '+relative)
    return target

def build():
    protected={}
    def add(name,expected):
        path=checked_path(name)
        if digest(path)!=expected:raise ValueError('Historical bytes changed: '+name)
        if name in protected and protected[name]!=expected:raise ValueError('Conflicting historical hash')
        protected[name]=expected
    for name,expected in BASES.items():
        add(name,expected);manifest=json.loads((ROOT/name).read_text(encoding='utf-8'))
        inverse={v:k for k,v in manifest.get('frozen_aliases',{}).items()}
        for entry in manifest['files']:add(inverse.get(entry['path'],entry['path']),entry['sha256'])
    for name,expected in PINS.items():add(name,expected)
    baseline=json.loads((ROOT/'data/v6-baseline-preservation.json').read_text(encoding='utf-8'))
    for name,expected in baseline['protected'].items():add(name,expected)
    if len(baseline['protected'])!=402:raise ValueError('V5 protected inventory changed')
    snapshot=(ROOT/'data/frontier-v6h-ledger-after-paced-canary.jsonl').read_text(encoding='utf-8').splitlines()
    if len(snapshot)!=95 or json.loads(snapshot[-1])['sha256']!='57765aa545987f8219401c6d4650b1b693794eee020db6450b21e07847072a30':raise ValueError('Closed ledger snapshot mismatch')
    if (ROOT/'results/frontier-v6h/budget/active.lock').exists():raise ValueError('Prior provider run still locked')
    return {'schema':'retrace.frontier-v6i-authorization.v1','created_at':datetime.now(timezone.utc).isoformat(),
        'cumulative_cap_credits':'250','historical_conservative_carry_credits':'47.409962587',
        'remaining_before_new_calls_credits':'202.590037413','baseline_snapshot_path':'data/frontier-v6h-ledger-after-paced-canary.jsonl',
        'baseline_snapshot_sha256':PINS['data/frontier-v6h-ledger-after-paced-canary.jsonl'],
        'baseline_terminal_chain_sha256':'57765aa545987f8219401c6d4650b1b693794eee020db6450b21e07847072a30',
        'baseline_halted':True,'baseline_halt_reason':'timeout; preserved, not reset or resumed',
        'known_h_attempts':42,'known_h_settlements':33,'h_retained_429_attempts':8,'h_retained_timeout_attempts':1,
        'older_unknown_reservations_inside_carry':7,'protected_v5_file_count':402,
        'planned_study_slots':1800,'all_base_cases':60,'primary_models':5,'separate_diagnostic_model':'qwen3.5-397b',
        'user_resolution':'User explicitly prioritized1,800 calls and authorized reduced secondary coverage after count clarification.',
        'runtime_scope':'New serial worker: concurrency1, four seconds after each attempt, at least65 seconds after any429; no non429 retries. Independent slots continue after ordinary recorded provider failures; systemic/accounting/auth failures halt. No old run is reopened.',
        'deadline_utc':'2026-11-16T03:55:00+00:00',
        'protected':dict(sorted(protected.items())),
        'scope':'Every old reservation is carried without release. All manifests, prior failures, frozen source inputs, reports and archives remain unchanged. Account numeric quotas are not inferred from the user-reported burst diagnosis.'}

if __name__=='__main__':
    value=build()
    with OUTPUT.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'path':str(OUTPUT.relative_to(ROOT)),'sha256':digest(OUTPUT),'protected_files':len(value['protected']),
        'carry':value['historical_conservative_carry_credits'],'cap':value['cumulative_cap_credits']}))
