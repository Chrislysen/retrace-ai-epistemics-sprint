"""Four-segment authentication for unchanged descriptive refuter partitions."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from retrace.frontier_v6j_refuter_partitions import analyze_refuter_partitions
from scripts.analyze_frontier_v6l_trajectory import authenticated_inputs,finish,arguments,write_result,require,strict


def run(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,l_audit_sha256,
        ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    result,bindings,sources,corpus,study=authenticated_inputs(root,freeze_sha256,i_audit_sha256,j_audit_sha256,
        k_audit_sha256,l_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,frozen_aliases=frozen_aliases)
    value=analyze_refuter_partitions(corpus,study,result['audits'])
    return finish(root,value,bindings,sources,freeze_sha256,dict(frozen_aliases or {}),
        ('retrace/frontier_v6j_refuter_partitions.py','scripts/analyze_frontier_v6l_trajectory.py',
         'scripts/analyze_frontier_v6l_refuter_partitions.py'),'retrace.frontier-v6l-refuter-partitions.v1')


def main():
    args=arguments(__doc__);require(not args.output.exists(),'exclusive new supplement output required')
    aliases=strict(args.aliases.read_bytes()) if args.aliases else {}
    value=run(args.root,args.freeze_sha256,args.i_audit_sha256,args.j_audit_sha256,args.k_audit_sha256,
        args.l_audit_sha256,args.ledger_snapshot,args.ledger_snapshot_sha256,frozen_aliases=aliases)
    write_result(args.output,value);print(json.dumps({'schema':value['schema'],'planned_slots_per_view':value['planned_slots_per_view'],'views':value['views']}))


if __name__=='__main__':main()
