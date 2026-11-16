"""Lossless three-segment closure; frozen v6i scientific computation unchanged."""
from copy import deepcopy
from hashlib import sha256
from types import FunctionType
from . import frontier_v6i_eval as frozen
from .frontier_v6j_eval import _rows,_strict,json_value,require,ROUTE
from .adaption_v6h import digest

SCHEMA='retrace.frontier-v6k-composite-evaluation.v1'
SEGMENTS=('i','j','k')
PREFIXES={'i':'results/frontier-v6i/primary/','j':'results/frontier-v6j/continuation/','k':'results/frontier-v6k/continuation/'}
NAMES={'requests':'requests.jsonl','responses':'responses.jsonl','outcomes':'slot-outcomes.jsonl','summary':'summary.json','run_manifest':'run.json'}
PLANNED={'i':1800,'j':1794,'k':1576}
DEFINITIVE={'i':6,'j':218,'k':1576}
OLD_ISSUED={'i':6,'j':207}
CARRY_I='47.653269434'
CARRY_J='80.145946577'


def role_paths(name):return {role:PREFIXES[name]+file for role,file in NAMES.items()}


def is_definitive(row):
    return row.get('issued') is True or (row.get('issued') is False and row.get('model_outcome')=='not_issued_dependency_failed')


def assemble_views(slots,receipt,segments):
    """Bind selected raw source rows; never normalize failures or old placeholders."""
    require(receipt['schema']=='retrace.frontier-v6k-continuation.v1','k receipt schema')
    require(len(slots)==1800 and receipt['sessions_sha256']==digest(slots),'unchanged 1800-slot scientific schedule')
    require(receipt['carried_final_slots']==224 and receipt['carried_issued_slots']==213 and receipt['continuation_slots']==1576,'fixed three-segment cohort')
    require(receipt['observed_response_models']==ROUTE,'observed route policy unchanged')
    index={s['slot_id']:s for s in slots};require(len(index)==1800,'unique planned slots')
    require(set(segments)==set(SEGMENTS),'exact i j k source segments')
    declarations=receipt['source_segments'];require([r['segment'] for r in declarations]==['i','j'],'ordered historical segment declarations')
    declared={r['segment']:r for r in declarations}
    values={};pointers={};bindings={}
    for name in SEGMENTS:
        segment=segments[name];require(segment['paths']==role_paths(name),'exact canonical segment paths required')
        require(segment['manifest']['run_id']==segment['summary']['run_id'],'segment metadata run identity')
        values[name]={};pointers[name]={}
        for role in NAMES:
            raw_key={'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)
            raw=segment[raw_key];require(isinstance(raw,bytes),'raw source bytes required')
            path=segment['paths'][role];bindings[path]={'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}
            if role in ('summary','run_manifest'):
                metadata=segment['summary' if role=='summary' else 'manifest']
                require(_strict(raw)==metadata,'raw metadata equality');values[name][role]=deepcopy(metadata)
            else:values[name][role],pointers[name][role]=_rows(raw,path)
            if name in declared:
                require(declared[name]['paths'][role]==path and declared[name]['sha256'][role]==bindings[path]['sha256'],'historical role changed')
                require(receipt['prior_journal_files'].get(path)==bindings[path]['sha256'],'historical source bytes changed')
        data=values[name];rid=data['summary']['run_id']
        require(all(row.get('run_id')==rid for row in data['responses']+data['outcomes']),'source rows bind segment run identity')
        finals={r['slot_id']:r for r in data['outcomes']}
        require(len(data['outcomes'])==len(finals)==PLANNED[name] and set(finals)<=set(index),'segment final denominator')
        data['finals']=finals
        if name in declared:
            require(declared[name]['run_id']==rid and declared[name]['definitive_final_slots']==DEFINITIVE[name] and declared[name]['issued_slots']==OLD_ISSUED[name],'historical count declaration')
    require(len({values[n]['summary']['run_id'] for n in SEGMENTS})==3,'distinct segment run IDs')
    require(receipt['original_run_ids']==[values[n]['summary']['run_id'] for n in ('i','j')] and receipt['original_run_id']==values['i']['summary']['run_id'],'original run identities')
    i,j,k=(values[n] for n in SEGMENTS)
    require(i['summary']['schema']=='retrace.adaption-v6i-summary.v1' and i['summary']['status']=='stopped' and i['summary']['stop_reasons']==['response_model_mismatch'],'only pinned i interruption authorized')
    require(j['summary']['schema']=='retrace.adaption-v6j-summary.v1' and j['summary']['status']=='stopped' and j['summary']['stop_reasons']==['network_or_transport_failure'],'only pinned j interruption authorized')
    selected={};selected_pointers={};carried_refs=[];issued_old=set()
    for name in ('i','j'):
        data=values[name];finals=data['finals'];chosen=[r for r in data['outcomes'] if is_definitive(r)]
        require(len(chosen)==DEFINITIVE[name],'exact historical definitive final count')
        issued={r['slot_id'] for r in chosen if r['issued']}
        require(len(issued)==OLD_ISSUED[name] and len(data['requests'])==len(data['responses'])==OLD_ISSUED[name],'all historical attempts retained without retry changes')
        require(data['summary']['issued_attempts']==OLD_ISSUED[name] and data['summary']['retries']==0,'historical attempt counts')
        require({r['slot_id'] for r in data['requests']}==issued=={r['slot_id'] for r in data['responses']},'historical attempt/final membership')
        require(not (issued_old & issued),'historical issued slot repeated');issued_old|=issued
        bysid={r['slot_id']:p for r,p in zip(data['outcomes'],pointers[name]['outcomes'])}
        for row in data['outcomes']:
            sid=row['slot_id']
            if is_definitive(row):
                require(sid not in selected,'historical definitive slot repeated');selected[sid]=row
                selected_pointers[sid]={'slot_id':sid,'segment':name,**bysid[sid]}
                carried_refs.append({'segment':name,'slot_id':sid,**{key:bysid[sid][key] for key in ('source_path','source_line_one_based','row_sha256')},'attempt_id':row.get('attempt_id'),'model_outcome':row['model_outcome']})
            else:require(row['issued'] is False and row['model_outcome']=='not_issued_global_stop' and row['attempts_issued']==0,'only unissued global-stop placeholders may be omitted')
        globals_=[r for r in data['responses'] if r.get('failure_scope')=='global']
        expected_error='response_model_mismatch' if name=='i' else 'network_or_transport_failure'
        require(len(globals_)==1 and globals_[0]['error']==expected_error and globals_[0]['terminal_valid'] is False,'historical global failure remains failed')
        if name=='i':require(globals_[0]['model']=='qwen3.5-397b','original rejected Qwen route retained')
    require(receipt['carried_final_outcomes']==carried_refs,'exact historical selected line pointers')
    carried=[row['slot_id'] for row in carried_refs]
    require(receipt['permanently_excluded_final_slot_ids']==carried,'all definitive historical outcomes excluded')
    require(set(receipt['permanently_excluded_issued_slot_ids'])==issued_old and len(receipt['permanently_excluded_issued_slot_ids'])==213,'all issued historical slots excluded')
    pending=[s['slot_id'] for s in slots if s['slot_id'] not in selected]
    require(receipt['continuation_slot_ids']==pending and len(pending)==1576,'exact ordered unissued continuation complement')
    require(set(i['finals'])==set(index) and set(j['finals'])==set(index)-{r['slot_id'] for r in carried_refs if r['segment']=='i'},'historical planned segment sets')
    require(set(k['finals'])==set(pending),'complete continuation final set')
    require(all(r['slot_id'] in pending for r in k['requests']+k['responses']),'historical definitive slot must never be reissued')
    all_requests=[r for n in SEGMENTS for r in values[n]['requests']]
    require(len({r['attempt_id'] for r in all_requests})==len(all_requests),'globally unique attempt IDs')
    for name in ('j','k'):
        for row in values[name]['responses']:
            require(row.get('requested_model')==row['model'],'requested model binding')
            if row['terminal_valid']:require(row.get('returned_model')==ROUTE.get(row['model'],row['model']),'exact observed future route')
    kp={r['slot_id']:p for r,p in zip(k['outcomes'],pointers['k']['outcomes'])}
    for sid,row in k['finals'].items():selected[sid]=row;selected_pointers[sid]={'slot_id':sid,'segment':'k',**kp[sid]}
    for sid in receipt['failed_producer_descendant_slot_ids']:
        require(sid in selected and selected[sid]['issued'] is False and selected[sid]['model_outcome']=='not_issued_dependency_failed','failed producer cannot feed a later history')
    merged_outcomes=[selected[s['slot_id']] for s in slots];all_responses=[r for n in SEGMENTS for r in values[n]['responses']]
    frozen.records(slots,merged_outcomes,all_responses,all_requests)
    provenance={'outcomes':[selected_pointers[s['slot_id']] for s in slots]}
    for role in ('requests','responses'):
        provenance[role]=[{'attempt_id':r['attempt_id'],'segment':name,**p} for name in SEGMENTS for r,p in zip(values[name][role],pointers[name][role])]
    return {'outcomes':merged_outcomes,'requests':all_requests,'responses':all_responses,'source_provenance':provenance,'source_bindings':bindings,
            'segment_summaries':{n:values[n]['summary'] for n in SEGMENTS},'source_rows_changed':False,
            'omitted_unissued_global_stop_placeholders':{n:[r['slot_id'] for r in values[n]['outcomes'] if not is_definitive(r)] for n in ('i','j')}}


def validate_segment_proofs(merged,receipt,audits):
    require(set(audits)==set(SEGMENTS),'all three independent segment audits required')
    for name in SEGMENTS:
        proof=audits[name]
        require(proof.get('passed') is True and proof.get('final_closed') is True and proof.get('all_scheduled_outcomes_accounted') is True,'closed accounted segment proof required')
        require(proof['schedule_status']==('completed' if name=='k' else 'stopped') and proof['counts']['planned']==PLANNED[name],'segment closure and denominator')
        for path in role_paths(name).values():require(proof['input_bindings'].get(path)==merged['source_bindings'][path],'segment proof binds different source bytes')
    require(audits['i']['cumulative_accounted_credits']==CARRY_I==audits['j']['historical_carry_credits'],'first segment carry preserved')
    require(audits['j']['cumulative_accounted_credits']==CARRY_J==receipt['historical_conservative_carry_credits']==audits['k']['historical_carry_credits'],'second segment carry preserved')
    summary=merged['segment_summaries']['k']
    require(summary['schema']=='retrace.adaption-v6k-summary.v1' and summary['status']=='completed' and summary['stop_reasons']==[] and summary['planned']==1576 and summary['original_planned']==1800 and summary['carried_over_slots']==224,'explicit completed k segment')
    require(summary['issued_without_outcome_attempt_ids']==[] and summary['all_scheduled_outcomes_recorded'] is True,'no orphan or missing k outcome')
    k_responses=[r for r in merged['responses'] if r['run_id']==summary['run_id']]
    require(not any(r.get('failure_scope')=='global' for r in k_responses),'new global failure cannot be waived')
    require(not any(r['model_outcome']=='not_issued_global_stop' for r,p in zip(merged['outcomes'],merged['source_provenance']['outcomes']) if p['segment']=='k'),'k global placeholders cannot imply completion')


def evaluate_composite(corpus,dossiers,study,slots,receipt,segments,segment_audits):
    merged=assemble_views(slots,receipt,segments);validate_segment_proofs(merged,receipt,segment_audits)
    operational={'schema':'retrace.frontier-v6k-derived-closure.v1','status':'closed_under_prospective_amendments',
        'planned':1800,'issued_attempts':len(merged['requests']),'slot_outcomes':1800,
        'carried_final_slots':224,'carried_issued_slots':213,'carried_dependency_failed_slots':11,'continuation_slots':1576,
        'retained_by_segment':{'i':6,'j':218},'segments':deepcopy(merged['segment_summaries']),
        'scope':'Derived three-segment closure. Both earlier interrupted summaries and all definitive failures remain unchanged.'}
    expected={'slots':digest(slots),'finals':digest(merged['outcomes']),'attempts':digest(merged['responses']),'requests':digest(merged['requests']),'summary':digest(operational)}
    def amended_closed(summary,selected_slots,finals,attempts,requests):
        actual={'slots':digest(selected_slots),'finals':digest(list(finals.values())),'attempts':digest(attempts),'requests':digest(requests),'summary':digest(summary)}
        require(actual==expected,'closure override binds exact audited merged records');return True
    scope=dict(frozen.evaluate.__globals__);scope['closed_summary']=amended_closed
    run=FunctionType(frozen.evaluate.__code__,scope,'evaluate_authenticated_v6k',frozen.evaluate.__defaults__,frozen.evaluate.__closure__)
    run.__kwdefaults__=deepcopy(frozen.evaluate.__kwdefaults__)
    result=run(corpus,dossiers,study,slots,merged['outcomes'],merged['responses'],merged['requests'],operational,10000,require_full_design=True)
    summary=result['summary'];require(summary['status']=='complete_primary' and summary['primary_holm_family_size']==21,'frozen scientific computation completed')
    summary['schema']=SCHEMA;summary['status']='complete_amended_primary'
    for row in summary['paired_comparisons']:
        if row['status']=='complete_primary':row['status']='complete_amended_primary'
    summary['amendment']={'receipt_sha256_canonical':digest(receipt),'prior_segment_statuses':{'i':'interrupted','j':'interrupted'},
        'historical_global_failures_preserved':True,'source_rows_changed':False,'carried_final_slots':224,'carried_issued_slots':213,
        'carried_dependency_failed_slots':11,'retained_by_segment':{'i':6,'j':218},'continuation_planned_slots':1576,
        'observed_response_models':deepcopy(ROUTE),'vendor_alias_mapping_documented':False,'weight_identity_verified':False,
        'resource_estimate_scope':'Frozen usage-derived resource estimates at requested-ID rates are not accepted ledger settlements or actual billing. Failed historical reservations remain fully retained; observed response-route labels do not prove price or weight equivalence.',
        'closure_override':'Only closed_summary in an isolated FunctionType globals copy; frozen scientific module and all source rows unchanged.',
        'scope':'A further prospectively frozen transport-only continuation of untouched slots. Neither historical segment is reclassified as completed; no issued observation or definitive dependency skip is replaced.'}
    summary['segment_runtime_audits']=deepcopy(segment_audits);summary['source_bindings']=deepcopy(merged['source_bindings']);result['merged_evidence']=merged
    return result
