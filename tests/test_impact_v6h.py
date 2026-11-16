from copy import deepcopy
from itertools import combinations
import random
import unittest
from retrace.impact_v6h import compare_families, withdrawal_robustness, enable_withdraw_impact
from retrace.tiered_v6h import family_supervaluation
from retrace.graph_identity_v6h import graph_key
from tests.test_tiered_v6h import fixture, ref, all_, any_, unless


class ImpactTests(unittest.TestCase):
    def test_exact_k3_and_locked_veto_k2(self):
        a=fixture();a['claims'][0]['positive']=any_(ref('A'),ref('B'),ref('U'))
        a['evidence'].append({'id':'Z','kind':'root','active':True,'parents':[]})
        b=deepcopy(a);b['claims'][0]['positive']=any_(ref('A'),ref('B'),ref('U'),ref('Z'))
        result=compare_families([a],[b])['decisions'][0]
        self.assertEqual(result['minimum_k'],3);self.assertEqual(result['withdraw'],['A','B','U'])
        self.assertEqual(compare_families([a],[b],locked=['A'])['decisions'][0]['minimum_k'],2)

    def test_nonmonotone_exact_vs_bruteforce100families(self):
        rng=random.Random(72561)
        def expr(depth):
            if not depth or rng.random()<.3:return ref(rng.choice('ABU'))
            a,b=expr(depth-1),expr(depth-1)
            return rng.choice([all_,any_,unless])(a,b)
        for _ in range(100):
            current=[fixture(),fixture()];proposed=[fixture()]
            for graph in current+proposed:graph['claims'][0]['positive']=expr(3)
            expected=None
            for k in range(4):
                for subset in combinations('ABU',k):
                    a=family_supervaluation(current,scenario_withdrawals=list(subset))['decisions']['D']
                    b=family_supervaluation(current+proposed,scenario_withdrawals=list(subset))['decisions']['D']
                    if (a['box_supported'] and not b['box_supported']) or (not a['diamond_supported'] and b['diamond_supported']):
                        expected=list(subset);break
                if expected is not None:break
            self.assertEqual(compare_families(current,proposed)['decisions'][0]['withdraw'],expected)

    def test_graph_identity_absorption_preserves_structure(self):
        a=fixture();a['claims'][0]['positive']=ref('A')
        b=deepcopy(a);b['claims'][0]['positive']=any_(ref('A'),all_(ref('A'),ref('B')))
        self.assertEqual(graph_key(a),graph_key(b))
        b['evidence'][1].update(kind='copy',parents=['A'])
        self.assertNotEqual(graph_key(a),graph_key(b))

    def test_tier_b_rebuttal_can_break_unanimity_at_k0(self):
        a=fixture();a['claims'][0]['positive']=ref('A')
        b=deepcopy(a);b['claims'][0]['negative']=ref('B')
        result=compare_families([a],[b])
        self.assertEqual(result['decisions'][0]['minimum_k'],0)
        self.assertFalse(result['proposal_applied'])
        self.assertFalse(result['source_entailment_verified'])

    def test_narrowed_scope_treats_others_as_fixed_available(self):
        a=fixture();a['claims'][0]['positive']=ref('A')
        b=deepcopy(a);b['claims'][0]['positive']=ref('B')
        self.assertIsNone(compare_families([a],[b],allowed=['U'])['decisions'][0]['minimum_k'])
        self.assertEqual(compare_families([a],[b],allowed=['B'])['decisions'][0]['withdraw'],['B'])

    def test_robustness_survives_two_withdrawals(self):
        a=fixture();a['claims'][0]['positive']=any_(ref('A'),ref('B'),ref('U'))
        row=withdrawal_robustness([a])['decisions'][0]
        self.assertTrue(row['survives_all_k2']);self.assertEqual(row['minimum_k'],3)
        self.assertFalse(withdrawal_robustness([fixture()])['decisions'][0]['applicable'])

    def test_hamming2_family_omission_is_dormant_and_hypothetical(self):
        a=fixture();a['evidence'][0]['active']=False;a['claims'][0]['positive']=ref('A')
        b=deepcopy(a);b['claims'][0]['positive']=all_(ref('A'),ref('B'))
        self.assertIsNone(compare_families([a],[b])['decisions'][0]['minimum_k'])
        result=enable_withdraw_impact([a],[b])
        self.assertEqual([(r['enable'],r['withdraw']) for r in result['witnesses']],[('A','B')])
        self.assertTrue(result['witnesses'][0]['hypothetical_activation'])
        self.assertFalse(a['evidence'][0]['active'])
        self.assertEqual(enable_withdraw_impact([a],[b],locked=['A'])['witnesses'],[])

    def test_hamming2_single_family_prerequisite(self):
        a=fixture();a['evidence'][0]['active']=False;a['claims'][0]['positive']=all_(ref('A'),ref('B'))
        self.assertEqual([(r['enable'],r['withdraw']) for r in enable_withdraw_impact([a])['witnesses']],[('A','B')])

    def test_hamming2_rejects_changed_typed_inventory_before_lookup(self):
        a=fixture();b=deepcopy(a);b['decisions'][0]['id']='other'
        with self.assertRaisesRegex(ValueError,'Fixed typed inventory'):
            enable_withdraw_impact([a],[b])

if __name__=='__main__':unittest.main()
