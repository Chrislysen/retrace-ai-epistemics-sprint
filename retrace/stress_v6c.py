"""Local, finite-scope stress analysis of explicitly supplied interpretations.

No source truth, candidate completeness, or probabilistic confidence is inferred.
All withdrawal sets are additional to the current state, and count record IDs,
not independent observations or causes. No network or file writes occur here.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import deque

from .core import analyze, validate_case
from .uncertainty_v6c import analyze_uncertainty

MAX_VARIABLES = 16
CATEGORIES = ("evidence", "claims", "decisions")


def _ids(value, known, name):
    if (not isinstance(value, list) or any(not isinstance(v, str) or v not in known for v in value)
            or len(value) != len(set(value))):
        raise ValueError(f"{name} must contain unique existing IDs")
    return sorted(value)


def _validate(brief, state):
    """Validate the entire supplied universe before answer-based filtering."""
    if not isinstance(brief, dict):
        raise ValueError("brief must be an object")
    for key in ("id", "title", "prose"):
        if key in brief and not isinstance(brief[key], str):
            raise ValueError(f"brief.{key} must be a string")
    candidates = brief.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 32:
        raise ValueError("Supply between 1 and 32 candidate graphs")
    candidate_ids = set()
    registry = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Candidates must be objects")
        cid, graph = candidate.get("id"), candidate.get("graph")
        if not isinstance(cid, str) or not cid or cid in candidate_ids:
            raise ValueError("Candidate IDs must be unique nonempty strings")
        candidate_ids.add(cid)
        if not isinstance(graph, dict) or any(not isinstance(graph.get(k), list) for k in CATEGORIES):
            raise ValueError("Each candidate graph needs evidence, claims and decisions arrays")
        if sum(len(graph[k]) for k in CATEGORIES) > 250:
            raise ValueError("Each candidate graph may have at most 250 nodes")
        if graph.get("revoke"):
            raise ValueError("encode current active flags first: nonempty graph.revoke is not accepted")
        fields = {"evidence": {"id", "kind", "active", "parents"},
                  "claims": {"id", "supports"}, "decisions": {"id", "requires"}}
        for category, required in fields.items():
            for node in graph[category]:
                if (not isinstance(node, dict) or not required <= set(node)
                        or set(node) - required - {"label"}):
                    raise ValueError(f"{category} nodes require explicit {', '.join(sorted(required))}; only label is optional")
        validate_case(graph)
        references = sum(len(row["parents"]) for row in graph["evidence"])
        references += sum(len(clause) for row in graph["claims"] for clause in row["supports"])
        references += sum(len(row["requires"]) for row in graph["decisions"])
        if references > 10000:
            raise ValueError("Each graph may contain at most 10000 dependency references")
        typed = {k: {r["id"] for r in graph[k]} for k in CATEGORIES}
        if registry is not None and typed != registry:
            raise ValueError("Candidate graphs must have the same IDs in each node category")
        registry = typed
    candidates = sorted(candidates, key=lambda row: row["id"])
    targets = (_ids(brief["target_decisions"], registry["decisions"], "target_decisions")
               if "target_decisions" in brief else sorted(registry["decisions"]))
    allowed = (_ids(brief["allowed_withdrawals"], registry["evidence"], "allowed_withdrawals")
               if "allowed_withdrawals" in brief else sorted(registry["evidence"]))
    if len(allowed) > MAX_VARIABLES:
        raise ValueError("Exact stress analysis supports at most 16 withdrawal variables; narrow allowed_withdrawals explicitly")

    raw_questions = brief.get("questions", [])
    if not isinstance(raw_questions, list) or len(raw_questions) > 5:
        raise ValueError("Supply at most 5 factual questions")
    questions, seen = [], set()
    for question in raw_questions:
        if not isinstance(question, dict):
            raise ValueError("Questions must be objects")
        qid = question.get("id")
        if not isinstance(qid, str) or not qid or qid in seen:
            raise ValueError("Question IDs must be unique nonempty strings")
        seen.add(qid)
        label, cost, answers = question.get("label"), question.get("cost", 1), question.get("answers")
        if not isinstance(label, str) or not label:
            raise ValueError("Each question needs a nonempty factual label")
        if type(cost) is not int or cost <= 0:
            raise ValueError("Question costs must be positive integers")
        if (not isinstance(answers, dict) or set(answers) != candidate_ids
                or any(type(v) is not bool for v in answers.values())):
            raise ValueError("Each question needs an explicit boolean answer for every supplied candidate")
        questions.append({"id": qid, "label": label, "cost": cost, "answers": answers})
    questions.sort(key=lambda row: row["id"])

    documents, document_ids = [], set()
    raw_documents = brief.get("documents", [])
    if not isinstance(raw_documents, list):
        raise ValueError("documents must be an array")
    for document in raw_documents:
        if not isinstance(document, dict):
            raise ValueError("Documents must be objects")
        did = document.get("id")
        if not isinstance(did, str) or not did or did in document_ids:
            raise ValueError("Document IDs must be unique nonempty strings")
        document_ids.add(did)
        if not isinstance(document.get("label"), str) or not document["label"]:
            raise ValueError("Each document needs a nonempty label")
        members = _ids(document.get("evidence_ids"), registry["evidence"], f"document {did}.evidence_ids")
        documents.append({"id": did, "label": document["label"], "evidence_ids": members})
    documents.sort(key=lambda row: row["id"])

    constraints, constraint_ids = [], set()
    node_ids = set.union(*registry.values())
    raw_constraints = brief.get("provenance_constraints", [])
    if not isinstance(raw_constraints, list):
        raise ValueError("provenance_constraints must be an array")
    for constraint in raw_constraints:
        if not isinstance(constraint, dict):
            raise ValueError("Provenance constraints must be objects")
        pcid = constraint.get("id")
        if not isinstance(pcid, str) or not pcid or pcid in constraint_ids:
            raise ValueError("Provenance constraint IDs must be unique nonempty strings")
        constraint_ids.add(pcid)
        child, ancestor = constraint.get("child"), constraint.get("ancestor")
        if (not isinstance(child, str) or child not in node_ids
                or not isinstance(ancestor, str) or not ancestor or child == ancestor):
            raise ValueError("A provenance constraint needs an existing child and a distinct nonempty ancestor ID")
        if "source_quote" in constraint and not isinstance(constraint["source_quote"], str):
            raise ValueError("A provenance source_quote must be a string")
        constraints.append(copy.deepcopy(constraint))
    constraints.sort(key=lambda row: row["id"])

    if state is None:
        state = {}
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    if set(state) - {"answers", "revoked_documents", "revoked_passages", "scenario_withdrawals"}:
        raise ValueError("Unknown stress state fields")
    answers = state.get("answers", {})
    if (not isinstance(answers, dict) or not set(answers) <= seen
            or any(value is not None and type(value) is not bool for value in answers.values())):
        raise ValueError("State answers must map existing question IDs to boolean or null")
    state = {
        "answers": dict(sorted(answers.items())),
        "revoked_documents": _ids(state.get("revoked_documents", []), document_ids, "revoked_documents"),
        "revoked_passages": _ids(state.get("revoked_passages", []), registry["evidence"], "revoked_passages"),
        "scenario_withdrawals": _ids(state.get("scenario_withdrawals", []), registry["evidence"], "scenario_withdrawals"),
    }
    # Bind all source text and declarations, including optional metadata. This
    # is a change detector for JSON inputs, not a semantic or authenticity hash.
    try:
        serialized = json.dumps({"brief": brief, "state": state}, sort_keys=True,
                                ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Brief and state must contain JSON-serializable finite values") from exc
    fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return candidates, registry, targets, allowed, questions, documents, constraints, state, fingerprint


def _basis(variables):
    """Shared truth-table masks, cardinality layers, and lexicographic choice."""
    states = 1 << len(variables)
    width = (states + 7) // 8
    layers = [bytearray(width) for _ in range(len(variables) + 1)]
    withdrawn = [bytearray(width) for _ in variables]
    for assignment in range(states):
        byte, bit = assignment >> 3, 1 << (assignment & 7)
        layers[assignment.bit_count()][byte] |= bit
        remaining = assignment
        while remaining:
            low = remaining & -remaining
            withdrawn[low.bit_length() - 1][byte] |= bit
            remaining ^= low
    layers = [int.from_bytes(value, "little") for value in layers]
    withdrawn = [int.from_bytes(value, "little") for value in withdrawn]
    universe = (1 << states) - 1
    available = {name: universe ^ withdrawn[pos] for pos, name in enumerate(variables)}
    cache = {}

    def minimum(mask):
        if not mask:
            return None
        if mask in cache:
            return cache[mask]
        for count, layer in enumerate(layers):
            choices = mask & layer
            if not choices:
                continue
            chosen = []
            for position, variable_mask in enumerate(withdrawn):
                if len(chosen) == count:
                    break
                with_position = choices & variable_mask
                if with_position:
                    chosen.append(position)
                    choices = with_position
            assignment = choices.bit_length() - 1
            result = assignment, [variables[pos] for pos in chosen]
            cache[mask] = result
            return result
        raise AssertionError("Truth-table mask outside declared universe")

    return states, universe, available, minimum


def _table(graph, available, universe):
    """Compile the validated positive DAG using one shared intervention basis."""
    index = {row["id"]: row for category in CATEGORIES for row in graph[category]}
    categories = {row["id"]: category for category in CATEGORIES for row in graph[category]}
    values = {}

    def conjunction(refs):
        result = universe
        for ref in refs:
            result &= visit(ref)
        return result

    def visit(identifier):
        if identifier in values:
            return values[identifier]
        row, category = index[identifier], categories[identifier]
        if category == "evidence":
            result = available.get(identifier, universe) if row.get("active", True) else 0
            if row.get("kind", "root") == "copy":
                result &= conjunction(row["parents"])
        elif category == "claims":
            result = 0
            for clause in row["supports"]:
                result |= conjunction(clause)
        else:
            result = conjunction(row["requires"])
        values[identifier] = result
        return result

    return {row["id"]: visit(row["id"]) for row in graph["decisions"]}


def _ancestry(candidates, constraints):
    dependencies = {}
    for candidate in candidates:
        graph = candidate["graph"]
        refs = {row["id"]: sorted(row.get("parents", [])) for row in graph["evidence"]}
        refs.update({row["id"]: sorted({ref for clause in row["supports"] for ref in clause})
                     for row in graph["claims"]})
        refs.update({row["id"]: sorted(row["requires"]) for row in graph["decisions"]})
        dependencies[candidate["id"]] = refs
    results = []
    for constraint in constraints:
        by_candidate = {}
        for cid, refs in dependencies.items():
            queue = deque([(constraint["child"], [constraint["child"]])])
            visited, found = set(), None
            while queue:
                node, path = queue.popleft()
                if node == constraint["ancestor"]:
                    found = path
                    break
                if node in visited:
                    continue
                visited.add(node)
                queue.extend((ref, path + [ref]) for ref in refs[node])
            reason = (None if found is not None else "missing_ancestor_node" if constraint["ancestor"] not in refs
                      else "missing_ancestor_path")
            by_candidate[cid] = {"satisfied": found is not None, "path": found, "reason": reason}
        results.append({**constraint, "by_candidate": by_candidate,
                        "violating_candidate_ids": [cid for cid, item in by_candidate.items() if not item["satisfied"]]})
    return results


def analyze_stress(brief: dict, state: dict | None = None) -> dict:
    """Analyze a finite declared brief without mutating any input.

    State answers are factual booleans or null (unknown); inconsistent known
    answers raise ValueError. Source, passage and scenario vetoes are independent
    and cumulative. Clearing one veto never overrides another or an originally
    inactive record. Scenario IDs may be any declared evidence; future additional
    searches use only allowed_withdrawals (default all evidence, maximum 16).

    Provenance constraints check declared structural ancestry, including claims
    and decisions, regardless of active flags. They report defects but never
    discard candidates. Question answer tables and constraints are trusted inputs.
    An externally declared ancestor may be absent from every candidate; that is
    reported as missing_ancestor_node and never added to a calculation graph.
    Costs default to one. Exact minimax clarification uses the effective graphs.
    All node fields must be explicit; only a descriptive label is optional.
    Each graph is bounded to 250 nodes and 10000 dependency references.
    """
    (candidates, registry, targets, variables, questions, documents,
     constraints, state, fingerprint) = _validate(brief, state)
    retained = [candidate for candidate in candidates if all(
        state["answers"].get(question["id"]) is None
        or question["answers"][candidate["id"]] == state["answers"][question["id"]]
        for question in questions)]
    if not retained:
        raise ValueError("The known answers contradict all supplied candidates; reopen or revise the candidate set")
    retained_ids = [candidate["id"] for candidate in retained]
    eliminated = [candidate["id"] for candidate in candidates if candidate["id"] not in retained_ids]
    revoked_documents = set(state["revoked_documents"])
    revoked_passages, scenario = set(state["revoked_passages"]), set(state["scenario_withdrawals"])
    membership = {eid: [doc["id"] for doc in documents
                        if doc["id"] in revoked_documents and eid in doc["evidence_ids"]]
                  for eid in sorted(registry["evidence"])}
    effective = copy.deepcopy(retained)
    original_evidence = {row["id"]: {node["id"]: node for node in row["graph"]["evidence"]}
                         for row in retained}
    flags = {eid: {"document_veto": bool(membership[eid]), "passage_veto": eid in revoked_passages,
                   "scenario_veto": eid in scenario, "revoked_documents": membership[eid], "by_candidate": {}}
             for eid in sorted(registry["evidence"])}
    for candidate in effective:
        for evidence in candidate["graph"]["evidence"]:
            eid, cid = evidence["id"], candidate["id"]
            original_active = original_evidence[cid][eid].get("active", True)
            evidence["active"] = original_active and not (membership[eid] or eid in revoked_passages or eid in scenario)
            flags[eid]["by_candidate"][cid] = {"original_active": original_active,
                                               "effective_active": evidence["active"]}
    filtered_questions = [{**question, "answers": {cid: question["answers"][cid] for cid in retained_ids}}
                          for question in questions]
    consensus = analyze_uncertainty(effective, filtered_questions, targets)
    original_outcomes = {row["id"]: {did: item["usable"] for did, item in analyze(row["graph"])["decisions"].items()}
                         for row in retained}
    decision_labels = {row["id"]: row.get("label", row["id"]) for row in retained[0]["graph"]["decisions"]}
    states_count, universe, available, minimum = _basis(variables)
    tables = {row["id"]: _table(row["graph"], available, universe) for row in effective}
    witnesses, audit_decisions, decision_states = {}, {}, {}

    def witness(mask, did):
        selected = minimum(mask)
        if selected is None:
            return None
        assignment, withdraw = selected
        return {"withdraw": withdraw, "scenario_withdrawals": sorted(scenario | set(withdraw)),
                "k": len(withdraw), "outcomes": {cid: bool((table[did] >> assignment) & 1)
                                                  for cid, table in tables.items()}}

    for did in sorted(registry["decisions"]):
        all_support, any_support = universe, 0
        for table in tables.values():
            all_support &= table[did]
            any_support |= table[did]
        disagreement = all_support ^ any_support
        current = {cid: bool(table[did] & 1) for cid, table in tables.items()}
        invariant_supported = bool(all_support & 1)
        current_consensus = consensus["decision_states"][did]["state"]
        distinguishing = witness(disagreement, did)
        revoked_candidates = [cid for cid in retained_ids if original_outcomes[cid][did] and not current[cid]]
        classification = ("supported" if current_consensus == "robust_supported" else
                          "needs_review" if current_consensus == "needs_review" else
                          "revoked" if revoked_candidates else "unsupported")
        display_label = {"supported": "Supported under declared links", "needs_review": "Needs review — supplied candidates disagree",
                         "revoked": "Revoked — falsity not asserted", "unsupported": "Unsupported"}[classification]
        decision_states[did] = {**consensus["decision_states"][did], "label": decision_labels[did],
                                "classification": classification, "display_label": display_label,
                                "revoked_candidate_ids": revoked_candidates,
                                "original_outcomes": {cid: original_outcomes[cid][did] for cid in retained_ids}}
        witnesses[did] = {
            "label": decision_labels[did], "current_consensus": current_consensus, "current_outcomes": current,
            "break_applicable": invariant_supported,
            "break_inapplicable_reason": None if invariant_supported else "Current support is not invariant across retained candidates",
            "minimum_break_any": witness(universe ^ all_support, did) if invariant_supported else None,
            "minimum_break_all": witness(universe ^ any_support, did) if invariant_supported else None,
            "minimum_distinguishing": distinguishing,
            "any_failure_state_count": (universe ^ all_support).bit_count(),
            "all_failure_state_count": (universe ^ any_support).bit_count(),
            "disagreement_state_count": disagreement.bit_count(),
        }
        audit_decisions[did] = {"equivalent_within_scope": not disagreement,
                                "disagreement_state_count": disagreement.bit_count(), "current_outcomes": current,
                                "minimum_withdrawal_witness": distinguishing}
    clarification = consensus["clarification"]
    tree = clarification["tree"]
    next_question = ({"id": tree["question_id"], "label": tree["label"], "cost": tree["cost"],
                      "worst_case_cost": tree["worst_case_cost"], "remaining_candidate_ids": retained_ids}
                     if tree and tree["kind"] == "question" else None)
    checks = _ancestry(candidates, constraints)
    retained_constraint_violations = sum(
        not check["by_candidate"][cid]["satisfied"] for check in checks for cid in retained_ids)
    fixed_ids = sorted(registry["evidence"] - set(variables))
    coverage = {"supplied_candidate_count": len(candidates), "retained_candidate_count": len(retained),
                "allowed_withdrawals": variables, "fixed_evidence_ids": fixed_ids, "variables_count": len(variables),
                "states_checked_per_candidate": states_count, "candidate_state_combinations": states_count * len(retained),
                "exhaustive_within_scope": True,
                "provenance_constraint_coverage": "declared_constraints_only" if constraints else "unknown_no_external_constraints",
                "provenance_constraint_count": len(constraints),
                "provenance_checked_candidate_ids": [row["id"] for row in candidates],
                "retained_constraint_violations_count": retained_constraint_violations,
                "retained_constraint_violations_unit": "candidate-constraint pairs",
                "retained_constraint_violating_candidate_ids": sorted({
                    cid for check in checks for cid in retained_ids if not check["by_candidate"][cid]["satisfied"]}),
                "status": ("source_constraint_conflict" if retained_constraint_violations else
                           "no_supplied_constraint_conflict" if constraints else "unknown_no_constraints"),
                "candidate_completeness": "unknown", "hidden_ancestor_coverage": "unknown"}
    return {
        "schema": "retrace.stress.v6c", "brief_id": brief.get("id"), "audit_fingerprint": fingerprint,
        "candidate_ids": retained_ids, "eliminated_candidate_ids": eliminated, "state": state,
        "consensus": consensus, "decision_states": decision_states, "decision_witnesses": witnesses,
        "next_question": next_question, "revocation_flags": flags, "provenance_checks": checks,
        "interventions": {"schema": "retrace.stress-interventions.v1", "candidate_count": len(retained),
                           "allowed_withdrawals": variables, "fixed_evidence_ids": fixed_ids,
                           "states_checked_per_candidate": states_count,
                           "all_decisions_equivalent_within_scope": all(row["equivalent_within_scope"] for row in audit_decisions.values()),
                           "decisions": audit_decisions},
        "coverage": coverage,
        "scope": [
            "All support, robustness and clarification results quantify only over supplied candidate graphs; source truth and candidate completeness are not established.",
            "Every subset of declared allowed withdrawal record IDs is evaluated exactly. IDs may share causes, documents or ancestors; k is not an independent-source count.",
            "Witnesses add withdrawals to the current effective state. Apply their cumulative scenario_withdrawals while preserving document and passage vetoes. Baseline-inactive records are never restored.",
            "Document, passage and scenario vetoes are independent. Clearing one veto cannot override another. Source withdrawal removes admissible support and does not assert falsity.",
            "Minimum break witnesses apply only to currently invariant-supported decisions; null means either inapplicable or no witness within the declared search, as indicated by break_applicable.",
            "Question answers and costs are trusted factual declarations, not model probabilities. Unknown answers retain candidates; contradictory known answers are rejected. The minimax planner uses the current effective decision vector.",
            "Provenance checks test only independently supplied structural ancestor requirements, including claim and decision paths. An externally declared ancestor absent from a graph is flagged, never inserted or inferred. Checks do not authenticate quoted text, prove causal necessity, discover unprovided hidden ancestors or automatically exclude candidates.",
            "The audit fingerprint binds the complete serialized brief and normalized state, including source text, documents and constraints. It detects input changes, not authenticity or semantic equivalence.",
        ],
    }
