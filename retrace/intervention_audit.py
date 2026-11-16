"""Exact bounded comparison across EVERY allowed withdrawal combination.

Boolean truth-table bitsets implement standard exhaustive model checking. This
is not a new inference algorithm, source verification, or a proof outside the
declared graph/candidate/intervention universe. No LLM calls are made.
"""
from itertools import combinations

from .core import validate_case

MAX_VARIABLES = 16


def _table(graph, variables):
    index = validate_case(graph)
    category = {r["id"]: k for k in ("evidence", "claims", "decisions") for r in graph[k]}
    states = 1 << len(variables)
    universe = (1 << states) - 1
    masks = {}
    for position, name in enumerate(variables):
        width = 1 << position
        # Bit s is one exactly when evidence name is NOT withdrawn in state s.
        block = (1 << width) - 1
        masks[name] = sum(block << offset for offset in range(0, states, 2 * width))
    values = {}

    def conjunction(refs):
        value = universe
        for ref in refs:
            value &= visit(ref)
        return value

    def visit(name):
        if name in values:
            return values[name]
        record = index[name]
        if category[name] == "evidence":
            value = masks.get(name, universe) if record.get("active", True) else 0
            if record.get("kind", "root") == "copy":
                value &= conjunction(record["parents"])
        elif category[name] == "claims":
            value = 0
            for clause in record["supports"]:
                value |= conjunction(clause)
        else:
            value = conjunction(record["requires"])
        values[name] = value
        return value

    return {r["id"]: visit(r["id"]) for r in graph["decisions"]}


def audit_interventions(graphs, allowed_withdrawals=None):
    """Compare 2–16 named candidates over all subsets of selected evidence IDs.

    Graph-local activity remains fixed; a withdrawal only removes support. This
    never restores originally inactive evidence. Default permits withdrawals of
    all evidence records. Missing coverage is explicit via fixed evidence IDs.
    """
    if not isinstance(graphs, dict) or not 2 <= len(graphs) <= 16:
        raise ValueError("Supply 2 to 16 named candidate graphs")
    if any(not isinstance(k, str) or not k for k in graphs):
        raise ValueError("Candidate names must be nonempty strings")
    for graph in graphs.values():
        if not isinstance(graph, dict) or any(not isinstance(graph.get(k), list) for k in ("evidence", "claims", "decisions")):
            raise ValueError("Candidates must contain graph category arrays")
        if sum(len(graph[k]) for k in ("evidence", "claims", "decisions")) > 250:
            raise ValueError("Candidate graph exceeds the 250-node limit")
        if graph.get("revoke"):
            raise ValueError("Encode current active flags first; nonempty revoke metadata is not accepted")
        validate_case(graph)
    first = next(iter(graphs.values()))
    registry = {k: {r["id"] for r in first[k]} for k in ("evidence", "claims", "decisions")}
    if any(any({r["id"] for r in graph[k]} != registry[k] for k in registry) for graph in graphs.values()):
        raise ValueError("Candidate typed IDs must match")
    variables = sorted(registry["evidence"]) if allowed_withdrawals is None else allowed_withdrawals
    if (not isinstance(variables, list) or any(not isinstance(v, str) for v in variables)
            or len(variables) != len(set(variables)) or not set(variables) <= registry["evidence"]):
        raise ValueError("Allowed withdrawals must be unique existing evidence IDs")
    if len(variables) > MAX_VARIABLES:
        raise ValueError("Exhaustive audit supports at most 16 independently withdrawable records; narrow the declared scope explicitly")
    variables = sorted(variables)
    tables = {name: _table(graph, variables) for name, graph in graphs.items()}
    decisions = {}
    for decision in sorted(registry["decisions"]):
        disagreement = 0
        base = next(iter(tables.values()))[decision]
        for table in tables.values():
            disagreement |= base ^ table[decision]
        witness = None
        if disagreement:
            for count in range(len(variables) + 1):
                found = False
                for positions in combinations(range(len(variables)), count):
                    state = sum(1 << p for p in positions)
                    if (disagreement >> state) & 1:
                        witness = {"withdraw": [variables[p] for p in positions],
                                   "outcomes": {name: bool((table[decision] >> state) & 1) for name, table in tables.items()}}
                        found = True
                        break
                if found:
                    break
        decisions[decision] = {
            "equivalent_within_scope": disagreement == 0,
            "disagreement_state_count": disagreement.bit_count(),
            "current_outcomes": {name: bool(table[decision] & 1) for name, table in tables.items()},
            "minimum_withdrawal_witness": witness,
        }
    return {"schema": "retrace.intervention-audit.v1", "candidate_count": len(graphs),
            "allowed_withdrawals": variables, "fixed_evidence_ids": sorted(registry["evidence"] - set(variables)),
            "states_checked_per_candidate": 1 << len(variables),
            "all_decisions_equivalent_within_scope": all(r["equivalent_within_scope"] for r in decisions.values()),
            "decisions": decisions,
            "scope": "Exhaustive only over the declared candidates and allowed withdrawal subsets. No source truth, candidate completeness, restoration or unseen-graph guarantee."}
