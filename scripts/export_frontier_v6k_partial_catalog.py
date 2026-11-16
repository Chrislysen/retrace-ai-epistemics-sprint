"""Export all300 planned extraction slots from a CLOSED interrupted study.

Separate output/schema from the complete-study catalog. No inference or repair.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import score_frontier_v6k_partial as partial
from scripts import score_frontier_v6k as full
from retrace.evidence_catalog_v6k import build_catalog,encode,DIRECTORY as COMPLETE_DIRECTORY,FREEZE_SHA256,require

DIRECTORY='results/frontier-v6k/partial-catalog'
SCHEMA='retrace.evidence-catalog.v6k-partial.v1'
STATUS=partial.STATUS
NOTICE=('INTERRUPTED STUDY. All300 planned first-attempt extraction slots remain visible. '
        'Unissued stop rows are censored, not observed model errors. No complete-study inference is available. ')
SOURCES=('scripts/export_frontier_v6k_partial_catalog.py','retrace/evidence_catalog_v6k.py',
         'scripts/score_frontier_v6k_partial.py','retrace/frontier_v6k_partial.py','retrace/source_ir_v6h.py')


def verify_saved(root,result,views,aliases):
    """Require the exact saved diagnostic, not a merely plausible manifest."""
    base=partial.OUTPUT; path=full.safe(root,base+'/partial-manifest.json')
    manifest=full.strict(path.read_bytes())
    require(manifest['schema']=='retrace.frontier-v6k-partial-artifacts.v1'
            and manifest['status']==STATUS and manifest['planned_slots']==1800
            and manifest['schedule_complete'] is False and manifest['inference_available'] is False
            and manifest['source_rows_changed'] is False and manifest['selected_jsonl_source_bytes_preserved'] is True,
            'Closed interrupted diagnostic manifest required')
    objects={'score.json':result['summary'],'score-audits.json':result['audits'],
             'source-provenance.json':result['merged_evidence']['source_provenance'],
             'interrupted-closure.json':result['summary']['operational_summary']}
    names=set(objects)|{'requests.jsonl','responses.jsonl','slot-outcomes.jsonl','report-facts.md'}
    require(set(manifest['files'])=={base+'/'+n for n in names},'Exact eight-file partial inventory required')
    bindings={base+'/partial-manifest.json':full.binding(path)}
    for name,expected in manifest['files'].items():
        require(full.binding(full.safe(root,name))==expected,'Saved partial artifact changed');bindings[name]=expected
    for name,value in objects.items():
        saved=full.strict(full.safe(root,base+'/'+name).read_bytes());expected=deepcopy(value)
        if name=='score.json':
            a=saved.pop('file_evidence');b=expected.pop('file_evidence')
            require(a==manifest['file_evidence'] and a['frozen_aliases'] in ({},full.ALIASES), 'Saved partial source evidence differs')
            a=deepcopy(a);a['frozen_aliases']=aliases
            require(a==b,'Saved and replayed partial source evidence differ')
        require(saved==expected,'Saved partial object differs from replay')
    for role,name in (('requests','requests.jsonl'),('responses','responses.jsonl'),('outcomes','slot-outcomes.jsonl')):
        require(full.safe(root,base+'/'+name).read_bytes()==views[role],'Saved partial raw-line view changed')
    require(full.safe(root,base+'/report-facts.md').read_bytes()==partial.report_facts(result['summary']).encode('utf-8'),
            'Saved partial factual source differs')
    require(manifest['source_bindings']==result['merged_evidence']['source_bindings']
            and manifest['writer_sha256']==full.sha(full.safe(root,'scripts/score_frontier_v6k_partial.py')),
            'Saved partial source/writer binding differs')
    return bindings


def project(corpus,study,slots,audits,merged):
    """Same public-only first attempts; distinct directory and persistent scope."""
    catalog=build_catalog(corpus,study,slots,audits,merged)
    def moved(name):
        require(name.startswith(COMPLETE_DIRECTORY+'/'),'Expected original public catalog path')
        return DIRECTORY+name[len(COMPLETE_DIRECTORY):]
    catalog['entries']={moved(name):value for name,value in catalog['entries'].items()}
    catalog['bundles']={moved(name):value for name,value in catalog['bundles'].items()}
    catalog['index']['scope']=NOTICE+catalog['index']['scope']
    for entry in catalog['entries'].values():
        entry['scope']=NOTICE+entry['scope']
        if entry['metadata']['status']=='not_issued':
            require(entry['metadata']['model_outcome']=='not_issued_global_stop'
                    and entry['metadata']['attempt_id'] is None and entry['brief'] is None,
                    'Unissued independent extraction must remain an explicit stop-censored row')
    for row in catalog['index']['entries']:
        row['entry_path']=moved(row['entry_path'])
        row['entry_sha256']=sha256(encode(catalog['entries'][row['entry_path']])).hexdigest()
        if row['bundle_path'] is not None:row['bundle_path']=moved(row['bundle_path'])
    return catalog


def run(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,
        ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    require(freeze_sha256==FREEZE_SHA256,'Pinned execution freeze required')
    require(not full.safe(root,DIRECTORY).exists(),'Exclusive partial catalog output required')
    require(not full.safe(root,'results/frontier-v6k/budget/active.lock').exists(),'Live study cannot be exported')
    before={name:full.binding(full.safe(root,name)) for name in SOURCES}
    result,views=partial.compute(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,
        ledger_snapshot,ledger_snapshot_sha256,frozen_aliases=aliases)
    artifacts=verify_saved(root,result,views,aliases)
    data={name:full.strict(full.safe(root,full.INPUTS[name]).read_bytes()) for name in ('corpus','study','sessions')}
    catalog=project(data['corpus'],data['study'],data['sessions'],result['audits'],result['merged_evidence'])
    evidence=result['summary']['file_evidence']
    sources={**evidence['source_files'],**evidence['runtime_input_bindings']}
    require(full.binding(full.safe(root,full.LEDGER))==full.binding(full.safe(root,ledger_snapshot)),
            'Canonical closed ledger and immutable snapshot must agree')
    catalog['authentication']={'source_freeze_sha256':freeze_sha256,'authenticated_input_bindings':artifacts,
        'authenticated_source_bindings':sources,'exporter_source_bindings':before,'frozen_aliases':aliases}
    verify_plan(root,catalog['authentication'])
    return catalog


def verify_plan(root,auth):
    require(auth['source_freeze_sha256']==FREEZE_SHA256 and set(auth['exporter_source_bindings'])==set(SOURCES),
            'Exact diagnostic source inventory required')
    require(not full.safe(root,'results/frontier-v6k/budget/active.lock').exists(),'Live study cannot be published')
    aliases=auth['frozen_aliases'];full.verify_inventory(root,FREEZE_SHA256,aliases)
    for role in ('authenticated_input_bindings','authenticated_source_bindings','exporter_source_bindings'):
        for name,expected in auth[role].items():
            require(full.binding(full.safe(root,aliases.get(name,name)))==expected,'Diagnostic catalog source changed')


def write_catalog(root,catalog):
    root=Path(root).resolve();directory=full.safe(root,DIRECTORY);index=catalog['index'];auth=catalog['authentication']
    require(not directory.exists(),'Exclusive partial catalog output required')
    require(index['scheduled_slots']==300 and index['selection_view']=='first_attempt' and index['test_fixture'] is False
            and len(index['entries'])==len(catalog['entries'])==300 and index['scope'].startswith(NOTICE),
            'All300 interrupted-study rows and explicit censoring scope required')
    payloads={DIRECTORY+'/index.json':encode(index)}
    payloads.update({name:encode(value) for name,value in catalog['entries'].items()})
    payloads.update({name:encode(value) for name,value in catalog['bundles'].items()})
    required={DIRECTORY+'/index.json'}
    for row in index['entries']:
        path=DIRECTORY+'/entries/'+row['key']+'.json'
        require(row['entry_path']==path and sha256(payloads[path]).hexdigest()==row['entry_sha256'],'Entry/index binding')
        required.add(path)
        if row['bundle_path'] is not None:
            name=DIRECTORY+'/bundles/'+row['key']+'.json'
            require(row['bundle_path']==name and sha256(payloads[name]).hexdigest()==row['bundle_sha256'],'Bundle/index binding')
            required.add(name)
    require(set(payloads)==required,'Exact diagnostic catalog inventory required')
    for name in payloads:require(full.safe(root,name).is_relative_to(directory),'Diagnostic member escaped its directory')
    manifest={'schema':SCHEMA,'status':STATUS,'schedule_complete':False,'inference_available':False,
        'scheduled_slots':300,'selection_view':'first_attempt','index_path':DIRECTORY+'/index.json',
        'files':{name:{'sha256':sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in payloads.items()},
        **auth,'scope':index['scope']}
    verify_plan(root,auth);directory.mkdir(parents=True,exist_ok=False)
    for name,raw in payloads.items():
        target=full.safe(root,name);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(raw)
    verify_plan(root,auth)
    with (directory/'manifest.json').open('xb') as stream:stream.write(encode(manifest))
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','i-audit-sha256','j-audit-sha256','k-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--aliases',type=Path);a=p.parse_args();aliases=full.strict(a.aliases.read_bytes()) if a.aliases else {}
    catalog=run(a.root,a.freeze_sha256,a.i_audit_sha256,a.j_audit_sha256,a.k_audit_sha256,
        a.ledger_snapshot,a.ledger_snapshot_sha256,frozen_aliases=aliases)
    manifest=write_catalog(a.root,catalog)
    print(full.json.dumps({'status':manifest['status'],'scheduled_slots':300,'output':DIRECTORY,'counts':catalog['index']['counts']}))


if __name__=='__main__':main()
