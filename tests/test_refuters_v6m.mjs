// Invented DOM/HTTP fixtures. Executes the unchanged workbench and new adapter;
// no browser, real network, model output, or empirical catalog is used.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import test from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const app = fs.readFileSync(path.join(root, 'web/v6h/app.js'), 'utf8');
const adapter = fs.readFileSync(path.join(root, 'web/v6m/refuters.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'web/v6m/index.html'), 'utf8');
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

function harness() {
  const nodes = new Map(), all = [], observers = [], requests = [];
  class Element {
    constructor(tag, id = '') {
      this.tagName = tag.toUpperCase(); this.id = id; this.children = []; this.listeners = [];
      this.hidden = false; this.disabled = false; this.files = []; this.value = ''; this._text = '';
      this.classList = {toggle() { for (const observer of observers) queueMicrotask(observer); }};
      all.push(this);
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(x => x.textContent ?? String(x)).join(''); }
    set innerHTML(_) { throw new Error('Untrusted HTML insertion is forbidden in this fixture'); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) {
      this._text = ''; this.children = children;
      if (this.tagName === 'SELECT') this.value = children[0]?.value ?? '';
    }
    addEventListener(type, fn, capture = false) { this.listeners.push({type, fn, capture}); }
    dispatch(type) {
      return Promise.all(this.listeners.filter(x => x.type === type)
        .sort((a, b) => Number(b.capture) - Number(a.capture)).map(x => x.fn({target: this})));
    }
    click() { return this.dispatch('click'); }
    setAttribute(key, value) { this[key] = value; }
    scrollIntoView() {} focus() {} select() {} showModal() {} close() {}
  }
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/gi)) {
    const el = new Element(match[1], match[3]); el.hidden = /\bhidden\b/.test(match[2]);
    el.disabled = /\bdisabled\b/.test(match[2]); nodes.set(el.id, el);
  }
  const body = new Element('body');
  const context = vm.createContext({
    document: {body, getElementById(id) { assert.ok(nodes.has(id), `Known element ${id}`); return nodes.get(id); },
      createElement(tag) { return new Element(tag); },
      querySelectorAll() { return all.filter(x => x.tagName === 'BUTTON' || x.type === 'checkbox'); }},
    MutationObserver: class { constructor(fn) { this.fn = fn; } observe() { observers.push(this.fn); } },
    fetch(url, options) { return new Promise((resolve, reject) => requests.push({url, options, resolve, reject, settled: false})); },
    setTimeout() {}, URL: {createObjectURL() { return 'blob:invented'; }, revokeObjectURL() {}},
    Blob: class {}, navigator: {clipboard: {async writeText() {}}}, console,
  });
  vm.runInContext(app, context, {filename: 'frozen-app.js'});
  vm.runInContext(adapter, context, {filename: 'refuters.js'});
  const pending = url => {
    const request = requests.find(x => x.url === url && !x.settled);
    assert.ok(request, `Pending local request ${url}`); return request;
  };
  const respond = async (request, value, ok = true) => {
    request.settled = true;
    request.resolve({ok, status: ok ? 200 : 409, async json() { return structuredClone(value); }});
    await flush();
  };
  return {nodes, requests, pending, respond, context, eval: code => vm.runInContext(code, context)};
}


function observation(key='one', status='source_located_proposal') {
  return {metadata:{key,case_id:key,model:'model',condition:'adversarial_refuter',selection_view:'first_attempt',status},
    source_documents:[{id:'source','text':'<script>source text</script>'}],registry:{},supplied_candidates:[{id:'authored',graph:{}}],
    raw_output_text:'{"status":"objection","status":"duplicate"}',partial_output_text:'',scope:'Controlled authored seeds, not upstream IR.',
    provenance:{hash:'preserved'},inspection:status==='source_located_proposal'?{
      gate:{status:'source_located_proposal',strict_bare_json:true,raw_warning_score:.8,locations:[{document_id:'source',start:0,end:3,text:'<b>exact</b>'}]},
      preview:{status:'preview_only',declaration_comparison:{seed_distinct:1,proposal_distinct:1,union_distinct:2,novel_proposed_readings:1},
        modal_summary:{status:'evaluated',decisions:{D:{seed:{box_supported:true,diamond_supported:true},augmented:{box_supported:false,diamond_supported:true}}}},
        decision_impact:{status:'evaluated',decisions:[{decision:'D',minimum_k:1,withdraw:['A'],current:{box_supported:true,diamond_supported:true},augmented:{box_supported:false,diamond_supported:true}}]},
        hamming2:{status:'evaluated',witnesses:[]}},status:'source_located_proposal'}:null};
}
const row = (key,status='source_located_proposal') => ({key,case_id:key,model:'model',status});
async function start(h,rows=[row('one')]) {
  await h.respond(h.pending('/api/v6m/refuters'),{available:true,entries:rows,case_order:rows.map(r=>r.case_id),counts:{source_located_proposal:rows.length}});
}
test('all interaction stays GET-only and never loads or replaces workbench',async()=>{
  const h=harness();await start(h);await h.respond(h.pending('/api/v6m/refuters/one'),observation());
  const content=h.nodes.get('refuter-entry').textContent;
  assert.match(content,/G union P/);assert.match(content,/Every seed reading remains/);assert.match(content,/k=1/);
  assert.match(content,/not upstream IR/);
  assert.equal(h.eval('current'),null);assert.equal(h.nodes.get('ir').value,'');
  assert.ok(h.requests.every(r=>r.options===undefined));
});

test('untrusted source and proposal remain text with no HTML interpretation',async()=>{
  const h=harness();await start(h);await h.respond(h.pending('/api/v6m/refuters/one'),observation());
  const content=h.nodes.get('refuter-entry').textContent;
  assert.match(content,/<script>source text<\/script>/);assert.match(content,/<b>exact<\/b>/);
  assert.match(content,/"status":"objection","status":"duplicate"/);
  assert.equal(h.requests.length,2);
});
test('failed first attempt remains visible and cannot load a graph',async()=>{
  const h=harness();await start(h,[row('one','provider_failure')]);
  const value=observation('one','provider_failure');value.raw_output_text='';value.partial_output_text='retained excluded fragment';
  await h.respond(h.pending('/api/v6m/refuters/one'),value);
  const content=h.nodes.get('refuter-entry').textContent;
  assert.match(content,/Provider failure/);assert.match(content,/excluded from analysis/);
  assert.doesNotMatch(content,/Conditional effect of adding/);assert.equal(h.eval('current'),null);
});
test('gate admission and unavailable mechanism remain distinct',async()=>{
  const h=harness();await start(h);const value=observation();
  value.inspection.preview.decision_impact={status:'unavailable',reason:'Exact search bound'};
  await h.respond(h.pending('/api/v6m/refuters/one'),value);
  const content=h.nodes.get('refuter-entry').textContent;
  assert.match(content,/Source-located proposal/);assert.match(content,/No absence of effect is inferred/);
});
test('abstention never displays a no-omission certificate',async()=>{
  const h=harness();await start(h,[row('one','abstained')]);const value=observation('one','abstained');
  value.inspection={status:'abstained',gate:{status:'abstained',strict_bare_json:true,locations:[]},preview:null,
    abstention_scope:'Abstention does not certify source completeness or absence of omissions.'};
  await h.respond(h.pending('/api/v6m/refuters/one'),value);
  assert.match(h.nodes.get('refuter-entry').textContent,/does not certify/);
  assert.doesNotMatch(h.nodes.get('refuter-entry').textContent,/Conditional effect/);
});
test('hypothetical pair shows the augmented union separately from proposal alone',async()=>{
  const h=harness();await start(h);const value=observation();
  value.inspection.preview.hamming2={status:'evaluated',witnesses:[{decision:'D',enable:'B',withdraw:'A',
    baseline:[false,false],enabled:[true,true],enabled_and_withdrawn:[true,true],proposed_enabled_and_withdrawn:[false,false],
    augmented_enabled_and_withdrawn:{box_supported:false,diamond_supported:true}}]};
  await h.respond(h.pending('/api/v6m/refuters/one'),value);
  const content=h.nodes.get('refuter-entry').textContent;
  assert.match(content,/after BOTH hypothetical actions, union G \+ P \(all readings: not universally supported; some reading supported: yes\)/);
  assert.match(content,/P alone, not a replacement for G/);assert.equal(h.eval('current'),null);
});
test('late stale selection cannot replace newer observation',async()=>{
  const h=harness();await start(h,[row('one'),row('two')]);const older=h.pending('/api/v6m/refuters/one');
  h.nodes.get('refuter-case').value='two';await h.nodes.get('refuter-case').dispatch('change');
  await h.respond(h.pending('/api/v6m/refuters/two'),observation('two'));
  await h.respond(older,observation('one'));
  assert.match(h.nodes.get('refuter-entry').textContent,/two · model/);
  assert.doesNotMatch(h.nodes.get('refuter-entry').textContent,/one · model/);
});
test('absence or integrity error does not use a constructed replacement',async()=>{
  const h=harness();await h.respond(h.pending('/api/v6m/refuters'),{available:false,scope:'No closed controlled-seed export'});
  assert.match(h.nodes.get('refuter-message').textContent,/No closed/);assert.equal(h.requests.length,1);
  assert.equal(h.nodes.get('refuter-download').disabled,true);
});
