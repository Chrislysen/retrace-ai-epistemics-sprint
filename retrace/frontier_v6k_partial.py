"""Closed interrupted-study diagnostics; never upgrades the complete-study gate.

Uses the ORIGINAL frozen i evaluator with its unchanged closed_summary function.
All raw outcomes, including stop placeholders, retain their recorded identity.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256

from . import frontier_v6i_eval as frozen
from . import frontier_v6k_eval as k

STATUS = 'interrupted_amended_diagnostic'
SCHEMA = 'retrace.frontier-v6k-partial-evaluation.v1'
require = k.require


def diagnostic_only(summary):
    comparisons = summary.get('paired_comparisons', [])
    primary = [r for r in comparisons if r.get('primary_family_member') is True and r.get('view') == 'first_attempt']
    return (summary.get('schedule_complete') is False and summary.get('planned_slots') == 1800
            and summary.get('cluster_intervals') == [] and len(primary) == 21
            and all(r['p_two_sided_exact'] is None and r['holm_adjusted_p'] is None for r in comparisons))


def assemble_closed_partial(slots, receipt, segments, audits):
    """Select audited source lines without the complete k closure override.

The frozen full assembler additionally requires a known failed-producer skip.
A stop can precede recording that skip; preserve its actual global-stop row
instead of repairing it into a dependency outcome. Independent runtime audits
must authenticate all three complete journals before this projection is used.
"""
    require(set(segments) == set(audits) == set(k.SEGMENTS), 'exact three segments required')
    require(len(slots) == 1800 and len({s['slot_id'] for s in slots}) == 1800
            and receipt['sessions_sha256'] == k.digest(slots), 'unchanged complete scientific schedule')
    require(receipt['schema'] == 'retrace.frontier-v6k-continuation.v1'
            and (receipt['carried_final_slots'], receipt['carried_issued_slots'], receipt['continuation_slots']) == (224, 213, 1576)
            and receipt['observed_response_models'] == k.ROUTE, 'fixed continuation receipt')
    declared = receipt['source_segments']
    require([r['segment'] for r in declared] == ['i', 'j'], 'historical segment order')
    declared = {r['segment']: r for r in declared}
    values, pointers, bindings = {}, {}, {}
    for name in k.SEGMENTS:
        segment, proof = segments[name], audits[name]
        require(segment['paths'] == k.role_paths(name), 'canonical segment paths')
        require(proof.get('passed') is True and proof.get('final_closed') is True
                and proof.get('all_scheduled_outcomes_accounted') is True
                and proof.get('schedule_status') == 'stopped'
                and proof['counts']['planned'] == k.PLANNED[name], 'closed STOPPED segment proof required')
        values[name], pointers[name] = {}, {}
        for role, path in segment['paths'].items():
            raw = segment[{'summary':'summary_bytes', 'run_manifest':'manifest_bytes'}.get(role, role)]
            require(isinstance(raw, bytes), 'unaltered raw source bytes required')
            bindings[path] = {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
            require(proof['input_bindings'].get(path) == bindings[path], 'audited source binding mismatch')
            if name in declared:
                require(declared[name]['paths'][role] == path
                        and declared[name]['sha256'][role] == bindings[path]['sha256']
                        and receipt['prior_journal_files'].get(path) == bindings[path]['sha256'], 'historical source changed')
            if role in ('summary', 'run_manifest'):
                obj = segment['summary' if role == 'summary' else 'manifest']
                require(k._strict(raw) == obj, 'raw metadata mismatch'); values[name][role] = deepcopy(obj)
            else:
                values[name][role], pointers[name][role] = k._rows(raw, path)
        data = values[name]; summary = data['summary']; rid = summary['run_id']
        require(summary['schema'] == f'retrace.adaption-v6{name}-summary.v1' and summary['status'] == 'stopped'
                and summary['planned'] == k.PLANNED[name] and summary['stop_reasons']
                and summary['issued_without_outcome_attempt_ids'] == []
                and summary['all_scheduled_outcomes_recorded'] is True, 'explicit drained stopped summary required')
        require(data['run_manifest']['run_id'] == rid
                and all(r['run_id'] == rid for r in data['responses'] + data['outcomes']), 'segment identity')
        require(len(data['outcomes']) == len({r['slot_id'] for r in data['outcomes']}) == k.PLANNED[name], 'all scheduled outcome rows required')
        if name in declared:
            require(declared[name]['run_id'] == rid, 'historical run identity')
            reason = 'response_model_mismatch' if name == 'i' else 'network_or_transport_failure'
            failures = [r for r in data['responses'] if r.get('failure_scope') == 'global']
            require(summary['stop_reasons'] == [reason] and len(failures) == 1
                    and failures[0]['error'] == reason and failures[0]['terminal_valid'] is False, 'historical global failure must remain failed')
            require(len(data['requests']) == len(data['responses']) == k.OLD_ISSUED[name], 'historical attempts retained')
    require(len({values[n]['summary']['run_id'] for n in k.SEGMENTS}) == 3, 'distinct segment run IDs')
    require(audits['k']['prior_segment_audits'] == {'i':audits['i'], 'j':audits['j']}, 'nested historical proofs differ')
    require(values['k']['summary']['original_planned'] == 1800
            and values['k']['summary']['carried_over_slots'] == 224, 'unchanged k plan denominator')
    require(audits['i']['cumulative_accounted_credits'] == k.CARRY_I == audits['j']['historical_carry_credits']
            and audits['j']['cumulative_accounted_credits'] == k.CARRY_J
            == receipt['historical_conservative_carry_credits'] == audits['k']['historical_carry_credits'], 'conservative carry chain')
    selected, selected_pointers, refs, omitted = {}, {}, [], {}
    for name in ('i', 'j'):
        omitted[name] = []
        for row, pointer in zip(values[name]['outcomes'], pointers[name]['outcomes']):
            sid = row['slot_id']
            if k.is_definitive(row):
                require(sid not in selected, 'historical definitive slot repeated')
                selected[sid] = row; selected_pointers[sid] = {'slot_id':sid, 'segment':name, **pointer}
                refs.append({'segment':name, 'slot_id':sid, **{p:pointer[p] for p in ('source_path','source_line_one_based','row_sha256')},
                             'attempt_id':row.get('attempt_id'), 'model_outcome':row['model_outcome']})
            else:
                require(row['issued'] is False and row['model_outcome'] == 'not_issued_global_stop'
                        and row['attempts_issued'] == 0, 'only obsolete historical unissued placeholders omitted')
                omitted[name].append(sid)
    require(refs == receipt['carried_final_outcomes'] and len(refs) == 224
            and Counter(r['segment'] for r in refs) == {'i':6, 'j':218}, 'exact 224 historical source pointers')
    issued = {r['slot_id'] for r in refs if r['attempt_id'] is not None}
    require(len(issued) == 213 and set(receipt['permanently_excluded_issued_slot_ids']) == issued
            and receipt['permanently_excluded_final_slot_ids'] == [r['slot_id'] for r in refs], 'all old issued slots and definitive skips protected')
    pending = [s['slot_id'] for s in slots if s['slot_id'] not in selected]
    require(pending == receipt['continuation_slot_ids'] and len(pending) == 1576
            and {r['slot_id'] for r in values['k']['outcomes']} == set(pending), 'exact continuation complement')
    require(all(r['slot_id'] in pending for r in values['k']['requests'] + values['k']['responses']), 'no historical slot reissue')
    for row, pointer in zip(values['k']['outcomes'], pointers['k']['outcomes']):
        selected[row['slot_id']] = row; selected_pointers[row['slot_id']] = {'slot_id':row['slot_id'], 'segment':'k', **pointer}
    merged = {'outcomes':[selected[s['slot_id']] for s in slots],
              **{role:[r for n in k.SEGMENTS for r in values[n][role]] for role in ('requests','responses')},
              'source_provenance':{'outcomes':[selected_pointers[s['slot_id']] for s in slots]},
              'source_bindings':bindings, 'source_rows_changed':False,
              'segment_summaries':{n:values[n]['summary'] for n in k.SEGMENTS},
              'omitted_unissued_global_stop_placeholders':omitted}
    for role in ('requests','responses'):
        merged['source_provenance'][role] = [{'attempt_id':r['attempt_id'], 'segment':n, **p}
            for n in k.SEGMENTS for r,p in zip(values[n][role], pointers[n][role])]
    frozen.records(slots, merged['outcomes'], merged['responses'], merged['requests'])
    return merged


def coverage(slots, corpus, merged, graded):
    """Descriptive coverage and nonidentification bounds, never accuracy CIs."""
    cases = {c['id']:c for c in corpus['cases']}; finals = {r['slot_id']:r for r in merged['outcomes']}
    rows = {(r['view'],r['slot_id']):r for r in graded if 'slot_id' in r}
    attempts = defaultdict(list)
    for row in merged['responses']: attempts[row['slot_id']].append(row)
    categories = {sid:('unissued_censored_by_stop' if r['model_outcome'] == 'not_issued_global_stop' else
                      'definitive_dependency_skip' if r['model_outcome'] == 'not_issued_dependency_failed' else 'issued')
                  for sid,r in finals.items()}
    groups = defaultdict(list)
    for slot in slots:
        for part in ('all', cases[slot['case_id']]['partition']):
            groups[(slot['model'],slot['condition'],slot['phase'],part)].append(slot)
    arms = []
    for (model,condition,phase,part), chosen in sorted(groups.items()):
        n = len(chosen); counts = Counter(categories[s['slot_id']] for s in chosen); u = counts['unissued_censored_by_stop']
        views = {}
        for view in ('first_attempt','eventual'):
            observed = [rows[(view,s['slot_id'])] for s in chosen]; successes = sum(r['correct'] is True for r in observed)
            records = [(attempts[s['slot_id']][0] if attempts[s['slot_id']] else None) if view == 'first_attempt'
                       else (finals[s['slot_id']] if finals[s['slot_id']]['issued'] else None) for s in chosen]
            has_schema = condition != 'nl_source'
            assessed = condition not in ('nl_source','sfr_probe','sfr_backtranslation')
            valid = [r for r in observed if r['eligible_completed'] and r['schema_valid'] and type(r['correct']) is bool]
            views[view] = {'provider_completed':sum(r['provider_completed'] for r in observed),
                'dependency_eligible_completed':sum(r['eligible_completed'] for r in observed),
                'schema_assessed':has_schema,'standalone_success_assessed':assessed,
                'schema_admitted':sum(r['schema_valid'] for r in observed) if has_schema else None,
                'issued_truncated':sum(bool(r and r.get('model_outcome') == 'truncated_max_output_tokens') for r in records),
                'issued_provider_failure':sum(bool(r and not frozen.h.completed(r) and r.get('model_outcome') != 'truncated_max_output_tokens') for r in records),
                'eligible_invalid_output':sum(r['eligible_completed'] and not r['schema_valid'] for r in observed) if has_schema else None,
                'received_but_dependency_ineligible':sum(r['provider_completed'] and not r['eligible_completed'] for r in observed),
                'observed_successes':successes if assessed else None,
                'observed_successes_per_planned_slot':successes/n if assessed else None,
                'unissued_censoring_bounds': [successes/n,(successes+u)/n] if assessed else None,
                'admitted_response_conditional':{'successes':sum(r['correct'] for r in valid), 'denominator':len(valid),
                    'rate':sum(r['correct'] for r in valid)/len(valid) if valid else None} if assessed else None}
        arms.append({'model':model,'condition':condition,'phase':phase,'partition':part,'planned_slots':n,
                     **{c:counts[c] for c in ('issued','definitive_dependency_skip','unissued_censored_by_stop')},'views':views})
    return {'planned_slots':len(slots),'slot_categories':{c:sum(v==c for v in categories.values())
            for c in ('issued','definitive_dependency_skip','unissued_censored_by_stop')},
            'slot_category_by_id':categories,'arms':arms,
            'scope':'Unissued stop rows are censored, not observed reasoning errors. Observed successes/planned slots is realized yield, not estimated complete-study accuracy. Bounds assign every censored slot failure or success; they are conservative, not necessarily sharp, and are not confidence intervals. Admitted-response results are selection-conditional. Definitive issued failures and dependency skips remain failures. No corpus population or causal inference.'}


def evaluate_partial(corpus, dossiers, study, slots, receipt, segments, segment_audits):
    merged = assemble_closed_partial(slots, receipt, segments, segment_audits)
    operational = {'schema':'retrace.frontier-v6k-partial-closure.v1','status':STATUS,
        'planned':1800,'slot_outcomes':1800,'issued_attempts':len(merged['requests']),
        'stop_reasons':deepcopy(merged['segment_summaries']['k']['stop_reasons']),
        'segments':deepcopy(merged['segment_summaries']),
        'scope':'Closed accounting of an interrupted three-segment schedule; placeholders are not model responses.'}
    # Deliberately no FunctionType or closed_summary override.
    result = frozen.evaluate(corpus,dossiers,study,slots,merged['outcomes'],merged['responses'],merged['requests'],
                             operational,10000,require_full_design=True)
    summary = result['summary']
    require(summary['status'] == 'diagnostic_incomplete_or_test_design' and summary['test_design'] is False
            and diagnostic_only(summary),
            'diagnostic evaluator must not produce complete-study inference')
    summary['frozen_evaluator_status'] = summary['status']; summary['schema'] = SCHEMA; summary['status'] = STATUS
    summary['coverage'] = coverage(slots,corpus,merged,result['audits'])
    summary['coverage']['stop_reasons'] = deepcopy(operational['stop_reasons'])
    summary['coverage']['censoring_trigger'] = ('administrative_or_budget_stop' if all(
        r.startswith('administrative_') or r == 'cumulative_budget_stop' for r in operational['stop_reasons'])
        else 'recorded_global_halt_or_mixed_reasons')
    summary['amendment'] = {'prior_segment_statuses':{'i':'interrupted','j':'interrupted','k':'interrupted'},
        'historical_global_failures_preserved':True,'source_rows_changed':False,'carried_final_slots':224,
        'carried_issued_slots':213,'carried_dependency_failed_slots':11,'retained_by_segment':{'i':6,'j':218},
        'continuation_planned_slots':1576,'observed_response_models':deepcopy(k.ROUTE),
        'closure_override':False,'resource_estimate_scope':'Requested-ID usage estimates are not ledger settlements or verified billing. All unknown retained reservations remain in the independently audited conservative ledger.'}
    summary['segment_runtime_audits'] = deepcopy(segment_audits); summary['source_bindings'] = deepcopy(merged['source_bindings'])
    summary['interpretation_limits'].append('The 21 prospective comparisons remain diagnostic only; do not salvage significance from completed arms or treat stop-censored zeros as reasoning errors. Calibration/ranking summaries with gate-zeroed missing scores are operational diagnostics, not probability calibration or complete-study findings.')
    result['merged_evidence'] = merged
    return result
