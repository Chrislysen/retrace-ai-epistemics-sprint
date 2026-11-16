"""Construct an unverified counter-reading preview from a current workbench state."""
from .falsification_v6 import verify_counter_reading


def preview_counter_reading(analysis, proposal):
    brief = analysis['compiled_brief']
    candidates = [{'id': candidate['id'], 'graph': candidate['graph']} for candidate in brief['candidates']
                  if candidate['id'] in analysis['candidate_ids']]
    if not candidates:
        raise ValueError('No compatible seed remains; reopen the source declaration before proposing an edit')
    registry = {category: [row['id'] for row in candidates[0]['graph'][category]]
                for category in ('evidence', 'claims', 'decisions')}
    sources = brief.get('source_documents', [{'id': 'source', 'text': brief.get('prose', '')}])
    locked = sorted(eid for eid, flags in analysis['revocation_flags'].items()
                    if flags['document_veto'] or flags['passage_veto'] or flags['scenario_veto'])
    allowed = brief.get('allowed_exposure_changes', analysis['interventions']['allowed_withdrawals'])
    public = {'source_documents': sources, 'candidates': candidates, 'registry': registry,
              'target_decisions': analysis['consensus']['target_decisions'],
              'locked_exclusions': locked}
    if allowed is not None:
        public['allowed_changes'] = allowed
    result = verify_counter_reading(public, proposal)
    return {**result, 'workbench_state_unchanged': True,
            'source_review_unchanged': analysis.get('source_review'),
            'preview_scope': 'Mechanical source-span and consequence checks only. This does not accept an interpretation, discharge a coverage warning or change source eligibility.'}
