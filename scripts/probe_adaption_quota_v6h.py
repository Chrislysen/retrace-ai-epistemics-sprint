"""Prospective transport-only rate diagnostic; never a scientific canary replacement.

The unchanged v6h ledger/stream implementation accounts every attempt. Three
five-model rounds admit HTTP requests serially at >=21, >=10, then >=5 seconds.
Advance only after a round has no 429 or operational failure. The frozen runner's
explicit 429-only retries remain visible. No graph prompt, case, or score changes.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.adaption_v6h import (AiohttpTransport, BASELINE_LEDGER, DurableJSONL,
    PRIMARY_MODELS, RollingLedger, now, run_slots, require, encoded, digest)
from scripts.run_frontier_v6h import integrity

OUTPUT = ROOT / 'results/frontier-v6h-quota-probe'
FREEZE = ROOT / 'data/frontier-v6h-quota-probe-freeze.json'
INTERVALS = (21.0, 10.0, 5.0)
SAFE_HEADERS = ('date', 'content-type', 'retry-after', 'ratelimit', 'ratelimit-policy',
                'ratelimit-limit', 'ratelimit-remaining', 'ratelimit-reset',
                'x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset',
                'x-ratelimit-limit-requests', 'x-ratelimit-remaining-requests',
                'x-ratelimit-reset-requests', 'x-ratelimit-limit-tokens',
                'x-ratelimit-remaining-tokens', 'x-ratelimit-reset-tokens')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def slots(round_index):
    return [dict(slot_id=f'quota-v6h::r{round_index+1}::{model}',
        case_id='transport-only-no-source-graph', model=model,
        condition='quota_probe', phase=f'interval_{INTERVALS[round_index]:g}s',
        instructions='Transport diagnostic. Reply exactly OK. No explanation.',
        input='Reply exactly OK.', max_output_tokens=8192, temperature=1.0,
        metadata={'scientific_result': False, 'nominal_global_start_interval': INTERVALS[round_index]})
        for model in PRIMARY_MODELS]

def check_original_freeze():
    original = ROOT / 'data/frontier-v6h-canary-freeze.json'
    require(sha(original) == '6e7cec65992f4f3cc8012fe06d7d8dfbe9de472357ef6fdf6af95c8414e6f8ec', 'original_freeze_changed')
    for row in json.loads(original.read_text(encoding='utf-8'))['files']:
        require(sha(ROOT / row['path']) == row['sha256'], 'original_dependency_changed')
    integrity(json.loads((ROOT/'data/frontier-v6h-authorization.json').read_text(encoding='utf-8')),
              json.loads((ROOT/'data/frontier-v6c-model-availability.json').read_text(encoding='utf-8')))

def create_freeze():
    check_original_freeze()
    require(not OUTPUT.exists(), 'probe_already_exists')
    snapshot = ROOT/'data/frontier-v6h-ledger-after-canary.jsonl'
    require(snapshot.is_file() and sha(snapshot) == '6f0f187e2ef48ff646305b108ea2cc550fb8c39bec7221c5418f9e6f64d5a73b', 'closed_canary_ledger_required')
    require(sha(ROOT/'results/frontier-v6h/budget/ledger.jsonl') == sha(snapshot), 'unaccounted_intervening_calls')
    paths = [Path(__file__), ROOT/'tests/test_quota_probe_v6h.py', snapshot,
             ROOT/'data/frontier-v6h-canary-freeze.json',
             ROOT/'results/frontier-v6h/canary/summary.json', ROOT/'results/frontier-v6h/canary/semantic-score.json']
    value = {'schema':'retrace.transport-quota-probe.v1','created_at':now(),
        'purpose':'Find a usable observed cadence; not a numeric service quota, scientific smoke gate, or benchmark result.',
        'files':{p.relative_to(ROOT).as_posix():sha(p) for p in paths},
        'round_slots':[slots(i) for i in range(3)], 'global_http_concurrency':1,
        'global_intervals_seconds':list(INTERVALS), 'minimum_round_gap_seconds':65,
        'advancement':'Next round only if all5 first attempts completed and no429/operational failure/truncation occurred.',
        'retry_policy':'Unchanged explicit v6h429-only retries (maximum2). Failed rounds are retained; do not repeat or escalate.',
        'cumulative_cap_credits':'250','planned_maximum_slots':15,
        'known_limit':'No numeric quota exposed by prior429 bodies, model-list headers, or documentation inspected.'}
    with FREEZE.open('x',encoding='utf-8') as f: json.dump(value,f,indent=2);f.write('\n')
    return {'path':str(FREEZE),'sha256':sha(FREEZE)}

class PacedHeaderTransport(AiohttpTransport):
    def __init__(self, key, interval, journal, clock=time.monotonic, sleep=asyncio.sleep):
        super().__init__(key,180,1)
        self.interval=interval;self.journal=journal;self.last_start=None
        self.clock=clock;self.sleep=sleep

    async def __call__(self, body):
        # run_slots concurrency1 ensures no queued transport can bypass this gate.
        if self.last_start is not None:
            await self.sleep(max(0,self.interval-(self.clock()-self.last_start)))
        started=self.clock();gap=None if self.last_start is None else started-self.last_start
        self.last_start=started
        self.journal.write({'kind':'http_admission','at':now(),'model':body['model'],
                            'request_sha256':digest(body),'gap_seconds':gap,'interval_seconds':self.interval})
        async with self.session.post('https://api.prod.adaptionlabs.ai/api/v1/responses',json=body,
            allow_redirects=False,headers={'Authorization':'Bearer '+self.api_key,'Accept':'text/event-stream'}) as response:
            safe={k:response.headers[k] for k in SAFE_HEADERS if k in response.headers}
            self.journal.write({'kind':'http_headers','at':now(),'model':body['model'],
                'request_sha256':digest(body),'status':response.status,'headers':safe})
            yield {'http_status':response.status,'content_type':response.headers.get('Content-Type',''),
                   'retry_after':response.headers.get('Retry-After')}
            async for chunk in response.content.iter_chunked(65536):yield chunk

def round_passed(summary):
    return (summary.get('status')=='completed' and summary.get('planned')==5
        and summary.get('issued_attempts')==5 and summary.get('first_attempt_completed')==5
        and summary.get('http_429_attempts')==0 and summary.get('issued_operational_failures')==0
        and summary.get('truncated')==0 and summary.get('unissued_slot_ids')==[])

async def execute(expected):
    require(sha(FREEZE)==expected,'probe_freeze_changed')
    frozen=json.loads(FREEZE.read_text(encoding='utf-8'))
    for rel,value in frozen['files'].items(): require(sha(ROOT/rel)==value,'probe_dependency_changed')
    require(frozen['round_slots']==[slots(i) for i in range(3)],'probe_projection_changed')
    check_original_freeze()
    require(sha(ROOT/'results/frontier-v6h/budget/ledger.jsonl') == sha(ROOT/'data/frontier-v6h-ledger-after-canary.jsonl'),'intervening_calls')
    key=sys.stdin.readline().strip();require(len(key)>=8 and not any(c.isspace() for c in key),'invalid_key')
    OUTPUT.mkdir(exist_ok=False)
    summaries=[]
    ledger=RollingLedger(ROOT/'results/frontier-v6h/budget',baseline_path=ROOT/BASELINE_LEDGER)
    journal=DurableJSONL(OUTPUT/'http-admissions.jsonl',scrub=lambda s:s.replace(key,'[REDACTED_CREDENTIAL]'))
    try:
        for i,interval in enumerate(INTERVALS):
            if i: await asyncio.sleep(65)
            async with PacedHeaderTransport(key,interval,journal) as transport:
                summary=await run_slots(slots(i),api_key=key,output_dir=OUTPUT/f'round-{i+1}',
                    ledger=ledger,transport=transport,model_interval=2.0,per_model_concurrency=1,
                    concurrency=1,timeout_seconds=180,stop_file=OUTPUT/'STOP')
            summaries.append(summary)
            print(json.dumps({'round':i+1,'interval':interval,'passed':round_passed(summary),
                              'completed':summary['completed'],'http_429':summary['http_429_attempts']}),flush=True)
            if not round_passed(summary): break
        result={'schema':'retrace.transport-quota-probe-result.v1','created_at':now(),
            'freeze_sha256':expected,'rounds':summaries,'numeric_quota_verified':False,
            'scope':'Short-input serial transport diagnostic only. Success does not establish long-input throughput or service quota.',
            'fastest_tested_zero_failure_interval_seconds':min([INTERVALS[i] for i,s in enumerate(summaries) if round_passed(s)],default=None),
            'budget':ledger.snapshot()}
        with (OUTPUT/'summary.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
        return {k:result[k] for k in ('numeric_quota_verified','fastest_tested_zero_failure_interval_seconds','budget')}
    finally:journal.close();ledger.close();key=None

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--freeze',action='store_true');p.add_argument('--execute-sha256')
    a=p.parse_args()
    if a.freeze: print(json.dumps(create_freeze()))
    elif a.execute_sha256: print(json.dumps(asyncio.run(execute(a.execute_sha256))))
    else: print(json.dumps({'round_slots':[slots(i) for i in range(3)],'paid_calls':0},indent=2))
