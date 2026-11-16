"""Read-only provisional metadata; never inspect generated answers or infer closure."""
import argparse
from collections import Counter
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.status_frontier_v6k import read_prefix,strict,digest,nano,credits,finite

CAP=750_000_000_000
ROLES={role:'results/frontier-v6l/'+directory+'/'+filename for role,directory,filename in (
    ('requests','continuation','requests.jsonl'),('responses','continuation','responses.jsonl'),
    ('outcomes','continuation','slot-outcomes.jsonl'),('ledger','budget','ledger.jsonl'))}


def require(ok,reason):
    if not ok:raise ValueError(reason)


def accounting(rows,baseline,baseline_sha):
    amount=nano(baseline);require(amount<=250_000_000_000,'prior cap changed')
    chain='0'*64;attempts={};started=closed=False;halted=False
    for n,row in enumerate(rows,1):
        require(not closed and row['seq']==n and row['previous_sha256']==chain and
            row['sha256']==digest({k:v for k,v in row.items() if k!='sha256'}),'ledger prefix chain mismatch')
        chain=row['sha256'];e=row['event'];kind=e['kind']
        if n==1:
            require(kind=='initialize' and e['historical_credits']==baseline and e['historical_sha256']==baseline_sha
                and e['cap_credits']=='750','ledger carry changed')
        elif kind=='run_started':
            require(not started and not halted,'duplicate run start');started=True
        elif kind=='reserve':
            aid=e['attempt_id'];bound=e['bound_nanocredits']
            require(started and not halted and aid not in attempts and type(bound)is int and bound>0,'invalid reservation')
            attempts[aid]={'bound':bound,'kind':'live','settled':0};amount+=bound
        elif kind in ('settle','retain_429','retain_unknown'):
            item=attempts[e['attempt_id']];require(item['kind']=='live','duplicate accounting');item['kind']=kind
            if kind=='settle':
                cost=e['accounted_nanocredits'];require(type(cost)is int and 0<=cost<=item['bound'],'invalid settlement')
                item['settled']=cost;amount+=cost-item['bound']
        elif kind=='halt':require(started and not halted,'duplicate halt');halted=True
        elif kind=='run_closed':require(started,'closure before start');closed=True
        else:raise ValueError('unknown accounting event')
        require(0<=amount<=CAP,'accounted cap exceeded')
    kinds=Counter(a['kind'] for a in attempts.values())
    return {'historical_conservative_carry_credits':baseline,'cumulative_cap_credits':'750',
        'cumulative_conservative_credits':credits(amount),'remaining_conservative_credits':credits(CAP-amount),
        'known_new_settled_credits':credits(sum(a['settled'] for a in attempts.values())),
        'live_reservation_count':kinds['live'],'live_reserved_credits':credits(sum(a['bound'] for a in attempts.values() if a['kind']=='live')),
        'finalized_unknown_429_count':kinds['retain_429'],'finalized_unknown_operational_count':kinds['retain_unknown'],
        'finalized_unknown_retained_credits':credits(sum(a['bound'] for a in attempts.values() if a['kind'].startswith('retain_'))),
        'settled_attempts':kinds['settle'],'ledger_prefix_chain_sha256':chain,
        'recorded_run_closed':closed,'recorded_halt':halted,'actual_billed_credits':None}


def status(root=ROOT,*,freeze_sha256):
    root=Path(root).resolve();raw=(root/'data/frontier-v6l-freeze.json').read_bytes()
    require(sha256(raw).hexdigest()==freeze_sha256,'freeze hash changed');freeze=strict(raw)
    require(freeze['schema']=='retrace.frontier-v6l-freeze.v1' and freeze['cumulative_cap_credits']=='750','freeze contract')
    inventory={r['path']:r['sha256'] for r in freeze['files']}
    def frozen(name):
        p=(root/name).resolve();require(p.is_relative_to(root),'frozen path escape');data=p.read_bytes()
        require(sha256(data).hexdigest()==inventory[name],'frozen status input changed');return strict(data)
    slots=frozen(freeze['sessions_path']);receipt=frozen(freeze['continuation_path'])
    index={s['slot_id']:s for s in slots};carried={r['slot_id'] for r in receipt['carried_final_outcomes']}
    require(len(index)==1800 and len(carried)==receipt['carried_final_slots'],'fixed schedule count')
    records={};prefixes={}
    for role,name in ROLES.items():records[role],prefixes[name]=read_prefix(root/name,role)
    rq={};rp={};finals={};models={m:Counter() for m in dict.fromkeys(s['model'] for s in slots)}
    for role,target in (('requests',rq),('responses',rp)):
        for row in records[role]:
            sid=row['slot_id'];aid=row['attempt_id']
            require(sid in index and sid not in carried and aid not in target,'unknown repeated or carried attempt')
            target[aid]=row;c=models[index[sid]['model']];c[role]+=1
            if role=='responses':c[row['model_outcome']]+=1;c['first_attempt_completed']+=row.get('first_attempt') is True and row['model_outcome']=='completed'
    for row in records['outcomes']:
        sid=row['slot_id'];require(sid in index and sid not in carried and sid not in finals,'unknown repeated or carried outcome')
        finals[sid]=row;models[index[sid]['model']]['finalized_slots']+=1
    gaps=[]
    for previous,current in zip(records['requests'],records['requests'][1:]):
        prior=rp.get(previous['attempt_id']);finish=current.get('previous_attempt_finished_monotonic');admit=current.get('admitted_monotonic')
        if prior and finite(finish) and finite(admit):
            need=max(4.0,prior.get('retry_cooldown_seconds') or 0,65.0 if prior.get('http_status')==429 else 0)
            gaps.append((admit-finish,need))
    return {'schema':'retrace.frontier-v6l-operational-status.v1','captured_at_utc':datetime.now(timezone.utc).isoformat(),
        'provisional':True,'final_audit_performed':False,'freeze_sha256':freeze_sha256,
        'active_worker_lock_present':(root/'results/frontier-v6l/budget/active.lock').exists(),
        'original_planned_slots':1800,'prior_definitive_carried_slots':len(carried),
        'continuation_planned_slots':receipt['continuation_slots'],
        'continuation_definitive_slots':sum(r['model_outcome']!='not_issued_global_stop' for r in finals.values()),
        'continuation_global_stop_placeholders':sum(r['model_outcome']=='not_issued_global_stop' for r in finals.values()),
        'continuation_issued_attempts':len(rq),'continuation_finished_attempts':len(rp),
        'observed_requests_without_response':len(set(rq)-set(rp)),'responses_not_yet_in_request_prefix':len(set(rp)-set(rq)),
        'accounting':accounting(records['ledger'],receipt['historical_conservative_carry_credits'],receipt['baseline_snapshot_sha256']),
        'per_model':{m:dict(c) for m,c in models.items()},'journal_prefixes':prefixes,
        'pacing':{'comparable_gaps':len(gaps),'minimum_observed_completion_gap_seconds':min((g[0] for g in gaps),default=None),
            'observed_gap_violations':sum(g[0]+1e-9<g[1] for g in gaps)},
        'scope':'Operational metadata from independently captured complete prefixes. No generated answer display, semantic score, final closure certification or claim of verified provider billing.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--freeze-sha256',required=True)
    a=p.parse_args();print(json.dumps(status(a.root,freeze_sha256=a.freeze_sha256),ensure_ascii=False,indent=2,allow_nan=False))
