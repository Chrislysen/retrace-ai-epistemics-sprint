"""Versioned node-local ambiguity syntax, mechanically desugared to frozen v4.

Claims: ``C target OP(arguments)``. Evidence independence:
``E child ? bit UNVERIFIED_INDEPENDENCE(parent)``. Evidence source choice:
``E child C|? bit UNSPECIFIED_CHOICE(first, second)``.

Evidence operators alone may repeat the enclosing child as their leading
argument; it must match exactly. Claim operators never accept a redundant target.
Existing fixed records and standalone v4 declarations remain valid. This is a
language extension, not repair or retroactive admission under the v4 contract.
"""
from __future__ import annotations

import hashlib
import re

from .compact_graph import _source_lines
from .compact_v4 import compile_ambiguity as compile_v4

_IDENT = r"[A-Za-z0-9_-]+"
_CLAIM = re.compile(r"C[ \t]+(" + _IDENT + r")[ \t]+([A-Z_]+)\((.*)\)\Z", re.ASCII)
_EVIDENCE = re.compile(r"E[ \t]+(" + _IDENT + r")[ \t]+([RC?])[ \t]+([01])[ \t]+([A-Z_]+)\((.*)\)\Z", re.ASCII)
_KINDS = {"AMBIGUOUS_GATE", "UNVERIFIED_INDEPENDENCE", "UNSPECIFIED_SOURCE",
          "UNSPECIFIED_CHOICE", "AMBIGUOUS_QUALIFIER", "OPTIONAL_ROUTE"}


class CompactV5Error(ValueError):
    def __init__(self, code, message, line_number=None, canonical_line_number=None, assignment=None):
        self.code = code
        self.line_number = line_number
        self.canonical_line_number = canonical_line_number
        self.assignment = assignment
        super().__init__((f"Line {line_number}: " if line_number is not None else "") + message)


def _error(code, message, line):
    raise CompactV5Error(code, message, line)


def _local_evidence(match, line):
    target, declared_kind, active, operator, body = match.groups()
    if operator not in ("UNVERIFIED_INDEPENDENCE", "UNSPECIFIED_CHOICE"):
        _error("node_local_operator_type", "Evidence accepts only independence or sole-source choice operators.", line)
    if operator == "UNVERIFIED_INDEPENDENCE" and declared_kind != "?":
        _error("node_local_evidence_kind", "Independence requires an unresolved '?' evidence kind.", line)
    if operator == "UNSPECIFIED_CHOICE" and declared_kind not in ("C", "?"):
        _error("node_local_evidence_kind", "Source choice requires copy or unresolved evidence kind.", line)
    if ":" in body or ";" in body:
        _error("node_local_argument_syntax", "Evidence operator arguments are comma-separated IDs only.", line)
    arguments = [value.strip(" \t") for value in body.split(",")]
    arity = 1 if operator == "UNVERIFIED_INDEPENDENCE" else 2
    redundant = len(arguments) == arity + 1
    if redundant:
        if arguments[0] != target:
            _error("redundant_target_mismatch", "A repeated evidence target must exactly match its enclosing node ID.", line)
        arguments = arguments[1:]
    if len(arguments) != arity or any(not re.fullmatch(_IDENT, value, re.ASCII) or value == "-" for value in arguments):
        _error("node_local_argument_arity", "Wrong number or spelling of evidence source arguments.", line)
    rendered = ", ".join(arguments)
    standalone = (f"UNVERIFIED_INDEPENDENCE({target}, {rendered})" if operator == "UNVERIFIED_INDEPENDENCE"
                  else f"UNSPECIFIED_CHOICE({target}: {rendered})")
    return [f"E {target} ? {active} -", standalone], {
        "node_id": target, "operator": operator,
        "classification": "node_local_evidence_redundant_target" if redundant else "node_local_evidence",
        "redundant_target_validated": redundant,
    }


def compile_ambiguity(text: str, registry: dict | None = None) -> dict:
    """Desugar only declared node-local forms and delegate all semantics to v4.

    Exact source_text is retained, including CRLF and whole outer fences. The
    canonical_v4 text and physical line_mapping record every syntactic change.
    Fences, ASCII, registry, operator bound, cycles and all-branch validation use
    the unchanged frozen contracts. No gold, source-reference graph or model is
    consulted; no candidate branch is dropped or amended.
    """
    active_lines, fenced = _source_lines(text)
    available = {number for number, _ in active_lines}
    physical = text.replace("\r\n", "\n").split("\n")
    rendered, mapping, transformations = [], [], []
    ended = False
    for source_line, original in enumerate(physical, 1):
        line = original.strip(" \t")
        pieces, transformation = [original], None
        if source_line in available and line:
            if ended:
                _error("trailing_content", "No nonblank content is permitted after END.", source_line)
            if line == "END":
                ended = True
            else:
                claim = _CLAIM.fullmatch(line)
                evidence = _EVIDENCE.fullmatch(line)
                if claim:
                    target, operator, arguments = claim.groups()
                    if operator not in _KINDS or operator == "UNVERIFIED_INDEPENDENCE":
                        _error("node_local_operator_type", "Claim operator is unknown or has the wrong target category.", source_line)
                    # Explicitly prohibit claim target repetition/colon forms.
                    # Full arity/reference validation is performed by frozen v4.
                    if ":" in arguments:
                        _error("node_local_argument_syntax", "A node-local claim body contains operands only, never another target prefix.", source_line)
                    pieces = [f"C {target} ?", f"{operator}({target}: {arguments})"]
                    transformation = {"node_id": target, "operator": operator,
                                      "classification": "node_local_claim", "redundant_target_validated": False}
                elif evidence:
                    pieces, transformation = _local_evidence(evidence, source_line)
        canonical_numbers = []
        for offset, piece in enumerate(pieces):
            rendered.append(piece)
            canonical_numbers.append(len(rendered))
            mapping.append({"canonical_line": len(rendered), "source_line": source_line,
                            "role": ("placeholder" if offset == 0 else "operator") if transformation else "verbatim"})
        if transformation:
            transformations.append({**transformation, "source_line": source_line, "canonical_lines": canonical_numbers})
    canonical = "\n".join(rendered) if transformations else text
    try:
        compiled = compile_v4(canonical, registry)
    except ValueError as exc:
        canonical_line = getattr(exc, "line_number", None)
        source_line = mapping[canonical_line - 1]["source_line"] if canonical_line and canonical_line <= len(mapping) else None
        raise CompactV5Error(getattr(exc, "code", "v4_rejection"), f"Canonical v4 validation rejected the complete declaration: {exc}",
                             source_line, canonical_line, getattr(exc, "assignment", None)) from exc
    return {
        **compiled, "schema": "retrace.compact-ambiguity.v5", "source_text": text,
        "source_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "canonical_v4": canonical, "canonical_v4_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "strict_bare": not fenced, "outer_fence_removed": fenced,
        "line_mapping": mapping, "transformations": transformations,
        "transformation_classification": "node_local_syntax_extension" if transformations else "identity_v4",
        "scope": compiled["scope"] + [
            "V5 is a separate node-local language extension. Post-hoc replay does not change any original v4 admission or result.",
            "Desugaring preserves every node, local flag, operator argument, branch assignment and question; only explicitly specified syntax is converted.",
            "Source text is preserved exactly; canonical v4 text and line mapping make every syntactic conversion inspectable.",
        ],
    }


compile_ambiguity_v5 = compile_ambiguity
