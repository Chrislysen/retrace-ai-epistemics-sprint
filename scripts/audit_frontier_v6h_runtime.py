"""Independent read-only audit of the closed v6h canary; no network or credentials.

The frozen independent v6f whole-stream parser is reused, not the production
SSE decoder. Later live-ledger appends are outside this snapshot's scope.
"""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
from pathlib import Path, PureWindowsPath
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_frontier_v6f_run import parse_sse, strict_json, output_text

FREEZE = 'data/frontier-v6h-canary-freeze.json'
FREEZE_HASH = '6e7cec65992f4f3cc8012fe06d7d8dfbe9de472357ef6fdf6af95c8414e6f8ec'
LEDGER = 'data/frontier-v6h-ledger-after-canary.jsonl'
LEDGER_HASH = '6f0f187e2ef48ff646305b108ea2cc550fb8c39bec7221c5418f9e6f64d5a73b'
CARRY = Decimal('43.633207445')
PRICES = {
 'deepseek-v4-flash': ('0.045','0.14',1048576),
 'gemma-4-31b-it': ('0.09','0.34',256000),
 'glm-5.3-flash': ('0.15','0.50',1048576),
 'qwen3.8-27b': ('0.039','1.25',262144),
 'glm-5.2': ('1.40','4.40',1048575),
}

def canon(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False).encode()
def hash_(raw): return sha256(raw).hexdigest()
def digest(value): return hash_(canon(value))
def nano(value): return int((Decimal(str(value))*1_000_000_000).to_integral_value(rounding=ROUND_CEILING))
def credits(value): return format(Decimal(value)/1_000_000_000,'f')
def stamp(value): return datetime.fromisoformat(value).timestamp()
def lines(raw):
    if raw and not raw.endswith(b'\n'): raise ValueError('Incomplete JSONL snapshot')
    return [strict_json(x.decode()) for x in raw.splitlines() if x.strip()]

def audit(root: Path = ROOT, frozen_aliases=None):
    root=Path(root).resolve(); aliases=frozen_aliases or {}; count=0; bindings={}; saved={}
    def check(ok,message):
        nonlocal count
        count+=1
        if not ok:raise ValueError(message)
    def path(name):
        target=(root/name).resolve();check(target.is_relative_to(root),'Path escapes root');return target
    def read(name):
        if name not in saved:
            target=path(aliases.get(name,name));raw=target.read_bytes();saved[name]=raw
            bindings[name]={'sha256':hash_(raw),'bytes':len(raw)}
        return saved[name]
    def obj(name):return strict_json(read(name).decode('utf-8'))
    for source,dest in aliases.items():
        if not (source.endswith('/active.lock') and dest.endswith('.txt') and source!=dest):
            raise ValueError('Only distinct inert historical lock aliases allowed')
        if not (root/dest).resolve().is_relative_to(root):
            raise ValueError('Alias escapes root')
    check(hash_(read(FREEZE))==FREEZE_HASH,'Scientific freeze hash changed')
    freeze=obj(FREEZE);check(len(freeze['files'])==844,'Expected844 frozen artifacts')
    frozen={}
    for entry in freeze['files']:
        name=entry['path'];check(name not in frozen,'Duplicate freeze path');frozen[name]=entry['sha256']
        check(hash_(read(name))==entry['sha256'],'Frozen file changed: '+name)
    check(set(aliases)<=set(frozen),'Alias is not a frozen artifact')
    authorization=obj('data/frontier-v6h-authorization.json')
    check(len(authorization['protected'])==695,'Historical inventory count')
    for name,expected in authorization['protected'].items():check(frozen.get(name)==expected,'Historical pin absent')
    # Independently replay the immediately preceding f ledger. Earlier inherited
    # unknown reservations remain inside its pinned starting carry.
    prior=lines(read(authorization['prior_ledger_path']));previous='0'*64;account=nano('42.997746364');pa={}
    for seq,row in enumerate(prior,1):
        check(row['seq']==seq and row['previous_sha256']==previous and row['sha256']==digest({k:v for k,v in row.items() if k!='sha256'}),'Prior ledger chain')
        previous=row['sha256'];e=row['event'];k=e['kind']
        if k=='initialize':check(seq==1 and e['historical_credits']=='42.997746364','Prior carry')
        elif k=='reserve':
            check(e['attempt_id'] not in pa,'Prior duplicate reservation');pa[e['attempt_id']]={'bound':e['bound_nanocredits'],'settled':False};account+=e['bound_nanocredits']
        elif k=='settle':
            a=pa[e['attempt_id']];check(not a['settled'] and 0<=e['accounted_nanocredits']<=a['bound'],'Prior settlement');account+=e['accounted_nanocredits']-a['bound'];a['settled']=True
        else:check(k in ('run_started','run_closed'),'Unexpected prior event')
        check(account<=250_000_000_000,'Prior cap')
    check(len(pa)==48 and all(a['settled'] for a in pa.values()) and account==nano(CARRY),'Prior final carry')
    run_dir='results/frontier-v6h/canary/'
    run=obj(run_dir+'run.json');slots=obj('data/frontier-v6h-canary-sessions.json');index={s['slot_id']:s for s in slots}
    check(len(index)==10 and run['slots']==slots and run['sessions_sha256']==digest(slots),'Frozen canary schedule')
    check(run['canary'] is True and run['test_hooks'] is False,'Real canary manifest')
    check((run['per_model_concurrency'],run['concurrency'],run['model_interval_seconds'],run['timeout_seconds'],run['max_retries'])==(8,40,2.0,180.0,2),'Runtime config')
    requests=lines(read(run_dir+'requests.jsonl'));responses=lines(read(run_dir+'responses.jsonl'));finals=lines(read(run_dir+'slot-outcomes.jsonl'))
    if not path(run_dir+'summary.json').is_file():
        return {'schema':'retrace.v6h-runtime-independent-audit.v1','passed':False,'status':'incomplete','final_closed':False,'primary_requests':0,'checks':count,'input_bindings':bindings}
    summary=obj(run_dir+'summary.json');check(summary['run_id']==run['run_id'],'Run identity')
    rq={};rp={};by_slot=defaultdict(list);raw_counts=Counter();error_bodies=[]
    def bound(slot):
        i,o,c=PRICES[slot['model']];return nano((Decimal(i)*c+Decimal(o)*slot['max_output_tokens'])/1_000_000)
    def usage_cost(slot,usage):
        i,o,c=PRICES[slot['model']];inp=usage['input_tokens'];out=usage['output_tokens']
        check(type(inp) is int and type(out) is int and 0<=inp<=c and 0<=out<=slot['max_output_tokens'],'Usage bounds')
        if 'total_tokens' in usage:check(usage['total_tokens']==inp+out,'Usage total')
        return nano((Decimal(i)*inp+Decimal(o)*out)/1_000_000)
    for row in requests:
        aid=row['attempt_id'];s=index[row['slot_id']];n=row['attempt_number']
        check(aid not in rq and type(n) is int and 1<=n<=3,'Request identity/number')
        check(aid==run['run_id']+':'+s['slot_id']+':attempt-'+str(n) and row['first_attempt'] is (n==1),'Canonical attempt identity')
        check(not s.get('history_from') and not s.get('input_from') and row['dependency_bindings']==[],'Canary has no histories')
        body={'model':s['model'],'instructions':s['instructions'],'input':[{'role':'user','content':s['input']}],
              'max_output_tokens':s['max_output_tokens'],'temperature':s['temperature'],'store':False,'previous_response_id':None,
              'agentic_memory':False,'tools':[],'tool_choice':'none','stream':True}
        check(row['request']==body and row['request_sha256']==digest(body),'Exact frozen request')
        check(nano(row['reserved_credits'])==bound(s),'Request reservation bound');rq[aid]=row
    for row in responses:
        aid=row['attempt_id'];check(aid in rq and aid not in rp,'Response identity');q=rq[aid];s=index[q['slot_id']]
        check(row['run_id']==run['run_id'] and all(row[k]==s[k] for k in ('slot_id','model','case_id','condition','phase')),'Response slot identity')
        check(row['attempt_number']==q['attempt_number'] and row['first_attempt']==q['first_attempt'] and row['issued'] is True,'Response attempt identity')
        meta=row['stream_evidence'];name=hash_(aid.encode())+'.sse';check(PureWindowsPath(meta['raw_stream_path']).name==name,'Stream filename')
        raw=read(run_dir+'streams/'+name)
        check(meta['closed'] is True and meta['credential_redacted'] is False and meta['received_bytes']==len(raw),'Raw stream completeness')
        check(meta['received_sha256']==hash_(raw)==meta['saved_sha256'] and meta['http_status']==row['http_status'],'Raw stream hashes/status')
        check(nano(row['reserved_credits'])==bound(s),'Response bound')
        if row['http_status']==429:
            payload=strict_json(raw.decode());err=payload.get('error',{})
            check(err.get('type')=='rate_limit_error' and err.get('code')=='rate_limit_exceeded','Explicit rate-limit body')
            check(row['terminal_valid'] is False and row['model_outcome']=='http_429' and row['error']=='http_429','429 classification')
            check(row['usage'] is None and row['settled_credits'] is None and row['output_text']=='','Unknown429 usage retained')
            check(row['retry_after']=='60' and 60*2**(row['attempt_number']-1)<=row['retry_cooldown_seconds']<=60*2**(row['attempt_number']-1)+5,'Logged cooldown range')
            error_bodies.append({'attempt_id':aid,'bytes':len(raw),'sha256':hash_(raw),'type':err['type'],'code':err['code'],'message':err.get('message'),'retry_after':row['retry_after']})
            raw_counts['http_429']+=1
        else:
            check(row['http_status']==200 and row['terminal_valid'] is True and row['error'] is None,'Successful HTTP terminal')
            parsed=parse_sse(raw);terminal=parsed['response'];check(terminal==strict_json(row['raw_response']),'Raw SSE to recorded terminal')
            check(parsed['terminal']==row['stream_terminal_event'] and parsed['event_count']==row['stream_event_count'],'SSE metadata')
            check(terminal['model']==s['model'] and terminal['usage']==row['usage'] and terminal['status']==row['response_status'],'Terminal identity/usage/status')
            text=output_text(terminal)
            nested=''.join(c['text'] for item in terminal.get('output',[]) if item.get('type')=='message' and item.get('role')=='assistant' for c in item.get('content',[]) if c.get('type')=='output_text')
            check(not nested or nested==text,'Terminal duplicate text agreement')
            expected='completed' if terminal['status']=='completed' else 'truncated_max_output_tokens'
            check(row['model_outcome']==expected and row['output_text']==(text if expected=='completed' else '') and row['partial_output_text']==(text if expected!='completed' else ''),'Delivered output binding')
            check(nano(row['settled_credits'])==usage_cost(s,row['usage']),'Independent token settlement');raw_counts[expected]+=1
        rp[aid]=row;by_slot[row['slot_id']].append(row)
    check(set(rq)==set(rp),'No orphan request/response')
    for sid,rows in by_slot.items():
        rows.sort(key=lambda r:r['attempt_number']);check([r['attempt_number'] for r in rows]==list(range(1,len(rows)+1)),'Attempt prefixes')
        for old,new in zip(rows,rows[1:]):
            check(old['http_status']==429,'Only429 retry')
            check(rq[old['attempt_id']]['request']==rq[new['attempt_id']]['request'],'No changed retry body')
            check(stamp(rq[new['attempt_id']]['at'])>=stamp(old['at'])+old['retry_cooldown_seconds']-.02,'Retry cooldown UTC lower bound')
    check(len(finals)==10 and {f['slot_id'] for f in finals}==set(index),'Every final slot')
    for f in finals:
        last=by_slot[f['slot_id']][-1];check(f['slot_final'] is True and f['attempt_id']==last['attempt_id'],'Last-attempt final')
        check(all(f.get(k)==v for k,v in last.items()) and f['attempts_issued']==len(by_slot[f['slot_id']]),'Final content/count')
        check(f['first_attempt_id']==by_slot[f['slot_id']][0]['attempt_id'],'First attempt binding')
    # UTC timing is observational; monotonic timing cannot be reconstructed.
    minimum_margin=None;timing=[];active=0;peak=0;events=[];model_starts=defaultdict(list)
    for q in requests:
        t=stamp(q['at']);model_starts[q['request']['model']].append(t);events.append((t,1));events.append((stamp(rp[q['attempt_id']]['at']),-1))
        for r in responses:
            if r['http_status']==429 and stamp(r['at'])<t:
                margin=t-stamp(r['at'])-r['retry_cooldown_seconds'];check(margin>=-.02,'Global cooldown UTC lower bound')
                minimum_margin=margin if minimum_margin is None else min(minimum_margin,margin)
    for starts in model_starts.values():check(all(b-a>=1.98 for a,b in zip(sorted(starts),sorted(starts)[1:])),'Per-model interval')
    for _,delta in sorted(events):active+=delta;peak=max(peak,active)
    check(peak<=40,'Observed concurrency bound')
    check(hash_(read(LEDGER))==LEDGER_HASH,'Closed ledger snapshot hash');ledger=lines(read(LEDGER));prev='0'*64;account=nano(CARRY);attempts={};maximum=account
    for seq,row in enumerate(ledger,1):
        check(row['seq']==seq and row['previous_sha256']==prev and row['sha256']==digest({k:v for k,v in row.items() if k!='sha256'}),'Ledger chain')
        prev=row['sha256'];e=row['event'];k=e['kind']
        if k=='initialize':check(seq==1 and e['historical_credits']==str(CARRY) and e['historical_sha256']==authorization['prior_ledger_sha256'] and e['cap_credits']=='250','Ledger carry')
        elif k=='reserve':
            aid=e['attempt_id'];check(aid in rq and aid not in attempts,'Reservation identity');s=index[rq[aid]['slot_id']]
            check(e['bound_nanocredits']==bound(s) and e['model']==s['model'] and e['attempt_number']==rq[aid]['attempt_number'],'Ledger bound/identity')
            check(stamp(row['at'])<=stamp(rq[aid]['at']),'Reservation precedes request');attempts[aid]={'bound':e['bound_nanocredits'],'settled':False,'retained':False};account+=e['bound_nanocredits']
        elif k in ('settle','retain_429'):
            aid=e['attempt_id'];a=attempts[aid];r=rp[aid];check(not a['settled'] and not a['retained'] and e['response_sha256']==digest(r),'Response/accounting binding')
            if k=='settle':
                check(e['accounted_nanocredits']==nano(r['settled_credits'])<=a['bound'],'Settlement amount');a['settled']=True;account+=e['accounted_nanocredits']-a['bound']
            else:check(r['http_status']==429 and r['usage'] is None,'Retention reason');a['retained']=True
        elif k=='run_started':check(e['run_id']==run['run_id'] and e['sessions_sha256']==digest(slots) and e['planned']==10,'Ledger run start')
        elif k=='run_closed':check(e['run_id']==run['run_id'] and e['issued_attempts']==len(requests) and e['issued_slots']==10 and e['unissued_slots']==0,'Ledger run close')
        else:raise ValueError('Unexpected ledger event '+str(k))
        maximum=max(maximum,account);check(account<=250_000_000_000,'Cumulative cap')
    check(set(attempts)==set(rq) and all(a['settled'] or a['retained'] for a in attempts.values()),'Ledger closure')
    check(ledger[-1]['event']['kind']=='run_closed','Closed ledger snapshot')
    completed=sum(f['model_outcome']=='completed' for f in finals);first_completed=sum(r['first_attempt'] and r['model_outcome']=='completed' for r in responses)
    check(summary['status']=='completed' and summary['stop_reasons']==[] and summary['all_scheduled_outcomes_recorded'] is True,'Closed schedule')
    check(summary['planned']==summary['issued_slots']==summary['slot_outcomes']==10 and summary['issued_attempts']==summary['responses']==15,'Summary counts')
    check(summary['completed']==summary['eventual_completed']==summary['eventual_terminal_slots']==completed and summary['first_attempt_completed']==first_completed,'First/eventual counts')
    check(summary['http_429_attempts']==6 and summary['retries']==5 and summary['unissued_slot_ids']==[] and summary['issued_without_outcome_attempt_ids']==[],'Summary retry/closure')
    budget=summary['budget'];check(budget['accounted_credits']==credits(account) and budget['remaining_credits']==credits(250_000_000_000-account) and budget['ledger_sha256']==prev,'Budget snapshot')
    check(budget['settled_attempts']==9 and budget['unknown_429_attempts_retained']==budget['unsettled_attempts']==6 and budget['actual_billed_credits'] is None,'Budget uncertainty')
    primary=0
    for f in path('results/frontier-v6h').rglob('requests.jsonl'):
        if f==path(run_dir+'requests.jsonl'):continue
        for r in lines(f.read_bytes()):primary+=str(r.get('slot_id','')).startswith('v6h::')
    check(primary==0,'Primary request observed')
    if path(run_dir+'semantic-score.json').is_file():
        sem=obj(run_dir+'semantic-score.json');check(sem['planned']==10 and sem['observed_attempts']==15 and sem['final_operational_completed']==completed,'Semantic-score accounting')
    # Require a stable read of every captured artifact. The canonical live ledger
    # is intentionally not read: subsequent separately authorized runs may append.
    for name,raw in saved.items():check(path(aliases.get(name,name)).read_bytes()==raw,'Artifact changed during audit: '+name)
    return {'schema':'retrace.v6h-runtime-independent-audit.v1','passed':True,'status':'closed_canary_gate_failed',
        'final_closed':True,'primary_requests':primary,'checks':count,'frozen_files':844,'protected_historical_files':695,
        'planned_slots':10,'issued_attempts':len(requests),'first_attempt_completed':first_completed,'eventual_completed':completed,
        'http_429_attempts':6,'retry_attempts':5,'raw_stream_counts':dict(raw_counts),'canary_dispatch_gate_passed':completed==10,
        'historical_carry_credits':str(CARRY),'cumulative_accounted_credits':credits(account),
        'known_usage_credits':credits(sum(nano(r['settled_credits']) for r in responses if r['settled_credits'] is not None)),
        'unknown429_full_bounds_credits':credits(sum(a['bound'] for a in attempts.values() if a['retained'])),
        'maximum_observed_accounted_credits':credits(maximum),'ledger_entries':len(ledger),'ledger_chain_sha256':prev,
        'observed_peak_inflight_upper_proxy':peak,'minimum_logged_global_cooldown_margin_seconds':round(minimum_margin,6),
        'rate_limit_bodies':error_bodies,'input_bindings':bindings,
        'limits':['Local hashes are not signed provider authenticity.','UTC logs are not a replay of monotonic clocks or server admission timestamps.',
                  'The429 payload gives no numeric concurrency, token, or request quota.','No paid probe, primary inference, or semantic repair was performed by this audit.',
                  'This snapshot audits the original h canary only; later ledger appends and transport revisions are separate.',
                  'Earlier c/d/e carries are hash-protected inherited evidence; this verifier independently replays f48 settlements and h15 attempts.',
                  'Current canary slots have no history/projection dependencies; full primary dependency integrity remains a future audit obligation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--aliases',type=Path)
    a=p.parse_args();aliases=strict_json(a.aliases.read_text()) if a.aliases else None
    print(json.dumps(audit(a.root,aliases),ensure_ascii=False,sort_keys=True,indent=2))

if __name__=='__main__':main()
