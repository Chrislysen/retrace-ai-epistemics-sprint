"""Authenticate four closed segments; publish separate complete/diagnostic views.

Offline only. No API calls, journal edits or automatic fallback to completion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from retrace.frontier_v6l_eval import (evaluate_composite, json_value, SEGMENTS, HISTORICAL,
    role_paths, receipt_counts, diagnostic_only, COMPLETE, PARTIAL)
from scripts.score_frontier_v6j import safe, strict, sha, binding, import_closure, selected_source_lines, ALIASES

FREEZE = 'data/frontier-v6l-freeze.json'
OUTPUT = 'results/frontier-v6l/composite'
PARTIAL_OUTPUT = 'results/frontier-v6l/partial-diagnostic'
INPUTS = {'corpus':'data/frontier-v6h-corpus.json','dossiers':'data/frontier-v6h-dossiers.json',
          'study':'data/frontier-v6i-design.json','sessions':'data/frontier-v6i-sessions.json',
          'receipt':'data/frontier-v6l-continuation.json'}
AUDITS = {n:role_paths(n)['summary'].removesuffix('summary.json')+'runtime-audit.json' for n in SEGMENTS}
LEDGER = 'results/frontier-v6l/budget/ledger.jsonl'
LOCK = 'results/frontier-v6l/budget/active.lock'


def require(ok, why):
    if not ok: raise ValueError(why)


def audit_runtime(*args, **kwargs):
    from scripts.audit_frontier_v6l_runtime import audit
    return audit(*args, **kwargs)


def verify_inventory(root, expected_sha, aliases):
    require(aliases in ({},ALIASES), 'unsupported_frozen_alias')
    path = safe(root,FREEZE); require(sha(path) == expected_sha, 'execution_freeze_hash')
    freeze = strict(path.read_bytes())
    require(freeze.get('schema') == 'retrace.frontier-v6l-freeze.v1' and freeze.get('scheduled_slots') == 1800,
            'prospective_l_freeze_schema_and_plan')
    carried, issued, remaining = (freeze.get(k) for k in ('carried_final_slots','carried_issued_slots','continuation_slots'))
    require(all(type(n) is int for n in (carried,issued,remaining)) and 224 <= carried < 1800
            and 213 <= issued <= carried and remaining == 1800-carried, 'dynamic_freeze_counts')
    inventory = {}
    for row in freeze['files']:
        name = row['path']; require(name not in inventory, 'duplicate_frozen_path')
        value = {'sha256':row['sha256'],'bytes':row['bytes']}
        require(binding(safe(root,aliases.get(name,name))) == value, 'frozen_dependency_changed: '+name)
        inventory[name] = value
    required = set(INPUTS.values()) | import_closure(root,[
        'scripts/score_frontier_v6l.py','retrace/frontier_v6l_eval.py','scripts/audit_frontier_v6l_runtime.py'])
    require(required <= set(inventory) and set(aliases) <= set(inventory), 'missing_scientific_dependency')
    return freeze,inventory


def segment(root, name):
    paths = role_paths(name); raw = {role:safe(root,path).read_bytes() for role,path in paths.items()}
    return {'paths':paths,**{role:raw[role] for role in ('requests','responses','outcomes')},
            'summary_bytes':raw['summary'],'manifest_bytes':raw['run_manifest'],
            'summary':strict(raw['summary']),'manifest':strict(raw['run_manifest'])}


def compute(root, freeze_sha256, i_audit_sha256, j_audit_sha256, k_audit_sha256, l_audit_sha256,
            ledger_snapshot, ledger_snapshot_sha256, *, frozen_aliases=None, diagnostic=False):
    require(type(diagnostic) is bool, 'explicit_diagnostic_selector')
    root = Path(root).resolve(); aliases = dict(frozen_aliases or {})
    require(not safe(root,LOCK).exists(), 'continuation_still_active')
    freeze,_ = verify_inventory(root,freeze_sha256,aliases)
    require(ledger_snapshot != LEDGER, 'immutable_ledger_snapshot_required')
    snapshot = safe(root,ledger_snapshot); require(sha(snapshot) == ledger_snapshot_sha256, 'ledger_snapshot_hash')
    before = {name:binding(safe(root,name)) for name in set(INPUTS.values())|set(AUDITS.values())|{ledger_snapshot,FREEZE}}
    hashes = dict(zip(SEGMENTS,(i_audit_sha256,j_audit_sha256,k_audit_sha256,l_audit_sha256)))
    saved = {}
    for name,path in AUDITS.items():
        require(before[path]['sha256'] == hashes[name], 'saved_runtime_audit_hash')
        saved[name] = strict(safe(root,path).read_bytes())
    actual = json_value(audit_runtime(root,freeze_sha256,frozen_aliases=aliases,ledger_snapshot=ledger_snapshot))
    require(actual == saved['l'] and actual['prior_segment_audits'] == {n:saved[n] for n in HISTORICAL},
            'all_four_runtime_audits_do_not_reproduce')
    require(actual.get('passed') is True and actual.get('final_closed') is True
            and actual.get('all_scheduled_outcomes_accounted') is True
            and actual.get('schedule_status') == ('stopped' if diagnostic else 'completed'),
            'explicit_diagnostic_or_complete_branch_required')
    require(actual.get('budget_cap_credits') == '750', 'prospective750_audit_required')
    segments = {n:segment(root,n) for n in SEGMENTS}
    for value in segments.values():
        for role,path in value['paths'].items():
            raw = value[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)]
            found = {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
            require(actual['input_bindings'].get(path) == found, 'runtime_bindings_differ_from_composite_source')
            before[path] = found
    require(actual['input_bindings'].get(LEDGER) == binding(snapshot), 'runtime_ledger_binding')
    data = {n:strict(safe(root,path).read_bytes()) for n,path in INPUTS.items()}
    receipt_counts(data['receipt'])
    for key in ('carried_final_slots','carried_issued_slots','continuation_slots'):
        require(freeze[key] == data['receipt'][key], 'freeze_receipt_count_mismatch')
    for path,digest in data['receipt']['prior_journal_files'].items():
        found = binding(safe(root,aliases.get(path,path)))
        require(found['sha256'] == digest, 'historical_receipt_source_changed'); before[path] = found
    result = json_value(evaluate_composite(data['corpus'],data['dossiers'],data['study'],data['sessions'],data['receipt'],
                                          segments,saved,diagnostic=diagnostic))
    require(result['summary']['status'] == (PARTIAL if diagnostic else COMPLETE), 'wrong_amended_result_branch')
    if diagnostic: require(diagnostic_only(result['summary']), 'interrupted_result_contains_inference')
    else: require(result['summary']['schedule_complete'] is True and result['summary']['primary_holm_family_size'] == 21,
                  'incomplete_scientific_result')
    views = {role:selected_source_lines(result['merged_evidence'],segments,role) for role in ('requests','responses','outcomes')}
    for path,value in before.items():
        require(binding(safe(root,aliases.get(path,path))) == value, 'source_changed_during_scoring')
    for path,value in actual['input_bindings'].items():
        target = ledger_snapshot if path == LEDGER else aliases.get(path,path)
        require(binding(safe(root,target)) == value, 'runtime_evidence_changed_during_scoring')
    verify_inventory(root,freeze_sha256,aliases)
    result['summary']['file_evidence'] = {'execution_freeze':{'path':FREEZE,'sha256':freeze_sha256},
        'source_files':before,'runtime_audits_replayed':True,'runtime_input_bindings_rechecked_after_score':True,
        'runtime_input_bindings':actual['input_bindings'],'frozen_aliases':aliases,
        'ledger_snapshot':{'path':ledger_snapshot,'sha256':ledger_snapshot_sha256},
        'scope':'Four-segment '+('interrupted diagnostics' if diagnostic else 'completed amended study')+
                '. All three prior interrupted summaries and definitive source outcomes remain unchanged.'}
    return result,views


def write_outputs(root, result, views, *, diagnostic=False):
    require(type(diagnostic) is bool, 'explicit_diagnostic_selector')
    output = PARTIAL_OUTPUT if diagnostic else OUTPUT
    directory = safe(root,output); require(not directory.exists(), 'output_already_exists')
    summary = result['summary']; require(summary['status'] == (PARTIAL if diagnostic else COMPLETE), 'wrong_publication_branch')
    if diagnostic: require(diagnostic_only(summary), 'diagnostic_only_publication_required')
    else: require(summary['schedule_complete'] is True and summary['planned_slots'] == 1800
                  and summary['primary_holm_family_size'] == 21, 'complete_publication_required')
    evidence = summary['file_evidence']; aliases = evidence['frozen_aliases']
    def recheck():
        require(not safe(root,LOCK).exists(), 'continuation_still_active')
        for name,value in evidence['source_files'].items():
            require(binding(safe(root,aliases.get(name,name))) == value, 'source_changed_before_publication')
        for name,value in evidence['runtime_input_bindings'].items():
            target = evidence['ledger_snapshot']['path'] if name == LEDGER else aliases.get(name,name)
            require(binding(safe(root,target)) == value, 'runtime_evidence_changed_before_publication')
        verify_inventory(root,evidence['execution_freeze']['sha256'],aliases)
    encode = lambda obj:(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    closure = 'interrupted-closure.json' if diagnostic else 'derived-closure.json'
    payloads = {'score.json':encode(summary),'score-audits.json':encode(result['audits']),
        'requests.jsonl':views['requests'],'responses.jsonl':views['responses'],'slot-outcomes.jsonl':views['outcomes'],
        'source-provenance.json':encode(result['merged_evidence']['source_provenance']),closure:encode(summary['operational_summary'])}
    recheck(); directory.mkdir(parents=True,exist_ok=False)
    for name,raw in payloads.items():
        with (directory/name).open('xb') as stream: stream.write(raw)
    recheck()
    a = summary['amendment']
    manifest = {'schema':'retrace.frontier-v6l-'+('partial' if diagnostic else 'composite')+'-artifacts.v1',
        'status':summary['status'],'planned_slots':1800,'schedule_complete':not diagnostic,'inference_available':not diagnostic,
        **{key:a[key] for key in ('carried_final_slots','carried_issued_slots','carried_dependency_failed_slots','retained_by_segment')},
        'continuation_slots':a['continuation_planned_slots'],'source_rows_changed':False,'selected_jsonl_source_bytes_preserved':True,
        'files':{output+'/'+name:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in payloads.items()},
        'source_bindings':result['merged_evidence']['source_bindings'],'file_evidence':evidence,'writer_sha256':sha(Path(__file__)),
        'scope':'Lossless four-segment views. Earlier failures and definitive skips are never replaced; interrupted outputs are not complete-study inference.'}
    with (directory/('partial-manifest.json' if diagnostic else 'composite-manifest.json')).open('xb') as stream:
        stream.write(encode(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','i-audit-sha256','j-audit-sha256','k-audit-sha256','l-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--diagnostic',action='store_true',help='Explicit stopped-l branch; never complete inference')
    parser.add_argument('--aliases',type=Path); args = parser.parse_args()
    output = PARTIAL_OUTPUT if args.diagnostic else OUTPUT
    require(not safe(args.root,output).exists(), 'output_already_exists')
    aliases = strict(args.aliases.read_bytes()) if args.aliases else {}
    result,views = compute(args.root,args.freeze_sha256,args.i_audit_sha256,args.j_audit_sha256,args.k_audit_sha256,
        args.l_audit_sha256,args.ledger_snapshot,args.ledger_snapshot_sha256,frozen_aliases=aliases,diagnostic=args.diagnostic)
    manifest = write_outputs(args.root,result,views,diagnostic=args.diagnostic)
    print(json.dumps({'status':manifest['status'],'planned_slots':1800,'continuation_slots':manifest['continuation_slots'],
                      'inference_available':manifest['inference_available'],'output':output}))


if __name__ == '__main__': main()
