"""Bounded Boolean provenance with scoped monus; no prose interpretation.

OR and AND are associative/idempotent and obey absorption. Monus is A AND NOT U;
it is NOT associative and its scope must never be reassociated. A fixed-order
reduced BDD gives canonical Boolean functions, checked against direct evaluation.
"""
from itertools import combinations


def validate_expr(expr, identifiers, *, max_depth=24, max_nodes=4096):
    count = [0]
    def visit(value, depth):
        count[0] += 1
        if depth > max_depth or count[0] > max_nodes or not isinstance(value, dict) or len(value) != 1:
            raise ValueError('Expression shape/depth/node bound')
        op, arg = next(iter(value.items()))
        if op == 'ref':
            if not isinstance(arg, str) or arg not in identifiers:
                raise ValueError('Unknown expression reference')
            return {arg}
        if op == 'const':
            if type(arg) is not bool:
                raise ValueError('Constant must be Boolean')
            return set()
        if op in ('all', 'any'):
            if not isinstance(arg, list) or not 2 <= len(arg) <= 250:
                raise ValueError('Boolean group requires2..250 operands')
            return set().union(*(visit(child, depth + 1) for child in arg))
        if op == 'unless':
            if not isinstance(arg, dict) or set(arg) != {'support', 'undercutter'}:
                raise ValueError('Unless requires explicit support and undercutter')
            return visit(arg['support'], depth + 1) | visit(arg['undercutter'], depth + 1)
        raise ValueError('Unknown Boolean constructor')
    return visit(expr, 0)


def evaluate(expr, values):
    op, arg = next(iter(expr.items()))
    if op == 'ref':
        return values[arg]
    if op == 'const':
        return arg
    if op == 'all':
        return all(evaluate(child, values) for child in arg)
    if op == 'any':
        return any(evaluate(child, values) for child in arg)
    if op == 'unless':
        return evaluate(arg['support'], values) and not evaluate(arg['undercutter'], values)
    raise ValueError('Unknown constructor')


class BDD:
    """Canonical reduced ordered Boolean DAG within one fixed variable order."""
    def __init__(self, variables, max_nodes=100000):
        if not isinstance(variables, list) or len(variables) > 250 or len(set(variables)) != len(variables):
            raise ValueError('Unique bounded variable order required')
        self.variables = list(variables)
        self.order = {v: i for i, v in enumerate(variables)}
        self.nodes = {0: None, 1: None}
        self.unique = {}
        self.cache = {}
        self.max_nodes = max_nodes

    def node(self, level, low, high):
        if low == high:
            return low
        key = level, low, high
        if key not in self.unique:
            if len(self.nodes) >= self.max_nodes:
                raise ValueError('ROBDD node bound; no partial result')
            ident = len(self.nodes)
            self.unique[key] = ident
            self.nodes[ident] = key
        return self.unique[key]

    def variable(self, name):
        return self.node(self.order[name], 0, 1)

    def apply(self, op, left, right):
        if op not in ('and', 'or', 'monus'):
            raise ValueError('Unknown operation')
        key = op, left, right
        if key in self.cache:
            return self.cache[key]
        if left <= 1 and right <= 1:
            result = int((bool(left) and bool(right)) if op == 'and' else
                         (bool(left) or bool(right)) if op == 'or' else (bool(left) and not bool(right)))
        else:
            level = min(self.nodes[v][0] for v in (left, right) if v > 1)
            def parts(v):
                return self.nodes[v][1:] if v > 1 and self.nodes[v][0] == level else (v, v)
            lo, hi = parts(left); ro, rh = parts(right)
            result = self.node(level, self.apply(op, lo, ro), self.apply(op, hi, rh))
        self.cache[key] = result
        return result

    def compile(self, expr, bindings=None):
        bindings = bindings or {}
        op, arg = next(iter(expr.items()))
        if op == 'ref':
            return bindings[arg] if arg in bindings else self.variable(arg)
        if op == 'const':
            return int(arg)
        if op == 'unless':
            return self.apply('monus', self.compile(arg['support'], bindings), self.compile(arg['undercutter'], bindings))
        if op in ('all', 'any'):
            result = 1 if op == 'all' else 0
            for child in arg:
                result = self.apply('and' if op == 'all' else 'or', result, self.compile(child, bindings))
            return result
        raise ValueError('Unknown constructor')

    def evaluate(self, root, values):
        while root > 1:
            level, low, high = self.nodes[root]
            root = high if values[self.variables[level]] else low
        return bool(root)

    def serialize(self, root):
        reachable = set()
        def walk(v):
            if v > 1 and v not in reachable:
                reachable.add(v)
                _, low, high = self.nodes[v]; walk(low); walk(high)
        walk(root)
        return {'order': self.variables, 'root': root,
                'nodes': [{'id': v, 'variable': self.variables[self.nodes[v][0]],
                           'low': self.nodes[v][1], 'high': self.nodes[v][2]} for v in sorted(reachable)]}


def minimum_withdrawal(function, current, allowed):
    """Exact cardinality search; valid for nonmonotone unless functions too."""
    if len(allowed) > 16 or len(set(allowed)) != len(allowed) or set(allowed) - set(current):
        raise ValueError('At most16 unique known withdrawal variables')
    before = function(current)
    for size in range(len(allowed) + 1):
        for subset in combinations(sorted(allowed), size):
            after = function({**current, **{key: False for key in subset}})
            if after != before:
                return {'k': size, 'withdraw': list(subset), 'before': before, 'after': after}
    return None


def hamming2_witnesses(function, current, *, locked=()):
    """Diagnostic activation then withdrawal; never an authorized restoration.

Find every (inactive E, active W) where enabling E changes the baseline result,
and additionally withdrawing W reverses that change. Locked IDs cannot change.
"""
    if len(current) > 16 or set(locked) - set(current):
        raise ValueError('Hamming2 bound or unknown locked ID')
    locked = set(locked); before = function(current); results = []
    for enable in sorted(key for key, value in current.items() if not value and key not in locked):
        enabled = {**current, enable: True}; middle = function(enabled)
        if middle == before:
            continue
        for withdraw in sorted(key for key, value in current.items() if value and key not in locked):
            after = function({**enabled, withdraw: False})
            if after == before:
                results.append({'enable': enable, 'withdraw': withdraw, 'hamming_distance': 2,
                                'baseline': before, 'enabled': middle, 'enabled_and_withdrawn': after,
                                'hypothetical_activation': True})
    return results
