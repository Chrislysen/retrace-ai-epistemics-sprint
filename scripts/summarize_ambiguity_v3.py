"""Verify frozen requests and raw journals before scoring the one v3 pilot."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.ambiguity_v3_eval import score_responses, candidate_brief


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON field: ' + key)
        value[key] = item
    return value


def read(path):
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def journal(path):
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise RuntimeError('Incomplete journal line: ' + str(path))
    return [json.loads(line, object_pairs_hook=unique) for line in raw.decode('utf-8').splitlines() if line.strip()]


def output_text(raw):
    if isinstance(raw.get('output_text'), str):
        return raw['output_text']
    return ''.join(part['text'] for entry in raw.get('output', [])
                   if entry.get('type') == 'message' and entry.get('role') == 'assistant'
                   for part in entry.get('content', [])
                   if part.get('type') == 'output_text' and isinstance(part.get('text'), str))


def main():
    frozen = read(ROOT / 'data/ambiguity-v3-freeze.json')
    for item in frozen['files']:
        if digest(ROOT / item['path']) != item['sha256']:
            raise RuntimeError('Frozen dependency changed: ' + item['path'])
    packets = read(ROOT / 'data/ambiguity-v3-staged.json')
    sessions = read(ROOT / 'data/ambiguity-v3-sessions.json')
    plan = read(ROOT / 'data/ambiguity-v3-plan.json')
    folder = ROOT / plan['output_directory']
    manifest, summary = read(folder / 'run.json'), read(folder / 'summary.json')
    requests, responses = journal(folder / 'requests.jsonl'), journal(folder / 'responses.jsonl')
    if datetime.fromisoformat(manifest['started_at'].replace('Z', '+00:00')) <= datetime.fromisoformat(frozen['created_at']):
        raise RuntimeError('Inference preceded freeze')
    if manifest['sessions_sha256'] != plan['sessions_sha256'] or manifest['model'] != plan['model']:
        raise RuntimeError('Wrong model or sessions')
    if (manifest['planned_requests'] != 20 or summary['planned_requests'] != 20
            or manifest['reserve_nanocredits_per_request'] != 24432640
            or summary['run_id'] != manifest['run_id']
            or summary['status'] not in ('completed', 'halted')
            or len(requests) != summary['issued_requests']
            or len(responses) != summary['recorded_responses']
            or len(requests) != len(responses)
            or summary['unissued_requests'] != 20 - len(requests)):
        raise RuntimeError('Run journal accounting mismatch')
    by_number = {row['request_number']: row for row in requests}
    if len(by_number) != len(requests) or sorted(by_number) != list(range(1, len(requests) + 1)):
        raise RuntimeError('Duplicate or missing request numbers')
    expected_sessions = {(s['case_id'], s['condition']): s for s in sessions}
    for request in requests:
        session = expected_sessions[(request['case_id'], request['condition'])]
        expected_request = {'model': plan['model'], 'instructions': session['instructions'],
                            'input': [{'role': 'user', 'content': session['steps'][0]['input']}],
                            'max_output_tokens': 4096, 'temperature': 0, 'store': False,
                            'agentic_memory': False, 'tools': [], 'tool_choice': 'none'}
        if request['request'] != expected_request or request['run_id'] != manifest['run_id'] or request['phase'] != 'final':
            raise RuntimeError('Provider request differs from frozen protocol')
        encoded = json.dumps(request['request'], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if hashlib.sha256(encoded).hexdigest() != request['request_sha256']:
            raise RuntimeError('Request digest mismatch')
    numbers = set()
    for response in responses:
        number = response['request_number']
        if number in numbers or number not in by_number:
            raise RuntimeError('Unexpected response number')
        numbers.add(number)
        request = by_number[number]
        for key in ('run_id', 'case_id', 'condition', 'phase', 'request', 'request_sha256'):
            if response[key] != request[key]:
                raise RuntimeError('Response/request identity mismatch')
        if not response.get('error'):
            raw = json.loads(response['raw_response'])
            if response['http_status'] != 200 or raw.get('status') != 'completed':
                raise RuntimeError('Incomplete response marked successful')
            if output_text(raw) != response['output_text']:
                raise RuntimeError('Scoring text differs from raw provider text')
    scores = score_responses(packets, responses)
    scored = {**scores, 'generated_at': datetime.now(timezone.utc).isoformat(),
              'freeze_sha256': digest(ROOT / 'data/ambiguity-v3-freeze.json'),
              'raw_run': {'path': plan['output_directory'], 'status': summary['status'],
                          'halt_reason': summary['halt_reason'],
                          'sha256': {p.name: digest(p) for p in folder.iterdir() if p.is_file()},
                          'response_models': sorted({r.get('response_model') or 'unreported' for r in responses})},
              'resources': {'fresh_reserved_credits': '0.48865280',
                            'cumulative_conservative_reserved_credits': '40.54847472',
                            'remaining_within_50_credits': '9.45152528',
                            'observed_new_token_cost_credits_uncached': summary['observed_token_cost_credits_uncached'],
                            'new_responses_missing_usage': summary['responses_missing_usage'],
                            'actual_billed_credits': None}}
    destination = ROOT / 'results/ambiguity-v3-summary.json'
    with destination.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(scored, indent=2) + '\n')
    briefs = []
    for packet in packets:
        candidates = [{'id': row['condition'], 'graph': row['graph']} for row in scores['outcomes']
                       if row['case_id'] == packet['public']['id'] and row['valid']]
        if candidates:
            brief = candidate_brief(packet, candidates)
            brief['artificial_demonstration'] = False
            brief['empirical_provenance'] = 'Actual Gemma outputs on authored synthetic prose; directed prompts. Questions and source constraints are author-supplied.'
            briefs.append(brief)
    with (ROOT / 'results/ambiguity-v3-live-briefs.json').open('x', encoding='utf-8') as handle:
        handle.write(json.dumps({'status': summary['status'], 'briefs': briefs,
                                 'provenance': 'Observed outputs only; no authored graph injected.'}, indent=2) + '\n')
    print(json.dumps({'summary': str(destination), 'groups': scores['groups'], 'aggregates': scores['aggregates'],
                      'resources': scored['resources']}, indent=2))


if __name__ == '__main__':
    main()
