/**
 * Runner for the extension of the scaling run, under prereg/scale_extension_rules.md.
 * Sprint addition, written with AI assistance on Monday 16 November 2026.
 *
 *   node post_sweep/run_scale_ext.mjs <model> --part <name> --sessions <file under post_sweep/out/scale> [--stream]
 *
 * It sends the same request body as the project's first-day runner (scripts/run_adaption.mjs: same endpoint,
 * temperature 0, no tools, nothing stored) and writes journals in the same format as post_sweep/run_scale_v2.mjs, from
 * which it is copied. Differences: the sessions file and the output folder are arguments; models without a reasoning
 * phase keep the output limit of 8,192 tokens and the others 32,768; with --stream the request asks for a streamed
 * response (as the sweep's own transport did) and the final response object is taken from the terminal stream event.
 * Nothing is retried except a request rejected with HTTP 429 (after 65 s, at most twice). A session issued in an earlier
 * segment of the same part is not issued again. The credential is held in memory only and is never written or printed.
 */
import { appendFile, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const first = await import(pathToFileURL(join(ROOT, 'scripts', 'run_adaption.mjs')).href);
const NO_REASONING = ['gemma-4-31b-it', 'gemma-4-26b-a4b-it'];
const MODELS = [...NO_REASONING, 'qwen3.8-27b', 'deepseek-v4-flash', 'glm-53-flash'];
const STOP_AT_DEFAULT = new Date('2026-11-16T09:15:00+01:00');
// Part E6 (prereg/scale_extension_addendum_4.md): the second model on the search task. It starts after every other part
// has stopped and has a stop of its own. Every other part keeps the stop above.
const STOP_AT_E6 = new Date('2026-11-16T09:50:00+01:00');
const E6 = { model: 'gemma-4-26b-a4b-it', parts: ['withdrawal_answer', 'withdrawal_working'] };
// Parts E7 and E8 (prereg/scale_extension_addendum_5.md): a second run and 80-record cases, for the two Gemma models.
const STOP_AT_E78 = new Date('2026-11-16T11:15:00+01:00');
const isE78 = name => /^(repeat|xl)/.test(name);
const REQUEST_CEILING = 1000;         // all parts of the extension together, rejected requests included (900 until addendum 5)
const RESERVATION_CEILING = 80;       // credits, all parts of the extension together
const sha256 = text => createHash('sha256').update(text).digest('hex');
const sleep = ms => new Promise(done => setTimeout(done, ms));

const args = process.argv.slice(2);
const model = args[0];
const option = name => args.includes(name) ? args[args.indexOf(name) + 1] : null;
const part = option('--part');
const sessionsFile = option('--sessions');
const stream = args.includes('--stream');
if (!MODELS.includes(model) || !part || !/^[a-z0-9_]+$/.test(part) || !sessionsFile) {
  console.log('usage: node post_sweep/run_scale_ext.mjs <' + MODELS.join('|') + '> --part <name> --sessions <file> [--stream]');
  process.exit(2);
}
const STOP_AT = model === E6.model && E6.parts.includes(part) ? STOP_AT_E6
  : (isE78(part) && NO_REASONING.includes(model) ? STOP_AT_E78 : STOP_AT_DEFAULT);
const SETTINGS = { maxOutputTokens: NO_REASONING.includes(model) ? 8192 : 32768, concurrency: 2, timeoutMs: 300000,
  minIntervalMs: 3100, maxConsecutiveErrors: 5, stream };
const price = first.MODEL_PRICING[model];
const reservePerRequest = Math.ceil(price.context * price.input * 1000 + SETTINGS.maxOutputTokens * price.output * 1000) / 1e9;

async function credential() {
  const file = join(ROOT, 'secrets.local.env');
  if (existsSync(file)) {
    const line = (await readFile(file, 'utf8')).split(/\r?\n/).find(l => /^\s*ADAPTION_API_KEY\s*=/.test(l));
    if (line) return { key: line.slice(line.indexOf('=') + 1).trim().replace(/^["']|["']$/g, ''), source: 'secrets.local.env' };
  }
  if (process.env.ADAPTION_API_KEY) return { key: process.env.ADAPTION_API_KEY.trim(), source: 'environment variable' };
  const record = process.env.RETRACE_SESSION_RECORD;
  if (record && existsSync(record)) {
    const found = (await readFile(record, 'utf8')).match(/pt_live_[0-9a-f]{24,}/g);
    if (found) return { key: found[found.length - 1], source: 'session record' };
  }
  return null;
}

function responseText(response) {   // as in the first-day runner
  if (typeof response?.output_text === 'string') return response.output_text;
  if (!Array.isArray(response?.output)) return '';
  return response.output.filter(x => x?.type === 'message' && x.role === 'assistant')
    .flatMap(x => Array.isArray(x.content) ? x.content : [])
    .filter(x => x?.type === 'output_text' && typeof x.text === 'string')
    .map(x => x.text).join('');
}

/** A streamed answer: the events are counted, the text deltas are joined, and the terminal event carries the response. */
function readStream(raw) {
  let events = 0, terminal = null, deltas = '', data = [];
  const frame = () => {   // one event: its data lines joined, as in the sweep's own decoder (retrace/adaption_v6h.py)
    const payload = data.join('\n');
    data = [];
    if (!payload || payload === '[DONE]') return;
    let event;
    try { event = JSON.parse(payload); } catch { return; }
    events++;
    if (event?.type === 'response.output_text.delta' && typeof event.delta === 'string') deltas += event.delta;
    if (['response.completed', 'response.incomplete', 'response.failed'].includes(event?.type) && event.response) terminal = event;
  };
  for (const line of raw.split(/\r\n|\n|\r/)) {
    if (line === '') { frame(); continue; }
    if (line.startsWith(':')) continue;
    const cut = line.indexOf(':');
    const field = cut < 0 ? line : line.slice(0, cut);
    let value = cut < 0 ? '' : line.slice(cut + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'data') data.push(value);
  }
  frame();
  return { events, terminal, deltas };
}

async function journal(folder, name) {
  const file = join(folder, name);
  if (!existsSync(file)) return [];
  return (await readFile(file, 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
}

const sessionsText = await readFile(join(ROOT, 'post_sweep', 'out', 'scale', sessionsFile), 'utf8');
const manifest = JSON.parse(sessionsText);
const extension = join(ROOT, 'post_sweep', 'out', 'scale', 'ext');
const base = join(extension, part, model);
const found = await credential();
if (!found) { console.log('no credential found'); process.exit(3); }
const apiKey = found.key;
console.log('credential source: ' + found.source + '; length ' + apiKey.length);
const scrub = text => text.split(apiKey).join('[REDACTED_CREDENTIAL]');

// A slot counts as issued when a request for it was answered (in any way other than HTTP 429) or was in flight when a run
// was stopped. A slot whose requests were all rejected with HTTP 429 was never seen by a model and is issued again.
const issued = new Set();
let segmentNumber = 1;
if (existsSync(base)) {
  for (const entry of (await readdir(base)).filter(n => n.startsWith('seg-')).sort()) {
    segmentNumber = Math.max(segmentNumber, Number(entry.slice(4)) + 1);
    const answers = new Map((await journal(join(base, entry), 'responses.jsonl')).map(r => [r.request_number, r.http_status]));
    for (const row of await journal(join(base, entry), 'requests.jsonl')) {
      if (answers.get(row.request_number) !== 429) issued.add(row.case_id + '|' + row.condition);
    }
  }
}
// Requests and reservations of the whole extension so far: every part, every model, every segment.
let sentBefore = 0, reservedBefore = 0;
if (existsSync(extension)) {
  for (const partName of await readdir(extension, { withFileTypes: true })) {
    if (!partName.isDirectory()) continue;
    for (const modelName of await readdir(join(extension, partName.name), { withFileTypes: true })) {
      if (!modelName.isDirectory()) continue;
      for (const entry of (await readdir(join(extension, partName.name, modelName.name))).filter(n => n.startsWith('seg-'))) {
        for (const row of await journal(join(extension, partName.name, modelName.name, entry), 'requests.jsonl')) {
          sentBefore++;
          reservedBefore += row.reserved_credits ?? 0;
        }
      }
    }
  }
}
const sessions = manifest.sessions.filter(s => !issued.has(s.case_id + '|' + s.condition));
console.log('extension so far: ' + sentBefore + ' requests of at most ' + REQUEST_CEILING + ', ' + reservedBefore.toFixed(2) +
  ' credits reserved of at most ' + RESERVATION_CEILING);
console.log(model + ' / ' + part + (stream ? ' (streamed)' : '') + ': ' + manifest.sessions.length + ' sessions planned, ' + issued.size +
  ' issued earlier, ' + sessions.length + ' to issue; reservation ' + reservePerRequest.toFixed(4) + ' credits per request, ' +
  (reservePerRequest * sessions.length).toFixed(2) + ' in all');
if (!sessions.length) process.exit(0);
if (sessions.some(s => s.steps.length !== 1)) { console.log('unexpected multi-step session'); process.exit(5); }
if (reservedBefore + reservePerRequest * sessions.length > RESERVATION_CEILING) { console.log('reservation ceiling of the extension would be exceeded'); process.exit(6); }

const directory = join(base, 'seg-' + String(segmentNumber).padStart(2, '0'));
await mkdir(directory, { recursive: true });
const runId = randomUUID();
const started = new Date().toISOString();
await writeFile(join(directory, 'run.json'), JSON.stringify({
  schema: 'retrace-scale-run-ext', run_id: runId, started_at: started, endpoint: first.ENDPOINT, model, part,
  rules: 'prereg/scale_extension_rules.md', settings: SETTINGS, stop_at: STOP_AT.toISOString(),
  sessions_file: sessionsFile, sessions_file_sha256: sha256(sessionsText),
  planned_requests: sessions.length, pricing: price, reserved_credits_per_request: reservePerRequest,
  max_reserved_credits: reservePerRequest * sessions.length, sessions_sha256: sha256(JSON.stringify(sessions)),
  retries: 0, tools: false, store: false, agentic_memory: false,
  sessions: sessions.map(s => ({ case_id: s.case_id, family: s.family, condition: s.condition })) }, null, 2) + '\n', { flag: 'wx' });

let next = 0, issuedNow = 0, done = 0, failed = 0, cutOff = 0, consecutive = 0, cost = 0, halted = null;
let gate = Promise.resolve(), last = 0, writes = Promise.resolve();
const append = (name, record) => { writes = writes.then(() => appendFile(join(directory, name), scrub(JSON.stringify(record)) + '\n')); return writes; };
const dispatch = () => { const turn = gate.then(async () => { const wait = last + SETTINGS.minIntervalMs - Date.now(); if (wait > 0) await sleep(wait); last = Date.now(); }); gate = turn.catch(() => {}); return turn; };

let rateLimited = 0;
async function worker(workerNumber) {
  while (!halted) {
    if (new Date() >= STOP_AT) { halted = 'stop_time_reached'; return; }
    if (rateLimited && workerNumber > 0) return;   // one request at a time after the first HTTP 429
    const index = next++;
    if (index >= sessions.length) return;
    const session = sessions[index];
    const step = session.steps[0];
    const request = { model, instructions: session.instructions ?? manifest.instructions, input: [{ role: 'user', content: step.input }],
      max_output_tokens: SETTINGS.maxOutputTokens, temperature: 0, store: false, agentic_memory: false, tools: [], tool_choice: 'none' };
    if (stream) request.stream = true;
    const body = JSON.stringify(request);
    let error = null, redacted = false;
    for (let attempt = 1; ; attempt++) {
      await dispatch();
      if (halted) return;
      if (new Date() >= STOP_AT) { halted = 'stop_time_reached'; return; }
      if (sentBefore + issuedNow >= REQUEST_CEILING) { halted = 'request_ceiling_reached'; return; }
      const identity = { run_id: runId, model, part, case_id: session.case_id, family: session.family, condition: session.condition,
        response_kind: session.response_kind ?? 'decisions', session_index: index, step_index: 0, phase: step.phase,
        request_number: ++issuedNow, attempt };
      await append('requests.jsonl', { ...identity, started_at: new Date().toISOString(), request, request_sha256: sha256(body), reserved_credits: reservePerRequest });
      const clock = Date.now();
      let raw = null, parsed = null, httpStatus = null, streamInfo = null;
      error = null;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), SETTINGS.timeoutMs);
      try {
        const result = await fetch(first.ENDPOINT, { method: 'POST', redirect: 'error',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` }, body, signal: controller.signal });
        httpStatus = result.status;
        raw = await result.text();
        if (!result.ok) error = 'http_error';
        else if (stream && (result.headers.get('content-type') ?? '').includes('text/event-stream')) {
          const read = readStream(raw);
          streamInfo = { events: read.events, bytes: raw.length, terminal_type: read.terminal?.type ?? null };
          if (!read.terminal) error = 'stream_without_terminal_event';
          else {
            parsed = read.terminal.response;
            if (parsed?.status !== 'completed') error = 'response_not_completed';
            else if (!responseText(parsed) && read.deltas) parsed = { ...parsed, output_text: read.deltas };
          }
        } else {
          try { parsed = JSON.parse(raw); } catch { error = 'non_json_response'; }
          if (!error && parsed?.status !== 'completed') error = 'response_not_completed';
        }
      } catch {
        error = controller.signal.aborted ? 'timeout' : 'network_or_redirect_error';
      } finally { clearTimeout(timer); }
      redacted = typeof raw === 'string' && scrub(raw) !== raw;
      if (redacted) error = 'credential_echo_detected';
      const usage = parsed?.usage ?? null;
      const tokenCost = usage && Number.isSafeInteger(usage.input_tokens) && Number.isSafeInteger(usage.output_tokens)
        ? (usage.input_tokens * price.input + usage.output_tokens * price.output) / 1e6 : null;
      if (tokenCost !== null) cost += tokenCost;
      const outputText = error ? '' : responseText(parsed);
      const parsing = error ? { status: 'not_parsed', reason: error, decisions: null }
        : session.response_kind === 'graph' || session.response_kind === 'working' ? { status: 'deferred_validation', reason: null, decisions: null }
        : first.parseDecisions(outputText, session.decision_ids);
      // A streamed body repeats every token in its own event; the journal keeps the final response object instead.
      const kept = streamInfo ? (parsed ? JSON.stringify(parsed) : (raw ?? '').slice(0, 4000)) : raw;
      await append('responses.jsonl', { ...identity, finished_at: new Date().toISOString(), request, request_sha256: sha256(body),
        latency_ms: Date.now() - clock, http_status: httpStatus, raw_response: kept, raw_response_redacted: redacted, stream: streamInfo,
        response_status: parsed?.status ?? null, response_model: parsed?.model ?? null, usage,
        observed_token_cost_credits_uncached: tokenCost, output_text: outputText, parsing, error });
      if (httpStatus === 429) {
        rateLimited++;
        last = Date.now() + 65000 - SETTINGS.minIntervalMs;   // nothing is dispatched for at least 65 s
        console.log('  rate limit (HTTP 429) on ' + session.case_id + ' ' + session.condition + ', attempt ' + attempt + '; pausing 65 s');
        if (attempt <= 2) continue;
      }
      break;
    }
    done++;
    if (error) failed++;
    if (error === 'response_not_completed') cutOff++;
    if (['http_error', 'timeout', 'network_or_redirect_error', 'non_json_response', 'stream_without_terminal_event'].includes(error)) consecutive++; else consecutive = 0;
    if (redacted) halted = 'credential_echo_detected';
    else if (consecutive >= SETTINGS.maxConsecutiveErrors) halted = 'five_consecutive_provider_errors';
    if (done % 12 === 0) console.log('  ' + done + ' of ' + sessions.length + ' done, ' + failed + ' unusable so far, ' + new Date().toTimeString().slice(0, 8));
  }
}
await Promise.allSettled(Array.from({ length: SETTINGS.concurrency }, (_, number) => worker(number)));
await writes;
const summary = { schema: 'retrace-scale-run-ext-summary', run_id: runId, started_at: started, finished_at: new Date().toISOString(), model, part,
  planned_sessions: sessions.length, requests_sent: issuedNow, sessions_finished: done, failed_or_cut_off: failed, cut_off_at_output_limit: cutOff,
  rejected_with_http_429: rateLimited, sessions_not_started: sessions.length - Math.min(next, sessions.length),
  status: halted ? 'halted' : 'completed', halt_reason: halted,
  observed_token_cost_credits_uncached: cost, reserved_credits_issued: reservePerRequest * issuedNow };
await writeFile(join(directory, 'summary.json'), JSON.stringify(summary, null, 2) + '\n', { flag: 'wx' });
console.log(model + ' / ' + part + ': ' + summary.status + (halted ? ' (' + halted + ')' : '') + '; sessions finished ' + done + ' of ' + sessions.length + '; requests sent ' + issuedNow +
  ' (' + rateLimited + ' rejected with 429); unusable ' + failed + ' (cut off ' + cutOff + '); observed cost ' + cost.toFixed(4) + ' credits');
