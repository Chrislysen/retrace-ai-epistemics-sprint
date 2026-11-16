"""Source-proposition IR for scoped undercutters and explicit polar warrants.

Exact span binding is necessary for admission, not proof of textual entailment.
No gold graph, regex relation extraction or automatic graph repair is used.
"""
from copy import deepcopy
from hashlib import sha256
from itertools import product
import json

from .frontier_v6c_io import parse_object
from .source_ir_v6d import source_segments, model_source
from .source_ir_v6c import _token_in
from .tiered_v6h import SCHEMA as GRAPH_SCHEMA, IDENT, validate, require
from .boolean_v6h import validate_expr

SCHEMA = 'retrace.source-ir.v6h'
TYPES = {'evidence': 'evidence', 'claim': 'claims', 'decision': 'decisions'}
SCOPES = {'current', 'historical', 'hypothetical', 'proposed'}


def _fields(row, keys):
    require(isinstance(row, dict) and set(row) == set(keys), 'Exact fields required: ' + ','.join(sorted(keys)))


def _ident(value):
    require(isinstance(value, str) and IDENT.fullmatch(value) and value != '-', 'ASCII ID required')
    return value


def compile_ir(value, documents, registry):
    strict = True
    if isinstance(value, str):
        require(len(value) <= 524288, 'IR text bound')
        value, strict = parse_object(value)
    else:
        value = deepcopy(value)
    require(len(json.dumps(value, ensure_ascii=False, allow_nan=False)) <= 524288, 'IR bound')
    source = model_source(documents, registry)
    segments = {row['span_id']: row for row in source_segments(documents)}
    _fields(value, {'schema', 'entities', 'bindings', 'choices', 'combination', 'propositions'})
    require(value['schema'] == SCHEMA, 'IR version')
    _fields(registry, set(TYPES.values()))
    vocabulary = {}
    for singular, plural in TYPES.items():
        require(isinstance(registry[plural], list), 'Registry arrays')
        for ident in registry[plural]:
            _ident(ident); require(ident not in vocabulary, 'Registry unique IDs'); vocabulary[ident] = singular
    def citations(values, empty=False):
        require(isinstance(values, list) and (0 if empty else 1) <= len(values) <= 8, '1..8 citation spans')
        require(all(isinstance(ref, str) and ref in segments for ref in values) and len(set(values)) == len(values), 'Unknown or duplicate citation span')
        return values
    require(isinstance(value['entities'], list) and 1 <= len(value['entities']) <= 250, 'Entity bound')
    entities = {}
    for row in value['entities']:
        _fields(row, {'id', 'type', 'operational', 'citations'})
        ident = _ident(row['id']); require(ident not in entities, 'Duplicate entity')
        require(isinstance(row['type'], str) and row['type'] in TYPES and type(row['operational']) is bool, 'Entity type/status')
        citations(row['citations'])
        require(any(_token_in(ident, segments[cite]['text']) for cite in row['citations']), 'Entity must occur literally in citation')
        require(ident not in vocabulary or row['type'] == vocabulary[ident], 'Registry type conflict')
        entities[ident] = row
    operational = {ident for ident, row in entities.items() if row['operational']}
    require(bool(operational), 'Empty operational declaration')
    bindings = {}
    require(isinstance(value['bindings'], list) and len(value['bindings']) <= 256, 'Binding bound')
    for row in value['bindings']:
        _fields(row, {'id', 'entity', 'mention', 'antecedent'})
        bid = _ident(row['id']); require(bid not in bindings and isinstance(row['entity'], str) and row['entity'] in entities, 'Binding identity')
        citations([row['mention']]); citations([row['antecedent']])
        require(_token_in(row['entity'], segments[row['antecedent']]['text']), 'Binding antecedent must name entity')
        bindings[bid] = row
    choices = {}
    require(isinstance(value['choices'], list) and len(value['choices']) <= 5, 'At most5 binary choices')
    for row in value['choices']:
        _fields(row, {'id', 'options', 'citations'})
        cid = _ident(row['id']); require(cid not in choices, 'Duplicate choice')
        options = row['options']; require(isinstance(options, list) and len(options) == 2, 'Binary choice required')
        options = [_ident(option) for option in options]; require(options[0] != options[1], 'Distinct options')
        citations(row['citations']); choices[cid] = options
    combo = value['combination']; _fields(combo, {'mode', 'assignments', 'citations'})
    require(combo['mode'] in ('cartesian', 'listed'), 'Combination mode')
    citations(combo['citations'], empty=combo['mode'] == 'cartesian' and len(choices) <= 1)
    if combo['mode'] == 'cartesian':
        require(combo['assignments'] == [], 'Cartesian assignments must be empty')
        assignments = [dict(zip(choices, options)) for options in product(*choices.values())]
    else:
        assignments = combo['assignments']
        require(isinstance(assignments, list) and 1 <= len(assignments) <= 32, 'Listed assignment bound')
        seen = set()
        for assignment in assignments:
            _fields(assignment, set(choices))
            require(all(isinstance(v, str) and v in choices[k] for k,v in assignment.items()), 'Listed option unknown')
            key = tuple(sorted(assignment.items())); require(key not in seen, 'Repeated assignment'); seen.add(key)
        require(all({a[cid] for a in assignments} == set(options) for cid, options in choices.items()), 'Listed unused option')
    propositions = value['propositions']; require(isinstance(propositions, list) and 1 <= len(propositions) <= 2048, 'Proposition bound')
    seen, used = set(), set()
    expr_ids = {ident for ident, row in entities.items() if row['type'] != 'decision'}
    def check_undercutters(expr):
        op,arg=next(iter(expr.items()))
        if op in ('all','any'):
            for child in arg:check_undercutters(child)
        elif op=='unless':
            require(all(entities[ref]['type']=='evidence' for ref in validate_expr(arg['undercutter'],expr_ids)), 'Undercutter references evidence only in every scope')
            check_undercutters(arg['support']);check_undercutters(arg['undercutter'])
    def typed_refs(values, kind, empty=False):
        require(isinstance(values, list) and (empty or bool(values)), 'Explicit reference array')
        require(all(isinstance(v, str) and v in entities and entities[v]['type'] == kind for v in values), 'Typed refs')
        require(len(values) == len(set(values)), 'Duplicate ref')
        return set(values)
    for prop in propositions:
        _fields(prop, {'id', 'kind', 'target', 'body', 'scope', 'when', 'citations', 'bindings'})
        pid = _ident(prop['id']); require(pid not in seen, 'Duplicate proposition'); seen.add(pid)
        require(isinstance(prop['target'], str) and prop['target'] in entities, 'Unknown target')
        target = prop['target']; category = entities[target]['type']; body = prop['body']; kind = prop['kind']
        require(isinstance(prop['scope'], str) and prop['scope'] in SCOPES, 'Explicit scope')
        require(isinstance(prop['when'], dict) and all(k in choices and isinstance(v,str) and v in choices[k] for k,v in prop['when'].items()), 'Choice condition')
        if prop['scope'] == 'current': used.update(prop['when'])
        citations(prop['citations'])
        if kind == 'eligibility':
            _fields(body, {'active'}); require(category == 'evidence' and type(body['active']) is bool, 'Eligibility type'); refs = set()
        elif kind == 'origin':
            _fields(body, {'kind', 'parents'}); require(category == 'evidence' and body['kind'] in ('root','copy','unknown'), 'Origin type')
            refs = typed_refs(body['parents'], 'evidence', empty=body['kind'] != 'copy')
            require(body['kind'] != 'root' or not refs, 'Root parents')
        elif kind == 'support':
            _fields(body, {'positive', 'negative'}); require(category == 'claim', 'Support target')
            refs = validate_expr(body['positive'], expr_ids) | validate_expr(body['negative'], expr_ids)
            check_undercutters(body['positive']);check_undercutters(body['negative'])
        elif kind == 'requirement':
            _fields(body, {'requires'}); require(category == 'decision', 'Requirement target')
            refs = typed_refs(body['requires'], 'claim')
        else:
            raise ValueError('Unknown proposition kind')
        require(target not in refs, 'Self-reference')
        if prop['scope'] == 'current':
            require(target in operational and refs <= operational, 'Current inactive entity reference')
        bids = prop['bindings']
        require(isinstance(bids,list) and len(bids)<=8 and all(isinstance(b,str) and b in bindings for b in bids) and len(bids)==len(set(bids)), 'Top-level binding ID array')
        for bid in bids:
            binding = bindings[bid]
            require(binding['entity'] in refs | {target} and binding['mention'] in prop['citations'], 'Binding must be used/cited by this proposition')
    require(used == set(choices), 'Unused choice axis')
    candidates = []
    for number, assignment in enumerate(assignments):
        definitions = {}
        for prop in propositions:
            if prop['scope'] == 'current' and all(assignment[k] == v for k,v in prop['when'].items()):
                key = prop['target'], prop['kind']; require(key not in definitions, 'Overlapping definitions')
                definitions[key] = prop['body']
        graph = {'schema': GRAPH_SCHEMA, 'evidence': [], 'claims': [], 'decisions': []}
        for ident in sorted(operational):
            typ = entities[ident]['type']
            required = ('eligibility','origin') if typ == 'evidence' else ('support',) if typ == 'claim' else ('requirement',)
            require(all((ident,kind) in definitions for kind in required), 'Missing per-world definition')
            if typ == 'evidence': row = {'id':ident, **definitions[(ident,'eligibility')], **definitions[(ident,'origin')]}
            else: row = {'id':ident, **definitions[(ident,required[0])]}
            graph[TYPES[typ]].append(row)
        validate(graph)
        candidates.append({'id':f'world-{number:04d}','assignment':assignment,'graph':graph})
    missing = sorted(set(vocabulary)-set(entities))
    return {'schema':'retrace.source-ir-compilation.v6h','original_ir':value,'candidates':candidates,
            'candidate_count':len(candidates),'registry_coverage_gaps':missing,
            'status':'reference_free_coverage_gap' if missing else 'compiled_declared_contract',
            'strict_bare_json':strict,'source_sha256':sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            'citations_verified':True,'semantic_entailment_verified':False,
            'scope':'Every admitted branch compiled without repair. Exact source spans verify location only; this is not a source-completeness or truth certificate.'}
