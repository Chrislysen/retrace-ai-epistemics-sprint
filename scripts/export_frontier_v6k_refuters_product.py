"""NEW product-only export from an actual closed THREE-segment k study.

No l execution proof, inference call, source repair or report/ZIP replacement.
"""
import argparse
from hashlib import sha256
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from retrace.refuter_catalog_v6l import build_catalog,encode,require,DIRECTORY as FORMAT_DIRECTORY
from scripts import score_frontier_v6k as full
from scripts import score_frontier_v6k_partial as partial
from scripts.analyze_frontier_v6k_trajectory import verify_saved as verify_complete
from scripts.export_frontier_v6k_partial_catalog import verify_saved as verify_partial

FREEZE_SHA='274d3101ed47e3ca918ee1e2273c0cdd269b43c60567e3fa4e121f6a7b9efa40'
SNAPSHOT='data/frontier-v6k-ledger-after-continuation.jsonl'
LOCK='results/frontier-v6k/budget/active.lock'
SOURCES=('scripts/export_frontier_v6k_refuters_product.py','retrace/refuter_catalog_v6l.py',
    'retrace/refuter_inspector_v6l.py','retrace/evidence_catalog_v6l.py','retrace/refuter_gate_v6h.py',
    'retrace/impact_v6h.py','retrace/source_ir_v6h.py','scripts/analyze_frontier_v6k_trajectory.py',
    'scripts/export_frontier_v6k_partial_catalog.py')


def branch(diagnostic):
    require(type(diagnostic) is bool,'Explicit diagnostic selector required')
    return ('results/frontier-v6k/partial-refuter-product','interrupted_amended_diagnostic',
        'retrace.controlled-refuter-product.v6k-partial.v1') if diagnostic else (
        'results/frontier-v6k/refuter-product','complete_amended_primary','retrace.controlled-refuter-product.v6k.v1')


def project(corpus,study,slots,audits,merged,*,diagnostic=False):
    directory,status,_=branch(diagnostic)
    require(set(merged.get('segment_summaries',{}))=={'i','j','k'},'Actual three-segment evidence required')
    require(all(p['segment'] in ('i','j','k') for rows in merged['source_provenance'].values() for p in rows), 'No fabricated fourth-segment pointer')
    value=build_catalog(corpus,study,slots,audits,merged)
    def moved(name):
        require(name.startswith(FORMAT_DIRECTORY+'/'),'Expected shared product-format path')
        return directory+name[len(FORMAT_DIRECTORY):]
    value['entries']={moved(p):v for p,v in value['entries'].items()}
    value['index']['scope']=('INTERRUPTED STUDY. ' if diagnostic else '')+'Scientific execution: v6k, three segments i/j/k. '+value['index']['scope']
    for row in value['index']['entries']:
        row['entry_path']=moved(row['entry_path'])
        row['entry_sha256']=sha256(encode(value['entries'][row['entry_path']])).hexdigest()
    return value


def authenticated(root,freeze,i,j,k,snapshot,snapshot_sha,*,frozen_aliases=None,diagnostic=False):
    root=Path(root).resolve();aliases=dict(frozen_aliases or {});_,status,_=branch(diagnostic)
    require(freeze==FREEZE_SHA and snapshot==SNAPSHOT,'Exact k freeze and final immutable snapshot required')
    require(aliases in ({},full.ALIASES),'Sole inert historical-lock alias only')
    require(not full.safe(root,LOCK).exists(),'Live k worker cannot be read/exported')
    prefix=partial.OUTPUT if diagnostic else full.OUTPUT
    saved=prefix+('/partial-manifest.json' if diagnostic else '/composite-manifest.json')
    require(full.safe(root,saved).is_file(),'Saved closed three-segment composite required')
    compute=partial.compute if diagnostic else full.compute
    result,views=compute(root,freeze,i,j,k,snapshot,snapshot_sha,frozen_aliases=aliases)
    result=full.json_value(result)
    require(result['summary']['status']==status,'Explicit completed or stopped k branch required')
    artifacts=verify_partial(root,result,views,aliases) if diagnostic else verify_complete(root,result,views,aliases=aliases,ledger_snapshot=snapshot)
    evidence=result['summary']['file_evidence'];saved_evidence=full.strict(full.safe(root,prefix+'/score.json').read_bytes())['file_evidence']
    normalized=dict(saved_evidence);normalized['frozen_aliases']=aliases
    require(normalized==evidence,'Exact complete saved/replayed authentication receipt required')
    # Frozen complete-k compute authenticates/replays this audit but does not
    # copy its input_bindings into summary.file_evidence. Partial-k does. Read
    # the authenticated saved audit, never invent or mutate the old receipt.
    audit_path=full.AUDITS['k'];audit_binding=full.binding(full.safe(root,audit_path))
    require(evidence['source_files'].get(audit_path)==audit_binding and audit_binding['sha256']==k,'Replayed k audit binding required')
    runtime=full.strict(full.safe(root,audit_path).read_bytes())
    require(runtime.get('passed') is True and runtime.get('final_closed') is True
        and runtime.get('schedule_status')==('stopped' if diagnostic else 'completed'),'Authenticated k closure required')
    runtime_inputs=runtime['input_bindings']
    require('runtime_input_bindings' not in evidence or evidence['runtime_input_bindings']==runtime_inputs,'Contradictory summary/runtime inventory')
    sources=dict(evidence['source_files'])
    for group in (runtime_inputs,evidence.get('post_freeze_diagnostic_code',{})):
        for name,value in group.items():
            name=snapshot if name==full.LEDGER else name
            require(name not in sources or sources[name]==value,'Contradictory k source binding')
            sources[name]=value
    data={key:full.strict(full.safe(root,full.INPUTS[key]).read_bytes()) for key in ('corpus','study','sessions')}
    return result,artifacts,sources,data


def run(root,freeze,i,j,k,snapshot,snapshot_sha,*,frozen_aliases=None,diagnostic=False):
    root=Path(root).resolve();directory,status,_=branch(diagnostic);aliases=dict(frozen_aliases or {})
    require(not full.safe(root,directory).exists(),'Exclusive new product catalog required')
    code={p:full.binding(full.safe(root,p)) for p in SOURCES}
    result,artifacts,sources,data=authenticated(root,freeze,i,j,k,snapshot,snapshot_sha,frozen_aliases=aliases,diagnostic=diagnostic)
    value=project(data['corpus'],data['study'],data['sessions'],result['audits'],result['merged_evidence'],diagnostic=diagnostic)
    value['authentication']={'scientific_execution':'v6k','scientific_segments':['i','j','k'],
        'source_freeze_sha256':freeze,'authenticated_input_bindings':artifacts,'authenticated_source_bindings':sources,
        'exporter_source_bindings':code,'frozen_aliases':aliases,'diagnostic':diagnostic,'study_status':status,
        'replay_arguments':{'freeze':freeze,'i':i,'j':j,'k':k,'snapshot':snapshot,'snapshot_sha':snapshot_sha}}
    verify_plan(root,value['authentication']);return value


def verify_plan(root,auth):
    require(auth['scientific_execution']=='v6k' and auth['scientific_segments']==['i','j','k']
        and auth['source_freeze_sha256']==FREEZE_SHA and auth['study_status']==branch(auth['diagnostic'])[1], 'Three-segment product identity')
    require(auth['frozen_aliases'] in ({},full.ALIASES) and set(auth['exporter_source_bindings'])==set(SOURCES),'Exact product sources/alias')
    require(not full.safe(root,LOCK).exists(),'Live worker cannot publish')
    full.verify_inventory(root,FREEZE_SHA,auth['frozen_aliases'])
    for group in ('authenticated_input_bindings','authenticated_source_bindings','exporter_source_bindings'):
        for name,value in auth[group].items():
            require(full.binding(full.safe(root,auth['frozen_aliases'].get(name,name)))==value,'Bound product source changed')


def write_catalog(root,value,*,diagnostic=False):
    directory,status,schema=branch(diagnostic);root=Path(root).resolve();target=full.safe(root,directory)
    require(not target.exists(),'Exclusive new product catalog required')
    auth=value['authentication'];index=value['index']
    require(auth['diagnostic'] is diagnostic and auth['study_status']==status and index['scheduled_slots']==300
        and index['test_fixture'] is False and len(value['entries'])==len(index['entries'])==300 and value['bundles']=={}, 'Exact all300 graph-free product')
    payload={directory+'/index.json':encode(index),**{p:encode(v) for p,v in value['entries'].items()}}
    require(set(payload)=={directory+'/index.json',*(r['entry_path'] for r in index['entries'])},'Exact301-member inventory')
    for row in index['entries']:
        require(row['entry_path']==directory+'/entries/'+row['key']+'.json' and sha256(payload[row['entry_path']]).hexdigest()==row['entry_sha256'],'Entry/index binding')
    manifest={'schema':schema,'status':status,'schedule_complete':not diagnostic,'inference_available':not diagnostic,
        'scheduled_slots':300,'selection_view':'first_attempt','index_path':directory+'/index.json',
        'files':{p:{'sha256':sha256(raw).hexdigest(),'bytes':len(raw)} for p,raw in payload.items()},**auth,
        'scope':index['scope'],'format_note':'The v6l entry/index schemas identify reusable product formats, not an l inference segment.'}
    verify_plan(root,auth);target.mkdir(parents=True,exist_ok=False)
    for name,raw in payload.items():
        p=full.safe(root,name);require(p.is_relative_to(target),'Product path escaped');p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(raw)
    verify_plan(root,auth)
    with (target/'manifest.json').open('xb') as f:f.write(encode(manifest))
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze','i','j','k','snapshot','snapshot-sha'):p.add_argument('--'+name,required=True)
    p.add_argument('--aliases',type=Path);p.add_argument('--diagnostic',action='store_true');a=p.parse_args()
    aliases=full.strict(a.aliases.read_bytes()) if a.aliases else {}
    result=run(a.root,a.freeze,a.i,a.j,a.k,a.snapshot,a.snapshot_sha,frozen_aliases=aliases,diagnostic=a.diagnostic)
    print(write_catalog(a.root,result,diagnostic=a.diagnostic)['status'])


if __name__=='__main__':main()
