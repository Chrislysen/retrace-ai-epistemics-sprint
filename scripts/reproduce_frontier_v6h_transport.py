"""Offline additive transport supplement; requires the unchanged base artifact.

No provider calls, credential access, automatic retries, or original-file edits.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib
import json
from pathlib import Path, PureWindowsPath
import sys
from zipfile import ZipFile

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.reproduce_frontier_v6h_release import (canonical,load,rows,require,safe_path,sha,verify_inventory)
from scripts.audit_frontier_v6f_run import parse_sse,strict_json,output_text
from scripts.audit_frontier_v6h_runtime import PRICES,nano,credits,digest

SCHEMA='retrace.v6h-transport-supplement.v1'
BASE_ZIP_SHA='3353795e3b379202bb3bf073648882e00831c884c8116a7e27fcc91a70097cfb'
BASE_MANIFEST_SHA='1704937500b9cabd6555b87eadb07170a120adc8d50fdd5c020af7f4054783b3'
PACED_FREEZE='data/frontier-v6h-paced-canary-freeze.json'
PACED_FREEZE_SHA='7fafe5ed48ad64c415800cf2a4fb9530e251867936db8a70e61ba2875ec517f6'
QUOTA_FREEZE='data/frontier-v6h-quota-probe-freeze.json'
QUOTA_FREEZE_SHA='b069d0cd396be00f4bd8931a5f5c4b043be8c1c771b01caa9bd07e767612cadf'
QUOTA='results/frontier-v6h-quota-probe'
PACED='results/frontier-v6h-paced/canary'
SUPPLEMENT_MANIFEST='transport-supplement-manifest.json'
NEW_REQUIRED=(
    'scripts/assemble_frontier_v6h_transport.py','scripts/reproduce_frontier_v6h_transport.py',
    'scripts/audit_frontier_v6h_paced_canary.py','tests/test_frontier_v6h_transport_release.py',
    'README-V6-TRANSPORT.md','results/adaption-quota-capability-inspection.json',
    'data/frontier-v6h-ledger-after-paced-canary.jsonl',PACED_FREEZE,
    PACED+'/runtime-audit.json',PACED+'/runtime-audit.md',
)


def base_manifest_from_zip(path):
    require(sha(path)==BASE_ZIP_SHA,'Wrong base ZIP; do not substitute another release')
    with ZipFile(path) as archive:
        raw=archive.read('release-manifest-v6h.json')
        require(hashlib.sha256(raw).hexdigest()==BASE_MANIFEST_SHA,'Base manifest pin')
        return strict_json(raw.decode('utf-8'))


def verify_new_inventory(root,manifest,base_manifest):
    require(manifest.get('schema')==SCHEMA and manifest.get('status')=='closed_transport_diagnostics_primary_unissued','Supplement scope')
    require(manifest.get('base_zip_sha256')==BASE_ZIP_SHA and manifest.get('base_manifest_sha256')==BASE_MANIFEST_SHA,'Base pins changed')
    require(manifest.get('primary_calls')==0 and manifest.get('main_study_complete') is False,'No primary-study claim permitted')
    protected={r['path'].casefold() for r in base_manifest['files']}|{'release-manifest-v6h.json'}
    entries=manifest.get('files');require(isinstance(entries,list) and entries,'Empty supplement')
    seen=set();indexed={}
    for entry in entries:
        require(set(entry)=={'path','sha256','bytes'},'Supplement entry schema')
        name=entry['path'];require(name.casefold() not in protected,'Supplement overwrites a base artifact')
        require(name.casefold() not in seen and name!=SUPPLEMENT_MANIFEST,'Duplicate/reserved supplement path')
        path=safe_path(root,name)
        require(type(entry['bytes']) is int and entry['bytes']>=0 and path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256'],'Supplement file changed: '+name)
        seen.add(name.casefold());indexed[name]=entry['sha256']
    require(hashlib.sha256(canonical(entries).encode()).hexdigest()==manifest.get('file_set_sha256'),'Supplement inventory digest')
    require(set(NEW_REQUIRED)<=set(indexed),'Required supplement evidence absent')
    require(indexed.get(PACED_FREEZE)==PACED_FREEZE_SHA,'Paced freeze missing or changed')
    require(manifest.get('base_files_changed')==0,'Base-change count must remain zero')
    base_index={r['path']:r['sha256'] for r in base_manifest['files']};aliases=base_manifest['frozen_aliases']
    frozen=load(safe_path(root,PACED_FREEZE));covered={**base_index,**indexed}
    for entry in frozen['files']:
        name=entry['path']
        if name=='deliverables/retrace-v6-sprint-artifact.zip':
            require(entry['sha256']==BASE_ZIP_SHA,'Frozen base ZIP reference');continue
        require(covered.get(aliases.get(name,name))==entry['sha256'],'Paced freeze dependency absent or changed: '+name)
    require(sha(safe_path(root,QUOTA_FREEZE))==QUOTA_FREEZE_SHA,'Quota freeze changed')
    for name,expected in load(safe_path(root,QUOTA_FREEZE))['files'].items():
        require(covered.get(name)==expected,'Quota freeze dependency absent')
    return {'supplement_files':len(entries),'base_files':len(base_manifest['files']),'base_files_overwritten':0,'paced_frozen_inputs':len(frozen['files'])}


def quota_replay(root):
    """Reconstruct all fifteen raw-terminal outcomes and exact provider bodies."""
    root=Path(root);frozen=load(root/QUOTA_FREEZE);summary=load(root/QUOTA/'summary.json')
    before=(root/'data/frontier-v6h-ledger-after-canary.jsonl').read_bytes()
    after=(root/'data/frontier-v6h-ledger-after-quota-probe.jsonl').read_bytes()
    closed=(root/'data/frontier-v6h-ledger-after-paced-canary.jsonl').read_bytes()
    require(after.startswith(before) and closed.startswith(after),'Immutable ledger snapshots must be exact byte prefixes')
    require([len(x.splitlines()) for x in (before,after,closed)]==[33,69,95],'Expected immutable ledger boundaries')
    require(summary['freeze_sha256']==QUOTA_FREEZE_SHA and summary['numeric_quota_verified'] is False,'Quota summary scope')
    require(frozen['global_intervals_seconds']==[21.,10.,5.] and len(frozen['round_slots'])==3,'Quota design')
    require(len(summary['rounds'])==3,'Three completed diagnostic rounds required')
    admissions=rows(root/QUOTA/'http-admissions.jsonl')
    require(len(admissions)==30 and [x['kind'] for x in admissions]==['http_admission','http_headers']*15,'One admission/header pair per request')
    total_cost=0;results=[];cursor=0;last_round_end=None
    for number,slots in enumerate(frozen['round_slots'],1):
        folder=root/QUOTA/f'round-{number}';run=load(folder/'run.json');round_summary=load(folder/'summary.json')
        require(run['slots']==slots and run['sessions_sha256']==digest(slots),'Frozen quota projection')
        require(round_summary==summary['rounds'][number-1],'Round summary binding')
        requests=rows(folder/'requests.jsonl');responses=rows(folder/'responses.jsonl');finals=rows(folder/'slot-outcomes.jsonl')
        require(len(requests)==len(responses)==len(finals)==len(slots)==5,'Quota five-slot denominator')
        require(len({r['attempt_id'] for r in responses})==5 and len({r['slot_id'] for r in finals})==5,'Quota unique attempts/finals')
        by_response={r['attempt_id']:r for r in responses};by_final={r['slot_id']:r for r in finals};gaps=[];starts=[];cost=0
        for q,s in zip(requests,slots):
            require(q['slot_id']==s['slot_id'] and q['attempt_number']==1 and q['first_attempt'] is True,'Quota first attempt/order')
            require(q['attempt_id']==run['run_id']+':'+s['slot_id']+':attempt-1','Quota attempt naming')
            body={'model':s['model'],'instructions':s['instructions'],'input':[{'role':'user','content':s['input']}],
                'max_output_tokens':s['max_output_tokens'],'temperature':s['temperature'],'store':False,'previous_response_id':None,
                'agentic_memory':False,'tools':[],'tool_choice':'none','stream':True}
            require(q['request']==body and q['request_sha256']==digest(body) and q['dependency_bindings']==[],'Exact quota request body')
            r=by_response[q['attempt_id']];require(r['slot_id']==s['slot_id'] and r['model']==s['model'] and r['run_id']==run['run_id'],'Quota response identity')
            require(r['attempt_number']==1 and r['first_attempt'] is True and r['issued'] is True,'Quota no retry')
            require(r['model_outcome']=='completed' and r['http_status']==200 and r['terminal_valid'] is True and r['error'] is None,'Quota successful terminal')
            meta=r['stream_evidence'];name=hashlib.sha256(r['attempt_id'].encode()).hexdigest()+'.sse';raw=(folder/'streams'/name).read_bytes()
            require(PureWindowsPath(meta['raw_stream_path']).name==name and meta['closed'] is True and meta['credential_redacted'] is False,'Quota stream identity')
            require(meta['received_bytes']==len(raw) and meta['received_sha256']==meta['saved_sha256']==hashlib.sha256(raw).hexdigest(),'Quota raw hash')
            parsed=parse_sse(raw);terminal=parsed['response']
            require(terminal==strict_json(r['raw_response']) and terminal['status']=='completed' and terminal['model']==s['model'],'Quota raw terminal replay')
            require(parsed['terminal']==r['stream_terminal_event'] and parsed['event_count']==r['stream_event_count'],'Quota event metadata')
            require(terminal['usage']==r['usage'] and output_text(terminal)==r['output_text'],'Quota usage/text binding')
            usage=r['usage'];ip,op,ctx=PRICES[s['model']]
            require(type(usage['input_tokens']) is int and type(usage['output_tokens']) is int and 0<=usage['input_tokens']<=ctx and 0<=usage['output_tokens']<=s['max_output_tokens'],'Quota usage bounds')
            if 'total_tokens' in usage:require(usage['total_tokens']==usage['input_tokens']+usage['output_tokens'],'Quota total usage')
            calculated=nano((Decimal(ip)*usage['input_tokens']+Decimal(op)*usage['output_tokens'])/1_000_000)
            require(calculated==nano(r['settled_credits']),'Quota exact uncached settlement');cost+=calculated
            final=by_final[s['slot_id']]
            require(all(final.get(k)==v for k,v in r.items()) and final['attempts_issued']==1 and final['first_attempt_id']==r['attempt_id'],'Quota final equals only attempt')
            admission,headers=admissions[cursor:cursor+2];cursor+=2
            require(admission['model']==headers['model']==s['model'] and admission['request_sha256']==headers['request_sha256']==digest(body),'Quota HTTP evidence identity')
            require(headers['status']==200 and admission['interval_seconds']==frozen['global_intervals_seconds'][number-1],'Quota status/interval')
            require(not any('ratelimit' in k.lower() or k.lower()=='retry-after' for k in headers['headers']),'Unexpected numeric quota header; revise claims')
            starts.append(datetime.fromisoformat(admission['at']).timestamp())
            if admission['gap_seconds'] is not None:gaps.append(admission['gap_seconds'])
        require(round_summary['status']=='completed' and round_summary['issued_attempts']==round_summary['first_attempt_completed']==5
            and round_summary['http_429_attempts']==round_summary['retries']==round_summary['issued_operational_failures']==round_summary['truncated']==0,'Quota round gate')
        if last_round_end is not None:require(starts[0]-last_round_end>=64.965,'Quota minimum round separation')
        last_round_end=max(datetime.fromisoformat(r['at']).timestamp() for r in responses)
        require(len(gaps)==4 and min(gaps)>=frozen['global_intervals_seconds'][number-1]-.035,'Quota observed cadence tolerance')
        total_cost+=cost;results.append({'round':number,'planned':5,'first_completed':5,'retries':0,'nominal_interval_seconds':frozen['global_intervals_seconds'][number-1],
            'minimum_logged_gap_seconds':min(gaps),'known_usage_credits':credits(cost)})
    return {'planned':15,'first_completed':15,'retries':0,'http_429':0,'rounds':results,'known_usage_credits':credits(total_cost),
        'numeric_quota_verified':False,'scope':'Tiny serial transport requests only. Observed timing is not a numeric provider quota or heavy-IR capacity guarantee.'}


def paced_semantic_replay(root):
    folder=Path(root)/PACED;slots=load(Path(root)/'data/frontier-v6h-canary-sessions.json')
    evaluate=importlib.import_module('scripts.score_frontier_v6h_canary').evaluate
    result=evaluate(slots,rows(folder/'slot-outcomes.jsonl'),rows(folder/'responses.jsonl'))
    saved=load(folder/'semantic-score.json')
    require(all(saved.get(k)==v for k,v in result.items()),'Paced semantic score replay')
    expected={'sessions':sha(Path(root)/'data/frontier-v6h-canary-sessions.json'),'outcomes':sha(folder/'slot-outcomes.jsonl'),'attempts':sha(folder/'responses.jsonl')}
    require(saved['input_sha256']==expected,'Paced semantic input binding')
    return {k:result[k] for k in ('planned','observed_attempts','final_operational_completed','final_schema_accepted','final_exact_family','first_attempt_exact_family')}


def verify(root,manifest,base_zip):
    root=Path(root).resolve();require(root==ROOT,'Execute the copy inside the extracted combined artifact')
    base=base_manifest_from_zip(base_zip)
    require(sha(root/'release-manifest-v6h.json')==BASE_MANIFEST_SHA,'Extracted base manifest changed')
    base_result=verify_inventory(root,base)
    result=verify_new_inventory(root,manifest,base)
    auditor=importlib.import_module('scripts.audit_frontier_v6h_paced_canary')
    audit=auditor.audit(root,frozen_aliases=base['frozen_aliases'],base_archive=Path(base_zip))
    require(audit['passed'] is True and audit['final_closed'] is True and audit['primary_requests']==0 and audit['canary_dispatch_gate_passed'] is False,'Paced gate/finality scope')
    saved=load(root/PACED/'runtime-audit.json')
    require(all(saved.get(k)==v for k,v in audit.items()),'Saved independent audit replay mismatch')
    require(saved['auditor_source']['sha256']==sha(root/'scripts/audit_frontier_v6h_paced_canary.py'),'Auditor source binding')
    quota=quota_replay(root);semantic=paced_semantic_replay(root)
    require(manifest['quota_replay']==quota and manifest['paced_semantic_replay']==semantic,'Supplement result binding')
    require(manifest['paced_runtime_checks']==audit['checks'] and manifest['cumulative_accounted_credits']==audit['cumulative_accounted_credits'],'Supplement audit/account binding')
    verify_inventory(root,base);verify_new_inventory(root,manifest,base)
    return {'schema':'retrace.v6h-transport-supplement-reproduction.v1','status':'verified_closed_transport_failures_primary_unissued',**result,
        'base_freeze_files':base_result['frozen_files_verified'],'quota':quota,'paced_canary':semantic,
        'paced_runtime_checks':audit['checks'],'canary_gate_passed':False,'primary_calls':0,'model_calls_made':0,
        'ledger_entries':audit['ledger_entries'],'cumulative_accounted_credits':audit['cumulative_accounted_credits'],'actual_billing_verified':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-zip',type=Path,required=True)
    p.add_argument('--manifest',type=Path,default=ROOT/SUPPLEMENT_MANIFEST);a=p.parse_args()
    print(json.dumps(verify(ROOT,load(a.manifest),a.base_zip),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
