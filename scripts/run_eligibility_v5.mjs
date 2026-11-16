/** Eight-call eligibility confirmation; original runner and older evidence remain frozen. */
import {readFile,open,access} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {runPilot,planPilot,createPilotBudget} from './run_adaption.mjs';
const hash = v => createHash('sha256').update(v).digest('hex');
const check = (ok,why) => {if(!ok) throw new Error(why);};

export async function verifyEligibility(root) {
  const base=resolve(root), read=async p=>JSON.parse(await readFile(join(base,p),'utf8'));
  const freeze=await read('data/eligibility-v5-freeze.json');
  const preservation=await read('data/eligibility-v5-preservation.json');
  for(const row of freeze.files) check(hash(await readFile(join(base,row.path)))===row.sha256,'frozen_input_changed:'+row.path);
  for(const [p,expected] of Object.entries({...preservation.protected,...preservation.all_prior_results})) check(hash(await readFile(join(base,p)))===expected,'prior_artifact_changed:'+p);
  const execution=await read('data/eligibility-v5-execution.json');
  const reservation=await read('results/eligibility-v5-reservation.json');
  const sessions=await read('data/eligibility-v5-paired-sessions.json');
  check(execution.status==='authorized_once'&&execution.planned_requests===8&&execution.retries===0,'wrong_authorization');
  check(reservation.reservation_id===execution.reservation_id&&reservation.fresh_reserved_credits==='0.19546112'&&reservation.cumulative_conservative_reserved_credits==='40.98826224','wrong_reservation');
  check(hash(JSON.stringify(sessions))===execution.sessions_json_sha256,'sessions_changed');
  check(execution.output_directory==='results/eligibility-v5/gemma-4-31b-it','unexpected_output_path');
  const plan=planPilot({model:execution.model,sessions,maxRequests:8,maxOutputTokens:4096});
  check(plan.planned_requests===8&&plan.reserve_nanocredits_per_request===24432640,'wrong_plan');
  return {base,execution,sessions,plan};
}

export async function runEligibility({root,apiKey}) {
  const {base,execution,sessions}=await verifyEligibility(root);
  check(typeof apiKey==='string'&&apiKey.length>8&&!/\s/.test(apiKey),'invalid_credential');
  try{await access(join(base,execution.output_directory));throw new Error('run_already_exists');}catch(e){if(e.code!=='ENOENT')throw e;}
  const marker=await open(join(base,'results/eligibility-v5-dispatch.json'),'wx');
  try{await marker.writeFile(JSON.stringify({schema:'retrace.eligibility-v5-dispatch.v1',started_at:new Date().toISOString(),reservation_id:execution.reservation_id,planned_requests:8,retries:0,cumulative_bound_credits:'40.98826224'},null,2)+'\n');await marker.sync();}finally{await marker.close();}
  return runPilot({apiKey,model:execution.model,sessions,instructions:sessions[0].instructions,
    outputDir:join(base,execution.output_directory),maxRequests:8,maxOutputTokens:4096,concurrency:1,
    minIntervalMs:3100,timeoutMs:120000,budget:createPilotBudget({maxCredits:0.19546112,maxRequests:8})});
}
