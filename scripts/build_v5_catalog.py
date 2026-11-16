"""Export transparently labelled replay and benchmark-comparison briefs."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'results/ambiguity-v5-live-briefs.json'
    if target.exists():
        raise RuntimeError('Refusing to overwrite the versioned catalog')
    read = lambda name: json.loads((ROOT / name).read_text(encoding='utf-8'))
    replay = read('results/ambiguity-v5-posthoc-replay.json')
    packets = {p['public']['id']: p for p in read('data/ambiguity-v3-staged.json')}
    briefs = []
    for row in replay['outcomes']:
        if row['status'] != 'admitted':
            continue
        packet = packets[row['case_id']]
        public = packet['public']
        source = '\n\n'.join(d['text'] for d in public['documents'])
        brief = {'id': 'v5-replay-' + row['case_id'], 'title': 'Post-hoc replay · ' + public['title'],
                 'prose': source + '\n\nREPLAY PROVENANCE: This is the unchanged raw v4 model response interpreted under the later v5 node-local grammar. It is not a fresh v5 model run. The original v4 result remains ' + row['primary_v4_status'] + '.',
                 'compact_v5': row['original_output_text'], 'registry': public['registry'],
                 'candidates': row['compilation']['candidates'],
                 'documents': packet['source_context']['documents'],
                 'provenance_constraints': packet['source_context']['provenance_constraints'],
                 'allowed_withdrawals': public['registry']['evidence'],
                 'post_hoc_replay': True, 'primary_v4_status': row['primary_v4_status']}
        briefs.append(brief)
        if row['case_id'] in ('ambiguity-v3-08', 'ambiguity-v3-09'):
            reference = packet['hidden']['allowed_interpretations'][packet['hidden']['author_actual_interpretation_index']]
            briefs.append({'id': 'exposure-diagnostic-' + row['case_id'],
                           'title': 'Benchmark comparison · ' + public['title'],
                           'reference_comparison': True,
                           'prose': source + '\n\nBENCHMARK COMPARISON: The first graph is actual model output; the second is the authored reference, inserted only for this explicitly labelled diagnostic. RETRACE did not discover or repair the missing rule. Hypothetical enabling changes local eligibility for sensitivity testing, not source truth.\n\nUnchanged model output:\n' + row['original_output_text'],
                           'candidates': [{'id': 'observed-model', 'label': 'Actual model graph', 'graph': copy.deepcopy(row['compilation']['candidates'][0]['graph'])},
                                          {'id': 'authored-reference', 'label': 'Authored reference · benchmark only', 'graph': copy.deepcopy(reference)}],
                           'questions': [], 'documents': packet['source_context']['documents'],
                           'allowed_withdrawals': public['registry']['evidence']})
    with target.open('x', encoding='utf-8') as output:
        output.write(json.dumps({'schema': 'retrace.v5-catalog.v1', 'status': 'completed', 'briefs': briefs,
                                 'provenance': 'V5 syntax replays use original v4 model text. Benchmark comparisons explicitly add authored reference graphs for diagnostics only; they are separate catalog entries.'}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'briefs': len(briefs), 'model_replays': sum(bool(b.get('post_hoc_replay')) for b in briefs),
                      'reference_comparisons': sum(bool(b.get('reference_comparison')) for b in briefs)}))


if __name__ == '__main__':
    main()
