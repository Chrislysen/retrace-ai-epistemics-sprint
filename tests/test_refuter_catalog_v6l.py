"""Invented all-grid first attempts; no real answers or network."""
from copy import deepcopy
import json
import unittest
from retrace import refuter_catalog_v6l as catalog
from retrace.refuter_gate_v6h import validate_refuter
from retrace.source_ir_v6d import model_source
from tests.test_frontier_v6l_catalog import fixture as base_fixture,bind,entry
from tests.test_refuter_inspector_v6l import DOCS,REG,graph,candidates,envelope


def fixture(full=False):
    corpus,study,slots,audits,merged=base_fixture(full=full)
    for case in corpus['cases']:case['public']={'source_documents':deepcopy(DOCS),'registry':deepcopy(REG)}
    for slot in slots:
        slot.update(condition='adversarial_refuter',phase='counter_read',input=json.dumps({**model_source(DOCS,REG),'supplied_candidates':candidates(graph())}))
    for req,slot in zip(merged['requests'],slots):req['request']['input'][-1]['content']=slot['input']
    raw=json.dumps(envelope())
    for row in merged['responses']+merged['outcomes']:row.update(condition='adversarial_refuter',phase='counter_read',output_text=raw)
    for audit in audits:audit.update(condition='adversarial_refuter',phase='counter_read',refuter_gate=validate_refuter(raw,DOCS,REG))
    bind(merged);return corpus,study,slots,audits,merged


def build(data,full=False):return catalog.build_catalog(*data,require_full_design=full)


class CatalogTests(unittest.TestCase):
    def test_all300_and_public_projection_poison_independent(self):
        data=fixture(True);before=deepcopy(data);out=build(data,True)
        self.assertEqual(data,before);self.assertEqual(out['index']['scheduled_slots'],300)
        text=json.dumps(out)
        for hidden in ('HIDDEN_GOLD','HIDDEN_SEED','HIDDEN_FAMILY','source_exact_family','seed_exact_evaluation_only','correct_decisions'):
            self.assertNotIn(hidden,text)
        self.assertEqual(out['index']['counts']['source_located_proposal'],300)
        self.assertEqual(len(out['bundles']),0)

    def test_exact_supplied_seed_comes_from_model_packet_only(self):
        data=fixture();data[0]['cases'][0]['authored_seed_pool']={'candidates':'NOT_THE_SENT_PACKET'}
        out=entry(build(data));self.assertEqual(out['supplied_candidates'],candidates(graph()))
        self.assertNotIn('NOT_THE_SENT_PACKET',json.dumps(out))

    def test_stale_request_or_source_rejects(self):
        for change in ('request','source'):
            data=fixture()
            if change=='request':data[4]['requests'][0]['request']['input'][-1]['content']='{}';bind(data[4])
            else:data[0]['cases'][0]['public']['source_documents'][0]['text']+=' changed'
            with self.subTest(change=change),self.assertRaises(ValueError):build(data)

    def test_failed_first_attempt_not_replaced_by_successful_retry(self):
        data=fixture();first=data[4]['responses'][0];second=deepcopy(first)
        second.update(attempt_id=first['attempt_id']+'-retry',attempt_number=2,first_attempt=False)
        req=deepcopy(data[4]['requests'][0]);req.update(attempt_id=second['attempt_id'],attempt_number=2,first_attempt=False)
        first.update(error='http_429',response_status=None,model_outcome='provider_error',terminal_valid=False,output_text='')
        data[4]['responses'].append(second);data[4]['requests'].append(req);data[4]['outcomes'][0]=deepcopy(second)
        data[3][0].update(provider_completed=False,eligible_completed=False,schema_valid=False,refuter_gate=None)
        bind(data[4]);out=entry(build(data))
        self.assertEqual(out['metadata']['status'],'provider_failure');self.assertIsNone(out['inspection'])
        self.assertEqual(out['raw_output_text'],'');self.assertEqual(out['metadata']['attempts_observed'],2)

    def test_unissued_and_partial_never_become_proposals(self):
        data=fixture();data[4]['requests']=[];data[4]['responses']=[]
        data[4]['outcomes'][0].update(issued=False,model_outcome='not_issued_global_stop',output_text='')
        data[3][0].update(record_observed=False,provider_completed=False,eligible_completed=False,schema_valid=False,refuter_gate=None)
        bind(data[4]);out=entry(build(data));self.assertEqual(out['metadata']['status'],'not_issued');self.assertIsNone(out['inspection'])
        data=fixture();first=data[4]['responses'][0]
        first.update(response_status='incomplete',model_outcome='truncated_max_output_tokens',output_text='',partial_output_text=json.dumps(envelope()))
        data[4]['outcomes'][0]=deepcopy(first);data[3][0].update(provider_completed=False,eligible_completed=False,schema_valid=False,refuter_gate=None)
        bind(data[4]);out=entry(build(data));self.assertEqual(out['metadata']['status'],'truncated_output');self.assertIsNone(out['inspection'])

    def test_downstream_grade_failure_does_not_become_correctness_claim(self):
        data=fixture();data[3][0].update(error='invalid_ValueError',candidates=[],compilation=None,correct=False)
        out=entry(build(data));self.assertEqual(out['metadata']['status'],'source_located_proposal')
        self.assertNotIn('"correct":',json.dumps(out));catalog.validate_entry(out)

    def test_rehashed_gate_promotion_and_hidden_fields_reject(self):
        out=entry(build(fixture()));out['inspection']['semantic_entailment_verified']=True
        with self.assertRaises(ValueError):catalog.validate_entry(out)
        out=entry(build(fixture()));out['metadata']['gold']='hidden'
        with self.assertRaises(ValueError):catalog.validate_entry(out)

    def test_no_union_truncation_over_32_total_rows(self):
        data=fixture();p=json.loads(data[2][0]['input']);p['supplied_candidates']=candidates(*[graph() for _ in range(32)])
        data[2][0]['input']=json.dumps(p);data[4]['requests'][0]['request']['input'][-1]['content']=data[2][0]['input'];bind(data[4])
        out=entry(build(data));self.assertEqual(len(out['supplied_candidates']),32)
        self.assertEqual(out['inspection']['preview']['status'],'preview_only')


if __name__=='__main__':unittest.main()
