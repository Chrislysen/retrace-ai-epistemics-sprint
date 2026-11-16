"""Invented graph/source fixtures only. No empirical responses or provider calls."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from retrace.refuter_inspector_v6l import inspect, compare
from retrace.source_ir_v6d import source_segments
from retrace.tiered_v6h import family_supervaluation

DOCS=[{'id':'invented-note','text':'A and B are original records. C has the declared positive warrant; D requires C. This invented packet tests machinery, not entailment.'}]
REG={'evidence':['A','B'],'claims':['C'],'decisions':['D']}


def graph(expr=None,active=True):
    return {'schema':'retrace.tiered-graph.v6h','evidence':[
        {'id':'A','kind':'root','active':True,'parents':[]},{'id':'B','kind':'root','active':active,'parents':[]}],
        'claims':[{'id':'C','positive':expr or {'ref':'A'},'negative':{'const':False}}],
        'decisions':[{'id':'D','requires':['C']}]}


def candidates(*graphs):return [{'id':'reading'+str(i),'graph':g} for i,g in enumerate(graphs)]


def envelope(g=None):
    g=g or graph();span=source_segments(DOCS)[0]['span_id']
    ir={'schema':'retrace.source-ir.v6h','entities':[],'bindings':[],'choices':[],
        'combination':{'mode':'cartesian','assignments':[],'citations':[]},'propositions':[]}
    def add(kind,target,body):ir['propositions'].append({'id':'p'+str(len(ir['propositions'])),
        'kind':kind,'target':target,'body':body,'scope':'current','when':{},'citations':[span],'bindings':[]})
    for field,kind in (('evidence','evidence'),('claims','claim'),('decisions','decision')):
        for row in g[field]:
            ir['entities'].append({'id':row['id'],'type':kind,'operational':True,'citations':[span]})
            if field=='evidence':
                add('eligibility',row['id'],{'active':row['active']});add('origin',row['id'],{k:row[k] for k in ('kind','parents')})
            elif field=='claims':add('support',row['id'],{k:row[k] for k in ('positive','negative')})
            else:add('requirement',row['id'],{'requires':row['requires']})
    return {'status':'objection','ir':ir,'objection_spans':[span],'warning_score':.7}


class InspectorTests(unittest.TestCase):
    def test_source_location_is_not_entailment_and_input_never_changes(self):
        proposal=envelope(graph({'ref':'B'}));seed=candidates(graph());before=deepcopy((proposal,seed,DOCS,REG))
        out=inspect(json.dumps(proposal),DOCS,REG,seed)
        self.assertEqual((proposal,seed,DOCS,REG),before)
        self.assertEqual(out['status'],'source_located_proposal');self.assertFalse(out['semantic_entailment_verified'])
        for span in out['gate']['locations']:self.assertEqual(DOCS[0]['text'][span['start']:span['end']],span['text'])
        self.assertFalse(out['proposal_applied']);self.assertFalse(out['state_mutated'])

    def test_union_never_replaces_seed_and_minimum_matches_scalar_all_masks(self):
        a=graph({'any':[{'ref':'A'},{'ref':'B'}]});b=graph({'all':[{'ref':'A'},{'ref':'B'}]})
        out=compare(candidates(a),candidates(b));row=out['decision_impact']['decisions'][0]
        self.assertEqual(row['minimum_k'],1)
        for mask in range(4):
            withdrawn=[e for bit,e in enumerate(('A','B')) if mask & (1<<bit)]
            old=family_supervaluation([a],scenario_withdrawals=withdrawn)['decisions']['D']
            new=family_supervaluation([a,b],scenario_withdrawals=withdrawn)['decisions']['D']
            changed=old['box_supported']!=new['box_supported'] or old['diamond_supported']!=new['diamond_supported']
            if len(withdrawn)<row['minimum_k']:self.assertFalse(changed)
        replacement=compare(candidates(graph({'const':False})),candidates(graph()))['modal_summary']['decisions']['D']
        self.assertFalse(replacement['augmented']['box_supported']);self.assertTrue(replacement['proposal']['box_supported'])
        self.assertTrue(replacement['augmented']['diamond_supported'])

    def test_duplicate_readings_add_no_novelty_or_witness(self):
        g=graph();out=compare(candidates(g,g),candidates(g))
        self.assertEqual(out['declaration_comparison']['union_distinct'],1)
        self.assertEqual(out['declaration_comparison']['novel_proposed_readings'],0)
        self.assertIsNone(out['decision_impact']['decisions'][0]['minimum_k'])

    def test_dormant_pair_uses_hypothetical_original_flag_not_a_veto(self):
        # Both start false; enabling B makes both true; withdrawing A separates.
        seed=graph({'ref':'B'},False);proposal=graph({'all':[{'ref':'A'},{'ref':'B'}]},False)
        out=compare(candidates(seed),candidates(proposal))
        self.assertIsNone(out['decision_impact']['decisions'][0]['minimum_k'])
        witness=out['hamming2']['witnesses'][0]
        self.assertEqual((witness['enable'],witness['withdraw']),('B','A'))
        self.assertEqual(witness['baseline'],[False,False]);self.assertTrue(witness['hypothetical_activation'])
        scalar=family_supervaluation([seed,proposal],local_overrides={'B':True},scenario_withdrawals=['A'])['decisions']['D']
        self.assertEqual(witness['augmented_enabled_and_withdrawn'],{k:scalar[k] for k in ('box_supported','diamond_supported')})
        self.assertEqual(witness['augmented_enabled_and_withdrawn'],{'box_supported':False,'diamond_supported':True})
        self.assertFalse(seed['evidence'][1]['active']);self.assertNotIn('typed_veto_release',out)

    def test_raw_duplicate_keys_or_invalid_span_never_repair(self):
        raw=json.dumps(envelope()).replace('"warning_score": 0.7','"warning_score": 0.1, "warning_score": 0.7')
        p=envelope();p['objection_spans']=['not-a-source-span']
        for text in (raw,json.dumps(p)):
            result=inspect(text,DOCS,REG,candidates(graph()))
            self.assertEqual(result['status'],'rejected');self.assertIsNone(result['preview'])

    def test_fence_stays_explicit_and_abstention_does_not_certify(self):
        out=inspect('```json\n'+json.dumps(envelope())+'\n```',DOCS,REG,candidates(graph()))
        self.assertFalse(out['gate']['strict_bare_json'])
        out=inspect(json.dumps({'status':'no_counter_reading','ir':None,'objection_spans':[],'warning_score':.1}),DOCS,REG,candidates(graph()))
        self.assertEqual(out['status'],'abstained');self.assertIsNone(out['preview']);self.assertEqual(out['source_completeness'],'unknown')

    def test_gate_remains_admitted_when_preview_bound_is_unavailable(self):
        with patch('retrace.refuter_inspector_v6l.compare_families',side_effect=ValueError('Exact bound exceeded')):
            out=inspect(json.dumps(envelope()),DOCS,REG,candidates(graph()))
        self.assertEqual(out['status'],'source_located_proposal')
        self.assertEqual(out['preview']['decision_impact']['status'],'unavailable')
        self.assertNotIn('decisions',out['preview']['decision_impact'])
        self.assertEqual(out['preview']['hamming2']['status'],'evaluated')

    def test_incompatible_inventory_is_not_a_negative_result(self):
        other=graph();other['evidence'].append({'id':'Z','kind':'root','active':True,'parents':[]})
        out=compare(candidates(graph()),candidates(other))
        self.assertEqual(out['status'],'unavailable');self.assertIsNone(out['decision_impact'])

    def test_unknown_ancestry_and_rebuttal_do_not_turn_into_union_certainty(self):
        unknown=graph();unknown['evidence'][0]['kind']='unknown'
        row=compare(candidates(unknown),candidates(graph()))['modal_summary']['decisions']['D']
        self.assertEqual(row['augmented'],{'box_supported':False,'diamond_supported':True})
        contested=graph();contested['claims'][0]['negative']={'ref':'B'}
        row=compare(candidates(contested),candidates(graph()))['modal_summary']['decisions']['D']
        self.assertEqual(row['seed'],{'box_supported':False,'diamond_supported':False})
        self.assertEqual(row['augmented'],{'box_supported':False,'diamond_supported':True})


if __name__=='__main__':unittest.main()
