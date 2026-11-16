import itertools
import json
from pathlib import Path
import random
import unittest
from copy import deepcopy

from retrace.boolean_v6h import BDD, evaluate, validate_expr, minimum_withdrawal, hamming2_witnesses
from retrace.argumentation_v6h import grounded_partitioned, rebuttal_arbiter
from retrace.tiered_v6h import SCHEMA, FALSE, analyze, family_supervaluation, from_positive_graph, tier_a_bdd, validate
from retrace.core import analyze as old_analyze


def ref(x): return {'ref': x}
def all_(*xs): return {'all': list(xs)}
def any_(*xs): return {'any': list(xs)}
def unless(a, u): return {'unless': {'support': a, 'undercutter': u}}
def fixture():
    return {'schema': SCHEMA,
            'evidence': [{'id': x, 'kind': 'root', 'active': True, 'parents': []} for x in 'ABU'],
            'claims': [{'id': 'C', 'positive': unless(any_(ref('A'), ref('B')), ref('U')), 'negative': FALSE.copy()}],
            'decisions': [{'id': 'D', 'requires': ['C']}]}


class BooleanTests(unittest.TestCase):
    def test_boolean_algebra_and_monus_exhaustive(self):
        b = BDD(['a', 'b', 'c']); a, x, c = [b.variable(v) for v in b.variables]
        self.assertEqual(a, b.apply('or', a, b.apply('and', a, x)))
        self.assertEqual(a, b.apply('and', a, a))
        self.assertEqual(a, b.apply('or', a, a))
        self.assertEqual(b.apply('and', a, b.apply('or', x, c)), b.apply('or', b.apply('and', a, x), b.apply('and', a, c)))
        self.assertEqual(b.apply('monus', b.apply('or', a, x), c), b.apply('or', b.apply('monus', a, c), b.apply('monus', x, c)))
        self.assertNotEqual(b.apply('monus', b.apply('monus', a, x), c), b.apply('monus', a, b.apply('monus', x, c)))
        for av, bv in itertools.product((False, True), repeat=2):
            self.assertEqual(b.evaluate(b.apply('monus', a, x), {'a': av, 'b': bv, 'c': False}), av and not bv)

    def test_500_random_expressions_bdd_vs_direct_all_assignments(self):
        rng = random.Random(20261114); identifiers = list('abcd'); b = BDD(identifiers)
        def expression(depth):
            if depth == 0 or rng.random() < .3: return ref(rng.choice(identifiers))
            op = rng.choice(['all', 'any', 'unless']); children = [expression(depth-1) for _ in range(2)]
            return unless(*children) if op == 'unless' else {op: children}
        for _ in range(500):
            expr = expression(4); validate_expr(expr, set(identifiers)); root = b.compile(expr)
            for bits in itertools.product((False, True), repeat=4):
                values = dict(zip(identifiers, bits))
                self.assertEqual(evaluate(expr, values), b.evaluate(root, values))

    def test_scoped_unless_does_not_kill_backup(self):
        values = {'A': True, 'B': True, 'U': True}
        self.assertTrue(evaluate(any_(unless(ref('A'), ref('U')), ref('B')), values))
        self.assertFalse(evaluate(unless(any_(ref('A'), ref('B')), ref('U')), values))

    def test_monus_nonmonotone_withdrawal(self):
        expr = unless(ref('A'), ref('U'))
        witness = minimum_withdrawal(lambda v: evaluate(expr, v), {'A': True, 'U': True}, ['A', 'U'])
        self.assertEqual(witness, {'k': 1, 'withdraw': ['U'], 'before': False, 'after': True})

    def test_hamming2_finds_dormant_mask_and_preserves_locks(self):
        expr = all_(ref('A'), ref('B'))
        f = lambda v: evaluate(expr, v)
        self.assertEqual(len(hamming2_witnesses(f, {'A': True, 'B': False})), 1)
        self.assertEqual(hamming2_witnesses(f, {'A': True, 'B': False}, locked=['B']), [])

    def test_hamming2_label_change_must_return_to_baseline(self):
        f = lambda v: 'contested' if not v['B'] else 'supported' if v['A'] else 'not_supported'
        self.assertEqual(hamming2_witnesses(f, {'A':True,'B':False}), [])

    def test_bad_expression_and_bound_fail_closed(self):
        for expr in ({'not': ref('a')}, {'const': 1}, {'all': [ref('a')]}, {'ref': 'z'}, {'unless': {'support': ref('a')}}):
            with self.assertRaises(ValueError): validate_expr(expr, {'a'})
        b = BDD(['a', 'b'], max_nodes=3); b.variable('a')
        with self.assertRaises(ValueError): b.variable('b')


class ArgumentTests(unittest.TestCase):
    def test_partition_vs_independent_characteristic_fixed_point(self):
        rng = random.Random(1824)
        for n in range(1, 9):
            for _ in range(20):
                ids = [str(i) for i in range(n)]
                edges = {(a,b) for a in ids for b in ids if rng.random() < .2}
                inside = set()
                while True:
                    defended = {a for a in ids if all(any((s,b) in edges for s in inside) for b in ids if (b,a) in edges)}
                    if defended == inside: break
                    inside = defended
                self.assertEqual(set(grounded_partitioned(ids, edges)['in']), inside)

    def test_rebuttal_does_not_explode_and_attacks_dependents(self):
        args = [{'id': 'p', 'claim': 'C', 'polarity': 'positive', 'subarguments': []},
                {'id': 'n', 'claim': 'C', 'polarity': 'negative', 'subarguments': []},
                {'id': 'dependent', 'claim': 'E', 'polarity': 'positive', 'subarguments': ['p']},
                {'id': 'unrelated', 'claim': 'Z', 'polarity': 'positive', 'subarguments': []}]
        result = rebuttal_arbiter(args)
        self.assertEqual(result['in'], ['unrelated'])
        self.assertIn(['n', 'dependent'], result['attacks'])
        self.assertEqual(set(result['undecided']), {'p', 'n', 'dependent'})

    def test_self_attack_and_defended_argument(self):
        self.assertEqual(grounded_partitioned(['a'], [('a','a')])['undecided'], ['a'])
        self.assertEqual(grounded_partitioned(['a','b','c'], [('a','b'),('b','c')])['in'], ['a','c'])

    def test_argument_cycle_rejected(self):
        with self.assertRaises(ValueError):
            rebuttal_arbiter([{'id':'a','claim':'C','polarity':'positive','subarguments':['a']}])


class TieredTests(unittest.TestCase):
    def test_tier_a_bdd_matches_arbitrated_known_graph(self):
        graph = fixture(); b, roots = tier_a_bdd(graph)
        for bits in itertools.product((False, True), repeat=3):
            values = dict(zip('ABU', bits)); result = analyze(graph, local_overrides=values)
            self.assertEqual(b.evaluate(roots['D'], values), result['decisions']['D']['box_supported'])

    def test_four_states_and_locality(self):
        graph = fixture(); graph['claims'][0]['positive'] = ref('A'); graph['claims'][0]['negative'] = ref('B')
        graph['claims'].append({'id':'Z','positive':ref('U'),'negative':FALSE.copy()})
        graph['decisions'].append({'id':'DZ','requires':['Z']})
        self.assertEqual(analyze(graph)['decisions']['D']['state'], 'contested')
        self.assertEqual(analyze(graph)['decisions']['DZ']['state'], 'supported')
        self.assertEqual(analyze(graph, passage_vetoes=['B'])['decisions']['D']['state'], 'supported')
        self.assertEqual(analyze(graph, passage_vetoes=['A'])['decisions']['D']['state'], 'not_supported')
        graph['evidence'][0]['kind'] = 'unknown'
        self.assertEqual(analyze(graph)['decisions']['D']['state'], 'insufficient_provenance')

    def test_unknown_irrelevant_alternative_does_not_block(self):
        graph = fixture(); graph['claims'][0]['positive'] = any_(ref('A'), ref('B')); graph['evidence'][0]['kind'] = 'unknown'
        self.assertEqual(analyze(graph)['decisions']['D']['state'], 'supported')

    def test_uncontested_backup_survives_contested_route(self):
        graph = fixture(); graph['claims'][0]['positive'] = ref('A'); graph['claims'][0]['negative'] = ref('B')
        graph['claims'].append({'id':'E','positive':any_(ref('C'),ref('U')),'negative':FALSE.copy()})
        graph['decisions'][0]['requires'] = ['E']
        result = analyze(graph)
        self.assertEqual(result['claims']['C']['state'], 'contested')
        self.assertEqual(result['claims']['E']['state'], 'supported')
        self.assertTrue(result['decisions']['D']['box_supported'])

    def test_unknown_blocked_and_document_passage_vetoes_independent(self):
        graph = fixture(); graph['claims'][0]['positive'] = ref('A'); graph['evidence'][0]['kind'] = 'unknown'
        self.assertEqual(analyze(graph, document_vetoes=['A'])['decisions']['D']['state'], 'not_supported')
        result = analyze(graph, document_vetoes=[], passage_vetoes=['A'], local_overrides={'A':True})
        self.assertEqual(result['decisions']['D']['state'], 'not_supported')

    def test_copy_collapse_keeps_local_withdrawal(self):
        graph = fixture(); graph['evidence'][1].update(kind='copy', parents=['A'])
        graph['claims'][0]['positive'] = any_(ref('A'), ref('B'))
        b, roots = tier_a_bdd(graph)
        self.assertEqual(roots['C'], roots['A'])
        graph['claims'][0]['positive'] = ref('B')
        self.assertFalse(analyze(graph, passage_vetoes=['B'])['decisions']['D']['box_supported'])
        self.assertFalse(analyze(graph, passage_vetoes=['A'])['decisions']['D']['box_supported'])

    def test_family_supervaluation_keeps_all_worlds(self):
        a = fixture(); a['claims'][0]['positive'] = ref('A')
        b = deepcopy(a); b['claims'][0]['positive'] = unless(ref('A'), ref('U'))
        row = family_supervaluation([a,b])['decisions']['D']
        self.assertFalse(row['box_supported']); self.assertTrue(row['diamond_supported']); self.assertFalse(row['interpretation_invariant'])

    def test_invariance_compares_aligned_unknowns_not_just_state_sets(self):
        a = fixture(); a['evidence'][0]['kind']='unknown'; a['claims'][0]['positive']=ref('A')
        b = deepcopy(a); b['claims'][0]['positive']=unless(ref('B'),ref('A'))
        result = family_supervaluation([a,b])['decisions']['D']
        self.assertTrue(result['possible_state_set_invariant'])
        self.assertFalse(result['interpretation_invariant'])

    def test_invalid_empty_override_values_rejected(self):
        for value in ([],False,'',0):
            with self.assertRaises(ValueError):analyze(fixture(),local_overrides=value)

    def test_polar_rebuttal_not_silently_treated_as_tier_a(self):
        graph = fixture(); graph['claims'][0]['negative'] = ref('B')
        with self.assertRaises(ValueError): tier_a_bdd(graph)

    def test_undercutter_on_contested_claim_is_explicitly_outside_fragment(self):
        graph = fixture(); graph['claims'].append({'id':'E','positive':unless(ref('B'), ref('C')),'negative':FALSE.copy()})
        with self.assertRaises(ValueError): validate(graph)

    def test_existing_201_source_worlds_agree_at_all_single_withdrawals(self):
        root = Path(__file__).resolve().parents[1]
        corpus = json.loads((root/'data/frontier-v6c-staged.json').read_text(encoding='utf-8'))
        count = 0
        for case in corpus['cases']:
            # The corpus key is explicit and has never been projected to models.
            families = case['evaluation']['source_family']
            for item in families:
                old = item['graph'] if 'graph' in item else item
                graph = from_positive_graph(old)
                for withdrawn in [[]] + [[row['id']] for row in old['evidence']]:
                    expected = old_analyze(old, withdrawn)
                    actual = analyze(graph, scenario_withdrawals=withdrawn)
                    self.assertEqual({d:r['usable'] for d,r in expected['decisions'].items()},
                                     {d:r['box_supported'] for d,r in actual['decisions'].items()})
                count += 1
        self.assertEqual(count, 201)


if __name__ == '__main__': unittest.main()
