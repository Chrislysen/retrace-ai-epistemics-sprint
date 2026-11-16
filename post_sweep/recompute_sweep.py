#!/usr/bin/env python3
"""Independent recomputation of the 1,800-slot sweep tables (pre-registration items R1, R2, R4, R5).

Sprint addition, written with AI assistance on Sunday 15 November 2026. Standard library only; it imports
nothing from the project. Inputs: the launch journals under results/, the two overlay rows for the interrupted
requests, the frozen sessions and corpus, and the per-slot grades written by post_sweep/rerun_frozen_scorer.py
(or, with --saved, the grades the project saved in results/frontier-v6n/composite/).

    python post_sweep/recompute_sweep.py [--saved]

Outputs: post_sweep/out/sweep_tables.json and paper_build/tables/sweep_*.md.
"""
import json
import sys
from collections import Counter, defaultdict
from itertools import product
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHES = [("i", "results/frontier-v6i/primary"), ("j", "results/frontier-v6j/continuation"),
            ("k", "results/frontier-v6k/continuation"), ("m", "results/frontier-v6m/continuation"),
            ("n", "results/frontier-v6n/continuation")]
OVERLAYS = [("k", "results/frontier-v6m-recovery/orphan-dispositions.jsonl"),
            ("m", "results/frontier-v6n-recovery/orphan-dispositions.jsonl")]
COMPOSITE = "results/frontier-v6n/composite"
PRIMARY = ["deepseek-v4-flash", "gemma-4-31b-it", "glm-5.2", "glm-5.3-flash", "qwen3.8-27b"]
DIAGNOSTIC = "qwen3.5-397b"
IR_CONDITIONS = ("strict_source_ir", "nl_projection", "long_source_ir")
CONTRASTS = [  # name, A (condition, phase), B (condition, phase), subset key in the design
    ("nl_projection_minus_strict_ir", ("strict_source_ir", "extract"), ("nl_projection", "project"), "nl_projection"),
    ("assisted_minus_oracle", ("oracle_ir_consumption", "fresh_withdrawn"), ("symbolic_assistance", "fresh_withdrawn"), "oracle_assisted"),
    ("no_commit_minus_history_withdrawn", ("commitment", "hist_withdrawn"), ("commitment", "evt_no_commit"), "temporal"),
    ("fresh_withdrawn_minus_no_commit", ("commitment", "evt_no_commit"), ("commitment", "fresh_withdrawn"), "temporal"),
]


def read_json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def read_jsonl(rel):
    return [json.loads(line) for line in (ROOT / rel).read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------- R1: rebuild the slot table
def merge_launches(slots):
    finals, origin, problems = {}, {}, []
    for name, folder in LAUNCHES:
        for row in read_jsonl(f"{folder}/slot-outcomes.jsonl"):
            definitive = row.get("issued") is True or row.get("model_outcome") == "not_issued_dependency_failed"
            if not definitive:
                continue
            if row["slot_id"] in finals:
                problems.append(f"slot final in two launches: {row['slot_id']}")
            finals[row["slot_id"]], origin[row["slot_id"]] = row, name
    for name, rel in OVERLAYS:
        for row in read_jsonl(rel):
            if row["slot_id"] in finals:
                problems.append(f"overlay collides with a final: {row['slot_id']}")
            finals[row["slot_id"]], origin[row["slot_id"]] = row, name + "-interrupted"
    planned = {slot["slot_id"] for slot in slots}
    problems += [f"no final for planned slot {s}" for s in sorted(planned - set(finals))]
    problems += [f"final for unplanned slot {s}" for s in sorted(set(finals) - planned)]
    return finals, origin, problems


def slot_class(row):
    if row.get("issued") is True:
        outcome = row.get("model_outcome")
        if (outcome == "completed" and row.get("terminal_valid") is True and row.get("response_status") == "completed"
                and row.get("error") is None):
            return "completed"
        if outcome == "truncated_max_output_tokens":
            return "truncated"
        if outcome == "http_429":
            return "rate_limited"
        return "operational:" + str(row.get("error"))
    outcome = row.get("model_outcome")
    if outcome == "not_issued_dependency_failed":
        return "not_issued_dependency"
    if outcome == "issued_without_response":
        return "host_interruption"
    return "other:" + str(outcome)


def root_cause(slot_id, finals, classes, seen=()):
    """For a slot that was not issued, the class of the producer that blocked it."""
    row = finals[slot_id]
    if classes[slot_id] != "not_issued_dependency":
        return classes[slot_id]
    causes = [root_cause(dep, finals, classes, seen + (slot_id,)) for dep in row.get("blocked_dependencies", [])
              if dep not in seen]
    return next((c for c in causes if c != "truncated"), "truncated") if causes else "unknown"


def is_missing(cause):
    return cause.startswith("operational:") or cause in ("rate_limited", "host_interruption", "unknown")


# ---------------------------------------------------------------- R5: independent graph identity
def refs(expr):
    op, arg = next(iter(expr.items()))
    if op == "ref":
        return {arg}
    if op == "const":
        return set()
    if op in ("all", "any"):
        return set().union(*(refs(child) for child in arg))
    return refs(arg["support"]) | refs(arg["undercutter"])


def value(expr, v):
    op, arg = next(iter(expr.items()))
    if op == "ref":
        return v[arg]
    if op == "const":
        return arg
    if op == "all":
        return all(value(child, v) for child in arg)
    if op == "any":
        return any(value(child, v) for child in arg)
    return value(arg["support"], v) and not value(arg["undercutter"], v)


def same_function(a, b):
    names = sorted(refs(a) | refs(b))
    if len(names) > 22:
        raise ValueError("too many references for a truth table")
    return all(value(a, dict(zip(names, bits))) == value(b, dict(zip(names, bits)))
               for bits in product((False, True), repeat=len(names)))


def same_graph(a, b):
    def evidence(g):
        return {(r["id"], r["kind"], r["active"], frozenset(r["parents"])) for r in g["evidence"]}

    def decisions(g):
        return {(r["id"], frozenset(r["requires"])) for r in g["decisions"]}

    if evidence(a) != evidence(b) or decisions(a) != decisions(b):
        return False
    ca, cb = {r["id"]: r for r in a["claims"]}, {r["id"]: r for r in b["claims"]}
    return set(ca) == set(cb) and all(same_function(ca[k]["positive"], cb[k]["positive"])
                                      and same_function(ca[k]["negative"], cb[k]["negative"]) for k in ca)


def distinct(graphs):
    kept = []
    for g in graphs:
        if not any(same_graph(g, other) for other in kept):
            kept.append(g)
    return kept


def exact_family(predicted, reference):
    p, r = distinct(predicted), distinct(reference)
    return len(p) == len(r) and all(any(same_graph(x, y) for y in r) for x in p)


# ---------------------------------------------------------------- R4: independent statistics
def mcnemar_exact(a_only, b_only):
    n, k = a_only + b_only, min(a_only, b_only)
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def holm(pvalues):
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted, running = [None] * len(pvalues), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvalues) - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def cell(n, d):
    return {"n": n, "of": d}


def pct(n, d):
    return "n/a" if not d else f"{100 * n / d:.1f}%"


def main():
    saved = "--saved" in sys.argv
    grade_dir = COMPOSITE if saved else "post_sweep/out/sweep_frozen"
    slots = read_json("data/frontier-v6i-sessions.json")
    design = read_json("data/frontier-v6i-design.json")
    corpus = {case["id"]: case for case in read_json("data/frontier-v6h-corpus.json")["cases"]}
    score = read_json(f"{grade_dir}/score.json")
    audits = read_json(f"{grade_dir}/score-audits.json")
    out = {"grades_from": grade_dir}

    # R1
    finals, origin, problems = merge_launches(slots)
    composite = {row["slot_id"]: row for row in read_jsonl(f"{COMPOSITE}/slot-outcomes.jsonl")}
    out["merge"] = {"planned": len(slots), "finals": len(finals), "problems": problems[:20],
                    "by_launch": dict(sorted(Counter(origin.values()).items())),
                    "rows_identical_to_project_table": sum(finals.get(s) == composite.get(s) for s in composite),
                    "project_table_rows": len(composite),
                    "slots_with_more_than_one_attempt": sum((row.get("attempts_issued") or 0) > 1 for row in finals.values())}

    # R2
    classes = {sid: slot_class(row) for sid, row in finals.items()}
    causes = {sid: root_cause(sid, finals, classes) for sid in finals}
    by_slot = {slot["slot_id"]: slot for slot in slots}
    accounting = defaultdict(Counter)
    for sid, slot in by_slot.items():
        for key in (slot["model"], "ALL"):
            accounting[key]["scheduled"] += 1
            accounting[key][classes[sid].split(":")[0]] += 1
            if classes[sid].startswith("operational:"):
                accounting[key]["error=" + classes[sid].split(":", 1)[1]] += 1
            if classes[sid] == "not_issued_dependency":
                accounting[key]["blocked_by_" + ("missing" if is_missing(causes[sid]) else "truncation")] += 1
            accounting[key]["missing_under_sensitivity_coding"] += is_missing(causes[sid])
    out["accounting"] = {k: dict(sorted(v.items())) for k, v in accounting.items()}
    arm_accounting = defaultdict(Counter)
    for sid, slot in by_slot.items():
        arm_accounting[f"{slot['model']}|{slot['condition']}"][classes[sid].split(":")[0]] += 1
    out["accounting_by_model_and_condition"] = {k: dict(sorted(v.items())) for k, v in sorted(arm_accounting.items())}

    # R4: cells from per-slot grades, first-attempt view
    first = {row["slot_id"]: row for row in audits if row.get("view") == "first_attempt" and row.get("slot_id") in by_slot}
    out["audit_rows"] = {"total": len(audits), "first_attempt_planned_slots": len(first),
                         "conditions_seen": dict(sorted(Counter(r["condition"] for r in audits).items()))}
    cells, mismatches = {}, []
    amended = score["amended_recovered_complete"]
    for sid, slot in by_slot.items():
        key = (slot["model"], f"{slot['condition']}/{slot['phase']}")
        c = cells.setdefault(key, Counter())
        row = first[sid]
        c["scheduled"] += 1
        for field in ("provider_completed", "eligible_completed", "schema_valid", "strict_bare_json", "strict_correct"):
            c[field] += bool(row.get(field))
        c["correct"] += row.get("correct") is True
        c["decisions_right"] += row.get("correct_decisions") or 0
        c["decisions"] += row.get("decision_denominator") or 0
        c["missing"] += is_missing(causes[sid])
        c["semantic_correct"] += bool(row.get("semantic_correct"))
    models_block = amended["views"]["first_attempt"]["primary_models"]
    for (model, name), c in cells.items():
        if model not in models_block or name not in models_block[model]["conditions"]:
            continue
        theirs = models_block[model]["conditions"][name]
        for field in ("provider_completed", "eligible_completed", "schema_valid", "strict_bare_json", "correct", "strict_correct"):
            if not isinstance(theirs.get(field), dict):
                continue
            if theirs[field]["numerator"] != c[field] or theirs[field]["denominator"] != c["scheduled"]:
                if not (field == "correct" and name.startswith("nl_source")):
                    mismatches.append(f"{model} {name} {field}: project {theirs[field]['numerator']}/{theirs[field]['denominator']}, here {c[field]}/{c['scheduled']}")
    out["cells"] = {f"{m}|{n}": dict(c) for (m, n), c in sorted(cells.items())}
    out["cell_mismatches_with_project_score"] = mismatches

    # R4: the 21 tests
    correct = {(s["model"], s["case_id"], s["condition"], s["phase"]): first[sid].get("correct") is True for sid, s in by_slot.items()}
    union = {(r["model"], r["case_id"]): r.get("correct") is True for r in audits
             if r.get("view") == "first_attempt" and r["condition"] == "k10_union"}
    tests = []
    for model in PRIMARY:
        for name, a, b, subset in CONTRASTS:
            listed = design["subsets"].get(subset)
            ids = listed if isinstance(listed, list) else None
            ids = ids or sorted({s["case_id"] for s in slots if s["model"] == model and (s["condition"], s["phase"]) == b})
            pairs = [(correct[(model, cid, *a)], correct[(model, cid, *b)]) for cid in ids]
            tests.append({"model": model, "contrast": name, "n": len(pairs), "a_correct": sum(x for x, _ in pairs),
                          "b_correct": sum(y for _, y in pairs), "a_only": sum(x and not y for x, y in pairs),
                          "b_only": sum(y and not x for x, y in pairs)})
    if union:
        ids = sorted(cid for (model, cid) in union if model == "gemma-4-31b-it")
        pairs = [(union[("gemma-4-31b-it", cid)], correct[("gemma-4-31b-it", cid, "strict_source_ir", "extract")]) for cid in ids]
        tests.append({"model": "gemma-4-31b-it", "contrast": "strict_ir_minus_k10_union", "n": len(pairs),
                      "a_correct": sum(x for x, _ in pairs), "b_correct": sum(y for _, y in pairs),
                      "a_only": sum(x and not y for x, y in pairs), "b_only": sum(y and not x for x, y in pairs)})
    for t in tests:
        t["p"] = mcnemar_exact(t["a_only"], t["b_only"])
    for t, adj in zip(tests, holm([t["p"] for t in tests])):
        t["holm_p"] = adj
    theirs = {(c["model"], c["contrast"]): c for c in amended["paired_comparisons"]
              if c["view"] == "first_attempt" and c.get("primary_family_member")}
    test_mismatches = []
    for t in tests:
        other = theirs.get((t["model"], t["contrast"]))
        if other is None:
            test_mismatches.append(f"{t['model']} {t['contrast']}: not in the project's primary family")
            continue
        same = (other["n_pairs"] == t["n"] and other["paired_counts"]["a_only"] == t["a_only"]
                and other["paired_counts"]["b_only"] == t["b_only"] and abs(other["p_two_sided_exact"] - t["p"]) < 1e-9
                and abs(other["holm_adjusted_p"] - t["holm_p"]) < 1e-9)
        if not same:
            test_mismatches.append(f"{t['model']} {t['contrast']}: project {other['paired_counts']} p={other['p_two_sided_exact']} "
                                   f"holm={other['holm_adjusted_p']}; here {t}")
    out["tests"] = tests
    out["tests_in_project_primary_family"] = len(theirs)
    out["test_mismatches_with_project_score"] = test_mismatches

    # R5: regrade the IR arms with independent graph identity
    regrade = Counter()
    disagreements = []
    for sid, slot in by_slot.items():
        if slot["condition"] not in IR_CONDITIONS:
            continue
        row = first[sid]
        regrade["slots"] += 1
        if not row.get("eligible_completed") or not row.get("candidates"):
            regrade["no_compiled_family"] += 1
            mine = False
        else:
            reference = [x["graph"] for x in corpus[slot["case_id"]]["evaluation"]["source_family"]]
            exact = exact_family([x["graph"] for x in row["candidates"]], reference)
            gaps = bool((row.get("compilation") or {}).get("registry_coverage_gaps"))
            regrade["exact_family_here"] += exact
            regrade["exact_family_project"] += bool(row["family"]["exact_family"])
            if exact != bool(row["family"]["exact_family"]):
                disagreements.append(sid)
            mine = exact and not gaps and bool(row.get("strict_bare_json"))
        regrade["correct_here"] += mine
        regrade["correct_project"] += row.get("correct") is True
        if mine != (row.get("correct") is True):
            disagreements.append(sid + " (final grade)")
    out["ir_regrade"] = {**regrade, "disagreements": disagreements[:20]}

    (ROOT / "post_sweep" / "out").mkdir(parents=True, exist_ok=True)
    (ROOT / "post_sweep" / "out" / "sweep_tables.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")

    # ---------------------------------------------------------------- markdown tables
    tables = ROOT / "paper_build" / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    note = (f"Produced by `post_sweep/recompute_sweep.py` from the launch journals and the per-slot grades in `{grade_dir}/`. "
            "First-attempt view. Counts are slots unless stated.")
    acc = ["# Sweep accounting", "", note, "",
           "| Model | Scheduled | Completed | Truncated at token cap | Provider or transport failure | Not issued (producer failed) | Interrupted by host | Missing under the sensitivity coding |",
           "|---|---|---|---|---|---|---|---|"]
    for model in PRIMARY + [DIAGNOSTIC, "ALL"]:
        a = accounting[model]
        acc.append(f"| {model} | {a['scheduled']} | {a['completed']} | {a['truncated']} | {a['operational'] + a['rate_limited']} | "
                   f"{a['not_issued_dependency']} | {a['host_interruption']} | {a['missing_under_sensitivity_coding']} |")
    errors = sorted(k for k in accounting["ALL"] if k.startswith("error="))
    acc += ["", "Provider and transport failures by recorded error: " + "; ".join(f"`{k[6:]}` {accounting['ALL'][k]}" for k in errors) + ".",
            "", f"Slots with more than one attempt: {out['merge']['slots_with_more_than_one_attempt']}. "
            f"Rows identical to the project's merged table: {out['merge']['rows_identical_to_project_table']} of {out['merge']['project_table_rows']}. "
            f"Merge problems found: {len(problems)}.", ""]
    (tables / "sweep_accounting.md").write_text("\n".join(acc), encoding="utf-8", newline="\n")

    def arm_row(model, name):
        c = cells.get((model, name))
        if not c:
            return None
        low, high = c["correct"] / c["scheduled"], (c["correct"] + c["missing"]) / c["scheduled"]
        return c, f"{c['correct']} of {c['scheduled']} ({pct(c['correct'], c['scheduled'])})", f"[{100 * low:.1f}%, {100 * high:.1f}%]"

    ir = ["# Strict source-IR arm (60 cases per primary model)", "", note,
          "Correct = the compiled family equals the authored family, no registry gap, bare JSON. The range treats provider "
          "failures and host interruptions as missing and everything else as scored.", "",
          "| Model | Completed by provider | Admitted by the compiler | Exact family, bare JSON (correct) | Exact family incl. fenced output | Missing | Range if missing slots are unknown |",
          "|---|---|---|---|---|---|---|"]
    for model in PRIMARY + [DIAGNOSTIC]:
        got = arm_row(model, "strict_source_ir/extract")
        if got:
            c, text, rng = got
            ir.append(f"| {model} | {c['provider_completed']} of {c['scheduled']} | {c['schema_valid']} | {text} | {c['semantic_correct']} | {c['missing']} | {rng} |")
    ir += ["", f"Independent regrade of the three IR arms ({regrade['slots']} slots): family exactness agrees with the project's grade on "
           f"{regrade['slots'] - regrade['no_compiled_family'] - sum(1 for d in disagreements if not d.endswith('(final grade)'))} of "
           f"{regrade['slots'] - regrade['no_compiled_family']} compiled families; final grades differ on "
           f"{sum(1 for d in disagreements if d.endswith('(final grade)'))} slots.", ""]
    (tables / "sweep_strict_ir.md").write_text("\n".join(ir), encoding="utf-8", newline="\n")

    arms = ["# Other arms, per primary model", "", note, "Each cell: correct of scheduled, then the range under the sensitivity coding.", "",
            "| Arm | " + " | ".join(PRIMARY) + " |", "|---|" + "---|" * len(PRIMARY)]
    names = ["nl_projection/project", "commitment/hist_init", "commitment/hist_withdrawn", "commitment/hist_restored",
             "commitment/evt_no_commit", "commitment/fresh_withdrawn", "commitment/fresh_restored",
             "oracle_ir_consumption/fresh_withdrawn", "symbolic_assistance/fresh_withdrawn", "adversarial_refuter/counter_read"]
    for name in names:
        row = [name]
        for model in PRIMARY:
            got = arm_row(model, name)
            row.append(f"{got[0]['correct']}/{got[0]['scheduled']} {got[2]}" if got else "-")
        arms.append("| " + " | ".join(row) + " |")
    arms += ["", "Decision labels right in the commitment, oracle and assisted arms (all scheduled labels):", "",
             "| Arm | " + " | ".join(PRIMARY) + " |", "|---|" + "---|" * len(PRIMARY)]
    for name in names[1:9]:
        row = [name]
        for model in PRIMARY:
            c = cells.get((model, name))
            row.append(f"{c['decisions_right']}/{c['decisions']}" if c else "-")
        arms.append("| " + " | ".join(row) + " |")
    arms.append("")
    (tables / "sweep_arms.md").write_text("\n".join(arms), encoding="utf-8", newline="\n")

    con = ["# The 21 pre-specified paired comparisons (first attempt)", "", note,
           "Under the frozen protocol these tests are null because the run was interrupted; the numbers below are the "
           "recovery-closure sensitivity declared before the last recovery launch. Exact two-sided McNemar, Holm over 21.", "",
           "| Contrast (B minus A) | Model | Cases | A correct | B correct | A only | B only | p | Holm p |", "|---|---|---|---|---|---|---|---|---|"]
    for t in tests:
        con.append(f"| {t['contrast']} | {t['model']} | {t['n']} | {t['a_correct']} | {t['b_correct']} | {t['a_only']} | {t['b_only']} | {t['p']:.4f} | {t['holm_p']:.4f} |")
    con += ["", f"Tests recomputed here: {len(tests)}. In the project's primary family: {len(theirs)}. "
            f"Differences from the project's values: {len(test_mismatches)}.", ""]
    (tables / "sweep_contrasts.md").write_text("\n".join(con), encoding="utf-8", newline="\n")

    print(json.dumps({k: out[k] for k in ("grades_from", "merge", "audit_rows", "cell_mismatches_with_project_score",
                                         "tests_in_project_primary_family", "test_mismatches_with_project_score", "ir_regrade")}, indent=1)[:6000])
    for name in ("sweep_accounting.md", "sweep_strict_ir.md", "sweep_arms.md", "sweep_contrasts.md"):
        print((tables / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
