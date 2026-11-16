"""Authenticate final k composite; reuse the unchanged descriptive K10 analyzer."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from retrace.frontier_v6j_trajectory import analyze_trajectories
from scripts.score_frontier_v6k import compute,safe,strict,sha,binding,json_value,ALIASES,OUTPUT,INPUTS


def require(ok,why):
    if not ok:raise ValueError(why)


def verify_saved(root,result,views,*,aliases,ledger_snapshot):
    """Objects use the writer's JSON projection; JSONL views remain byte exact."""
    root=Path(root).resolve();path=safe(root,OUTPUT+'/composite-manifest.json');manifest=strict(path.read_bytes())
    require(manifest['schema']=='retrace.frontier-v6k-composite-artifacts.v1' and manifest['status']=='complete_amended_primary','final complete k composite required')
    require((manifest['planned_slots'],manifest['carried_final_slots'],manifest['carried_issued_slots'],manifest['continuation_slots'])==(1800,224,213,1576) and manifest['retained_by_segment']=={'i':6,'j':218},'three-segment cohort')
    names={OUTPUT+'/'+name for name in ('score.json','score-audits.json','requests.jsonl','responses.jsonl','slot-outcomes.jsonl','source-provenance.json','derived-closure.json')}
    require(set(manifest['files'])==names,'exact seven-file composite inventory')
    bindings={OUTPUT+'/composite-manifest.json':binding(path)}
    for name,expected in manifest['files'].items():require(binding(safe(root,name))==expected,'changed final artifact');bindings[name]=expected
    saved=strict(safe(root,OUTPUT+'/score.json').read_bytes());replay=json_value(result['summary'])
    evidence=saved.pop('file_evidence');replay_evidence=replay.pop('file_evidence')
    require(saved==replay and evidence==manifest['file_evidence'],'saved scientific score differs from replay')
    require(evidence['execution_freeze']==replay_evidence['execution_freeze'] and evidence['runtime_audits_replayed'] is True and evidence['runtime_input_bindings_rechecked_after_score'] is True,'final runtime evidence not replayed')
    require(evidence['frozen_aliases'] in ({},ALIASES),'unsupported saved aliases')
    require(evidence['ledger_snapshot']['sha256']==sha(safe(root,ledger_snapshot)),'immutable ledger differs')
    normalized={ledger_snapshot if name==evidence['ledger_snapshot']['path'] else name:value for name,value in evidence['source_files'].items()}
    require(normalized==replay_evidence['source_files'],'saved and replayed source inventories differ')
    for name,expected in normalized.items():require(binding(safe(root,aliases.get(name,name)))==expected,'saved source evidence changed')
    objects={'score-audits.json':result['audits'],'source-provenance.json':result['merged_evidence']['source_provenance'],'derived-closure.json':result['summary']['operational_summary']}
    for name,value in objects.items():require(strict(safe(root,OUTPUT+'/'+name).read_bytes())==json_value(value),'saved audit/provenance/closure differs from replay')
    for role,name in (('requests','requests.jsonl'),('responses','responses.jsonl'),('outcomes','slot-outcomes.jsonl')):
        require(safe(root,OUTPUT+'/'+name).read_bytes()==views[role],'saved raw-byte view changed')
    require(manifest['source_bindings']==json_value(result['merged_evidence']['source_bindings']) and manifest['source_rows_changed'] is False and manifest['selected_jsonl_source_bytes_preserved'] is True,'lossless source provenance required')
    return bindings


def authenticated_inputs(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    require(not (root/'results/frontier-v6k/budget/active.lock').exists(),'live continuation cannot be analyzed')
    require((root/OUTPUT/'composite-manifest.json').is_file(),'saved authenticated final k composite required')
    result,views=compute(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,frozen_aliases=aliases)
    bindings=verify_saved(root,result,views,aliases=aliases,ledger_snapshot=ledger_snapshot);sources=result['summary']['file_evidence']['source_files']
    for name in (INPUTS['corpus'],INPUTS['study']):require(name in sources and binding(safe(root,name))==sources[name],'frozen supplement input changed')
    corpus=strict(safe(root,INPUTS['corpus']).read_bytes());study=strict(safe(root,INPUTS['study']).read_bytes())
    return result,bindings,sources,corpus,study


def finish(root,value,bindings,sources,freeze_sha256,aliases,source_names,schema):
    for name,expected in bindings.items():require(binding(safe(root,name))==expected,'composite changed during supplement')
    for name,expected in sources.items():require(binding(safe(root,aliases.get(name,name)))==expected,'source evidence changed during supplement')
    value['pure_analysis_schema']=value['schema'];value['schema']=schema
    value['authenticated_input_bindings']=bindings;value['authenticated_source_bindings']=sources;value['execution_freeze_sha256']=freeze_sha256
    value['supplement_source_sha256']={name:sha(ROOT/name) for name in source_names}
    value['closure_scope']='Authenticated i+j+k composite only; both historical interruptions and all224 definitive old outcomes remain unchanged.'
    return value


def run(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    result,bindings,sources,corpus,study=authenticated_inputs(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,frozen_aliases=frozen_aliases)
    value=analyze_trajectories(corpus,study,result['audits'])
    return finish(root,value,bindings,sources,freeze_sha256,dict(frozen_aliases or {}),('retrace/frontier_v6j_trajectory.py','scripts/analyze_frontier_v6k_trajectory.py'),'retrace.frontier-v6k-k10-trajectory.v1')


def arguments(description):
    parser=argparse.ArgumentParser(description=description);parser.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','i-audit-sha256','j-audit-sha256','k-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--aliases',type=Path);parser.add_argument('--output',type=Path,required=True);return parser.parse_args()


def write_result(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')


def main():
    args=arguments(__doc__);require(not args.output.exists(),'exclusive new supplement output required');aliases=strict(args.aliases.read_bytes()) if args.aliases else {}
    value=run(args.root,args.freeze_sha256,args.i_audit_sha256,args.j_audit_sha256,args.k_audit_sha256,args.ledger_snapshot,args.ledger_snapshot_sha256,frozen_aliases=aliases)
    write_result(args.output,value);print(json.dumps({'schema':value['schema'],'planned_cases':value['planned_cases'],'views':value['views']}))

if __name__=='__main__':main()
