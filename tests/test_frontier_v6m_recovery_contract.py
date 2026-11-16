"""Invented orphan-overlay contract tests against the unchanged frozen scorer.

No actual crash prefix, answer, API, ledger or worker is read or modified.
These prove interface compatibility, not authenticity of a real prefix.
"""
from copy import deepcopy
import unittest
from retrace import frontier_v6i_eval as frozen
from retrace import frontier_v6h_eval as h
from tests.test_frontier_v6i_eval import small_fixture,journals


def orphan_disposition(slot,request):
    """Proposed NEW recovery-artifact row, never an old provider response."""
    return {**{key:slot[key] for key in ('slot_id','case_id','model','condition','phase')},
        'run_id':'constructed-recovery-adjudication','origin_run_id':'constructed-interrupted-k',
        'record_origin':'derived_recovery_disposition','actual_request_issued':True,
        'orphan_attempt_id':request['attempt_id'],'request_sha256':request['request_sha256'],
        'provider_response_observed':False,'provider_completion_unknown':True,
        # Frozen final-row field: no response payload is available. Issuance is
        # represented above and in the unchanged request journal, not inferred
        # from this compatibility field.
        'issued':False,'terminal_valid':False,'attempt_id':None,'attempts_issued':1,
        'first_attempt_id':request['attempt_id'],'slot_final':True,
        'model_outcome':'issued_without_response','error':'host_interruption_orphan_request',
        'response_status':None,'output_text':'','usage':None,
        'scope':'Derived slot disposition only; no provider status, output, usage or original-run closure is asserted.'}


class RecoveryContractTests(unittest.TestCase):
    def make(self,conditions=None):
        data=small_fixture(conditions or [('strict_source_ir','extract','orphan')])
        corpus,dossiers,study,slots,texts=data
        finals,responses,requests,summary=journals(slots,texts)
        return data,finals,responses,requests,summary

    def test_orphan_final_uses_existing_frozen_missing_response_contract(self):
        data,_,_,requests,_=self.make();slots=data[3];before=deepcopy(requests)
        overlay=orphan_disposition(slots[0],requests[0]);_,final,by_slot,request_index=frozen.records(slots,[overlay],[],requests)
        self.assertEqual(requests,before);self.assertEqual(len(request_index),1)
        self.assertEqual(dict(by_slot),{});self.assertEqual(final[slots[0]['slot_id']],overlay)
        self.assertTrue(overlay['actual_request_issued']);self.assertFalse(overlay['provider_response_observed'])

    def test_no_fabricated_provider_payload_or_usage_and_both_grades_zero(self):
        data,_,_,requests,_=self.make();corpus,_,_,slots,_=data;case=corpus['cases'][0]
        overlay=orphan_disposition(slots[0],requests[0]);_,final,by_slot,_=frozen.records(slots,[overlay],[],requests)
        self.assertNotIn('http_status',overlay);self.assertIsNone(overlay['response_status']);self.assertIsNone(overlay['usage'])
        for view in ('first_attempt','eventual'):
            record,eligible=h._view_records(slots,final,by_slot,view)[slots[0]['slot_id']]
            grade=h._score_slot(slots[0],record,eligible,case,case['public']['source_documents'],{})
            self.assertFalse(grade['provider_completed']);self.assertFalse(grade['eligible_completed'])
            self.assertFalse(grade['correct']);self.assertEqual(grade['candidates'],[])
            self.assertEqual(grade['record_observed'],view=='eventual')

    def test_original_completion_gate_remains_false_even_after_all_slot_dispositions(self):
        data,_,_,requests,summary=self.make();slots=data[3]
        overlay=orphan_disposition(slots[0],requests[0]);_,final,_,_=frozen.records(slots,[overlay],[],requests)
        self.assertFalse(frozen.closed_summary(summary,slots,final,[],requests))
        result=frozen.evaluate(*data[:3],slots,[overlay],[],requests,summary,10,require_full_design=False)
        self.assertFalse(result['summary']['schedule_complete']);self.assertEqual(result['summary']['cluster_intervals'],[])
        self.assertEqual(result['summary']['issued_attempts_observed'],0)
        self.assertEqual(len(requests),1)  # New outer accounting must retain this.

    def test_orphan_cannot_be_upgraded_to_issued_final_without_response(self):
        data,_,_,requests,_=self.make();slots=data[3];overlay=orphan_disposition(slots[0],requests[0])
        overlay.update(issued=True,attempt_id=requests[0]['attempt_id'])
        with self.assertRaisesRegex(ValueError,'final attempt absent'):frozen.records(slots,[overlay],[],requests)

    def test_orphan_cannot_supply_assistant_history_or_nl_projection(self):
        data,finals,responses,requests,_=self.make([('nl_source','extract','nl'),('nl_projection','project','child')])
        slots=data[3];overlay=orphan_disposition(slots[0],requests[0]);kept_responses=[responses[1]]
        with self.assertRaisesRegex(ValueError,'unsuccessful dependency'):
            frozen.records(slots,[overlay,finals[1]],kept_responses,requests)

    def test_required_descendant_can_be_definitively_skipped_without_call(self):
        data,_,_,requests,_=self.make([('nl_source','extract','nl'),('nl_projection','project','child')]);slots=data[3]
        overlay=orphan_disposition(slots[0],requests[0]);s=slots[1]
        skipped={**{k:s[k] for k in ('slot_id','case_id','model','condition','phase')},
            'issued':False,'terminal_valid':False,'attempt_id':None,'slot_final':True,'attempts_issued':0,
            'model_outcome':'not_issued_dependency_failed','error':'not_issued_dependency_failed',
            'output_text':'','blocked_dependencies':[slots[0]['slot_id']]}
        _,final,by_slot,_=frozen.records(slots,[overlay,skipped],[],requests[:1])
        for view in ('first_attempt','eventual'):
            self.assertFalse(h._view_records(slots,final,by_slot,view)[s['slot_id']][1])
        self.assertEqual(len(requests[:1]),1)

    def test_changed_original_request_still_rejects(self):
        data,_,_,requests,_=self.make();slots=data[3];overlay=orphan_disposition(slots[0],requests[0])
        requests[0]['request']['instructions']='invented repair'
        requests[0]['request_sha256']=frozen.digest(requests[0]['request'])
        with self.assertRaisesRegex(ValueError,'frozen request'):frozen.records(slots,[overlay],[],requests)


if __name__=='__main__':unittest.main()
