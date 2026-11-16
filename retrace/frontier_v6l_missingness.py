"""Pure post-freeze descriptive operational-missingness sensitivity.

Call only on an already-authenticated composite/diagnostic result. This module
does no I/O, source reconstruction, model invocation, grading, imputation or
publication. It leaves frozen pipeline scores and inferential endpoints intact.
"""
from collections import Counter
from . import frontier_v6i_eval as frozen
from . import frontier_v6h_eval as h
from .adaption_v6h import PRIMARY_MODELS, slot_dependencies, validate_slots, digest

VIEWS = ('first_attempt', 'eventual')
# Exact names, endpoints and subsets from frozen v6i.evaluate's contrast loop.
ELEMENTARY = {
    'nl_projection_minus_strict_ir': ('nl_projection', ('strict_source_ir','extract'), ('nl_projection','project')),
    'assisted_minus_oracle': ('oracle_assisted', ('oracle_ir_consumption','fresh_withdrawn'), ('symbolic_assistance','fresh_withdrawn')),
    'no_commit_minus_history_withdrawn': ('temporal', ('commitment','hist_withdrawn'), ('commitment','evt_no_commit')),
    'fresh_withdrawn_minus_no_commit': ('temporal', ('commitment','evt_no_commit'), ('commitment','fresh_withdrawn')),
}
EXCLUDED = 'strict_ir_minus_k10_union'
require = h.require


def _metadata(study, slots, summary):
    validate_slots(slots)
    require(study.get('schema')=='retrace.frontier-v6i-design.v1' and study.get('planned_requests')==1800,
            'Frozen 1800-slot design required')
    require(len(slots)==1800 and Counter(s['condition'] for s in slots)==Counter(frozen.COUNT_CONDITIONS),
            'Exact scheduled allocation required')
    cases=study.get('all_case_ids');subsets=study.get('subsets')
    require(isinstance(cases,list) and len(cases)==len(set(cases))==60 and set(cases)=={s['case_id'] for s in slots},
            'Exact 60-case inventory required')
    require(study.get('primary_models')==list(PRIMARY_MODELS), 'Frozen primary models/order required')
    require(isinstance(subsets,dict) and set(subsets)==set(frozen.SUBSET_COUNTS), 'Exact subset inventory required')
    for key,count in frozen.SUBSET_COUNTS.items():
        ids=subsets[key]
        require(isinstance(ids,list) and len(ids)==len(set(ids))==count and set(ids)<=set(cases), 'Subset denominator '+key)
    require(summary.get('planned_slots')==1800 and summary.get('primary_holm_family_size')==21,
            'Original score denominator/family required')
    identities={}
    for s in slots:
        key=(s['model'],s['case_id'],s['condition'],s['phase'])
        require(key not in identities,'Duplicate scheduled endpoint');identities[key]=s
    selected={}
    for view in VIEWS:
        rows=[r for r in summary['paired_comparisons'] if r.get('view')==view and r.get('primary_family_member') is True]
        require(len(rows)==21,'Exactly21 frozen primary-family rows per view required')
        for row in rows:
            name=row['contrast'];model=row['model'];key=(view,model,name)
            if name==EXCLUDED:
                require(model==frozen.GEMMA,'Only frozen Gemma K10 contrast may be excluded')
                continue
            require(name in ELEMENTARY and model in PRIMARY_MODELS and key not in selected,'Unknown/duplicate elementary contrast')
            subset,a,b=ELEMENTARY[name];ids=sorted(subsets[subset])
            require(row['case_ids']==ids and row['n_pairs']==len(ids),'Matched frozen case IDs/denominator changed')
            require(all((model,c,*arm) in identities for c in ids for arm in (a,b)),'Scheduled contrast endpoint missing')
            selected[key]=row
    expected={(view,m,n) for view in VIEWS for m in PRIMARY_MODELS for n in ELEMENTARY}
    require(set(selected)==expected,'Exactly20 elementary contrasts in both views required')
    return identities,selected


def _audits(slots, audits, final, by_slot):
    index={s['slot_id']:s for s in slots};found={}
    for row in audits:
        if 'slot_id' not in row:
            require(row.get('condition') in ('k10_union','sfr_matched_quartet'),'Unknown non-slot audit')
            continue
        sid=row['slot_id'];view=row.get('view');key=(view,sid)
        require(sid in index and view in VIEWS and key not in found,'Unknown/duplicate slot audit')
        require(all(row.get(k)==index[sid][k] for k in ('case_id','model','condition','phase')),'Slot audit identity mismatch')
        found[key]=row
    require(set(found)=={(v,sid) for v in VIEWS for sid in index},'All scheduled slot grades in both views required')
    selections={}
    for view in VIEWS:
        selections[view]=h._view_records(slots,final,by_slot,view)
        for s in slots:
            sid=s['slot_id'];record,deps_ok=selections[view][sid];grade=found[(view,sid)]
            expected={'record_observed':record is not None,'provider_completed':h.completed(record),
                      'dependencies_completed':deps_ok,'eligible_completed':h.completed(record) and deps_ok}
            require(all(type(grade.get(k)) is bool and grade[k]==value for k,value in expected.items()),
                    'Audit availability/dependency mismatch')
            if not expected['eligible_completed']:
                require(grade.get('correct') is (None if s['condition']=='nl_source' else False),
                        'Ineligible frozen grade must remain its original unassessed/failure placeholder')
    return found,selections


def _truncated(row):
    if not row or row.get('model_outcome')!='truncated_max_output_tokens':return False
    require(row.get('issued') is True and row.get('terminal_valid') is True and row.get('response_status')=='incomplete'
            and row.get('error') is None,'Truncation requires a valid max-output terminal record')
    return True


def _classify(slots, view, selected, grades, final, requests):
    """Build recursively in the unchanged topological slot order, not by output text."""
    request_slots={q['slot_id'] for q in requests};roots={};available={};out={}
    for slot in slots:
        sid=slot['slot_id'];record,deps_ok=selected[sid];grade=grades[(view,sid)]
        dependencies=slot_dependencies(slot)
        require(all(d in roots for d in dependencies),'Dependency order or cycle invalid')
        own_truncated=_truncated(record)
        ancestors=sorted({r for d in dependencies for r in roots[d]})
        roots[sid]=sorted(set(ancestors+([sid] if own_truncated else [])))
        available[sid]=grade['eligible_completed']
        blockers=[d for d in dependencies if not available[d]]
        if own_truncated:
            lo=hi=0;reason='own_max_output_tokens_truncation'
        elif ancestors:
            lo=hi=0;reason='required_ancestor_max_output_tokens_truncation'
        elif grade['eligible_completed']:
            # Ancestor NL accounts have no standalone success endpoint. Their
            # completion matters only for availability of selected descendants.
            if slot['condition']=='nl_source':
                require(grade.get('correct') is None,'NL stage must remain unassessed')
                lo=hi=None;reason='unassessed_plain_language_stage'
            else:
                require(type(grade.get('correct')) is bool and type(grade.get('schema_valid')) is bool,
                        'Eligible target needs an explicit frozen Boolean grade')
                require(grade['schema_valid'] or grade['correct'] is False,'Malformed output cannot be graded correct')
                lo=hi=int(grade['correct'])
                reason='eligible_completed_scored' if grade['schema_valid'] else 'eligible_completed_malformed'
        else:
            lo,hi=0,1
            if h.completed(record):reason='completed_but_dependency_ineligible'
            elif record and record['model_outcome'] in ('http_429','operational_failure'):reason=record['model_outcome']
            else:
                last=final.get(sid)
                outcome=last.get('model_outcome') if last else None
                if outcome in ('not_issued_dependency_failed','not_issued_global_stop','issued_without_response'):reason=outcome
                elif sid in request_slots:reason='request_without_observed_response'
                elif last is None:reason='absent_final_outcome'
                else:raise ValueError('Unavailable observation lacks a classified reason')
        out[sid]={'slot_id':sid,'lower':lo,'upper':hi,'reason':reason,
                  'selected_attempt_id':record.get('attempt_id') if record else None,
                  'provider_completed':grade['provider_completed'],'eligible_completed':grade['eligible_completed'],
                  'dependency_blocker_slot_ids':blockers,'truncated_ancestor_slot_ids':ancestors,
                  'frozen_pipeline_correct':grade.get('correct')}
    return out


def _arm(rows):
    require(all(type(r['lower']) is int and type(r['upper']) is int and 0<=r['lower']<=r['upper']<=1 for r in rows),
            'Only elementary binary targets can be summarized')
    return {'n':len(rows),'fixed_correct':sum(r['lower']==r['upper']==1 for r in rows),
            'fixed_zero':sum(r['lower']==r['upper']==0 for r in rows),
            'unresolved':sum(r['lower']==0 and r['upper']==1 for r in rows),
            'provider_completed':sum(r['provider_completed'] for r in rows),
            'eligible_completed':sum(r['eligible_completed'] for r in rows),
            'reason_counts':dict(sorted(Counter(r['reason'] for r in rows).items())),
            'lower_successes':sum(r['lower'] for r in rows),'upper_successes':sum(r['upper'] for r in rows)}


def analyze(study, slots, result):
    """Return40 outer sensitivity rows; caller must authenticate all inputs first.

    result requires original frozen summary/audits plus merged_evidence with
    requests/responses/outcomes. This function checks logical bindings but does
    not certify raw SSE, ledger, source hashes, semantic grades or run closure.
    """
    require(isinstance(result,dict),'Authenticated result object required')
    summary=result['summary'];merged=result['merged_evidence']
    identities,contrasts=_metadata(study,slots,summary)
    _,final,by_slot,_=frozen.records(slots,merged['outcomes'],merged['responses'],merged['requests'])
    grades,selections=_audits(slots,result['audits'],final,by_slot)
    rows=[]
    for view in VIEWS:
        classified=_classify(slots,view,selections[view],grades,final,merged['requests'])
        for model in PRIMARY_MODELS:
            for name,(_,a,b) in ELEMENTARY.items():
                original=contrasts[(view,model,name)];pairs=[]
                for cid in original['case_ids']:
                    ar=classified[identities[(model,cid,*a)]['slot_id']]
                    br=classified[identities[(model,cid,*b)]['slot_id']]
                    require(type(ar['frozen_pipeline_correct']) is bool and type(br['frozen_pipeline_correct']) is bool,
                            'Frozen elementary pipeline grade missing')
                    pairs.append({'case_id':cid,'a':dict(ar),'b':dict(br),
                                  'difference_lower':br['lower']-ar['upper'],'difference_upper':br['upper']-ar['lower']})
                n=len(pairs);lower=sum(p['difference_lower'] for p in pairs);upper=sum(p['difference_upper'] for p in pairs)
                pipeline=sum(int(p['b']['frozen_pipeline_correct'])-int(p['a']['frozen_pipeline_correct']) for p in pairs)/n
                require(original['difference_b_minus_a']==pipeline,'Frozen paired point estimate/grades disagree')
                rows.append({'view':view,'model':model,'contrast':name,'case_ids':list(original['case_ids']),'n_pairs':n,
                    'a_endpoint':{'condition':a[0],'phase':a[1]},'b_endpoint':{'condition':b[0],'phase':b[1]},
                    'a_counts':_arm([p['a'] for p in pairs]),'b_counts':_arm([p['b'] for p in pairs]),
                    'outer_difference_b_minus_a':{'lower_numerator':lower,'upper_numerator':upper,'denominator':n,
                        'lower':lower/n,'upper':upper/n},
                    'unchanged_frozen_pipeline_difference_b_minus_a':pipeline,'case_pairs':pairs})
    return {'schema':'retrace.frontier-v6l-operational-missingness-sensitivity.v1',
            'status':'post_freeze_descriptive_outer_sensitivity','elementary_contrasts_per_view':20,
            'views':list(VIEWS),'contrast_rows':40,'scheduled_slots':1800,'rows':rows,
            'excluded_contrast':EXCLUDED,'new_inferential_tests':0,'new_model_observations':0,
            'input_hashes':{'study':digest(study),'slots':digest(slots),'summary':digest(summary),'audits':digest(result['audits']),
                **{k:digest(merged[k]) for k in ('requests','responses','outcomes')}},
            'scope':[
                'Outer logical sensitivity ranges, not confidence intervals, capability estimates, causal effects, forecasts or jointly attainable counterfactual outcomes.',
                'Eligible completed outputs retain their frozen Boolean grade, including known-zero malformed answers. Their output is never repaired or regraded.',
                'Own max-output truncation and recursively required truncated predecessors fix zero in the selected view; no output-budget increase is assumed.',
                'Other unavailable or dependency-ineligible observations receive[0,1]. Completed but ineligible outputs were not semantically assessed and are not relabeled malformed.',
                'Shared dependencies and changed hypothetical upstream content can constrain joint attainability; marginal interval arithmetic deliberately does not solve those constraints.',
                'K10 exact-family union is nonmonotone in added readings and is entirely excluded. No new selection, case denominator or frozen primary endpoint is introduced.',
                'First and eventual views remain separate; retry-mediated success does not replace the first attempt. Original unavailable-as-failed pipeline grades remain unchanged.',
                'Authentication/publication and proof of closure belong to a future explicit caller. This pure helper reads no files and makes no empirical claim.'
            ]}
