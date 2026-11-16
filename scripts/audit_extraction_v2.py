"""Offline independent v2 audit; imports no RETRACE model scorer or engine.

The earlier independent journal/fixed-point helper is reused and hashed. This
audit was authored after the prospective freeze and after inference began; it
does not change admission rules, repair outputs, or make network requests.
"""
from __future__ import annotations

import ast
import copy
import difflib
import hashlib
import json
import math
import random
import re
import statistics
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import audit_prose_runs as independent

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("evidence", "claims", "decisions")
CONDITIONS = ("json_v2", "compact_v2")
FIELDS = {"evidence": {"id", "kind", "active", "parents"},
          "claims": {"id", "supports"}, "decisions": {"id", "requires"}}
require = independent.require
read = independent.read
digest = independent.digest


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identifier(value):
    require(isinstance(value, str) and value != "-"
            and re.fullmatch(r"[A-Za-z0-9_-]+", value, flags=re.ASCII), "invalid ASCII ID")
    return value


def strict_graph(graph, reference):
    """Separate explicit schema, typed registry and topology admission."""
    require(isinstance(graph, dict) and set(graph) == set(CATEGORIES), "wrong graph fields")
    require(all(isinstance(graph[k], list) for k in CATEGORIES), "non-array category")
    require(sum(map(len, graph.values())) <= 250, "node bound")
    compact_size = 3 + sum(map(len, graph.values()))

    def refs(values, nonempty=False):
        require(isinstance(values, list) and (not nonempty or values), "empty/non-array conjunction")
        require(len(values) <= 250, "conjunction bound")
        for value in values:
            identifier(value)
        require(len(values) == len(set(values)), "duplicate conjunction member")
        return sum(map(len, values)) + max(0, len(values) - 1)

    for category in CATEGORIES:
        for row in graph[category]:
            require(isinstance(row, dict) and set(row) == FIELDS[category], "missing/extra explicit fields")
            identifier(row["id"])
            if category == "evidence":
                require(row["kind"] in ("root", "copy") and type(row["active"]) is bool, "invalid kind/activity")
                size = refs(row["parents"], row["kind"] == "copy")
                require(row["kind"] != "root" or not row["parents"], "root parents")
                compact_size += 7 + len(row["id"]) + (size if row["parents"] else 1)
            elif category == "claims":
                require(isinstance(row["supports"], list), "non-array routes")
                size = sum(refs(route, True) for route in row["supports"])
                routes = [tuple(sorted(route)) for route in row["supports"]]
                require(len(routes) == len(set(routes)), "repeated route")
                compact_size += 3 + len(row["id"]) + (size + len(routes) - 1 if routes else 1)
            else:
                compact_size += 3 + len(row["id"]) + refs(row["requires"], True)
            require(compact_size <= 65536, "minimal representation exceeds character bound")
    # Independent helper uses topological elimination, not frozen core DFS.
    independent.graph_index(graph, reference)
    return graph


def parse_output(text, condition, reference):
    """Parse complete source; never extract a block or complete a truncation."""
    require(isinstance(text, str) and len(text) <= 65536, "source character bound")
    if condition == "json_v2":
        enclosed = re.fullmatch(r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", text, re.DOTALL)
        fenced = bool(enclosed and "```" not in enclosed.group(1))
        graph = independent.decode(enclosed.group(1) if fenced else text)
    else:
        require(condition == "compact_v2", "unknown format")
        require(all(32 <= ord(c) <= 126 or c in "\t\r\n" for c in text), "non-ASCII source")
        normalized = text.replace("\r\n", "\n")
        require("\r" not in normalized, "isolated carriage return")
        lines = [line.strip(" \t") for line in normalized.split("\n")]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        require(bool(lines), "empty compact source")
        fenced = bool(re.fullmatch(r"```(?:text|plaintext)?[ \t]*", lines[0]))
        if fenced:
            require(len(lines) >= 2 and lines[-1] == "```", "incomplete outer fence")
            lines = lines[1:-1]
        graph = {k: [] for k in CATEGORIES}
        ended = False
        for line in lines:
            if not line:
                continue
            require(not ended, "content after END")
            if line == "END":
                ended = True
                continue
            parts = re.split(r"[ \t]+", line)
            tag = parts[0]
            require(tag in ("E", "C", "D") and len(parts) == (5 if tag == "E" else 3), "record fields")
            node = identifier(parts[1])
            if tag == "E":
                require(parts[2] in ("R", "C") and parts[3] in ("0", "1"), "evidence fields")
                graph["evidence"].append({"id": node, "kind": "root" if parts[2] == "R" else "copy",
                                          "active": parts[3] == "1", "parents": [] if parts[4] == "-" else parts[4].split(",")})
            elif tag == "C":
                graph["claims"].append({"id": node, "supports": [] if parts[2] == "-" else
                                        [route.split("+") for route in parts[2].split("|")]})
            else:
                graph["decisions"].append({"id": node, "requires": parts[2].split("+")})
        require(ended, "missing END")
    return strict_graph(graph, reference), not fenced


def public_packet(entry):
    sections = ["Fictional packet: " + entry["title"]]
    for document in entry["documents"]:
        sections.append("DOCUMENT " + document["id"] + " — " + document["title"] + "\n" + document["text"])
    sections.append("DECISIONS\n" + "\n".join(row["id"] + ": " + row["text"] for row in entry["decision_questions"]))
    sections.extend(["AUTHORITATIVE CURRENT UPDATE\n" + entry["event_text"],
                     "Extract the complete direct support graph AFTER the update."])
    return "\n\n".join(sections)


def verify_protocol(freeze, corpus, manifest):
    files = []
    for row in freeze["files"]:
        require(file_hash(ROOT / row["path"]) == row["sha256"], "Frozen file changed: " + row["path"])
        files.append({**row, "verified": True})
    lock = read(ROOT / "data/extraction-v2-prompt-lock.json")
    require(independent.timestamp(lock["created_at"]) <= independent.timestamp(freeze["created_at"]), "Prompt lock after freeze")
    for row in lock["files"]:
        require(file_hash(ROOT / row["path"]) == row["sha256"], "Locked prompt/codec changed")
    without_hash = {k: v for k, v in manifest.items() if k != "sha256"}
    require(digest(without_hash, sorted_keys=True) == manifest["sha256"], "Manifest canonical hash")
    constants = {}
    # Read frozen literal strings without importing/executing prompt module.
    tree = ast.parse((ROOT / "retrace/extraction_v2_sessions.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("COMMON", "JSON_FORMAT", "COMPACT_FORMAT", "SEED"):
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    require(manifest["instructions"] == constants["COMMON"], "Common instructions differ")
    expected = [(entry["id"], condition) for entry in corpus for condition in CONDITIONS]
    random.Random(constants["SEED"]).shuffle(expected)
    sessions = manifest["sessions"]
    require([(s["case_id"], s["condition"]) for s in sessions] == expected, "Session identities/order differ")
    require(manifest["case_count"] == len(corpus) and manifest["request_count"] == len(sessions)
            and len(sessions) == freeze["requests_per_model"], "Plan count mismatch")
    by_id = {entry["id"]: entry for entry in corpus}
    require(len(by_id) == len(corpus), "Duplicate case identity")
    for session in sessions:
        entry, condition = by_id[session["case_id"]], session["condition"]
        suffix = constants["JSON_FORMAT" if condition == "json_v2" else "COMPACT_FORMAT"]
        require(session["instructions"] == constants["COMMON"] + "\n" + suffix, "Format instructions vary")
        require(session["steps"] == [{"phase": "final", "input": public_packet(entry)}], "Payload differs from public-only reconstruction")
        require(session["decision_ids"] == [q["id"] for q in entry["decision_questions"]], "Decision registry differs")
        require(session["response_kind"] == "graph" and session["family"] == entry["family"], "Session metadata differs")
        for private in (entry["id"], entry["family"], '"review_notes"', '"supports":', '"revoke":'):
            require(private not in session["steps"][0]["input"], "Private metadata in public input")
        require(not any(row["id"] in session["instructions"] for k in CATEGORIES for row in entry["case"][k]),
                "Case-specific ID in instructions")
    return files


def verify_test_amendment(freeze):
    amendments = freeze.get("amendments", [])
    require(len(amendments) == 1, "Unexpected amendment inventory")
    amendment = amendments[0]
    original_path = ROOT / amendment["original_freeze"]
    require(file_hash(original_path) == amendment["original_freeze_sha256"], "Original freeze archive hash")
    original = read(original_path)
    before = {item["path"]: item["sha256"] for item in original["files"]}
    after = {item["path"]: item["sha256"] for item in freeze["files"]}
    require(set(before) == set(after), "Amendment changed freeze file inventory")
    changed = [path for path in before if before[path] != after[path]]
    require(changed == ["tests/test_intervention_audit.py"] == [amendment["path"]], "Amendment changed runtime or extra files")
    require({k: v for k, v in freeze.items() if k not in ("files", "amendments")} ==
            {k: v for k, v in original.items() if k != "files"}, "Amendment changed execution settings")
    require(before[changed[0]] == amendment["original_sha256"] and after[changed[0]] == amendment["amended_sha256"],
            "Amendment's stated test hashes differ")
    archived = ROOT / "research/extraction-v2-frozen-intervention-test.txt"
    require(file_hash(archived) == before[changed[0]], "Frozen test archive mismatch")
    old_source, new_source = archived.read_text(encoding="utf-8"), (ROOT / changed[0]).read_text(encoding="utf-8")
    old_test = ('        result = audit_interventions({"with_metadata": a, "without_metadata": b})\n'
                '        self.assertTrue(result["all_decisions_equivalent_within_scope"])\n'
                '        self.assertEqual(result["decisions"]["d1"]["current_outcomes"], {"with_metadata": True, "without_metadata": True})')
    new_test = ('        with self.assertRaisesRegex(ValueError, "current active flags"):\n'
                '            audit_interventions({"with_metadata": a, "without_metadata": b})')
    require(old_source.count(old_test) == 1 and old_source.replace(old_test, new_test) == new_source,
            "Amended test differs beyond disclosed metadata expectation")
    return {"verified": True, "created_at": amendment["created_at"], "only_changed_file": changed[0],
            "original_freeze_sha256": file_hash(original_path), "original_test_sha256": file_hash(archived),
            "amended_test_sha256": after[changed[0]], "all_runtime_prompt_data_scoring_hashes_unchanged": True,
            "disclosure": "A final secondary-module guard change was not followed by a complete pre-dispatch test run. The stale test expected ignored revoke metadata; only its expectation was corrected after dispatch. This process error does not change the paid pipeline, whose admitted graphs prohibit that metadata.",
            "diff": list(difflib.unified_diff(old_source.splitlines(), new_source.splitlines(), fromfile="frozen test", tofile="amended test", lineterm="")),
            "amendment_document_sha256": file_hash(ROOT / "research/extraction-v2-test-amendment.md")}


def summarize(corpus, records):
    by_key = {(r["case_id"], r["condition"]): r for r in records}
    require(len(by_key) == len(records), "Duplicate model/format response")
    groups, outcomes, structures = {}, [], []
    for condition in CONDITIONS:
        group = dict(expected=len(corpus), received=0, valid=0, strict_valid=0,
                     graph_exact=0, decision_exact=0, decision_targets=0,
                     correct_decisions_all_scheduled=0, correct_decisions_valid=0,
                     decision_targets_valid=0, operational_failures=0,
                     input_tokens=0, output_tokens=0, reasoning_tokens=0, usage_records=0)
        latencies, failures = [], []
        for entry in corpus:
            reference = independent.final_graph(entry)
            truth = independent.fixed_point(reference)
            group["decision_targets"] += len(truth)
            outcome = {"case_id": entry["id"], "condition": condition, "valid": False, "strict_valid": False,
                       "graph_exact": False, "decision_exact": False, "correct_decisions": 0,
                       "decision_targets": len(truth), "predictions": None}
            row = by_key.get((entry["id"], condition))
            failure = "missing_response"
            if row is not None:
                group["received"] += 1
                latency = row.get("latency_ms")
                require(type(latency) in (int, float) and math.isfinite(latency) and latency >= 0, "Invalid latency")
                latencies.append(latency)
                usage = row.get("usage")
                if usage:
                    group["usage_records"] += 1
                    for field in ("input_tokens", "output_tokens"):
                        require(type(usage.get(field)) is int and usage[field] >= 0, "Invalid usage count")
                        group[field] += usage[field]
                    reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0
                    require(type(reasoning) is int and 0 <= reasoning <= usage["output_tokens"], "Invalid reasoning subset")
                    group["reasoning_tokens"] += reasoning
                if row.get("error") or row.get("response_status") not in (None, "completed"):
                    group["operational_failures"] += 1
                    failure = row.get("error") or "incomplete_provider_response"
                else:
                    try:
                        graph, strict = parse_output(row.get("output_text"), condition, reference)
                        prediction = independent.fixed_point(graph)
                        correct = sum(prediction[k] == v for k, v in truth.items())
                        outcome.update(valid=True, strict_valid=strict, predictions=prediction,
                                       graph_exact=independent.canonical(graph) == independent.canonical(reference),
                                       correct_decisions=correct, decision_exact=correct == len(truth))
                        normalized = {
                            "evidence": sorted((r["id"], r["kind"], r["active"], sorted(r["parents"])) for r in graph["evidence"]),
                            "claims": sorted((r["id"], sorted(sorted(route) for route in r["supports"])) for r in graph["claims"]),
                            "decisions": sorted((r["id"], sorted(r["requires"])) for r in graph["decisions"]),
                        }
                        structures.append({"case_id": entry["id"], "condition": condition,
                                           "canonical_sha256": digest(normalized, sorted_keys=True),
                                           "reference_exact": outcome["graph_exact"]})
                        for field in ("valid", "strict_valid", "graph_exact", "decision_exact"):
                            group[field] += int(outcome[field])
                        group["correct_decisions_all_scheduled"] += correct
                        group["correct_decisions_valid"] += correct
                        group["decision_targets_valid"] += len(truth)
                        failure = None if outcome["graph_exact"] else "admitted_nonexact_graph"
                    except (ValueError, TypeError, KeyError, RecursionError) as exc:
                        failure = str(exc)
            if failure:
                failures.append({"case_id": entry["id"], "reason": failure,
                                 "valid": outcome["valid"], "decision_exact": outcome["decision_exact"]})
            outcomes.append(outcome)
        group["median_latency_ms"] = statistics.median(latencies) if latencies else None
        groups[condition] = {"scorer_comparable": group, "latency_records": len(latencies),
                             "latency_sum_ms": sum(latencies), "observed_failures": failures}
    contrasts = {}
    indexed = {(r["case_id"], r["condition"]): r for r in outcomes}
    for metric in ("valid", "graph_exact", "decision_exact"):
        differences = [int(indexed[(c["id"], "compact_v2")][metric]) - int(indexed[(c["id"], "json_v2")][metric]) for c in corpus]
        rng = random.Random(2026111319)
        resampled = sorted(sum(rng.choices(differences, k=len(differences))) / len(differences) for _ in range(2000))
        contrasts[metric] = {"compact_minus_json": sum(differences) / len(differences),
                             "case_resampling_95_stability_interval": [resampled[49], resampled[1949]],
                             "compact_only": differences.count(1), "json_only": differences.count(-1)}
    pairing = {"both_received": [], "both_admitted": [], "json_only_received": [],
               "compact_only_received": [], "neither_received": []}
    for entry in corpus:
        cid = entry["id"]
        json_received, compact_received = (cid, "json_v2") in by_key, (cid, "compact_v2") in by_key
        bucket = "both_received" if json_received and compact_received else "json_only_received" if json_received else "compact_only_received" if compact_received else "neither_received"
        pairing[bucket].append(cid)
        if indexed[(cid, "json_v2")]["valid"] and indexed[(cid, "compact_v2")]["valid"]:
            pairing["both_admitted"].append(cid)
    paired_supplement = {"label": "posthoc descriptive availability supplement, not a replacement endpoint",
                         "case_ids": pairing, "counts": {k: len(v) for k, v in pairing.items()},
                         "received_pair_exact_graph_counts": {condition: sum(indexed[(cid, condition)]["graph_exact"] for cid in pairing["both_received"]) for condition in CONDITIONS},
                         "caveat": "A runner halt induces order-dependent missingness. All-scheduled contrasts mix format outcomes with unissued calls; admitted-only pairs are selected."}
    return {"groups": groups, "outcomes": outcomes, "contrasts": contrasts,
            "accepted_structure_fingerprints": structures, "paired_availability": paired_supplement}


def self_check():
    graph = {"evidence": [{"id": "a", "kind": "root", "active": False, "parents": []},
                           {"id": "b", "kind": "root", "active": True, "parents": []},
                           {"id": "x", "kind": "copy", "active": True, "parents": ["a"]}],
             "claims": [{"id": "c", "supports": [["x"], ["b"]]}, {"id": "l", "supports": [["x", "b"]]}],
             "decisions": [{"id": "d", "requires": ["c"]}, {"id": "e", "requires": ["l"]}]}
    compact = "E a R 0 -\nE b R 1 -\nE x C 1 a\nC c x|b\nC l x+b\nD d c\nD e l\nEND"
    for condition, output, fence in (("json_v2", json.dumps(graph), "json"), ("compact_v2", compact, "text")):
        for source, strict in ((output, True), ("```" + fence + "\n" + output + "\n```", False)):
            parsed, is_strict = parse_output(source, condition, graph)
            require(is_strict == strict and independent.canonical(parsed) == independent.canonical(graph), "Parser self-check")
            require(independent.fixed_point(parsed) == {"d": True, "e": False}, "Independent fixed-point self-check")
        for source in ("Explanation\n" + output, output + "\nextra"):
            try:
                parse_output(source, condition, graph)
            except ValueError:
                pass
            else:
                raise ValueError("Audit accepted explanatory/trailing prose")
    bad = copy.deepcopy(graph)
    del bad["evidence"][0]["active"]
    for source, condition in ((json.dumps(bad), "json_v2"), (compact.removesuffix("END"), "compact_v2"),
                              (compact.replace("C c x|b", "C c b|b"), "compact_v2"),
                              (compact.replace("C c x|b", "C c c"), "compact_v2")):
        try:
            parse_output(source, condition, graph)
        except ValueError:
            pass
        else:
            raise ValueError("Audit accepted a malformed graph")
    return "passed: explicit fields, complete source, fences, grouping, local-copy flags, duplicate routes, cycles"


def audit():
    checks = self_check()
    freeze = read(ROOT / "data/extraction-v2-freeze.json")
    manifest = read(ROOT / "data/extraction-v2-sessions.json")
    corpus = read(ROOT / "data/extraction-v2-holdout.json")
    corpus = corpus["cases"] if isinstance(corpus, dict) else corpus
    files = verify_protocol(freeze, corpus, manifest)
    amendment = verify_test_amendment(freeze)
    summary_path = ROOT / "results/extraction-v2-summary.json"
    summary_hash = file_hash(summary_path) if summary_path.exists() else None
    summary = read(summary_path) if summary_path.exists() else None
    plan = read(ROOT / "data/extraction-v2-plan.json")
    plan_by_model = {row["model"]: row for row in plan["plans"]}
    models, issues, reservations = {}, [], Decimal(0)
    for model in freeze["models"]:
        directory = ROOT / "results/extraction-v2" / model
        if not (directory / "run.json").exists():
            models[model] = {"status": "not_started"}
            continue
        detail, responses, requests, reserved, cost, found = independent.audit_segment(
            directory, model, manifest["sessions"], manifest["instructions"], freeze, freeze["created_at"])
        run = read(directory / "run.json")
        require(all(run.get(key) == value for key, value in plan_by_model[model].items()), "Run differs from frozen reservation plan")
        require(Decimal(str(run["budget_before"]["reserved_credits"])) == reservations, "Shared budget reservation sequence")
        require(Decimal(str(run["budget_after_reservation"]["reserved_credits"])) == reservations + reserved,
                "Shared budget after reservation")
        require(all(Decimal(str(row["reserved_credits"])) == Decimal(str(run["reserved_credits_per_request"])) for row in requests),
                "Journal request reservation differs")
        require(all(row.get("raw_response_redacted") is False for row in responses), "Provider source was credential-redacted")
        for failure in detail["operational_failures"]:
            row = next(r for r in responses if r["request_number"] == failure["request"])
            raw = independent.decode(row["raw_response"]) if row.get("raw_response") else None
            failure.update({"usage": row.get("usage"), "latency_ms": row.get("latency_ms"),
                            "saved_scoring_output_characters": len(row.get("output_text") or ""),
                            "raw_provider_visible_output_characters": len(independent.provider_text(raw)) if isinstance(raw, dict) else None,
                            "raw_response_sha256": hashlib.sha256(row["raw_response"].encode()).hexdigest() if row.get("raw_response") else None,
                            "failed_output_parsed_or_repaired": False})
        reservations += reserved
        issues.extend(found)
        calculated = summarize(corpus, responses)
        compared = False
        if summary is not None and detail["settled"]:
            reported = summary["models"][model]
            for condition in CONDITIONS:
                require(calculated["groups"][condition]["scorer_comparable"] == reported["groups"][condition],
                        model + " summary group differs: " + condition)
            require(calculated["contrasts"] == reported["contrasts"], model + " paired contrast differs")
            reported_rows = {(r["case_id"], r["condition"]): r for r in reported["outcomes"]}
            require(len(reported_rows) == len(reported["outcomes"]) == len(calculated["outcomes"]), "Summary outcome count")
            for row in calculated["outcomes"]:
                other = reported_rows[(row["case_id"], row["condition"])]
                require(all(other[key] == value for key, value in row.items()), model + " case admission/evaluation mismatch: " + row["case_id"])
            compared = True
        models[model] = {"integrity": detail, "independent_scoring": calculated, "root_summary_matches": compared}
    planned = sum(Decimal(str(row["max_reserved_credits"])) for row in plan["plans"])
    cumulative = Decimal(str(plan["prior_reserved"])) + planned
    require(cumulative == Decimal(str(plan["total_after"])) <= Decimal(str(plan["approved_total"])), "Cumulative plan budget")
    require(reservations <= planned, "Run reservations exceed plan")
    if summary_hash:
        require(file_hash(summary_path) == summary_hash, "Root summary changed during audit")
    done = all(row.get("integrity", {}).get("settled") and row.get("root_summary_matches") for row in models.values())
    candidate_diagnostics = []
    for entry in corpus:
        candidates = [{"model": model, **graph} for model, result in models.items()
                      for graph in result.get("independent_scoring", {}).get("accepted_structure_fingerprints", [])
                      if graph["case_id"] == entry["id"]]
        candidate_diagnostics.append({"case_id": entry["id"], "admitted_output_count": len(candidates),
                                      "distinct_structures": len({c["canonical_sha256"] for c in candidates}),
                                      "all_admitted_exact_reference": all(c["reference_exact"] for c in candidates) if candidates else None,
                                      "candidates": candidates})
    scheduled = len(manifest["sessions"]) * len(freeze["models"])
    issued = sum(r.get("integrity", {}).get("issued", 0) for r in models.values())
    accepted = sum(len(r.get("independent_scoring", {}).get("accepted_structure_fingerprints", [])) for r in models.values())
    return {"schema": "retrace.extraction-v2-independent-audit.v1", "status": "failed" if issues else "passed" if done else "incomplete",
            "created_at": datetime.now(timezone.utc).isoformat(), "issues": issues, "self_checks": checks,
            "freeze_sha256": file_hash(ROOT / "data/extraction-v2-freeze.json"), "frozen_files": files,
            "test_only_amendment": amendment,
            "audit_script_sha256": file_hash(Path(__file__)), "independent_helper_sha256": file_hash(ROOT / "scripts/audit_prose_runs.py"),
            "root_summary_sha256": summary_hash, "models": models,
            "execution_coverage": {"scheduled": scheduled, "issued": issued, "unissued": scheduled - issued,
                                   "admitted": accepted, "all_scheduled_attempted": issued == scheduled,
                                   "audit_pass_does_not_mean_experiment_completed": True},
            "candidate_structure_diagnostics": candidate_diagnostics,
            "paired_bootstrap": {"seed": 2026111319, "replicates": 2000, "unit": "constructed case", "interpretation": "descriptive resampling stability, not population confidence"},
            "budget": {"new_plan_reserved": str(planned), "new_run_reserved": str(reservations),
                       "prior_reserved": str(plan["prior_reserved"]), "cumulative_plan_bound": str(cumulative),
                       "approved_limit": str(plan["approved_total"]), "actual_billed_credits": None},
            "scope": ["Separate AI code audit, not independent human validation or natural-document evaluation.",
                      "No frozen core, codec, prompt module or scoring module is imported; frozen prompt string literals are read via AST only.",
                      "Journal integrity and synchronous fixed-point helper reuse the earlier independent audit, whose exact source hash is recorded.",
                      "This audit was authored after inference began. It verifies adherence and reproduces results; it does not prospectively define endpoints.",
                      "A passed audit includes correctly recorded halted runs and all-scheduled missing failures; it does not imply all planned calls were made.",
                      "The author reference is used for retrospective evaluation only, never to repair or complete an output.",
                      "Raw response text is checked against saved provider envelopes. Transport/account billing cannot be independently authenticated from local logs.",
                      "Received latency and usage include operational failures. Reasoning tokens are a subset of output tokens, never added again."]}


if __name__ == "__main__":
    result = audit()
    destination = ROOT / "results/extraction-v2-independent-audit.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "issues": result["issues"],
                      "models": {m: {"responses": row.get("integrity", {}).get("responses"),
                                      "summary_matches": row.get("root_summary_matches")} for m, row in result["models"].items()}}, indent=2))
