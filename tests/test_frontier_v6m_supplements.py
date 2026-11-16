"""Invented adapter fixtures only; run after the active recovery closes."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_frontier_v6m_supplements as module


class SupplementAdapterTests(unittest.TestCase):
    def result(self):
        frozen = {'cluster_intervals': [], 'paired_comparisons': [
            {'view': 'first_attempt', 'primary_family_member': True,
             'p_two_sided_exact': None, 'holm_adjusted_p': None} for _ in range(21)]}
        return {'summary': {'status': module.score.COMPLETE, 'frozen_diagnostic': frozen,
                            'amended_recovered_complete': {'sentinel': 'never used for descriptive grading'}},
                'audits': ['invented'], 'merged_evidence': {'invented': True}}

    def test_original_diagnostic_passed_without_mutation(self):
        result = self.result()
        before = deepcopy(result)
        data = {'corpus': {}, 'study': {}, 'sessions': []}
        with patch.object(module, 'analyze_trajectories', return_value={'a': 1}), \
                patch.object(module, 'analyze_refuter_partitions', return_value={'b': 2}), \
                patch.object(module, 'analyze_missingness', return_value={'c': 3}) as missing:
            outputs = module.project(result, data)
        self.assertEqual(len(outputs), 3)
        self.assertEqual(result, before)
        self.assertIs(missing.call_args.args[2]['summary'], result['summary']['frozen_diagnostic'])

    def test_nonnull_frozen_inference_rejected(self):
        result = self.result()
        result['summary']['frozen_diagnostic']['paired_comparisons'][0]['p_two_sided_exact'] = 0.02
        with self.assertRaisesRegex(ValueError, 'diagnostic'):
            module.project(result, {})

    def test_missing_primary_test_rejected(self):
        result = self.result()
        result['summary']['frozen_diagnostic']['paired_comparisons'].pop()
        with self.assertRaisesRegex(ValueError, 'diagnostic'):
            module.project(result, {})

    def test_helper_mutation_rejected(self):
        result = self.result()
        def mutate(*_):
            result['audits'].append('forbidden')
            return {}
        with patch.object(module, 'analyze_trajectories', side_effect=mutate), \
                patch.object(module, 'analyze_refuter_partitions', return_value={}), \
                patch.object(module, 'analyze_missingness', return_value={}):
            with self.assertRaisesRegex(ValueError, 'changed original evidence'):
                module.project(result, {'corpus': {}, 'study': {}, 'sessions': []})

    def test_active_worker_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock = root / module.score.LOCK
            lock.parent.mkdir(parents=True)
            lock.write_bytes(b'')
            with self.assertRaisesRegex(ValueError, 'active'):
                module.recheck(root, {})


if __name__ == '__main__':
    unittest.main()
