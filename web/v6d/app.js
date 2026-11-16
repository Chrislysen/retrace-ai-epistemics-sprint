'use strict';
const $ = id => document.getElementById(id);
const clone = value => JSON.parse(JSON.stringify(value));
let current = null, currentBrief = null, dirty = true, busy = false, generation = 0;
let catalog = null, selectedRecord = null, catalogGeneration = 0;

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined && text !== null) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}
function button(text, callback, className) {
  const item = node('button', text, className);
  item.type = 'button'; item.disabled = busy;
  item.addEventListener('click', callback); return item;
}
function setError(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
function notice(message) { $('notice').textContent = message; }
function setBusy(value) {
  busy = value; document.body.classList.toggle('busy', value);
  document.querySelectorAll('button').forEach(item => { item.disabled = value; });
  document.querySelectorAll('input[type="checkbox"]').forEach(item => { item.disabled = value; });
  if (!value) {
    $('export-audit').disabled = !current || dirty;
    $('preview-refuter').disabled = !current || dirty;
  }
  updateCatalogButtons();
}
function markDirty() {
  dirty = true; generation += 1;
  $('analysis').hidden = true; $('empty').hidden = false;
  $('export-audit').disabled = true;
  updateCatalogButtons();
  notice('Source edited. Previous answers and statuses are stale. Analyze again to start a fresh state.');
}
function readBrief() {
  const bundle = JSON.parse($('bundle').value);
  if (!bundle || Array.isArray(bundle) || typeof bundle !== 'object') throw new Error('The source bundle must be a JSON object.');
  if (Object.hasOwn(bundle, 'source_ir')) throw new Error('Put source_ir in the separate proposed-interpretation editor.');
  return {...bundle, source_ir: JSON.parse($('ir').value)};
}
async function post(path, payload) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Local request failed.');
  return result;
}
function loadBrief(brief) {
  const bundle = clone(brief); const ir = bundle.source_ir || {};
  delete bundle.source_ir;
  $('bundle').value = JSON.stringify(bundle, null, 2);
  $('ir').value = JSON.stringify(ir, null, 2);
  $('proposal').value = '';
  current = null; currentBrief = null; markDirty();
}
async function analyze(nextState) {
  if (busy) return;
  let brief;
  try { brief = readBrief(); } catch (error) { setError(error.message); return; }
  const wasDirty = dirty, token = ++generation;
  const payload = {brief, state: wasDirty ? {} : (nextState || current?.state || {})};
  if (!wasDirty && current) payload.expected_declaration_fingerprint = current.declaration_fingerprint;
  setError(''); setBusy(true);
  try {
    const result = await post('/api/v6d/analyze', payload);
    if (generation !== token) return;
    current = result; currentBrief = brief; dirty = false;
    render();
    notice(wasDirty ? 'New declaration analyzed. Answers and exclusions start afresh. Source completeness remains unknown.' : 'Updated the declared state. All other answers and vetoes remain in force.');
  } catch (error) {
    if (generation === token) { setError(error.message); if (current && !dirty) render(); }
  } finally { setBusy(false); }
}
function changeState(change) {
  if (!current || dirty || busy) return;
  const state = clone(current.state); change(state); analyze(state);
}
function toggleList(state, field, identifier, enabled) {
  const values = new Set(state[field] || []);
  if (enabled) values.add(identifier); else values.delete(identifier);
  state[field] = [...values].sort();
}
function ratio(values, field) { return `${values.filter(value => value[field]).length} / ${values.length}`; }
function render() {
  $('empty').hidden = true; $('analysis').hidden = false;
  const compiled = current.compilation, stress = current.stress;
  const recorded = current.recorded_provenance;
  $('provenance').textContent = recorded?.status === 'matched_recorded_catalog_declaration'
    ? (recorded.catalog_kind === 'test_fixture_only' ? 'TEST FIXTURE · NOT EMPIRICAL' : `RECORDED ${recorded.model} · ${recorded.case_id} · ${recorded.condition}`)
    : current.provenance === 'constructed_offline_demonstration' ? 'CONSTRUCTED OFFLINE DEMONSTRATION · NO MODEL RESULT' : 'SUPPLIED INTERPRETATION · NOT EXTERNALLY VERIFIED';
  $('analysis-title').textContent = currentBrief.title || 'Source interpretation review';
  $('summary-text').textContent = current.registry_coverage?.missing_disposition_ids.length
    ? 'Interpretation incomplete: known identifier dispositions are missing. Current decision claims are withheld.'
    : stress ? `${stress.candidate_ids.length} of ${compiled.candidate_count} declared interpretations remain. Exact locations are checked; semantic entailment and source completeness are not certified.` : 'A declared unknown source prevents a complete executable graph family.';
  $('world-count').textContent = `${stress ? stress.candidate_ids.length : compiled.candidate_count} / ${compiled.assignment_count}`;
  const inventory = current.registry_coverage;
  $('unresolved').hidden = compiled.status === 'compiled';
  $('inventory-gap').hidden = !inventory?.missing_disposition_ids.length;
  $('inventory-gap-text').textContent = inventory?.missing_disposition_ids.length ? 'Known IDs without a declared disposition: ' + inventory.missing_disposition_ids.join(', ') : '';
  $('computed').hidden = !stress || !current.ready_for_conditional_decision_review;
  const dispositions = $('registry-dispositions'); dispositions.replaceChildren();
  for (const item of inventory?.dispositions || []) dispositions.append(node('p', `${item.id} · ${item.type} · ${item.status.replaceAll('_', ' ')}`, 'small'));
  $('refuter-result').hidden = true; $('exposure-result').hidden = true; $('citation').hidden = true;
  if (stress) { renderDecisions(stress); renderQuestions(stress); renderRecords(stress); renderExposure(); }
  renderClauses(compiled);
  $('export-audit').disabled = false;
  updateCatalogButtons();
}
function renderDecisions(stress) {
  const container = $('decisions'); container.replaceChildren();
  for (const [id, state] of Object.entries(stress.decision_states)) {
    const item = node('article', null, `decision ${state.classification === 'needs_review' ? 'disputed' : state.classification}`);
    item.append(node('h3', id), node('div', state.display_label, 'status'));
    item.append(node('p', `${state.supporting_candidates.length} supported · ${state.unsupported_candidates.length} unsupported declared interpretations. Counts are not probabilities.`));
    const witness = stress.decision_witnesses[id];
    for (const [field, label] of [['minimum_distinguishing', 'Expose disagreement'], ['minimum_break_any', 'Break support in at least one'], ['minimum_break_all', 'Break support in every interpretation']]) {
      const value = witness[field];
      if (value) {
        item.append(button(`${label}: k=${value.k}${value.withdraw.length ? ' · ' + value.withdraw.join(', ') : ' · already differs'}`, () => changeState(next => { next.scenario_withdrawals = [...value.scenario_withdrawals]; })));
      } else {
        item.append(node('div', `${label}: ${field.startsWith('minimum_break') && !witness.break_applicable ? 'not currently invariant-supported' : 'none within this search'}`, 'small'));
      }
    }
    container.append(item);
  }
}
function renderQuestions(stress) {
  const container = $('question'); container.replaceChildren();
  const question = stress.next_question;
  if (question) {
    const declaration = current.question_catalog.find(row => row.choice_id === question.id);
    container.append(node('h3', question.label));
    container.append(node('p', `Worst-case remaining cost with decisive Yes/No answers: ${question.worst_case_cost}. Yes = ${declaration?.true_option}; no = ${declaration?.false_option}. Unknown keeps every remaining interpretation.`, 'hint'));
    const source = document.createElement('details');
    source.append(node('summary', 'Read the source for this question'));
    for (const cite of declaration?.citations || []) {
      source.append(node('p', `${cite.document_id} · code points ${cite.start}–${cite.end}`, 'small'), node('blockquote', cite.quote));
    }
    source.append(node('p', 'This passage locates the declared alternatives. It may leave the answer unresolved; answer only from information you actually have.', 'hint'));
    container.append(source);
    const actions = node('div', null, 'button-row');
    for (const [label, value] of [['Yes', true], ['No', false], ['Unknown', null]]) actions.append(button(label, () => changeState(next => { next.answers[question.id] = value; }), label === 'Yes' ? 'primary' : 'secondary'));
    container.append(actions);
  } else {
    const possible = stress.consensus.clarification.possible;
    container.append(node('h3', possible ? 'No further question is needed for the current target decisions.' : 'The available questions cannot settle every target decision.'));
    container.append(node('p', possible ? 'Other graph details may remain unresolved. Agreement is conditional on this declared family, not complete source knowledge.' : 'Keep the disputed status and review the source or supply a factual clarification. No candidate is silently chosen.', 'hint'));
  }
  const history = $('answers'); history.replaceChildren();
  for (const [id, answer] of Object.entries(current.state.answers)) {
    const item = node('div', null, 'answer-item');
    item.append(node('span', `${id}: ${answer === null ? 'unknown (no filtering)' : answer ? 'yes' : 'no'}`));
    item.append(button('Clear', () => changeState(next => { delete next.answers[id]; })));
    history.append(item);
  }
}
function renderRecords(stress) {
  const documents = $('documents'); documents.replaceChildren();
  for (const doc of currentBrief.documents || []) {
    const label = node('label', null, 'document-toggle'); const input = document.createElement('input');
    input.type = 'checkbox'; input.checked = current.state.revoked_documents.includes(doc.id);
    input.addEventListener('change', () => changeState(next => toggleList(next, 'revoked_documents', doc.id, input.checked)));
    label.append(input, node('span', `Exclude document: ${doc.label} (${doc.evidence_ids.join(', ')})`)); documents.append(label);
  }
  if (!documents.childElementCount) documents.append(node('p', 'No document veto groups declared. Passage exclusions remain available.', 'hint'));
  $('scenario').textContent = current.state.scenario_withdrawals.length ? `Current scenario withdrawals: ${current.state.scenario_withdrawals.join(', ')}` : 'No additional scenario withdrawals.';
  const body = $('records'); body.replaceChildren();
  for (const [id, record] of Object.entries(current.record_states)) {
    const values = Object.values(record.by_candidate), flags = stress.revocation_flags[id], row = node('tr');
    row.append(node('td', id), node('td', ratio(values, 'original_active')), node('td', ratio(values, 'effective_active')), node('td', ratio(values, 'usable')));
    const cell = node('td'), input = document.createElement('input'); input.type = 'checkbox'; input.checked = flags.passage_veto;
    input.setAttribute('aria-label', `Exclude evidence passage ${id}`);
    input.addEventListener('change', () => changeState(next => toggleList(next, 'revoked_passages', id, input.checked)));
    cell.append(input); row.append(cell);
    row.append(node('td', [flags.document_veto ? 'document' : '', flags.scenario_veto ? 'scenario' : ''].filter(Boolean).join(' + ') || '—'));
    body.append(row);
  }
}
function renderExposure() {
  const container = $('exposure'); container.replaceChildren();
  const exposure = current.exposure;
  if (exposure.status !== 'evaluated') { container.append(node('p', exposure.reason, 'hint')); return; }
  container.append(node('p', `${exposure.states_checked_per_candidate} eligibility states checked per retained interpretation. Existing document, passage and scenario exclusions stay locked. Enabling is hypothetical, not restoration or a truth claim.`, 'hint'));
  for (const [id, row] of Object.entries(exposure.decisions)) {
    const item = node('div', null, 'exposure-row'); const witness = row.minimum_changes;
    item.append(node('span', witness ? `${id}: enable [${witness.enable.join(', ')}], withdraw [${witness.withdraw.join(', ')}]` : `${id}: no disagreement under the allowed eligibility changes`));
    if (witness) item.append(button(`Preview ${witness.total_changes} changes`, () => exposurePreview(witness)));
    container.append(item);
  }
}
function expression(value) {
  if (Object.hasOwn(value, 'ref')) return value.ref;
  if (value.none) return 'NO SUPPORT ROUTE';
  const key = value.all ? 'all' : 'any';
  return '(' + value[key].map(expression).join(key === 'all' ? ' AND ' : ' OR ') + ')';
}
function bodyText(prop) {
  const b = prop.body;
  if (prop.kind === 'eligibility') return `${prop.target}: baseline locally ${b.active ? 'eligible' : 'ineligible'}`;
  if (prop.kind === 'origin') return `${prop.target}: ${b.kind === 'root' ? 'original; no parents' : 'copy requiring ' + b.parents.join(' AND ')}`;
  if (prop.kind === 'support') return `${prop.target} ← ${b.expr ? expression(b.expr) : b.supports.map(route => '(' + route.join(' AND ') + ')').join(' OR ') || 'NO ROUTE'}`;
  if (prop.kind === 'requirement') return `${prop.target} requires ${b.requires.join(' AND ')}`;
  if (prop.kind === 'dependency') return `${prop.target}: ${prop.polarity === 'deny' ? 'NOT ' : ''}${b.relation} [${b.refs.join(', ')}]`;
  return `${prop.target}: unknown ancestry — ${b.description}`;
}
function showCitation(citation, prop) {
  const target = $('citation'); target.replaceChildren(); target.hidden = false;
  target.append(node('strong', `${prop.id} · ${citation.document_id} · code points ${citation.start}–${citation.end}`), node('div', citation.quote));
  target.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}
function renderClauses(compiled) {
  const container = $('clauses'); container.replaceChildren();
  for (const prop of compiled.propositions) {
    const item = node('article', null, 'clause'), heading = node('div', null, 'clause-head');
    heading.append(node('span', prop.scope, 'tag' + (prop.scope === 'current' ? '' : ' noncurrent')),
      node('span', prop.polarity, 'tag' + (prop.polarity === 'deny' ? ' deny' : '')), node('span', `${prop.id} · ${prop.kind}`, 'small'));
    item.append(heading, node('code', bodyText(prop)));
    if (Object.keys(prop.when).length) item.append(node('span', 'Applies when ' + Object.entries(prop.when).map(([key, val]) => `${key} = ${val}`).join(' AND '), 'small'));
    if (prop.bindings.length) item.append(node('span', 'Supplied antecedent bindings: ' + prop.bindings.join(', '), 'small'));
    prop.citations.forEach((cite, index) => item.append(button(`Source span ${index + 1}`, () => showCitation(cite, prop))));
    container.append(item);
  }
}
async function exposurePreview(witness) {
  if (!current || dirty || busy) return;
  const token = ++generation; setBusy(true); setError('');
  try {
    const result = await post('/api/v6d/exposure-preview', {brief: currentBrief, state: current.state,
      expected_declaration_fingerprint: current.declaration_fingerprint, enable: witness.enable, withdraw: witness.withdraw});
    if (generation !== token) return;
    $('exposure-result').hidden = false;
    $('exposure-result').textContent = 'HYPOTHETICAL PREVIEW · ACTIVE STATE UNCHANGED\n' + JSON.stringify(result, null, 2);
  } catch (error) { if (generation === token) setError(error.message); }
  finally { setBusy(false); }
}
async function refuterPreview() {
  if (!current || dirty || busy) return;
  let proposed;
  try { proposed = JSON.parse($('proposal').value); } catch (error) { setError('Counter-reading must be valid JSON: ' + error.message); return; }
  const token = ++generation; setBusy(true); setError(''); $('refuter-result').hidden = true;
  try {
    const result = await post('/api/v6d/refuter-preview', {brief: currentBrief, state: current.state,
      expected_declaration_fingerprint: current.declaration_fingerprint, proposed_ir: proposed});
    if (generation !== token) return;
    const box = $('refuter-result'); box.replaceChildren(); box.hidden = false;
    box.append(node('h3', 'Preview only · ' + result.status.replaceAll('_', ' ')));
    box.append(node('p', 'The current decision status and state are unchanged. Meaning and source completeness are not certified.'));
    const a = result.against_current_declaration;
    if (a) box.append(node('p', `${a.missing_worlds.length} current declared readings absent from proposal; ${a.extra_supplied_worlds.length} proposed readings unlicensed by the current declaration. This does not decide which interpretation follows from the source.`));
    const impact = result.decision_impact;
    box.append(node('h3', 'Conditional effect of adding the proposal'));
    if (impact?.status !== 'evaluated') {
      box.append(node('p', impact?.reason || 'Decision impact is unavailable for this comparison.'));
    } else {
      box.append(node('p', `${impact.novel_proposed_graphs} distinct proposed readings would be added to ${impact.current_distinct_graphs} current readings. Existing readings are retained. This is a preview, not a correction or truth claim.`));
      box.append(node('p', `${impact.states_checked_per_graph} withdrawal states checked per graph; existing document, passage and scenario vetoes remain locked. Inactive evidence is not enabled.`, 'small'));
      for (const [id, decision] of Object.entries(impact.decisions)) {
        const witness = decision.minimum_consensus_loss;
        const card = node('article', null, 'decision');
        card.append(node('h3', id));
        if (!witness) card.append(node('p', 'No loss of unanimity within these declared withdrawals. This does not prove equivalence beyond this scope.'));
        else {
          card.append(node('p', `Smallest additional withdrawal: k=${witness.k} · ${witness.withdraw.length ? witness.withdraw.join(', ') : 'none needed'}`));
          card.append(node('p', `${witness.current_family_state.replaceAll('_', ' ')} → ${witness.augmented_family_state.replaceAll('_', ' ')}. No smaller allowed withdrawal changes this consensus.`));
          const rows = document.createElement('details'); rows.append(node('summary', 'Per-interpretation witness outcomes'));
          for (const [label, outcomes] of [['Current', witness.current_outcomes], ['Added proposal', witness.novel_proposal_outcomes]]) {
            for (const row of outcomes) rows.append(node('p', `${label} ${row.candidate_id} · ${row.supported ? 'supported' : 'unsupported'} · graph ${row.graph_sha256.slice(0, 12)}`, 'small'));
          }
          card.append(rows);
        }
        box.append(card);
      }
    }
    const details = document.createElement('details'); details.append(node('summary', 'Inspect full comparison'), node('pre', JSON.stringify(result, null, 2), 'output')); box.append(details);
  } catch (error) { if (generation === token) setError('Proposal rejected; current state unchanged. ' + error.message); }
  finally { setBusy(false); }
}
function download(name, value) {
  const link = document.createElement('a'), url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}));
  link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function updateCatalogButtons() {
  $('view-recorded').disabled = busy || !$('catalog-outcome').value;
  $('load-recorded').disabled = busy || !selectedRecord?.outcome.loadable_ir || selectedRecord.provenance.condition === 'adversarial_refuter';
  $('preview-recorded').disabled = busy || !selectedRecord?.outcome.loadable_ir || selectedRecord.provenance.condition !== 'adversarial_refuter' || !current || dirty;
  for (const id of ['catalog-model', 'catalog-case', 'catalog-arm', 'catalog-outcome']) $(id).disabled = busy || !catalog;
}
function option(value, text) { const item = node('option', text); item.value = value; return item; }
function clearRecordedSelection() {
  catalogGeneration += 1; selectedRecord = null; $('catalog-entry').hidden = true; updateCatalogButtons();
}
function filterCatalog() {
  clearRecordedSelection(); const outcomes = $('catalog-outcome'); outcomes.replaceChildren();
  if (!catalog) { updateCatalogButtons(); return; }
  const entries = catalog.entries.filter(row => (!$('catalog-model').value || row.model === $('catalog-model').value)
    && (!$('catalog-case').value || row.case_id === $('catalog-case').value)
    && (!$('catalog-arm').value || row.condition === $('catalog-arm').value));
  outcomes.append(option('', 'Choose a scheduled outcome to inspect'));
  for (const row of entries) outcomes.append(option(row.id, `${row.model} · ${row.case_id} · ${row.condition} · ${row.status.replaceAll('_', ' ')}`));
  $('catalog-filter-count').textContent = `${entries.length} matching slots of ${catalog.scheduled_catalog_slots} scheduled catalog slots. Filters do not change the denominator or select the best output.`;
  updateCatalogButtons();
}
async function refreshCatalog() {
  if (busy) return;
  const token = ++catalogGeneration; setBusy(true);
  try {
    const response = await fetch('/api/v6d/catalog'); const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'Catalog unavailable');
    if (token !== catalogGeneration) return;
    catalog = value.schema === 'retrace.recorded-catalog.v6' ? value : null;
    for (const id of ['catalog-model', 'catalog-case', 'catalog-arm', 'catalog-outcome']) $(id).replaceChildren();
    if (!catalog) {
      $('catalog-badge').textContent = 'No recorded catalog published';
      $('catalog-status').textContent = value.scope || 'Recorded outcomes are not published yet. The default demonstration remains constructed.';
      $('catalog-filter-count').textContent = ''; clearRecordedSelection(); return;
    }
    const counts = Object.entries(catalog.status_counts).map(([key, count]) => `${key.replaceAll('_', ' ')}: ${count}`).join(' · ');
    const snapshot = catalog.publication_status === 'closed_run_snapshot' ? 'Closed-run snapshot' : 'PROVISIONAL snapshot';
    $('catalog-badge').textContent = `${snapshot} · ${catalog.scheduled_catalog_slots} scheduled outcomes`;
    $('catalog-status').textContent = `${catalog.catalog_kind === 'test_fixture_only' ? 'TEST FIXTURE ONLY. ' : ''}${snapshot}. ${catalog.scheduled_catalog_slots} catalog slots from ${catalog.full_schedule_slots} total scheduled calls. ${counts}. Pending and missing slots stay in the denominator. These are status counts, not accuracy scores.`;
    for (const [id, field, label] of [['catalog-model', 'model', 'All models'], ['catalog-case', 'case_id', 'All cases'], ['catalog-arm', 'condition', 'All arms']]) {
      $(id).append(option('', label));
      for (const value of [...new Set(catalog.entries.map(row => row[field]))].sort()) $(id).append(option(value, value));
    }
    filterCatalog();
  } catch (error) {
    if (token === catalogGeneration) {
      catalog = null; clearRecordedSelection(); $('catalog-badge').textContent = 'Catalog unavailable';
      $('catalog-status').textContent = error.message + '. The local constructed demo remains separate.';
    }
  } finally { setBusy(false); }
}
async function viewRecorded() {
  const id = $('catalog-outcome').value;
  if (!id || busy) return;
  const token = ++catalogGeneration; setBusy(true); setError('');
  try {
    const response = await fetch('/api/v6d/catalog/' + encodeURIComponent(id)); const entry = await response.json();
    if (!response.ok) throw new Error(entry.error || 'Recorded artifact unavailable');
    if (token !== catalogGeneration || $('catalog-outcome').value !== id) return;
    selectedRecord = entry;
    const container = $('catalog-entry'); container.replaceChildren(); container.hidden = false;
    container.append(node('h3', `${entry.provenance.model} · ${entry.provenance.case_id} · ${entry.provenance.condition}`));
    container.append(node('p', `Recorded status: ${entry.outcome.status.replaceAll('_', ' ')}. ${entry.outcome.loadable_ir ? 'Formally admitted IR can be reviewed explicitly; it is not certified entailed or complete.' : 'This outcome is not loaded as an executable interpretation. Its raw output remains visible.'}`, 'catalog-meta'));
    container.append(node('p', `Slot: ${entry.provenance.slot_id}. Provider response: ${entry.provenance.response_status || 'none recorded'}. Strict bare JSON: ${entry.outcome.strict_bare_json ? 'yes' : 'no'}.`, 'hint'));
    if (entry.outcome.compiler_error) container.append(node('pre', JSON.stringify(entry.outcome.compiler_error, null, 2), 'output'));
    if (entry.outcome.missing_disposition_ids.length) container.append(node('p', 'Reference-Free Coverage Gap: missing identifier dispositions ' + entry.outcome.missing_disposition_ids.join(', ') + '.', 'hint'));
    for (const [label, data] of [['Preserved raw and partial output', entry.raw], ['Recorded provenance and hash binding', {...entry.provenance, ...entry.catalog_provenance}], ['Public source bundle', entry.source_bundle], ['Actual parsed output (if admitted to JSON)', entry.outcome.parsed_output]]) {
      const details = document.createElement('details'); details.append(node('summary', label), node('pre', JSON.stringify(data, null, 2), 'output')); container.append(details);
    }
  } catch (error) { if (token === catalogGeneration) { selectedRecord = null; setError(error.message); } }
  finally { setBusy(false); }
}
$('refresh-catalog').addEventListener('click', refreshCatalog);
for (const id of ['catalog-model', 'catalog-case', 'catalog-arm']) $(id).addEventListener('change', filterCatalog);
$('catalog-outcome').addEventListener('change', clearRecordedSelection);
$('view-recorded').addEventListener('click', viewRecorded);
$('load-recorded').addEventListener('click', () => {
  if (!selectedRecord?.bundle || selectedRecord.provenance.condition === 'adversarial_refuter' || busy) return;
  loadBrief(selectedRecord.bundle); setError(''); notice('Recorded model IR loaded into the editors. Review it, then analyze explicitly. No source truth or completeness is asserted.');
});
$('preview-recorded').addEventListener('click', () => {
  if (!selectedRecord?.outcome.source_ir || selectedRecord.provenance.condition !== 'adversarial_refuter' || !current || dirty || busy) return;
  $('proposal').value = JSON.stringify(selectedRecord.outcome.source_ir, null, 2);
  notice('Previewing this recorded proposal against the active declaration. Its original study seed family is not loaded or certified by this catalog.');
  refuterPreview(); $('proposal').scrollIntoView({behavior: 'smooth', block: 'center'});
});
$('bundle').addEventListener('input', markDirty); $('ir').addEventListener('input', markDirty);
$('proposal').addEventListener('input', () => { generation += 1; $('refuter-result').hidden = true; });
$('analyze').addEventListener('click', () => analyze());
$('demo').addEventListener('click', async () => {
  if (busy) return;
  setError(''); setBusy(true);
  try { const response = await fetch('/api/v6d/demo'); if (!response.ok) throw new Error('Demo unavailable'); loadBrief(await response.json()); }
  catch (error) { setError(error.message); }
  finally { setBusy(false); }
  if (!current && $('ir').value) analyze();
});
$('import').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  try { if (file.size > 2097152) throw new Error('Bundle exceeds the local2MB limit.'); loadBrief(JSON.parse(await file.text())); setError(''); notice('Bundle loaded. Review the source and interpretation, then analyze.'); }
  catch (error) { setError(error.message); }
  event.target.value = '';
});
$('clear-scenario').addEventListener('click', () => changeState(next => { next.scenario_withdrawals = []; }));
$('preview-refuter').addEventListener('click', refuterPreview);
$('export-bundle').addEventListener('click', () => { try { download('retrace-source-bundle.json', readBrief()); } catch (error) { setError(error.message); } });
$('export-audit').addEventListener('click', () => { if (current && !dirty) download('retrace-local-analysis.json', {brief: currentBrief, analysis: current}); });
$('segments').addEventListener('click', async () => {
  if (busy) return;
  let bundle; try { bundle = JSON.parse($('bundle').value); } catch (error) { setError(error.message); return; }
  const token = ++generation; setBusy(true); setError('');
  try { const result = await post('/api/v6d/source', {brief: bundle}); if (generation !== token) return;
    $('prompt-text').value = result.instructions + '\n\n' + JSON.stringify(result.source, null, 2); $('prompt-dialog').showModal();
  } catch (error) { if (generation === token) setError(error.message); }
  finally { setBusy(false); }
});
$('close-prompt').addEventListener('click', () => $('prompt-dialog').close());
$('copy-prompt').addEventListener('click', async () => { try { await navigator.clipboard.writeText($('prompt-text').value); $('copy-prompt').textContent = 'Copied'; } catch { $('prompt-text').focus(); $('prompt-text').select(); $('copy-prompt').textContent = 'Select all and copy'; } });
refreshCatalog();
