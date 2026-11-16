"""Small invented trajectory fixtures; no live model outputs."""
from copy import deepcopy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from retrace.frontier_v6j_trajectory import analyze_trajectories,signature,monotonic,MODEL,VIEWS
from retrace.graph_identity_v6h import family_score
from retrace.tiered_v6h import SCHEMA,FALSE
from scripts import analyze_frontier_v6j_trajectory as cli
from scripts.score_frontier_v6j import write_outputs
from retrace.typed_interventions_v6h import restore_then_withdraw_impact


def graph(active=True):
    return {'schema':SCHEMA,'evidence':[{'id':'A','kind':'root','active':active,'parents':[]}],'claims':[{'id':'C','positive':{'ref':'A'},'negative':deepcopy(FALSE)}],'decisions':[{'id':'D','requires':['C']}]}

def fixture(sequence=None,count=1,reference=None):
    sequence=sequence or [graph(True),graph(False)]+[graph(True)]*8
    refs=reference or [graph(True),graph(False)];cases=[];audits=[];ids=[f'fixture-{n}' for n in range(count)]
    for cid in ids:
        cases.append({'id':cid,'public':{'registry':{'evidence':['A'],'claims':['C'],'decisions':['D']}},'evaluation':{'source_family':[{'id':str(i),'graph':g} for i,g in enumerate(refs)]},'events':{'document_groups':[{'id':'source','evidence_ids':['A']}],'states':{'initial':{'revoked_documents':[],'revoked_passages':[]}}}})
        for view in VIEWS:
            chosen=[]
            for n,item in enumerate(sequence,1):
                options=item if isinstance(item,dict) and 'schema' not in item else {'candidates':[{'id':'sample','graph':item}],'provider_completed':True,'eligible_completed':True,'schema_valid':True,'strict_bare_json':True}
                row={'slot_id':f'{cid}:{n}','case_id':cid,'model':MODEL,'condition':'sample_graph','phase':f'draw_{n:02}','view':view,**options}
                audits.append(row)
                if row['strict_bare_json']:chosen.extend(row['candidates'])
            score=family_score(chosen,refs)
            audits.append({'case_id':cid,'model':MODEL,'condition':'k10_union','phase':'union','view':view,'family':score,'scheduled_draws':10,'strict_valid_draws':sum(r['schema_valid'] and r['strict_bare_json'] for r in audits if r.get('case_id')==cid and r.get('view')==view and r.get('condition')=='sample_graph'),'structural_k10_ceiling':score['expected_distinct']>10})
    return {'cases':cases},{'subsets':{'k10_gemma':ids}},audits


def run(data):return analyze_trajectories(*data,require_full_design=False)


def final_fixture(root,witness=None):
    """Invented saved artifact shape; compute is separately mocked, never live."""
    corpus,study,audits=fixture(count=12)
    inputs={cli.INPUTS['corpus']:corpus,cli.INPUTS['study']:study,'data/fixture-ledger.jsonl':{'closed':True}}
    for name,value in inputs.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
    sources={name:cli.binding(root/name) for name in inputs}
    evidence={'execution_freeze':{'path':'data/fixture-freeze.json','sha256':'fixture'},'source_files':sources,'runtime_audits_replayed':True,'runtime_input_bindings_rechecked_after_score':True,'frozen_aliases':{},'ledger_snapshot':{'path':'data/fixture-ledger.jsonl','sha256':sources['data/fixture-ledger.jsonl']['sha256']}}
    result={'summary':{'status':'complete_amended_primary','operational_summary':{'status':'completed'},'file_evidence':evidence},'audits':audits,'merged_evidence':{'source_provenance':{'fixture':True},'source_bindings':{'fixture':'invented'}}}
    if witness is not None:
        result['summary']['typed_witness_fixture']=deepcopy(witness)
        result['summary']['operational_summary']['typed_witness_fixture']=deepcopy(witness)
        result['audits'][0]['typed_witness_fixture']=deepcopy(witness)
        result['merged_evidence']['source_provenance']['typed_witness_fixture']=deepcopy(witness)
    views={role:(json.dumps({'fixture_role':role})+'\n').encode() for role in ('requests','responses','outcomes')}
    write_outputs(root,result,views)
    return result,views


class TrajectoryTests(unittest.TestCase):
    def test_all12_both_views_all10_prefixes_and_frozen_order(self):
        c,s,a=fixture(count=12);s['subsets']['k10_gemma'].reverse();value=analyze_trajectories(c,s,a)
        self.assertEqual(value['case_ids_in_frozen_order'],s['subsets']['k10_gemma']);self.assertEqual(len(value['trajectories']),24)
        self.assertTrue(all(len(t['prefixes'])==10 for t in value['trajectories']));self.assertTrue(value['prefix10_all_match_frozen_unions'])
        self.assertEqual(value['monotonicity']['violations'],0)
    def test_invalid_and_fenced_draws_keep_denominator_without_repair(self):
        invalid={'candidates':[],'provider_completed':True,'eligible_completed':True,'schema_valid':False,'strict_bare_json':False}
        fenced={'candidates':[{'graph':graph()}],'provider_completed':True,'eligible_completed':True,'schema_valid':True,'strict_bare_json':False}
        result=run(fixture([invalid,fenced]+[graph()]*8));rows=result['trajectories'][0]['prefixes']
        self.assertEqual(rows[1]['planned_draws_so_far'],2);self.assertEqual(rows[1]['provider_completed_draws'],2);self.assertEqual(rows[1]['schema_valid_draws'],1)
        self.assertEqual(rows[1]['retained_candidate_occurrences'],0);self.assertEqual(rows[1]['decision_signature']['reason'],'empty_prefix')
        self.assertIsNone(rows[1]['decision_signature']['decisions']);self.assertFalse(rows[2]['monotonicity']['checked'])
        self.assertEqual(rows[-1]['distinct_admitted_candidates'],1);self.assertEqual(rows[-1]['duplicate_candidate_occurrences'],7)
    def test_incompatible_inventory_is_not_dropped_or_repaired(self):
        wrong=graph();wrong['evidence'].append({'id':'EXTRA','kind':'root','active':True,'parents':[]})
        value=run(fixture([graph(),wrong]+[graph()]*8));rows=value['trajectories'][0]['prefixes']
        self.assertTrue(rows[0]['decision_signature']['available']);self.assertEqual(rows[1]['decision_signature']['reason'],'incompatible_typed_inventory')
        self.assertEqual(rows[-1]['distinct_admitted_candidates'],2);self.assertEqual(rows[-1]['family']['spurious_distinct'],1)
        self.assertFalse(rows[-1]['monotonicity']['checked'])
    def test_box_can_fall_and_diamond_can_rise(self):
        for sequence in ([graph(),graph(False)]+[graph()]*8,[graph(False),graph()]+[graph(False)]*8):
            rows=run(fixture(sequence))['trajectories'][0]['prefixes']
            self.assertEqual(rows[1]['decision_signature']['decisions']['D'],{'box_supported':False,'diamond_supported':True})
            self.assertEqual(rows[1]['monotonicity']['violations'],[])
    def test_original_inactive_flags_and_document_veto_are_preserved(self):
        data=fixture([graph(False)]*10);rows=run(data)['trajectories'][0]['prefixes']
        self.assertFalse(rows[-1]['decision_signature']['decisions']['D']['diamond_supported'])
        c,s,a=fixture();c['cases'][0]['events']['states']['initial']['revoked_documents']=['source']
        rows=run((c,s,a))['trajectories'][0]['prefixes'];self.assertFalse(rows[-1]['decision_signature']['decisions']['D']['diamond_supported'])
    def test_unknown_ancestry_is_not_independent_true_or_vacuous_false(self):
        unknown=graph();unknown['evidence'][0]['kind']='unknown'
        data=fixture([unknown]*10,reference=[unknown]);row=run(data)['trajectories'][0]['prefixes'][0]
        self.assertEqual(row['decision_signature']['decisions']['D'],{'box_supported':False,'diamond_supported':True})
    def test_capacity_ceiling_is_not_an_accuracy_claim(self):
        refs=[]
        for bits in itertools.product((False,True),repeat=4):
            g=graph();g['evidence']=[{'id':f'A{i}','kind':'root','active':b,'parents':[]} for i,b in enumerate(bits)];g['claims'][0]['positive']={'ref':'A0'};refs.append(g)
        c,s,a=fixture([refs[0]]*10,reference=refs);c['cases'][0]['public']['registry']['evidence']=[f'A{i}' for i in range(4)]
        last=run((c,s,a))['trajectories'][0]['prefixes'][-1]
        self.assertEqual(last['expected_family_capacity']['recall_upper_bound_from_output_capacity'],10/16)
        self.assertEqual(last['family']['recall'],1/16);self.assertFalse(last['expected_family_capacity']['exact_family_capacity_possible'])
    def test_duplicate_missing_or_changed_frozen_union_rejected(self):
        for change in ('duplicate','missing','score'):
            data=fixture()
            if change=='duplicate':data[2].append(deepcopy(data[2][0]))
            elif change=='missing':data[2].pop(0)
            else:next(r for r in data[2] if r['condition']=='k10_union')['family']['recall']=.25
            with self.assertRaises(ValueError):run(data)
    def test_engine_bound_unavailable_and_no_model_text_export(self):
        data=fixture();data[2][0]['output_text']='PRIVATE MODEL ANSWER'
        with patch('retrace.frontier_v6j_trajectory.family_supervaluation',side_effect=ValueError('constructed bound')):
            result=run(data)
        self.assertEqual(result['trajectories'][0]['prefixes'][0]['decision_signature']['reason'],'fixed_engine_rejected_or_bound_exceeded')
        self.assertNotIn('PRIVATE MODEL ANSWER',json.dumps(result))
    def test_monotonic_checker_detects_theoretical_violation(self):
        def row(k,box,diamond):return {'prefix_length':k,'decision_signature':{'available':True,'decisions':{'D':{'box_supported':box,'diamond_supported':diamond}}}}
        value=monotonic(row(1,False,True),row(2,True,False));self.assertEqual(len(value['violations']),2)
    def test_cli_refuses_live_or_absent_final_before_compute(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(cli,'compute') as compute:
            root=Path(tmp);lock=root/'results/frontier-v6j/budget/active.lock';lock.parent.mkdir(parents=True);lock.write_text('active')
            with self.assertRaisesRegex(ValueError,'live'):cli.run(root,'a','b','c','snapshot','d')
            lock.unlink()
            with self.assertRaisesRegex(ValueError,'saved authenticated'):cli.run(root,'a','b','c','snapshot','d')
            compute.assert_not_called()
    def test_saved_artifact_shape_replays_and_runs_all_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result,views=final_fixture(root)
            with patch.object(cli,'compute',return_value=(result,views)) as compute:
                value=cli.run(root,'fixture','old','new','data/fixture-ledger.jsonl','ledger-sha')
            self.assertEqual(value['planned_cases'],12);self.assertEqual(len(value['trajectories']),24)
            self.assertEqual(len(value['authenticated_input_bindings']),8)
            self.assertIn(cli.INPUTS['corpus'],value['authenticated_source_bindings']);compute.assert_called_once()
    def test_rehashed_saved_audit_tamper_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result,views=final_fixture(root);path=root/cli.OUTPUT/'score-audits.json'
            changed=deepcopy(result['audits']);changed[0]['schema_valid']=False;path.write_text(json.dumps(changed),encoding='utf-8')
            manifest_path=root/cli.OUTPUT/'composite-manifest.json';manifest=json.loads(manifest_path.read_text());manifest['files'][cli.OUTPUT+'/score-audits.json']=cli.binding(path);manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'differs from replay'):cli.verify_saved(root,result,views,aliases={},ledger_snapshot='data/fixture-ledger.jsonl')
    def test_real_typed_witness_tuples_match_saved_json_but_raw_bytes_stay_exact(self):
        a=graph();a['evidence'].append({'id':'B','kind':'root','active':True,'parents':[]})
        b=deepcopy(a);b['claims'][0]['positive']={'all':[{'ref':'A'},{'ref':'B'}]}
        witness=restore_then_withdraw_impact([a],[b],document_groups=[{'id':'paper','evidence_ids':['A']}],revoked_documents=['paper'])
        self.assertIsInstance(witness['witnesses'][0]['baseline'],tuple)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result,views=final_fixture(root,witness);before=deepcopy(result)
            bindings=cli.verify_saved(root,result,views,aliases={},ledger_snapshot='data/fixture-ledger.jsonl')
            self.assertEqual(len(bindings),8);self.assertEqual(result,before)
            saved=json.loads((root/cli.OUTPUT/'score.json').read_text(encoding='utf-8'))
            self.assertIsInstance(saved['typed_witness_fixture']['witnesses'][0]['baseline'],list)
            # Semantically equal JSON with different source bytes still fails.
            altered=dict(views);altered['requests']=json.dumps(json.loads(views['requests']),separators=(',',':')).encode()+b'\n'
            self.assertNotEqual(altered['requests'],views['requests'])
            with self.assertRaisesRegex(ValueError,'raw-byte'):cli.verify_saved(root,result,altered,aliases={},ledger_snapshot='data/fixture-ledger.jsonl')
    def test_source_changed_during_supplement_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result,views=final_fixture(root)
            def changed(*args,**kwargs):
                value=analyze_trajectories(*args,**kwargs);(root/cli.INPUTS['corpus']).write_text('{}',encoding='utf-8');return value
            with patch.object(cli,'compute',return_value=(result,views)),patch.object(cli,'analyze_trajectories',side_effect=changed):
                with self.assertRaisesRegex(ValueError,'source evidence changed'):cli.run(root,'fixture','old','new','data/fixture-ledger.jsonl','ledger-sha')

if __name__=='__main__':unittest.main()
