"""Offline journal-integrity checks with synthetic provider fixtures; no API calls."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from retrace.compact_graph import serialize_compact

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v3_summary_under_test', ROOT / 'scripts/summarize_ambiguity_v3.py')
summary_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary_module)


class PipelineIntegrityTests(unittest.TestCase):
    def run_fixture(self, corruption=None):
        with tempfile.TemporaryDirectory(prefix='retrace-v3-journal-') as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'results').mkdir()
            for name in ['ambiguity-v3-staged.json', 'ambiguity-v3-sessions.json', 'ambiguity-v3-plan.json']:
                (root / 'data' / name).write_bytes((ROOT / 'data' / name).read_bytes())
            read = lambda name: json.loads((root / name).read_text(encoding='utf-8'))
            write = lambda name, value: (root / name).write_text(json.dumps(value), encoding='utf-8')
            packets = {p['public']['id']: p for p in read('data/ambiguity-v3-staged.json')}
            sessions, plan = read('data/ambiguity-v3-sessions.json'), read('data/ambiguity-v3-plan.json')
            folder = root / plan['output_directory']
            folder.mkdir(parents=True)
            requests, responses = [], []
            for number, session in enumerate(sessions, 1):
                graphs = packets[session['case_id']]['hidden']['allowed_interpretations']
                text = serialize_compact(graphs[0 if session['condition'] == 'earlier_sparse' else -1])
                request = {'model': plan['model'], 'instructions': session['instructions'],
                           'input': [{'role': 'user', 'content': session['steps'][0]['input']}],
                           'max_output_tokens': 4096, 'temperature': 0, 'store': False,
                           'agentic_memory': False, 'tools': [], 'tool_choice': 'none'}
                encoded = json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                row = {'request_number': number, 'run_id': 'synthetic-offline-fixture', 'case_id': session['case_id'],
                       'condition': session['condition'], 'phase': 'final', 'request': request,
                       'request_sha256': hashlib.sha256(encoded).hexdigest()}
                requests.append(row)
                responses.append({**copy.deepcopy(row), 'error': None, 'http_status': 200, 'response_status': 'completed',
                                  'response_model': plan['model'], 'output_text': text,
                                  'raw_response': json.dumps({'status': 'completed', 'output_text': text})})
            if corruption == 'request':
                requests[0]['request']['input'][0]['content'] = 'Injected oracle answer'
            if corruption == 'raw':
                responses[0]['output_text'] = 'E invented R 1 -\nEND'
            for name, records in [('requests.jsonl', requests), ('responses.jsonl', responses)]:
                (folder / name).write_text(''.join(json.dumps(row) + '\n' for row in records), encoding='utf-8')
            write(plan['output_directory'] + '/run.json', {'run_id': 'synthetic-offline-fixture',
                  'started_at': '2026-11-13T01:00:01Z', 'sessions_sha256': plan['sessions_sha256'],
                  'model': plan['model'], 'planned_requests': 20, 'reserve_nanocredits_per_request': 24432640})
            write(plan['output_directory'] + '/summary.json', {'run_id': 'synthetic-offline-fixture',
                  'planned_requests': 20, 'status': 'completed', 'issued_requests': 20, 'recorded_responses': 20,
                  'unissued_requests': 0, 'halt_reason': None, 'observed_token_cost_credits_uncached': 0, 'responses_missing_usage': 0})
            write('data/ambiguity-v3-freeze.json', {'created_at': '2026-11-13T01:00:00+00:00', 'files': [
                  {'path': str(p.relative_to(root)).replace('\\', '/'), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                  for p in (root / 'data').glob('*.json')]})
            original = summary_module.ROOT
            summary_module.ROOT = root
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    summary_module.main()
                return read('results/ambiguity-v3-summary.json'), read('results/ambiguity-v3-live-briefs.json')
            finally:
                summary_module.ROOT = original

    def test_offline_pipeline_preserves_slots_and_only_output_candidates(self):
        scores, catalog = self.run_fixture()
        self.assertEqual(scores['scheduled'], 20)
        self.assertEqual(scores['aggregates']['both_admitted_cases'], 10)
        self.assertEqual(len(catalog['briefs']), 10)
        self.assertTrue(all({c['id'] for c in b['candidates']} == {'earlier_sparse', 'later_joint'} for b in catalog['briefs']))

    def test_request_changes_and_raw_output_changes_fail_closed(self):
        for corruption in ['request', 'raw']:
            with self.subTest(corruption=corruption), self.assertRaises(RuntimeError):
                self.run_fixture(corruption)


if __name__ == '__main__':
    unittest.main()
