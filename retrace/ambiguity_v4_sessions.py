"""Offline-only v4 diagnostic sessions and projected cost; no provider client.

Reuses the exact public v3 packets. Hidden reference data never enters sessions.
Preparing these files is neither a reservation nor authorization to dispatch.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import random
import re

ROOT = Path(__file__).resolve().parents[1]
CONDITION = 'ambiguity_preserving_v4'
SEED = 2026111334
ABSTENTION = 'ABSTAIN_UNREPRESENTABLE_AMBIGUITY'
BASELINE_HASHES = {
    'data/ambiguity-v3-staged.json': 'c6314a8c69d741436d8b99f7986f828af7f470c00b0aeaefeaad6b63fd25e431',
    'data/ambiguity-v3-freeze.json': '29a8abe5a5e9d0469c57dfac2ac7bfd69c0df3f375b663975763a053836239a4',
    'results/ambiguity-v3/gemma-4-31b-it/responses.jsonl': '251d65ecb3784f65273095a73b8414a9e9d309600040e5cfec3ca6ffdc122360',
    'results/ambiguity-v3-summary.json': '8ce4fb035085c7a313f5e9482eaf99b1afe9e02065a786a354f290b7ecffac58',
    'results/ambiguity-v3-budget-final.json': '12e92343dcaf672fd39712fea1684a24fafb3691f3abda1f0207c31776388c9b',
}

BASE = '''Read the supplied source packet and encode its complete support specification, preserving explicitly unresolved source ambiguity. Return one compact specification, not a chosen interpretation or a list of graphs.
Use exactly the evidence, claim and decision IDs in the supplied registry. Do not invent helper IDs, observations, parents, policies or uncertainty. Explicit source statements override ordinary-practice guesses. Do not resolve an unknown source fact by current evidence usability or by which decision you prefer.
Evidence originals are usable when locally eligible. A copy additionally requires ALL direct parents usable. Claims have OR between sufficient routes and AND within a route. Decisions require ALL named claims. Preserve local flags; inherited unavailability does not change a copy's local flag.
For determined records use these forms (uppercase illustrative IDs must be replaced with source IDs):
E ID R 1 -
E ID C 1 PARENT1,PARENT2
C ID ITEM1+ITEM2|ITEM3
C ID -
D ID CLAIM1+CLAIM2
An explicit local activity bit is always 0 or 1. The dash is the empty parent/no-route marker, not an ID.
For unresolved claims write C TARGET ? instead of a fixed claim body. For unresolved evidence kind or copy parent write E CHILD ? 0 - or E CHILD ? 1 -, preserving its local flag. Each placeholder MUST have exactly one resolving operator. Do not also give it a fixed rule.
Only these six operators are available, with the exact punctuation shown:
AMBIGUOUS_GATE(TARGET: A, B)
  A claim whose unresolved rule is either both A AND B, or either A OR B. This differs from an unknown selection of exactly one prerequisite.
UNVERIFIED_INDEPENDENCE(CHILD, PARENT)
  Evidence whose unresolved production history is either a copy with PARENT as its sole parent, or an independent original. Equal content alone proves neither reading.
UNSPECIFIED_SOURCE(TARGET: SOURCE)
  A claim whose entire unresolved support rule is either no admitted route, or SOURCE alone. It does not append an optional route to an existing fixed rule.
UNSPECIFIED_CHOICE(TARGET: A, B)
  With a claim placeholder: the prerequisite is exactly one designated item, either A alone or B alone. The selection is unknown. This MUST NOT become interchangeable OR routes in one graph.
  With an evidence placeholder: TARGET is definitely a copy, but its sole direct parent is either evidence A or evidence B. Each branch is a copy with exactly one parent; neither is a root or a two-parent copy.
AMBIGUOUS_QUALIFIER(TARGET: A, B, C)
  A claim whose unresolved grouping is either A OR (B AND C), or (A AND C) OR (B AND C). Preserve the roles and order of A, B and C.
OPTIONAL_ROUTE(TARGET: A, B, C; D)
  A claim with fixed singleton sufficient routes A, B and C, plus an unresolved additional singleton route D. The left comma list may contain one or more distinct fixed sources; the right side is exactly one distinct optional source. The alternatives are the fixed OR routes alone, or the fixed OR routes plus D. Use a claim placeholder; do not duplicate the fixed routes in a separate claim record.
All operand IDs within a multi-item operator must be distinct. Emit an operator only if BOTH of its precise alternatives are defensible from the source. Do not add uncertainty to determined relationships. Include every registry record exactly once, all required operators, and END on its own final line. No commentary, question answers, probabilities, Markdown or additional graphs.
At most u=4 unresolved operators are permitted. The compiler enumerates exactly all 2^u assignments, including 2^0=1 for a determined packet. Do not select, prune, rank or pre-expand the assignments yourself. Use multiple operators only when their full combination set is defensible; do not turn explicitly coupled choices into independent choices. Every branch must remain well typed and acyclic; one invalid branch rejects the complete specification.
If an explicitly unresolved source relationship cannot be represented exactly by these operators using the supplied IDs, or would require more than four operators, return only ABSTAIN_UNREPRESENTABLE_AMBIGUITY. This is an abstention, not a graph and not a successful extraction. Never guess a single reading or replace unknown selection with OR to avoid abstaining.'''


def public_projection(packet):
    """Whitelist source content, including nested fields; ignore all hidden data."""
    public = packet['public'] if 'public' in packet else packet
    result = {key: public[key] for key in ('id', 'title')}
    if not all(isinstance(result[k], str) and result[k] for k in result):
        raise ValueError('Public ID and title must be nonempty strings')
    documents = public['documents']
    if not isinstance(documents, list) or not documents:
        raise ValueError('A packet needs source documents')
    result['documents'] = [{key: d[key] for key in ('id', 'title', 'text')} for d in documents]
    if any(not isinstance(d[k], str) or not d[k] for d in result['documents'] for k in d):
        raise ValueError('Document fields must be nonempty strings')
    if len({d['id'] for d in result['documents']}) != len(documents):
        raise ValueError('Duplicate source document ID')
    registry = public['registry']
    result['registry'] = {key: registry[key] for key in ('evidence', 'claims', 'decisions')}
    ids = []
    for values in result['registry'].values():
        if not isinstance(values, list) or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', v) or v == '-' for v in values):
            raise ValueError('Typed registries must contain ASCII IDs')
        ids.extend(values)
    if len(ids) != len(set(ids)) or not result['registry']['decisions']:
        raise ValueError('Typed IDs must be unique and decisions nonempty')
    return deepcopy(result)


def build_public_corpus(packets):
    public = [public_projection(p) for p in packets]
    if len(public) != 10 or len({p['id'] for p in public}) != 10:
        raise ValueError('This paired diagnostic requires exactly 10 unique packets')
    return public


def build_sessions(packets, seed=SEED):
    sessions = [{'case_id': p['id'], 'family': 'ambiguity_v4_diagnostic_reuse',
                 'condition': CONDITION, 'response_kind': 'graph', 'instructions': BASE,
                 'steps': [{'phase': 'final', 'input': json.dumps(p, ensure_ascii=False, separators=(',', ':'))}]}
                for p in build_public_corpus(packets)]
    random.Random(seed).shuffle(sessions)
    return sessions


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def project_cost(baseline_credits='40.54847472', requests=10, context_tokens=256000,
                 max_output_tokens=4096, input_rate='0.09', output_rate='0.34'):
    """Decimal-only hypothetical bound; no budget ledger is read or changed."""
    if type(requests) is not int or requests != 10:
        raise ValueError('The staged pilot contains exactly 10 hypothetical requests')
    if type(context_tokens) is not int or context_tokens <= 0 or type(max_output_tokens) is not int or max_output_tokens != 4096:
        raise ValueError('Invalid context/output bound')
    baseline, incoming, outgoing = map(Decimal, (baseline_credits, input_rate, output_rate))
    if not all(x.is_finite() and x >= 0 for x in (baseline, incoming, outgoing)):
        raise ValueError('Credit values must be finite and nonnegative')
    one = (Decimal(context_tokens) * incoming + Decimal(max_output_tokens) * outgoing) / Decimal(1000000)
    new = one * requests
    total = baseline + new
    if total > Decimal(50):
        raise ValueError('Projected cumulative cap exceeded')
    fmt = lambda value: format(value, '.8f')
    return {'status': 'projected_only', 'reservation_created': False, 'dispatch_authorized': False,
            'baseline_committed_credits': fmt(baseline), 'per_request_bound_credits': fmt(one),
            'hypothetical_new_bound_credits': fmt(new), 'projected_cumulative_bound_credits': fmt(total),
            'projected_remaining_under_50_credits': fmt(Decimal(50) - total),
            'approved_cumulative_cap_credits': '50.00000000',
            'method': 'full_context_uncached_input_plus_max_output_no_refunds'}


def build_config(root, public, sessions):
    root = Path(root)
    for path, expected in BASELINE_HASHES.items():
        if sha256_bytes((root / path).read_bytes()) != expected:
            raise ValueError('Preserved v3 evidence hash mismatch: ' + path)
    source = json.loads((root / 'data/ambiguity-v3-staged.json').read_text(encoding='utf-8'))
    if public != build_public_corpus(source) or sessions != build_sessions(public):
        raise ValueError('Projected artifacts differ from the exact public corpus or fixed session builder')
    ledger = json.loads((root / 'results/ambiguity-v3-budget-final.json').read_text(encoding='utf-8'))
    costs = project_cost(ledger['current_conservative_reserved_credits'])
    return {'schema': 'retrace.ambiguity-v4-offline-config.v1', 'status': 'projected_only',
            'dispatch_authorized': False, 'reservation_created': False,
            'requires_later_user_approval': True, 'prepared_offline': True,
            'model': 'gemma-4-31b-it', 'session_count': 10, 'hypothetical_requests': 10,
            'max_requests': 10, 'max_output_tokens': 4096, 'temperature': 0,
            'concurrency': 1, 'min_interval_ms': 3100, 'timeout_ms': 120000, 'retries': 0,
            'store': False, 'agentic_memory': False, 'tools': [], 'tool_choice': 'none',
            'condition': CONDITION, 'session_shuffle_seed': SEED,
            'compiler_module': 'retrace.compact_v4', 'max_uncertainty_operators': 4,
            'expansion': 'all 2^u assignments; no pruning, sampling or branch repair',
            'abstention_token': ABSTENTION, 'abstention_counts_as_admitted': False,
            'pricing': {'input_credits_per_million': '0.09', 'cached_input_credits_per_million': '0.05',
                        'output_credits_per_million': '0.34', 'full_context_tokens': 256000,
                        'source': 'https://docs.adaptionlabs.ai/inference-stacks/models/',
                        'verification_status': 'reverified_by_root', 'verified_date': '2026-11-13',
                        'verification_method': 'Direct PowerShell Invoke-WebRequest of official models page after web open could not retrieve; extracted Gemma values matched the earlier snapshot.',
                        'cached_rate_used_in_projection': False},
            'cost_projection': costs,
            'comparison': {'unit': 'same public packet ID', 'fresh_heldout': False,
                           'design': 'post-hoc paired diagnostic reuse of all 10 v3 packets',
                           'primary_diagnostic_subset': ['ambiguity-v3-01', 'ambiguity-v3-02', 'ambiguity-v3-04'],
                           'subset_selected_after_v3_results': True,
                           'baseline': 'two actual v3 directed completions and their admitted union, unchanged',
                           'prospective_v4': 'one hypothetical completion then exhaustive typed expansion',
                           'typed_extensions': ['claim/evidence UNSPECIFIED_CHOICE', 'AMBIGUOUS_QUALIFIER', 'OPTIONAL_ROUTE'],
                           'caution': 'Different call counts, prompts and representations; no isolated causal format estimate.'},
            'baseline_evidence_sha256': dict(BASELINE_HASHES),
            'public_sha256': sha256_bytes(json_bytes(public)),
            'sessions_sha256': sha256_bytes(json_bytes(sessions)),
            'fixed_instructions_sha256': sha256_bytes(BASE.encode('utf-8')),
            'public_packet_sha256': {p['id']: sha256_bytes(json_bytes(p)) for p in public},
            'note': 'Preparation creates no provider request, live result, reservation ID or ledger entry. Any later run needs explicit user approval, a new ledger reservation and verified frozen artifacts.'}


def prepare_artifacts(root=ROOT):
    root = Path(root)
    paths = [root / 'data' / name for name in ('ambiguity-v4-public.json', 'ambiguity-v4-sessions.json', 'ambiguity-v4-config.json')]
    if (root / 'data/ambiguity-v4-freeze.json').exists() or any(p.exists() for p in paths):
        raise FileExistsError('Refusing to overwrite prepared or frozen v4 artifacts')
    packets = json.loads((root / 'data/ambiguity-v3-staged.json').read_text(encoding='utf-8'))
    public = build_public_corpus(packets)
    sessions = build_sessions(public)
    config = build_config(root, public, sessions)
    for path, value in zip(paths, (public, sessions, config)):
        with path.open('xb') as stream:
            stream.write(json_bytes(value))
    return config


if __name__ == '__main__':
    config = prepare_artifacts()
    print(json.dumps({'status': config['status'], 'sessions': config['session_count'],
                      'cost_projection': config['cost_projection']}, indent=2))
