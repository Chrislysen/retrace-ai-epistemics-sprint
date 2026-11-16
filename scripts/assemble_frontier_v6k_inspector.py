"""Compose a verified existing complete k ZIP with NEW inspector paths only.

No report generation or partial-base invention. All outputs are exclusive and
the original base archive remains untouched.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import reproduce_frontier_v6k_inspector as repro
from scripts.reproduce_frontier_v6h_release import safe_path,require,load,sha,canonical,scan_credentials
from scripts import export_frontier_v6k_refuters_product as export

TARGET='deliverables/v6k-inspector/retrace-v6-sprint-artifact.zip'
SIDECAR='deliverables/v6k-inspector/release-manifest-v6k-inspector.json'


def extract_base(archive_path,expected_sha,target):
    require(sha(archive_path)==expected_sha,'Externally pinned original base archive changed')
    target=Path(target)
    with ZipFile(archive_path) as archive:
        rows=archive.infolist();names=[r.filename for r in rows]
        require(len(names)==len(set(n.casefold() for n in names)) and repro.BASE_MANIFEST in names,'Unique exact base archive members')
        require(all(not r.is_dir() and not stat.S_ISLNK(r.external_attr>>16) for r in rows),'Only regular base members')
        # Parse via strict JSON after exclusive safe extraction of manifest.
        path=safe_path(target,repro.BASE_MANIFEST,exists=False);path.parent.mkdir(parents=True,exist_ok=True)
        raw=archive.read(repro.BASE_MANIFEST)
        with path.open('xb') as stream:stream.write(raw)
        inventory=repro.base_inventory(load(path),{'sha256':sha256(raw).hexdigest(),'bytes':len(raw)})
        require(set(names)==set(inventory),'Exact original base ZIP inventory')
        for info in rows:
            name=info.filename;expected=inventory[name]
            require(info.file_size==expected['bytes'],'Original base member size')
            if name!=repro.BASE_MANIFEST:
                path=safe_path(target,name,exists=False);path.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(name) as source,path.open('xb') as dest:shutil.copyfileobj(source,dest)
            path=safe_path(target,name);require(sha(path)==expected['sha256'],'Original base member hash')
            scan_credentials(path)
    require(sha(archive_path)==expected_sha,'Base ZIP changed while reading')
    return inventory


def add_product_files(root,target,base,extra_names):
    """Shared files must be byte identical. Additions never overwrite base."""
    root=Path(root);target=Path(target);names=set(extra_names)
    from scripts.score_frontier_v6h import local_dependencies
    names|={p.relative_to(root).as_posix() for p in local_dependencies([root/n for n in names if n.endswith('.py')])}
    require(len(names)==len({n.casefold() for n in names}),'Case-folded product collision')
    base_folded={n.casefold():n for n in base}
    for name in sorted(names):
        require(name!=repro.MANIFEST and name not in (TARGET,SIDECAR),'Reserved composition output')
        source=safe_path(root,name);scan_credentials(source)
        if name.casefold() in base_folded:
            require(base_folded[name.casefold()]==name and sha(source)==base[name]['sha256']
                and source.stat().st_size==base[name]['bytes'],'Product would replace original base bytes: '+name)
            continue
        destination=safe_path(target,name,exists=False);require(not destination.exists(),'Exclusive new composition member')
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
        require(sha(destination)==sha(source),'Product source changed while copying')
    return set(base)|names


def write_zip(output,root,manifest):
    output=Path(output);require(not output.exists(),'No archive overwrite')
    members=repro.indexed(manifest['files']);repro.verify_inventory(root,manifest)
    with ZipFile(output,'x',compression=ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        for name,row in sorted(members.items()):
            path=safe_path(root,name);require(sha(path)==row['sha256'],'Input changed before ZIP write');archive.write(path,name)
        archive.writestr(repro.MANIFEST,json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with ZipFile(output) as archive:
        require(set(archive.namelist())==set(members)|{repro.MANIFEST} and len(archive.namelist())==len(members)+1,'Combined ZIP membership')
        for name,row in members.items():
            h=sha256();size=0
            with archive.open(name) as source:
                for block in iter(lambda:source.read(1024*1024),b''):h.update(block);size+=len(block)
            require(h.hexdigest()==row['sha256'] and size==row['bytes'],'Combined ZIP decompressed bytes changed')
        require(json.loads(archive.read(repro.MANIFEST))==manifest,'Combined ZIP manifest changed')
    return {'sha256':sha(output),'bytes':output.stat().st_size}


def assemble(root,base_zip,base_zip_sha256,*,extras=()):
    root=Path(root).resolve();base_zip=Path(base_zip).resolve()
    require(base_zip.is_file(),'Existing verified complete k base ZIP required')
    require(root==ROOT,'Assemble from the authenticated source checkout; replay after relocation is separate')
    output=safe_path(root,TARGET,exists=False);sidecar=safe_path(root,SIDECAR,exists=False)
    require(not output.exists() and not sidecar.exists() and output!=base_zip,'Exclusive new nested inspector outputs')
    product=load(safe_path(root,repro.PRODUCT));require(product.get('diagnostic') is False,'Complete product/base composition only')
    product_names={repro.PRODUCT,*product['files']}
    names=set(repro.ADDITIONS)|set(extras)|product_names|set(product['exporter_source_bindings'])
    with tempfile.TemporaryDirectory(prefix='retrace-k-compose-') as tmp:
        assembled=Path(tmp);base=extract_base(base_zip,base_zip_sha256,assembled)
        base_sha=base[repro.BASE_MANIFEST]['sha256'];proof=repro.run_base_verifier(assembled,base_sha)
        all_names=add_product_files(root,assembled,base,names)
        require(product_names.isdisjoint(base),'Product must remain additional absent paths')
        # The combined tree contains the original immutable raw streams/ledgers.
        product_proof=repro.verify_product(assembled,sha(safe_path(assembled,repro.PRODUCT)),frozen_aliases=repro.ALIASES)
        rows=[{'path':n,'sha256':sha(safe_path(assembled,n)),'bytes':safe_path(assembled,n).stat().st_size} for n in sorted(all_names)]
        manifest={'schema':repro.SCHEMA,'status':'complete_amended_primary','scientific_segments':['i','j','k'],
            'source_freeze_sha256':export.FREEZE_SHA,'files':rows,'file_set_sha256':sha256(canonical(rows).encode()).hexdigest(),
            'base':{'original_archive_sha256':base_zip_sha256,'original_archive_bytes':base_zip.stat().st_size,
                'manifest_path':repro.BASE_MANIFEST,'manifest_sha256':base_sha,'member_paths':sorted(base),'verified_reproduction':proof},
            'new_member_paths':sorted(all_names-set(base)),
            'product':{'manifest_path':repro.PRODUCT,'manifest_sha256':sha(safe_path(assembled,repro.PRODUCT)),'verified_reproduction':product_proof},
            'scope':'One self-contained archive. Every original complete-k base member is unchanged. The extra controlled-seed inspector is not a fourth execution segment, a new primary endpoint, or source-entailed repair.'}
        repro.verify_inventory(assembled,manifest)
        require(sha(base_zip)==base_zip_sha256,'Original archive changed before publication')
        output.parent.mkdir(parents=True,exist_ok=True)
        archive=write_zip(output,assembled,manifest)
        with sidecar.open('x',encoding='utf-8',newline='\n') as stream:json.dump(manifest,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    return {'archive':str(output),'archive_sha256':archive['sha256'],'manifest':str(sidecar),'manifest_sha256':sha(sidecar),'base_archive_unchanged':sha(base_zip)==base_zip_sha256}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-zip',type=Path,required=True);p.add_argument('--base-zip-sha256',required=True)
    p.add_argument('--include',action='append',default=[]);a=p.parse_args()
    print(json.dumps(assemble(ROOT,a.base_zip,a.base_zip_sha256,extras=a.include),indent=2))


if __name__=='__main__':main()
