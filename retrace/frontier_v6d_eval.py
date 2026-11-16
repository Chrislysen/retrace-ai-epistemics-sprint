"""Prospective, offline scoring for the fixed v6d frontier study.

Missing requests and invalid outputs remain in scheduled denominators. Source
interpretation is never certified by location matching or compiler admission.
No file access, network access, model calls, or mutation of inputs occurs here.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math

from .compact_graph import validate_explicit_graph
from .frontier_v6c_io import parse_object, verdict, graph_signature, family_score, counterfactual_consensus_score
from .frontier_v6c_stats import exact_mcnemar, holm_adjust, case_cluster_bootstrap
from .source_ir_v6d import compile_cited_ir, audit_cited_ir, expand_ir
from .stress_v6c import _basis, _table

MODELS = ('deepseek-v4-flash', 'gemma-4-31b-it', 'glm-5.3-flash', 'qwen3.8-27b', 'glm-5.2')
PHASES = ('hist_init', 'hist_withdrawn', 'hist_restored', 'evt_no_commit', 'fresh_withdrawn', 'fresh_restored')
BOOTSTRAP_SEED = 2026111409


def _require(value, message):
    if not value:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _rate(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None}


def _quantile(values, probability):
    if not values:
        return None
    values = sorted(values)
    position = probability * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (position - lower) * (values[upper] - values[lower])


def _usage(record):
    usage = record.get('usage')
    if not isinstance(usage, dict):
        return None
    counts = [usage.get('input_tokens'), usage.get('output_tokens')]
    if any(type(value) is not int or value < 0 for value in counts):
        return None
    if 'total_tokens' in usage and (type(usage['total_tokens']) is not int or usage['total_tokens'] != sum(counts)):
        return None
    result = {'input_tokens': counts[0], 'output_tokens': counts[1], 'reasoning_tokens': 0, 'cached_input_tokens': 0}
    for detail, field, label, maximum in [('input_tokens_details', 'cached_tokens', 'cached_input_tokens', counts[0]),
                                           ('output_tokens_details', 'reasoning_tokens', 'reasoning_tokens', counts[1])]:
        if usage.get(detail) is not None:
            if not isinstance(usage[detail], dict):
                return None
            value = usage[detail].get(field, 0)
            if type(value) is not int or not 0 <= value <= maximum:
                return None
            result[label] = value
    return result


def _money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _resources(slots, records_by_id):
    outcomes = [records_by_id[s['slot_id']] for s in slots if s['slot_id'] in records_by_id]
    records = [record for record in outcomes if record.get('issued', True)]
    usage_rows = [_usage(record) for record in records]
    latencies = [record['latency_ms'] for record in records if type(record.get('latency_ms')) in (int, float)
                 and math.isfinite(record['latency_ms']) and record['latency_ms'] >= 0]
    settled = [_money(record.get('settled_credits')) for record in records]
    reserved = [_money(record.get('reserved_credits')) for record in records]
    settled_total = sum((value for value in settled if value is not None), Decimal(0))
    retained = sum((bound for bound, actual in zip(reserved, settled) if bound is not None and actual is None), Decimal(0))
    complete = sum(_completed(record) for record in records)
    truncated = sum(record.get('response_status') == 'incomplete' and record.get('model_outcome') == 'truncated_max_output_tokens' for record in records)
    return {'planned_slots': len(slots), 'scheduled_outcome_records_observed': len(outcomes),
            'issued_records_observed': len(records), 'not_issued_dependency_outcomes': len(outcomes) - len(records),
            'no_record_slots': len(slots) - len(outcomes), 'provider_completed': complete,
            'terminal_truncated_outcomes': truncated, 'noncompleted_issued_outcomes': len(records) - complete,
            'provider_or_accounting_failures': sum(record.get('error') is not None or record.get('http_status') != 200 or _usage(record) is None for record in records),
            'issued_without_response_records': sum(record.get('error') == 'issued_response_missing' for record in records),
            'valid_usage_records': sum(usage is not None for usage in usage_rows),
            'tokens': {key: sum(usage[key] for usage in usage_rows if usage is not None)
                       for key in ('input_tokens', 'output_tokens', 'reasoning_tokens', 'cached_input_tokens')},
            'reported_settled_credits': str(settled_total), 'reported_unsettled_reserved_credits': str(retained),
            'reported_accounted_new_credits': str(settled_total + retained),
            'cost_record_count': sum(value is not None for value in settled),
            'latency_ms': {'observed': len(latencies), 'sum': sum(latencies),
                           'mean': sum(latencies) / len(latencies) if latencies else None,
                           'median': _quantile(latencies, .5), 'p95': _quantile(latencies, .95)},
            'scope': 'Resource totals describe supplied issued records only; the durable ledger, orphan requests, historical carry and cumulative cap require separate reconciliation. Output tokens already include reasoning tokens; no double charge is added.'}


def _completed(record):
    return (record.get('issued', True) is True and record.get('error') is None and record.get('http_status') == 200
            and record.get('response_status') == 'completed' and isinstance(record.get('output_text'), str)
            and _usage(record) is not None)


def _grid(corpus, dossiers, slots, records):
    _require(isinstance(corpus, dict) and isinstance(corpus.get('cases'), list) and corpus['cases'], 'Nonempty corpus required')
    cases = {case['id']: case for case in corpus['cases']}
    _require(len(cases) == len(corpus['cases']), 'Duplicate case IDs')
    long_cases = {case['case_id']: case for case in dossiers.get('cases', [])}
    _require(len(long_cases) == len(dossiers.get('cases', [])) and set(long_cases) <= set(cases), 'Invalid dossier IDs')
    slot_index, identities = {}, {}
    for slot in slots:
        _require(isinstance(slot, dict) and {'slot_id', 'case_id', 'model', 'condition', 'phase'} <= set(slot), 'Incomplete slot identity')
        sid = slot['slot_id']
        _require(isinstance(sid, str) and sid not in slot_index and slot['case_id'] in cases and slot['model'] in MODELS, 'Unknown or duplicate slot')
        identity = (slot['model'], slot['case_id'], slot['condition'], slot['phase'])
        _require(identity not in identities, 'Duplicate scheduled semantic identity')
        slot_index[sid], identities[identity] = slot, slot
    expected = set()
    for model in MODELS:
        for cid in cases:
            expected.update((model, cid, 'commitment', phase) for phase in PHASES)
            expected.update((model, cid, 'sample_graph', f'draw_{draw:02d}') for draw in range(1, 11))
            expected.update([(model, cid, 'source_ir', 'extract'), (model, cid, 'adversarial_refuter', 'counter_read')])
            if cid in long_cases:
                expected.update([(model, cid, 'long_commitment', 'fresh_withdrawn'), (model, cid, 'long_source_ir', 'extract')])
    _require(set(identities) == expected, 'Schedule must include every declared model/case/phase/draw exactly once')
    index = {}
    for record in records:
        _require(isinstance(record, dict) and record.get('slot_id') in slot_index, 'Unknown response slot')
        sid = record['slot_id']
        _require(sid not in index, 'Duplicate response slot; retries cannot be silently selected')
        slot = slot_index[sid]
        _require(all(record.get(key) == slot[key] for key in ('case_id', 'model', 'condition', 'phase')), 'Response identity differs from schedule')
        _require('issued' not in record or type(record['issued']) is bool, 'Issued flag must be Boolean')
        if record.get('issued') is False:
            _require(record.get('model_outcome') == 'not_issued_dependency_truncated'
                     and record.get('error') == 'history_dependency_truncated'
                     and record.get('usage') is None and record.get('reserved_credits') is None
                     and record.get('settled_credits') is None and not record.get('attempt_id'),
                     'Not-issued row must be an explicit uncharged truncated-history dependency outcome')
        index[sid] = record
    return cases, long_cases, slot_index, identities, index


def _truth_masks(graph, variables, available, universe):
    amended = deepcopy(graph)
    for node in amended['evidence']:
        node['active'] = True
    return _table(amended, available, universe)


def actual_event_fidelity(predicted, case):
    """Evaluate original flags under the three actual, separately scoped veto sets.

    No local flag is activated here. Source-family annotations are used only to
    score predicted decision vectors after the declared graphs are evaluated.
    """
    requested = sorted(case['public']['registry']['decisions'])
    _require(bool(requested), 'Actual event fidelity requires requested decisions')
    if not predicted:
        status = 'no_prediction'
    elif any(not set(requested) <= {node['id'] for node in candidate['graph']['decisions']} for candidate in predicted):
        status = 'missing_requested_decisions'
    else:
        status = 'evaluated'
    groups = {group['id']: set(group['evidence_ids']) for group in case['events'].get('document_groups', [])}
    states = {}
    for name in ('initial', 'withdrawn', 'restored'):
        state = case['events']['states'][name]
        excluded = set(state['revoked_passages'])
        for document_id in state['revoked_documents']:
            _require(document_id in groups, 'Event references an unknown document group')
            excluded |= groups[document_id]
        expected = case['evaluation']['state_gold'][name]['decision_consensus']
        _require(set(expected) == set(requested), 'Authored event vector differs from requested decisions')
        consensus = None
        if status == 'evaluated':
            tables = []
            for candidate in predicted:
                graph = candidate['graph']
                # universe=1 is one actual snapshot, not an all-enable basis.
                # _table independently retains each node's original active flag.
                available = {node['id']: 0 if node['id'] in excluded else 1 for node in graph['evidence']}
                tables.append(_table(graph, available, 1))
            consensus = {did: 'supported' if all(table[did] for table in tables)
                         else 'unsupported' if not any(table[did] for table in tables)
                         else 'disputed' for did in requested}
        correct = sum(consensus[did] == expected[did] for did in requested) if consensus is not None else 0
        states[name] = {'excluded_evidence_ids': sorted(excluded), 'predicted_consensus': consensus,
                        'correct_decisions': correct, 'planned_decisions': len(requested),
                        'decision_accuracy': correct / len(requested),
                        'exact_vector': consensus is not None and correct == len(requested)}
    total_correct = sum(state['correct_decisions'] for state in states.values())
    return {'status': status, 'requested_decision_ids': requested, 'states': states,
            'all_three_vectors_correct': all(state['exact_vector'] for state in states.values()),
            'correct_decision_states': total_correct, 'planned_decision_states': 3 * len(requested),
            'decision_state_accuracy': total_correct / (3 * len(requested)),
            'scope': 'Original local flags plus the actual document and passage vetoes. Restoration clears only the listed vetoes; no originally inactive record is enabled. Missing families or any missing requested decision fail the complete-vector evaluation.'}


def _event_aggregate(rows):
    result = {'scheduled_cases': len(rows), 'status_counts': dict(Counter(row['status'] for row in rows)),
              'all_three_vectors_correct': _rate(sum(row['all_three_vectors_correct'] for row in rows), len(rows)),
              'decision_state_accuracy': _rate(sum(row['correct_decision_states'] for row in rows),
                                               sum(row['planned_decision_states'] for row in rows)), 'states': {}}
    for name in ('initial', 'withdrawn', 'restored'):
        result['states'][name] = {
            'exact_vector': _rate(sum(row['states'][name]['exact_vector'] for row in rows), len(rows)),
            'decision_accuracy': _rate(sum(row['states'][name]['correct_decisions'] for row in rows),
                                       sum(row['states'][name]['planned_decisions'] for row in rows))}
    return result


def _counterexample(seed, new_graph, baseline, cache):
    """Finite consequential addition and weaker pairwise distinction witnesses."""
    evidence = sorted(node['id'] for node in baseline['evidence'])
    _require(len(evidence) <= 12, 'Counterexample eligibility basis exceeds12')
    registry = {category: {node['id'] for node in baseline[category]} for category in baseline}
    graphs = [candidate['graph'] for candidate in seed] + [new_graph]
    if any({node['id'] for node in graph[category]} != registry[category] for graph in graphs for category in registry):
        return {'status': 'registry_mismatch', 'consequential': None, 'pairwise': None}
    basis_key = tuple(evidence)
    if basis_key not in cache:
        cache[basis_key] = _basis(evidence)[:3]
    states, universe, available = cache[basis_key]

    def table(graph):
        key = (basis_key, graph_signature(graph))
        if key not in cache:
            cache[key] = _truth_masks(graph, evidence, available, universe)
        return cache[key]

    seed_tables, added = [table(candidate['graph']) for candidate in seed], table(new_graph)
    original = {node['id']: node['active'] for node in baseline['evidence']}
    source_inactive = {ident for ident, active in original.items() if not active}

    def witness(mask, did):
        if not mask:
            return None
        choices = []
        while mask:
            bit = mask & -mask
            assignment = bit.bit_length() - 1
            inactive = {ident for position, ident in enumerate(evidence) if assignment >> position & 1}
            enable, withdraw = sorted(source_inactive - inactive), sorted(inactive - source_inactive)
            choices.append((len(enable) + len(withdraw), len(enable), enable, withdraw, assignment))
            mask ^= bit
        _, _, enable, withdraw, assignment = min(choices)
        outcomes = {candidate['id']: bool(values[did] >> assignment & 1) for candidate, values in zip(seed, seed_tables)}
        values = list(outcomes.values())
        before = 'supported' if all(values) else 'unsupported' if not any(values) else 'disputed'
        value = bool(added[did] >> assignment & 1)
        after_values = values + [value]
        return {'decision_id': did, 'enable': enable, 'withdraw': withdraw,
                'changed_local_flags': len(enable) + len(withdraw),
                'final_ineligible_ids': [ident for position, ident in enumerate(evidence) if assignment >> position & 1],
                'seed_outcomes': outcomes, 'added_graph_outcome': value, 'seed_consensus': before,
                'augmented_consensus': 'supported' if all(after_values) else 'unsupported' if not any(after_values) else 'disputed',
                'hypothetical': True,
                'scope': 'Hypothetical final local eligibility, including possible activation of originally inactive records. No real veto is cleared and no source truth or repaired consensus is asserted.'}
    consequential, pairwise = [], []
    for did in sorted(added):
        every, any_support, differing = universe, 0, 0
        for values in seed_tables:
            every &= values[did]
            any_support |= values[did]
            differing |= values[did] ^ added[did]
        changed = (added[did] & (universe ^ any_support)) | ((universe ^ added[did]) & every)
        if changed:
            consequential.append(witness(changed, did))
        if differing:
            pairwise.append(witness(differing, did))
    key = lambda row: (row['changed_local_flags'], len(row['enable']), row['enable'], row['withdraw'], row['decision_id'])
    return {'status': 'exhaustive', 'states_checked': states,
            'consequential': min(consequential, key=key) if consequential else None,
            'pairwise': min(pairwise, key=key) if pairwise else None}


def _recovery(predicted, expected, seed, cache):
    wanted = {graph_signature(candidate['graph']) for candidate in expected}
    existing = {graph_signature(candidate['graph']) for candidate in seed}
    novel, consequential, pairwise = [], [], []
    seen = set()
    for candidate in predicted:
        signature = graph_signature(candidate['graph'])
        if signature not in wanted or signature in existing or signature in seen:
            continue
        seen.add(signature)
        novel.append(candidate['id'])
        check = _counterexample(seed, candidate['graph'], expected[0]['graph'], cache)
        if check['consequential']:
            consequential.append({'candidate_id': candidate['id'], **check['consequential']})
        if check['pairwise']:
            pairwise.append({'candidate_id': candidate['id'], **check['pairwise']})
    key = lambda row: (row['changed_local_flags'], len(row['enable']), row['candidate_id'], row['decision_id'])
    return {'novel_source_aligned_candidate_ids': novel, 'structural_recovery': bool(novel),
            'source_aligned_consequential_addition': bool(consequential),
            'consequential_witness': min(consequential, key=key) if consequential else None,
            'pairwise_distinguishing_witness': min(pairwise, key=key) if pairwise else None,
            'scope': 'Authored source-family membership is used only for evaluation. A novel correct graph causing disagreement is a grounded review trigger, not automatic correction of the supplied seed family.'}


def _slot_result(slot, record, case, documents):
    result = {key: slot[key] for key in ('slot_id', 'case_id', 'model', 'condition', 'phase')}
    result.update(record_observed=record is not None, provider_completed=False, json_parse_valid=False,
                  strict_bare_json=False, schema_valid=False, executable=False, correct=False,
                  strict_correct=False, candidates=[], parsed=None, compilation=None, abstained=False,
                  reference_transport_valid=False)
    if record is None:
        result.update(status='no_response_record', error='unissued_or_missing_response_record')
        return result
    result['record_sha256'] = _digest(record)
    result.update(http_status=record.get('http_status'), response_status=record.get('response_status'),
                  reported_error=record.get('error'), issued=record.get('issued', True), model_outcome=record.get('model_outcome'))
    output = record.get('output_text')
    if isinstance(output, str):
        result['output_text_sha256'] = hashlib.sha256(output.encode()).hexdigest()
    if not _completed(record):
        status = ('not_issued_dependency_truncated' if record.get('issued') is False else
                  'truncated_max_output_tokens' if record.get('response_status') == 'incomplete' and record.get('model_outcome') == 'truncated_max_output_tokens'
                  else 'provider_or_accounting_failure')
        result.update(status=status, error=record.get('error') or 'incomplete_or_invalid_usage')
        return result
    result['provider_completed'] = True
    try:
        parsed, strict = parse_object(output)
        result.update(parsed=parsed, json_parse_valid=True, strict_bare_json=strict)
        condition = slot['condition']
        if condition in ('commitment', 'long_commitment'):
            value, _ = verdict(output, case['public']['registry']['decisions'])
            state_name = case['phases'][slot['phase']]['state_name']
            expected = case['evaluation']['state_gold'][state_name]['decision_consensus']
            correct_decisions = sum(value[did] == expected[did] for did in expected)
            result.update(schema_valid=True, executable=True, status='valid_verdict', prediction=value,
                          correct=correct_decisions == len(expected), correct_decisions=correct_decisions,
                          planned_decisions=len(expected), decision_matches={did: value[did] == expected[did] for did in expected})
        elif condition == 'sample_graph':
            # Do not use graph_value here: its authored-comparison helper strips
            # labels, but model-output labels and omitted registry IDs are invalid.
            graph = validate_explicit_graph(parsed, case['public']['registry'])
            result.update(schema_valid=True, executable=True, status='valid_graph', candidates=[{'id': slot['phase'], 'graph': graph}])
        elif condition == 'adversarial_refuter' and parsed == {'status': 'no_counter_reading'}:
            result.update(schema_valid=True, status='valid_abstention', abstained=True,
                          correct=case['evaluation']['seed_kind'] == 'faithful_complete')
        else:
            expand_ir(parsed, documents)
            result['reference_transport_valid'] = True
            compiled = compile_cited_ir(parsed, documents, case['public']['registry'])
            result.update(schema_valid=True, compilation=compiled, candidates=compiled['candidates'],
                          executable=compiled['status'] == 'compiled', status=compiled['status'])
        if result['candidates']:
            scored = family_score(result['candidates'], case['evaluation']['source_family'])
            result.update(family=scored, correct=scored['precision'] == 1.0 if condition == 'sample_graph' else scored['exact_family'])
        result['strict_correct'] = result['correct'] and strict
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        result.update(status='invalid_output', error_type=type(exc).__name__, error=str(exc)[:1500], candidates=[], correct=False, strict_correct=False)
    return result


def _aggregate(rows):
    n = len(rows)
    result = {'scheduled': n, 'status_counts': dict(Counter(row['status'] for row in rows)),
              'observed': sum(row['record_observed'] for row in rows),
              'provider_completed': sum(row['provider_completed'] for row in rows),
              'json_parse_valid': _rate(sum(row['json_parse_valid'] for row in rows), n),
              'strict_bare_json': _rate(sum(row['strict_bare_json'] for row in rows), n),
              'schema_valid': _rate(sum(row['schema_valid'] for row in rows), n),
              'all_supplied_span_references_resolve': _rate(sum(row['reference_transport_valid'] for row in rows), n),
              'executable': _rate(sum(row['executable'] for row in rows), n),
              'correct': _rate(sum(row['correct'] for row in rows), n),
              'strict_correct': _rate(sum(row['strict_correct'] for row in rows), n)}
    if any('decision_denominator' in row for row in rows):
        result['decision_accuracy'] = _rate(sum(row.get('correct_decisions', 0) for row in rows), sum(row['decision_denominator'] for row in rows))
    return result


def _paired(a, b, complete, *, names):
    n = len(a)
    descriptive = exact_mcnemar([row['correct'] for row in a], [row['correct'] for row in b])
    difference = sum(right['correct'] - left['correct'] for left, right in zip(a, b)) / n
    subset = [(left, right) for left, right in zip(a, b) if left['required_records_observed'] and right['required_records_observed']]
    sensitivity = None
    if subset:
        sensitivity = exact_mcnemar([left['correct'] for left, _ in subset], [right['correct'] for _, right in subset])
        sensitivity.pop('p_two_sided_exact')
        sensitivity['difference_b_minus_a'] = sum(right['correct'] - left['correct'] for left, right in subset) / len(subset)
        sensitivity['scope'] = 'Descriptive available-record pairs only; completion selection can bias this subset. No inferential p value is assigned.'
    completed_subset = [(left, right) for left, right in zip(a, b) if left['required_provider_completed'] and right['required_provider_completed']]
    completed_sensitivity = None
    if completed_subset:
        completed_sensitivity = exact_mcnemar([left['correct'] for left, _ in completed_subset], [right['correct'] for _, right in completed_subset])
        completed_sensitivity.pop('p_two_sided_exact')
        completed_sensitivity['difference_b_minus_a'] = sum(right['correct'] - left['correct'] for left, right in completed_subset) / len(completed_subset)
        completed_sensitivity['scope'] = 'Provider-completed pairs only, including schema-invalid completed text as unsuccessful. Selection can bias this descriptive subset; it has no primary p value.'
    p_value = descriptive.pop('p_two_sided_exact')
    return {'a': names[0], 'b': names[1], 'status': 'evaluated_all_scheduled' if complete else 'unavailable_incomplete_dispatch',
            'all_scheduled_counts': descriptive, 'difference_b_minus_a': difference,
            'p_two_sided_exact': p_value if complete else None, 'holm_input_p': p_value if complete else 1.0,
            'available_record_sensitivity': sensitivity,
            'provider_completed_sensitivity': completed_sensitivity,
            'scope': 'Missing/invalid outcomes remain unsuccessful in scheduled descriptive counts. Paired inference requires every primary scheduled slot to have a final outcome record; explicit unissued truncated-history dependencies count as unsuccessful final outcomes, not completed requests.'}


def evaluate(corpus, dossiers, slots, records, bootstrap_repeats=10000):
    """Return {summary, audits}, without writes or network activity."""
    _require(type(bootstrap_repeats) is int and bootstrap_repeats >= 1, 'Positive bootstrap replicate count required')
    cases, long_cases, slot_index, identities, record_index = _grid(corpus, dossiers, slots, records)
    cache, opportunities = {}, {}
    for cid, case in cases.items():
        opportunities[cid] = _recovery(case['evaluation']['source_family'], case['evaluation']['source_family'], case['authored_seed_pool']['candidates'], cache)
    results, audits = {}, []
    for slot in slots:
        case = cases[slot['case_id']]
        documents = long_cases[case['id']]['source_documents'] if slot['condition'].startswith('long_') else case['public']['source_documents']
        result = _slot_result(slot, record_index.get(slot['slot_id']), case, documents)
        result['required_records_observed'] = result['record_observed'] and record_index[slot['slot_id']].get('error') != 'issued_response_missing'
        result['required_provider_completed'] = result['provider_completed']
        if slot['condition'] in ('commitment', 'long_commitment'):
            result['decision_denominator'] = len(case['public']['registry']['decisions'])
        results[(slot['model'], case['id'], slot['condition'], slot['phase'])] = result
        audits.append(result)
    unions, model_summaries, pairs, bootstrap_rows = {}, {}, [], []
    terminal_complete = len(record_index) == len(slots) and all(record.get('error') != 'issued_response_missing' for record in records)
    for model in MODELS:
        for cid, case in cases.items():
            draws = [results[(model, cid, 'sample_graph', f'draw_{draw:02d}')] for draw in range(1, 11)]
            candidates = [candidate for draw in draws for candidate in draw['candidates']]
            scored = family_score(candidates, case['evaluation']['source_family'])
            strict_candidates = [candidate for draw in draws if draw['strict_bare_json'] for candidate in draw['candidates']]
            union = {'schema': 'retrace.frontier-v6d-k10-union.v1', 'case_id': cid, 'model': model,
                     'condition': 'k10_union', 'scheduled_draws': 10, 'observed_draws': sum(draw['record_observed'] for draw in draws),
                     'valid_draws': sum(draw['schema_valid'] for draw in draws), 'distinct_valid_graphs': scored['predicted_distinct_graphs'],
                     'duplicate_valid_draws': len(candidates) - scored['predicted_distinct_graphs'], 'family': scored,
                     'correct': scored['exact_family'], 'strict_correct': family_score(strict_candidates, case['evaluation']['source_family'])['exact_family'],
                     'required_records_observed': all(draw['required_records_observed'] for draw in draws),
                     'required_provider_completed': all(draw['provider_completed'] for draw in draws),
                     'actual_events': actual_event_fidelity(candidates, case),
                     'semantic': counterfactual_consensus_score(candidates, case['evaluation']['source_family'])}
            unions[(model, cid)] = union
            audits.append(union)
            for condition in ('source_ir', 'long_source_ir', 'adversarial_refuter'):
                if condition == 'long_source_ir' and cid not in long_cases:
                    continue
                phase = 'counter_read' if condition == 'adversarial_refuter' else 'extract'
                row = results[(model, cid, condition, phase)]
                row['family'] = family_score(row['candidates'], case['evaluation']['source_family'])
                row['actual_events'] = actual_event_fidelity(row['candidates'], case)
                row['semantic'] = counterfactual_consensus_score(row['candidates'], case['evaluation']['source_family'])
                if condition == 'adversarial_refuter':
                    seed = case['authored_seed_pool']['candidates']
                    row['seed_kind_evaluation_only'] = case['evaluation']['seed_kind']
                    row['recovery'] = _recovery(row['candidates'], case['evaluation']['source_family'], seed, cache)
                    row['clean_full_family_recovery'] = row['executable'] and row['family']['exact_family']
                    row['emitted_counter_reading'] = row['provider_completed'] and row['json_parse_valid'] and not row['abstained']
                    row['authored_consequential_opportunity'] = opportunities[cid]['source_aligned_consequential_addition']
                    # For controls, exact abstention is the only clean success.
                    row['correct'] = row['abstained'] if case['evaluation']['seed_kind'] == 'faithful_complete' else row['recovery']['source_aligned_consequential_addition']
                    row['strict_correct'] = row['correct'] and row['strict_bare_json']
                    comparison = seed
                else:
                    comparison = candidates
                if row['compilation'] is not None and comparison:
                    docs = long_cases[cid]['source_documents'] if condition == 'long_source_ir' else case['public']['source_documents']
                    row['declared_source_audit'] = audit_cited_ir(row['parsed'], docs, comparison, case['public']['registry'])
                    row['declared_source_audit_scope'] = 'Compares model-interpreted IR with supplied graph declarations. A gap or extra world is not verified textual entailment or aligned source omission.'
                else:
                    row['declared_source_audit'] = None
        short_rows = [row for row in audits if row.get('model') == model and row.get('condition') != 'k10_union']
        grouped = defaultdict(list)
        for row in short_rows:
            grouped[(row['condition'], row['phase'])].append(row)
        model_summary = {'conditions': {condition + '/' + phase: _aggregate(rows) for (condition, phase), rows in sorted(grouped.items())},
                         'resources': _resources([slot for slot in slots if slot['model'] == model], record_index)}
        case_ids = sorted(cases)
        ir_rows = [results[(model, cid, 'source_ir', 'extract')] for cid in case_ids]
        union_rows = [unions[(model, cid)] for cid in case_ids]
        history = [results[(model, cid, 'commitment', 'hist_withdrawn')] for cid in case_ids]
        fresh = [results[(model, cid, 'commitment', 'fresh_withdrawn')] for cid in case_ids]
        model_summary['actual_event_fidelity'] = {
            'source_ir': _event_aggregate([row['actual_events'] for row in ir_rows]),
            'k10_union': _event_aggregate([row['actual_events'] for row in union_rows]),
            'long_source_ir': _event_aggregate([results[(model, cid, 'long_source_ir', 'extract')]['actual_events'] for cid in sorted(long_cases)])}
        event_ir = [{**row, 'correct': row['actual_events']['states']['withdrawn']['exact_vector']} for row in ir_rows]
        secondary_pair = _paired(fresh, event_ir, False, names=('direct_fresh_withdrawn', 'compiled_source_ir_actual_withdrawn'))
        secondary_pair['status'] = 'secondary_descriptive_paired'
        secondary_pair['scope'] = 'Different input/output contracts, including final-event verdict prompting versus original-graph extraction followed by deterministic event application. Descriptive paired comparison only; no additional primary hypothesis or Holm position.'
        secondary_pair['resampling_interval'] = None
        secondary_pair['resampling_status'] = 'pending_complete_schedule' if terminal_complete else 'unavailable_incomplete_dispatch'
        model_summary['compiled_ir_vs_direct_withdrawn'] = secondary_pair
        for a, b, names in [(union_rows, ir_rows, ('k10_union', 'source_ir')),
                             (history, fresh, ('hist_withdrawn', 'fresh_withdrawn'))]:
            pairs.append({'model': model, **_paired(a, b, terminal_complete, names=names)})
        capacity = [cid for cid in case_ids if family_score([], cases[cid]['evaluation']['source_family'])['source_distinct_graphs'] <= 10]
        ceiling = [cid for cid in case_ids if cid not in capacity]
        model_summary['family_recovery'] = {}
        strata = [('all_scheduled', case_ids), ('at_most10_distinct_source_graphs', capacity), ('more_than10_baseline_ceiling', ceiling)]
        strata += [('family/' + family, [cid for cid in case_ids if cases[cid]['family'] == family]) for family in sorted({case['family'] for case in cases.values()})]
        for name, selected in strata:
            model_summary['family_recovery'][name] = {
                'case_ids': selected, 'k10_exact': _rate(sum(unions[(model, cid)]['correct'] for cid in selected), len(selected)),
                'source_ir_exact': _rate(sum(results[(model, cid, 'source_ir', 'extract')]['correct'] for cid in selected), len(selected)),
                'k10_mean_recall': sum(unions[(model, cid)]['family']['recall'] for cid in selected) / len(selected) if selected else None,
                'source_ir_mean_recall': sum(results[(model, cid, 'source_ir', 'extract')]['family']['recall'] for cid in selected) / len(selected) if selected else None,
                'k10_mean_precision': sum(unions[(model, cid)]['family']['precision'] for cid in selected) / len(selected) if selected else None,
                'source_ir_mean_precision': sum(results[(model, cid, 'source_ir', 'extract')]['family']['precision'] for cid in selected) / len(selected) if selected else None,
                'k10_semantic_exact': _rate(sum(unions[(model, cid)]['semantic']['exact'] for cid in selected), len(selected)),
                'source_ir_semantic_exact': _rate(sum(results[(model, cid, 'source_ir', 'extract')]['semantic']['exact'] for cid in selected), len(selected))}
        model_summary['refuter'] = {}
        for kind in ('deficient', 'faithful_complete'):
            selected = [results[(model, cid, 'adversarial_refuter', 'counter_read')] for cid in case_ids if cases[cid]['evaluation']['seed_kind'] == kind]
            opportunity = [row for row in selected if row['authored_consequential_opportunity']]
            model_summary['refuter'][kind] = {
                'scheduled': len(selected), 'valid_abstention': _rate(sum(row['abstained'] for row in selected), len(selected)),
                'emitted_counter_reading': _rate(sum(row['emitted_counter_reading'] for row in selected), len(selected)),
                'operational_or_schema_failure': _rate(sum(not row['schema_valid'] for row in selected), len(selected)),
                'structural_recovery': _rate(sum(row['recovery']['structural_recovery'] for row in selected), len(selected)),
                'consequential_source_aligned_addition': _rate(sum(row['recovery']['source_aligned_consequential_addition'] for row in selected), len(selected)),
                'authored_consequential_opportunities': len(opportunity),
                'consequential_recovery_when_possible': _rate(sum(row['recovery']['source_aligned_consequential_addition'] for row in opportunity), len(opportunity)),
                'clean_full_family_recovery': _rate(sum(row['clean_full_family_recovery'] for row in selected), len(selected)),
                'declared_contract_warning': _rate(sum(row['declared_source_audit'] is not None and row['declared_source_audit']['status'] != 'represented_declared_contract' for row in selected), len(selected))}
        model_summary['long_short'] = {}
        for condition, short_condition, phase in [('long_source_ir', 'source_ir', 'extract'), ('long_commitment', 'commitment', 'fresh_withdrawn')]:
            ids = sorted(long_cases)
            if ids:
                pair = _paired([results[(model, cid, short_condition, phase)] for cid in ids],
                               [results[(model, cid, condition, phase)] for cid in ids], False, names=(short_condition, condition))
                pair['status'] = 'secondary_descriptive_paired'
                pair['scope'] = 'Same selected base cases and authored semantics; not an additional independent sample. This secondary contrast is outside the ten-test primary Holm family.'
                model_summary['long_short'][condition] = pair
        model_summary['resources_by_condition'] = {condition: _resources([slot for slot in slots if slot['model'] == model and slot['condition'] == condition], record_index)
                                                    for condition in sorted({slot['condition'] for slot in slots})}
        model_summaries[model] = model_summary
    adjusted = holm_adjust([row['holm_input_p'] for row in pairs])
    for row, p_value in zip(pairs, adjusted):
        row['holm_adjusted_p'] = p_value if row['p_two_sided_exact'] is not None else None
        row['reserved_holm_position_adjusted_value'] = p_value
    if terminal_complete:
        for cid, case in sorted(cases.items()):
            metrics = {}
            for model in MODELS:
                metrics[model + ':source_ir_minus_k10'] = int(results[(model, cid, 'source_ir', 'extract')]['correct']) - int(unions[(model, cid)]['correct'])
                metrics[model + ':fresh_minus_history'] = int(results[(model, cid, 'commitment', 'fresh_withdrawn')]['correct']) - int(results[(model, cid, 'commitment', 'hist_withdrawn')]['correct'])
                metrics[model + ':compiled_ir_actual_withdrawn_minus_direct_fresh'] = int(results[(model, cid, 'source_ir', 'extract')]['actual_events']['states']['withdrawn']['exact_vector']) - int(results[(model, cid, 'commitment', 'fresh_withdrawn')]['correct'])
            bootstrap_rows.append({'case_id': cid, 'family': case['family'], 'metrics': metrics})
        bootstrap = {'status': 'evaluated_all_scheduled', **case_cluster_bootstrap(bootstrap_rows, seed=BOOTSTRAP_SEED, repeats=bootstrap_repeats)}
        for model in MODELS:
            metric = bootstrap['metrics'][model + ':compiled_ir_actual_withdrawn_minus_direct_fresh']
            model_summaries[model]['compiled_ir_vs_direct_withdrawn']['resampling_interval'] = metric['percentile_95_interval']
            model_summaries[model]['compiled_ir_vs_direct_withdrawn']['resampling_status'] = 'within_family_base_case_resampling_stability'
    else:
        bootstrap = {'status': 'unavailable_incomplete_dispatch', 'planned_replicates': bootstrap_repeats, 'seed': BOOTSTRAP_SEED,
                     'scope': 'No inferential/resampling interval is assigned to an incompletely dispatched study.'}
    primary_shape = len(cases) == 48 and len(long_cases) == 24 and len(slots) == 4560 and sorted(Counter(case['family'] for case in cases.values()).values()) == [8] * 6
    summary = {'schema': 'retrace.frontier-v6d-evaluation.v1',
               'status': 'complete_records' if terminal_complete else 'not_started' if not records else 'incomplete_records',
               'matches_primary48_design': primary_shape, 'base_cases': len(cases), 'long_base_cases': len(long_cases),
               'planned_slots': len(slots), 'response_records': len(records), 'all_planned_terminal_records': terminal_complete,
               'all_planned_final_outcomes': terminal_complete,
               'corpus_sha256_canonical': _digest(corpus), 'dossiers_sha256_canonical': _digest(dossiers), 'slots_sha256_canonical': _digest(slots),
               'models': model_summaries, 'primary_comparisons': pairs, 'holm_family_size': len(pairs), 'bootstrap': bootstrap,
               'resources': _resources(slots, record_index),
               'authored_opportunities': {cid: {'seed_kind': cases[cid]['evaluation']['seed_kind'], **value} for cid, value in opportunities.items()},
               'interpretation_limits': [
                   'Exact authored-family recovery is a controlled diagnostic; source completeness and semantic entailment are not certified by citation location or compiler admission.',
                   'Missing and invalid calls remain scheduled failures; a ten-draw union receives no graph from such calls and repeated valid draws do not add coverage.',
                   'A finalized schedule can include explicitly unissued truncated-history dependency outcomes. These remain failures and are not counted as issued or provider-completed requests.',
                   'K10 cannot recover more than10 distinct interpretations; report the feasible subset and behavioral fidelity alongside full-family recovery.',
                   'Actual-event fidelity retains original local flags and actual document/passage vetoes. It is separate from exhaustive hypothetical eligibility fidelity, which intentionally varies every local flag.',
                   'Bootstrap resamples base cases within fixed families with all models/conditions together; intervals describe this authored set, not an unspecified document population.',
                   'N=48 does not guarantee power. Primary inference is withheld for incomplete dispatch; unavailable comparisons retain their ten-test Holm positions with p=1 inputs.',
                   'History length, prior output and explicit event framing differ across commitment conditions; this is not an isolated causal estimate of psychological commitment.',
                   'Source IR and adversarial refutation have different input contexts; the refuter additionally sees authored seed graphs. Their contrast is not a prompt-isolated causal estimate.',
                   'A consequential counter-reading adds a source-aligned graph and changes conditional consensus under a hypothetical local-eligibility scenario. It does not automatically repair the seed family or establish factual truth.',
                   'Resource summaries are not substitutes for the append-only budget ledger and retained unknown-charge bounds.']}
    # Drop duplicate parsed payloads from the public summary; complete audit
    # objects remain available to a caller for exclusive JSONL persistence.
    for row in audits:
        row.pop('parsed', None)
    return {'summary': summary, 'audits': audits}
