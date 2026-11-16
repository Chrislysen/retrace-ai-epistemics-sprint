"""Eight new synthetic F5 cases; pure construction until explicit reviewed write.

Public prose is independently authored for scoped undercutters, polar warrants,
copy lineage and an unidentified origin. Gold, seeds and annotations stay in
separate fields. Neither source truth nor natural-distribution novelty is claimed.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.source_ir_v6d import source_segments
from retrace.source_ir_v6h import compile_ir
from retrace.tiered_v6h import SCHEMA, analyze, family_supervaluation, validate
from retrace.graph_identity_v6h import family_score


def ref(x): return {"ref": x}
def all_(*xs): return {"all": list(xs)}
def any_(*xs): return {"any": list(xs)}
def unless(support, undercutter): return {"unless": {"support": support, "undercutter": undercutter}}
def false(): return {"const": False}
def evidence(text, *, kind="root", parents=(), active=True):
    return {"text": text, "kind": kind, "parents": list(parents), "active": active}
def warrant(positive, text, negative=None):
    return {"positive": positive, "negative": false() if negative is None else negative, "text": text}


def controls(context):
    return {
        "S": evidence(f"The {context} record {{S}} is locally eligible original evidence with no parents. It is kept independently of the other records in this packet."),
        "F": evidence(f"Record {{F}} is the unissued {context} form. It is an original evidence record without parents, but it is locally ineligible in the initial inventory.", active=False),
    }


def control_claims():
    return {
        "T": warrant(ref("S"), "Claim {T} has one positive warrant: record {S} alone. No additional prerequisite belongs to that warrant."),
        "V": warrant(ref("F"), "Claim {V} receives its only positive warrant from {F}. The record's listing does not change its declared local eligibility."),
    }


def specs():
    """Each narrative and its operational rule are declared together, before output."""
    result = []
    result.append({
        "domain": "museum caption mounting", "title": "A route-specific obstruction and an independent caption check",
        "evidence": {
            "A": evidence("For a fictional caption-mounting exercise, {A} is the alignment checklist. It is a locally eligible original evidence record and has no parent records."),
            "B": evidence("The independently prepared spacing card is {B}. It is locally eligible original evidence, with no copying or other parent requirement."),
            "U": evidence("An active mounting-obstruction notice is recorded as evidence {U}. This locally eligible record is an original without parents; its effect on a warrant is specified separately."),
            **controls("label-stock")},
        "claims": {"C": warrant(any_(unless(ref("A"), ref("U")), ref("B")),
            "There are two complete positive routes to claim {C}. The alignment-checklist route uses {A}, but that route is disabled while {U} is usable. The second route uses {B} alone. The obstruction notice has no authority over the spacing-card route; it does not warrant not {C}."),
            "R": warrant(all_(ref("C"), ref("T")), "The release-stage claim {R} needs the positive warrants for {C} and {T} together. Neither component alone is sufficient."), **control_claims()},
        "doc_veto": "U", "passage_veto": "B", "seed_kind": "deficient", "defect": "omitted_route_undercutter"})
    result.append({
        "domain": "community workshop tool display", "title": "A temporary hold over both display routes",
        "evidence": {
            "A": evidence("Display-plan record {A} is an original, locally eligible item of evidence for a community workshop's toy-tool exhibit. No parent record is required."),
            "B": evidence("Layout alternative {B} was prepared independently. It is an original evidence record with an empty parent list and is locally eligible."),
            "U": evidence("The coordinator's temporary-hold record {U} is locally eligible original evidence without parents. Its applicability is a warrant-disabling condition, not a contrary observation."),
            **controls("display-tag")},
        "claims": {"C": warrant(unless(any_(ref("A"), ref("B")), ref("U")),
            "Ordinarily either {A} by itself or {B} by itself would warrant claim {C}. The temporary hold {U} applies to the entire inference to {C}, including both alternatives. While that hold is usable, neither route supplies a positive warrant. The hold supplies no negative warrant for not {C}."),
            "R": warrant(all_(ref("T"), ref("C")), "Claim {R} combines {T} with {C}: both positive prerequisites are needed in this one route."), **control_claims()},
        "doc_veto": "U", "passage_veto": "A", "seed_kind": "faithful_complete", "defect": None})
    result.append({
        "domain": "audio archive indexing", "title": "Opposite index warrants and a separately withheld sleeve card",
        "evidence": {
            "P": evidence("In a fictional audio-archive indexing exercise, listening note {P} is locally eligible original evidence. It was not copied from another record and has no parents."),
            "N": evidence("The separately authored correction note {N} is another locally eligible original evidence record without parents. Its signed conclusion is specified in the index rule."),
            "Q": evidence("Sleeve-position card {Q} is locally eligible original evidence with no required parent. It belongs to a later assembly check."),
            **controls("index-tab")},
        "claims": {"C": warrant(ref("P"),
            "Listening note {P} gives a positive warrant for claim {C}. Correction note {N} gives an equally defeasible negative warrant for not {C}. These are the only two signed routes. Neither note withdraws the other, and the correction is a rebuttal of the conclusion rather than an undercutter of the listening procedure.", ref("N")),
            "R": warrant(all_(ref("C"), ref("Q")), "For claim {R}, a positive argument for {C} must be combined with the sleeve card {Q}. The complete route requires both."), **control_claims()},
        "doc_veto": "N", "passage_veto": "Q", "seed_kind": "deficient", "defect": "omitted_negative_warrant"})
    result.append({
        "domain": "planetarium poster rehearsal", "title": "An independent route around a rebutted subclaim",
        "evidence": {
            "A": evidence("Poster-scale note {A} is an original locally eligible evidence record in this fictional planetarium rehearsal. It has no parents."),
            "N": evidence("A counter-note labelled {N} is locally eligible original evidence, independently recorded with no parents."),
            "B": evidence("The full-poster trial record {B} is locally eligible original evidence. It has no parent or dependency on the poster-scale note or counter-note."),
            **controls("rehearsal-token")},
        "claims": {"C": warrant(ref("A"),
            "Claim {C} receives a positive warrant from {A} and a negative warrant for not {C} from {N}. They have equal defeasible standing. No priority or withdrawal rule resolves their opposition.", ref("N")),
            "R": warrant(any_(ref("C"), ref("B")),
            "Claim {R} has two independent positive routes: a positive argument for {C}, or the complete trial record {B} alone. The route through {B} does not require {C}. Neither route supplies a negative warrant for {R}."), **control_claims()},
        "main": "R", "secondary": "C", "doc_veto": "B", "passage_veto": "N", "seed_kind": "faithful_complete", "defect": None})
    result.append({
        "domain": "seed-library drawer labels", "title": "Shared transcription origin with an optional second parent",
        "evidence": {
            "A": evidence("Master drawer-label ledger {A} is locally eligible original evidence in this fictional seed-library exercise. It has no parent record."),
            "X": evidence("Transcript {X} is locally eligible evidence. It copies {A}, which is its sole direct parent; it is not an independent original.", kind="copy", parents=["A"]),
            "Y": evidence("Locally eligible transcript {Y} certainly copies the master {A}. Its complete direct-parent rule has exactly two unresolved readings: master_only requires {A} alone, whereas master_and_check requires {A} together with {E}. Neither reading is preferred, and no third parent list is admitted.", kind="copy", parents=["A"]),
            "E": evidence("Supplementary cross-check {E} is a locally eligible original evidence record with no parent records."),
            "U": evidence("A legibility-objection record {U} is locally eligible original evidence without parents. It disables only the transcript route named in the claim rule."),
            "B": evidence("Independent drawer-map record {B} is locally eligible original evidence. It has no parents and is not copied from the master ledger."),
            **controls("drawer-token")},
        "claims": {"C": warrant(any_(unless(ref("X"), ref("U")), ref("Y")),
            "Claim {C} can be warranted by transcript {X}, unless usable {U} disables that particular route, or by transcript {Y} on its own. The objection does not disable the {Y} route. It supplies no negative warrant against {C}."),
            "R": warrant(any_(ref("C"), ref("B")), "Claim {R} accepts a positive argument for {C} as one full route and independent map {B} as another. Neither route needs the other."), **control_claims()},
        "choice": {"options": ["master_only", "master_and_check"], "document": "eY", "variant": "second_parent"},
        "doc_veto": "A", "passage_veto": "E", "seed_kind": "deficient", "defect": "copied_transcript_as_independent_root"})
    result.append({
        "domain": "miniature sculpture inventory", "title": "An unidentified origin revealed only when a hold is removed",
        "evidence": {
            "X": evidence("Record {X} concerns a fictional miniature sculpture. It is locally eligible, but its ancestry is unidentified: no named parent has been established, and it must not be treated as an independent original. The missing-origin condition remains unresolved rather than being filled with an invented record.", kind="unknown"),
            "U": evidence("Temporary-hold record {U} is locally eligible original evidence with no parents. The hold has the limited warrant-disabling effect set out below."),
            "B": evidence("An independent stand-layout record {B} is locally eligible original evidence. No source parent is required for it."),
            **controls("sculpture-token")},
        "claims": {"C": warrant(unless(ref("X"), ref("U")),
            "The only positive route to claim {C} uses {X}; that route is disabled while hold {U} is usable. The hold is not a negative warrant for not {C}, and its removal does not identify the missing ancestry."),
            "R": warrant(any_(ref("C"), ref("B")), "Claim {R} has a positive route through {C} and a separate sufficient route using {B} alone. The independent route does not require the unidentified-origin record."), **control_claims()},
        "doc_veto": "U", "passage_veto": "B", "seed_kind": "faithful_complete", "defect": None})
    result.append({
        "domain": "school puppet-theatre scenery", "title": "A waiver disables the rebuttal but not the positive warrant",
        "evidence": {
            "P": evidence("Scenery inspection {P} is locally eligible original evidence for a fictional puppet-theatre exercise. It has no parent records."),
            "N": evidence("Objection sheet {N} is a locally eligible original evidence record, with no copying or required source parent."),
            "U": evidence("Waiver record {U} is locally eligible original evidence without parents. Its scope is limited to the objection warrant."),
            "B": evidence("The separately prepared scenery mock-up {B} is locally eligible original evidence with no parents."),
            **controls("scenery-token")},
        "claims": {"C": warrant(ref("P"),
            "Inspection {P} warrants claim {C}. Objection {N} would warrant not {C}, except that usable waiver {U} disables that negative-warrant route. The waiver does not disable {P}, does not itself support {C}, and is not a withdrawal of either source. No other signed route is authorized.", unless(ref("N"), ref("U"))),
            "R": warrant(any_(ref("C"), ref("B")), "Claim {R} has one complete positive route through claim {C} and another through mock-up {B} alone. These are alternatives, not a joint requirement."), **control_claims()},
        "doc_veto": "U", "passage_veto": "B", "seed_kind": "deficient", "defect": "omitted_undercutter_of_negative_warrant"})
    result.append({
        "domain": "community clock-model exhibit", "title": "Two explicit scope readings and a dormant contrary note",
        "evidence": {
            "A": evidence("Mechanism sketch {A} is locally eligible original evidence in a fictional clock-model exhibit, without parent records."),
            "B": evidence("The independently prepared motion trial {B} is locally eligible original evidence and requires no source parent."),
            "U": evidence("Hold notice {U} is locally eligible original evidence without parents. Its stated scope is unresolved in exactly the two ways described in the policy note."),
            "N": evidence("Contrary note {N} is an original evidence record with no parents. It is locally ineligible in the initial inventory; mentioning its possible warrant does not activate the record.", active=False),
            **controls("clock-token")},
        "claims": {"C": warrant(any_(unless(ref("A"), ref("U")), ref("B")),
            "There are exactly two admitted interpretations of the positive rule for claim {C}. In route_scope, {A} is a sufficient route unless {U} disables it, while {B} remains a separate sufficient route. In whole_scope, either {A} or {B} would suffice but {U} disables the entire positive inference, covering both routes. No reading is preferred. In both readings, {N} alone supplies a negative warrant for not {C} when that record is usable; the hold has no effect on this negative route.", ref("N")),
            "R": warrant(all_(ref("C"), ref("T")), "Claim {R} needs positive arguments for {C} and {T} together. These are its complete prerequisites."), **control_claims()},
        "choice": {"options": ["route_scope", "whole_scope"], "document": "cC", "variant": "whole_scope"},
        "doc_veto": "U", "passage_veto": "B", "seed_kind": "faithful_complete", "defect": None})
    return result


def opaque(number, symbol):
    return "x" + hashlib.sha256(f"v6h-polar/{number}/{symbol}".encode()).hexdigest()[:9]


def replace_ids(value, mapping):
    if isinstance(value, dict): return {k: replace_ids(v, mapping) for k, v in value.items()}
    if isinstance(value, list): return [replace_ids(v, mapping) for v in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def graph_for(spec):
    graph = {"schema": SCHEMA,
             "evidence": [{"id": eid, **{k: deepcopy(row[k]) for k in ("kind", "active", "parents")}} for eid, row in spec["evidence"].items()],
             "claims": [{"id": cid, "positive": deepcopy(row["positive"]), "negative": deepcopy(row["negative"])} for cid, row in spec["claims"].items()],
             "decisions": [{"id": did, "requires": [cid]} for did, cid in (("D", spec.get("main", "C")), ("J", spec.get("secondary", "R")), ("K", "T"), ("H", "V"))]}
    variants = [graph]
    if spec.get("choice"):
        other = deepcopy(graph)
        if spec["choice"]["variant"] == "second_parent":
            next(row for row in other["evidence"] if row["id"] == "Y")["parents"] = ["A", "E"]
        else:
            next(row for row in other["claims"] if row["id"] == "C")["positive"] = unless(any_(ref("A"), ref("B")), ref("U"))
        variants.append(other)
    return variants


def mutate_seed(graphs, spec):
    result = deepcopy(graphs)
    for graph in result:
        claim = next(row for row in graph["claims"] if row["id"] == "C")
        if spec["defect"] == "omitted_route_undercutter": claim["positive"] = any_(ref("A"), ref("B"))
        elif spec["defect"] == "omitted_negative_warrant": claim["negative"] = false()
        elif spec["defect"] == "copied_transcript_as_independent_root":
            next(row for row in graph["evidence"] if row["id"] == "Y").update(kind="root", parents=[])
        elif spec["defect"] == "omitted_undercutter_of_negative_warrant": claim["negative"] = ref("N")
    while len(result) < 2: result.append(deepcopy(result[0]))
    return result


def reference_ir(spec, graphs, docs, doc_ids, mapping, number):
    spans = {row["document_id"]: row["span_id"] for row in source_segments(docs)}
    cite = lambda key: spans[doc_ids[key]]
    ir = {"schema": "retrace.source-ir.v6h", "entities": [], "bindings": [], "choices": [],
          "combination": {"mode": "cartesian", "assignments": [], "citations": []}, "propositions": []}
    for category, kind in (("evidence", "evidence"), ("claims", "claim"), ("decisions", "decision")):
        for row in graphs[0][category]:
            symbol = next(key for key, ident in mapping.items() if ident == row["id"])
            document = "e" + symbol if kind == "evidence" else "c" + symbol if kind == "claim" else "decisions"
            ir["entities"].append({"id": row["id"], "type": kind, "operational": True, "citations": [cite(document)]})
    choice_id = opaque(number, "choice")
    if spec.get("choice"):
        ir["choices"] = [{"id": choice_id, "options": spec["choice"]["options"], "citations": [cite(spec["choice"]["document"])]}]
    for category in ("evidence", "claims", "decisions"):
        for base in graphs[0][category]:
            ident = base["id"]; symbol = next(key for key, value in mapping.items() if value == ident)
            kinds = ("eligibility", "origin") if category == "evidence" else ("support",) if category == "claims" else ("requirement",)
            for kind in kinds:
                values = []
                for graph in graphs:
                    row = next(item for item in graph[category] if item["id"] == ident)
                    keys = ("active",) if kind == "eligibility" else ("kind", "parents") if kind == "origin" else ("positive", "negative") if kind == "support" else ("requires",)
                    values.append({key: deepcopy(row[key]) for key in keys})
                varied = any(value != values[0] for value in values)
                for index, body in enumerate(values if varied else values[:1]):
                    document = "e" + symbol if category == "evidence" else "c" + symbol if category == "claims" else "decisions"
                    ir["propositions"].append({"id": opaque(number, f"prop{len(ir['propositions'])}"), "kind": kind, "target": ident,
                        "body": body, "scope": "current", "when": {choice_id: spec["choice"]["options"][index]} if varied else {},
                        "citations": [cite(document)], "bindings": []})
    return ir


def build_cases():
    cases = []
    for number, spec in enumerate(specs(), 1):
        symbols = list(spec["evidence"]) + list(spec["claims"]) + ["D", "J", "K", "H"]
        if len(symbols) != len(set(symbols)): raise ValueError("Authored symbol collision")
        mapping = {symbol: opaque(number, symbol) for symbol in symbols}
        raw_graphs = graph_for(spec); graphs = [replace_ids(graph, mapping) for graph in raw_graphs]
        for graph in graphs:
            for category in ("evidence", "claims", "decisions"): graph[category].sort(key=lambda row: row["id"])
            validate(graph)
        docs, doc_ids = [], {}
        parts = [("e" + symbol, row["text"]) for symbol, row in spec["evidence"].items()]
        parts += [("c" + symbol, row["text"]) for symbol, row in spec["claims"].items()]
        main, secondary = spec.get("main", "C"), spec.get("secondary", "R")
        parts.append(("decisions", "Decision {D} requires claim {" + main + "} only. Decision {J} requires claim {" + secondary + "} only. Decision {K} requires {T} only; decision {H} requires {V} only. These requirements are exhaustive. All warrants are defeasible and have equal standing. No claim has a negative warrant unless a negative route is explicitly described. No additional source parent or support route may be inferred. Excluding an evidence record makes it ineligible under that veto, rather than declaring its content false."))
        # Different packet order is deterministic; rules never depend on adjacency.
        if number % 2 == 0: parts = parts[-1:] + parts[:-1]
        for key, text in parts:
            did = "d" + hashlib.sha256(f"polar-document/{number}/{key}".encode()).hexdigest()[:12]
            doc_ids[key] = did
            docs.append({"id": did, "title": spec["domain"].capitalize() + " note", "text": text.format_map(mapping)})
        registry = {category: [row["id"] for row in graphs[0][category]] for category in ("evidence", "claims", "decisions")}
        doc_symbol, passage_symbol = spec["doc_veto"], spec["passage_veto"]
        event_doc = doc_ids["e" + doc_symbol]
        states = {"initial": {"revoked_documents": [], "revoked_passages": []},
                  "withdrawn": {"revoked_documents": [event_doc], "revoked_passages": [mapping[passage_symbol]]},
                  "restored": {"revoked_documents": [], "revoked_passages": [mapping[passage_symbol]]}}
        groups = [{"id": doc_ids["e" + symbol], "label": "Source note for " + mapping[symbol], "evidence_ids": [mapping[symbol]]} for symbol in spec["evidence"]]
        family = [{"id": f"reading-{i+1}", "graph": graph, "assignment": {"reading": spec["choice"]["options"][i]} if spec.get("choice") else {}} for i, graph in enumerate(graphs)]
        seeds = [{"id": f"authored-seed-{i+1:02d}", "graph": replace_ids(graph, mapping)} for i, graph in enumerate(mutate_seed(raw_graphs, spec))]
        ir = reference_ir(spec, graphs, docs, doc_ids, mapping, number)
        compiled = compile_ir(ir, docs, registry)
        if not family_score(compiled["candidates"], family)["exact_family"]: raise AssertionError("Authored IR disagrees with manual graph family")
        state_gold = {}
        for name, state in states.items():
            document_vetoes = [mapping[doc_symbol]] if state["revoked_documents"] else []
            options = {"document_vetoes": document_vetoes, "passage_vetoes": state["revoked_passages"]}
            state_gold[name] = {"candidate_decisions": {row["id"]: analyze(row["graph"], **options)["decisions"] for row in family},
                                "family_decisions": family_supervaluation(graphs, **options)["decisions"]}
        cid = f"V6H-F5-{number:02d}"
        cases.append({"id": cid, "partition": "synthetic", "family_id": "F5", "family": "scoped_undercutters_and_polar_warrants",
            "within_family_index": number, "domain": spec["domain"], "title": spec["title"],
            "public": {"source_documents": docs, "registry": registry},
            "events": {"states": states, "document_groups": groups,
                       "withdrawal": {"add_document_vetoes": [event_doc], "add_passage_vetoes": [mapping[passage_symbol]]},
                       "restoration": {"clear_document_vetoes": [event_doc], "clear_passage_vetoes": []},
                       "semantics": "Separate cumulative vetoes over original local eligibility. Clearing a document veto leaves the passage veto and original inactive flags intact; no source truth is asserted."},
            "phases": {phase: {"state_name": state, "state": deepcopy(states[state])} for phase, state in (("hist_init", "initial"), ("hist_withdrawn", "withdrawn"), ("hist_restored", "restored"), ("evt_no_commit", "withdrawn"), ("fresh_withdrawn", "withdrawn"), ("fresh_restored", "restored"))},
            "authored_seed_pool": {"provenance": "Constructed controlled seed declarations; separate from ordinary prose extraction input", "candidates": seeds},
            "long_context_selected": number in (1, 4, 5, 8),
            "evaluation": {"source_family": family, "reference_ir": ir, "state_gold": state_gold,
                "seed_kind": spec["seed_kind"], "seed_defect_recipe": spec["defect"], "semantic_key_ids": mapping,
                "uncertainty_count": int(bool(spec.get("choice"))), "unknown_ancestry_ids": [row["id"] for row in graphs[0]["evidence"] if row["kind"] == "unknown"],
                "max_evidence_ids": len(registry["evidence"]), "authorship": "New controlled synthetic prose and explicit operationalization; no claim of natural-document representativeness or independent human annotation", "independent_audit": "pending"}})
    return cases


def build():
    cases = build_cases()
    return {"schema": "retrace.frontier-v6h-polar-cases.v1", "cases": cases,
            "long_context_subset_ids": [case["id"] for case in cases if case["long_context_selected"]],
            "scope": "Eight newly authored F5 synthetic packets, four deficient and four faithful controlled seeds. Public prose, supplied seed declarations, and evaluation-only gold have separate fields."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-reviewed-data", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data/frontier-v6h-polar-cases.json")
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(build(), stream, ensure_ascii=False, indent=2); stream.write("\n")
