"""Offline independent reconstruction of the authored v6c source families.

This is a narrow audit reader for the explicit prose templates in this corpus,
not a production semantic extractor or evidence of general NLP completeness.
The reconstruction and scalar evaluator use only the Python standard library.
The frozen compiler is invoked separately for an additional agreement check.
Default execution prints JSON; --output creates one NEW result exclusively.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CORPUS = ROOT / "data/frontier-v6c-staged.json"
REVIEWED_SHA256 = "0dd2d6d05a27049db7f5050d2f5b768c9dc6b0492161df594942b1e82a6d0c8a"


def canonical(graph):
    result = {}
    for category, rows in graph.items():
        result[category] = sorted([
            {key: (sorted([sorted(route) for route in value]) if key == "supports"
                   else sorted(value) if isinstance(value, list) else value)
             for key, value in row.items() if key != "label"}
            for row in rows], key=lambda row: row["id"])
    return json.dumps(result, sort_keys=True, separators=(",", ":"))


def reconstruct_public(public):
    """Read explicit current definitions only; no evaluation argument exists."""
    known = [ident for values in public["registry"].values() for ident in values]
    pattern = re.compile(r"(?<![A-Za-z0-9_-])(?:" + "|".join(map(re.escape, known)) + r")(?![A-Za-z0-9_-])")

    def identifiers(text):
        return list(dict.fromkeys(pattern.findall(text)))

    options = {"evidence": {}, "claims": {}, "decisions": {}}
    scope_text = []
    for document in public["source_documents"]:
        if document["title"].endswith("scope"):
            scope_text.append(document["text"])
        elif document["title"].endswith("source record"):
            for paragraph in document["text"].split("\n\n"):
                found = identifiers(paragraph)
                assert found, "Unaligned source record"
                target, references = found[0], found[1:]
                assert paragraph.count("locally eligible at baseline") + paragraph.count("locally ineligible at baseline") == 1
                active = "locally ineligible" not in paragraph
                original = {"id": target, "kind": "root", "active": active, "parents": []}

                def copied(parents):
                    return {"id": target, "kind": "copy", "active": active, "parents": parents}

                if "Its production history is unresolved:" in paragraph:
                    assert len(references) == 1
                    alternatives = [copied(references), original]
                elif "It is certainly a copy, but its sole direct parent is unknown:" in paragraph:
                    assert len(references) == 2
                    alternatives = [copied([parent]) for parent in references]
                elif references:
                    assert any(word in paragraph for word in ("copy", "derivative", "derived record", "reproduces material", "transcription assembled"))
                    alternatives = [copied(references)]
                else:
                    assert any(phrase in paragraph for phrase in ("original", "own observation", "direct observation of its own"))
                    alternatives = [original]
                assert target not in options["evidence"]
                options["evidence"][target] = alternatives
        elif document["title"].endswith("warrant ledger"):
            for paragraph in document["text"].split("\n\n"):
                found = identifiers(paragraph)
                assert found, "Unaligned warrant"
                target, references = found[0], found[1:]
                if paragraph.startswith("Decision "):
                    assert "complete prerequisite set" in paragraph and "Every named review is required" in paragraph
                    assert target not in options["decisions"]
                    options["decisions"][target] = [{"id": target, "requires": references}]
                    continue
                if "Its complete support rule has exactly two unresolved readings." in paragraph:
                    if "A fixed nomination selected either" in paragraph:
                        assert len(references) == 2
                        routes = [[[ref]] for ref in references]
                    elif "One reading requires" in paragraph:
                        assert len(references) == 2
                        routes = [[references], [[ref] for ref in references]]
                    elif "The qualifier either applies only to the second route" in paragraph:
                        first, second, qualifier = references
                        routes = [[[first], [second, qualifier]], [[first, qualifier], [second, qualifier]]]
                    elif "The fixed sufficient routes are each of" in paragraph:
                        first, second, extra = references
                        routes = [[[first], [second]], [[first], [second], [extra]]]
                    else:
                        raise AssertionError("Unknown source ambiguity formulation")
                else:
                    assert "no other support route is admitted" in paragraph or "These alternatives are exhaustive" in paragraph
                    routes = [[]]
                    for index, group in enumerate(paragraph.split("; alternatively,")):
                        members = identifiers(group)
                        routes[0].append(members[1:] if index == 0 else members)
                assert target not in options["claims"]
                options["claims"][target] = [{"id": target, "supports": route} for route in routes]
    for category in options:
        assert set(options[category]) == set(public["registry"][category]), "Current source inventory differs from registry"
    axes = [(category, ident, alternatives) for category, nodes in options.items() for ident, alternatives in nodes.items()]
    ambiguous = sum(len(alternatives) > 1 for _, _, alternatives in axes)
    if ambiguous > 1:
        assert any("every combination of their two readings is admitted, with no hidden coupling" in text for text in scope_text)
    graphs = []
    for selections in itertools.product(*(alternatives for _, _, alternatives in axes)):
        graph = {"evidence": [], "claims": [], "decisions": []}
        for (category, _, _), node in zip(axes, selections):
            graph[category].append(node)
        graphs.append(graph)
    return graphs


def scalar(graph, excluded):
    """Independent synchronous monotone fixed point; no engine import."""
    truth = {node["id"]: False for rows in graph.values() for node in rows}
    for _ in range(len(truth) + 1):
        following = {
            node["id"]: node["active"] and node["id"] not in excluded and all(truth[parent] for parent in node["parents"])
            for node in graph["evidence"]}
        following.update({node["id"]: any(all(truth[ref] for ref in route) for route in node["supports"]) for node in graph["claims"]})
        following.update({node["id"]: all(truth[ref] for ref in node["requires"]) for node in graph["decisions"]})
        if following == truth:
            return truth
        truth = following
    raise AssertionError("Fixed point did not settle")


def audit(corpus_path=CORPUS):
    payload = corpus_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert digest == REVIEWED_SHA256, "This review is bound to the exact reviewed source corpus"
    corpus = json.loads(payload)
    # Independent reconstruction happens before any hidden evaluation is passed
    # to comparison code. Public-only signature prevents hidden-field access.
    reconstructed = {case["id"]: reconstruct_public(case["public"]) for case in corpus["cases"]}
    from retrace.source_ir_v6c import compile_source_ir, audit_source_ir
    rows, vectors, decision_outcomes, phases = [], 0, 0, 0
    for case in corpus["cases"]:
        family = case["evaluation"]["source_family"]
        public_family = Counter(canonical(graph) for graph in reconstructed[case["id"]])
        authored_family = Counter(canonical(candidate["graph"]) for candidate in family)
        assert public_family == authored_family, (case["id"], "public_reconstruction")
        compiled = compile_source_ir(case["evaluation"]["reference_ir"], case["public"]["source_documents"], case["public"]["registry"])
        assert Counter(canonical(candidate["graph"]) for candidate in compiled["candidates"]) == authored_family
        contract = audit_source_ir(case["evaluation"]["reference_ir"], case["public"]["source_documents"], family, case["public"]["registry"])
        assert contract["status"] == "represented_declared_contract"
        events = case["events"]
        documents = {document["id"]: document["text"] for document in case["public"]["source_documents"]}
        groups = {group["id"]: set(group["evidence_ids"]) for group in events["document_groups"]}
        for document_id, identifiers in groups.items():
            assert all(any(ident in paragraph.split(".")[0] for paragraph in documents[document_id].split("\n\n")) for ident in identifiers)
        for category in ("document", "passage"):
            field = "revoked_" + category + "s"
            initial = set(events["states"]["initial"][field])
            withdrawn = initial | set(events["withdrawal"]["add_" + category + "_vetoes"])
            restored = withdrawn - set(events["restoration"]["clear_" + category + "_vetoes"])
            assert withdrawn == set(events["states"]["withdrawn"][field])
            assert restored == set(events["states"]["restored"][field])
        for phase in case["phases"].values():
            assert phase["state"] == events["states"][phase["state_name"]]
            phases += 1
        for name, state in events["states"].items():
            excluded = set(state["revoked_passages"]).union(*(groups[ident] for ident in state["revoked_documents"]))
            expected = case["evaluation"]["state_gold"][name]
            assert excluded == set(expected["excluded_evidence_ids"])
            by_decision = {}
            for candidate in family:
                actual = scalar(candidate["graph"], excluded)
                assert actual == expected["candidate_states"][candidate["id"]]["all_nodes"]
                vectors += 1
                for node in candidate["graph"]["decisions"]:
                    assert actual[node["id"]] == expected["candidate_states"][candidate["id"]]["decisions"][node["id"]]
                    by_decision.setdefault(node["id"], []).append(actual[node["id"]])
                    decision_outcomes += 1
            consensus = {ident: "supported" if all(values) else "unsupported" if not any(values) else "disputed" for ident, values in by_decision.items()}
            assert consensus == expected["decision_consensus"]
        rows.append({"id": case["id"], "public_reconstructed_branches": len(reconstructed[case["id"]]),
                     "authored_branches": len(family), "compiled_branches": compiled["candidate_count"],
                     "public_multiset_matches": True, "compiled_multiset_matches": True,
                     "contract_membership": contract["status"], "all_three_states_match": True})
    return {
        "schema": "retrace.frontier-v6c-source-audit.v1", "status": "passed",
        "corpus_sha256": digest, "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "compiler_sha256": hashlib.sha256((ROOT / "retrace/source_ir_v6c.py").read_bytes()).hexdigest(),
        "cases": len(rows), "branches": sum(row["authored_branches"] for row in rows),
        "candidate_state_vectors": vectors, "individual_decision_outcomes": decision_outcomes,
        "phase_mappings": phases, "rows": rows,
        "method": "AI-assisted manual semantic reading plus independently written public-only controlled-template reconstruction and stdlib scalar fixed point; frozen compiler agreement checked separately.",
        "scope": ["No human annotation or semantic entailment certification.",
                  "Source-template audit is not a general prose parser or a production extraction method.",
                  "Explicit source exhaustiveness and Cartesian-independence declarations are authored premises.",
                  "No model outputs, API calls, credentials, mutations of old artifacts, or automatic graph replacement."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Exclusively create a new audit result; never overwrite")
    args = parser.parse_args()
    result = audit()
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
