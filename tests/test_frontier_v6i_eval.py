"""Prospective v6i tests; invented journals stay in memory and never become results."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from retrace import frontier_v6i_eval as v
from retrace import frontier_v6h_eval as h
from scripts.build_frontier_v6h_polar_cases import build_cases
from tests.test_frontier_v6h_eval import journals as old_journals,slot

ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))


def journals(slots,texts,**kw):
    final,attempts,requests,summary=old_journals(slots,texts,**kw)
    for r in requests:r['first_attempt']=r['attempt_number']==1
    for r in attempts:r['failure_scope']=None
    for r in final:
        if r.get('issued'):r['failure_scope']=None
    summary['schema']='retrace.adaption-v6i-summary.v1'
    return final,attempts,requests,summary


def small_fixture(conditions):
    case=deepcopy(build_cases()[0]);slots=[];texts={}
    for condition,phase,suffix in conditions:
        s=slot(case,condition,phase,suffix)
        if condition=='nl_projection':s.update(input='',input_from={'slot_id':'test::nl','mode':'assistant_output_only'})
        slots.append(s)
        texts[s['slot_id']]=json.dumps(case['evaluation']['reference_ir']) if condition!='nl_source' else 'Actual ordinary-language output.'
    corpus={'cases':[case],'long_context_subset_ids':[]}
    subsets={key:[] for key in v.SUBSET_COUNTS}
    if any(s['condition']=='nl_projection' for s in slots):subsets['nl_projection']=[case['id']]
    return corpus,{'cases':[]},{'subsets':subsets},slots,texts


class V6iScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=read('data/frontier-v6h-corpus.json');cls.dossiers=read('data/frontier-v6h-dossiers.json')
        cls.study=read('data/frontier-v6i-design.json');cls.slots=read('data/frontier-v6i-sessions.json')
        cls.cases,_,_,_,cls.layouts=v.design(cls.corpus,cls.dossiers,cls.study,cls.slots,True)

    def test_exact1800_design_and_subset_denominators(self):
        self.assertEqual(len(self.slots),1800)
        self.assertEqual(sum(s['model']==v.QWEN for s in self.slots),84)
        self.assertEqual({k:len(ids) for k,ids in self.study['subsets'].items()},v.SUBSET_COUNTS)
        with self.assertRaisesRegex(ValueError,'1800'):v.design(self.corpus,self.dossiers,self.study,self.slots[:-1],True)
        bad=deepcopy(self.study);bad['subsets']['nl_projection']=bad['subsets']['nl_projection'][:-1]
        with self.assertRaisesRegex(ValueError,'denominator'):v.design(self.corpus,self.dossiers,bad,self.slots,True)

    def test_all24_sfr_actual_request_mappings_match_prospective_assignments(self):
        assignments={r['case_id']:r for r in self.study['sfr_assignments_evaluation_only']}
        self.assertEqual(len(assignments),24)
        for cid,layout in self.layouts.items():
            row=assignments[cid];self.assertEqual(layout['target'],row['entity_id'])
            self.assertEqual(layout['source_truth'],row['source_fact_is_root'])
            self.assertEqual(layout['preferred_a'],row['first_arm_prefers_yes'])
            self.assertEqual(layout['mapping']['dax'],row['yes_gloss_is_dax'])
            s=next(s for s in self.slots if s['case_id']==cid and s['condition']=='sfr_probe' and s['phase']=='a')
            payload=json.loads(s['input'])
            self.assertEqual(layout['mapping'][payload['glosses'][0]['token']],row['yes_gloss_displayed_first'])

    def test_sfr_neutral_source_change_or_preference_leak_rejected(self):
        cid=self.study['subsets']['sfr_gemma'][0];case=self.cases[cid]
        chosen={(s['condition'],s['phase']):deepcopy(s) for s in self.slots if s['case_id']==cid and s['condition'] in ('sfr_probe','sfr_backtranslation')}
        s=chosen[('sfr_probe','neutral_a')];payload=json.loads(s['input']);payload['reviewer_preference']='agree';s['input']=json.dumps(payload)
        with self.assertRaisesRegex(ValueError,'Neutral'):v.sfr_layout(case,chosen)

    def test_finalized_slot_timeout_counts_as_failure_but_schedule_can_close(self):
        c,d,study,s,t=small_fixture([('strict_source_ir','extract','ir')]);f,a,r,summary=journals(s,t)
        a[0].update(terminal_valid=False,model_outcome='operational_failure',failure_scope='slot',error='timeout',response_status=None,output_text='',usage=None)
        f[0].update(a[0]);result=v.evaluate(c,d,study,s,f,a,r,summary,10,require_full_design=False)['summary']
        self.assertTrue(result['schedule_complete']);self.assertEqual(result['finalized_slot_operational_failures'],1)
        m=result['views']['first_attempt']['primary_models'][v.GEMMA]
        self.assertEqual(m['family_recovery']['strict_source_ir']['strict_exact_family'],v.rate(0,1))
        a[0]['failure_scope']='global';f[0].update(a[0])
        self.assertFalse(v.evaluate(c,d,study,s,f,a,r,summary,10,require_full_design=False)['summary']['schedule_complete'])

    def test_first_stage429_keeps_first_pipeline_failed_and_eventual_recovers(self):
        c,d,study,s,t=small_fixture([('strict_source_ir','extract','ir'),('nl_source','extract','nl'),('nl_projection','project','project')])
        f,a,r,summary=journals(s,t,retry_first={'test::nl'})
        result=v.evaluate(c,d,study,s,f,a,r,summary,10,require_full_design=False)['summary']
        first=result['views']['first_attempt']['primary_models'][v.GEMMA];eventual=result['views']['eventual']['primary_models'][v.GEMMA]
        self.assertEqual(first['family_recovery']['nl_projection']['strict_exact_family']['numerator'],0)
        self.assertEqual(eventual['family_recovery']['nl_projection']['strict_exact_family']['numerator'],1)
        self.assertIsNone(first['conditions']['nl_source/extract']['correct'])

    def test_retry_after_timeout_and_false_first_flag_rejected(self):
        c,d,study,s,t=small_fixture([('strict_source_ir','extract','ir')]);f,a,r,summary=journals(s,t,retry_first={'test::ir'})
        a[0].update(model_outcome='operational_failure',http_status=504,error='timeout',failure_scope='slot')
        with self.assertRaisesRegex(ValueError,'unauthorized retry'):v.records(s,f,a,r)
        f,a,r,summary=journals(s,t);r[0]['first_attempt']=False
        with self.assertRaisesRegex(ValueError,'first-attempt'):v.records(s,f,a,r)

    def test_dependency_request_cannot_use_reference_or_repaired_text(self):
        c,d,study,s,t=small_fixture([('nl_source','extract','nl'),('nl_projection','project','project')]);f,a,r,summary=journals(s,t)
        r[-1]['request']['input'][-1]['content']='invented repaired source';r[-1]['request_sha256']=v.digest(r[-1]['request'])
        with self.assertRaisesRegex(ValueError,'dependency changed'):v.records(s,f,a,r)

    def test_strict_extraction_fence_is_sensitivity_only(self):
        c,d,study,s,t=small_fixture([('strict_source_ir','extract','ir')]);t['test::ir']='```json\n'+t['test::ir']+'\n```'
        f,a,r,summary=journals(s,t);result=v.evaluate(c,d,study,s,f,a,r,summary,10,require_full_design=False)['summary']
        family=result['views']['first_attempt']['primary_models'][v.GEMMA]['family_recovery']['strict_source_ir']
        self.assertEqual(family['strict_exact_family']['numerator'],0);self.assertEqual(family['semantic_admission_sensitivity']['numerator'],1)

    def sfr_result(self,answers,invalid_arm=None,wrong_translation=None):
        cid=self.study['subsets']['sfr_gemma'][0];case=self.cases[cid];layout=self.layouts[cid]
        token={value:key for key,value in layout['mapping'].items()};out={};gold={state:h.expected_verdict(case,state) for state in ('initial','withdrawn','restored')}
        for s in self.slots:
            if s['case_id']!=cid or s['condition'] not in ('sfr_probe','sfr_backtranslation'):continue
            arm=s['phase'];answer=answers[arm]
            text=json.dumps({'choice':token[answer]}) if s['condition']=='sfr_probe' else json.dumps({'answer':not answer if arm==wrong_translation else answer})
            if arm==invalid_arm and s['condition']=='sfr_probe':text='```json\n'+text+'\n```'
            row={'issued':True,'terminal_valid':True,'model_outcome':'completed','response_status':'completed','error':None,'output_text':text}
            out[(v.GEMMA,cid,s['condition'],arm)]=h._score_slot(s,row,True,case,case['public']['source_documents'],gold)
        return v.sfr_case(case,out,layout),layout

    def test_neutral_repeat_contrast_and_planned_missingness_bounds(self):
        cid=self.study['subsets']['sfr_gemma'][0];layout=self.layouts[cid];pa=layout['preferred_a'];pb=layout['preferred_b']
        row,_=self.sfr_result({'a':pa,'b':pb,'neutral_a':pa,'neutral_b':pa})
        self.assertTrue(row['matched_quartet_valid']);self.assertEqual(row['excess_all_flips'],1)
        self.assertEqual(row['excess_aligned_flips'],1);self.assertEqual(row['excess_directional_net'],1)
        missing=deepcopy(row);missing['matched_quartet_valid']=False;missing['neutral_pair_valid']=False
        result=v.sfr_summary([row,missing])
        self.assertEqual(result['planned_cases'],2);self.assertEqual(result['excess_all_flips']['all_planned_missingness_bounds'],[0,1])

    def test_valid_backtranslation_does_not_rescue_fenced_or_wrong_probe(self):
        row,_=self.sfr_result(dict(a=True,b=False,neutral_a=True,neutral_b=False),invalid_arm='a')
        self.assertFalse(row['matched_quartet_valid']);self.assertIsNone(row['excess_all_flips'])
        row,_=self.sfr_result(dict(a=True,b=False,neutral_a=True,neutral_b=False),wrong_translation='neutral_a')
        self.assertFalse(row['matched_quartet_valid']);self.assertFalse(row['neutral_pair_valid'])

    def test_administrative_halt_suppresses_inference(self):
        c,d,study,s,t=small_fixture([('strict_source_ir','extract','ir')]);f,a,r,summary=journals(s,t)
        summary.update(status='stopped',stop_reasons=['administrative_cutoff'])
        result=v.evaluate(c,d,study,s,f,a,r,summary,10,require_full_design=False)['summary']
        self.assertFalse(result['schedule_complete']);self.assertEqual(result['cluster_intervals'],[])

    def test_global_scope_in_earlier_attempt_cannot_be_hidden_by_eventual_success(self):
        c,d,study,s,t=small_fixture([('strict_source_ir','extract','ir')]);f,a,r,summary=journals(s,t,retry_first={'test::ir'})
        a[0]['failure_scope']='global'
        result=v.evaluate(c,d,study,s,f,a,r,summary,10,require_full_design=False)['summary']
        self.assertFalse(result['schedule_complete']);self.assertEqual(result['cluster_intervals'],[])

    def test_full1800_grid_nonzero_pairing_holm_and_matched_long(self):
        # Only ten Gemma projections and six fresh verdicts are correct. This
        # fixture proves subset arithmetic without saving fabricated results.
        texts={s['slot_id']:'{}' for s in self.slots}
        projection=set(sorted(self.study['subsets']['nl_projection'])[:10])
        fresh=set(sorted(self.study['subsets']['temporal'])[:6])
        for s in self.slots:
            if s['model']!=v.GEMMA:continue
            case=self.cases[s['case_id']]
            if s['condition']=='nl_projection' and s['case_id'] in projection:texts[s['slot_id']]=json.dumps(case['evaluation']['reference_ir'])
            if s['condition']=='commitment' and s['phase']=='fresh_withdrawn' and s['case_id'] in fresh:
                texts[s['slot_id']]=json.dumps(h.expected_verdict(case,'withdrawn'))
        f,a,r,summary=journals(self.slots,texts)
        result=v.evaluate(self.corpus,self.dossiers,self.study,self.slots,f,a,r,summary,bootstrap_repeats=10000)['summary']
        self.assertEqual(result['status'],'complete_primary')
        primary=[x for x in result['paired_comparisons'] if x['primary_family_member'] and x['view']=='first_attempt']
        self.assertEqual(len(primary),21)
        selected=next(x for x in primary if x['model']==v.GEMMA and x['contrast']=='nl_projection_minus_strict_ir')
        self.assertEqual(selected['n_pairs'],30);self.assertEqual(selected['paired_counts']['b_only'],10)
        self.assertEqual(selected['p_two_sided_exact'],2/1024);self.assertEqual(selected['holm_adjusted_p'],21*2/1024)
        temporal=next(x for x in primary if x['model']==v.GEMMA and x['contrast']=='fresh_withdrawn_minus_no_commit')
        self.assertEqual(temporal['n_pairs'],12);self.assertEqual(temporal['paired_counts']['b_only'],6)
        self.assertEqual(temporal['holm_adjusted_p'],20*2/64)
        gemma=result['views']['first_attempt']['primary_models'][v.GEMMA]
        long=next(x for x in gemma['matched_long_context'] if x['contrast']=='long_withdrawn_minus_short_withdrawn')
        self.assertEqual(long['n_pairs'],12);self.assertEqual(long['a_correct'],v.rate(6,12));self.assertEqual(long['b_correct'],v.rate(0,12))
        self.assertEqual(result['views']['first_attempt']['qwen3_5_397b_diagnostic_only']['scheduled_slots'],84)
        self.assertTrue(all(x['p_two_sided_exact'] is None for x in result['paired_comparisons'] if x['view']=='eventual'))
        nl_intervals=[x for x in result['cluster_intervals'] if x['partition']=='all' and x['case_ids']==sorted(self.study['subsets']['nl_projection'])]
        self.assertEqual(len(nl_intervals),1);self.assertEqual(nl_intervals[0]['n_base_cases'],30)
        self.assertEqual(nl_intervals[0]['family_counts'],{'ECO':6,**{f'F{i}':4 for i in range(1,7)}})
        self.assertEqual(nl_intervals[0]['metrics'][f'first_attempt/{v.GEMMA}/nl_projection_minus_strict_ir']['estimate'],1/3)


if __name__=='__main__':unittest.main()
