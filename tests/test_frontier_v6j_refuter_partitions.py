"""Invented refuter audit fixtures; no live model answers or parser changes."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from retrace.frontier_v6j_refuter_partitions import analyze_refuter_partitions,CATEGORIES,SCOPES,VIEWS
from retrace.graph_identity_v6h import family_score
from tests.test_frontier_v6j_trajectory import graph
from scripts import analyze_frontier_v6j_refuter_partitions as cli
from scripts.score_frontier_v6j import write_outputs
from retrace import frontier_v6h_eval as frozen_eval


def fixture(count=5,model_count=1):
    reference=[{'graph':graph(True)},{'graph':graph(False)}];cases=[];rows=[]
    ids=[f'case-{n}' for n in range(count)];models=[f'model-{n}' for n in range(model_count)]
    for number,cid in enumerate(ids):
        faithful=number%2==0;seed=reference if faithful else reference[:1]
        cases.append({'id':cid,'partition':'ecological' if number%3==0 else 'synthetic','evaluation':{'source_family':deepcopy(reference)},'authored_seed_pool':{'candidates':deepcopy(seed)}})
        for model in models:
            for view in VIEWS:
                category=number%5;proposal=[]
                if category==0:proposal=deepcopy(reference)
                if category==1:proposal=deepcopy(reference[:1])*2
                if category==2:
                    extra=graph();extra['claims'][0]['positive']={'const':False};proposal=deepcopy(reference)+[{'graph':extra}]
                located=category<3;abstained=category==3;valid=category<4
                score=family_score(proposal,reference);exact=located and score['exact_family']
                impact={scope:{'available':located,'consequential':located and scope!='actual_initial_locked'} for scope in SCOPES}
                primary=exact and impact['baseline_unvetoed_structural']['consequential'];correct=abstained if faithful else primary
                rows.append({'slot_id':f'{model}:{cid}','model':model,'case_id':cid,'condition':'adversarial_refuter','phase':'counter_read','view':view,
                    'record_observed':True,'provider_completed':valid,'eligible_completed':valid,'schema_valid':valid,'strict_bare_json':valid,
                    'candidates':proposal,'family':score,'compilation':{'registry_coverage_gaps':[]} if located else None,
                    'source_locations_valid':located,'abstained':abstained,'impact':impact,'source_exact_family':exact,
                    'source_aligned_consequential':primary,'typed_veto_release_source_aligned_consequential':exact and impact['typed_veto_release']['consequential'],
                    'located_semantically_wrong_objection':located and not exact,'seed_exact_evaluation_only':faithful,'correct':correct,'strict_correct':correct})
    return {'cases':cases},{'all_case_ids':ids,'primary_models':models},rows


def small(data):return analyze_refuter_partitions(*data,require_full_design=False)


def saved_fixture(root):
    corpus,study,audits=fixture(60,5);snapshot='data/fixture-ledger.jsonl'
    inputs={cli.INPUTS['corpus']:corpus,cli.INPUTS['study']:study,snapshot:{'closed':True}}
    for name,value in inputs.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
    sources={name:cli.binding(root/name) for name in inputs}
    evidence={'execution_freeze':{'path':'data/fixture-freeze.json','sha256':'fixture'},'source_files':sources,'runtime_audits_replayed':True,'runtime_input_bindings_rechecked_after_score':True,'frozen_aliases':{},'ledger_snapshot':{'path':snapshot,'sha256':sources[snapshot]['sha256']}}
    result={'summary':{'status':'complete_amended_primary','operational_summary':{'status':'completed'},'file_evidence':evidence},'audits':audits,'merged_evidence':{'source_provenance':{'fixture':True},'source_bindings':{'fixture':'invented'}}}
    views={role:(json.dumps({'role':role})+'\n').encode() for role in ('requests','responses','outcomes')};write_outputs(root,result,views)
    return result,views,snapshot


class RefuterPartitionTests(unittest.TestCase):
    def test_all300_each_view_and_all_categories_in_frozen_order(self):
        data=fixture(60,5);data[1]['all_case_ids'].reverse();value=analyze_refuter_partitions(*data)
        self.assertEqual(len(value['rows']),600);self.assertEqual(value['planned_slots_per_view'],300)
        self.assertEqual([r['case_id'] for r in value['rows'][:60]],data[1]['all_case_ids'])
        for view in VIEWS:self.assertEqual(value['summaries'][view]['overall']['categories'],dict.fromkeys(CATEGORIES,60))
    def test_partial_duplicates_are_consistent_not_exact_or_spurious(self):
        value=small(fixture());partial=next(r for r in value['rows'] if r['category']==CATEGORIES[1])
        self.assertEqual(partial['family']['predicted_distinct'],1);self.assertEqual(partial['family']['precision'],1);self.assertEqual(partial['family']['recall'],.5)
        self.assertFalse(partial['frozen_metrics']['source_aligned_consequential']);self.assertTrue(partial['frozen_metrics']['source_located_nonexact_family'])
        impact=value['summaries']['first_attempt']['overall']['proper_subset_impact']
        self.assertEqual(impact['actual_initial_locked']['consequential'],0);self.assertEqual(impact['baseline_unvetoed_structural']['consequential'],1)
    def test_any_extra_reading_remains_spurious_even_with_full_recall(self):
        row=next(r for r in small(fixture())['rows'] if r['category']==CATEGORIES[2])
        self.assertEqual(row['family']['recall'],1);self.assertEqual(row['family']['spurious_distinct'],1)
    def test_fenced_partial_retained_and_format_separate(self):
        data=fixture();row=data[2][2];self.assertEqual(row['case_id'],'case-1');row['strict_bare_json']=False;row['strict_correct']=False
        value=small(data);chosen=next(r for r in value['rows'] if r['case_id']=='case-1' and r['view']=='first_attempt')
        self.assertEqual(chosen['category'],CATEGORIES[1]);self.assertFalse(chosen['strict_bare_json'])
    def test_rejected_gap_inventory_is_unknown_not_empty(self):
        value=small(fixture());row=next(r for r in value['rows'] if r['category']=='invalid_or_unavailable')
        self.assertEqual(row['registry_coverage'],{'available':False,'gaps':None})
        abstention=next(r for r in value['rows'] if r['category']=='explicit_abstention');self.assertIsNone(abstention['registry_coverage']['gaps'])
    def test_stored_nonempty_gap_is_retained_separately(self):
        data=fixture();row=data[2][0];row['compilation']['registry_coverage_gaps']=['UNACCOUNTED']
        for key in ('source_exact_family','source_aligned_consequential','typed_veto_release_source_aligned_consequential','correct','strict_correct'):row[key]=False
        row['located_semantically_wrong_objection']=True
        out=small(data)['rows'][0];self.assertEqual(out['category'],'exact_authored_family');self.assertEqual(out['registry_coverage']['gaps'],['UNACCOUNTED']);self.assertFalse(out['frozen_metrics']['source_exact_family'])
    def test_actual_frozen_post_gate_scoring_failure_is_unavailable(self):
        corpus,study,rows=fixture(1);case=corpus['cases'][0];case['public']={'registry':{'evidence':['A'],'claims':['C'],'decisions':['D']}}
        slot={key:rows[0][key] for key in ('slot_id','case_id','model','condition','phase')}
        provider={'issued':True,'terminal_valid':True,'model_outcome':'completed','response_status':'completed','error':None,'output_text':'{}'}
        gate={'status':'source_located_proposal','strict_bare_json':True,'raw_warning_score':.8,
              'compilation':{'registry_coverage_gaps':[],'candidates':deepcopy(case['evaluation']['source_family'])}}
        initial=family_score([],case['evaluation']['source_family'])
        with patch.object(frozen_eval,'validate_refuter',return_value=gate),patch.object(frozen_eval,'family_score',side_effect=[initial,ValueError('constructed BDD bound')]):
            failed=frozen_eval._score_slot(slot,provider,True,case,[],{})
        self.assertTrue(failed['source_locations_valid']);self.assertTrue(failed['schema_valid'])
        self.assertEqual(failed['candidates'],[]);self.assertIsNone(failed['compilation']);self.assertEqual(failed['error'],'invalid_ValueError')
        for index,view in enumerate(VIEWS):
            rows[index]=deepcopy(failed);rows[index].update(view=view,impact={scope:{'available':False,'consequential':False} for scope in SCOPES},
                source_aligned_consequential=False,typed_veto_release_source_aligned_consequential=False,
                located_semantically_wrong_objection=True,seed_exact_evaluation_only=True)
        result=small((corpus,study,rows));out=result['rows'][0]
        self.assertEqual(out['category'],'invalid_or_unavailable');self.assertTrue(out['source_located_proposal_scoring_incomplete'])
        self.assertTrue(out['source_locations_valid']);self.assertTrue(out['schema_valid']);self.assertEqual(out['family'],initial)
        self.assertTrue(out['frozen_metrics']['source_located_nonexact_family']);self.assertIsNone(out['registry_coverage']['gaps'])
        self.assertEqual(result['summaries']['first_attempt']['overall']['source_located_proposal_scoring_incomplete'],1)
    def test_partial_witness_can_exist_with_other_impact_audit_unavailable(self):
        data=fixture();data[2][2]['impact']['baseline_unvetoed_structural']['available']=False
        value=small(data)['summaries']['first_attempt']['overall']['proper_subset_impact']['baseline_unvetoed_structural']
        self.assertEqual(value['consequential'],1);self.assertEqual(value['consequential_with_incomplete_audit'],1)
    def test_missing_duplicate_or_frozen_metric_tamper_rejected(self):
        for mode in ('missing','duplicate','family','metric','unexpected'):
            data=fixture()
            if mode=='missing':data[2].pop()
            if mode=='duplicate':data[2].append(deepcopy(data[2][0]))
            if mode=='family':data[2][2]['family']['exact_family']=True
            if mode=='metric':data[2][2]['source_aligned_consequential']=True
            if mode=='unexpected':data[2][0]['model']='unplanned'
            with self.assertRaises(ValueError):small(data)
    def test_no_raw_text_export_or_mutation(self):
        data=fixture();data[2][0]['output_text']='SECRET ANSWER';before=deepcopy(data);result=small(data)
        self.assertEqual(data,before);self.assertNotIn('SECRET ANSWER',json.dumps(result))
    def test_cli_live_or_missing_final_refused_before_compute(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(cli,'compute') as compute:
            root=Path(temp);lock=root/'results/frontier-v6j/budget/active.lock';lock.parent.mkdir(parents=True);lock.write_text('live')
            with self.assertRaisesRegex(ValueError,'live'):cli.run(root,'a','b','c','s','d')
            lock.unlink()
            with self.assertRaisesRegex(ValueError,'saved authenticated'):cli.run(root,'a','b','c','s','d')
            compute.assert_not_called()
    def test_saved_composite_fixture_and_late_input_change(self):
        for mutate in (False,True):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);result,views,snapshot=saved_fixture(root)
                def analyze(*args,**kwargs):
                    value=analyze_refuter_partitions(*args,**kwargs)
                    if mutate:(root/cli.INPUTS['study']).write_text('{}',encoding='utf-8')
                    return value
                with patch.object(cli,'compute',return_value=(result,views)),patch.object(cli,'analyze_refuter_partitions',side_effect=analyze):
                    if mutate:
                        with self.assertRaisesRegex(ValueError,'source evidence changed'):cli.run(root,'f','a','b',snapshot,'s')
                    else:self.assertEqual(cli.run(root,'f','a','b',snapshot,'s')['planned_slots_per_view'],300)

if __name__=='__main__':unittest.main()
