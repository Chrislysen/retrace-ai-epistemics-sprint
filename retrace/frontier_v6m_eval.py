"""Crash-recovery scoring: unchanged diagnostics and a separate sensitivity.

No provider row or k run closure is synthesized. A separately authenticated
orphan disposition has the original scorer's existing missing-response shape.
The unchanged diagnostic result is retained even after the remaining schedule
finishes. The additional closure interpretation is explicitly an amendment.
"""
from copy import deepcopy
from hashlib import sha256
from types import FunctionType

from . import frontier_v6i_eval as frozen
from .recovery_v6m import derive_carry, rows
from .frontier_v6j_eval import _rows, _strict, json_value, require, ROUTE
from .adaption_v6h import digest
from .frontier_v6k_partial import diagnostic_only
from .frontier_v6k_eval import is_definitive

SCHEMA='retrace.frontier-v6m-recovered-evaluation.v1'
COMPLETE='complete_host_recovered_schedule'
PARTIAL='interrupted_recovery_diagnostic'
SENSITIVITY='amended_recovered_complete_sensitivity'
PREFIX='results/frontier-v6m/continuation/'
NAMES={'requests':'requests.jsonl','responses':'responses.jsonl','outcomes':'slot-outcomes.jsonl',
       'summary':'summary.json','run_manifest':'run.json'}


def role_paths():return {key:PREFIX+name for key,name in NAMES.items()}


def assemble_views(slots,receipt,contents,continuation):
    carry=derive_carry(slots,receipt,contents,continuation_sha256=digest(receipt))
    paths=role_paths();require(continuation['paths']==paths,'canonical m segment paths')
    values={};pointers={};bindings={}
    for role,path in paths.items():
        raw=continuation[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)]
        require(isinstance(raw,bytes),'unaltered m source bytes required')
        bindings[path]={'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}
        if role in ('summary','run_manifest'):
            values[role]=_strict(raw)
            require(values[role]==continuation['summary' if role=='summary' else 'manifest'],'m metadata byte equality')
        else:values[role],pointers[role]=_rows(raw,path)
    run=values['run_manifest'];summary=values['summary'];rid=summary['run_id']
    require(run['run_id']==rid and run['slots']==slots and run['sessions_sha256']==digest(slots)
            and summary['schema']=='retrace.adaption-v6m-summary.v1','m run identity and original slots')
    require(rid not in carry['original_run_ids'],'new m run identity required')
    require(summary['planned']==len(carry['continuation_slot_ids']) and summary['original_planned']==len(slots)
            and summary['carried_over_slots']==len(carry['finals']),'m cohort counts')
    require(summary['all_scheduled_outcomes_recorded'] is True
            and summary['issued_without_outcome_attempt_ids']==[],'m segment must have closed accounting')
    pending=set(carry['continuation_slot_ids']);finals=dict(carry['finals']);out_prov={}
    requests=[];responses=[];provenance={'requests':[],'responses':[]};omitted={}
    for seg in receipt['source_segments']:
        name=seg['segment'];oldpaths=seg['paths'];omitted[name]=[]
        for role in ('requests','responses','outcomes'):
            path=oldpaths[role];raw=contents[path];rs,ps=_rows(raw,path)
            bindings[path]={'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}
            for row,point in zip(rs,ps):
                if role=='outcomes':
                    if is_definitive(row):
                        require(carry['finals'][row['slot_id']]==row,'preserved final source mismatch')
                        out_prov[row['slot_id']]={'slot_id':row['slot_id'],'segment':name,**point}
                    else:omitted[name].append(row['slot_id'])
                else:
                    (requests if role=='requests' else responses).append(row)
                    provenance[role].append({'attempt_id':row['attempt_id'],'segment':name,**point})
    overlay_path=receipt['orphan_disposition_path'];ors,ops=_rows(contents[overlay_path],overlay_path)
    bindings[overlay_path]={'sha256':sha256(contents[overlay_path]).hexdigest(),'bytes':len(contents[overlay_path])}
    require(len(ors)==1,'one explicitly derived orphan disposition')
    out_prov[ors[0]['slot_id']]={'slot_id':ors[0]['slot_id'],'segment':'recovery',
        'record_origin':'derived_recovery_disposition',**ops[0]}
    require(len(values['outcomes'])==len(pending) and {r['slot_id'] for r in values['outcomes']}==pending,
            'm exact never-issued complement')
    for role in ('requests','responses','outcomes'):
        for row,point in zip(values[role],pointers[role]):
            require(row['slot_id'] in pending,'m reissued an original slot')
            if role!='requests':require(row['run_id']==rid,'m row run identity')
            if role=='outcomes':
                finals[row['slot_id']]=row;out_prov[row['slot_id']]={'slot_id':row['slot_id'],'segment':'m',**point}
            else:
                (requests if role=='requests' else responses).append(row)
                provenance[role].append({'attempt_id':row['attempt_id'],'segment':'m',**point})
    require(len({r['attempt_id'] for r in requests})==len(requests),'attempt IDs unique across all segments')
    new_q={r['attempt_id'] for r in values['requests']};new_r={r['attempt_id'] for r in values['responses']}
    require(new_q==new_r and len(new_q)==len(values['requests'])==len(values['responses']),
            'no new m orphan may be silently adjudicated')
    for row in values['responses']:
        require(row.get('requested_model')==row['model'],'m requested model metadata')
        if row['terminal_valid']:
            require(row.get('returned_model')==ROUTE.get(row['model'],row['model']),'exact observed model route')
    ordered=[finals[s['slot_id']] for s in slots]
    frozen.records(slots,ordered,responses,requests)
    provenance['outcomes']=[out_prov[s['slot_id']] for s in slots]
    return {'outcomes':ordered,'requests':requests,'responses':responses,'source_provenance':provenance,
        'source_bindings':bindings,'continuation_summary':summary,'carry':carry,
        'source_rows_changed':False,'derived_disposition_rows':1,
        'omitted_unissued_global_stop_placeholders':omitted}


def validate_proofs(merged,receipt,prefix_proof,m_audit,*,diagnostic=False):
    require(prefix_proof.get('passed') is True and prefix_proof.get('final_closed') is False
            and prefix_proof.get('schedule_status')=='interrupted_without_closure','k forensic proof is not run closure')
    require(m_audit.get('passed') is True and m_audit.get('final_closed') is True
            and m_audit.get('all_scheduled_outcomes_accounted') is True
            and m_audit.get('schedule_status')==('stopped' if diagnostic else 'completed'),
            'm audited closed branch required')
    require(m_audit['recovery_prefix_proof']==prefix_proof,'exact replayed forensic proof')
    require(m_audit['budget_cap_credits']=='750'
            and m_audit['historical_carry_credits']==prefix_proof['cumulative_accounted_credits']
            ==receipt['historical_conservative_carry_credits'],'all prior retained costs carried')
    for path,value in merged['source_bindings'].items():
        require(m_audit['input_bindings'].get(path)==value,'runtime proof source binding differs')
    summary=merged['continuation_summary']
    require(summary['status']==('stopped' if diagnostic else 'completed'),'continuation branch mismatch')
    if diagnostic:require(bool(summary['stop_reasons']),'stopped m reason required')
    else:
        require(summary['stop_reasons']==[],'completed m cannot hide halt')
        mrows=[r for r in merged['responses'] if r['run_id']==summary['run_id']]
        require(not any(r.get('failure_scope')=='global' for r in mrows),'new global failure forbids sensitivity completion')
        require(not any(r['model_outcome']=='not_issued_global_stop' for r,p in zip(merged['outcomes'],
            merged['source_provenance']['outcomes']) if p['segment']=='m'),'new untouched stop rows forbid sensitivity completion')


def score_views(corpus,dossiers,study,slots,merged,operational,*,complete,
                bootstrap_repeats=10000,require_full_design=True):
    """Two explicitly distinct closure interpretations of identical raw grades."""
    args=(corpus,dossiers,study,slots,merged['outcomes'],merged['responses'],merged['requests'],operational,bootstrap_repeats)
    diagnostic=frozen.evaluate(*args,require_full_design=require_full_design)
    require(diagnostic['summary']['schedule_complete'] is False
            and (diagnostic_only(diagnostic['summary']) if require_full_design else
                 diagnostic['summary']['cluster_intervals']==[]),'unchanged frozen closure must remain diagnostic')
    sensitivity=None
    if complete:
        expected={'slots':digest(slots),'finals':digest(merged['outcomes']),
            'attempts':digest(merged['responses']),'requests':digest(merged['requests']),'summary':digest(operational)}
        def amended_closed(summary,selected_slots,finals,attempts,requests):
            actual={'slots':digest(selected_slots),'finals':digest(list(finals.values())),
                'attempts':digest(attempts),'requests':digest(requests),'summary':digest(summary)}
            require(actual==expected,'sensitivity predicate binds exact authenticated records');return True
        scope=dict(frozen.evaluate.__globals__);scope['closed_summary']=amended_closed
        run=FunctionType(frozen.evaluate.__code__,scope,'evaluate_recovered_sensitivity',frozen.evaluate.__defaults__,frozen.evaluate.__closure__)
        run.__kwdefaults__=deepcopy(frozen.evaluate.__kwdefaults__)
        sensitivity=run(*args,require_full_design=require_full_design)
        require(json_value(sensitivity['audits'])==json_value(diagnostic['audits']),
                'closure sensitivity must not alter a grade')
        if require_full_design:
            require(sensitivity['summary']['status']=='complete_primary'
                    and sensitivity['summary']['primary_holm_family_size']==21,'unchanged21 scientific computations')
        sensitivity['summary']['original_evaluator_status']=sensitivity['summary']['status']
        sensitivity['summary']['schema']='retrace.frontier-v6m-amended-sensitivity.v1'
        sensitivity['summary']['status']=SENSITIVITY
        sensitivity['summary']['confirmatory_status']='explicitly_amended_not_untouched_confirmatory'
        old_closure_limit='Administrative/global halt, orphan requests or missing scheduled outcomes permit diagnostic summaries only. No failed answer is retried except explicit429 under the frozen runtime policy.'
        require(old_closure_limit in sensitivity['summary']['interpretation_limits'],'known original closure interpretation')
        sensitivity['summary']['interpretation_limits']=[
            ('The original frozen closure rule remains diagnostic and is preserved in frozen_diagnostic. '
             'This separately predeclared sensitivity treats the authenticated recovered schedule as accounted for; '
             'historical failures and the unanswered orphan remain failures, not replacements. '
             'No failed answer is retried except explicit429 under the unchanged runtime policy.')
            if text==old_closure_limit else text for text in sensitivity['summary']['interpretation_limits']]
        for row in sensitivity['summary']['paired_comparisons']:
            if row['status']=='complete_primary':row['status']=SENSITIVITY
        sensitivity['summary']['interpretation_limits'].append(
            'Separately predeclared recovery sensitivity: unchanged grades,21 contrasts and1800 denominators; '
            'an issued request with no recorded provider response is retained as zero. Original frozen closure rejects this schedule.')
    return diagnostic,sensitivity


def evaluate_recovered(corpus,dossiers,study,slots,receipt,contents,continuation,prefix_proof,m_audit,*,diagnostic=False):
    require(type(diagnostic) is bool,'explicit diagnostic branch')
    merged=assemble_views(slots,receipt,contents,continuation)
    validate_proofs(merged,receipt,prefix_proof,m_audit,diagnostic=diagnostic)
    operational={'schema':'retrace.frontier-v6m-recovery-closure.v1','status':PARTIAL if diagnostic else COMPLETE,
        'planned':1800,'carried_final_slots':receipt['carried_final_slots'],'continuation_slots':receipt['continuation_slots'],
        'slot_outcomes':len(merged['outcomes']),'original_k_status':'interrupted_without_closure',
        'original_k_summary_exists':False,'original_k_provider_response_fabricated':False,
        'derived_orphan_dispositions':1,'new_segment':deepcopy(merged['continuation_summary']),
        'scope':'Derived accounting across i,j,k-prefix,m. The old k run remains unclosed; no provider response or usage is invented.'}
    baseline,sensitivity=score_views(corpus,dossiers,study,slots,merged,operational,complete=not diagnostic)
    qids={r['attempt_id'] for r in merged['requests']};rids={r['attempt_id'] for r in merged['responses']}
    require(qids-rids==set(receipt['orphan_attempt_ids']),'only authenticated orphan remains unanswered')
    summary={'schema':SCHEMA,'status':PARTIAL if diagnostic else COMPLETE,'planned_slots':1800,
        'frozen_diagnostic':baseline['summary'],
        'amended_recovered_complete':sensitivity['summary'] if sensitivity else None,
        'operational_summary':operational,
        'request_accounting':{'actual_issued_attempts':len(merged['requests']),
            'provider_response_records':len(merged['responses']),'orphan_issued_attempts':len(qids-rids),
            'orphan_attempt_ids':list(receipt['orphan_attempt_ids']),
            'frozen_resource_denominator':'Recorded provider response rows only; see actual_issued_attempts for all requests.',
            'orphan_usage_known':False,'orphan_reservation_retained_in_full':True},
        'amendment':{'receipt_sha256_canonical':digest(receipt),'source_rows_changed':False,
            'previous_cumulative_cap_credits':'250','cumulative_cap_credits':'750',
            'recovery_proof_sha256':receipt['recovery_proof_sha256'],
            'interpretation':'Original diagnostic gate preserved verbatim. The separate sensitivity changes only the authenticated schedule-closure predicate, not methods, scores, denominators or model inputs.'}}
    return json_value({'summary':summary,'audits':baseline['audits'],'merged_evidence':merged})
