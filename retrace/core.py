"""A small, deterministic support engine; support is not real-world truth.

Evidence roots are usable when active. Copies require every declared parent.
Claims use OR-of-AND support clauses; decisions require all declared claims.
The declarations are trusted inputs, not inferred or authenticated by this engine.
"""

from __future__ import annotations

from typing import Any


def _ids(value: Any, location: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError(f"{location} must be a list of nonempty string IDs")
    if nonempty and not value:
        raise ValueError(f"{location} cannot be empty")
    if len(value) != len(set(value)):
        raise ValueError(f"{location} contains duplicate IDs")
    return value


def validate_case(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate the complete graph and return its ID index.

Rejecting malformed graphs is deliberate: dangling provenance must not silently
look like a valid independent source. No mutation of the supplied case occurs.
"""
    if not isinstance(case, dict):
        raise ValueError("case must be an object")
    index: dict[str, dict[str, Any]] = {}
    categories: dict[str, str] = {}
    for category in ("evidence", "claims", "decisions"):
        records = case.get(category)
        if not isinstance(records, list):
            raise ValueError(f"{category} must be a list")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"{category} records must be objects")
            identifier = record.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError(f"{category} record needs a nonempty string id")
            if identifier in index:
                raise ValueError(f"duplicate node ID: {identifier}")
            if not isinstance(record.get("label", identifier), str):
                raise ValueError(f"{identifier}.label must be a string")
            index[identifier] = record
            categories[identifier] = category

    dependencies: dict[str, list[str]] = {}
    for identifier, record in index.items():
        category = categories[identifier]
        if category == "evidence":
            kind = record.get("kind", "root")
            if kind not in ("root", "copy"):
                raise ValueError(f"{identifier}.kind must be root or copy")
            if type(record.get("active", True)) is not bool:
                raise ValueError(f"{identifier}.active must be a boolean")
            refs = _ids(record.get("parents", []), f"{identifier}.parents", nonempty=kind == "copy")
            if kind == "root" and refs:
                raise ValueError(f"root {identifier} cannot declare parents")
            allowed = {"evidence"}
        elif category == "claims":
            supports = record.get("supports")
            if not isinstance(supports, list):
                raise ValueError(f"{identifier}.supports must be a list of support clauses")
            refs = []
            for number, clause in enumerate(supports):
                refs.extend(_ids(clause, f"{identifier}.supports[{number}]", nonempty=True))
            refs = list(dict.fromkeys(refs))
            allowed = {"evidence", "claims"}
        else:
            refs = _ids(record.get("requires"), f"{identifier}.requires", nonempty=True)
            allowed = {"claims"}
        for ref in refs:
            if ref not in index:
                raise ValueError(f"{identifier} refers to missing node {ref}")
            if categories[ref] not in allowed:
                raise ValueError(f"{identifier} cannot depend on {categories[ref]} node {ref}")
        dependencies[identifier] = refs

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise ValueError(f"dependency cycle at {identifier}")
        if identifier in visited:
            return
        visiting.add(identifier)
        for ref in dependencies[identifier]:
            visit(ref)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in index:
        visit(identifier)
    return index


def _snapshot(case: dict[str, Any], index: dict[str, dict[str, Any]], revoked: set[str]) -> dict[str, Any]:
    categories = {record["id"]: category for category in ("evidence", "claims", "decisions") for record in case[category]}
    memo: dict[str, dict[str, Any]] = {}

    def resolve(identifier: str) -> dict[str, Any]:
        if identifier in memo:
            return memo[identifier]
        record = index[identifier]
        category = categories[identifier]
        if category == "evidence":
            clauses = [record.get("parents", [])] if record.get("kind", "root") == "copy" else []
        elif category == "claims":
            clauses = record["supports"]
        else:
            clauses = [record["requires"]]
        refs = list(dict.fromkeys(ref for clause in clauses for ref in clause))
        children = {ref: resolve(ref) for ref in refs}
        root = category == "evidence" and record.get("kind", "root") == "root"
        locally_active = category != "evidence" or (record.get("active", True) and identifier not in revoked)
        valid_supports = [list(clause) for clause in clauses if all(children[ref]["usable"] for ref in clause)]
        usable = bool(locally_active and (root or valid_supports))
        if not locally_active:
            valid_supports = []
        roots = {identifier} if root else {r for child in children.values() for r in child["roots"]}
        supporting_roots = ({identifier} if root else {r for clause in valid_supports for ref in clause for r in children[ref]["supporting_roots"]}) if usable else set()
        causes: set[str] = set()
        if not usable:
            if not locally_active:
                causes.add(identifier)
            elif not clauses:
                causes.add(identifier)
            else:
                for child in children.values():
                    if not child["usable"]:
                        causes.update(child["invalidation_causes"])
        paths: dict[str, list[str]] = {identifier: [identifier]} if root else {}
        for ref, child in children.items():
            for origin, path in child["dependency_paths"].items():
                paths.setdefault(origin, [identifier] + path)
        failures = [
            {"clause": list(clause), "unavailable": [ref for ref in clause if not children[ref]["usable"]]}
            for clause in clauses if not all(children[ref]["usable"] for ref in clause)
        ]
        result = {
            "id": identifier,
            "label": record.get("label", identifier),
            "usable": usable,
            "status": "supported" if usable else "not_supported",
            "roots": sorted(roots),
            "supporting_roots": sorted(supporting_roots),
            "valid_supports": valid_supports,
            "failed_supports": failures,
            "invalidation_causes": sorted(causes),
            "dependency_paths": paths,
        }
        if category == "evidence":
            result.update(kind=record.get("kind", "root"), active=bool(locally_active), parents=record.get("parents", []))
        memo[identifier] = result
        return result

    return {category: {record["id"]: resolve(record["id"]) for record in case[category]} for category in ("evidence", "claims", "decisions")}


def analyze(case: dict[str, Any], revoked: list[str] | None = None) -> dict[str, Any]:
    """Evaluate support after explicit evidence revocations.

``revoked=None`` means no additional revocations; it does not implicitly use the
benchmark's ``case['revoke']`` field. Pass that field to evaluate the event.
Restoration is evaluated by removing an ID from the revoked list and re-running.
``roots`` names declared origins, without asserting statistical independence.
``dependency_paths`` supplies one witness path per origin, not all possible paths.
"""
    index = validate_case(case)
    revoked = [] if revoked is None else _ids(revoked, "revoked")
    evidence_ids = {record["id"] for record in case["evidence"]}
    for identifier in revoked:
        if identifier not in evidence_ids:
            raise ValueError(f"revoked ID is not evidence: {identifier}")
    before = _snapshot(case, index, set())
    after = _snapshot(case, index, set(revoked))
    invalidated = [identifier for category in before for identifier, record in before[category].items() if record["usable"] and not after[category][identifier]["usable"]]
    impacted = [identifier for identifier in before["decisions"] if before["decisions"][identifier]["usable"] and not after["decisions"][identifier]["usable"]]
    after.update(
        case_id=case.get("id", "unidentified"),
        revoked=sorted(revoked),
        invalidated_ids=sorted(invalidated),
        impacted_decisions=sorted(impacted),
        unaffected_decisions=sorted(set(before["decisions"]) - set(impacted)),
        supported_decisions=sorted(identifier for identifier, result in after["decisions"].items() if result["usable"]),
        semantics="Declared evidence support only; not a truth verdict or an estimate of real-world confidence.",
    )
    return after
