/**
 * Runs the scaling run of prereg/scale_rules.md through the project's first-day runner (scripts/run_adaption.mjs),
 * which is imported unchanged. Sprint addition, written with AI assistance on Monday 16 November 2026.
 *
 *   node post_sweep/run_scale.mjs <model> [--smoke] [--dry <folder>]
 *
 * --smoke  one request with a first-day session (not one of the 108 slots), to check that the endpoint answers
 * --dry    no network and no credential: a stand-in fetch returns a fixed reply; output goes to <folder>
 *
 * The credential is held in memory only. It is read from secrets.local.env in the project root if that file exists,
 * else from the environment variable ADAPTION_API_KEY, else from the local record of the session in which the
 * author supplied it. It is never printed, and the runner refuses to write it into any journal.
 * The runner stops a segment at the first provider error and retries nothing; sessions not yet issued are run in
 * the next segment. A request that was issued is never issued again.
 */
import { readFile, readdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const runner = await import(pathToFileURL(join(ROOT, 'scripts', 'run_adaption.mjs')).href);
const MODELS = ['gemma-4-31b-it', 'qwen3.8-27b', 'deepseek-v4-flash', 'glm-53-flash'];
const MAX_SEGMENTS = 6;
const STOP_AT = new Date('2026-11-16T08:30:00+01:00');
const SETTINGS = { maxOutputTokens: 8192, concurrency: 2, timeoutMs: 180000, minIntervalMs: 3100 };

const args = process.argv.slice(2);
const model = args[0];
const smoke = args.includes('--smoke');
const dryAt = args.includes('--dry') ? args[args.indexOf('--dry') + 1] : null;
if (!MODELS.includes(model)) { console.log('usage: node post_sweep/run_scale.mjs <' + MODELS.join('|') + '> [--smoke] [--dry <folder>]'); process.exit(2); }
// Amendment 1 (prereg/scale_rules_amendment_1.md): this runner is used for gemma-4-31b-it only. The three reasoning
// models exceed its 8,192-token output limit and are run by post_sweep/run_scale_v2.mjs.
if (model !== 'gemma-4-31b-it' && !smoke && !dryAt) { console.log(model + ': held for the amended runner (run_scale_v2.mjs)'); process.exit(4); }

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
    if (found) return { key: found[found.length - 1], source: 'session record (' + new Set(found).size + ' distinct candidate(s), last one used)' };
  }
  return null;
}

const stubFetch = async () => ({ ok: true, status: 200, text: async () => JSON.stringify({
  status: 'completed', model, output_text: '{"decisions":{}}', usage: { input_tokens: 10, output_tokens: 5 } }) });

async function journal(folder, name) {
  const file = join(folder, name);
  if (!existsSync(file)) return [];
  return (await readFile(file, 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
}

const manifest = JSON.parse(await readFile(join(ROOT, 'post_sweep', 'out', 'scale', 'sessions.json'), 'utf8'));
let sessions = manifest.sessions;
let base = join(ROOT, 'post_sweep', 'out', 'scale', 'runs', model);
if (smoke) {
  const first = JSON.parse(await readFile(join(ROOT, 'data', 'prose-sessions.json'), 'utf8'));
  sessions = [first.sessions.find(s => s.condition === 'prose_fresh')];
  base = join(ROOT, 'post_sweep', 'out', 'scale', 'smoke', model);
}
let apiKey = 'dry-run-no-credential-0000000000';
let fetchImpl = globalThis.fetch;
if (dryAt) { base = join(resolve(dryAt), model + (smoke ? '-smoke' : '')); fetchImpl = stubFetch; }
else {
  const found = await credential();
  if (!found) { console.log('no credential found'); process.exit(3); }
  apiKey = found.key;
  console.log('credential source: ' + found.source + '; length ' + apiKey.length);
}

const issued = new Set();
if (existsSync(base)) {
  for (const entry of (await readdir(base)).filter(n => n.startsWith('seg-')).sort()) {
    for (const row of await journal(join(base, entry), 'requests.jsonl')) issued.add(row.case_id + '|' + row.condition);
  }
}
console.log(model + ': ' + sessions.length + ' sessions planned, ' + issued.size + ' already issued in earlier segments');

for (let segment = 1; segment <= MAX_SEGMENTS; segment++) {
  const remaining = sessions.filter(s => !issued.has(s.case_id + '|' + s.condition));
  if (!remaining.length) { console.log('all sessions issued'); break; }
  if (new Date() >= STOP_AT) { console.log('stop time reached; ' + remaining.length + ' sessions not issued'); break; }
  let number = segment;
  while (existsSync(join(base, 'seg-' + String(number).padStart(2, '0')))) number++;
  if (number > MAX_SEGMENTS) { console.log('segment limit reached; ' + remaining.length + ' sessions not issued'); break; }
  const outputDir = join(base, 'seg-' + String(number).padStart(2, '0'));
  const requests = remaining.reduce((sum, s) => sum + s.steps.length, 0);
  const plan = runner.planPilot({ model, sessions: remaining, maxRequests: requests, maxOutputTokens: SETTINGS.maxOutputTokens });
  const started = Date.now();
  let summary;
  try {
    summary = await runner.runPilot({ apiKey, model, sessions: remaining, instructions: manifest.instructions, outputDir,
      maxRequests: requests, maxCredits: Math.min(50, plan.max_reserved_credits * 1.01 + 0.01), fetchImpl, ...SETTINGS });
  } catch (error) {
    console.log('segment ' + number + ' could not run: ' + (error && error.message));
    break;
  }
  for (const row of await journal(outputDir, 'requests.jsonl')) issued.add(row.case_id + '|' + row.condition);
  const responses = await journal(outputDir, 'responses.jsonl');
  const failed = responses.filter(r => r.error);
  console.log('segment ' + number + ': ' + summary.status + (summary.halt_reason ? ' (' + summary.halt_reason + ')' : '') + '; issued ' +
    summary.issued_requests + ' of ' + requests + '; responses ' + responses.length + '; failed ' + failed.length +
    (failed.length ? ' [' + failed.map(r => r.error + (r.http_status ? ' ' + r.http_status : '')).join(', ') + ']' : '') +
    '; observed cost ' + summary.observed_token_cost_credits_uncached.toFixed(4) + ' credits; ' + Math.round((Date.now() - started) / 1000) + ' s');
  if (summary.status === 'completed') break;
}
console.log(model + ': issued ' + issued.size + ' of ' + sessions.length);
