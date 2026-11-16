from copy import deepcopy
from pathlib import Path
import json
import unittest
from retrace.source_ir_v6d import source_segments
from retrace.frontier_v6c_io import graph_signature
from scripts.build_frontier_v6d_regression import study,sessions
from scripts.score_frontier_v6d_regression import evaluate
ROOT=Path(__file__).resolve().parents[1]


def fixture_ir(case):
    """Mechanical test fixture, not an extraction or independent annotation."""
    public=case['public'];gold=case['evaluation'];spans=source_segments(public['source_documents'])
    cite=lambda ident:next(s['span_id'] for s in spans if ident in s['text'])
    family=gold['expected_family'] or public['candidates']
    graphs=list({graph_signature(c['graph']):c['graph'] for c in family}.values())
    axes=0 if len(graphs)==1 else 1 if len(graphs)==2 else 2
    ir={'schema':'retrace.source-ir.v6d','entities':[],'bindings':[],
        'choices':[{'id':f'u{i}','options':['a','b'],'citations':[spans[-1]['span_id']]} for i in range(axes)],
        'combination':{'mode':'cartesian','assignments':[],'citations':[spans[-1]['span_id']] if axes>1 else []},'propositions':[]}
    for category,ids in public['registry'].items():
        for ident in ids:ir['entities'].append({'id':ident,'type':{'evidence':'evidence','claims':'claim','decisions':'decision'}[category],
                                              'operational':True,'citations':[cite(ident)]})
    def add(target,kind,body,when):
        ir['propositions'].append({'id':'p'+str(len(ir['propositions'])),'target':target,'kind':kind,'body':body,
                                  'scope':'current','polarity':'assert','when':when,'bindings':[],'citations':[cite(target)]})
    for number,g in enumerate(graphs):
        when={f'u{i}':'b' if number&(1<<i) else 'a' for i in range(axes)}
        for e in g['evidence']:
            add(e['id'],'eligibility',{'active':e['active']},when)
            if e['id'] in gold['unidentified_ancestor_targets']:
                add(e['id'],'unknown_ancestry',{'description':'Unidentified shared whiteboard tally'},when)
                ir['propositions'][-1]['citations']=[next(s['span_id'] for s in spans if s['document_id']=='holdout-04-section-2')]
            else:add(e['id'],'origin',{'kind':e['kind'],'parents':e['parents']},when)
        for c in g['claims']:
            routes=[{'ref':r[0]} if len(r)==1 else {'all':[{'ref':x} for x in r]} for r in c['supports']]
            expr={'none':True} if not routes else routes[0] if len(routes)==1 else {'any':routes}
            add(c['id'],'support',{'expr':expr},when)
        for d in g['decisions']:add(d['id'],'requirement',{'requires':d['requires']},when)
    return ir


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=study(json.loads((ROOT/'data/conservation-v6b-holdout-reviewed.json').read_text(encoding='utf-8')))
        cls.slots=sessions(cls.data)

    def test_gold_not_in_requests_and_all_80_slots(self):
        changed=deepcopy(self.data)
        for c in changed['cases']:c['evaluation']={'poison':'FORBIDDEN'}
        self.assertEqual(self.slots,sessions(changed));self.assertEqual(len(self.slots),80)

    def test_constructed_exact_ir_and_abstentions_score_clean(self):
        cases={c['id']:c for c in self.data['cases']};rows=[]
        for s in self.slots:
            case=cases[s['case_id']]
            value={'status':'no_counter_reading'} if s['condition']=='adversarial_refuter' and not case['evaluation']['positive'] else fixture_ir(case)
            rows.append({**{k:s[k] for k in ('slot_id','model','case_id','condition')},'http_status':200,'response_status':'completed','output_text':json.dumps(value)})
        scored=evaluate(self.data,self.slots,rows)
        self.assertTrue(all(r['clean_success'] for r in scored['audits']),scored['audits'])
        self.assertTrue(all(g['positive_clean_success']==4 and g['control_clean_success']==4 for g in scored['groups']))

    def test_missing_controls_are_not_zero_false_alarm_success(self):
        result=evaluate(self.data,self.slots,[])
        self.assertTrue(all(g['control_clean_success']==0 and g['control_invalid_or_missing']==4 for g in result['groups']))

    def test_unknown_recognition_does_not_hide_corrupted_known_rule(self):
        case=self.data['cases'][3];ir=fixture_ir(case)
        next(p for p in ir['propositions'] if p['kind']=='support')['body']={'expr':{'none':True}}
        slot=next(s for s in self.slots if s['case_id']==case['id'])
        row={**{k:slot[k] for k in ('slot_id','model','case_id','condition')},'http_status':200,'response_status':'completed','output_text':json.dumps(ir)}
        result=evaluate(self.data,[slot],[row])['audits'][0]
        self.assertTrue(result['unidentified_ancestor_targets_recognized'])
        self.assertFalse(result['clean_success'])

    def test_truncated_valid_looking_text_never_counts_as_completed(self):
        case=self.data['cases'][0];slot=self.slots[0]
        row={**{k:slot[k] for k in ('slot_id','model','case_id','condition')},'http_status':200,'response_status':'incomplete','output_text':json.dumps(fixture_ir(case))}
        self.assertFalse(evaluate(self.data,[slot],[row])['audits'][0]['clean_success'])


if __name__=='__main__':unittest.main()
