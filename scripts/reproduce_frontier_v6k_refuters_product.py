"""Replay a k-only controlled-seed product from authenticated three-segment evidence.

Both explicit completed and interrupted branches are supported. This performs no
inference, source repair, publication, or file writes.
"""
import argparse
from hashlib import sha256
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import export_frontier_v6k_refuters_product as export
from retrace.refuter_product_v6k import KRefuterCatalog
from retrace.refuter_catalog_v6l import encode,require


def verify(root,manifest_sha256,*,diagnostic=False,frozen_aliases=None):
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    directory,status,schema=export.branch(diagnostic);name=directory+'/manifest.json'
    path=export.full.safe(root,name);raw=path.read_bytes()
    require(sha256(raw).hexdigest()==manifest_sha256,'Externally pinned product manifest changed')
    manifest=export.full.strict(raw)
    require(manifest.get('schema')==schema and manifest.get('status')==status
        and manifest.get('diagnostic') is diagnostic,'Explicit k product branch required')
    reader=KRefuterCatalog(root,expected_manifest_sha256=manifest_sha256,diagnostic=diagnostic)
    require(reader.index().get('available') is True,'All300 recorded observations required')
    args=manifest.get('replay_arguments',{})
    require(set(args)=={'freeze','i','j','k','snapshot','snapshot_sha'},'Exact three-audit replay arguments required')
    result,artifacts,sources,data=export.authenticated(root,**args,frozen_aliases=aliases,diagnostic=diagnostic)
    require(manifest.get('authenticated_input_bindings')==artifacts,'Saved product/composite binding differs')
    require(manifest.get('authenticated_source_bindings')==sources,'Saved product raw/SSE/source inventory differs')
    require(manifest.get('exporter_source_bindings')=={p:export.full.binding(export.full.safe(root,p)) for p in export.SOURCES},'Saved product projection code changed')
    require(manifest.get('frozen_aliases') in ({},export.full.ALIASES),'Unknown saved relocation alias')
    rebuilt=export.project(data['corpus'],data['study'],data['sessions'],result['audits'],result['merged_evidence'],diagnostic=diagnostic)
    require(rebuilt['bundles']=={},'Controlled seed cannot be promoted to source IR')
    payload={directory+'/index.json':encode(rebuilt['index']),**{p:encode(v) for p,v in rebuilt['entries'].items()}}
    require(len(payload)==301 and set(payload)==set(manifest['files']),'Exact all300 entries plus index required')
    for name,expected in payload.items():
        require(export.full.safe(root,name).read_bytes()==expected,'Byte-exact first-attempt product replay differs: '+name)
    # Recheck all sources, including raw streams, after the bounded product pass.
    auth={**manifest,'frozen_aliases':aliases};export.verify_plan(root,auth)
    require(path.read_bytes()==raw,'Product manifest changed during replay')
    return {'schema':'retrace.controlled-refuter-product.v6k-reproduction.v1','passed':True,
        'scientific_execution':'v6k','scientific_segments':['i','j','k'],'study_status':status,
        'scheduled_slots':300,'payload_members':301,'selection_view':'first_attempt',
        'manifest_path':directory+'/manifest.json','manifest_sha256':manifest_sha256,
        'source_freeze_sha256':export.FREEZE_SHA,'raw_source_and_sse_bindings_replayed':True,
        'source_ir_promotions':0,'model_calls_made':0,
        'scope':'Controlled model-given seeds only. Citation location and symbolic effects do not establish textual entailment or refute an actual upstream extraction.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--manifest-sha256',required=True);p.add_argument('--diagnostic',action='store_true');p.add_argument('--aliases',type=Path)
    a=p.parse_args();aliases=export.full.strict(a.aliases.read_bytes()) if a.aliases else {}
    import json
    print(json.dumps(verify(a.root,a.manifest_sha256,diagnostic=a.diagnostic,frozen_aliases=aliases),indent=2))


if __name__=='__main__':main()
