'use strict';
// Read-only controlled-seed inspector. Never load a seed/proposal into the workbench.
(() => {
  const el = id => document.getElementById(id);
  const labels = {source_located_proposal:'Source-located proposal · meaning unverified',
    abstained:'Abstained · completeness not certified', rejected:'Envelope or declaration rejected',
    provider_failure:'Provider failure', truncated_output:'Truncated · excluded from comparison',
    not_issued:'Unissued · stop-censored'};
  let entries = [], selected = null, sequence = 0;
  function refresh() {
    el('refuter-download').disabled=busy || !selected;
    el('refuter-case').disabled=busy || !entries.length;
    el('refuter-model').disabled=busy || !entries.length;
  }
  const text = (tag,value,cls) => {const n=document.createElement(tag);n.textContent=String(value ?? '');if(cls)n.className=cls;return n;};
  const detail = (title,value) => {const d=document.createElement('details');d.append(text('summary',title),text('pre',typeof value==='string'?value:JSON.stringify(value,null,2),'output'));return d;};
  const option = (value,label) => {const o=text('option',label);o.value=value;return o;};
  const flags = v => `all readings: ${v.box_supported?'supported':'not universally supported'}; some reading supported: ${v.diamond_supported?'yes':'no'}`;
  function models() {
    const box=el('refuter-model'), old=box.value;
    const rows=entries.filter(r=>r.case_id===el('refuter-case').value);
    box.replaceChildren(...rows.map(r=>option(r.model,`${r.model} · ${labels[r.status]}`)));
    if(rows.some(r=>r.model===old))box.value=old;
  }
  function show(value) {
    const box=el('refuter-entry'), m=value.metadata, inspection=value.inspection;
    box.hidden=false;box.replaceChildren(text('h3',labels[m.status]),text('p',`${m.case_id} · ${m.model} · first attempt`, 'small'),
      text('p',value.scope));
    box.append(detail('Authored candidate family supplied to this refuter',value.supplied_candidates),
      detail('Original returned text',value.raw_output_text || '(No completed output text)'));
    if(value.partial_output_text)box.append(detail('Retained partial text · excluded from analysis',value.partial_output_text));
    const source=document.createElement('details');source.append(text('summary','Exact public source documents'));
    for(const doc of value.source_documents)source.append(text('h3',doc.id),text('pre',doc.text,'source-prose'));
    box.append(source);
    if(inspection) {
      const gate=inspection.gate;
      box.append(text('h3','Location and schema gate'),text('p',gate.status==='rejected'
        ? `Rejected before any comparison: ${gate.reason}`
        : `Admitted ${gate.strict_bare_json?'bare JSON':'whole outer wrapper; not strict bare JSON'}. Locations do not establish entailment.`));
      if(gate.raw_warning_score!==undefined)box.append(text('p',`Raw model warning score: ${gate.raw_warning_score}. Uncalibrated; not proof or a product confidence.`, 'small'));
      for(const span of gate.locations || [])box.append(detail(`Cited source: ${span.document_id}, code points ${span.start}–${span.end}`,span.text));
      if(inspection.status==='abstained')box.append(text('p',inspection.abstention_scope));
      const p=inspection.preview;
      if(p) {
        box.append(text('h3','Conditional effect of adding the proposal'),text('p','Seed G → G union P. Every seed reading remains; no correction or replacement is applied.'));
        if(p.status==='unavailable')box.append(text('p',`Comparison unavailable: ${p.reason}. No absence of effect is inferred.`));
        else {
          const d=p.declaration_comparison;
          box.append(text('p',`${d.seed_distinct} distinct seed readings; ${d.proposal_distinct} proposed; ${d.union_distinct} in the union. ${d.novel_proposed_readings} proposed readings are structurally new. Novel does not mean correct.`));
          if(p.modal_summary.status==='evaluated')for(const [id,row] of Object.entries(p.modal_summary.decisions))
            box.append(text('p',`${id}: seed (${flags(row.seed)}) → union (${flags(row.augmented)}).`));
          else box.append(text('p',`Current modal summary unavailable: ${p.modal_summary.reason}`));
          const w=p.decision_impact;box.append(text('h3','Smallest additional record withdrawal'));
          if(w.status!=='evaluated')box.append(text('p',`Unavailable: ${w.reason}. No absence of effect is inferred.`));
          else for(const row of w.decisions)box.append(text('p',row.withdraw===null
            ? `${row.decision}: no modal change from addition within the exact declared withdrawal scope.`
            : `${row.decision}: k=${row.minimum_k}; withdraw ${row.withdraw.join(', ')||'no records'}. Seed (${flags(row.current)}) → union (${flags(row.augmented)}).`));
          box.append(text('h3','Hypothetical original-ineligibility exposure'));
          const h=document.createElement('div');renderHamming(h,p.hamming2);box.append(h);
          if(p.hamming2.status==='evaluated')for(const witness of p.hamming2.witnesses)
            box.append(text('p',`${witness.decision}: after BOTH hypothetical actions, union G + P (${flags(witness.augmented_enabled_and_withdrawn)}). The preceding proposed trajectory describes P alone, not a replacement for G.`));
          box.append(text('p','No document or passage veto is inferred from the request. This preview cannot restore a named veto and never changes original eligibility.', 'small'));
        }
      }
      box.append(detail('Complete reference-free gate and mechanism audit',inspection));
    }
    box.append(detail('First-attempt paths and byte hashes',value.provenance));
  }
  async function choose() {
    const row=entries.find(r=>r.case_id===el('refuter-case').value&&r.model===el('refuter-model').value);
    if(!row)return;const token=++sequence;selected=null;el('refuter-download').disabled=true;
    el('refuter-entry').hidden=true;el('refuter-message').textContent='Reading the bound first attempt locally…';
    try {
      const response=await fetch(`/api/v6n/refuters/${encodeURIComponent(row.key)}`),value=await response.json();
      if(token!==sequence)return;if(!response.ok)throw new Error(value.error||'Observation unavailable');
      if(value.metadata.key!==row.key||value.metadata.selection_view!=='first_attempt'||value.metadata.condition!=='adversarial_refuter')throw new Error('Observation identity differs');
      selected=value;show(value);el('refuter-download').disabled=false;
      el('refuter-message').textContent='Read-only comparison. The active workbench and every recorded output remain unchanged.';
    } catch(e) {if(token===sequence)el('refuter-message').textContent=e.message;}
  }
  el('refuter-case').addEventListener('change',()=>{models();choose();});
  el('refuter-model').addEventListener('change',choose);
  el('refuter-download').addEventListener('click',()=>{if(selected)download('retrace-controlled-seed-observation.json',selected);});
  new MutationObserver(refresh).observe(document.body,{attributes:true,attributeFilter:['class']});
  refresh();
  (async()=>{
    try {
      const response=await fetch('/api/v6n/refuters'),value=await response.json();
      if(!response.ok)throw new Error(value.error||'Catalog unavailable');
      if(!value.available){el('refuter-message').textContent=value.scope;return;}
      entries=value.entries;el('refuter-total').textContent=`${entries.length} scheduled first attempts · controlled authored seeds`;
      el('refuter-counts').textContent=Object.entries(value.counts).map(([s,n])=>`${labels[s]}: ${n}`).join(' · ');
      el('refuter-case').replaceChildren(...value.case_order.map(id=>option(id,id)));
      el('refuter-case').disabled=false;el('refuter-model').disabled=false;models();await choose();
    }catch(e){el('refuter-message').textContent=e.message;}
  })();
})();
