"""Versioned offline composition; never rewrites the frozen v1–v3 engine."""
from __future__ import annotations

import copy
import hashlib
import json

from .compact_v4 import compile_ambiguity
from .coverage_v4 import analyze_root_coverage
from .stress import analyze_stress


def analyze_v4(brief, state=None):
    """Compile declared choices, resolve them, then check effective root coverage.

    compact_v4, when present, is the authoritative graph declaration. Generated
    candidates/questions carried by an exported session are disposable derived
    fields, never used as a second source of truth. Ordinary candidate briefs
    can also receive the common-cause withdrawal audit without recompilation.
    """
    if not isinstance(brief, dict):
        raise ValueError('brief must be an object')
    working = copy.deepcopy(brief)
    compilation = None
    if 'compact_v4' in working:
        compilation = compile_ambiguity(working['compact_v4'], working.get('registry'))
        working['candidates'] = compilation['candidates']
        working['questions'] = compilation['questions']
    result = analyze_stress(working, state)
    effective = []
    for candidate in working['candidates']:
        cid = candidate['id']
        if cid not in result['candidate_ids']:
            continue
        row = copy.deepcopy(candidate)
        for evidence in row['graph']['evidence']:
            evidence['active'] = result['revocation_flags'][evidence['id']]['by_candidate'][cid]['effective_active']
        effective.append(row)
    # Validate scoped attestations against the complete supplied universe before
    # projecting them onto the retained set. Eliminated IDs cannot hide typos.
    attestations = working.get('verified_independence', [])
    attestations = [] if attestations is None else attestations
    if not isinstance(attestations, list):
        raise ValueError('verified_independence must be an array or null')
    if attestations:
        analyze_root_coverage(working['candidates'], attestations)
    projected = []
    for attestation in attestations:
        row = copy.deepcopy(attestation)
        if 'candidate_ids' in row:
            row['candidate_ids'] = [cid for cid in row['candidate_ids'] if cid in result['candidate_ids']]
            if not row['candidate_ids']:
                continue
        projected.append(row)
    root_coverage = analyze_root_coverage(effective, projected)
    # Bind complete original inputs as well as their derived analysis. The
    # fingerprint is an integrity marker, not external attestation validation.
    fingerprint = hashlib.sha256(json.dumps({'brief': brief, 'state': result['state']},
                              sort_keys=True, ensure_ascii=True, separators=(',', ':'),
                              allow_nan=False).encode('utf-8')).hexdigest()
    return {**result, 'schema': 'retrace.stress.v4', 'v4_input_fingerprint': fingerprint,
            'compiled_brief': working, 'ambiguity_compilation': compilation,
            'root_coverage': root_coverage,
            'scope': result['scope'] + [
                'Compiled coverage is exact only for the explicitly declared binary ambiguity tokens; omitted tokens and source misreadings remain possible.',
                'The common-cause guard tests withdrawal of a hypothetical shared ancestor. Merging available roots alone does not revoke support.',
                'Verified-independence entries are externally supplied declarations with a stated basis, not facts authenticated by this engine.',
            ]}
