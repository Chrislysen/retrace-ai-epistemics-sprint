"""Export all300 first attempts after authenticated closed four-segment replay.

Complete and interrupted catalogs have explicit separate branches. No API calls,
source truth labels, output repair, or selection by semantic outcome.
"""
import argparse
from hashlib import sha256
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from retrace.evidence_catalog_v6l import build_catalog,encode,require,DIRECTORY
from scripts.analyze_frontier_v6l_trajectory import authenticated_inputs,verify_saved
from scripts.score_frontier_v6l import (compute,safe,strict,binding,sha,INPUTS,OUTPUT,PARTIAL_OUTPUT,
    LEDGER,LOCK,verify_inventory,ALIASES)

PARTIAL_DIRECTORY='results/frontier-v6l/partial-catalog'
NOTICE=('INTERRUPTED STUDY. All300 planned first-attempt extraction slots remain visible. '
        'Unissued stop rows are censored, not observed model errors. No complete-study inference is available. ')
SOURCES=('scripts/export_frontier_v6l_catalog.py','retrace/evidence_catalog_v6l.py',
         'scripts/analyze_frontier_v6l_trajectory.py','scripts/score_frontier_v6l.py','retrace/source_ir_v6h.py')


def branch(diagnostic):
    require(type(diagnostic) is bool,'Explicit diagnostic selector required')
    return (PARTIAL_DIRECTORY,'interrupted_amended_diagnostic','retrace.evidence-catalog.v6l-partial.v1') if diagnostic else (
        DIRECTORY,'complete_amended_primary','retrace.evidence-catalog.v6l.v1')


def project(corpus,study,slots,audits,merged,*,diagnostic=False):
    directory,_,_=branch(diagnostic)
    value=build_catalog(corpus,study,slots,audits,merged)
    if not diagnostic:return value
    def moved(name):
        require(name.startswith(DIRECTORY+'/'),'Expected original catalog directory')
        return directory+name[len(DIRECTORY):]
    value['entries']={moved(name):entry for name,entry in value['entries'].items()}
    value['bundles']={moved(name):entry for name,entry in value['bundles'].items()}
    value['index']['scope']=NOTICE+value['index']['scope']
    for entry in value['entries'].values():
        entry['scope']=NOTICE+entry['scope']
        if entry['metadata']['status']=='not_issued':
            require(entry['metadata']['model_outcome']=='not_issued_global_stop'
                and entry['metadata']['attempt_id'] is None and entry['brief'] is None,
                'Independent extraction must remain an explicit stop-censored row')
    for row in value['index']['entries']:
        row['entry_path']=moved(row['entry_path'])
        row['entry_sha256']=sha256(encode(value['entries'][row['entry_path']])).hexdigest()
        if row['bundle_path'] is not None:row['bundle_path']=moved(row['bundle_path'])
    return value


def run(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,l_audit_sha256,
        ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None,diagnostic=False):
    directory,status,_=branch(diagnostic);root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    require(isinstance(freeze_sha256,str) and re.fullmatch(r'[a-f0-9]{64}',freeze_sha256),'Explicit l freeze digest required')
    require(not safe(root,directory).exists(),'Exclusive new catalog output required')
    require(not safe(root,LOCK).exists(),'Live continuation cannot be exported')
    saved=(PARTIAL_OUTPUT+'/partial-manifest.json') if diagnostic else (OUTPUT+'/composite-manifest.json')
    require(safe(root,saved).is_file(),'Saved authenticated closed composite required')
    code_before={name:binding(safe(root,name)) for name in SOURCES}
    args=(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,l_audit_sha256,ledger_snapshot,ledger_snapshot_sha256)
    if diagnostic:
        result,views=compute(*args,frozen_aliases=aliases,diagnostic=True)
        artifacts=verify_saved(root,result,views,aliases=aliases,ledger_snapshot=ledger_snapshot,diagnostic=True)
        evidence=result['summary']['file_evidence'];sources=dict(evidence['source_files'])
        for name,found in evidence['runtime_input_bindings'].items():
            name=ledger_snapshot if name==LEDGER else name
            require(name not in sources or sources[name]==found,'Contradictory source binding');sources[name]=found
        corpus=strict(safe(root,INPUTS['corpus']).read_bytes());study=strict(safe(root,INPUTS['study']).read_bytes())
    else:
        result,artifacts,sources,corpus,study=authenticated_inputs(*args,frozen_aliases=aliases)
    require(result['summary']['status']==status,'Explicit catalog closure branch required')
    for name in (INPUTS['corpus'],INPUTS['study'],INPUTS['sessions']):
        require(name in sources and binding(safe(root,name))==sources[name],'Frozen catalog input changed')
    slots=strict(safe(root,INPUTS['sessions']).read_bytes())
    catalog=project(corpus,study,slots,result['audits'],result['merged_evidence'],diagnostic=diagnostic)
    require(catalog['index']['scheduled_slots']==300 and not catalog['index']['test_fixture'],'All300 planned rows required')
    catalog['authentication']={'source_freeze_sha256':freeze_sha256,'authenticated_input_bindings':artifacts,
        'authenticated_source_bindings':sources,'exporter_source_bindings':code_before,'frozen_aliases':aliases,
        'study_status':status,'diagnostic':diagnostic}
    verify_plan(root,catalog['authentication'])
    return catalog


def verify_plan(root,auth):
    require(type(auth['diagnostic']) is bool and auth['study_status']==branch(auth['diagnostic'])[1],
        'Explicit matching catalog branch required')
    require(not safe(root,LOCK).exists(),'Live continuation cannot be published')
    require(auth['frozen_aliases'] in ({},ALIASES),'Unsupported aliases')
    verify_inventory(root,auth['source_freeze_sha256'],auth['frozen_aliases'])
    require(set(auth['exporter_source_bindings'])==set(SOURCES),'Exact exporter source inventory required')
    for role in ('authenticated_input_bindings','authenticated_source_bindings','exporter_source_bindings'):
        for name,expected in auth[role].items():
            require(binding(safe(root,auth['frozen_aliases'].get(name,name)))==expected,
                'Source or exporter changed before catalog publication')


def write_catalog(root,catalog,*,diagnostic=False):
    directory_name,status,schema=branch(diagnostic);root=Path(root).resolve();directory=safe(root,directory_name)
    require(not directory.exists(),'Exclusive new catalog output required')
    auth=catalog['authentication'];index=catalog['index']
    require(auth['diagnostic'] is diagnostic and auth['study_status']==status and index['scheduled_slots']==300
        and index['selection_view']=='first_attempt' and index['test_fixture'] is False
        and len(index['entries'])==len(catalog['entries'])==300,'Authenticated all300 catalog required')
    if diagnostic:require(index['scope'].startswith(NOTICE),'Interrupted scope must remain explicit')
    payloads={directory_name+'/index.json':encode(index)}
    payloads.update({name:encode(value) for name,value in catalog['entries'].items()})
    payloads.update({name:encode(value) for name,value in catalog['bundles'].items()})
    required={directory_name+'/index.json'}
    for row in index['entries']:
        name=directory_name+'/entries/'+row['key']+'.json'
        require(row['entry_path']==name and sha256(payloads[name]).hexdigest()==row['entry_sha256'],'Entry/index binding')
        required.add(name)
        if row['bundle_path'] is not None:
            name=directory_name+'/bundles/'+row['key']+'.json'
            require(row['bundle_path']==name and sha256(payloads[name]).hexdigest()==row['bundle_sha256'],'Bundle/index binding')
            required.add(name)
    require(set(payloads)==required,'Exact catalog member inventory required')
    for name in payloads:require(safe(root,name).is_relative_to(directory),'Catalog member escaped directory')
    manifest={'schema':schema,'status':status,'schedule_complete':not diagnostic,'inference_available':not diagnostic,
        'scheduled_slots':300,'selection_view':'first_attempt','index_path':directory_name+'/index.json',
        'files':{name:{'sha256':sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in payloads.items()},
        **auth,'scope':index['scope']}
    verify_plan(root,auth);directory.mkdir(parents=True,exist_ok=False)
    for name,raw in payloads.items():
        target=safe(root,name);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(raw)
    verify_plan(root,auth)
    with (directory/'manifest.json').open('xb') as stream:stream.write(encode(manifest))
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','i-audit-sha256','j-audit-sha256','k-audit-sha256','l-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--aliases',type=Path);parser.add_argument('--diagnostic',action='store_true');args=parser.parse_args()
    aliases=strict(args.aliases.read_bytes()) if args.aliases else {}
    value=run(args.root,args.freeze_sha256,args.i_audit_sha256,args.j_audit_sha256,args.k_audit_sha256,args.l_audit_sha256,
        args.ledger_snapshot,args.ledger_snapshot_sha256,frozen_aliases=aliases,diagnostic=args.diagnostic)
    manifest=write_catalog(args.root,value,diagnostic=args.diagnostic)
    print({'status':manifest['status'],'scheduled_slots':300,'output':branch(args.diagnostic)[0],'counts':value['index']['counts']})


if __name__=='__main__':main()
