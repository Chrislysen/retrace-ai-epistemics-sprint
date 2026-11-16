"""Exact pairwise common-cause withdrawal checks over supplied effective graphs.

An available common ancestor does not change the current truth of a positive
support graph: replace two available roots by available copies of that ancestor;
both still evaluate true, and induction through the DAG preserves every result.
This module therefore does NOT claim a dependency merge breaks support. It asks
the additional, explicitly hypothetical question: what if a shared ancestor
were unavailable, thereby excluding both currently supporting roots?

The input candidate set and any independence attestations are trusted supplied
declarations, not authenticated sources, statistical evidence or probabilities.
No candidate, source fact, hidden ancestor or graph mutation is produced.
"""
from __future__ import annotations

from itertools import combinations

from .core import validate_case

MAX_CANDIDATES = 16
MAX_NODES = 250
CATEGORIES = ("evidence", "claims", "decisions")
WARNING_LABEL = "Coverage Warning: Relies on Unverified Root Independence"
ASSUMPTION = "hypothetical shared ancestor is unavailable/withdrawn"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _prepare(candidates):
    _require(isinstance(candidates, list) and 1 <= len(candidates) <= MAX_CANDIDATES,
             f"Supply 1 to {MAX_CANDIDATES} candidate graphs")
    prepared, candidate_ids, registry = [], set(), None
    for candidate in candidates:
        _require(isinstance(candidate, dict), "Each candidate must be an object")
        cid = candidate.get("id")
        _require(isinstance(cid, str) and bool(cid) and cid not in candidate_ids,
                 "Candidate IDs must be unique nonempty strings")
        candidate_ids.add(cid)
        graph = candidate.get("graph")
        _require(isinstance(graph, dict) and all(isinstance(graph.get(k), list) for k in CATEGORIES),
                 "Each candidate needs evidence, claims and decisions arrays")
        _require(sum(len(graph[k]) for k in CATEGORIES) <= MAX_NODES,
                 f"Each candidate may contain at most {MAX_NODES} nodes")
        _require(not graph.get("revoke"), "Encode current effective active flags first; nonempty revoke metadata is not accepted")
        index = validate_case(graph)
        typed_ids = {k: {row["id"] for row in graph[k]} for k in CATEGORIES}
        _require(registry is None or typed_ids == registry, "Candidate graphs must share the same IDs in each node category")
        registry = typed_ids
        categories = {row["id"]: k for k in CATEGORIES for row in graph[k]}
        dependencies = {}
        for name, row in index.items():
            category = categories[name]
            dependencies[name] = set(row.get("parents", [])) if category == "evidence" else (
                {ref for route in row["supports"] for ref in route} if category == "claims" else set(row["requires"]))
        remaining, resolved, order = set(index), set(), []
        while remaining:
            ready = sorted(name for name in remaining if dependencies[name] <= resolved)
            _require(bool(ready), "Candidate graph contains a dependency cycle")
            order.extend(ready)
            resolved.update(ready)
            remaining.difference_update(ready)
        # A small scalar pass tracks ONLY roots of currently successful routes.
        # Inactive paths, copies and roots of failed alternative clauses do not
        # enter the supporting-root pair universe.
        baseline, supporting = {}, {}
        for name in order:
            row, category = index[name], categories[name]
            if category == "evidence" and row.get("kind", "root") == "root":
                usable = row.get("active", True)
                roots = {name} if usable else set()
            else:
                routes = ([row.get("parents", [])] if category == "evidence" else
                          row["supports"] if category == "claims" else [row["requires"]])
                successful = [route for route in routes if all(baseline[ref] for ref in route)]
                usable = bool(successful) and (category != "evidence" or row.get("active", True))
                roots = {root for route in successful for ref in route for root in supporting[ref]} if usable else set()
            baseline[name], supporting[name] = bool(usable), roots
        prepared.append({"id": cid, "graph": graph, "index": index, "categories": categories,
                         "order": order, "baseline": baseline, "supporting": supporting,
                         "root_ids": {r["id"] for r in graph["evidence"] if r.get("kind", "root") == "root"}})
    return sorted(prepared, key=lambda item: item["id"]), registry


def _attestations(value, candidates):
    if value is None:
        value = []
    _require(isinstance(value, list), "verified_independence must be an array of source-supplied attestations")
    by_id = {row["id"]: row for row in candidates}
    _require(len(value) <= len(candidates) * MAX_NODES * (MAX_NODES - 1) // 2, "Too many independence attestations")
    covered, normalized = set(), []
    for row in value:
        _require(isinstance(row, dict) and {"roots", "basis"} <= set(row)
                 and set(row) <= {"roots", "basis", "candidate_ids"}, "Attestations need roots, basis and optional candidate_ids only")
        roots = row["roots"]
        _require(isinstance(roots, list) and len(roots) == 2
                 and all(isinstance(root, str) and root for root in roots) and roots[0] != roots[1],
                 "An independence attestation needs two distinct root IDs")
        _require(isinstance(row["basis"], str) and bool(row["basis"].strip()), "Independence basis must be nonempty provenance evidence")
        ids = row.get("candidate_ids", sorted(by_id))
        _require(isinstance(ids, list) and bool(ids) and all(isinstance(cid, str) and cid in by_id for cid in ids)
                 and len(ids) == len(set(ids)), "Attestation candidate_ids must be distinct existing candidate IDs")
        pair = tuple(sorted(roots))
        for cid in ids:
            _require(set(pair) <= by_id[cid]["root_ids"], "Attestation IDs must be root evidence in every scoped candidate")
            key = (cid, pair)
            _require(key not in covered, "Repeated or conflicting attestations overlap on the same root pair and candidate")
            covered.add(key)
        normalized.append({"roots": list(pair), "basis": row["basis"], "candidate_ids": sorted(ids)})
    normalized.sort(key=lambda row: (row["roots"], row["candidate_ids"]))
    return covered, normalized


class _PairBasis:
    """Baseline, all singles and all unordered pairs; no 2**root_count table."""

    def __init__(self, root_ids):
        self.roots = sorted(root_ids)
        self.positions = {root: i for i, root in enumerate(self.roots)}
        n = len(self.roots)
        self.size = 1 + n + n * (n - 1) // 2
        self.universe = (1 << self.size) - 1
        width = (self.size + 7) // 8
        excluded = [bytearray(width) for _ in self.roots]
        self.pair_at = [None] * (1 + n)
        for i in range(n):
            bit = i + 1
            excluded[i][bit >> 3] |= 1 << (bit & 7)
        for bit, (i, j) in enumerate(combinations(range(n), 2), start=1 + n):
            self.pair_at.append((self.roots[i], self.roots[j]))
            for position in (i, j):
                excluded[position][bit >> 3] |= 1 << (bit & 7)
        self.available = {root: self.universe ^ int.from_bytes(excluded[i], "little") for i, root in enumerate(self.roots)}
        self._cache = {}

    def pair_index(self, pair):
        i, j = sorted(self.positions[root] for root in pair)
        n = len(self.roots)
        return 1 + n + i * (2 * n - i - 1) // 2 + j - i - 1

    def pairs(self, roots):
        key = tuple(sorted(roots))
        if key not in self._cache:
            data = bytearray((self.size + 7) // 8)
            for pair in combinations(key, 2):
                bit = self.pair_index(pair)
                data[bit >> 3] |= 1 << (bit & 7)
            self._cache[key] = int.from_bytes(data, "little")
        return self._cache[key]

    def first_pair(self, mask):
        bit = (mask & -mask).bit_length() - 1
        return self.pair_at[bit]


def _decision_tables(candidate, basis):
    values = {}

    def conjunction(refs):
        value = basis.universe
        for ref in refs:
            value &= values[ref]
        return value

    for name in candidate["order"]:
        row, category = candidate["index"][name], candidate["categories"][name]
        if category == "evidence":
            value = basis.available.get(name, basis.universe) if row.get("active", True) else 0
            if row.get("kind", "root") == "copy":
                value &= conjunction(row["parents"])
        elif category == "claims":
            value = 0
            for route in row["supports"]:
                value |= conjunction(route)
        else:
            value = conjunction(row["requires"])
        values[name] = value
    return {row["id"]: values[row["id"]] for row in candidate["graph"]["decisions"]}


def analyze_root_coverage(candidates, verified_independence=None):
    """Check every un-attested supporting-root pair of invariant decisions.

    ``candidates``: 1–16 {id, graph} objects, at most250 nodes per graph, same
    typed IDs. Graphs must already encode current effective local active flags.
    Core root/active/parents defaults are accepted; nonempty revoke metadata is
    rejected. No caller-owned input is modified.

    ``verified_independence``: [{roots:[a,b], basis:nonempty_source_text,
    candidate_ids?:[ids]}]. An omitted scope means all supplied candidates.
    These are trusted attestations supplied by the caller, not verification by
    RETRACE. Overlapping attestations of the same pair/candidate are rejected.

    Counts cover all eligible pair/candidate occurrences exactly. A bounded
    deterministic witness is returned for every affected candidate, plus a
    joint-only failure witness when the first witness already fails singly.
    No-warning is only a result about un-attested pair withdrawals in this
    declared universe; it never establishes root independence or completeness.
    """
    rows, registry = _prepare(candidates)
    attested, declarations = _attestations(verified_independence, rows)
    decision_ids = sorted(registry["decisions"])
    invariant = {did for did in decision_ids if all(row["baseline"][did] for row in rows)}
    relevant_roots = {root for row in rows for did in invariant for root in row["supporting"][did]}
    basis = _PairBasis(relevant_roots)
    tables = {row["id"]: _decision_tables(row, basis) for row in rows}
    attested_masks = {row["id"]: 0 for row in rows}
    for cid, pair in attested:
        if set(pair) <= relevant_roots:
            attested_masks[cid] |= 1 << basis.pair_index(pair)

    def witness(cid, did, pair):
        table = tables[cid][did]
        singles = {root: bool(table & (1 << (basis.positions[root] + 1))) for root in pair}
        joint = bool(table & (1 << basis.pair_index(pair)))
        return {"candidate_id": cid, "roots": list(pair), "original_support": bool(table & 1),
                "single_withdrawal_support": singles, "joint_withdrawal_support": joint,
                "pair_only_failure": all(singles.values()) and not joint,
                "single_failure_already_present": not all(singles.values()),
                "assumption": ASSUMPTION, "merge_only_changes_current_support": False,
                "interpretation": "One hypothetical unavailable common cause excludes two records; neither its existence nor its unavailability is asserted."}

    decisions = {}
    total_occurrences = total_tested = total_exempted = total_failures = total_joint_only = 0
    for did in decision_ids:
        current = {row["id"]: row["baseline"][did] for row in rows}
        counts = {key: 0 for key in ("eligible_candidate_pairs", "attested_candidate_pairs", "tested_candidate_pairs",
                                     "joint_failure_candidate_pairs", "joint_only_failure_candidate_pairs",
                                     "single_failure_already_present_candidate_pairs", "nonbreaking_candidate_pairs")}
        eligible_union = tested_union = failure_union = 0
        examples, candidate_counts = [], {}
        supporting = {row["id"]: sorted(row["supporting"][did]) for row in rows}
        if did in invariant:
            for row in rows:
                cid, roots, table = row["id"], supporting[row["id"]], tables[row["id"]][did]
                _require(bool(table & 1) == current[cid], "Scalar and bitset baseline disagree")
                eligible = basis.pairs(roots)
                exempted = eligible & attested_masks[cid]
                tested = eligible & ~attested_masks[cid]
                failures = tested & (basis.universe ^ table)
                safe_singles = [root for root in roots if table & (1 << (basis.positions[root] + 1))]
                joint_only = failures & basis.pairs(safe_singles)
                per_candidate = {
                    "eligible_candidate_pairs": eligible.bit_count(), "attested_candidate_pairs": exempted.bit_count(),
                    "tested_candidate_pairs": tested.bit_count(), "joint_failure_candidate_pairs": failures.bit_count(),
                    "joint_only_failure_candidate_pairs": joint_only.bit_count(),
                    "single_failure_already_present_candidate_pairs": (failures ^ joint_only).bit_count(),
                    "nonbreaking_candidate_pairs": (tested ^ failures).bit_count(),
                }
                candidate_counts[cid] = per_candidate
                for key, value in per_candidate.items():
                    counts[key] += value
                eligible_union |= eligible
                tested_union |= tested
                failure_union |= failures
                if failures:
                    first = basis.first_pair(failures)
                    examples.append(witness(cid, did, first))
                    if joint_only and not examples[-1]["pair_only_failure"]:
                        examples.append(witness(cid, did, basis.first_pair(joint_only)))
        counts.update(distinct_eligible_root_pairs=eligible_union.bit_count(),
                      distinct_tested_root_pairs=tested_union.bit_count(),
                      distinct_failing_root_pairs=failure_union.bit_count())
        warning = bool(failure_union)
        decisions[did] = {"label": rows[0]["index"][did].get("label", did), "current_outcomes": current,
                          "applicable": did in invariant, "inapplicable_reason": None if did in invariant else "Decision is not supported by every retained candidate",
                          "warning": warning, "warning_label": WARNING_LABEL if warning else None,
                          "currently_supporting_root_ids": supporting, "pair_counts": counts,
                          "candidate_pair_counts": candidate_counts, "witnesses": examples,
                          "witness_policy": "Deterministic first failing pair per affected candidate; also first joint-only pair when not already represented. Counts remain exhaustive."}
        total_occurrences += counts["eligible_candidate_pairs"]
        total_tested += counts["tested_candidate_pairs"]
        total_exempted += counts["attested_candidate_pairs"]
        total_failures += counts["joint_failure_candidate_pairs"]
        total_joint_only += counts["joint_only_failure_candidate_pairs"]
    any_warning = any(row["warning"] for row in decisions.values())
    return {"schema": "retrace.root-coverage.v4", "warning": any_warning,
            "warning_label": WARNING_LABEL if any_warning else None,
            "merge_only_changes_current_support": False, "assumption": ASSUMPTION,
            "candidate_ids": [row["id"] for row in rows], "decisions": decisions,
            "attestations": declarations,
            "attestation_status": "Caller-supplied provenance declarations, not statistical independence authenticated by RETRACE.",
            "coverage": {"candidate_count": len(rows), "node_limit_per_candidate": MAX_NODES,
                         "decision_count": len(decision_ids), "applicable_decision_count": len(invariant),
                         "supporting_root_ids_in_basis": basis.roots, "basis_state_count": basis.size,
                         "basis_semantics": "Current state plus all single and unordered pair withdrawals of the union of currently supporting roots. Only candidate-specific supporting root pairs count as eligible.",
                         "eligible_decision_candidate_pairs": total_occurrences, "tested_decision_candidate_pairs": total_tested,
                         "attested_decision_candidate_pairs": total_exempted, "failing_decision_candidate_pairs": total_failures,
                         "joint_only_failing_decision_candidate_pairs": total_joint_only,
                         "all_eligible_pairs_checked": True, "root_truncation": False,
                         "candidate_completeness": "unknown", "higher_order_common_causes": "not tested"},
            "assumptions": [
                "Inputs are already filtered retained candidates with effective local eligibility encoded in active flags.",
                "An available common ancestor leaves two available roots true and therefore preserves all current positive-DAG support by induction. A pure merge is not a withdrawal.",
                "Every warning additionally assumes a hypothetical shared ancestor is unavailable/withdrawn and consequently excludes both named roots. This is a counterfactual vulnerability, not an asserted source fact.",
                "The exact envelope considers pairs of distinct root IDs on currently successful support routes, never copies or roots of inactive/failed routes.",
                "Warnings include AND-style cases in which a single withdrawal already breaks support; pair_only_failure separately identifies the loss of protection against individual record withdrawal.",
                "Attestations exempt their exact candidate/root pairs using trusted supplied provenance. They do not establish probabilistic independence, authenticate evidence or imply that larger groups are independent.",
                "No warning means no un-attested pair withdrawal breaks an applicable decision within these graphs. It does not verify independence, cover three-or-more-root common causes, or establish complete candidate coverage.",
                "Witnesses illustrate exact failure states but do not insert new ancestors/candidates, mutate the input graphs, infer probabilities or change current support labels.",
            ]}
