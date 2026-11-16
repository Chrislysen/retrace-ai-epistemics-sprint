"""Offline four-state source-review workbench. Declarations are not source truth.

No inference requests, hidden reference graphs, probabilistic value of
information, implicit restoration, or automatic proposal application.
"""
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json

from .source_ir_v6h import compile_ir
from .source_ir_v6d import source_segments, model_source
from .tiered_v6h import family_supervaluation, require
from .graph_identity_v6h import graph_key
from .impact_v6h import compare_families, withdrawal_robustness, enable_withdraw_impact
from .refuter_gate_v6h import validate_refuter
from .typed_interventions_v6h import restore_then_withdraw_impact

SCHEMA = "retrace.workbench.v6h"
STATES = {"supported", "not_supported", "contested", "insufficient_provenance"}
FIELDS = {"id", "title", "source_documents", "registry", "source_ir", "documents", "clarifications", "target_decisions", "allowed_withdrawals"}


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def minimax_clarification(vectors, questions):
    """Exact worst-case additive cost until current grounded-status tuples agree.

Accurate available binary answers are assumed. Unknown is not a third DP
branch; it preserves candidates. Agreement on an unresolved status is not
resolution of the underlying provenance.
"""
    require(isinstance(vectors, dict) and 1 <= len(vectors) <= 32, "1..32 candidate status vectors required")
    ids = sorted(vectors)
    require(all(isinstance(cid, str) and cid for cid in ids), "Candidate IDs required")
    targets = sorted(vectors[ids[0]])
    for vector in vectors.values():
        require(isinstance(vector, dict) and sorted(vector) == targets and all(value in STATES for value in vector.values()), "Fixed four-state decision vectors required")
    require(isinstance(questions, list) and len(questions) <= 5, "At most five binary clarification questions")
    normalized = []; seen = set()
    for question in questions:
        require(isinstance(question, dict) and set(question) == {"id", "label", "cost", "answers"}, "Explicit question fields")
        qid = question["id"]
        require(isinstance(qid, str) and qid and qid not in seen, "Unique question ID")
        require(isinstance(question["label"], str) and 0 < len(question["label"]) <= 2048, "Bounded question label")
        require(type(question["cost"]) is int and 1 <= question["cost"] <= 1000000, "Positive integer question cost")
        require(isinstance(question["answers"], dict) and set(question["answers"]) == set(ids) and all(type(v) is bool for v in question["answers"].values()), "Boolean answer for every candidate required")
        seen.add(qid); normalized.append(deepcopy(question))
    normalized.sort(key=lambda row: row["id"])
    signatures = [tuple(vectors[cid][did] for did in targets) for cid in ids]
    masks = [sum(1 << i for i, cid in enumerate(ids) if q["answers"][cid]) for q in normalized]
    def members(mask): return [i for i in range(len(ids)) if mask & (1 << i)]
    def agreed(mask): return len({signatures[i] for i in members(mask)}) <= 1
    @lru_cache(maxsize=None)
    def solve(mask):
        if agreed(mask): return 0, None
        best = None
        for i, question in enumerate(normalized):
            yes, no = mask & masks[i], mask & ~masks[i]
            if not yes or not no: continue
            left, _ = solve(yes); right, _ = solve(no)
            if left is None or right is None: continue
            option = question["cost"] + max(left, right), i
            if best is None or option < best: best = option
        return best if best is not None else (None, None)
    def tree(mask):
        cost, i = solve(mask); remaining = [ids[j] for j in members(mask)]
        if i is None:
            return {"kind": "status_agreement", "candidate_ids": remaining, "decisions": deepcopy(vectors[remaining[0]]), "worst_case_cost": 0}
        question = normalized[i]
        return {"kind": "question", "id": question["id"], "label": question["label"], "cost": question["cost"],
                "worst_case_cost": cost, "candidate_ids": remaining,
                "branches": {"yes": tree(mask & masks[i]), "no": tree(mask & ~masks[i])}}
    full = (1 << len(ids)) - 1; cost, index = solve(full)
    root = tree(full) if cost is not None else None
    next_question = {key: normalized[index][key] for key in ("id", "label", "cost")} | {"worst_case_cost": cost} if index is not None else None
    blocking = [{"candidate_ids": [ids[i], ids[j]], "differing_decisions": [d for d in targets if vectors[ids[i]][d] != vectors[ids[j]][d]]}
                for i in range(len(ids)) for j in range(i + 1, len(ids)) if signatures[i] != signatures[j]
                and all(q["answers"][ids[i]] == q["answers"][ids[j]] for q in normalized)]
    return {"possible": cost is not None, "worst_case_cost": cost, "next_question": next_question,
            "tree": root, "blocking_pairs": blocking, "states_evaluated": solve.cache_info().currsize,
            "status_vectors_agree": agreed(full), "scope": "Exact minimax declared cost for current four-state decision vectors. No probabilities or expected information value. Unknown retains candidates; agreement on contested or insufficient provenance does not establish support or truth."}


def _prepare(brief, expected=None):
    require(isinstance(brief, dict) and set(brief) <= FIELDS and {"source_documents", "registry", "source_ir"} <= set(brief), "Supply only documented source bundle fields")
    for field in ("id", "title"):
        require(field not in brief or isinstance(brief[field], str) and len(brief[field]) <= 512, "Bounded title and ID")
    digest = fingerprint(brief)
    require(expected is None or digest == expected, "Source or interpretation changed; discard stale answers and vetoes")
    working = deepcopy(brief)
    compiled = compile_ir(working["source_ir"], working["source_documents"], working["registry"])
    return working, compiled, digest


def _questions(brief, compiled):
    choices = {row["id"]: row for row in compiled["original_ir"]["choices"]}
    supplied = brief.get("clarifications")
    if supplied is None:
        supplied = [{"choice_id": qid, "label": f"For {qid}, is {q['options'][1]} the applicable source reading rather than {q['options'][0]}?", "true_option": q["options"][1], "cost": 1} for qid, q in choices.items()]
    require(isinstance(supplied, list) and len(supplied) <= 5, "At most five clarification declarations")
    questions, catalog, seen = [], [], set()
    for item in supplied:
        require(isinstance(item, dict) and set(item) == {"choice_id", "label", "true_option", "cost"}, "Explicit clarification fields")
        key = item["choice_id"]
        require(isinstance(key, str) and key in choices and key not in seen, "Known unique clarification choice")
        seen.add(key); options = choices[key]["options"]
        require(item["true_option"] in options and isinstance(item["label"], str) and 0 < len(item["label"]) <= 2048, "Clarification label and true option")
        require(type(item["cost"]) is int and 1 <= item["cost"] <= 1000000, "Positive declared clarification cost")
        questions.append({"id": key, "label": item["label"], "cost": item["cost"],
                          "answers": {row["id"]: row["assignment"][key] == item["true_option"] for row in compiled["candidates"]}})
        catalog.append({**item, "false_option": next(option for option in options if option != item["true_option"]), "citations": choices[key]["citations"]})
    return questions, catalog


def _ids(values, known, label):
    require(isinstance(values, list) and all(isinstance(value, str) and value in known for value in values) and len(values) == len(set(values)), label + " must contain unique known IDs")
    return sorted(values)


def _state(brief, compiled, questions, state, expected):
    if state is None: state = {}
    require(isinstance(state, dict) and set(state) <= {"answers", "revoked_documents", "revoked_passages", "scenario_withdrawals"}, "Explicit answer/veto state required")
    if any(state.get(key) for key in state): require(expected is not None, "State changes require the current declaration fingerprint")
    evidence = {row["id"] for row in compiled["candidates"][0]["graph"]["evidence"]}
    source_ids = {doc["id"] for doc in brief["source_documents"]}
    groups = brief.get("documents", []); require(isinstance(groups, list) and len(groups) <= 64, "Document groups required as an array")
    index = {}
    for group in groups:
        require(isinstance(group, dict) and set(group) == {"id", "label", "evidence_ids"}, "Explicit document-veto group fields")
        require(isinstance(group["id"], str) and group["id"] in source_ids and group["id"] not in index, "Unique supplied document ID")
        require(isinstance(group["label"], str) and len(group["label"]) <= 512, "Bounded document label")
        _ids(group["evidence_ids"], evidence, "Document group evidence"); index[group["id"]] = group
    answers = state.get("answers", {})
    qindex = {q["id"]: q for q in questions}
    require(isinstance(answers, dict) and set(answers) <= set(qindex) and all(value is None or type(value) is bool for value in answers.values()), "Known Boolean or Unknown answers required")
    normalized = {"answers": deepcopy(answers), "revoked_documents": _ids(state.get("revoked_documents", []), index, "Document vetoes"),
                  "revoked_passages": _ids(state.get("revoked_passages", []), evidence, "Passage vetoes"),
                  "scenario_withdrawals": _ids(state.get("scenario_withdrawals", []), evidence, "Scenario withdrawals")}
    document_records = sorted({eid for docid in normalized["revoked_documents"] for eid in index[docid]["evidence_ids"]})
    locked = sorted(set(document_records) | set(normalized["revoked_passages"]) | set(normalized["scenario_withdrawals"]))
    retained = [row for row in compiled["candidates"] if all(answer is None or qindex[qid]["answers"][row["id"]] == answer for qid, answer in answers.items())]
    require(bool(retained), "Answers contradict the supplied interpretation family; reopen an answer instead of selecting an empty family")
    return normalized, retained, document_records, locked


def _record_flags(candidates, state, document_records):
    rows = {}
    for candidate in candidates:
        evidence = {row["id"]: row for row in candidate["graph"]["evidence"]}; memo = {}
        def bounds(eid):
            if eid not in memo:
                row = evidence[eid]
                active = row["active"] and eid not in document_records and eid not in state["revoked_passages"] and eid not in state["scenario_withdrawals"]
                parents = [bounds(parent) for parent in row["parents"]]
                memo[eid] = active and row["kind"] != "unknown" and all(lo for lo, _ in parents), active and all(hi for _, hi in parents)
            return memo[eid]
        for eid, row in evidence.items():
            lower, upper = bounds(eid)
            flags = rows.setdefault(eid, {"document_veto": eid in document_records, "passage_veto": eid in state["revoked_passages"], "scenario_veto": eid in state["scenario_withdrawals"], "by_candidate": {}})
            flags["by_candidate"][candidate["id"]] = {"original_active": row["active"], "effective_active": row["active"] and not any(flags[key] for key in ("document_veto", "passage_veto", "scenario_veto")),
                "usable_in_all_ancestry_completions": lower, "usable_in_some_ancestry_completions": upper, "kind": row["kind"], "parents": row["parents"]}
    return rows


def _bounded(call, *args, **kwargs):
    try: return {"status": "evaluated", **call(*args, **kwargs)}
    except ValueError as exc: return {"status": "unavailable", "reason": str(exc)}


def _typed_scope(brief, state, targets, evidence_ids):
    return {"document_groups": brief.get("documents", []),
            **{k: state[k] for k in ("revoked_documents", "revoked_passages", "scenario_withdrawals")},
            "allowed": sorted(set(brief.get("allowed_withdrawals", evidence_ids)) - set(state["scenario_withdrawals"])),
            "decisions": targets}


def analyze_workbench(brief, state=None, expected_fingerprint=None):
    # Validate even an empty/incomplete inventory before withholding its outputs.
    if state is not None:
        require(isinstance(state, dict) and set(state) <= {"answers", "revoked_documents", "revoked_passages", "scenario_withdrawals"}, "Explicit answer/veto state required")
        require("answers" not in state or isinstance(state["answers"], dict), "Answer state must be an object")
        require(all(key not in state or isinstance(state[key], list) for key in ("revoked_documents", "revoked_passages", "scenario_withdrawals")), "Veto state must be arrays")
    working, compiled, digest = _prepare(brief, expected_fingerprint)
    questions, catalog = _questions(working, compiled)
    common = {"schema": SCHEMA, "declaration_fingerprint": digest, "compilation": compiled, "question_catalog": catalog,
              "source_segments": source_segments(working["source_documents"]),
              "source_entailment_verified": False, "source_completeness": "unknown",
              "provenance": "constructed_offline_demo" if digest == fingerprint(demo_brief()) else "supplied_unverified_interpretation",
              "scope": "Exact declared finite semantics and source locations; not source truth, completeness, probability, or verified textual entailment. Unknown ancestry ranges over named availability gates, not arbitrary hidden graphs."}
    if compiled["registry_coverage_gaps"]:
        require(state is None or isinstance(state, dict) and not any(state.values()), "Incomplete inventory cannot reuse answers or vetoes")
        return {**common, "status": "inventory_gap", "warning_label": "Reference-Free Coverage Gap", "ready": False,
                "state": {"answers": {}, "revoked_documents": [], "revoked_passages": [], "scenario_withdrawals": []},
                "decisions": {}, "candidate_ids": [], "planner": None, "record_flags": {}}
    current, retained, document_records, locked = _state(working, compiled, questions, state, expected_fingerprint)
    graphs = [row["graph"] for row in retained]
    registry = {kind: {row["id"] for row in graphs[0][kind]} for kind in ("evidence", "claims", "decisions")}
    targets = _ids(working.get("target_decisions", sorted(registry["decisions"])), registry["decisions"], "Target decisions")
    allowed = _ids(working.get("allowed_withdrawals", sorted(registry["evidence"])), registry["evidence"], "Allowed withdrawals")
    allowed = sorted(set(allowed) - set(locked))
    family = family_supervaluation(graphs, document_vetoes=document_records, passage_vetoes=current["revoked_passages"], scenario_withdrawals=current["scenario_withdrawals"])
    vectors = {candidate["id"]: {did: outcome["decisions"][did]["state"] for did in targets} for candidate, outcome in zip(retained, family["candidates"])}
    filtered_questions = [{**q, "answers": {cid: answer for cid, answer in q["answers"].items() if cid in vectors}} for q in questions]
    planner = minimax_clarification(vectors, filtered_questions)
    decisions = {}
    for did in targets:
        row = family["decisions"][did]; statuses = sorted(set(row["states_by_candidate"]))
        decisions[did] = {**row, "state": statuses[0] if len(statuses) == 1 else None, "interpretations_disagree_on_status": len(statuses) > 1,
                          "status_counts": {status: row["states_by_candidate"].count(status) for status in statuses},
                          "by_candidate": {candidate["id"]: outcome["decisions"][did] for candidate, outcome in zip(retained, family["candidates"])}}
    kwargs = {"locked": locked, "allowed": allowed, "decisions": targets}
    return {**common, "status": "analyzed", "ready": True, "state": current, "candidate_ids": [row["id"] for row in retained],
            "eliminated_candidate_ids": [row["id"] for row in compiled["candidates"] if row not in retained],
            "analysis_fingerprint": fingerprint({"declaration": digest, "state": current}), "decisions": decisions, "family": family,
            "planner": planner, "record_flags": _record_flags(retained, current, document_records), "locked_vetoes": locked,
            "allowed_withdrawals": allowed, "target_decisions": targets,
            "robustness": _bounded(withdrawal_robustness, graphs, **kwargs),
            "hamming2": _bounded(enable_withdraw_impact, graphs, **kwargs),
            "typed_veto_release": _bounded(restore_then_withdraw_impact, graphs, **_typed_scope(working, current, targets, registry["evidence"]))}


def preview_refuter(brief, proposal_envelope, state=None, expected_fingerprint=None):
    require(isinstance(brief, dict) and {"source_documents", "registry"} <= set(brief), "Source bundle required")
    # Admission/citation errors terminate before any warning or proposal result.
    gated = validate_refuter(proposal_envelope, brief["source_documents"], brief["registry"])
    current = analyze_workbench(brief, state, expected_fingerprint)
    proposal = gated["compilation"]
    result = {"schema": "retrace.refuter-preview.v6h", "declaration_fingerprint": current["declaration_fingerprint"],
              "original_state": current["state"], "proposal_compilation": proposal, "proposal_applied": False,
              "objection_locations": gated["locations"], "raw_uncalibrated_warning_score": gated["raw_warning_score"],
              "source_entailment_verified": False, "scope": "Conditional addition of proposed readings, never automatic replacement or source truth. Verified spans establish location only."}
    if gated["status"] == "abstained":
        return {**result, "status": "abstained", "decision_impact": None, "hamming2": None,
                "scope": "The supplied refuter abstained. This does not certify source completeness, soundness, or absence of omissions. Active analysis is unchanged."}
    reason = ("Current identifier inventory is incomplete" if not current["ready"] else
              "Proposed identifier inventory is incomplete: " + ", ".join(proposal["registry_coverage_gaps"]) if proposal["registry_coverage_gaps"] else
              "Reset answered clarifications before comparing new choice structures" if any(type(value) is bool for value in current["state"]["answers"].values()) else None)
    if reason: return {**result, "status": "unavailable", "reason": reason, "decision_impact": None, "hamming2": None}
    old = [row["graph"] for row in current["compilation"]["candidates"]]; new = [row["graph"] for row in proposal["candidates"]]
    keys, proposed_keys = {graph_key(g) for g in old}, {graph_key(g) for g in new}
    inventory = lambda graph: {kind: {row["id"] for row in graph[kind]} for kind in ("evidence", "claims", "decisions")}
    if inventory(old[0]) != inventory(new[0]):
        return {**result, "status": "unavailable", "reason": "Compared interpretations have different operational typed inventories", "decision_impact": None, "hamming2": None}
    kwargs = {"locked": current["locked_vetoes"], "allowed": current["allowed_withdrawals"], "decisions": current["target_decisions"]}
    return {**result, "status": "preview_only", "declaration_comparison": {"same_graph_family": keys == proposed_keys,
                "current_readings_absent_from_proposal": len(keys - proposed_keys), "novel_proposed_readings": len(proposed_keys - keys),
                "scope": "Difference from the current supplied declaration is not proof of a source omission or a correct edit."},
            "decision_impact": _bounded(compare_families, old, new, **kwargs),
            "hamming2": _bounded(enable_withdraw_impact, old, new, **kwargs),
            "typed_veto_release": _bounded(restore_then_withdraw_impact, old, new, **_typed_scope(brief, current["state"], current["target_decisions"], {r["id"] for r in old[0]["evidence"]}))}


def prepared_source(brief):
    require(isinstance(brief, dict) and {"source_documents", "registry"} <= set(brief), "Source and registry required")
    return model_source(brief["source_documents"], brief["registry"])


def demo_brief():
    paragraphs = [
        "This is a constructed paper-exhibit review, not a model result. Evidence A, B, C, D, U, P and N are locally eligible originals with no parents. Original evidence Z has no parents but is locally ineligible. Evidence X is locally eligible with unidentified ancestry and no established named parent; it must not be silently treated as an independent original.",
        "Evidence Y is locally eligible. Its two admitted origin readings are root (an independent original, no parents) and copied (a copy with D as its sole parent). No decision uses Y.",
        "Claim RELEASE has exactly two positive-rule readings. In three, A alone, B alone and C alone are alternative complete routes. In four, the same alternatives are joined by D alone. There is no negative warrant for RELEASE.",
        "Claim DEBATE always has a positive warrant from P. Its two admitted negative-rule readings are no_objection (no negative warrant) and objection (N alone warrants not DEBATE). Positive and negative warrants have equal defeasible standing; an objection does not withdraw P.",
        "Claim SAFE has two positive routes: A unless usable U disables that particular route, or B alone. U does not affect the B route and supplies no negative warrant. Claim UNKNOWN has X as its only positive route. Claim DORMANT has one positive route requiring A and Z together. These three claims have no negative warrants.",
        "Decisions RELEASE_D, DEBATE_D, SAFE_D, UNKNOWN_D and DORMANT_D require only their correspondingly named claim. All three unresolved choices combine independently; every combination is admitted without a preferred actual reading. The stated origin and signed-warrant rules are exhaustive. Exclusions concern usability, not truth."
    ]
    docs = [{"id": f"demo-source-{i+1}", "title": "Constructed source note", "text": text} for i, text in enumerate(paragraphs)]
    spans = [row["span_id"] for row in source_segments(docs)]
    ir = {"schema": "retrace.source-ir.v6h", "entities": [], "bindings": [], "choices": [],
          "combination": {"mode": "cartesian", "assignments": [], "citations": [spans[5]]}, "propositions": []}
    def add(kind, target, body, index, when=None):
        ir["propositions"].append({"id": "p" + str(len(ir["propositions"]) + 1), "kind": kind, "target": target, "body": body,
                                   "scope": "current", "when": when or {}, "citations": [spans[index]], "bindings": []})
    for eid in ("A", "B", "C", "D", "U", "P", "N", "Z", "X", "Y"):
        index = 1 if eid == "Y" else 0
        ir["entities"].append({"id": eid, "type": "evidence", "operational": True, "citations": [spans[index]]})
        add("eligibility", eid, {"active": eid != "Z"}, index)
        if eid != "Y": add("origin", eid, {"kind": "unknown" if eid == "X" else "root", "parents": []}, index)
    for qid, options, index in (("route", ["three", "four"], 2), ("polarity", ["no_objection", "objection"], 3), ("decoration", ["root", "copied"], 1)):
        ir["choices"].append({"id": qid, "options": options, "citations": [spans[index]]})
    for option, kind, parents in (("root", "root", []), ("copied", "copy", ["D"])):
        add("origin", "Y", {"kind": kind, "parents": parents}, 1, {"decoration": option})
    no = {"const": False}; r = lambda name: {"ref": name}
    for cid, index in (("RELEASE", 2), ("DEBATE", 3), ("SAFE", 4), ("UNKNOWN", 4), ("DORMANT", 4)):
        ir["entities"].append({"id": cid, "type": "claim", "operational": True, "citations": [spans[index]]})
        did = cid + "_D"; ir["entities"].append({"id": did, "type": "decision", "operational": True, "citations": [spans[5]]})
        add("requirement", did, {"requires": [cid]}, 5)
    for option, refs in (("three", "ABC"), ("four", "ABCD")):
        add("support", "RELEASE", {"positive": {"any": [r(x) for x in refs]}, "negative": no}, 2, {"route": option})
    for option, negative in (("no_objection", no), ("objection", r("N"))):
        add("support", "DEBATE", {"positive": r("P"), "negative": negative}, 3, {"polarity": option})
    add("support", "SAFE", {"positive": {"any": [{"unless": {"support": r("A"), "undercutter": r("U")}}, r("B")]}, "negative": no}, 4)
    add("support", "UNKNOWN", {"positive": r("X"), "negative": no}, 4)
    add("support", "DORMANT", {"positive": {"all": [r("A"), r("Z")]}, "negative": no}, 4)
    return {"id": "constructed-v6h-demo", "title": "Scoped objections, a protected route, and a three-record witness", "source_documents": docs,
            "registry": {"evidence": ["A", "B", "C", "D", "U", "P", "N", "Z", "X", "Y"], "claims": ["RELEASE", "DEBATE", "SAFE", "UNKNOWN", "DORMANT"],
                         "decisions": [name + "_D" for name in ("RELEASE", "DEBATE", "SAFE", "UNKNOWN", "DORMANT")]},
            "source_ir": ir, "documents": [{"id": docs[0]["id"], "label": "Original-record inventory note", "evidence_ids": ["A", "B", "C", "D", "U", "P", "N", "Z", "X"]}],
            "clarifications": [{"choice_id": "route", "label": "Does the source policy admit D as the fourth independent route to RELEASE?", "true_option": "four", "cost": 1},
                               {"choice_id": "polarity", "label": "Does N provide an applicable negative warrant for not DEBATE?", "true_option": "objection", "cost": 1},
                               {"choice_id": "decoration", "label": "Is the unused decorative record Y copied from D?", "true_option": "copied", "cost": 1}]}
