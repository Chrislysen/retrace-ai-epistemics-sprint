"""Separate observed extraction diagnostics from authored ambiguity controls."""
from copy import deepcopy

from .ambiguity_v3_sessions import CONDITIONS
from .compact_graph import parse_compact_output, serialize_compact
from .core import analyze, validate_case
from .stress import analyze_stress


def canonical(graph):
    return serialize_compact(graph)


def factual_answer(graph,predicate):
    """Project a frozen source-factual predicate from THIS candidate, never gold."""
    validate_case(graph)
    evidence={r['id']:r for r in graph['evidence']}
    claims={r['id']:r for r in graph['claims']}
    kind=predicate['kind']
    if kind=='direct_parent':
        child=evidence[predicate['child']]
        return child['kind']=='copy' and predicate['parent']in child['parents']
    if kind=='exact_route':
        routes=claims[predicate['claim']]['supports']
        return any(set(r)==set(predicate['items'])for r in routes)
    if kind=='all_routes_contain':
        routes=claims[predicate['claim']]['supports']
        return bool(routes) and all(predicate['item']in r for r in routes)
    if kind=='ancestor':
        deps={r['id']:list(r['parents'])for r in graph['evidence']}
        deps.update({r['id']:[x for route in r['supports']for x in route]for r in graph['claims']})
        deps.update({r['id']:r['requires']for r in graph['decisions']})
        seen=set();stack=list(deps[predicate['child']])
        while stack:
            node=stack.pop()
            if node==predicate['ancestor']:
                return True
            if node not in seen:
                seen.add(node);stack.extend(deps[node])
        return False
    raise ValueError('Unknown frozen factual predicate')


def candidate_brief(packet,candidates,with_constraints=True):
    """No authored interpretation or actual oracle answer enters this brief."""
    public=packet['public'];question=packet['hidden']['author_clarification_oracle']
    return {'id':public['id'],'title':public['title'],
            'prose':'\n\n'.join(d['text']for d in public['documents']),
            'candidates':deepcopy(candidates),
            'target_decisions':list(public['registry']['decisions']),
            'allowed_withdrawals':list(public['registry']['evidence']),
            'documents':deepcopy(packet['source_context']['documents']),
            'provenance_constraints':deepcopy(packet['source_context']['provenance_constraints'])if with_constraints else [],
            'questions':[{'id':question['question_id'],'label':question['question'],'cost':question['cost'],
                          'answers':{c['id']:factual_answer(c['graph'],question['factual_predicate'])for c in candidates}}]}


def _reference(packet):
    hidden=packet['hidden']
    return hidden['allowed_interpretations'][hidden['author_actual_interpretation_index']]


def _agreement(result,expected):
    states={did:r['state']for did,r in result['decision_states'].items()}
    unanimous={did:state=='robust_supported' for did,state in states.items()if state!='needs_review'}
    return {'states':states,'unanimous_labels':unanimous,
            'unanimous_correct':sum(value==expected[did]for did,value in unanimous.items()),
            'unanimous_wrong':sum(value!=expected[did]for did,value in unanimous.items()),
            'disputed':sum(s=='needs_review'for s in states.values()),
            'target_count':len(expected)}


def _pool(packet,candidates,withdrawals):
    if not candidates:
        return {'status':'no_admitted_candidates','candidate_count':0,'oracle_graph_covered':False}
    actual=_reference(packet)
    expected={did:r['usable']for did,r in analyze(actual,withdrawals)['decisions'].items()}
    result={'status':'analyzed','candidate_count':len(candidates),
            'distinct_graph_count':len({canonical(c['graph'])for c in candidates}),
            'oracle_graph_covered':any(canonical(c['graph'])==canonical(actual)for c in candidates),
            'withdrawals':list(withdrawals),'reference_labels_scoring_only':expected}
    for constraints,label in [(False,'without_source_constraints'),(True,'with_source_constraints')]:
        brief=candidate_brief(packet,candidates,constraints)
        stress=analyze_stress(brief,{'scenario_withdrawals':withdrawals})
        result[label]={'agreement':_agreement(stress,expected),'coverage':stress['coverage'],
                      'provenance_checks':stress['provenance_checks'],
                      'minimum_distinguishing':{d:r['minimum_distinguishing']for d,r in stress['decision_witnesses'].items()},
                      'next_question':stress['next_question'],
                      'worst_case_question_cost':stress['consensus']['clarification']['worst_case_cost']}
    question=packet['hidden']['author_clarification_oracle']
    result['factual_question_candidate_answers']={c['id']:factual_answer(c['graph'],question['factual_predicate'])for c in candidates}
    result['oracle_answer_check']={'author_answer':question['actual_answer'],
        'was_question_requested':result['with_source_constraints']['next_question']is not None,
        'note':'Forced factual-answer consistency diagnostic; only a requested question represents the planner choosing to ask.'}
    try:
        following=analyze_stress(candidate_brief(packet,candidates,True),
            {'scenario_withdrawals':withdrawals,'answers':{question['question_id']:question['actual_answer']}})
        result['oracle_answer_check'].update(status='retained_candidates',retained_ids=following['candidate_ids'],
            agreement=_agreement(following,expected),
            oracle_graph_covered=any(canonical(c['graph'])==canonical(actual)for c in candidates if c['id']in following['candidate_ids']))
    except ValueError as exc:
        if 'contradict all supplied candidates'not in str(exc):
            raise
        result['oracle_answer_check'].update(status='candidate_set_exhausted',retained_ids=[],oracle_graph_covered=False)
    return result


def evaluate_case(packet,candidates):
    """All admitted candidates remain, including structurally wrong interpretations."""
    return {'case_id':packet['public']['id'],
        'singleton_baselines':{c['id']:{'current':_pool(packet,[c],[]),
            'challenge':_pool(packet,[c],packet['hidden']['challenge_withdrawals'])}for c in candidates},
        'union':{'current':_pool(packet,candidates,[]),
                 'challenge':_pool(packet,candidates,packet['hidden']['challenge_withdrawals'])}}


def validate_packets(packets):
    assert len(packets)==10 and len({p['public']['id']for p in packets})==10
    for index,p in enumerate(packets):
        allowed=p['hidden']['allowed_interpretations']
        assert len(allowed)==(2 if index<6 else 1)
        assert len({canonical(g)for g in allowed})==len(allowed)
        for g in allowed:
            validate_case(g)
            assert {k:sorted(n['id']for n in g[k])for k in ('evidence','claims','decisions')}=={k:sorted(v)for k,v in p['public']['registry'].items()}
        oracle=p['hidden']['author_clarification_oracle']
        assert factual_answer(_reference(p),oracle['factual_predicate'])is oracle['actual_answer']
        text='\n'.join(d['text']for d in p['public']['documents'])
        assert all(c['source_quote']in text for c in p['source_context']['provenance_constraints'])
        controls=[{'id':str(i),'graph':g}for i,g in enumerate(allowed)]
        checked=analyze_stress(candidate_brief(p,controls))
        assert checked['coverage']['retained_constraint_violations_count']==0
    k3=analyze_stress(candidate_brief(packets[5],[{'id':str(i),'graph':g}for i,g in enumerate(packets[5]['hidden']['allowed_interpretations'])]))
    assert all(r['minimum_distinguishing']['k']==3 for r in k3['decision_witnesses'].values())
    irrelevant=analyze_stress(candidate_brief(packets[4],[{'id':str(i),'graph':g}for i,g in enumerate(packets[4]['hidden']['allowed_interpretations'])]))
    assert irrelevant['next_question']is None and irrelevant['consensus']['clarification']['worst_case_cost']==0
    return True


def constructed_controls(packets):
    result=[]
    for packet in packets:
        hidden=packet['hidden'];allowed=hidden['allowed_interpretations']
        row={'case_id':packet['public']['id'],'kind':'authored_offline_control_not_model_output',
             'allowed_interpretation_pool':evaluate_case(packet,[{'id':f'authored-{i}','graph':g}for i,g in enumerate(allowed)])}
        mutant=hidden['constructed_common_omission_graph']
        if mutant:
            row['identical_omission_pool']=evaluate_case(packet,[{'id':'mutant-a','graph':mutant},{'id':'mutant-b','graph':deepcopy(mutant)}])
            row['note']='Duplicating one constructed error is not independent model evidence.'
        result.append(row)
    return result


def _rate(numerator,denominator):
    return numerator/denominator if denominator else None


def _stage_aggregates(pools,total_cases):
    available=[p for p in pools if p['status']=='analyzed']
    requested=[p for p in available if p['oracle_answer_check']['was_question_requested']]
    resolved=[p for p in requested if p['oracle_answer_check']['status']=='retained_candidates'
              and p['oracle_answer_check']['agreement']['disputed']==0
              and p['oracle_answer_check']['agreement']['unanimous_wrong']==0
              and p['oracle_answer_check']['agreement']['unanimous_correct']==p['oracle_answer_check']['agreement']['target_count']]
    covered=sum(p['oracle_graph_covered']for p in available)
    disagreed=sum(p['with_source_constraints']['agreement']['disputed']>0 for p in available)
    wrong=sum(p['with_source_constraints']['agreement']['unanimous_wrong']>0 for p in available)
    return {'case_denominator':total_cases,'cases_with_candidates':len(available),
        'cases_with_decision_disagreement':disagreed,'decision_disagreement_case_rate':_rate(disagreed,total_cases),
        'decision_disagreement_rate_among_available':_rate(disagreed,len(available)),
        'cases_with_wrong_unanimous_label':wrong,'wrong_unanimity_case_rate':_rate(wrong,total_cases),
        'wrong_unanimity_rate_among_available':_rate(wrong,len(available)),
        'oracle_graph_covered_cases':covered,'oracle_graph_coverage_rate':_rate(covered,total_cases),
        'planner_requested_question_cases':len(requested),
        'correct_full_target_resolution_after_requested_question':len(resolved),
        'resolution_rate_among_requested':_rate(len(resolved),len(requested)),
        'forced_unrequested_oracle_checks':sum(not p['oracle_answer_check']['was_question_requested']for p in available),
        'oracle_answer_exhausted_candidate_set_cases':sum(p['oracle_answer_check']['status']=='candidate_set_exhausted'for p in available),
        'requested_oracle_exhaustions':sum(p['oracle_answer_check']['status']=='candidate_set_exhausted'for p in requested),
        'forced_unrequested_oracle_exhaustions':sum(p['oracle_answer_check']['status']=='candidate_set_exhausted' and not p['oracle_answer_check']['was_question_requested']for p in available),
        'note':'Current and challenge are separately defined views of the same cases, not independent observations. Missing candidate cases are unavailable, not correct. Both scheduled-case event frequencies and available-case rates are explicit. Unrequested forced oracle checks are not planner interventions.'}


def aggregate_observed(packets,observed):
    by_id={r['case_id']:r for r in observed}
    both=[r for r in observed if r['union']['current'].get('candidate_count')==2]
    result={'case_denominator':len(packets),'both_admitted_cases':len(both),
            'both_admitted_rate':_rate(len(both),len(packets)),
            'both_admitted_graph_disagreement_cases':sum(r['union']['current']['distinct_graph_count']>1 for r in both),
            'graph_disagreement_rate_among_both_admitted':_rate(sum(r['union']['current']['distinct_graph_count']>1 for r in both),len(both)),
            'union':{stage:_stage_aggregates([r['union'][stage]for r in observed],len(packets))for stage in ('current','challenge')},
            'singleton_baselines':{condition:{stage:_stage_aggregates([r['singleton_baselines'][condition][stage]
                       for r in observed if condition in r['singleton_baselines']],len(packets))for stage in ('current','challenge')}for condition in CONDITIONS}}
    omission_cases=[p for p in packets if p['source_context']['provenance_constraints']]
    details=[]
    for p in omission_cases:
        r=by_id[p['public']['id']];pool=r['union']['current']
        if pool.get('candidate_count')!=2:
            details.append({'case_id':p['public']['id'],'both_admitted':False,'shared_missing_constraint_ids':[]})
            continue
        checks=pool['with_source_constraints']['provenance_checks']
        shared=[c['id']for c in checks if len(c['by_candidate'])==2 and all(not x['satisfied']for x in c['by_candidate'].values())]
        details.append({'case_id':p['public']['id'],'both_admitted':True,'shared_missing_constraint_ids':shared,
            'with_constraint_warning':pool['with_source_constraints']['coverage']['status']=='source_constraint_conflict',
            'without_constraint_warning':pool['without_source_constraints']['coverage']['status']=='source_constraint_conflict',
            'current_wrong_unanimity':pool['with_source_constraints']['agreement']['unanimous_wrong']>0,
            'challenge_wrong_unanimity':r['union']['challenge']['with_source_constraints']['agreement']['unanimous_wrong']>0})
    common=[r for r in details if r['shared_missing_constraint_ids']]
    result['observed_shared_omission']={'source_case_denominator':len(omission_cases),'both_admitted_source_cases':sum(r['both_admitted']for r in details),
        'common_omission_cases':len(common),'common_omission_rate_among_both_admitted_source_cases':_rate(len(common),sum(r['both_admitted']for r in details)),
        'with_source_constraint_detected_cases':sum(r['with_constraint_warning']for r in common),
        'without_source_constraint_detected_cases':sum(r['without_constraint_warning']for r in common),
        'with_source_constraint_detection_rate':_rate(sum(r['with_constraint_warning']for r in common),len(common)),
        'without_source_constraint_detection_rate':_rate(sum(r['without_constraint_warning']for r in common),len(common)),
        'details':details,
        'note':'A common omission requires both actual admitted outputs to violate the SAME supplied ancestry constraint. No common omissions means detection rates null, not a manufactured success. Constraints flag defects but do not repair decisions; all constraints are author-supplied from public source text.'}
    return result


def score_responses(packets,responses):
    """Every planned slot is counted; incomplete and absent outputs stay distinct."""
    validate_packets(packets)
    registry={(p['public']['id'],c):p for p in packets for c in CONDITIONS}
    seen={}
    for response in responses:
        key=(response['case_id'],response['condition'])
        if key not in registry or key in seen or response.get('phase','final')!='final':
            raise ValueError('Unknown, duplicate or wrong-phase response')
        seen[key]=response
    outcomes=[];by_case={p['public']['id']:[]for p in packets}
    for key,packet in registry.items():
        response=seen.get(key)
        row={'case_id':key[0],'condition':key[1],'received':response is not None,
             'valid':False,'strict_valid':False,'allowed_interpretation':False,'oracle_graph_exact':False}
        if response is None:
            row.update(status='unissued_or_missing',error=None)
        elif response.get('error') or ('response_status'in response and response['response_status']!='completed'):
            row.update(status='operational_failure',error=response.get('error') or 'response_not_completed')
        else:
            try:
                parsed=parse_compact_output(response.get('output_text'),packet['public']['registry'])
                g=parsed['graph'];norm=canonical(g)
                row.update(status='admitted',valid=True,strict_valid=parsed['strict_bare'],graph=g,
                    allowed_interpretation=norm in {canonical(v)for v in packet['hidden']['allowed_interpretations']},
                    oracle_graph_exact=norm==canonical(_reference(packet)))
                by_case[key[0]].append({'id':key[1],'graph':g})
            except (ValueError,TypeError,KeyError)as exc:
                row.update(status='schema_invalid',error=str(exc))
        outcomes.append(row)
    groups={condition:{'scheduled':10,'received':sum(r['received']for r in outcomes if r['condition']==condition),
        **{key:sum(r[key]for r in outcomes if r['condition']==condition)for key in ('valid','strict_valid','allowed_interpretation','oracle_graph_exact')},
        **{status:sum(r['status']==status for r in outcomes if r['condition']==condition)for status in ('operational_failure','schema_invalid','unissued_or_missing')}}for condition in CONDITIONS}
    observed=[evaluate_case(p,by_case[p['public']['id']])for p in packets]
    return {'schema':'retrace.ambiguity-v3-scores','scheduled':20,'received':len(seen),'groups':groups,
            'outcomes':outcomes,'observed_candidate_audits':observed,'aggregates':aggregate_observed(packets,observed),
            'scope':'Observed model outputs only in outcomes/candidate audits. Directed temperature-zero prompts are not unbiased stochastic samples. Authored controls are not included here.'}
