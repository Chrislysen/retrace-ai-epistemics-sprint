from copy import deepcopy
import json
from pathlib import Path
import unittest
from retrace.typed_interventions_v6h import restore_then_withdraw_impact
from tests.test_tiered_v6h import fixture,ref,all_,unless

class TypedInterventionTests(unittest.TestCase):
    def pair(self):
        a=fixture();a['claims'][0]['positive']=ref('A')
        b=deepcopy(a);b['claims'][0]['positive']=all_(ref('A'),ref('B'))
        return a,b

    def test_document_release_exposes_joint_omission_only_with_second_action(self):
        a,b=self.pair();before=deepcopy((a,b))
        result=restore_then_withdraw_impact([a],[b],document_groups=[{'id':'paper','evidence_ids':['A']}],revoked_documents=['paper'])
        self.assertEqual([(w['release'],w['withdraw']) for w in result['witnesses']],[({'kind':'document','id':'paper'},'B')])
        row=result['witnesses'][0]
        self.assertEqual(row['baseline'],(False,False));self.assertEqual(row['release_only'],(True,True))
        self.assertEqual(row['withdraw_only'],(False,False));self.assertEqual(row['joint'],(True,True))
        self.assertEqual(row['proposed_joint'],(False,False));self.assertEqual(row['typed_action_count'],2)
        self.assertEqual((a,b),before);self.assertFalse(result['state_mutated'])

    def test_passage_release_is_typed_separately(self):
        a,b=self.pair()
        row=restore_then_withdraw_impact([a],[b],document_groups=[],revoked_passages=['A'])['witnesses'][0]
        self.assertEqual(row['release'],{'kind':'passage','id':'A'})

    def test_overlapping_veto_and_original_inactivity_cannot_be_cleared_together(self):
        a,b=self.pair();groups=[{'id':'paper','evidence_ids':['A']},{'id':'other','evidence_ids':['A']}]
        for state in ({'revoked_documents':['paper','other']},{'revoked_documents':['paper'],'revoked_passages':['A']},
                      {'revoked_documents':['paper'],'scenario_withdrawals':['A']}):
            self.assertEqual(restore_then_withdraw_impact([a],[b],document_groups=groups,**state)['witnesses'],[])
        a['evidence'][0]['active']=False;b['evidence'][0]['active']=False
        self.assertEqual(restore_then_withdraw_impact([a],[b],document_groups=groups,revoked_documents=['paper'])['witnesses'],[])

    def test_release_alone_disagreement_is_not_claimed_as_two_action_exposure(self):
        a,b=self.pair();b['claims'][0]['positive']=unless(ref('A'),ref('U'))
        self.assertEqual(restore_then_withdraw_impact([a],[b],document_groups=[{'id':'paper','evidence_ids':['A']}],revoked_documents=['paper'])['witnesses'],[])

    def test_no_veto_and_wrong_inventory_are_explicit(self):
        a,b=self.pair()
        self.assertEqual(restore_then_withdraw_impact([a],[b],document_groups=[])['witnesses'],[])
        b['decisions'][0]['id']='other'
        with self.assertRaisesRegex(ValueError,'Fixed typed inventory'):
            restore_then_withdraw_impact([a],[b],document_groups=[])

    def test_single_family_restoration_diagnostic_never_applies(self):
        _,b=self.pair()
        rows=restore_then_withdraw_impact([b],document_groups=[{'id':'paper','evidence_ids':['A']}],revoked_documents=['paper'])['witnesses']
        self.assertEqual({r['withdraw'] for r in rows},{'A','B'})
        self.assertTrue(all(r['original_local_flags_unchanged'] for r in rows))

    def test_all_eight_frozen_f4_packets_match_public_first_opportunity_review(self):
        corpus=json.loads((Path(__file__).resolve().parents[1]/'data/frontier-v6h-corpus.json').read_text(encoding='utf-8'))
        found={}
        for case in corpus['cases']:
            if case['family_id']!='F4':continue
            result=restore_then_withdraw_impact([r['graph'] for r in case['authored_seed_pool']['candidates']],
                [r['graph'] for r in case['evaluation']['source_family']],document_groups=case['events']['document_groups'],**case['events']['states']['initial'])
            found[case['within_family_index']]=len(result['witnesses'])
        self.assertEqual(found,{1:0,2:4,3:0,4:3,5:0,6:2,7:0,8:5})

if __name__=='__main__':unittest.main()
