"""Exclusive offline conservation evaluation; gold never enters the auditor call.

The detector is imported only by main, after the parent authorizes its first
frozen evaluation. Tests use independent stub auditors, not held-out outcomes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS_SHA256 = "a275c409efb4597b600ce88bca3fc07b925e4bfcb0a32e3b45e1241127d31396"
PUBLIC_FIELDS = {"prose", "candidates", "registry"}
RELATIONS = {
    "named_source_presence": {("source_node_mention", "node_presence")},
    "copy_source": {("lineage_direct", "direct_parent_conjunction")},
    "claim_conjunction": {("mandatory", "mandatory_conjunction"), ("sufficient", "sufficient_conjunction")},
    "decision_conjunction": {("mandatory", "mandatory_conjunction")},
    "claim_alternatives": {("alternative_routes", "alternative_sufficient_routes")},
}


def _replace(text, mapping):
    """Simultaneous exact opaque-token replacement, never substring repair."""
    return re.sub(r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?![A-Za-z0-9])",
                  lambda match: mapping.get(match.group(), match.group()), text)


def _rename(value, mapping):
    if isinstance(value, str):
        return _replace(value, mapping)
    if isinstance(value, list):
        return [_rename(item, mapping) for item in value]
    if isinstance(value, dict):
        return {mapping.get(key, key): _rename(item, mapping) for key, item in value.items()}
    return value


def transformed_case(case):
    """Derived paired packet; annotations transform only for after-call scoring."""
    mapping = case["evaluation"]["metamorphic"]["id_map"]
    transformed = _rename(copy.deepcopy(case), mapping)
    public = transformed["public"]
    public["prose"].reverse()
    public["candidates"].reverse()
    for candidate in public["candidates"]:
        graph = candidate["graph"]
        for category in ("evidence", "claims", "decisions"):
            graph[category].reverse()
        for row in graph["evidence"]:
            row["parents"].reverse()
        for row in graph["claims"]:
            row["supports"].reverse()
            for route in row["supports"]:
                route.reverse()
        for row in graph["decisions"]:
            row["requires"].reverse()
    for category in public["registry"]:
        public["registry"][category].reverse()
    # Offsets are recomputed even though the locked maps preserve ID length.
    documents = {doc["id"]: doc["text"] for doc in public["prose"]}
    for obligation in transformed["evaluation"]["source_obligations"]:
        source = obligation["source"]
        source["start"] = documents[source["document_id"]].index(source["quote"])
        source["end"] = source["start"] + len(source["quote"])
    return transformed


def _span_valid(item, documents):
    span = item.get("source_span", {})
    start, end = span.get("start"), span.get("end")
    return (isinstance(span, dict) and span.get("document_id") in documents
            and type(start) is int and type(end) is int
            and 0 <= start < end <= len(documents[span["document_id"]])
            and documents[span["document_id"]][start:end] == span.get("text"))


def _overlap(item, annotation):
    source, span = annotation["source"], item.get("source_span", {})
    return (span.get("document_id") == source["document_id"]
            and isinstance(span.get("start"), int) and isinstance(span.get("end"), int)
            and max(span["start"], source["start"]) < min(span["end"], source["end"]))


def _annotation_result(annotation, result, documents):
    obligations = result.get("obligations", [])
    overlap = [item for item in obligations if _span_valid(item, documents) and _overlap(item, annotation)]
    unresolved = [item for item in result.get("unresolved_cues", []) if _span_valid(item, documents) and _overlap(item, annotation)]
    suppressed = [item for item in result.get("suppressed_cues", []) if _span_valid(item, documents) and _overlap(item, annotation)]
    types = RELATIONS.get(annotation["kind"], set())
    targets, references = set(annotation["target_ids"]), set(annotation["referenced_ids"])
    matches = []
    for item in overlap:
        if (item.get("kind"), item.get("representation_type")) not in types:
            continue
        actual_targets, actual_references = set(item.get("target_ids", [])), set(item.get("referenced_ids", []))
        if annotation["kind"] == "named_source_presence":
            aligned = bool((actual_targets | actual_references) & targets)
        else:
            aligned = bool(actual_targets & targets) and actual_references == references
        if aligned:
            matches.append(item)
    def covered(status=None):
        found = set()
        for item in matches:
            if status is not None and item.get("status") != status:
                continue
            found |= set(item.get("target_ids", []))
            if annotation["kind"] == "named_source_presence":
                found |= set(item.get("referenced_ids", []))
        return bool(targets) and targets <= found
    eligible = annotation["exact_edge_recovery_expected"] or annotation["kind"] == "named_source_presence"
    return {
        "annotation": copy.deepcopy(annotation),
        "exact_relation_or_node_alignment_applicable": eligible,
        "recognized_annotated_relation_or_node": covered() if eligible else None,
        "aligned_gap_reported": covered("gap") if eligible else None,
        "aligned_representation_reported": covered("represented") if eligible else None,
        "matched_obligation_ids": [item.get("id") for item in matches],
        "overlapping_obligation_ids": [item.get("id") for item in overlap],
        "overlapping_unresolved_count": len(unresolved),
        "overlapping_suppressed_count": len(suppressed),
        "scope": "Kind, source-span overlap, targets and full referenced-ID group align; this is not proof of complete rule extraction.",
    }


def evaluate_case(case, auditor, variant="base"):
    public = case["public"]
    if set(public) != PUBLIC_FIELDS:
        raise ValueError("Only prose, candidates and registry are allowed in public input")
    record = {"case_id": case["id"], "variant": variant,
              "semantic_omission_scoring_only": case["evaluation"]["semantic_omission"],
              "limitation_category": case["evaluation"]["limitation_category"],
              "scheduled_annotations_scoring_only": len(case["evaluation"]["source_obligations"]),
              "scheduled_exact_relation_annotations_scoring_only": sum(
                  item["exact_edge_recovery_expected"] for item in case["evaluation"]["source_obligations"]),
              "scheduled_node_presence_annotations_scoring_only": sum(
                  item["kind"] == "named_source_presence" for item in case["evaluation"]["source_obligations"]),
              "status": "auditor_failure", "result": None, "error": None}
    try:
        # Crucially, evaluation and its annotations are not arguments.
        result = auditor(prose=copy.deepcopy(public["prose"]), candidates=copy.deepcopy(public["candidates"]),
                         registry=copy.deepcopy(public["registry"]), compilation=None)
        if not isinstance(result, dict) or result.get("status") not in {
                "gap_detected", "unresolved", "no_gap_detected_in_recognized_cues"}:
            raise ValueError("Unrecognized auditor result contract")
        for key in ("obligations", "gaps", "unresolved_cues", "suppressed_cues"):
            if not isinstance(result.get(key), list) or any(not isinstance(item, dict) for item in result[key]):
                raise ValueError("Auditor must return object arrays: " + key)
        record["result"] = copy.deepcopy(result)
        documents = {doc["id"]: doc["text"] for doc in public["prose"]}
        cited = [item for key in ("obligations", "gaps", "unresolved_cues", "suppressed_cues") for item in result[key]]
        record.update(status="completed", auditor_status=result["status"],
                      has_structural_gap=bool(result["gaps"]), has_unresolved_review=bool(result["unresolved_cues"]),
                      structural_gap_count=len(result["gaps"]), unresolved_cue_count=len(result["unresolved_cues"]),
                      suppressed_cue_count=len(result["suppressed_cues"]),
                      every_returned_citation_valid=all(_span_valid(item, documents) for item in cited),
                      annotation_results=[_annotation_result(annotation, result, documents)
                                          for annotation in case["evaluation"]["source_obligations"]])
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def semantic_profile(result, inverse=None):
    if result is None:
        return None
    inverse = inverse or {}
    profile = {"status": result["status"]}
    for key in ("obligations", "gaps", "unresolved_cues", "suppressed_cues"):
        rows = []
        for original in result[key]:
            item = _rename(original, inverse)
            row = {k: item.get(k) for k in ("kind", "representation_type", "status", "reason", "source_span")}
            for k in ("target_ids", "referenced_ids", "represented_candidate_ids"):
                row[k] = sorted(item.get(k, []))
            rows.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
        profile[key] = sorted(rows)
    return profile


def _aggregate(rows):
    complete = [row for row in rows if row["status"] == "completed"]
    positives = [row for row in rows if row["semantic_omission_scoring_only"]]
    controls = [row for row in rows if not row["semantic_omission_scoring_only"]]
    def counts(group):
        return {"scheduled": len(group), "completed": sum(row["status"] == "completed" for row in group),
                "cases_with_structural_gap": sum(bool(row.get("has_structural_gap")) for row in group),
                "cases_with_unresolved_review": sum(bool(row.get("has_unresolved_review")) for row in group),
                "cases_with_either": sum(bool(row.get("has_structural_gap") or row.get("has_unresolved_review")) for row in group)}
    annotations = [ann for row in complete for ann in row["annotation_results"]]
    aligned = [ann for ann in annotations if ann["exact_relation_or_node_alignment_applicable"]]
    return {"scheduled": len(rows), "completed": len(complete), "auditor_failures": len(rows) - len(complete),
            "auditor_status_counts": dict(Counter(row.get("auditor_status", "auditor_failure") for row in rows)),
            "semantic_omission_cases": counts(positives), "controls": counts(controls),
            "returned_source_citations_valid_cases": sum(row["every_returned_citation_valid"] for row in complete),
            "scheduled_annotations": sum(row["scheduled_annotations_scoring_only"] for row in rows),
            "scheduled_exact_relation_annotations": sum(row["scheduled_exact_relation_annotations_scoring_only"] for row in rows),
            "scheduled_node_presence_annotations": sum(row["scheduled_node_presence_annotations_scoring_only"] for row in rows),
            "annotated_obligations_in_completed_cases": len(annotations),
            "alignment_applicable_annotations_in_completed_cases": len(aligned),
            "aligned_relation_or_node_annotations": sum(bool(ann["recognized_annotated_relation_or_node"]) for ann in aligned),
            "aligned_structural_relation_annotations": sum(bool(ann["recognized_annotated_relation_or_node"])
                and ann["annotation"]["kind"] != "named_source_presence" for ann in aligned),
            "aligned_node_presence_annotations": sum(bool(ann["recognized_annotated_relation_or_node"])
                and ann["annotation"]["kind"] == "named_source_presence" for ann in aligned),
            "aligned_gap_annotations": sum(bool(ann["aligned_gap_reported"]) for ann in aligned),
            "aligned_represented_annotations": sum(bool(ann["aligned_representation_reported"]) for ann in aligned),
            "annotations_with_overlapping_unresolved_review": sum(ann["overlapping_unresolved_count"] > 0 for ann in annotations),
            "scope": "Warnings and unresolved review are counts, not automatically correct semantic detections; inspect case and annotation correspondence."}


def evaluate_corpus(corpus, auditor):
    cases = corpus["cases"]
    if len(cases) != 12 or len({case["id"] for case in cases}) != 12:
        raise ValueError("Exactly twelve distinct locked base cases are required")
    rows, paired = [], []
    for case in cases:
        transformed = transformed_case(case)
        base = evaluate_case(case, auditor, "base")
        variant = evaluate_case(transformed, auditor, "renamed_reordered")
        rows.extend((base, variant))
        inverse = {value: key for key, value in case["evaluation"]["metamorphic"]["id_map"].items()}
        available = base["status"] == variant["status"] == "completed"
        paired.append({"case_id": case["id"], "both_completed": available,
                       "semantic_profiles_invariant": semantic_profile(base["result"]) == semantic_profile(variant["result"], inverse) if available else None})
    return {"schema": "retrace.conservation-offline-evaluation.v1", "rows": rows, "metamorphic_pairs": paired,
            "base": _aggregate([row for row in rows if row["variant"] == "base"]),
            "derived": _aggregate([row for row in rows if row["variant"] != "base"]),
            "metamorphic": {"scheduled_pairs": 12, "both_completed": sum(pair["both_completed"] for pair in paired),
                            "semantic_profiles_invariant": sum(pair["semantic_profiles_invariant"] is True for pair in paired)},
            "scope": ["Twelve authored bases and twelve derived paired checks, not twenty-four independent examples.",
                      "Gold annotations never enter auditor calls. Source text and supplied candidate graphs are the complete audit inputs.",
                      "Unresolved review is distinct from an asserted structural gap and is never automatically a correct semantic interpretation.",
                      "A recognized relation alignment checks kind, span and ID grouping, not full semantic completeness or source truth."]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", required=True, help="Prospective manifest containing files[{path,sha256}] and created_at")
    parser.add_argument("--output", default="results/v6/conservation-offline-primary.json")
    args = parser.parse_args()
    destination = ROOT / args.output
    if destination.exists():
        raise FileExistsError("Refusing to overwrite a prior conservation result")
    frozen = json.loads((ROOT / args.freeze).read_text(encoding="utf-8"))
    required = {"data/conservation-v6-cases.json", "research/conservation-v6-offline-protocol.md",
                "scripts/evaluate_conservation_v6.py", "tests/test_conservation_v6_cases.py", "retrace/conservation_v6.py"}
    if not required <= {row["path"] for row in frozen["files"]}:
        raise ValueError("Freeze omits corpus, protocol, scorer, tests or auditor")
    for row in frozen["files"]:
        if hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Frozen input changed: " + row["path"])
    corpus_path = ROOT / "data/conservation-v6-cases.json"
    if hashlib.sha256(corpus_path.read_bytes()).hexdigest() != CORPUS_SHA256:
        raise ValueError("Locked authoring corpus changed")
    generated_at = datetime.now(timezone.utc)
    if generated_at <= datetime.fromisoformat(frozen["created_at"].replace("Z", "+00:00")):
        raise ValueError("Evaluation must follow the prospective freeze")
    sys.path.insert(0, str(ROOT))
    from retrace.conservation_v6 import audit_conservation
    scored = evaluate_corpus(json.loads(corpus_path.read_text(encoding="utf-8")), audit_conservation)
    scored.update(generated_at=generated_at.isoformat(), corpus_sha256=CORPUS_SHA256,
                  freeze_path=args.freeze, freeze_sha256=hashlib.sha256((ROOT / args.freeze).read_bytes()).hexdigest())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(scored, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(destination), "base": scored["base"], "metamorphic": scored["metamorphic"]}, indent=2))


if __name__ == "__main__":
    main()
