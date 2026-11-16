"""Post-hoc clause-parser revision of the bounded source conservation audit.

The first v6 recognizer and its failed/selectivity diagnostics remain unchanged.
This module separates entity alignment, statement scope, clause boundaries and
Boolean grouping. It reuses v6 graph witnesses; no model or reference is used.
"""
from __future__ import annotations

import hashlib
import re

from . import conservation_v6 as base

_TYPE_WORDS = {"evidence", "record", "claim", "decision", "review", "copy", "card", "sheet", "report", "check", "certificate"}
_FRAMES = [
    ("lineage_direct", r"\b(?:is|are|was|were)\s+(?:(?:a|an|the|first|second|third|additional|locally eligible)\s+)*(?:copy|copies|transcription|transcriptions|duplicate|duplicates)\s+of\b"),
    ("lineage_direct", r"\b(?:copied|transcribed|duplicated|reproduced|extracted|retyped)\s+(?:directly\s+)?from\b"),
    ("lineage_direct", r"\b(?:assembled|produced|created|made)\s+by\s+(?:retyping|copying|transcribing|duplicating)\b"),
    ("lineage_direct", r"\b(?:takes?|draws?)\s+(?:all\s+)?(?:its\s+)?(?:recorded\s+)?(?:numbers|readings|entries|content|text|data)\s+from\b"),
    ("lineage_ancestor", r"\bderived\s+from\b"),
    ("lineage_direct", r"\btranscribed\b"),
    ("mandatory", r"\b(?:requires?|needs?|depends?\s+on|is\s+conditional\s+on|is\s+contingent\s+on)\b"),
    ("mandatory", r"\b(?:clears?|passes?|is\s+(?:supported|usable|valid|eligible|warranted))\s+only\s+(?:if|when|while|with|on)\b"),
    ("sufficient", r"\b(?:accepts?|is\s+(?:supported|warranted|established|authorized)\s+(?:by|if|when))\b"),
    ("sufficient", r"\bhas\s+(?:(?:two|three|four|one|several)\s+)?(?:alternative\s+)?(?:sufficient\s+)?(?:support\s+)?routes?\s*:?"),
]
_FRAMES = [(kind, re.compile(pattern, re.I)) for kind, pattern in _FRAMES]
_STRUCTURAL = re.compile(r"\b(?:cop(?:y|ies|ied|ying)|transcrib\w*|transcription\w*|retyp\w*|deriv\w*|"
                         r"parent\w*|lineage|provenance|source|origin|ancestor|shared|requires?|needs?|"
                         r"support\w*|warrant\w*|suffic\w*|prerequisite\w*|conditional|contingent|"
                         r"joint|gate|authorization|unresolved|uncertain|relies|reliance|worksheet|"
                         r"fuses?|combines?|replicates?)\b", re.I)
_UNACCOUNTED_ACTION = re.compile(r"\b(?:fuses?|combines?|replicates?|relies|reliance|shared|gate|authorization|"
                                 r"copied|copying|transcrib\w*|retyp\w*|derived|derivation)\b", re.I)
_DENIAL = re.compile(r"\b(?:not|never|neither|denied|denial|without|unless|except)\b|n['’]t\b", re.I)
_HYPOTHESIS = re.compile(r"\b(?:hypothetical\w*|counterfactual|suppose|imagine)\b|\bfor\s+example\b|"
                         r"\btraining\s+(?:handout|example|exercise)\b|\b(?:if|were)\b.*\bwould\b", re.I)
_PROPOSAL = re.compile(r"\b(?:unadopted|proposed|proposal|future meeting|unanswered question)\b|"
                      r"\bquestion\b.*\b(?:future|should)\b|\bshould\b.*\?", re.I)
_HISTORICAL = re.compile(r"\b(?:historical|superseded|discarded|archived|rejected)\b.*\b(?:draft|quote|quotes|quotation|example|identifier|discussion)\b|"
                        r"\b(?:draft|quote|quotation|example)\b.*\b(?:historical|superseded|discarded|archived)\b", re.I)
_BOOKKEEPING = re.compile(r"\b(?:local(?:ly)?\s+(?:eligib\w*|ineligib\w*)|no\s+(?:parent(?:s| records)?|other|additional)|"
                         r"complete\s+(?:current\s+)?(?:register|routes|specification)|rules?\s+(?:are\s+)?exhaustive|"
                         r"(?:independent\s+)?original(?:s| evidence records| records)?|fresh\s+(?:count|check|observation))\b", re.I)


def _find_ids(text, ids_pattern):
    return list(ids_pattern.finditer(text)) if ids_pattern else []


def _source_units(doc):
    """A closing quotation can terminate its sentence with punctuation inside."""
    text, start, quote, code = doc["text"], 0, None, False
    i = 0
    while i < len(text):
        if text.startswith("```", i):
            code = not code
            i += 3
            continue
        char, closed = text[i], False
        if not code and char in '\"“”':
            if quote is None and char in '\"“':
                quote = '"' if char == '"' else '”'
            elif char == quote:
                quote, closed = None, True
        quoted_end = closed and i > 0 and text[i-1] in ".!?" and (i+1 == len(text) or text[i+1].isspace())
        if char == "\n" or quoted_end or (char in ".!?;" and quote is None and not code):
            end = i + (char != "\n")
            if text[start:end].strip():
                yield start, end, code or quote is not None
            start = i + 1
        i += 1
    if text[start:].strip():
        yield start, len(text), code or quote is not None


def _declared_identifiers(documents):
    """A source-derived name vocabulary, never graph completion or truth repair.

    An explicit type noun plus an identifier-shaped token is stronger than an
    arbitrary capitalized word. Newly recognized tokens must be uppercase ASCII
    or contain digits/underscore/hyphen; existing supplied IDs have no new rule.
    """
    expression = re.compile(r"\b(evidence|record|claim|review|decision)\s+([A-Za-z0-9_-]+)(?![A-Za-z0-9_-])", re.I)
    categories = {"evidence": "evidence", "record": "evidence", "claim": "claims", "review": "claims", "decision": "decisions"}
    declarations = []
    for doc in documents:
        for start, end, quoted in _source_units(doc):
            text = doc["text"][start:end]
            if quoted or any(pattern.search(text) for pattern in (_HISTORICAL, _HYPOTHESIS, _PROPOSAL, _DENIAL)):
                continue
            if re.search(r"\bno\s+(?:current\s+)?(?:role|source relation|dependency|production link)\b", text, re.I):
                continue
            quote = re.search(r'["“](.*)["”]', text, re.S)
            if quote:
                prefix = text[:quote.start()]
                if not re.search(r"\bauthoritative\b|\b(?:current|adopted|binding|operative|actual)\b.*\b(?:rule|policy|specification)\b", prefix, re.I):
                    continue
                start += quote.start(1)
                text = quote[1]
            for match in expression.finditer(text):
                ident = match[2]
                if ident == "-" or not (ident.isupper() or re.search(r"[0-9_-]", ident)):
                    continue
                base._require(len(ident) <= 128, "Source-declared identifiers may contain at most 128 characters")
                declarations.append({"node_id": ident, "category": categories[match[1].lower()],
                                     "source_span": base._span(doc, start+match.start(2), start+match.end(2)),
                                     "basis": "Explicit source type noun and identifier-shaped token; no graph node inserted."})
    return declarations


def _subject(raw, ids_pattern, types, aliases):
    # Reporting clauses and appositives are not graph subjects. Their text is
    # retained in the citation, while a unique explicit subject ID is aligned.
    raw = re.split(r"\b(?:states?\s+that|says?|reports?\s+that|specifies?\s+that)\b", raw, flags=re.I)[-1]
    found = _find_ids(raw, ids_pattern)
    values = list(dict.fromkeys(match[1] for match in found))
    if len(values) == 1:
        return values, []
    if len(values) > 1:
        # A compound subject needs an actual conjunction, not mere co-occurrence.
        between = raw[found[0].end():found[-1].start()]
        if re.search(r"\band\b", between, re.I) and not re.search(r"\bor\b", between, re.I):
            return values, []
        return [], [{"text": raw, "reason": "ambiguous_multiple_subject_ids"}]
    ident, reason = base._entity(raw, types, aliases)
    return ([ident], []) if ident is not None else ([], [{"text": raw, "reason": reason}])


def _frames(text):
    found = []
    for kind, pattern in _FRAMES:
        found.extend((m.start(), m.end(), kind) for m in pattern.finditer(text))
    accepted = []
    for start, end, kind in sorted(found, key=lambda x: (x[0], -(x[1]-x[0]))):
        if not any(start < prior_end and end > prior_start for prior_start, prior_end, _ in accepted):
            accepted.append((start, end, kind))
    return accepted


def _clauses(start, text, ids_pattern):
    """Split coordination only when its following clause has an explicit subject."""
    frames = _frames(text)
    boundaries = []
    previous_end = 0
    for number, (begin, end, _) in enumerate(frames):
        if number:
            separators = list(re.finditer(r",\s*(?:and\s+)?|\b(?:and|while|whereas)\s+", text[previous_end:begin], re.I))
            for separator in reversed(separators):
                stop = previous_end + separator.end()
                subject = text[stop:begin]
                if _find_ids(subject, ids_pattern):
                    boundaries.append((previous_end + separator.start(), stop))
                    break
        previous_end = end
    cursor = 0
    for left, right in boundaries:
        if left > cursor:
            yield start + cursor, start + left, text[cursor:left]
        cursor = right
    if cursor < len(text):
        yield start + cursor, start + len(text), text[cursor:]


def _expressions(body, ids_pattern, types, aliases):
    """Small parse forest: no implicit precedence for ambiguous AND/OR prose.

    A typed noun phrase with exactly one explicit ID identifies that entity.
    Logical connectors are inspected between entity mentions, not inside labels.
    Explicit parentheses or separately marked 'alone'/'both ... together' may
    disambiguate mixed routes; otherwise more than one reading remains unresolved.
    """
    found = _find_ids(body, ids_pattern)
    if not found:
        refs, connector, problems = base._references(body, types, aliases)
        return ([refs] if connector != "or" else [[ref] for ref in refs]), problems
    values = [match[1] for match in found]
    if len(values) != len(set(values)):
        return [], [{"text": body, "reason": "repeated_operand_or_scope_needs_review"}]
    # IDs embedded in noun phrases are alignments, not a license to discard
    # unnamed operands or qualifications surrounding those IDs.
    prefix, suffix = body[:found[0].start()], body[found[-1].end():]
    dangling = re.compile(r"\b(?:and|or|plus|as\s+well\s+as|along\s+with|together\s+with)\b", re.I)
    if dangling.search(prefix) or dangling.search(suffix):
        return [], [{"text": body, "reason": "unidentified_conjoined_operand"}]
    if re.search(r"\b(?:if|when|unless|provided|subject\s+to|requires?|needs?|conditional)\b", suffix, re.I):
        return [], [{"text": suffix, "reason": "unparsed_trailing_condition"}]
    links = []
    for first, second in zip(found, found[1:]):
        between = body[first.end():second.start()]
        if len(list(dangling.finditer(between))) > 1:
            return [], [{"text": between, "reason": "possible_unidentified_middle_operand"}]
        conjunction = bool(re.search(r"\band\b|\bplus\b|\bas\s+well\s+as\b|\balong\s+with\b|\btogether\s+with\b", between, re.I))
        alternative = bool(re.search(r"\bor\b", between, re.I))
        if conjunction == alternative:
            return [], [{"text": between, "reason": "connector_or_scope_unresolved"}]
        links.append("and" if conjunction else "or")
    if "and" in links and "or" in links:
        # Parentheses or explicit singleton/paired route wording justify the
        # ordinary OR-of-AND reading; bare A or B and C does not.
        explicit = "(" in body and ")" in body
        explicit |= bool(re.search(r"\balone\b", body, re.I) and re.search(r"\bboth\b|\btogether\b", body, re.I))
        if not explicit:
            return [], [{"text": body, "reason": "multiple_boolean_parses"}]
        # Reject parentheses spanning an OR with an outside conjunct; this
        # revision does not distribute formulas or pretend the grouping is flat.
        for group in re.finditer(r"\(([^()]*)\)", body):
            if re.search(r"\bor\b", group[1], re.I):
                return [], [{"text": body, "reason": "nested_disjunction_requires_review"}]
    routes = [[values[0]]]
    for link, value in zip(links, values[1:]):
        if link == "or":
            routes.append([value])
        else:
            routes[-1].append(value)
    return routes, []


def _witness(item, row, types):
    mode = item["representation_type"]
    if mode == "root_origin_branch":
        node = row["index"].get(item["target_ids"][0], {})
        if node.get("kind") == "root" and node.get("parents") == []:
            return {"candidate_id": row["id"], "kind": "root", "parents": []}
        return None
    if mode == "declared_sufficient_routes":
        node = row["index"].get(item["target_ids"][0], {})
        have = {tuple(sorted(route)) for route in node.get("supports", [])}
        required = {tuple(sorted(route)) for route in item["support_routes"]}
        return {"candidate_id": row["id"], "support_routes": item["support_routes"]} if required <= have else None
    return base._representation(item, row, types)


def audit_conservation(prose, candidates, registry=None, compilation=None):
    documents = base._sources(prose)
    rows, types, aliases = base._prepare(candidates, registry)
    declarations = _declared_identifiers(documents)
    type_conflicts = []
    for declaration in declarations:
        ident, category = declaration["node_id"], declaration["category"]
        if ident in types and types[ident] != category:
            type_conflicts.append(declaration)
        else:
            types[ident] = category
    base._require(len(types) <= base.MAX_NODES, "Source-derived and supplied identifier union exceeds 250 nodes")
    ids_pattern = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(re.escape(x) for x in sorted(types, key=lambda x: (-len(x), x))) + r")(?![A-Za-z0-9_-])") if types else None
    obligations, unresolved, suppressed, mentions, accounted = [], [], [], [], []

    def add(kind, span, targets=(), refs=(), representation="unresolved", **extra):
        base._require(len(obligations) < base.MAX_OBLIGATIONS, "Recognized obligations exceed 2,048; no partial audit returned")
        item = {"id": f"cue-{len(obligations)+1:04d}", "kind": kind, "source_span": span,
                "target_ids": list(targets), "referenced_ids": list(refs), "representation_type": representation,
                "represented_candidate_ids": [], "representations": [], **extra}
        obligations.append(item)
        if representation == "unresolved":
            item["status"] = "unresolved"
            unresolved.append(item)
        else:
            for row in rows:
                witness = _witness(item, row, types)
                if witness is not None:
                    item["representations"].append(witness)
                    item["represented_candidate_ids"].append(row["id"])
            item["status"] = "represented" if item["representations"] else "gap"
        return item

    def account(span, reason, **extra):
        accounted.append({"source_span": span, "reason": reason, **extra})

    for conflict in type_conflicts:
        add("source_type_conflict", conflict["source_span"], [conflict["node_id"]],
            reason="source_declared_type_disagrees_with_supplied_type", source_declared_category=conflict["category"])

    def process(doc, start, end, *, authority=False, quoted=False, context=None):
        span = base._span(doc, start, end)
        text = span["text"].strip().rstrip(".;").strip()
        if not text:
            return
        found = _find_ids(text, ids_pattern)
        identifiers = list(dict.fromkeys(match[1] for match in found))
        # Explicit non-current scope is evaluated before node-presence checks.
        exclusion = ("historical_or_noncurrent" if _HISTORICAL.search(text) else
                     "proposal_or_question" if _PROPOSAL.search(text) else
                     "hypothetical_statement" if _HYPOTHESIS.search(text) else
                     "explicit_no_current_role_or_relation" if re.search(r"\bno\s+(?:current\s+)?(?:role|source relation|dependency|production link)\b", text, re.I) else None)
        if exclusion:
            suppressed.append({"source_span": span, "reason": exclusion})
            return
        # Actual quoted policies retain their inner, exact character spans.
        quote = re.search(r'["“](.*)["”]', text, re.S)
        if quote and not authority:
            prefix = text[:quote.start()]
            current = bool(re.search(r"\bauthoritative\b|\b(?:current|adopted|binding|operative|actual)\b.*\b(?:rule|policy|specification)\b", prefix, re.I))
            if current and not _DENIAL.search(prefix):
                absolute = start + span["text"].index(text) + quote.start(1)
                for part in re.finditer(r"[^;.!?]+[;.!?]?", quote[1]):
                    process(doc, absolute+part.start(), absolute+part.end(), authority=True, context=context)
                account(span, "explicit_authoritative_quotation", inner_span=base._span(doc, absolute, absolute+len(quote[1])))
            else:
                add("quoted_or_code_cue", span, identifiers, reason="quotation_authority_or_scope_unresolved")
            return
        if quoted:
            add("quoted_or_code_cue", span, identifiers, reason="quotation_authority_or_scope_unresolved")
            return
        if _DENIAL.search(text):
            suppressed.append({"source_span": span, "reason": "negated_statement"})
            return
        for match in _find_ids(span["text"], ids_pattern):
            cite = base._span(doc, start+match.start(), start+match.end())
            mentions.append({"node_id": match[1], "source_span": cite, "context": "current_declaration"})
            add("source_node_mention", cite, [match[1]], representation="node_presence")

        # Explicitly declared uncertainty gets a narrow discourse subject; a
        # generic last-mentioned noun is never substituted for an unbound 'it'.
        if len(identifiers) == 1 and re.search(r"\b(?:provenance|production|origin|history)\b.*\b(?:missing|unknown|uncertain|unresolved)\b", text, re.I):
            context["production_focus"] = identifiers[0]
            context["pending_uncertainty"] = span
            account(span, "declared_production_uncertainty_pending_alternatives")
            return
        modal = re.search(r"\b(?:could|may|might)\s+be\b", text, re.I)
        if modal:
            prefix = text[:modal.start()]
            target, problems = _subject(prefix, ids_pattern, types, aliases)
            if not target and re.fullmatch(r"\s*it\s*", prefix, re.I) and context.get("production_focus"):
                target, problems = [context["production_focus"]], []
            body = text[modal.end():]
            origin_choice = re.search(r"\bcopy\s+of\b(.+?)\bor\b.*\bindependent\s+original\b", body, re.I)
            if origin_choice and len(target) == 1 and (context.get("production_focus") == target[0] or re.search(r"\b(?:unknown|unresolved|uncertain|possibilit|either)\w*\b", text, re.I)):
                parent_ids = list(dict.fromkeys(m[1] for m in _find_ids(origin_choice[1], ids_pattern)))
                if len(parent_ids) == 1 and types[target[0]] == types[parent_ids[0]] == "evidence":
                    add("lineage_direct", span, target, parent_ids, "direct_parent_conjunction", interpretation="declared_possible_copy")
                    add("independence_alternative", span, target, [], "root_origin_branch", interpretation="declared_possible_original")
                    context.pop("pending_uncertainty", None)
                    account(span, "declared_two_way_production_alternatives")
                    return
            add("unresolved_modal_cue", span, target or identifiers, reason="modal_scope_or_alternatives_unresolved")
            return

        alias = base.ALIAS.fullmatch(text.rstrip(".!?"))
        if alias and alias[1] in types:
            aliases.setdefault(base._name(alias[2]), set()).add(alias[1])
            account(span, "explicit_entity_alias")
            return
        frames = _frames(text)
        if not frames:
            if _BOOKKEEPING.search(text) and not _UNACCOUNTED_ACTION.search(text):
                account(span, "eligibility_origin_or_scope_bookkeeping", note="No new dependency is inferred; local flags/closure statements are outside this audit's relation checks.")
            elif re.search(r"\b(?:both|joint pair|two reviews)\b.*\b(?:required|route|prerequisite)\w*\b", text, re.I) and context.get("last_conjunction"):
                account(span, "anaphoric_conjunction_restatement", obligation_id=context["last_conjunction"])
            elif not identifiers and re.search(r"\b(?:either|each)\b.*\b(?:complete\s+)?sufficient\s+route\b", text, re.I) and context.get("last_alternatives"):
                account(span, "anaphoric_alternative_restatement", obligation_id=context["last_alternatives"])
            elif _STRUCTURAL.search(text):
                add("unparsed_structural_cue", span, identifiers, reason="outside_declared_clause_grammar")
            else:
                account(span, "no_recognized_structural_predicate")
            return
        # Subjectless generic copy usability is the already-declared graph
        # interpretation rule, not a newly identified ancestor or target.
        if not identifiers and re.search(r"\b(?:each|every)\s+(?:copy|card|transcription)\b", text, re.I) and re.search(r"\b(?:stated source|sole parent|parents?)\b", text, re.I) and re.search(r"\busable\b", text, re.I):
            account(span, "generic_copy_admissibility_convention")
            return
        begin, finish, kind = frames[0]
        if kind.startswith("lineage") and re.search(r"\b(?:unknown|uncertain|unresolved|whether|either)\b", text[:begin], re.I):
            add("unresolved_lineage_choice", span, identifiers, reason="lineage_assertion_scope_unresolved")
            return
        targets, target_problems = _subject(text[:begin], ids_pattern, types, aliases)
        body = text[finish:].strip(" :")
        routes, expression_problems = _expressions(body, ids_pattern, types, aliases)
        refs = list(dict.fromkeys(ref for route in routes for ref in route))
        problems = target_problems + expression_problems
        if not targets or not refs or problems:
            add("unaligned_lineage" if kind.startswith("lineage") else "unaligned_structural_cue", span,
                targets, refs, reason="source_entity_or_grouping_unresolved", unaligned_entities=problems,
                source_target=text[:begin], source_dependency=body)
            return
        if set(targets) & set(refs):
            add("self_referential_cue", span, targets, refs, reason="self_reference_or_unsplit_clause")
            return
        if kind.startswith("lineage") and len(routes) > 1:
            add("unresolved_lineage_choice", span, targets, refs, reason="parent_choice_scope_unresolved")
            return
        if kind == "mandatory" and len(routes) > 1:
            add("unresolved_requirement", span, targets, refs, reason="disjunction_is_not_an_explicit_sufficient_route_or_choice")
            return
        if kind.startswith("lineage"):
            representation = "direct_parent_conjunction" if kind == "lineage_direct" else "ancestor_paths"
        elif kind == "mandatory":
            representation = "mandatory_conjunction"
        elif len(routes) == 1:
            representation = "sufficient_conjunction"
        elif all(len(route) == 1 for route in routes):
            kind, representation = "alternative_routes", "alternative_sufficient_routes"
        else:
            representation = "declared_sufficient_routes"
        for target in targets:
            if kind.startswith("lineage") and (types[target] != "evidence" or any(types[ref] != "evidence" for ref in refs)):
                add("type_unresolved_lineage", span, [target], refs, reason="lineage_requires_evidence_entities")
            elif kind in ("sufficient", "alternative_routes") and types[target] != "claims":
                add("type_unresolved_support", span, [target], refs, reason="sufficient_routes_require_claim_target")
            else:
                item = add(kind, span, [target], refs, representation, support_routes=routes)
                if representation in ("mandatory_conjunction", "sufficient_conjunction") and len(refs) > 1:
                    context["last_conjunction"] = item["id"]
                if representation == "alternative_sufficient_routes":
                    context["last_alternatives"] = item["id"]

    for doc in documents:
        context = {}
        for start, end, quoted in _source_units(doc):
            text = doc["text"][start:end]
            # Quoted policies must be classified as one framed unit first.
            if any(mark in text for mark in ('"', '“', '”')) or quoted:
                process(doc, start, end, quoted=quoted, context=context)
            else:
                for left, right, _ in _clauses(start, text, ids_pattern):
                    process(doc, left, right, context=context)
        if context.get("pending_uncertainty"):
            add("unresolved_production_history", context["pending_uncertainty"], [context["production_focus"]],
                reason="declared_uncertainty_without_recognized_alternative_set")
    gaps = [item for item in obligations if item["status"] == "gap"]
    return {"schema": "retrace.conservation.v6b", "development_status": "Post-hoc redesign; original v6 artifacts unchanged.",
            "status": "gap_detected" if gaps else "unresolved" if unresolved else "no_gap_detected_in_recognized_cues",
            "warning_label": base.WARNING_LABEL if gaps else None, "gaps": gaps, "unresolved": unresolved,
            "obligations": obligations, "suppressed": suppressed, "mentions": mentions, "accounted": accounted,
            "source_declared_entities": declarations,
            "unresolved_cues": unresolved, "suppressed_cues": suppressed,
            "compiler_annotations": base._compiler_annotations(compilation, rows),
            "source_documents": [{"id": doc["id"], "characters": len(doc["text"]), "sha256": hashlib.sha256(doc["text"].encode()).hexdigest()} for doc in documents],
            "coverage": {"candidate_ids": [row["id"] for row in rows], "recognized_obligations": len(obligations),
                         "represented_obligations": sum(o["status"] == "represented" for o in obligations),
                         "zero_representation_gaps": len(gaps), "unresolved_obligations": len(unresolved),
                         "suppressed_units": len(suppressed), "accounted_units": len(accounted),
                         "source_completeness": "unknown", "semantic_soundness": "not_certified", "reference_graph_used": False,
                         "union_policy": "One within-graph witness per obligation; never merge conjunction members across candidates."},
            "scope": [
                "V6b was developed after inspecting the original 12-case v6 failures. Development-set improvements are post-hoc, not fresh accuracy.",
                "This is a bounded clause recognizer, not unrestricted semantic parsing. Unrecognized structural grammar and unresolved entities remain explicit review items.",
                "Exact source identifiers may align within noun phrases. Explicit typed identifier-shaped source tokens extend the audit vocabulary even if registry and graph omit them; no graph node is inserted. Unaligned implicit entities remain unresolved.",
                "Only recognizable explicit authority framing opens quoted rules. Negated, proposed, historical and hypothetical statements retain separate dispositions.",
                "Bookkeeping and generic copy-admissibility statements are separately accounted; their treatment is not independent verification of local flags or global closure.",
                "Direct parent edges, ancestor paths, mandatory conjunctions and sufficient clause groups remain distinct. Mere ID presence or compiler metadata cannot close a structural gap.",
                "No gap certifies neither completeness nor soundness. A gap is zero recognized representation, not proof of source truth or semantic error; alternate factorizations may need review.",
                "All source citations are exact half-open Unicode code-point spans. Candidate graphs, eligibility and source text remain unchanged."]}
