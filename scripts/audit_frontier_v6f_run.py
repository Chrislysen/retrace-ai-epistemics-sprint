"""Independent read-only v6f accounting and execution audit. Never imports a runner.

Only reads local bytes and writes JSON to stdout. No provider, credential, model,
semantic scorer or tokenizer access. Active journals are snapshots, not closure.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FREEZE = 'data/frontier-v6f-primary-freeze.json'
FREEZE_SHA256 = '93debd70b8667f8f656d2f0929b5cf81b1ef410665ca80d43a666ad5ddf20358'
CAP = 250_000_000_000
BASELINE = '42.997746364'
SCALE = Decimal(1_000_000_000)
PRICES = {
    'deepseek-v4-flash': ('0.045', '0.14', 1048576),
    'gemma-4-31b-it': ('0.09', '0.34', 256000),
    'glm-5.3-flash': ('0.15', '0.50', 1048576),
    'qwen3.8-27b': ('0.039', '1.25', 262144),
    'glm-5.2': ('1.40', '4.40', 1048575),
}
POLICY = {'window_seconds': 61.0, 'reference_token_budget': 100000,
          'max_starts': 10, 'solo_weight_limit': 125000,
          'initial_cooldown_seconds': 61.0, 'quota_verified': False,
          'basis': 'Conservative local policy; provider quota is not documented.'}


class AuditError(ValueError):
    """A bounded local diagnostic; never include raw prompts/provider text."""


def require(condition, code):
    if not condition:
        raise AuditError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return sha(canonical(value).encode('utf-8'))


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def invalid(_):
        raise AuditError('nonfinite_json')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError):
        raise AuditError('invalid_json_bytes') from None


def jsonl(raw):
    require(not raw or raw.endswith(b'\n'), 'incomplete_journal_line')
    lines = raw.splitlines(keepends=True)
    require(all(line.strip() for line in lines), 'blank_journal_line')
    return [strict_json(line) for line in lines]


def nanocredits(value):
    try:
        number = Decimal(str(value)) * SCALE
        require(number.is_finite() and number >= 0, 'invalid_credit_amount')
        require(number == number.to_integral_value(), 'subnanocredit_amount')
        return int(number)
    except (ValueError, ArithmeticError):
        raise AuditError('invalid_credit_amount') from None


def credits(value):
    return format(Decimal(value) / SCALE, 'f')


def integer(value, low=0, high=10**18):
    require(type(value) is int and low <= value <= high, 'invalid_integer')
    return value


def bound(model, maximum):
    inp, out, context = PRICES[model]
    cost = (Decimal(context) * Decimal(inp) + Decimal(maximum) * Decimal(out)) / 1_000_000
    return int((cost * SCALE).to_integral_value(rounding=ROUND_CEILING))


def cost(model, usage, maximum):
    require(isinstance(usage, dict), 'missing_usage')
    inp, out, context = PRICES[model]
    it = integer(usage.get('input_tokens'), 0, context)
    ot = integer(usage.get('output_tokens'), 0, maximum)
    if 'total_tokens' in usage:
        require(type(usage['total_tokens']) is int and usage['total_tokens'] == it + ot, 'usage_total_mismatch')
    for key, field, ceiling in [('input_tokens_details', 'cached_tokens', it),
                                 ('output_tokens_details', 'reasoning_tokens', ot)]:
        detail = usage.get(key)
        require(detail is None or isinstance(detail, dict), 'invalid_usage_details')
        if detail is not None and field in detail:
            integer(detail[field], 0, ceiling)
    amount = (Decimal(it) * Decimal(inp) + Decimal(ot) * Decimal(out)) / 1_000_000
    return int((amount * SCALE).to_integral_value(rounding=ROUND_CEILING))


def snapshot(accounted, attempts, chain, halted, historical):
    settled = sum(a.get('settle') is not None for a in attempts.values())
    return {'cumulative_cap_credits': '250', 'historical_carry_credits': historical,
            'accounted_credits': credits(accounted), 'remaining_credits': credits(CAP - accounted),
            'attempt_reservations': len(attempts), 'settled_attempts': settled,
            'unsettled_attempts': len(attempts) - settled, 'ledger_sha256': chain,
            'halted': halted, 'actual_billed_credits': None}


def replay_ledger(raw, historical, historical_sha256):
    """Independent integer replay; no old unsettled reservation is released."""
    rows = jsonl(raw)
    require(bool(rows), 'empty_ledger')
    accounted, chain, attempts, runs, states = nanocredits(historical), '0' * 64, {}, {}, {}
    halted = False
    for seq, row in enumerate(rows, 1):
        require(isinstance(row, dict) and row.get('seq') == seq and row.get('previous_sha256') == chain, 'ledger_chain_mismatch')
        require(row.get('sha256') == digest({k: v for k, v in row.items() if k != 'sha256'}), 'ledger_row_hash_mismatch')
        event = row['event']; kind = event['kind']
        if seq == 1:
            require(kind == 'initialize' and event['historical_credits'] == historical
                    and event['historical_sha256'] == historical_sha256 and event['cap_credits'] == '250', 'ledger_initial_mismatch')
        elif kind == 'run_started':
            rid = event['run_id']
            require(not halted and rid not in runs and all(r.get('close') for r in runs.values()), 'invalid_run_start')
            runs[rid] = {'start': event, 'start_seq': seq, 'prior_chain': chain, 'close': None, 'halts': []}
        elif kind == 'reserve':
            rid, aid = event['run_id'], event['attempt_id']
            require(not halted and rid in runs and runs[rid]['close'] is None, 'reservation_outside_active_run')
            require(aid == rid + ':' + event['slot_id'] and aid not in attempts, 'duplicate_or_invalid_attempt')
            amount = integer(event['bound_nanocredits'], 1, CAP)
            require(event['model'] in PRICES, 'unknown_ledger_model')
            accounted += amount
            attempts[aid] = {'reserve': event, 'reserve_seq': seq, 'settle': None}
        elif kind == 'settle':
            aid = event['attempt_id']; require(aid in attempts, 'settlement_without_reservation')
            attempt = attempts[aid]
            require(attempt['settle'] is None, 'duplicate_settlement')
            require(runs[attempt['reserve']['run_id']]['close'] is None, 'settlement_after_run_close')
            amount = integer(event['accounted_nanocredits'], 0, attempt['reserve']['bound_nanocredits'])
            accounted += amount - attempt['reserve']['bound_nanocredits']
            attempt.update(settle=event, settle_seq=seq)
        elif kind == 'halt':
            require(event['run_id'] in runs and runs[event['run_id']]['close'] is None, 'halt_outside_run')
            halted = True; runs[event['run_id']]['halts'].append(event)
        elif kind == 'run_closed':
            rid = event['run_id']; require(rid in runs and runs[rid]['close'] is None, 'duplicate_or_unknown_run_close')
            require(event['status'] in ('completed', 'stopped'), 'invalid_closed_status')
            require(event['status'] == ('stopped' if runs[rid]['halts'] else 'completed'), 'halt_close_status_mismatch')
            runs[rid].update(close=event, close_seq=seq, close_chain=row['sha256'])
        else:
            raise AuditError('unknown_or_repeated_ledger_initialization')
        require(0 <= accounted <= CAP, 'cumulative_cap_breach')
        chain = row['sha256']
        states[chain] = snapshot(accounted, attempts, chain, halted, historical)
    return {'rows': rows, 'attempts': attempts, 'runs': runs, 'states': states,
            'snapshot': states[chain], 'raw_sha256': sha(raw)}


def output_text(response):
    if isinstance(response.get('output_text'), str):
        return response['output_text']
    require(isinstance(response.get('output'), list), 'terminal_output_missing')
    parts = []
    for item in response['output']:
        if isinstance(item, dict) and item.get('type') == 'message' and item.get('role') == 'assistant':
            for part in item.get('content', []):
                if isinstance(part, dict) and part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                    parts.append(part['text'])
    return ''.join(parts)


def parse_sse(raw):
    """Parse saved whole-stream bytes independently of the production decoder."""
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        raise AuditError('sse_invalid_utf8') from None
    # Only CR/LF delimit SSE lines; Unicode separators inside JSON are data.
    lines = re.split(r'\r\n|\r|\n', text)
    require(lines[-1] == '', 'sse_unterminated_line')
    data, event_name, begun = [], None, False
    terminal, final, done, events, last_seq, rid, deltas = None, None, False, 0, None, None, []
    for line in lines[:-1]:
        if line:
            if line.startswith(':'):
                continue
            begun = True
            field, sep, value = line.partition(':')
            if value.startswith(' '): value = value[1:]
            if field == 'data': data.append(value if sep else '')
            if field == 'event':
                require(event_name is None, 'sse_duplicate_event_field'); event_name = value
            continue
        if data:
            payload = '\n'.join(data)
            if payload == '[DONE]':
                require(final is not None and not done, 'sse_unproven_done'); done = True
            else:
                require(terminal is None and not done, 'sse_event_after_terminal')
                event = strict_json(payload)
                require(isinstance(event, dict) and isinstance(event.get('type'), str) and bool(event['type']), 'sse_missing_type')
                kind = event['type']; events += 1
                require(events <= 100000 and event_name in (None, 'message', kind), 'sse_event_type_or_count')
                if 'sequence_number' in event:
                    seq = integer(event['sequence_number'], 0, 10**9)
                    require(last_seq is None or seq > last_seq, 'sse_sequence_order'); last_seq = seq
                response = event.get('response')
                if isinstance(response, dict) and isinstance(response.get('id'), str):
                    require(rid in (None, response['id']), 'sse_response_identity_changed'); rid = response['id']
                if kind == 'response.output_text.delta':
                    require(isinstance(event.get('delta'), str), 'sse_invalid_delta'); deltas.append(event['delta'])
                require(kind not in ('error', 'response.failed', 'response.cancelled'), 'sse_terminal_failure')
                if kind in ('response.completed', 'response.incomplete'):
                    require(isinstance(response, dict), 'sse_terminal_response_missing')
                    status = response.get('status')
                    if status == 'incomplete':
                        require(isinstance(response.get('incomplete_details'), dict)
                                and response['incomplete_details'].get('reason') == 'max_output_tokens', 'sse_invalid_incomplete_reason')
                    else:
                        require(status == 'completed' and kind == 'response.completed', 'sse_invalid_terminal_status')
                    require(isinstance(response.get('id'), str) and bool(response['id']) and not response.get('error'), 'sse_invalid_terminal_identity_or_error')
                    answer = output_text(response)
                    require(not deltas or ''.join(deltas) == answer, 'sse_delta_final_mismatch')
                    terminal, final = kind, response
        data, event_name, begun = [], None, False
    require(not data and not begun and final is not None, 'sse_missing_terminal_or_truncated_frame')
    return {'response': final, 'terminal': terminal, 'event_count': events}


def expected_body(slot, responses):
    messages = []
    for dependency in slot.get('history_from', []):
        require(dependency in responses, 'request_history_missing_response')
        prior = responses[dependency]
        require(prior.get('issued') is True and prior.get('terminal_valid') is True
                and prior.get('model_outcome') == 'completed' and prior.get('error') is None, 'request_history_not_completed')
        messages.extend([{'role': 'user', 'content': prior['_slot']['input']},
                         {'role': 'assistant', 'content': prior['output_text']}])
    messages.append({'role': 'user', 'content': slot['input']})
    return {'model': slot['model'], 'instructions': slot['instructions'], 'input': messages,
            'max_output_tokens': slot['max_output_tokens'], 'temperature': slot.get('temperature', 0),
            'store': False, 'agentic_memory': False, 'tools': [], 'tool_choice': 'none', 'stream': True}


def verify_estimate(row, body):
    require(row.get('admission_policy') == POLICY, 'admission_policy_mismatch')
    est = row.get('admission_estimate'); require(isinstance(est, dict), 'missing_admission_estimate')
    count = integer(est.get('reference_input_tokens'))
    weighted = (5 * count + 3) // 4; weight = weighted + body['max_output_tokens']
    require(est.get('schema') == 'retrace.admission-estimate.v6f' and est.get('encoding') == 'cl100k_base'
            and est.get('tokenizer_version') == '0.14.0' and est.get('input_safety_multiplier') == '1.25'
            and est.get('quota_verified') is False and est.get('weighted_input_tokens') == weighted
            and est.get('requested_max_output_tokens') == body['max_output_tokens']
            and est.get('weight') == weight and 0 < weight <= 125000
            and est.get('solo_required') is (weight > 100000), 'admission_estimate_mismatch')


def audit_run(run_dir, slots, files, ledger):
    """Check one captured run. files supplies immutable captured journal bytes."""
    run_dir = Path(run_dir)
    manifest_rows = jsonl(files['run.json']); require(len(manifest_rows) == 1, 'invalid_run_manifest_count')
    manifest = manifest_rows[0]; rid = manifest['run_id']
    require(manifest.get('slots') == slots and manifest.get('sessions_sha256') == digest(slots), 'manifest_slots_mismatch')
    require(manifest.get('planned_slots') == len(slots) and manifest.get('models') == dict(Counter(s['model'] for s in slots)), 'manifest_plan_counts')
    bounds = {model: sum(bound(model, s['max_output_tokens']) for s in slots if s['model'] == model) for model in PRICES}
    require(manifest.get('full_plan_bound_by_model') == {model: credits(value) for model, value in bounds.items()}
            and manifest.get('full_plan_no_settlement_bound_credits') == credits(sum(bounds.values()))
            and manifest.get('historical_carry_credits') == BASELINE and manifest.get('cumulative_cap_credits') == '250', 'manifest_bound_or_carry_mismatch')
    require(manifest.get('schema') == 'retrace.adaption-v6f-plan.v1'
            and manifest.get('endpoint') == 'https://api.prod.adaptionlabs.ai/api/v1/responses'
            and manifest.get('stream') is True and manifest.get('store') is False
            and manifest.get('agentic_memory') is False and manifest.get('tools') is False
            and manifest.get('retries') == 0 and manifest.get('clock_test_hooks') is False
            and manifest.get('concurrency') == 5 and manifest.get('timeout_seconds') == 1200
            and manifest.get('model_interval_seconds') == 3.1 and manifest.get('global_interval_seconds') == 3.1
            and manifest.get('admission_policy') == POLICY, 'manifest_runtime_mismatch')
    for model, (inp, out, context) in PRICES.items():
        price = manifest['models_pricing'][model]
        require((price['input'], price['output'], price['context']) == (inp, out, context), 'manifest_pricing_mismatch')
    require(rid in ledger['runs'], 'run_without_ledger_start')
    run_ledger = ledger['runs'][rid]
    require(run_ledger['start']['sessions_sha256'] == digest(slots)
            and run_ledger['start']['planned'] == len(slots), 'ledger_run_schedule_mismatch')
    require(manifest.get('budget_before') == ledger['states'][run_ledger['prior_chain']], 'initial_run_budget_mismatch')
    slotmap = {s['slot_id']: s for s in slots}; require(len(slotmap) == len(slots), 'duplicate_scheduled_slot')
    requests, responses = jsonl(files['requests.jsonl']), jsonl(files['responses.jsonl'])
    reqmap, respmap = {}, {}
    response_positions = {r['slot_id']: i for i, r in enumerate(responses)}
    for row in responses:
        sid = row['slot_id']; require(sid in slotmap and sid not in respmap, 'duplicate_or_unknown_response')
        slot = slotmap[sid]
        require(row.get('run_id') == rid and all(row.get(k) == slot[k] for k in ('case_id', 'model', 'condition', 'phase')), 'response_identity_mismatch')
        respmap[sid] = dict(row, _slot=slot)
    for row in requests:
        sid = row['slot_id']; require(sid in slotmap and sid not in reqmap, 'duplicate_or_unknown_request')
        slot = slotmap[sid]; aid = rid + ':' + sid
        require(row['attempt_id'] == aid and aid in ledger['attempts'], 'request_without_exact_reservation')
        attempt = ledger['attempts'][aid]
        require(attempt['reserve']['slot_id'] == sid and attempt['reserve']['model'] == slot['model'], 'reservation_identity_mismatch')
        ceiling = bound(slot['model'], slot['max_output_tokens'])
        require(attempt['reserve']['bound_nanocredits'] == ceiling and nanocredits(row['reserved_credits']) == ceiling, 'reservation_bound_mismatch')
        body = expected_body(slot, respmap)
        require(row['request'] == body and row['request_sha256'] == digest(body), 'request_body_or_hash_mismatch')
        verify_estimate(row, body)
        for dep in slot.get('history_from', []):
            require(dep in reqmap and respmap[dep]['at'] <= row['at'], 'history_not_preceding_actual_request')
        reqmap[sid] = row
    provider_ids, pending_settlements, redacted, outcomes = [], [], [], Counter()
    for original in responses:
        sid = original['slot_id']; row = respmap[sid]; slot = slotmap[sid]
        if row.get('issued') is False:
            require(sid not in reqmap and rid + ':' + sid not in ledger['attempts'], 'unissued_dependency_was_reserved')
            blocked = [dep for dep in slot.get('history_from', []) if dep in respmap and respmap[dep].get('model_outcome') in ('truncated_max_output_tokens', 'not_issued_dependency_truncated')]
            require(bool(blocked) and row.get('blocked_dependencies') == blocked
                    and row.get('model_outcome') == 'not_issued_dependency_truncated'
                    and row.get('error') == 'history_dependency_truncated'
                    and row.get('terminal_valid') is False and row.get('response_status') is None
                    and row.get('output_text') == '', 'invalid_dependency_skip')
            require(all(response_positions[dep] < response_positions[sid] for dep in blocked), 'dependency_skip_precedes_cause')
            require(not any(k in row for k in ('attempt_id', 'reserved_credits', 'settled_credits', 'usage')), 'dependency_skip_has_usage_or_attempt')
            outcomes['dependency_skips'] += 1
            continue
        require(row.get('issued') is True and sid in reqmap and row.get('attempt_id') == rid + ':' + sid, 'issued_response_without_request')
        latency = row.get('latency_ms')
        require(type(latency) in (int, float) and math.isfinite(latency) and latency >= 0, 'invalid_response_latency')
        aid = row['attempt_id']; attempt = ledger['attempts'][aid]
        require(nanocredits(row['reserved_credits']) == attempt['reserve']['bound_nanocredits'], 'response_reservation_mismatch')
        meta = row.get('stream_evidence')
        if meta is not None:
            require(meta.get('closed') is True and meta.get('http_status') == row.get('http_status'), 'stream_metadata_not_closed_or_http_mismatch')
            name = sha(aid.encode()) + '.sse'
            require(Path(meta['raw_stream_path']).name == name, 'stream_filename_mismatch')
            stream = (run_dir / 'streams' / name).read_bytes()
            require(sha(stream) == meta['saved_sha256'], 'saved_stream_hash_mismatch')
            if meta.get('credential_redacted') is False:
                require(meta['received_bytes'] == len(stream) and meta['received_sha256'] == sha(stream), 'received_stream_hash_or_length_mismatch')
            else:
                require(meta.get('credential_redacted') is True and row.get('error') is not None, 'redacted_stream_claimed_success')
                redacted.append(sid)
        if row.get('error') is not None:
            require(row.get('terminal_valid') is False and row.get('model_outcome') == 'operational_failure'
                    and row.get('output_text') == '' and row.get('settled_credits') is None
                    and attempt['settle'] is None, 'operational_failure_settled_or_promoted')
            outcomes['operational_failures'] += 1
            continue
        require(meta is not None and row.get('http_status') == 200 and row.get('terminal_valid') is True, 'valid_terminal_without_stream')
        parsed = parse_sse(stream); response = parsed['response']
        require(canonical(response) == row.get('raw_response') and row.get('stream_terminal_event') == parsed['terminal']
                and row.get('stream_event_count') == parsed['event_count'], 'raw_terminal_binding_mismatch')
        require(response.get('model') == slot['model'] and response.get('status') == row.get('response_status')
                and response.get('usage') == row.get('usage'), 'terminal_model_status_usage_mismatch')
        provider_ids.append(response['id'])
        charge = cost(slot['model'], response['usage'], slot['max_output_tokens'])
        require(nanocredits(row['settled_credits']) == charge, 'reported_settlement_cost_mismatch')
        if response['status'] == 'completed':
            require(row.get('model_outcome') == 'completed' and row.get('output_text') == output_text(response)
                    and row.get('partial_output_text') == '', 'completed_text_mismatch')
            outcomes['completed'] += 1
        else:
            require(row.get('model_outcome') == 'truncated_max_output_tokens' and row.get('output_text') == ''
                    and row.get('partial_output_text') == output_text(response), 'truncation_promoted_or_partial_changed')
            outcomes['truncated'] += 1
        settlement = attempt['settle']
        if settlement is None:
            pending_settlements.append(sid)
        else:
            require(settlement.get('response_sha256') == digest(original)
                    and settlement.get('accounted_nanocredits') == charge
                    and settlement.get('model_outcome') == row['model_outcome']
                    and settlement.get('basis') == 'valid_terminal_reported_usage_uncached_no_double_reasoning', 'settlement_response_binding_mismatch')
    require(len(set(provider_ids)) == len(provider_ids), 'reused_provider_response_id')
    issued = [r['slot_id'] for r in requests]
    skips = [r['slot_id'] for r in responses if r.get('issued') is False]
    orphan_requests = [sid for sid in issued if sid not in respmap]
    missing = [s['slot_id'] for s in slots if s['slot_id'] not in reqmap and s['slot_id'] not in skips]
    reserved_orphans = [a['reserve']['slot_id'] for a in ledger['attempts'].values()
                        if a['reserve']['run_id'] == rid and a['reserve']['slot_id'] not in reqmap]
    for attempt in ledger['attempts'].values():
        if attempt['reserve']['run_id'] == rid and attempt['settle'] is not None:
            require(attempt['reserve']['slot_id'] in respmap, 'settled_attempt_without_response')
    for model in PRICES:
        observed = {sid for sid in reqmap if slotmap[sid]['model'] == model} | {sid for sid in skips if slotmap[sid]['model'] == model}
        queue = [s['slot_id'] for s in slots if s['model'] == model]
        require(observed == set(queue[:len(observed)]), 'model_queue_not_a_prefix')
        require([sid for sid in issued if slotmap[sid]['model'] == model] == [sid for sid in queue if sid in reqmap], 'model_request_order_changed')
    closed = files.get('summary.json') is not None and run_ledger['close'] is not None
    if files.get('summary.json') is not None:
        summaries = jsonl(files['summary.json']); require(len(summaries) == 1, 'invalid_summary_count')
        summary = summaries[0]
        require(run_ledger['close'] is not None, 'summary_without_ledger_close')
        close = run_ledger['close']
        expected = {'run_id': rid, 'planned': len(slots), 'issued': len(requests), 'responses': len(responses),
                    'schema': 'retrace.adaption-v6f-summary.v1', 'canary': manifest['canary'],
                    'models': dict(Counter(s['model'] for s in slots)), 'admission_policy': POLICY,
                    'completed': outcomes['completed'], 'truncated': outcomes['truncated'],
                    'issued_operational_failures': outcomes['operational_failures'], 'dependency_skips': len(skips),
                    'valid_terminal_records': outcomes['completed'] + outcomes['truncated'],
                    'issued_slot_ids': issued, 'dependency_skipped_slot_ids': skips,
                    'unissued_due_global_halt_slot_ids': missing, 'issued_without_outcome_slot_ids': orphan_requests,
                    'unissued_slot_ids': [s['slot_id'] for s in slots if s['slot_id'] not in reqmap],
                    'admission_starts': len(requests), 'retries': 0, 'stream': True,
                    'status': close['status'], 'budget': ledger['states'][run_ledger['close_chain']]}
        require(all(summary.get(k) == v for k, v in expected.items()) and close['issued'] == len(requests), 'closed_summary_count_or_budget_mismatch')
        require(summary.get('stop_reasons') == list(dict.fromkeys(e['reason'] for e in run_ledger['halts'])), 'summary_stop_reasons_mismatch')
        require(not pending_settlements or summary['status'] == 'stopped', 'completed_run_unsettled_terminal')
        if summary['status'] == 'completed':
            require(not missing and not orphan_requests and not reserved_orphans and not outcomes['operational_failures'], 'completed_run_has_missing_or_failed_dispatch')
    all_scheduled = len(responses) == len(slots) and not orphan_requests and not reserved_orphans
    return {'run_id': rid, 'final_closed': closed, 'dispatch_status': 'closed' if closed else 'incomplete_active_or_unclosed',
            'all_scheduled_outcomes_recorded': all_scheduled, 'planned': len(slots), 'issued': len(requests),
            'responses': len(responses), **{k: outcomes[k] for k in ('completed', 'truncated', 'operational_failures', 'dependency_skips')},
            'unissued_slot_count': len(missing), 'issued_without_response_count': len(orphan_requests),
            'reserved_without_request_count': len(reserved_orphans),
            'unissued_slot_ids': missing, 'issued_without_response_slot_ids': orphan_requests,
            'reserved_without_request_slot_ids': reserved_orphans, 'terminal_without_settlement_slot_ids': pending_settlements,
            'redacted_stream_original_hash_unverifiable_slot_ids': redacted, 'provider_response_ids': provider_ids,
            'request_attempt_ids': [row['attempt_id'] for row in requests],
            'source_sha256': {k: sha(v) for k, v in files.items() if v is not None}}


def within(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), 'manifest_path_outside_workspace')
    return path


def freeze_checks(root):
    raw = (root / FREEZE).read_bytes(); require(sha(raw) == FREEZE_SHA256, 'primary_freeze_changed')
    freeze = strict_json(raw); entries = freeze['files']; frozen = {}
    require(len(entries) == 619, 'primary_freeze_inventory_count')
    for entry in entries:
        path = entry['path']; require(path not in frozen, 'duplicate_frozen_path')
        require(sha(within(root, path).read_bytes()) == entry['sha256'], 'frozen_file_changed:' + path)
        frozen[path] = entry['sha256']
    protection = {}
    for path, count in [('data/v6-baseline-preservation.json', 402), ('data/frontier-v6f-authorization.json', 555)]:
        manifest = strict_json((root / path).read_bytes()); protected = manifest['protected']
        require(len(protected) == count, 'protected_inventory_count')
        for name, expected in protected.items():
            require(frozen.get(name) == expected and sha(within(root, name).read_bytes()) == expected, 'protected_hash_mismatch:' + name)
        protection[path] = count
    require(freeze['planned_slots'] == 4640 and freeze['primary_slots'] == 4560
            and freeze['development_regression_slots'] == 80, 'frozen_design_count_mismatch')
    return freeze, {'primary_freeze_sha256': sha(raw), 'frozen_files_verified': len(entries),
                    'v5_preserved_files_verified': 402, 'authorization_protected_files_verified': 555}


def capture(paths, attempts=3):
    """Two equal bounded reads; no lock, delay, retry of paid calls or writes."""
    def read(): return {str(p): p.read_bytes() if p.exists() else None for p in paths}
    for _ in range(attempts):
        first, second = read(), read()
        if first == second: return second
    return None


def audit_workspace(root=ROOT, require_closed=False):
    root = Path(root).resolve()
    freeze, evidence = freeze_checks(root)
    historical = '40.98826224'; prior_raw = (root / 'results/eligibility-v5-budget-final.json').read_bytes()
    require(strict_json(prior_raw)['current_conservative_reserved_credits'] == historical, 'v5_carry_mismatch')
    old = []
    for phase in ('v6c', 'v6d', 'v6e'):
        raw = (root / f'results/frontier-{phase}/budget/ledger.jsonl').read_bytes()
        replay = replay_ledger(raw, historical, sha(prior_raw))
        old.append({'phase': phase, 'sha256': sha(raw), 'snapshot': replay['snapshot']})
        historical = replay['snapshot']['accounted_credits']; prior_raw = raw
    require(nanocredits(historical) == nanocredits(BASELINE)
            and sum(r['snapshot']['unsettled_attempts'] for r in old) == 7, 'inherited_carry_or_unknowns_mismatch')
    ledger_path = root / 'results/frontier-v6f/budget/ledger.jsonl'
    run_dirs = {name: root / 'results/frontier-v6f' / name for name in ('canary', 'combined')}
    names = ('run.json', 'requests.jsonl', 'responses.jsonl', 'summary.json')
    paths = [ledger_path] + [p / name for p in run_dirs.values() for name in names]
    captured = capture(paths)
    if captured is None:
        require(not require_closed, 'final_closure_required_but_snapshot_changing')
        return {'schema': 'retrace.frontier-v6f-independent-run-audit.v1', 'status': 'incomplete_snapshot_changing',
                'integrity': 'not_fully_evaluated', 'final_closed': False, **evidence}
    live = captured[str(ledger_path)]
    require(live is not None, 'missing_live_ledger')
    prefix = (root / freeze['ledger_prefix_snapshot']).read_bytes()
    require(live.startswith(prefix), 'frozen_canary_ledger_prefix_changed')
    initial = replay_ledger(prefix, BASELINE, sha(prior_raw))
    require(initial['snapshot'] == freeze['initial_budget'], 'frozen_initial_budget_mismatch')
    # A writer caught between partial appends must not be mistaken for closure.
    if any(raw is not None and raw and not raw.endswith(b'\n') for raw in captured.values()):
        require(not require_closed, 'final_closure_required_but_snapshot_incomplete')
        return {'schema': 'retrace.frontier-v6f-independent-run-audit.v1', 'status': 'incomplete_snapshot_line',
                'integrity': 'not_fully_evaluated', 'final_closed': False, **evidence}
    ledger = replay_ledger(live, BASELINE, sha(prior_raw))
    results = {}
    for name, directory in run_dirs.items():
        files = {key: captured[str(directory / key)] for key in names}
        if files['run.json'] is None:
            require(name == 'combined', 'missing_frozen_canary_run')
            results[name] = {'final_closed': False, 'dispatch_status': 'not_started', 'all_scheduled_outcomes_recorded': False}
            continue
        require(files['requests.jsonl'] is not None and files['responses.jsonl'] is not None, 'missing_run_journals')
        session_name = 'canary' if name == 'canary' else 'combined'
        slots = strict_json((root / f'data/frontier-v6f-{session_name}-sessions.json').read_bytes())
        results[name] = audit_run(directory, slots, files, ledger)
    known_runs = {r['run_id'] for r in results.values() if 'run_id' in r}
    require(set(ledger['runs']) == known_runs, 'unrecognized_v6f_ledger_run')
    ids = [rid for result in results.values() for rid in result.pop('provider_response_ids', [])]
    require(len(ids) == len(set(ids)), 'provider_response_reused_across_runs')
    attempts = [aid for result in results.values() for aid in result.pop('request_attempt_ids', [])]
    require(len(attempts) == len(set(attempts)), 'duplicate_attempt_across_runs')
    final = all(r['final_closed'] for r in results.values())
    all_scheduled = all(r['all_scheduled_outcomes_recorded'] for r in results.values())
    if require_closed: require(final, 'final_closure_required_but_run_incomplete')
    return {'schema': 'retrace.frontier-v6f-independent-run-audit.v1',
            'status': 'passed_closed' if final else 'incomplete', 'integrity': 'passed_captured_evidence',
            'final_closed': final, 'all_scheduled_outcomes_recorded': all_scheduled,
            'captured_at_utc': datetime.now(timezone.utc).isoformat(), **evidence,
            'canary_ledger_prefix_sha256': sha(prefix), 'live_ledger_sha256': sha(live),
            'historical_ledgers': old, 'inherited_v6_unknown_attempts_retained': 7,
            'current_budget': ledger['snapshot'], 'runs': results,
            'scope': ['Read-only independent stdlib audit; no runner/scorer imports, API calls, credentials or output-file writes.',
                      'Passed integrity does not imply semantic success, complete dispatch, accurate source interpretation or a verified provider bill.',
                      'Request bodies and replayed assistant text are reconstructed exactly. One recorded attempt per slot is checked; unlogged external provider behavior cannot be ruled out.',
                      'SSE saved bytes and terminal/usage bindings are checked independently. HTTP metadata itself is a local journal assertion, not a separately signed provider receipt.',
                      'Admission arithmetic is verified from recorded reference counts; tokenizer counts and monotonic pacing clocks are not independently reproduced. No tokenizer or network dependency is loaded.',
                      'Redacted failed streams cannot independently authenticate original unredacted hashes; their saved bytes remain verifiable.',
                      'Active snapshots retain outstanding reservations and missing slots. Closed stopped runs may still be incomplete; inspect all_scheduled_outcomes_recorded.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--require-closed', action='store_true')
    parser.add_argument('--compact', action='store_true', help='Replace long unissued-ID lists with their count and canonical SHA256; full audit checks are unchanged.')
    args = parser.parse_args()
    try:
        result = audit_workspace(args.root, args.require_closed)
        if args.compact:
            for run in result.get('runs', {}).values():
                if 'unissued_slot_ids' in run:
                    run['unissued_slot_ids_sha256'] = digest(run.pop('unissued_slot_ids'))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (AuditError, OSError, KeyError, TypeError, ValueError) as exc:
        code = str(exc) if isinstance(exc, AuditError) else type(exc).__name__
        print(json.dumps({'schema': 'retrace.frontier-v6f-independent-run-audit.v1', 'status': 'failed', 'error': code}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
