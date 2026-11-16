"""Offline plan by default. Paid execution requires exact frozen dependencies.

The credential comes only from hidden prompt or transient stdin, never argv.
"""
import argparse
import asyncio
import getpass
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.adaption_v6h import (AiohttpTransport,BASELINE,BASELINE_LEDGER,BASELINE_SHA256,
    V6C_LEDGER,V6C_LEDGER_SHA256,V6D_LEDGER,V6D_LEDGER_SHA256,V6E_LEDGER,V6E_LEDGER_SHA256,
    MANUAL_CLOSURE,MANUAL_CLOSURE_SHA256,MODEL_PRICING,PRIMARY_MODELS,RollingLedger,plan,require,run_slots)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integrity(auth,models):
    require(auth['cumulative_cap_credits']=='250','authorization_cap_mismatch')
    require(auth['historical_conservative_carry_credits']==BASELINE,'authorization_carry_mismatch')
    require(auth['prior_ledger_path']==BASELINE_LEDGER and auth['prior_ledger_sha256']==BASELINE_SHA256,'authorization_prior_ledger_mismatch')
    require(auth['manual_closure_path']==MANUAL_CLOSURE and auth['manual_closure_sha256']==MANUAL_CLOSURE_SHA256,'authorization_closure_mismatch')
    require(auth['earlier_ledgers']==[{'path':V6C_LEDGER,'sha256':V6C_LEDGER_SHA256},
        {'path':V6D_LEDGER,'sha256':V6D_LEDGER_SHA256},{'path':V6E_LEDGER,'sha256':V6E_LEDGER_SHA256}],'authorization_earlier_ledger_mismatch')
    for relative,expected in auth['protected'].items():
        p=(ROOT/relative).resolve();require(p.is_relative_to(ROOT),'invalid_protected_path');require(sha(p)==expected,'protected_artifact_changed')
    require(models['http_status']==200,'model_availability_unverified')
    records={r['id']:r for r in models['models']}
    for model,p in MODEL_PRICING.items():
        require(model in records,'model_not_available')
        require(records[model]['max_input_tokens']<=p['context'],'model_input_bound_changed')
        require(records[model]['max_output_tokens']>=65536,'model_output_bound_too_small')
    return len(auth['protected'])


def verify_freeze(path,expected,sessions_path,corpus_path):
    require(sha(path)==expected,'freeze_hash_mismatch')
    freeze=json.loads(Path(path).read_text(encoding='utf-8'));entries=freeze.get('files')
    require(isinstance(entries,list) and entries,'invalid_freeze_entries');seen=set()
    for row in entries:
        require(isinstance(row,dict) and {'path','sha256'}<=set(row),'invalid_freeze_entry')
        target=(ROOT/row['path']).resolve()
        require(target.is_relative_to(ROOT) and target not in seen,'invalid_freeze_path')
        require(sha(target)==row['sha256'],'frozen_dependency_changed');seen.add(target)
    required={Path(sessions_path).resolve(),Path(corpus_path).resolve(),Path(__file__).resolve(),ROOT/'retrace/adaption_v6h.py',
        ROOT/'data/frontier-v6h-authorization.json',ROOT/'data/frontier-v6c-model-availability.json',ROOT/BASELINE_LEDGER,
        ROOT/V6C_LEDGER,ROOT/V6D_LEDGER,ROOT/V6E_LEDGER,ROOT/MANUAL_CLOSURE,
        ROOT/'retrace/adaption_v6c.py',ROOT/'retrace/adaption_v6d.py',ROOT/'retrace/adaption_v6e.py',ROOT/'retrace/adaption_v6f.py',
        ROOT/'retrace/pacing_v6f.py',ROOT/'requirements-v6h.txt'}
    require(required<=seen,'required_runtime_file_not_frozen')
    return len(seen)


def verify_corpus(path,expected):
    require(sha(path)==expected,'corpus_hash_mismatch')
    corpus=json.loads(Path(path).read_text(encoding='utf-8'))
    require(isinstance(corpus,dict) and corpus.get('schema')=='retrace.frontier-v6h-corpus.v1','invalid_corpus_schema')
    cases=corpus.get('cases')
    require(isinstance(cases,list) and len(cases)==60,'corpus_requires_sixty_cases')
    ids=[c.get('case_id',c.get('id')) for c in cases]
    require(all(isinstance(x,str) and x for x in ids) and len(set(ids))==60,'corpus_ids_invalid')
    synthetic=[c for c in cases if c.get('partition')=='synthetic']
    ecological=[c for c in cases if c.get('partition')=='ecological']
    require(len(synthetic)==48 and len(ecological)==12,'corpus_partition_invalid')
    require(Counter(c.get('family_id') for c in synthetic)==Counter({f'F{i}':8 for i in range(1,7)}),'corpus_family_counts_invalid')
    require(all(c.get('family_id')=='ECO' for c in ecological) and
            {c.get('case_id',c.get('id')) for c in ecological}=={f'ECO-{i:02}' for i in range(1,13)},'corpus_ecological_ids_invalid')
    long_ids=corpus.get('long_context_subset_ids')
    require(isinstance(long_ids,list) and len(long_ids)==len(set(long_ids))==24 and
            set(long_ids)<={c.get('case_id',c.get('id')) for c in synthetic},'corpus_long_subset_invalid')
    return set(ids)


def verify_canary(value):
    require(value.get('schema')=='retrace.adaption-v6h-summary.v1' and value.get('canary') is True
        and value.get('status')=='completed' and value.get('stream') is True and value.get('planned')==10
        and value.get('issued_slots')==10 and value.get('slot_outcomes')==10
        and value.get('valid_terminal_records')==10 and value.get('issued_operational_failures')==0
        and value.get('dependency_skips')==0 and value.get('unissued_slot_ids')==[]
        and value.get('issued_without_outcome_attempt_ids')==[]
        and value.get('models')=={m:2 for m in PRIMARY_MODELS},'canary_not_terminal_complete')


def verify_runtime_config(freeze,args):
    expected={'model_interval_seconds':args.model_interval,'per_model_concurrency':args.per_model_concurrency,
        'global_concurrency':args.concurrency,'timeout_seconds':args.timeout,'max_retries':2}
    require(freeze.get('runtime_config')==expected,'runtime_config_not_exactly_frozen')
    if args.canary:
        require(expected=={'model_interval_seconds':2.0,'per_model_concurrency':8,
            'global_concurrency':40,'timeout_seconds':180.0,'max_retries':2},'canary_runtime_config_mismatch')


async def execute(args,slots):
    auth_path=ROOT/'data/frontier-v6h-authorization.json';models_path=ROOT/'data/frontier-v6c-model-availability.json'
    verify_freeze(Path(args.freeze).resolve(),args.freeze_sha256,args.sessions,args.corpus_manifest)
    freeze=json.loads(Path(args.freeze).read_text(encoding='utf-8'))
    verify_runtime_config(freeze,args)
    verify_corpus(args.corpus_manifest,args.corpus_manifest_sha256)
    require(2.0<=args.model_interval<=2.5,'live_pacing_outside_frozen_range')
    require(args.timeout==180.0,'live_timeout_not_180')
    require(args.authorization_sha256==sha(auth_path) and args.models_sha256==sha(models_path),'execution_metadata_hash_mismatch')
    integrity(json.loads(auth_path.read_text(encoding='utf-8')),json.loads(models_path.read_text(encoding='utf-8')))
    if not args.canary:
        require(args.canary_summary and args.canary_summary_sha256,'missing_smoke_gate')
        canary_path=Path(args.canary_summary).resolve()
        require(sha(canary_path)==args.canary_summary_sha256,'canary_summary_hash_mismatch')
        require(any((ROOT/e['path']).resolve()==canary_path and e['sha256']==args.canary_summary_sha256
                    for e in freeze['files']),'canary_summary_not_in_primary_freeze')
        verify_canary(json.loads(canary_path.read_text(encoding='utf-8')))
    output=Path(args.output).resolve();ledger_path=Path(args.ledger).resolve()
    require(output.is_relative_to(ROOT/'results/frontier-v6h'),'output_outside_v6h')
    require(ledger_path==(ROOT/'results/frontier-v6h/budget').resolve(),'noncanonical_phase_ledger')
    stop_file=Path(args.stop_file).resolve()
    require(stop_file.is_relative_to(ROOT/'results/frontier-v6h'),'stop_file_outside_v6h')
    api_key=sys.stdin.readline().strip() if args.key_stdin else getpass.getpass('Adaption key (hidden): ')
    ledger=RollingLedger(ledger_path,baseline_path=ROOT/BASELINE_LEDGER)
    try:
        async with AiohttpTransport(api_key,args.timeout,args.concurrency) as transport:
            return await run_slots(slots,api_key=api_key,output_dir=output,ledger=ledger,transport=transport,
                canary=args.canary,model_interval=args.model_interval,per_model_concurrency=args.per_model_concurrency,
                concurrency=args.concurrency,timeout_seconds=args.timeout,stop_file=stop_file)
    finally:
        ledger.close();api_key=None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('sessions','sessions-sha256','authorization-sha256','models-sha256','freeze','freeze-sha256',
                 'corpus-manifest','corpus-manifest-sha256','canary-summary','canary-summary-sha256','output','ledger','stop-file'):
        p.add_argument('--'+name,required=name=='sessions')
    p.add_argument('--canary',action='store_true');p.add_argument('--execute',action='store_true');p.add_argument('--key-stdin',action='store_true')
    p.add_argument('--concurrency',type=int,default=40);p.add_argument('--per-model-concurrency',type=int,default=8)
    p.add_argument('--model-interval',type=float,default=2.0);p.add_argument('--timeout',type=float,default=180.0)
    args=p.parse_args();path=Path(args.sessions).resolve();slots=json.loads(path.read_text(encoding='utf-8'))
    prepared=plan(slots,canary=args.canary)
    if not args.execute:print(json.dumps(prepared,indent=2));return
    require(args.sessions_sha256==sha(path),'sessions_hash_mismatch')
    require(all((args.authorization_sha256,args.models_sha256,args.freeze,args.freeze_sha256,args.corpus_manifest,
        args.corpus_manifest_sha256,args.output,args.ledger,args.stop_file)),'missing_execution_parameters')
    print(json.dumps(asyncio.run(execute(args,slots)),indent=2))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'aborted','error_type':type(exc).__name__,'details':'See durable journals; only explicitly recorded HTTP429 attempts may be retried.'}));sys.exit(1)
