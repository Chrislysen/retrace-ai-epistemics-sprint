"""Bounded support under supplied candidate graphs and exact clarification.

Candidate graphs and factual question answers are trusted declarations. This
module does not infer a complete candidate set, probabilities, or source truth.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

from .core import analyze, validate_case


CATEGORIES = ("evidence", "claims", "decisions")
MAX_CANDIDATES = 32
MAX_QUESTIONS = 5
MAX_NODES = 250


def _canonical(graph: dict) -> dict:
    return {
        "evidence": sorted((row["id"], row.get("kind", "root"), row.get("active", True),
                            sorted(row.get("parents", []))) for row in graph["evidence"]),
        "claims": sorted((row["id"], sorted({tuple(sorted(clause)) for clause in row["supports"]}))
                         for row in graph["claims"]),
        "decisions": sorted((row["id"], sorted(row["requires"])) for row in graph["decisions"]),
    }


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def _candidates(candidates: list[dict]) -> list[dict]:
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise ValueError(f"Supply between 1 and {MAX_CANDIDATES} candidate graphs")
    ids = set()
    category_ids = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Each candidate must be an object with id and graph")
        identifier = candidate.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError("Candidate IDs must be unique nonempty strings")
        ids.add(identifier)
        graph = candidate.get("graph")
        if isinstance(graph, dict) and graph.get("revoke"):
            raise ValueError("encode current active flags first: nonempty graph.revoke is not accepted")
        if (isinstance(graph, dict) and all(isinstance(graph.get(category), list) for category in CATEGORIES)
                and sum(len(graph[category]) for category in CATEGORIES) > MAX_NODES):
            raise ValueError(f"Each graph may contain at most {MAX_NODES} nodes")
        index = validate_case(graph)
        if len(index) > MAX_NODES:
            raise ValueError(f"Each graph may contain at most {MAX_NODES} nodes")
        this_ids = {category: {row["id"] for row in graph[category]} for category in CATEGORIES}
        if category_ids is not None and this_ids != category_ids:
            raise ValueError("Candidate graphs must have the same IDs in each node category")
        category_ids = this_ids
    return sorted(candidates, key=lambda row: row["id"])


def candidate_set_fingerprint(candidates: list[dict]) -> str:
    """Bind candidate identities, rules and current local eligibility.

    Labels, list order and duplicate equivalent support clauses are ignored.
    This fingerprint does not bind external document contents or source truth.
    """
    return _digest([{ "id": row["id"], "graph": _canonical(row["graph"]) }
                    for row in _candidates(candidates)])


def analyze_uncertainty(candidates: list[dict], questions: list[dict] | None = None,
                        target_decisions: list[str] | None = None) -> dict:
    """Evaluate support and find a minimum worst-case-cost clarification tree.

    ``candidates`` is [{"id": str, "graph": final_graph}, ...]. Graphs must
    share node-category IDs, but may disagree on kinds, parents, rules and flags.
    Current eligibility must already be in ``active``; nonempty revoke metadata
    is rejected to avoid silently evaluating an event's initial graph.

    ``questions`` is [{"id": str, "label": str, "cost": positive_int,
    "answers": {candidate_id: bool, ...}}, ...]. Labels and costs are declared,
    not estimated; omitted cost defaults to one unit. Every question must supply an authoritative yes/no answer for
    every candidate. Missing/unknown answers are rejected, never guessed.

    The exact minimax tree stops as soon as all remaining candidates agree on
    the target decision vector, not when the entire graph is identified. Costs
    add along a path; no prior probabilities or candidate-count confidence are
    assumed. Equal-cost choices use lexicographic question-ID order.
    """
    rows = _candidates(candidates)
    ids = [row["id"] for row in rows]
    decision_ids = sorted(node["id"] for node in rows[0]["graph"]["decisions"])
    if target_decisions is None:
        targets = decision_ids
    elif (not isinstance(target_decisions, list)
          or any(not isinstance(item, str) or item not in decision_ids for item in target_decisions)
          or len(target_decisions) != len(set(target_decisions))):
        raise ValueError("target_decisions must contain distinct existing decision IDs")
    else:
        targets = sorted(target_decisions)

    questions = [] if questions is None else questions
    if not isinstance(questions, list) or len(questions) > MAX_QUESTIONS:
        raise ValueError(f"Supply at most {MAX_QUESTIONS} questions")
    normalized_questions = []
    seen_questions = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Questions must be objects")
        identifier = question.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen_questions:
            raise ValueError("Question IDs must be unique nonempty strings")
        seen_questions.add(identifier)
        label, cost, answers = question.get("label"), question.get("cost", 1), question.get("answers")
        if not isinstance(label, str) or not label:
            raise ValueError("Each question needs a nonempty factual label")
        if type(cost) is not int or cost <= 0:
            raise ValueError("Question costs must be positive integers")
        if (not isinstance(answers, dict) or set(answers) != set(ids)
                or any(type(value) is not bool for value in answers.values())):
            raise ValueError("Each question needs an explicit boolean answer for every candidate")
        normalized_questions.append({"id": identifier, "label": label, "cost": cost,
                                     "answers": {cid: answers[cid] for cid in ids}})
    normalized_questions.sort(key=lambda row: row["id"])

    vectors = {}
    for row in rows:
        snapshot = analyze(row["graph"])
        vectors[row["id"]] = {did: snapshot["decisions"][did]["usable"] for did in decision_ids}
    states = {}
    for did in decision_ids:
        supporting = [cid for cid in ids if vectors[cid][did]]
        unsupported = [cid for cid in ids if not vectors[cid][did]]
        states[did] = {
            "state": "robust_supported" if not unsupported else "robust_unsupported" if not supporting else "needs_review",
            "supporting_candidates": supporting,
            "unsupported_candidates": unsupported,
            "conflicting_witnesses": {"supported": supporting[0], "unsupported": unsupported[0]}
                                     if supporting and unsupported else None,
        }

    signatures = [tuple(vectors[cid][did] for did in targets) for cid in ids]
    full_mask = (1 << len(ids)) - 1
    yes_masks = [sum(1 << index for index, cid in enumerate(ids) if question["answers"][cid])
                 for question in normalized_questions]

    def members(mask: int) -> list[int]:
        return [index for index in range(len(ids)) if mask & (1 << index)]

    def agreed(mask: int) -> bool:
        return len({signatures[index] for index in members(mask)}) <= 1

    @lru_cache(maxsize=None)
    def solve(mask: int) -> tuple[int | None, int | None]:
        if agreed(mask):
            return 0, None
        best_cost = best_question = None
        for index, question in enumerate(normalized_questions):
            yes, no = mask & yes_masks[index], mask & ~yes_masks[index]
            if not yes or not no:
                continue
            yes_cost, _ = solve(yes)
            no_cost, _ = solve(no)
            if yes_cost is None or no_cost is None:
                continue
            cost = question["cost"] + max(yes_cost, no_cost)
            if best_cost is None or cost < best_cost:
                best_cost, best_question = cost, index
        return best_cost, best_question

    def tree(mask: int) -> dict:
        cost, index = solve(mask)
        remaining = [ids[item] for item in members(mask)]
        if index is None:
            return {"kind": "decision_agreement", "remaining_candidates": remaining,
                    "decisions": {did: vectors[remaining[0]][did] for did in targets},
                    "worst_case_cost": 0}
        question = normalized_questions[index]
        return {"kind": "question", "question_id": question["id"], "label": question["label"],
                "cost": question["cost"], "worst_case_cost": cost, "remaining_candidates": remaining,
                "branches": {"yes": tree(mask & yes_masks[index]), "no": tree(mask & ~yes_masks[index])}}

    minimum_cost, _ = solve(full_mask)
    blocking_pairs = [
        {"candidate_ids": [ids[left], ids[right]],
         "differing_target_decisions": [did for did in targets if vectors[ids[left]][did] != vectors[ids[right]][did]]}
        for left in range(len(ids)) for right in range(left + 1, len(ids))
        if signatures[left] != signatures[right]
        and all(question["answers"][ids[left]] == question["answers"][ids[right]] for question in normalized_questions)
    ]
    fingerprint = candidate_set_fingerprint(rows)
    return {
        "schema_version": "retrace.uncertainty.v6c",
        "candidate_set_fingerprint": fingerprint,
        "analysis_fingerprint": _digest({"candidate_set": fingerprint, "targets": targets,
                                         "questions": normalized_questions}),
        "candidate_ids": ids,
        "candidate_decision_vectors": vectors,
        "decision_states": states,
        "target_decisions": targets,
        "clarification": {"possible": minimum_cost is not None, "worst_case_cost": minimum_cost,
                          "tree": tree(full_mask) if minimum_cost is not None else None,
                          "blocking_pairs": blocking_pairs, "states_evaluated": solve.cache_info().currsize},
        "scope": [
            "Support states quantify only over the explicitly supplied candidate graphs, not all plausible graphs or real-world truth.",
            "Candidate completeness and factual question labels are trusted inputs; systematic shared omissions can create false reassurance.",
            "No probabilities, statistical independence, calibrated confidence, or expected information value are inferred from candidate counts.",
            "Clarification minimizes additive worst-case declared integer cost until the target decision vector agrees; it need not identify the graph.",
            "Questions are assumed answerable, accurate, fixed and noninterventional. Unknown answers must retain uncertainty; inconsistent answers require re-opening the candidate set.",
            "Compare candidate_set_fingerprint before reusing support certificates; rule, eligibility, candidate membership or identity changes invalidate them.",
            "The fingerprint excludes labels and external documents; external source changes require explicit graph or candidate revision.",
            "Graphs must encode current local active flags; nonempty revoke metadata is rejected. Only positive acyclic declared support is modeled.",
        ],
    }
