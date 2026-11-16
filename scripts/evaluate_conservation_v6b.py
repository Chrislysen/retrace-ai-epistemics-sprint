"""Fresh eight-case holdout and separate development replay for frozen v6b.

Imports scoring helpers, not the revised detector, until the CLI verifies the
prospective freeze. All detector calls receive public fields only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_conservation_v6 import (
    RELATIONS, _aggregate, _overlap, _span_valid, evaluate_case, semantic_profile, transformed_case,
)
from scripts.evaluate_conservation_v6_compatible import adapt_result, evaluate_compatible

PUBLIC_SHA256 = "61376a1448594b545d76c6b391041924ebce825205b860f1ec7ce90ffc9f9c10"
ORIGINAL_HOLDOUT_PATH = "data/conservation-v6b-holdout.json"
HOLDOUT_PATH = "data/conservation-v6b-holdout-reviewed.json"
AMENDMENT_PATH = "data/conservation-v6b-annotation-amendment.json"
GATE_PATH = "data/conservation-v6b-quality-gate.json"
PRESERVATION_PATH = "data/v6-baseline-preservation.json"


def _coverage_of_targets(items, targets):
    covered = set()
    for item in items:
        covered.update(item.get("target_ids", []))
    return bool(targets) and set(targets) <= covered


def source_alignment(annotation, result, documents):
    """Conservative relation typing; never equate alternative routes with necessity."""
    cited = [item for item in result["obligations"]
             if _span_valid(item, documents) and _overlap(item, annotation)]
    targets, references = set(annotation["target_ids"]), set(annotation["referenced_ids"])
    aligned = [item for item in cited if set(item.get("target_ids", [])) & targets
               and set(item.get("referenced_ids", [])) == references]
    kind = annotation["kind"]
    required_types = RELATIONS.get(kind, set())
    if kind == "evidence_prerequisite":
        required_types = {("mandatory", "mandatory_conjunction"), ("lineage_direct", "direct_parent_conjunction")}
    elif kind == "sufficient_conjunction":
        required_types = {("sufficient", "sufficient_conjunction")}
    direct = [item for item in aligned if (item.get("kind"), item.get("representation_type")) == ("lineage_direct", "direct_parent_conjunction")]
    mandatory = [item for item in aligned if (item.get("kind"), item.get("representation_type")) == ("mandatory", "mandatory_conjunction")]
    ancestor = [item for item in aligned if (item.get("kind"), item.get("representation_type")) == ("lineage_ancestor", "ancestor_paths")]
    exact = [item for item in aligned if (item.get("kind"), item.get("representation_type")) in required_types]
    # Explicit direct-copy declarations imply ancestral dependence. A correctly
    # identified weaker dependency is reported separately from direct recovery.
    implied = direct + mandatory + ancestor if kind == "copy_source" else exact
    relevant_gaps = [item for item in implied if item.get("status") == "gap"]
    warning_items = [item for key in ("gaps", "unresolved_cues") for item in result[key]
                     if _span_valid(item, documents) and _overlap(item, annotation)]
    return {
        "annotation": copy.deepcopy(annotation),
        "aligned_declared_relation": _coverage_of_targets(exact, targets) if required_types else None,
        "aligned_declared_relation_gap": _coverage_of_targets([item for item in exact if item.get("status") == "gap"], targets) if required_types else None,
        "aligned_source_implied_dependency_gap": _coverage_of_targets(relevant_gaps, targets) if required_types else None,
        "aligned_direct_parent_relation": _coverage_of_targets(direct, targets) if kind in ("copy_source", "evidence_prerequisite") else None,
        "aligned_mandatory_dependency_group": _coverage_of_targets(mandatory, targets) if kind in ("copy_source", "evidence_prerequisite") else None,
        "aligned_ancestor_relation": _coverage_of_targets(ancestor, targets) if kind == "copy_source" else None,
        "overlapping_gap_or_unresolved": bool(warning_items),
        "matched_obligation_ids": [item.get("id") for item in exact],
        "implied_dependency_gap_ids": [item.get("id") for item in relevant_gaps],
        "scope": "Direct-parent, mandatory-input and ancestral recognition are distinct. Sufficient alternatives do not imply each route member is mandatory.",
    }


def _enrich(row, case):
    if row["status"] != "completed":
        row["source_alignment"] = []
        return
    documents = {doc["id"]: doc["text"] for doc in case["public"]["prose"]}
    row["source_alignment"] = [source_alignment(annotation, row["result"], documents)
                               for annotation in case["evaluation"]["source_obligations"]]


def _fresh_metrics(rows):
    positive = [row for row in rows if row["semantic_omission_scoring_only"]]
    controls = [row for row in rows if not row["semantic_omission_scoring_only"]]
    def omission_annotations(row):
        return [item for item in row["source_alignment"]
                if item["annotation"]["desired_disposition"].startswith("gap")
                or item["annotation"]["desired_disposition"] == "review_unresolved"]
    return {
        "positive_cases_with_annotation_aligned_structural_gap": sum(any(
            item["aligned_source_implied_dependency_gap"] is True for item in omission_annotations(row)) for row in positive),
        "positive_cases_with_annotation_overlapping_gap_or_unresolved": sum(any(
            item["overlapping_gap_or_unresolved"] for item in omission_annotations(row)) for row in positive),
        "controls_with_structural_gap": sum(bool(row.get("has_structural_gap")) for row in controls),
        "controls_with_any_source_review_block": sum(bool(row.get("has_structural_gap") or row.get("has_unresolved_review")) for row in controls),
        "declared_relation_alignments": sum(item["aligned_declared_relation"] is True for row in rows for item in row["source_alignment"]),
        "direct_parent_alignments": sum(item["aligned_direct_parent_relation"] is True for row in rows for item in row["source_alignment"]),
        "mandatory_dependency_group_alignments": sum(item["aligned_mandatory_dependency_group"] is True for row in rows for item in row["source_alignment"]),
        "ancestor_alignments": sum(item["aligned_ancestor_relation"] is True for row in rows for item in row["source_alignment"]),
        "scope": "The structural-gap gate includes correctly aligned source-implied dependencies; it does not claim those are recovered direct-copy edges. All warning counts remain visible.",
    }


def evaluate_holdout(corpus, auditor):
    cases = corpus["cases"]
    if len(cases) != 8 or len({case["id"] for case in cases}) != 8:
        raise ValueError("Exactly eight distinct fresh holdout cases are required")
    rows, raw_audits, pairs = [], [], []
    for case in cases:
        current = []
        for variant, packet in (("base", case), ("renamed_reordered", transformed_case(case))):
            def wrapped(**kwargs):
                try:
                    raw = auditor(**kwargs)
                except Exception as exc:
                    raw_audits.append({"case_id": case["id"], "variant": variant, "raw_result": None,
                                       "error": f"{type(exc).__name__}: {exc}"})
                    raise
                raw_audits.append({"case_id": case["id"], "variant": variant, "raw_result": copy.deepcopy(raw), "error": None})
                return adapt_result(raw)
            row = evaluate_case(packet, wrapped, variant)
            _enrich(row, packet)
            rows.append(row)
            current.append(row)
        inverse = {value: key for key, value in case["evaluation"]["metamorphic"]["id_map"].items()}
        complete = all(row["status"] == "completed" for row in current)
        pairs.append({"case_id": case["id"], "both_completed": complete,
                      "semantic_profiles_invariant": semantic_profile(current[0]["result"]) == semantic_profile(current[1]["result"], inverse) if complete else None})
    base = [row for row in rows if row["variant"] == "base"]
    derived = [row for row in rows if row["variant"] != "base"]
    return {"schema": "retrace.conservation-v6b-fresh-holdout.v1", "rows": rows, "raw_audits": raw_audits,
            "base": _aggregate(base), "derived": _aggregate(derived),
            "source_alignment_base": _fresh_metrics(base), "source_alignment_derived": _fresh_metrics(derived),
            "metamorphic_pairs": pairs,
            "metamorphic": {"scheduled_pairs": 8, "both_completed": sum(pair["both_completed"] for pair in pairs),
                            "semantic_profiles_invariant": sum(pair["semantic_profiles_invariant"] is True for pair in pairs)}}


def assess_gate(fresh, declared, protected_unchanged):
    requirements = declared["requirements"]
    metrics = fresh["source_alignment_base"]
    checks = {
        "all_cases_complete": all(row["status"] == "completed" for row in fresh["rows"]),
        "all_source_citations_valid": all(row.get("every_returned_citation_valid") is True for row in fresh["rows"]),
        "positive_cases_with_annotation_aligned_structural_gap_at_least": metrics["positive_cases_with_annotation_aligned_structural_gap"] >= requirements["positive_cases_with_annotation_aligned_structural_gap_at_least"],
        "positive_cases_with_annotation_overlapping_gap_or_unresolved_at_least": metrics["positive_cases_with_annotation_overlapping_gap_or_unresolved"] >= requirements["positive_cases_with_annotation_overlapping_gap_or_unresolved_at_least"],
        "controls_with_structural_gap_at_most": metrics["controls_with_structural_gap"] <= requirements["controls_with_structural_gap_at_most"],
        "controls_with_any_source_review_block_at_most": metrics["controls_with_any_source_review_block"] <= requirements["controls_with_any_source_review_block_at_most"],
        "metamorphic_profiles_all_invariant": fresh["metamorphic"]["semantic_profiles_invariant"] == 8,
        "protected_v5_files_unchanged": protected_unchanged,
    }
    if set(checks) != set(requirements):
        raise ValueError("Unrecognized quality-gate requirements")
    return {"passed": all(checks.values()), "checks": checks, "declared_gate": copy.deepcopy(declared),
            "metrics_from_fresh_base_only": copy.deepcopy(metrics),
            "scope": "A pass only permits considering a separately authorized live study; this offline script dispatches no model calls."}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--output", default="results/v6b/conservation-v6b-primary.json")
    args = parser.parse_args()
    destination = ROOT / args.output
    if destination.exists():
        raise FileExistsError("Refusing to overwrite a previous diagnostic")
    frozen = json.loads((ROOT / args.freeze).read_text(encoding="utf-8"))
    required = {HOLDOUT_PATH, ORIGINAL_HOLDOUT_PATH, AMENDMENT_PATH, GATE_PATH, PRESERVATION_PATH, "retrace/conservation_v6b.py",
                "scripts/evaluate_conservation_v6b.py", "tests/test_conservation_v6b_holdout.py",
                "research/conservation-v6b-holdout-protocol.md", "data/conservation-v6-cases.json",
                "scripts/evaluate_conservation_v6.py", "scripts/evaluate_conservation_v6_compatible.py"}
    if not required <= {item["path"] for item in frozen["files"]}:
        raise ValueError("Freeze omits required fresh or development dependencies")
    for item in frozen["files"]:
        if _digest(ROOT / item["path"]) != item["sha256"]:
            raise ValueError("Frozen input changed: " + item["path"])
    preservation = json.loads((ROOT / PRESERVATION_PATH).read_text(encoding="utf-8"))
    for path, expected in preservation["protected"].items():
        if _digest(ROOT / path) != expected:
            raise ValueError("Protected v5 artifact changed: " + path)
    fresh_data = json.loads((ROOT / HOLDOUT_PATH).read_text(encoding="utf-8"))
    original = json.loads((ROOT / ORIGINAL_HOLDOUT_PATH).read_text(encoding="utf-8"))
    amendment = json.loads((ROOT / AMENDMENT_PATH).read_text(encoding="utf-8"))
    if (_digest(ROOT / ORIGINAL_HOLDOUT_PATH) != amendment["original_sha256"]
            or _digest(ROOT / HOLDOUT_PATH) != amendment["reviewed_sha256"]):
        raise ValueError("Annotation amendment hashes do not match the protected corpus files")
    reconstructed = copy.deepcopy(original)
    for change in amendment["changes"]:
        case = next(row for row in reconstructed["cases"] if row["id"] == change["case_id"])
        annotation = case["evaluation"]["source_obligations"][change["annotation_index"]]
        if change["field"] != "kind" or annotation["kind"] != change["before"]:
            raise ValueError("Unexpected annotation amendment")
        annotation["kind"] = change["after"]
    if reconstructed != fresh_data:
        raise ValueError("Reviewed corpus has changes beyond the declared annotation labels")
    public_hash = hashlib.sha256(json.dumps([case["public"] for case in fresh_data["cases"]], ensure_ascii=False,
                                           sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if public_hash != PUBLIC_SHA256:
        raise ValueError("Prospectively locked public holdout changed")
    started = datetime.now(timezone.utc)
    declared = json.loads((ROOT / GATE_PATH).read_text(encoding="utf-8"))
    for record in (frozen, declared, amendment):
        if started <= datetime.fromisoformat(record["created_at"].replace("Z", "+00:00")):
            raise ValueError("Evaluation must follow the input freeze and declared gate")
    from retrace.conservation_v6b import audit_conservation
    fresh = evaluate_holdout(fresh_data, audit_conservation)
    gate = assess_gate(fresh, declared, True)
    development = evaluate_compatible(json.loads((ROOT / "data/conservation-v6-cases.json").read_text(encoding="utf-8")), audit_conservation)
    result = {"schema": "retrace.conservation-v6b-evaluation.v1", "generated_at": started.isoformat(),
              "fresh_holdout": fresh, "quality_gate": gate, "development_replay": development,
              "integrity": {"freeze_path": args.freeze, "freeze_sha256": _digest(ROOT / args.freeze),
                            "holdout_sha256": _digest(ROOT / HOLDOUT_PATH), "public_holdout_sha256": public_hash,
                            "protected_v5_files_checked": len(preservation["protected"]), "api_calls": 0},
              "scope": ["Fresh eight-case holdout and twelve-case development replay are separate; never pool their scores.",
                        "The revised recognizer was developed after the original twelve-case diagnostic; only the newly locked eight are prospective to this revision.",
                        "Both sets are targeted authored falsification cases, not natural-source population samples.",
                        "Raw audit output remains unchanged and separate from field aliases used by the frozen scorer."]}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(destination), "fresh_base": fresh["base"], "quality_gate": gate}, indent=2))


if __name__ == "__main__":
    main()
