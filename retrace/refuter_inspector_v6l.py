"""Reference-free inspection of an unchanged controlled-seed refuter response.

The input family is authored and was supplied to the model. It is NOT the
model's earlier extraction. No gold, event vetoes, source repair or mutation.
"""
from copy import deepcopy
import json

from .refuter_gate_v6h import validate_refuter
from .tiered_v6h import validate, family_supervaluation, require
from .graph_identity_v6h import graph_key
from .impact_v6h import compare_families, enable_withdraw_impact

SCOPE = ('Controlled authored candidate family supplied to the refuter; not an actual upstream model extraction. '
         'Compare G with G union P, never replace G with P. Exact source locations do not verify entailment '
         'or completeness. Original local flags apply; no event vetoes, document groups or source corrections are inferred.')


def json_value(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def seed_graphs(candidates):
    require(isinstance(candidates, list) and 1 <= len(candidates) <= 32, 'One to32 supplied candidates required')
    ids = set(); graphs = []
    for row in candidates:
        require(isinstance(row, dict) and set(row) == {'id', 'graph'} and isinstance(row['id'], str)
                and 0 < len(row['id']) <= 256 and row['id'] not in ids, 'Exact unique supplied candidate fields')
        ids.add(row['id']); graphs.append(validate(row['graph'])[0])
    return graphs


def bounded(call, *args, **kwargs):
    try:
        return {'status': 'evaluated', **json_value(call(*args, **kwargs))}
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        return {'status': 'unavailable', 'reason': str(exc), 'error_type': type(exc).__name__,
                'scope': 'A bound or compatibility check prevented this mechanism. No effect or absence of effect is inferred.'}


def compare(seed, proposed):
    """Same additive semantics as the frozen preview, without a fabricated IR."""
    old = seed_graphs(seed); new = seed_graphs(proposed)
    inventory = lambda graph: {k: sorted(r['id'] for r in graph[k]) for k in ('evidence', 'claims', 'decisions')}
    common = {'proposal_applied': False, 'state_mutated': False, 'semantic_entailment_verified': False,
              'comparison': 'G versus G union P', 'event_state': 'original_local_flags_no_external_vetoes', 'scope': SCOPE}
    if any(inventory(g) != inventory(old[0]) for g in old + new):
        return {**common, 'status': 'unavailable', 'reason': 'Compared families have different operational typed inventories',
                'decision_impact': None, 'hamming2': None, 'modal_summary': None}
    keys = {graph_key(g) for g in old}; proposed_keys = {graph_key(g) for g in new}
    def modal():
        a = family_supervaluation(old)['decisions']; p = family_supervaluation(new)['decisions']
        pick = lambda row: {k: row[k] for k in ('box_supported', 'diamond_supported')}
        return {'decisions': {d: {'seed': pick(a[d]), 'proposal': pick(p[d]),
            'augmented': {'box_supported': a[d]['box_supported'] and p[d]['box_supported'],
                          'diamond_supported': a[d]['diamond_supported'] or p[d]['diamond_supported']}}
            for d in sorted(a)}}
    def exposure():
        result = enable_withdraw_impact(old, new)
        # Frozen helper preserves the seed and P-only trajectories. Add an
        # explicitly named union view; do not replace or alter those fields.
        for row in result['witnesses']:
            a = row['enabled_and_withdrawn']; p = row['proposed_enabled_and_withdrawn']
            row['augmented_enabled_and_withdrawn'] = {
                'box_supported': a[0] and p[0], 'diamond_supported': a[1] or p[1]}
        return result
    return {**common, 'status': 'preview_only',
            'declaration_comparison': {'seed_distinct': len(keys), 'proposal_distinct': len(proposed_keys),
                'union_distinct': len(keys | proposed_keys), 'novel_proposed_readings': len(proposed_keys - keys),
                'seed_readings_absent_from_proposal': len(keys - proposed_keys),
                'scope': 'Structural difference from an authored seed is not proof of a source omission.'},
            'modal_summary': bounded(modal), 'decision_impact': bounded(compare_families, old, new),
            'hamming2': bounded(exposure)}


def inspect(raw_text, documents, registry, supplied_candidates):
    """Only completed original response TEXT may enter; callers enforce transport."""
    require(isinstance(raw_text, str), 'Unchanged response text required')
    seed_graphs(supplied_candidates)
    base = {'schema': 'retrace.controlled-refuter-inspection.v6l.v1', 'scope': SCOPE,
            'semantic_entailment_verified': False, 'source_completeness': 'unknown',
            'proposal_applied': False, 'state_mutated': False, 'preview': None}
    try:
        require(len(raw_text) <= 524288, 'Bounded unchanged response text required')
        gate = validate_refuter(raw_text, documents, registry)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        return {**base, 'status': 'rejected', 'gate': {'status': 'rejected', 'error_type': type(exc).__name__,
            'reason': str(exc), 'semantic_entailment_verified': False}}
    # Preserve gate results without any evaluation-only family or correctness fields.
    public_gate = {k: deepcopy(gate[k]) for k in ('status', 'raw_warning_score', 'strict_bare_json',
                   'proposal_applied', 'semantic_entailment_verified', 'locations')}
    public_gate['candidate_count'] = gate['compilation']['candidate_count'] if gate['compilation'] else 0
    if gate['status'] == 'abstained':
        return {**base, 'status': 'abstained', 'gate': public_gate,
                'abstention_scope': 'Abstention does not certify source completeness or absence of omissions.'}
    proposal = gate['compilation']['candidates']
    public_gate['original_ir'] = deepcopy(gate['compilation']['original_ir'])
    return {**base, 'status': 'source_located_proposal', 'gate': public_gate,
            'preview': bounded(compare, supplied_candidates, [{'id': r['id'], 'graph': r['graph']} for r in proposal])}
