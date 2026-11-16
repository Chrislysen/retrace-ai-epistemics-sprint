"""Add a source-conservation review gate without changing frozen graph semantics."""
from __future__ import annotations

import copy

from .engine_v5 import analyze_v5
from .conservation_v6 import audit_conservation


def analyze_v6(brief, state=None):
    if not isinstance(brief, dict):
        raise ValueError('brief must be an object')
    working = copy.deepcopy(brief)
    source = working.get('source_documents', working.get('prose', ''))
    if 'source_documents' in working:
        if (not isinstance(source, list) or not source
                or any(not isinstance(d, dict) or not isinstance(d.get('id'), str)
                       or not isinstance(d.get('text'), str) for d in source)):
            raise ValueError('source_documents must contain nonempty source records with string id and text')
        working['prose'] = '\n\n'.join(d['id'] + ':\n' + d['text'] for d in source)
    result = analyze_v5(working, state)
    # The coverage universe is the entire declaration, not an answer-pruned set.
    # Otherwise choosing one valid reading would erase a represented ambiguity.
    audit = audit_conservation(source, result['compiled_brief']['candidates'],
                               registry=working.get('registry'),
                               compilation=result.get('ambiguity_compilation'))
    gaps, unresolved = audit['gaps'], audit['unresolved']
    review_required = bool(gaps or unresolved)
    gate = ('structural_coverage_gap' if gaps else 'unresolved_source_alignment'
            if unresolved else 'no_gap_detected_in_recognized_cues')
    presentations = {}
    for did, verdict in result['decision_states'].items():
        unanimous = verdict['state'] in ('robust_supported', 'robust_unsupported')
        presentations[did] = {
            'conditional_state': verdict['state'],
            'conditional_label': verdict['display_label'],
            'review_required': review_required,
            'blocks_unqualified_unanimity': bool(unanimous and review_required),
            'review_label': ('Reference-Free Coverage Gap' if gaps else
                             'Reference-Free Coverage Gap — unresolved alignment' if unresolved else None),
        }
    return {**result, 'schema': 'retrace.stress.v6', 'conservation': audit,
            'source_review': {
                'status': gate, 'review_required': review_required,
                'structural_gap_count': len(gaps), 'unresolved_alignment_count': len(unresolved),
                'decisions': presentations,
                'universe': 'All compiled candidate declarations, before answer filtering.',
                'policy': 'Conservative brief-wide review gate. Unknown relevance is not silently treated as irrelevant.',
            },
            'scope': result['scope'] + [
                'Reference-free conservation checks only the explicitly implemented cue grammar and alignments; no warning is not a completeness certificate.',
                'A coverage or alignment gap requires source review. It does not prove a missing dependency, alter a graph, or establish a decision as false.',
                'Answers to existing graph questions cannot discharge a missing source representation. Revise the declaration with independently checked source evidence.',
            ]}


def demonstration():
    graph = {
        'evidence': [
            {'id': 'O', 'kind': 'root', 'active': False, 'parents': [], 'label': 'Original worksheet'},
            {'id': 'A', 'kind': 'root', 'active': True, 'parents': [], 'label': 'First transcription'},
            {'id': 'B', 'kind': 'root', 'active': True, 'parents': [], 'label': 'Second transcription'}],
        'claims': [{'id': 'C', 'supports': [['A'], ['B']], 'label': 'Count review'}],
        'decisions': [{'id': 'D', 'requires': ['C'], 'label': 'Release the count'}]}
    return {
        'id': 'v6-shared-lineage-demonstration',
        'title': 'Shared omission · two transcriptions, one original',
        'artificial_demonstration': True,
        'prose': ('Evidence A is copied from evidence O. Evidence B is copied from evidence O. '
                  'Evidence O is currently locally ineligible. Evidence A and evidence B are locally eligible. '
                  'Claim C accepts either A or B. Decision D requires C.'),
        'candidates': [{'id': 'reading-one', 'label': 'Supplied reading one', 'graph': copy.deepcopy(graph)},
                       {'id': 'reading-two', 'label': 'Supplied reading two', 'graph': copy.deepcopy(graph)}],
        'questions': [],
        'documents': [{'id': 'worksheet', 'label': 'Original worksheet', 'evidence_ids': ['O']},
                      {'id': 'transcriptions', 'label': 'Transcriptions', 'evidence_ids': ['A', 'B']}],
    }
