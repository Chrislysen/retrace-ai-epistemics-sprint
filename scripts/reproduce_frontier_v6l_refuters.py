"""Shared reference-free controlled-seed catalog verification for explicit branches.

No provider calls, gold-family substitution, output repair, or mutable import
globals. A caller may pass only an already-authenticated composite result.
"""
from pathlib import Path
from scripts.reproduce_frontier_v6h_release import load, require, safe_path, sha

LOCK = 'results/frontier-v6f/budget/active.lock'
LOCK_ALIAS = 'provenance/frozen-locks/'+LOCK+'.txt'
LEDGER = 'results/frontier-v6l/budget/ledger.jsonl'
SNAPSHOT = 'data/frontier-v6l-ledger-after-continuation.jsonl'
DATA = {'corpus':'data/frontier-v6h-corpus.json','study':'data/frontier-v6i-design.json',
        'sessions':'data/frontier-v6i-sessions.json'}


def binding(root, name):
    path=safe_path(root,name)
    return {'sha256':sha(path),'bytes':path.stat().st_size}


def refuter_catalog_files(root, aliases=None, *, freeze_sha256, result=None, diagnostic=False):
    from retrace.refuter_reader_v6l import RefuterCatalog
    from retrace.refuter_catalog_v6l import encode
    from scripts.export_frontier_v6l_refuters import SOURCES, project, branch
    root=Path(root).resolve();aliases=dict(aliases or {})
    require(type(diagnostic) is bool and aliases in ({},{LOCK:LOCK_ALIAS}), 'Explicit branch and sole inert alias required')
    directory,status,schema=branch(diagnostic)
    prefix='results/frontier-v6l/'+('partial-diagnostic' if diagnostic else 'composite')
    score=prefix+'/score.json';manifest_path=directory+'/manifest.json'
    closure='interrupted-closure.json' if diagnostic else 'derived-closure.json'
    composite_manifest='partial-manifest.json' if diagnostic else 'composite-manifest.json'
    artifacts={prefix+'/'+name for name in ('score.json','score-audits.json','source-provenance.json',
        'requests.jsonl','responses.jsonl','slot-outcomes.jsonl',closure,composite_manifest)}
    manifest=load(safe_path(root,manifest_path))
    require(manifest.get('schema')==schema and manifest.get('status')==status
        and manifest.get('diagnostic') is diagnostic and manifest.get('study_status')==status
        and manifest.get('schedule_complete') is (not diagnostic)
        and manifest.get('inference_available') is (not diagnostic), 'Explicit controlled-seed catalog branch required')
    reader=RefuterCatalog(root,expected_manifest_sha256=sha(safe_path(root,manifest_path)),
        expected_freeze_sha256=freeze_sha256,diagnostic=diagnostic)
    index=reader.index()
    require(index.get('available') is True, 'Recorded all300 controlled-seed catalog required')
    require(manifest.get('authenticated_input_bindings')=={n:binding(root,n) for n in artifacts},
        'Refuter catalog binds a different authenticated composite')
    evidence=load(safe_path(root,score))['file_evidence']
    sources=dict(evidence['source_files'])
    for name,value in evidence['runtime_input_bindings'].items():
        name=SNAPSHOT if name==LEDGER else name
        require(name not in sources or sources[name]==value,'Contradictory controlled-seed source binding')
        sources[name]=value
    require(manifest.get('authenticated_source_bindings')==sources,'Controlled-seed source inventory differs from authenticated score')
    require(manifest.get('frozen_aliases') in ({},{LOCK:LOCK_ALIAS}),'Unknown controlled-seed relocation alias')
    for name,value in sources.items():
        require(binding(root,aliases.get(name,name))==value,'Controlled-seed raw/source evidence changed')
    require(manifest.get('exporter_source_bindings')=={n:binding(root,n) for n in SOURCES},'Controlled-seed exporter code changed')
    require(len(manifest['files'])==301,'All300 entries plus index required')
    for name,value in manifest['files'].items():
        require(binding(root,name)==value,'Controlled-seed member changed')
    if result is not None:
        rebuilt=project(load(safe_path(root,DATA['corpus'])),load(safe_path(root,DATA['study'])),
            load(safe_path(root,DATA['sessions'])),result['audits'],result['merged_evidence'],diagnostic=diagnostic)
        require(rebuilt['bundles']=={},'Controlled seeds must never become source-IR bundles')
        payloads={directory+'/index.json':encode(rebuilt['index'])}
        payloads.update({name:encode(value) for name,value in rebuilt['entries'].items()})
        require(len(rebuilt['entries'])==300 and set(payloads)==set(manifest['files']), 'Exact rebuilt all300 refuter inventory required')
        for name,raw in payloads.items():
            require(safe_path(root,name).read_bytes()==raw,'Controlled-seed catalog differs from original first-attempt replay: '+name)
    return {manifest_path,*manifest['files']}, {
        'manifest_path':manifest_path,'manifest_sha256':sha(safe_path(root,manifest_path)),
        'index_sha256':sha(safe_path(root,directory+'/index.json')),'scheduled_slots':300,
        'catalog_payload_members':301,'selection_view':'first_attempt','study_status':status,
        'source_freeze_sha256':freeze_sha256,'recomputed_from_authenticated_first_attempts':result is not None,
        'scope':'Controlled authored-seed inspection, not natural upstream consensus, source truth, or an added scientific endpoint.'}
