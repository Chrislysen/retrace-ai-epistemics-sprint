"""Prospective transport-only amendment; original h remains a failed canary.

No scientific prompts, corpus, scorer or semantic admission policies change.
The whole ten-slot feasibility source is repeated under a new transport freeze;
this does not replace any original attempt. Paid execution is explicit only.
"""
import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.adaption_v6h import AiohttpTransport, BASELINE_LEDGER, RollingLedger, require
from scripts.run_frontier_v6h import integrity, verify_canary, verify_corpus

ORIGINAL='data/frontier-v6h-canary-freeze.json'
ORIGINAL_SHA='6e7cec65992f4f3cc8012fe06d7d8dfbe9de472357ef6fdf6af95c8414e6f8ec'
BASE='results/frontier-v6h-paced'
QUOTA_SNAPSHOT='data/frontier-v6h-ledger-after-quota-probe.jsonl'
QUOTA_SHA='84eac421c782e3502e32eb8bf2a0d8f328130b3190e88cc378ed2db7aaa22ba1'
CONFIG={'global_interval_seconds':5.0,'model_interval_seconds':2.0,
        'per_model_concurrency':1,'global_concurrency':3,'timeout_seconds':180.0,'max_retries':2}
CUTOFF=datetime(2026,11,16,3,55,tzinfo=timezone.utc)
TESTS=('tests.test_adaption_v6h','tests.test_adaption_global_v6h',
       'tests.test_frontier_v6h_canary','tests.test_frontier_v6h_eval',
       'tests.test_frontier_v6h_paced_driver')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write_new(p,value):
    with Path(p).open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')

def original_integrity():
    require(sha(ROOT/ORIGINAL)==ORIGINAL_SHA,'original_freeze_changed')
    original=read(ROOT/ORIGINAL)
    for row in original['files']:require(sha(ROOT/row['path'])==row['sha256'],'original_dependency_changed')
    integrity(read(ROOT/'data/frontier-v6h-authorization.json'),read(ROOT/'data/frontier-v6c-model-availability.json'))
    verify_corpus(ROOT/'data/frontier-v6h-corpus.json','bf765acefac71765c3647c0a1df2df9c56cd2a2fffe160d447bc1d31ccf7c5b1')
    return original

def frozen_paths(phase):
    original=original_integrity()
    paths={ROOT/row['path'] for row in original['files']}
    paths.add(ROOT/ORIGINAL)
    paths.update(ROOT/p for p in ('scripts/run_frontier_v6h_paced.py','retrace/adaption_global_v6h.py',
        'tests/test_adaption_global_v6h.py','tests/test_frontier_v6h_paced_driver.py',
        'research/frontier-v6h-global-pacing-amendment.md','research/prospective-global-pacing-review.md',
        'research/frontier-v6h-quota-findings.md','research/frontier-v6h-runtime-audit.md',
        'scripts/audit_frontier_v6h_runtime.py','scripts/probe_adaption_quota_v6h.py',
        'tests/test_quota_probe_v6h.py','data/frontier-v6h-quota-probe-freeze.json',QUOTA_SNAPSHOT,
        'data/frontier-v6h-ledger-after-canary.jsonl',
        'deliverables/retrace-v6-sprint-artifact.zip','deliverables/retrace-v6h-release-manifest.json',
        'deliverables/retrace-v6-clean-reproduction.json','report/v6-unified/RETRACE-v6h-unified-draft.pdf'))
    for folder in ('results/frontier-v6h/canary','results/frontier-v6h-quota-probe'):
        paths.update(p for p in (ROOT/folder).rglob('*') if p.is_file())
    if phase=='primary':
        previous=read(ROOT/'data/frontier-v6h-paced-canary-freeze.json')
        require(previous['runtime_config']==CONFIG,'canary_config_changed')
        for row in previous['files']:require(sha(ROOT/row['path'])==row['sha256'],'post_canary_dependency_changed')
        run=ROOT/BASE/'canary';verify_canary(read(run/'summary.json'))
        require((run/'semantic-score.json').is_file(),'new_canary_semantic_score_required')
        paths.update(p for p in run.rglob('*') if p.is_file())
        paths.add(ROOT/'data/frontier-v6h-paced-canary-freeze.json')
    return paths

def freeze(phase):
    paths=frozen_paths(phase)
    require(not (ROOT/BASE/phase).exists(),'phase_already_exists')
    probe=read(ROOT/'results/frontier-v6h-quota-probe/summary.json')
    require(len(probe['rounds'])==3 and all(r['issued_attempts']==5 and r['http_429_attempts']==0
        and r['first_attempt_completed']==5 for r in probe['rounds']),'quota_probe_not_complete')
    require(sha(ROOT/QUOTA_SNAPSHOT)==QUOTA_SHA,'quota_snapshot_changed')
    ledger=ROOT/'results/frontier-v6h/budget/ledger.jsonl'
    if phase=='canary':require(sha(ledger)==QUOTA_SHA,'intervening_calls')
    else:
        # Primary must follow only the newly identified paced canary, no hidden calls.
        summary=read(ROOT/BASE/'canary/summary.json')
        tail=json.loads(ledger.read_text(encoding='utf-8').splitlines()[-1])
        require(tail.get('sha256')==summary['budget']['ledger_sha256'],
            'intervening_ledger_events')
    prefix=ROOT/f'data/frontier-v6h-paced-ledger-before-{phase}.jsonl'
    capture=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromNames(TESTS)
    result=unittest.TextTestRunner(stream=capture,verbosity=1).run(suite)
    require(result.wasSuccessful(),'paced_preflight_failed: '+capture.getvalue())
    with prefix.open('xb') as f:f.write(ledger.read_bytes())
    paths.add(prefix)
    preflight=ROOT/f'results/frontier-v6h-paced-{phase}-preflight.json'
    write_new(preflight,{'passed':True,'tests_run':result.testsRun,'tests':list(TESTS),
        'paid_calls':0,'scope':'Offline transport and scoring regressions immediately before new phase freeze',
        'raw_log':capture.getvalue()})
    paths.add(preflight)
    entries=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size}
             for p in sorted(paths)]
    sessions=f'data/frontier-v6h-{ "canary-sessions" if phase=="canary" else "sessions"}.json'
    value={'schema':'retrace.frontier-v6h-paced-freeze.v1','phase':phase,
        'created_at':datetime.now(timezone.utc).isoformat(),'files':entries,'runtime_config':CONFIG,
        'scientific_freeze':{'path':ORIGINAL,'sha256':ORIGINAL_SHA},'sessions_path':sessions,
        'ledger_prefix_path':prefix.relative_to(ROOT).as_posix(),'ledger_prefix_sha256':sha(prefix),
        'primary_admission_cutoff_utc':CUTOFF.isoformat(),
        'scheduled_slots':10 if phase=='canary' else 8148,'cumulative_cap_credits':'250',
        'scope':'Transport-only prospective amendment; no original scientific file or failed attempt replaced. No under-one-hour guarantee.'}
    out=ROOT/f'data/frontier-v6h-paced-{phase}-freeze.json';write_new(out,value)
    return {'path':out.relative_to(ROOT).as_posix(),'sha256':sha(out),'files':len(entries),'tests':result.testsRun}

async def execute(phase,expected):
    from retrace.adaption_global_v6h import run_slots
    path=ROOT/f'data/frontier-v6h-paced-{phase}-freeze.json'
    require(sha(path)==expected,'paced_freeze_changed');frozen=read(path)
    require(frozen['phase']==phase and frozen['runtime_config']==CONFIG,'paced_config_changed')
    require(frozen['primary_admission_cutoff_utc']==CUTOFF.isoformat(),'cutoff_changed')
    require(datetime.now(timezone.utc)<CUTOFF,'delivery_buffer_reached')
    for row in frozen['files']:require(sha(ROOT/row['path'])==row['sha256'],'paced_dependency_changed')
    original_integrity()
    ledger_path=ROOT/'results/frontier-v6h/budget'
    require(sha(ledger_path/'ledger.jsonl')==frozen['ledger_prefix_sha256'],'intervening_calls')
    if phase=='primary':verify_canary(read(ROOT/BASE/'canary/summary.json'))
    slots=read(ROOT/frozen['sessions_path'])
    require(len(slots)==frozen['scheduled_slots'],'slot_count_changed')
    require(datetime.now(timezone.utc)<CUTOFF,'delivery_buffer_reached')
    key=sys.stdin.readline().strip()
    require(datetime.now(timezone.utc)<CUTOFF,'delivery_buffer_reached')
    require(sha(ledger_path/'ledger.jsonl')==frozen['ledger_prefix_sha256'],'intervening_calls')
    ledger=RollingLedger(ledger_path,baseline_path=ROOT/BASELINE_LEDGER)
    try:
        # The exclusive ledger lock closes the check/open race with other runners.
        require(sha(ledger_path/'ledger.jsonl')==frozen['ledger_prefix_sha256'],'intervening_calls')
    except BaseException:
        ledger.close();key=None
        raise
    async def deadline_guard():
        while True:
            if datetime.now(timezone.utc)>=CUTOFF:
                stop=ROOT/BASE/'STOP';stop.parent.mkdir(parents=True,exist_ok=True)
                try:
                    with stop.open('x',encoding='utf-8') as f:f.write('Prospectively declared delivery-buffer cutoff reached. Drain in-flight calls.\n')
                except FileExistsError:pass
                return
            await asyncio.sleep(15)
    guard=asyncio.create_task(deadline_guard())
    try:
        async with AiohttpTransport(key,180,3) as transport:
            return await run_slots(slots,api_key=key,output_dir=ROOT/BASE/phase,ledger=ledger,
                transport=transport,canary=phase=='canary',global_interval=5.0,model_interval=2.0,
                concurrency=3,per_model_concurrency=1,timeout_seconds=180,stop_file=ROOT/BASE/'STOP')
    finally:
        guard.cancel()
        try:await guard
        except asyncio.CancelledError:pass
        ledger.close();key=None

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--phase',choices=('canary','primary'),required=True)
    p.add_argument('--freeze',action='store_true');p.add_argument('--execute-sha256')
    a=p.parse_args()
    if a.freeze:print(json.dumps(freeze(a.phase)))
    elif a.execute_sha256:print(json.dumps(asyncio.run(execute(a.phase,a.execute_sha256)),indent=2))
    else:print(json.dumps({'phase':a.phase,'runtime':CONFIG,'paid_calls':0}))
