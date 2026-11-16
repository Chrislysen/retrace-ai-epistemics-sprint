"""Invented journals/grades only; frozen IDs and subset metadata, no live answers."""
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import unittest

from retrace import frontier_v6l_missingness as m
from retrace import frontier_v6h_eval as h
from retrace import frontier_v6i_eval as v
from retrace.adaption_v6h import PRIMARY_MODELS
from tests.test_frontier_v6i_eval import journals

ROOT=Path(__file__).resolve().parents[1]
STUDY=json.loads((ROOT/'data/frontier-v6i-design.json').read_text(encoding='utf-8'))
SLOTS=json.loads((ROOT/'data/frontier-v6i-sessions.json').read_text(encoding='utf-8'))
# Preserve only the prospective matrix/dependencies; every prompt/output here is invented.
for slot in SLOTS:
    slot['instructions']='Invented test-only instruction.'
    if not slot.get('input_from') or slot['input_from']['mode']!='assistant_output_only':slot['input']='Invented public fixture.'
MODEL=v.GEMMA


def sid(condition,phase,case=None,model=MODEL):
    subset='nl_projection' if condition in ('strict_source_ir','nl_source','nl_projection') else 'temporal'
    case=case or STUDY['subsets'][subset][0]
    return next(s['slot_id'] for s in SLOTS if (s['model'],s['case_id'],s['condition'],s['phase'])==(model,case,condition,phase))


def refresh(result, successes=()):
    merged=result['merged_evidence'];_,final,by_slot,_=v.records(SLOTS,merged['outcomes'],merged['responses'],merged['requests'])
    audits=[];idx={}
    for view in m.VIEWS:
        selected=h._view_records(SLOTS,final,by_slot,view)
        for s in SLOTS:
            record,deps=selected[s['slot_id']];eligible=h.completed(record) and deps
            grade={k:s[k] for k in ('slot_id','case_id','model','condition','phase')}
            grade.update(view=view,record_observed=record is not None,provider_completed=h.completed(record),
                dependencies_completed=deps,eligible_completed=eligible,schema_valid=False,
                correct=None if s['condition']=='nl_source' else False)
            if eligible and (view,s['slot_id']) in successes:grade.update(schema_valid=True,correct=True)
            audits.append(grade);idx[(view,s['slot_id'])]=grade
    pairs=[]
    for view in m.VIEWS:
        for model in PRIMARY_MODELS:
            for name,(subset,a,b) in m.ELEMENTARY.items():
                ids=sorted(STUDY['subsets'][subset])
                av=[idx[(view,sid(*a,c,model))]['correct'] for c in ids]
                bv=[idx[(view,sid(*b,c,model))]['correct'] for c in ids]
                pairs.append({'view':view,'model':model,'contrast':name,'case_ids':ids,'n_pairs':len(ids),
                    'primary_family_member':True,'difference_b_minus_a':sum(int(b)-int(a) for a,b in zip(av,bv))/len(ids)})
        pairs.append({'view':view,'model':MODEL,'contrast':m.EXCLUDED,'primary_family_member':True})
    result['audits']=audits
    result['summary']={'planned_slots':1800,'primary_holm_family_size':21,'paired_comparisons':pairs}
    return result


def fixture(*,truncated=(),operational=(),retry_first=(),successes=()):
    f,a,q,_=journals(SLOTS,{},truncated=set(truncated)|set(operational),retry_first=retry_first)
    for row in a:
        if row['slot_id'] in operational:
            row.update(terminal_valid=False,model_outcome='operational_failure',failure_scope='slot',
                       response_status=None,error='timeout',http_status=None,usage=None,output_text='')
    by_aid={r['attempt_id']:r for r in a}
    for row in f:
        if row.get('attempt_id'):row.update(by_aid[row['attempt_id']])
    return refresh({'merged_evidence':{'outcomes':f,'responses':a,'requests':q}},successes)


def contrast(out,name='nl_projection_minus_strict_ir',view='first_attempt'):
    return next(r for r in out['rows'] if (r['model'],r['contrast'],r['view'])==(MODEL,name,view))


def pair(out,condition,phase,view='first_attempt'):
    target=sid(condition,phase)
    return next(p[arm] for r in out['rows'] if r['view']==view for p in r['case_pairs'] for arm in ('a','b') if p[arm]['slot_id']==target)


class MissingnessTests(unittest.TestCase):
    def analyze(self,result):return m.analyze(STUDY,SLOTS,result)

    def test_all40_rows_exact_matched_ids_and_no_mutation_or_inference(self):
        result=fixture();before=deepcopy(result);out=self.analyze(result)
        self.assertEqual(result,before);self.assertEqual(len(out['rows']),40)
        self.assertEqual(out['elementary_contrasts_per_view'],20)
        self.assertFalse(any(r['contrast']==m.EXCLUDED for r in out['rows']))
        for row in out['rows']:
            expected=sorted(STUDY['subsets'][m.ELEMENTARY[row['contrast']][0]])
            self.assertEqual(row['case_ids'],expected);self.assertEqual(row['n_pairs'],len(expected))
            self.assertEqual(row['outer_difference_b_minus_a']['lower'],0)
            self.assertEqual(row['outer_difference_b_minus_a']['upper'],0)
            self.assertNotIn('p_two_sided_exact',row);self.assertNotIn('confidence_interval',row)
        self.assertEqual(out['new_inferential_tests'],0)

    def test_eligible_malformed_is_known_zero_not_missing(self):
        out=self.analyze(fixture());row=pair(out,'strict_source_ir','extract')
        self.assertEqual((row['lower'],row['upper'],row['reason']),(0,0,'eligible_completed_malformed'))
        self.assertTrue(row['provider_completed']);self.assertTrue(row['eligible_completed'])

    def test_known_correct_and_known_failure_collapse_to_pipeline_difference(self):
        target=sid('nl_projection','project');result=fixture(successes={(v,target) for v in m.VIEWS})
        row=contrast(self.analyze(result));bound=row['outer_difference_b_minus_a']
        self.assertEqual((bound['lower_numerator'],bound['upper_numerator'],bound['denominator']),(1,1,30))
        self.assertEqual(bound['lower'],row['unchanged_frozen_pipeline_difference_b_minus_a'])

    def test_own_truncation_and_recursive_required_truncation_stay_fixed_zero(self):
        init=sid('commitment','hist_init');out=self.analyze(fixture(truncated={init}))
        for view in m.VIEWS:
            row=pair(out,'commitment','hist_withdrawn',view)
            self.assertEqual((row['lower'],row['upper']),(0,0))
            self.assertEqual(row['truncated_ancestor_slot_ids'],[init])
            self.assertEqual(row['reason'],'required_ancestor_max_output_tokens_truncation')
        own=sid('strict_source_ir','extract');row=pair(self.analyze(fixture(truncated={own})),'strict_source_ir','extract')
        self.assertEqual((row['lower'],row['upper'],row['reason']),(0,0,'own_max_output_tokens_truncation'))

    def test_failed_parent_zero_placeholder_is_not_semantic_false(self):
        parent=sid('nl_source','extract');out=self.analyze(fixture(operational={parent}))
        row=pair(out,'nl_projection','project')
        self.assertEqual((row['lower'],row['upper']),(0,1))
        self.assertEqual(row['reason'],'not_issued_dependency_failed')
        self.assertFalse(row['eligible_completed']);self.assertEqual(row['dependency_blocker_slot_ids'],[parent])

    def test_truncation_constraint_propagates_through_two_required_edges(self):
        slots=[{'slot_id':x,'condition':'commitment',**({'history_from':[previous]} if previous else {})}
               for x,previous in [('a',None),('b','a'),('c','b')]]
        trunc={'issued':True,'terminal_valid':True,'model_outcome':'truncated_max_output_tokens',
               'response_status':'incomplete','error':None,'attempt_id':'a1'}
        selected={'a':(trunc,True),'b':(None,False),'c':(None,False)}
        grades={('first_attempt',x):{'eligible_completed':False,'provider_completed':False,'correct':False} for x in 'abc'}
        classified=m._classify(slots,'first_attempt',selected,grades,{},[])
        self.assertEqual(classified['c']['truncated_ancestor_slot_ids'],['a'])
        self.assertEqual((classified['c']['lower'],classified['c']['upper']),(0,0))
        self.assertEqual(classified['c']['dependency_blocker_slot_ids'],['b'])

    def test_completed_after_upstream_retry_is_unknown_first_known_eventual(self):
        parent=sid('nl_source','extract');child=sid('nl_projection','project')
        result=fixture(retry_first={parent},successes={('eventual',child)})
        out=self.analyze(result);first=pair(out,'nl_projection','project');last=pair(out,'nl_projection','project','eventual')
        self.assertEqual((first['lower'],first['upper'],first['reason']),(0,1,'completed_but_dependency_ineligible'))
        self.assertTrue(first['provider_completed']);self.assertFalse(first['eligible_completed'])
        self.assertEqual((last['lower'],last['upper']),(1,1))

    def test_first429_is_unknown_but_eventual_truncation_is_fixed(self):
        own=sid('strict_source_ir','extract');out=self.analyze(fixture(retry_first={own},truncated={own}))
        first=pair(out,'strict_source_ir','extract');last=pair(out,'strict_source_ir','extract','eventual')
        self.assertEqual((first['lower'],first['upper'],first['reason']),(0,1,'http_429'))
        self.assertEqual((last['lower'],last['upper'],last['reason']),(0,0,'own_max_output_tokens_truncation'))

    def test_operational_absent_and_stop_censored_are_different_unknown_reasons(self):
        own=sid('strict_source_ir','extract')
        self.assertEqual(pair(self.analyze(fixture(operational={own})),'strict_source_ir','extract')['reason'],'operational_failure')
        for mode in ('absent','censored'):
            result=fixture();merged=result['merged_evidence']
            merged['requests']=[r for r in merged['requests'] if r['slot_id']!=own]
            merged['responses']=[r for r in merged['responses'] if r['slot_id']!=own]
            final=next(r for r in merged['outcomes'] if r['slot_id']==own)
            if mode=='absent':merged['outcomes'].remove(final)
            else:final.update(issued=False,terminal_valid=False,attempt_id=None,attempts_issued=0,first_attempt_id=None,
                model_outcome='not_issued_global_stop',response_status=None,output_text='',error='not_issued_global_stop')
            refresh(result);row=pair(self.analyze(result),'strict_source_ir','extract')
            self.assertEqual((row['lower'],row['upper']),(0,1))
            self.assertEqual(row['reason'],'absent_final_outcome' if mode=='absent' else 'not_issued_global_stop')

    def test_sensitivity_arithmetic_matches_exhaustive_binary_assignments(self):
        a=sid('strict_source_ir','extract');b=sid('nl_projection','project')
        result=fixture(operational={a,b});row=contrast(self.analyze(result))
        bound=row['outer_difference_b_minus_a'];values=[(bb-aa)/30 for aa,bb in product((0,1),repeat=2)]
        self.assertEqual((bound['lower'],bound['upper']),(min(values),max(values)))
        self.assertEqual((row['a_counts']['unresolved'],row['b_counts']['unresolved']),(1,1))

    def test_missing_or_contradictory_grades_fail_closed(self):
        result=fixture();result['audits'].pop()
        with self.assertRaisesRegex(ValueError,'All scheduled slot grades'):self.analyze(result)
        result=fixture();result['audits'][0]['eligible_completed']=False
        with self.assertRaisesRegex(ValueError,'availability/dependency'):self.analyze(result)
        result=fixture();result['audits'][0]['correct']=True
        with self.assertRaisesRegex(ValueError,'Malformed'):self.analyze(result)
        own=sid('strict_source_ir','extract');result=fixture(operational={own})
        next(r for r in result['audits'] if r['slot_id']==own)['correct']=True
        with self.assertRaisesRegex(ValueError,'Ineligible frozen grade'):self.analyze(result)

    def test_missing_contrast_subset_drift_and_changed_request_reject(self):
        result=fixture();result['summary']['paired_comparisons'].pop(0)
        with self.assertRaisesRegex(ValueError,'Exactly21'):self.analyze(result)
        result=fixture();result['summary']['paired_comparisons'][0]['case_ids'].reverse()
        with self.assertRaisesRegex(ValueError,'Matched frozen'):self.analyze(result)
        result=fixture();result['merged_evidence']['requests'][0]['request']['instructions']='changed'
        with self.assertRaisesRegex(ValueError,'request hash'):self.analyze(result)

    def test_source_pipeline_point_must_match_original_grade_sum(self):
        result=fixture();result['summary']['paired_comparisons'][0]['difference_b_minus_a']=1
        with self.assertRaisesRegex(ValueError,'point estimate'):self.analyze(result)


if __name__=='__main__':unittest.main()
