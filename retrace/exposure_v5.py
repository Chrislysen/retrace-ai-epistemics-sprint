"""Exact hypothetical eligibility changes exposing supplied graph disagreement.

This does not discover missing structures, change the factual source, or restore
ordinary withdrawals. Existing exclusions are locked false. An enable changes
an originally inactive local flag only in an explicitly hypothetical scenario.
The common baseline is required so every witness has one shared interpretation.
"""
from __future__ import annotations

import hashlib
import json

from .core import validate_case

MAX_CANDIDATES = 16
MAX_NODES = 250
MAX_CHANGES = 16
CATEGORIES = ("evidence", "claims", "decisions")
ASSUMPTION = "Hypothetical changes to local eligibility; not a source truth claim."


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _ids(value, allowed, name):
    _require(isinstance(value, list) and all(isinstance(x, str) and x for x in value),
             f"{name} must be an array of nonempty string IDs")
    _require(len(value) == len(set(value)), f"{name} contains duplicate IDs")
    _require(set(value) <= set(allowed), f"{name} contains an unknown or wrong-category ID")
    return sorted(value)


def _prepare(candidates):
    _require(isinstance(candidates, list) and 1 <= len(candidates) <= MAX_CANDIDATES,
             f"Supply 1 to {MAX_CANDIDATES} candidate graphs")
    prepared, seen, registry, initial = [], set(), None, None
    for item in candidates:
        _require(isinstance(item, dict), "Each candidate must be an object")
        cid, graph = item.get("id"), item.get("graph")
        _require(isinstance(cid, str) and bool(cid) and cid not in seen,
                 "Candidate IDs must be unique nonempty strings")
        seen.add(cid)
        _require(isinstance(graph, dict) and all(isinstance(graph.get(k), list) for k in CATEGORIES),
                 "Each graph needs evidence, claims and decisions arrays")
        _require(sum(len(graph[k]) for k in CATEGORIES) <= MAX_NODES,
                 f"Each graph may contain at most {MAX_NODES} nodes")
        _require(not graph.get("revoke"), "Pass exclusions as locked_exclusions; nonempty graph.revoke is not accepted")
        index = validate_case(graph)
        typed = {k: {r["id"] for r in graph[k]} for k in CATEGORIES}
        _require(registry is None or typed == registry, "Candidates must share the same IDs in each node category")
        flags = {r["id"]: r.get("active", True) for r in graph["evidence"]}
        _require(initial is None or flags == initial,
                 "Candidates must share original local active flags; baseline activity disagreement is unsupported")
        registry, initial = typed, flags
        categories = {r["id"]: k for k in CATEGORIES for r in graph[k]}
        order, visited = [], set()

        def visit(identifier):
            if identifier in visited:
                return
            row, kind = index[identifier], categories[identifier]
            refs = row.get("parents", []) if kind == "evidence" else (
                [ref for route in row["supports"] for ref in route] if kind == "claims" else row["requires"])
            for ref in sorted(set(refs)):
                visit(ref)
            visited.add(identifier)
            order.append(identifier)

        for identifier in sorted(index):
            visit(identifier)
        prepared.append({"id": cid, "graph": graph, "index": index, "categories": categories, "order": order})
    return sorted(prepared, key=lambda r: r["id"]), registry, initial


def _canonical(row):
    graph = row["graph"]
    return {"id": row["id"],
            "evidence": sorted((r["id"], r.get("label", r["id"]), r.get("kind", "root"),
                                r.get("active", True), sorted(r.get("parents", []))) for r in graph["evidence"]),
            "claims": sorted((r["id"], r.get("label", r["id"]), sorted(sorted(c) for c in r["supports"]))
                             for r in graph["claims"]),
            "decisions": sorted((r["id"], r.get("label", r["id"]), sorted(r["requires"]))
                                for r in graph["decisions"])}


def _evaluate(row, eligibility_bits, universe):
    values = {}
    for identifier in row["order"]:
        node, category = row["index"][identifier], row["categories"][identifier]
        if category == "evidence":
            result = eligibility_bits[identifier]
            for parent in node.get("parents", []):
                result &= values[parent]
        else:
            routes = node["supports"] if category == "claims" else [node["requires"]]
            result = 0
            for route in routes:
                clause = universe
                for ref in route:
                    clause &= values[ref]
                result |= clause
        values[identifier] = result
    return {r["id"]: values[r["id"]] for r in row["graph"]["decisions"]}


def audit_exposure(candidates, allowed_changes=None, locked_exclusions=None, target_decisions=None):
    """Enumerate exact final eligibility over at most sixteen unlocked records.

    Inputs are [{id, graph}, ...] with common typed IDs and original local flags.
    ``allowed_changes=None`` selects all evidence; an explicit list is exact.
    Locked IDs remain false, even when also listed as allowed, and do not count
    as changeable variables. Other fixed records retain their original flag.
    ``target_decisions=None`` selects every decision; [] selects no targets.
    Core's root/active/parents defaults are retained and included in the digest.
    No inputs are mutated. All costs count records, never probabilities/causes.
    """
    rows, registry, initial = _prepare(candidates)
    allowed = sorted(registry["evidence"]) if allowed_changes is None else _ids(
        allowed_changes, registry["evidence"], "allowed_changes")
    locked = [] if locked_exclusions is None else _ids(locked_exclusions, registry["evidence"], "locked_exclusions")
    targets = sorted(registry["decisions"]) if target_decisions is None else _ids(
        target_decisions, registry["decisions"], "target_decisions")
    variables = sorted(set(allowed) - set(locked))
    _require(len(variables) <= MAX_CHANGES,
             f"At most {MAX_CHANGES} unlocked evidence IDs may be changeable; choose an explicit bounded scope")
    states = 1 << len(variables)
    universe = (1 << states) - 1
    eligibility = {eid: universe if value and eid not in locked else 0 for eid, value in initial.items()}
    inactive_mask = 0
    for bit, eid in enumerate(variables):
        block = 1 << bit
        toggled = (universe // ((1 << block) + 1)) << block
        eligibility[eid] = universe ^ toggled if initial[eid] else toggled
        if not initial[eid]:
            inactive_mask |= 1 << bit
    active_mask = ((1 << len(variables)) - 1) ^ inactive_mask
    by_candidate = {row["id"]: _evaluate(row, eligibility, universe) for row in rows}
    groups = {}
    for assignment in range(states):
        counts = ((assignment & inactive_mask).bit_count(), (assignment & active_mask).bit_count())
        groups[counts] = groups.get(counts, 0) | (1 << assignment)
    group_counts = {pair: mask.bit_count() for pair, mask in groups.items()}
    global_total = [0] * (len(variables) + 1)
    for pair, count in group_counts.items():
        global_total[sum(pair)] += count
    candidate_ids = [row["id"] for row in rows]
    baseline = {cid: {did: bool(by_candidate[cid][did] & 1) for did in targets} for cid in candidate_ids}

    def witness(did, mask):
        assignment = (mask & -mask).bit_length() - 1
        changed = [eid for bit, eid in enumerate(variables) if assignment & (1 << bit)]
        enable = [eid for eid in changed if not initial[eid]]
        withdraw = [eid for eid in changed if initial[eid]]
        return {"enable": enable, "withdraw": withdraw, "enable_count": len(enable),
                "withdraw_count": len(withdraw), "total_changes": len(changed),
                "outcomes": {cid: bool(by_candidate[cid][did] & (1 << assignment)) for cid in candidate_ids},
                "assumption": ASSUMPTION}

    decisions = {}
    for did in targets:
        first = by_candidate[candidate_ids[0]][did]
        differences = 0
        for cid in candidate_ids[1:]:
            differences |= first ^ by_candidate[cid][did]
        counts = {pair: (mask & differences).bit_count() for pair, mask in groups.items()}
        nonzero = sorted((pair for pair, count in counts.items() if count), key=lambda p: (sum(p), p))
        minimum = witness(did, differences & groups[nonzero[0]]) if nonzero else None
        no_enabling = [pair for pair in nonzero if pair[0] == 0]
        minimum_plain = witness(did, differences & groups[no_enabling[0]]) if no_enabling else None
        pareto = sorted(p for p in nonzero
                        if not any(q != p and q[0] <= p[0] and q[1] <= p[1] for q in nonzero))
        frontier = [{"enable_count": p[0], "withdraw_count": p[1], "state_count": counts[p],
                     "witness": witness(did, differences & groups[p]),
                     "strictly_dominating_states_checked": sum(count for q, count in group_counts.items()
                                                               if q != p and q[0] <= p[0] and q[1] <= p[1]),
                     "strictly_dominating_distinguishing_states": 0} for p in pareto]
        total_hist = [0] * (len(variables) + 1)
        for pair, count in counts.items():
            total_hist[sum(pair)] += count
        minimum_count = minimum["total_changes"] if minimum else None
        decisions[did] = {
            "label": rows[0]["index"][did].get("label", did),
            "current_outcomes": {cid: baseline[cid][did] for cid in candidate_ids},
            "exposure_exists": bool(differences), "minimum": minimum,
            "minimum_without_enabling": minimum_plain, "frontier": frontier,
            "distinguishing_state_count": differences.bit_count(),
            "total_change_histogram": total_hist,
            "distinguishing_count_histogram": [{"enable_count": p[0], "withdraw_count": p[1], "state_count": counts[p]}
                                               for p in sorted(nonzero)],
            "minimality": {"exhaustive": True, "states_checked": states,
                           "minimum_total_changes": minimum_count,
                           "states_with_fewer_changes": sum(global_total[:minimum_count]) if minimum_count is not None else None,
                           "distinguishing_states_with_fewer_changes": 0 if minimum else None,
                           "withdrawal_only_states_checked": 1 << active_mask.bit_count(),
                           "withdrawal_only_distinguishing_states": sum(count for p, count in counts.items() if p[0] == 0),
                           "no_exposure_within_declared_scope": not bool(differences)},
        }
    digest_input = {"schema": "retrace.exposure.v5", "candidates": [_canonical(row) for row in rows],
                    "allowed_changes": allowed, "locked_exclusions": locked, "targets": targets}
    fingerprint = hashlib.sha256(json.dumps(digest_input, sort_keys=True, separators=(",", ":"),
                                            ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()
    return {
        "schema": "retrace.exposure.v5", "status": "hypothetical_source_amendment_audit",
        "input_fingerprint": fingerprint, "candidate_ids": candidate_ids, "target_decisions": targets,
        "baseline_outcomes": baseline, "decisions": decisions,
        "coverage": {"allowed_changes": allowed, "changeable_evidence_ids": variables,
                     "locked_exclusions": locked, "allowed_but_locked_ids": sorted(set(allowed) & set(locked)),
                     "fixed_evidence_ids": sorted(registry["evidence"] - set(variables)),
                     "originally_inactive_changeable_ids": [eid for eid in variables if not initial[eid]],
                     "originally_active_changeable_ids": [eid for eid in variables if initial[eid]],
                     "variables_count": len(variables), "states_checked_per_candidate": states,
                     "candidate_state_combinations": states * len(rows), "exhaustive_within_scope": True,
                     "state_count_histogram": [{"enable_count": p[0], "withdraw_count": p[1], "state_count": group_counts[p]}
                                               for p in sorted(groups)],
                     "total_change_state_histogram": global_total,
                     "candidate_completeness": "unknown"},
        "scope": [
            ASSUMPTION,
            "Existing document, passage and scenario vetoes must be supplied as locked_exclusions and remain false in every state.",
            "Enabling an inactive copy changes its local flag only; every declared parent must still be usable.",
            "The candidate graphs and common baseline flags are supplied assumptions. The audit cannot discover omitted structure or certify source fidelity.",
            "Witnesses expose disagreement among supplied graphs; they do not identify which graph is true or automatically insert an evaluation reference.",
            "Minimality is exact over the stated unlocked record IDs, counting enables and withdrawals separately; it is not a claim about causes, probabilities or human review cost.",
            "No witness means observational equivalence only within this eligibility-change scope, not structural equality or coverage completeness.",
            "Ties use minimum total changes, then fewer enables, then fewer withdrawals, then lowest binary assignment index in sorted record order.",
            "No factual input, evidence flag, candidate, or existing withdrawal state is mutated.",
        ],
    }
