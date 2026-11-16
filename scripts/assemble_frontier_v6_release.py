"""Validate an explicit release inventory; assemble only with --assemble.

No model access, credential loading, regeneration, publication or overwrite.
An active run or unfinished report cannot become a final release archive.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCHEMA = "retrace.frontier-v6-release-inventory.v1"
NATURAL_FREEZE="data/natural-ensemble-v6-freeze.json"
NATURAL_FREEZE_SHA256="a87a66212958c00536f3123a8941a40567f767b6649adb4db6898f796515856a"
SECRET = re.compile(rb"(?:pt_live_[A-Za-z0-9_-]{16,}|(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
ALLOWED_TOP = {"retrace", "scripts", "tests", "data", "results", "research", "report", "deliverables", "web", "web_v6", "web_v6d"}
ALLOWED_ROOT = {"README.md", "README-V6-FRONTIER.md", "REPRODUCE-V6-FRONTIER.md", "REPRODUCE-V5.md",
    "REPRODUCE-V6-EXPERIMENTAL.md", "start-retrace-v6-frontier.ps1", "requirements-v6c.txt", "requirements-v6f.txt",
    "start-retrace-v5.ps1", "start-retrace-v6.ps1", "start-retrace.ps1",
    ".gitignore", "pyproject.toml", "LICENSE", "LICENSE.md", "package.json"}


def require(ok, code):
    if not ok: raise ValueError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""): result.update(block)
    return result.hexdigest()


def load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key"); result[key] = value
        return result
    def invalid(_): raise ValueError("nonfinite_json")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=invalid)


def safe_path(root, name):
    require(isinstance(name, str) and bool(name) and "\\" not in name and ":" not in name, "invalid_inventory_path")
    parts = PurePosixPath(name).parts
    require(not name.startswith("/") and name == "/".join(parts) and all(x not in (".", "..", "") for x in parts), "unsafe_inventory_path")
    require(name in ALLOWED_ROOT or (len(parts)>1 and parts[0] in ALLOWED_TOP), "unapproved_inventory_root")
    require(not any(x.lower() in (".git", ".env", "attachments", "__pycache__", "node_modules") or x.lower().startswith(".venv") for x in parts), "private_or_runtime_directory")
    path = (Path(root) / name).resolve()
    require(path.is_relative_to(Path(root).resolve()) and path.is_file(), "inventory_path_missing_or_outside_root")
    return path


def scan_credentials(path):
    """Heuristic scanning supplements the explicit content-review declaration."""
    tail = b""
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            require(SECRET.search(tail+block) is None, "credential_pattern_in_inventory")
            tail = block[-256:]
    if path.suffix.lower() == ".docx":
        with ZipFile(path) as doc:
            for entry in doc.infolist():
                require(entry.file_size < 50_000_000, "oversized_docx_member")
                if entry.filename.endswith((".xml", ".rels")):
                    require(SECRET.search(doc.read(entry)) is None, "credential_pattern_in_docx")


def validate_files(root, inventory):
    require(inventory.get("schema") == SCHEMA, "inventory_schema")
    entries = inventory.get("files")
    require(isinstance(entries,list) and entries, "empty_inventory")
    names = set(); indexed = {}
    for entry in entries:
        require(isinstance(entry,dict) and set(entry)=={"path","sha256"}, "inventory_entry_schema")
        name = entry["path"]; path = safe_path(root,name)
        require(name.casefold() not in names, "duplicate_inventory_path")
        names.add(name.casefold())
        require(isinstance(entry["sha256"],str) and re.fullmatch(r"[a-f0-9]{64}",entry["sha256"]), "invalid_inventory_hash")
        require(sha(path)==entry["sha256"], "inventory_file_changed")
        scan_credentials(path); indexed[name] = entry["sha256"]
    file_set_hash=hashlib.sha256(canonical(sorted(entries,key=lambda x:x["path"])).encode()).hexdigest()
    review=inventory.get("content_review",{})
    require(review.get("reviewed") is True and review.get("file_set_sha256")==file_set_hash
            and isinstance(review.get("reviewer"),str) and bool(review["reviewer"].strip())
            and isinstance(review.get("scope"),str) and bool(review["scope"].strip()), "content_review_missing_or_stale")
    return indexed,file_set_hash


def verify_report_result_bindings(build,indexed,gates):
    require(set(gates)=={"primary_summary","primary_audits","regression_summary","split_manifest","natural_ensemble_summary"},"report_final_result_gate_paths")
    for relative in gates.values():
        require(relative in indexed and build["evidence_inputs"].get(relative)==indexed[relative],"report_not_built_against_final_results")


def verify_page_inventory(render,visual):
    pages=render["pages"];expected=list(range(1,render["total_pages"]+1))
    require([p.get("page") for p in pages]==expected,"report_render_page_sequence")
    paths=[p.get("path") for p in pages]
    require(all(isinstance(p,str) for p in paths) and len({p.casefold() for p in paths})==len(paths),"report_duplicate_page_path")
    require(visual.get("inspected_pages")==expected and visual.get("unresolved_visual_issues")==[],"report_visual_gate")
    require(set(visual.get("page_hashes",{}))=={str(p) for p in expected},"report_visual_hash_page_keys")


def validate_report(root, indexed, gates):
    folder=Path(root)/"report/v6-cycle"
    layout=load(folder/"layout.json");build=load(folder/"build-manifest.json")
    render=load(folder/"render-manifest.json");visual=load(folder/"visual-review.json")
    stem=layout["output_stem"]
    require(re.fullmatch(r"[A-Za-z0-9._-]+",stem) is not None,"invalid_report_stem")
    needed={"research-draft.md","author-metadata.json","layout.json","build-manifest.json","render-manifest.json","visual-review.json",stem+".docx",stem+".pdf",
        "build_report.py","render_report.ps1","render_pdf_pages.py","verify_report.py","artifact.md","README.md","references.bib"}
    require({"report/v6-cycle/"+name for name in needed} <= set(indexed), "report_artifacts_not_in_inventory")
    require(layout.get("release_status")=="ready_for_author_review" and build.get("draft_mode") is False,"report_still_draft")
    text=(folder/"research-draft.md").read_text(encoding="utf-8")
    require("PENDING" not in text,"report_has_unresolved_placeholders")
    for key,name in (("markdown_sha256","research-draft.md"),("layout_sha256","layout.json"),("author_metadata_sha256","author-metadata.json"),("builder_sha256","build_report.py")):
        require(build[key]==sha(folder/name),"report_build_input_changed")
    require(build["reference_sha256"]==sha(Path(root)/"report/template-reference.docx"),"official_template_changed")
    docx_hash=sha(folder/(stem+".docx"));pdf_hash=sha(folder/(stem+".pdf"))
    require(build["output_sha256"]==render["docx_sha256"]==visual["docx_sha256"]==docx_hash,"report_docx_binding")
    require(render["pdf_sha256"]==visual["pdf_sha256"]==pdf_hash,"report_pdf_binding")
    require(6<=render["main_pages_including_title"]<=8 and 150<=build["abstract_word_count"]<=250,"report_length_gate")
    verify_page_inventory(render,visual)
    for page in render["pages"]:
        # Resolve original absolute render paths locally; archive keeps their
        # complete relative directory, and manifests remain original evidence.
        path=Path(page["path"]).resolve()
        require(path.is_relative_to(Path(root).resolve()),"report_page_outside_root")
        relative=path.relative_to(Path(root).resolve()).as_posix()
        require(indexed.get(relative)==page["sha256"] and visual["page_hashes"].get(str(page["page"]))==page["sha256"],"report_page_not_reviewed_or_inventoried")
    for relative,expected in build["evidence_inputs"].items():
        require(indexed.get(relative)==expected,"report_evidence_missing_or_changed")
    verify_report_result_bindings(build,indexed,gates)
    author=load(folder/"author-metadata.json")
    require(author["author_count"]==1 and len(author["authors"])==1,"author_count_mismatch")
    require(author["authors"][0]["full_name"]=="Christian Lysenstøen" and author["authors"][0]["affiliation"]=="Inland Norway University of Applied Sciences","author_identity_mismatch")
    return {"main_pages":render["main_pages_including_title"],"total_pages":render["total_pages"],
            "human_review_complete":author.get("human_manuscript_review_completed") is True,
            "pdf_sha256":pdf_hash,"docx_sha256":docx_hash}


def verify_score_replay(root, primary, regression, audit_path):
    """Recompute frozen scores in memory; never invoke exclusive writer CLIs."""
    def rows(name):return [json.loads(line) for line in (Path(root)/name).read_text(encoding="utf-8").splitlines() if line.strip()]
    evaluate=importlib.import_module("retrace.frontier_v6d_eval").evaluate
    result=evaluate(load(Path(root)/"data/frontier-v6c-staged.json"),load(Path(root)/"data/frontier-v6d-dossiers.json"),
        load(Path(root)/"data/frontier-v6f-sessions.json"),rows("results/frontier-v6f/study-views/primary-responses.jsonl"),bootstrap_repeats=10000)
    require(all(primary.get(key)==value for key,value in result["summary"].items()),"primary_score_replay_mismatch")
    require(rows(audit_path)==result["audits"],"primary_audit_replay_mismatch")
    evaluate_regression=importlib.import_module("scripts.score_frontier_v6f_regression").evaluate
    reproduced=evaluate_regression(load(Path(root)/"data/frontier-v6f-regression.json"),load(Path(root)/"data/frontier-v6f-regression-sessions.json"),
        rows("results/frontier-v6f/study-views/regression-responses.jsonl"))
    require(all(regression.get(key)==value for key,value in reproduced.items()),"regression_score_replay_mismatch")
    return result["audits"]


def verify_natural(root,indexed,gates,primary_audits):
    root=Path(root)
    require(indexed.get(NATURAL_FREEZE)==NATURAL_FREEZE_SHA256 and sha(root/NATURAL_FREEZE)==NATURAL_FREEZE_SHA256,"natural_supplement_freeze_mismatch")
    freeze=load(root/NATURAL_FREEZE)
    for entry in freeze["files"]:
        require(indexed.get(entry["path"])==entry["sha256"] and sha(root/entry["path"])==entry["sha256"],"natural_supplement_dependency_changed")
    result=load(root/gates["natural_ensemble_summary"])
    expected_inputs={str((root/name).resolve()):{"sha256":indexed[name],"bytes":(root/name).stat().st_size}
        for name in ("data/frontier-v6c-staged.json","data/frontier-v6f-sessions.json",gates["primary_summary"],gates["primary_audits"])}
    require(result.get("inputs")==expected_inputs,"natural_supplement_input_binding_mismatch")
    require(result.get("implementation_sha256")==indexed["scripts/audit_natural_ensembles_v6.py"],"natural_supplement_implementation_binding")
    require(result.get("primary_status")=="complete_records" and result.get("primary_all_planned_final_outcomes") is True,"natural_supplement_primary_status")
    # run_declared_closed is deliberately not accepted as closure evidence.
    # The independent whole-run audit has already proved closure above.
    audit_ensembles=importlib.import_module("scripts.audit_natural_ensembles_v6").audit_ensembles
    actual=audit_ensembles(load(root/"data/frontier-v6c-staged.json"),load(root/"data/frontier-v6f-sessions.json"),primary_audits)
    require(all(result.get(key)==value for key,value in actual.items()),"natural_supplement_replay_mismatch")


def verify_views(root, manifest):
    """Independently bind exact study lines to their original combined journal."""
    root=Path(root);base=root/"results/frontier-v6f";slot_study={};counts={};source_hashes={}
    for study in ("primary","regression"):
        path=root/("data/frontier-v6f-"+("sessions" if study=="primary" else "regression-sessions")+".json")
        slots=load(path);counts[study]=len(slots);source_hashes[study+"_sessions"]=sha(path)
        for slot in slots:
            require(slot["slot_id"] not in slot_study,"cross_study_slot")
            slot_study[slot["slot_id"]]=study
    mapping=[];view_rows={};view_hashes={}
    for kind in ("requests","responses"):
        path=base/"combined"/(kind+".jsonl");source_hashes[kind]=sha(path);seen=set()
        streams={study:(base/"study-views"/(study+"-"+kind+".jsonl")).open("rb") for study in counts}
        counters={study:0 for study in counts};hashes={study:hashlib.sha256() for study in counts}
        try:
            with path.open("rb") as original:
                for index,line in enumerate(original,1):
                    require(line.endswith(b"\n") and bool(line.strip()),"truncated_or_empty_combined_line")
                    sid=json.loads(line)["slot_id"]
                    require(sid in slot_study and sid not in seen,"duplicate_or_unknown_combined_slot")
                    seen.add(sid);study=slot_study[sid]
                    require(streams[study].readline()==line,"study_view_line_changed")
                    counters[study]+=1;hashes[study].update(line)
                    mapping.append({"journal":kind,"source_line":index,"study":study,"view_line":counters[study],
                        "slot_id":sid,"line_sha256":hashlib.sha256(line).hexdigest()})
            require(all(stream.read()==b"" for stream in streams.values()),"study_view_has_extra_lines")
        finally:
            for stream in streams.values():stream.close()
        for study in counts:view_rows[(study,kind)]=counters[study];view_hashes[(study,kind)]=hashes[study].hexdigest()
    files=[{"path":study+"-"+kind+".jsonl","sha256":view_hashes[(study,kind)],"records":view_rows[(study,kind)],
            "study":study,"journal":kind} for study in ("primary","regression") for kind in ("requests","responses")]
    require(manifest.get("schema")=="retrace.frontier-v6f-lossless-study-views.v1" and manifest.get("planned")==counts
            and manifest.get("files")==files and manifest.get("line_mapping")==mapping,"study_view_manifest_mismatch")
    require({key:value.get("sha256") for key,value in manifest.get("sources",{}).items()}==source_hashes,"study_view_source_hash_mismatch")


def validate_release(root, inventory):
    root=Path(root).resolve()
    require(root==ROOT,"release_root_must_match_script_workspace")
    indexed,file_set_hash=validate_files(root,inventory)
    audit=importlib.import_module("scripts.audit_frontier_v6f_run")
    evidence=audit.audit_workspace(root,require_closed=True)
    require(evidence["integrity"]=="passed_captured_evidence" and evidence["final_closed"] is True,"run_integrity_gate")
    # A future censored release requires a separate explicit policy review;
    # this complete-study assembler never silently treats it as full evidence.
    require(evidence["all_scheduled_outcomes_recorded"] is True,"study_incomplete_no_complete_release")
    freeze=load(root/audit.FREEZE)
    needed={entry["path"] for entry in freeze["files"]}|{audit.FREEZE,"scripts/audit_frontier_v6f_run.py",
        "scripts/assemble_frontier_v6_release.py","README-V6-FRONTIER.md","REPRODUCE-V6-FRONTIER.md",
        "start-retrace-v6-frontier.ps1","results/frontier-v6f/budget/ledger.jsonl"}
    for name in ("canary","combined"):
        folder="results/frontier-v6f/"+name
        needed|={folder+"/"+name for name in ("run.json","requests.jsonl","responses.jsonl","summary.json")}
        for line in (root/folder/"responses.jsonl").read_text(encoding="utf-8").splitlines():
            meta=json.loads(line).get("stream_evidence")
            if meta is not None:needed.add(folder+"/streams/"+Path(meta["raw_stream_path"]).name)
    needed|={"results/frontier-v6f/study-views/"+prefix+"-"+kind+".jsonl" for prefix in ("primary","regression") for kind in ("requests","responses")}
    gates=inventory.get("gates",{})
    require(set(gates)=={"primary_summary","primary_audits","regression_summary","split_manifest","natural_ensemble_summary"},"release_gate_paths")
    needed|=set(gates.values())
    needed.add(NATURAL_FREEZE)
    require(needed<=set(indexed),"reproduction_dependencies_missing_from_inventory")
    primary=load(safe_path(root,gates["primary_summary"]));regression=load(safe_path(root,gates["regression_summary"]))
    verify_views(root,load(safe_path(root,gates["split_manifest"])))
    require(primary.get("schema")=="retrace.frontier-v6d-evaluation.v1" and primary.get("status")=="complete_records"
            and primary.get("all_planned_final_outcomes") is True and primary.get("planned_slots")==4560
            and primary.get("base_cases")==48 and primary.get("long_base_cases")==24 and primary.get("holm_family_size")==10,"primary_summary_not_final_design")
    require(regression.get("schema")=="retrace.frontier-v6d-development-regression-score.v1" and regression.get("planned")==80
            and regression.get("received")==80,"regression_summary_incomplete")
    report=validate_report(root,indexed,gates)
    primary_audits=verify_score_replay(root,primary,regression,gates["primary_audits"])
    verify_natural(root,indexed,gates,primary_audits)
    return {"schema":"retrace.frontier-v6-release-validation.v1","status":"passed","file_count":len(indexed),
        "file_set_sha256":file_set_hash,"total_input_bytes":sum((root/name).stat().st_size for name in indexed),
        "source_run_audit":evidence,"report":report,"score_replay":"primary_summary_and_audits_regression_and_natural_supplement_matched_in_memory_10000_bootstrap_replicates",
        "submission_authorized":False,"credential_scan_scope":"Heuristic byte patterns and DOCX XML, supplemented by the inventory-bound content review declaration; not a universal private-data detector."}


def assemble(root, inventory, output, validation):
    root=Path(root).resolve();output=Path(output).resolve()
    require(output.is_relative_to(root/"deliverables") and output.suffix.lower()==".zip" and not output.exists(),"output_must_be_new_deliverable_zip")
    output.parent.mkdir(parents=True,exist_ok=True)
    partial=output.with_name("."+output.name+".partial-"+uuid.uuid4().hex)
    landing=("# RETRACE frontier-study artifact\n\nStart with [the frontier guide](artifact/README-V6-FRONTIER.md). "
             "The exact workspace layout is preserved under `artifact/`, including its historical README.\n\n"
             "Run offline commands from that directory: `cd artifact`. The report is ready for author review; "
             "this archive does not imply author approval, publication or competition submission.\n")
    with partial.open("xb") as handle:
        with ZipFile(handle,"w",compression=ZIP_DEFLATED,compresslevel=6) as archive:
            archive.writestr("README.md",landing)
            archive.writestr("RELEASE-MANIFEST.json",json.dumps({"inventory":inventory,"validation":validation},ensure_ascii=False,indent=2)+"\n")
            for entry in sorted(inventory["files"],key=lambda x:x["path"]):
                source=safe_path(root,entry["path"])
                require(sha(source)==entry["sha256"],"source_changed_during_assembly")
                archive.write(source,"artifact/"+entry["path"])
        handle.flush();os.fsync(handle.fileno())
    with ZipFile(partial) as archive:
        require(archive.testzip() is None,"archive_crc_failure")
        for entry in inventory["files"]:
            digest=hashlib.sha256()
            with archive.open("artifact/"+entry["path"]) as member:
                for block in iter(lambda:member.read(1024*1024),b""):digest.update(block)
            require(digest.hexdigest()==entry["sha256"],"packaged_bytes_changed")
    # Hard-link publication refuses an existing destination on both Windows
    # and POSIX. A failed publication leaves only the clearly named partial.
    os.link(partial,output)
    partial.unlink()
    return {"output":str(output),"sha256":sha(output),"bytes":output.stat().st_size,"status":"assembled_for_author_review","submitted":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory",required=True,type=Path)
    parser.add_argument("--assemble",action="store_true")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args();inventory=load(args.inventory)
    validation=validate_release(ROOT,inventory)
    require(not args.assemble or args.output is not None,"missing_new_output_path")
    print(json.dumps(assemble(ROOT,inventory,args.output,validation) if args.assemble else validation,indent=2,ensure_ascii=False))


if __name__=="__main__":
    try:main()
    except Exception as exc:
        # Never echo raw file contents, source text or candidate credentials.
        print(json.dumps({"status":"refused","error_type":type(exc).__name__,"code":str(exc) if type(exc) is ValueError else "inspect_local_gate"}))
        sys.exit(1)
