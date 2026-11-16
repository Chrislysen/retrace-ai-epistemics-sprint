"""Prospective scoring checks using independently authored tiny source cases."""
from copy import deepcopy
import itertools
import json
import unittest
from unittest.mock import patch

from retrace.frontier_v6d_eval import evaluate, actual_event_fidelity, MODELS, PHASES
from retrace.source_ir_v6d import source_segments, compile_cited_ir


def truth(graph, excluded):
    nodes = {n['id']: (category, n) for category, rows in graph.items() for n in rows}
    def read(ident):
        category, node = nodes[ident]
        if category == 'evidence':
            return node['active'] and ident not in excluded and all(read(parent) for parent in node['parents'])
        if category == 'claims':
            return any(all(read(member) for member in route) for route in node['supports'])
        return all(read(member) for member in node['requires'])
    return {n['id']: read(n['id']) for n in graph['decisions']}


def ir_for(graph, documents):
    sid = source_segments(documents)[0]['span_id']
    ir = {'schema': 'retrace.source-ir.v6d', 'entities': [], 'bindings': [], 'choices': [],
          'combination': {'mode': 'cartesian', 'assignments': [], 'citations': []}, 'propositions': []}
    def add(kind, target, body):
        ir['propositions'].append({'id': kind + '_' + target, 'kind': kind, 'target': target, 'body': body,
                                   'scope': 'current', 'polarity': 'assert', 'when': {}, 'citations': [sid], 'bindings': []})
    for category, singular in [('evidence', 'evidence'), ('claims', 'claim'), ('decisions', 'decision')]:
        for node in graph[category]:
            ir['entities'].append({'id': node['id'], 'type': singular, 'operational': True, 'citations': [sid]})
            if category == 'evidence':
                add('eligibility', node['id'], {'active': node['active']})
                add('origin', node['id'], {'kind': node['kind'], 'parents': node['parents']})
            elif category == 'claims':
                terms = [{'ref': route[0]} if len(route) == 1 else {'all': [{'ref': member} for member in route]} for route in node['supports']]
                add('support', node['id'], {'expr': {'none': True} if not terms else terms[0] if len(terms) == 1 else {'any': terms}})
            else:
                add('requirement', node['id'], {'requires': node['requires']})
    return ir


def case_fixture(*, faithful=False, many=False, redundant=False):
    if many:
        source = 'R is an eligible original. ' + ' '.join(f'E{i} is eligible and independently either original or a copy of R.' for i in range(5))
        source += ' C accepts any E record alone. D requires C. Every combination of the five choices is admitted.'
        graphs = []
        for bits in itertools.product((False, True), repeat=5):
            evidence = [{'id': 'R', 'kind': 'root', 'active': True, 'parents': []}]
            evidence += [{'id': f'E{i}', 'kind': 'copy' if bit else 'root', 'active': True, 'parents': ['R'] if bit else []} for i, bit in enumerate(bits)]
            graphs.append({'evidence': evidence, 'claims': [{'id': 'C', 'supports': [[f'E{i}'] for i in range(5)]}], 'decisions': [{'id': 'D', 'requires': ['C']}]})
        revoked = ['R']
    else:
        source = 'A and B are locally eligible original evidence. Claim C accepts A alone or B alone. Decision D requires C.'
        graphs = [{'evidence': [{'id': ident, 'kind': 'root', 'active': True, 'parents': []} for ident in ('A', 'B')],
                   'claims': [{'id': 'C', 'supports': [['A'], ['B']]}], 'decisions': [{'id': 'D', 'requires': ['C']}]}]
        if redundant:
            # B copies A. C=A OR B is behaviorally equal to C=A at every local
            # eligibility assignment, but the full source structures differ.
            source = 'A is locally eligible original evidence. B is an eligible copy of A. Claim C accepts A alone or B alone. Decision D requires C.'
            graphs[0]['evidence'][1].update(kind='copy', parents=['A'])
        revoked = ['A']
    documents = [{'id': 'source', 'text': source}]
    family = [{'id': f'gold-{i:02d}', 'graph': graph} for i, graph in enumerate(graphs)]
    seed = deepcopy(family if faithful else [family[0]])
    for i, candidate in enumerate(seed):
        candidate['id'] = f'seed-{i:02d}'
    if not faithful and not many:
        seed[0]['graph']['claims'][0]['supports'] = [['A']] if redundant else [['A', 'B']]
    states = {'initial': {'revoked_documents': [], 'revoked_passages': []},
              'withdrawn': {'revoked_documents': [], 'revoked_passages': revoked},
              'restored': {'revoked_documents': [], 'revoked_passages': []}}
    mapping = {'hist_init': 'initial', 'hist_withdrawn': 'withdrawn', 'hist_restored': 'restored',
               'evt_no_commit': 'withdrawn', 'fresh_withdrawn': 'withdrawn', 'fresh_restored': 'restored'}
    gold = {}
    for name, state in states.items():
        answers = [truth(graph, set(state['revoked_passages'])) for graph in graphs]
        gold[name] = {'decision_consensus': {did: 'supported' if all(answer[did] for answer in answers) else 'unsupported' if not any(answer[did] for answer in answers) else 'disputed' for did in answers[0]}}
    case = {'id': 'toy-case', 'family': 'toy-family', 'public': {'source_documents': documents,
            'registry': {category: [node['id'] for node in graphs[0][category]] for category in graphs[0]}},
            'events': {'states': states}, 'phases': {phase: {'state_name': name, 'state': states[name]} for phase, name in mapping.items()},
            'authored_seed_pool': {'candidates': seed},
            'evaluation': {'source_family': family, 'state_gold': gold, 'seed_kind': 'faithful_complete' if faithful else 'deficient'}}
    ir = ir_for(graphs[0], documents)
    if many:
        sid = source_segments(documents)[0]['span_id']
        ir['combination']['citations'] = [sid]
        for i in range(5):
            axis = f'u{i}'
            ir['choices'].append({'id': axis, 'options': ['original', 'copy'], 'citations': [sid]})
            original = next(p for p in ir['propositions'] if p['kind'] == 'origin' and p['target'] == f'E{i}')
            original['when'] = {axis: 'original'}
            copied = deepcopy(original)
            copied.update(id='copied_' + str(i), when={axis: 'copy'}, body={'kind': 'copy', 'parents': ['R']})
            ir['propositions'].append(copied)
    return case, ir


def study(case, ir, *, long=False):
    dossiers = {'cases': []}
    long_ir = None
    if long:
        docs = [{'id': 'long-source', 'text': case['public']['source_documents'][0]['text'] + ' Neutral filing notes follow.'}]
        dossiers['cases'].append({'case_id': case['id'], 'source_documents': docs})
        long_ir = ir_for(case['evaluation']['source_family'][0]['graph'], docs)
    slots, records = [], []
    for model in MODELS:
        identities = [('commitment', phase) for phase in PHASES]
        identities += [('sample_graph', f'draw_{i:02d}') for i in range(1, 11)]
        identities += [('source_ir', 'extract'), ('adversarial_refuter', 'counter_read')]
        if long:
            identities += [('long_commitment', 'fresh_withdrawn'), ('long_source_ir', 'extract')]
        for condition, phase in identities:
            slot = {'slot_id': '::'.join((model, case['id'], condition, phase)), 'case_id': case['id'], 'model': model, 'condition': condition, 'phase': phase}
            slots.append(slot)
            if condition in ('commitment', 'long_commitment'):
                value = case['evaluation']['state_gold'][case['phases'][phase]['state_name']]['decision_consensus']
            elif condition == 'sample_graph':
                value = case['evaluation']['source_family'][(int(phase[-2:]) - 1) % len(case['evaluation']['source_family'])]['graph']
            elif condition == 'adversarial_refuter' and case['evaluation']['seed_kind'] == 'faithful_complete':
                value = {'status': 'no_counter_reading'}
            else:
                value = long_ir if condition == 'long_source_ir' else ir
            records.append({**slot, 'error': None, 'http_status': 200, 'response_status': 'completed', 'output_text': json.dumps(value),
                            'usage': {'input_tokens': 7, 'output_tokens': 5, 'total_tokens': 12, 'output_tokens_details': {'reasoning_tokens': 2}},
                            'latency_ms': 100, 'reserved_credits': '0.1', 'settled_credits': '0.01'})
    return {'cases': [case]}, dossiers, slots, records


def run(args):
    return evaluate(*args, bootstrap_repeats=30)


def find(result, condition, model=MODELS[0], phase=None):
    return next(row for row in result['audits'] if row['model'] == model and row['condition'] == condition and (phase is None or row.get('phase') == phase))


class FrontierV6dScoringTests(unittest.TestCase):
    def test_perfect_full_schedule_keeps_case_not_draw_unit(self):
        args = study(*case_fixture())
        before = deepcopy(args)
        result = run(args)
        self.assertEqual(args, before)
        summary = result['summary']
        self.assertEqual(summary['status'], 'complete_records')
        self.assertEqual(summary['planned_slots'], 90)
        self.assertEqual(summary['holm_family_size'], 10)
        self.assertEqual(summary['bootstrap']['n_base_cases'], 1)
        self.assertTrue(all(row['all_scheduled_counts']['n_pairs'] == 1 for row in summary['primary_comparisons']))
        self.assertEqual(find(result, 'k10_union')['duplicate_valid_draws'], 9)
        self.assertTrue(find(result, 'adversarial_refuter')['recovery']['source_aligned_consequential_addition'])
        self.assertEqual(summary['resources']['tokens']['output_tokens'], 450)
        self.assertEqual(summary['resources']['tokens']['reasoning_tokens'], 180)
        self.assertEqual(summary['resources']['reported_settled_credits'], '0.90')

    def test_all_unissued_remain_denominators_and_inference_unavailable(self):
        corpus, dossiers, slots, _ = study(*case_fixture())
        result = run((corpus, dossiers, slots, []))
        summary = result['summary']
        self.assertEqual(summary['status'], 'not_started')
        self.assertEqual(summary['resources']['no_record_slots'], 90)
        self.assertEqual(summary['bootstrap']['status'], 'unavailable_incomplete_dispatch')
        self.assertTrue(all(row['p_two_sided_exact'] is None and row['holm_input_p'] == 1 for row in summary['primary_comparisons']))
        self.assertEqual(summary['models'][MODELS[0]]['conditions']['commitment/hist_init']['decision_accuracy']['denominator'], 1)
        self.assertFalse(find(result, 'adversarial_refuter')['abstained'])

    def test_missing_one_slot_withholds_primary_inference_for_entire_study(self):
        corpus, dossiers, slots, records = study(*case_fixture())
        result = run((corpus, dossiers, slots, records[:-1]))
        self.assertTrue(all(row['p_two_sided_exact'] is None for row in result['summary']['primary_comparisons']))
        self.assertEqual(result['summary']['primary_comparisons'][0]['available_record_sensitivity']['n_pairs'], 1)

    def test_provider_error_is_not_scored_even_with_correct_text(self):
        args = study(*case_fixture())
        record = next(r for r in args[3] if r['condition'] == 'source_ir')
        record.update(error='response_not_completed', response_status='incomplete', settled_credits=None)
        result = run(args)
        self.assertFalse(find(result, 'source_ir')['correct'])
        self.assertEqual(find(result, 'source_ir')['status'], 'provider_or_accounting_failure')
        self.assertEqual(result['summary']['resources']['reported_unsettled_reserved_credits'], '0.1')

    def test_v6e_truncation_and_uncharged_dependency_are_scheduled_failures(self):
        args = study(*case_fixture())
        initial = next(r for r in args[3] if r['model'] == MODELS[0] and r['condition'] == 'commitment' and r['phase'] == 'hist_init')
        initial.update(response_status='incomplete', model_outcome='truncated_max_output_tokens', issued=True,
                       terminal_valid=True, partial_output_text=initial['output_text'], output_text='')
        dependency = next(r for r in args[3] if r['model'] == MODELS[0] and r['condition'] == 'commitment' and r['phase'] == 'hist_withdrawn')
        dependency.update(response_status=None, http_status=None, model_outcome='not_issued_dependency_truncated',
                          issued=False, error='history_dependency_truncated', output_text='', usage=None,
                          reserved_credits=None, settled_credits=None)
        result = run(args)
        self.assertFalse(find(result, 'commitment', phase='hist_init')['correct'])
        self.assertFalse(find(result, 'commitment', phase='hist_withdrawn')['correct'])
        self.assertEqual(result['summary']['resources']['issued_records_observed'], 89)
        self.assertEqual(result['summary']['resources']['not_issued_dependency_outcomes'], 1)
        self.assertEqual(result['summary']['resources']['terminal_truncated_outcomes'], 1)
        self.assertEqual(result['summary']['resources']['reported_settled_credits'], '0.89')
        self.assertTrue(result['summary']['all_planned_terminal_records'])
        self.assertIsNone(result['summary']['primary_comparisons'][1]['provider_completed_sensitivity'])

    def test_truncated_valid_partial_json_is_never_repaired_into_success(self):
        args = study(*case_fixture())
        record = next(r for r in args[3] if r['condition'] == 'source_ir')
        record.update(response_status='incomplete', model_outcome='truncated_max_output_tokens', terminal_valid=True, issued=True)
        row = find(run(args), 'source_ir')
        self.assertFalse(row['schema_valid'])
        self.assertFalse(row['correct'])
        self.assertEqual(row['status'], 'truncated_max_output_tokens')

    def test_strict_json_and_semantic_admission_remain_separate(self):
        args = study(*case_fixture())
        record = next(r for r in args[3] if r['condition'] == 'source_ir')
        record['output_text'] = '```json\n' + record['output_text'] + '\n```'
        row = find(run(args), 'source_ir')
        self.assertTrue(row['correct'])
        self.assertFalse(row['strict_bare_json'])
        self.assertFalse(row['strict_correct'])

    def test_sampler_labels_missing_ids_and_duplicate_keys_are_rejected(self):
        args = study(*case_fixture())
        rows = [r for r in args[3] if r['model'] == MODELS[0] and r['condition'] == 'sample_graph']
        extra = json.loads(rows[0]['output_text']);extra['evidence'][0]['label'] = 'not allowed'
        rows[0]['output_text'] = json.dumps(extra)
        missing = json.loads(rows[1]['output_text']);missing['evidence'].pop();missing['claims'][0]['supports'] = [['A']]
        rows[1]['output_text'] = json.dumps(missing)
        rows[2]['output_text'] = rows[2]['output_text'].replace('"evidence":', '"evidence":[],"evidence":', 1)
        result = run(args)
        union = find(result, 'k10_union')
        self.assertEqual(union['valid_draws'], 7)
        self.assertEqual(union['duplicate_valid_draws'], 6)
        self.assertTrue(union['correct'])
        self.assertEqual(find(result, 'sample_graph', phase='draw_01')['status'], 'invalid_output')

    def test_exact_citation_does_not_credit_semantically_wrong_ir(self):
        args = study(*case_fixture())
        for row in args[3]:
            if row['condition'] in ('source_ir', 'adversarial_refuter'):
                value = json.loads(row['output_text'])
                next(p for p in value['propositions'] if p['kind'] == 'support')['body'] = {'expr': {'all': [{'ref': 'A'}, {'ref': 'B'}]}}
                row['output_text'] = json.dumps(value)
        result = run(args)
        row = find(result, 'source_ir')
        self.assertTrue(row['schema_valid'])
        self.assertFalse(row['correct'])
        self.assertFalse(find(result, 'adversarial_refuter')['recovery']['structural_recovery'])

    def test_one_gold_graph_plus_spurious_world_is_not_clean_recovery(self):
        case, ir = case_fixture()
        sid = ir['entities'][0]['citations'][0]
        ir['choices'] = [{'id': 'u', 'options': ['or', 'and'], 'citations': [sid]}]
        support = next(p for p in ir['propositions'] if p['kind'] == 'support')
        support['when'] = {'u': 'or'}
        other = deepcopy(support);other.update(id='spurious', when={'u': 'and'}, body={'expr': {'all': [{'ref': 'A'}, {'ref': 'B'}]}})
        ir['propositions'].append(other)
        result = run(study(case, ir))
        row = find(result, 'adversarial_refuter')
        self.assertTrue(row['recovery']['source_aligned_consequential_addition'])
        self.assertFalse(row['clean_full_family_recovery'])
        self.assertEqual(row['family']['spurious_graphs'], 1)
        self.assertFalse(find(result, 'source_ir')['correct'])

    def test_redundant_structural_omission_has_no_consequential_opportunity(self):
        result = run(study(*case_fixture(redundant=True)))
        row = find(result, 'adversarial_refuter')
        self.assertTrue(row['recovery']['structural_recovery'])
        self.assertFalse(row['recovery']['source_aligned_consequential_addition'])
        self.assertFalse(row['authored_consequential_opportunity'])
        self.assertIsNone(row['recovery']['pairwise_distinguishing_witness'])
        self.assertTrue(row['clean_full_family_recovery'])

    def test_faithful_control_invalid_is_not_successful_abstention(self):
        args = study(*case_fixture(faithful=True))
        next(r for r in args[3] if r['condition'] == 'adversarial_refuter')['output_text'] = '{'
        result = run(args)
        control = result['summary']['models'][MODELS[0]]['refuter']['faithful_complete']
        self.assertEqual(control['valid_abstention']['numerator'], 0)
        self.assertEqual(control['operational_or_schema_failure']['numerator'], 1)

    def test_high_multiplicity_baseline_ceiling_and_sampling_duplicates(self):
        result = run(study(*case_fixture(many=True, faithful=True)))
        union = find(result, 'k10_union')
        self.assertEqual(union['distinct_valid_graphs'], 10)
        self.assertFalse(union['correct'])
        self.assertEqual(union['family']['recall'], 10 / 32)
        self.assertTrue(find(result, 'source_ir')['correct'])
        self.assertTrue(find(result, 'sample_graph')['correct'])
        feasible = result['summary']['models'][MODELS[0]]['family_recovery']['at_most10_distinct_source_graphs']
        self.assertEqual(feasible['source_ir_exact']['denominator'], 0)

    def test_long_ir_uses_original_long_dossier_locations(self):
        case, ir = case_fixture()
        args = study(case, ir, long=True)
        next(r for r in args[3] if r['condition'] == 'long_source_ir')['output_text'] = json.dumps(ir)
        result = run(args)
        self.assertEqual(find(result, 'long_source_ir')['status'], 'invalid_output')
        self.assertTrue(find(result, 'source_ir')['correct'])
        self.assertEqual(result['summary']['long_base_cases'], 1)

    def test_hidden_metadata_never_enters_compiler_inputs(self):
        args = study(*case_fixture())
        marker = 'POISONED_EVALUATION_NOT_SOURCE'
        args[0]['cases'][0]['evaluation']['reference_ir'] = marker
        args[0]['cases'][0]['review_notes'] = marker
        calls = []
        def check(value, documents, registry):
            calls.append((deepcopy(value), deepcopy(documents), deepcopy(registry)))
            self.assertNotIn(marker, json.dumps([value, documents, registry]))
            return compile_cited_ir(value, documents, registry)
        with patch('retrace.frontier_v6d_eval.compile_cited_ir', side_effect=check):
            result = run(args)
        self.assertTrue(calls)
        self.assertTrue(find(result, 'source_ir')['correct'])

    def test_duplicates_unknown_slots_and_identity_mismatch_abort(self):
        args = study(*case_fixture())
        for mutate in (lambda rows: rows.append(deepcopy(rows[0])),
                       lambda rows: rows[0].update(slot_id='unknown'),
                       lambda rows: rows[0].update(model=MODELS[1])):
            altered = deepcopy(args)
            mutate(altered[3])
            with self.assertRaises(ValueError):
                run(altered)

    def test_schedule_cannot_silently_drop_a_model_or_draw(self):
        corpus, dossiers, slots, records = study(*case_fixture())
        with self.assertRaises(ValueError):
            run((corpus, dossiers, slots[:-1], records[:-1]))

    def test_primary_direction_exact_tail_holm_and_case_bootstrap(self):
        cases, slots, records = [], [], []
        for i in range(8):
            case, ir = case_fixture()
            case.update(id=f'case-{i}', family=f'family-{i % 2}')
            part = study(case, ir)
            cases.append(case)
            slots.extend(part[2])
            for record in part[3]:
                if record['model'] == MODELS[0] and record['condition'] == 'sample_graph':
                    record['output_text'] = 'not JSON'
                records.append(record)
        result = run(({'cases': cases}, {'cases': []}, slots, records))
        contrast = result['summary']['primary_comparisons'][0]
        self.assertEqual(contrast['all_scheduled_counts']['b_only'], 8)
        self.assertEqual(contrast['difference_b_minus_a'], 1)
        self.assertEqual(contrast['p_two_sided_exact'], 1 / 128)
        self.assertEqual(contrast['holm_adjusted_p'], 10 / 128)
        boot = result['summary']['bootstrap']
        self.assertEqual(boot['family_counts'], {'family-0': 4, 'family-1': 4})
        self.assertEqual(boot['metrics'][MODELS[0] + ':source_ir_minus_k10']['percentile_95_interval'], [1, 1])

    def test_actual_events_detect_wrong_local_flag_hidden_by_eligibility_truth_table(self):
        args = study(*case_fixture())
        for row in args[3]:
            if row['model'] != MODELS[0]:
                continue
            if row['condition'] == 'source_ir':
                value = json.loads(row['output_text'])
                next(p for p in value['propositions'] if p['kind'] == 'eligibility' and p['target'] == 'B')['body']['active'] = False
                row['output_text'] = json.dumps(value)
            elif row['condition'] == 'sample_graph':
                value = json.loads(row['output_text'])
                next(n for n in value['evidence'] if n['id'] == 'B')['active'] = False
                row['output_text'] = json.dumps(value)
        result = run(args)
        for arm in ('source_ir', 'k10_union'):
            row = find(result, arm)
            self.assertTrue(row['semantic']['exact'])
            self.assertFalse(row['actual_events']['states']['withdrawn']['exact_vector'])
            self.assertTrue(row['actual_events']['states']['initial']['exact_vector'])
            self.assertTrue(row['actual_events']['states']['restored']['exact_vector'])
        model = result['summary']['models'][MODELS[0]]
        self.assertEqual(model['actual_event_fidelity']['source_ir']['all_three_vectors_correct']['numerator'], 0)
        contrast = model['compiled_ir_vs_direct_withdrawn']
        self.assertEqual(contrast['difference_b_minus_a'], -1)
        self.assertEqual(contrast['resampling_interval'], [-1, -1])
        self.assertIsNone(contrast['p_two_sided_exact'])
        self.assertEqual(result['summary']['holm_family_size'], 10)

    def test_actual_document_restore_preserves_passage_veto_and_original_ineligibility(self):
        case, _ = case_fixture()
        graph = case['evaluation']['source_family'][0]['graph']
        graph['evidence'][0]['active'] = False
        case['events']['document_groups'] = [{'id': 'sheet', 'evidence_ids': ['A', 'B']}]
        case['events']['states']['withdrawn'] = {'revoked_documents': ['sheet'], 'revoked_passages': ['B']}
        case['events']['states']['restored'] = {'revoked_documents': [], 'revoked_passages': ['B']}
        for name in ('withdrawn', 'restored'):
            case['evaluation']['state_gold'][name]['decision_consensus'] = {'D': 'unsupported'}
        result = actual_event_fidelity([{'id': 'predicted', 'graph': graph}], case)
        self.assertTrue(result['all_three_vectors_correct'])
        self.assertEqual(result['states']['withdrawn']['excluded_evidence_ids'], ['A', 'B'])
        self.assertEqual(result['states']['restored']['excluded_evidence_ids'], ['B'])
        self.assertEqual(result['states']['restored']['predicted_consensus'], {'D': 'unsupported'})

    def test_actual_state_missing_family_or_requested_decision_never_matches_by_default(self):
        case, _ = case_fixture()
        missing = deepcopy(case['evaluation']['source_family'][0]['graph'])
        missing['decisions'] = []
        for candidates, expected in [([], 'no_prediction'), ([{'id': 'missing', 'graph': missing}], 'missing_requested_decisions'),
                                     (case['evaluation']['source_family'] + [{'id': 'missing', 'graph': missing}], 'missing_requested_decisions')]:
            result = actual_event_fidelity(candidates, case)
            self.assertEqual(result['status'], expected)
            self.assertFalse(result['all_three_vectors_correct'])
            self.assertEqual(result['correct_decision_states'], 0)
            self.assertTrue(all(state['predicted_consensus'] is None for state in result['states'].values()))


if __name__ == '__main__':
    unittest.main()
