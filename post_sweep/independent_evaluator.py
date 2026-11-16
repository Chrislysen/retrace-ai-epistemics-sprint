#!/usr/bin/env python3
"""An evaluator for RETRACE declarations written from the paper's definitions (Section 2 and Proposition B.3).

Sprint addition, written with AI assistance on Monday 16 November 2026. Standard library only, and no import from
retrace/: it shares no code with the engine. compare_independent_evaluator.py runs both on the authored readings.

Definitions used
  record     usable when its own flag is on, it is not withdrawn or vetoed, every parent is usable and, for a record
             of unknown ancestry, the world assumes it available
  expression ref, const, all, any, or "support unless undercutter"; the undercutter is a plain Boolean over records
  argument   one way of establishing a claim's positive or negative expression; a reference to another claim uses
             one of that claim's positive arguments. An argument relies on a set of signed conclusions: its own and
             those of the arguments it uses
  attack     an argument is attacked when some argument concludes the opposite of one of the conclusions it relies on
  claim      supported if it has an unattacked positive argument; otherwise contested if one of its arguments, for or
             against, is attacked; otherwise not supported  (Proposition B.3: nothing else can be accepted)
  decision   not supported if a required claim is not supported; otherwise contested if one is contested; otherwise
             supported
  reading    its decision state over all worlds of unknown ancestry: the common state, or insufficient provenance.
             Box: supported in every world. Diamond: supported in some world
  family     Box: Box under every reading. Diamond: Diamond under some reading
"""
from itertools import product

FLIP = {"positive": "negative", "negative": "positive"}


def references(expr):
    op, arg = next(iter(expr.items()))
    if op == "ref":
        return {arg}
    if op == "const":
        return set()
    if op == "unless":
        return references(arg["support"]) | references(arg["undercutter"])
    return set().union(*(references(child) for child in arg))


def in_dependency_order(graph):
    needs = {r["id"]: set(r["parents"]) for r in graph["evidence"]}
    for claim in graph["claims"]:
        needs[claim["id"]] = references(claim["positive"]) | references(claim["negative"])
    order, done = [], set()
    while len(order) < len(needs):
        ready = sorted(i for i in needs if i not in done and needs[i] <= done)
        if not ready:
            raise ValueError("cyclic declaration")
        order += ready
        done |= set(ready)
    return order


def holds(expr, usable):
    """Plain Boolean value over record usability; used for the guard of an exception."""
    op, arg = next(iter(expr.items()))
    if op == "ref":
        return usable[arg]
    if op == "const":
        return arg
    if op == "all":
        return all(holds(child, usable) for child in arg)
    if op == "any":
        return any(holds(child, usable) for child in arg)
    return holds(arg["support"], usable) and not holds(arg["undercutter"], usable)


def ways(expr, usable, positive):
    """Every way of establishing an expression, each as the set of signed conclusions it relies on."""
    op, arg = next(iter(expr.items()))
    if op == "ref":
        if arg in usable:
            return {frozenset()} if usable[arg] else set()
        return positive[arg]
    if op == "const":
        return {frozenset()} if arg else set()
    if op == "unless":
        return set() if holds(arg["undercutter"], usable) else ways(arg["support"], usable, positive)
    parts = [ways(child, usable, positive) for child in arg]
    if op == "any":
        return set().union(*parts)
    combined = {frozenset()}
    for part in parts:
        combined = {a | b for a in combined for b in part}
    return combined


def world(graph, excluded, assumed):
    """Decision states in one world. `excluded`: withdrawn or vetoed records. `assumed`: unknown ancestry fixed."""
    records = {r["id"]: r for r in graph["evidence"]}
    claims = {c["id"]: c for c in graph["claims"]}
    usable, positive, negative = {}, {}, {}
    for ident in in_dependency_order(graph):
        if ident in records:
            record = records[ident]
            usable[ident] = (record["active"] and ident not in excluded and assumed.get(ident, True)
                             and all(usable[parent] for parent in record["parents"]))
        else:
            claim = claims[ident]
            positive[ident] = {w | {(ident, "positive")} for w in ways(claim["positive"], usable, positive)}
            negative[ident] = {w | {(ident, "negative")} for w in ways(claim["negative"], usable, positive)}
    concluded = {(c, "positive") for c in positive if positive[c]} | {(c, "negative") for c in negative if negative[c]}

    def attacked(way):
        return any((claim, FLIP[polarity]) in concluded for claim, polarity in way)

    state = {}
    for c in claims:
        if any(not attacked(w) for w in positive[c]):
            state[c] = "supported"
        elif any(attacked(w) for w in positive[c] | negative[c]):
            state[c] = "contested"
        else:
            state[c] = "not_supported"
    result = {}
    for decision in graph["decisions"]:
        states = [state[c] for c in decision["requires"]]
        result[decision["id"]] = ("not_supported" if "not_supported" in states else
                                  "contested" if "contested" in states else "supported")
    return result


def reading(graph, excluded=()):
    unknown = sorted(r["id"] for r in graph["evidence"] if r["kind"] == "unknown")
    worlds = [world(graph, set(excluded), dict(zip(unknown, bits))) for bits in product((False, True), repeat=len(unknown))]
    result = {}
    for decision in worlds[0]:
        states = sorted({w[decision] for w in worlds})
        result[decision] = {"state": states[0] if len(states) == 1 else "insufficient_provenance",
                            "box": states == ["supported"], "diamond": "supported" in states}
    return result


def family(graphs, excluded=()):
    rows = [reading(graph, excluded) for graph in graphs]
    return {d: {"box": all(row[d]["box"] for row in rows), "diamond": any(row[d]["diamond"] for row in rows)}
            for d in rows[0]}
