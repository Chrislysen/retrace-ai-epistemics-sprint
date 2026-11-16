'use strict';
const $ = id => document.getElementById(id);
const copy = value => JSON.parse(JSON.stringify(value));
const labels = {supported: 'Supported under declared links', not_supported: 'Unsupported', contested: 'Contested', insufficient_provenance: 'Insufficient provenance'};
let current = null, activeBrief = null, dirty = true, busy = false, generation = 0;
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = String(text); if (className) el.className = className; return el; }
function button(text, action) { const el = node('button', text); el.type = 'button'; el.disabled = busy; el.addEventListener('click', action); return el; }
function error(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
function notice(message) { $('notice').textContent = message; }
function setBusy(value) {
  busy = value; document.body.classList.toggle('busy', value);
  document.querySelectorAll('button,input[type="checkbox"]').forEach(el => { el.disabled = value; });
  if (!value) { $('export-analysis').disabled = !current || dirty; $('preview').disabled = !current || dirty; }
}
function edited() { dirty = true; generation += 1; $('analysis').hidden = true; $('empty').hidden = false; $('export-analysis').disabled = true; $('preview').disabled = true; notice('Declaration edited. Previous statuses are stale; analyze again to clear old answers and vetoes.'); }
function readBrief() {
  const source = JSON.parse($('bundle').value);
  if (!source || typeof source !== 'object' || Array.isArray(source) || Object.hasOwn(source, 'source_ir')) throw new Error('Use a source bundle object; place source_ir in its separate editor.');
  return {...source, source_ir: JSON.parse($('ir').value)};
}
function loadBrief(brief) { const source = copy(brief), ir = source.source_ir || {}; delete source.source_ir; $('bundle').value = JSON.stringify(source, null, 2); $('ir').value = JSON.stringify(ir, null, 2); $('proposal').value = ''; current = null; activeBrief = null; edited(); }
async function post(path, body) { const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Local request failed'); return result; }
async function analyze(nextState) {
  if (busy) return; let brief; try { brief = readBrief(); } catch (e) { error(e.message); return; }
  const fresh = dirty, token = ++generation, payload = {brief, state: fresh ? {} : (nextState || current?.state || {})};
  if (!fresh && current) payload.expected_fingerprint = current.declaration_fingerprint;
  setBusy(true); error('');
  try { const result = await post('/api/v6h/analyze', payload); if (token !== generation) return; current = result; activeBrief = brief; dirty = false; render(); notice(fresh ? 'New declaration analyzed; answers and vetoes start afresh. Meaning and source completeness remain unverified.' : 'Updated only the selected answer or veto. Every other state component remains in force.'); }
  catch (e) { if (token === generation) { error(e.message); if (current && !dirty) render(); } }
  finally { setBusy(false); }
}
function change(mutator) { if (!current || dirty || busy) return; const state = copy(current.state); mutator(state); analyze(state); }
function listToggle(state, field, id, value) { const set = new Set(state[field]); value ? set.add(id) : set.delete(id); state[field] = [...set].sort(); }
function yesNo(value) { return value === null ? 'outside comparison bound' : value ? 'yes' : 'no'; }
function modal(value) { const all = Array.isArray(value) ? value[0] : value.box_supported, some = Array.isArray(value) ? value[1] : value.diamond_supported; return all ? 'all completions support' : some ? 'some completions support' : 'no completion has grounded support'; }
function render() {
  $('empty').hidden = true; $('analysis').hidden = false; $('computed').hidden = !current.ready;
  $('provenance').textContent = current.provenance === 'constructed_offline_demo' ? 'CONSTRUCTED DEMO · NOT A MODEL RESULT' : 'SUPPLIED INTERPRETATION · UNVERIFIED MEANING';
  $('title').textContent = activeBrief.title || 'Four-state source review';
  $('count').textContent = `${current.candidate_ids.length} / ${current.compilation.candidate_count}`;
  $('summary').textContent = current.ready ? `${current.candidate_ids.length} declared readings remain. Exact source spans are checked; neither citations nor unanimity certify source truth.` : 'Known identifier dispositions are missing. Decision claims are withheld.';
  $('inventory-gap').hidden = current.ready; $('inventory-text').textContent = 'Missing dispositions: ' + current.compilation.registry_coverage_gaps.join(', ');
  $('preview-result').hidden = true; $('citation').hidden = true;
  if (current.ready) { renderDecisions(); renderQuestions(); renderRecords(); renderRobustness(); renderHamming($('hamming2'), current.hamming2); renderTyped($('typed-release'), current.typed_veto_release); }
  renderSource(); renderClauses();
}
function renderDecisions() {
  const box = $('decisions'); box.replaceChildren();
  for (const [id, row] of Object.entries(current.decisions)) {
    const card = node('article', undefined, 'decision ' + (row.interpretations_disagree_on_status || row.state === 'contested' || row.state === 'insufficient_provenance' ? 'disputed' : ''));
    card.append(node('h3', id), node('div', row.interpretations_disagree_on_status ? 'Interpretations disagree' : labels[row.state], 'status'));
    card.append(node('p', Object.entries(row.status_counts).map(([s, n]) => `${labels[s]}: ${n}`).join(' · ')));
    card.append(node('p', `Support in every completion: ${yesNo(row.box_supported)}. Support in any completion: ${yesNo(row.diamond_supported)}.`));
    card.append(node('p', `Same decision across aligned readings: ${yesNo(row.interpretation_invariant)}. An invariant unresolved status can still need provenance review.`, 'small'));
    const detail = document.createElement('details'); detail.append(node('summary', 'Inspect per-reading status'), node('pre', JSON.stringify(row.by_candidate, null, 2), 'output')); card.append(detail); box.append(card);
  }
}
function renderQuestions() {
  const box = $('question'); box.replaceChildren(); const planner = current.planner, q = planner.next_question;
  if (q) {
    box.append(node('h3', q.label), node('p', `Worst-case remaining declared question cost: ${q.worst_case_cost}. This question costs ${q.cost}.`, 'hint'));
    const actions = node('div', undefined, 'button-row');
    for (const [label, value] of [['Yes', true], ['No', false], ['Unknown', null]]) actions.append(button(label, () => change(state => { state.answers[q.id] = value; })));
    box.append(actions);
  } else box.append(node('h3', planner.possible ? 'No further reading question changes the current status vector.' : 'Available questions cannot settle the current status vector.'), node('p', 'Contested arguments or unidentified ancestry can remain. This is not a completeness or truth certificate.', 'hint'));
  const answers = $('answers'); answers.replaceChildren();
  for (const [id, answer] of Object.entries(current.state.answers)) {
    const row = node('div', undefined, 'answer-item'); row.append(node('span', `${id}: ${answer === null ? 'Unknown — all readings retained by this answer' : answer ? 'Yes' : 'No'}`), button('Reopen', () => change(state => { delete state.answers[id]; }))); answers.append(row);
  }
}
function check(label, checked, action) { const input = document.createElement('input'); input.type = 'checkbox'; input.checked = checked; input.disabled = busy; input.setAttribute('aria-label', label); input.addEventListener('change', () => action(input.checked)); return input; }
function renderRecords() {
  const docs = $('documents'); docs.replaceChildren();
  for (const group of activeBrief.documents || []) { const label = node('label', undefined, 'document-toggle'); label.append(check('Document veto ' + group.label, current.state.revoked_documents.includes(group.id), value => change(state => listToggle(state, 'revoked_documents', group.id, value))), node('span', group.label)); docs.append(label); }
  const records = $('records'); records.replaceChildren();
  for (const [id, flags] of Object.entries(current.record_flags)) {
    const values = Object.values(flags.by_candidate), count = key => `${values.filter(v => v[key]).length}/${values.length}`;
    const row = document.createElement('tr'); row.append(node('td', id), node('td', count('original_active')), node('td', count('effective_active')),
      node('td', `all: ${count('usable_in_all_ancestry_completions')} · some: ${count('usable_in_some_ancestry_completions')}`));
    for (const [field, flag] of [['revoked_passages', 'passage_veto'], ['scenario_withdrawals', 'scenario_veto']]) { const cell = document.createElement('td'); cell.append(check(field + ' ' + id, flags[flag], value => change(state => listToggle(state, field, id, value)))); row.append(cell); }
    row.append(node('td', flags.document_veto ? 'active' : 'none'), node('td', flags.document_veto || flags.passage_veto || flags.scenario_veto ? 'Revoked — falsity not asserted' : 'No veto')); records.append(row);
  }
}
function renderRobustness() {
  const box = $('robustness'); box.replaceChildren(); const result = current.robustness;
  if (result.status !== 'evaluated') { box.append(node('p', 'Exact search unavailable: ' + result.reason)); return; }
  for (const row of result.decisions) {
    const line = node('div', undefined, 'exposure-row');
    line.append(node('span', `${row.decision}: ${!row.applicable ? 'not currently supported in every completion' : row.withdraw === null ? 'no break within declared withdrawals' : `smallest break k=${row.minimum_k} · ${row.withdraw.join(', ')}`}`));
    if (row.withdraw !== null) line.append(button('Apply additional withdrawal', () => change(state => { state.scenario_withdrawals = [...new Set([...state.scenario_withdrawals, ...row.withdraw])].sort(); })));
    box.append(line);
    if (row.applicable) box.append(node('p', `Survives every one-record withdrawal: ${yesNo(row.survives_all_k1)}; every two-record withdrawal: ${yesNo(row.survives_all_k2)}.`, 'small'));
  }
}
function renderHamming(box, result) {
  box.replaceChildren();
  if (!result || result.status !== 'evaluated') { box.append(node('p', 'Diagnostic unavailable: ' + (result?.reason || 'incomplete comparison'))); return; }
  if (!result.witnesses.length) box.append(node('p', 'No matching two-change witness within the declared scope.'));
  for (const row of result.witnesses) { const line = node('div', undefined, 'clause'); line.append(node('strong', `${row.decision}: hypothetically enable ${row.enable}, then withdraw ${row.withdraw}`),
      node('p', `${modal(row.baseline)} → ${modal(row.enabled)} → ${modal(row.enabled_and_withdrawn)}. Not applied.`));
    if (row.proposed_enabled_and_withdrawn) line.append(node('p', `Proposed family after the same hypothetical changes: ${modal(row.proposed_enabled_and_withdrawn)}.`)); box.append(line); }
}
function renderSource() {
  const box = $('source-docs'); box.replaceChildren();
  for (const doc of activeBrief.source_documents) { const detail = document.createElement('details'); detail.append(node('summary', doc.title || doc.id), node('p', doc.id, 'small'), node('pre', doc.text, 'source-prose')); box.append(detail); }
}
function renderTyped(box, result) {
  box.replaceChildren();
  if (!result || result.status !== 'evaluated') { box.append(node('p', 'Restoration diagnostic unavailable: ' + (result?.reason || 'incomplete comparison'))); return; }
  if (!result.witnesses.length) box.append(node('p', 'No matching named-veto release and withdrawal pair in this state.'));
  for (const row of result.witnesses) {
    const line = node('div', undefined, 'clause');
    line.append(node('strong', `${row.decision}: hypothetically release ${row.release.kind} veto ${row.release.id}, then withdraw ${row.withdraw}`),
      node('p', `Current: ${modal(row.baseline)}. Release alone: ${modal(row.release_only)}. Both actions: ${modal(row.joint)}. Not applied.`));
    if (row.proposed_joint) line.append(node('p', `Proposed family with both actions: ${modal(row.proposed_joint)}. Neither single action in this pair exposed that loss of agreement; no global minimum is claimed.`));
    box.append(line);
  }
}
function expression(expr) { if (expr.ref !== undefined) return expr.ref; if (expr.const !== undefined) return expr.const ? 'unconditional warrant' : 'no warrant'; if (expr.unless) return `(${expression(expr.unless.support)} UNLESS ${expression(expr.unless.undercutter)})`; const op = expr.all ? ' AND ' : ' OR '; return '(' + (expr.all || expr.any).map(expression).join(op) + ')'; }
function citation(id) {
  const span = current.source_segments.find(s => s.span_id === id); if (!span) return;
  const box = $('citation'); box.replaceChildren(); box.hidden = false;
  box.append(node('strong', `${span.document_id} · code points ${span.start}–${span.end} · ${span.span_id}`), node('p', span.text)); box.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}
function renderClauses() {
  const box = $('clauses'); box.replaceChildren();
  for (const p of current.compilation.original_ir.propositions) {
    const card = node('article', undefined, 'clause'); card.append(node('div', `${p.id} · ${p.target} · ${p.scope}${Object.keys(p.when).length ? ' · when ' + JSON.stringify(p.when) : ''}`, 'clause-head'));
    let text = p.kind === 'support' ? `positive: ${expression(p.body.positive)}\nnegative (not ${p.target}): ${expression(p.body.negative)}` : p.kind === 'origin' ? `${p.body.kind} · required known parents: ${p.body.parents.join(' AND ') || 'none named'}` : p.kind === 'eligibility' ? `original local eligibility: ${p.body.active}` : `requires: ${p.body.requires.join(' AND ')}`;
    card.append(node('code', text)); for (const id of p.citations) card.append(button('View source span', () => citation(id))); box.append(card);
  }
}
async function preview() {
  if (!current || dirty || busy) return; let proposal; try { proposal = JSON.parse($('proposal').value); } catch (e) { error('Invalid proposal JSON: ' + e.message); return; }
  const token = ++generation; setBusy(true); error(''); $('preview-result').hidden = true;
  try {
    const result = await post('/api/v6h/refuter-preview', {brief: activeBrief, state: current.state, expected_fingerprint: current.declaration_fingerprint, proposal}); if (generation !== token) return;
    const box = $('preview-result'); box.replaceChildren(); box.hidden = false;
    box.append(node('h3', result.status === 'abstained' ? 'Refuter abstained · completeness not certified' : 'Preview only · active analysis unchanged'), node('p', result.scope));
    box.append(node('p', `Raw model warning score: ${result.raw_uncalibrated_warning_score}. This score is not calibrated or used as proof.`, 'small'));
    if (result.reason) box.append(node('p', result.reason));
    for (const location of result.objection_locations) { const detail = document.createElement('details'); detail.append(node('summary', `Source-located objection: ${location.document_id}`), node('p', `Code points ${location.start}–${location.end} · quote SHA ${location.quote_sha256}`, 'small'), node('pre', location.text, 'source-prose')); box.append(detail); }
    if (result.declaration_comparison) box.append(node('p', `${result.declaration_comparison.novel_proposed_readings} proposed readings are absent from the current declaration. Difference from that declaration does not establish a source omission.`));
    const impact = result.decision_impact;
    if (impact) {
      box.append(node('h3', 'Conditional effect of adding proposed readings'));
      if (impact.status !== 'evaluated') box.append(node('p', impact.reason));
      else for (const row of impact.decisions) box.append(node('p', row.withdraw === null ? `${row.decision}: no new loss of unanimity within these withdrawals.` : `${row.decision}: smallest additional withdrawal k=${row.minimum_k} (${row.withdraw.join(', ') || 'none needed'}); ${modal(row.current)} → ${modal(row.augmented)} if the proposed readings are added.`));
    }
    if (result.hamming2) { box.append(node('h3', 'Hypothetical activation diagnostic')); const h = node('div'); renderHamming(h, result.hamming2); box.append(h); }
    if (result.typed_veto_release) { box.append(node('h3', 'Hypothetical named-veto release')); const t = node('div'); renderTyped(t, result.typed_veto_release); box.append(t); }
    const detail = document.createElement('details'); detail.append(node('summary', 'Inspect complete preview audit'), node('pre', JSON.stringify(result, null, 2), 'output')); box.append(detail);
  } catch (e) { if (generation === token) error('Proposal rejected before comparison. Active state unchanged. ' + e.message); }
  finally { setBusy(false); }
}
function download(name, value) { const a = document.createElement('a'), url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'})); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
$('bundle').addEventListener('input', edited); $('ir').addEventListener('input', edited);
$('proposal').addEventListener('input', () => { generation += 1; $('preview-result').hidden = true; });
$('analyze').addEventListener('click', () => analyze()); $('preview').addEventListener('click', preview);
$('clear-scenario').addEventListener('click', () => change(state => { state.scenario_withdrawals = []; }));
$('reset-answers').addEventListener('click', () => change(state => { state.answers = {}; }));
$('demo').addEventListener('click', async () => {
  if (busy) return; const token = ++generation; let loaded = false; setBusy(true); error('');
  try { const response = await fetch('/api/v6h/demo'); if (!response.ok) throw new Error('Demo could not be loaded'); const brief = await response.json(); if (generation !== token) return; loadBrief(brief); loaded = true; }
  catch (e) { if (generation === token) error(e.message); } finally { setBusy(false); }
  if (loaded) analyze();
});
$('import').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', async () => { const file = $('file').files[0]; if (!file || busy) return; const token = ++generation; setBusy(true); try { if (file.size > 2097152) throw new Error('Bundle exceeds the 2 MB input bound'); const brief = JSON.parse(await file.text()); if (token !== generation) return; loadBrief(brief); error(''); notice('Imported locally. Review the source and IR, then analyze a fresh state.'); } catch (e) { if (token === generation) error(e.message); } finally { $('file').value = ''; setBusy(false); } });
$('export-bundle').addEventListener('click', () => { try { download('retrace-v6h-bundle.json', readBrief()); } catch (e) { error(e.message); } });
$('export-analysis').addEventListener('click', () => { if (current && !dirty) download('retrace-v6h-analysis.json', current); });
$('prepare').addEventListener('click', async () => {
  if (busy) return; let brief; try { brief = JSON.parse($('bundle').value); } catch (e) { error(e.message); return; }
  const token = ++generation; setBusy(true); error('');
  try { const result = await post('/api/v6h/source', {brief}); if (generation !== token) return; $('prompt-text').value = result.instructions + '\n\n' + JSON.stringify(result.source, null, 2); $('prompt-dialog').showModal(); }
  catch (e) { if (generation === token) error(e.message); } finally { setBusy(false); }
});
$('close-prompt').addEventListener('click', () => $('prompt-dialog').close());
$('copy-prompt').addEventListener('click', async () => { try { await navigator.clipboard.writeText($('prompt-text').value); $('copy-prompt').textContent = 'Copied'; } catch { $('prompt-text').focus(); $('prompt-text').select(); $('copy-prompt').textContent = 'Select all and copy'; } });
setBusy(false);
