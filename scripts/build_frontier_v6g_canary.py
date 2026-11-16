"""Prospective contract-feasibility canary; no provider access or old edits.

The source is outside the48 cases, but deliberately targets a known v6f prompt
failure. It is not a fresh-population generalization test. Sessions are written
only through the explicit --write-reviewed-sessions CLI action after review.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.source_ir_v6d import model_source, source_segments
from scripts.build_frontier_v6c_canary import MODELS
from scripts.build_frontier_v6e_sessions import IR_PREAMBLE, REFUTER_INSTRUCTIONS
from retrace.source_ir_v6e_prompt import IR_V6E_INSTRUCTIONS

CASE_ID = "canary-v6g-lantern"


def source_cases():
    documents = [
        {"id": "inventory-note", "text": "This fictional paper-lantern exhibit uses evidence records, claims, and administrative decisions, rather than measurements about real people. Master-size ledger L61 and comparison stencil Q65 are independent original evidence records with no parents. Extract M62, extract N63, and fit certificate P64 are evidence records too. All five records are locally eligible in the current inventory. Local eligibility does not remove any stated copying requirement."},
        {"id": "transfer-note", "text": "Extract M62 is a transcription of master-size ledger L61. Its entire origin is that one ledger: M62 is a copy, with the ledger as its sole required parent. The extract contributes no independent original observation."},
        {"id": "duplicate-note", "text": "The second extract, N63, reproduces the same master ledger identified in the preceding transfer note. That ledger is its sole required parent. This second extract is also a copy and has no independent origin; it does not take the first extract as a parent."},
        {"id": "certificate-note", "text": "Fit certificate P64 is assembled from M62 and N63 together. It is a copy rather than an independent observation. Those two extracts are its complete direct parent list, and both are required, in addition to its own local eligibility."},
        {"id": "continuation-note", "text": "Neither of the two extracts alone suffices to keep that certificate usable. This sentence restates the joint-parent requirement in the preceding certificate note; it does not introduce another source or a separate support route."},
        {"id": "policy-note", "text": "Claim R66 has exactly two admitted, unresolved policy readings. Under the separate reading, P64 alone and Q65 alone are the two alternative complete sufficient routes. Under the joint reading, P64 together with Q65 is the single complete sufficient route. Each whole route is sufficient, and every member of a joint route is required. No other route or policy reading is admitted, and neither reading is preferred. Claim T68 accepts Q65 alone as its only route. Decision S67 requires R66 only; decision U69 requires T68 only. These statements and the origin notes are the complete current rules. Unusable or unsupported does not assert falsity."},
    ]
    registry = {"evidence": ["L61", "M62", "N63", "P64", "Q65"], "claims": ["R66", "T68"], "decisions": ["S67", "U69"]}
    return documents, registry


def expected_family():
    evidence = [{"id": eid, "kind": "root", "active": True, "parents": []} for eid in ("L61", "Q65")]
    evidence += [{"id": eid, "kind": "copy", "active": True, "parents": parents}
                 for eid, parents in (("M62", ["L61"]), ("N63", ["L61"]), ("P64", ["M62", "N63"]))]
    graph = {"evidence": evidence, "claims": [{"id": "R66", "supports": [["P64"], ["Q65"]]}, {"id": "T68", "supports": [["Q65"]]}],
             "decisions": [{"id": "S67", "requires": ["R66"]}, {"id": "U69", "requires": ["T68"]}]}
    joint = deepcopy(graph); joint["claims"][0]["supports"] = [["P64", "Q65"]]
    return [graph, joint]


def supplied_candidates():
    candidates = []
    for number, graph in enumerate(expected_family(), 1):
        next(row for row in graph["evidence"] if row["id"] == "P64")["parents"] = ["M62"]
        candidates.append({"id": f"supplied-{number}", "graph": graph})
    return candidates


def reference_ir():
    """Evaluation-only fixture; never projected into model input or instructions."""
    documents, registry = source_cases()
    spans = {s["document_id"]: s["span_id"] for s in source_segments(documents)}
    ir = {"schema": "retrace.source-ir.v6d", "entities": [], "bindings": [
        {"id": "ledger_reference", "entity": "L61", "mention": spans["duplicate-note"], "antecedent": spans["transfer-note"]},
        {"id": "certificate_reference", "entity": "P64", "mention": spans["continuation-note"], "antecedent": spans["certificate-note"]}],
        "choices": [{"id": "policy", "options": ["separate", "joint"], "citations": [spans["policy-note"]]}],
        "combination": {"mode": "cartesian", "assignments": [], "citations": []}, "propositions": []}
    for category, kind in (("evidence", "evidence"), ("claims", "claim"), ("decisions", "decision")):
        for ident in registry[category]:
            ir["entities"].append({"id": ident, "type": kind, "operational": True,
                                   "citations": [spans["inventory-note" if kind == "evidence" else "policy-note"]]})
    def add(kind, target, body, documents, when=None, bindings=None):
        ir["propositions"].append({"id": f"p{len(ir['propositions'])+1}", "kind": kind, "target": target, "body": body,
                                   "scope": "current", "polarity": "assert", "when": when or {},
                                   "citations": [spans[d] for d in documents], "bindings": bindings or []})
    for eid in registry["evidence"]: add("eligibility", eid, {"active": True}, ["inventory-note"])
    for eid in ("L61", "Q65"): add("origin", eid, {"kind": "root", "parents": []}, ["inventory-note"])
    add("origin", "M62", {"kind": "copy", "parents": ["L61"]}, ["transfer-note"])
    add("origin", "N63", {"kind": "copy", "parents": ["L61"]}, ["duplicate-note"], bindings=["ledger_reference"])
    add("origin", "P64", {"kind": "copy", "parents": ["M62", "N63"]}, ["certificate-note", "continuation-note"], bindings=["certificate_reference"])
    add("support", "R66", {"expr": {"any": [{"ref": "P64"}, {"ref": "Q65"}]}}, ["policy-note"], {"policy": "separate"})
    add("support", "R66", {"expr": {"all": [{"ref": "P64"}, {"ref": "Q65"}]}}, ["policy-note"], {"policy": "joint"})
    add("support", "T68", {"expr": {"ref": "Q65"}}, ["policy-note"])
    add("requirement", "S67", {"requires": ["R66"]}, ["policy-note"])
    add("requirement", "U69", {"requires": ["T68"]}, ["policy-note"])
    return ir


def build(instructions=None):
    if instructions is None:
        from retrace.source_ir_v6g_prompt import IR_V6G_INSTRUCTIONS
        instructions = IR_V6G_INSTRUCTIONS
    if not isinstance(instructions, str) or not instructions: raise ValueError("Reviewed v6g prompt is required")
    if not REFUTER_INSTRUCTIONS.endswith(IR_V6E_INSTRUCTIONS): raise ValueError("Existing generic refuter preamble changed")
    refuter = REFUTER_INSTRUCTIONS[:-len(IR_V6E_INSTRUCTIONS)] + instructions
    documents, registry = source_cases(); slots = []
    for index, model in enumerate(MODELS, 1):
        for suffix, condition, prompt in (("ir", "canary_source_ir", IR_PREAMBLE + instructions),
                                          ("refuter", "canary_adversarial_refuter", refuter)):
            payload = model_source(documents, registry)
            if suffix == "refuter": payload["supplied_candidates"] = supplied_candidates()
            slots.append({"slot_id": f"canary-v6g-{index}-{suffix}", "case_id": CASE_ID, "model": model,
                          "condition": condition, "phase": "probe", "instructions": prompt,
                          "input": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                          "max_output_tokens": 65536, "temperature": 1.0})
    return slots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-reviewed-sessions", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data/frontier-v6g-canary-sessions.json")
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(build(), stream, ensure_ascii=False, indent=2); stream.write("\n")


if __name__ == "__main__": main()
