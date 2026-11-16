/** One authorized frozen run. The key is caller memory only; no environment lookup. */
import { readFile, open, access } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
import { runPilot, planPilot, createPilotBudget } from './run_adaption.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const require = (condition, reason) => { if (!condition) throw new Error(reason); };

export async function verifyExecution(root) {
  const base = resolve(root);
  const read = async path => JSON.parse(await readFile(join(base, path), 'utf8'));
  const digest = async path => hash(await readFile(join(base, path)));
  const execution = await read('data/ambiguity-v4-execution.json');
  const preservation = await read('data/ambiguity-v4-cycle-preservation.json');
  const checkpoint = await read('data/ambiguity-v4-scorer-checkpoint.json');
  const reservation = await read('results/ambiguity-v4-reservation.json');
  for (const [path, expected] of Object.entries({...preservation.protected, ...preservation.all_prior_results})) {
    require(await digest(path) === expected, 'prior_artifact_changed:' + path);
  }
  for (const row of checkpoint.files) require(await digest(row.path) === row.sha256, 'scorer_changed:' + row.path);
  require(execution.status === 'authorized_once' && execution.planned_requests === 10 && execution.retries === 0, 'invalid_authorization');
  for (const [path, field] of [['data/ambiguity-v4-config.json','config_sha256'],
                               ['data/ambiguity-v4-freeze.json','offline_freeze_sha256'],
                               ['data/ambiguity-v4-sessions.json','sessions_file_sha256'],
                               ['scripts/run_adaption.mjs','runner_sha256'],
                               ['scripts/run_ambiguity_v4.mjs','runner_entry_sha256']]) {
    require(await digest(path) === execution[field], 'execution_input_changed:' + path);
  }
  require(reservation.reservation_id === execution.reservation_id && reservation.status === 'reserved_before_dispatch', 'missing_reservation');
  require(reservation.fresh_reserved_credits === '0.24432640' && reservation.cumulative_conservative_reserved_credits === '40.79280112', 'reservation_mismatch');
  const sessions = await read('data/ambiguity-v4-sessions.json');
  require(hash(JSON.stringify(sessions)) === execution.sessions_json_sha256, 'session_content_changed');
  const plan = planPilot({model:execution.model,sessions,maxRequests:10,maxOutputTokens:4096});
  require(plan.planned_requests === 10 && plan.reserve_nanocredits_per_request === 24432640 && plan.max_reserved_credits === 0.2443264, 'runner_budget_mismatch');
  require(execution.output_directory === 'results/ambiguity-v4/gemma-4-31b-it', 'unexpected_output_path');
  return {base,execution,sessions,plan};
}

export async function runV4({root,apiKey}) {
  const {base,execution,sessions} = await verifyExecution(root);
  require(typeof apiKey === 'string' && apiKey.length > 8 && !/\s/.test(apiKey), 'invalid_credential');
  try { await access(join(base,execution.output_directory)); throw new Error('run_already_exists'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  // This durable, exclusive dispatch marker forbids accidental re-entry even
  // when a process stops before the runner can create its own exclusive files.
  const marker = await open(join(base,'results/ambiguity-v4-dispatch.json'),'wx');
  try {
    await marker.writeFile(JSON.stringify({schema:'retrace.ambiguity-v4-dispatch.v1',
      started_at:new Date().toISOString(),reservation_id:execution.reservation_id,
      planned_requests:10,retries:0,output_directory:execution.output_directory,
      cumulative_bound_credits:'40.79280112',actual_billed_credits:null},null,2)+'\n');
    await marker.sync();
  } finally { await marker.close(); }
  return runPilot({apiKey,model:execution.model,sessions,instructions:sessions[0].instructions,
    outputDir:join(base,execution.output_directory),maxRequests:10,maxOutputTokens:4096,
    concurrency:1,minIntervalMs:3100,timeoutMs:120000,
    budget:createPilotBudget({maxCredits:0.24432640,maxRequests:10})});
}
