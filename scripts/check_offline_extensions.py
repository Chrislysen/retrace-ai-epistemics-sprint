"""Reproduce constructed offline demonstrations and verify preserved artifacts.

No provider calls, credentials or model outputs are used. An ephemeral loopback
HTTP server checks local backend contracts; --skip-backend omits that part.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import threading
from datetime import datetime, timezone
from functools import lru_cache
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retrace.graph_review import review_graphs
from retrace.intervention_audit import audit_interventions
from retrace.uncertainty import analyze_uncertainty, candidate_set_fingerprint


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def checked_file(relative, expected):
    observed = file_hash(ROOT / relative)
    return {"path": relative, "expected_sha256": expected, "observed_sha256": observed,
            "matches": observed == expected}


def verify_integrity():
    result = {}
    for name in ("data/prose-freeze.json", "data/extraction-v2-freeze.json"):
        manifest = read(name)
        checks = [checked_file(row["path"], row["sha256"]) for row in manifest["files"]]
        require(all(row["matches"] for row in checks), f"Frozen file changed: {name}")
        result[name] = {"manifest_sha256": file_hash(ROOT / name), "checked": len(checks),
                        "all_match": True, "files": checks}

    historical = read("results/archive/prose-v1-artifact-manifest.json")
    originals = {row["path"]: row["sha256"] for row in historical["files"]}
    archive = read("report/archive/prose-v1/archive-manifest.json")
    checks = []
    for row in archive["files"]:
        relative = "report/archive/prose-v1/" + row["file"]
        checked = checked_file(relative, row["sha256"])
        source = "report/" + row["file"]
        checked["historical_source_path"] = source
        checked["historical_source_sha256"] = originals.get(source)
        checked["archive_matches_historical_source"] = originals.get(source) == row["sha256"]
        checks.append(checked)
    require(all(row["matches"] and row["archive_matches_historical_source"] for row in checks),
            "Archived report differs from its archive or original source inventory")
    result["prose_v1_report_archive"] = {"checked": len(checks), "all_match": True, "files": checks}

    # Current UI/report files are allowed to evolve. Verify the original journals
    # and source/parser inputs against the preserved v1 inventory explicitly.
    prefixes = ("results/prose-heldout/", "results/prose-continuation/")
    explicit = {"data/prose-holdout.json", "data/prose-sessions.json", "data/prose-freeze.json",
                "data/prose-continuation-gemma.json", "retrace/core.py", "retrace/prose_eval.py",
                "retrace/prose_sessions.py", "retrace/experiment.py", "scripts/run_adaption.mjs"}
    checks = [checked_file(path, expected) for path, expected in sorted(originals.items())
              if path in explicit or path.startswith(prefixes)]
    require(explicit <= {row["path"] for row in checks}, "Original source inventory is incomplete")
    require(all(row["matches"] for row in checks), "Preserved v1 source or journal changed")
    result["prose_v1_protected_sources_and_journals"] = {"checked": len(checks), "all_match": True, "files": checks}
    budget = checked_file("results/archive/prose-v1-budget-audit.json", originals["results/budget-audit.json"])
    require(budget["matches"], "Archived v1 budget differs from original inventory")
    result["prose_v1_budget_archive"] = budget
    result["scope"] = "Local byte-integrity checks against saved manifests, not externally timestamped authenticity or source truth. Mutable current report and UI files are not compared to their old versions."
    return result


def full_identity_minimax(candidates, questions):
    """Separate recurrence: identify candidate ID, not its decision vector."""
    names = tuple(sorted(row["id"] for row in candidates))

    @lru_cache(maxsize=None)
    def solve(remaining, available):
        if len(remaining) <= 1:
            return 0
        best = None
        for number in available:
            question = questions[number]
            yes = tuple(name for name in remaining if question["answers"][name])
            no = tuple(name for name in remaining if not question["answers"][name])
            if not yes or not no:
                continue
            rest = tuple(index for index in available if index != number)
            outcomes = (solve(yes, rest), solve(no, rest))
            if None not in outcomes:
                cost = question.get("cost", 1) + max(outcomes)
                best = cost if best is None else min(best, cost)
        return best
    return solve(names, tuple(range(len(questions))))


def constructed_checks():
    demo = read("data/uncertainty-demo.json")
    require(demo["artificial_demonstration"] is True, "Demo must remain explicitly artificial")
    result = analyze_uncertainty(demo["candidates"], demo["questions"], demo["target_decisions"])
    identity_cost = full_identity_minimax(demo["candidates"], demo["questions"])
    require(result["clarification"]["worst_case_cost"] == 1 and identity_cost == 2,
            "Constructed clarification cost comparison changed")
    leaf_sizes = {answer: len(leaf["remaining_candidates"])
                  for answer, leaf in result["clarification"]["tree"]["branches"].items()}
    require(set(leaf_sizes.values()) == {2}, "Decision agreement should leave two possible graphs")

    reference = {"evidence": [{"id": name, "kind": "root", "active": True} for name in "ABCD"],
                 "claims": [{"id": "claim", "supports": [[name] for name in "ABCD"]}],
                 "decisions": [{"id": "decision", "requires": ["claim"]}]}
    predicted = copy.deepcopy(reference)
    predicted["claims"][0]["supports"] = [[name] for name in "ABC"]
    bounded = review_graphs(reference, predicted, max_interventions=2)
    exhaustive = audit_interventions({"four_routes": reference, "three_routes": predicted})
    witness = exhaustive["decisions"]["decision"]["minimum_withdrawal_witness"]
    require(bounded["current"]["agreement"] and bounded["witness"] is None, "Bounded illustration changed")
    require(bounded["total_interventions_tested"] == 10, "Expected all four singles and six pairs")
    require(witness == {"withdraw": ["A", "B", "C"], "outcomes": {"four_routes": True, "three_routes": False}},
            "Exhaustive three-withdrawal witness changed")

    baseline = candidate_set_fingerprint(demo["candidates"])
    reordered = copy.deepcopy(demo["candidates"])[::-1]
    for row in reordered:
        row["graph"]["evidence"].reverse()
        row["graph"]["evidence"][0]["label"] = "Changed display label"
    require(candidate_set_fingerprint(reordered) == baseline, "Presentation-only change altered semantic fingerprint")
    restored = copy.deepcopy(demo["candidates"])
    for row in restored:
        next(node for node in row["graph"]["evidence"] if node["id"] == "K7MP4R")["active"] = True
    restored_result = analyze_uncertainty(restored)
    require(restored_result["candidate_set_fingerprint"] != baseline, "Eligibility change failed to invalidate certificate")
    require(restored_result["decision_states"]["R9EP4N"]["state"] == "robust_supported", "Restoration illustration changed")
    expanded = copy.deepcopy(demo["candidates"])
    added = copy.deepcopy(expanded[-1]); added["id"] = "candidate-added"
    next(node for node in added["graph"]["evidence"] if node["id"] == "H6CD8X")["active"] = False
    expanded.append(added)
    expanded_result = analyze_uncertainty(expanded)
    require(expanded_result["candidate_set_fingerprint"] != baseline, "Membership change failed to invalidate certificate")
    require(expanded_result["decision_states"]["M7KB3T"]["state"] == "needs_review", "Expanded-set uncertainty not reflected")
    return demo, reference, predicted, {
        "decision_clarification": {"decision_vector_worst_case_cost": 1, "full_candidate_identity_worst_case_cost": identity_cost,
                                   "question": result["clarification"]["tree"]["question_id"], "leaf_candidate_counts": leaf_sizes,
                                   "decision_states": {key: value["state"] for key, value in result["decision_states"].items()}},
        "three_withdrawal_counterexample": {"bounded_checks": 10, "bounded_witness": None,
                                            "exhaustive_states_per_candidate": exhaustive["states_checked_per_candidate"],
                                            "minimum_witness": witness, "constructed_graphs": {"four_routes": reference, "three_routes": predicted}},
        "certificate_invalidation": {"baseline_fingerprint": baseline,
                                     "presentation_only_fingerprint_unchanged": True,
                                     "restored_fingerprint": restored_result["candidate_set_fingerprint"],
                                     "restored_listening_decision": restored_result["decision_states"]["R9EP4N"]["state"],
                                     "expanded_fingerprint": expanded_result["candidate_set_fingerprint"],
                                     "expanded_booklet_decision": expanded_result["decision_states"]["M7KB3T"]["state"]},
    }


def backend_checks(demo, reference, predicted):
    from retrace.server import Handler
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, body=None):
        req = Request(base + path, data=None if body is None else json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())
    try:
        status, served_demo = request("/api/uncertainty-demo")
        require(status == 200 and served_demo == demo, "Backend demo mismatch")
        status, current = request("/api/uncertainty", {key: demo[key] for key in ("candidates", "questions", "target_decisions")})
        require(status == 200 and current["clarification"]["worst_case_cost"] == 1, "Backend minimax mismatch")
        lineage = next(q for q in demo["questions"] if q["id"] == "record_lineage")
        remaining = [candidate for candidate in demo["candidates"] if lineage["answers"][candidate["id"]]]
        questions = [{**q, "answers": {c["id"]: q["answers"][c["id"]] for c in remaining}} for q in demo["questions"]]
        status, settled = request("/api/uncertainty", {"candidates": remaining, "questions": questions,
                                                       "target_decisions": demo["target_decisions"]})
        require(status == 200 and settled["clarification"]["worst_case_cost"] == 0
                and len(settled["candidate_ids"]) == 2, "Backend did not stop after decision agreement")
        invalid = copy.deepcopy(remaining); invalid[0]["graph"]["revoke"] = ["K7MP4R"]
        invalid_status, invalid_body = request("/api/uncertainty", {"candidates": invalid})
        require(invalid_status == 400 and "encode current active flags first" in invalid_body["error"],
                "Backend silently accepted unapplied withdrawal")
        status, intervention = request("/api/interventions", {"graphs": {"four_routes": reference, "three_routes": predicted}})
        require(status == 200 and len(intervention["decisions"]["decision"]["minimum_withdrawal_witness"]["withdraw"]) == 3,
                "Backend intervention witness mismatch")
        return {"status": "passed", "surface": "ephemeral loopback HTTP backend; no browser actions",
                "checks": ["demo matches saved source", "initial clarification cost one", "yes-answer leaves two graphs and cost zero",
                           "unapplied revoke rejected with HTTP 400", "three-withdrawal witness returned"]}
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-backend", action="store_true")
    args = parser.parse_args()
    integrity = verify_integrity()
    demo, reference, predicted, checks = constructed_checks()
    result = {"schema": "retrace.offline-extension-checks.v1", "checked_at": datetime.now(timezone.utc).isoformat(),
              "constructed_only": True, "provider_calls": 0, "checks": checks, "integrity": integrity,
              "backend": {"status": "not_run"} if args.skip_backend else backend_checks(demo, reference, predicted),
              "interpretation": ["Constructed software demonstrations, not empirical model gains or user-study outcomes.",
                                 "One versus two questions holds for this supplied candidate set, factual answers and unit costs.",
                                 "The three-withdrawal witness demonstrates the limit of a two-action search; exhaustive guarantees are only within declared graphs and withdrawal variables.",
                                 "Fingerprints bind graph semantics and membership, not source truth or completeness; changed external documents require explicit candidate revision."]}
    path = ROOT / "results/offline-extension-checks.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(path), "constructed_checks": "passed", "integrity": "passed", "backend": result["backend"]["status"]}))


if __name__ == "__main__":
    main()
