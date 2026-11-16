import unittest
from retrace.frontier_v6c_io import parse_object,verdict,family_score,counterfactual_consensus_score


def graph(routes):
    return {'evidence':[{'id':'A','kind':'root','active':True,'parents':[]},{'id':'B','kind':'root','active':False,'parents':[]}],
            'claims':[{'id':'C','supports':routes}], 'decisions':[{'id':'D','requires':['C']}]}


class ScoringTests(unittest.TestCase):
    def test_only_one_outer_fence_and_duplicates_rejected(self):
        self.assertEqual(parse_object('```json\n{"D":"unsupported"}\n```')[1],False)
        for text in ['{"x":0,"x":1}','{"x":NaN}','prefix {"D":true}','```json\n```json\n{}\n```\n```']:
            with self.assertRaises(ValueError): parse_object(text)

    def test_exact_decision_keys(self):
        with self.assertRaises(ValueError): verdict('{"D":true}',['D'])
        with self.assertRaises(ValueError): verdict('{"D":"supported","E":"unsupported"}',['D'])

    def test_empty_family_is_failure(self):
        score=family_score([], [graph([['A']])])
        self.assertFalse(score['exact_family']);self.assertEqual(score['recall'],0)

    def test_duplicates_not_additional_coverage(self):
        a,b=graph([['A']]),graph([['B']])
        score=family_score([a]*10,[a,b])
        self.assertEqual(score['predicted_distinct_graphs'],1);self.assertEqual(score['recall'],.5)

    def test_dormant_error_exposed_by_hypothetical_eligibility(self):
        score=counterfactual_consensus_score([graph([['A','B']])],[graph([['A'],['B']])])
        self.assertEqual(score['states'],4)
        self.assertEqual(score['incorrect_state_decisions'],2)
        self.assertEqual(score['state_decision_accuracy'],.5)

    def test_ambiguity_compares_both_unanimity_masks(self):
        score=counterfactual_consensus_score([graph([['A']])],[graph([['A']]),graph([['B']])])
        self.assertFalse(score['exact']);self.assertEqual(score['incorrect_state_decisions'],2)
        same=counterfactual_consensus_score([graph([['A']]),graph([['B']])],[graph([['B']]),graph([['A']])])
        self.assertTrue(same['exact'])


if __name__=='__main__': unittest.main()
