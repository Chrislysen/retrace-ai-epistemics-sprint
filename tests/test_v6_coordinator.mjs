import test from 'node:test';
import assert from 'node:assert/strict';
import {coordinateV6,runFalsificationV6} from '../scripts/run_falsification_v6.mjs';
import {mkdtemp,mkdir,writeFile,readdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

test('failed offline gate blocks the entry point before execution files or credentials are read',async()=>{
  const root=await mkdtemp(join(tmpdir(),'retrace-v6-gate-'));
  try {
    await mkdir(join(root,'results','v6b'),{recursive:true});
    await writeFile(join(root,'results','v6b','conservation-v6b-primary.json'),JSON.stringify({quality_gate:{passed:false}}));
    await assert.rejects(runFalsificationV6({root,apiKey:null}),/offline_quality_gate_failed/);
    assert.deepEqual(await readdir(join(root,'results')),['v6b']);
  } finally { await rm(root,{recursive:true,force:true}); }
});

const slot = model => ({model,session:{case_id:'case',condition:'arm',instructions:'Test only'}});
const ok = () => ({status:'completed',issued_requests:1,recorded_responses:1,responses_missing_usage:0});
const order = ['gemma-4-31b-it','glm-53-flash','gemma-4-31b-it','glm-53-flash'].map(slot);
const setup = extra => ({slots:order,apiKey:'fake-local-test-credential',outputRoot:'unused-test-path',
  minIntervalMs:0,sleep:async()=>{},...extra});

test('ungated coordinator has no live provider default',async()=>{
  await assert.rejects(coordinateV6(setup({})),/explicit_pilot_required/);
});

for (const failure of ['http_error','timeout','network_or_redirect_error','non_json_response',
                       'response_not_completed','documented_token_bound_exceeded',
                       'credential_echo_detected','journal_or_worker_error']) {
  for (const position of [0,1]) test(`${failure} in model position ${position} stops all later models`,async()=>{
    let calls=0;
    const result=await coordinateV6(setup({pilot:async()=>{
      const i=calls++;
      return i===position?{...ok(),status:'halted',halt_reason:failure}:ok();
    }}));
    assert.equal(calls,position+1);assert.equal(result.status,'halted');
    assert.equal(result.halt_reason,failure);assert.equal(result.later_slots_not_dispatched,3-position);
    assert.match(result.fallback,/unchanged v5/);assert.equal(result.retries,0);
  });
}

test('missing usage stops before another model despite completed response',async()=>{
  let calls=0;
  const result=await coordinateV6(setup({pilot:async()=>{calls++;return {...ok(),responses_missing_usage:1};}}));
  assert.equal(calls,1);assert.equal(result.halt_reason,'missing_usage_accounting');
});

test('exception inside a slot remains uncertain and is never retried',async()=>{
  let calls=0;
  const result=await coordinateV6(setup({pilot:async()=>{calls++;throw Error('private text must not escape');}}));
  assert.equal(calls,1);assert.equal(result.invocations_without_summary,1);
  assert.equal(result.later_slots_not_dispatched,3);assert.doesNotMatch(JSON.stringify(result),/private text/);
});

test('failed start journal prevents dispatch',async()=>{
  let calls=0;
  const result=await coordinateV6(setup({pilot:async()=>{calls++;return ok();},
    onEvent:async e=>{if(e.type==='slot_start')throw Error('write failed');}}));
  assert.equal(calls,0);assert.equal(result.pilot_invocations_started,0);assert.equal(result.status,'halted');
});

test('failed end journal prevents later calls even after successful API output',async()=>{
  let calls=0;
  const result=await coordinateV6(setup({pilot:async()=>{calls++;return ok();},
    onEvent:async e=>{if(e.type==='slot_end')throw Error('write failed');}}));
  assert.equal(calls,1);assert.equal(result.status,'halted');
});

test('failed terminal journal rejects instead of returning a successful experiment',async()=>{
  let calls=0;
  await assert.rejects(coordinateV6(setup({pilot:async()=>{calls++;return ok();},
    onEvent:async e=>{if(e.type==='experiment_end')throw Error('terminal write failed');}})));
  assert.equal(calls,4);
});

test('global serial completion spacing crosses model boundaries',async()=>{
  let clock=1000,active=0;const starts=[],finishes=[];
  const result=await coordinateV6(setup({minIntervalMs:3100,now:()=>clock,sleep:async ms=>{clock+=ms;},
    pilot:async()=>{assert.equal(active++,0);starts.push(clock);clock+=137;await Promise.resolve();
      finishes.push(clock);active--;return ok();}}));
  assert.equal(result.status,'completed');
  for(let i=1;i<starts.length;i++)assert.ok(starts[i]-finishes[i-1]>=3100);
});

test('schema-invalid completed model output is retained without retry or transport halt',async()=>{
  let calls=0;
  const result=await coordinateV6(setup({pilot:async()=>{calls++;return {...ok(),deferred_graph_responses:1};}}));
  assert.equal(calls,4);assert.equal(result.status,'completed');assert.equal(result.outcomes.length,4);
});
