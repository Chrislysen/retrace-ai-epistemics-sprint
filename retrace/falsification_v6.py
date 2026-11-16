"""Mechanical checks for source-cited counter-readings, never source entailment.

Quotes are located exactly in the caller's public source. Typed edits and their
consequences are checked against supplied seed graphs. No reference family,
semantic grader, model call, fuzzy repair or state mutation is used here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .core import validate_case
from .exposure_v5 import audit_exposure

CATEGORIES = ("evidence", "claims", "decisions")
STATUS = "mechanically_checked_semantically_unverified"
MAX_SOURCE_CODEPOINTS = 1_000_000
MAX_CITATIONS = 8


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, required, optional=(), name="object"):
    _require(isinstance(value, dict), f"{name} must be an object")
    _require(set(required) <= set(value), f"{name} is missing required fields")
    _require(set(value) <= set(required) | set(optional), f"{name} contains unknown fields")


def _string(value, name, nonempty=True):
    _require(isinstance(value, str) and (bool(value) or not nonempty), f"{name} must be a {'nonempty ' if nonempty else ''}string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} contains an invalid Unicode scalar") from exc
    return value


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON object key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Nonfinite JSON value is not permitted: {value}")


def _object(value, name):
    if isinstance(value, str):
        try:
            value = json.loads(value, object_pairs_hook=_strict_pairs, parse_constant=_constant)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} must be one strict JSON object") from exc
    _require(isinstance(value, dict), f"{name} must be an object")
    return value


def parse_counter_reading(text):
    """Parse a bare JSON proposal, rejecting duplicate keys at every depth.

    Schema checks occur in verify_counter_reading. Already-decoded dictionaries
    cannot reveal duplicate keys discarded by an upstream JSON parser.
    """
    _require(isinstance(text, str), "Proposal JSON must be text")
    return _object(text, "proposal")


def _ids(value, allowed=None, name="IDs", nonempty=False):
    _require(isinstance(value, list), f"{name} must be an array")
    for item in value:
        _string(item, name)
    _require(not nonempty or bool(value), f"{name} cannot be empty")
    _require(len(value) == len(set(value)), f"{name} contains duplicate IDs")
    _require(allowed is None or set(value) <= set(allowed), f"{name} contains unknown or wrong-category IDs")
    return list(value)


def _fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical(graph):
    return {
        "evidence": sorted((r["id"], r.get("kind", "root"), r.get("active", True),
                            tuple(sorted(r.get("parents", [])))) for r in graph["evidence"]),
        "claims": sorted((r["id"], tuple(sorted(tuple(sorted(route)) for route in r["supports"])))
                         for r in graph["claims"]),
        "decisions": sorted((r["id"], tuple(sorted(r["requires"]))) for r in graph["decisions"]),
    }


def _body_signature(category, row):
    if category == "evidence":
        return row.get("kind", "root"), tuple(sorted(row.get("parents", [])))
    if category == "claims":
        return tuple(sorted(tuple(sorted(route)) for route in row["supports"]))
    return tuple(sorted(row["requires"]))


def _graph(graph, registry):
    _keys(graph, CATEGORIES, name="candidate graph")
    for category in CATEGORIES:
        _require(isinstance(graph[category], list), f"{category} must be an array")
        for row in graph[category]:
            if category == "evidence":
                _keys(row, ("id",), ("label", "kind", "active", "parents"), "evidence node")
            elif category == "claims":
                _keys(row, ("id", "supports"), ("label",), "claim node")
                _require(isinstance(row["supports"], list), "Claim supports must be an array")
                routes = []
                for route in row["supports"]:
                    routes.append(tuple(sorted(_ids(route, name="support route", nonempty=True))))
                _require(len(routes) == len(set(routes)), "Duplicate support route")
            else:
                _keys(row, ("id", "requires"), ("label",), "decision node")
            _string(row["id"], "node ID")
            if "label" in row:
                _string(row["label"], "node label", nonempty=False)
        _require({r["id"] for r in graph[category]} == set(registry[category]), "Candidate and registry typed IDs differ")
    _require(sum(len(graph[k]) for k in CATEGORIES) <= 250, "At most 250 graph nodes are supported")
    return validate_case(graph)


def _prepare(public):
    public = _object(public, "public")
    _keys(public, ("candidates", "registry"),
          ("id", "title", "source_documents", "documents", "target_decisions", "allowed_changes", "locked_exclusions"), "public")
    _require(("source_documents" in public) != ("documents" in public),
             "Supply exactly one of source_documents or documents")
    for field in ("id", "title"):
        if field in public:
            _string(public[field], field, nonempty=False)
    docs = public.get("source_documents", public.get("documents"))
    _require(isinstance(docs, list) and 1 <= len(docs) <= 64, "Supply 1 to 64 source documents")
    documents = {}
    for doc in docs:
        _keys(doc, ("id", "text"), ("title", "label"), "source document")
        did = _string(doc["id"], "document ID")
        _require(did not in documents, "Duplicate source document ID")
        source = _string(doc["text"], "source text", nonempty=False)
        for field in ("title", "label"):
            if field in doc:
                _string(doc[field], field, nonempty=False)
        documents[did] = {"id": did, "text": source,
                          "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}
    _require(sum(len(d["text"]) for d in documents.values()) <= MAX_SOURCE_CODEPOINTS,
             "Source text exceeds the supported code-point limit")
    registry = public["registry"]
    _keys(registry, CATEGORIES, name="registry")
    for category in CATEGORIES:
        _ids(registry[category], name=f"registry.{category}")
    flattened = [v for category in CATEGORIES for v in registry[category]]
    _require(len(flattened) == len(set(flattened)), "Registry IDs overlap across categories")
    targets = _ids(public.get("target_decisions", registry["decisions"]), registry["decisions"], "target_decisions", nonempty=True)
    allowed = _ids(public.get("allowed_changes", registry["evidence"]), registry["evidence"], "allowed_changes")
    locked = _ids(public.get("locked_exclusions", []), registry["evidence"], "locked_exclusions")
    _require(len(set(allowed) - set(locked)) <= 16, "At most sixteen unlocked eligibility IDs may be changeable")
    candidates = public["candidates"]
    _require(isinstance(candidates, list) and 1 <= len(candidates) <= 16, "Supply 1 to 16 seed candidates")
    candidate_ids = set()
    for row in candidates:
        _keys(row, ("id", "graph"), name="candidate")
        cid = _string(row["id"], "candidate ID")
        _require(cid not in candidate_ids, "Duplicate candidate ID")
        candidate_ids.add(cid)
        _graph(row["graph"], registry)
    # This validates a common local baseline and computes unanimity without
    # enumerating hypothetical changes. Explicit current exclusions remain on.
    current = audit_exposure(candidates, allowed_changes=[], locked_exclusions=locked, target_decisions=targets)
    outcomes = current["baseline_outcomes"]
    unanimous = {did: len({values[did] for values in outcomes.values()}) == 1 for did in targets}
    _require(all(unanimous.values()), "The requested seed decisions are not currently unanimous")
    return public, documents, registry, targets, allowed, locked, candidates, outcomes


def _span(citation, documents):
    _keys(citation, ("document_id", "quote"), ("start", "end"), "source citation")
    did = _string(citation["document_id"], "citation document_id")
    _require(did in documents, "Citation refers to an unknown source document")
    quote = _string(citation["quote"], "citation quote")
    doc = documents[did]
    source = doc["text"]
    _require(("start" in citation) == ("end" in citation), "Supply both start and end offsets or neither")
    if "start" in citation:
        start, end = citation["start"], citation["end"]
        _require(type(start) is int and type(end) is int, "Offsets must be integer Unicode code-point indices")
        _require(0 <= start < end <= len(source) and source[start:end] == quote,
                 "Explicit offsets do not exactly match the quote")
        method = "explicit_exact_offsets"
    else:
        start = source.find(quote)
        _require(start >= 0, "Quote does not occur exactly in the supplied source")
        _require(source.find(quote, start + 1) < 0, "Quote has multiple exact occurrences; supply exact offsets")
        end = start + len(quote)
        method = "unique_exact_quote"
    return {"document_id": did, "quote": quote, "start": start, "end": end,
            "index_unit": "unicode_code_point", "end_exclusive": True,
            "source_text_sha256": doc["sha256"], "resolution": method}


def verify_counter_reading(public, proposal):
    """Check up to two cited body replacements without applying them.

    Public may use source_documents or documents, with [{id,text,...}]. Registry
    and candidates are required. Optional scope fields are target_decisions,
    allowed_changes and locked_exclusions. Proposals are dictionaries or bare
    strict JSON. Differing seed structures require an explicit candidate ID.
    Invalid input raises ValueError; the caller's objects are never changed.
    All successful outputs retain semantic_verified=False, even if a perfectly
    valid quote accompanies an unsupported interpretation.
    """
    public, documents, registry, targets, allowed, locked, candidates, baseline = _prepare(public)
    proposal = _object(proposal, "proposal")
    _keys(proposal, ("status",), ("seed_candidate_id", "changes"), "proposal")
    _require(proposal["status"] in ("no_counter_reading", "counter_reading"), "Unknown proposal status")
    seed_id = proposal.get("seed_candidate_id")
    by_id = {r["id"]: r for r in candidates}
    if "seed_candidate_id" in proposal:
        _string(seed_id, "seed_candidate_id")
        _require(seed_id in by_id, "Unknown seed_candidate_id")
    elif len({_fingerprint(_canonical(r["graph"])) for r in candidates}) == 1:
        seed_id = sorted(by_id)[0]
    result = {
        "schema": "retrace.counter_reading.v6", "status": STATUS,
        "proposal_status": proposal["status"], "semantic_verified": False,
        "auto_applied": False, "reference_graph_used": False,
        "public_input_sha256": _fingerprint(public), "proposal_sha256": _fingerprint(proposal),
        "source_documents": [{"document_id": did, "source_text_sha256": documents[did]["sha256"],
                              "code_points": len(documents[did]["text"])} for did in sorted(documents)],
        "seed_candidate_id": seed_id, "seed_pool_current_outcomes": baseline,
        "seed_pool_unanimous": True, "target_decisions": list(targets),
        "original_candidates": deepcopy(candidates), "changes": [], "source_spans": [],
        "original_graph": deepcopy(by_id[seed_id]["graph"]) if seed_id is not None else None,
        "counter_graph": None, "exposure": None, "consequential_within_scope": False,
        "already_in_seed_pool": None,
        "scope": [
            "Exact quotation matching proves location, not semantic entailment or source authenticity.",
            "Typed edits and witnesses are mechanically checked proposals, never automatically applied facts.",
            "Exposure compares the explicitly selected seed with the proposed graph, not an authored reference.",
            "Hypothetical enables change local eligibility only; supplied current vetoes remain locked false.",
            "No counter-reading, no exposure, or a surviving unanimous pool does not prove source completeness.",
        ],
    }
    if proposal["status"] == "no_counter_reading":
        _require("changes" not in proposal or proposal["changes"] == [], "No-counter-reading proposals cannot contain edits")
        return result
    _require(seed_id is not None, "Select seed_candidate_id explicitly when seed structures differ")
    changes = proposal.get("changes")
    _require(isinstance(changes, list) and 1 <= len(changes) <= 2, "A counter-reading requires exactly one or two changes")
    original = by_id[seed_id]["graph"]
    modified = deepcopy(original)
    index = {r["id"]: r for category in CATEGORIES for r in modified[category]}
    categories = {r["id"]: category for category in CATEGORIES for r in modified[category]}
    seen = set()
    for change in changes:
        _keys(change, ("target", "replacement", "sources"), name="change")
        target = _string(change["target"], "change target")
        _require(target in index, "Cannot add or rename nodes")
        _require(target not in seen, "Duplicate change target")
        seen.add(target)
        replacement = change["replacement"]
        category = categories[target]
        fields = ("kind", "parents") if category == "evidence" else (("supports",) if category == "claims" else ("requires",))
        _keys(replacement, fields, name="replacement")
        sources = change["sources"]
        _require(isinstance(sources, list) and 1 <= len(sources) <= MAX_CITATIONS,
                 f"Every changed node needs 1 to {MAX_CITATIONS} source citations")
        spans = [_span(citation, documents) for citation in sources]
        signatures = [(s["document_id"], s["start"], s["end"]) for s in spans]
        _require(len(signatures) == len(set(signatures)), "Duplicate citation within one change")
        before = {field: deepcopy(index[target].get(field, "root" if field == "kind" else [])) for field in fields}
        index[target].update(deepcopy(replacement))
        result["changes"].append({"target": target, "category": category,
                                  "original_body": before, "replacement": deepcopy(replacement), "sources": spans})
        result["source_spans"].extend({"target": target, **span} for span in spans)
    _graph(modified, registry)  # Validate the complete simultaneous edit, not partial edits.
    original_index = {r["id"]: r for category in CATEGORIES for r in original[category]}
    for target in seen:
        _require(_body_signature(categories[target], original_index[target]) !=
                 _body_signature(categories[target], index[target]), "Every listed change must replace a different structural body")
    _require(_canonical(modified) != _canonical(original), "The proposed changes do not change graph structure")
    original_flags = {r["id"]: r.get("active", True) for r in original["evidence"]}
    _require({r["id"]: r.get("active", True) for r in modified["evidence"]} == original_flags,
             "Local eligibility must remain unchanged")
    exposure = audit_exposure([{"id": "seed", "graph": original}, {"id": "counter_reading", "graph": modified}],
                              allowed_changes=allowed, locked_exclusions=locked, target_decisions=targets)
    result.update(counter_graph=modified, exposure=exposure,
                  consequential_within_scope=any(d["exposure_exists"] for d in exposure["decisions"].values()),
                  already_in_seed_pool=any(_canonical(modified) == _canonical(r["graph"]) for r in candidates))
    return result
