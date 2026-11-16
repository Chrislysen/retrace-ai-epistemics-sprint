"""Explicit, bounded ambiguity declarations over the frozen E/C/D grammar.

A claim placeholder is ``C target ?``. An evidence placeholder is
``E target ? 0|1 -``; its local eligibility is never inferred or changed.
Each placeholder has exactly one complete-body operator, on a separate line:

    AMBIGUOUS_GATE(target: a, b)
        false: a AND b; true: a OR b
    UNVERIFIED_INDEPENDENCE(child, parent)
        false: COPY(parent); true: ROOT
    UNSPECIFIED_SOURCE(target: source)
        false: no claim routes; true: source alone
    UNSPECIFIED_CHOICE(target: a, b)
        claim: false a alone / true b alone (never OR)
        evidence: false COPY(a) / true COPY(b)
    AMBIGUOUS_QUALIFIER(target: a, b, c)
        false: a OR (b AND c); true: (a AND c) OR (b AND c)
    OPTIONAL_ROUTE(target: a, b, c; d)
        false: listed fixed singleton routes; true: those routes plus d alone

The optional-route fixed list has at least one distinct item; its optional item
must differ from all fixed items. All multi-item operators require distinct
operand IDs so their factual question does not compare an item with itself.
Four binary declarations yield sixteen full
assignment branches. No branch is dropped or deduplicated, including branches
whose current decision outcomes agree. Any invalid branch rejects the complete
packet. This compiler enumerates supplied hypotheses; it does not establish that
they are complete, source-faithful, jointly plausible, or real-world truth.
"""

from __future__ import annotations

import itertools
import re

from .compact_graph import MAX_NODES, _source_lines, parse_compact_output

MAX_UNCERTAINTIES = 4
_ID = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_OPERATOR = re.compile(r"([A-Z_]+)\((.*)\)\Z", re.ASCII)
_KINDS = {"AMBIGUOUS_GATE", "UNVERIFIED_INDEPENDENCE", "UNSPECIFIED_SOURCE",
          "UNSPECIFIED_CHOICE", "AMBIGUOUS_QUALIFIER", "OPTIONAL_ROUTE"}


class CompactV4Error(ValueError):
    """An ambiguity admission error, optionally identifying an invalid branch."""

    def __init__(self, code, message, line_number=None, assignment=None):
        self.code = code
        self.line_number = line_number
        self.assignment = assignment
        prefix = f"Line {line_number}: " if line_number is not None else ""
        super().__init__(prefix + message)


def _fail(code, message, line=None):
    raise CompactV4Error(code, message, line)


def _identifier(value, line):
    value = value.strip(" \t")
    if not _ID.fullmatch(value) or value == "-":
        _fail("invalid_id", "IDs use ASCII letters, digits, underscores or hyphens; '-' is reserved.", line)
    return value


def _operator(line, number):
    matched = _OPERATOR.fullmatch(line)
    if not matched or matched[1] not in _KINDS:
        _fail("unknown_operator", "Expected an E/C/D record, a declared ambiguity operator, or END.", number)
    kind, body = matched.groups()
    if kind == "UNVERIFIED_INDEPENDENCE":
        parts = body.split(",")
        if len(parts) != 2 or ":" in body or ";" in body:
            _fail("operator_arity", "Use UNVERIFIED_INDEPENDENCE(child, parent).", number)
        target, arguments = _identifier(parts[0], number), [_identifier(parts[1], number)]
    else:
        parts = body.split(":")
        if len(parts) != 2:
            _fail("operator_syntax", "Claim/source-choice operators require target: arguments.", number)
        target, raw_arguments = _identifier(parts[0], number), parts[1]
        if kind == "OPTIONAL_ROUTE":
            sides = raw_arguments.split(";")
            if len(sides) != 2:
                _fail("operator_syntax", "OPTIONAL_ROUTE requires fixed singleton sources; one optional source.", number)
            base = [_identifier(item, number) for item in sides[0].split(",")]
            optional = _identifier(sides[1], number)
            if len(base) != len(set(base)) or optional in base:
                _fail("duplicate_argument", "OPTIONAL_ROUTE sources must be distinct.", number)
            arguments = base + [optional]
        else:
            expected = {"AMBIGUOUS_GATE": 2, "UNSPECIFIED_SOURCE": 1,
                        "UNSPECIFIED_CHOICE": 2, "AMBIGUOUS_QUALIFIER": 3}[kind]
            arguments = [_identifier(item, number) for item in raw_arguments.split(",")]
            if len(arguments) != expected:
                _fail("operator_arity", f"{kind} requires exactly {expected} argument IDs.", number)
    if len(arguments) != len(set(arguments)):
        _fail("duplicate_argument", "Operator operands must be distinct source IDs.", number)
    return {"id": "resolve_" + target, "kind": kind, "target": target,
            "arguments": arguments, "line_number": number}


def _options(operator, placeholder):
    kind, target, args = operator["kind"], operator["target"], operator["arguments"]
    evidence = placeholder["category"] == "evidence"
    if kind == "UNVERIFIED_INDEPENDENCE":
        parent = args[0]
        replacements = [{"kind": "copy", "parents": [parent]}, {"kind": "root", "parents": []}]
        labels = [f"Copy whose sole parent is {parent}", "Independent original record"]
        question = f"Is {target} an independent original record rather than a copy whose sole parent is {parent}?"
    elif kind == "UNSPECIFIED_CHOICE" and evidence:
        first, second = args
        replacements = [{"kind": "copy", "parents": [first]}, {"kind": "copy", "parents": [second]}]
        labels = [f"Copy of {first} alone", f"Copy of {second} alone"]
        question = f"Is {second}, rather than {first}, the sole copied source of {target}?"
    elif kind == "AMBIGUOUS_GATE":
        first, second = args
        replacements = [{"supports": [[first, second]]}, {"supports": [[first], [second]]}]
        labels = [f"{first} and {second} jointly required", f"Either {first} alone or {second} alone is sufficient"]
        question = f"Does the rule for {target} permit either {first} alone or {second} alone as a complete sufficient route?"
    elif kind == "UNSPECIFIED_SOURCE":
        source = args[0]
        replacements = [{"supports": []}, {"supports": [[source]]}]
        labels = ["No sufficient route admitted", f"{source} alone is admitted as sufficient"]
        question = f"Is {source} explicitly admitted as a sufficient route for {target}?"
    elif kind == "UNSPECIFIED_CHOICE":
        first, second = args
        replacements = [{"supports": [[first]]}, {"supports": [[second]]}]
        labels = [f"{first} alone is the designated route", f"{second} alone is the designated route"]
        question = f"Is {second}, rather than {first}, the designated sole sufficient route for {target}?"
    elif kind == "AMBIGUOUS_QUALIFIER":
        first, second, qualifier = args
        replacements = [{"supports": [[first], [second, qualifier]]},
                        {"supports": [[first, qualifier], [second, qualifier]]}]
        labels = [f"{qualifier} qualifies only the {second} route", f"{qualifier} qualifies both routes"]
        question = f"Does qualifier {qualifier} apply to the {first} route as well as the {second} route for {target}?"
    else:
        base, optional = args[:-1], args[-1]
        replacements = [{"supports": [[item] for item in base]},
                        {"supports": [[item] for item in base] + [[optional]]}]
        labels = ["Only the listed fixed singleton routes are admitted",
                  f"The fixed routes and {optional} alone are admitted"]
        question = f"Is {optional} admitted as an additional sufficient route for {target} alongside the listed fixed routes?"
    if evidence:
        for replacement in replacements:
            replacement["active"] = placeholder["active"]
    return [{"answer": answer, "label": label, "replacement": replacement}
            for answer, label, replacement in zip((False, True), labels, replacements)], question


def compile_ambiguity(text: str, registry: dict | None = None) -> dict:
    """Compile every assignment of up to four explicit binary declarations.

    Fixed records retain the frozen compact grammar. Source admission preserves
    its exact ASCII rules and permits the same single whole-response unlabeled,
    text or plaintext fence, reported through strict_bare/outer_fence_removed.
    Fences inside the response, truncated packets and prose wrappers are rejected.
    Operator order does not change stable IDs, assignment order or graphs.

    Questions label source-factual choices, independent of current support.
    Their answer tables encode branch assignments; none is asserted correct.
    Pass candidates/questions directly to analyze_stress, selecting an explicit
    allowed_withdrawals scope if more than sixteen evidence records are present.
    """
    lines, fenced = _source_lines(text)
    declarations, placeholders, operators = {}, {}, []
    ended = False
    for number, original in lines:
        line = original.strip(" \t")
        if not line:
            continue
        if ended:
            _fail("trailing_content", "No nonblank content is permitted after END.", number)
        if line == "END":
            ended = True
            continue
        parts = re.split(r"[ \t]+", line)
        if parts[0] not in {"E", "C", "D"}:
            operators.append(_operator(line, number))
            if len(operators) > MAX_UNCERTAINTIES:
                _fail("uncertainty_limit", "At most four binary ambiguity declarations are supported.", number)
            continue
        tag = parts[0]
        if len(parts) != (5 if tag == "E" else 3):
            _fail("field_count", "Wrong number of compact node fields.", number)
        identifier = _identifier(parts[1], number)
        if identifier in declarations:
            _fail("duplicate_id", "Every node must have exactly one declaration.", number)
        if len(declarations) >= MAX_NODES:
            _fail("node_limit", f"At most {MAX_NODES} nodes are supported.", number)
        category = {"E": "evidence", "C": "claims", "D": "decisions"}[tag]
        declarations[identifier] = {"category": category, "line_number": number}
        if tag == "C" and parts[2] == "?":
            placeholders[identifier] = declarations[identifier]
        elif tag == "E" and parts[2] == "?":
            if parts[3] not in {"0", "1"} or parts[4] != "-":
                _fail("placeholder_fields", "Evidence placeholders require E ID ? 0|1 -.", number)
            placeholders[identifier] = {**declarations[identifier], "active": parts[3] == "1"}
    if not ended:
        _fail("missing_end", "Output must explicitly end with END.")
    operators.sort(key=lambda row: row["target"])
    claimed = set()
    for operator in operators:
        target, kind, number = operator["target"], operator["kind"], operator["line_number"]
        if target in claimed:
            _fail("overlapping_operators", "Multiple ambiguity declarations cannot own the same target.", number)
        claimed.add(target)
        if target not in placeholders:
            _fail("missing_placeholder", "An operator must own one unresolved node declaration, never a competing fixed rule.", number)
        target_category = placeholders[target]["category"]
        allowed_target = {"evidence", "claims"} if kind == "UNSPECIFIED_CHOICE" else {"evidence"} if kind == "UNVERIFIED_INDEPENDENCE" else {"claims"}
        if target_category not in allowed_target:
            _fail("operator_target_type", "Operator target has the wrong node category.", number)
        allowed_sources = {"evidence"} if target_category == "evidence" else {"evidence", "claims"}
        for argument in operator["arguments"]:
            if argument not in declarations or declarations[argument]["category"] not in allowed_sources:
                _fail("operator_argument_type", "Operator sources must be existing nodes of the permitted category.", number)
        operator["options"], operator["question_label"] = _options(operator, placeholders[target])
    if claimed != set(placeholders):
        _fail("unresolved_placeholder", "Every unresolved placeholder requires exactly one ambiguity declaration.")

    candidates = []
    operator_lines = {operator["line_number"] for operator in operators}
    for answers in itertools.product((False, True), repeat=len(operators)):
        assignment = {operator["id"]: answer for operator, answer in zip(operators, answers)}
        replacements = {}
        for operator, answer in zip(operators, answers):
            option = operator["options"][int(answer)]["replacement"]
            target = operator["target"]
            if "supports" in option:
                body = "|".join("+".join(clause) for clause in option["supports"]) or "-"
                replacements[placeholders[target]["line_number"]] = f"C {target} {body}"
            else:
                kind = "R" if option["kind"] == "root" else "C"
                parents = ",".join(option["parents"]) or "-"
                replacements[placeholders[target]["line_number"]] = f"E {target} {kind} {int(option['active'])} {parents}"
        # Keep physical line positions, even when a whole outer fence was used.
        expanded = [""] * (lines[-1][0] if lines else 0)
        for number, original in lines:
            expanded[number - 1] = "" if number in operator_lines else replacements.get(number, original)
        try:
            graph = parse_compact_output("\n".join(expanded), registry)["graph"]
        except ValueError as exc:
            raise CompactV4Error("invalid_branch", f"An assignment is invalid; the whole packet is rejected: {exc}",
                                 getattr(exc, "line_number", None), assignment) from exc
        bits = "".join("1" if answer else "0" for answer in answers)
        candidates.append({"id": "branch-" + (bits or "fixed"), "graph": graph, "assignment": assignment})
    questions = [{"id": operator["id"], "label": operator["question_label"], "cost": 1,
                  "answers": {candidate["id"]: candidate["assignment"][operator["id"]] for candidate in candidates}}
                 for operator in operators]
    return {
        "schema": "retrace.compact-ambiguity.v4", "source_text": text,
        "strict_bare": not fenced, "outer_fence_removed": fenced,
        "operators": operators, "candidates": candidates, "questions": questions,
        "uncertainty_count": len(operators), "expected_candidate_count": 2 ** len(operators),
        "candidate_count": len(candidates),
        "expansion_policy": "Full Cartesian product of declared binary choices; no pruning or deduplication.",
        "scope": [
            "Operators enumerate explicitly supplied hypotheses, not inferred source truth or complete possible worlds.",
            "Every assignment branch is retained, even if its current decision outcomes agree with another branch. Repeated source operands are rejected as degenerate declarations; any invalid branch rejects the whole declaration.",
            "Factual question answers identify declared choices; no answer, probability or statistical independence is assumed.",
            "Declared choices may omit jointly plausible alternatives or include implausible combinations; graph validation does not settle real-world compatibility.",
            "Local evidence activity stays explicit and unchanged. Source withdrawal removes admissible support without asserting falsity.",
        ],
    }
