"""Add fresh confirmed model cases to a successor catalog without changing replay evidence."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / 'results/retrace-v5-catalog.json'
    if destination.exists():
        raise RuntimeError('Refusing to overwrite release catalog')
    read = lambda path: json.loads((ROOT / path).read_text(encoding='utf-8'))
    packets = {p['id']: p for p in read('data/eligibility-v5-paired-staged.json')}
    fresh = []
    for row in read('results/eligibility-v5-summary.json')['outcomes']:
        if row['status'] != 'admitted':
            continue
        p = packets[row['case_id']]
        public = p['public']
        fresh.append({'id': row['case_id'], 'title': 'Fresh confirmation · ' + public['title'] + ' · ' + row['eligibility_condition'],
                      'fresh_confirmation': True, 'pair_id': row['pair_id'],
                      'prose': '\n\n'.join(d['text'] for d in public['documents']) + '\n\nPROSPECTIVE CONFIRMATION: One raw completion from the separately frozen eight-packet study. No authored graph or oracle answer is included in this candidate set.',
                      'compact_v5': row['raw_row_audit']['output_text'], 'registry': public['registry'],
                      'candidates': row['compilation']['candidates'], 'allowed_withdrawals': public['registry']['evidence']})
    prior = read('results/ambiguity-v5-live-briefs.json')
    catalog = {'schema': 'retrace.v5-release-catalog.v1', 'status': 'completed',
               'briefs': fresh + prior['briefs'],
               'provenance': 'Entries are explicitly labelled as prospectively frozen fresh model outputs, post-hoc syntax replays, or authored-reference benchmark comparisons. None is a verified natural-document claim.'}
    with destination.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(catalog, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'fresh': len(fresh), 'total': len(catalog['briefs'])}))


if __name__ == '__main__':
    main()
