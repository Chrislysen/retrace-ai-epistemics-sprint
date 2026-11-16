"""Authenticate three closed segments and write exclusive lossless composite views."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from retrace.frontier_v6k_eval import evaluate_composite,json_value,SEGMENTS,role_paths
from scripts.score_frontier_v6j import safe,strict,sha,binding,import_closure,selected_source_lines,ALIASES

FREEZE='data/frontier-v6k-freeze.json'
OUTPUT='results/frontier-v6k/composite'
INPUTS={'corpus':'data/frontier-v6h-corpus.json','dossiers':'data/frontier-v6h-dossiers.json','study':'data/frontier-v6i-design.json',
        'sessions':'data/frontier-v6i-sessions.json','receipt':'data/frontier-v6k-continuation.json'}
AUDITS={name:role_paths(name)['summary'].removesuffix('summary.json')+'runtime-audit.json' for name in SEGMENTS}
LEDGER='results/frontier-v6k/budget/ledger.jsonl'


def require(ok,why):
    if not ok:raise ValueError(why)


def audit_runtime(*args,**kwargs):
    # The independent auditor is owned separately; import only on offline replay.
    from scripts.audit_frontier_v6k_runtime import audit
    return audit(*args,**kwargs)


def verify_inventory(root,expected_sha,aliases):
    require(aliases in ({},ALIASES),'unsupported_frozen_alias')
    path=safe(root,FREEZE);require(sha(path)==expected_sha,'execution_freeze_hash');freeze=strict(path.read_bytes())
    require(freeze.get('schema')=='retrace.frontier-v6k-freeze.v1','execution_freeze_schema')
    require((freeze.get('scheduled_slots'),freeze.get('continuation_slots'),freeze.get('carried_final_slots'),freeze.get('carried_issued_slots'))==(1800,1576,224,213),'amended_schedule_counts')
    inventory={}
    for row in freeze['files']:
        name=row['path'];require(name not in inventory,'duplicate_frozen_path')
        value={'sha256':row['sha256'],'bytes':row['bytes']};require(binding(safe(root,aliases.get(name,name)))==value,'frozen_dependency_changed: '+name);inventory[name]=value
    required=set(INPUTS.values())|import_closure(root,['scripts/score_frontier_v6k.py','retrace/frontier_v6k_eval.py','scripts/audit_frontier_v6k_runtime.py'])
    require(required<=set(inventory),'missing_scientific_dependency');require(set(aliases)<=set(inventory),'alias_not_in_freeze')
    return freeze,inventory


def segment(root,name):
    paths=role_paths(name);raw={role:safe(root,path).read_bytes() for role,path in paths.items()}
    return {'paths':paths,**{role:raw[role] for role in ('requests','responses','outcomes')},'summary_bytes':raw['summary'],
            'manifest_bytes':raw['run_manifest'],'summary':strict(raw['summary']),'manifest':strict(raw['run_manifest'])}


def compute(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    """Pure authenticated replay; all three historical/runtime proofs are required."""
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    require(not safe(root,'results/frontier-v6k/budget/active.lock').exists(),'continuation_still_active')
    freeze,inventory=verify_inventory(root,freeze_sha256,aliases)
    require(ledger_snapshot!=LEDGER,'immutable_ledger_snapshot_required');snapshot=safe(root,ledger_snapshot)
    require(sha(snapshot)==ledger_snapshot_sha256,'ledger_snapshot_hash')
    before={name:binding(safe(root,name)) for name in set(INPUTS.values())|set(AUDITS.values())|{ledger_snapshot,FREEZE}}
    expected=dict(zip(SEGMENTS,(i_audit_sha256,j_audit_sha256,k_audit_sha256)));saved={}
    for name,path in AUDITS.items():
        require(before[path]['sha256']==expected[name],'saved_runtime_audit_hash');saved[name]=strict(safe(root,path).read_bytes())
    actual=json_value(audit_runtime(root,freeze_sha256,frozen_aliases=aliases,ledger_snapshot=ledger_snapshot))
    require(actual==saved['k'] and actual['prior_segment_audits']=={'i':saved['i'],'j':saved['j']},'all_runtime_audits_do_not_reproduce')
    require(actual.get('passed') is True and actual.get('final_closed') is True and actual.get('all_scheduled_outcomes_accounted') is True and actual.get('schedule_status')=='completed','continuation_not_complete')
    segments={name:segment(root,name) for name in SEGMENTS}
    for name,value in segments.items():
        for role,path in value['paths'].items():
            raw=value[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)]
            found={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
            require(actual['input_bindings'].get(path)==found,'runtime_bindings_differ_from_composite_source');before[path]=found
    require(actual['input_bindings'].get(LEDGER)==binding(snapshot),'runtime_ledger_binding')
    data={name:strict(safe(root,path).read_bytes()) for name,path in INPUTS.items()}
    for path,expected_sha in data['receipt']['prior_journal_files'].items():
        target=aliases.get(path,path);found=binding(safe(root,target));require(found['sha256']==expected_sha,'historical receipt source changed');before[path]=found
    result=json_value(evaluate_composite(data['corpus'],data['dossiers'],data['study'],data['sessions'],data['receipt'],segments,saved))
    require(result['summary']['status']=='complete_amended_primary' and result['summary']['primary_holm_family_size']==21,'incomplete_amended_scientific_result')
    views={role:selected_source_lines(result['merged_evidence'],segments,role) for role in ('requests','responses','outcomes')}
    for path,value in before.items():require(binding(safe(root,aliases.get(path,path)))==value,'source_changed_during_scoring')
    for path,value in actual['input_bindings'].items():
        target=ledger_snapshot if path==LEDGER else aliases.get(path,path)
        require(binding(safe(root,target))==value,'runtime_evidence_changed_during_scoring')
    verify_inventory(root,freeze_sha256,aliases)
    result['summary']['file_evidence']={'execution_freeze':{'path':FREEZE,'sha256':freeze_sha256},'source_files':before,
        'runtime_audits_replayed':True,'runtime_input_bindings_rechecked_after_score':True,'frozen_aliases':aliases,
        'ledger_snapshot':{'path':ledger_snapshot,'sha256':ledger_snapshot_sha256},
        'scope':'Three-segment amended composite. Both old interrupted segments and every definitive old outcome are preserved unchanged.'}
    return result,views


def write_outputs(root,result,views):
    directory=safe(root,OUTPUT);require(not directory.exists(),'composite_output_already_exists')
    encode=lambda value:(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    payloads={'score.json':encode(result['summary']),'score-audits.json':encode(result['audits']),
        'requests.jsonl':views['requests'],'responses.jsonl':views['responses'],'slot-outcomes.jsonl':views['outcomes'],
        'source-provenance.json':encode(result['merged_evidence']['source_provenance']),'derived-closure.json':encode(result['summary']['operational_summary'])}
    directory.mkdir(parents=True,exist_ok=False)
    for name,raw in payloads.items():
        with (directory/name).open('xb') as stream:stream.write(raw)
    manifest={'schema':'retrace.frontier-v6k-composite-artifacts.v1','status':'complete_amended_primary',
        'planned_slots':1800,'carried_final_slots':224,'carried_issued_slots':213,'carried_dependency_failed_slots':11,
        'retained_by_segment':{'i':6,'j':218},'continuation_slots':1576,'source_rows_changed':False,'selected_jsonl_source_bytes_preserved':True,
        'files':{OUTPUT+'/'+name:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in payloads.items()},
        'source_bindings':result['merged_evidence']['source_bindings'],'file_evidence':result['summary']['file_evidence'],
        'writer_sha256':sha(Path(__file__)),'scope':'Derived three-segment views. No old journal, summary, failure or definitive skip is rewritten.'}
    with (directory/'composite-manifest.json').open('xb') as stream:stream.write(encode(manifest))
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','i-audit-sha256','j-audit-sha256','k-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--aliases',type=Path);args=parser.parse_args();require(not safe(args.root,OUTPUT).exists(),'composite_output_already_exists')
    aliases=strict(args.aliases.read_bytes()) if args.aliases else {}
    result,views=compute(args.root,args.freeze_sha256,args.i_audit_sha256,args.j_audit_sha256,args.k_audit_sha256,args.ledger_snapshot,args.ledger_snapshot_sha256,frozen_aliases=aliases)
    manifest=write_outputs(args.root,result,views)
    print(json.dumps({'status':manifest['status'],'planned_slots':1800,'retained_prior_final_slots':224,'continuation_slots':1576,'output':OUTPUT,'holm_family':21,'source_rows_changed':False}))

if __name__=='__main__':main()
