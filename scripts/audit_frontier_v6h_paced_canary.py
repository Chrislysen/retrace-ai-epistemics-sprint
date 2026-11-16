"""Independent read-only audit of the paced v6h canary; explicit exclusive output.

No provider, credential, mutation, or production decoder is used by audit().
Closed ledger bytes are preserved inside its result so later appends are safe.
"""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path, PureWindowsPath
import argparse, base64, json, re, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.audit_frontier_v6f_run import parse_sse, strict_json, output_text
from scripts.audit_frontier_v6h_runtime import canon,digest,nano,credits,PRICES
FREEZE='data/frontier-v6h-paced-canary-freeze.json'
FREEZE_SHA='7fafe5ed48ad64c415800cf2a4fb9530e251867936db8a70e61ba2875ec517f6'
RUN='results/frontier-v6h-paced/canary/'
PREFIX='data/frontier-v6h-ledger-after-quota-probe.jsonl'
PREFIX_SHA='84eac421c782e3502e32eb8bf2a0d8f328130b3190e88cc378ed2db7aaa22ba1'
CLOSED='data/frontier-v6h-ledger-after-paced-canary.jsonl'
CLOSED_SHA='0f8e54bbe0a13fbf56f50e3c40b43578e63200ab02bba130b7f8c4eb704057f6'
BASE_ARCHIVE='deliverables/retrace-v6-sprint-artifact.zip'
BASE_ARCHIVE_SHA='3353795e3b379202bb3bf073648882e00831c884c8116a7e27fcc91a70097cfb'
TOLERANCE=.035  # UTC evidence is coarser than the actual monotonic scheduler.

def sha(raw):return sha256(raw).hexdigest()
def timestamp(value):return datetime.fromisoformat(value).timestamp()
def jsonlines(raw):
    if raw and not raw.endswith(b'\n'):raise ValueError('Truncated JSONL snapshot')
    return [strict_json(r.decode()) for r in raw.splitlines() if r.strip()]

def unfinished_sse(raw,require):
    """Independently verify a saved, frame-complete but nonterminal SSE prefix.

    This deliberately cannot create a terminal or infer usage from deltas.
    An incomplete byte/frame tail would fail this particular observed-prefix
    check; it would remain preserved evidence, not be repaired or discarded.
    """
    lines=re.split(r'\r\n|\r|\n',raw.decode('utf-8'))
    require(lines[-1]=='','Partial SSE last line complete')
    data=[];name=None;begun=False;count=0;last_seq=None;first_seq=None;rid=None;types=Counter()
    for line in lines[:-1]:
        if line:
            if line.startswith(':'):continue
            begun=True;field,sep,value=line.partition(':')
            if value.startswith(' '):value=value[1:]
            if field=='data':data.append(value if sep else '')
            if field=='event':require(name is None,'Duplicate SSE event field');name=value
            continue
        if data:
            payload='\n'.join(data);require(payload!='[DONE]','No fabricated done')
            event=strict_json(payload);require(isinstance(event,dict) and isinstance(event.get('type'),str),'Partial SSE typed object')
            kind=event['type'];require(name in (None,'message',kind),'Partial SSE type agreement')
            require(kind not in ('response.completed','response.incomplete','response.failed','response.cancelled','error'),'No terminal in timeout prefix')
            seq=event.get('sequence_number')
            if seq is not None:
                require(type(seq) is int and (last_seq is None or seq==last_seq+1),'Partial SSE consecutive sequence')
                if first_seq is None:first_seq=seq
                last_seq=seq
            response=event.get('response')
            if isinstance(response,dict):
                require(response.get('status') not in ('completed','incomplete','failed','cancelled'),'No nested terminal')
                if response.get('id') is not None:require(rid in (None,response['id']),'Partial SSE identity');rid=response['id']
            if kind.endswith('.delta'):require(isinstance(event.get('delta'),str),'Partial delta type')
            types[kind]+=1;count+=1;require(count<=100000,'Partial SSE bounded event count')
        data=[];name=None;begun=False
    require(not data and not begun and count>0 and types['response.created']==1,'Complete nonterminal frame prefix')
    return {'events':count,'event_types':dict(types),'first_sequence':first_seq,'last_sequence':last_seq,'terminal_present':False,'frame_complete_prefix':True}

def audit(root=ROOT, frozen_aliases=None, ledger_snapshot=None, base_archive=None):
    root=Path(root).resolve();aliases=frozen_aliases or {};files={};bindings={};checks=0
    def require(ok,message):
        nonlocal checks
        checks+=1
        if not ok:raise ValueError(message)
    def resolve(name):
        # A separate supplement must not recursively package the original ZIP.
        # The explicit external path is valid only for this one pinned entry;
        # read() still binds it to its original relative name and checks bytes.
        if name==BASE_ARCHIVE and base_archive is not None:
            require(Path(base_archive).is_file(),'Explicit base archive exists')
            return Path(base_archive).resolve()
        p=(root/aliases.get(name,name)).resolve();require(p.is_relative_to(root),'Path escape');return p
    def read(name):
        if name not in files:
            files[name]=resolve(name).read_bytes();bindings[name]={'sha256':sha(files[name]),'bytes':len(files[name])}
        return files[name]
    def obj(name):return strict_json(read(name).decode())
    for a,b in aliases.items():
        if not (a.endswith('/active.lock') and b.endswith('.txt') and (root/b).resolve().is_relative_to(root)):raise ValueError('Invalid inert lock alias')
    require(sha(read(FREEZE))==FREEZE_SHA,'Paced freeze changed');freeze=obj(FREEZE);require(len(freeze['files'])==918,'Expected918 frozen inputs')
    frozen={}
    for r in freeze['files']:
        require(r['path'] not in frozen,'Duplicate freeze path');frozen[r['path']]=r['sha256'];require(sha(read(r['path']))==r['sha256'],'Frozen file changed: '+r['path'])
    require(frozen.get(BASE_ARCHIVE)==BASE_ARCHIVE_SHA,'Original base ZIP pin')
    require(set(aliases)<=set(frozen),'Unfrozen alias')
    if not resolve(RUN+'summary.json').is_file():
        return {'schema':'retrace.v6h-paced-canary-audit.v1','passed':False,'final_closed':False,'status':'incomplete','checks':checks}
    summary=obj(RUN+'summary.json');manifest=obj(RUN+'run.json');slots=obj('data/frontier-v6h-canary-sessions.json');index={s['slot_id']:s for s in slots}
    require(len(index)==10 and manifest['slots']==slots and manifest['sessions_sha256']==digest(slots),'Exact original ten-slot schedule')
    config=freeze['runtime_config']
    require(config=={'global_interval_seconds':5.0,'model_interval_seconds':2.0,'per_model_concurrency':1,'global_concurrency':3,'timeout_seconds':180.0,'max_retries':2},'Frozen pacing config')
    for k in ('global_interval_seconds','model_interval_seconds','per_model_concurrency','timeout_seconds','max_retries'):require(manifest[k]==config[k],'Manifest '+k)
    require(manifest['concurrency']==3 and manifest['test_hooks'] is False and 'round_robin' in manifest['ready_model_order'],'Real fair scheduler')
    requests=jsonlines(read(RUN+'requests.jsonl'));responses=jsonlines(read(RUN+'responses.jsonl'));finals=jsonlines(read(RUN+'slot-outcomes.jsonl'))
    rq={};rp={};groups=defaultdict(list);costs={};body_signatures={};errors=[];streams=Counter();unfinished=[]
    old_requests=jsonlines(read('results/frontier-v6h/canary/requests.jsonl'))
    old_body={r['slot_id']:r['request'] for r in old_requests}
    for q in requests:
        aid=q['attempt_id'];s=index[q['slot_id']];n=q['attempt_number'];require(aid not in rq and type(n) is int and 1<=n<=3,'Unique bounded attempt')
        require(aid==manifest['run_id']+':'+s['slot_id']+':attempt-'+str(n) and q['first_attempt'] is (n==1),'Attempt naming/first flag')
        require(q['dependency_bindings']==[] and not s.get('history_from') and not s.get('input_from'),'Canary statelessness')
        body={'model':s['model'],'instructions':s['instructions'],'input':[{'role':'user','content':s['input']}],'max_output_tokens':s['max_output_tokens'],'temperature':s['temperature'],
              'store':False,'previous_response_id':None,'agentic_memory':False,'tools':[],'tool_choice':'none','stream':True}
        require(q['request']==body==old_body[s['slot_id']] and q['request_sha256']==digest(body),'Byte-equivalent original provider body')
        i,o,ctx=PRICES[s['model']];bound=nano((Decimal(i)*ctx+Decimal(o)*s['max_output_tokens'])/1_000_000)
        require(nano(q['reserved_credits'])==bound,'Conservative reservation');rq[aid]=q;body_signatures[s['slot_id']]=digest(body)
    for r in responses:
        aid=r['attempt_id'];require(aid in rq and aid not in rp,'Response identity');q=rq[aid];s=index[q['slot_id']]
        require(all(r[k]==s[k] for k in ('slot_id','case_id','model','condition','phase')) and r['run_id']==manifest['run_id'],'Response slot/run identity')
        require(r['attempt_number']==q['attempt_number'] and r['first_attempt']==q['first_attempt'] and r['issued'] is True,'Response attempt metadata')
        meta=r['stream_evidence'];name=sha(aid.encode())+'.sse';require(PureWindowsPath(meta['raw_stream_path']).name==name,'Stream name');raw=read(RUN+'streams/'+name)
        require(meta['closed'] is True and meta['credential_redacted'] is False and meta['received_bytes']==len(raw),'Complete preserved stream')
        require(sha(raw)==meta['received_sha256']==meta['saved_sha256'] and meta['http_status']==r['http_status'],'Stream metadata hashes')
        if r['http_status']==429:
            err=strict_json(raw.decode()).get('error',{});require(err.get('code')=='rate_limit_exceeded' and err.get('type')=='rate_limit_error','Explicit429 body')
            require(r['model_outcome']=='http_429' and r['error']=='http_429' and not r['terminal_valid'] and r['usage'] is None and r['settled_credits'] is None,'429 outcome/accounting')
            require(r['retry_after']=='60' and 60*2**(r['attempt_number']-1)<=r['retry_cooldown_seconds']<=60*2**(r['attempt_number']-1)+5,'Retry policy cooldown')
            errors.append({'slot_id':r['slot_id'],'attempt':r['attempt_number'],'at':r['at'],'body_sha256':sha(raw),'error_type':err['type'],'error_code':err['code'],'retry_after':r['retry_after']});streams['http_429']+=1
        elif r['terminal_valid']:
            require(r['http_status']==200 and r['error'] is None,'Terminal HTTP status');parsed=parse_sse(raw);terminal=parsed['response']
            require(terminal==strict_json(r['raw_response']) and parsed['terminal']==r['stream_terminal_event'] and parsed['event_count']==r['stream_event_count'],'Independent raw SSE replay')
            require(terminal['model']==s['model'] and terminal['usage']==r['usage'] and terminal['status']==r['response_status'],'Terminal model/status/usage')
            text=output_text(terminal);nested=''.join(c['text'] for x in terminal.get('output',[]) if x.get('type')=='message' and x.get('role')=='assistant' for c in x.get('content',[]) if c.get('type')=='output_text')
            require(not nested or nested==text,'Duplicate output text agreement');outcome='completed' if terminal['status']=='completed' else 'truncated_max_output_tokens'
            require(r['model_outcome']==outcome and r['output_text']==(text if outcome=='completed' else '') and r['partial_output_text']==(text if outcome!='completed' else ''),'Delivered text binding')
            u=r['usage'];i,o,ctx=PRICES[s['model']];require(type(u['input_tokens']) is int and type(u['output_tokens']) is int and 0<=u['input_tokens']<=ctx and 0<=u['output_tokens']<=s['max_output_tokens'],'Usage bounds')
            if 'total_tokens' in u:require(u['total_tokens']==u['input_tokens']+u['output_tokens'],'Usage total')
            cost=nano((Decimal(i)*u['input_tokens']+Decimal(o)*u['output_tokens'])/1_000_000);require(cost==nano(r['settled_credits']),'Independent settlement');costs[aid]=cost;streams[outcome]+=1
        else:
            require(r['model_outcome']=='operational_failure' and r['error']=='timeout' and r['settled_credits'] is None,'Explicit observed timeout failure')
            require(r['usage'] is None and r['raw_response'] is None and r['response_status'] is None and r['stream_terminal_event'] is None and r['output_text']==r['partial_output_text']=='','No invented terminal/output/usage')
            partial=unfinished_sse(raw,require);require(partial['events']==r['stream_event_count'],'Partial SSE event count')
            unfinished.append({'slot_id':r['slot_id'],'attempt_id':aid,'reason':r['error'],'bytes':len(raw),'sha256':sha(raw),**partial});streams['operational_failure']+=1
        rp[aid]=r;groups[r['slot_id']].append(r)
    require(set(rq)==set(rp),'No orphan attempt');require(len(finals)==10 and {f['slot_id'] for f in finals}==set(index),'All ten final outcomes')
    for sid,rs in groups.items():
        rs.sort(key=lambda r:r['attempt_number']);require([r['attempt_number'] for r in rs]==list(range(1,len(rs)+1)),'Attempt prefix')
        for a,b in zip(rs,rs[1:]):require(a['http_status']==429,'No non429 retry')
    for f in finals:
        if f.get('issued') is True:
            rs=groups[f['slot_id']];require(f['slot_final'] is True and all(f.get(k)==v for k,v in rs[-1].items()),'Final exactly last attempt')
            require(f['attempts_issued']==len(rs) and f['first_attempt_id']==rs[0]['attempt_id'],'Final count/first binding')
        else:require(f['slot_id'] not in groups and f['model_outcome'] in ('not_issued_global_stop','not_issued_dependency_failed'),'Explicit unissued final')
    # Reconstruct ready-model priority from recorded completions. UTC tolerance
    # reflects Windows clock granularity, not relaxed production pacing.
    models=list(dict.fromkeys(s['model'] for s in slots));cursor=0;state={sid:'pending' for sid in index};notbefore=defaultdict(float);active={};model_last={};global_last=None;cooldown=0.;gaps=[];peak=0;order=[]
    ordered_responses=sorted(responses,key=lambda r:timestamp(r['at']));seen_response=0
    for q in requests:
        t=timestamp(q['at'])
        while seen_response<len(ordered_responses) and timestamp(ordered_responses[seen_response]['at'])<=t:
            r=ordered_responses[seen_response];seen_response+=1;active.pop(r['attempt_id'],None)
            if r['http_status']==429:
                due=timestamp(r['at'])+r['retry_cooldown_seconds'];cooldown=max(cooldown,due)
                state[r['slot_id']]='pending' if r['attempt_number']<3 else 'done';notbefore[r['slot_id']]=due
            else:state[r['slot_id']]='done'
        require(len(active)<3 and all(m!=q['request']['model'] for m in active.values()),'Global3/per-model1 active bound')
        require(t+TOLERANCE>=cooldown and t+TOLERANCE>=notbefore[q['slot_id']],'Global and own429 cooldown')
        if global_last is not None:gaps.append(t-global_last);require(t-global_last>=5-TOLERANCE,'Global UTC admission gap')
        if q['request']['model'] in model_last:require(t-model_last[q['request']['model']]>=2-TOLERANCE,'Per-model UTC gap')
        eligible=None
        for model in models[cursor:]+models[:cursor]:
            if model in active.values():continue
            for s in slots:
                if s['model']==model and state[s['slot_id']]=='pending' and t+TOLERANCE>=notbefore[s['slot_id']]:eligible=s['slot_id'];break
            if eligible:break
        require(eligible==q['slot_id'],'Ready-model round-robin order')
        model=q['request']['model'];cursor=(models.index(model)+1)%len(models);state[q['slot_id']]='active';active[q['attempt_id']]=model;peak=max(peak,len(active));global_last=t;model_last[model]=t
        order.append({'slot_id':q['slot_id'],'attempt':q['attempt_number'],'at':q['at']})
    prefix=read(PREFIX);require(sha(prefix)==PREFIX_SHA and len(jsonlines(prefix))==69,'Original69-entry snapshot unchanged')
    require(read(freeze['ledger_prefix_path'])==prefix and freeze['ledger_prefix_sha256']==PREFIX_SHA,'Execution prefix equality')
    preserved=read(CLOSED);require(sha(preserved)==CLOSED_SHA,'Closed95-entry ledger snapshot')
    live=ledger_snapshot if ledger_snapshot is not None else preserved
    require(live==preserved,'Supplied ledger equals preserved closed snapshot')
    require(isinstance(live,bytes) and live.startswith(prefix),'Ledger preserves exact prefix')
    rawlines=live.splitlines(keepends=True);tail=summary['budget']['ledger_sha256'];end=next((i+1 for i,l in enumerate(rawlines) if strict_json(l.decode())['sha256']==tail),None)
    require(end is not None and end==len(rawlines),'Closed ledger endpoint');closed=b''.join(rawlines[:end]);ledger=jsonlines(closed);previous='0'*64;account=nano('43.633207445');res={};settled={};retained=set();halts={};peak_account=account
    all_rsp={}
    for folder in ('results/frontier-v6h/canary','results/frontier-v6h-quota-probe/round-1','results/frontier-v6h-quota-probe/round-2','results/frontier-v6h-quota-probe/round-3'):
        all_rsp.update({r['attempt_id']:r for r in jsonlines(read(folder+'/responses.jsonl'))})
    all_rsp.update(rp)
    for seq,row in enumerate(ledger,1):
        require(row['seq']==seq and row['previous_sha256']==previous and row['sha256']==digest({k:v for k,v in row.items() if k!='sha256'}),'Ledger chain');previous=row['sha256'];e=row['event'];kind=e['kind']
        if kind=='initialize':require(seq==1 and e['historical_credits']=='43.633207445' and e['cap_credits']=='250','Historical carry')
        elif kind=='reserve':
            aid=e['attempt_id'];require(aid not in res and type(e['bound_nanocredits']) is int and e['bound_nanocredits']>0,'Unique reservation');res[aid]=e['bound_nanocredits'];account+=res[aid]
            if seq>69:require(aid in rq and res[aid]==nano(rq[aid]['reserved_credits']) and timestamp(row['at'])<=timestamp(rq[aid]['at']),'New reserve/request binding')
        elif kind in ('settle','retain_429'):
            aid=e['attempt_id'];r=all_rsp[aid];require(aid in res and aid not in settled and aid not in retained and e['response_sha256']==digest(r),'Ledger response binding')
            if kind=='settle':require(0<=e['accounted_nanocredits']<=res[aid] and e['accounted_nanocredits']==nano(r['settled_credits']),'Ledger settlement');settled[aid]=e['accounted_nanocredits'];account+=settled[aid]-res[aid]
            else:require(r['http_status']==429 and r['usage'] is None,'Unknown429 retention');retained.add(aid)
        elif kind=='halt':
            aid=e['attempt_id'];require(summary['status']=='stopped' and e['run_id']==manifest['run_id'] and aid in rp and rp[aid]['model_outcome']=='operational_failure' and e['reason']==rp[aid]['error'],'Halt/response binding');halts[aid]=e
        else:
            require(kind in ('run_started','run_closed'),'Unknown ledger event')
            if seq>69:
                require(e['run_id']==manifest['run_id'],'New lifecycle run binding')
                if kind=='run_started':require(seq==70 and e['planned']==10 and e['sessions_sha256']==digest(slots),'Run start/session binding')
                else:require(seq==len(ledger) and e['status']==summary['status'] and e['issued_attempts']==len(rq) and e['issued_slots']==len(groups) and e['unissued_slots']==10-len(groups) and e['administrative'] is False,'Exact actual closure counts')
        require(account<=250_000_000_000,'Cumulative cap');peak_account=max(peak_account,account)
    require(ledger[-1]['event']['kind']=='run_closed' and ledger[-1]['event']['run_id']==manifest['run_id'],'Closed target run')
    require({aid for aid in res if aid.startswith(manifest['run_id']+':')}==set(rq),'All new reserves journaled')
    unknown_operational=set(res)-set(settled)-retained
    require(unknown_operational==set(halts) and all(rp[aid]['settled_credits'] is None for aid in unknown_operational),'Every non429 unknown has explicit halted failure and full bound retained')
    budget=summary['budget'];require(credits(account)==budget['accounted_credits'] and previous==budget['ledger_sha256'],'Final budget summary')
    require(budget['attempt_reservations']==len(res) and budget['settled_attempts']==len(settled) and budget['unknown_429_attempts_retained']==len(retained),'Budget counts')
    require(budget['unsettled_attempts']==len(retained)+len(unknown_operational) and budget['halted']==bool(halts),'Unknown counts and halted state')
    require(summary['planned']==summary['slot_outcomes']==10 and summary['all_scheduled_outcomes_recorded'] and summary['issued_attempts']==summary['responses']==len(rq),'Summary scheduled/attempt counts')
    completed=sum(r['model_outcome']=='completed' for r in responses);valid=sum(r['terminal_valid'] for r in responses);first=sum(r['first_attempt'] and r['model_outcome']=='completed' for r in responses)
    require(summary['completed']==summary['eventual_completed']==completed and summary['first_attempt_completed']==first,'First/eventual completions')
    require(summary['valid_terminal_records']==valid and summary['http_429_attempts']==len(errors) and summary['retries']==len(rq)-len(groups),'Summary retry/terminal counts')
    require(summary['issued_without_outcome_attempt_ids']==[],'No orphan attempts')
    gate=summary['status']=='completed' and valid==10 and summary['issued_operational_failures']==0 and summary['dependency_skips']==0 and summary['unissued_slot_ids']==[]
    require(summary['issued_operational_failures']==len(unknown_operational),'Operational failure summary')
    primary_paths=['results/frontier-v6h/primary/requests.jsonl','results/frontier-v6h-paced/primary/requests.jsonl']
    for name in primary_paths:
        require(not resolve(name).exists() or not jsonlines(read(name)),'No primary request issued')
    require(sha(read(PREFIX))==PREFIX_SHA,'Prefix still unchanged')
    for name,raw in files.items():require(resolve(name).read_bytes()==raw,'Artifact changed during audit')
    return {'schema':'retrace.v6h-paced-canary-audit.v1','passed':True,'final_closed':True,'canary_dispatch_gate_passed':gate,'checks':checks,
        'frozen_files':918,'planned_slots':10,'issued_attempts':len(rq),'first_attempt_completed':first,'eventual_completed':completed,'valid_terminals':valid,
        'http_429_attempts':len(errors),'retry_attempts':len(rq)-len(groups),'streams':dict(streams),'raw_rate_limits':errors,'unfinished_streams':unfinished,
        'primary_requests':0,'primary_request_paths_checked':primary_paths,
        'observed_admission_order':order,'observed_minimum_utc_start_gap_seconds':min(gaps) if gaps else None,'observed_peak_concurrency_proxy':peak,
        'ready_round_robin_verified':True,'same_original_request_bodies':True,'body_sha256_by_slot':body_signatures,
        'prior_cumulative_accounted_credits':'45.587397366','known_new_usage_credits':credits(sum(costs.values())),
        'new_unknown_429_bounds_credits':credits(sum(res[x] for x in retained if x in rq)),
        'new_unknown_operational_bounds_credits':credits(sum(res[x] for x in unknown_operational if x in rq)),
        'new_unknown_full_bounds_credits':credits(sum(res[x] for x in retained|unknown_operational if x in rq)),
        'phase_accounting_attempts':len(res),'phase_settled_attempts':len(settled),'phase_unknown_429_attempts':len(retained),'phase_unknown_operational_attempts':len(unknown_operational),
        'cumulative_accounted_credits':credits(account),'maximum_running_accounted_credits':credits(peak_account),
        'ledger_entries':len(ledger),'ledger_chain_sha256':previous,'closed_ledger_bytes_base64':base64.b64encode(closed).decode(),
        'closed_ledger_file_sha256':sha(closed),'input_bindings':bindings,
        'limits':['Post-run independent local integrity audit, not provider cryptographic authentication or source entailment.',
                  'UTC timing permits 35 ms evidence tolerance; monotonic admission implementation is separately frozen/tested. No numeric quota is inferred.',
                  'Same ten previously observed development slots; replication is transport feasibility, not independent scientific generalization.',
                  'A passing eventual-terminal canary is not evidence that thousands of heavy requests will avoid rate limiting.',
                  'The earlier seven unknown attempts remain inside the historical carry; the 42 phase reservations here comprise 33 settled, eight retained HTTP 429s and one retained timeout.',
                  'No history dependencies occur in these canary slots; primary replay will require its own audit.']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--write',action='store_true');p.add_argument('--aliases',type=Path);p.add_argument('--ledger-base64',type=Path);p.add_argument('--base-zip',type=Path)
    a=p.parse_args();aliases=strict_json(a.aliases.read_text()) if a.aliases else None;snapshot=base64.b64decode(a.ledger_base64.read_text()) if a.ledger_base64 else None
    result=audit(a.root,aliases,snapshot,a.base_zip)
    if a.write:
        if not result['final_closed']:raise ValueError('Refuse to save a final audit before closure')
        source=Path(__file__).read_text(encoding='utf-8');result['auditor_source']={'path':'scripts/audit_frontier_v6h_paced_canary.py','sha256':sha(source.encode()),'text':source}
        target=Path(a.root)/RUN
        with (target/'runtime-audit.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
        report=('# Independent paced-canary runtime audit\n\n'
            f"Integrity passed: {result['checks']} checks; {result['frozen_files']} frozen files unchanged. The dispatch gate passed: {result['canary_dispatch_gate_passed']}.\n\n"
            f"Scheduled 10 slots, issued {result['issued_attempts']} attempts, first-attempt completions {result['first_attempt_completed']}, eventual completions {result['eventual_completed']}, valid terminals {result['valid_terminals']}, HTTP 429 attempts {result['http_429_attempts']}. Original provider bodies match exactly. Every raw stream, final outcome and ledger binding is preserved. No primary requests were issued.\n\n"
            f"Ready-model rotation, global 3/per-model 1 concurrency and global cooldown are consistent with the journals. Minimum UTC start gap: {result['observed_minimum_utc_start_gap_seconds']:.6f} seconds; the 35 ms UTC evidence tolerance is distinct from the monotonic 5-second scheduler policy.\n\n"
            "The GLM5.2 refuter timeout preserved 4,174,049 bytes: 20,186 complete SSE frames, consecutive sequences 0–20,185, including 20,182 reasoning deltas and no terminal event. No response, answer or usage was invented. The 180-second timeout remains an operational failure with its entire reservation retained; it was not retried. This is a complete saved byte prefix, not a completed response.\n\n"
            f"Known new usage: {result['known_new_usage_credits']} credits; new full unknown reservations: {result['new_unknown_full_bounds_credits']} credits ({result['new_unknown_429_bounds_credits']} for two rate-limit attempts, {result['new_unknown_operational_bounds_credits']} for the timeout); cumulative conservative accounting: {result['cumulative_accounted_credits']} credits. These are not a verified invoice.\n\n"
            f"Closed ledger: {result['ledger_entries']} entries, file SHA256 {result['closed_ledger_file_sha256']}. The new data/frontier-v6h-ledger-after-paced-canary.jsonl preserves those bytes, and they are embedded in runtime-audit.json so later authorized appends cannot alter the audited boundary. Auditor source and hash are also embedded for reproduction.\n\n"
            "The numerical provider quota remains unknown. Both rate-limit payloads give a 60-second retry interval but no numerical request, token or concurrency capacity. The serial tiny-prompt probe did not establish capacity for these larger calls. The stricter new scheduler was followed, but the full-size repeat still failed its dispatch gate. All old results and the prior diagnostic package remain unchanged.\n\n"
            "Reproduce offline with `python scripts/audit_frontier_v6h_paced_canary.py`. For a relocated supplement use `--root`, the base manifest's inert-lock `--aliases` JSON, and `--base-zip` pointing to the original authenticated archive. Only that one hard-pinned archive may be read outside the relocated root; original relative input bindings are preserved.\n\n"
            'Limits:\n\n'+''.join('- '+x+'\n' for x in result['limits']))
        with (target/'runtime-audit.md').open('x',encoding='utf-8',newline='\n') as f:f.write(report)
    print(json.dumps({k:v for k,v in result.items() if k not in ('closed_ledger_bytes_base64','input_bindings','auditor_source','body_sha256_by_slot','observed_admission_order')},indent=2))

if __name__=='__main__':main()
