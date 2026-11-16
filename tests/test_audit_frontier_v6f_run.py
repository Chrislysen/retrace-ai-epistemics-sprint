"""Offline tamper fixtures; no runner import, credential or provider access."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from scripts import audit_frontier_v6f_run as audit

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'gemma-4-31b-it'


def lines(rows):
    return b''.join((audit.canonical(row) + '\n').encode() for row in rows)


def chain(events):
    rows, previous = [], '0' * 64
    for seq, event in enumerate(events, 1):
        row = {'seq': seq, 'previous_sha256': previous, 'at': f'2026-11-14T00:00:{seq:02d}+00:00', 'event': event}
        row['sha256'] = audit.digest(row); previous = row['sha256']; rows.append(row)
    return lines(rows)


def frame(event):
    return ('data: ' + audit.canonical(event) + '\n\n').encode()


class Fixture:
    def __init__(self, folder, mode='completed', closed=True):
        self.folder = Path(folder); (self.folder / 'streams').mkdir()
        self.rid = 'independent-fixture'; self.prior = 'f' * 64
        self.slots = [dict(slot_id=f'S{i}', case_id='case', model=MODEL, condition='commitment',
                           phase='hist_init' if i == 0 else 'hist_withdrawn', instructions='Use the source.',
                           input='Original source 🧭' if i == 0 else 'Withdraw the source.',
                           max_output_tokens=100, temperature=1.0) for i in range(2)]
        self.slots[1]['history_from'] = ['S0']
        self.events = [{'kind': 'initialize', 'historical_credits': audit.BASELINE,
                        'historical_sha256': self.prior, 'cap_credits': '250'}]
        initial = self.replay()['snapshot']
        bounds = {m: sum(audit.bound(m, s['max_output_tokens']) for s in self.slots if s['model'] == m) for m in audit.PRICES}
        self.manifest = {'schema': 'retrace.adaption-v6f-plan.v1', 'run_id': self.rid, 'slots': self.slots,
                         'sessions_sha256': audit.digest(self.slots), 'planned_slots': 2, 'models': {MODEL: 2},
                         'endpoint': 'https://api.prod.adaptionlabs.ai/api/v1/responses', 'stream': True,
                         'store': False, 'agentic_memory': False, 'tools': False, 'retries': 0,
                         'clock_test_hooks': False, 'concurrency': 5, 'timeout_seconds': 1200,
                         'model_interval_seconds': 3.1, 'global_interval_seconds': 3.1,
                         'admission_policy': audit.POLICY, 'models_pricing': {m: dict(input=p[0], output=p[1], context=p[2]) for m, p in audit.PRICES.items()},
                         'full_plan_bound_by_model': {m: audit.credits(v) for m, v in bounds.items()},
                         'full_plan_no_settlement_bound_credits': audit.credits(sum(bounds.values())),
                         'historical_carry_credits': audit.BASELINE, 'cumulative_cap_credits': '250',
                         'budget_before': initial, 'canary': False}
        self.events.append(dict(kind='run_started', run_id=self.rid, planned=2, sessions_sha256=audit.digest(self.slots)))
        self.requests, self.responses = [], []
        for i, slot in enumerate(self.slots):
            sid, aid = slot['slot_id'], self.rid + ':' + slot['slot_id']
            if i and mode == 'truncated':
                self.responses.append(dict(run_id=self.rid, slot_id=sid, case_id='case', model=MODEL,
                    condition=slot['condition'], phase=slot['phase'], issued=False, terminal_valid=False,
                    model_outcome='not_issued_dependency_truncated', error='history_dependency_truncated',
                    response_status=None, output_text='', blocked_dependencies=['S0'], at='2026-11-14T00:03:00+00:00'))
                continue
            if i and mode in ('active', 'failure'): break
            ceiling = audit.bound(MODEL, 100)
            self.events.append(dict(kind='reserve', run_id=self.rid, attempt_id=aid, slot_id=sid, model=MODEL, bound_nanocredits=ceiling))
            messages = []
            if i:
                messages += [{'role': 'user', 'content': self.slots[0]['input']}, {'role': 'assistant', 'content': self.responses[0]['output_text']}]
            messages.append({'role': 'user', 'content': slot['input']})
            body = dict(model=MODEL, instructions=slot['instructions'], input=messages, max_output_tokens=100,
                        temperature=1.0, store=False, agentic_memory=False, tools=[], tool_choice='none', stream=True)
            estimate = dict(schema='retrace.admission-estimate.v6f', reference_input_tokens=10, weighted_input_tokens=13,
                            requested_max_output_tokens=100, weight=113, encoding='cl100k_base', tokenizer_version='0.14.0',
                            input_safety_multiplier='1.25', quota_verified=False, solo_required=False)
            self.requests.append(dict(attempt_id=aid, slot_id=sid, request=body, request_sha256=audit.digest(body),
                reserved_credits=audit.credits(ceiling), admission_policy=audit.POLICY, admission_estimate=estimate,
                at=f'2026-11-14T00:0{i*2}:00+00:00'))
            if mode == 'active': break
            answer = 'Observed "answer" 🧭\n' + sid
            response = dict(id='provider-' + sid, model=MODEL, status='incomplete' if mode == 'truncated' else 'completed',
                            output_text=answer, usage=dict(input_tokens=10, output_tokens=20, total_tokens=30))
            if mode == 'truncated': response['incomplete_details'] = {'reason': 'max_output_tokens'}
            stream = frame({'type': 'response.output_text.delta', 'sequence_number': 0, 'delta': answer})
            stream += frame({'type': 'response.completed', 'sequence_number': 1, 'response': response}) + b'data: [DONE]\n\n'
            if mode == 'failure': stream = b'{"error":"rate limit"}'
            name = audit.sha(aid.encode()) + '.sse'; path = self.folder / 'streams' / name; path.write_bytes(stream)
            status = 429 if mode == 'failure' else 200
            meta = dict(raw_stream_path=str(path), received_bytes=len(stream), received_sha256=audit.sha(stream),
                        saved_sha256=audit.sha(stream), credential_redacted=False, closed=True, http_status=status)
            charge = audit.cost(MODEL, response['usage'], 100)
            row = dict(run_id=self.rid, attempt_id=aid, slot_id=sid, case_id='case', model=MODEL,
                       condition=slot['condition'], phase=slot['phase'], issued=True, terminal_valid=mode != 'failure',
                       model_outcome='operational_failure' if mode == 'failure' else 'truncated_max_output_tokens' if mode == 'truncated' else 'completed',
                       error='http_429' if mode == 'failure' else None, response_status=None if mode == 'failure' else response['status'],
                       http_status=status, stream_evidence=meta, stream_terminal_event=None if mode == 'failure' else 'response.completed',
                       stream_event_count=0 if mode == 'failure' else 2, raw_response=None if mode == 'failure' else audit.canonical(response),
                       output_text=answer if mode == 'completed' else '', partial_output_text=answer if mode == 'truncated' else '',
                       usage=None if mode == 'failure' else response['usage'], latency_ms=12.5,
                       reserved_credits=audit.credits(ceiling), settled_credits=None if mode == 'failure' else audit.credits(charge),
                       at=f'2026-11-14T00:0{i*2+1}:00+00:00')
            self.responses.append(row)
            if mode != 'failure':
                self.events.append(dict(kind='settle', attempt_id=aid, accounted_nanocredits=charge,
                                        response_sha256=audit.digest(row), basis='valid_terminal_reported_usage_uncached_no_double_reasoning',
                                        model_outcome=row['model_outcome']))
            else:
                self.events.append(dict(kind='halt', run_id=self.rid, reason='http_429', attempt_id=aid))
        self.summary = None
        if closed:
            self.events.append(dict(kind='run_closed', run_id=self.rid, issued=len(self.requests), status='stopped' if mode == 'failure' else 'completed'))
            issued = [r['slot_id'] for r in self.requests]; skips = [r['slot_id'] for r in self.responses if not r['issued']]
            self.summary = dict(schema='retrace.adaption-v6f-summary.v1', run_id=self.rid, planned=2,
                models={MODEL: 2}, canary=False, admission_policy=audit.POLICY, issued=len(issued), responses=len(self.responses),
                completed=2 if mode == 'completed' else 0, truncated=1 if mode == 'truncated' else 0,
                issued_operational_failures=1 if mode == 'failure' else 0, dependency_skips=len(skips),
                valid_terminal_records=2 if mode == 'completed' else 1 if mode == 'truncated' else 0,
                issued_slot_ids=issued, dependency_skipped_slot_ids=skips,
                unissued_due_global_halt_slot_ids=[s['slot_id'] for s in self.slots if s['slot_id'] not in issued + skips],
                issued_without_outcome_slot_ids=[], unissued_slot_ids=[s['slot_id'] for s in self.slots if s['slot_id'] not in issued],
                admission_starts=len(issued), retries=0, stream=True, status='stopped' if mode == 'failure' else 'completed',
                budget=self.replay()['snapshot'], stop_reasons=['http_429'] if mode == 'failure' else [])

    def replay(self):
        return audit.replay_ledger(chain(self.events), audit.BASELINE, self.prior)

    def run(self):
        files = {'run.json': lines([self.manifest]), 'requests.jsonl': lines(self.requests),
                 'responses.jsonl': lines(self.responses), 'summary.json': lines([self.summary]) if self.summary else None}
        return audit.audit_run(self.folder, self.slots, files, self.replay())


class RunAuditTests(unittest.TestCase):
    def test_real_frozen_canary_all_ten_raw_streams_and_settlements(self):
        folder = ROOT / 'results/frontier-v6f/canary'
        files = {name: (folder / name).read_bytes() for name in ('run.json', 'requests.jsonl', 'responses.jsonl', 'summary.json')}
        raw = (ROOT / 'data/frontier-v6f-canary-ledger.jsonl').read_bytes()
        first = audit.jsonl(raw)[0]['event']
        ledger = audit.replay_ledger(raw, audit.BASELINE, first['historical_sha256'])
        result = audit.audit_run(folder, audit.strict_json((ROOT / 'data/frontier-v6f-canary-sessions.json').read_bytes()), files, ledger)
        self.assertTrue(result['final_closed']); self.assertTrue(result['all_scheduled_outcomes_recorded'])
        self.assertEqual(result['completed'], 10)

    def test_actual_history_is_valid_but_rehashed_fabricated_history_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(folder); self.assertTrue(fixture.run()['final_closed'])
            request = fixture.requests[1]; request['request']['input'][1]['content'] = 'A fabricated assistant answer'
            request['request_sha256'] = audit.digest(request['request'])
            with self.assertRaisesRegex(audit.AuditError, 'request_body_or_hash'): fixture.run()

    def test_rehashed_extra_provider_field_and_changed_temperature_fail(self):
        for field, value in [('seed', 2), ('temperature', 0)]:
            with tempfile.TemporaryDirectory() as folder:
                fixture = Fixture(folder); request = fixture.requests[0]
                request['request'][field] = value; request['request_sha256'] = audit.digest(request['request'])
                with self.assertRaisesRegex(audit.AuditError, 'request_body_or_hash'): fixture.run()

    def test_active_request_and_unissued_slot_remain_incomplete(self):
        with tempfile.TemporaryDirectory() as folder:
            result = Fixture(folder, mode='active', closed=False).run()
            self.assertFalse(result['final_closed']); self.assertFalse(result['all_scheduled_outcomes_recorded'])
            self.assertEqual(result['issued_without_response_slot_ids'], ['S0'])
            self.assertEqual(result['unissued_slot_ids'], ['S1'])

    def test_truncation_and_uncharged_dependency_are_distinct_from_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(folder, mode='truncated'); result = fixture.run()
            self.assertTrue(result['all_scheduled_outcomes_recorded']); self.assertEqual(result['truncated'], 1)
            self.assertEqual(result['dependency_skips'], 1); self.assertEqual(len(fixture.replay()['attempts']), 1)
            fixture.responses[0]['output_text'] = fixture.responses[0]['partial_output_text']
            with self.assertRaisesRegex(audit.AuditError, 'truncation_promoted'): fixture.run()

    def test_closed_failure_retains_bound_and_missing_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(folder, mode='failure'); result = fixture.run()
            self.assertTrue(result['final_closed']); self.assertFalse(result['all_scheduled_outcomes_recorded'])
            self.assertEqual(result['operational_failures'], 1)
            self.assertEqual(fixture.replay()['snapshot']['unsettled_attempts'], 1)
            self.assertEqual(audit.nanocredits(fixture.replay()['snapshot']['accounted_credits']), audit.nanocredits(audit.BASELINE) + audit.bound(MODEL, 100))

    def test_tampered_saved_stream_rejected_before_semantics(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(folder); path = Path(fixture.responses[0]['stream_evidence']['raw_stream_path'])
            path.write_bytes(path.read_bytes() + b': tampered\n\n')
            with self.assertRaisesRegex(audit.AuditError, 'saved_stream_hash'): fixture.run()

    def test_tampered_ledger_response_binding_rejected_even_if_chain_rehashed(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(folder)
            next(e for e in fixture.events if e['kind'] == 'settle')['response_sha256'] = '0' * 64
            with self.assertRaisesRegex(audit.AuditError, 'settlement_response_binding'): fixture.run()

    def test_settled_deleted_response_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(folder); fixture.responses.pop()
            with self.assertRaisesRegex(audit.AuditError, 'settled_attempt_without_response'): fixture.run()

    def test_duplicate_requests_and_identity_corruption_rejected(self):
        for mutation in ('duplicate', 'identity'):
            with tempfile.TemporaryDirectory() as folder:
                fixture = Fixture(folder)
                if mutation == 'duplicate': fixture.requests.append(deepcopy(fixture.requests[0]))
                else: fixture.responses[0]['model'] = 'wrong-model'
                with self.assertRaises(audit.AuditError): fixture.run()

    def test_summary_cannot_hide_a_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(folder, mode='truncated'); fixture.summary['truncated'] = 0
            with self.assertRaisesRegex(audit.AuditError, 'summary_count'): fixture.run()

    def test_ledger_cap_and_duplicate_settlement_are_checked_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(folder)
            broken = deepcopy(fixture.events); next(e for e in broken if e['kind'] == 'reserve')['bound_nanocredits'] = audit.CAP
            with self.assertRaisesRegex(audit.AuditError, 'cap_breach'): audit.replay_ledger(chain(broken), audit.BASELINE, fixture.prior)
            broken = deepcopy(fixture.events); at = next(i for i, e in enumerate(broken) if e['kind'] == 'settle')
            broken.insert(at + 1, deepcopy(broken[at]))
            with self.assertRaisesRegex(audit.AuditError, 'duplicate_settlement'): audit.replay_ledger(chain(broken), audit.BASELINE, fixture.prior)

    def test_json_duplicates_and_partial_lines_never_parse_as_clean(self):
        for raw in [b'{"a":1,"a":2}\n', b'{"a":NaN}\n', b'{"a":1}']:
            with self.assertRaises(audit.AuditError): audit.jsonl(raw)

    def test_sse_done_alone_wrong_delta_and_event_after_terminal_rejected(self):
        response = dict(id='r', status='completed', output_text='answer')
        terminal = frame({'type': 'response.completed', 'response': response})
        variants = [b'data: [DONE]\n\n',
                    frame({'type': 'response.output_text.delta', 'delta': 'wrong'}) + terminal,
                    terminal + frame({'type': 'response.output_text.delta', 'delta': 'extra'}),
                    terminal.rstrip(b'\n'),
                    frame({'type': 'response.completed', 'response': dict(response, status='incomplete', incomplete_details={'reason': 'unknown'})})]
        for raw in variants:
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(audit.AuditError): audit.parse_sse(raw)

    def test_current_freeze_and_both_protected_sets_are_intact(self):
        _, evidence = audit.freeze_checks(ROOT)
        self.assertEqual((evidence['frozen_files_verified'], evidence['v5_preserved_files_verified'],
                          evidence['authorization_protected_files_verified']), (619, 402, 555))


if __name__ == '__main__': unittest.main()
