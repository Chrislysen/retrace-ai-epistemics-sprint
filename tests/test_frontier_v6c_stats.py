import unittest
from retrace.frontier_v6c_stats import exact_mcnemar, holm_adjust, case_cluster_bootstrap, mcnemar_design_power


class PairedStatisticsTests(unittest.TestCase):
    def test_exact_known_tail_and_symmetry(self):
        a, b = [False] * 8, [True] * 8
        self.assertEqual(exact_mcnemar(a, b)['p_two_sided_exact'], 1 / 128)
        self.assertEqual(exact_mcnemar(b, a)['p_two_sided_exact'], 1 / 128)
        self.assertEqual(exact_mcnemar([True, False], [True, False])['p_two_sided_exact'], 1)

    def test_mixed_discordance(self):
        result = exact_mcnemar([True] * 3 + [False] * 7, [False] * 3 + [True] * 7)
        self.assertAlmostEqual(result['p_two_sided_exact'], .34375)

    def test_cluster_rejects_sample_pseudoreplication(self):
        row = {'case_id': 'a', 'family': 'one', 'metrics': {'delta': 1}}
        with self.assertRaises(ValueError): case_cluster_bootstrap([row, row])

    def test_paired_metrics_resample_together_and_order_invariant(self):
        rows = [{'case_id': str(i), 'family': str(i % 2), 'metrics': {'a': i % 3, 'b': i % 3 + 1, 'delta': 1}} for i in range(8)]
        result = case_cluster_bootstrap(rows, repeats=500)
        self.assertEqual(result, case_cluster_bootstrap(list(reversed(rows)), repeats=500))
        self.assertEqual(result['metrics']['delta']['percentile_95_interval'], [1, 1])
        self.assertEqual(result['family_counts'], {'0': 4, '1': 4})

    def test_holm_monotone_and_original_order(self):
        self.assertEqual(holm_adjust([.04, .001, .02]), [.04, .003, .04])
        with self.assertRaises(ValueError): holm_adjust([float('nan')])

    def test_power_extreme_and_null(self):
        self.assertEqual(mcnemar_design_power(8, 1, 1), 1)
        self.assertEqual(mcnemar_design_power(5, 1, 1), 0)
        self.assertLessEqual(mcnemar_design_power(48, .4, 0), .05)
        self.assertGreater(mcnemar_design_power(48, .4, .3), mcnemar_design_power(48, .4, .1))

    def test_missing_metrics_not_silently_dropped(self):
        with self.assertRaises(ValueError):
            case_cluster_bootstrap([{'case_id':'a','family':'f','metrics':{'x':None}}])


if __name__ == '__main__': unittest.main()
