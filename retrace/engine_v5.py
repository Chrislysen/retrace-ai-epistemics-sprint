"""Versioned syntax and hypothetical exposure composition; frozen engines stay intact."""
import copy

from .compact_v5 import compile_ambiguity
from .engine_v4 import analyze_v4
from .core import analyze
from .exposure_v5 import audit_exposure


def _inputs(brief, state):
    if not isinstance(brief, dict):
        raise ValueError('brief must be an object')
    working = copy.deepcopy(brief)
    compilation = None
    if 'compact_v5' in working:
        compilation = compile_ambiguity(working['compact_v5'], working.get('registry'))
        working['compact_v4'] = compilation['canonical_v4']
    result = analyze_v4(working, state)
    candidates = [c for c in result['compiled_brief']['candidates'] if c['id'] in result['candidate_ids']]
    locked = sorted(eid for eid, flags in result['revocation_flags'].items()
                    if flags['document_veto'] or flags['passage_veto'] or flags['scenario_veto'])
    allowed = working.get('allowed_exposure_changes', result['interventions']['allowed_withdrawals'])
    targets = working.get('target_decisions')
    return result, compilation, candidates, locked, allowed, targets


def analyze_v5(brief, state=None):
    result, compilation, candidates, locked, allowed, targets = _inputs(brief, state)
    try:
        exposure = audit_exposure(candidates, allowed, locked, targets)
    except ValueError as exc:
        # A broader source-eligibility audit may be undefined for candidate sets
        # disagreeing about baseline activity. Never alter the valid v4 result.
        exposure = {'status': 'unavailable', 'reason': str(exc), 'decisions': {},
                    'scope': ['Ordinary consensus and withdrawal analysis remain independently available.']}
    return {**result, 'schema': 'retrace.stress.v5',
            'ambiguity_compilation': compilation or result['ambiguity_compilation'],
            'exposure': exposure,
            'scope': result['scope'] + ['Exposure previews change hypothetical local eligibility only; no source truth, actual restoration or repair is inferred.']}


def preview_exposure(brief, state, enable, withdraw):
    result, _, candidates, locked, allowed, targets = _inputs(brief, state)
    audit = audit_exposure(candidates, allowed, locked, targets)
    allowed = audit['coverage']['changeable_evidence_ids']
    registry = {row['id']: row.get('active', True) for row in candidates[0]['graph']['evidence']}
    for values, label, baseline in ((enable, 'enable', False), (withdraw, 'withdraw', True)):
        if (not isinstance(values, list) or any(not isinstance(x, str) for x in values)
                or len(values) != len(set(values)) or not set(values) <= set(allowed)
                or set(values) & set(locked)):
            raise ValueError(f'{label} must contain distinct permitted, unlocked evidence IDs')
        if any(registry[x] is not baseline for x in values):
            raise ValueError(f'{label} conflicts with original local eligibility')
    if set(enable) & set(withdraw):
        raise ValueError('Enable and withdraw sets must be disjoint')
    outcomes = {}
    for candidate in candidates:
        graph = copy.deepcopy(candidate['graph'])
        for evidence in graph['evidence']:
            if evidence['id'] in enable:
                evidence['active'] = True
            if evidence['id'] in set(withdraw) | set(locked):
                evidence['active'] = False
        snapshot = analyze(graph)
        outcomes[candidate['id']] = {did: row['usable'] for did, row in snapshot['decisions'].items()
                                     if did in audit['target_decisions']}
    return {'schema': 'retrace.exposure-preview.v5', 'status': 'hypothetical_source_amendment',
            'enable': sorted(enable), 'withdraw': sorted(withdraw), 'locked_exclusions': locked,
            'outcomes': outcomes, 'original_state': result['state'],
            'audit_input_fingerprint': audit['input_fingerprint'],
            'assumption': 'Enabling assumes local eligibility, not truth. This preview does not modify source records, answers, or revocation flags.'}
