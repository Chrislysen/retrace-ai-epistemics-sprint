"""Offline source-interpretation workbench; no inference, persistence or repairs.

The supplied IR is an interpretation, never a verified reading of the prose.
State is bound to the full declaration before answers or vetoes are reused.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .core import analyze
from .source_ir_v6d import compile_cited_ir, audit_cited_ir, source_segments
from .stress_v6c import analyze_stress, _basis, _table
from .refuter_impact_v6 import compare_readings

SCHEMA = "retrace.workbench.v6d"
FIELDS = {"id", "title", "source_documents", "registry", "source_ir", "documents",
          "clarifications", "target_decisions", "allowed_withdrawals", "allowed_exposure_changes"}


def declaration_fingerprint(brief):
    return hashlib.sha256(json.dumps(brief, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _prepare(brief, expected=None):
    if not isinstance(brief, dict) or set(brief) - FIELDS or not {"source_documents", "source_ir"} <= set(brief):
        raise ValueError("Supply a source bundle and source_ir with only documented workbench fields")
    for key in ("id", "title"):
        if key in brief and (not isinstance(brief[key], str) or len(brief[key]) > 512):
            raise ValueError(f"{key} must be bounded text")
    fingerprint = declaration_fingerprint(brief)
    if expected is not None and expected != fingerprint:
        raise ValueError("The source declaration changed; discard stale answers and exclusions before analyzing it")
    working = deepcopy(brief)
    compilation = compile_cited_ir(working["source_ir"], working["source_documents"], working.get("registry"))
    return working, compilation, fingerprint


def _questions(compilation, declarations):
    choices = {choice["id"]: choice for choice in compilation["choices"]}
    if declarations is None:
        declarations = [{"choice_id": key, "label": f"For {key}, is {choice['options'][1]} the applicable source reading rather than {choice['options'][0]}?",
                         "true_option": choice["options"][1], "cost": 1} for key, choice in choices.items()]
    if not isinstance(declarations, list) or len(declarations) > 5:
        raise ValueError("Clarifications must be an array of at most five declared choice questions")
    questions, catalog, seen = [], [], set()
    for row in declarations:
        if not isinstance(row, dict) or set(row) != {"choice_id", "label", "true_option", "cost"}:
            raise ValueError("Each clarification needs choice_id, label, true_option and cost")
        key = row["choice_id"]
        if key not in choices or key in seen:
            raise ValueError("Clarification IDs must be distinct declared choices")
        seen.add(key)
        options = choices[key]["options"]
        if row["true_option"] not in options or not isinstance(row["label"], str) or not 1 <= len(row["label"]) <= 2048:
            raise ValueError("Clarification label and true option must be explicit and valid")
        if type(row["cost"]) is not int or not 1 <= row["cost"] <= 1000000:
            raise ValueError("Clarification costs must be positive bounded integers")
        question = {"id": key, "label": row["label"], "cost": row["cost"],
                    "answers": {c["id"]: c["assignment"][key] == row["true_option"] for c in compilation["candidates"]}}
        questions.append(question)
        catalog.append({**row, "false_option": next(option for option in options if option != row["true_option"]),
                        "citations": choices[key]["citations"]})
    return questions, catalog


def _stress_brief(brief, compilation, questions):
    out = {"id": brief.get("id", "supplied-source"), "title": brief.get("title", "Source review"),
           "prose": "\n\n".join(d["text"] for d in brief["source_documents"]),
           "candidates": compilation["candidates"], "questions": questions,
           "documents": deepcopy(brief.get("documents", []))}
    source_ids = {d["id"] for d in brief["source_documents"]}
    if not isinstance(out["documents"], list) or any(not isinstance(d, dict) or d.get("id") not in source_ids for d in out["documents"]):
        raise ValueError("Document veto groups must name supplied source documents")
    for key in ("target_decisions", "allowed_withdrawals"):
        if key in brief: out[key] = deepcopy(brief[key])
    return out


def _retained(compilation, stress):
    return [c for c in compilation["candidates"] if c["id"] in stress["candidate_ids"]]


def _locked(stress):
    return sorted(eid for eid, flags in stress["revocation_flags"].items()
                  if flags["document_veto"] or flags["passage_veto"] or flags["scenario_veto"])


def _exposure(candidates, stress, allowed=None):
    """Exact <=12-variable eligibility toggles over all32 retained branches."""
    flags = [{n["id"]: n["active"] for n in c["graph"]["evidence"]} for c in candidates]
    if any(item != flags[0] for item in flags):
        return {"status": "unavailable", "reason": "Candidates disagree on original local eligibility", "decisions": {}}
    initial = flags[0]; locked = _locked(stress)
    allowed = list(initial) if allowed is None else allowed
    if (not isinstance(allowed, list) or any(not isinstance(x, str) or x not in initial for x in allowed)
            or len(allowed) != len(set(allowed))):
        raise ValueError("allowed_exposure_changes must contain distinct evidence IDs")
    variables = sorted(set(allowed) - set(locked))
    if len(variables) > 12:
        return {"status": "unavailable", "reason": "Narrow exposure to at most12 unlocked evidence IDs", "decisions": {}}
    states, universe, remaining, minimum = _basis(variables)
    eligibility = {eid: 0 if eid in locked or not active else universe for eid, active in initial.items()}
    no_enable = universe
    for eid in variables:
        eligibility[eid] = remaining[eid] if initial[eid] else universe ^ remaining[eid]
        if not initial[eid]: no_enable &= remaining[eid]
    tables = {}
    for candidate in candidates:
        graph = deepcopy(candidate["graph"])
        for row in graph["evidence"]: row["active"] = True
        tables[candidate["id"]] = _table(graph, eligibility, universe)
    def witness(did, mask):
        found = minimum(mask)
        if found is None: return None
        assignment, changed = found
        return {"enable": [eid for eid in changed if not initial[eid]], "withdraw": [eid for eid in changed if initial[eid]],
                "total_changes": len(changed), "outcomes": {cid: bool(bits[did] & (1 << assignment)) for cid, bits in tables.items()}}
    decisions = {}
    for did in stress["consensus"]["target_decisions"]:
        every, any_support = universe, 0
        for table in tables.values(): every &= table[did]; any_support |= table[did]
        disagreement = every ^ any_support
        decisions[did] = {"minimum_changes": witness(did, disagreement), "minimum_without_enabling": witness(did, disagreement & no_enable),
                          "disagreement_state_count": disagreement.bit_count(), "equivalent_within_scope": not bool(disagreement)}
    return {"status": "evaluated", "decisions": decisions, "locked_exclusions": locked,
            "changeable_evidence_ids": variables, "states_checked_per_candidate": states,
            "candidate_count": len(candidates), "scope": "Exact hypothetical local-eligibility changes; all existing vetoes stay locked. No truth, ordinary restoration or source amendment is inferred."}


def _record_states(candidates, stress):
    locked = _locked(stress)
    snapshots = {c["id"]: analyze(c["graph"], locked) for c in candidates}
    return {eid: {"by_candidate": {cid: {"usable": s["evidence"][eid]["usable"], "kind": s["evidence"][eid]["kind"],
                                         "parents": s["evidence"][eid]["parents"], **stress["revocation_flags"][eid]["by_candidate"][cid]}
                                     for cid, s in snapshots.items()}}
            for eid in stress["revocation_flags"]}


def analyze_v6d(brief, state=None, expected_declaration_fingerprint=None):
    if state is not None and (not isinstance(state, dict) or set(state) - {"answers", "revoked_documents", "revoked_passages", "scenario_withdrawals"}):
        raise ValueError("State must contain only answers and the three exclusion types")
    working, compilation, fingerprint = _prepare(brief, expected_declaration_fingerprint)
    questions, catalog = _questions(compilation, working.get("clarifications"))
    missing_dispositions = [row["id"] for row in compilation["registry_disposition"] if row["status"] == "absent_from_ir"]
    registry_coverage = {"status": "inventory_gap" if missing_dispositions else "declared_inventory_accounted",
                         "warning_label": "Reference-Free Coverage Gap" if missing_dispositions else None,
                         "missing_disposition_ids": missing_dispositions, "dispositions": compilation["registry_disposition"],
                         "scope": "Known registry IDs need an explicit operational or nonoperational disposition. Missing does not imply an operational node, a semantic error, or a discovered dependency. Accounting for IDs does not certify source completeness or truth."}
    common = {"schema": SCHEMA, "declaration_fingerprint": fingerprint, "compilation": compilation,
              "registry_coverage": registry_coverage,
              "ready_for_conditional_decision_review": compilation["status"] == "compiled" and not missing_dispositions,
              "question_catalog": catalog, "source_completeness": "unknown", "semantic_entailment": "not_certified",
              "provenance": "constructed_offline_demonstration" if fingerprint == declaration_fingerprint(demo_brief()) else "supplied_unverified_interpretation",
              "scope": ["Exact source locations and formal consistency are checked. The proposed interpretation is not authenticated or proven entailed by prose.",
                        "Decision states quantify only over declared interpretations. A complete source reading or real-world truth is not established.",
                        "Factual yes/no labels are supplied interpretations; unknown preserves candidates. No probabilities are inferred.",
                        "Source edits invalidate prior answers and status. Refuter and eligibility previews never replace current declarations or state."]}
    if compilation["status"] != "compiled" or missing_dispositions:
        if state and any(state.get(k) for k in ("answers", "revoked_documents", "revoked_passages", "scenario_withdrawals")):
            raise ValueError("Incomplete interpretation cannot reuse answers or exclusions as an executable analysis")
        return {**common, "status": "incomplete_inventory" if missing_dispositions else "unresolved_structure", "stress": None, "record_states": {}, "exposure": {"status": "unavailable", "reason": "Source interpretation is incomplete"},
                "source_audit": None, "state": {"answers": {}, "revoked_documents": [], "revoked_passages": [], "scenario_withdrawals": []}}
    stress = analyze_stress(_stress_brief(working, compilation, questions), state)
    candidates = _retained(compilation, stress)
    audit = audit_cited_ir(working["source_ir"], working["source_documents"], compilation["candidates"], working.get("registry"))
    audit.pop("compilation", None)
    return {**common, "status": "analyzed", "stress": stress, "state": stress["state"], "source_audit": audit,
            "record_states": _record_states(candidates, stress),
            "exposure": _exposure(candidates, stress, working.get("allowed_exposure_changes", working.get("allowed_withdrawals")))}


def preview_exposure(brief, state, enable, withdraw, expected_declaration_fingerprint=None):
    result = analyze_v6d(brief, state, expected_declaration_fingerprint)
    if result["status"] != "analyzed" or result["exposure"]["status"] != "evaluated":
        raise ValueError("No bounded eligibility preview is available for this declaration")
    candidates = _retained(result["compilation"], result["stress"])
    initial = {n["id"]: n["active"] for n in candidates[0]["graph"]["evidence"]}
    allowed = set(result["exposure"]["changeable_evidence_ids"]); locked = set(_locked(result["stress"]))
    for values, baseline, label in ((enable, False, "enable"), (withdraw, True, "withdraw")):
        if (not isinstance(values, list) or any(not isinstance(eid, str) or eid not in allowed for eid in values)
                or len(values) != len(set(values)) or any(initial[eid] is not baseline for eid in values)):
            raise ValueError(f"{label} must name distinct unlocked records with the matching original eligibility")
    outcomes = {}
    for candidate in candidates:
        graph = deepcopy(candidate["graph"])
        for row in graph["evidence"]:
            if row["id"] in enable: row["active"] = True
            if row["id"] in set(withdraw) | locked: row["active"] = False
        snapshot = analyze(graph)
        outcomes[candidate["id"]] = {did: snapshot["decisions"][did]["usable"] for did in result["stress"]["consensus"]["target_decisions"]}
    return {"schema": "retrace.exposure-preview.v6d", "status": "hypothetical_only", "enable": sorted(enable), "withdraw": sorted(withdraw),
            "outcomes": outcomes, "locked_exclusions": sorted(locked), "original_state": result["state"],
            "declaration_fingerprint": result["declaration_fingerprint"], "scope": "No current record, local flag, answer, veto or decision status was changed."}


def preview_refuter(brief, proposed_ir, state=None, expected_declaration_fingerprint=None):
    current = analyze_v6d(brief, state, expected_declaration_fingerprint)
    proposal = compile_cited_ir(proposed_ir, brief["source_documents"], brief.get("registry"))
    out = {"schema": "retrace.refuter-preview.v6d", "declaration_fingerprint": current["declaration_fingerprint"],
           "original_state": current["state"], "proposal_compilation": proposal, "automatic_commit": False,
           "semantic_entailment": "not_certified", "source_completeness": "unknown",
           "scope": "Comparison is between two supplied interpretations of the same source. A licensed graph means licensed by the current declaration, not proven true or textually entailed. No proposal is committed."}
    missing = [row["id"] for row in proposal["registry_disposition"] if row["status"] == "absent_from_ir"]
    out["proposal_missing_disposition_ids"] = missing
    reason = ("Current interpretation is incomplete" if current["status"] != "analyzed" else
              "Proposed interpretation has unresolved structure" if proposal["status"] != "compiled" else
              "Proposed interpretation is missing identifier dispositions: " + ", ".join(missing) if missing else
              "Reset answered clarifications before comparing an augmented family; answers cannot transfer to new choices"
              if any(type(answer) is bool for answer in current["state"]["answers"].values()) else None)
    if reason:
        out["decision_impact"] = {"status": "unavailable", "reason": reason, "automatic_commit": False}
    else:
        try:
            out["decision_impact"] = compare_readings(current["compilation"]["candidates"], proposal["candidates"],
                locked_exclusions=_locked(current["stress"]), allowed_withdrawals=brief.get("allowed_withdrawals"),
                target_decisions=brief.get("target_decisions"))
        except ValueError as exc:
            out["decision_impact"] = {"status": "unavailable", "reason": str(exc), "automatic_commit": False}
    if current["status"] != "analyzed" or proposal["status"] != "compiled" or missing:
        return {**out, "status": "unresolved_interpretation", "against_current_declaration": None, "current_under_proposal": None}
    against = audit_cited_ir(brief["source_ir"], brief["source_documents"], proposal["candidates"], brief.get("registry"))
    reverse = audit_cited_ir(proposed_ir, brief["source_documents"], current["compilation"]["candidates"], brief.get("registry"))
    against.pop("compilation", None); reverse.pop("compilation", None)
    return {**out, "status": against["status"], "against_current_declaration": against, "current_under_proposal": reverse}


def demo_brief():
    """Constructed source, not empirical model output or a benchmark result."""
    paragraphs = [
        "A, B, C and D are distinct locally eligible original evidence records with no parents. P and U are locally ineligible original evidence with no parents.",
        "X is locally eligible evidence. Its origin has two admitted readings: copy means its sole direct parent is P; original means it is an independent original with no parents. It has no other origin reading.",
        "Y is locally eligible evidence. Its decorative note may be an independent original without parents, called root, or a copy whose only parent is D, called copy. No decision uses Y.",
        "Claim L has two complete route rules. The three reading accepts A alone, B alone or C alone. The four reading accepts those same three alternatives and D alone. Each listed route is sufficient and there are no other routes.",
        "Claim M accepts X alone and no other route. Claim S accepts B alone and no other route. Claim N accepts U alone and no other route. Decision RELEASE requires L only. Decision LINEAGE requires M only. Decision STEADY requires S only. Decision LEGACY requires N only.",
        "All three unresolved choices combine independently: every combination is admitted, without a preferred or actual assignment. An archived suggestion that A copied B is not current. The current register denies B as a parent of A. Unsupported does not mean false. Document, passage and scenario exclusions are separate vetoes; clearing one leaves the others in force.",
    ]
    docs = [{"id": f"source-{n+1}", "title": f"Constructed source paragraph {n+1}", "text": text} for n, text in enumerate(paragraphs)]
    spans = [s["span_id"] for s in source_segments(docs)]
    ir = {"schema": "retrace.source-ir.v6d", "entities": [], "bindings": [], "choices": [],
          "combination": {"mode": "cartesian", "assignments": [], "citations": [spans[5]]}, "propositions": []}
    def add(kind, target, body, paragraph, when=None, scope="current", polarity="assert"):
        ir["propositions"].append({"id": f"p{len(ir['propositions'])+1}", "kind": kind, "target": target, "body": body,
                                   "scope": scope, "polarity": polarity, "when": when or {}, "citations": [spans[paragraph]], "bindings": []})
    for eid in ("A", "B", "C", "D", "P", "U", "X", "Y"):
        p = 1 if eid == "X" else 2 if eid == "Y" else 0
        ir["entities"].append({"id": eid, "type": "evidence", "operational": True, "citations": [spans[p]]})
        add("eligibility", eid, {"active": eid not in ("P", "U")}, p)
        if eid not in ("X", "Y"): add("origin", eid, {"kind": "root", "parents": []}, p)
    for qid, options, p in (("lineage", ["copy", "original"], 1), ("route", ["three", "four"], 3), ("decoration", ["root", "copy"], 2)):
        ir["choices"].append({"id": qid, "options": options, "citations": [spans[p]]})
    for eid, qid, parent, root_option, copy_option, p in (("X", "lineage", "P", "original", "copy", 1), ("Y", "decoration", "D", "root", "copy", 2)):
        add("origin", eid, {"kind": "root", "parents": []}, p, {qid: root_option})
        add("origin", eid, {"kind": "copy", "parents": [parent]}, p, {qid: copy_option})
    for cid in ("L", "M", "S", "N"):
        ir["entities"].append({"id": cid, "type": "claim", "operational": True, "citations": [spans[3 if cid == 'L' else 4]]})
    for option, refs in (("three", ["A", "B", "C"]), ("four", ["A", "B", "C", "D"])):
        add("support", "L", {"expr": {"any": [{"ref": x} for x in refs]}}, 3, {"route": option})
    for cid, eid in (("M", "X"), ("S", "B"), ("N", "U")): add("support", cid, {"expr": {"ref": eid}}, 4)
    for did, cid in (("RELEASE", "L"), ("LINEAGE", "M"), ("STEADY", "S"), ("LEGACY", "N")):
        ir["entities"].append({"id": did, "type": "decision", "operational": True, "citations": [spans[4]]})
        add("requirement", did, {"requires": [cid]}, 4)
    add("dependency", "A", {"relation": "parent", "refs": ["B"]}, 5, scope="historical")
    add("dependency", "A", {"relation": "parent", "refs": ["B"]}, 5, polarity="deny")
    return {"id": "constructed-v6d-demo", "title": "An unresolved lineage and a three-record stress witness", "source_documents": docs,
            "registry": {"evidence": ["A", "B", "C", "D", "P", "U", "X", "Y"], "claims": ["L", "M", "S", "N"], "decisions": ["RELEASE", "LINEAGE", "STEADY", "LEGACY"]},
            "source_ir": ir, "documents": [{"id": docs[0]["id"], "label": "Original-record sheet", "evidence_ids": ["A", "B", "C", "D", "P", "U"]},
                                         {"id": docs[1]["id"], "label": "X origin sheet", "evidence_ids": ["X"]},
                                         {"id": docs[2]["id"], "label": "Decorative note", "evidence_ids": ["Y"]}],
            "clarifications": [{"choice_id": "lineage", "label": "Is X an independent original rather than a copy of P?", "true_option": "original", "cost": 1},
                               {"choice_id": "route", "label": "Is D alone an admitted additional route for L?", "true_option": "four", "cost": 1},
                               {"choice_id": "decoration", "label": "Was the unused note Y copied from D?", "true_option": "copy", "cost": 1}]}
