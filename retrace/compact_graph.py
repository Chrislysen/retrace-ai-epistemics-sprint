"""Strict, bounded compiler for the prospective RETRACE compact graph format.

    E source R 1 -
    E other R 1 -
    E copy C 1 source
    C claim copy+source|other
    C no_routes -
    D decision claim
    END

E: evidence ID, R/root or C/copy, explicit local active bit, comma parents.
C: claim ID and OR-separated, plus-joined AND routes, or '-' for no routes.
D: decision ID and plus-joined required claims. '-' is reserved, not an ID.

Only bare text or one whole unlabeled/text/plaintext fence is accepted. Parsing
never searches prose for a usable block or invents missing records/relationships.
An optional typed ID registry checks completeness without supplying graph rules.
serialize_compact is an offline fixture/roundtrip helper, not an answer repairer.
"""
from __future__ import annotations

import re
from typing import Any

from .core import validate_case

MAX_TEXT_CHARS = 65_536
MAX_NODES = 250
_CATEGORIES = ("evidence", "claims", "decisions")
_ID = re.compile(r"[A-Za-z0-9_-]+\Z", flags=re.ASCII)
_FENCE = re.compile(r"```(?:text|plaintext)?[ \t]*\Z", flags=re.ASCII)


class CompactGraphError(ValueError):
    """A stable error code and original physical line number, when applicable."""

    def __init__(self, code: str, message: str, line_number: int | None = None):
        self.code = code
        self.line_number = line_number
        location = f"Line {line_number}: " if line_number is not None else ""
        super().__init__(location + message)


def _fail(code, message, line=None):
    raise CompactGraphError(code, message, line)


def _identifier(value, line=None):
    if not isinstance(value, str) or not _ID.fullmatch(value) or value == "-":
        _fail("invalid_id", "IDs must use ASCII letters, digits, underscores or hyphens; standalone '-' is reserved.", line)
    return value


def _references(value, separator, line):
    parts = value.split(separator)
    for identifier in parts:
        _identifier(identifier, line)
    if len(parts) != len(set(parts)):
        _fail("duplicate_reference", "A dependency is listed more than once in the same conjunction.", line)
    return sorted(parts)


def _registry(registry):
    if registry is None:
        return None
    if not isinstance(registry, dict) or set(registry) != set(_CATEGORIES):
        _fail("invalid_registry", "Registry must have exactly evidence, claims and decisions ID arrays.")
    result, seen = {}, set()
    for category in _CATEGORIES:
        values = registry[category]
        if not isinstance(values, list):
            _fail("invalid_registry", "Registry values must be ID arrays.")
        for identifier in values:
            _identifier(identifier)
            if identifier in seen:
                _fail("invalid_registry", "Registry IDs must be unique across all categories.")
            seen.add(identifier)
        result[category] = set(values)
    if len(seen) > MAX_NODES:
        _fail("node_limit", f"Registry exceeds the {MAX_NODES}-node limit.")
    return result


def _source_lines(text):
    if not isinstance(text, str):
        _fail("invalid_text", "Compact output must be a string.")
    if len(text) > MAX_TEXT_CHARS:
        _fail("text_limit", f"Compact output exceeds {MAX_TEXT_CHARS} source characters.", text[:MAX_TEXT_CHARS].count("\n") + 1)
    for offset, char in enumerate(text):
        if ord(char) > 126 or (ord(char) < 32 and char not in "\t\n\r"):
            _fail("unsupported_character", "Only printable ASCII, tabs and LF/CRLF line endings are allowed.", text[:offset].count("\n") + 1)
    normalized = text.replace("\r\n", "\n")
    if "\r" in normalized:
        _fail("unsupported_character", "A carriage return must be followed by a line feed.", normalized[:normalized.index("\r")].count("\n") + 1)
    lines = normalized.split("\n")
    occupied = [i for i, line in enumerate(lines) if line.strip(" \t")]
    if not occupied:
        _fail("missing_end", "Output must explicitly end with END.", 1)
    first, last = occupied[0], occupied[-1]
    fenced = bool(_FENCE.fullmatch(lines[first].strip(" \t")))
    if fenced:
        if last == first or lines[last].strip(" \t") != "```":
            _fail("invalid_fence", "A whole-response opening fence requires a matching final fence.", first + 1)
        first, last = first + 1, last - 1
    return list(enumerate(lines[first:last + 1], start=first + 1)), fenced


def _canonical(graph):
    result = {category: [] for category in _CATEGORIES}
    for row in sorted(graph["evidence"], key=lambda row: row["id"]):
        result["evidence"].append({"id": row["id"], "kind": row.get("kind", "root"),
                                   "active": row.get("active", True), "parents": sorted(row.get("parents", []))})
    for row in sorted(graph["claims"], key=lambda row: row["id"]):
        clauses = [tuple(sorted(clause)) for clause in row["supports"]]
        if len(clauses) != len(set(clauses)):
            _fail("duplicate_clause", "A claim repeats an identical sufficient route.")
        result["claims"].append({"id": row["id"], "supports": [list(clause) for clause in sorted(clauses)]})
    for row in sorted(graph["decisions"], key=lambda row: row["id"]):
        result["decisions"].append({"id": row["id"], "requires": sorted(row["requires"])})
    return result


def parse_compact_output(text: str, registry: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Compile a complete output and preserve its exact original text.

    Returns graph, outer_fence_removed, strict_bare and source_text. Record order,
    clause order and conjunction-member order are canonicalized, never their logic.
    Source-format errors carry original physical line numbers (including fences).
    Configuration/registry errors may have line_number=None.
    """
    expected = _registry(registry)
    lines, fenced = _source_lines(text)
    graph = {category: [] for category in _CATEGORIES}
    identities, node_lines, dependencies = {}, {}, {}
    ended, end_line = False, None
    for line_number, original in lines:
        line = original.strip(" \t")
        if not line:
            continue
        if ended:
            _fail("trailing_content", "No nonblank content is allowed after END.", line_number)
        if line == "END":
            ended, end_line = True, line_number
            continue
        parts = re.split(r"[ \t]+", line)
        tag = parts[0]
        if tag not in {"E", "C", "D"}:
            _fail("unknown_record", "Expected E, C, D or the terminal END line.", line_number)
        if len(parts) != (5 if tag == "E" else 3):
            _fail("field_count", "Wrong number of fields; separators within a dependency field cannot contain whitespace.", line_number)
        identifier = _identifier(parts[1], line_number)
        if identifier in identities:
            _fail("duplicate_id", f"Node '{identifier}' was already declared on line {node_lines[identifier]}.", line_number)
        if len(identities) >= MAX_NODES:
            _fail("node_limit", f"Compact output exceeds the {MAX_NODES}-node limit.", line_number)
        category = {"E": "evidence", "C": "claims", "D": "decisions"}[tag]
        if tag == "E":
            kind, active, parent_field = parts[2:]
            if kind not in {"R", "C"}:
                _fail("invalid_kind", "Evidence kind must be R or C.", line_number)
            if active not in {"0", "1"}:
                _fail("invalid_activity", "Local activity must be explicitly 0 or 1.", line_number)
            parents = [] if parent_field == "-" else _references(parent_field, ",", line_number)
            if (kind == "R" and parents) or (kind == "C" and not parents):
                _fail("invalid_parents", "Roots require '-', and copies require at least one evidence parent.", line_number)
            row = {"id": identifier, "kind": "root" if kind == "R" else "copy", "active": active == "1", "parents": parents}
            refs, allowed = set(parents), {"evidence"}
        elif tag == "C":
            clauses = [] if parts[2] == "-" else [_references(clause, "+", line_number) for clause in parts[2].split("|")]
            if len(clauses) != len({tuple(clause) for clause in clauses}):
                _fail("duplicate_clause", "A claim repeats an identical sufficient route.", line_number)
            row = {"id": identifier, "supports": clauses}
            refs, allowed = {ref for clause in clauses for ref in clause}, {"evidence", "claims"}
        else:
            required = _references(parts[2], "+", line_number)
            row = {"id": identifier, "requires": required}
            refs, allowed = set(required), {"claims"}
        graph[category].append(row)
        identities[identifier], node_lines[identifier], dependencies[identifier] = category, line_number, (refs, allowed)
    if not ended:
        _fail("missing_end", "Output must explicitly end with END; no truncated graph is accepted.", lines[-1][0] if lines else 1)
    if expected is not None:
        for category in _CATEGORIES:
            observed = {row["id"] for row in graph[category]}
            if observed != expected[category]:
                _fail("registry_mismatch", f"{category} IDs differ from the exact registry: missing={sorted(expected[category] - observed)}, unexpected={sorted(observed - expected[category])}.", end_line)
    for identifier, (refs, allowed) in dependencies.items():
        for ref in sorted(refs):
            if ref not in identities:
                _fail("unknown_reference", f"Node '{identifier}' refers to undeclared ID '{ref}'.", node_lines[identifier])
            if identities[ref] not in allowed:
                _fail("reference_category", f"Node '{identifier}' cannot depend on {identities[ref]} ID '{ref}'.", node_lines[identifier])
    remaining, resolved = set(identities), set()
    while remaining:
        ready = {identifier for identifier in remaining if dependencies[identifier][0] <= resolved}
        if not ready:
            identifier = min(remaining, key=node_lines.get)
            _fail("dependency_cycle", f"Dependency cycle prevents resolving '{identifier}'.", node_lines[identifier])
        resolved |= ready
        remaining -= ready
    try:
        validate_case(graph)
    except (ValueError, RecursionError) as exc:
        _fail("invalid_graph", str(exc), end_line)
    return {"graph": _canonical(graph), "outer_fence_removed": fenced,
            "strict_bare": not fenced, "source_text": text}


def parse_compact(text: str, registry: dict[str, list[str]] | None = None) -> dict:
    """Return the graph only; see parse_compact_output for formatting metadata."""
    return parse_compact_output(text, registry)["graph"]


def validate_explicit_graph(graph: dict, registry: dict[str, list[str]] | None = None) -> dict:
    """Admit an explicit graph under the compact format's shared constraints.

    This validates/canonicalizes the supplied object directly, without converting
    model output to another textual representation. All fields are mandatory;
    labels and other extra fields are rejected. The caller must separately bound
    its raw source text. The object must fit the same node and minimal compact
    character budgets. No omitted values or relationships are filled in.
    """
    expected = _registry(registry)
    fields = {"evidence": {"id", "kind", "active", "parents"},
              "claims": {"id", "supports"}, "decisions": {"id", "requires"}}
    if not isinstance(graph, dict) or set(graph) != set(fields):
        _fail("invalid_graph", "Graph must have exactly evidence, claims and decisions arrays.")
    if any(not isinstance(graph[k], list) for k in fields):
        _fail("invalid_graph", "Graph categories must be arrays.")
    count = sum(len(graph[k]) for k in fields)
    if count > MAX_NODES:
        _fail("node_limit", f"Graph exceeds the {MAX_NODES}-node limit.")
    character_count = 3 + count  # END plus one newline after each node line.

    def refs(values, *, nonempty):
        if not isinstance(values, list) or (nonempty and not values):
            _fail("invalid_graph", "Dependency conjunctions must be arrays of IDs, nonempty where required.")
        if len(values) > MAX_NODES:
            _fail("invalid_graph", "A conjunction exceeds the maximum possible unique node references.")
        for value in values:
            _identifier(value)
        if len(values) != len(set(values)):
            _fail("duplicate_reference", "A dependency is listed more than once in the same conjunction.")
        return sum(len(value) for value in values) + max(0, len(values) - 1)

    for category, required in fields.items():
        for row in graph[category]:
            if not isinstance(row, dict) or set(row) != required:
                _fail("explicit_fields", "All and only explicit fields are required for " + category + ".")
            _identifier(row["id"])
            if category == "evidence":
                if row["kind"] not in ("root", "copy") or type(row["active"]) is not bool:
                    _fail("invalid_graph", "Evidence kind and boolean activity must be explicit and valid.")
                length = refs(row["parents"], nonempty=row["kind"] == "copy")
                if row["kind"] == "root" and row["parents"]:
                    _fail("invalid_parents", "Root evidence cannot declare parents.")
                character_count += 7 + len(row["id"]) + (length if row["parents"] else 1)
            elif category == "claims":
                if not isinstance(row["supports"], list):
                    _fail("invalid_graph", "Claim routes must be an array.")
                if len(row["supports"]) > MAX_TEXT_CHARS:
                    _fail("text_limit", "Too many routes to fit the source character budget.")
                length = 0
                for clause in row["supports"]:
                    length += refs(clause, nonempty=True)
                    if length > MAX_TEXT_CHARS:
                        _fail("text_limit", "Claim routes exceed the source character budget.")
                character_count += 3 + len(row["id"]) + (length + len(row["supports"]) - 1 if row["supports"] else 1)
            else:
                character_count += 3 + len(row["id"]) + refs(row["requires"], nonempty=True)
            if character_count > MAX_TEXT_CHARS:
                _fail("text_limit", f"Explicit graph cannot fit the {MAX_TEXT_CHARS}-character compact budget.")
    try:
        validate_case(graph)
    except (ValueError, RecursionError) as exc:
        _fail("invalid_graph", str(exc))
    if expected is not None:
        for category in fields:
            if {row["id"] for row in graph[category]} != expected[category]:
                _fail("registry_mismatch", "Graph IDs differ from the exact typed registry in " + category + ".")
    return _canonical(graph)


def serialize_compact(graph: dict) -> str:
    """Deterministic offline serialization, not a transform of model answers.

    Descriptive labels and top-level metadata have no compact representation.
    All support-relevant fields are emitted explicitly, including default core
    root/activity/parent values. Duplicate routes are rejected, not repaired.
    """
    if not isinstance(graph, dict) or any(not isinstance(graph.get(k), list) for k in _CATEGORIES):
        _fail("invalid_graph", "Graph must contain evidence, claims and decisions arrays.")
    if sum(len(graph[k]) for k in _CATEGORIES) > MAX_NODES:
        _fail("node_limit", f"Graph exceeds the {MAX_NODES}-node limit.")
    try:
        validate_case(graph)
    except (ValueError, RecursionError) as exc:
        _fail("invalid_graph", str(exc))
    for category in _CATEGORIES:
        for row in graph[category]:
            _identifier(row["id"])
            permitted = {"evidence": {"id", "label", "kind", "active", "parents"},
                         "claims": {"id", "label", "supports"}, "decisions": {"id", "label", "requires"}}[category]
            if set(row) - permitted:
                _fail("unexpected_field", "Compact serialization cannot silently discard unknown node fields.")
    normalized = _canonical(graph)
    lines = []
    for row in normalized["evidence"]:
        lines.append(f"E {row['id']} {'R' if row['kind'] == 'root' else 'C'} {int(row['active'])} {','.join(row['parents']) or '-'}")
    for row in normalized["claims"]:
        lines.append(f"C {row['id']} {'|'.join('+'.join(clause) for clause in row['supports']) or '-'}")
    for row in normalized["decisions"]:
        lines.append(f"D {row['id']} {'+'.join(row['requires'])}")
    result = "\n".join(lines + ["END"])
    if len(result) > MAX_TEXT_CHARS:
        _fail("text_limit", f"Serialized graph exceeds {MAX_TEXT_CHARS} source characters.")
    return result
