import copy
import unittest

from retrace.engine_v5 import analyze_v5
from retrace.engine_v6 import analyze_v6, demonstration


class ConservationCompositionTests(unittest.TestCase):
    def test_shared_omission_blocks_unqualified_agreement_without_rewriting_graphs(self):
        brief = demonstration()
        original = copy.deepcopy(brief)
        old = analyze_v5(brief)
        new = analyze_v6(brief)
        self.assertTrue(new['source_review']['review_required'])
        self.assertTrue(new['source_review']['decisions']['D']['blocks_unqualified_unanimity'])
        self.assertEqual(new['source_review']['decisions']['D']['conditional_label'],
                         'Supported under declared links')
        self.assertEqual(new['decision_states'], old['decision_states'])
        self.assertEqual(new['compiled_brief']['candidates'], old['compiled_brief']['candidates'])
        self.assertEqual(brief, original)
        self.assertGreater(len(new['conservation']['gaps']), 0)

    def test_client_claim_of_complete_coverage_cannot_bypass_source_audit(self):
        brief = demonstration()
        brief['conservation'] = {'status': 'complete', 'gaps': []}
        brief['source_review'] = {'review_required': False}
        result = analyze_v6(brief)
        self.assertTrue(result['source_review']['review_required'])

    def test_review_gate_does_not_clear_document_or_passage_revocations(self):
        brief = demonstration()
        state = {'revoked_documents': ['transcriptions'], 'revoked_passages': ['A']}
        result = analyze_v6(brief, state)
        self.assertTrue(result['revocation_flags']['A']['document_veto'])
        self.assertTrue(result['revocation_flags']['A']['passage_veto'])
        self.assertEqual(result['decision_states'], analyze_v5(brief, state)['decision_states'])
        self.assertTrue(result['source_review']['review_required'])

    def test_document_text_is_the_audited_source_even_with_conflicting_display_prose(self):
        brief = demonstration()
        brief['source_documents'] = [{'id': 'actual-source', 'text': brief['prose']}]
        brief['prose'] = 'No dependencies mentioned.'
        result = analyze_v6(brief)
        self.assertTrue(result['source_review']['review_required'])
        self.assertTrue(all(row['source_span']['document_id'] == 'actual-source'
                            for row in result['conservation']['gaps']))

    def test_malformed_document_records_fail_closed(self):
        for value in ([], {}, [{'id': 'x', 'text': 17}], [{'text': 'source'}]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                brief = demonstration()
                brief['source_documents'] = value
                analyze_v6(brief)


if __name__ == '__main__':
    unittest.main()
