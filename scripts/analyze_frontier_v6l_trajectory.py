"""Authenticate the four-segment result; reuse the unchanged descriptive analyzer."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from retrace.frontier_v6j_trajectory import analyze_trajectories
from scripts.score_frontier_v6l import compute,safe,strict,sha,binding,json_value,ALIASES,OUTPUT,PARTIAL_OUTPUT,INPUTS


def require(ok,why):
    if not ok:raise ValueError(why)


def verify_saved(root,result,views,*,aliases,ledger_snapshot,diagnostic=False):
    """Reproduce every saved object and exact JSONL bytes; explicit closure branch."""
    require(type(diagnostic) is bool,'explicit diagnostic selector')
    root=Path(root).resolve();output=PARTIAL_OUTPUT if diagnostic else OUTPUT
    filename='partial-manifest.json' if diagnostic else 'composite-manifest.json'
    closure='interrupted-closure.json' if diagnostic else 'derived-closure.json'
    path=safe(root,output+'/'+filename);manifest=strict(path.read_bytes())
    status='interrupted_amended_diagnostic' if diagnostic else 'complete_amended_primary'
    schema='retrace.frontier-v6l-'+('partial' if diagnostic else 'composite')+'-artifacts.v1'
    require(manifest['schema']==schema and manifest['status']==status
        and result['summary']['status']==status,'explicit final l branch required')
    a=result['summary']['amendment']
    require(manifest['planned_slots']==1800 and all(manifest[k]==a[k] for k in
        ('carried_final_slots','carried_issued_slots','carried_dependency_failed_slots','retained_by_segment'))
        and manifest['continuation_slots']==a['continuation_planned_slots']
        and manifest['schedule_complete'] is (not diagnostic) and manifest['inference_available'] is (not diagnostic),'four-segment cohort')
    names={output+'/'+name for name in ('score.json','score-audits.json','requests.jsonl','responses.jsonl',
        'slot-outcomes.jsonl','source-provenance.json',closure)}
    require(set(manifest['files'])==names,'exact seven-file composite inventory')
    bindings={output+'/'+filename:binding(path)}
    for name,expected in manifest['files'].items():
        require(binding(safe(root,name))==expected,'changed final artifact');bindings[name]=expected
    saved=strict(safe(root,output+'/score.json').read_bytes());replay=json_value(result['summary'])
    evidence=saved.pop('file_evidence');replay_evidence=replay.pop('file_evidence')
    require(saved==replay and evidence==manifest['file_evidence'],'saved scientific score differs from replay')
    writer='scripts/score_frontier_v6l.py'
    require(writer in replay_evidence['runtime_input_bindings'] and manifest['writer_sha256']==
        replay_evidence['runtime_input_bindings'][writer]['sha256'],'saved writer differs from authenticated execution source')
    require(evidence['frozen_aliases'] in ({},ALIASES) and aliases in ({},ALIASES),'unsupported saved aliases')
    require(evidence['ledger_snapshot']['sha256']==sha(safe(root,ledger_snapshot)),'immutable ledger differs')
    normalized=deepcopy(evidence)
    normalized['source_files']={ledger_snapshot if name==evidence['ledger_snapshot']['path'] else name:value
        for name,value in evidence['source_files'].items()}
    require(len(normalized['source_files'])==len(evidence['source_files']),'snapshot normalization collision')
    normalized['ledger_snapshot']['path']=ledger_snapshot;normalized['frozen_aliases']=aliases
    require(normalized==replay_evidence,'saved and replayed full evidence differ')
    require(evidence['runtime_audits_replayed'] is True and evidence['runtime_input_bindings_rechecked_after_score'] is True,'final runtime evidence not replayed')
    for name,expected in normalized['source_files'].items():
        require(binding(safe(root,aliases.get(name,name)))==expected,'saved source evidence changed')
    for name,expected in evidence['runtime_input_bindings'].items():
        target=ledger_snapshot if name=='results/frontier-v6l/budget/ledger.jsonl' else aliases.get(name,name)
        require(binding(safe(root,target))==expected,'saved runtime evidence changed')
    objects={'score-audits.json':result['audits'],'source-provenance.json':result['merged_evidence']['source_provenance'],closure:result['summary']['operational_summary']}
    for name,value in objects.items():
        require(strict(safe(root,output+'/'+name).read_bytes())==json_value(value),'saved audit/provenance/closure differs from replay')
    for role,name in (('requests','requests.jsonl'),('responses','responses.jsonl'),('outcomes','slot-outcomes.jsonl')):
        require(safe(root,output+'/'+name).read_bytes()==views[role],'saved raw-byte view changed')
    require(manifest['source_bindings']==json_value(result['merged_evidence']['source_bindings']) and
        manifest['source_rows_changed'] is False and manifest['selected_jsonl_source_bytes_preserved'] is True,'lossless source provenance required')
    return bindings


def authenticated_inputs(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,l_audit_sha256,
        ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    require(not (root/'results/frontier-v6l/budget/active.lock').exists(),'live continuation cannot be analyzed')
    require((root/OUTPUT/'composite-manifest.json').is_file(),'saved authenticated final l composite required')
    result,views=compute(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,l_audit_sha256,
        ledger_snapshot,ledger_snapshot_sha256,frozen_aliases=aliases)
    bindings=verify_saved(root,result,views,aliases=aliases,ledger_snapshot=ledger_snapshot)
    evidence=result['summary']['file_evidence'];sources=dict(evidence['source_files'])
    for name,value in evidence['runtime_input_bindings'].items():
        name=ledger_snapshot if name=='results/frontier-v6l/budget/ledger.jsonl' else name
        require(name not in sources or sources[name]==value,'contradictory source binding');sources[name]=value
    for name in (INPUTS['corpus'],INPUTS['study']):
        require(name in sources and binding(safe(root,name))==sources[name],'frozen supplement input changed')
    corpus=strict(safe(root,INPUTS['corpus']).read_bytes());study=strict(safe(root,INPUTS['study']).read_bytes())
    return result,bindings,sources,corpus,study


def finish(root,value,bindings,sources,freeze_sha256,aliases,source_names,schema):
    for name,expected in bindings.items():require(binding(safe(root,name))==expected,'composite changed during supplement')
    for name,expected in sources.items():require(binding(safe(root,aliases.get(name,name)))==expected,'source evidence changed during supplement')
    value['pure_analysis_schema']=value['schema'];value['schema']=schema
    value['authenticated_input_bindings']=bindings;value['authenticated_source_bindings']=sources;value['execution_freeze_sha256']=freeze_sha256
    value['supplement_source_sha256']={name:sha(ROOT/name) for name in source_names}
    value['closure_scope']='Authenticated i+j+k+l composite only; all three historical interruptions and every definitive old outcome remain unchanged.'
    return value


def run(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,l_audit_sha256,
        ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    result,bindings,sources,corpus,study=authenticated_inputs(root,freeze_sha256,i_audit_sha256,j_audit_sha256,
        k_audit_sha256,l_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,frozen_aliases=frozen_aliases)
    value=analyze_trajectories(corpus,study,result['audits'])
    return finish(root,value,bindings,sources,freeze_sha256,dict(frozen_aliases or {}),
        ('retrace/frontier_v6j_trajectory.py','scripts/analyze_frontier_v6l_trajectory.py'),'retrace.frontier-v6l-k10-trajectory.v1')


def arguments(description):
    parser=argparse.ArgumentParser(description=description);parser.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','i-audit-sha256','j-audit-sha256','k-audit-sha256','l-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--aliases',type=Path);parser.add_argument('--output',type=Path,required=True);return parser.parse_args()


def write_result(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')


def main():
    args=arguments(__doc__);require(not args.output.exists(),'exclusive new supplement output required')
    aliases=strict(args.aliases.read_bytes()) if args.aliases else {}
    value=run(args.root,args.freeze_sha256,args.i_audit_sha256,args.j_audit_sha256,args.k_audit_sha256,
        args.l_audit_sha256,args.ledger_snapshot,args.ledger_snapshot_sha256,frozen_aliases=aliases)
    write_result(args.output,value);print(json.dumps({'schema':value['schema'],'planned_cases':value['planned_cases'],'views':value['views']}))


if __name__=='__main__':main()
