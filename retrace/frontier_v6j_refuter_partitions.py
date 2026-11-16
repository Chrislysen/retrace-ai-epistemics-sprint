"""Descriptive partitions of final frozen refuter audits; no model-text parsing."""
from copy import deepcopy
from .graph_identity_v6h import family_score

SCHEMA='retrace.frontier-v6j-refuter-partitions.v1'
VIEWS=('first_attempt','eventual')
SCOPES=('actual_initial_locked','baseline_unvetoed_structural','typed_veto_release')
CATEGORIES=('exact_authored_family','authored_family_consistent_partial_proposal',
            'contains_spurious_reading','explicit_abstention','invalid_or_unavailable')


def require(ok,why):
    if not ok:raise ValueError(why)


def flag(row,key,default=None):
    value=row.get(key,default);require(type(value) is bool,'explicit Boolean audit flag: '+key);return value


def partition_row(row,case):
    """Grade canonical sets offline, without changing admission or impact tests."""
    metadata={key:flag(row,key) for key in ('record_observed','provider_completed','eligible_completed','schema_valid','strict_bare_json')}
    candidates=row['candidates'];require(isinstance(candidates,list),'frozen candidate list')
    score=family_score(candidates,case['evaluation']['source_family'])
    require(score==row['family'] and score['expected_distinct']>0,'frozen family score must reproduce')
    located=flag(row,'source_locations_valid',False);abstained=flag(row,'abstained',False)
    compilation=row['compilation'];gaps=None
    if compilation is not None:
        require(isinstance(compilation,dict),'compiled metadata object')
        gaps=compilation['registry_coverage_gaps'];require(isinstance(gaps,list) and all(isinstance(x,str) for x in gaps),'registry inventory list')
    require(not (located and abstained),'proposal and abstention cannot overlap')
    admitted=metadata['eligible_completed'] and metadata['schema_valid']
    scoring_incomplete=False
    if located:
        require(admitted,'located proposal requires admitted schema')
        # Frozen _score_slot records location admission before canonical family
        # scoring. A caught bound/error can leave the initially empty candidates
        # and null compilation. Preserve that outcome; never recover candidates
        # from refuter_gate or reparse its raw output here.
        if compilation is None and not candidates:
            require(isinstance(row.get('error'),str) and row['error'].startswith('invalid_'),'incomplete post-gate scoring requires a recorded failure')
            scoring_incomplete=True;category='invalid_or_unavailable'
        elif compilation is None or not candidates:
            raise ValueError('inconsistent partially stored compiled proposal')
        elif score['exact_family']:category='exact_authored_family'
        elif score['spurious_distinct']:category='contains_spurious_reading'
        else:
            require(0<score['correct_distinct']<score['expected_distinct'],'nonempty proper authored-family subset')
            category='authored_family_consistent_partial_proposal'
    elif abstained:
        require(admitted and not candidates and compilation is None,'explicit admitted abstention')
        category='explicit_abstention'
    else:
        require(not candidates and compilation is None,'unlocated candidates must not be silently classified')
        category='invalid_or_unavailable'
    impact={}
    for scope in SCOPES:
        original=row['impact'][scope]
        impact[scope]={'available':flag(original,'available'),'consequential':flag(original,'consequential')}
        for key in ('withdrawal_consequential','hamming2_consequential'):
            if key in original:impact[scope][key]=flag(original,key)
    expected_exact=bool(located and score['exact_family'] and gaps==[])
    require(flag(row,'source_exact_family',False)==expected_exact,'frozen source-exact flag differs')
    require(flag(row,'source_aligned_consequential')==(expected_exact and impact['baseline_unvetoed_structural']['consequential']),'frozen strict consequential flag differs')
    require(flag(row,'typed_veto_release_source_aligned_consequential')==(expected_exact and impact['typed_veto_release']['consequential']),'frozen typed consequence flag differs')
    require(flag(row,'located_semantically_wrong_objection')==(located and not expected_exact),'frozen located non-exact flag differs')
    seed_exact=family_score(case['authored_seed_pool']['candidates'],case['evaluation']['source_family'])['exact_family']
    require(flag(row,'seed_exact_evaluation_only')==seed_exact,'frozen seed label differs')
    correct=abstained if seed_exact else row['source_aligned_consequential']
    require(flag(row,'correct')==correct and flag(row,'strict_correct')==(correct and metadata['strict_bare_json']),'frozen correctness differs')
    return {'slot_id':row['slot_id'],'case_id':case['id'],'model':row['model'],'view':row['view'],
            'partition':case['partition'],'category':category,'seed_exact_evaluation_only':seed_exact,
            **metadata,'source_locations_valid':located,'family':deepcopy(score),
            'source_located_proposal_scoring_incomplete':scoring_incomplete,
            'registry_coverage':{'available':gaps is not None,'gaps':deepcopy(gaps)},
            'frozen_impact_flags':impact,
            'frozen_metrics':{'source_exact_family':expected_exact,
                'source_aligned_consequential':row['source_aligned_consequential'],
                'typed_veto_release_source_aligned_consequential':row['typed_veto_release_source_aligned_consequential'],
                'source_located_nonexact_family':row['located_semantically_wrong_objection'],
                'correct':row['correct'],'strict_correct':row['strict_correct']}}


def summarize(rows):
    partial=[r for r in rows if r['category']=='authored_family_consistent_partial_proposal']
    return {'scheduled':len(rows),'categories':{key:sum(r['category']==key for r in rows) for key in CATEGORIES},
            'provider_completed':sum(r['provider_completed'] for r in rows),
            'schema_valid':sum(r['schema_valid'] for r in rows),
            'strict_bare_json':sum(r['strict_bare_json'] for r in rows),
            'registry_gap_inventory_unavailable':sum(not r['registry_coverage']['available'] for r in rows),
            'registry_gap_inventory_nonempty':sum(bool(r['registry_coverage']['gaps']) for r in rows),
            'source_located_proposal_scoring_incomplete':sum(r['source_located_proposal_scoring_incomplete'] for r in rows),
            'frozen_source_aligned_consequential':sum(r['frozen_metrics']['source_aligned_consequential'] for r in rows),
            'proper_subset_impact':{scope:{'partial_proposals':len(partial),
                'consequential':sum(r['frozen_impact_flags'][scope]['consequential'] for r in partial),
                'fully_available':sum(r['frozen_impact_flags'][scope]['available'] for r in partial),
                'unavailable_or_incomplete':sum(not r['frozen_impact_flags'][scope]['available'] for r in partial),
                'consequential_with_incomplete_audit':sum(r['frozen_impact_flags'][scope]['consequential'] and not r['frozen_impact_flags'][scope]['available'] for r in partial)} for scope in SCOPES}}


def analyze_refuter_partitions(corpus,study,graded_audits,*,require_full_design=True):
    ids=list(study['all_case_ids']);models=list(study['primary_models'])
    require(len(ids)==len(set(ids)) and len(models)==len(set(models)),'unique planned cases/models')
    require((len(ids)==60 and len(models)==5) if require_full_design else bool(ids and models),'complete 60-case five-model design')
    cases={c['id']:c for c in corpus['cases']};require(set(ids)<=set(cases),'all planned corpus cases')
    selected={}
    for row in graded_audits:
        if row.get('condition')!='adversarial_refuter':continue
        require(row['case_id'] in ids and row['model'] in models and row['view'] in VIEWS and row['phase']=='counter_read','unexpected refuter slot')
        key=(row['view'],row['model'],row['case_id']);require(key not in selected,'duplicate refuter audit');selected[key]=row
    require(len(selected)==len(ids)*len(models)*2,'all planned refuter outcomes required')
    rows=[partition_row(selected[(v,m,c)],cases[c]) for v in VIEWS for m in models for c in ids]
    summaries={}
    for view in VIEWS:
        chosen=[r for r in rows if r['view']==view]
        summaries[view]={'overall':summarize(chosen),
            'by_model':{m:summarize([r for r in chosen if r['model']==m]) for m in models},
            'by_partition':{p:summarize([r for r in chosen if r['partition']==p]) for p in sorted({r['partition'] for r in chosen})},
            'by_seed':{label:summarize([r for r in chosen if r['seed_exact_evaluation_only']==value]) for label,value in (('faithful',True),('deficient',False))}}
    return {'schema':SCHEMA,'analysis_role':'Post-freeze descriptive audit prepared during execution; outside the 21 primary tests.',
            'planned_cases':len(ids),'primary_models':models,'case_ids_in_frozen_order':ids,
            'planned_slots_per_view':len(ids)*len(models),'views':list(VIEWS),'rows':rows,'summaries':summaries,
            'frozen_endpoint_unchanged':True,'source_of_candidates':'Final authenticated frozen graded audits only. Canonical Boolean identities are recomputed; no new parsing, repair, proposal generation or impact-engine rerun.',
            'terminology':'A partial proposal is authored-family-consistent, not verified textual entailment. Any spurious reading means outside the authored canonical family, not an independent proof of textual falsehood.',
            'impact_scope':'Frozen flags only: actual initial vetoes; unvetoed structural withdrawal/enable-withdraw audit; and separate typed veto-release-plus-withdrawal diagnostic. Availability is reported separately from a positive witness flag.',
            'registry_scope':'The frozen refuter gate rejects inventory gaps atomically. A failed or abstained proposal has no admitted compilation: missing gap information is unavailable, not an empty inventory.',
            'renamed_presentation_field':{'source_located_nonexact_family':'located_semantically_wrong_objection'},
            'scope':'All planned outcomes retained in both views. No new significance tests, confidence intervals, replacement primary endpoint or selected examples. Duplicate branches are counted by the frozen canonical distinct-family score.'}
