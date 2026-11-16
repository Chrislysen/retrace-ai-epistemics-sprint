"""Create an exclusive NEW-path overlay; never replace the base v6 artifact."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile,ZIP_DEFLATED

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.reproduce_frontier_v6h_release import canonical,load,require,safe_path,scan_credentials,sha
from scripts.reproduce_frontier_v6h_transport import (
    SCHEMA,BASE_ZIP_SHA,BASE_MANIFEST_SHA,PACED_FREEZE,PACED_FREEZE_SHA,PACED,QUOTA,
    SUPPLEMENT_MANIFEST,NEW_REQUIRED,base_manifest_from_zip,quota_replay,paced_semantic_replay,
)


def plan(root,base_zip):
    root=Path(root).resolve();base=base_manifest_from_zip(base_zip)
    base_names={r['path'] for r in base['files']};reverse={v:k for k,v in base['frozen_aliases'].items()}
    for entry in base['files']:
        original=reverse.get(entry['path'],entry['path'])
        require(sha(safe_path(root,original,allow_lock=True))==entry['sha256'],'Base workspace bytes changed')
    require(sha(root/PACED_FREEZE)==PACED_FREEZE_SHA,'Paced freeze changed')
    names=set(NEW_REQUIRED)
    for entry in load(root/PACED_FREEZE)['files']:
        name=entry['path'];require(sha(safe_path(root,name,allow_lock=True))==entry['sha256'],'Paced frozen dependency changed')
        if name=='deliverables/retrace-v6-sprint-artifact.zip':continue
        if base['frozen_aliases'].get(name,name) not in base_names:names.add(name)
    for folder in (PACED,QUOTA):
        names.update(p.relative_to(root).as_posix() for p in (root/folder).rglob('*') if p.is_file())
    require(not ({n.casefold() for n in names}&({n.casefold() for n in base_names}|{'release-manifest-v6h.json'})),'Overlay collides with base')
    require(SUPPLEMENT_MANIFEST not in names,'Reserved supplement manifest name')
    sources={name:safe_path(root,name) for name in sorted(names)};entries=[]
    for name,path in sources.items():
        scan_credentials(path);entries.append({'path':name,'sha256':sha(path),'bytes':path.stat().st_size})
    auditor=importlib.import_module('scripts.audit_frontier_v6h_paced_canary')
    audit=auditor.audit(root,base_archive=Path(base_zip))
    require(audit['passed'] and audit['final_closed'] and not audit['canary_dispatch_gate_passed'] and audit['primary_requests']==0,'Require closed failed gate with primary unissued')
    saved=load(root/PACED/'runtime-audit.json')
    require(all(saved.get(k)==v for k,v in audit.items()),'Independent audit replay differs')
    require(saved['auditor_source']['sha256']==sha(root/'scripts/audit_frontier_v6h_paced_canary.py'),'Auditor source changed')
    manifest={'schema':SCHEMA,'created_at':datetime.now(timezone.utc).isoformat(),
        'status':'closed_transport_diagnostics_primary_unissued','base_zip_sha256':BASE_ZIP_SHA,'base_manifest_sha256':BASE_MANIFEST_SHA,
        'files':entries,'file_set_sha256':hashlib.sha256(canonical(entries).encode()).hexdigest(),'base_files_changed':0,
        'primary_calls':0,'main_study_complete':False,'paced_runtime_checks':audit['checks'],
        'quota_replay':quota_replay(root),'paced_semantic_replay':paced_semantic_replay(root),
        'cumulative_accounted_credits':audit['cumulative_accounted_credits'],'actual_billed_credits':None,
        'scope':'Additive local transport diagnostic. No base artifact, failed attempt, frozen scientific input or eight-page paper is replaced. The main study remains unissued.',
        'limits':['Fifteen tiny serial calls do not establish a numeric service quota or capacity for long structured outputs.',
            'The paced canary repeats a previously observed development source under a prospectively frozen timing amendment; it is not a fresh scientific sample.',
            'The paced operational gate failed. No primary comparisons or successful large-study completion are claimed.',
            'Unknown rate-limit and timeout usage retains full reservations; conservative accounting is not provider billing.',
            'Extract only onto the pinned base artifact. This overlay contains new paths only; retain the original ZIP outside the extraction for verification.']}
    return manifest,sources


def write_zip(path,manifest,sources,base_names):
    path=Path(path);require(not path.exists(),'Refuse archive overwrite')
    entries={r['path']:r for r in manifest['files']}
    require(len(entries)==len(manifest['files']) and set(entries)==set(sources),'Overlay source inventory')
    require(not ({n.casefold() for n in entries}&{n.casefold() for n in base_names}),'Overlay base collision')
    require(SUPPLEMENT_MANIFEST not in entries and 'release-manifest-v6h.json' not in entries,'Reserved manifest collision')
    with ZipFile(path,'x',compression=ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        for name,source in sorted(sources.items()):
            require(sha(source)==entries[name]['sha256'] and source.stat().st_size==entries[name]['bytes'],'Source changed before assembly')
            archive.write(source,name)
        archive.writestr(SUPPLEMENT_MANIFEST,json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with ZipFile(path) as archive:
        require(archive.testzip() is None and len(archive.namelist())==len(set(archive.namelist())),'ZIP integrity/unique paths')
        require(set(archive.namelist())==set(entries)|{SUPPLEMENT_MANIFEST},'ZIP inventory')
        for name,entry in entries.items():
            h=hashlib.sha256();size=0
            with archive.open(name) as f:
                for block in iter(lambda:f.read(1024*1024),b''):h.update(block);size+=len(block)
            require(h.hexdigest()==entry['sha256'] and size==entry['bytes'],'Packaged member changed')
    return {'path':str(path.resolve()),'sha256':sha(path),'bytes':path.stat().st_size}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-zip',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--zip',type=Path,required=True);a=p.parse_args()
    require(not a.manifest.exists() and not a.zip.exists() and a.manifest.resolve()!=a.zip.resolve(),'Exclusive distinct outputs required')
    manifest,sources=plan(ROOT,a.base_zip)
    with a.manifest.open('x',encoding='utf-8',newline='\n') as f:json.dump(manifest,f,ensure_ascii=False,indent=2);f.write('\n')
    base=base_manifest_from_zip(a.base_zip)
    result=write_zip(a.zip,manifest,sources,{r['path'] for r in base['files']}|{'release-manifest-v6h.json'})
    print(json.dumps({'manifest':str(a.manifest.resolve()),'manifest_sha256':sha(a.manifest),'files':len(sources),'archive':result},indent=2))


if __name__=='__main__':main()
