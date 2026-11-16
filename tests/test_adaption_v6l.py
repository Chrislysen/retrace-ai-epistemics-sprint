"""Invented l fixtures only; never reads live k answers or changes frozen globals."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retrace import adaption_v6h as h
from retrace import adaption_v6l as j
from tests.test_adaption_v6h import KEY, MODEL, emit, final, slot
from tests import test_adaption_v6i as prior_tests
Clock = prior_tests.Clock

ROOT = Path(__file__).resolve().parents[1]
QWEN = 'qwen3.5-397b'
ROUTE = 'qwen3.5-397b-a17b-nvfp4'
RECEIPT_SHA = 'a' * 64


def synthetic_prior(carry='249', inherited=73):
    return {'carry_credits': carry, 'file_sha256': 'b' * 64,
        'cumulative_inherited_unsettled_attempts': inherited,
        'continuation_path': j.CONTINUATION, 'continuation_sha256': RECEIPT_SHA}



def synthetic_carry(slots, seeds=None):
    seeds = seeds or {}; completed = {}
    for s in slots:
        if s['slot_id'] in seeds and seeds[s['slot_id']]['terminal_valid']:
            completed[s['slot_id']] = {'actual_input': s['input'], 'output_text': seeds[s['slot_id']]['output_text']}
    return {'finals': deepcopy(seeds), 'completed': completed, 'issued_slot_ids': list(seeds),
        'continuation_slot_ids': [s['slot_id'] for s in slots if s['slot_id'] not in seeds],
        'bindings': [], 'failed_descendant_slot_ids': [], 'last_issued_model': None, 'final_slot_ids': list(seeds),
        'original_run_id': 'synthetic-original', 'original_run_ids': ['synthetic-original'], 'earliest_next_admission_utc': '2026-11-14T00:00:00+00:00',
        'continuation_path': j.CONTINUATION, 'continuation_sha256': RECEIPT_SHA}


def make_manifest(path, slots, **overrides):
    value = {'sessions_sha256': j.digest(slots), 'runtime_config': j.RUNTIME_CONFIG,
        'deadline_utc': j.DEADLINE.isoformat(), 'continuation_path': j.CONTINUATION,
        'continuation_sha256': RECEIPT_SHA, 'observed_response_models': j.OBSERVED_RESPONSE_MODELS, 'cumulative_cap_credits':'750', **overrides}
    raw = json.dumps(value).encode(); path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class ContinuationTests(unittest.TestCase):
    def run_case(self, slots, factory=None, *, clock=None, utc_start=None, before=None, carry=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); clock = clock or Clock(); starts = []; ends = []; reservations = []
            class Ledger(j.RollingLedger):
                def record(self, event):
                    if event['kind'] == 'reserve': reservations.append((clock.now(), event['slot_id']))
                    super().record(event)
            with patch.object(j, 'verify_prior_ledger', return_value=synthetic_prior()):
                ledger = Ledger(root / 'budget', baseline_path=ROOT / j.BASELINE_LEDGER,
                    continuation_path=ROOT/j.CONTINUATION, continuation_sha256=RECEIPT_SHA)
            p = root / 'execution.json'; sha = make_manifest(p, slots)
            chosen = factory(clock, starts, ends) if factory else lambda body: emit(final(body))
            active = [0]; peak = [0]
            async def transport(body):
                starts.append((clock.now(), body['model'], body['input'][-1]['content']))
                active[0] += 1; peak[0] = max(peak[0], active[0])
                try:
                    async for event in chosen(body): yield event
                finally:
                    active[0] -= 1; ends.append(clock.now())
            start = utc_start or datetime(2026, 11, 14, tzinfo=timezone.utc)
            seed = deepcopy(carry) if carry is not None else synthetic_carry(slots)
            before_seed = deepcopy(seed)
            try:
                if before: before(ledger, root, clock)
                with patch.object(j, 'verify_continuation', return_value=seed), patch.object(j, 'read_continuation',
                    return_value={'sessions_sha256':j.digest(slots)}):
                    summary = asyncio.run(j.run_slots(slots, api_key=KEY, output_dir=root / 'run', ledger=ledger,
                        transport=transport, execution_manifest_path=p, execution_manifest_sha256=sha,
                        _clock=clock.now, _sleep=clock.sleep, _utcnow=lambda: start + timedelta(seconds=clock.now())))
                self.assertEqual(seed, before_seed, 'Runtime mutated authenticated original state')
                rows = lambda name: [json.loads(x) for x in (root / 'run' / name).read_text().splitlines()]
                return {'summary': summary, 'requests': rows('requests.jsonl'), 'responses': rows('responses.jsonl'),
                    'outcomes': rows('slot-outcomes.jsonl'), 'manifest': rows('run.json')[0],
                    'ledger': [json.loads(x) for x in (root / 'budget/ledger.jsonl').read_text().splitlines()],
                    'streams': {p.name: p.read_text(encoding='utf-8') for p in (root / 'run/streams').glob('*.sse')},
                    'starts': starts, 'ends': ends, 'peak': peak[0], 'reservations': reservations}
            finally: ledger.close()

    # The same frozen synthetic behavioral tests exercise the unchanged pacing
    # and ordinary-failure policies against the NEW runtime through our helper.
    test_serial_completion_gap = prior_tests.SerialRuntimeTests.test_serial_completion_gap_includes_long_attempts_and_precedes_reserve
    test_early_wake = prior_tests.SerialRuntimeTests.test_early_wake_cannot_shorten_completion_delay
    test_fair_rotation = prior_tests.SerialRuntimeTests.test_fair_ready_rotation_and_model_order
    test_429_same_body = prior_tests.SerialRuntimeTests.test_429_retry_same_body_after_global65_and_no_slot_overtake
    test_larger_retry_after = prior_tests.SerialRuntimeTests.test_large_retry_after_blocks_every_model_and_fixed_floor_repeated
    test_exhausted_retry_continuation = prior_tests.SerialRuntimeTests.test_exhausted429_retains_three_bounds_and_independent_continues
    test_exhausted_retry_cooldown = prior_tests.SerialRuntimeTests.test_exhausted429_still_delays_next_independent_slot
    test408_5xx_continuation = prior_tests.SerialRuntimeTests.test408_and5xx_continue_without_retry_or_guessed_usage
    test_auth_protocol_halt = prior_tests.SerialRuntimeTests.test_auth_payment_and_unsafe_protocol_halt
    test_system_halt = prior_tests.SerialRuntimeTests.test_network_error_is_fatal_not_inferred_transient
    test_truncation = prior_tests.SerialRuntimeTests.test_valid_truncation_settles_and_skips_transitive_history
    test_actual_new_history = prior_tests.SerialRuntimeTests.test_actual_history_after_eventual_completion_and_output_only_projection
    test_deadline = prior_tests.SerialRuntimeTests.test_deadline_before_reservation_and_expiry_during_gap

    def test_exact_frozen_parser_body_and_prices_are_reused(self):
        self.assertIs(j.SSEDecoder, h.SSEDecoder); self.assertIs(j.StreamJournal, h.StreamJournal)
        self.assertIs(j.build_body, h.build_body); self.assertIs(j.usage_cost, h.usage_cost)



    def test_carried_success_used_as_actual_history_never_reissued(self):
        old = slot(0); new = slot(1, history_from=['s-0']); new['input'] = 'next event'
        seed = {'s-0': {'slot_id': 's-0', 'terminal_valid': True, 'output_text': 'original actual answer',
            'attempt_id': 'original-attempt', 'failure_scope': None, 'model_outcome': 'completed'}}
        result = self.run_case([old, new], carry=synthetic_carry([old, new], seed))
        self.assertEqual([r['slot_id'] for r in result['requests']], ['s-1'])
        self.assertEqual([r['slot_id'] for r in result['outcomes']], ['s-1'])
        body = result['requests'][0]['request']
        self.assertEqual(body['input'], [{'role': 'user', 'content': 'Source text'}, {'role': 'assistant', 'content': 'original actual answer'}, {'role': 'user', 'content': 'next event'}])
        self.assertEqual(result['requests'][0]['dependency_bindings'][0]['final_attempt_id'], 'original-attempt')
        self.assertEqual(result['summary']['planned'], 1); self.assertEqual(result['summary']['original_planned'], 2)
        self.assertEqual(result['summary']['carried_over_slots'], 1); self.assertEqual(result['summary']['completed'], 1)

    def test_carried_global_failure_propagates_two_skips_without_halting_new_independent_slot(self):
        slots = [slot(0, QWEN), slot(1, QWEN, history_from=['s-0']), slot(2, QWEN, history_from=['s-0', 's-1']), slot(3)]
        seed = {'s-0': {'slot_id': 's-0', 'terminal_valid': False, 'output_text': '', 'attempt_id': 'original-failed',
            'failure_scope': 'global', 'error': 'response_model_mismatch', 'model_outcome': 'operational_failure'}}
        result = self.run_case(slots, carry=synthetic_carry(slots, seed))
        self.assertEqual([r['slot_id'] for r in result['requests']], ['s-3'])
        self.assertEqual(len(result['outcomes']), 3); self.assertEqual(result['summary']['dependency_skips'], 2)
        self.assertEqual(result['summary']['status'], 'completed')
        self.assertEqual(result['summary']['issued_operational_failures'], 0)
        self.assertEqual(result['summary']['budget']['attempt_reservations'], 1)

    def test_only_observed_future_qwen_route_is_accepted_without_rewriting_raw(self):
        def factory(*args):
            def t(body):
                response_body = dict(body); response_body['model'] = ROUTE
                return emit(final(response_body, text='future answer'))
            return t
        result = self.run_case([slot(0, QWEN)], factory)
        row = result['responses'][0]
        self.assertEqual(row['model'], QWEN); self.assertEqual(row['requested_model'], QWEN)
        self.assertEqual(row['returned_model'], ROUTE); self.assertEqual(json.loads(row['raw_response'])['model'], ROUTE)
        self.assertEqual(result['requests'][0]['request']['model'], QWEN)
        self.assertEqual(row['model_identity_policy'], 'prospectively_pinned_observed_route_not_verified_alias')
        self.assertTrue(row['terminal_valid']); self.assertEqual(result['summary']['budget']['settled_attempts'], 1)

    def test_wrong_qwen_and_primary_alias_still_halt_and_retain(self):
        for requested, returned in ((QWEN, QWEN), (QWEN, 'qwen3.5-397b-some-other-route'), (MODEL, ROUTE)):
            with self.subTest(requested=requested, returned=returned):
                def factory(*args):
                    return lambda body: emit(final({**body, 'model': returned}))
                result = self.run_case([slot(0, requested), slot(1, requested)], factory)
                self.assertEqual(len(result['requests']), 1); self.assertEqual(result['summary']['status'], 'stopped')
                self.assertEqual(result['responses'][0]['error'], 'response_model_mismatch')
                self.assertEqual(result['responses'][0]['returned_model'], returned)
                self.assertEqual(result['summary']['budget']['unknown_operational_attempts_retained'], 1)

    def test_first_continuation_honors_previous_process_closure_gap(self):
        slots = [slot()]; carry = synthetic_carry(slots)
        carry['earliest_next_admission_utc'] = '2026-11-14T00:00:04+00:00'
        result = self.run_case(slots, carry=carry)
        self.assertGreaterEqual(result['starts'][0][0], 4)


    def read_failure(self, exc, *, headers=True, status=200, content_type='text/event-stream'):
        def factory(clock, starts, ends):
            async def transport(body):
                if len(starts) == 1:
                    if headers:
                        yield {'http_status': status, 'content_type': content_type, 'retry_after': '90' if status == 429 else None}
                    raise exc
                async for item in emit(final(body)): yield item
            return transport
        return self.run_case([slot(0), slot(1, history_from=['s-0']), slot(2)], factory)

    def test_post_header_reset_retains_skips_history_and_continues_without_retry(self):
        result = self.read_failure(ConnectionResetError('must not record arbitrary exception message'))
        row = result['responses'][0]
        self.assertEqual(result['summary']['status'], 'completed')
        self.assertEqual([r['slot_id'] for r in result['requests']], ['s-0', 's-2'])
        self.assertEqual(row['error'], 'post_headers_transport_read_failure')
        self.assertEqual(row['transport_exception_type'], 'builtins.ConnectionResetError')
        self.assertEqual(row['transport_failure_stage'], 'response_body')
        self.assertTrue(row['transport_headers_validated'])
        self.assertEqual(row['transport_content_type'], 'text/event-stream')
        self.assertEqual(row['failure_scope'], 'slot'); self.assertFalse(row['terminal_valid'])
        self.assertIsNone(row['usage']); self.assertIsNone(row['settled_credits'])
        self.assertIsNone(row['raw_response']); self.assertEqual(row['output_text'], '')
        self.assertEqual(result['summary']['retries'], 0)
        self.assertEqual(result['summary']['budget']['unknown_operational_attempts_retained'], 1)
        self.assertGreaterEqual(result['starts'][1][0] - result['ends'][0], 4)
        self.assertNotIn('must not record', json.dumps(result))

    def test_preheader_reset_and_arbitrary_postheader_oserror_remain_global(self):
        for exc, headers in ((ConnectionResetError('secret'), False), (OSError('secret'), True),
                             (RuntimeError('secret'), True), (asyncio.TimeoutError(), False)):
            with self.subTest(exc=type(exc).__name__, headers=headers):
                result = self.read_failure(exc, headers=headers)
                row = result['responses'][0]
                self.assertEqual(result['summary']['status'], 'stopped')
                self.assertEqual(len(result['requests']), 1)
                self.assertEqual(row['error'], 'network_or_transport_failure')
                self.assertEqual(row['failure_scope'], 'global')
                self.assertEqual(row['transport_headers_validated'], headers)
                self.assertIsNone(row['settled_credits'])

    def test_postheader_auth_payment_wrong_content_and_redirect_never_downgrade(self):
        for status, content_type in ((401, 'application/json'), (402, 'application/json'),
                                    (403, 'application/json'), (200, 'application/json'),
                                    (302, 'text/html'), (400, 'application/json')):
            with self.subTest(status=status, content_type=content_type):
                result = self.read_failure(ConnectionResetError(), status=status, content_type=content_type)
                self.assertEqual(result['summary']['status'], 'stopped')
                self.assertEqual(result['responses'][0]['failure_scope'], 'global')

    def test_header_range_violation_is_protocol_failure_not_transport_failure(self):
        result = self.read_failure(ConnectionResetError(), status=999)
        row = result['responses'][0]
        self.assertEqual(row['error'], 'stream_invalid_headers')
        self.assertFalse(row['transport_headers_validated'])
        self.assertIsNone(row['transport_exception_type'])
        self.assertEqual(result['summary']['status'], 'stopped')

    def test_postheader429_reset_keeps_cooldown_but_is_not_retryable429(self):
        result = self.read_failure(ConnectionResetError(), status=429, content_type='application/json')
        self.assertEqual(result['responses'][0]['retry_cooldown_seconds'], 90)
        self.assertEqual(result['summary']['http_429_attempts'], 0)
        self.assertEqual(result['summary']['retries'], 0)
        self.assertGreaterEqual(result['starts'][1][0] - result['ends'][0], 90)

    def test_unsafe_sse_parser_failure_after_headers_stays_global(self):
        def factory(*args):
            async def transport(body):
                yield {'http_status': 200, 'content_type': 'text/event-stream'}
                yield b'data: {bad json}\n\n'
            return transport
        result = self.run_case([slot(0), slot(1)], factory)
        self.assertEqual(result['summary']['status'], 'stopped')
        self.assertIsNone(result['responses'][0]['transport_exception_type'])
        self.assertTrue(result['responses'][0]['transport_headers_validated'])
        self.assertNotEqual(result['responses'][0]['error'], 'post_headers_transport_read_failure')

    def test_consumer_reset_is_not_misclassified_as_transport_reset(self):
        # Same exception type, different origin: the decoder must still halt.
        with patch.object(j.SSEDecoder, 'feed', side_effect=ConnectionResetError('decoder internal')):
            result = self.run_case([slot(0), slot(1)])
        self.assertEqual(result['summary']['status'], 'stopped')
        self.assertIsNone(result['responses'][0]['transport_exception_type'])
        self.assertEqual(result['responses'][0]['exception_type'], 'builtins.ConnectionResetError')

    def test_consumer_and_close_timeout_are_not_outer_deadline_expiration(self):
        with patch.object(j.SSEDecoder, 'feed', side_effect=TimeoutError('decoder timeout')):
            result = self.run_case([slot(0), slot(1)])
        self.assertEqual(result['summary']['status'], 'stopped')
        self.assertEqual(result['responses'][0]['error'], 'network_or_transport_failure')
        self.assertEqual(result['responses'][0]['exception_type'], 'builtins.TimeoutError')
        self.assertIsNone(result['responses'][0]['transport_exception_type'])
        class CloseFails:
            def __aiter__(self): return self
            async def __anext__(self): raise StopAsyncIteration
            async def aclose(self): raise TimeoutError('close timeout')
        async def exercise():
            with self.assertRaises(j.InnerOperationTimeout):
                await asyncio.wait_for(j.separate_inner_timeout(j.consume_stream(
                    j.guard_transport(CloseFails(), {'validated':False,'status':None,'content_type':None}),
                    None, j.SSEDecoder())), timeout=180)
        asyncio.run(exercise())

    def test_terminal_received_then_disconnect_is_not_rescued_as_completion(self):
        def factory(clock, starts, ends):
            async def transport(body):
                async for item in emit(final(body)): yield item
                if len(starts) == 1: raise ConnectionResetError('late read failure')
            return transport
        result = self.run_case([slot(0), slot(1)], factory)
        row = result['responses'][0]
        self.assertIsNotNone(row['stream_terminal_event'])
        self.assertFalse(row['terminal_valid']); self.assertIsNone(row['usage'])
        self.assertIsNone(row['settled_credits']); self.assertEqual(row['output_text'], '')
        stream = result['streams'][hashlib.sha256(row['attempt_id'].encode()).hexdigest()+'.sse']
        self.assertEqual(hashlib.sha256(stream.encode()).hexdigest(), row['stream_evidence']['saved_sha256'])
        self.assertEqual(result['summary']['completed'], 1)
        self.assertEqual(result['summary']['budget']['unknown_operational_attempts_retained'], 1)

    def test_outer_fixed_timeout_remains_per_slot_with_no_retry(self):
        original_wait = asyncio.wait_for
        async def shortened_wait(coro, timeout):
            self.assertEqual(timeout, 180)
            return await original_wait(coro, timeout=.025)
        def factory(clock, starts, ends):
            async def transport(body):
                if len(starts) == 1: await asyncio.sleep(1)
                async for item in emit(final(body)): yield item
            return transport
        with patch.object(j.asyncio, 'wait_for', side_effect=shortened_wait):
            result = self.run_case([slot(0), slot(1, history_from=['s-0']), slot(2)], factory)
        self.assertEqual(result['summary']['status'], 'completed')
        self.assertEqual(result['responses'][0]['error'], 'timeout')
        self.assertIsNone(result['responses'][0]['transport_exception_type'])
        self.assertEqual(result['summary']['dependency_skips'], 1)

    def test_exact_aiohttp_exception_types_and_preheader_rejection(self):
        try:
            from aiohttp import client_exceptions as ce
        except ImportError:
            self.skipTest('Pinned aiohttp checked in full preflight; stdlib-only reproduction omits it')
        for cls in (ce.ServerDisconnectedError, ce.ClientPayloadError, ce.ClientConnectionResetError):
            with self.subTest(cls=cls.__name__):
                result = self.read_failure(cls('private error body'))
                self.assertEqual(result['responses'][0]['error'], 'post_headers_transport_read_failure')
                result = self.read_failure(cls('private error body'), headers=False)
                self.assertEqual(result['summary']['status'], 'stopped')
        for cls in (ce.ConnectionTimeoutError, ce.ServerTimeoutError, ce.ClientConnectionError):
            result = self.read_failure(cls('private error body'))
            self.assertEqual(result['summary']['status'], 'stopped')






def prior_chain_fixture(*, extra=0, reason='cumulative_budget_stop'):
    """Independently specified closed old-cap chain, with one unknown bound."""
    earlier={'carry_credits':'80.145946577','file_sha256':'e'*64,
             'cumulative_inherited_unsettled_attempts':64}
    events=[{'kind':'initialize','historical_credits':earlier['carry_credits'],
             'historical_sha256':earlier['file_sha256'],'cap_credits':'250'},
        {'kind':'run_started','run_id':'old-k'},
        {'kind':'reserve','run_id':'old-k','attempt_id':'unknown','bound_nanocredits':169_000_000_000+extra},
        {'kind':'retain_unknown','attempt_id':'unknown','reason':'http_502','response_sha256':'c'*64},
        {'kind':'reserve','run_id':'old-k','attempt_id':'known','bound_nanocredits':200_000_000},
        {'kind':'settle','attempt_id':'known','accounted_nanocredits':50_000_000,'response_sha256':'d'*64},
        {'kind':'halt','run_id':'old-k','reason':reason,'attempt_id':None},
        {'kind':'run_closed','run_id':'old-k','status':'stopped','issued_attempts':2}]
    def pack(items):
        rows=[]; previous='0'*64
        for n,event in enumerate(items,1):
            row={'seq':n,'previous_sha256':previous,'at':'2026-11-14T00:00:00+00:00','event':event}
            row['sha256']=j.digest(row); previous=row['sha256'];rows.append(row)
        return b''.join((j.encoded(x)+'\n').encode() for x in rows), previous
    raw,chain=pack(events)
    carry=j.credits(j.nano(earlier['carry_credits'])+169_000_000_000+extra+50_000_000)
    receipt={'baseline_snapshot_sha256':hashlib.sha256(raw).hexdigest(),
             'historical_conservative_carry_credits':carry,'inherited_unsettled_attempts':65}
    summary={'run_id':'old-k','issued_attempts':2,'budget':{'ledger_sha256':chain,
             'unsettled_attempts':1,'settled_attempts':1}}
    return raw,earlier,receipt,summary,events,pack


class BudgetAndAuthenticationTests(unittest.TestCase):
    def ledger(self, directory, **kwargs):
        with patch.object(j,'verify_prior_ledger',return_value=synthetic_prior(**kwargs)):
            return j.RollingLedger(directory,baseline_path=ROOT/j.BASELINE_LEDGER,
                continuation_path=ROOT/j.CONTINUATION,continuation_sha256=RECEIPT_SHA)

    def test_old_cap_replay_retains_full_unknown_and_dynamic_carry(self):
        raw,earlier,receipt,summary,_,_=prior_chain_fixture()
        proof=j.replay_prior_ledger(raw,earlier,receipt,summary)
        self.assertEqual(proof['carry_credits'],'249.195946577')
        self.assertEqual(proof['cumulative_inherited_unsettled_attempts'],65)
        self.assertEqual(proof['unknown_operational_attempts_retained'],1)
        self.assertEqual(proof['settled_attempts'],1)
        # A rehashed old chain still may never exploit the prospective 750 cap.
        raw,earlier,receipt,summary,_,_=prior_chain_fixture(extra=1_000_000_000)
        with self.assertRaisesRegex(ValueError,'original_cap_breach'):
            j.replay_prior_ledger(raw,earlier,receipt,summary)

    def test_wrong_prior_stop_or_unknown_release_is_rejected_even_after_rehash(self):
        raw,earlier,receipt,summary,_,_=prior_chain_fixture(reason='administrative_deadline')
        with self.assertRaisesRegex(ValueError,'halt_not_budget'):
            j.replay_prior_ledger(raw,earlier,receipt,summary)
        raw,earlier,receipt,summary,events,pack=prior_chain_fixture()
        events.insert(4,{'kind':'settle','attempt_id':'unknown','accounted_nanocredits':0,'response_sha256':'a'*64})
        raw,chain=pack(events);receipt['baseline_snapshot_sha256']=hashlib.sha256(raw).hexdigest();summary['budget']['ledger_sha256']=chain
        with self.assertRaisesRegex(ValueError,'double_finalization'):
            j.replay_prior_ledger(raw,earlier,receipt,summary)

    def test_wrong_inherited_unknown_count_and_pending_prior_reservation_reject(self):
        raw,earlier,receipt,summary,events,pack=prior_chain_fixture()
        receipt['inherited_unsettled_attempts']=1
        with self.assertRaisesRegex(ValueError,'unknown_carry'):
            j.replay_prior_ledger(raw,earlier,receipt,summary)
        receipt['inherited_unsettled_attempts']=65;events.pop(3)
        raw,chain=pack(events);receipt['baseline_snapshot_sha256']=hashlib.sha256(raw).hexdigest();summary['budget']['ledger_sha256']=chain
        with self.assertRaisesRegex(ValueError,'halt_not_budget'):
            j.replay_prior_ledger(raw,earlier,receipt,summary)

    def test_new_cap_exceeds250_exactly750_works_and_one_nano_more_rejects_atomically(self):
        old_hcap=h.CAP
        from retrace import adaption_v6k as k
        old_kcap=k.CAP
        self.assertEqual(old_kcap,250_000_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            ledger=self.ledger(Path(tmp))
            try:
                ledger.record({'kind':'run_started','run_id':'l'})
                ledger.record({'kind':'reserve','run_id':'l','attempt_id':'a','bound_nanocredits':501_000_000_000})
                self.assertEqual(ledger.accounted,750_000_000_000)
                self.assertGreater(ledger.accounted,h.CAP)
                before=ledger.snapshot();raw=(Path(tmp)/'ledger.jsonl').read_bytes()
                with self.assertRaisesRegex(ValueError,'cap_exceeded'):
                    ledger.record({'kind':'reserve','run_id':'l','attempt_id':'b','bound_nanocredits':1})
                self.assertEqual(ledger.snapshot(),before);self.assertEqual((Path(tmp)/'ledger.jsonl').read_bytes(),raw)
                ledger.record({'kind':'retain_unknown','attempt_id':'a','reason':'timeout','response_sha256':'a'*64})
                with self.assertRaisesRegex(ValueError,'cannot_settle'):
                    ledger.record({'kind':'settle','attempt_id':'a','accounted_nanocredits':0,'response_sha256':'b'*64})
                self.assertEqual(ledger.accounted,750_000_000_000)
                self.assertEqual(ledger.snapshot()['cumulative_inherited_unsettled_attempts'],73)
                ledger.record({'kind':'run_closed','run_id':'l','status':'completed','issued_attempts':1})
            finally:ledger.close()
        self.assertEqual(h.CAP,old_hcap);self.assertEqual(k.CAP,old_kcap)

    def test_global_accounting_failure_can_close_without_releasing_or_hiding_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=self.ledger(Path(tmp))
            try:
                ledger.record({'kind':'run_started','run_id':'l'})
                ledger.record({'kind':'reserve','run_id':'l','attempt_id':'orphan','bound_nanocredits':100})
                with self.assertRaisesRegex(ValueError,'unresolved_or_misclassified'):
                    ledger.record({'kind':'run_closed','run_id':'l','status':'completed'})
                ledger.record({'kind':'halt','run_id':'l','reason':'unexpected_worker_or_journal_failure'})
                ledger.record({'kind':'run_closed','run_id':'l','status':'stopped'})
                self.assertEqual(ledger.accounted,249_000_000_100)
                self.assertEqual(ledger.snapshot()['unsettled_attempts'],1)
                self.assertIsNone(ledger.attempts['orphan']['kind'])
            finally:ledger.close()

    def test_settlement_releases_only_new_known_unused_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=self.ledger(Path(tmp))
            try:
                ledger.record({'kind':'run_started','run_id':'l'})
                ledger.record({'kind':'reserve','run_id':'l','attempt_id':'a','bound_nanocredits':100_000_000_000})
                ledger.record({'kind':'settle','attempt_id':'a','accounted_nanocredits':123,'response_sha256':'a'*64})
                self.assertEqual(ledger.accounted,249_000_000_123)
                self.assertEqual(ledger.snapshot()['historical_carry_credits'],'249')
                self.assertEqual(ledger.snapshot()['cumulative_inherited_unsettled_attempts'],73)
                with self.assertRaisesRegex(ValueError,'cannot_settle'):
                    ledger.record({'kind':'settle','attempt_id':'a','accounted_nanocredits':0,'response_sha256':'a'*64})
            finally:ledger.close()

    def test_new_ledger_cannot_reopen_or_steal_lock_and_write_failure_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=self.ledger(root)
            try:
                ledger.record({'kind':'run_started','run_id':'l'})
                before=ledger.snapshot()
                with patch.object(ledger.file,'write',side_effect=OSError('invented fsync failure')):
                    with self.assertRaises(OSError): ledger.record({'kind':'reserve','run_id':'l','attempt_id':'a','bound_nanocredits':100})
                self.assertEqual(before,ledger.snapshot())
                with self.assertRaisesRegex(ValueError,'must_be_new'):self.ledger(root)
                self.assertTrue((root/'active.lock').exists())
            finally:ledger.close()
            with self.assertRaisesRegex(ValueError,'must_be_new'):self.ledger(root)
            other=root/'other';other.mkdir();(other/'active.lock').write_text('someone else')
            with self.assertRaises(FileExistsError):self.ledger(other)
            self.assertEqual((other/'active.lock').read_text(),'someone else')

    def test_manifest_cap_route_config_and_receipt_hash_remain_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'execution.json';slots=[slot()]
            with patch.object(j,'read_continuation',return_value={'sessions_sha256':j.digest(slots)}) as reader:
                sha=make_manifest(path,slots);j.verify_execution_manifest(path,sha,slots)
                reader.assert_called_with(ROOT/j.CONTINUATION,RECEIPT_SHA)
                for fields,error in (({'cumulative_cap_credits':'250'},'budget'),
                    ({'runtime_config':{**j.RUNTIME_CONFIG,'completion_delay_seconds':3}},'policy'),
                    ({'observed_response_models':{}},'continuation_policy')):
                    sha=make_manifest(path,slots,**fields)
                    with self.assertRaisesRegex(ValueError,error):j.verify_execution_manifest(path,sha,slots)
                sha=make_manifest(path,slots);path.write_bytes(path.read_bytes()+b' ')
                with self.assertRaisesRegex(ValueError,'hash'):j.verify_execution_manifest(path,sha,slots)

    def test_runtime_attempt_scheduler_and_transport_guard_match_frozen_k_ast(self):
        import ast
        def functions(path):
            return {x.name:ast.dump(x,include_attributes=False) for x in ast.walk(ast.parse(path.read_text()))
                if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))}
        old=functions(ROOT/'retrace/adaption_v6k.py');new=functions(ROOT/'retrace/adaption_v6l.py')
        for name in ('attempt','worker','retry_delay','guard_transport','admitted_read_exception',
                     'separate_inner_timeout','exception_name','finalize','skipped','check_stop','stop'):
            self.assertEqual(old[name],new[name],name)





def carry_fixture():
    """Three prior invented journals; known answer text is fixed test data."""
    slots=[slot(0),slot(1,history_from=['s-0']),slot(2),slot(3,history_from=['s-2']),
           slot(4,history_from=['s-1']),slot(5,history_from=['s-4']),slot(6,history_from=['s-2'])]
    contents={};segments=[];carried={};completed={};bindings=[];issued=[]
    for segment,definitions in [('i',[(0,'completed')]),('j',[(1,'completed'),(2,'operational_failure'),(3,'not_issued_dependency_failed')]),('k',[(4,'completed')])]:
        rid='old-'+segment;qs=[];rs=[];fs=[];remaining=[x for x in slots if x['slot_id'] not in carried]
        paths={key:segment+'/'+key for key in ['run_manifest','requests','responses','outcomes','summary','audit','ledger']}
        for number,(n,outcome) in enumerate(definitions,1):
            st=slots[n];sid=st['slot_id']
            if outcome=='not_issued_dependency_failed':
                f={'run_id':rid,'slot_id':sid,'slot_final':True,'issued':False,'attempts_issued':0,
                   'model_outcome':outcome,'first_attempt_id':None,'blocked_dependencies':['s-2'],'output_text':''}
            else:
                aid=rid+':'+sid;messages=[]
                for dep in st.get('history_from',[]):
                    messages += [{'role':'user','content':completed[dep]['actual_input']},
                                 {'role':'assistant','content':completed[dep]['output_text']}]
                messages.append({'role':'user','content':st['input']})
                body={'model':st['model'],'instructions':st['instructions'],'input':messages,
                      'max_output_tokens':st['max_output_tokens'],'temperature':st.get('temperature',1.0),'stream':True,
                      'store':False,'previous_response_id':None,'agentic_memory':False,'tools':[],'tool_choice':'none'}
                q={'attempt_id':aid,'slot_id':sid,'request':body,'request_sha256':j.digest(body),'attempt_number':1}
                r={'run_id':rid,'slot_id':sid,'attempt_id':aid,'attempt_number':1,'first_attempt':True,
                   'issued':True,'model_outcome':outcome,'terminal_valid':outcome=='completed',
                   'error':None if outcome=='completed' else 'http_502','response_status':'completed' if outcome=='completed' else None,
                   'output_text':segment+' test answer' if outcome=='completed' else '',
                   'raw_response':json.dumps({'id':'synthetic','model':st['model'],'status':'completed','output_text':segment+' test answer'}) if outcome=='completed' else None}
                qs.append(q);rs.append(r);issued.append(sid)
                if outcome=='completed':completed[sid]={'actual_input':st['input'],'output_text':r['output_text']}
                f={**r,'slot_final':True,'attempts_issued':1,'first_attempt_id':aid}
            fs.append(f);carried[sid]=f
            bindings.append({'segment':segment,'slot_id':sid,'source_path':paths['outcomes'],
                             'source_line_one_based':number,'row_sha256':j.digest(f),
                             'attempt_id':f.get('attempt_id'),'model_outcome':outcome})
        fs += [{'run_id':rid,'slot_id':x['slot_id'],'slot_final':True,'issued':False,'attempts_issued':0,
                'model_outcome':'not_issued_global_stop','output_text':''} for x in remaining if x['slot_id'] not in carried]
        objects={'run_manifest':{'run_id':rid,'slots':slots,'sessions_sha256':j.digest(slots)},
                 'summary':{'run_id':rid,'status':'stopped','issued_slots':len(qs)},
                 'audit':{'schedule_status':'stopped','passed':True,'final_closed':True}}
        contents.update({paths[key]:(j.encoded(value)+'\n').encode() for key,value in objects.items()})
        contents.update({paths[key]:b''.join((j.encoded(value)+'\n').encode() for value in rows)
                         for key,rows in [('requests',qs),('responses',rs),('outcomes',fs)]})
        segments.append({'segment':segment,'run_id':rid,'paths':paths,
                         'issued_slots':len(qs),'definitive_final_slots':len(definitions)})
    contents['snapshot']=(j.encoded({'at':'2026-11-14T00:00:00+00:00','event':{'kind':'run_closed'}})+'\n').encode()
    receipt={'source_segments':segments,'carried_final_outcomes':bindings,
             'permanently_excluded_final_slot_ids':list(carried),'permanently_excluded_issued_slot_ids':issued,
             'continuation_slot_ids':['s-5','s-6'],'continuation_slots':2,'carried_final_slots':5,'carried_issued_slots':4,
             'failed_producer_descendant_slot_ids':['s-6'],'original_run_ids':['old-i','old-j','old-k'],
             'original_run_id':'old-i','baseline_snapshot_path':'snapshot'}
    return slots,receipt,contents


class CarryBoundaryTests(unittest.TestCase):
    def test_three_segments_preserve_actual_histories_definitive_skips_and_only_neverissued_complement(self):
        slots,receipt,contents=carry_fixture();original=deepcopy((receipt,contents))
        carry=j.derive_carry(slots,receipt,contents,continuation_sha256=RECEIPT_SHA)
        self.assertEqual(carry['final_slot_ids'],['s-0','s-1','s-2','s-3','s-4'])
        self.assertEqual(carry['issued_slot_ids'],['s-0','s-1','s-2','s-4'])
        self.assertEqual(carry['continuation_slot_ids'],['s-5','s-6'])
        self.assertEqual(carry['failed_descendant_slot_ids'],['s-6'])
        self.assertEqual(carry['completed']['s-4']['output_text'],'k test answer')
        self.assertEqual(carry['earliest_next_admission_utc'],'2026-11-14T00:00:04+00:00')
        self.assertEqual((receipt,contents),original)

    def test_dropping_any_definitive_row_or_replacing_history_is_rejected(self):
        slots,receipt,contents=carry_fixture()
        for sid in ('s-2','s-3','s-4'):
            changed=deepcopy(receipt)
            changed['carried_final_outcomes']=[x for x in changed['carried_final_outcomes'] if x['slot_id']!=sid]
            with self.assertRaisesRegex(ValueError,'carryover_selection_changed'):
                j.derive_carry(slots,changed,contents,continuation_sha256=RECEIPT_SHA)
        rows=[json.loads(x) for x in contents['k/requests'].splitlines()]
        rows[0]['request']['input'][1]['content']='invented replacement of original answer'
        rows[0]['request_sha256']=j.digest(rows[0]['request'])
        changed=dict(contents);changed['k/requests']=b''.join((j.encoded(r)+'\n').encode() for r in rows)
        with self.assertRaisesRegex(ValueError,'actual_history_binding'):
            j.derive_carry(slots,receipt,changed,continuation_sha256=RECEIPT_SHA)

    def test_k_only_cap_stop_gate_rejects_other_stops_active_worker_and_unbound_audit(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(j,'ROOT',Path(tmp)):
            paths={key:'k/'+key for key in ('summary','audit','run_manifest','requests','responses','outcomes','ledger')}
            receipt={'source_segments':[{'paths':paths}],'historical_conservative_carry_credits':'249'}
            summary={'schema':'retrace.adaption-v6k-summary.v1','status':'stopped','stop_reasons':['cumulative_budget_stop'],
                     'issued_without_outcome_attempt_ids':[],'all_scheduled_outcomes_recorded':True,
                     'budget':{'accounted_credits':'249','cumulative_cap_credits':'250','halted':True}}
            contents={name:b'{}' for name in paths.values()};contents[paths['summary']]=j.encoded(summary).encode()
            audit={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':'stopped',
                   'cumulative_accounted_credits':'249','input_bindings':{name:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
                   for name,raw in contents.items() if name!=paths['audit']}}
            contents[paths['audit']]=j.encoded(audit).encode()
            j.closed_k_contract(receipt,contents)
            for stop in ('administrative_deadline','network_or_transport_failure'):
                changed=deepcopy(contents);changed[paths['summary']]=j.encoded({**summary,'stop_reasons':[stop]}).encode()
                with self.assertRaisesRegex(ValueError,'not_closed_budget_stop'):j.closed_k_contract(receipt,changed)
            changed=deepcopy(contents);changed[paths['requests']]+=b' '
            with self.assertRaisesRegex(ValueError,'audit_source_binding'):j.closed_k_contract(receipt,changed)
            lock=Path(tmp)/'results/frontier-v6k/budget/active.lock';lock.parent.mkdir(parents=True);lock.write_text('existing worker')
            with self.assertRaisesRegex(ValueError,'still_active'):j.closed_k_contract(receipt,contents)


if __name__=='__main__':unittest.main()
