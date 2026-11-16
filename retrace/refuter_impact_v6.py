"""Reference-free, exact *conditional* impact of adding a proposed graph family.

This checks declarations, never whether a proposed reading follows from prose.
Adding candidates can destroy unanimity, but cannot reverse it to the opposite
unanimity. Existing evidence eligibility and vetoes are never repaired here.
"""
from hashlib import sha256
import json

from .stress_v6c import _basis, _table, _validate
from .uncertainty_v6c import _canonical


def _signature(graph):
    return sha256(json.dumps(_canonical(graph), sort_keys=True,
                            separators=(",", ":")).encode()).hexdigest()


def _unique(candidates):
    seen = set()
    result = []
    for candidate in candidates:
        signature = _signature(candidate['graph'])
        if signature not in seen:
            seen.add(signature)
            result.append({**candidate, 'graph_sha256': signature})
    return result


def _state(values):
    return 'unanimous_supported' if all(values) else 'disputed' if any(values) else 'unanimous_unsupported'


def compare_readings(current, proposed, *, locked_exclusions=None,
                     allowed_withdrawals=None, target_decisions=None):
    """Return minimum-cardinality witnesses for consensus loss, within <=16 IDs.

    Each family has <=32 validated candidates. Candidate IDs are local to their
    family; structural duplicates count once. A proposal is added, never used to
    replace or delete existing readings. The caller must resolve/review prior
    clarification answers before invoking this on a changed interpretation set.
    """
    families = []
    registry = None
    for candidates in (current, proposed):
        validated = _validate({'candidates': candidates, 'allowed_withdrawals': []}, {})
        if registry is not None and validated[1] != registry:
            raise ValueError('Compared families need identical typed operational IDs')
        registry = validated[1]
        families.append(_unique(validated[0]))
    current, proposed = families
    known = registry['evidence']

    def ids(values, domain, label):
        if (not isinstance(values, list) or any(not isinstance(x, str) or x not in domain for x in values)
                or len(values) != len(set(values))):
            raise ValueError(label + ' must name distinct declared IDs')
        return sorted(values)

    locked = ids([] if locked_exclusions is None else locked_exclusions, known, 'locked_exclusions')
    allowed = ids(sorted(known) if allowed_withdrawals is None else allowed_withdrawals, known, 'allowed_withdrawals')
    targets = ids(sorted(registry['decisions']) if target_decisions is None else target_decisions,
                  registry['decisions'], 'target_decisions')
    variables = sorted(set(allowed) - set(locked))
    if len(variables) > 16:
        raise ValueError('Narrow counter-reading impact to at most16 unlocked withdrawal IDs')
    states, universe, available, minimum = _basis(variables)
    available.update({eid: 0 for eid in locked})
    current_signatures = {c['graph_sha256'] for c in current}
    novel = [c for c in proposed if c['graph_sha256'] not in current_signatures]
    tables = [[(c, _table(c['graph'], available, universe)) for c in family]
              for family in (current, novel)]
    decisions = {}
    for did in targets:
        current_all, current_any = universe, 0
        novel_all, novel_any = universe, 0
        for _, table in tables[0]:
            current_all &= table[did]
            current_any |= table[did]
        for _, table in tables[1]:
            novel_all &= table[did]
            novel_any |= table[did]
        # Only unanimous old states can become newly disputed after set growth.
        changed = (current_all & (universe ^ novel_all)) | ((universe ^ current_any) & novel_any)
        found = minimum(changed)
        witness = None
        if found is not None:
            assignment, withdrawn = found
            outcomes = [[{'candidate_id': c['id'], 'graph_sha256': c['graph_sha256'],
                          'supported': bool(table[did] & (1 << assignment))}
                         for c, table in family] for family in tables]
            before = [r['supported'] for r in outcomes[0]]
            after = before + [r['supported'] for r in outcomes[1]]
            witness = {'withdraw': withdrawn, 'k': len(withdrawn),
                       'current_family_state': _state(before), 'augmented_family_state': _state(after),
                       'current_outcomes': outcomes[0], 'novel_proposal_outcomes': outcomes[1],
                       'no_smaller_withdrawal_changes_consensus': True}
        decisions[did] = {'minimum_consensus_loss': witness,
                          'affected_withdrawal_states': changed.bit_count(),
                          'already_affected_at_current_state': bool(changed & 1),
                          'no_consensus_loss_within_scope': not bool(changed)}
    return {'schema': 'retrace.refuter-impact.v6', 'status': 'evaluated',
            'current_distinct_graphs': len(current), 'proposed_distinct_graphs': len(proposed),
            'novel_proposed_graphs': len(novel), 'augmented_distinct_graphs': len(current) + len(novel),
            'locked_exclusions': locked, 'withdrawal_variables': variables,
            'states_checked_per_graph': states, 'decisions': decisions,
            'automatic_commit': False, 'semantic_entailment': 'not_certified',
            'scope': 'Exact effect if the novel proposed graphs are admitted in addition to the current declared family. No gold graph, source entailment, completeness, truth, calibrated probability, activation of inactive evidence, or replacement of current readings is inferred. No detected effect is limited to these withdrawals and decisions.'}
