"""Explicit post-hoc language-extension replay; never rewrites v4 scores or raw logs."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.compact_v5 import compile_ambiguity
from retrace.ambiguity_v4_eval import evaluate_compilation, _aggregate


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def main():
    destination = ROOT / 'results/ambiguity-v5-posthoc-replay.json'
    if destination.exists():
        raise RuntimeError('Refusing to overwrite a replay result')
    original = read('results/ambiguity-v4-summary.json')
    packets = read('data/ambiguity-v3-staged.json')
    primary = {row['case_id']: row for row in original['outcomes']}
    rows = []
    for packet in packets:
        cid = packet['public']['id']
        old = primary[cid]
        raw = old.get('raw_row_audit', {}).get('output_text')
        row = {'case_id': cid, 'primary_v4_status': old['status'], 'received': old['received'],
               'provider_completed': old['provider_completed'], 'strict_bare': False,
               'status': 'unissued_or_missing', 'original_output_text': raw,
               'original_output_sha256': hashlib.sha256(raw.encode()).hexdigest() if isinstance(raw, str) else None}
        if old['provider_completed']:
            try:
                compilation = compile_ambiguity(raw, packet['public']['registry'])
            except (ValueError, TypeError) as exc:
                row.update(status='syntax_or_branch_failure', error=str(exc))
            else:
                row.update(status='admitted', strict_bare=compilation['strict_bare'], compilation=compilation,
                           evaluation=evaluate_compilation(packet, compilation))
        elif old['received']:
            row['status'] = 'operational_failure'
        rows.append(row)
    result = {'schema': 'retrace.ambiguity-v5-posthoc-replay.v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'kind': 'post_hoc_replay_of_the_same_unmodified_v4_raw_responses', 'new_model_calls': 0,
              'fresh_evaluation': False, 'primary_v4_results_replaced': False,
              'method': 'New explicitly declared node-local language is desugared into frozen v4 declarations; same frozen structural/decision scorer then evaluates it.',
              'input_hashes': {name: digest(name) for name in ['results/ambiguity-v4-summary.json',
                  'results/ambiguity-v4/gemma-4-31b-it/responses.jsonl', 'retrace/compact_v5.py',
                  'tests/test_compact_v5.py', 'retrace/ambiguity_v4_eval.py', 'scripts/replay_v4_inline_v5.py']},
              'outcomes': rows, 'aggregates': _aggregate(rows, packets),
              'limitations': ['The v5 syntax was designed after seeing v4 errors; this is not a prospective v5 extraction success rate.',
                              'All ten outputs remain in the denominator; no model retry, output substitution or graph correction occurs.',
                              'Source-exact errors in fixed graph rows remain errors, even if current decisions happen to agree.',
                              'Authored structural question answers are diagnostics, not measured human clarification.']}
    with destination.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': destination.name, 'aggregates': result['aggregates']}, indent=2))


if __name__ == '__main__':
    main()
