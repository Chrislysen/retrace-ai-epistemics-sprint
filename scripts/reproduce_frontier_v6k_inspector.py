"""Offline verification of one composed k-base-plus-inspector archive.

The unchanged base verifier runs in an isolated copy of exactly the base members.
The new public product then replays against the full extracted archive. No base
file is overwritten and no l scientific execution is fabricated.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.reproduce_frontier_v6h_release import safe_path,require,load,sha,canonical,scan_credentials
from scripts.export_frontier_v6k_refuters_product import FREEZE_SHA
from scripts.reproduce_frontier_v6k_refuters_product import verify as verify_product

MANIFEST='release-manifest-v6k-inspector.json'
BASE_MANIFEST='release-manifest-v6k.json'
SCHEMA='retrace.frontier-v6k-inspector-composition.v1'
PRODUCT='results/frontier-v6k/refuter-product/manifest.json'
ALIASES={'results/frontier-v6f/budget/active.lock':'provenance/frozen-locks/results/frontier-v6f/budget/active.lock.txt'}
ADDITIONS=(
    'scripts/export_frontier_v6k_refuters_product.py','scripts/reproduce_frontier_v6k_refuters_product.py',
    'scripts/assemble_frontier_v6k_inspector.py','scripts/reproduce_frontier_v6k_inspector.py',
    'retrace/refuter_product_v6k.py','retrace/server_v6k_inspector.py',
    'retrace/refuter_catalog_v6l.py','retrace/refuter_inspector_v6l.py','retrace/refuter_reader_v6l.py',
    'retrace/server_v6l.py','retrace/evidence_catalog_v6l.py','retrace/source_diagnostics_v6k.py',
    'web/v6k-inspector/index.html','web/v6k-inspector/diagnostic.html',
    'web/v6l/evidence.js','web/v6l/refuters.js',
    'tests/test_refuter_product_v6k.py','tests/test_refuter_product_composition_v6k.py',
    'tests/test_refuters_v6k_inspector.mjs',
    'tests/test_refuter_inspector_v6l.py','tests/test_refuter_catalog_v6l.py',
    'tests/test_refuter_reader_v6l.py','tests/test_frontier_v6l_catalog.py',
    'research/frontier-v6k-inspector-product-review.md',
    'README-V6K-INSPECTOR.md','REPRODUCE-V6K-INSPECTOR.md','START-V6K-INSPECTOR.ps1')


def indexed(rows):
    require(isinstance(rows,list) and rows,'Nonempty explicit inventory required')
    result={};folded=set()
    for row in rows:
        require(isinstance(row,dict) and set(row)=={'path','sha256','bytes'},'Exact member binding fields')
        name=row['path'];safe_path(ROOT,name,exists=False)
        require(name.casefold() not in folded and name!=MANIFEST,'Duplicate/reserved composition member')
        require(type(row['bytes']) is int and row['bytes']>=0 and isinstance(row['sha256'],str)
            and len(row['sha256'])==64 and set(row['sha256'])<=set('0123456789abcdef'),'Member digest/length')
        result[name]=row;folded.add(name.casefold())
    return result


def base_inventory(manifest,manifest_binding):
    require(manifest.get('schema')=='retrace.frontier-v6k-amended-release.v1'
        and manifest.get('status')=='complete_amended_primary' and manifest.get('planned_slots')==1800
        and manifest.get('freeze')=={'path':'data/frontier-v6k-freeze.json','sha256':FREEZE_SHA},'Existing complete k base required; no partial-base convention')
    result=indexed(manifest['files'])
    require(BASE_MANIFEST not in result,'Base manifest cannot inventory itself')
    require(sha256(canonical(manifest['files']).encode()).hexdigest()==manifest.get('file_set_sha256'),'Base inventory digest')
    result[BASE_MANIFEST]={'path':BASE_MANIFEST,**manifest_binding}
    return result


def run_base_verifier(root,manifest_sha):
    """Call only the exact authenticated script in an isolated base tree."""
    env=dict(os.environ);env.pop('PYTHONPATH',None);env['PYTHONDONTWRITEBYTECODE']='1'
    result=subprocess.run([sys.executable,'-B','-S',str(root/'scripts/reproduce_frontier_v6k_release.py'),
        '--manifest-sha256',manifest_sha],cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',check=False)
    require(result.returncode==0,'Unchanged isolated base reproduction failed: '+result.stderr[-2000:])
    value=json.loads(result.stdout)
    require(value.get('status')=='verified_complete_amended_primary' and value.get('model_calls_made')==0,'Base verifier did not authenticate complete study')
    return {k:value[k] for k in ('status','files_verified','frozen_files_verified','symbolic_tests','model_calls_made')}


def verify_inventory(root,manifest):
    root=Path(root).resolve()
    require(manifest.get('schema')==SCHEMA and manifest.get('status')=='complete_amended_primary'
        and manifest.get('scientific_segments')==['i','j','k'] and manifest.get('source_freeze_sha256')==FREEZE_SHA,'Complete three-segment composition required')
    members=indexed(manifest['files'])
    require(sha256(canonical(manifest['files']).encode()).hexdigest()==manifest.get('file_set_sha256'),'Combined inventory digest')
    for name,row in members.items():
        path=safe_path(root,name);require(path.stat().st_size==row['bytes'] and sha(path)==row['sha256'],'Combined member changed: '+name)
    base_info=manifest['base'];require(base_info['manifest_path']==BASE_MANIFEST,'Exact base manifest path')
    base_path=safe_path(root,BASE_MANIFEST);base_binding={'sha256':sha(base_path),'bytes':base_path.stat().st_size}
    require(base_binding['sha256']==base_info['manifest_sha256'],'Base manifest pin')
    base=base_inventory(load(base_path),base_binding)
    require(base_info['member_paths']==sorted(base) and all(members.get(n)==row for n,row in base.items()),'Original base bytes or exact membership changed')
    additions=set(members)-set(base)
    require(additions==set(manifest['new_member_paths']) and not set(base)&additions,'New paths only; no base replacement')
    require(set(ADDITIONS)<=set(members) and PRODUCT in additions,'Product inputs/catalog missing')
    catalog=load(safe_path(root,PRODUCT));require(catalog.get('scientific_segments')==['i','j','k']
        and catalog.get('status')=='complete_amended_primary' and catalog.get('diagnostic') is False,'No diagnostic catalog in a complete composition')
    require({PRODUCT,*catalog['files']}<=additions,'The new product must use only absent paths')
    require(manifest['product']['manifest_path']==PRODUCT and manifest['product']['manifest_sha256']==members[PRODUCT]['sha256'],'Product pin changed')
    # All raw study paths must be inventoried; never smuggle an active ledger.
    for prefix in ('results/frontier-v6i','results/frontier-v6j','results/frontier-v6k'):
        for path in (root/prefix).rglob('*'):
            if path.is_file():require(path.relative_to(root).as_posix() in members,'Uninventoried study artifact')
    return {'files_verified':len(members),'base_members_preserved':len(base),'new_members':len(additions),'base':base}


def verify(root,manifest,*,run_tests=True):
    root=Path(root).resolve();before=verify_inventory(root,manifest)
    with tempfile.TemporaryDirectory(prefix='retrace-k-base-') as temp:
        isolated=Path(temp)
        for name,row in before['base'].items():
            target=safe_path(isolated,name,exists=False);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(safe_path(root,name),target)
            require(sha(target)==row['sha256'],'Isolated original base changed')
        base=run_base_verifier(isolated,manifest['base']['manifest_sha256'])
    require(base==manifest['base']['verified_reproduction'],'Original base reproduction differs')
    product=verify_product(root,manifest['product']['manifest_sha256'],frozen_aliases=ALIASES)
    require(product==manifest['product']['verified_reproduction'],'Product replay differs')
    if run_tests:
        import unittest,io
        stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromNames(('tests.test_refuter_product_v6k','tests.test_refuter_product_composition_v6k'))
        tests=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
        require(tests.wasSuccessful() and not tests.skipped,'Offline product fixtures failed: '+stream.getvalue())
        test_result={'tests_run':tests.testsRun,'passed':True}
    else:test_result={'not_run':True}
    verify_inventory(root,manifest)
    return {'schema':'retrace.frontier-v6k-inspector-reproduction.v1','passed':True,'status':'verified_complete_amended_primary',
        'files_verified':before['files_verified'],'base_members_preserved':before['base_members_preserved'],
        'new_members':before['new_members'],'base_reproduction':base,'product_reproduction':product,
        'product_fixture_tests':test_result,'model_calls_made':0,
        'scope':'Saved report and all-page visual-review records are authenticated by the unchanged base verifier; this does not rerender the paper or certify human review.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--hashes-only',action='store_true',help='Integrity only; does not replay raw streams or scores');a=p.parse_args()
    path=ROOT/MANIFEST;require(sha(path)==a.manifest_sha256,'Externally pinned outer manifest changed')
    value=verify_inventory(ROOT,load(path)) if a.hashes_only else verify(ROOT,load(path))
    value.pop('base',None);print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
