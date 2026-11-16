"""Exact bounded fusion of Boolean provenance and local rebuttal arbitration.

The declaration is trusted input. Source entailment, truth and interpretation
completeness are not established. Unknown ancestry is explicitly quantified,
never silently converted into an independent root.
"""
from copy import deepcopy
from hashlib import sha256
from itertools import product
import json
import re

from .boolean_v6h import BDD, evaluate, validate_expr
from .argumentation_v6h import rebuttal_arbiter, claim_state

SCHEMA = 'retrace.tiered-graph.v6h'
IDENT = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
FALSE = {'const': False}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def validate(graph):
    require(isinstance(graph, dict) and set(graph) == {'schema', 'evidence', 'claims', 'decisions'}, 'Graph fields')
    require(graph['schema'] == SCHEMA, 'Graph schema')
    graph = deepcopy(graph)
    index, category = {}, {}
    fields = {'evidence': {'id', 'kind', 'active', 'parents'},
              'claims': {'id', 'positive', 'negative'}, 'decisions': {'id', 'requires'}}
    for kind in fields:
        require(isinstance(graph[kind], list), 'Node array required')
        for row in graph[kind]:
            require(isinstance(row, dict) and set(row) == fields[kind], 'Exact node fields required')
            ident = row['id']
            require(isinstance(ident, str) and IDENT.fullmatch(ident) and ident != '-' and ident not in index, 'Unique typed identifier')
            index[ident] = row; category[ident] = kind
    require(0 < len(index) <= 250, 'Node count')
    dependencies = {}
    for row in graph['evidence']:
        require(type(row['active']) is bool and row['kind'] in ('root', 'copy', 'unknown'), 'Origin/local eligibility')
        parents = row['parents']
        require(isinstance(parents, list) and all(isinstance(p, str) and category.get(p) == 'evidence' for p in parents), 'Typed parents')
        require(len(parents) == len(set(parents)) and row['id'] not in parents, 'Unique nonself parents')
        require(row['kind'] != 'root' or not parents, 'Root cannot have parents')
        require(row['kind'] != 'copy' or bool(parents), 'Copy needs parents')
        dependencies[row['id']] = set(parents)
    expr_ids = {ident for ident, kind in category.items() if kind != 'decisions'}
    def undercuts(expr):
        op, arg = next(iter(expr.items()))
        if op in ('all', 'any'):
            for child in arg:
                undercuts(child)
        elif op == 'unless':
            refs = validate_expr(arg['undercutter'], expr_ids)
            require(all(category[ref] == 'evidence' for ref in refs), 'Undercutter must have evidence-only provenance in this fragment')
            undercuts(arg['support']); undercuts(arg['undercutter'])
    for row in graph['claims']:
        dependencies[row['id']] = set()
        for polarity in ('positive', 'negative'):
            dependencies[row['id']] |= validate_expr(row[polarity], expr_ids)
            undercuts(row[polarity])
    for row in graph['decisions']:
        refs = row['requires']
        require(isinstance(refs, list) and bool(refs) and all(isinstance(p, str) and category.get(p) == 'claims' for p in refs), 'Typed decision requirements')
        require(len(refs) == len(set(refs)), 'Duplicate requirement')
        dependencies[row['id']] = set(refs)
    pending, order, done = set(index), [], set()
    while pending:
        ready = sorted(ident for ident in pending if dependencies[ident] <= done)
        require(bool(ready), 'Cyclic/self dependency')
        order.extend(ready); done.update(ready); pending.difference_update(ready)
    unknown = [row['id'] for row in graph['evidence'] if row['kind'] == 'unknown']
    require(len(unknown) <= 8, 'At most8 unresolved ancestry variables')
    return graph, index, category, order, unknown


def from_positive_graph(graph):
    def expr(routes):
        clauses = [{'ref': clause[0]} if len(clause) == 1 else {'all': [{'ref': ref} for ref in clause]} for clause in routes]
        return FALSE.copy() if not clauses else clauses[0] if len(clauses) == 1 else {'any': clauses}
    result = {'schema': SCHEMA, 'evidence': deepcopy(graph['evidence']),
              'claims': [{'id': row['id'], 'positive': expr(row['supports']), 'negative': FALSE.copy()} for row in graph['claims']],
              'decisions': deepcopy(graph['decisions'])}
    return validate(result)[0]


def _concrete(prepared, overrides, excluded, unknown_values):
    graph, index, category, order, unknown = prepared
    values, evidence_proofs, proof_by_claim, arguments, provenance = {}, {}, {}, [], {}
    def proofs(expr):
        op, arg = next(iter(expr.items()))
        if op == 'ref':
            if category[arg] == 'evidence':
                return {(evidence_proofs[arg], frozenset())} if values[arg] else set()
            return proof_by_claim[arg]
        if op == 'const':
            return {(frozenset(), frozenset())} if arg else set()
        if op == 'unless':
            return set() if evaluate(arg['undercutter'], values) else proofs(arg['support'])
        groups = [proofs(child) for child in arg]
        if op == 'any':
            result = set().union(*groups)
        else:
            result = {(frozenset(), frozenset())}
            for group in groups:
                combined = set()
                for e, a in result:
                    for f, b in group:
                        combined.add((e | f, a | b))
                        require(len(combined) <= 1024, 'Proof expansion bound')
                result = combined
        require(len(result) <= 1024, 'Proof expansion bound')
        return result
    for ident in order:
        row = index[ident]; kind = category[ident]
        if kind == 'evidence':
            local = overrides.get(ident, row['active']) and ident not in excluded
            values[ident] = local and all(values[parent] for parent in row['parents']) and unknown_values.get(ident, True)
            evidence_proofs[ident] = frozenset({ident}).union(*(evidence_proofs[parent] for parent in row['parents']))
        elif kind == 'claims':
            positive = set()
            for polarity in ('positive', 'negative'):
                for evidence, subs in sorted(proofs(row[polarity]), key=lambda pair: (sorted(pair[0]), sorted(pair[1]))):
                    signature = json.dumps([ident, polarity, sorted(evidence), sorted(subs)], separators=(',', ':'))
                    aid = 'arg-' + sha256(signature.encode()).hexdigest()[:24]
                    arguments.append({'id': aid, 'claim': ident, 'polarity': polarity, 'subarguments': sorted(subs)})
                    provenance[aid] = sorted(evidence)
                    if polarity == 'positive':
                        positive.add((evidence, frozenset({aid})))
            require(len(arguments) <= 2048, 'Structured argument bound')
            proof_by_claim[ident] = positive; values[ident] = bool(positive)
    labels = rebuttal_arbiter(arguments)
    claims = {row['id']: claim_state(row['id'], arguments, labels) for row in graph['claims']}
    decisions = {}
    for row in graph['decisions']:
        states = [claims[ref]['state'] for ref in row['requires']]
        state = ('not_supported' if 'not_supported' in states else 'contested' if 'contested' in states else 'supported')
        decisions[row['id']] = {'state': state, 'truth_asserted': False}
    return {'evidence_usable': {row['id']: values[row['id']] for row in graph['evidence']},
            'claims': claims, 'decisions': decisions, 'arguments': arguments, 'argument_provenance': provenance,
            'arbitration': labels}


def analyze(graph, *, local_overrides=None, document_vetoes=None, passage_vetoes=None, scenario_withdrawals=None):
    prepared = validate(graph)
    known = {row['id'] for row in prepared[0]['evidence']}
    overrides = {} if local_overrides is None else local_overrides
    require(isinstance(overrides, dict) and set(overrides) <= known and all(type(v) is bool for v in overrides.values()), 'Explicit known Boolean overrides')
    vetoes = {}
    for label, values in [('document', document_vetoes), ('passage', passage_vetoes), ('scenario', scenario_withdrawals)]:
        values = [] if values is None else values
        require(isinstance(values, list) and all(isinstance(v, str) and v in known for v in values) and len(set(values)) == len(values), 'Unique known veto IDs')
        vetoes[label] = sorted(values)
    excluded = set().union(*map(set, vetoes.values()))
    unknown = prepared[-1]
    assignments = [dict(zip(unknown, bits)) for bits in product((False, True), repeat=len(unknown))]
    worlds = [_concrete(prepared, overrides, excluded, assignment) for assignment in assignments]
    aggregate = {}
    for category in ('claims', 'decisions'):
        aggregate[category] = {}
        for ident in worlds[0][category]:
            states = sorted({world[category][ident]['state'] for world in worlds})
            aggregate[category][ident] = {'state': states[0] if len(states) == 1 else 'insufficient_provenance',
                'possible_states': states, 'box_supported': states == ['supported'],
                'diamond_supported': 'supported' in states, 'truth_asserted': False}
    return {'schema': 'retrace.tiered-analysis.v6h', **aggregate, 'unknown_ancestry_ids': unknown,
            'ancestry_completions': len(worlds), 'vetoes': vetoes, 'hypothetical_local_overrides': overrides,
            'completion_decisions': [{'assignment': assignment, 'states': {d:r['state'] for d,r in world['decisions'].items()}}
                                     for assignment, world in zip(assignments, worlds)],
            'concrete': worlds[0] if not unknown else None,
            'scope': 'Grounded declared-support status. Exact only within this finite declaration; no source entailment or truth certification.'}


def family_supervaluation(candidates, **state):
    require(isinstance(candidates, list) and 1 <= len(candidates) <= 32, '1..32 candidates required')
    outcomes = [analyze(graph, **state) for graph in candidates]
    typed = [{kind: {row['id'] for row in graph[kind]} for kind in ('evidence', 'claims', 'decisions')} for graph in candidates]
    require(all(registry == typed[0] for registry in typed), 'Fixed typed family inventory required')
    shared_unknowns = sorted(set().union(*(set(row['unknown_ancestry_ids']) for row in outcomes)))
    aligned = [dict(zip(shared_unknowns, bits)) for bits in product((False, True), repeat=len(shared_unknowns))] if len(shared_unknowns) <= 8 else None
    def at_completion(outcome, assignment, decision):
        return next(row['states'][decision] for row in outcome['completion_decisions']
                    if all(assignment[key] == val for key,val in row['assignment'].items()))
    decisions = {}
    for ident in outcomes[0]['decisions']:
        statuses = [row['decisions'][ident] for row in outcomes]
        decisions[ident] = {'box_supported': all(row['box_supported'] for row in statuses),
                           'diamond_supported': any(row['diamond_supported'] for row in statuses),
                           'possible_state_set_invariant': len({tuple(row['possible_states']) for row in statuses}) == 1,
                           'interpretation_invariant': all(len({at_completion(outcome, assignment, ident) for outcome in outcomes}) == 1 for assignment in aligned) if aligned is not None else None,
                           'states_by_candidate': [row['state'] for row in statuses]}
    return {'decisions': decisions, 'candidates': outcomes, 'candidate_count': len(candidates),
            'aligned_ancestry_completions': len(aligned) if aligned is not None else None,
            'invariance_scope': 'Compare candidate decision states at each common named-ancestry completion; withhold above8 joint variables. Box/diamond quantify all candidate-local completions.'}


def tier_a_bdd(graph):
    """Evidence-local flag functions. Tier B rebuttals require separate arbitration.

The variables are hypothetical local eligibilities, not operational restoration
permissions. Unknown origins and negative warrants deliberately reject this path.
"""
    graph, index, categories, order, unknown = validate(graph)
    require(not unknown and all(row['negative'] == FALSE for row in graph['claims']), 'ROBDD Tier A requires known ancestry and no polar rebuttals')
    variables = sorted(row['id'] for row in graph['evidence'])
    manager = BDD(variables); roots = {}
    for ident in order:
        row = index[ident]; kind = categories[ident]
        if kind == 'evidence':
            root = manager.variable(ident)
            for parent in row['parents']:
                root = manager.apply('and', root, roots[parent])
        elif kind == 'claims':
            root = manager.compile(row['positive'], roots)
        else:
            root = 1
            for parent in row['requires']:
                root = manager.apply('and', root, roots[parent])
        roots[ident] = root
    return manager, roots
