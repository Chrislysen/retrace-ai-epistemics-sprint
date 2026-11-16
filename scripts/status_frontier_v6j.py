"""Read-only operational metadata from complete v6j journal prefixes.

No provider access, credential inspection, answer display, semantic scoring,
ledger mutation, or final-closure certification. A live snapshot is provisional.
"""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import argparse
import json
import math
import os
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]
FREEZE_SHA='6fffc08ce31ac6aa19079be690a244a0e9b649d4a6281f7df8d53038c3811ea0'
BASELINE='47.653269434'
CAP=250_000_000_000
ROLES={'requests':'results/frontier-v6j/continuation/requests.jsonl','responses':'results/frontier-v6j/continuation/responses.jsonl','outcomes':'results/frontier-v6j/continuation/slot-outcomes.jsonl','ledger':'results/frontier-v6j/budget/ledger.jsonl'}


def strict(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def bad(_):raise ValueError('nonfinite JSON value')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return sha256(canonical(value)).hexdigest()
def credits(value):return format(Decimal(value)/1_000_000_000,'f')
def nano(value):
    n=Decimal(str(value))*1_000_000_000
    if not n.is_finite() or n<0 or n!=n.to_integral_value():raise ValueError('invalid nanocredits')
    return int(n)
def finite(value):return type(value) in (int,float) and math.isfinite(value)


def projection(role,row):
    """Whitelist metadata; request instructions and generated prose are discarded."""
    if role=='ledger':return row # Events contain accounting metadata, never bodies.
    names={'slot_id','attempt_id','attempt_number','first_attempt','model_outcome','terminal_valid','issued','slot_final','attempts_issued','http_status','failure_scope','at','latency_ms','admitted_monotonic','previous_attempt_finished_monotonic','transport_finished_monotonic','retry_cooldown_seconds','settled_credits','reserved_credits','usage'}
    out={k:row[k] for k in names if k in row}
    if 'model_outcome' in out and out['model_outcome'] not in {'completed','truncated_max_output_tokens','http_429','operational_failure','not_issued_dependency_failed','not_issued_global_stop','issued_without_response'}:raise ValueError('unknown operational outcome')
    if 'usage' in out:
        usage=out['usage'];out['usage']={k:usage[k] for k in ('input_tokens','output_tokens') if k in usage} if isinstance(usage,dict) else None
    # Do not echo arbitrary provider error strings or nested raw response bodies.
    error=row.get('error')
    out['failure_category']='timeout' if error=='timeout' else 'rate_limit' if row.get('http_status')==429 else 'provider_408_or_5xx' if type(row.get('http_status')) is int and (row['http_status']==408 or 500<=row['http_status']<=599) else 'response_model_mismatch' if error=='response_model_mismatch' else 'global_protocol_or_auth' if row.get('failure_scope')=='global' else 'other' if error else None
    return out


def read_prefix(path,role):
    """Capture a bounded byte prefix; ignore only an incomplete final JSONL line."""
    path=Path(path)
    if not path.exists():return [],{'present':False,'captured_bytes':0,'complete_bytes':0,'ignored_partial_bytes':0,'complete_lines':0,'complete_prefix_sha256':sha256(b'').hexdigest(),'changed_during_read':False}
    rows=[];h=sha256();complete=0
    with path.open('rb') as stream:
        initial=os.fstat(stream.fileno());remaining=initial.st_size
        while remaining:
            line=stream.readline(remaining);remaining-=len(line)
            if not line:break
            if not line.endswith(b'\n'):break
            if not line.strip():raise ValueError('blank completed journal line')
            row=strict(line)
            if not isinstance(row,dict):raise ValueError('journal row must be an object')
            rows.append(projection(role,row));h.update(line);complete+=len(line)
        final=os.fstat(stream.fileno())
    return rows,{'present':True,'captured_bytes':initial.st_size,'complete_bytes':complete,'ignored_partial_bytes':initial.st_size-complete,'complete_lines':len(rows),'complete_prefix_sha256':h.hexdigest(),'changed_during_read':(initial.st_size,initial.st_mtime_ns)!=(final.st_size,final.st_mtime_ns)}


def accounting(rows):
    amount=nano(BASELINE);chain='0'*64;attempts={};started=closed=False;halts=[]
    for n,row in enumerate(rows,1):
        if row['seq']!=n or row['previous_sha256']!=chain or row['sha256']!=digest({k:v for k,v in row.items() if k!='sha256'}):raise ValueError('ledger prefix chain mismatch')
        chain=row['sha256'];e=row['event'];kind=e['kind']
        if n==1:
            if kind!='initialize' or e['historical_credits']!=BASELINE or e['cap_credits']!='250':raise ValueError('ledger carry changed')
        elif kind=='run_started':
            if started or closed:raise ValueError('duplicate run start')
            started=True
        elif kind=='reserve':
            aid=e['attempt_id'];bound=e['bound_nanocredits']
            if not started or closed or aid in attempts or type(bound)is not int or bound<=0:raise ValueError('invalid reservation')
            attempts[aid]={'bound':bound,'kind':'live_reservation','settled':None};amount+=bound
        elif kind in ('settle','retain_429','retain_unknown'):
            item=attempts[e['attempt_id']]
            if closed or item['kind']!='live_reservation':raise ValueError('duplicate/late accounting')
            item['kind']=kind
            if kind=='settle':
                value=e['accounted_nanocredits']
                if type(value)is not int or not 0<=value<=item['bound']:raise ValueError('invalid settlement')
                item['settled']=value;amount+=value-item['bound']
        elif kind=='halt':halts.append(True)
        elif kind=='run_closed':
            if closed:raise ValueError('duplicate run closure')
            closed=True
        else:raise ValueError('unknown accounting event')
        if not 0<=amount<=CAP:raise ValueError('accounted cap exceeded')
    kinds=Counter(a['kind'] for a in attempts.values())
    sums={kind:sum(a['bound'] for a in attempts.values() if a['kind']==kind) for kind in kinds}
    return {'historical_conservative_carry_credits':BASELINE,'cumulative_cap_credits':'250','cumulative_conservative_credits':credits(amount),'remaining_conservative_credits':credits(CAP-amount),'known_new_settled_credits':credits(sum(a['settled'] or 0 for a in attempts.values())),'live_reservation_count':kinds['live_reservation'],'live_reserved_credits':credits(sums.get('live_reservation',0)),'finalized_unknown_429_count':kinds['retain_429'],'finalized_unknown_operational_count':kinds['retain_unknown'],'finalized_unknown_retained_credits':credits(sums.get('retain_429',0)+sums.get('retain_unknown',0)),'settled_attempts':kinds['settle'],'ledger_complete_entries':len(rows),'ledger_prefix_chain_sha256':chain,'recorded_run_closed':closed,'recorded_halt':bool(halts),'actual_billed_credits':None}


def summarize(slots,receipt,records,*,active_lock):
    index={s['slot_id']:s for s in slots}
    if len(index)!=len(slots):raise ValueError('duplicate planned slot')
    carried=receipt['carryover_rows'];carry_ids={r['slot_id'] for r in carried}
    pending=[s for s in slots if s['slot_id'] not in carry_ids]
    if len(carry_ids)!=len(carried) or not carry_ids<=set(index):raise ValueError('invalid carried cohort')
    counters={m:Counter() for m in dict.fromkeys(s['model'] for s in slots)};latencies=defaultdict(list);categories=defaultdict(Counter)
    for s in slots:counters[s['model']]['original_planned']+=1
    for s in pending:counters[s['model']]['continuation_planned']+=1
    for r in carried:
        c=counters[index[r['slot_id']]['model']];c['carried_original_issued']+=1;c['carried_original_completed']+=r['model_outcome']=='completed';c['carried_original_failed']+=r['model_outcome']!='completed'
    requests=records['requests'];responses=records['responses'];finals=records['outcomes']
    rq={};rp={};done=set()
    for q in requests:
        sid=q['slot_id'];aid=q['attempt_id']
        if sid not in index or sid in carry_ids or aid in rq:raise ValueError('unknown/repeated/carried request')
        rq[aid]=q;c=counters[index[sid]['model']];c['issued_attempts']+=1;c['retry_attempts']+=q['attempt_number']>1
    for r in responses:
        sid=r['slot_id'];aid=r['attempt_id']
        if sid not in index or sid in carry_ids or aid in rp:raise ValueError('unknown/repeated/carried response')
        rp[aid]=r;c=counters[index[sid]['model']];c['finished_attempts']+=1
        outcome=r['model_outcome'];c['attempt_'+outcome]+=1
        if r.get('first_attempt'):c['first_attempt_completed']+=outcome=='completed'
        if r.get('failure_category'):categories[index[sid]['model']][r['failure_category']]+=1
        if finite(r.get('latency_ms')):latencies[index[sid]['model']].append(r['latency_ms']/1000)
        if r.get('settled_credits') is not None:
            c['known_settled_nanocredits']+=nano(r['settled_credits'])
            for k in ('input_tokens','output_tokens'):
                value=(r.get('usage') or {}).get(k)
                if type(value)is int and value>=0:c['known_usage_'+k]+=value
    for r in finals:
        sid=r['slot_id']
        if sid not in index or sid in carry_ids or sid in done:raise ValueError('unknown/repeated/carried final')
        done.add(sid);c=counters[index[sid]['model']];c['finalized_slots']+=1;c['final_'+r['model_outcome']]+=1
    timing=[]
    for previous,q in zip(requests,requests[1:]):
        prior=rp.get(previous['attempt_id']);finished=q.get('previous_attempt_finished_monotonic');admit=q.get('admitted_monotonic')
        if prior and finite(finished) and finite(admit):
            required=max(4.0,prior.get('retry_cooldown_seconds') or 0,65.0 if prior.get('http_status')==429 else 0)
            timing.append({'required_seconds':required,'observed_seconds':admit-finished})
    per_model={}
    for m,c in counters.items():
        value={key:c[key] for key in ('original_planned','continuation_planned','carried_original_issued','carried_original_completed','carried_original_failed','issued_attempts','retry_attempts','finished_attempts','first_attempt_completed','finalized_slots','known_usage_input_tokens','known_usage_output_tokens')};value.update(c);value['not_finalized_continuation_slots']=c['continuation_planned']-c['finalized_slots'];value['finished_first_attempts']=sum(r.get('first_attempt') is True for r in responses if index[r['slot_id']]['model']==m)
        value['observed_latency_median_seconds']=statistics.median(latencies[m]) if latencies[m] else None
        value['failure_categories']=dict(categories[m]);value['known_settled_credits_from_response_prefix']=credits(value.pop('known_settled_nanocredits',0));per_model[m]=value
    budget=accounting(records['ledger'])
    return {'schema':'retrace.frontier-v6j-operational-status.v1','provisional':True,'active_worker_lock_present':active_lock,'final_audit_performed':False,'original_planned_slots':len(slots),'original_issued_carried_slots':len(carried),'continuation_planned_slots':len(pending),'continuation_finalized_slots':len(finals),'continuation_not_finalized_slots':len(pending)-len(finals),'continuation_issued_attempts':len(requests),'continuation_finished_attempts':len(responses),'observed_requests_without_response':len(set(rq)-set(rp)),'responses_not_yet_in_request_prefix':len(set(rp)-set(rq)),'per_model':per_model,'pacing':{'comparable_gaps':len(timing),'minimum_observed_completion_gap_seconds':min((r['observed_seconds'] for r in timing),default=None),'observed_gap_violations':sum(r['observed_seconds']+1e-9<r['required_seconds'] for r in timing),'minimum_observed_429_margin_seconds':min((r['observed_seconds']-r['required_seconds'] for r in timing if r['required_seconds']>=65),default=None)},'accounting':budget,'scope':'Operational metadata only. Independent file prefixes may be sampled at different instants. Complete journal lines are not a closure certificate or semantic score. The original six observations remain unchanged; unknown and live reservations are distinct. Usage is accepted ledger/response metadata, not a claim about provider billing.'}


def status(root=ROOT):
    root=Path(root).resolve();freeze_path=root/'data/frontier-v6j-freeze.json';fraw=freeze_path.read_bytes()
    if sha256(fraw).hexdigest()!=FREEZE_SHA:raise ValueError('frozen execution manifest changed')
    freeze=strict(fraw);inventory={r['path']:r['sha256'] for r in freeze['files']}
    def frozen(name):
        raw=(root/name).read_bytes()
        if sha256(raw).hexdigest()!=inventory[name]:raise ValueError('frozen status input changed')
        return strict(raw)
    slots=frozen(freeze['sessions_path']);receipt=frozen(freeze['continuation_path'])
    rows={};prefixes={}
    for role,path in ROLES.items():rows[role],prefixes[path]=read_prefix(root/path,role)
    result=summarize(slots,receipt,rows,active_lock=(root/'results/frontier-v6j/budget/active.lock').exists())
    result['captured_at_utc']=datetime.now(__import__('datetime').timezone.utc).isoformat();result['journal_prefixes']=prefixes
    result['capture_notes']={'files_changed_while_reading':sum(v['changed_during_read'] for v in prefixes.values()),'files_with_partial_tail':sum(v['ignored_partial_bytes']>0 for v in prefixes.values()),'freeze_sha256':FREEZE_SHA}
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);a=p.parse_args()
    print(json.dumps(status(a.root),ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()
