/** Globally serial, stop-on-first-API-failure coordinator. No automatic retries. */
import {readFile, open, access} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {runPilot, planPilot, createPilotBudget} from './run_adaption.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const check = (condition, message) => { if (!condition) throw new Error(message); };
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

export async function coordinateV6({slots, apiKey, outputRoot, pilot,
    budget=createPilotBudget({maxCredits:2.94027264,maxRequests:32}),
    minIntervalMs=3100, timeoutMs=120000, now=Date.now, sleep=pause, onEvent=async () => {}}) {
  check(typeof pilot === 'function', 'explicit_pilot_required');
  check(Array.isArray(slots) && slots.length > 0 && slots.length <= 32, 'invalid_v6_slots');
  check(Number.isInteger(minIntervalMs) && minIntervalMs >= 0, 'invalid_v6_interval');
  let lastFinish = null, haltReason = null, invocations = 0;
  const outcomes = [];
  for (let index=0; index<slots.length; index++) {
    const slot = slots[index];
    if (haltReason) break;
    try {
      // Spacing from completion is stronger than start spacing and cannot be
      // shortened by variable per-slot journal initialization latency.
      if (lastFinish !== null) await sleep(Math.max(0, minIntervalMs - (now()-lastFinish)));
      await onEvent({type:'slot_start', slot:index, model:slot.model});
      invocations++;
      const result = await pilot({apiKey, model:slot.model, sessions:[slot.session],
        instructions:slot.session.instructions, outputDir:join(outputRoot, 'slot-'+String(index+1).padStart(2,'0')),
        maxRequests:1, maxOutputTokens:4096, concurrency:1, minIntervalMs:3100,
        timeoutMs, budget});
      lastFinish = now();
      outcomes.push({slot:index, model:slot.model, case_id:slot.session.case_id,
                     condition:slot.session.condition, summary:result});
      if (result.status !== 'completed' || result.issued_requests !== 1 || result.recorded_responses !== 1)
        haltReason = result.halt_reason || 'incomplete_slot_accounting';
      else if (result.responses_missing_usage !== 0) haltReason = 'missing_usage_accounting';
      await onEvent({type:'slot_end', slot:index, model:slot.model, status:result.status,
                     halt_reason:haltReason});
    } catch {
      // Provider and filesystem error messages may contain sensitive material.
      haltReason = 'coordinator_or_slot_error';
    }
  }
  const result = {schema:'retrace.v6-dispatch-summary.v1', status:haltReason?'halted':'completed',
    halt_reason:haltReason, planned_slots:slots.length, returned_slot_summaries:outcomes.length,
    pilot_invocations_started:invocations,
    invocations_without_summary:invocations-outcomes.length,
    later_slots_not_dispatched:slots.length-invocations,
    outcomes, budget:budget.snapshot(), retries:0,
    fallback:haltReason?'Use the unchanged v5 deliverable; do not resume this frozen run.':null};
  // A failed terminal journal write rejects the entire coordinator. Never restart.
  await onEvent({type:'experiment_end', status:result.status, halt_reason:haltReason});
  return result;
}

export async function runFalsificationV6({root, apiKey}) {
  const base = resolve(root);
  const read = async p => JSON.parse(await readFile(join(base,p),'utf8'));
  const offline = await read('results/v6b/conservation-v6b-primary.json');
  check(offline.quality_gate?.passed === true, 'offline_quality_gate_failed');
  const execution = await read('data/falsification-v6-execution.json');
  const freeze = await read('data/falsification-v6-freeze.json');
  const preservation = await read('data/v6-baseline-preservation.json');
  for (const row of freeze.files)
    check(hash(await readFile(join(base,row.path)))===row.sha256, 'v6_frozen_input_changed:'+row.path);
  for (const [path, expected] of Object.entries(preservation.protected))
    check(hash(await readFile(join(base,path)))===expected, 'v5_baseline_changed:'+path);
  const slots = await read('data/falsification-v6-sessions.json');
  check(execution.status==='authorized_once' && execution.planned_requests===32 && execution.retries===0,
        'invalid_v6_execution');
  check(hash(JSON.stringify(slots))===execution.sessions_json_sha256,'v6_sessions_changed');
  check(execution.conservative_cumulative_credits==='43.92853488' && execution.reserved_credits==='2.94027264',
        'unexpected_v6_reservation');
  let bound=0;
  for (const slot of slots) {
    check(['gemma-4-31b-it','glm-53-flash'].includes(slot.model),'unexpected_v6_model');
    bound+=planPilot({model:slot.model,sessions:[slot.session],maxRequests:1,maxOutputTokens:4096}).reserve_nanocredits_per_request;
  }
  check(bound===2940272640,'v6_plan_bound_mismatch');
  check(typeof apiKey==='string' && apiKey.length>8 && !/\s/.test(apiKey),'invalid_credential');
  const out = join(base, execution.output_directory);
  check(execution.output_directory==='results/v6/falsification','unexpected_v6_output_directory');
  try { await access(out); throw new Error('v6_run_already_exists'); } catch(error) { if(error.code!=='ENOENT') throw error; }
  const journal = await open(join(base,'results/v6/falsification-dispatch.jsonl'),'wx');
  const event = async row => { await journal.writeFile(JSON.stringify({...row,at:new Date().toISOString()})+'\n'); await journal.sync(); };
  try {
    await event({type:'experiment_start',planned_slots:32,retries:0,reserved_credits:'2.94027264',cumulative_credits:'43.92853488'});
    const summary = await coordinateV6({slots,apiKey,outputRoot:out,onEvent:event,pilot:runPilot});
    const handle = await open(join(base,'results/v6/falsification-dispatch-summary.json'),'wx');
    try { await handle.writeFile(JSON.stringify(summary,null,2)+'\n'); await handle.sync(); }
    finally { await handle.close(); }
    return summary;
  } finally { await journal.close(); }
}
