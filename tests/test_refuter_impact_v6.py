from copy import deepcopy
import itertools
import random
import unittest

from retrace.core import analyze
from retrace.refuter_impact_v6 import compare_readings


def candidate(routes, *, name='g', active=None, parents=None):
    active = active or {}
    parents = parents or {}
    return {'id': name, 'graph': {
        'evidence': [{'id': x, 'kind': 'copy' if parents.get(x) else 'root',
                      'active': active.get(x, True), 'parents': parents.get(x, [])}
                     for x in 'ABCDE'],
        'claims': [{'id': 'C0', 'supports': routes}],
        'decisions': [{'id': 'D0', 'requires': ['C0']}],
    }}


def consensus(candidates, withdrawn):
    values = [analyze(c['graph'], withdrawn)['decisions']['D0']['usable'] for c in candidates]
    return 'unanimous_supported' if all(values) else 'disputed' if any(values) else 'unanimous_unsupported'


class RefuterImpactTests(unittest.TestCase):
    def test_three_way_loss_after_single_and_pair_withdrawals_survive(self):
        old = [candidate([[x] for x in 'ABCD'])]
        proposal = [candidate([[x] for x in 'ABC'])]
        pristine = deepcopy((old, proposal))
        result = compare_readings(old, proposal)
        witness = result['decisions']['D0']['minimum_consensus_loss']
        self.assertEqual(witness['withdraw'], ['A', 'B', 'C'])
        self.assertEqual(witness['current_family_state'], 'unanimous_supported')
        self.assertEqual(witness['augmented_family_state'], 'disputed')
        self.assertEqual((old, proposal), pristine)

    def test_five_way_minimum_is_not_silently_capped_at_pairs(self):
        # Six alternative routes versus five agree until all five shared routes
        # are withdrawn, beyond the single/pair boundary of earlier guards.
        old = candidate([[x] for x in 'ABCDE'])
        old['graph']['evidence'].append({'id': 'F', 'kind': 'root', 'active': True, 'parents': []})
        new = deepcopy(old)
        old['graph']['claims'][0]['supports'].append(['F'])
        witness = compare_readings([old], [new])['decisions']['D0']['minimum_consensus_loss']
        self.assertEqual(witness['withdraw'], list('ABCDE'))
        self.assertEqual(witness['k'], 5)

    def test_pairwise_difference_does_not_break_already_disputed_family(self):
        a, b = candidate([['A']], name='a'), candidate([['B']], name='b')
        result = compare_readings([a, b], [deepcopy(a)])
        self.assertEqual(result['novel_proposed_graphs'], 0)
        self.assertIsNone(result['decisions']['D0']['minimum_consensus_loss'])
        # A novel but semantically equivalent (redundant route) graph still adds
        # no consensus loss to a family already covering both decision values.
        novel = candidate([['A'], ['A', 'B']], name='third')
        result = compare_readings([a, b], [novel])
        self.assertEqual(result['novel_proposed_graphs'], 1)
        self.assertEqual(result['decisions']['D0']['affected_withdrawal_states'], 0)

    def test_current_unanimous_unsupported_can_be_challenged_without_withdrawal(self):
        result = compare_readings([candidate([])], [candidate([['A']])])
        witness = result['decisions']['D0']['minimum_consensus_loss']
        self.assertEqual(witness['k'], 0)
        self.assertEqual(witness['current_family_state'], 'unanimous_unsupported')
        self.assertEqual(witness['augmented_family_state'], 'disputed')

    def test_locked_veto_and_original_ineligibility_never_get_restored(self):
        old = candidate([['A']], active={'A': False})
        new = candidate([['B']], active={'A': False})
        result = compare_readings([old], [new], locked_exclusions=['B'])
        self.assertIsNone(result['decisions']['D0']['minimum_consensus_loss'])
        self.assertNotIn('B', result['withdrawal_variables'])

    def test_shared_parent_omission_yields_ancestor_withdrawal(self):
        old = candidate([['B'], ['C']])
        new = candidate([['B'], ['C']], parents={'B': ['A'], 'C': ['A']})
        witness = compare_readings([old], [new])['decisions']['D0']['minimum_consensus_loss']
        self.assertEqual(witness['withdraw'], ['A'])

    def test_rejects_registry_mismatch_and_duplicate_restrictions(self):
        old = candidate([['A']])
        new = deepcopy(old); new['graph']['decisions'][0]['id'] = 'other'
        with self.assertRaises(ValueError): compare_readings([old], [new])
        with self.assertRaises(ValueError): compare_readings([old], [old], locked_exclusions=['A', 'A'])
        with self.assertRaises(ValueError): compare_readings([old], [old], allowed_withdrawals=['missing'])

    def test_exact_minima_against_independent_state_by_state_core(self):
        rng = random.Random(713)
        for _ in range(100):
            def family(prefix):
                return [candidate([rng.sample(list('ABCDE'), rng.randint(1, 3))
                                   for _ in range(rng.randint(0, 5))], name=f'{prefix}{j}',
                                  active={x: rng.random() > .15 for x in 'ABCDE'})
                        for j in range(rng.randint(1, 4))]
            old, new = family('old'), family('new')
            locked = rng.sample(list('ABCDE'), rng.randint(0, 2))
            allowed = sorted(set(rng.sample(list('ABCDE'), rng.randint(0, 5))) - set(locked))
            expected = []
            for k in range(len(allowed) + 1):
                for subset in itertools.combinations(allowed, k):
                    veto = locked + list(subset)
                    if consensus(old, veto) != consensus(old + new, veto): expected.append(list(subset))
            decision = compare_readings(old, new, locked_exclusions=locked,
                                        allowed_withdrawals=allowed)['decisions']['D0']
            self.assertEqual(decision['affected_withdrawal_states'], len(expected))
            actual = decision['minimum_consensus_loss']
            self.assertEqual(actual['withdraw'] if actual else None, expected[0] if expected else None)


if __name__ == '__main__':
    unittest.main()
