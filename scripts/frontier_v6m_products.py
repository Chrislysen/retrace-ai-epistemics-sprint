"""Post-closure product authentication; no network, output repair or source gold.

The two scientific views remain separate. Catalogs show all first attempts and
do not turn amended schedule accounting into an entailment certificate.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import score_frontier_v6m as score
from retrace.frontier_v6j_eval import json_value,require,_strict as strict
from retrace import evidence_catalog_v6m as evidence
from retrace import refuter_catalog_v6m as refuters

KINDS=('catalog','refuter-catalog')
COMPLETE_NOTICE=('HOST-RECOVERED STUDY. The original frozen closure remains diagnostic. '
    'A separate amended recovered-complete sensitivity does not replace it. '
    'All planned first-attempt observations are retained; source entailment and completeness remain unverified. ')
PARTIAL_NOTICE=('INTERRUPTED STUDY. The recovered schedule did not complete. '
    'Original frozen diagnostics remain separate and no amended recovered-complete sensitivity is available. '
    'All planned first-attempt observations remain visible; unissued rows are censored. ')
SHARED_SOURCES=('scripts/frontier_v6m_products.py','scripts/score_frontier_v6m.py',
    'retrace/frontier_v6m_eval.py','retrace/source_ir_v6h.py')
SOURCES={
    'catalog':SHARED_SOURCES+('scripts/export_frontier_v6m_catalog.py','retrace/evidence_catalog_v6m.py'),
    'refuter-catalog':SHARED_SOURCES+('scripts/export_frontier_v6m_refuters.py','retrace/refuter_catalog_v6m.py',
        'retrace/evidence_catalog_v6m.py','retrace/refuter_inspector_v6l.py','retrace/refuter_gate_v6h.py','retrace/impact_v6h.py')}


def branch(kind,diagnostic):
    require(kind in KINDS and type(diagnostic) is bool,'Explicit product kind and closure branch')
    directory='results/frontier-v6m/'+('partial-' if diagnostic else '')+kind
    label='evidence' if kind=='catalog' else 'controlled-refuter'
    return directory,score.PARTIAL if diagnostic else score.COMPLETE,


def schema(kind,diagnostic):
    label='evidence' if kind=='catalog' else 'controlled-refuter'
    return 'retrace.'+label+'-catalog.v6m'+('-partial' if diagnostic else '')+'.v1'


def verify_saved(root,result,views,*,aliases,ledger_snapshot,diagnostic=False):
    root=Path(root).resolve();output=score.PARTIAL_OUTPUT if diagnostic else score.OUTPUT
    status=score.PARTIAL if diagnostic else score.COMPLETE
    require(result['summary']['status']==status,'Matching recovered result branch')
    manifest_path=output+'/composite-manifest.json';manifest=strict(score.safe(root,manifest_path).read_bytes())
    require(manifest.get('schema')=='retrace.frontier-v6m-composite-artifacts.v1'
            and manifest.get('status')==status,'Recovered composite manifest branch')
    names={output+'/'+name for name in ('score.json','score-audits.json','requests.jsonl','responses.jsonl',
        'slot-outcomes.jsonl','source-provenance.json','recovered-closure.json')}
    inventory={row['path']:{'sha256':row['sha256'],'bytes':row['bytes']} for row in manifest['files']}
    require(len(inventory)==len(manifest['files'])==7 and set(inventory)==names,'Exact seven-file recovered composite')
    artifacts={manifest_path:score.binding(score.safe(root,manifest_path))}
    for name,wanted in inventory.items():
        require(score.binding(score.safe(root,name))==wanted,'Changed saved composite');artifacts[name]=wanted
    saved=strict(score.safe(root,output+'/score.json').read_bytes());replay=json_value(result['summary'])
    saved_evidence=saved.pop('file_evidence');replay_evidence=replay.pop('file_evidence')
    require(saved==replay,'Both saved scientific views must exactly reproduce')
    normalized=deepcopy(saved_evidence)
    normalized['source_files']={ledger_snapshot if n==saved_evidence['ledger_snapshot']['path'] else n:v
        for n,v in saved_evidence['source_files'].items()}
    require(len(normalized['source_files'])==len(saved_evidence['source_files']),'Snapshot normalization collision')
    normalized['ledger_snapshot']['path']=ledger_snapshot;normalized['frozen_aliases']=aliases
    require(normalized==replay_evidence,'Full saved evidence binding differs')
    require(all(score.ALIASES.get(k)==v for k,v in saved_evidence['frozen_aliases'].items())
            and all(score.ALIASES.get(k)==v for k,v in aliases.items()),'Exact historical aliases only')
    writer='scripts/score_frontier_v6m.py'
    require(manifest['writer_sha256']==replay_evidence['runtime_input_bindings'][writer]['sha256'],
            'Writer must match frozen independent runtime inventory')
    require(manifest['source_bindings']==saved_evidence['source_files']
            and manifest['runtime_input_bindings']==saved_evidence['runtime_input_bindings'],
            'Composite manifest source inventories differ')
    objects={'score-audits.json':result['audits'],'source-provenance.json':result['merged_evidence']['source_provenance'],
        'recovered-closure.json':result['summary']['operational_summary']}
    for name,value in objects.items():
        require(strict(score.safe(root,output+'/'+name).read_bytes())==json_value(value),'Saved audit/provenance/closure differs')
    for role,name in (('requests','requests.jsonl'),('responses','responses.jsonl'),('outcomes','slot-outcomes.jsonl')):
        require(score.safe(root,output+'/'+name).read_bytes()==views[role],'Saved raw source lines differ')
    return artifacts


def authenticated(root,freeze_sha256,prefix_proof_sha256,m_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,
                  *,frozen_aliases=None,diagnostic=False):
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    require(not score.safe(root,score.LOCK).exists(),'Active recovery worker cannot be exported')
    output=score.PARTIAL_OUTPUT if diagnostic else score.OUTPUT
    require(score.safe(root,output+'/composite-manifest.json').is_file(),'Saved final authenticated composite required')
    result,views=score.compute(root,freeze_sha256,prefix_proof_sha256,m_audit_sha256,ledger_snapshot,
        ledger_snapshot_sha256,frozen_aliases=aliases,diagnostic=diagnostic)
    artifacts=verify_saved(root,result,views,aliases=aliases,ledger_snapshot=ledger_snapshot,diagnostic=diagnostic)
    ev=result['summary']['file_evidence'];sources=dict(ev['source_files'])
    for name,found in ev['runtime_input_bindings'].items():
        name=ledger_snapshot if name==score.LEDGER else name
        require(name not in sources or sources[name]==found,'Contradictory raw/SSE source binding');sources[name]=found
    data={key:strict(score.safe(root,score.INPUTS[key]).read_bytes()) for key in ('corpus','study','sessions')}
    for key in data:
        name=score.INPUTS[key];require(score.binding(score.safe(root,name))==sources[name],'Frozen product input changed')
    return result,artifacts,sources,data


def project(kind,corpus,study,slots,audits,merged,*,diagnostic=False):
    directory,_=branch(kind,diagnostic);builder=evidence if kind=='catalog' else refuters
    value=builder.build_catalog(corpus,study,slots,audits,merged)
    notice=PARTIAL_NOTICE if diagnostic else COMPLETE_NOTICE
    value['index']['scope']=notice+value['index']['scope']
    old=builder.DIRECTORY
    def moved(name):
        require(name.startswith(old+'/'),'Canonical projection member');return directory+name[len(old):]
    value['entries']={moved(name):entry for name,entry in value['entries'].items()}
    value['bundles']={moved(name):entry for name,entry in value['bundles'].items()}
    for row in value['index']['entries']:
        row['entry_path']=moved(row['entry_path'])
        row['entry_sha256']=sha256(builder.encode(value['entries'][row['entry_path']])).hexdigest()
        if row.get('bundle_path') is not None:row['bundle_path']=moved(row['bundle_path'])
    require(value['index']['scheduled_slots']==300 and len(value['entries'])==300 and not value['index']['test_fixture'],
            'All300 original primary first attempts required')
    if kind=='refuter-catalog':require(value['bundles']=={},'Controlled seeds cannot become source IR')
    return value


def verify_plan(root,auth,kind):
    _,status=branch(kind,auth['diagnostic']);aliases=auth['frozen_aliases']
    require(auth['study_status']==status and all(score.ALIASES.get(k)==v for k,v in aliases.items()),'Product branch/aliases')
    require(not score.safe(root,score.LOCK).exists(),'Active recovery worker cannot publish')
    score.verify_inventory(root,auth['source_freeze_sha256'],aliases)
    require(set(auth['exporter_source_bindings'])==set(SOURCES[kind]),'Exact product projection source inventory')
    for role in ('authenticated_input_bindings','authenticated_source_bindings','exporter_source_bindings'):
        for name,wanted in auth[role].items():
            require(score.binding(score.safe(root,aliases.get(name,name)))==wanted,'Product input/source changed')


def run(kind,root,freeze_sha256,prefix_proof_sha256,m_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,
        *,frozen_aliases=None,diagnostic=False):
    root=Path(root).resolve();directory,status=branch(kind,diagnostic)
    require(not score.safe(root,directory).exists(),'Exclusive new product directory required')
    code={name:score.binding(score.safe(root,name)) for name in SOURCES[kind]}
    result,artifacts,sources,data=authenticated(root,freeze_sha256,prefix_proof_sha256,m_audit_sha256,
        ledger_snapshot,ledger_snapshot_sha256,frozen_aliases=frozen_aliases,diagnostic=diagnostic)
    value=project(kind,data['corpus'],data['study'],data['sessions'],result['audits'],result['merged_evidence'],diagnostic=diagnostic)
    value['authentication']={'source_freeze_sha256':freeze_sha256,'authenticated_input_bindings':artifacts,
        'authenticated_source_bindings':sources,'exporter_source_bindings':code,'frozen_aliases':dict(frozen_aliases or {}),
        'study_status':status,'diagnostic':diagnostic,'replay_arguments':{'freeze_sha256':freeze_sha256,
            'prefix_proof_sha256':prefix_proof_sha256,'m_audit_sha256':m_audit_sha256,
            'ledger_snapshot':ledger_snapshot,'ledger_snapshot_sha256':ledger_snapshot_sha256}}
    verify_plan(root,value['authentication'],kind);return value


def payloads(kind,value,diagnostic):
    directory,_=branch(kind,diagnostic);encode=evidence.encode
    result={directory+'/index.json':encode(value['index'])}
    result.update({name:encode(entry) for name,entry in value['entries'].items()})
    result.update({name:encode(bundle) for name,bundle in value['bundles'].items()})
    required={directory+'/index.json'}
    for row in value['index']['entries']:
        name=directory+'/entries/'+row['key']+'.json'
        require(row['entry_path']==name and sha256(result[name]).hexdigest()==row['entry_sha256'],'Exact index/entry binding')
        required.add(name)
        if row.get('bundle_path') is not None:
            name=directory+'/bundles/'+row['key']+'.json'
            require(row['bundle_path']==name and sha256(result[name]).hexdigest()==row['bundle_sha256'],'Exact bundle binding')
            required.add(name)
    require(set(result)==required,'Exact public catalog inventory')
    return result


def write_catalog(kind,root,value,*,diagnostic=False):
    root=Path(root).resolve();directory,status=branch(kind,diagnostic);target=score.safe(root,directory)
    require(not target.exists(),'Exclusive new catalog directory required')
    auth=value['authentication'];require(auth['diagnostic'] is diagnostic and auth['study_status']==status,'Exact publication branch')
    index=value['index'];require(index['scheduled_slots']==len(index['entries'])==len(value['entries'])==300
        and index['test_fixture'] is False and index['selection_view']=='first_attempt','No selected/invented subset')
    raw=payloads(kind,value,diagnostic)
    for name in raw:require(score.safe(root,name).is_relative_to(target),'Member escaped catalog')
    manifest={'schema':schema(kind,diagnostic),'status':status,'schedule_complete':not diagnostic,
        'inference_available':False,'amended_sensitivity_available':not diagnostic,'scientific_segments':['i','j','k-prefix','m'],
        'scheduled_slots':300,'selection_view':'first_attempt','index_path':directory+'/index.json',
        'files':{name:{'sha256':sha256(data).hexdigest(),'bytes':len(data)} for name,data in raw.items()},
        **auth,'scope':index['scope']}
    verify_plan(root,auth,kind);target.mkdir(parents=True,exist_ok=False)
    for name,data in raw.items():
        path=score.safe(root,name);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(data)
    verify_plan(root,auth,kind)
    with (target/'manifest.json').open('xb') as stream:stream.write(evidence.encode(manifest))
    return manifest


def export_main(kind):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','prefix-proof-sha256','m-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--aliases',type=Path);p.add_argument('--diagnostic',action='store_true');a=p.parse_args()
    aliases=strict(a.aliases.read_bytes()) if a.aliases else {}
    value=run(kind,a.root,a.freeze_sha256,a.prefix_proof_sha256,a.m_audit_sha256,a.ledger_snapshot,
        a.ledger_snapshot_sha256,frozen_aliases=aliases,diagnostic=a.diagnostic)
    manifest=write_catalog(kind,a.root,value,diagnostic=a.diagnostic)
    print(json.dumps({'status':manifest['status'],'scheduled_slots':300,'directory':branch(kind,a.diagnostic)[0]}))
