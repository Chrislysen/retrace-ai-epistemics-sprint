from copy import deepcopy
import unittest
from retrace.refuter_gate_v6h import validate_refuter
from retrace.prompts_v6h import EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY,example_ir


class RefuterGateTests(unittest.TestCase):
    def proposal(self):
        ir=example_ir()
        return {'status':'objection','ir':ir,'objection_spans':ir['entities'][0]['citations'],'warning_score':.8}

    def test_exact_location_admits_review_not_truth_or_mutation(self):
        value=self.proposal();before=deepcopy(value)
        result=validate_refuter(value,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)
        self.assertEqual(value,before);self.assertFalse(result['proposal_applied']);self.assertFalse(result['semantic_entailment_verified'])
        location=result['locations'][0]
        self.assertEqual(EXAMPLE_DOCUMENTS[0]['text'][location['start']:location['end']],location['text'])

    def test_hallucinated_span_rejects_even_with_valid_ir(self):
        value=self.proposal();value['objection_spans']=['invented']
        with self.assertRaises(ValueError):validate_refuter(value,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)

    def test_cited_but_semantically_wrong_statement_is_not_certified(self):
        value=self.proposal();row=next(p for p in value['ir']['propositions'] if p['kind']=='support')
        row['body']['positive']={'ref':'EXU'}
        result=validate_refuter(value,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)
        self.assertEqual(result['status'],'source_located_proposal')
        self.assertFalse(result['semantic_entailment_verified'])

    def test_bad_branch_rejects_before_any_proposal_returned(self):
        value=self.proposal();value['ir']['propositions'].pop()
        with self.assertRaises(ValueError):validate_refuter(value,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)

    def test_registry_gap_rejects_before_a_warning_or_proposal(self):
        registry=deepcopy(EXAMPLE_REGISTRY);registry['evidence'].append('EXOTHER')
        with self.assertRaisesRegex(ValueError,'explicit dispositions'):
            validate_refuter(self.proposal(),EXAMPLE_DOCUMENTS,registry)

    def test_abstention_and_score_types(self):
        value={'status':'no_counter_reading','ir':None,'objection_spans':[],'warning_score':.1}
        self.assertEqual(validate_refuter(value,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)['status'],'abstained')
        for score in (True,float('nan'),1.1):
            value['warning_score']=score
            with self.assertRaises(ValueError):validate_refuter(value,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)

if __name__=='__main__':unittest.main()
