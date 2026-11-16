'use strict';

// A local client for the declared-graph stress engine. No inference or external requests.
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const emptyState = () => ({answers:{}, revoked_documents:[], revoked_passages:[], scenario_withdrawals:[]});
const app = {brief:null, state:emptyState(), analysis:null, pending:false, witnesses:new Map()};
let savedCases = {briefs:[],status:'not_run',provenance:''};
let catalogSequence = 0;
let catalogLoading = false;
const STORAGE_KEY = 'retrace.stress.session.v5';
const exposureWitnesses = new Map();
let importReadSequence = 0;

function notice(message, error=false) {
  $('notice').textContent = message;
  $('notice').className = error ? 'error' : '';
  $('notice').hidden = !message;
}
function setBusy(busy) {
  app.pending = busy;
  document.body.classList.toggle('busy', busy);
  $('decision-results').setAttribute('aria-busy', String(busy));
  document.querySelectorAll('button,input,textarea').forEach(element => {
    if (busy) {
      element.dataset.busyDisabled = String(element.disabled);
      element.disabled = true;
    } else if ('busyDisabled' in element.dataset) {
      element.disabled = element.dataset.busyDisabled === 'true';
      delete element.dataset.busyDisabled;
    }
  });
  syncSavedControls();
}
function syncSavedControls() {
  $('refresh-saved-cases').disabled = app.pending || catalogLoading;
  $('saved-case-select').disabled = app.pending || catalogLoading || savedCases.briefs.length === 0;
  $('load-saved-case').disabled = app.pending || catalogLoading || savedCases.briefs.length === 0 || $('saved-case-select').value === '';
}
async function request(path, body, rawBody=null) {
  const response = await fetch(path, body === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:rawBody ?? JSON.stringify(body)
  });
  let result;
  try { result = await response.json(); } catch { throw new Error('The local server returned an unreadable response. Check that RETRACE is running.'); }
  if (!response.ok) throw new Error(result.error || `The local request failed (${response.status}).`);
  return result;
}
function remember() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({brief:app.brief,state:app.state})); }
  catch { notice('The current session is open, but browser storage is unavailable. Export it to keep a copy.'); }
}
async function evaluate(brief, state, message='', rawBody=null) {
  if (app.pending) return false;
  setBusy(true);
  try {
    const result = await request('/api/v5/analyze', {brief,state}, rawBody);
    if (!result || !result.consensus || !Array.isArray(result.candidate_ids)) throw new Error('The local engine response is missing its candidate analysis.');
    app.brief = result.compiled_brief || brief;
    app.analysis = result;
    app.state = {...emptyState(), ...state, ...(result.state || {})};
    render();
    remember();
    notice(message);
    return true;
  } catch (error) {
    notice(error.message, true);
    if ($('import-dialog').open) {
      $('import-error').textContent = error.message;
      $('import-error').hidden = false;
    }
    return false;
  } finally { setBusy(false); }
}
async function loadDemo() {
  if (app.pending) return;
  setBusy(true);
  try {
    const brief = await request('/api/stress-demo');
    setBusy(false);
    await evaluate(brief, emptyState(), 'Worked example loaded. Its interpretations are constructed, not verified source facts.');
  } catch (error) { notice(error.message, true); }
  finally { setBusy(false); }
}
function updateState(change, message='') {
  if (!app.brief || app.pending) return;
  const next = JSON.parse(JSON.stringify(app.state));
  change(next);
  return evaluate(app.brief, next, message);
}
function node(id) {
  for (const candidate of app.brief?.candidates || []) {
    for (const category of ['evidence','claims','decisions']) {
      const found = candidate.graph?.[category]?.find(row => row.id === id);
      if (found) return found;
    }
  }
  return null;
}
const label = id => node(id)?.label || id;
const candidateLabel = id => app.brief?.candidates?.find(row => row.id === id)?.label || id;
const names = ids => ids.map(label).join(' + ');
function sourceDocuments(id) { return (app.brief.documents || []).filter(doc => (doc.evidence_ids || []).includes(id)); }
function revokedReasons(id) {
  const reasons = [];
  if (app.state.revoked_passages.includes(id)) reasons.push('passage excluded');
  if (sourceDocuments(id).some(doc => app.state.revoked_documents.includes(doc.id))) reasons.push('source document excluded');
  if (app.state.scenario_withdrawals.includes(id)) reasons.push('scenario exclusion');
  return reasons;
}
function evidenceIds() { return (app.brief.candidates?.[0]?.graph?.evidence || []).map(row => row.id); }
function candidateOutcomes(outcomes) {
  return '<div class="outcomes-strip">' + Object.entries(outcomes || {}).map(([id,value]) =>
    `<span class="outcome-chip ${value ? '' : 'no'}" title="${escapeHTML(candidateLabel(id))}">${escapeHTML(candidateLabel(id))}: ${value ? 'supported' : 'unsupported'}</span>`).join('') + '</div>';
}
function renderSource() {
  $('source-prose').textContent = typeof app.brief.prose === 'string' ? app.brief.prose : 'No source prose was supplied.';
  const constraints = app.brief.provenance_constraints;
  $('constraint-content').replaceChildren();
  if (!constraints || (Array.isArray(constraints) && constraints.length === 0)) {
    $('constraint-content').textContent = 'No independent provenance constraints were supplied. An omitted relationship cannot be diagnosed from candidate agreement alone.';
  } else {
    const introductory = document.createElement('p');
    introductory.textContent = 'These are supplied checks on the candidate links. RETRACE does not independently authenticate them.';
    $('constraint-content').append(introductory);
    const pre = document.createElement('pre');
    pre.className = 'constraint-row';
    pre.textContent = JSON.stringify(constraints, null, 2);
    $('constraint-content').append(pre);
  }
  const documents = app.brief.documents || [];
  $('document-controls').innerHTML = documents.length ? '<div class="panel-caption">WHOLE DOCUMENTS</div>' + documents.map(doc => {
    const checked = app.state.revoked_documents.includes(doc.id);
    return `<div class="control-row ${checked ? 'revoked' : ''}"><input type="checkbox" data-revoke-document="${escapeHTML(doc.id)}" id="doc-${escapeHTML(doc.id)}" ${checked ? 'checked' : ''}><label for="doc-${escapeHTML(doc.id)}">${escapeHTML(doc.label || doc.title || doc.id)}<small>${(doc.evidence_ids || []).length} linked passage${(doc.evidence_ids || []).length === 1 ? '' : 's'} · ${checked ? 'Revoked — falsity not asserted' : 'Document exclusion is off'}</small></label></div>`;
  }).join('') : '<p class="section-description">No document-to-passage mapping is supplied. Individual passage controls remain available.</p>';
  $('passage-controls').innerHTML = evidenceIds().map(id => {
    const checked = app.state.revoked_passages.includes(id);
    const reasons = revokedReasons(id);
    const sources = sourceDocuments(id).map(doc => doc.label || doc.title || doc.id).join(' · ');
    const parents = [...new Set(app.brief.candidates.flatMap(c => c.graph.evidence.find(e => e.id === id)?.parents || []))];
    return `<div class="control-row ${reasons.length ? 'revoked' : ''}"><input type="checkbox" data-revoke-passage="${escapeHTML(id)}" id="passage-${escapeHTML(id)}" ${checked ? 'checked' : ''}><label for="passage-${escapeHTML(id)}">${escapeHTML(label(id))}${sources ? `<small>${escapeHTML(sources)}</small>` : ''}${parents.length ? `<small>Declared parent links include: ${escapeHTML(names(parents))}</small>` : ''}<small class="${reasons.length ? 'revoke-state' : 'included-state'}">${reasons.length ? 'Revoked — falsity not asserted. ' + escapeHTML(reasons.join('; ')) + '.' : 'No explicit exclusion. Eligibility and parent links still apply.'}</small></label></div>`;
  }).join('');
}
function witnessBlock(decisionId, key, title, definition, witness, absent) {
  const token = decisionId + ':' + key;
  if (witness && Array.isArray(witness.withdraw)) app.witnesses.set(token, witness);
  return `<div class="witness-row"><div class="witness-heading"><h4>${escapeHTML(title)}</h4>${witness ? `<span class="k-badge">k = ${Number.isInteger(witness.k) ? witness.k : witness.withdraw?.length ?? 0}</span>` : ''}</div><p class="witness-definition">${escapeHTML(definition)}</p>${witness ? `<div class="witness-body"><ul>${witness.withdraw.length ? witness.withdraw.map(id => `<li>${escapeHTML(label(id))}</li>`).join('') : '<li>No additional withdrawal is needed.</li>'}</ul>${witness.withdraw.length ? `<button data-apply-witness="${escapeHTML(token)}">Apply scenario →</button>` : ''}</div>${candidateOutcomes(witness.outcomes)}` : `<p class="witness-empty">${escapeHTML(absent)}</p>`}</div>`;
}
function routeDetails(decisionId) {
  const rows = app.brief.candidates.filter(c => app.analysis.candidate_ids.includes(c.id));
  return `<details><summary>Inspect the declared support routes</summary>${rows.map(candidate => {
    const graph = candidate.graph;
    const decision = graph.decisions.find(d => d.id === decisionId);
    const labels = new Map([...graph.evidence,...graph.claims,...graph.decisions].map(row => [row.id,row.label || row.id]));
    const text = id => escapeHTML(labels.get(id) || id);
    return `<div class="route-detail"><strong>${escapeHTML(candidate.label || candidate.id)}</strong><p>Decision requires all: ${(decision?.requires || []).map(text).join(' + ') || 'No prerequisites supplied'}</p>${(decision?.requires || []).map(id => {
      const claim = graph.claims.find(c => c.id === id);
      return `<p>${text(id)} is supported by:</p>${claim?.supports?.length ? claim.supports.map((route,i) => `${i ? '<div class="route-separator">OR</div>' : ''}<p>${route.map(text).join(' + ')}</p>`).join('') : '<p>No declared support route.</p>'}`;
    }).join('')}</div>`;
  }).join('')}<p class="scope-note">“+” requires every member. Alternatives are joined by OR. Intermediate claim dependencies remain in the exported graph.</p></details>`;
}
function renderDecisions() {
  app.witnesses.clear();
  const states = app.analysis.decision_states || app.analysis.consensus.decision_states || {};
  const targetSet = new Set(app.analysis.consensus.target_decisions || Object.keys(states));
  const ordered = Object.keys(states).sort((a,b) => Number(targetSet.has(b)) - Number(targetSet.has(a)));
  const focused = targetSet.size < Object.keys(states).length;
  $('clarification-focus').innerHTML = `<span>Clarification target: ${focused ? escapeHTML(names([...targetSet]) || 'none') : 'all decisions'}</span>${focused ? '<button class="text-button" data-clear-targets="true">Include all decisions</button>' : ''}`;
  $('decision-results').innerHTML = ordered.length ? ordered.map((id,index) => {
    const state = states[id], info = app.analysis.decision_witnesses?.[id] || {};
    const supported = state.state === 'robust_supported';
    const unsupported = state.state === 'robust_unsupported';
    const kind = supported ? 'supported' : unsupported ? 'unsupported' : 'disputed';
    const status = state.display_label || (supported ? 'Supported under declared links' : unsupported ? 'Unsupported' : 'Disputed across compatible interpretations');
    const explanation = supported ? 'Every remaining interpretation supports this decision at the current exclusions.' : state.classification === 'revoked' ? 'Support was lost in at least one compatible interpretation after an exclusion, and none currently supports this decision. Falsity is not asserted.' : unsupported ? 'None of the remaining interpretations currently supports this decision. Falsity is not asserted.' : 'The remaining interpretations disagree. Their source relationships need clarification.';
    const minAny = info.minimum_break_any;
    const breakK = minAny ? (minAny.k ?? minAny.withdraw?.length) : null;
    const resilience = supported && breakK >= 3 ? `<div class="resilience-note"><strong>${breakK}</strong><span>additional withdrawals before support can break<small>Survives every single and pair withdrawal within the allowed scope.</small></span></div>` : '';
    let witnesses = '';
    if (supported) {
      witnesses += witnessBlock(id,'break_any','Break support in at least one interpretation','Minimum additional record withdrawals; the surviving interpretation may still support it.',info.minimum_break_any,'No permitted withdrawal subset breaks this decision in any remaining interpretation.');
      witnesses += witnessBlock(id,'break_all','Break support in every interpretation','A shared withdrawal set that leaves no remaining interpretation supporting this decision.',info.minimum_break_all,'No permitted withdrawal subset breaks support in every remaining interpretation.');
    }
    witnesses += witnessBlock(id,'distinguish','Separate the interpretations','Minimum additional withdrawals that make compatible interpretations disagree. This is not necessarily a support-breaking test.',info.minimum_distinguishing,'No withdrawal within the allowed scope separates the remaining interpretations on this decision.');
    return `<article class="decision-card ${kind}" id="decision-${escapeHTML(id)}"><div class="decision-head"><h3>${escapeHTML(info.label || label(id))}</h3><span class="decision-index">${String(index+1).padStart(2,'0')}${targetSet.has(id) ? ' / TARGET' : ''}</span></div><span class="status-badge">${status}</span><p class="status-explanation">${explanation}</p>${targetSet.size === 1 && targetSet.has(id) ? '<span class="focus-current">Clarification is focused here</span>' : `<button class="text-button" data-focus-decision="${escapeHTML(id)}">Focus clarification here</button>`}${resilience}<div class="witness-list">${witnesses}</div>${routeDetails(id)}</article>`;
  }).join('') : '<div class="empty-state">This brief has no decisions. Add explicit decision prerequisites to a brief before testing its support.</div>';
}
function renderQuestion() {
  const next = app.analysis.next_question;
  const clarification = app.analysis.consensus.clarification || {};
  const sourceDefect = (app.analysis.provenance_checks || []).some(check =>
    check.violating_candidate_ids?.some(id => app.analysis.candidate_ids.includes(id)));
  const rootWarning = Boolean(app.analysis.root_coverage?.warning);
  document.querySelector('.question-panel').classList.toggle('source-warning', sourceDefect || rootWarning);
  if (next) {
    const cost = next.worst_case_cost ?? clarification.worst_case_cost;
    const markedUnknown = Object.hasOwn(app.state.answers,next.id) && app.state.answers[next.id] === null;
    $('next-question').innerHTML = `<p class="question-prompt">${escapeHTML(next.label)}</p><p class="question-context">Answer from an authoritative source. This question is chosen to resolve the target decisions with minimum worst-case declared cost.</p>${markedUnknown ? '<p class="unknown-note">You marked this unknown. It remains the cheapest first clarification if its answer can be established; all compatible interpretations are retained.</p>' : ''}<div class="cost-strip"><strong>${cost === null || cost === undefined ? '—' : escapeHTML(cost)}</strong><span>worst-case remaining cost</span><small>Declared units, not confidence or expected information value.</small></div><div class="answer-buttons"><button data-answer="yes" data-question="${escapeHTML(next.id)}">Yes</button><button data-answer="no" data-question="${escapeHTML(next.id)}">No</button></div><button class="unknown-button" data-answer="unknown" data-question="${escapeHTML(next.id)}">I cannot establish this · keep uncertainty</button>`;
  } else if (clarification.possible && clarification.worst_case_cost === 0) {
    $('next-question').innerHTML = sourceDefect
      ? '<span class="complete-mark">!</span><p class="question-finished">Graph agreement.<br>Source review is still required.</p><p>The declared graphs agree, but an independent constraint flags a missing provenance link in a remaining interpretation. The question planner cannot repair that link or supply a missing candidate. Review the source and revise the candidate set.</p><div class="cost-strip"><strong>0</strong><span>cost to resolve the current graph outputs</span><small>This does not resolve the flagged source defect.</small></div>'
      : rootWarning
        ? '<span class="complete-mark">!</span><p class="question-finished">Graph agreement.<br>Common-cause sensitivity remains.</p><p>The declared graphs agree, but joint withdrawal of an unverified root pair can remove support. This is a hypothetical vulnerability, not evidence of actual dependence. Inspect the coverage warning below.</p><div class="cost-strip"><strong>0</strong><span>cost to resolve the current graph outputs</span><small>Graph agreement does not verify source independence.</small></div>'
        : '<span class="complete-mark">✓</span><p class="question-finished">The target decisions agree.</p><p>No further question is needed for the current target decision vector. Different source interpretations can remain unresolved.</p><div class="cost-strip"><strong>0</strong><span>remaining clarification cost</span><small>Agreement is conditional on the supplied candidate set.</small></div>';
  } else {
    $('next-question').innerHTML = '<p class="question-finished">Keep this uncertainty open.</p><p>The available factual questions cannot resolve every target decision. Unknown answers do not eliminate candidates. Inspect the conflicting interpretations or supply an independently justified clarification.</p>';
  }
}
function renderCandidates() {
  const remaining = new Set(app.analysis.candidate_ids);
  const eliminated = app.analysis.eliminated_candidate_ids || app.brief.candidates.filter(c => !remaining.has(c.id)).map(c => c.id);
  $('candidate-tally').textContent = `${remaining.size} / ${app.brief.candidates.length}`;
  $('candidate-list').innerHTML = app.brief.candidates.filter(c => remaining.has(c.id)).map(c => `<div class="candidate-chip">${escapeHTML(c.label || c.id)}</div>`).join('');
  $('eliminated-details').hidden = eliminated.length === 0;
  $('eliminated-summary').textContent = `${eliminated.length} eliminated interpretation${eliminated.length === 1 ? '' : 's'}`;
  $('eliminated-list').innerHTML = eliminated.map(id => `<div class="candidate-chip eliminated">${escapeHTML(candidateLabel(id))}</div>`).join('');
  const answers = Object.entries(app.state.answers);
  $('answer-history').innerHTML = answers.length ? '<div class="answer-history-label">ANSWERS IN THIS SESSION</div>' + answers.map(([id,value]) => {
    const question = app.brief.questions?.find(q => q.id === id);
    return `<div class="answer-row"><p>${escapeHTML(question?.label || id)}</p><div><span>${value === true ? 'Yes' : value === false ? 'No' : 'Unknown · candidates retained'}</span><button class="text-button" data-clear-answer="${escapeHTML(id)}">Clear answer</button></div></div>`;
  }).join('') : '';
}
function renderScope() {
  const audit = app.analysis.interventions || {};
  const variables = audit.allowed_withdrawals || app.brief.allowed_withdrawals || evidenceIds();
  const fixed = audit.fixed_evidence_ids || evidenceIds().filter(id => !variables.includes(id));
  const states = audit.states_checked_per_candidate ?? 2 ** variables.length;
  $('scope-summary').innerHTML = `<strong>Exact, bounded search.</strong> ${Number(states).toLocaleString()} withdrawal states per compatible interpretation across ${variables.length} permitted record${variables.length === 1 ? '' : 's'}. Witnesses count additional records, including copies; they are not independent-source counts or probabilities.<details><summary>See the intervention boundary</summary><p>Allowed to vary: ${escapeHTML(names(variables) || 'none')}.</p><p>Fixed outside this search: ${escapeHTML(names(fixed) || 'none')}.</p><p>Original local ineligibility and explicit exclusions remain in force. The search does not restore an originally inactive record.</p></details>`;
  const coverage = app.analysis.coverage;
  const constraints = app.brief.provenance_constraints;
  $('coverage-note').textContent = constraints && (!Array.isArray(constraints) || constraints.length) ? 'Independent constraints were supplied. Inspect their coverage check in the audit; agreement alone cannot reveal other omitted relationships.' : 'Omitted provenance is unknown: no independent constraints were supplied to expose it.';
  $('coverage-note').className = '';
  const retained = new Set(app.analysis.candidate_ids);
  const failures = (app.analysis.provenance_checks || []).filter(check => check.violating_candidate_ids?.length);
  $('coverage-banner').hidden = failures.length === 0;
  if (failures.length) {
    const shared = failures.some(check => check.violating_candidate_ids.filter(id => retained.has(id)).length === retained.size);
    $('coverage-banner').innerHTML = `<h3>${shared ? 'Agreement can conceal a shared provenance omission.' : 'An independent provenance constraint flags a missing link.'}</h3><ul>${failures.map(check => {
      const live = check.violating_candidate_ids.filter(id => retained.has(id));
      const removed = check.violating_candidate_ids.filter(id => !retained.has(id));
      const scope = live.length === retained.size ? `Absent from every remaining interpretation (${live.length}).` : live.length ? `Absent from ${live.length} remaining interpretation${live.length === 1 ? '' : 's'}: ${live.map(candidateLabel).join('; ')}.` : 'The failing interpretations have all been eliminated by your answers.';
      return `<li><strong>${escapeHTML(label(check.child))}</strong> should have a declared ancestor path to <strong>${escapeHTML(label(check.ancestor))}</strong>. ${escapeHTML(scope)}${removed.length ? ` Also absent from ${removed.length} eliminated interpretation${removed.length === 1 ? '' : 's'}.` : ''}${check.source_quote ? `<p>Supplied constraint: “${escapeHTML(check.source_quote)}”</p>` : ''}</li>`;
    }).join('')}</ul><p>These checks use only the independently supplied constraints. They flag a defect without inventing a link or eliminating a candidate. Support labels remain conditional on the declared graphs.</p>`;
  }
  const sourceScope = Array.isArray(app.analysis.scope) ? app.analysis.scope : [app.analysis.scope].filter(Boolean);
  $('audit-explanation').innerHTML = `<p>This is a deterministic calculation over supplied graphs and factual answer tables. It does not extract relationships from prose or authenticate the source.</p><ul>${sourceScope.map(text => `<li>${escapeHTML(typeof text === 'string' ? text : JSON.stringify(text))}</li>`).join('')}</ul>`;
  if (coverage) {
    const pre = document.createElement('pre');
    pre.textContent = 'Coverage / independent constraint checks\n' + JSON.stringify(coverage,null,2);
    $('audit-explanation').append(pre);
  }
  $('audit-json').textContent = JSON.stringify(app.analysis,null,2);
  $('audit-count').textContent = Number(states).toLocaleString();
}
function render() {
  $('brief-title').textContent = app.brief.title || 'Untitled evidence brief';
  const provenance = app.analysis.provenance || {};
  const verifiedKind = provenance.status === 'matched_saved_catalog' ? provenance.kind : null;
  $('brief-kind').textContent = verifiedKind === 'reference_comparison'
    ? 'Matched saved diagnostic · actual model versus explicitly supplied authored reference'
    : verifiedKind === 'fresh_confirmation'
    ? 'Matched saved output · prospectively frozen targeted confirmation'
    : verifiedKind === 'post_hoc_replay'
    ? 'Matched saved output · post-hoc syntax replay; original v4 result preserved'
    : provenance.declared_reference_comparison
    ? 'Unverified supplied brief · declares an authored reference comparison; run provenance is not established'
    : 'Unverified supplied brief · candidate completeness and run provenance are not established';
  $('live-count').textContent = app.analysis.candidate_ids.length;
  $('decision-count').textContent = Object.keys(app.analysis.consensus.decision_states || {}).length;
  $('withdrawal-count').textContent = evidenceIds().filter(id => revokedReasons(id).length).length;
  $('scenario-tray').hidden = app.state.scenario_withdrawals.length === 0;
  $('scenario-description').textContent = names(app.state.scenario_withdrawals);
  renderSource(); renderDecisions(); renderQuestion(); renderCandidates(); renderScope(); renderV4(); renderExposure();
}

function renderV4() {
  const compilation = app.analysis.ambiguity_compilation;
  $('v4-source').value = app.brief.compact_v5 || app.brief.compact_v4 || '';
  $('v4-compilation-summary').textContent = compilation
    ? `${compilation.uncertainty_count} binary uncertainty tokens → ${compilation.candidates.length} compiled assignments. ${app.analysis.candidate_ids.length} remain after answers. Exhaustive over declared tokens; missing source ambiguities remain possible.`
    : 'This brief contains supplied candidate graphs. Load or paste a typed program to enumerate declared alternatives.';
  const live = new Set(app.analysis.candidate_ids);
  $('v4-branch-list').innerHTML = compilation ? `<details open><summary>Compiled branches and source questions</summary><ul>${compilation.questions.map(q => `<li><strong>${escapeHTML(q.id)}</strong>: ${escapeHTML(q.label)}</li>`).join('')}</ul><div class="v4-assignments">${compilation.candidates.map(c => `<details class="candidate-chip ${live.has(c.id) ? '' : 'eliminated'}"><summary>${escapeHTML(c.id)} · ${live.has(c.id) ? 'compatible' : 'excluded by answer'}</summary><p>${compilation.questions.map(q => `${escapeHTML(q.id)}: ${q.answers[c.id] ? 'Yes' : 'No'}`).join('<br>')}</p><pre>${escapeHTML(JSON.stringify(c.graph,null,2))}</pre></details>`).join('')}</div></details>` : '';
  const guard = app.analysis.root_coverage;
  $('root-coverage-banner').hidden = !guard?.warning;
  if (!guard?.warning) return;
  const rows = Object.entries(guard.decisions || {}).filter(([,d]) => d.warning);
  $('root-coverage-banner').innerHTML = `<h3>Coverage Warning: Relies on Unverified Root Independence</h3><p>This is an adversarial withdrawal hypothesis, not a discovered shared source. Merging available roots alone preserves support. An unavailable shared ancestor could remove both roots together.</p>${rows.map(([id,d]) => {
    const groups = new Map();
    for (const w of d.witnesses || []) {
      const key = JSON.stringify([w.roots,w.pair_only_failure]);
      if (!groups.has(key)) groups.set(key,{...w,candidate_ids:[]});
      groups.get(key).candidate_ids.push(w.candidate_id);
    }
    return `<details open><summary>${escapeHTML(label(id))}</summary>${[...groups.values()].map((w,index) => {
    const token = `coverage:${id}:${index}`;
    const permitted = w.roots.every(root => app.analysis.interventions.allowed_withdrawals.includes(root));
    app.witnesses.set(token,{withdraw:w.roots,scenario_withdrawals:[...new Set([...app.state.scenario_withdrawals,...w.roots])]});
    return `<p>${escapeHTML(names(w.roots))} in ${w.candidate_ids.length} compatible interpretation${w.candidate_ids.length === 1 ? '' : 's'}. Joint withdrawal loses support. ${w.pair_only_failure ? 'Both single withdrawals preserve support.' : 'At least one single withdrawal already loses support; this is not additional protection from independent routes.'}${permitted ? `<button data-apply-witness="${escapeHTML(token)}">Test joint withdrawal</button>` : '<span> Pair lies outside the permitted interactive withdrawal scope.</span>'}</p><details><summary>Inspect affected assignments</summary><p>${escapeHTML(w.candidate_ids.join(', '))}</p></details>`;
  }).join('')}</details>`; }).join('')}<p>Checks cover root pairs only. No warning does not establish independence or exclude larger shared causes. Independence attestations, when supplied, are trusted external declarations.</p>`;
}

$('load-v4-demo').addEventListener('click', async () => {
  if (app.pending) return;
  setBusy(true);
  try { const brief = await request('/api/v4/demo'); setBusy(false); await evaluate(brief,emptyState(),'Typed example compiled locally. No model call or source verification performed.'); }
  catch (error) { notice(error.message,true); }
  finally { setBusy(false); }
});
$('compile-v4-source').addEventListener('click', async () => {
  if (app.pending) return;
  const source = $('v4-source').value;
  await evaluate({id:'local-v5-program',title:'Locally compiled ambiguity program',compact_v5:source,
    prose:'User-supplied dependency program. Source fidelity and omitted uncertainty have not been verified.'},emptyState(),'All declared assignments compiled. Answers and exclusions reset for the new program.');
});
function renderExposure() {
  exposureWitnesses.clear();
  $('exposure-preview').hidden = true;
  const audit = app.analysis.exposure;
  if (!audit || audit.status === 'unavailable') {
    $('exposure-results').textContent = audit?.reason || 'No exposure audit available.';
    return;
  }
  $('exposure-results').innerHTML = Object.entries(audit.decisions).map(([did,row]) => {
    if (!row.exposure_exists) return `<article class="exposure-card"><h3>${escapeHTML(label(did))}</h3><p>No eligibility state within this bounded audit separates the supplied interpretations. This does not establish source accuracy or complete interpretation coverage.</p></article>`;
    const dormant = !row.minimum_without_enabling;
    return `<article class="exposure-card"><h3>${escapeHTML(label(did))}</h3>${dormant ? '<strong class="dormant-label">Withdrawal-only tests cannot expose this disagreement.</strong>' : '<p>A withdrawal-only distinction exists within scope.</p>'}<p>Each point below minimizes withdrawals for its enabling count; dominated alternatives are omitted.</p>${row.frontier.map((point,index) => {
      const token = `${did}:${index}`;
      exposureWitnesses.set(token,point.witness);
      return `<div class="exposure-witness"><strong>Enable ${point.enable_count} · withdraw ${point.withdraw_count}</strong><p>Assume eligible: ${escapeHTML(names(point.witness.enable) || 'none')}. Withdraw: ${escapeHTML(names(point.witness.withdraw) || 'none')}.</p><button data-preview-exposure="${escapeHTML(token)}">Preview hypothetical state</button></div>`;
    }).join('')}<details><summary>Inspect exhaustive minimality record</summary><pre>${escapeHTML(JSON.stringify({minimality:row.minimality,histogram:row.total_change_histogram,scope:audit.coverage},null,2))}</pre></details></article>`;
  }).join('');
}

document.addEventListener('click', async event => {
  const button = event.target.closest('button[data-preview-exposure]');
  if (!button || app.pending) return;
  const witness = exposureWitnesses.get(button.dataset.previewExposure);
  if (!witness) return;
  setBusy(true);
  try {
    const result = await request('/api/v5/exposure-preview',{brief:app.brief,state:app.state,enable:witness.enable,withdraw:witness.withdraw});
    $('exposure-preview').innerHTML = `<h3>Hypothetical eligibility preview</h3><p>${escapeHTML(result.assumption)}</p><p>Assume eligible: ${escapeHTML(names(result.enable) || 'none')}. Withdraw: ${escapeHTML(names(result.withdraw) || 'none')}.</p><table><thead><tr><th>Interpretation</th><th>Decision</th><th>Under this hypothesis</th></tr></thead><tbody>${Object.entries(result.outcomes).flatMap(([cid,vector]) => Object.entries(vector).map(([did,value]) => `<tr><td>${escapeHTML(candidateLabel(cid))}</td><td>${escapeHTML(label(did))}</td><td>${value ? 'Supported under hypothetical eligibility' : 'Unsupported under hypothetical eligibility'}</td></tr>`)).join('')}</tbody></table>`;
    $('exposure-preview').hidden = false;
  } catch (error) { notice(error.message,true); }
  finally { setBusy(false); }
});

function download(value, name) {
  const blob = new Blob([JSON.stringify(value,null,2)+'\n'], {type:'application/json'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
function exportName(suffix) { return String(app.brief?.id || 'retrace').replace(/[^a-zA-Z0-9_-]/g,'-') + suffix; }

async function refreshSavedCases() {
  const sequence = ++catalogSequence;
  const selected = $('saved-case-select').value;
  const selectedId = selected === '' ? null : savedCases.briefs[Number(selected)]?.id;
  catalogLoading = true;
  syncSavedControls();
  $('saved-case-note').textContent = 'Checking local results…';
  try {
    const catalog = await request('/api/stress-benchmark');
    if (sequence !== catalogSequence) return;
    const briefs = Array.isArray(catalog.briefs) ? catalog.briefs.filter(brief =>
      brief && typeof brief.id === 'string' && Array.isArray(brief.candidates) && brief.candidates.length) : [];
    savedCases = {briefs,status:catalog.status || 'not_run',provenance:catalog.provenance || ''};
    const options = briefs.map((brief,index) => {
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = brief.title || brief.id;
      return option;
    });
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = briefs.length ? 'Choose a saved model case' : 'No model cases saved yet';
    $('saved-case-select').replaceChildren(placeholder,...options);
    const retainedSelection = briefs.findIndex(brief => brief.id === selectedId);
    if (retainedSelection >= 0) $('saved-case-select').value = String(retainedSelection);
    $('saved-case-select').disabled = briefs.length === 0;
    $('load-saved-case').disabled = !briefs.length || $('saved-case-select').value === '' || app.pending;
    $('saved-case-note').textContent = briefs.length
      ? `${briefs.length} cases · fresh outputs, post-hoc replays and labelled benchmark comparisons`
      : 'Refresh after a model run is saved. No new inference is requested here.';
  } catch {
    if (sequence !== catalogSequence) return;
    savedCases = {briefs:[],status:'unavailable',provenance:''};
    const placeholder = document.createElement('option');
    placeholder.value = ''; placeholder.textContent = 'Saved cases unavailable';
    $('saved-case-select').replaceChildren(placeholder);
    $('saved-case-select').disabled = true;
    $('load-saved-case').disabled = true;
    $('saved-case-note').textContent = 'The local results catalog is not available yet. Your active brief is unchanged.';
  } finally {
    if (sequence === catalogSequence) { catalogLoading = false; syncSavedControls(); }
  }
}

$('refresh-saved-cases').addEventListener('click', refreshSavedCases);
$('saved-case-select').addEventListener('change', () => {
  syncSavedControls();
});
$('load-saved-case').addEventListener('click', async () => {
  if (app.pending || $('saved-case-select').value === '') return;
  const brief = savedCases.briefs[Number($('saved-case-select').value)];
  if (!brief) return;
  const message = (savedCases.provenance || 'Observed model outputs; source questions and constraints are author-supplied.')
    + (savedCases.status === 'halted' ? ' The run halted; this brief contains the saved available candidates only.' : '')
    + (brief.reference_comparison ? ' This benchmark-only comparison explicitly includes an authored reference; it is not an extracted alternative or an automatic repair.' : ' No reference graph is inserted into this candidate set.');
  await evaluate(brief,emptyState(),message);
});

$('import-open').addEventListener('click', () => {
  importReadSequence++;
  $('import-error').hidden = true;
  $('import-dialog').showModal();
  $('import-text').focus();
});
for (const id of ['import-close','import-cancel']) $(id).addEventListener('click', () => { importReadSequence++; $('import-dialog').close(); });
$('import-text').addEventListener('input', () => importReadSequence++);
$('import-file').addEventListener('change', async event => {
  const sequence = ++importReadSequence;
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 500000) { $('import-error').textContent = 'Choose a JSON file smaller than 500 KB.'; $('import-error').hidden = false; return; }
  try { const text = await file.text(); if (sequence !== importReadSequence || !$('import-dialog').open) return; $('import-text').value = text; $('import-error').hidden = true; }
  catch { if (sequence !== importReadSequence || !$('import-dialog').open) return; $('import-error').textContent = 'This file could not be read.'; $('import-error').hidden = false; }
});
$('import-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (app.pending) return;
  try {
    const text = $('import-text').value;
    if (new TextEncoder().encode(text).length > 500000) throw new Error('The pasted brief exceeds 500 KB.');
    const input = JSON.parse(text);
    const brief = input.brief || input;
    const state = input.brief ? {...emptyState(), ...(input.state || {})} : emptyState();
    // Preserve original bytes for the server's duplicate-key validation. Local
    // JSON.parse is only provisional; its result is never committed before validation.
    const rawEnvelope = input.brief ? text : '{"brief":' + text + ',"state":{}}';
    const success = await evaluate(brief,state,'Imported brief validated. The calculation is conditional on its supplied relationships.',rawEnvelope);
    if (success) $('import-dialog').close();
  } catch (error) { $('import-error').textContent = error.message; $('import-error').hidden = false; }
});
$('reset-state').addEventListener('click', () => app.brief && evaluate(app.brief,emptyState(),'Answers and exclusions reset. The supplied brief is unchanged.'));
$('load-demo').addEventListener('click', loadDemo);
$('clear-scenario').addEventListener('click', () => updateState(s => {s.scenario_withdrawals=[];}, 'Scenario cleared. Explicit document and passage exclusions remain.'));
$('export-brief').addEventListener('click', () => app.brief && download({brief:app.brief,state:app.state},exportName('-session.json')));
$('download-audit').addEventListener('click', () => app.analysis && download(app.analysis,exportName('-audit.json')));
document.addEventListener('change', event => {
  const control = event.target;
  const documentId = control.dataset.revokeDocument;
  const passageId = control.dataset.revokePassage;
  if (!documentId && !passageId) return;
  const key = documentId ? 'revoked_documents' : 'revoked_passages';
  const id = documentId || passageId;
  const desired = control.checked;
  const pending = updateState(state => {
    const values = new Set(state[key]);
    desired ? values.add(id) : values.delete(id);
    state[key] = [...values];
  }, desired ? 'Support exclusion applied. Falsity is not asserted.' : 'This exclusion was removed. Other exclusions and original eligibility still apply.');
  pending?.then(success => { if (!success && app.brief) render(); });
});
document.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button || app.pending) return;
  if (button.dataset.focusDecision || button.dataset.clearTargets) {
    const brief = JSON.parse(JSON.stringify(app.brief));
    if (button.dataset.focusDecision) brief.target_decisions = [button.dataset.focusDecision];
    else delete brief.target_decisions;
    evaluate(brief,app.state,'Clarification target updated. Source interpretations and exclusions are unchanged.');
  } else if (button.dataset.applyWitness) {
    const witness = app.witnesses.get(button.dataset.applyWitness);
    if (!witness) return;
    updateState(state => {state.scenario_withdrawals = witness.scenario_withdrawals || [...new Set([...state.scenario_withdrawals,...witness.withdraw])];},'Witness applied. Support and the clarification plan were recomputed for this scenario.');
  } else if (button.dataset.answer) {
    const answer = button.dataset.answer === 'yes' ? true : button.dataset.answer === 'no' ? false : null;
    updateState(state => {state.answers = {...state.answers,[button.dataset.question]:answer};},answer === null ? 'Marked unknown. No interpretation is eliminated by an unknown answer.' : 'Answer applied to the supplied candidate table. Decisions and the next clarification were recomputed.');
  } else if (button.dataset.clearAnswer) {
    updateState(state => {delete state.answers[button.dataset.clearAnswer];},'Answer cleared. Compatible interpretations were restored where appropriate.');
  }
});

(async function start() {
  const catalogReady = refreshSavedCases();
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    if (saved?.brief && saved?.state) {
      if (await evaluate(saved.brief,saved.state,'Restored the session saved in this browser.')) return;
    }
  } catch { /* A missing or unreadable browser cache never blocks the demo. */ }
  await catalogReady;
  const fresh = savedCases.briefs.find(brief => brief.id === 'eligibility-v5-d-ineligible');
  if (fresh && await evaluate(fresh,emptyState(),'Fresh model output from the prospectively frozen paired confirmation. No authored graph or oracle answer was inserted.')) return;
  await loadDemo();
})();
