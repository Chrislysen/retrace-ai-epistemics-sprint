/** Adaption-only, no-retry pilot runner. Credentials stay in caller memory. */
import { mkdir, open, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

export const ENDPOINT = 'https://api.prod.adaptionlabs.ai/api/v1/responses';
export const PRICING_SOURCE = 'https://docs.adaptionlabs.ai/inference-stacks/models/';
export const PRICING_VERIFIED = '2026-11-13';
export const MODEL_PRICING = Object.freeze(Object.fromEntries(Object.entries({
  'gemma-4-31b-it': [0.09, 0.34, 256000],
  'glm-5.2': [1.40, 4.40, 786432],
  'qwen3.5-397b': [0.55, 3.50, 131072],
  'gemma-4-26b-a4b-it': [0.0765, 0.255, 256000],
  'qwen3.8-27b': [0.039, 1.25, 262144],
  'deepseek-v4-flash': [0.04444, 0.13332, 1048576],
  'glm-53-flash': [0.15, 0.50, 1048576],
}).map(([id, [input, output, context]]) => [id, Object.freeze({ input, output, context })])));

const budgets = new WeakMap();
const credits = n => n / 1e9;
const sha256 = text => createHash('sha256').update(text).digest('hex');
const fail = code => { throw new Error(code); };
function integer(value, min, max, code) {
  if (!Number.isSafeInteger(value) || value < min || value > max) fail(code);
}

/** Share this one object across all model runs in the approved pilot. */
export function createPilotBudget({ maxCredits = 50, maxRequests = 1000 } = {}) {
  if (!Number.isFinite(maxCredits) || maxCredits <= 0 || maxCredits > 50) fail('invalid_credit_cap');
  integer(maxRequests, 1, 10000, 'invalid_request_cap');
  const state = { cap: Math.floor(maxCredits * 1e9), maxRequests, reserved: 0, requests: 0 };
  const budget = Object.freeze({ snapshot: () => ({
    max_credits: credits(state.cap), max_requests: state.maxRequests,
    reserved_credits: credits(state.reserved), reserved_requests: state.requests,
    remaining_credits: credits(state.cap - state.reserved),
  }) });
  budgets.set(budget, state);
  return budget;
}

function reserve(budget, plan) {
  const state = budgets.get(budget);
  if (!state) fail('invalid_shared_budget');
  const amount = plan.reserve_nanocredits_per_request * plan.planned_requests;
  if (state.reserved + amount > state.cap) fail('credit_cap_would_be_exceeded');
  if (state.requests + plan.planned_requests > state.maxRequests) fail('request_cap_would_be_exceeded');
  state.reserved += amount;
  state.requests += plan.planned_requests;
}

export function planPilot({ model, sessions, maxRequests = 100, maxOutputTokens = 1200 }) {
  if (!Object.hasOwn(MODEL_PRICING, model)) fail('unpriced_or_nonhosted_model');
  integer(maxRequests, 1, 10000, 'invalid_request_cap');
  integer(maxOutputTokens, 1, 8192, 'invalid_output_token_cap');
  if (!Array.isArray(sessions) || !sessions.length) fail('invalid_sessions');
  const identities = new Set();
  let count = 0;
  for (const session of sessions) {
    if (!session || ['case_id', 'family', 'condition'].some(k => typeof session[k] !== 'string' || !session[k])) fail('invalid_session_identity');
    const identity = JSON.stringify([session.case_id, session.condition]);
    if (identities.has(identity)) fail('duplicate_session');
    identities.add(identity);
    if (session.instructions !== undefined && (typeof session.instructions !== 'string' || !session.instructions.trim())) fail('invalid_session_instructions');
    if (session.response_kind !== undefined && !['decisions', 'graph'].includes(session.response_kind)) fail('invalid_response_kind');
    if (!Array.isArray(session.steps) || !session.steps.length) fail('invalid_steps');
    for (const step of session.steps) {
      if (!step || typeof step.phase !== 'string' || !step.phase || typeof step.input !== 'string' || !step.input) fail('invalid_step');
      const ids = step.decision_ids ?? session.decision_ids;
      if (ids !== undefined && (!Array.isArray(ids) || !ids.length || ids.some(x => typeof x !== 'string' || !x) || new Set(ids).size !== ids.length)) fail('invalid_decision_ids');
      count++;
    }
  }
  if (count > maxRequests) fail('planned_requests_exceed_cap');
  const price = MODEL_PRICING[model];
  // Reserve the ENTIRE model context at the uncached input rate, regardless of
  // actual prompt size, plus maximum generation. No tokenizer estimate or refunds.
  const bound = Math.ceil(price.context * price.input * 1000 + maxOutputTokens * price.output * 1000);
  return {
    model, session_count: sessions.length, planned_requests: count,
    max_requests: maxRequests, max_output_tokens: maxOutputTokens,
    pricing: price, pricing_source: PRICING_SOURCE, pricing_verified: PRICING_VERIFIED,
    reserve_method: 'full_context_uncached_input_plus_max_output_no_refunds',
    reserve_nanocredits_per_request: bound,
    reserved_credits_per_request: credits(bound), max_reserved_credits: credits(bound * count),
  };
}

/** No Markdown extraction, coercion, answer repair, or model-based grading. */
export function parseDecisions(text, expectedIds) {
  const invalid = reason => ({ status: 'invalid', reason, decisions: null });
  if (typeof text !== 'string' || !text.trim()) return invalid('empty_output');
  let value;
  try { value = JSON.parse(text); } catch { return invalid('not_strict_json'); }
  if (!value || Array.isArray(value) || typeof value !== 'object' || Object.keys(value).length !== 1 || !Object.hasOwn(value, 'decisions')) return invalid('invalid_top_level');
  const decisions = value.decisions;
  if (!decisions || Array.isArray(decisions) || typeof decisions !== 'object' || !Object.keys(decisions).length || Object.values(decisions).some(v => typeof v !== 'boolean')) return invalid('invalid_decisions');
  // With boolean-only values, all string-colon tokens are object keys.
  const keys = [...text.matchAll(/"(?:[^"\\]|\\.)*"\s*:/g)].map(m => JSON.parse(m[0].replace(/\s*:\s*$/, '')));
  if (keys.length !== Object.keys(decisions).length + 1) return invalid('duplicate_keys');
  if (expectedIds && (expectedIds.length !== Object.keys(decisions).length || expectedIds.some(id => !Object.hasOwn(decisions, id)))) return invalid('decision_ids_mismatch');
  return { status: 'valid', reason: null, decisions };
}

function responseText(response) {
  if (typeof response?.output_text === 'string') return response.output_text;
  if (!Array.isArray(response?.output)) return '';
  return response.output.filter(x => x?.type === 'message' && x.role === 'assistant')
    .flatMap(x => Array.isArray(x.content) ? x.content : [])
    .filter(x => x?.type === 'output_text' && typeof x.text === 'string')
    .map(x => x.text).join('');
}

function usageCost(usage, price) {
  if (!usage || !Number.isSafeInteger(usage.input_tokens) || usage.input_tokens < 0 || !Number.isSafeInteger(usage.output_tokens) || usage.output_tokens < 0) return null;
  // Conservative observed token cost: ignores any cache discount.
  return (usage.input_tokens * price.input + usage.output_tokens * price.output) / 1e6;
}

/** No CLI/key environment lookup: call from the parent's persistent Node session. */
export async function runPilot({
  apiKey, model, sessions, instructions, outputDir, maxRequests = 100,
  maxOutputTokens = 1200, concurrency = 2, timeoutMs = 120000,
  minIntervalMs = 3100, maxCredits = 50, budget, fetchImpl = globalThis.fetch,
}) {
  const plan = planPilot({ model, sessions, maxRequests, maxOutputTokens });
  integer(concurrency, 1, 2, 'invalid_concurrency');
  integer(timeoutMs, 1, 300000, 'invalid_timeout');
  integer(minIntervalMs, 0, 60000, 'invalid_dispatch_interval');
  if (typeof apiKey !== 'string' || apiKey.length < 8 || /\s/.test(apiKey)) fail('invalid_credential');
  if (typeof instructions !== 'string' || !instructions.trim()) fail('missing_instructions');
  if (typeof outputDir !== 'string' || !outputDir || typeof fetchImpl !== 'function') fail('invalid_configuration');
  const sessionJson = JSON.stringify(sessions);
  if ([sessionJson, instructions, outputDir, model].some(s => s.includes(apiKey) || s.includes(JSON.stringify(apiKey).slice(1, -1)))) fail('credential_in_pilot_data');
  sessions = JSON.parse(sessionJson); // Freeze the submitted protocol against caller mutation.
  const shared = budget ?? createPilotBudget({ maxCredits, maxRequests });
  if (!budgets.has(shared)) fail('invalid_shared_budget');
  const before = shared.snapshot();
  const directory = resolve(outputDir);
  try { await mkdir(directory, { recursive: true }); } catch { fail('output_directory_unavailable'); }
  // Exclusive files prevent silent overwrites or accidental paid resumption.
  let manifestFile, requestsFile, responsesFile;
  try {
    manifestFile = await open(join(directory, 'run.json'), 'wx');
    requestsFile = await open(join(directory, 'requests.jsonl'), 'wx');
    responsesFile = await open(join(directory, 'responses.jsonl'), 'wx');
  } catch {
    await Promise.allSettled([manifestFile?.close(), requestsFile?.close(), responsesFile?.close()]);
    fail('output_files_unavailable_or_run_exists');
  }
  const runId = randomUUID();
  const started = new Date().toISOString();
  let halted = null, issued = 0, completed = 0, valid = 0, deferred = 0, observedCost = 0, unknownUsage = 0;
  let nextSession = 0;
  let writes = Promise.resolve();
  let dispatchQueue = Promise.resolve();
  let lastDispatchAt = null;
  const scrub = text => text.split(apiKey).join('[REDACTED_CREDENTIAL]')
    .split(JSON.stringify(apiKey).slice(1, -1)).join('[REDACTED_CREDENTIAL]');
  const append = (file, record) => {
    const line = scrub(JSON.stringify(record)) + '\n';
    writes = writes.then(async () => { await file.write(line); await file.sync(); });
    return writes;
  };
  // One start-time gate for ALL sessions in this run, independent of concurrency.
  const dispatchSlot = prepare => {
    const slot = dispatchQueue.then(async () => {
      if (halted) return false;
      if (lastDispatchAt !== null) {
        let remaining;
        while ((remaining = lastDispatchAt + minIntervalMs - performance.now()) > 0) {
          await new Promise(resolve => setTimeout(resolve, Math.ceil(remaining)));
        }
      }
      if (halted) return false;
      await prepare();
      lastDispatchAt = performance.now();
      return true;
    });
    dispatchQueue = slot.catch(() => {});
    return slot;
  };
  try {
    reserve(shared, plan); // Entire plan counted before ANY network request.
    await manifestFile.writeFile(scrub(JSON.stringify({
      schema: 'retrace-adaption-pilot-v1', run_id: runId, started_at: started,
      endpoint: ENDPOINT, ...plan, concurrency, timeout_ms: timeoutMs,
      min_interval_ms: minIntervalMs,
      budget_before: before, budget_after_reservation: shared.snapshot(),
      instructions, sessions_sha256: sha256(sessionJson),
      sessions: sessions.map(s => ({ case_id: s.case_id, family: s.family, condition: s.condition, phases: s.steps.map(x => x.phase) })),
      actual_prior_assistant_text_replayed: true, retries: 0,
      tools: false, store: false, agentic_memory: false,
    }, null, 2)) + '\n');
    await manifestFile.sync();

    async function worker() {
      while (!halted) {
        const index = nextSession++;
        if (index >= sessions.length) return;
        const session = sessions[index];
        const messages = [];
        for (let stepIndex = 0; stepIndex < session.steps.length; stepIndex++) {
          if (halted) return;
          const step = session.steps[stepIndex];
          messages.push({ role: 'user', content: step.input });
          const request = {
            model, instructions: session.instructions ?? instructions, input: messages.map(m => ({ ...m })),
            max_output_tokens: maxOutputTokens, temperature: 0,
            store: false, agentic_memory: false, tools: [], tool_choice: 'none',
          };
          const identity = { run_id: runId, model,
            case_id: session.case_id, family: session.family, condition: session.condition,
            response_kind: session.response_kind ?? 'decisions',
            session_index: index, step_index: stepIndex, phase: step.phase };
          const requestBody = JSON.stringify(request);
          const dispatchAllowed = await dispatchSlot(async () => {
            identity.request_number = ++issued;
            await append(requestsFile, { ...identity, started_at: new Date().toISOString(),
              request, request_sha256: sha256(requestBody),
              reserved_credits: plan.reserved_credits_per_request });
          });
          if (!dispatchAllowed) return;
          const clock = performance.now();
          let raw = null, parsedResponse = null, error = null, httpStatus = null;
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), timeoutMs);
          try {
            const result = await fetchImpl(ENDPOINT, { method: 'POST', redirect: 'error',
              headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
              body: requestBody, signal: controller.signal });
            httpStatus = result.status;
            raw = await result.text();
            if (!result.ok) error = 'http_error';
            else {
              try { parsedResponse = JSON.parse(raw); } catch { error = 'non_json_response'; }
              if (!error && parsedResponse?.status !== 'completed') error = 'response_not_completed';
            }
          } catch {
            error = controller.signal.aborted ? 'timeout' : 'network_or_redirect_error';
          } finally { clearTimeout(timer); }
          const rawRedacted = typeof raw === 'string' && scrub(raw) !== raw;
          if (rawRedacted) error = 'credential_echo_detected';
          const usage = parsedResponse?.usage ?? null;
          const tokenCost = usageCost(usage, MODEL_PRICING[model]);
          if (tokenCost === null) unknownUsage++; else observedCost += tokenCost;
          const breach = tokenCost !== null && (usage.input_tokens > MODEL_PRICING[model].context || usage.output_tokens > maxOutputTokens);
          if (breach) error = 'documented_token_bound_exceeded';
          const outputText = error ? '' : responseText(parsedResponse);
          const parsing = error ? { status: 'not_parsed', reason: error, decisions: null }
            : session.response_kind === 'graph' ? { status: 'deferred_graph_validation', reason: null, decisions: null }
            : parseDecisions(outputText, step.decision_ids ?? session.decision_ids);
          if (error) halted = error;
          completed++;
          if (parsing.status === 'valid') valid++;
          if (parsing.status === 'deferred_graph_validation') deferred++;
          await append(responsesFile, { ...identity, finished_at: new Date().toISOString(),
            request, request_sha256: sha256(requestBody), latency_ms: Math.round(performance.now() - clock),
            http_status: httpStatus, raw_response: raw, raw_response_redacted: rawRedacted,
            response_status: parsedResponse?.status ?? null, response_model: parsedResponse?.model ?? null,
            usage, observed_token_cost_credits_uncached: tokenCost,
            output_text: outputText, parsing, error });
          if (error) return;
          // Preserve the actual response, even when its answer schema is invalid.
          // Do not inject reference answers, repair prompts or fabricated completions.
          messages.push({ role: 'assistant', content: outputText });
        }
      }
    }
    const outcomes = await Promise.allSettled(Array.from({ length: Math.min(concurrency, sessions.length) }, worker));
    if (outcomes.some(x => x.status === 'rejected')) halted = 'journal_or_worker_error';
    await writes;
    const summary = {
      schema: 'retrace-adaption-pilot-summary-v1', run_id: runId,
      started_at: started, finished_at: new Date().toISOString(), model,
      planned_requests: plan.planned_requests, issued_requests: issued,
      recorded_responses: completed, valid_responses: valid,
      deferred_graph_responses: deferred,
      invalid_or_failed_responses: completed - valid - deferred,
      unissued_requests: plan.planned_requests - issued,
      status: halted ? 'halted' : 'completed', halt_reason: halted,
      max_reserved_credits: plan.max_reserved_credits,
      observed_token_cost_credits_uncached: observedCost, responses_missing_usage: unknownUsage,
      actual_billed_credits: null, budget: shared.snapshot(), output_dir: directory,
    };
    await writeFile(join(directory, 'summary.json'), scrub(JSON.stringify(summary, null, 2)) + '\n', { flag: 'wx' });
    return summary;
  } catch (error) {
    // Only our small constant diagnostic codes may escape; no raw fetch/fs errors.
    if (['credit_cap_would_be_exceeded', 'request_cap_would_be_exceeded'].includes(error?.message)) throw error;
    fail('pilot_io_or_execution_error');
  } finally {
    await Promise.allSettled([manifestFile.close(), requestsFile.close(), responsesFile.close()]);
  }
}
