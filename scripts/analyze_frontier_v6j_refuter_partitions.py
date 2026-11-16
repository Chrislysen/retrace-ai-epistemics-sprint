"""Write an exclusive descriptive refuter audit after authenticated final closure."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from retrace.frontier_v6j_refuter_partitions import analyze_refuter_partitions
from scripts.analyze_frontier_v6j_trajectory import verify_saved
from scripts.score_frontier_v6j import compute,safe,strict,sha,binding,OUTPUT,INPUTS


def require(ok,why):
    if not ok:raise ValueError(why)


def run(root,freeze_sha256,original_audit_sha256,continuation_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    require(not (root/'results/frontier-v6j/budget/active.lock').exists(),'live continuation cannot be analyzed')
    require((root/OUTPUT/'composite-manifest.json').is_file(),'saved authenticated final composite required')
    result,views=compute(root,freeze_sha256,original_audit_sha256,continuation_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,frozen_aliases=aliases)
    bindings=verify_saved(root,result,views,aliases=aliases,ledger_snapshot=ledger_snapshot)
    sources=result['summary']['file_evidence']['source_files']
    for name in (INPUTS['corpus'],INPUTS['study']):
        require(name in sources and binding(safe(root,name))==sources[name],'frozen supplement input changed')
    corpus=strict(safe(root,INPUTS['corpus']).read_bytes());study=strict(safe(root,INPUTS['study']).read_bytes())
    value=analyze_refuter_partitions(corpus,study,result['audits'])
    for name,expected in bindings.items():require(binding(safe(root,name))==expected,'composite changed during supplement')
    for name,expected in sources.items():require(binding(safe(root,aliases.get(name,name)))==expected,'source evidence changed during supplement')
    value['authenticated_input_bindings']=bindings;value['authenticated_source_bindings']=sources
    value['execution_freeze_sha256']=freeze_sha256
    value['supplement_source_sha256']={name:sha(ROOT/name) for name in ('retrace/frontier_v6j_refuter_partitions.py','scripts/analyze_frontier_v6j_refuter_partitions.py','scripts/analyze_frontier_v6j_trajectory.py')}
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','original-audit-sha256','continuation-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--aliases',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    require(not args.output.exists(),'exclusive new supplement output required')
    aliases=strict(args.aliases.read_bytes()) if args.aliases else {}
    result=run(args.root,args.freeze_sha256,args.original_audit_sha256,args.continuation_audit_sha256,args.ledger_snapshot,args.ledger_snapshot_sha256,frozen_aliases=aliases)
    with args.output.open('x',encoding='utf-8',newline='\n') as stream:json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'schema':result['schema'],'planned_slots_per_view':result['planned_slots_per_view'],'views':result['views'],'frozen_endpoint_unchanged':True}))

if __name__=='__main__':main()
