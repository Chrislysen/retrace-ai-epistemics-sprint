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
const adapter = fs.readFileSync(path.join(root, 'web/v6k/evidence.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'web/v6k/index.html'), 'utf8');
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
  vm.runInContext(adapter, context, {filename: 'evidence.js'});
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

function observation(name, loadable = true) {
  const brief = {id: name, title: `Recorded ${name}`, source_documents: [{id: 'DOC', text: '<img src=x onerror=alert(1)>'}],
    registry: {evidence: [], claims: [], decisions: []}, source_ir: {propositions: []}};
  const row = {key: name, slot_id: `fixture::${name}`, case_id: `case-${name}`, model: 'invented-model', provider_completed: true, status: loadable ? 'admitted' : 'invalid_ir',
    strict_bare_json: true, candidate_count: loadable ? 1 : 0, registry_coverage_gaps: []};
  return {row, value: {metadata: row, brief: loadable ? brief : null,
    source_documents: brief.source_documents, raw_output_text: '<script>not executable</script>', partial_output_text: '',
    provenance: {fixture: true,raw_output_text_sha256:`raw-${name}`,public_source_sha256:`source-${name}`}}};
}

async function started(h, observations) {
  await h.respond(h.pending('/api/v6k/catalog'), {available: true, entries: observations.map(x => x.row), counts: {admitted: observations.length}});
  await h.respond(h.pending(`/api/v6k/catalog/${observations[0].row.key}`), observations[0].value);
}
function analysis(brief) {
  return {ready: false, candidate_ids: ['world'], compilation: {candidate_count: 1, registry_coverage_gaps: ['FIXTURE'], original_ir: brief.source_ir},
    state: {answers: {}, revoked_documents: [], revoked_passages: [], scenario_withdrawals: []}, provenance: 'supplied_interpretation'};
}
async function loaded(h, item) {
  const click = h.nodes.get('catalog-load').dispatch('click');
  const request = h.pending('/api/v6h/analyze');
  assert.deepEqual(JSON.parse(request.options.body).state, {});
  await h.respond(request, analysis(item.value.brief)); await click; await flush();
}

test('absent catalog remains explicit and cannot load fabricated observations', async () => {
  const h = harness(); await h.respond(h.pending('/api/v6k/catalog'), {available: false, scope: 'No completed export'});
  assert.equal(h.nodes.get('catalog-message').textContent, 'No completed export');
  assert.equal(h.nodes.get('catalog-load').disabled, true); assert.equal(h.requests.length, 1);
});

test('late observation response cannot replace the newer selected row', async () => {
  const h = harness(), a = observation('A'), b = observation('B');
  await h.respond(h.pending('/api/v6k/catalog'), {available: true, entries: [a.row, b.row], counts: {admitted: 2}});
  const old = h.pending('/api/v6k/catalog/A');
  h.nodes.get('catalog-case').value = b.row.case_id;
  await h.nodes.get('catalog-case').dispatch('change'); await flush();
  await h.respond(h.pending('/api/v6k/catalog/B'), b.value);
  await h.respond(old, a.value);
  assert.match(h.nodes.get('catalog-entry').textContent, /case-B/);
  assert.doesNotMatch(h.nodes.get('catalog-entry').textContent, /case-A/);
  assert.equal(h.nodes.get('recorded-origin').hidden, true);
});

test('raw/source text remains literal and invalid IR cannot be loaded', async () => {
  const h = harness(), bad = observation('BAD', false); await started(h, [bad]);
  assert.equal(h.nodes.get('catalog-load').disabled, true);
  assert.equal(h.nodes.get('catalog-download').disabled, true);
  assert.match(h.nodes.get('catalog-entry').textContent, /<script>not executable<\/script>/);
  await h.nodes.get('catalog-load').dispatch('click');
  assert.equal(h.requests.some(x => x.url === '/api/v6h/analyze'), false);
});

test('loading recorded IR clears prior state and labels only completed matching analysis', async () => {
  const h = harness(), a = observation('A'); await started(h, [a]);
  h.eval("current={state:{answers:{old:true},revoked_documents:['old'],revoked_passages:[],scenario_withdrawals:['old']}};dirty=false;");
  await loaded(h, a);
  assert.equal(h.nodes.get('recorded-origin').hidden, false);
  assert.match(h.nodes.get('recorded-origin').textContent, /case-A/);
  assert.match(h.nodes.get('recorded-origin').textContent, /MEANING UNVERIFIED/);
});

test('editing source during pending analysis prevents stale output and provenance', async () => {
  const h = harness(), a = observation('A'); await started(h, [a]);
  const click = h.nodes.get('catalog-load').dispatch('click'), request = h.pending('/api/v6h/analyze');
  h.nodes.get('bundle').value = '{}'; await h.nodes.get('bundle').dispatch('input');
  await h.respond(request, analysis(a.value.brief)); await click;
  assert.equal(h.nodes.get('recorded-origin').hidden, true); assert.equal(h.eval('current'), null);
  assert.equal(h.nodes.get('analysis').hidden, true);
});

test('failed analysis cannot acquire recorded provenance', async () => {
  const h = harness(), a = observation('A'); await started(h, [a]);
  const click = h.nodes.get('catalog-load').dispatch('click');
  await h.respond(h.pending('/api/v6h/analyze'), {error: 'Invented rejection'}, false); await click;
  assert.equal(h.nodes.get('recorded-origin').hidden, true); assert.equal(h.eval('current'), null);
  assert.match(h.nodes.get('error').textContent, /Invented rejection/);
});

test('source/IR edits and demo/import actions clear recorded provenance', async () => {
  for (const [id, event] of [['bundle', 'input'], ['ir', 'input'], ['demo', 'click'], ['import', 'click'], ['file', 'change']]) {
    const h = harness(), a = observation('A'); await started(h, [a]); await loaded(h, a);
    const action = h.nodes.get(id).dispatch(event);
    await flush(); assert.equal(h.nodes.get('recorded-origin').hidden, true, `${id} clears origin`);
    if (id === 'demo') await h.respond(h.pending('/api/v6h/demo'), {error: 'Invented demo failure'}, false);
    await action;
  }
});

test('selecting another observation alone does not relabel the active workbench', async () => {
  const h = harness(), a = observation('A'), b = observation('B'); await started(h, [a, b]); await loaded(h, a);
  h.nodes.get('catalog-case').value = b.row.case_id; await h.nodes.get('catalog-case').dispatch('change'); await flush();
  await h.respond(h.pending('/api/v6k/catalog/B'), b.value);
  assert.match(h.nodes.get('catalog-entry').textContent, /case-B/);
  assert.match(h.nodes.get('recorded-origin').textContent, /case-A/);
  assert.equal(h.eval('activeBrief.id'), 'A');
});

function rejectedDiagnosis(item) {
  return {schema:'retrace.source-diagnostics.v6k.v1',compile_admitted:false,parser_admitted:false,
    strict_bare_json:null,raw_text_sha256:item.value.provenance.raw_output_text_sha256,
    source_packet_sha256:item.value.provenance.public_source_sha256,slot_id:item.row.slot_id,
    original_error:{type:'ValueError',message:'<script>literal rejected text</script>'},
    localization_status:'localized',diagnostics:[{kind:'malformed_closing_fence_boundary',line:3,column:7}]};
}

test('local rejection review never loads or repairs the observed interpretation', async () => {
  const h=harness(),bad=observation('BAD',false);await started(h,[bad]);
  const original=bad.value.raw_output_text;
  assert.equal(h.nodes.get('catalog-diagnose').disabled,false);
  const click=h.nodes.get('catalog-diagnose').dispatch('click');
  await h.respond(h.pending('/api/v6k/catalog/BAD/diagnosis'),rejectedDiagnosis(bad));await click;
  assert.match(h.nodes.get('catalog-diagnosis').textContent,/Local rejection review · no repair/);
  assert.match(h.nodes.get('catalog-diagnosis').textContent,/<script>literal rejected text<\/script>/);
  assert.equal(bad.value.raw_output_text,original);assert.equal(h.eval('current'),null);
  assert.equal(h.nodes.get('catalog-load').disabled,true);
  assert.equal(h.requests.some(x=>x.url==='/api/v6h/analyze'),false);
});

test('diagnosis with a different source binding is rejected', async () => {
  const h=harness(),bad=observation('BAD',false);await started(h,[bad]);
  const click=h.nodes.get('catalog-diagnose').dispatch('click');
  await h.respond(h.pending('/api/v6k/catalog/BAD/diagnosis'),{...rejectedDiagnosis(bad),source_packet_sha256:'other-source'});await click;
  assert.match(h.nodes.get('catalog-diagnosis').textContent,/does not match/);
  assert.doesNotMatch(h.nodes.get('catalog-diagnosis').textContent,/literal rejected text/);
  assert.equal(h.nodes.get('catalog-load').disabled,true);
});

test('late rejection detail cannot appear under a newer selected observation', async () => {
  const h=harness(),bad=observation('BAD',false),next=observation('NEXT',false);await started(h,[bad,next]);
  const click=h.nodes.get('catalog-diagnose').dispatch('click'),old=h.pending('/api/v6k/catalog/BAD/diagnosis');
  h.nodes.get('catalog-case').value=next.row.case_id;await h.nodes.get('catalog-case').dispatch('change');await flush();
  await h.respond(h.pending('/api/v6k/catalog/NEXT'),next.value);
  await h.respond(old,rejectedDiagnosis(bad));await click;
  assert.match(h.nodes.get('catalog-entry').textContent,/case-NEXT/);
  assert.equal(h.nodes.get('catalog-diagnosis').hidden,true);
  assert.equal(h.nodes.get('catalog-diagnose').disabled,false);
});

test('completed admitted and unavailable provider outputs cannot be diagnosed as rejected IR', async () => {
  for (const mode of ['admitted','provider_failure']) {
    const h=harness(),item=observation('A',mode==='admitted');
    if(mode==='provider_failure'){item.row.status=mode;item.row.provider_completed=false;}
    await started(h,[item]);assert.equal(h.nodes.get('catalog-diagnose').disabled,true);
    await h.nodes.get('catalog-diagnose').dispatch('click');
    assert.equal(h.requests.some(x=>x.url.endsWith('/diagnosis')),false);
  }
});
