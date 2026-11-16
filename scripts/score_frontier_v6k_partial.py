"""Authenticate a CLOSED STOPPED k segment and emit diagnostic-only sources.

No provider calls, forced stop, complete-study override, PDF, or old-file writes.
This post-freeze fallback is separately identified from prospective inference.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from scripts import score_frontier_v6k as full
from retrace.frontier_v6k_partial import evaluate_partial, diagnostic_only, STATUS, require

FREEZE_SHA = '274d3101ed47e3ca918ee1e2273c0cdd269b43c60567e3fa4e121f6a7b9efa40'
OUTPUT = 'results/frontier-v6k/partial-diagnostic'
NEW_SOURCES = {'scripts/score_frontier_v6k_partial.py','retrace/frontier_v6k_partial.py'}


def compute(root,freeze_sha256,i_audit_sha256,j_audit_sha256,k_audit_sha256,
            ledger_snapshot,ledger_snapshot_sha256,*,frozen_aliases=None):
    root=Path(root).resolve(); aliases=dict(frozen_aliases or {})
    require(not full.safe(root,'results/frontier-v6k/budget/active.lock').exists(),'continuation_still_active')
    require(freeze_sha256==FREEZE_SHA,'pinned_execution_freeze_required')
    _,inventory=full.verify_inventory(root,freeze_sha256,aliases)
    closure=full.import_closure(root,sorted(NEW_SOURCES))
    require(closure-set(inventory)==NEW_SOURCES,'unexpected_unfrozen_scoring_dependency')
    extra={name:full.binding(full.safe(root,name)) for name in NEW_SOURCES}
    require(ledger_snapshot!=full.LEDGER,'immutable_ledger_snapshot_required')
    snapshot=full.safe(root,ledger_snapshot);require(full.sha(snapshot)==ledger_snapshot_sha256,'ledger_snapshot_hash')
    before={name:full.binding(full.safe(root,name)) for name in set(full.INPUTS.values())|set(full.AUDITS.values())|{ledger_snapshot,full.FREEZE}}
    expected=dict(zip(full.SEGMENTS,(i_audit_sha256,j_audit_sha256,k_audit_sha256)));saved={}
    for name,path in full.AUDITS.items():
        require(before[path]['sha256']==expected[name],'saved_runtime_audit_hash');saved[name]=full.strict(full.safe(root,path).read_bytes())
    actual=full.json_value(full.audit_runtime(root,freeze_sha256,frozen_aliases=aliases,ledger_snapshot=ledger_snapshot))
    require(actual==saved['k'] and actual['prior_segment_audits']=={'i':saved['i'],'j':saved['j']},'all_runtime_audits_do_not_reproduce')
    require(actual.get('passed') is True and actual.get('final_closed') is True
            and actual.get('all_scheduled_outcomes_accounted') is True and actual.get('schedule_status')=='stopped',
            'closed_stopped_k_required_use_complete_scorer_if_completed')
    segments={name:full.segment(root,name) for name in full.SEGMENTS}
    for segment in segments.values():
        for role,path in segment['paths'].items():
            raw=segment[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)]
            found={'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}
            require(actual['input_bindings'].get(path)==found,'runtime_bindings_differ_from_partial_source');before[path]=found
    require(actual['input_bindings'].get(full.LEDGER)==full.binding(snapshot),'runtime_ledger_binding')
    data={name:full.strict(full.safe(root,path).read_bytes()) for name,path in full.INPUTS.items()}
    for path,expected_sha in data['receipt']['prior_journal_files'].items():
        found=full.binding(full.safe(root,aliases.get(path,path)));require(found['sha256']==expected_sha,'historical_source_changed');before[path]=found
    result=full.json_value(evaluate_partial(data['corpus'],data['dossiers'],data['study'],data['sessions'],data['receipt'],segments,saved))
    require(result['summary']['status']==STATUS and result['summary']['schedule_complete'] is False,'diagnostic_status_required')
    views={role:full.selected_source_lines(result['merged_evidence'],segments,role) for role in ('requests','responses','outcomes')}
    for path,value in before.items():require(full.binding(full.safe(root,aliases.get(path,path)))==value,'source_changed_during_diagnostics')
    for path,value in actual['input_bindings'].items():
        target=ledger_snapshot if path==full.LEDGER else aliases.get(path,path)
        require(full.binding(full.safe(root,target))==value,'runtime_evidence_changed_during_diagnostics')
    require(extra=={name:full.binding(full.safe(root,name)) for name in NEW_SOURCES},'partial_code_changed_during_diagnostics')
    full.verify_inventory(root,freeze_sha256,aliases)
    result['summary']['file_evidence']={'execution_freeze':{'path':full.FREEZE,'sha256':freeze_sha256},'source_files':before,
        'runtime_audits_replayed':True,'runtime_input_bindings_rechecked_after_score':True,'frozen_aliases':aliases,
        'runtime_input_bindings':actual['input_bindings'],
        'ledger_snapshot':{'path':ledger_snapshot,'sha256':ledger_snapshot_sha256},'post_freeze_diagnostic_code':extra,
        'scope':'Post-freeze fallback projection of a closed interrupted schedule. Original frozen diagnostic evaluator; no closure override, p-values or confidence intervals.'}
    return result,views


def report_facts(summary):
    require(summary['status']==STATUS and not summary['schedule_complete'],'partial report source only')
    c=summary['coverage']['slot_categories']; reasons=summary['operational_summary']['stop_reasons']
    return ('# Interrupted-study factual source — not a finished manuscript\n\n'
        f'The frozen design contains 1,800 scheduled slots. The closed composite retains {c["issued"]} issued slots, '
        f'{c["definitive_dependency_skip"]} definitive dependency skips, and {c["unissued_censored_by_stop"]} unissued stop-censored slots. '
        f'HTTP attempts: {summary["issued_attempts_observed"]}; these are not independent cases.\n\n'
        f'The k stop reasons are {json.dumps(reasons)}. All i/j/k summaries and original failure classifications remain unchanged. '
        'Six i outcomes plus 218 definitive j outcomes were carried into k; no prior issued slot or definitive skip was rerun.\n\n'
        'The original frozen evaluator ran in diagnostic mode. All 21 planned comparisons remain without p-values or Holm adjustments; '
        'no bootstrap confidence intervals were produced. Observed successes per planned slot are realized yield. Unissued slots are '
        'censored, not observed wrong reasoning. Conditional admitted-response results are selection-conditional. '
        'Warning-score ranking diagnostics are not probability calibration, and no completed arm is promoted to a salvaged primary hypothesis.\n\n'
        'The exact recorded Qwen NVFP4 route does not establish weight, precision or price equivalence. Conservative retained credits '
        'are separate from usage-derived estimates and actual billing. Complete-study report, catalog and release gates remain unavailable.\n')


def write_outputs(root,result,views):
    root=Path(root).resolve();directory=full.safe(root,OUTPUT)
    require(not directory.exists(),'partial_output_already_exists')
    summary=result['summary'];require(summary['status']==STATUS and diagnostic_only(summary), 'diagnostic_only_output_required')
    evidence=summary['file_evidence'];aliases=evidence['frozen_aliases']
    def recheck():
        require(not full.safe(root,'results/frontier-v6k/budget/active.lock').exists(),'continuation_still_active')
        for name,value in {**evidence['source_files'],**evidence['post_freeze_diagnostic_code']}.items():
            require(full.binding(full.safe(root,aliases.get(name,name)))==value,'source_changed_before_partial_publication')
        for name,value in evidence['runtime_input_bindings'].items():
            target=evidence['ledger_snapshot']['path'] if name==full.LEDGER else aliases.get(name,name)
            require(full.binding(full.safe(root,target))==value,'runtime_evidence_changed_before_partial_publication')
        full.verify_inventory(root,evidence['execution_freeze']['sha256'],aliases)
    encode=lambda obj:(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    payloads={'score.json':encode(summary),'score-audits.json':encode(result['audits']),
        'requests.jsonl':views['requests'],'responses.jsonl':views['responses'],'slot-outcomes.jsonl':views['outcomes'],
        'source-provenance.json':encode(result['merged_evidence']['source_provenance']),
        'interrupted-closure.json':encode(summary['operational_summary']),'report-facts.md':report_facts(summary).encode('utf-8')}
    recheck();directory.mkdir(parents=True,exist_ok=False)
    for name,raw in payloads.items():
        with (directory/name).open('xb') as stream:stream.write(raw)
    recheck()
    manifest={'schema':'retrace.frontier-v6k-partial-artifacts.v1','status':STATUS,'planned_slots':1800,
        'schedule_complete':False,'inference_available':False,'source_rows_changed':False,'selected_jsonl_source_bytes_preserved':True,
        'files':{OUTPUT+'/'+name:{'sha256':sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in payloads.items()},
        'source_bindings':result['merged_evidence']['source_bindings'],'file_evidence':evidence,'writer_sha256':full.sha(Path(__file__))}
    with (directory/'partial-manifest.json').open('xb') as stream:stream.write(encode(manifest))
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    for name in ('freeze-sha256','i-audit-sha256','j-audit-sha256','k-audit-sha256','ledger-snapshot','ledger-snapshot-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--aliases',type=Path);args=parser.parse_args()
    require(not full.safe(args.root,OUTPUT).exists(),'partial_output_already_exists')
    aliases=full.strict(args.aliases.read_bytes()) if args.aliases else {}
    result,views=compute(args.root,args.freeze_sha256,args.i_audit_sha256,args.j_audit_sha256,args.k_audit_sha256,
        args.ledger_snapshot,args.ledger_snapshot_sha256,frozen_aliases=aliases)
    manifest=write_outputs(args.root,result,views)
    print(json.dumps({'status':manifest['status'],'planned_slots':1800,'inference_available':False,'output':OUTPUT}))


if __name__=='__main__':main()
