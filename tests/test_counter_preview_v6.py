import copy
import unittest

from retrace.counter_preview_v6 import preview_counter_reading
from retrace.engine_v6 import analyze_v6, demonstration


class CounterPreviewTests(unittest.TestCase):
    def test_checked_two_edge_preview_preserves_committed_state_and_warning(self):
        analysis = analyze_v6(demonstration())
        original = copy.deepcopy(analysis)
        proposal = {'status': 'counter_reading', 'changes': [
            {'target': target, 'replacement': {'kind': 'copy', 'parents': ['O']},
             'sources': [{'document_id': 'source', 'quote': f'Evidence {target} is copied from evidence O.'}]}
            for target in ('A', 'B')]}
        preview = preview_counter_reading(analysis, proposal)
        self.assertTrue(preview['consequential_within_scope'])
        self.assertFalse(preview['semantic_verified'])
        self.assertFalse(preview['auto_applied'])
        self.assertEqual(analysis, original)
        self.assertTrue(preview['source_review_unchanged']['review_required'])

    def test_actual_revocations_become_locked_exclusions(self):
        analysis = analyze_v6(demonstration(), {'revoked_documents': ['transcriptions']})
        preview = preview_counter_reading(analysis, {'status': 'no_counter_reading'})
        self.assertTrue(all(not values['D'] for values in preview['seed_pool_current_outcomes'].values()))
        self.assertFalse(preview['auto_applied'])

    def test_exhausted_candidate_pool_cannot_accept_a_preview(self):
        analysis = analyze_v6(demonstration())
        analysis['candidate_ids'] = []
        with self.assertRaises(ValueError):
            preview_counter_reading(analysis, {'status': 'no_counter_reading'})


if __name__ == '__main__':
    unittest.main()
