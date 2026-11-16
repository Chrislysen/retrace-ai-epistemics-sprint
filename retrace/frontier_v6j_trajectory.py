"""Post-freeze descriptive K10 prefixes over final authenticated graded audits.

This module performs no parsing of model text, no provider calls, no repairs,
no selection of successful cases, and no statistical hypothesis tests.
"""
from .graph_identity_v6h import graph_key, family_score
from .tiered_v6h import family_supervaluation
from .frontier_v6h_eval import exclusions

MODEL='gemma-4-31b-it'
VIEWS=('first_attempt','eventual')
SCHEMA='retrace.frontier-v6j-k10-trajectory.v1'


def require(ok,why):
    if not ok:raise ValueError(why)


def inventory(graph):
    return {kind:sorted(row['id'] for row in graph[kind]) for kind in ('evidence','claims','decisions')}


def signature(graphs,case):
    """Use original graph flags and actual initial document/passage vetoes."""
    if not graphs:return {'available':False,'reason':'empty_prefix','decisions':None}
    wanted={kind:sorted(case['public']['registry'][kind]) for kind in ('evidence','claims','decisions')}
    if any(inventory(graph)!=wanted for graph in graphs):
        return {'available':False,'reason':'incompatible_typed_inventory','decisions':None}
    try:
        value=family_supervaluation(graphs,**exclusions(case,'initial'))
    except ValueError as error:
        # Fixed engine limits are not relaxed for this descriptive supplement.
        return {'available':False,'reason':'fixed_engine_rejected_or_bound_exceeded','detail':str(error),'decisions':None}
    return {'available':True,'reason':None,'decisions':{did:{'box_supported':row['box_supported'],'diamond_supported':row['diamond_supported']} for did,row in sorted(value['decisions'].items())}}


def monotonic(previous,current):
    if previous is None or not previous['decision_signature']['available'] or not current['decision_signature']['available']:
        return {'checked':False,'reason':'requires_two_compatible_nonempty_prefixes','violations':[]}
    a=previous['decision_signature']['decisions'];b=current['decision_signature']['decisions']
    require(set(a)==set(b),'aligned decision inventory')
    violations=[]
    for did in a:
        if not a[did]['box_supported'] and b[did]['box_supported']:violations.append({'decision':did,'kind':'box_became_true'})
        if a[did]['diamond_supported'] and not b[did]['diamond_supported']:violations.append({'decision':did,'kind':'diamond_became_false'})
    return {'checked':True,'compared_prefix':previous['prefix_length'],'box_cannot_increase':not any(v['kind']=='box_became_true' for v in violations),'diamond_cannot_decrease':not any(v['kind']=='diamond_became_false' for v in violations),'violations':violations}


def analyze_trajectories(corpus,study,graded_audits,*,require_full_design=True):
    """All twelve frozen cases, both fixed views; corpus gold is evaluation-only.

    Admission matches frozen K10 exactly: include row.candidates iff
    row.strict_bare_json. Completion/schema flags are separately tabulated,
    never substituted as a new gate or used to repair an admitted reading.
    """
    ids=list(study['subsets']['k10_gemma'])
    require(len(ids)==len(set(ids)) and (len(ids)==12 if require_full_design else bool(ids)),'exact unique twelve-case K10 subset')
    cases={c['id']:c for c in corpus['cases']};require(set(ids)<=set(cases),'all selected cases present')
    selected={};unions={}
    for row in graded_audits:
        if row.get('model')!=MODEL or row.get('case_id') not in ids:continue
        cond=row.get('condition');view=row.get('view')
        if cond not in ('sample_graph','k10_union'):continue
        require(view in VIEWS,'known fixed trajectory view')
        if cond=='sample_graph':
            require(row['phase'] in {f'draw_{n:02}' for n in range(1,11)},'ten exact draw phases')
            key=(view,row['case_id'],row['phase']);require(key not in selected,'duplicate graded draw')
            selected[key]=row
        else:
            key=(view,row['case_id']);require(key not in unions and row['phase']=='union','one frozen union audit')
            unions[key]=row
    require(len(selected)==len(ids)*20 and len(unions)==len(ids)*2,'complete planned graded draws and unions required')
    trajectories=[]
    for view in VIEWS:
        for cid in ids:
            case=cases[cid];reference=case['evaluation']['source_family'];expected=family_score([],reference)['expected_distinct'];require(expected>0,'nonempty authored family')
            cumulative=[];prefixes=[];unique={};counts={'provider_completed_draws':0,'eligible_completed_draws':0,'schema_valid_draws':0,'strict_bare_json_draws':0,'strict_valid_draws':0}
            for k in range(1,11):
                draw=selected[(view,cid,f'draw_{k:02}')]
                for field,counter in (('provider_completed','provider_completed_draws'),('eligible_completed','eligible_completed_draws'),('schema_valid','schema_valid_draws'),('strict_bare_json','strict_bare_json_draws')):
                    require(type(draw[field])is bool,'explicit frozen admission metadata');counts[counter]+=draw[field]
                counts['strict_valid_draws']+=draw['schema_valid'] and draw['strict_bare_json']
                require(isinstance(draw['candidates'],list),'graded candidate list')
                additions=draw['candidates'] if draw['strict_bare_json'] else []
                require(len(additions)<=1,'frozen single-graph draw capacity')
                cumulative.extend(additions)
                for row in additions:
                    graph=row.get('graph',row);unique.setdefault(graph_key(graph),graph)
                score=family_score(cumulative,reference)
                current={'prefix_length':k,'last_graded_slot_id':draw['slot_id'],'planned_draws_so_far':k,**counts,'retained_candidate_occurrences':len(cumulative),'distinct_admitted_candidates':len(unique),'duplicate_candidate_occurrences':len(cumulative)-len(unique),'draw_without_retained_candidate_count':k-len(cumulative),'family':score,'expected_family_capacity':{'expected_distinct':expected,'maximum_distinct_under_single_graph_format':k,'recall_upper_bound_from_output_capacity':min(k,expected)/expected,'exact_family_capacity_possible':expected<=k,'scope':'Format capacity, not estimated accuracy or a probability.'},'decision_signature':signature([row.get('graph',row) for row in cumulative],case)}
                current['monotonicity']=monotonic(prefixes[-1] if prefixes else None,current)
                prefixes.append(current)
            union=unions[(view,cid)]
            require(prefixes[-1]['family']==union['family'],'prefix10 family score must reproduce frozen union audit')
            require(prefixes[-1]['strict_valid_draws']==union['strict_valid_draws'] and union['scheduled_draws']==10,'prefix10 admission counts match frozen union')
            require(union['structural_k10_ceiling']==(expected>10),'frozen expected-family capacity ceiling')
            trajectories.append({'case_id':cid,'view':view,'prefixes':prefixes,'prefix10_matches_frozen_union':True,'state_name':'initial','state_exclusions':exclusions(case,'initial')})
    checks=[p['monotonicity'] for t in trajectories for p in t['prefixes'] if p['monotonicity']['checked']]
    return {'schema':SCHEMA,'model':MODEL,'case_ids_in_frozen_order':ids,'planned_cases':len(ids),'draws_per_case':10,'views':list(VIEWS),'trajectories':trajectories,'prefix10_all_match_frozen_unions':True,'monotonicity':{'compatible_nonempty_adjacent_comparisons':len(checks),'violations':sum(len(c['violations']) for c in checks),'scope':'A finite set property under reading addition, not evidence of correct extraction.'},'analysis_role':'Post-freeze descriptive supplement prepared during execution; outside the 21 primary tests.','source_of_candidates':'Final frozen graded audits only; no authored seed substitution or parsing/repair of output text.','signature_scope':'Box and Diamond quantify supplied candidate readings and named unknown-ancestry completions under original flags plus actual initial vetoes. Inventory incompatibility and engine limits are explicit unavailable.','scope':'All 12 planned K10 cases and all ten ordered draws. Authored-family labels grade descriptions offline only. No new p-values, confidence intervals, causal claim, stopping rule or showcase selection.'}
