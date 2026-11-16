"""Publish and exactly rebuild both public catalogs from one authenticated tuple.

Offline post-closure orchestration only. The frozen scorer is invoked once by
product.authenticated; all saved-composite and source checks remain in force.
The independent final release reproducer invokes that authentication anew.
"""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import frontier_v6n_products as product
from scripts import reproduce_frontier_v6n_products as replay

RECEIPT='results/frontier-v6n-offline/public-product-export.json'


def run(root,freeze_sha256,prefix_proof_sha256,n_audit_sha256,ledger_snapshot,ledger_snapshot_sha256):
    root=Path(root).resolve();receipt_path=product.score.safe(root,RECEIPT)
    product.require(not receipt_path.exists(),'Never overwrite an export receipt')
    for kind in product.KINDS:
        directory,_=product.branch(kind,False)
        product.require(not product.score.safe(root,directory).exists(),'Exclusive new product directories required')
    own_path=Path(__file__).resolve();own_binding=product.score.binding(own_path)
    code={kind:{p:product.score.binding(product.score.safe(root,p)) for p in product.SOURCES[kind]}
          for kind in product.KINDS}
    args={'freeze_sha256':freeze_sha256,'prefix_proof_sha256':prefix_proof_sha256,
          'n_audit_sha256':n_audit_sha256,'ledger_snapshot':ledger_snapshot,
          'ledger_snapshot_sha256':ledger_snapshot_sha256}
    result,artifacts,sources,data=product.authenticated(root,**args,diagnostic=False)
    values={}
    # Finish both projections before creating either product directory.
    for kind in product.KINDS:
        value=product.project(kind,data['corpus'],data['study'],data['sessions'],
            result['audits'],result['merged_evidence'],diagnostic=False)
        value['authentication']={'source_freeze_sha256':freeze_sha256,
            'authenticated_input_bindings':artifacts,'authenticated_source_bindings':sources,
            'exporter_source_bindings':code[kind],'frozen_aliases':{},
            'study_status':product.branch(kind,False)[1],'diagnostic':False,'replay_arguments':args}
        product.verify_plan(root,value['authentication'],kind);values[kind]=value
    checks=[];manifests={}
    for kind in product.KINDS:
        product.write_catalog(kind,root,values[kind],diagnostic=False)
        name=product.branch(kind,False)[0]+'/manifest.json'
        binding=product.score.binding(product.score.safe(root,name));manifests[name]=binding
        checks.append(replay.verify_catalog(root,kind,freeze_sha256,binding['sha256'],
            result,artifacts,sources,data,diagnostic=False))
    # Late code, full source inventory, and saved-composite equality checks.
    product.require(product.score.binding(own_path)==own_binding,'Capture script changed during export')
    for kind in product.KINDS:product.verify_plan(root,values[kind]['authentication'],kind)
    for name,binding in artifacts.items():
        product.require(product.score.binding(product.score.safe(root,name))==binding,'Saved composite changed during export')
    receipt={'schema':'retrace.frontier-v6n-public-product-export.v1','passed':True,
        'study_status':result['summary']['status'],'scheduled_public_observations':600,
        'selection_view':'first_attempt','provider_calls':0,'authentication_invocations':1,
        'shared_authenticated_tuple':True,'independent_full_release_replay_pending':True,
        'source_entailment_verified':False,'source_completeness':'unknown',
        'original_frozen_inference_available':False,'amended_sensitivity_available':True,
        'replay_arguments':args,'capture_script':{'path':own_path.relative_to(root).as_posix(),**own_binding},
        'authenticated_input_bindings':artifacts,'product_manifests':manifests,'catalog_checks':checks,
        'scope':'Both catalogs are rebuilt byte-exactly against one fully authenticated saved composite; no provider response, source annotation, score, or frozen file is edited.'}
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    with receipt_path.open('xb') as stream:stream.write(product.evidence.encode(receipt))
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','prefix-proof-sha256','n-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args();receipt=run(a.root,a.freeze_sha256,a.prefix_proof_sha256,a.n_audit_sha256,
        a.ledger_snapshot,a.ledger_snapshot_sha256)
    import json
    print(json.dumps({'passed':receipt['passed'],'scheduled_public_observations':600,
        'receipt':RECEIPT,'product_manifests':receipt['product_manifests'],'catalog_checks':receipt['catalog_checks']},indent=2))


if __name__=='__main__':main()
