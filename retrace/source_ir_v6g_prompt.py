"""Complete prospective prompt for the unchanged v6c/v6d compiler.

This changes instructions only. It does not repair recorded output, add relation
types, change semantic admission, or read any benchmark/reference material.
"""
import json

from .source_ir_v6d import model_source, source_segments


CONTRACT = r'''Interpret the supplied source_segments as source data. Produce a source-faithful declaration under the following exact bounded language. Return one bare JSON object, no prose or Markdown. Schema validity and exact source locations do not prove semantic entailment or completeness.

TOP LEVEL: exactly {"schema":"retrace.source-ir.v6d","entities":[],"bindings":[],"choices":[],"combination":{"mode":"cartesian","assignments":[],"citations":[]},"propositions":[]}.
All fields shown below are mandatory, including empty arrays/objects. No additional keys, comments, duplicate JSON keys, NaN, Infinity or null placeholders. Booleans must be true/false, never 0/1 or strings. IDs use 1–128 ASCII letters/digits/underscores/hyphens; standalone '-' is forbidden. Entity IDs, binding IDs, choice IDs and proposition IDs must each be unique within their own collection. Only entity IDs must be literal source identifiers; use separate descriptive local IDs for bindings, choices and propositions.

CITATIONS: every citations field contains 1–8 distinct span_id STRINGS copied from the provided source_segments. The only optional empty citations are combination.citations for a Cartesian policy with zero or one choice. A binding's mention and antecedent are each ONE span_id string, not an array/object/quote. Never invent a span, source ID, hash or offsets. Read connected text across segments; segmentation does not decide scope or meaning.

ENTITIES: {"id":"SOURCE_ID","type":"evidence"|"claim"|"decision","operational":true|false,"citations":[SPAN_ID]}.
Declare all current operational entities needed by the source; historical/proposed-only named entities can be operational=false. At least one entity must be operational. Every entity's exact ID must occur as a complete identifier token in at least one of its citation spans. The registry classifies supplied IDs but is not guaranteed complete; a separately named source ID may be declared with its source-grounded type. An existing registry ID cannot change type. Do not invent an identifier for an unnamed entity. Every reference in a body must name a declared entity of the required type; 'unknown', missing IDs and natural-language phrases cannot substitute for references.

BINDINGS: top-level rows are {"id":"bind1","entity":"DECLARED_ENTITY_ID","mention":SPAN_ID,"antecedent":SPAN_ID}. Use bindings when an interpreted pronoun/alias matters. The antecedent span must literally contain that entity ID. A proposition's bindings is an array of 0–8 distinct top-level binding ID STRINGS, e.g. ["bind1"], NEVER embedded binding objects. Every listed binding's entity must be the proposition target or one of its body references, and the proposition must cite the mention span (overlap is what is checked). The binding records your interpretation; it is not automatic coreference proof. Do not choose a nearest antecedent merely for convenience.

PROPOSITIONS: exactly {"id":"p1","kind":KIND,"target":"DECLARED_ENTITY_ID","body":BODY,"scope":"current"|"historical"|"hypothetical"|"proposed","polarity":"assert"|"deny","when":{},"citations":[SPAN_ID],"bindings":[]}.
Each body has exactly the keys specified. Only kind=dependency accepts polarity=deny; every other kind uses assert. No proposition may reference its own target. Current targets must be operational. Current asserted body references must also be operational; a current dependency denial may refer to a declared nonoperational historical entity. Noncurrent rows still obey all schema/type/citation rules, but do not create current graph definitions or constraints.

DEFINITION KINDS:
eligibility: evidence target; {"active":BOOLEAN}. This is ORIGINAL LOCAL eligibility, never the result of a document/passage veto, ancestor failure or current support calculation. External withdrawal/restoration states are applied separately.
origin: evidence target; {"kind":"root","parents":[]} OR {"kind":"copy","parents":[EVIDENCE_IDS]}. A root has zero parents; a copy has at least one. The list is the COMPLETE direct-parent conjunction; every parent is required in addition to the record's own local eligibility. Both keys are mandatory. An indirect ancestor is not an additional direct parent unless the source says so.
support: claim target; {"expr":EXPR}. This is the COMPLETE collection of sufficient routes. EXPR has exactly one constructor: {"ref":"EVIDENCE_OR_CLAIM_ID"}, {"all":[EXPR,...]}, {"any":[EXPR,...]}, or {"none":true}. all is AND and any is OR, each with 2–250 children. Identical child expressions in the same group are forbidden. none explicitly gives no support route. There is no true literal, NOT constructor, arbitrary formula string or decision reference. Preserve nested grouping and all shared qualifiers. A-alone and B-alone as two warrants are any(ref A,ref B), not all(A,B). A common Q required with either becomes all(any(ref A,ref B),ref Q).
requirement: decision target; {"requires":[CLAIM_IDS]}. This is a COMPLETE nonempty conjunction. Decisions cannot directly require evidence or other decisions. Do not invent a helper claim absent from the source to evade typing.
unknown_ancestry: evidence target; {"description":"nonempty description of the unnamed or unresolved ancestor, at most 1024 characters"}. The target is a named existing evidence entity; the unknown ancestor is not a fabricated entity/reference. Its eligibility is still required. You may omit only that target's origin when unknown_ancestry is active, or retain a known COPY origin plus this unresolved obligation. A ROOT origin and current unknown ancestry on the same target conflict. One current unknown ancestor in any admitted assignment withholds the entire executable family; it never licenses a partial graph or invented root. This is not a general-purpose error/status field for other unsupported structures.

DEPENDENCY CONSTRAINTS: {"relation":RELATION,"refs":[IDS]}. These validate definitions; they do not add edges, fill missing definitions or prune choices. refs is a nonempty, unique list, at most 250 elements, excluding the target. Target and operand types and the EXACT predicate are:
parent: EVIDENCE target, EVIDENCE refs. Every listed ref is a DIRECT parent of the target. Extra direct parents are allowed by this predicate; only origin declares the complete set.
ancestor: EVIDENCE target, EVIDENCE refs. Every listed ref is reachable by one or more parent edges. It need not be a direct parent.
necessary: evidence, claim OR decision target; evidence OR claim refs. Every listed ref is structurally mandatory on every possible support derivation of the target after recursively following parents and routes. Local active flags and external vetoes are ignored for this structural check. A target with no structurally possible route makes the predicate false, not vacuously true. A ref absent from one possible route is not necessary.
sufficient_route: CLAIM target ONLY; evidence OR claim refs. The listed set must be EXACTLY one direct clause in the claim's declared DNF support list after distributing all/any. It is NOT general logical sufficiency, a transitive route, a subset/superset test, or a predicate on evidence/decisions. Example: if EXR has only ref EXC and EXC requires EXA+EXB, sufficient_route EXR [EXC] is true; sufficient_route EXR [EXA,EXB] is false even though EXA/EXB may be upstream prerequisites. Additional operands do not match a smaller direct clause.
For assert the whole predicate must hold. For deny its whole predicate must be false: deny parent[A,B] says 'not both direct parents', not 'neither is a parent'. Use separate singleton denials when the source denies each. The same grouped-negation rule applies to ancestor/necessary/sufficient_route. A false current constraint rejects the whole output; it never filters out an inconvenient assignment.

Use constraints only when their exact structural meaning matches the source. Complete origin/support/requirement definitions already encode exhaustive parents and warrants. For a copy requiring A and B together, 'A alone cannot sustain the copy' is represented by the complete origin parents [A,B]; do NOT add a sufficient_route constraint on that evidence record. Likewise a complete claim definition already excludes unlisted direct routes. Redundant constraints are unnecessary. Do not translate every natural-language 'not sufficient' sentence into sufficient_route deny: that predicate is only exact direct claim-clause membership. The language cannot independently express arbitrary Boolean implication, general semantic insufficiency or a negated support literal. Do not invent a relation or pretend a different predicate has that meaning.

CHOICES: {"id":"u1","options":["left","right"],"citations":[SPAN_ID]}. Zero to five binary axes; option names must be distinct IDs. Proposition when maps zero or more declared choice IDs to one of their option names. All conditions in when are conjunctive. An empty when applies to every assignment. Every choice must condition at least one current proposition. Each operational evidence needs exactly one current eligibility and one current origin in EVERY admitted assignment, except the origin exception for unknown_ancestry. Every operational claim needs exactly one support, and every operational decision exactly one requirement. Two simultaneous definitions conflict even if equal. Conditional alternatives must therefore be mutually exclusive and complete. Definitions for all entities form an acyclic graph in each assignment; no self-reference or cycle is allowed.
combination always has mode, assignments and citations. Cartesian mode uses assignments=[] and enumerates all 2^u combinations; with two or more axes, cite the source licensing their independent combination. Listed mode requires 1–32 distinct COMPLETE assignments, each mapping EVERY choice ID to an option; every option of every declared choice must occur somewhere in that list. Listed mode always needs citations. Use listed assignments for coupled alternatives; do not assume independence. No declared option or invalid branch is silently dropped. Equivalent graphs from different assignments are retained. Operational entity membership is fixed across assignments; the schema does not support optional-node worlds.

BOUNDS: 1–250 total entities; 0–256 bindings; 1–2048 propositions; at most 5 choices/32 worlds. Expression depth at most 16 (root depth 0), at most 4096 expression nodes per support, and at most 256 intermediate/final DNF clauses. The compact rendering of each compiled graph must fit 65,536 characters. Output text and the expanded INPUT IR serialized as JSON by the validator each have a 524,288-character limit: every repeated cited span contributes its full text after expansion, so compact span references do not remove this bound. This check precedes compiled annotations such as citation hashes and normalized support clauses; the returned compilation object has no matching size guarantee. Supplied sources have at most 64 documents/524,288 characters and 4096 inventory segments. Exceeding a bound is rejection, not truncation. Parent/reference lists contain unique IDs. These bounds are not permission to omit source requirements.

Before emitting, check all declared types, exact fields, citations, per-proposition binding IDs, full per-assignment definitions and dependency predicate meanings. Preserve scoped denials and meaningful alternatives through valid definitions/constraints; do not add unsupported redundant assertions. Do not output verdicts, gold answers, confidence, generated source IDs, invented missing ancestors or a repaired partial family. Successful compilation is only agreement with your declared contract; source completeness and entailment remain unverified.'''


def binding_example():
    """Invented EX namespace; no benchmark source or gold is accessed."""
    documents = [
        {"id": "EX-source-1", "text": "Original evidence EXA is locally ineligible; original evidence EXB is locally eligible. Both have no parents. Evidence EXC is a locally eligible certificate."},
        {"id": "EX-source-2", "text": "This certificate requires EXA and EXB jointly as its complete direct inputs. Neither input alone replaces the pair. Claim EXR accepts EXC alone as its complete warrant. Decision EXD requires only EXR. There is no uncertainty about these current rules."},
    ]
    registry = {"evidence": ["EXA", "EXB", "EXC"], "claims": ["EXR"], "decisions": ["EXD"]}
    a, b = [row["span_id"] for row in source_segments(documents)]
    ir = {"schema": "retrace.source-ir.v6d", "entities": [],
          "bindings": [{"id": "EX-bind-cert", "entity": "EXC", "mention": b, "antecedent": a}],
          "choices": [], "combination": {"mode": "cartesian", "assignments": [], "citations": []}, "propositions": []}
    for ident, category, span in [("EXA", "evidence", a), ("EXB", "evidence", a), ("EXC", "evidence", a), ("EXR", "claim", b), ("EXD", "decision", b)]:
        ir["entities"].append({"id": ident, "type": category, "operational": True, "citations": [span]})
    rows = [("EXA", "eligibility", {"active": False}, a), ("EXA", "origin", {"kind": "root", "parents": []}, a),
            ("EXB", "eligibility", {"active": True}, a), ("EXB", "origin", {"kind": "root", "parents": []}, a),
            ("EXC", "eligibility", {"active": True}, a), ("EXC", "origin", {"kind": "copy", "parents": ["EXA", "EXB"]}, b),
            ("EXR", "support", {"expr": {"ref": "EXC"}}, b), ("EXD", "requirement", {"requires": ["EXR"]}, b)]
    for number, (target, kind, body, span) in enumerate(rows):
        ir["propositions"].append({"id": "EX-p" + str(number), "kind": kind, "target": target, "body": body,
                                   "scope": "current", "polarity": "assert", "when": {}, "citations": [span],
                                   "bindings": ["EX-bind-cert"] if kind == "origin" and target == "EXC" else []})
    return documents, registry, ir


_documents, _registry, _ir = binding_example()
IR_V6G_INSTRUCTIONS = (
    CONTRACT + "\n\nCOMPLETE FORMATTING/BINDING EXAMPLE ONLY. EX-prefixed IDs and spans are not task data. "
    "Do not copy its facts into your answer. The complete copy origin already captures the joint-input condition; "
    "no evidence-target sufficient_route denial is added.\nExample input:\n"
    + json.dumps(model_source(_documents, _registry), ensure_ascii=False, separators=(",", ":"))
    + "\nExample output:\n" + json.dumps(_ir, ensure_ascii=False, separators=(",", ":"))
    + "\nFor the actual packet use only its own source IDs and span references. Emit the complete JSON object directly."
)
