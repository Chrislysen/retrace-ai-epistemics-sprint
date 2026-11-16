"""Independent, post-hoc mechanics audit; imports no RETRACE implementation.

Does not admit, repair or rescore the six rejected responses. Their intended
semantics are AI-assisted manual reconstruction, with no human annotation,
tied to exact observed lines below.
Counterfactual enablement is a hypothetical input amendment, not revocation.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/ambiguity-v3-staged.json"
SUMMARY = ROOT / "results/ambiguity-v4-summary.json"
RESPONSES = ROOT / "results/ambiguity-v4/gemma-4-31b-it/responses.jsonl"
OUTPUT = ROOT / "results/ambiguity-v4-mechanics-audit-v2.json"

# Post-hoc semantic hypotheses, not a permissive parser or changed scores.
# Both the exact observed line and each interpreted replacement are recorded.
ANNOTATIONS = {
    "ambiguity-v3-01": (
        "C R01004 AMBIGUOUS_QUALIFIER(R01001, R01002, R01003)",
        ["C R01004 R01001|R01002+R01003", "C R01004 R01001+R01003|R01002+R01003"]),
    "ambiguity-v3-02": (
        "E R02002 ? 1 UNVERIFIED_INDEPENDENCE(R02002, R02001)",
        ["E R02002 C 1 R02001", "E R02002 R 1 -"]),
    "ambiguity-v3-03": (
        "E R03003 C 1 UNSPECIFIED_CHOICE(R03003, R03001, R03002)",
        ["E R03003 C 1 R03001", "E R03003 C 1 R03002"]),
    "ambiguity-v3-04": (
        "C R04005 UNSPECIFIED_CHOICE(R04003, R04004)",
        ["C R04005 R04003", "C R04005 R04004"]),
    "ambiguity-v3-05": (
        "C R05004 UNSPECIFIED_CHOICE(R05001, R05002)",
        ["C R05004 R05001", "C R05004 R05002"]),
    "ambiguity-v3-06": (
        "C R06005 OPTIONAL_ROUTE(R06001, R06002, R06003; R06004)",
        ["C R06005 R06001|R06002|R06003", "C R06005 R06001|R06002|R06003|R06004"]),
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(graph):
    """Exact declared structure modulo ordering, not Boolean minimization."""
    return (
        tuple(sorted((r["id"], r["kind"], r["active"], tuple(sorted(r["parents"])))
                     for r in graph["evidence"])),
        tuple(sorted((r["id"], tuple(sorted(tuple(sorted(c)) for c in r["supports"])))
                     for r in graph["claims"])),
        tuple(sorted((r["id"], tuple(sorted(r["requires"]))) for r in graph["decisions"])),
    )


def fixed_graph(text):
    """Small independent reader for fixed bare E/C/D lines in these outputs."""
    graph = {"evidence": [], "claims": [], "decisions": []}
    seen, ended = set(), False
    for line in text.splitlines():
        if not line.strip():
            continue
        assert not ended, "Unexpected content after END"
        if line == "END":
            ended = True
            continue
        p = line.split()
        assert len(p) in (3, 5) and p[1] not in seen, line
        seen.add(p[1])
        if p[0] == "E":
            assert len(p) == 5 and p[2] in ("R", "C") and p[3] in ("0", "1"), line
            parents = [] if p[4] == "-" else p[4].split(",")
            assert bool(parents) == (p[2] == "C"), line
            graph["evidence"].append({"id": p[1], "kind": "root" if p[2] == "R" else "copy",
                                      "active": p[3] == "1", "parents": parents})
        elif p[0] == "C":
            assert len(p) == 3, line
            routes = [] if p[2] == "-" else [c.split("+") for c in p[2].split("|")]
            graph["claims"].append({"id": p[1], "supports": routes})
        else:
            assert p[0] == "D" and len(p) == 3, line
            graph["decisions"].append({"id": p[1], "requires": p[2].split("+")})
    assert ended
    evaluate(graph)
    return graph


def evaluate(graph, final_flags=None):
    """Own scalar recursive Boolean evaluator; explicit cycle/reference checks."""
    nodes, kinds = {}, {}
    for category in ("evidence", "claims", "decisions"):
        for row in graph[category]:
            assert row["id"] not in nodes
            nodes[row["id"]], kinds[row["id"]] = row, category
    cache, visiting = {}, set()

    def value(identifier):
        if identifier in cache:
            return cache[identifier]
        assert identifier in nodes and identifier not in visiting, identifier
        visiting.add(identifier)
        row, kind = nodes[identifier], kinds[identifier]
        if kind == "evidence":
            flag = row["active"] if final_flags is None else final_flags[identifier]
            assert isinstance(flag, bool)
            parent_values = [value(p) for p in row["parents"]]
            result = flag and (row["kind"] == "root" or all(parent_values))
        elif kind == "claims":
            routes = [[value(p) for p in route] for route in row["supports"]]
            assert all(route for route in row["supports"])
            result = any(all(route) for route in routes)
        else:
            result = all([value(p) for p in row["requires"]])
        visiting.remove(identifier)
        cache[identifier] = bool(result)
        return cache[identifier]

    for identifier in nodes:
        value(identifier)
    return {r["id"]: cache[r["id"]] for r in graph["decisions"]}


def subsets(ids):
    for n in range(len(ids) + 1):
        yield from itertools.combinations(sorted(ids), n)


def contrast(predicted, reference, withdrawal_groups):
    initial = {r["id"]: r["active"] for r in reference["evidence"]}
    assert initial == {r["id"]: r["active"] for r in predicted["evidence"]}
    rows = []
    for selected in subsets(list(withdrawal_groups)):
        withdrawn = sorted({eid for group in selected for eid in withdrawal_groups[group]})
        flags = {eid: active and eid not in withdrawn for eid, active in initial.items()}
        actual, expected = evaluate(predicted, flags), evaluate(reference, flags)
        rows.append({"selected": list(selected), "withdraw": withdrawn,
                     "predicted": actual, "reference": expected,
                     "differing_decisions": [d for d in expected if actual[d] != expected[d]]})
    return {"states": len(rows), "differing_states": sum(bool(r["differing_decisions"]) for r in rows),
            "decision_cells": sum(len(r["reference"]) for r in rows),
            "differing_decision_cells": sum(len(r["differing_decisions"]) for r in rows),
            "truth_table": rows}


def exposure(predicted, reference):
    """Enumerate all final local flags, including explicit hypothetical enabling."""
    initial = {r["id"]: r["active"] for r in reference["evidence"]}
    assert initial == {r["id"]: r["active"] for r in predicted["evidence"]}
    assert len(initial) <= 16
    rows = []
    for toggled in subsets(list(initial)):
        flags = {eid: (not value if eid in toggled else value) for eid, value in initial.items()}
        actual, expected = evaluate(predicted, flags), evaluate(reference, flags)
        rows.append({"enable": sorted(e for e in toggled if not initial[e]),
                     "withdraw": sorted(e for e in toggled if initial[e]),
                     "predicted": actual, "reference": expected,
                     "differing_decisions": [d for d in expected if actual[d] != expected[d]]})
    minima = {}
    for did in evaluate(reference):
        failures = [r for r in rows if did in r["differing_decisions"]]
        count_pairs = {(len(r["enable"]), len(r["withdraw"])) for r in failures}
        frontier = sorted(p for p in count_pairs
                          if not any(q != p and q[0] <= p[0] and q[1] <= p[1] for q in count_pairs))
        minima[did] = [{"enable_count": p[0], "withdraw_count": p[1],
                        "witnesses": [r for r in failures
                                      if (len(r["enable"]), len(r["withdraw"])) == p]}
                       for p in frontier]
    return {"states": len(rows), "differing_states": sum(bool(r["differing_decisions"]) for r in rows),
            "differing_decision_cells": sum(len(r["differing_decisions"]) for r in rows),
            "pareto_minimum_exposure": minima, "truth_table": rows,
            "scope": "Hypothetical changes to local eligibility; enables are not permitted by ordinary withdrawal-only controls. No source amendment is asserted true."}


def main():
    corpus = {c["public"]["id"]: c for c in read_json(CORPUS)}
    summary = read_json(SUMMARY)
    raw = [json.loads(s) for s in RESPONSES.read_text(encoding="utf-8").splitlines()]
    assert len(raw) == 10 and len({r["case_id"] for r in raw}) == 10
    raw = {r["case_id"]: r for r in raw}
    results = []
    for scored in summary["outcomes"]:
        cid = scored["case_id"]
        row, source = raw[cid], corpus[cid]
        text = row["output_text"]
        assert text == scored["raw_row_audit"]["output_text"]
        assert row["response_status"] == "completed"
        allowed = source["hidden"]["allowed_interpretations"]
        expected = set(map(canonical, allowed))
        record = {"case_id": cid, "frozen_status": scored["status"], "raw_output_text": text,
                  "reference_family_count": len(expected)}
        if cid in ANNOTATIONS:
            observed, interpreted = ANNOTATIONS[cid]
            assert text.splitlines().count(observed) == 1
            assert scored["status"] == "syntax_or_branch_failure"
            graphs = [fixed_graph(text.replace(observed, line)) for line in interpreted]
            record.update({"review_kind": "AI-assisted manual semantic reconstruction; no human annotation; not admission or rescore",
                           "observed_inline_line": observed, "analyst_interpreted_alternatives": interpreted,
                           "intended_family_matches_exactly": set(map(canonical, graphs)) == expected,
                           "interpreted_graphs": graphs})
        else:
            graph = fixed_graph(text)
            compiled = scored["compilation"]["candidates"]
            assert len(compiled) == 1 and canonical(graph) == canonical(compiled[0]["graph"])
            assert len(allowed) == 1
            reference = allowed[0]
            exact = canonical(graph) in expected
            assert exact == scored["evaluation"]["family"]["exact_family_recovery"]
            all_records = {r["id"]: [r["id"]] for r in reference["evidence"]}
            roots = {r["id"]: [r["id"]] for r in reference["evidence"] if r["kind"] == "root"}
            documents = {d["id"]: d["evidence_ids"] for d in source["source_context"]["documents"]}
            record.update({"review_kind": "admitted fixed graph independent scalar audit",
                           "source_exact": exact,
                           "record_withdrawals": contrast(graph, reference, all_records),
                           "root_only_withdrawals": contrast(graph, reference, roots),
                           "document_only_withdrawals": contrast(graph, reference, documents) if documents else None,
                           "hypothetical_exposure": exposure(graph, reference)})
        results.append(record)
    artifact = {"schema": "retrace.ambiguity-v4-mechanics-audit.v2",
                "supersedes": "results/ambiguity-v4-mechanics-audit.json",
                "supersession_reason": "Correct reviewer attribution: AI-assisted manual semantic reconstruction; no human annotation. Calculations and frozen scores unchanged.",
                "method": "Independent Python scalar evaluator and exact finite enumeration; no production imports or model calls.",
                "post_hoc": True, "changes_primary_scores": False,
                "input_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (CORPUS, SUMMARY, RESPONSES)},
                "audit_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "all_ten_reviewed": len(results) == 10,
                "rejected_inline_intended_families_exact": sum(r.get("intended_family_matches_exactly", False) for r in results),
                "admitted_source_exact_count": sum(r.get("source_exact", False) for r in results),
                "results": results}
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "inline_intended_exact": artifact["rejected_inline_intended_families_exact"],
                      "admitted_source_exact": artifact["admitted_source_exact_count"],
                      "admitted": [{"case": r["case_id"],
                                    "withdrawal_mismatches": r["record_withdrawals"]["differing_decision_cells"],
                                    "root_only_mismatches": r["root_only_withdrawals"]["differing_decision_cells"],
                                    "pareto_exposure": r["hypothetical_exposure"]["pareto_minimum_exposure"]}
                                   for r in results if "source_exact" in r]}, indent=2))


if __name__ == "__main__":
    main()
