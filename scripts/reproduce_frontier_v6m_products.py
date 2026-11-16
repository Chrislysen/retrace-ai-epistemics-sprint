"""Offline exact replay of both recovered-study public catalogs.

No API calls, repairs, publication or catalog selection by outcome. The public
entry formats reuse earlier reviewed schemas; execution provenance is m.
"""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import frontier_v6m_products as product
from retrace.server_v6m import EvidenceCatalog
from retrace.refuter_reader_v6m import RefuterCatalog


def read_manifest(root,kind,freeze_sha256,manifest_sha256,diagnostic):
    directory,status=product.branch(kind,diagnostic);name=directory+'/manifest.json'
    raw=product.score.safe(root,name).read_bytes()
    product.require(product.sha256(raw).hexdigest()==manifest_sha256,'Externally pinned product manifest changed')
    value=product.strict(raw)
    product.require(value['schema']==product.schema(kind,diagnostic) and value['status']==status
        and value['diagnostic'] is diagnostic and value['source_freeze_sha256']==freeze_sha256,
        'Exact recovered product branch/freeze')
    product.require(value['inference_available'] is False
        and value['amended_sensitivity_available'] is (not diagnostic)
        and value['scientific_segments']==['i','j','k-prefix','m'],'Diagnostic and recovery sensitivity remain distinct')
    return name,raw,value


def verify_catalog(root,kind,freeze_sha256,manifest_sha256,result,artifacts,sources,data,*,diagnostic=False,frozen_aliases=None):
    """Caller supplies the exact output of product.authenticated; no new scoring."""
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    name,raw,manifest=read_manifest(root,kind,freeze_sha256,manifest_sha256,diagnostic)
    product.require(result['summary']['status']==product.branch(kind,diagnostic)[1],'Matching authenticated composite')
    reader_type=EvidenceCatalog if kind=='catalog' else RefuterCatalog
    reader=reader_type(root,expected_manifest_sha256=manifest_sha256,expected_freeze_sha256=freeze_sha256,diagnostic=diagnostic)
    product.require(reader.index().get('available') is True,'All300 pinned public observations required')
    product.require(manifest['authenticated_input_bindings']==artifacts,'Exact eight final artifact bindings')
    product.require(manifest['authenticated_source_bindings']==sources,'Exact raw/source/SSE provenance union')
    actual_code={p:product.score.binding(product.score.safe(root,p)) for p in product.SOURCES[kind]}
    product.require(manifest['exporter_source_bindings']==actual_code,'Recorded projection code changed')
    rebuilt=product.project(kind,data['corpus'],data['study'],data['sessions'],result['audits'],result['merged_evidence'],diagnostic=diagnostic)
    payloads=product.payloads(kind,rebuilt,diagnostic)
    product.require(set(payloads)==set(manifest['files']),'Exact first-attempt member inventory')
    for path,expected in payloads.items():
        product.require(product.score.safe(root,path).read_bytes()==expected,'Byte-exact public projection differs: '+path)
    product.verify_plan(root,{**manifest,'frozen_aliases':aliases},kind)
    product.require(product.score.safe(root,name).read_bytes()==raw,'Manifest changed during replay')
    return {'kind':kind,'passed':True,'scheduled_slots':300,'payload_members':len(payloads),
        'manifest_path':name,'manifest_sha256':manifest_sha256,'selection_view':'first_attempt',
        'source_entailment_verified':False,'source_completeness':'unknown'}


def verify(root,freeze_sha256,catalog_manifest_sha256,refuter_manifest_sha256,*,diagnostic=False,frozen_aliases=None):
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    product.require(not product.score.safe(root,product.score.LOCK).exists(),'Active recovery worker cannot be reproduced')
    manifests=[read_manifest(root,kind,freeze_sha256,pin,diagnostic)[2]
        for kind,pin in zip(product.KINDS,(catalog_manifest_sha256,refuter_manifest_sha256))]
    args=manifests[0]['replay_arguments']
    product.require(set(args)=={'freeze_sha256','prefix_proof_sha256','m_audit_sha256','ledger_snapshot','ledger_snapshot_sha256'}
        and args==manifests[1]['replay_arguments'] and args['freeze_sha256']==freeze_sha256,'Exact common recovery replay arguments')
    result,artifacts,sources,data=product.authenticated(root,**args,frozen_aliases=aliases,diagnostic=diagnostic)
    results=[verify_catalog(root,kind,freeze_sha256,pin,result,artifacts,sources,data,
        diagnostic=diagnostic,frozen_aliases=aliases) for kind,pin in zip(product.KINDS,(catalog_manifest_sha256,refuter_manifest_sha256))]
    return {'schema':'retrace.frontier-v6m-public-products-reproduction.v1','passed':True,
        'study_status':product.branch('catalog',diagnostic)[1],'source_freeze_sha256':freeze_sha256,
        'catalogs':results,'scientific_segments':['i','j','k-prefix','m'],'model_calls_made':0,
        'original_frozen_inference_available':False,'amended_sensitivity_available':not diagnostic,
        'scope':'Both public projections reproduce all300 first attempts each. Controlled seeds are not actual upstream IR; location and symbolic effects do not certify source entailment.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--freeze-sha256',required=True);p.add_argument('--catalog-manifest-sha256',required=True)
    p.add_argument('--refuter-manifest-sha256',required=True);p.add_argument('--diagnostic',action='store_true');p.add_argument('--aliases',type=Path)
    a=p.parse_args();aliases=product.strict(a.aliases.read_bytes()) if a.aliases else {}
    import json
    print(json.dumps(verify(a.root,a.freeze_sha256,a.catalog_manifest_sha256,a.refuter_manifest_sha256,
        diagnostic=a.diagnostic,frozen_aliases=aliases),indent=2))


if __name__=='__main__':main()
