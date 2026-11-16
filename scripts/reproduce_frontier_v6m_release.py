"""Offline verification of the final host-recovered m artifact. No API or writes.

Original diagnostic results and the separate recovery sensitivity are both
replayed. A historical unclosed k prefix is never relabeled as a closed run.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.reproduce_frontier_v6h_release import canonical,load,require,safe_path,scan_credentials,sha
from scripts import frontier_v6m_products as product
from scripts import reproduce_frontier_v6m_products as products
SCHEMA='retrace.frontier-v6m-recovered-release.v1'
STATUS='complete_host_recovered_schedule'
FREEZE='data/frontier-v6m-freeze.json'
FREEZE_SHA='d8820db0702d53169d4afac813756414e4d67fffd25d31ef312695181023da10'
REPORT='report/v6m-study'
REPORT_RECEIPT=REPORT+'/release-evidence.json'
TEMPLATE='report/template-reference.docx'
TEMPLATE_SHA='0fd7b50198a1b002fa6544df936189538a6c2c55ab0865606139b4127932dda9'
PDF_BYTES_LIMIT=25_000_000
MANIFEST_NAME='release-manifest-v6m.json'
LEDGER='results/frontier-v6m/budget/ledger.jsonl'
SNAPSHOT='data/frontier-v6m-ledger-after-continuation.jsonl'
AUDIT='results/frontier-v6m/continuation/runtime-audit.json'
PREFIX_PROOF='results/frontier-v6m-recovery/k-prefix-proof.json'
POSTCHECKS='results/frontier-v6m/post-sweep/checks.json'
IR_MANIFEST='results/frontier-v6m/catalog/manifest.json'
REFUTER_MANIFEST='results/frontier-v6m/refuter-catalog/manifest.json'
ALIASES=product.score.ALIASES

def report_gate(root):
 spec=importlib.util.spec_from_file_location('m_release_report_gate',safe_path(root,REPORT+'/prepare_sources.py'))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

# Required evidence roles include no invented k summary or closed-k runtime audit.
_gate=report_gate(ROOT)
REQUIRED_EVIDENCE=set(_gate.PATHS.values())|{LEDGER,POSTCHECKS}
ADDITIONS={
 'scripts/assemble_frontier_v6m_release.py','scripts/reproduce_frontier_v6m_release.py',
 'tests/test_frontier_v6m_release.py','README-V6M.md','REPRODUCE-V6M.md','START-V6M.ps1','SOURCE-NOTICES-V6.md',
 'scripts/frontier_v6m_products.py','scripts/reproduce_frontier_v6m_products.py',
 'scripts/export_frontier_v6m_catalog.py','scripts/export_frontier_v6m_refuters.py',
 'retrace/evidence_catalog_v6m.py','retrace/refuter_catalog_v6m.py','retrace/refuter_reader_v6m.py','retrace/server_v6m.py',
 'web/v6m/index.html','web/v6m/diagnostic.html','web/v6m/evidence.js','web/v6m/refuters.js',
 'web/v6h/app.js','web/v6h/style.css','scripts/check_frontier_v6m_post_sweep.py',
 'tests/test_frontier_v6m_post_sweep.py','tests/test_frontier_v6m_products.py',
 'tests/test_frontier_v6m_product_replay.py','tests/test_evidence_v6m.mjs','tests/test_refuters_v6m.mjs',
 'scripts/analyze_frontier_v6m_supplements.py','tests/test_frontier_v6m_supplements.py',
 'research/frontier-v6m-product-preparation.md',
 REPORT+'/prepare_sources.py',REPORT+'/build_docx.py',REPORT+'/template_builder.py',
 REPORT+'/test_prepare_sources.py',REPORT+'/artifact.md',REPORT+'/README.md',REPORT+'/author-metadata.json',
 REPORT+'/preclosure-narrative.txt',REPORT+'/references.json'}

def entry(root,name):
 p=safe_path(root,name);return {'path':name,'sha256':sha(p),'bytes':p.stat().st_size}

def entries_index(root,rows):
 require(isinstance(rows,list) and rows,'Nonempty inventory')
 result={};seen=set()
 for row in rows:
  require(isinstance(row,dict) and set(row)=={'path','sha256','bytes'},'Strict inventory entry')
  name=row['path'];p=safe_path(root,name)
  require(name.casefold() not in seen,'Duplicate case-folded member')
  require(type(row['bytes']) is int and row['bytes']>=0 and isinstance(row['sha256'],str) and re.fullmatch('[a-f0-9]{64}',row['sha256']),'Inventory types')
  require(p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],'Changed inventory '+name)
  seen.add(name.casefold());result[name]=row
 return result

def report_files(root, freeze_sha256):
    """Verify finalized report receipt, every page and exact final-study inputs."""
    receipt = load(safe_path(root, REPORT_RECEIPT))
    require(receipt.get("schema") == "retrace.v6m-report-release-evidence.v1"
        and receipt.get("status") == "verified" and receipt.get("study_status") == "complete_host_recovered_schedule", "Final report receipt required")
    main = receipt.get("main_pages"); total = receipt.get("total_pages")
    require(type(main) is int and main == 7 and type(total) is int and main <= total <= 100, "Report page limits")
    indexed = entries_index(root, receipt.get("files")); names = set(indexed)
    require(REPORT_RECEIPT not in names, "Report receipt cannot hash itself")
    artifacts = receipt.get("artifacts")
    required = {"markdown", "docx", "pdf", "build_manifest", "render_manifest", "verification", "visual_review",
        "builder", "source_manifest", "authoring_evidence", "layout", "references", "author_metadata"}
    require(isinstance(artifacts, dict) and required <= set(artifacts), "Report artifact roles")
    require(all(isinstance(p, str) and p.startswith(REPORT + "/") and p in names for p in artifacts.values()), "Report role outside inventory")
    require(len({p.casefold() for p in artifacts.values()}) == len(artifacts), "Duplicate report role file")
    for kind, ext in (("markdown", ".md"), ("docx", ".docx"), ("pdf", ".pdf")):
        require(artifacts[kind].endswith(ext), "Report role extension")
    require(indexed[artifacts['pdf']]['bytes'] < PDF_BYTES_LIMIT, 'Submission PDF must be smaller than 25,000,000 bytes')
    evidence = receipt.get("evidence_inputs")
    require(isinstance(evidence, dict) and REQUIRED_EVIDENCE <= set(evidence), "Report must bind every final evidence role")
    require(evidence[FREEZE] == freeze_sha256, "Report binds another execution freeze")
    for name, expected in evidence.items():
        require(sha(safe_path(root, name)) == expected, "Report evidence changed: " + name)
    read = lambda role: load(safe_path(root, artifacts[role]))
    author=read("author_metadata")
    require(isinstance(author.get("authors"),list) and len(author["authors"])==1, "Sole author metadata required")
    expected_author={"full_name":"Christian Lysenstøen","affiliation":"University of Inland Norway",
        "academic_status":"Undergraduate Student","country":"Norway",
        "display_affiliation":"Undergraduate Student, University of Inland Norway, Norway"}
    require(all(author["authors"][0].get(key)==value for key,value in expected_author.items()), "Exact supplied author and printed affiliation required")
    build = read("build_manifest"); render = read("render_manifest"); verification = read("verification"); visual = read("visual_review")
    docx = indexed[artifacts["docx"]]["sha256"]; pdf = indexed[artifacts["pdf"]]["sha256"]
    require(build.get("scientific_placeholders_remaining") == 0
        and build.get("output_sha256") == docx and isinstance(build.get("evidence_inputs"), dict)
        and all(build["evidence_inputs"].get(p) == h for p, h in evidence.items()), "Report build/evidence binding")
    source_inputs = build.get("source_inputs")
    required_sources = {artifacts[role] for role in ("markdown", "builder", "source_manifest", "authoring_evidence", "layout", "references", "author_metadata")} | {TEMPLATE}
    require(isinstance(source_inputs, dict) and required_sources <= set(source_inputs), "Report must bind current authored source dependencies")
    require(source_inputs[TEMPLATE] == TEMPLATE_SHA, "Official report template binding changed")
    for name, expected in source_inputs.items():
        require(sha(safe_path(root, name)) == expected, "Report source changed after build: " + name)
    require(verification.get("status") == "passed" and visual.get("status") == "passed", "Report technical/visual verification required")
    require(verification.get("docx_sha256") == docx and verification.get("pdf_sha256") == pdf,
        "Technical verification must bind current report outputs")
    require(render.get("docx_sha256") == visual.get("docx_sha256") == docx
        and render.get("pdf_sha256") == visual.get("pdf_sha256") == pdf, "Report output/render/visual binding")
    require(render.get("main_pages_including_title") == main and render.get("total_pages") == total, "Report layout counts")
    pages = receipt.get("pages"); sequence = list(range(1, total + 1))
    require(isinstance(pages, list) and [p.get("page") for p in pages] == sequence, "Ordered complete page list")
    require(render.get("pages") == pages and visual.get("inspected_pages") == sequence
        and visual.get("unresolved_visual_issues") == [], "All current pages must be visually reviewed")
    page_hashes = {}
    for page in pages:
        require(set(page) == {"page", "path", "sha256"}, "Page entry schema")
        path = page["path"]
        require(path.startswith(REPORT + "/") and path.lower().endswith(".png") and path in indexed, "Page missing from report inventory")
        require(path.casefold() not in {p.casefold() for p in page_hashes}, "Duplicate page path")
        require(page["sha256"] == indexed[path]["sha256"], "Page digest mismatch")
        page_hashes[path] = page["sha256"]
    require(visual.get("page_sha256_by_path") == page_hashes, "Visual review does not bind all page images")
    require(isinstance(visual.get("review_method"), str) and visual["review_method"].strip(), "Explicit visual review method")
    human = receipt.get("human_review_complete"); submission = receipt.get("submission_ready")
    require(type(human) is bool and type(submission) is bool and visual.get("human_review_complete") is human, "Human review provenance")
    require(type(author.get('human_manuscript_review_completed')) is bool
        and author['human_manuscript_review_completed'] is human, 'Author metadata and report human-review record must agree')
    if 'build_authentication' in artifacts:
        require(read('build_authentication').get('human_review_complete') is human,
            'Build authentication and report human-review record must agree')
    require(human is False and submission is False, "This release remains a draft awaiting human review and submission approval")
    names |= set(evidence) | set(source_inputs) | {REPORT_RECEIPT}
    return names, {"receipt_path": REPORT_RECEIPT, "receipt_sha256": sha(safe_path(root, REPORT_RECEIPT)),
        "main_pages": main, "total_pages": total, "pdf_sha256": pdf, "docx_sha256": docx,
        "human_review_complete": human, "submission_ready": submission}


def verify_postchecks(root,aliases=None):
    aliases=dict(aliases or {})
    value=load(safe_path(root,POSTCHECKS))
    require(value.get('schema')=='retrace.frontier-v6m-post-sweep-checks.v1' and value.get('passed') is True,
        'Completed post-sweep checks required')
    require(value.get('provider_calls')==0 and value.get('network_used') is False and value.get('servers_started') is False,
        'Post-sweep checks must be zero-call and offline')
    require(value.get('source_freeze_sha256')==FREEZE_SHA and value.get('runtime_audit_sha256')==sha(safe_path(root,AUDIT))
        and value.get('runtime_schedule_status')=='completed','Post-sweep checks bind this closed recovery')
    bindings=value.get('source_bindings');require(isinstance(bindings,dict) and bindings,'Post-sweep source bindings')
    for name,wanted in bindings.items():
        p=safe_path(root,aliases.get(name,name),allow_lock=name in ALIASES and name not in aliases)
        require(wanted=={'sha256':sha(p),'bytes':p.stat().st_size},'Changed post-sweep input '+name)
    outputs=value.get('files');expected={'results/frontier-v6m/post-sweep/'+name for name in
        ('rule-baseline-cases.json','rule-baselines.json','event-sequence-vs-fresh.json')}
    require(isinstance(outputs,dict) and set(outputs)==expected,'Exact authored post-sweep check artifacts')
    for name,wanted in outputs.items():
        p=safe_path(root,name);require(wanted=={'sha256':sha(p),'bytes':p.stat().st_size},'Changed post-sweep output')
    return value


def freeze_binding(root,freeze_sha256,aliases):
    require(freeze_sha256==FREEZE_SHA and sha(safe_path(root,FREEZE))==freeze_sha256,'Exact m execution freeze')
    require(isinstance(aliases,dict) and all(ALIASES.get(k)==v for k,v in aliases.items()),'Exact inert old-lock aliases')
    frozen=load(safe_path(root,FREEZE));require(frozen['schema']=='retrace.frontier-v6m-freeze.v1'
        and frozen['scheduled_slots']==1800 and frozen['continuation_slots']==554
        and frozen['carried_final_slots']==1246 and frozen['cumulative_cap_credits']=='750'
        and frozen['previous_cumulative_cap_credits']=='250','Prospective recovery contract')
    seen=set()
    for row in frozen['files']:
        name=row['path'];require(name.casefold() not in seen,'Duplicate frozen member');seen.add(name.casefold())
        path=safe_path(root,aliases.get(name,name),allow_lock=name in ALIASES and name not in aliases)
        require(sha(path)==row['sha256'] and path.stat().st_size==row['bytes'],'Frozen input changed '+name)
    return frozen


def optional_supplements(root,result,artifacts,sources,data,aliases):
    directory=Path(root)/'results/frontier-v6m/supplements'
    if not directory.exists(): return set(),None
    from scripts import analyze_frontier_v6m_supplements as supplement
    manifest_path='results/frontier-v6m/supplements/manifest.json';saved=load(safe_path(root,manifest_path))
    require(saved.get('schema')=='retrace.frontier-v6m-descriptive-supplements.v1'
        and saved.get('study_status')==STATUS and saved.get('diagnostic') is False
        and saved.get('provider_calls')==0 and saved.get('new_inferential_tests')==0
        and saved.get('source_observations_changed') is False,'Explicit descriptive supplement scope')
    require(saved['authenticated_input_bindings']==artifacts and saved['authenticated_source_bindings']==sources,
        'Supplements must use the same authenticated evidence')
    require(all(ALIASES.get(k)==v for k,v in saved['frozen_aliases'].items()),'Supplement aliases')
    outputs=supplement.project(result,data)
    expected={'results/frontier-v6m/supplements/'+name:supplement.encode(value) for name,value in outputs.items()}
    require(set(saved['files'])==set(expected),'Exact descriptive supplement inventory')
    for name,raw in expected.items():
        p=safe_path(root,name)
        require(p.read_bytes()==raw and saved['files'][name]=={'sha256':sha(p),'bytes':p.stat().st_size},
            'Descriptive arithmetic must reproduce exactly')
    supplement.recheck(Path(root),{**saved,'frozen_aliases':aliases})
    names={manifest_path}|set(expected)|set(saved['analysis_source_bindings'])
    return names,{'manifest_path':manifest_path,'manifest_sha256':sha(safe_path(root,manifest_path)),
        'outputs':3,'provider_calls':0,'new_inferential_tests':0}


def authenticated(root,freeze_sha256,aliases):
    require(not (Path(root)/'results/frontier-v6m/budget/active.lock').exists(),'Recovery worker still active')
    freeze_binding(root,freeze_sha256,aliases)
    # This invokes the frozen pure scorer and independent prefix/runtime replay,
    # once for the composite and both public catalogs.
    result,artifacts,sources,data=product.authenticated(Path(root),freeze_sha256,sha(safe_path(root,PREFIX_PROOF)),
        sha(safe_path(root,AUDIT)),SNAPSHOT,sha(safe_path(root,SNAPSHOT)),frozen_aliases=aliases,diagnostic=False)
    gate=report_gate(root);gate.validate_summary(result['summary'])
    require(sha(safe_path(root,LEDGER))==sha(safe_path(root,SNAPSHOT)),'Closed m ledger and snapshot differ')
    checks=verify_postchecks(root,aliases)
    names=set(artifacts)|set(sources)|set(checks['source_bindings'])|set(checks['files'])
    catalog_checks=[]
    for kind,manifest_path in (('catalog',IR_MANIFEST),('refuter-catalog',REFUTER_MANIFEST)):
        pin=sha(safe_path(root,manifest_path))
        check=products.verify_catalog(root,kind,freeze_sha256,pin,result,artifacts,sources,data,
            diagnostic=False,frozen_aliases=aliases)
        catalog_checks.append(check);manifest=load(safe_path(root,manifest_path))
        names.add(manifest_path);names.update(manifest['files']);names.update(manifest['exporter_source_bindings'])
    supplementary_names,supplementary_check=optional_supplements(root,result,artifacts,sources,data,aliases)
    names|=supplementary_names
    report_names,report=report_files(root,freeze_sha256);names|=report_names
    return names,{'status':STATUS,'planned_slots':1800,'original_frozen_inference_available':False,
        'amended_sensitivity_available':True,'request_accounting':result['summary']['request_accounting'],
        'runtime_audit_sha256':sha(safe_path(root,AUDIT)),'prefix_proof_sha256':sha(safe_path(root,PREFIX_PROOF)),
        'score_sha256':sha(safe_path(root,'results/frontier-v6m/composite/score.json')),
        'post_sweep_sha256':sha(safe_path(root,POSTCHECKS)),'catalogs':catalog_checks,'report':report,
        'descriptive_supplements':supplementary_check,
        'scope':'Original frozen diagnostic and separately amended recovery sensitivity are both reproduced; k remains unclosed.'}


def verify(root,manifest,freeze_sha256):
    root=Path(root).resolve()
    require(manifest.get('schema')==SCHEMA and manifest.get('status')==STATUS,'Host-recovered release only')
    require(manifest.get('original_frozen_inference_available') is False and manifest.get('amended_sensitivity_available') is True,
        'Do not replace diagnostic inference with sensitivity')
    require(manifest.get('freeze')=={'path':FREEZE,'sha256':freeze_sha256},'Pinned release freeze')
    aliases=manifest.get('frozen_aliases',{});frozen=freeze_binding(root,freeze_sha256,aliases)
    inventory=entries_index(root,manifest['files'])
    require(manifest['file_set_sha256']==hashlib.sha256(canonical(manifest['files']).encode()).hexdigest(),'Inventory digest')
    required=set(ADDITIONS)|REQUIRED_EVIDENCE|{REPORT_RECEIPT,IR_MANIFEST,REFUTER_MANIFEST}
    required|={aliases.get(row['path'],row['path']) for row in frozen['files']}
    require(required<=set(inventory),'Required recovery evidence missing')
    for path in inventory:
        require(not path.endswith('/active.lock') and not any(p in ('.venv','__pycache__','.git') for p in Path(path).parts)
            and not path.endswith(('.pyc','.pyo')),'No active locks, caches or environments')
    names,replay=authenticated(root,freeze_sha256,aliases)
    require({aliases.get(name,name) for name in names}<=set(inventory),'Replayed source/product/report omitted from ZIP')
    require(replay==manifest['reproduction'],'Reproduction differs from assembly receipt')
    entries_index(root,manifest['files'])
    return {'schema':'retrace.frontier-v6m-release-reproduction.v1','passed':True,'status':STATUS,
        'files':len(inventory),'planned_slots':1800,'provider_calls':0,'original_frozen_inference_available':False,
        'amended_sensitivity_available':True,'human_review_complete':False,'submission_ready':False,
        'scope':'Hash and pure replay verification; visual quality relies on current hash-bound all-page review receipts.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--manifest',default=MANIFEST_NAME);parser.add_argument('--freeze-sha256',required=True)
    args=parser.parse_args();manifest=load(safe_path(args.root,args.manifest))
    print(json.dumps(verify(args.root,manifest,args.freeze_sha256),indent=2))


if __name__=='__main__':main()


