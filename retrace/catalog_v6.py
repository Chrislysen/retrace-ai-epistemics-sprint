"""Attach original public source documents, never benchmark annotations, to v6 briefs."""
import copy
import json
from pathlib import Path

from .server_v5 import provenance_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def catalog_v6(demonstration):
    old = _read('results/retrace-v5-catalog.json')
    ambiguity = {row['id']: row for row in _read('data/ambiguity-v4-public.json')}
    fresh = {row['id']: row['public'] for row in _read('data/eligibility-v5-paired-staged.json')}
    briefs = [demonstration()]
    for original in old['briefs']:
        brief = copy.deepcopy(original)
        key = brief['id']
        if key in fresh:
            public = fresh[key]
        else:
            source_id = key.removeprefix('v5-replay-').removeprefix('exposure-diagnostic-')
            public = ambiguity[source_id]
        brief['source_documents'] = [{'id': doc['id'], 'text': doc['text']} for doc in public['documents']]
        brief['prior_display_prose'] = brief['prose']
        brief['prose'] = '\n\n'.join(d['id'] + ':\n' + d['text'] for d in brief['source_documents'])
        briefs.append(brief)
    return {'schema': 'retrace.v6-source-catalog.v1', 'status': 'offline', 'briefs': briefs,
            'provenance': 'Constructed v6 check and unchanged v5 graph outputs. Conservation reads original public source documents; benchmark commentary is excluded from source text.'}


def provenance_v6(brief, demonstration):
    fingerprint = provenance_fingerprint(brief)
    result = {'status': 'unverified_supplied_brief', 'fingerprint': fingerprint,
              'declared_reference_comparison': bool(brief.get('reference_comparison')),
              'scope': 'Local declaration match only; not authentication or source truth.'}
    for saved in catalog_v6(demonstration)['briefs']:
        if provenance_fingerprint(saved) != fingerprint:
            continue
        if saved.get('artificial_demonstration'):
            return {**result, 'status': 'matched_constructed_demonstration'}
        kinds = [key for key in ('reference_comparison', 'fresh_confirmation', 'post_hoc_replay') if saved.get(key)]
        if len(kinds) == 1:
            return {**result, 'status': 'matched_saved_catalog', 'kind': kinds[0], 'catalog_id': saved['id']}
    return result
