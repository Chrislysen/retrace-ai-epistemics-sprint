'use strict';
// The frozen workbench functions stay unchanged. This adapter only imports a
// recorded declaration and shows its separate, unverified source provenance.
(() => {
  const element = id => document.getElementById(id);
  const stateLabels = {
    admitted: 'Schema admitted · meaning unverified',
    admitted_registry_gap: 'Admitted with a Reference-Free Coverage Gap',
    invalid_ir: 'Invalid source IR · no repaired interpretation',
    scoring_unavailable: 'Admission unavailable in the frozen score',
    provider_failure: 'Provider failure · no interpretation available',
    truncated_output: 'Truncated output · not used as an interpretation',
    not_issued: 'Not issued · retained in the scheduled denominator'
  };
  let entries = [], selected = null, loading = false, diagnosing = false, requestNumber = 0;
  const text = (tag, value, className) => {
    const e = document.createElement(tag); e.textContent = String(value ?? '');
    if (className) e.className = className; return e;
  };
  function refreshButtons() {
    const blocked = busy || loading;
    element('catalog-load').disabled = blocked || !selected?.brief;
    element('catalog-download').disabled = blocked || !selected?.brief;
    element('catalog-raw-download').disabled = blocked || !selected;
    element('catalog-diagnose').disabled = blocked || diagnosing || !selected?.metadata?.provider_completed || selected?.metadata?.status !== 'invalid_ir';
    element('catalog-case').disabled = blocked || !entries.length;
    element('catalog-model').disabled = blocked || !entries.length;
  }
  function clearOrigin() {
    element('recorded-origin').hidden = true;
    element('recorded-origin').replaceChildren();
  }
  function option(value,label) {
    const o = document.createElement('option'); o.value = value; o.textContent = label; return o;
  }
  function fillModels() {
    const box = element('catalog-model'), previous = box.value;
    const rows = entries.filter(row => row.case_id === element('catalog-case').value);
    box.replaceChildren(...rows.map(row => option(row.model,`${row.model} · ${stateLabels[row.status]}`)));
    if (rows.some(row => row.model === previous)) box.value = previous;
  }
  function showEntry(row,value) {
    selected = value;
    const panel = element('catalog-entry'); panel.hidden = false; panel.replaceChildren();
    const stateLabel = value.metadata?.model_outcome === 'not_issued_global_stop'
      ? 'Unissued because the study stopped · censored, not an observed model error'
      : stateLabels[row.status];
    panel.append(text('h3',stateLabel),
      text('p',`${row.case_id} · ${row.model} · First attempt`, 'catalog-meta'),
      text('p',`Bare JSON: ${row.strict_bare_json ? 'yes' : 'no'}. Declared readings: ${value.brief ? row.candidate_count : 'unavailable'}.`, 'hint'));
    if (row.registry_coverage_gaps?.length) panel.append(text('p',`Missing identifier dispositions: ${row.registry_coverage_gaps.join(', ')}. The workbench withholds decision claims.`, 'hint'));
    panel.append(text('p',value.brief
      ? 'Loading starts from the original declared local eligibility with no added event vetoes. It does not reproduce a scored temporal phase. Source meaning and completeness remain unverified.'
      : 'This observation remains visible but cannot be loaded as a graph. Its output has not been repaired.', 'hint'));
    const output = document.createElement('details');
    output.append(text('summary','Inspect original returned text'),text('pre',value.raw_output_text || '(No completed output text)', 'output'));
    panel.append(output);
    if (value.partial_output_text) {
      const partial = document.createElement('details');
      partial.append(text('summary','Inspect truncated text · excluded from analysis'),text('pre',value.partial_output_text,'output'));
      panel.append(partial);
    }
    const source = document.createElement('details');
    source.append(text('summary','Inspect public source documents'));
    for (const doc of value.source_documents || []) source.append(text('h3',doc.title || doc.id),text('pre',doc.text,'source-prose'));
    panel.append(source);
    const provenance = document.createElement('details');
    provenance.append(text('summary','Inspect source paths and hashes'),text('pre',JSON.stringify(value.provenance,null,2),'output'));
    panel.append(provenance);
  }
  async function selectEntry() {
    const row = entries.find(r => r.case_id === element('catalog-case').value && r.model === element('catalog-model').value);
    if (!row) return;
    const token = ++requestNumber; loading = true; diagnosing = false; selected = null;
    element('catalog-diagnosis').hidden = true; element('catalog-diagnosis').replaceChildren(); refreshButtons();
    element('catalog-message').textContent = 'Reading the bound observation locally…';
    try {
      const response = await fetch(`/api/v6l/catalog/${encodeURIComponent(row.key)}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Observation could not be loaded');
      if (token !== requestNumber) return;
      showEntry(row,result);
      element('catalog-message').textContent = 'Selected observation only. The current workbench changes when you load its declaration.';
    } catch (e) {
      if (token !== requestNumber) return;
      element('catalog-entry').hidden = true;
      element('catalog-message').textContent = e.message;
    } finally { if (token === requestNumber) { loading = false; refreshButtons(); } }
  }
  element('catalog-case').addEventListener('change',() => { fillModels(); selectEntry(); });
  element('catalog-model').addEventListener('change',selectEntry);
  element('catalog-load').addEventListener('click',async () => {
    if (busy || loading || !selected?.brief) return;
    const observation = selected, brief = copy(observation.brief);
    clearOrigin(); loadBrief(brief); await analyze();
    if (dirty || !current || JSON.stringify(activeBrief) !== JSON.stringify(brief)) return;
    const origin = element('recorded-origin');
    origin.append(text('strong','RECORDED MODEL INTERPRETATION · MEANING UNVERIFIED'),
      text('p',`${observation.metadata.case_id} · ${observation.metadata.model} · First attempt`),
      text('p','Answers and vetoes started cleared. Subsequent clarification and withdrawal choices are local explorations, not additional model responses. Editing the source or IR removes this provenance label.'));
    origin.hidden = false;
    element('analysis').scrollIntoView({behavior:'smooth',block:'start'});
    refreshButtons();
  });
  element('catalog-download').addEventListener('click',() => {
    if (!busy && !loading && selected?.brief) download('retrace-recorded-declaration.json',selected.brief);
  });
  element('catalog-raw-download').addEventListener('click',() => {
    if (!busy && !loading && selected) download('retrace-recorded-observation.json',selected);
  });
  element('catalog-diagnose').addEventListener('click',async () => {
    if (busy || loading || diagnosing || selected?.metadata?.status !== 'invalid_ir' || !selected.metadata.provider_completed) return;
    const observation = selected, token = requestNumber, panel = element('catalog-diagnosis');
    diagnosing = true; refreshButtons(); panel.hidden = false;
    panel.replaceChildren(text('p','Checking the original rejection locally…'));
    try {
      const response = await fetch(`/api/v6l/catalog/${encodeURIComponent(observation.metadata.key)}/diagnosis`);
      const result = await response.json();
      if (token !== requestNumber || selected !== observation) return;
      if (!response.ok) throw new Error(result.error || 'Local diagnosis unavailable');
      if (result.schema !== 'retrace.source-diagnostics.v6k.v1' || result.compile_admitted !== false
          || result.raw_text_sha256 !== observation.provenance.raw_output_text_sha256
          || result.source_packet_sha256 !== observation.provenance.public_source_sha256
          || result.slot_id !== observation.metadata.slot_id)
        throw new Error('Diagnostic does not match the selected rejected observation');
      panel.replaceChildren(text('h3','Local rejection review · no repair'),
        text('p','This explains the frozen compiler rejection. It changes no recorded output, graph, benchmark score or current workbench.'),
        text('p',result.original_error?.message || 'No localized compiler message'),
        text('p',`Parser syntax: ${result.parser_admitted ? (result.strict_bare_json ? 'bare JSON' : 'admitted outer wrapper') : 'not admitted'}. This is separate from the frozen benchmark success criterion.`, 'hint'));
      for (const issue of result.diagnostics || []) {
        const labels = {malformed_closing_fence_boundary:'Closing fence is not on a separate line',
          overlapping_current_definitions:'Active definitions overlap'};
        panel.append(text('h3',labels[issue.kind] || 'Recorded structural detail'),text('pre',JSON.stringify(issue,null,2),'output'));
      }
      if (result.localization_status === 'not_localized') panel.append(text('p','The exact cause could not be localized safely. No correction is guessed.'));
    } catch (e) {
      if (token === requestNumber && selected === observation) panel.replaceChildren(text('p',e.message));
    } finally { if (token === requestNumber && selected === observation) { diagnosing = false; refreshButtons(); } }
  });
  for (const id of ['bundle','ir']) element(id).addEventListener('input',clearOrigin);
  for (const id of ['demo','import']) element(id).addEventListener('click',clearOrigin,true);
  element('file').addEventListener('change',clearOrigin,true);
  new MutationObserver(refreshButtons).observe(document.body,{attributes:true,attributeFilter:['class']});
  async function start() {
    refreshButtons();
    try {
      const response = await fetch('/api/v6l/catalog'), value = await response.json();
      if (!response.ok) throw new Error(value.error || 'Catalog unavailable');
      if (!value.available) { element('catalog-message').textContent = value.scope; return; }
      entries = value.entries;
      element('catalog-total').textContent = `${entries.length} scheduled observations · all 60 cases · five primary models`;
      element('catalog-counts').textContent = Object.entries(value.counts || {}).map(([key,n]) => `${stateLabels[key] || key}: ${typeof n === 'object' ? JSON.stringify(n) : n}`).join(' · ');
      const cases = [...new Set(entries.map(r => r.case_id))];
      element('catalog-case').replaceChildren(...cases.map(id => option(id,id)));
      fillModels(); await selectEntry();
    } catch (e) { element('catalog-message').textContent = e.message; }
    finally { refreshButtons(); }
  }
  start();
})();
