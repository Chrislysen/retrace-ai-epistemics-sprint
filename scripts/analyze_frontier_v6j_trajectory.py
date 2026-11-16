"""Run the descriptive K10 supplement only on authenticated final composites."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from retrace.frontier_v6j_trajectory import analyze_trajectories
from scripts.score_frontier_v6j import compute,safe,strict,sha,binding,json_value,ALIASES,OUTPUT,INPUTS


def require(ok,why):
    if not ok:raise ValueError(why)


def verify_saved(root,result,views,*,aliases,ledger_snapshot):
    """Authenticate the saved complete composite; do not create it from live data."""
    root=Path(root).resolve();path=safe(root,OUTPUT+'/composite-manifest.json');manifest=strict(path.read_bytes())
    require(manifest['schema']=='retrace.frontier-v6j-composite-artifacts.v1' and manifest['status']=='complete_amended_primary' and manifest['planned_slots']==1800,'final complete amended composite required')
    expected_names={OUTPUT+'/'+name for name in ('score.json','score-audits.json','requests.jsonl','responses.jsonl','slot-outcomes.jsonl','source-provenance.json','derived-closure.json')}
    require(set(manifest['files'])==expected_names,'exact final composite output inventory')
    bindings={OUTPUT+'/composite-manifest.json':binding(path)}
    for name,expected in manifest['files'].items():
        require(binding(safe(root,name))==expected,'changed final composite artifact');bindings[name]=expected
    # Match the frozen writer's JSON value projection (e.g. tuples become
    # arrays). This applies to objects only, never to exact JSONL source bytes.
    saved=strict(safe(root,OUTPUT+'/score.json').read_bytes());replay=json_value(result['summary'])
    evidence=saved.pop('file_evidence');replay_evidence=replay.pop('file_evidence')
    require(saved==replay and evidence==manifest['file_evidence'],'saved final scientific score does not reproduce')
    require(evidence['execution_freeze']==replay_evidence['execution_freeze'] and evidence['runtime_audits_replayed'] is True and evidence['runtime_input_bindings_rechecked_after_score'] is True,'final evidence was not replayed')
    require(evidence['frozen_aliases'] in ({},ALIASES),'unsupported saved alias map')
    require(evidence['ledger_snapshot']['sha256']==sha(safe(root,ledger_snapshot)),'final immutable ledger differs')
    normalized_sources={ledger_snapshot if name==evidence['ledger_snapshot']['path'] else name:expected for name,expected in evidence['source_files'].items()}
    require(normalized_sources==replay_evidence['source_files'],'saved and replayed source inventories differ')
    for name,expected in evidence['source_files'].items():
        target=ledger_snapshot if name==evidence['ledger_snapshot']['path'] else aliases.get(name,name)
        require(binding(safe(root,target))==expected,'saved evidence input changed')
    objects={'score-audits.json':result['audits'],'source-provenance.json':result['merged_evidence']['source_provenance'],'derived-closure.json':result['summary']['operational_summary']}
    for name,value in objects.items():require(strict(safe(root,OUTPUT+'/'+name).read_bytes())==json_value(value),'saved audit/provenance/closure differs from replay')
    for role,name in (('requests','requests.jsonl'),('responses','responses.jsonl'),('outcomes','slot-outcomes.jsonl')):
        require(safe(root,OUTPUT+'/'+name).read_bytes()==views[role],'saved raw-byte composite view changed')
    require(manifest['source_bindings']==json_value(result['merged_evidence']['source_bindings']) and manifest['source_rows_changed'] is False and manifest['selected_jsonl_source_bytes_preserved'] is True,'lossless composite provenance required')
    return bindings


def run(root,freeze_sha256,original_audit_sha256,continuation_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    # Refuse early before invoking a final auditor or reading generated answers.
    require(not (root/'results/frontier-v6j/budget/active.lock').exists(),'live continuation cannot be analyzed')
    require((root/OUTPUT/'composite-manifest.json').is_file(),'saved authenticated final composite required')
    result,views=compute(root,freeze_sha256,original_audit_sha256,continuation_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,frozen_aliases=aliases)
    bindings=verify_saved(root,result,views,aliases=aliases,ledger_snapshot=ledger_snapshot)
    source_bindings=result['summary']['file_evidence']['source_files']
    for name in (INPUTS['corpus'],INPUTS['study']):
        require(name in source_bindings and binding(safe(root,name))==source_bindings[name],'frozen supplement input changed')
    corpus=strict(safe(root,INPUTS['corpus']).read_bytes());study=strict(safe(root,INPUTS['study']).read_bytes())
    value=analyze_trajectories(corpus,study,result['audits'])
    for name,expected in bindings.items():require(binding(safe(root,name))==expected,'composite changed during supplement')
    for name,expected in source_bindings.items():
        require(binding(safe(root,aliases.get(name,name)))==expected,'source evidence changed during supplement')
    value['authenticated_input_bindings']=bindings
    value['authenticated_source_bindings']=source_bindings
    value['execution_freeze_sha256']=freeze_sha256
    value['supplement_source_sha256']={'retrace/frontier_v6j_trajectory.py':sha(ROOT/'retrace/frontier_v6j_trajectory.py'),'scripts/analyze_frontier_v6j_trajectory.py':sha(Path(__file__))}
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT)
    for key in ('freeze-sha256','original-audit-sha256','continuation-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):p.add_argument('--'+key,required=True)
    p.add_argument('--aliases',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    require(not a.output.exists(),'exclusive new supplement output required')
    aliases=strict(a.aliases.read_bytes()) if a.aliases else {}
    result=run(a.root,a.freeze_sha256,a.original_audit_sha256,a.continuation_audit_sha256,a.ledger_snapshot,a.ledger_snapshot_sha256,frozen_aliases=aliases)
    with a.output.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'schema':result['schema'],'planned_cases':result['planned_cases'],'views':result['views'],'prefix10_all_match_frozen_unions':result['prefix10_all_match_frozen_unions'],'monotonicity':result['monotonicity']}))

if __name__=='__main__':main()
