import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, dirname, basename } from 'node:path';
import { ENDPOINT, planPilot, createPilotBudget, parseDecisions, runPilot } from '../scripts/run_adaption.mjs';

const KEY = 'test_only_secret_never_real_12345';
const model = 'gemma-4-31b-it';
const sessions = [{ case_id: 'case-1', family: 'alternate_support', condition: 'history',
  decision_ids: ['D1'], steps: [{ phase: 'before', input: 'first question' }, { phase: 'after', input: 'second question' }] }];
const options = { apiKey: KEY, model, sessions, instructions: 'Return only JSON decisions.', maxRequests: 2, minIntervalMs: 0 };
const response = (text, extra = {}) => ({ status: 200, ok: true,
  text: async () => JSON.stringify({ status: 'completed', model, output_text: text,
    usage: { input_tokens: 40, output_tokens: 10, total_tokens: 50 }, ...extra }) });
async function withDir(fn) {
  const directory = await mkdtemp(join(tmpdir(), 'retrace-runner-test-'));
  try { await fn(directory); } finally {
    const target = resolve(directory);
    if (dirname(target) !== resolve(tmpdir()) || !basename(target).startsWith('retrace-runner-test-')) throw new Error('invalid_test_cleanup_target');
    await rm(target, { recursive: true, force: true });
  }
}
async function lines(directory, file = 'responses.jsonl') {
  return (await readFile(join(directory, file), 'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse);
}

test('strict decisions reject coercion, Markdown, unknown IDs, extra fields and duplicate keys', () => {
  assert.equal(parseDecisions('{"decisions":{"D1":true}}', ['D1']).status, 'valid');
  for (const text of ['```json\n{"decisions":{"D1":true}}\n```', '{"decisions":{"D1":1}}',
    '{"decisions":{"D2":true}}', '{"decisions":{"D1":true},"explanation":"x"}',
    '{"decisions":{"D1":true,"D1":false}}', '{"decisions":{}}']) {
    assert.equal(parseDecisions(text, ['D1']).status, 'invalid');
  }
});

test('planning fails closed on unpriced models, stacks, output caps and excess requests', () => {
  const plan = planPilot({ model, sessions, maxRequests: 2, maxOutputTokens: 1200 });
  assert.equal(plan.planned_requests, 2);
  assert.equal(plan.max_reserved_credits, 2 * ((256000 * .09 + 1200 * .34) / 1e6));
  assert.throws(() => planPilot({ model: 'stack:any', sessions }), /unpriced/);
  assert.throws(() => planPilot({ model, sessions, maxOutputTokens: 8193 }), /output_token/);
  const larger = planPilot({ model, sessions, maxRequests: 2, maxOutputTokens: 8192 });
  assert.ok(larger.max_reserved_credits > plan.max_reserved_credits);
  assert.equal(larger.max_output_tokens, 8192);
  assert.throws(() => planPilot({ model, sessions, maxRequests: 1 }), /exceed/);
  assert.throws(() => createPilotBudget({ maxCredits: 51 }), /credit_cap/);
});

test('session-specific extraction instructions are journaled and graph validation is explicitly deferred', async () => withDir(async directory => {
  const graphSessions = [{...sessions[0], response_kind:'graph', instructions:'Extract the evidence graph.',
    steps:[{phase:'final',input:'A fictional packet'}]}];
  let sent;
  const summary = await runPilot({...options,sessions:graphSessions,maxRequests:1,outputDir:directory,
    fetchImpl:async (_url,init)=>{sent=JSON.parse(init.body);return response('{"evidence":[],"claims":[],"decisions":[]}');}});
  assert.equal(sent.instructions,'Extract the evidence graph.');
  assert.equal(summary.deferred_graph_responses,1);
  assert.equal(summary.invalid_or_failed_responses,0);
  assert.equal(summary.valid_responses,0);
  const records=await lines(directory);
  assert.equal(records[0].parsing.status,'deferred_graph_validation');
  assert.equal(records[0].response_kind,'graph');
  await assert.rejects(runPilot({...options,sessions:[{...graphSessions[0],instructions:KEY}],outputDir:join(directory,'leak')}),/credential_in_pilot_data/);
}));

test('replays actual assistant output with fresh session isolation and no credentials in journals', async () => withDir(async directory => {
  const seen = [];
  const combined = [...sessions, { ...sessions[0], case_id: 'case-2', steps: [{ phase: 'snapshot', input: 'third question' }] }];
  const summary = await runPilot({ ...options, sessions: combined, maxRequests: 3, concurrency: 1, outputDir: directory,
    fetchImpl: async (url, init) => {
      assert.equal(url, ENDPOINT); assert.equal(init.redirect, 'error');
      assert.equal(init.headers.Authorization, `Bearer ${KEY}`);
      const body = JSON.parse(init.body); seen.push(body);
      assert.equal(body.store, false); assert.equal(body.agentic_memory, false);
      assert.equal(body.tool_choice, 'none'); assert.deepEqual(body.tools, []);
      return response(seen.length === 1 ? '{"decisions":{"D1":false}}' : '{"decisions":{"D1":true}}');
    } });
  assert.equal(summary.issued_requests, 3); assert.equal(summary.valid_responses, 3);
  assert.equal(seen[1].input[1].role, 'assistant');
  assert.equal(seen[1].input[1].content, '{"decisions":{"D1":false}}');
  assert.equal(seen[2].input.length, 1);
  assert.equal((await lines(directory, 'requests.jsonl')).length, 3);
  for (const file of await readdir(directory)) assert.equal((await readFile(join(directory, file), 'utf8')).includes(KEY), false);
}));

test('shared budget reserves complete plans across runs and rejects excess before fetch', async () => withDir(async directory => {
  const plan = planPilot({ model, sessions, maxRequests: 2 });
  const budget = createPilotBudget({ maxCredits: plan.max_reserved_credits + .000001, maxRequests: 4 });
  let calls = 0;
  const fetchImpl = async () => { calls++; return response('{"decisions":{"D1":true}}'); };
  await runPilot({ ...options, outputDir: join(directory, 'one'), budget, fetchImpl });
  await assert.rejects(runPilot({ ...options, outputDir: join(directory, 'two'), budget, fetchImpl }), /credit_cap_would_be_exceeded/);
  assert.equal(calls, 2);
  assert.equal(budget.snapshot().reserved_requests, 2);
}));

test('request cap is shared and counted upfront even when first request fails', async () => withDir(async directory => {
  const budget = createPilotBudget({ maxRequests: 2 }); let calls = 0;
  const fetchImpl = async () => { calls++; throw new Error(`private header ${KEY}`); };
  const result = await runPilot({ ...options, concurrency: 1, outputDir: join(directory, 'one'), budget, fetchImpl });
  assert.equal(result.status, 'halted'); assert.equal(result.issued_requests, 1);
  assert.equal(result.unissued_requests, 1); assert.equal(budget.snapshot().reserved_requests, 2);
  const records = await lines(join(directory, 'one'));
  assert.equal(records[0].error, 'network_or_redirect_error'); assert.equal(records[0].raw_response, null);
  await assert.rejects(runPilot({ ...options, outputDir: join(directory, 'two'), budget, fetchImpl }), /request_cap_would_be_exceeded/);
  assert.equal(calls, 1);
}));

test('never retries HTTP errors, records raw response and halts later turns', async () => withDir(async directory => {
  let calls = 0;
  const summary = await runPilot({ ...options, outputDir: directory, fetchImpl: async () => {
    calls++; return { ok: false, status: 429, text: async () => '{"error":"rate limited"}' };
  } });
  assert.equal(calls, 1); assert.equal(summary.halt_reason, 'http_error');
  const records = await lines(directory);
  assert.equal(records[0].raw_response, '{"error":"rate limited"}');
  assert.equal(records[0].parsing.status, 'not_parsed');
}));

test('invalid answer is preserved into subsequent turn without repair calls', async () => withDir(async directory => {
  const seen = [];
  const result = await runPilot({ ...options, outputDir: directory, fetchImpl: async (url, init) => {
    seen.push(JSON.parse(init.body)); return response(seen.length === 1 ? 'not JSON' : '{"decisions":{"D1":true}}');
  } });
  assert.equal(seen.length, 2); assert.equal(seen[1].input[1].content, 'not JSON');
  assert.equal(result.invalid_or_failed_responses, 1); assert.equal(result.valid_responses, 1);
}));

test('no more than two sessions in flight; individual session steps remain serial', async () => withDir(async directory => {
  let active = 0, maximum = 0;
  const many = Array.from({ length: 4 }, (_, i) => ({ ...sessions[0], case_id: `case-${i}` }));
  const result = await runPilot({ ...options, sessions: many, maxRequests: 8, outputDir: directory,
    fetchImpl: async () => {
      active++; maximum = Math.max(maximum, active);
      await new Promise(resolve => setTimeout(resolve, 5)); active--;
      return response('{"decisions":{"D1":true}}');
    } });
  assert.equal(result.issued_requests, 8); assert.equal(maximum, 2);
  const records = await lines(directory);
  for (const session of many) assert.deepEqual(records.filter(x => x.case_id === session.case_id).map(x => x.step_index), [0, 1]);
}));

test('credential echo is scrubbed and halts; secret cannot enter prompt', async () => withDir(async directory => {
  const result = await runPilot({ ...options, outputDir: join(directory, 'echo'), fetchImpl: async () => response(KEY) });
  assert.equal(result.halt_reason, 'credential_echo_detected');
  const records = await lines(join(directory, 'echo'));
  assert.equal(records[0].raw_response_redacted, true);
  for (const file of await readdir(join(directory, 'echo'))) assert.equal((await readFile(join(directory, 'echo', file), 'utf8')).includes(KEY), false);
  await assert.rejects(runPilot({ ...options, instructions: KEY, outputDir: join(directory, 'prompt'), fetchImpl: async () => { throw new Error('must not execute'); } }), /credential_in_pilot_data/);
}));

test('existing run cannot be silently overwritten or resumed', async () => withDir(async directory => {
  let calls = 0; const fetchImpl = async () => { calls++; return response('{"decisions":{"D1":true}}'); };
  await runPilot({ ...options, outputDir: directory, fetchImpl });
  await assert.rejects(runPilot({ ...options, outputDir: directory, fetchImpl }), /run_exists/);
  assert.equal(calls, 2);
}));

test('global pacing spaces dispatch across different concurrent sessions', async () => withDir(async directory => {
  const starts = [];
  const many = Array.from({ length: 4 }, (_, i) => ({ ...sessions[0], case_id: `paced-${i}`, steps: [sessions[0].steps[0]] }));
  const result = await runPilot({ ...options, sessions: many, maxRequests: 4, concurrency: 2,
    minIntervalMs: 30, outputDir: directory, fetchImpl: async () => {
      starts.push(performance.now());
      await new Promise(resolve => setTimeout(resolve, 40));
      return response('{"decisions":{"D1":true}}');
    } });
  assert.equal(result.issued_requests, 4);
  for (let i = 1; i < starts.length; i++) assert.ok(starts[i] - starts[i - 1] >= 29, 'dispatch must honor global interval');
  assert.equal(JSON.parse(await readFile(join(directory, 'run.json'), 'utf8')).min_interval_ms, 30);
}));

test('incomplete responses and reported token-bound violations halt without retry', async () => withDir(async directory => {
  const incomplete = await runPilot({ ...options, outputDir: join(directory, 'incomplete'),
    fetchImpl: async () => response('', { status: 'incomplete', incomplete_details: { reason: 'max_output_tokens' } }) });
  assert.equal(incomplete.issued_requests, 1);
  assert.equal(incomplete.halt_reason, 'response_not_completed');
  const exceeded = await runPilot({ ...options, outputDir: join(directory, 'exceeded'),
    fetchImpl: async () => response('{"decisions":{"D1":true}}', { usage: { input_tokens: 10, output_tokens: 1201 } }) });
  assert.equal(exceeded.halt_reason, 'documented_token_bound_exceeded');
  assert.equal(exceeded.valid_responses, 0);
}));

