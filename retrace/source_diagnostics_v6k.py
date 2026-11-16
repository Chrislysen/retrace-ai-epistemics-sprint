"""Review-only localization around the unchanged frozen IR admission boundary.

No source relation is inferred, no rejected text is repaired, and no graph or
loadable IR is returned. Input-boundary errors raise ValueError; compiler/parser
errors from bounded public inputs are preserved in the diagnostic result.
"""
from copy import deepcopy
from hashlib import sha256
from itertools import product
import json

from .frontier_v6c_io import parse_object
from .source_ir_v6d import source_segments
from .source_ir_v6h import compile_ir
from .tiered_v6h import IDENT


SCHEMA = 'retrace.source-diagnostics.v6k.v1'
MAX_TEXT = 524288
SCOPE = (
    'Review-only localization of the unchanged frozen parser/compiler result. '
    'Not benchmark rescoring, textual entailment, source completeness or a repaired interpretation. '
    'No loadable graph or IR is returned. Locations use zero-based, end-exclusive Unicode '
    'code-point offsets and one-based lines/columns. A localized defect may not be the only defect.'
)
CAUGHT = (ValueError, TypeError, KeyError, RecursionError, OverflowError)


def _require(value, message):
    if not value:
        raise ValueError(message)


def _public_inputs(raw_text, documents, registry):
    _require(isinstance(raw_text, str) and len(raw_text) <= MAX_TEXT, 'Bounded raw text required')
    _require(isinstance(documents, list) and 1 <= len(documents) <= 64, 'Public source document bound')
    for doc in documents:
        _require(isinstance(doc, dict) and {'id', 'text'} <= set(doc) <= {'id', 'text', 'title'},
                 'Only public id/text/optional title document fields are accepted')
        _require(isinstance(doc['id'], str) and 1 <= len(doc['id']) <= 256, 'Bounded document ID required')
        _require(isinstance(doc['text'], str), 'Document text required')
        if 'title' in doc:
            _require(isinstance(doc['title'], str) and len(doc['title']) <= 512, 'Bounded public title required')
    _require(isinstance(registry, dict) and set(registry) == {'evidence', 'claims', 'decisions'},
             'Exact typed public registry required')
    seen = set()
    for category in ('evidence', 'claims', 'decisions'):
        ids = registry[category]
        _require(isinstance(ids, list) and len(ids) <= 250, 'Public registry array bound')
        for ident in ids:
            _require(isinstance(ident, str) and IDENT.fullmatch(ident) and ident != '-' and ident not in seen,
                     'Unique typed ASCII registry IDs required')
            seen.add(ident)
    _require(len(seen) <= 250, 'At most250 public registry IDs')
    # Reuse the frozen segment inventory for document count/text/span bounds.
    spans = source_segments(documents)
    try:
        raw_text.encode('utf-8')
        json.dumps({'source_documents': documents, 'registry': registry}, ensure_ascii=False,
                   sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except UnicodeError as exc:
        raise ValueError('Unicode scalar text required') from exc
    return {span['span_id']: span for span in spans}


def _error(exc):
    return {'type': type(exc).__name__, 'message': str(exc)}


def _location(text, start, end):
    cursor = 0
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        if start < cursor + len(line):
            return {'start': start, 'end': end, 'line': number, 'column': start - cursor + 1,
                    'text': text[start:end], 'offset_unit': 'unicode_code_points'}
        cursor += len(line)
    # All callers currently locate actual characters, not a guessed missing token.
    raise ValueError('Diagnostic location must refer to existing raw characters')


def _malformed_closing_fence(text):
    """Recognize only an existing terminal fence glued to a content line.

This does not parse the interior or say a corrected interior would be valid.
The frozen parser's admitted opener/closer test remains authoritative.
"""
    source = text.strip()
    lines = source.splitlines()
    if (len(lines) < 2 or lines[0].strip() not in ('```', '```json')
            or not source.endswith('```') or source.endswith('````')
            or lines[-1].strip() == '```'):
        return None
    end = len(text.rstrip())
    start = end - 3
    return {
        'kind': 'malformed_closing_fence_boundary',
        'message': 'The terminal three backticks share a line with content. The frozen whole-fence '
                   'parser requires the closing fence to occupy its own line.',
        'raw_location': _location(text, start, end),
        'other_errors_may_remain': True,
        'interior_parsed_or_repaired': False,
    }


def _declared_assignments(value):
    """Mirror only the frozen compiler's finite guard enumeration, not logic.

Called exclusively after the compiler reached its overlap check: all choice,
combination, proposition, scope and citation validation has already succeeded.
"""
    if value['combination']['mode'] == 'listed':
        return value['combination']['assignments']
    choices = {row['id']: row['options'] for row in value['choices']}
    return [dict(zip(choices, options)) for options in product(*choices.values())]


def _overlap(value, spans):
    # This walks the same <=32 declared assignments and ordered definitions as
    # compile_ir, and localizes its first duplicate key. It never evaluates a
    # Boolean body, chooses a reading, merges definitions, or validates a repair.
    for assignment in _declared_assignments(value):
        definitions = {}
        for index, prop in enumerate(value['propositions']):
            if prop['scope'] != 'current' or not all(assignment[k] == v for k, v in prop['when'].items()):
                continue
            key = prop['target'], prop['kind']
            if key in definitions:
                first_index, first = definitions[key]
                pair = []
                for position, item in ((first_index, first), (index, prop)):
                    cited = []
                    for ref in item['citations']:
                        span = deepcopy(spans[ref])
                        span['text_sha256'] = sha256(span['text'].encode('utf-8')).hexdigest()
                        span['offset_unit'] = 'unicode_code_points'
                        cited.append(span)
                    pair.append({'id': item['id'], 'proposition_index': position,
                                 'scope': item['scope'], 'when': deepcopy(item['when']),
                                 'citation_spans': cited})
                return {
                    'kind': 'overlapping_current_definitions',
                    'message': 'Two current definitions own the same target and kind in one declared assignment. '
                               'This reports an admission conflict, not necessarily logically inconsistent bodies.',
                    'target': prop['target'], 'definition_kind': prop['kind'], 'scope': 'current',
                    'assignment': deepcopy(assignment), 'proposition_ids': [first['id'], prop['id']],
                    'propositions': pair, 'other_errors_may_remain': True,
                    'citation_scope': 'Exact existing source locations only; no textual entailment verified.',
                }
            definitions[key] = index, prop
    return None


def diagnose(raw_text, source_documents, registry):
    """Return the original admission outcome and at most one exact localization.

``strict_bare_json`` describes parser format only; it is null if parsing failed.
It is not a benchmark success field. An admitted result with registry gaps is
still an incomplete identifier disposition. No candidates are exposed.
"""
    spans = _public_inputs(raw_text, source_documents, registry)
    packet = json.dumps({'source_documents': source_documents, 'registry': registry}, ensure_ascii=False,
                        sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    result = {
        'schema': SCHEMA, 'raw_text_sha256': sha256(raw_text.encode('utf-8')).hexdigest(),
        'source_packet_sha256': sha256(packet).hexdigest(), 'parser_admitted': False,
        'strict_bare_json': None, 'parser_error': None, 'compile_admitted': False,
        'compiler_status': None, 'registry_coverage_gaps': None, 'original_error': None,
        'localization_status': 'not_localized', 'diagnostics': [], 'repaired': False,
        'loadable_graph_returned': False, 'semantic_entailment_verified': False,
        'benchmark_rescored': False, 'scope': SCOPE,
    }
    # The exact original text goes to the unchanged compiler. No reconstructed
    # or normalized text, best-effort graph, or evaluation reference is used.
    try:
        compiled = compile_ir(raw_text, source_documents, registry)
    except CAUGHT as exc:
        result['original_error'] = _error(exc)
    else:
        result.update(compile_admitted=True, parser_admitted=True,
                      strict_bare_json=compiled['strict_bare_json'],
                      compiler_status=compiled['status'],
                      registry_coverage_gaps=deepcopy(compiled['registry_coverage_gaps']),
                      localization_status='not_needed')
        return result
    try:
        value, strict = parse_object(raw_text)
    except CAUGHT as exc:
        result['parser_error'] = _error(exc)
        found = _malformed_closing_fence(raw_text)
    else:
        result.update(parser_admitted=True, strict_bare_json=strict)
        found = (_overlap(value, spans) if result['original_error'] == {
            'type': 'ValueError', 'message': 'Overlapping definitions'} else None)
    if found is not None:
        result.update(localization_status='localized', diagnostics=[found])
    return result
