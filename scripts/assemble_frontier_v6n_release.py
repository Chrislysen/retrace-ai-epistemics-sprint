"""Exclusive final n archive, only after genuine closure, replay and report QA."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import reproduce_frontier_v6n_release as verify
TARGET='deliverables/v6n-final/retrace-v6-sprint-artifact.zip'
MANIFEST_TARGET='deliverables/v6n-final/release-manifest-v6n.json'


def plan(root,freeze_sha256,extras=()):
    root=Path(root).resolve();verify.require(root==ROOT,'Assemble only from the source workspace')
    frozen=verify.freeze_binding(root,freeze_sha256,{})
    names,reproduction=verify.authenticated(root,freeze_sha256,{})
    names|=set(verify.ADDITIONS)|verify.REQUIRED_EVIDENCE|{verify.REPORT_RECEIPT}|set(extras)
    names|={row['path'] for row in frozen['files']}
    # Static dependencies of new post-freeze modules join the frozen inventory.
    from scripts.score_frontier_v6h import local_dependencies
    names|={p.relative_to(root).as_posix() for p in local_dependencies([root/n for n in names if n.endswith('.py')])}
    sources={};aliases={};seen=set()
    for name in sorted(names):
        verify.require(name not in (TARGET,MANIFEST_TARGET,verify.MANIFEST_NAME),'Archive cannot contain itself')
        source=verify.safe_path(root,name,allow_lock=name in verify.ALIASES)
        archive_name=verify.ALIASES.get(name,name)
        if name in verify.ALIASES:aliases[name]=archive_name
        verify.safe_path(root,archive_name,exists=False)
        verify.require(archive_name.casefold() not in seen,'Duplicate archive member')
        seen.add(archive_name.casefold());verify.scan_credentials(source);sources[archive_name]=source
    verify.require(aliases==verify.ALIASES,'All three historical lock bytes must be preserved as inert aliases')
    rows=[{'path':name,'sha256':verify.sha(path),'bytes':path.stat().st_size} for name,path in sorted(sources.items())]
    manifest={'schema':verify.SCHEMA,'status':verify.STATUS,'created_at':datetime.now(timezone.utc).isoformat(),
        'freeze':{'path':verify.FREEZE,'sha256':freeze_sha256},'frozen_file_count':len(frozen['files']),
        'files':rows,'file_set_sha256':hashlib.sha256(verify.canonical(rows).encode()).hexdigest(),
        'frozen_aliases':aliases,'planned_slots':1800,'original_frozen_inference_available':False,
        'amended_sensitivity_available':True,'reproduction':reproduction,
        'human_review_complete':False,'submission_ready':False,
        'scope':'Recovered original schedule with two unanswered issued requests preserved as failed/full-reserved. Original k and m remain unclosed. The frozen diagnostic and separate recovery sensitivity are both included.'}
    for row in rows:
        path=sources[row['path']];verify.require(verify.sha(path)==row['sha256'] and path.stat().st_size==row['bytes'],'Source changed during assembly')
    return manifest,sources


def write_zip(output,manifest,sources):
    output=Path(output);verify.require(not output.exists(),'Never overwrite an archive')
    verify.require(manifest.get('schema')==verify.SCHEMA and manifest.get('status')==verify.STATUS,'Wrong archive branch')
    rows={r['path']:r for r in manifest['files']}
    verify.require(len(rows)==len(manifest['files']) and set(rows)==set(sources) and verify.MANIFEST_NAME not in rows,'Exact ZIP inventory')
    verify.require(len({n.casefold() for n in rows})==len(rows),'Case-colliding ZIP members')
    with ZipFile(output,'x',ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        for name,path in sorted(sources.items()):
            verify.safe_path(ROOT,name,exists=False);row=rows[name]
            verify.require(verify.sha(path)==row['sha256'] and Path(path).stat().st_size==row['bytes'],'ZIP source changed')
            archive.write(path,name)
        archive.writestr(verify.MANIFEST_NAME,json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with ZipFile(output) as archive:
        verify.require(archive.testzip() is None and len(archive.namelist())==len(rows)+1
            and set(archive.namelist())==set(rows)|{verify.MANIFEST_NAME},'ZIP integrity/membership')
        for name,row in rows.items():
            digest=hashlib.sha256();size=0
            with archive.open(name) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):size+=len(block);digest.update(block)
            verify.require(size==row['bytes'] and digest.hexdigest()==row['sha256'],'Decompressed member changed')
        verify.require(json.loads(archive.read(verify.MANIFEST_NAME))==manifest,'Embedded manifest changed')
    return {'path':str(output.resolve()),'sha256':verify.sha(output),'bytes':output.stat().st_size}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--freeze-sha256',required=True)
    p.add_argument('--include',action='append',default=[]);a=p.parse_args()
    archive=ROOT/TARGET;receipt=ROOT/MANIFEST_TARGET
    verify.require(not archive.exists() and not receipt.exists(),'Exclusive new release paths')
    manifest,sources=plan(ROOT,a.freeze_sha256,a.include)
    archive.parent.mkdir(parents=True,exist_ok=True)
    with receipt.open('x',encoding='utf-8',newline='\n') as f:json.dump(manifest,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps(write_zip(archive,manifest,sources),indent=2))


if __name__=='__main__':main()
