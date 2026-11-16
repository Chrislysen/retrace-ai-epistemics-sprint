"""Four immutable segments; the original v6i scientific grader stays unchanged.

Only a closed k cumulative-budget stop can authorize this continuation. The
complete and interrupted paths have distinct gates and output statuses.
"""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from types import FunctionType

from . import frontier_v6i_eval as frozen
from .frontier_v6j_eval import _rows, _strict, json_value, require, ROUTE
from .frontier_v6k_eval import is_definitive, CARRY_I, CARRY_J
from .frontier_v6k_partial import coverage, diagnostic_only
from .adaption_v6h import digest

SCHEMA = 'retrace.frontier-v6l-composite-evaluation.v1'
PARTIAL_SCHEMA = 'retrace.frontier-v6l-partial-evaluation.v1'
COMPLETE = 'complete_amended_primary'
PARTIAL = 'interrupted_amended_diagnostic'
SEGMENTS = ('i', 'j', 'k', 'l')
HISTORICAL = SEGMENTS[:-1]
NAMES = {'requests':'requests.jsonl', 'responses':'responses.jsonl', 'outcomes':'slot-outcomes.jsonl',
         'summary':'summary.json', 'run_manifest':'run.json'}


def role_paths(name):
    require(name in SEGMENTS, 'known segment required')
    prefix = f'results/frontier-v6{name}/' + ('primary/' if name == 'i' else 'continuation/')
    return {role:prefix+file for role,file in NAMES.items()}


def receipt_counts(receipt):
    require(receipt.get('schema') == 'retrace.frontier-v6l-continuation.v1', 'l receipt schema')
    require(receipt.get('full_planned_slots') == 1800 and receipt.get('previous_cumulative_cap_credits') == '250'
            and receipt.get('cumulative_cap_credits') == '750', 'unchanged plan and prospective cap policy')
    carried, issued, remaining = (receipt.get(k) for k in ('carried_final_slots','carried_issued_slots','continuation_slots'))
    require(all(type(n) is int for n in (carried,issued,remaining)) and 224 <= carried < 1800
            and 213 <= issued <= carried and remaining == 1800-carried, 'dynamic carry/complement counts')
    require(receipt.get('observed_response_models') == ROUTE, 'observed route policy unchanged')
    carry = Decimal(receipt['historical_conservative_carry_credits'])
    require(carry.is_finite() and Decimal(CARRY_J) <= carry <= Decimal('250'), 'prior250 credit bound remains intact')
    return {'i':1800,'j':1794,'k':1576,'l':remaining}, {'i':6,'j':218,'k':carried-224}


def assemble_views(slots, receipt, segments, *, diagnostic=False):
    planned, definitive = receipt_counts(receipt)
    require(len(slots) == len({s['slot_id'] for s in slots}) == 1800
            and receipt['sessions_sha256'] == digest(slots), 'unchanged unique1800 schedule')
    index = {s['slot_id']:s for s in slots}
    require(set(segments) == set(SEGMENTS), 'exact i j k l source segments')
    declarations = receipt['source_segments']
    require([d['segment'] for d in declarations] == list(HISTORICAL), 'ordered historical segment declarations')
    declared = {d['segment']:d for d in declarations}
    values, pointers, bindings = {}, {}, {}
    for name in SEGMENTS:
        segment = segments[name]
        require(segment['paths'] == role_paths(name), 'exact canonical segment paths required')
        values[name], pointers[name] = {}, {}
        for role,path in segment['paths'].items():
            raw = segment[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)]
            require(isinstance(raw,bytes), 'unaltered source bytes required')
            bindings[path] = {'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}
            if role in ('summary','run_manifest'):
                obj = segment['summary' if role == 'summary' else 'manifest']
                require(_strict(raw) == obj, 'raw metadata equality'); values[name][role] = deepcopy(obj)
            else:
                values[name][role], pointers[name][role] = _rows(raw,path)
            if name in declared:
                require(declared[name]['paths'][role] == path
                        and declared[name]['sha256'][role] == bindings[path]['sha256']
                        and receipt['prior_journal_files'].get(path) == bindings[path]['sha256'], 'historical source changed')
        data = values[name]; summary = data['summary']; rid = summary['run_id']
        require(summary['schema'] == f'retrace.adaption-v6{name}-summary.v1'
                and data['run_manifest']['run_id'] == rid
                and all(r['run_id'] == rid for r in data['responses']+data['outcomes']), 'segment run identity/schema')
        require(summary['planned'] == planned[name] and summary['issued_without_outcome_attempt_ids'] == []
                and summary['all_scheduled_outcomes_recorded'] is True, 'closed segment denominator and accounting')
        finals = {r['slot_id']:r for r in data['outcomes']}
        require(len(finals) == len(data['outcomes']) == planned[name] and set(finals) <= set(index), 'segment final denominator')
        data['finals'] = finals
        if name in declared:
            require(declared[name]['run_id'] == rid and declared[name]['definitive_final_slots'] == definitive[name], 'historical count declaration')
            expected = {'i':'response_model_mismatch','j':'network_or_transport_failure','k':'cumulative_budget_stop'}[name]
            require(summary['status'] == 'stopped' and summary['stop_reasons'] == [expected], 'only specified historical interruption authorized')
    require(len({values[n]['summary']['run_id'] for n in SEGMENTS}) == 4, 'distinct segment run IDs')
    require(receipt['original_run_ids'] == [values[n]['summary']['run_id'] for n in HISTORICAL]
            and receipt['original_run_id'] == values['i']['summary']['run_id'], 'original run identities')
    selected, selected_pointers, refs, issued_old, omitted = {}, {}, [], set(), {}
    for name in HISTORICAL:
        data = values[name]
        require(set(data['finals']) == set(index)-set(selected), 'historical planned complement')
        chosen = [r for r in data['outcomes'] if is_definitive(r)]
        issued = {r['slot_id'] for r in chosen if r['issued']}
        require(len(chosen) == definitive[name] and len(issued) == declared[name]['issued_slots'], 'all historical definitive outcomes retained')
        require(len(data['requests']) == len(data['responses']) == data['summary']['issued_attempts']
                and {r['slot_id'] for r in data['requests']} == issued == {r['slot_id'] for r in data['responses']}, 'historical attempt/final membership')
        if name in ('i','j'):
            fixed = 6 if name == 'i' else 207
            require(len(issued) == len(data['requests']) == fixed and data['summary']['retries'] == 0, 'pinned original attempt counts')
        require(not issued_old & issued, 'historical issued slot repeated'); issued_old |= issued
        globals_ = [r for r in data['responses'] if r.get('failure_scope') == 'global']
        if name == 'k':
            require(not globals_, 'budget-stopped k cannot hide a global response failure')
        else:
            error = 'response_model_mismatch' if name == 'i' else 'network_or_transport_failure'
            require(len(globals_) == 1 and globals_[0]['error'] == error and globals_[0]['terminal_valid'] is False,
                    'original global failure remains failed')
            if name == 'i': require(globals_[0]['model'] == 'qwen3.5-397b', 'original rejected Qwen route retained')
        omitted[name] = []
        for row,pointer in zip(data['outcomes'],pointers[name]['outcomes']):
            sid = row['slot_id']
            if is_definitive(row):
                require(sid not in selected, 'historical definitive slot repeated')
                selected[sid] = row; selected_pointers[sid] = {'slot_id':sid,'segment':name,**pointer}
                refs.append({'segment':name,'slot_id':sid,**{key:pointer[key] for key in ('source_path','source_line_one_based','row_sha256')},
                             'attempt_id':row.get('attempt_id'),'model_outcome':row['model_outcome']})
            else:
                require(row['issued'] is False and row['model_outcome'] == 'not_issued_global_stop'
                        and row['attempts_issued'] == 0, 'only untouched stop placeholders may be omitted')
                omitted[name].append(sid)
    require(refs == receipt['carried_final_outcomes'] and len(refs) == receipt['carried_final_slots'], 'exact historical source-line pointers')
    require(receipt['permanently_excluded_final_slot_ids'] == [r['slot_id'] for r in refs], 'all old definitive outcomes excluded')
    excluded = receipt['permanently_excluded_issued_slot_ids']
    require(set(excluded) == issued_old and len(excluded) == len(issued_old) == receipt['carried_issued_slots'], 'all old issued slots excluded')
    pending = [s['slot_id'] for s in slots if s['slot_id'] not in selected]
    require(pending == receipt['continuation_slot_ids'] and len(pending) == planned['l'], 'exact ordered untouched complement')
    last = values['l']
    require(set(last['finals']) == set(pending) and all(r['slot_id'] in pending for r in last['requests']+last['responses']),
            'no definitive historical slot may be reissued')
    for row,pointer in zip(last['outcomes'],pointers['l']['outcomes']):
        selected[row['slot_id']] = row; selected_pointers[row['slot_id']] = {'slot_id':row['slot_id'],'segment':'l',**pointer}
    for sid in receipt['failed_producer_descendant_slot_ids']:
        row = selected[sid]
        require(row['issued'] is False and (row['model_outcome'] == 'not_issued_dependency_failed'
                or diagnostic and row['model_outcome'] == 'not_issued_global_stop'), 'failed producer cannot feed later history')
    requests = [r for n in SEGMENTS for r in values[n]['requests']]
    responses = [r for n in SEGMENTS for r in values[n]['responses']]
    require(len({r['attempt_id'] for r in requests}) == len(requests), 'globally unique attempt IDs')
    for name in ('j','k','l'):
        for row in values[name]['responses']:
            require(row.get('requested_model') == row['model'], 'requested model binding')
            if row['terminal_valid']: require(row.get('returned_model') == ROUTE.get(row['model'],row['model']), 'exact observed future route')
    outcomes = [selected[s['slot_id']] for s in slots]
    frozen.records(slots,outcomes,responses,requests)
    provenance = {'outcomes':[selected_pointers[s['slot_id']] for s in slots]}
    for role in ('requests','responses'):
        provenance[role] = [{'attempt_id':r['attempt_id'],'segment':n,**p} for n in SEGMENTS
                            for r,p in zip(values[n][role],pointers[n][role])]
    return {'outcomes':outcomes,'requests':requests,'responses':responses,'source_provenance':provenance,
            'source_bindings':bindings,'segment_summaries':{n:values[n]['summary'] for n in SEGMENTS},
            'source_rows_changed':False,'omitted_unissued_global_stop_placeholders':omitted}


def validate_segment_proofs(merged, receipt, audits, *, diagnostic=False):
    planned, _ = receipt_counts(receipt)
    require(set(audits) == set(SEGMENTS), 'all four independent audits required')
    require(audits['l']['prior_segment_audits'] == {n:audits[n] for n in HISTORICAL}, 'exact nested prior proofs')
    for name in SEGMENTS:
        proof = audits[name]
        expected = 'stopped' if name != 'l' or diagnostic else 'completed'
        require(proof.get('passed') is True and proof.get('final_closed') is True
                and proof.get('all_scheduled_outcomes_accounted') is True and proof['schedule_status'] == expected
                and proof['counts']['planned'] == planned[name], 'closed accounted segment status/denominator')
        for path in role_paths(name).values():
            require(proof['input_bindings'].get(path) == merged['source_bindings'][path], 'proof binds different source bytes')
    require(audits['i']['cumulative_accounted_credits'] == CARRY_I == audits['j']['historical_carry_credits'], 'i carry preserved')
    require(audits['j']['cumulative_accounted_credits'] == CARRY_J == audits['k']['historical_carry_credits'], 'j carry preserved')
    require(audits['k']['cumulative_accounted_credits'] == receipt['historical_conservative_carry_credits']
            == audits['l']['historical_carry_credits'] and audits['l']['budget_cap_credits'] == '750', 'k carry and new750 cap preserved')
    summary = merged['segment_summaries']['l']
    require(summary['status'] == ('stopped' if diagnostic else 'completed') and summary['original_planned'] == 1800
            and summary['carried_over_slots'] == receipt['carried_final_slots'], 'explicit l closure metadata')
    if diagnostic:
        require(bool(summary['stop_reasons']), 'explicit interrupted l reason required')
    else:
        require(summary['stop_reasons'] == [], 'completed l cannot have a halt')
        require(not any(r.get('failure_scope') == 'global' for r in merged['responses'] if r['run_id'] == summary['run_id']),
                'new global failure cannot be waived')
        require(not any(r['model_outcome'] == 'not_issued_global_stop' for r,p in zip(merged['outcomes'],merged['source_provenance']['outcomes'])
                        if p['segment'] == 'l'), 'stop placeholders cannot imply completion')


def evaluate_composite(corpus, dossiers, study, slots, receipt, segments, segment_audits, *, diagnostic=False):
    require(type(diagnostic) is bool, 'explicit diagnostic selector')
    merged = assemble_views(slots,receipt,segments,diagnostic=diagnostic)
    validate_segment_proofs(merged,receipt,segment_audits,diagnostic=diagnostic)
    _, retained = receipt_counts(receipt)
    operational = {'schema':'retrace.frontier-v6l-'+('interrupted' if diagnostic else 'derived')+'-closure.v1',
        'status':PARTIAL if diagnostic else 'closed_under_prospective_amendments', 'planned':1800,
        'issued_attempts':len(merged['requests']),'slot_outcomes':1800,
        'carried_final_slots':receipt['carried_final_slots'],'carried_issued_slots':receipt['carried_issued_slots'],
        'carried_dependency_failed_slots':receipt['carried_final_slots']-receipt['carried_issued_slots'],
        'continuation_slots':receipt['continuation_slots'],'retained_by_segment':retained,
        'segments':deepcopy(merged['segment_summaries']),
        'scope':'Derived four-segment accounting; all three historical interrupted summaries and definitive failures remain unchanged.'}
    if diagnostic:
        operational['stop_reasons'] = deepcopy(merged['segment_summaries']['l']['stop_reasons'])
        run = frozen.evaluate  # No override in the interrupted path.
    else:
        expected = {'slots':digest(slots),'finals':digest(merged['outcomes']),'attempts':digest(merged['responses']),
                    'requests':digest(merged['requests']),'summary':digest(operational)}
        def amended_closed(summary, selected_slots, finals, attempts, requests):
            actual = {'slots':digest(selected_slots),'finals':digest(list(finals.values())),'attempts':digest(attempts),
                      'requests':digest(requests),'summary':digest(summary)}
            require(actual == expected, 'closure override binds exact audited merged records'); return True
        scope = dict(frozen.evaluate.__globals__); scope['closed_summary'] = amended_closed
        run = FunctionType(frozen.evaluate.__code__,scope,'evaluate_authenticated_v6l',frozen.evaluate.__defaults__,frozen.evaluate.__closure__)
        run.__kwdefaults__ = deepcopy(frozen.evaluate.__kwdefaults__)
    result = run(corpus,dossiers,study,slots,merged['outcomes'],merged['responses'],merged['requests'],operational,10000,require_full_design=True)
    summary = result['summary']
    if diagnostic:
        require(summary['status'] == 'diagnostic_incomplete_or_test_design' and summary['test_design'] is False
                and diagnostic_only(summary), 'interrupted original grader must have null inference')
        summary['frozen_evaluator_status'] = summary['status']; summary['schema'] = PARTIAL_SCHEMA; summary['status'] = PARTIAL
        summary['coverage'] = coverage(slots,corpus,merged,result['audits'])
        summary['coverage']['stop_reasons'] = deepcopy(operational['stop_reasons'])
        summary['interpretation_limits'].append('Interrupted four-segment diagnostic only. Unissued stop rows are censored; no primary inference is salvaged from completed arms.')
    else:
        require(summary['status'] == 'complete_primary' and summary['primary_holm_family_size'] == 21, 'frozen scientific computation completed')
        summary['schema'] = SCHEMA; summary['status'] = COMPLETE
        for row in summary['paired_comparisons']:
            if row['status'] == 'complete_primary': row['status'] = COMPLETE
    summary['amendment'] = {'receipt_sha256_canonical':digest(receipt),'prior_segment_statuses':dict.fromkeys(HISTORICAL,'interrupted'),
        'historical_global_failures_preserved':True,'source_rows_changed':False,
        'carried_final_slots':receipt['carried_final_slots'],'carried_issued_slots':receipt['carried_issued_slots'],
        'carried_dependency_failed_slots':receipt['carried_final_slots']-receipt['carried_issued_slots'],
        'retained_by_segment':retained,'continuation_planned_slots':receipt['continuation_slots'],
        'previous_cumulative_cap_credits':'250','cumulative_cap_credits':'750',
        'observed_response_models':deepcopy(ROUTE),'vendor_alias_mapping_documented':False,'weight_identity_verified':False,
        'closure_override':False if diagnostic else 'Only closed_summary in an isolated FunctionType globals copy; no frozen module mutation.',
        'resource_estimate_scope':'Requested-ID usage estimates are not ledger settlements or actual billing. Old unknown reservations remain retained; observed route labels do not establish price/precision equivalence.',
        'scope':'Prospective continuation only of untouched frozen slots after the authenticated k250-credit budget stop; no historical issued outcome or definitive dependency skip is replaced.'}
    summary['segment_runtime_audits'] = deepcopy(segment_audits); summary['source_bindings'] = deepcopy(merged['source_bindings'])
    result['merged_evidence'] = merged
    return result
