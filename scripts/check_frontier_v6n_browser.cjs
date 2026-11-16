'use strict';
// Actual published catalogs and localhost only. No provider connection or repair.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const assert=require('node:assert/strict'),net=require('node:net'),{spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const out=path.join(root,'results/frontier-v6n-browser-qa-complete');
const runtime='C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1112-611-0_26.1112.611.0_x64__3k8sg7r9htsxt/dependencies';
const {chromium}=require(path.join(runtime,'node/node_modules/playwright'));
const origin='http://127.0.0.1:8778';
const pins={freeze:'7cf7661e1a2674ed6a7553ddd98b75d460443b52161a3ff6310ac42dc9877202',
  ir:'e0ea9340d09060cd2942cb43faa01706b34d5da2923c95cb4bc5803193037bd2',
  refuter:'c6317f04d0647745eabc0394f1b646cdb040110d9e64949f7b9da07913b86523'};
const hash=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const fileHash=name=>hash(fs.readFileSync(path.join(root,name)));
const read=name=>JSON.parse(fs.readFileSync(path.join(root,name),'utf8'));
const rel=name=>path.relative(root,name).split(path.sep).join('/');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const sourceNames=['data/frontier-v6n-freeze.json','results/frontier-v6n/catalog/manifest.json',
  'results/frontier-v6n/refuter-catalog/manifest.json','retrace/server_v6n.py',
  'retrace/refuter_reader_v6n.py','retrace/refuter_catalog_v6n.py','retrace/refuter_inspector_v6l.py',
  'retrace/source_diagnostics_v6k.py','web/v6h/app.js','web/v6h/style.css',
  'web/v6n/index.html','web/v6n/evidence.js','web/v6n/refuters.js',rel(__filename)];
let browser,context,server,serverLog,stage='initial',passed=false;
const checks=[],screenshots=[],requests=[],errors=[],blocked=[];
fs.mkdirSync(out); // Refuse any existing QA directory and retain failures.
const traceFile=path.join(out,'events.jsonl');fs.writeFileSync(traceFile,'',{flag:'wx'});
const record=(name,detail={})=>{const row={name,detail};checks.push(row);fs.appendFileSync(traceFile,JSON.stringify(row)+'\n');console.log(name);};
const bindings=Object.fromEntries(sourceNames.map(name=>[name,{sha256:fileHash(name),bytes:fs.statSync(path.join(root,name)).size}]));
async function freePort(){await new Promise((resolve,reject)=>{const probe=net.createServer();probe.once('error',reject);probe.listen(8778,'127.0.0.1',()=>probe.close(resolve));});}
async function screenshot(page,name,selector){
  const target=path.join(out,name);if(selector)await page.locator(selector).screenshot({path:target});
  else await page.screenshot({path:target,fullPage:true});
  screenshots.push({path:rel(target),sha256:hash(fs.readFileSync(target)),bytes:fs.statSync(target).size});
}
async function stable(page){await page.waitForFunction(()=>!document.body.classList.contains('busy'),null,{timeout:30000});}
async function snapshot(page){return page.evaluate(()=>({bundle:document.querySelector('#bundle').value,
  ir:document.querySelector('#ir').value,analysis:document.querySelector('#analysis').innerHTML,
  current:JSON.stringify(current),active:JSON.stringify(activeBrief),dirty,
  provenance:document.querySelector('#recorded-origin').innerHTML,
  provenanceHidden:document.querySelector('#recorded-origin').hidden}));}
async function choose(page,kind,row){
  const prefix=kind==='catalog'?'catalog':'refuter',endpoint=kind==='catalog'?'catalog':'refuters';
  await page.locator('#'+prefix+'-panel').evaluate(el=>{el.open=true;});
  const response=page.waitForResponse(r=>r.url()===`${origin}/api/v6n/${endpoint}/${row.key}`,{timeout:45000});
  await page.evaluate(({prefix,cid,model})=>{
    const c=document.querySelector('#'+prefix+'-case'),m=document.querySelector('#'+prefix+'-model');
    c.value=cid;c.dispatchEvent(new Event('change',{bubbles:true}));
    m.value=model;m.dispatchEvent(new Event('change',{bubbles:true}));
  },{prefix,cid:row.case_id,model:row.model});
  assert.equal((await response).status(),200);
  await page.waitForFunction(({prefix,cid,model})=>{
    const box=document.querySelector('#'+prefix+'-entry'),msg=document.querySelector('#'+prefix+'-message').textContent;
    return !box.hidden&&box.textContent.includes(cid)&&box.textContent.includes(model)&&
      (prefix==='catalog'?msg.startsWith('Selected observation only.'):msg.startsWith('Read-only comparison.'));
  },{prefix,cid:row.case_id,model:row.model},{timeout:45000});
}

(async()=>{
 try{
  assert.equal(bindings[sourceNames[0]].sha256,pins.freeze);assert.equal(bindings[sourceNames[1]].sha256,pins.ir);
  assert.equal(bindings[sourceNames[2]].sha256,pins.refuter);
  const index=read('results/frontier-v6n/catalog/index.json'),refuters=read('results/frontier-v6n/refuter-catalog/index.json');
  assert.equal(index.entries.length,300);assert.equal(refuters.entries.length,300);
  const admitted=index.entries.find(r=>r.status==='admitted'&&r.candidate_count===1);
  const invalid=index.entries.find(r=>r.status==='invalid_ir');
  const failed=index.entries.find(r=>r.status==='provider_failure');
  const proposal=refuters.entries.find(r=>{
    if(r.status!=='source_located_proposal')return false;
    const value=read(r.entry_path);return value.inspection?.preview?.status==='preview_only'&&
      value.inspection.preview.modal_summary?.status==='evaluated';
  });
  assert.ok(admitted&&invalid&&failed&&proposal,'Published representative statuses required');
  record('representative_selection',{policy:'First published index match for each stated UI condition; not an accuracy sample',
    admitted:admitted.slot_id,invalid:invalid.slot_id,provider_failure:failed.slot_id,refuter:proposal.slot_id});
  await freePort();stage='server_start';serverLog=fs.openSync(path.join(out,'server.log'),'wx');
  server=spawn(path.join(runtime,'python/python.exe'),['-X','utf8','-B','-S','-m','retrace.server_v6n',
    '--port','8778','--freeze-sha256',pins.freeze,'--catalog-manifest-sha256',pins.ir,
    '--refuter-manifest-sha256',pins.refuter],{cwd:root,windowsHide:true,
      env:{...process.env,__PYVENV_LAUNCHER__:path.join(root,'.venv-v6c/Scripts/python.exe')},
      stdio:['ignore',serverLog,serverLog]});
  for(let i=0;i<80;i++){
    if(server.exitCode!==null)throw new Error('Owned localhost server exited before readiness');
    try{const r=await fetch(origin+'/api/v6n/catalog',{signal:AbortSignal.timeout(1000)});if(r.ok)break;}catch{}
    if(i===79)throw new Error('Local server readiness timeout');await delay(250);
  }
  browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true,
    args:['--disable-background-networking','--disable-component-update','--no-first-run','--disable-sync']});
  context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
  await context.route('**/*',route=>{const u=new URL(route.request().url());
    if(u.origin===origin)return route.continue();blocked.push(u.origin+u.pathname);return route.abort();});
  await context.tracing.start({screenshots:true,snapshots:true,sources:true});
  const page=await context.newPage();page.setDefaultTimeout(20000);
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>requests.push({method:r.method(),path:new URL(r.url()).pathname,origin:new URL(r.url()).origin}));
  await page.goto(origin,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>document.querySelector('#catalog-total').textContent.startsWith('300 scheduled')&&
    document.querySelector('#refuter-total').textContent.startsWith('300 scheduled'));
  record('published_catalogs_loaded',{ir:300,refuter:300});
  stage='constructed_demo';await page.locator('#demo').click();await stable(page);
  await page.waitForFunction(()=>current?.candidate_ids.length===8);
  await page.locator('#question').getByRole('button',{name:'Unknown',exact:true}).click();await stable(page);
  assert.equal(await page.evaluate(()=>current.candidate_ids.length),8);
  await page.locator('#question').getByRole('button',{name:'Yes',exact:true}).click();await stable(page);
  assert.equal(await page.evaluate(()=>current.candidate_ids.length),4);
  assert.equal(await page.locator('#question').getByRole('button').count(),0);
  await page.locator('#reset-answers').click();await stable(page);
  assert.equal(await page.evaluate(()=>current.candidate_ids.length),8);
  record('constructed_clarification',{initial:8,unknown:8,yes:4,decision_question_stops:true,reset:8});
  await page.locator('.exposure-row').filter({hasText:'RELEASE_D:'}).getByRole('button',{name:'Apply additional withdrawal'}).click();await stable(page);
  const withdrawal=await page.evaluate(()=>({state:current.state.scenario_withdrawals,decision:current.decisions.RELEASE_D.state}));
  assert.deepEqual(withdrawal.state,['A','B','C']);assert.equal(withdrawal.decision,'not_supported');
  record('constructed_minimum_three_withdrawal',withdrawal);
  await page.locator('#clear-scenario').click();await stable(page);
  const group=await page.evaluate(()=>activeBrief.documents.find(g=>g.evidence_ids.includes('A')));
  assert.ok(group);const docToggle=page.getByRole('checkbox',{name:'Document veto '+group.label,exact:true});
  await docToggle.check();await stable(page);await page.getByRole('checkbox',{name:'revoked_passages A',exact:true}).check();await stable(page);
  await docToggle.uncheck();await stable(page);
  const veto=await page.evaluate(()=>({document:current.record_flags.A.document_veto,passage:current.record_flags.A.passage_veto}));
  assert.deepEqual(veto,{document:false,passage:true});
  assert.ok((await page.locator('#records').textContent()).includes('Revoked — falsity not asserted'));
  record('independent_document_passage_veto',veto);await screenshot(page,'01-constructed-vetoes.png');
  stage='actual_admitted';await choose(page,'catalog',admitted);assert.equal(await page.locator('#catalog-load').isDisabled(),false);
  await page.locator('#catalog-load').click();await stable(page);
  await page.waitForFunction(()=>!document.querySelector('#recorded-origin').hidden&&current!==null&&!dirty);
  assert.equal(await page.evaluate(()=>current.candidate_ids.length),1);
  assert.equal(await page.locator('#analysis').isVisible(),true);
  const cleared=await page.evaluate(()=>({answers:current.state.answers,documents:current.state.revoked_documents,
    passages:current.state.revoked_passages,scenario:current.state.scenario_withdrawals}));
  assert.deepEqual(cleared,{answers:{},documents:[],passages:[],scenario:[]});
  record('actual_admitted_ir_loaded',{slot_id:admitted.slot_id,state_cleared:true,meaning_verified:false});
  await screenshot(page,'02-real-admitted-ir.png');
  stage='invalid_rejection';let before=await snapshot(page);await choose(page,'catalog',invalid);
  assert.equal(await page.locator('#catalog-load').isDisabled(),true);assert.equal(await page.locator('#catalog-diagnose').isDisabled(),false);
  await page.locator('#catalog-diagnose').click();await page.waitForFunction(()=>document.querySelector('#catalog-diagnosis').textContent.includes('Local rejection review · no repair'));
  assert.deepEqual(await snapshot(page),before);
  record('actual_rejection_explanation_nonmutating',{slot_id:invalid.slot_id,workbench_sha256:hash(JSON.stringify(before))});
  await screenshot(page,'03-real-rejection-review.png','#catalog-panel');
  stage='provider_failure';before=await snapshot(page);await choose(page,'catalog',failed);
  assert.equal(await page.locator('#catalog-load').isDisabled(),true);assert.equal(await page.locator('#catalog-download').isDisabled(),true);
  assert.equal(await page.locator('#catalog-diagnose').isDisabled(),true);assert.deepEqual(await snapshot(page),before);
  record('actual_provider_failure_disabled',{slot_id:failed.slot_id});await screenshot(page,'04-real-provider-failure.png','#catalog-panel');
  stage='refuter_preview';before=await snapshot(page);await choose(page,'refuter',proposal);
  const refuterText=await page.locator('#refuter-entry').textContent();
  assert.ok(refuterText.includes('Seed G → G union P.'));assert.ok(refuterText.includes('Locations do not establish entailment.'));
  assert.ok(refuterText.includes('Smallest additional record withdrawal'));assert.deepEqual(await snapshot(page),before);
  record('actual_controlled_seed_preview_nonmutating',{slot_id:proposal.slot_id,comparison:'G union P',source_entailment_verified:false,
    workbench_sha256:hash(JSON.stringify(before))});await screenshot(page,'05-real-controlled-seed-preview.png','#refuter-panel');
  stage='source_edit';const source=await page.locator('#bundle').inputValue();await page.locator('#bundle').fill(source+'\n ');
  assert.equal(await page.locator('#analysis').isVisible(),false);assert.equal(await page.locator('#recorded-origin').isVisible(),false);
  assert.equal(await page.locator('#export-analysis').isDisabled(),true);assert.equal(await page.locator('#preview').isDisabled(),true);
  assert.ok((await page.locator('#notice').textContent()).includes('Previous statuses are stale'));
  record('source_edit_invalidates_analysis_and_recorded_provenance');await screenshot(page,'06-edited-source-stale.png');
  assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);assert.ok(requests.every(r=>r.origin===origin));
  assert.ok(requests.filter(r=>r.method==='POST').every(r=>r.path==='/api/v6h/analyze'));
  for(const [name,binding] of Object.entries(bindings))assert.equal(fileHash(name),binding.sha256,'Source changed '+name);
  record('local_only_and_late_source_integrity',{browser_errors:0,blocked_remote_requests:0,provider_calls:0});passed=true;
 }catch(error){
  errors.push({stage,message:error.message,stack:error.stack});
  if(context){const page=context.pages()[0];if(page)try{await screenshot(page,'failure.png');}catch{}}
  console.error(error.stack);process.exitCode=1;
 }finally{
  if(context)try{await context.tracing.stop({path:path.join(out,'trace.zip')});}catch(e){errors.push({cleanup:'trace',message:e.message});passed=false;}
  if(browser)await browser.close();
  if(server&&server.exitCode===null){server.kill();await Promise.race([new Promise(r=>server.once('exit',r)),delay(5000)]);}
  const serverStopped=!server||server.exitCode!==null||server.signalCode!==null;
  if(serverLog!==undefined)fs.closeSync(serverLog);
  const receipt={schema:'retrace.frontier-v6n-browser-qa.v1',passed:passed&&serverStopped,stage,
    provider_calls:0,source_bindings:bindings,screenshots,checks,errors,blocked_remote_requests:blocked,
    localhost_requests:requests,server_pid:server?.pid??null,server_stopped:serverStopped,
    browser_closed:true,headless:true,browser:'Microsoft Edge via bundled Playwright',
    selection_scope:'Deterministic representative UI conditions only; not additional empirical accuracy estimates',
    automated_interaction_checks:true,visual_review_complete:false,human_review_complete:false};
  const trace=path.join(out,'trace.zip');if(fs.existsSync(trace))receipt.trace={path:rel(trace),sha256:hash(fs.readFileSync(trace)),bytes:fs.statSync(trace).size};
  fs.writeFileSync(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({passed:receipt.passed,checks:checks.length,screenshots:screenshots.length,receipt:rel(path.join(out,'receipt.json')),server_stopped:serverStopped}));
  if(!receipt.passed)process.exitCode=1;
 }
})();
