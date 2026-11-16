"""Post-hoc, offline review of an extracted graph against an authored reference.

This module does not change the frozen experiment scorer. It finds concrete
decision-level consequences of graph differences under bounded interventions;
it does not establish source truth or supply a confidence estimate.
"""

from __future__ import annotations

import copy
import itertools
import math
from typing import Any

from .core import analyze, validate_case


CATEGORIES = ("evidence", "claims", "decisions")
MAX_EVIDENCE = 24


def _canonical(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize ordering and labels, retaining local flags and AND/OR groups."""
    return {
        "evidence": {
            row["id"]: {
                "kind": row.get("kind", "root"),
                "active": row.get("active", True),
                "parents": sorted(row.get("parents", [])),
            }
            for row in sorted(graph["evidence"], key=lambda row: row["id"])
        },
        "claims": {
            row["id"]: {
                "supports": [list(clause) for clause in sorted({
                    tuple(sorted(clause)) for clause in row["supports"]
                })]
            }
            for row in sorted(graph["claims"], key=lambda row: row["id"])
        },
        "decisions": {
            row["id"]: {"requires": sorted(row["requires"])}
            for row in sorted(graph["decisions"], key=lambda row: row["id"])
        },
    }


def _compare(reference: dict, predicted: dict) -> dict:
    reference_decisions = {
        identifier: reference["decisions"][identifier]["usable"]
        for identifier in sorted(reference["decisions"])
    }
    predicted_decisions = {
        identifier: predicted["decisions"][identifier]["usable"]
        for identifier in sorted(predicted["decisions"])
    }
    differing = [identifier for identifier, value in reference_decisions.items()
                 if value != predicted_decisions[identifier]]
    return {
        "agreement": not differing,
        "matching_decisions": len(reference_decisions) - len(differing),
        "total_decisions": len(reference_decisions),
        "reference_decisions": reference_decisions,
        "predicted_decisions": predicted_decisions,
        "differing_decisions": differing,
        "node_usability_differences": [
            {"id": identifier, "category": category,
             "reference_usable": reference[category][identifier]["usable"],
             "predicted_usable": predicted[category][identifier]["usable"]}
            for category in CATEGORIES
            for identifier in sorted(reference[category])
            if reference[category][identifier]["usable"] != predicted[category][identifier]["usable"]
        ],
    }


def _intervene(graph: dict, interventions: tuple[dict, ...]) -> dict:
    result = copy.deepcopy(graph)
    evidence = {row["id"]: row for row in result["evidence"]}
    for intervention in interventions:
        # An authoritative action sets the SAME flag in both graphs. It is not
        # a graph-relative XOR, and it never changes a root/copy classification.
        evidence[intervention["id"]]["active"] = intervention["active"]
    return result


def review_graphs(reference: dict, predicted: dict, max_interventions: int = 2) -> dict:
    """Compare valid, same-category-ID graphs and find a minimal witness.

    Inputs are current/final graphs whose evidence ``active`` flags already
    encode the event. As in ``analyze(graph)``, ``revoke`` metadata is ignored.
    Inputs are never mutated. Labels and list order are ignored in structural
    comparison; support-clause grouping and supplied root/copy types are kept.

    Each evidence ID has one action determined by its reference local flag:
    withdraw if active, restore if inactive. The action sets the same local flag
    in both graphs, even if their starting flags differ. All subsets of these
    actions of sizes 1 through ``max_interventions`` (0, 1 or 2) are evaluated.
    A restored record may still be unusable through an unavailable parent.

    The witness is the first divergent decision vector in cardinality then
    lexicographic ID order; cardinality 0 identifies an existing disagreement.
    Search continues after finding it, so counts cover the complete bound.
    Restoring an initially unavailable record is hypothetical, not a claim that
    it was withdrawn or that it should be admitted in the real task.
    """
    if type(max_interventions) is not int or not 0 <= max_interventions <= 2:
        raise ValueError("max_interventions must be an integer from 0 through 2")
    validate_case(reference)
    validate_case(predicted)
    for category in CATEGORIES:
        if {row["id"] for row in reference[category]} != {row["id"] for row in predicted[category]}:
            raise ValueError(f"Reference and predicted {category} IDs must match")
    evidence_count = len(reference["evidence"])
    if evidence_count > MAX_EVIDENCE:
        raise ValueError(f"Graph review supports at most {MAX_EVIDENCE} evidence nodes")

    reference_nodes, predicted_nodes = _canonical(reference), _canonical(predicted)
    differences = [
        {"id": identifier, "category": category,
         "fields": sorted(key for key in node if node[key] != predicted_nodes[category][identifier][key]),
         "reference": node, "predicted": predicted_nodes[category][identifier]}
        for category in CATEGORIES
        for identifier, node in reference_nodes[category].items()
        if node != predicted_nodes[category][identifier]
    ]
    reference_snapshot, predicted_snapshot = analyze(reference), analyze(predicted)
    current = _compare(reference_snapshot, predicted_snapshot)
    eligibility_mismatches = [
        {"id": identifier, "reference_active": node["active"],
         "predicted_active": predicted_nodes["evidence"][identifier]["active"],
         "reference_usable": reference_snapshot["evidence"][identifier]["usable"],
         "predicted_usable": predicted_snapshot["evidence"][identifier]["usable"]}
        for identifier, node in reference_nodes["evidence"].items()
        if node["active"] != predicted_nodes["evidence"][identifier]["active"]
    ]
    candidates = [
        {"id": identifier, "action": "withdraw" if node["active"] else "restore",
         "active": not node["active"]}
        for identifier, node in reference_nodes["evidence"].items()
    ]
    witness = None if current["agreement"] else {
        "kind": "current_disagreement", "cardinality": 0, "actions": [], **current,
    }
    by_cardinality = []
    for size in range(1, min(max_interventions, evidence_count) + 1):
        tested = divergent = 0
        for actions in itertools.combinations(candidates, size):
            comparison = _compare(analyze(_intervene(reference, actions)),
                                  analyze(_intervene(predicted, actions)))
            tested += 1
            if not comparison["agreement"]:
                divergent += 1
                if witness is None:
                    witness = {"kind": "intervention_disagreement", "cardinality": size,
                               "actions": copy.deepcopy(list(actions)), **comparison}
        by_cardinality.append({"cardinality": size, "possible_subsets": math.comb(evidence_count, size),
                               "tested_subsets": tested, "divergent_subsets": divergent})

    return {
        "schema_version": "retrace.graph-review.v1",
        "diagnostic_type": "post_hoc_offline_engineering_review",
        "graph_exact": not differences,
        "relationship_agreement": all(diff["category"] == "evidence" and diff["fields"] == ["active"]
                                      for diff in differences),
        "node_count": sum(len(reference_nodes[category]) for category in CATEGORIES),
        "differing_node_count": len(differences),
        "node_differences": differences,
        "local_eligibility_mismatches": eligibility_mismatches,
        "current": current,
        "candidate_toggles": candidates,
        "total_interventions_tested": sum(row["tested_subsets"] for row in by_cardinality),
        "search": {
            "max_interventions": max_interventions,
            "evidence_count": evidence_count,
            "possible_subsets": sum(row["possible_subsets"] for row in by_cardinality),
            "tested_subsets": sum(row["tested_subsets"] for row in by_cardinality),
            "divergent_subsets": sum(row["divergent_subsets"] for row in by_cardinality),
            "by_cardinality": by_cardinality,
            "exhaustive_within_bound": True,
            "baseline_included_in_subset_counts": False,
        },
        "witness": witness,
        "scope": [
            "Post-hoc engineering diagnostic; not a prespecified experimental outcome or another model call.",
            "Reference is an authored comparison graph, not independently established real-world truth.",
            "Each intervention authoritatively sets the same evidence local flag in both graphs; inherited usability is recomputed.",
            "Restoration includes hypothetical eligibility of initially unavailable records; it is not permission to trust those records.",
            "A witness establishes decision-level inequivalence for the displayed actions under declared Boolean support semantics.",
            "No witness means no decision divergence within this bounded action set, not graph correctness, general equivalence, or calibrated confidence.",
            "Metadata such as revoke is ignored; callers must supply final local active flags.",
        ],
    }
