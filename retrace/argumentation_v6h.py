"""Component-local grounded Dung semantics for explicit structured rebuttals.

This is an equal-priority defeasible rebuttal fragment, not full ASPIC+.
No contraposition, classical explosion, implicit attacks or truth claims.
"""
from collections import defaultdict


def grounded_partitioned(arguments, attacks):
    ids = set(arguments)
    if len(ids) != len(arguments) or len(ids) > 2048:
        raise ValueError('Argument uniqueness/bound')
    predecessors, neighbors = defaultdict(set), defaultdict(set)
    pairs = set()
    for source, target in attacks:
        if source not in ids or target not in ids:
            raise ValueError('Unknown attack endpoint')
        pairs.add((source, target)); predecessors[target].add(source)
        neighbors[source].add(target); neighbors[target].add(source)
    components, remaining = [], set(ids)
    while remaining:
        todo = [min(remaining)]; component = set()
        while todo:
            item = todo.pop()
            if item not in component:
                component.add(item); todo.extend(neighbors[item] - component)
        remaining -= component; components.append(component)
    accepted, rejected, undecided, records = set(), set(), set(), []
    for component in components:
        inside = set()
        while True:
            defeated = {target for source, target in pairs if source in inside}
            next_inside = {argument for argument in component if predecessors[argument] <= defeated}
            if not inside <= next_inside:
                raise AssertionError('Dung characteristic iteration must be monotone from empty')
            if next_inside == inside:
                break
            inside = next_inside
        outside = {target for source, target in pairs if source in inside}
        pending = component - inside - outside
        accepted |= inside; rejected |= outside; undecided |= pending
        records.append({'arguments': sorted(component), 'in': sorted(inside),
                        'out': sorted(outside), 'undecided': sorted(pending)})
    return {'in': sorted(accepted), 'out': sorted(rejected), 'undecided': sorted(undecided), 'components': records}


def rebuttal_arbiter(arguments):
    """Arguments declare signed conclusions and the IDs of all subarguments.

An opposite conclusion attacks a matching defeasible subargument and every
argument containing it. Do not merge unrelated claims into one contradiction.
"""
    if not isinstance(arguments, list):
        raise ValueError('Argument array required')
    index = {}
    for row in arguments:
        if not isinstance(row, dict) or set(row) != {'id', 'claim', 'polarity', 'subarguments'}:
            raise ValueError('Explicit argument fields required')
        if not all(isinstance(row[key], str) and row[key] for key in ('id', 'claim')) or row['id'] in index:
            raise ValueError('Unique nonempty argument ID/claim required')
        if row['polarity'] not in ('positive', 'negative') or not isinstance(row['subarguments'], list):
            raise ValueError('Signed conclusion and subargument IDs required')
        if len(set(row['subarguments'])) != len(row['subarguments']):
            raise ValueError('Duplicate subargument')
        index[row['id']] = row
    closures = {}
    def closure(ident, trail):
        if ident not in index or ident in trail:
            raise ValueError('Dangling or cyclic subargument')
        if ident not in closures:
            found = {ident}
            for child in index[ident]['subarguments']:
                found |= closure(child, trail | {ident})
            closures[ident] = found
        return closures[ident]
    for ident in index:
        closure(ident, set())
    attacks = set()
    for attacker, row in index.items():
        for target, subids in closures.items():
            if any(index[sub]['claim'] == row['claim'] and index[sub]['polarity'] != row['polarity'] for sub in subids):
                attacks.add((attacker, target))
    labels = grounded_partitioned(list(index), attacks)
    return {**labels, 'attacks': [list(pair) for pair in sorted(attacks)],
            'semantics': 'grounded; equal-priority defeasible rebuttal fragment; no full ASPIC+ claim'}


def claim_state(claim, arguments, labels, *, unresolved=False):
    accepted = set(labels['in']); undecided = set(labels['undecided'])
    positive = [row['id'] for row in arguments if row['claim'] == claim and row['polarity'] == 'positive']
    negative = [row['id'] for row in arguments if row['claim'] == claim and row['polarity'] == 'negative']
    if unresolved:
        state = 'insufficient_provenance'
    elif set(positive) & accepted:
        state = 'supported'
    elif (set(positive) | set(negative)) & undecided:
        state = 'contested'
    else:
        state = 'not_supported'
    return {'state': state, 'positive_warrant_accepted': bool(set(positive) & accepted),
            'negative_warrant_accepted': bool(set(negative) & accepted),
            'truth_asserted': False}
