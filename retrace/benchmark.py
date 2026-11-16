"""Reproducible synthetic tasks and explicitly non-LLM rule baselines.

These measurements validate a formal task and its implementation. They are not
empirical measurements of language-model behavior or user decision quality.
"""

from __future__ import annotations

import copy
import random
from typing import Any

from .core import analyze, validate_case


FAMILIES = ("chain", "redundant", "conjunctive", "copy", "irrelevant", "partial_retraction", "no_op")
POLICIES = ("stale_before", "blanket_retract", "string_only", "descendant_flood", "oracle")


def generate_cases(seed: int = 1729, count: int = 70) -> list[dict[str, Any]]:
    """Generate varied graph structures, not just renamed fixed templates.

The case contains no oracle answer. Its explicit support declarations define the
formal task. Ground truth must be computed, not inferred from a real-world label.
"""
    if type(seed) is not int or type(count) is not int or count < 0:
        raise ValueError("seed must be an integer; count must be a nonnegative integer")
    rng = random.Random(seed)
    cases = []
    for number in range(count):
        family = FAMILIES[number % len(FAMILIES)]
        evidence: list[dict[str, Any]] = []
        claims: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []

        def root(label: str, active: bool = True) -> str:
            identifier = f"E{len(evidence) + 1}"
            evidence.append({"id": identifier, "label": label, "kind": "root", "parents": [], "active": active})
            return identifier

        def copied(parent: str, length: int) -> str:
            for step in range(length):
                identifier = f"E{len(evidence) + 1}"
                evidence.append({"id": identifier, "label": f"Derivative bulletin {step + 1} citing {parent}", "kind": "copy", "parents": [parent], "active": True})
                parent = identifier
            return parent

        def claim(label: str, supports: list[list[str]]) -> str:
            identifier = f"C{len(claims) + 1}"
            claims.append({"id": identifier, "label": label, "supports": supports})
            return identifier

        def decision(label: str, requires: list[str]) -> str:
            identifier = f"D{len(decisions) + 1}"
            decisions.append({"id": identifier, "label": label, "requires": requires})
            return identifier

        origin = root("Primary inspection record")
        safe_origin = root("Unrelated independent inspection record")
        unavailable = root("Record already unavailable at the start", active=False)
        safe_claim = claim("Separate module has usable inspection support", [[safe_origin]])
        unavailable_claim = claim("Unavailable report supports a reserve module", [[unavailable]])
        branch_length = rng.randint(1, 4)
        copy_length = rng.randint(1, 4)
        next_ref = copied(origin, copy_length) if family in ("copy", "partial_retraction", "no_op") else origin
        if family == "redundant":
            alternatives = [root(f"Alternative inspection origin {j + 1}", active=(j != 0 or number % 2 == 0)) for j in range(rng.randint(1, 3))]
            next_ref = claim("Module has at least one admissible inspection", [[origin]] + [[ref] for ref in alternatives])
        elif family == "conjunctive":
            required = [root(f"Required supplementary check {j + 1}") for j in range(rng.randint(1, 3))]
            next_ref = claim("Module has all required checks", [[origin] + required])
        elif family == "partial_retraction":
            alternative = root("Independent backup for one branch")
            preserved = claim("Backup preserves one module", [[next_ref], [alternative]])
            decision("Authorize the independently backed module", [preserved])
        for depth in range(branch_length):
            next_ref = claim(f"Derived clearance level {depth + 1}", [[next_ref]])
        decision("Authorize the module covered by the primary record", [next_ref])
        decision("Authorize the separate module", [safe_claim])
        decision("Authorize both modules together", [next_ref, safe_claim])
        decision("Authorize the reserve module", [unavailable_claim])
        revoke = [origin]
        event_history: list[dict[str, Any]] = [{"type": "revoke", "ids": [origin]}]
        if family == "irrelevant":
            unused = root("Withdrawn record for an out-of-scope module")
            revoke = [unused]
            event_history = [{"type": "revoke", "ids": [unused]}]
        elif family == "partial_retraction" and (number // len(FAMILIES)) % 2 == 1:
            # A local derivative can be withdrawn without revoking its parent.
            derivative = next(record["id"] for record in evidence if record["kind"] == "copy")
            revoke = [derivative]
            event_history = [{"type": "revoke", "ids": [derivative]}]
        elif family == "no_op":
            revoke = []
            event_history = []
        case = {
            "id": f"retrace-{seed}-{number:04d}",
            "title": f"Synthetic module review {number + 1}",
            "family": family,
            "synthetic": True,
            "evidence": evidence,
            "claims": claims,
            "decisions": decisions,
            "revoke": revoke,
            "event_history": event_history,
        }
        validate_case(case)
        cases.append(case)
    return cases


def baseline_predictions(case: dict[str, Any], policy: str) -> dict[str, bool]:
    """Return formal rule-baseline predictions, never simulated LLM output."""
    if policy not in POLICIES:
        raise ValueError(f"unknown baseline policy: {policy}")
    before = analyze(case)
    revoked = case.get("revoke", [])
    if policy == "oracle":
        current = analyze(case, revoked)
        return {key: record["usable"] for key, record in current["decisions"].items()}
    if policy == "stale_before":
        return {key: record["usable"] for key, record in before["decisions"].items()}
    if policy == "blanket_retract":
        return {key: False if revoked else record["usable"] for key, record in before["decisions"].items()}
    if policy == "string_only":
        flattened = copy.deepcopy(case)
        for record in flattened["evidence"]:
            if record.get("kind", "root") == "copy":
                record["kind"] = "root"
                record["parents"] = []
        current = analyze(flattened, revoked)
        return {key: record["usable"] for key, record in current["decisions"].items()}
    # Deliberately wrong cascade: ignores alternative support clauses.
    blocked = set(revoked)
    index = validate_case(case)
    changed = True
    while changed:
        changed = False
        for identifier, record in index.items():
            dependencies = record.get("parents", record.get("requires", []))
            if "supports" in record:
                dependencies = [ref for clause in record["supports"] for ref in clause]
            if identifier not in blocked and any(ref in blocked for ref in dependencies):
                blocked.add(identifier)
                changed = True
    return {key: record["usable"] and key not in blocked for key, record in before["decisions"].items()}


def _metrics(counts: dict[str, int]) -> dict[str, Any]:
    total = counts["decision_count"]
    supported = counts["true_positive"] + counts["over_retraction"]
    unsupported = counts["true_negative"] + counts["under_retraction"]
    predicted_supported = counts["true_positive"] + counts["under_retraction"]
    unsupported_acceptance_rate = counts["under_retraction"] / unsupported if unsupported else None
    # Undefined class-specific rates remain null rather than misleading zeroes.
    return {
        **counts,
        "decision_accuracy": (counts["true_positive"] + counts["true_negative"]) / total if total else None,
        "under_retraction_rate": unsupported_acceptance_rate,
        "unsupported_acceptance_rate": unsupported_acceptance_rate,
        "missed_retraction_rate": counts["missed_retractions"] / counts["required_retractions"] if counts["required_retractions"] else None,
        "over_retraction_rate": counts["over_retraction"] / supported if supported else None,
        "supported_precision": counts["true_positive"] / predicted_supported if predicted_supported else None,
        "supported_recall": counts["true_positive"] / supported if supported else None,
    }


def evaluate_predictions(case: dict[str, Any], predictions: dict[str, bool], revoked: list[str] | None = None) -> dict[str, Any]:
    """Score complete boolean predictions against the declared support semantics.

By default this uses the case's final ``revoke`` event. The legacy
``under_retraction_rate`` is an alias for ``unsupported_acceptance_rate``:
it measures unsupported decisions marked supported, including decisions already
unsupported before the event. It is not a selective-repair rate.
``missed_retraction_rate`` uses only required retractions: before-supported
decisions that become unsupported after this event and are still marked supported.
Supported decisions marked unsupported are over-retractions. Undefined rates are
null; initially unsupported controls never dilute the required-retraction denominator.
"""
    actual = analyze(case, case.get("revoke", []) if revoked is None else revoked)
    expected = {key: record["usable"] for key, record in actual["decisions"].items()}
    if not isinstance(predictions, dict) or set(predictions) != set(expected):
        raise ValueError("predictions must contain exactly every decision ID")
    if any(type(value) is not bool for value in predictions.values()):
        raise ValueError("every prediction must be a boolean")
    counts = {"decision_count": len(expected), "true_positive": 0, "true_negative": 0, "under_retraction": 0, "over_retraction": 0}
    errors = []
    for identifier, truth in expected.items():
        predicted = predictions[identifier]
        if truth and predicted:
            counts["true_positive"] += 1
        elif not truth and not predicted:
            counts["true_negative"] += 1
        else:
            kind = "over_retraction" if truth else "under_retraction"
            counts[kind] += 1
            errors.append({"decision_id": identifier, "error": kind, "expected": truth, "predicted": predicted})
    lost = actual["impacted_decisions"]
    counts["required_retractions"] = len(lost)
    counts["missed_retractions"] = sum(predictions[identifier] for identifier in lost)
    return {
        **_metrics(counts),
        "case_id": case.get("id"),
        "exact_match": not errors,
        "errors": errors,
        "lost_support_count": len(lost),
        "lost_support_recovered": sum(not predictions[identifier] for identifier in lost),
    }


def run_benchmarks(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate rule-baseline scores with explicit non-empirical labeling."""
    policies = {}
    for policy in POLICIES:
        scored = [evaluate_predictions(case, baseline_predictions(case, policy)) for case in cases]
        keys = ("decision_count", "true_positive", "true_negative", "under_retraction", "over_retraction", "required_retractions", "missed_retractions")
        counts = {key: sum(result[key] for result in scored) for key in keys}
        exact = sum(result["exact_match"] for result in scored)
        families = sorted(set(case.get("family", "unclassified") for case in cases))
        by_family = {}
        for family in families:
            family_scores = [result for case, result in zip(cases, scored) if case.get("family", "unclassified") == family]
            family_counts = {key: sum(result[key] for result in family_scores) for key in keys}
            by_family[family] = {
                **_metrics(family_counts),
                "case_count": len(family_scores),
                "exact_match_cases": sum(result["exact_match"] for result in family_scores),
            }
        policies[policy] = {
            **_metrics(counts),
            "exact_match_cases": exact,
            "exact_match_rate": exact / len(cases) if cases else None,
            "by_family": by_family,
        }
    return {
        "kind": "deterministic_synthetic_rule_baselines",
        "case_count": len(cases),
        "decision_count": sum(len(case["decisions"]) for case in cases),
        "disclaimer": "Synthetic formal-task checks only. No language models or human participants were evaluated. Oracle performance is a correctness check by construction, not evidence of an intervention's effectiveness.",
        "metric_definitions": {
            "unsupported_acceptance_rate": "Unsupported decisions predicted supported / all unsupported decisions, including initially unsupported controls. Legacy under_retraction_rate is the same classifier rate.",
            "missed_retraction_rate": "Required retractions missed / required retractions. Only decisions supported before the event and unsupported afterward are eligible; preunsupported controls are excluded.",
            "over_retraction_rate": "Still-supported decisions predicted unsupported / all still-supported decisions.",
        },
        "policies": policies,
    }
