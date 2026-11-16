"""Bounded, reference-free conservation checks for explicit source cues.

This is a recognizer, not a general natural-language parser or a truth oracle.
A gap means a recognized source cue has zero matching structural witnesses in
the supplied candidate union. It does not establish the source's correctness,
prove a semantic omission, or certify completeness when no gap is found.
No candidate, reference graph, factual answer, or active flag is synthesized.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from .compact_graph import validate_explicit_graph

MAX_SOURCE_CHARS = 65_536
MAX_DOCUMENTS = 32
MAX_CANDIDATES = 16
MAX_NODES = 250
MAX_OBLIGATIONS = 2_048
WARNING_LABEL = "Reference-Free Coverage Gap"
CATEGORIES = ("evidence", "claims", "decisions")
ID = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
TYPE_PREFIX = re.compile(r"^(?:the\s+)?(?:evidence|record|claim|decision)\s+", re.I)
CUE = re.compile(r"\b(?:cop(?:y|ies|ied)|transcrib\w*|transcription|deriv\w*|duplicat\w*|"
                 r"reproduc\w*|extract\w*|requires?|needs?|depends?|conditional|contingent|"
                 r"support\w*|suffic\w*|prerequisite|only\s+(?:if|when|while)|source|ancestor|"
                 r"worksheet|shared|unresolved|uncertain|unknown)\b", re.I)
NEGATED = re.compile(r"\b(?:not|never|neither|no\s+longer|without|unless|except|denied|false)\b|n['’]t\b", re.I)
HYPOTHETICAL = re.compile(r"\b(?:hypothetical\w*|suppos\w*|imagine|counterfactual|could|would|might)\b|"
                        r"\b(?:for\s+example|as\s+an?\s+example|if\s+we)\b|^\s*if\b", re.I)
ARCHIVED = re.compile(r"\b(?:archived|historical|discarded|rejected|superseded|irrelevant)\s+"
                     r"(?:example|quotation|quote|rule|draft|policy)\b", re.I)
AUTHORITATIVE_QUOTE = re.compile(
    r'^(?:the\s+)?(?:actual|current|operative|authoritative|adopted|binding)\s+'
    r'(?:rule|policy|requirement|specification)\s*(?:(?:states|says|is|reads)\s*)?[:,]?\s*'
    r'["“](?P<body>.*)["”]\s*$', re.I | re.S)
ALIAS = re.compile(r'\b(?:Evidence|Record|Claim|Decision)\s+([A-Za-z0-9_-]+)\s+'
                   r'is\s+(?:called|named|labeled)\s+["“]([^"”\n]{1,160})["”]', re.I)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _name(value):
    return re.sub(r"\s+", " ", re.sub(r"^(?:the|an?|this)\s+", "", value.strip(), flags=re.I)).casefold()


def _sources(prose):
    if isinstance(prose, str):
        prose = [{"id": "source", "text": prose}]
    _require(isinstance(prose, list) and 1 <= len(prose) <= MAX_DOCUMENTS, "Supply a source string or 1–32 source documents")
    result, names, total = [], set(), 0
    for doc in prose:
        _require(isinstance(doc, dict) and set(doc) == {"id", "text"}, "Source documents need exactly id and text")
        _require(isinstance(doc["id"], str) and 0 < len(doc["id"]) <= 128 and doc["id"] not in names,
                 "Source document IDs must be unique nonempty strings of at most 128 characters")
        _require(isinstance(doc["text"], str), "Source text must be a string")
        total += len(doc["text"])
        _require(total <= MAX_SOURCE_CHARS, "Source exceeds the 65,536 code-point limit")
        _require(not any(0xD800 <= ord(c) <= 0xDFFF for c in doc["text"]), "Source contains an unpaired Unicode surrogate")
        names.add(doc["id"])
        result.append(dict(doc))
    return result


def _prepare(candidates, registry):
    _require(isinstance(candidates, list) and 1 <= len(candidates) <= MAX_CANDIDATES, "Supply 1–16 candidates")
    expected = None
    if registry is not None:
        _require(isinstance(registry, dict) and set(registry) == set(CATEGORIES), "Registry needs three typed ID arrays")
        expected = {}
        for category in CATEGORIES:
            values = registry[category]
            _require(isinstance(values, list), "Registry values must be arrays")
            for ident in values:
                _require(isinstance(ident, str) and len(ident) <= 128 and ID.fullmatch(ident) and ident != "-" and ident not in expected,
                         "Registry IDs must be unique ASCII identifiers of at most 128 characters across types")
                expected[ident] = category
        _require(len(expected) <= MAX_NODES, "Registry exceeds 250 nodes")
    rows, ids, types, aliases = [], set(), dict(expected or {}), {}
    for candidate in candidates:
        _require(isinstance(candidate, dict), "Candidate must be an object")
        cid, original = candidate.get("id"), candidate.get("graph")
        _require(isinstance(cid, str) and 0 < len(cid) <= 128 and cid not in ids, "Candidate IDs must be unique nonempty strings")
        ids.add(cid)
        _require(isinstance(original, dict) and set(original) == set(CATEGORIES), "Candidate graph must have exactly the three node arrays")
        graph = deepcopy(original)
        node_labels = []
        for category in CATEGORIES:
            _require(isinstance(graph[category], list), "Graph categories must be arrays")
            for node in graph[category]:
                _require(isinstance(node, dict), "Nodes must be objects")
                label = node.pop("label", None)
                if label is not None:
                    _require(isinstance(label, str) and 0 < len(label) <= 512, "Labels must be nonempty strings of at most 512 characters")
                    node_labels.append((node.get("id"), label))
        graph = validate_explicit_graph(graph)
        for ident, label in node_labels:
            aliases.setdefault(_name(label), set()).add(ident)
        index = {node["id"]: node for category in CATEGORIES for node in graph[category]}
        for category in CATEGORIES:
            for node in graph[category]:
                ident = node["id"]
                _require(len(ident) <= 128, "Node IDs may contain at most 128 characters")
                _require(expected is None or expected.get(ident) == category, "Candidate IDs/types must belong to the supplied registry")
                _require(ident not in types or types[ident] == category, "Candidate node types disagree")
                types[ident] = category
        rows.append({"id": cid, "graph": graph, "index": index})
    _require(len(types) <= MAX_NODES, "Candidate-union registry exceeds 250 nodes")
    return sorted(rows, key=lambda row: row["id"]), types, aliases


def _units(doc):
    # Keep punctuation within quoted rules so a quoted sentence can be classified
    # using its surrounding framing. Offsets always index the untouched text.
    text, start, quote, code = doc["text"], 0, None, False
    i = 0
    while i < len(text):
        if text.startswith("```", i):
            code = not code
            i += 3
            continue
        char = text[i]
        if not code and char in '\"“”':
            if quote is None and char in '\"“':
                quote = '"' if char == '"' else '”'
            elif char == quote:
                quote = None
        if char == "\n" or (char in ".!?;" and quote is None and not code):
            end = i + (char != "\n")
            if text[start:end].strip():
                yield start, end, code or quote is not None
            start = i + 1
        i += 1
    if text[start:].strip():
        yield start, len(text), code or quote is not None


def _span(doc, start, end):
    return {"document_id": doc["id"], "start": start, "end": end, "text": doc["text"][start:end]}


def _entity(raw, types, aliases):
    raw = TYPE_PREFIX.sub("", raw.strip()).strip(" \t()[]")
    if raw in types:
        return raw, None
    found = aliases.get(_name(raw), set())
    if len(found) == 1:
        return next(iter(found)), None
    return None, "ambiguous_entity_label" if found else "unaligned_source_entity"


def _references(raw, types, aliases):
    raw = re.sub(r"\s+(?:(?:is|are|remains?)\s+)?(?:usable|eligible|available|present|valid)\s*$", "", raw.strip(), flags=re.I)
    raw = re.sub(r"^(?:both|either)\s+", "", raw, flags=re.I)
    has_and, has_or = bool(re.search(r"\band\b|,", raw, re.I)), bool(re.search(r"\bor\b", raw, re.I))
    if has_and and has_or:
        return [], None, [{"text": raw, "reason": "unresolved_boolean_grouping"}]
    connector = "or" if has_or else "and"
    pieces = re.split(r"\s+(?:and|or)\s+|\s*,\s*", raw, flags=re.I)
    values, unresolved = [], []
    for piece in pieces:
        ident, reason = _entity(piece, types, aliases)
        if reason:
            unresolved.append({"text": piece, "reason": reason})
        else:
            values.append(ident)
    if len(values) != len(set(values)):
        unresolved.append({"text": raw, "reason": "repeated_operand_needs_review"})
    return values, connector, unresolved


def _recognize(text):
    """Return only registered relation forms; unmatched cue-bearing prose abstains."""
    text = text.strip().rstrip(".!?;").strip()
    patterns = (
        ("lineage_direct", r"(.+?)\s+(?:(?:is|are|was|were|has been|have been)\s+)?(?:copied|transcribed|duplicated|reproduced|extracted)\s+from\s+(.+)"),
        ("lineage_direct", r"(.+?)\s+(?:is|are|was|were)\s+(?:a\s+)?(?:copy|copies|transcription|duplicate)\s+of\s+(.+)"),
        ("lineage_ancestor", r"(.+?)\s+(?:(?:is|are|was|were)\s+)?derived\s+from\s+(.+)"),
        ("mandatory", r"(.+?)\s+(?:requires?|needs?|depends? on|is conditional on|is contingent on)\s+(.+)"),
        ("mandatory", r"(.+?)\s+(?:is\s+)?(?:supported|usable|eligible|warranted|valid)\s+only\s+(?:if|when|while|with)\s+(.+)"),
        ("sufficient", r"(.+?)\s+(?:is\s+)?(?:supported|warranted|established|authorized)\s+(?:by|if|when)\s+(.+)"),
        ("alternative_routes", r"(.+?)\s+has\s+(?:(?:two|three|four)\s+)?alternative\s+(?:sufficient\s+)?(?:support\s+)?routes?\s+(.+)"),
    )
    for kind, pattern in patterns:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            target, body = match.groups()
            choice = re.fullmatch(r"exactly one of\s+(.+?),?\s+but\s+(?:which|the selection)\s+is\s+(?:unknown|unresolved)", body, re.I)
            if choice and kind in ("mandatory", "lineage_direct"):
                return "choice_" + kind, target, choice[1].rstrip(", ")
            return kind, target, body
    match = re.fullmatch(r"(.+?)\s+(?:alone\s+)?(?:suffices for|is sufficient for|supports)\s+(.+)", text, re.I)
    if match:
        return "sufficient", match[2], match[1]
    return None


def _paths(row, start, ancestor, types):
    if start not in row["index"] or ancestor not in row["index"]:
        return None
    pending = [(start, [start])]
    seen = set()
    while pending:
        ident, path = pending.pop(0)
        if ident in seen:
            continue
        seen.add(ident)
        if ident == ancestor and len(path) > 1:
            return path
        node = row["index"][ident]
        deps = node["parents"] if types[ident] == "evidence" else (
            sorted({x for clause in node["supports"] for x in clause}) if types[ident] == "claims" else node["requires"])
        pending.extend((dep, path + [dep]) for dep in sorted(deps))
    return None


def _mandatory(row, ident, types, cache):
    if ident in cache:
        return cache[ident]
    node = row["index"][ident]
    category = types[ident]
    if category == "evidence":
        routes = [node["parents"]] if node["kind"] == "copy" else [[]]
    else:
        routes = node["supports"] if category == "claims" else [node["requires"]]
    expanded = [set().union(*(_mandatory(row, x, types, cache) for x in route)) for route in routes]
    # An empty support rule is not admitted as a vacuous conservation witness.
    mandatory = set.intersection(*expanded) if expanded else set()
    cache[ident] = {ident} | mandatory
    return cache[ident]


def _representation(obligation, row, types):
    target = obligation["target_ids"][0]
    refs, kind = obligation["referenced_ids"], obligation["representation_type"]
    node = row["index"].get(target)
    if node is None:
        return None
    if kind == "node_presence":
        return {"candidate_id": row["id"], "node_id": target}
    if any(ref not in row["index"] for ref in refs):
        return None
    if kind in ("direct_parent_conjunction", "ancestor_paths"):
        if types[target] != "evidence" or any(types[ref] != "evidence" for ref in refs):
            return None
        if kind == "direct_parent_conjunction":
            return {"candidate_id": row["id"], "parent_edges": [[target, ref] for ref in refs]} if node["kind"] == "copy" and set(refs) <= set(node["parents"]) else None
        paths = [_paths(row, target, ref, types) for ref in refs]
        return {"candidate_id": row["id"], "paths": paths} if all(paths) else None
    if kind == "mandatory_conjunction":
        needed = _mandatory(row, target, types, {}) - {target}
        return {"candidate_id": row["id"], "mandatory_ids": refs} if set(refs) <= needed else None
    if kind in ("sufficient_conjunction", "alternative_sufficient_routes"):
        if types[target] != "claims":
            return None
        required = [set(refs)] if kind == "sufficient_conjunction" else [{ref} for ref in refs]
        routes = [set(route) for route in node["supports"]]
        return {"candidate_id": row["id"], "support_routes": [sorted(route) for route in required]} if all(route in routes for route in required) else None
    if kind == "exclusive_choice_branch":
        if obligation["choice_relation"] == "lineage_direct":
            valid = types[target] == "evidence" and node["kind"] == "copy" and node["parents"] == refs
        else:
            valid = types[target] == "claims" and node["supports"] == [refs]
        return {"candidate_id": row["id"], "selected_only": refs[0]} if valid else None
    return None


def _compiler_annotations(compilation, rows):
    if compilation is None:
        return []
    _require(isinstance(compilation, dict) and isinstance(compilation.get("operators", []), list), "Compilation metadata must contain an operator array when provided")
    operators = compilation.get("operators", [])
    _require(len(operators) <= 64, "Compilation metadata exceeds 64 operators")
    result = []
    for op in operators:
        _require(isinstance(op, dict) and isinstance(op.get("target"), str) and isinstance(op.get("kind"), str), "Operators need target and kind strings")
        options = op.get("options", [])
        _require(isinstance(options, list) and len(options) <= 16, "Operator options must be a bounded array")
        checks = []
        for option in options:
            _require(isinstance(option, dict) and isinstance(option.get("replacement"), dict), "Options need replacement objects")
            replacement = option["replacement"]
            _require(set(replacement) <= {"kind", "parents", "supports"} and bool(replacement), "Metadata cannot supply source facts or eligibility updates")
            represented = []
            for row in rows:
                node = row["index"].get(op["target"], {})
                if all(node.get(key) == value for key, value in replacement.items()):
                    represented.append(row["id"])
            checks.append({"answer": option.get("answer"), "represented_candidate_ids": represented})
        result.append({"id": op.get("id"), "kind": op["kind"], "target_id": op["target"],
                       "options": checks, "all_options_present": bool(checks) and all(x["represented_candidate_ids"] for x in checks),
                       "role": "Annotation only; metadata never satisfies a source obligation without a graph witness."})
    return result


def audit_conservation(prose, candidates, registry=None, compilation=None):
    """Inspect explicit cues against ALL supplied graphs, without reference graphs.

    Source spans are half-open Python Unicode code-point offsets within the
    identified untouched document. Activity flags do not suppress specification
    dependencies. The candidate union is not a probability distribution.
    """
    documents = _sources(prose)
    rows, types, aliases = _prepare(candidates, registry)
    obligations, unresolved, suppressed, mentions = [], [], [], []
    # An exact explicit alias declaration aligns a name, not its source truth.
    for doc in documents:
        for start, end, code in _units(doc):
            text = doc["text"][start:end].strip().rstrip(".!?;").strip()
            match = ALIAS.fullmatch(text)
            if match and not code and not (NEGATED.search(text) or HYPOTHETICAL.search(text) or ARCHIVED.search(text)) and match[1] in types:
                aliases.setdefault(_name(match[2]), set()).add(match[1])
    ids_pattern = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(re.escape(x) for x in sorted(types, key=lambda x: (-len(x), x))) + r")(?![A-Za-z0-9_-])") if types else None

    def add(kind, span, targets, refs, representation, **extra):
        _require(len(obligations) < MAX_OBLIGATIONS, "Recognized obligations exceed 2,048; no partial audit is returned")
        item = {"id": f"cue-{len(obligations) + 1:04d}", "kind": kind, "source_span": dict(span),
                "target_ids": list(targets), "referenced_ids": list(refs), "representation_type": representation,
                "represented_candidate_ids": [], "representations": [], **extra}
        obligations.append(item)
        if representation == "unresolved":
            item["status"] = "unresolved"
            unresolved.append(item)
            return item
        for row in rows:
            witness = _representation(item, row, types)
            if witness is not None:
                item["representations"].append(witness)
                item["represented_candidate_ids"].append(row["id"])
        item["status"] = "represented" if item["represented_candidate_ids"] else "gap"
        return item

    for doc in documents:
        for start, end, code in _units(doc):
            span = _span(doc, start, end)
            original = span["text"].strip().rstrip(".!?;").strip()
            text, quoted_actual = original, False
            authoritative = AUTHORITATIVE_QUOTE.fullmatch(text)
            if authoritative:
                text, quoted_actual = authoritative["body"].strip().rstrip(".!?;").strip(), True
            unit_mentions = list(ids_pattern.finditer(span["text"])) if ids_pattern else []
            cue = bool(CUE.search(text))
            exclusion = "negated_statement" if NEGATED.search(text) else ("hypothetical_statement" if HYPOTHETICAL.search(text) else ("historical_or_irrelevant_quotation" if ARCHIVED.search(text) else None))
            alias_declaration = ALIAS.fullmatch(text)
            quote_unresolved = code or text.startswith(">") or (not quoted_actual and not alias_declaration and bool(re.search(r'["“”]|(?:^|\s)\'[^\n]*\'', text)))
            for mention in unit_mentions:
                mentions.append({"node_id": mention[1], "source_span": _span(doc, start + mention.start(), start + mention.end()),
                                 "context": exclusion or ("quoted_or_code_unresolved" if quote_unresolved else "assertive_or_unclassified")})
            if exclusion:
                if cue or unit_mentions:
                    suppressed.append({"source_span": span, "reason": exclusion,
                                       "note": "No positive dependency is inferred from this unit; suppression is not a proof of irrelevance."})
                continue
            if quote_unresolved:
                if cue:
                    add("quoted_or_code_cue", span, [], [], "unresolved", reason="quotation_authority_or_scope_unresolved")
                continue
            for mention in unit_mentions:
                add("source_node_mention", _span(doc, start + mention.start(), start + mention.end()), [mention[1]], [], "node_presence")
            if ALIAS.fullmatch(text):
                continue
            relation = _recognize(text)
            if relation is None:
                if cue:
                    add("unparsed_structural_cue", span, sorted({m[1] for m in unit_mentions}), [], "unresolved", reason="outside_declared_cue_grammar")
                continue
            kind, target_raw, body = relation
            targets, target_connector, target_unresolved = _references(target_raw, types, aliases)
            refs, connector, reference_unresolved = _references(body, types, aliases)
            problems = target_unresolved + reference_unresolved
            if target_connector == "or":
                problems.append({"text": target_raw, "reason": "ambiguous_target_selection"})
            if not targets or not refs or problems:
                add("unaligned_lineage" if kind.startswith("lineage") else "unaligned_structural_cue", span, targets, refs,
                    "unresolved", reason="source_entity_or_grouping_unresolved", unaligned_entities=problems,
                    source_target=target_raw, source_dependency=body)
                continue
            if set(targets) & set(refs):
                add("self_referential_cue", span, targets, refs, "unresolved", reason="self_reference_needs_source_review")
                continue
            if kind.startswith("choice_"):
                if connector != "or" or len(refs) != 2:
                    add("unresolved_choice", span, targets, refs, "unresolved", reason="only_explicit_two-way_exclusive_choice_is_recognized")
                    continue
                for target in targets:
                    for ref in refs:
                        add("unresolved_choice_branch", span, [target], [ref], "exclusive_choice_branch", choice_relation=kind[7:])
                continue
            if kind.startswith("lineage") and connector == "or":
                add("unresolved_lineage_choice", span, targets, refs, "unresolved", reason="disjunctive_parent_scope_unresolved")
                continue
            if kind == "mandatory" and connector == "or":
                add("unresolved_requirement", span, targets, refs, "unresolved", reason="disjunctive_requirement_does_not_specify_sufficient_routes_or_unknown_selection")
                continue
            representation = {"lineage_direct": "direct_parent_conjunction", "lineage_ancestor": "ancestor_paths",
                              "mandatory": "mandatory_conjunction", "sufficient": "alternative_sufficient_routes" if connector == "or" else "sufficient_conjunction",
                              "alternative_routes": "alternative_sufficient_routes"}[kind]
            for target in targets:
                if kind.startswith("lineage") and (types[target] != "evidence" or any(types[x] != "evidence" for x in refs)):
                    add("type_unresolved_lineage", span, [target], refs, "unresolved", reason="lineage_requires_evidence_entities")
                elif kind in ("sufficient", "alternative_routes") and types[target] != "claims":
                    add("type_unresolved_support", span, [target], refs, "unresolved", reason="sufficient_route_requires_a_claim_target")
                else:
                    add(kind, span, [target], refs, representation)
    gaps = [item for item in obligations if item["status"] == "gap"]
    annotations = _compiler_annotations(compilation, rows)
    return {"schema": "retrace.conservation.v6", "status": "gap_detected" if gaps else ("unresolved" if unresolved else "no_gap_detected_in_recognized_cues"),
            "warning_label": WARNING_LABEL if gaps else None, "gaps": gaps, "unresolved": unresolved,
            "obligations": obligations, "suppressed": suppressed, "mentions": mentions, "compiler_annotations": annotations,
            "source_documents": [{"id": doc["id"], "characters": len(doc["text"]), "sha256": hashlib.sha256(doc["text"].encode("utf-8")).hexdigest()} for doc in documents],
            "coverage": {"candidate_ids": [row["id"] for row in rows], "source_characters": sum(len(d["text"]) for d in documents),
                         "recognized_obligations": len(obligations), "represented_obligations": sum(o["status"] == "represented" for o in obligations),
                         "zero_representation_gaps": len(gaps), "unresolved_obligations": len(unresolved), "suppressed_units": len(suppressed),
                         "union_policy": "Each structural obligation needs a witness within at least one supplied graph; a conjunction cannot be assembled across graphs.",
                         "source_completeness": "unknown", "semantic_soundness": "not_certified", "reference_graph_used": False},
            "scope": [
                "Only the declared bounded cue recognizer is checked. No gap is not a certificate of source completeness, graph soundness, or truth.",
                "Reference-Free Coverage Gap means zero matching literal/declared structural representation, not a proven semantic omission; equivalent factorings outside recognized representations can require review.",
                "IDs are exact and case-sensitive. Entity names align only through exact unambiguous graph labels or recognized explicit alias declarations; unaligned entities remain unresolved.",
                "Direct-copy cues require parent edges, derived-from cues allow ancestry paths, mandatory conjunctions inspect all structural routes, and sufficient routes require their explicit clause grouping.",
                "Local eligibility is ignored for specification conservation: inactive records do not erase their declared dependencies. No flags, sources, graphs or answers are changed.",
                "Negated, hypothetical and explicitly historical quotation units do not create positive obligations. Unframed quoted policies remain unresolved; explicitly current/authoritative quoted policies use the same recognizer.",
                "Union coverage does not require all supplied candidates to represent a cue and does not authenticate their compatibility. Compiler metadata alone cannot close a gap.",
                "Offsets are half-open Unicode code-point indices in each untouched document; duplicate source occurrences remain separately auditable."]}
