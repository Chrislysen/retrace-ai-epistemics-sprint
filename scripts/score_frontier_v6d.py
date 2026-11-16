"""Offline v6d scoring; outputs are exclusively created, never overwritten.

No provider access or credential loading. Original regeneration/runner scripts
are not called. Request journals can identify issued attempts lacking responses.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.frontier_v6d_eval import evaluate


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def load(text):
    def invalid(_):
        raise ValueError('Nonfinite JSON value')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def jsonl(path):
    return [load(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=ROOT / 'data/frontier-v6c-staged.json')
    parser.add_argument('--dossiers', type=Path, default=ROOT / 'data/frontier-v6d-dossiers.json')
    parser.add_argument('--sessions', type=Path, default=ROOT / 'data/frontier-v6d-sessions.json')
    parser.add_argument('--responses', type=Path, nargs='+', required=True)
    parser.add_argument('--requests', type=Path, nargs='*', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audits', type=Path)
    parser.add_argument('--bootstrap-repeats', type=int, default=10000)
    args = parser.parse_args()
    outputs = [path.resolve() for path in (args.output, args.audits) if path is not None]
    if len(outputs) != len(set(outputs)) or any(path.exists() for path in outputs):
        raise ValueError('Output paths must be distinct and new')
    corpus, dossiers, slots = [load(path.read_text(encoding='utf-8')) for path in (args.corpus, args.dossiers, args.sessions)]
    records = [row for path in args.responses for row in jsonl(path)]
    scheduled = {slot['slot_id']: slot for slot in slots}
    response_ids = {row['slot_id'] for row in records}
    issued_response_ids = {row['slot_id'] for row in records if row.get('issued', True)}
    requests = [row for path in args.requests for row in jsonl(path)]
    request_ids = set()
    for request in requests:
        sid = request['slot_id']
        if sid in request_ids or sid not in scheduled:
            raise ValueError('Duplicate or unknown issued request slot')
        request_ids.add(sid)
        if sid not in response_ids:
            slot = scheduled[sid]
            records.append({key: slot[key] for key in ('slot_id', 'case_id', 'model', 'condition', 'phase')} |
                           {'error': 'issued_response_missing', 'http_status': None, 'response_status': None,
                            'output_text': '', 'usage': None, 'reserved_credits': request.get('reserved_credits'),
                            'settled_credits': None, 'request_sha256': request.get('request_sha256')})
    if requests and not issued_response_ids <= request_ids:
        raise ValueError('Response lacks corresponding issued request')
    result = evaluate(corpus, dossiers, slots, records, bootstrap_repeats=args.bootstrap_repeats)
    if not result['summary']['matches_primary48_design']:
        raise ValueError('CLI primary scoring requires the complete48-case/24-dossier/4560-slot design')
    result['summary']['request_journal_coverage'] = {
        'journals_supplied': bool(args.requests), 'issued_requests': len(requests) if args.requests else None,
        'unissued_scheduled_slots': len(slots) - len(requests) if args.requests else None,
        'scope': 'Missing response slots are not assumed unissued unless complete request journals are supplied. Cryptographic raw/request validation belongs to the independent run audit.'}
    # Score completely before creating either deliverable. Exclusive creation
    # preserves earlier runs and rejects accidental primary-result replacement.
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result['summary'], stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    if args.audits:
        with args.audits.open('x', encoding='utf-8', newline='\n') as stream:
            for audit in result['audits']:
                stream.write(json.dumps(audit, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print(json.dumps({key: result['summary'][key] for key in ('status', 'base_cases', 'long_base_cases', 'planned_slots', 'response_records')}))


if __name__ == '__main__':
    main()
