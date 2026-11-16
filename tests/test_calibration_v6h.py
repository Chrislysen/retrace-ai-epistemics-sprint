import itertools
import unittest
from retrace.calibration_v6h import selective_risk, warning_precision_recall, sycophancy_flip_rate


class CalibrationTests(unittest.TestCase):
    def test_perfect_and_total_failure(self):
        for n in range(1,9):
            self.assertEqual(selective_risk([.5]*n,[False]*n)['aurc'],0)
            result=selective_risk([.5]*n,[True]*n)
            self.assertAlmostEqual(result['aurc'],1)
            self.assertAlmostEqual(result['augrc'],.5)
            self.assertAlmostEqual(result['excess_aurc'],0)

    def test_tied_scores_equal_average_over_all_permutations(self):
        labels=[False,False,True,True]
        values=[]
        for permutation in set(itertools.permutations(labels)):
            values.append(selective_risk([.9,.8,.7,.6],list(permutation)))
        tied=selective_risk([.5]*4,labels)
        for metric in ('aurc','augrc'):
            self.assertAlmostEqual(tied[metric],sum(x[metric] for x in values)/len(values))

    def test_augrc_pairwise_identity(self):
        for bits in itertools.product((False,True),repeat=5):
            errors=sum(bits); correct=5-errors
            risk=selective_risk([1,.8,.6,.4,.2],list(bits))
            # A high-confidence error before a correct item is a ranking inversion.
            inversions=sum(bits[i] and not bits[j] for i in range(5) for j in range(i+1,5))
            self.assertAlmostEqual(risk['augrc'],inversions/25 + .5*(errors/5)**2)
            self.assertGreaterEqual(risk['excess_aurc'],-1e-14)

    def test_average_precision_ties_and_no_positives(self):
        self.assertEqual(warning_precision_recall([.5,.5],[True,False])['average_precision'],.5)
        self.assertEqual(warning_precision_recall([1,0],[True,False])['average_precision'],1)
        self.assertIsNone(warning_precision_recall([.2],[False])['average_precision'])

    def test_invalid_scores_are_not_silently_imputed(self):
        for values in ([float('nan')],[-.1],[1.1],[True]):
            with self.assertRaises(ValueError): selective_risk(values,[False])

    def test_sfr_distinguishes_order_effect_and_missingness(self):
        rows=[{'valid':True,'choice_a':True,'choice_b':False,'preferred_a':True,'preferred_b':False},
              {'valid':True,'choice_a':False,'choice_b':True,'preferred_a':True,'preferred_b':False},
              {'valid':False}]
        result=sycophancy_flip_rate(rows)
        self.assertEqual(result['sfr_valid_pairs'],.5)
        self.assertEqual(result['all_choice_flips'],2)
        self.assertEqual(result['missingness_bounds'],[1/3,2/3])


if __name__=='__main__':unittest.main()
