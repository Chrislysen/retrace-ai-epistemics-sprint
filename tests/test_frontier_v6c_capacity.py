import copy
import itertools
import unittest
from retrace.uncertainty_v6c import analyze_uncertainty
from retrace.stress_v6c import analyze_stress
from retrace.stress import analyze_stress as historical_stress
from retrace.exposure_v6c import audit_exposure
from retrace.coverage_v6c import analyze_root_coverage


def five_axes():
    candidates=[]
    for assignment in itertools.product([False,True],repeat=5):
        cid=''.join(str(int(x)) for x in assignment)
        graph={'evidence':[{'id':'A','kind':'root','active':True,'parents':[]},
                           {'id':'B','kind':'root','active':False,'parents':[]}],
               'claims':[{'id':f'C{i}','supports':[['B' if bit else 'A']]} for i,bit in enumerate(assignment)],
               'decisions':[{'id':'D','requires':[f'C{i}' for i in range(5)]}]}
        candidates.append({'id':cid,'graph':graph})
    questions=[{'id':f'q{i}','label':f'Is prerequisite {i} B?', 'cost':1,
                'answers':{c['id']:c['id'][i]=='1' for c in candidates}} for i in range(5)]
    return {'candidates':candidates,'questions':questions,'allowed_withdrawals':['A','B']}


class CapacityTests(unittest.TestCase):
    def test_five_axes_all32_retained_and_five_question_worst_case(self):
        brief=five_axes(); original=copy.deepcopy(brief)
        result=analyze_stress(brief)
        self.assertEqual(len(result['candidate_ids']),32)
        self.assertEqual(result['consensus']['clarification']['worst_case_cost'],5)
        self.assertEqual(result['coverage']['candidate_state_combinations'],128)
        self.assertEqual(brief,original)

    def test_one_answer_can_settle_decision_without_identifying_graph(self):
        result=analyze_stress(five_axes(),{'answers':{'q0':True}})
        self.assertEqual(len(result['candidate_ids']),16)
        self.assertIsNone(result['next_question'])
        self.assertEqual(result['consensus']['clarification']['worst_case_cost'],0)

    def test_exposure_and_root_guard_accept_all32(self):
        candidates=five_axes()['candidates']
        self.assertEqual(len(audit_exposure(candidates)['candidate_ids']),32)
        result=analyze_root_coverage(candidates)
        self.assertEqual(result['coverage']['candidate_count'],32)

    def test_old_supported_domain_identical_except_version(self):
        brief=five_axes(); brief['candidates']=brief['candidates'][:8]
        ids={c['id'] for c in brief['candidates']}
        for q in brief['questions']: q['answers']={k:v for k,v in q['answers'].items() if k in ids}
        old=historical_stress(brief); new=analyze_stress(brief)
        old.pop('schema');new.pop('schema')
        old['consensus'].pop('schema_version');new['consensus'].pop('schema_version')
        self.assertEqual(old,new)

    def test_33rd_candidate_rejected_not_dropped(self):
        brief=five_axes(); extra=copy.deepcopy(brief['candidates'][0]);extra['id']='extra'
        with self.assertRaises(ValueError): analyze_uncertainty(brief['candidates']+[extra])


if __name__=='__main__': unittest.main()
