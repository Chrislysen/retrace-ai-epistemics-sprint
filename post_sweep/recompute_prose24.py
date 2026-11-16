#!/usr/bin/env python3
"""Recompute the 24-case prose experiment of Friday 13 November 2026 from its raw records.

Sprint addition, written with AI assistance on Sunday 15 November 2026.

Two computations over the same records:
  A. the project's frozen scorer, retrace.prose_eval.score_prose, called the way
     scripts/summarize_prose.py calls it;
  B. an independent evaluator and parser written here from research/prose-protocol.md,
     importing nothing from the project.
The script reports every record on which A and B differ, and writes its results to
post_sweep/out/prose24_recompute.json and paper_build/tables/prose24.md.
No network. Nothing outside post_sweep/ and paper_build/ is written.

    python post_sweep/recompute_prose24.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CELLS = [("formal_fresh", "final"), ("prose_fresh", "final"), ("prose_history", "initial"),
         ("prose_history", "withdrawn"), ("prose_no_commitment", "final"), ("prose_extract", "final")]
CELL_LABEL = {
    ("formal_fresh", "final"): "Formal graph, final state",
    ("prose_fresh", "final"): "Prose, final state",
    ("prose_history", "initial"): "Prose history, initial answer",
    ("prose_history", "withdrawn"): "Prose history, after withdrawal",
    ("prose_no_commitment", "final"): "Prose event, no prior answer",
    ("prose_extract", "final"): "Extraction + recomputation",
}
CATEGORIES = ("evidence", "claims", "decisions")
FENCE = re.compile(r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", re.DOTALL)


class Invalid(ValueError):
    """The output breaks the written contract."""


# ------------------------------------------------------------------ B: independent pieces
def load_json(text, allow_fence):
    if not isinstance(text, str):
        raise Invalid("output is not text")
    fenced = False
    if allow_fence:
        match = FENCE.fullmatch(text)
        if match and "```" not in match.group(1):
            text, fenced = match.group(1), True

    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Invalid("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=no_duplicates)
    except RecursionError as exc:
        raise Invalid("nesting too deep") from exc
    if not isinstance(value, dict):
        raise Invalid("not a JSON object")
    return value, fenced


def id_list(value, nonempty=False):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise Invalid("not a list of IDs")
    if (nonempty and not value) or len(set(value)) != len(value):
        raise Invalid("empty or repeated IDs")
    return value


def check_graph(graph):
    """Raise Invalid unless the graph satisfies the ledger contract of the protocol."""
    category = {}
    for name in CATEGORIES:
        if not isinstance(graph.get(name), list):
            raise Invalid(f"{name} is not a list")
        for row in graph[name]:
            if not isinstance(row, dict):
                raise Invalid("record is not an object")
            ident = row.get("id")
            if not isinstance(ident, str) or not ident or ident in category:
                raise Invalid("bad or repeated node ID")
            if not isinstance(row.get("label", ident), str):
                raise Invalid("label is not text")
            category[ident] = name
    needs = {}
    for name in CATEGORIES:
        for row in graph[name]:
            if name == "evidence":
                kind = row.get("kind", "root")
                if kind not in ("root", "copy") or type(row.get("active", True)) is not bool:
                    raise Invalid("bad evidence kind or active flag")
                refs = id_list(row.get("parents", []), nonempty=kind == "copy")
                if kind == "root" and refs:
                    raise Invalid("root with parents")
                allowed = {"evidence"}
            elif name == "claims":
                if not isinstance(row.get("supports"), list):
                    raise Invalid("supports is not a list")
                refs = [ref for clause in row["supports"] for ref in id_list(clause, nonempty=True)]
                allowed = {"evidence", "claims"}
            else:
                refs = id_list(row.get("requires"), nonempty=True)
                allowed = {"claims"}
            if any(ref not in category or category[ref] not in allowed for ref in refs):
                raise Invalid("missing or wrongly typed reference")
            needs[row["id"]] = refs
    state = {}

    def visit(ident):
        if state.get(ident) == "open":
            raise Invalid("dependency cycle")
        if ident not in state:
            state[ident] = "open"
            for ref in needs[ident]:
                visit(ref)
            state[ident] = "done"

    for ident in needs:
        visit(ident)
    return needs


def supported(graph, revoked=()):
    """Decision -> supported or not. Roots count if active and not withdrawn; a copy needs
    itself and every parent; a claim needs one whole clause; a decision needs every claim."""
    revoked = set(revoked)
    rows = {row["id"]: (name, row) for name in CATEGORIES for row in graph[name]}
    known = {}

    def ok(ident):
        if ident not in known:
            name, row = rows[ident]
            if name == "evidence":
                live = bool(row.get("active", True)) and ident not in revoked
                known[ident] = live and all(ok(p) for p in row.get("parents", []))
            elif name == "claims":
                known[ident] = any(all(ok(ref) for ref in clause) for clause in row["supports"])
            else:
                known[ident] = all(ok(ref) for ref in row["requires"])
        return known[ident]

    return {row["id"]: ok(row["id"]) for row in graph["decisions"]}


def reference(item):
    case = item["case"]
    needs = check_graph(case)
    initial, final = supported(case), supported(case, case["revoke"])
    reached = {}

    def touched(ident):
        if ident not in reached:
            reached[ident] = ident in case["revoke"] or any(touched(ref) for ref in needs[ident])
        return reached[ident]

    kept = {d for d in initial if initial[d] and final[d]}
    final_graph = {name: [dict(row) for row in case[name]] for name in CATEGORIES}
    for row in final_graph["evidence"]:
        if row["id"] in case["revoke"]:
            row["active"] = False
    return {"initial": initial, "final": final,
            "lost": {d for d in initial if initial[d] and not final[d]},
            "protected": {d for d in kept if touched(d)},
            "unaffected": {d for d in kept if not touched(d)},
            "never": {d for d in initial if not initial[d]},
            "final_graph": final_graph}


def canonical(graph):
    return (
        {r["id"]: (r.get("kind", "root"), r.get("active", True), tuple(sorted(r.get("parents", []))))
         for r in graph["evidence"]},
        {r["id"]: frozenset(tuple(sorted(clause)) for clause in r["supports"]) for r in graph["claims"]},
        {r["id"]: tuple(sorted(r["requires"])) for r in graph["decisions"]},
    )


def read_output(text, condition, ref, allow_fence):
    """Return (predictions, graph_exact or None). Raise Invalid on any contract breach."""
    value, _ = load_json(text, allow_fence)
    if condition != "prose_extract":
        if set(value) != {"decisions"} or not isinstance(value["decisions"], dict):
            raise Invalid("expected exactly the key decisions")
        answer = value["decisions"]
        if set(answer) != set(ref["final"]) or any(type(v) is not bool for v in answer.values()):
            raise Invalid("decision IDs or types do not match the task")
        return answer, None
    if set(value) != set(CATEGORIES):
        raise Invalid("graph must have exactly evidence, claims, decisions")
    allowed = {"evidence": {"id", "label", "kind", "parents", "active"},
               "claims": {"id", "label", "supports"}, "decisions": {"id", "label", "requires"}}
    for name in CATEGORIES:
        if not isinstance(value[name], list):
            raise Invalid(f"{name} is not a list")
        for row in value[name]:
            if not isinstance(row, dict) or set(row) - allowed[name]:
                raise Invalid("unexpected field")
        try:
            got = {row.get("id") for row in value[name]}
        except TypeError as exc:
            raise Invalid("unhashable ID") from exc
        if got != {row["id"] for row in ref["final_graph"][name]}:
            raise Invalid("node IDs do not match the task")
    check_graph(value)
    return supported(value), canonical(value) == canonical(ref["final_graph"])


def independent_rows(corpus, records):
    refs = {item["id"]: reference(item) for item in corpus}
    by_key = {}
    for record in records:
        key = (record.get("case_id"), record.get("condition"), record.get("phase"))
        if key in by_key:
            raise SystemExit(f"duplicate record {key}")
        by_key[key] = record
    rows = {}
    for item in corpus:
        ref = refs[item["id"]]
        for condition, phase in CELLS:
            key = (item["id"], condition, phase)
            truth = ref["initial"] if phase == "initial" else ref["final"]
            row = {"received": key in by_key, "operational_failure": False, "strict_valid": False,
                   "semantic_valid": False, "exact": False, "errors": len(truth), "targets": len(truth),
                   "predictions": None, "graph_exact": None}
            record = by_key.get(key)
            if record is not None:
                if record.get("error") or record.get("response_status", "completed") not in (None, "completed"):
                    row["operational_failure"] = True
                else:
                    try:
                        read_output(record.get("output_text"), condition, ref, allow_fence=False)
                        row["strict_valid"] = True
                    except Invalid:
                        pass
                    except ValueError:
                        pass
                    try:
                        answer, graph_exact = read_output(record.get("output_text"), condition, ref, allow_fence=True)
                    except ValueError:
                        answer = None
                    if answer is not None:
                        errors = sum(answer[d] != truth[d] for d in truth)
                        row.update(semantic_valid=True, exact=errors == 0, errors=errors,
                                   predictions=answer, graph_exact=graph_exact)
                        if phase != "initial":
                            row["missed"] = sum(answer[d] for d in ref["lost"])
                            row["protected_dropped"] = sum(not answer[d] for d in ref["protected"])
                            row["unaffected_dropped"] = sum(not answer[d] for d in ref["unaffected"])
                            row["never_accepted"] = sum(answer[d] for d in ref["never"])
            row["class_sizes"] = {k: len(ref[k]) for k in ("lost", "protected", "unaffected", "never")}
            rows[key] = row
    return rows


def tally(rows):
    cells = {}
    for condition, phase in CELLS:
        chosen = [row for key, row in rows.items() if key[1:] == (condition, phase)]
        valid = [row for row in chosen if row["semantic_valid"]]
        cell = {"expected": len(chosen), "received": sum(r["received"] for r in chosen),
                "operational_failures": sum(r["operational_failure"] for r in chosen),
                "strict_valid": sum(r["strict_valid"] for r in chosen), "semantic_valid": len(valid),
                "fully_correct_cases": sum(r["exact"] for r in chosen),
                "decision_errors_all_scheduled": sum(r["errors"] for r in chosen),
                "decision_targets_all_scheduled": sum(r["targets"] for r in chosen),
                "decision_errors_valid_only": sum(r["errors"] for r in valid),
                "decision_targets_valid_only": sum(r["targets"] for r in valid)}
        if phase != "initial":
            for name, size in (("missed", "lost"), ("protected_dropped", "protected"),
                               ("unaffected_dropped", "unaffected"), ("never_accepted", "never")):
                cell[name] = sum(r[name] for r in valid)
                cell[name + "_of"] = sum(r["class_sizes"][size] for r in valid)
        if condition == "prose_extract":
            cell["graph_exact"] = sum(bool(r["graph_exact"]) for r in valid)
            cell["accepted_and_wrong_decisions"] = sum(not r["exact"] for r in valid)
            cell["accepted_but_graph_not_exact"] = sum(not r["graph_exact"] for r in valid)
        cells[f"{condition}/{phase}"] = cell
    return cells


# ------------------------------------------------------------------ main
def main():
    freeze = json.loads((ROOT / "data/prose-freeze.json").read_text(encoding="utf-8"))
    changed = [f["path"] for f in freeze["files"]
               if hashlib.sha256((ROOT / f["path"]).read_bytes()).hexdigest() != f["sha256"]]
    corpus = json.loads((ROOT / "data/prose-holdout.json").read_text(encoding="utf-8"))
    from retrace.prose_eval import gold_for, score_prose  # the frozen scorer (computation A)

    gold_disagreements = 0
    for item in corpus:
        theirs, mine = gold_for(item), reference(item)
        gold_disagreements += theirs["initial"] != mine["initial"] or theirs["final"] != mine["final"]
        gold_disagreements += theirs["lost"] != mine["lost"] or theirs["protected"] != mine["protected"]

    result = {"freeze_files_changed": changed, "cases": len(corpus),
              "decisions_per_case": sorted({len(item["case"]["decisions"]) for item in corpus}),
              "families": sorted({item["family"] for item in corpus}),
              "domains": sorted({item["domain"] for item in corpus}),
              "reference_disagreements_engine_vs_independent": gold_disagreements, "models": {}}
    for model in freeze["models"]:
        folders = [ROOT / "results/prose-heldout" / model]
        if model == "gemma-4-31b-it":
            folders.append(ROOT / "results/prose-continuation" / model)
        records, segments = [], []
        for folder in folders:
            log = folder / "responses.jsonl"
            lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line] if log.exists() else []
            times = sorted(r["finished_at"] for r in lines if r.get("finished_at"))
            segments.append({"folder": folder.relative_to(ROOT).as_posix(), "records": len(lines),
                             "sha256": hashlib.sha256(log.read_bytes()).hexdigest() if log.exists() else None,
                             "first_finished_at": times[0] if times else None,
                             "last_finished_at": times[-1] if times else None})
            records.extend(lines)
        frozen = score_prose(corpus, records)
        mine = independent_rows(corpus, records)
        differences = []
        for row in frozen["outcomes"]:
            key = (row["case_id"], row["condition"], row["phase"])
            other = mine[key]
            if (row["semantic_valid"], row["exact"], row["predictions"]) != (other["semantic_valid"], other["exact"], other["predictions"]):
                differences.append("/".join(key))
        result["models"][model] = {
            "segments": segments, "records": len(records),
            "response_models_reported": sorted({str(r.get("response_model")) for r in records}),
            "frozen_scorer_cells": {name: {k: v for k, v in group.items() if isinstance(v, int)}
                                    for name, group in frozen["groups"].items()},
            "independent_cells": tally(mine),
            "records_where_frozen_and_independent_differ": differences,
            "contrasts_frozen_scorer": [{"name": c["name"], "mean_accuracy_delta_all_scheduled": c["mean_accuracy_delta_all_scheduled"],
                                         "bootstrap_interval_95": c["case_bootstrap_stability_interval_95"],
                                         "both_valid_cases": c["both_valid_cases"]} for c in frozen["contrasts"]],
        }

    out = ROOT / "post_sweep" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "prose24_recompute.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")

    models = list(result["models"])
    lines = ["# The 24-case prose experiment, recomputed from raw records", "",
             "Produced by `post_sweep/recompute_prose24.py`. Inputs: `data/prose-holdout.json`, "
             "`results/prose-heldout/*/responses.jsonl`, `results/prose-continuation/gemma-4-31b-it/responses.jsonl`. "
             "Numbers are from the independent computation; the frozen scorer's are in "
             "`post_sweep/out/prose24_recompute.json`.", "",
             "## Fully correct cases out of 24", "",
             "| Condition | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    for cell in CELLS:
        name = "/".join(cell)
        lines.append(f"| {CELL_LABEL[cell]} | " + " | ".join(
            str(result["models"][m]["independent_cells"][name]["fully_correct_cases"]) for m in models) + " |")
    lines += ["", "## Decision labels wrong, out of all scheduled labels (an unusable answer counts every label wrong)", "",
              "| Condition | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    for cell in CELLS:
        name = "/".join(cell)
        lines.append(f"| {CELL_LABEL[cell]} | " + " | ".join(
            "{decision_errors_all_scheduled} of {decision_targets_all_scheduled}".format(**result["models"][m]["independent_cells"][name])
            for m in models) + " |")
    lines += ["", "## Error classes among usable answers", "",
              "| Condition | Model | Usable answers | Required withdrawals missed | Protected alternatives dropped | Unaffected dropped | Never-supported accepted |",
              "|---|---|---|---|---|---|---|"]
    for cell in CELLS:
        if cell[1] == "initial":
            continue
        name = "/".join(cell)
        for m in models:
            c = result["models"][m]["independent_cells"][name]
            lines.append(f"| {CELL_LABEL[cell]} | {m} | {c['semantic_valid']} of {c['expected']} | "
                         f"{c['missed']} of {c['missed_of']} | {c['protected_dropped']} of {c['protected_dropped_of']} | "
                         f"{c['unaffected_dropped']} of {c['unaffected_dropped_of']} | {c['never_accepted']} of {c['never_accepted_of']} |")
    lines += ["", "## Extraction", "",
              "| Model | Accepted by the validator | Accepted and graph identical to the reference | Accepted with a wrong decision |", "|---|---|---|---|"]
    for m in models:
        c = result["models"][m]["independent_cells"]["prose_extract/final"]
        lines.append(f"| {m} | {c['semantic_valid']} of {c['expected']} | {c['graph_exact']} | {c['accepted_and_wrong_decisions']} |")
    lines += ["", "## Paired contrasts from the frozen scorer (mean difference in decision accuracy, all scheduled labels)", "",
              "| Contrast | Model | Mean difference | 95% resampling interval over the 24 cases |", "|---|---|---|---|"]
    for m in models:
        for c in result["models"][m]["contrasts_frozen_scorer"]:
            low, high = c["bootstrap_interval_95"]
            lines.append(f"| {c['name']} | {m} | {100 * c['mean_accuracy_delta_all_scheduled']:+.2f} points | "
                         f"[{100 * low:+.2f}, {100 * high:+.2f}] |")
    lines += ["", "## Checks", "",
              f"- Frozen files that no longer match `data/prose-freeze.json`: {len(changed)}.",
              f"- Reference decisions, project engine against the independent evaluator: {gold_disagreements} disagreements over {len(corpus)} cases.",
              *[f"- {m}: {result['models'][m]['records']} records; frozen scorer and independent computation differ on "
                f"{len(result['models'][m]['records_where_frozen_and_independent_differ'])} of them." for m in models], ""]
    tables = ROOT / "paper_build" / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    (tables / "prose24.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("\n".join(lines[4:]))
    for m in models:
        for seg in result["models"][m]["segments"]:
            print(m, seg["folder"], seg["records"], seg["first_finished_at"], seg["last_finished_at"])
        print(m, "response models reported:", result["models"][m]["response_models_reported"])
        print(m, "differences:", result["models"][m]["records_where_frozen_and_independent_differ"][:10])


if __name__ == "__main__":
    main()
