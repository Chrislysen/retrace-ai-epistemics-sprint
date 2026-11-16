#!/usr/bin/env python3
"""Zero-call analyses A1 to A7 of prereg/post_sweep_rules.md.

Sprint addition, written with AI assistance on Sunday 15 November 2026. No model call, no network.
It uses the project's engine (retrace.tiered_v6h) because the engine is the thing under test, the frozen
corpus and sessions, the launch journals, and the per-slot grades from post_sweep/rerun_frozen_scorer.py.

    python post_sweep/zero_call_analyses.py

Outputs: post_sweep/out/zero_call.json and paper_build/tables/zero_call_*.md.
"""
import json
import random
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_sweep import (PRIMARY, DIAGNOSTIC, is_missing, merge_launches, read_json, refs, root_cause,  # noqa: E402
                             slot_class)
from retrace import tiered_v6h  # noqa: E402

STATES = ("initial", "withdrawn", "restored")
PHASES = ("hist_init", "hist_withdrawn", "hist_restored", "evt_no_commit", "fresh_withdrawn", "fresh_restored")
SEED, DRAWS = 20261116, 5000


# ---------------------------------------------------------------- common definitions
def exclusions(case, state_name):
    state = case["events"]["states"][state_name]
    groups = {g["id"]: g["evidence_ids"] for g in case["events"]["document_groups"]}
    return {"document_vetoes": sorted({e for d in state["revoked_documents"] for e in groups[d]}),
            "passage_vetoes": list(state["revoked_passages"])}


def klass(box, diamond):
    return "ASSERT" if box else ("SPLIT" if diamond else "WITHHOLD")


def family_classes(graphs, case, state_name):
    result = tiered_v6h.family_supervaluation(graphs, **exclusions(case, state_name))
    return {d: klass(row["box_supported"], row["diamond_supported"]) for d, row in result["decisions"].items()}


def compare(method, gold):
    if method == gold:
        return "agree"
    if method == "ASSERT":
        return "unsafe"
    if gold == "ASSERT":
        return "over_cautious"
    return "other_difference"


def stratum(case):
    return case["family_id"]


def bootstrap(per_case, strata, seed=SEED, draws=DRAWS):
    """per_case: {case_id: (numerator, denominator)}. Percentile interval of the pooled ratio, resampling
    cases within strata. Returns None if no draw has a positive denominator."""
    rng = random.Random(seed)
    groups = defaultdict(list)
    for cid in per_case:
        groups[strata[cid]].append(cid)
    values = []
    for _ in range(draws):
        n = d = 0
        for members in groups.values():
            for cid in rng.choices(members, k=len(members)):
                n += per_case[cid][0]
                d += per_case[cid][1]
        if d:
            values.append(n / d)
    if not values:
        return None
    values.sort()
    return [values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]]


def fmt(n, d, interval=None):
    if not d:
        return f"{n} of {d}"
    text = f"{n} of {d} ({100 * n / d:.1f}%)"
    if interval:
        text += f" [{100 * interval[0]:.1f}, {100 * interval[1]:.1f}]"
    return text


# ---------------------------------------------------------------- baselines (A4)
def strip_lineage(graph):
    g = deepcopy(graph)
    for row in g["evidence"]:
        row["parents"] = []
        if row["kind"] == "copy":
            row["kind"] = "root"
    return g


def closure(graph, decision_id):
    claims = {r["id"]: r for r in graph["claims"]}
    evidence = {r["id"]: r for r in graph["evidence"]}
    seen, todo = set(), list(next(r["requires"] for r in graph["decisions"] if r["id"] == decision_id))
    while todo:
        ident = todo.pop()
        if ident in seen:
            continue
        seen.add(ident)
        if ident in claims:
            todo += list(refs(claims[ident]["positive"]) | refs(claims[ident]["negative"]))
        else:
            todo += evidence[ident]["parents"]
    return {i for i in seen if i in evidence}


def downstream_classes(graphs, case, state_name):
    engine = family_classes(graphs, case, state_name)
    x = exclusions(case, state_name)
    excluded = set(x["document_vetoes"]) | set(x["passage_vetoes"])
    return {d: ("WITHHOLD" if any(closure(g, d) & excluded for g in graphs) else c) for d, c in engine.items()}


def naive_gate_classes(graphs, case, state_name):
    """An argument is accepted unless one of its attackers is labelled IN; a claim is supported if one of its
    positive arguments is accepted; a decision if all its claims are."""
    x = exclusions(case, state_name)
    excluded = set(x["document_vetoes"]) | set(x["passage_vetoes"])
    per_decision = defaultdict(list)
    for graph in graphs:
        prepared = tiered_v6h.validate(graph)
        unknown = prepared[-1]
        for bits in product((False, True), repeat=len(unknown)):
            world = tiered_v6h._concrete(prepared, {}, excluded, dict(zip(unknown, bits)))
            labels = world["arbitration"]
            inside = set(labels["in"])
            attacked_by_in = {target for attacker, target in labels["attacks"] if attacker in inside}
            accepted = {a["id"] for a in world["arguments"] if a["id"] not in attacked_by_in}
            supported = {a["claim"] for a in world["arguments"] if a["polarity"] == "positive" and a["id"] in accepted}
            for row in prepared[0]["decisions"]:
                per_decision[row["id"]].append(all(c in supported for c in row["requires"]))
    return {d: klass(all(v), any(v)) for d, v in per_decision.items()}


# ---------------------------------------------------------------- main
def main():
    corpus = {c["id"]: c for c in read_json("data/frontier-v6h-corpus.json")["cases"]}
    slots = read_json("data/frontier-v6i-sessions.json")
    audits = read_json("post_sweep/out/sweep_frozen/score-audits.json")
    first = {(r["model"], r["case_id"], r["condition"], r["phase"]): r for r in audits
             if r.get("view") == "first_attempt" and "slot_id" in r}
    finals, _, _ = merge_launches(slots)
    classes = {sid: slot_class(row) for sid, row in finals.items()}
    causes = {sid: root_cause(sid, finals, classes) for sid in finals}
    slot_id = {(s["model"], s["case_id"], s["condition"], s["phase"]): s["slot_id"] for s in slots}
    strata = {cid: stratum(c) for cid, c in corpus.items()}
    gold = {cid: {s: family_classes([x["graph"] for x in c["evaluation"]["source_family"]], c, s) for s in STATES}
            for cid, c in corpus.items()}
    out = {"seed": SEED, "draws": DRAWS}

    def status(key):
        row = first[key]
        if is_missing(causes[slot_id[key]]):
            return "missing"
        gaps = bool((row.get("compilation") or {}).get("registry_coverage_gaps"))
        if row.get("eligible_completed") and row.get("schema_valid") and row.get("candidates") and not gaps:
            return "admitted_bare" if row.get("strict_bare_json") else "admitted_fenced"
        return "rejected"

    def pipeline(model, cid, state_name):
        key = (model, cid, "strict_source_ir", "extract")
        if not status(key).startswith("admitted"):
            return None
        return family_classes([x["graph"] for x in first[key]["candidates"]], corpus[cid], state_name)

    # A1: pipeline table on the strict-IR arm
    a1 = {}
    for model in PRIMARY + [DIAGNOSTIC]:
        cases = sorted(cid for (m, cid, cond, _) in first if m == model and cond == "strict_source_ir")
        tally, per_case_cov, per_case_unsafe = Counter(), {}, {}
        for cid in cases:
            st = status((model, cid, "strict_source_ir", "extract"))
            tally["slots"] += 1
            tally["slot_" + st] += 1
            exact = bool(first[(model, cid, "strict_source_ir", "extract")]["family"]["exact_family"])
            tally["admitted_and_exact"] += st.startswith("admitted") and exact
            tally["admitted_not_exact"] += st.startswith("admitted") and not exact
            cov = [0, 0]
            uns = [0, 0]
            for s in STATES:
                verdicts = pipeline(model, cid, s)
                for d, g in gold[cid][s].items():
                    tally["pairs"] += 1
                    tally["pairs_gold_" + g] += 1
                    result = "no_verdict" if verdicts is None else compare(verdicts[d], g)
                    tally["pair_" + result] += 1
                    if g == "ASSERT":
                        cov[1] += 1
                        cov[0] += verdicts is not None and verdicts[d] == "ASSERT"
                    else:
                        uns[1] += 1
                        uns[0] += result == "unsafe"
            per_case_cov[cid], per_case_unsafe[cid] = tuple(cov), tuple(uns)
        a1[model] = {**tally,
                     "asserted_of_gold_assert": [sum(v[0] for v in per_case_cov.values()), sum(v[1] for v in per_case_cov.values())],
                     "asserted_of_gold_assert_interval": bootstrap(per_case_cov, strata),
                     "unsafe_of_gold_not_assert": [sum(v[0] for v in per_case_unsafe.values()), sum(v[1] for v in per_case_unsafe.values())]}
    out["A1_pipeline"] = a1

    # exactness of every compiled family, by arm
    compiled = defaultdict(Counter)
    for (model, cid, cond, phase), row in first.items():
        if cond in ("strict_source_ir", "nl_projection", "long_source_ir") and row.get("candidates"):
            compiled[cond]["compiled"] += 1
            compiled[cond]["exact"] += bool(row["family"]["exact_family"])
            compiled[cond]["registry_gap"] += bool((row.get("compilation") or {}).get("registry_coverage_gaps"))
    out["compiled_families_by_arm"] = {k: dict(v) for k, v in compiled.items()}

    # A2: direct answers against the pipeline on the commitment cases
    a2 = {}
    temporal = sorted({cid for (m, cid, cond, _) in first if cond == "commitment"})
    for model in PRIMARY:
        rows = {}
        for arm, phases in (("commitment", PHASES), ("oracle_ir_consumption", ("fresh_withdrawn",)),
                            ("symbolic_assistance", ("fresh_withdrawn",))):
            for phase in phases:
                tally = Counter()
                unsafe_case, cautious_case = {}, {}
                for cid in temporal:
                    case = corpus[cid]
                    state_name = case["phases"][phase]["state_name"]
                    row = first[(model, cid, arm, phase)]
                    parsed = row.get("parsed") if row.get("eligible_completed") and row.get("schema_valid") else None
                    verdicts = pipeline(model, cid, state_name)
                    u, o = [0, 0], [0, 0]
                    for d, g in gold[cid][state_name].items():
                        tally["pairs"] += 1
                        tally["gold_" + g] += 1
                        if parsed is None:
                            direct = "no_answer"
                        else:
                            a = parsed["decisions"][d]
                            direct = compare(klass(a["box_supported"], a["diamond_supported"]), g)
                        tally["direct_" + direct] += 1
                        tally["pipeline_" + ("no_verdict" if verdicts is None else compare(verdicts[d], g))] += 1
                        if g == "ASSERT":
                            o[1] += 1
                            o[0] += direct == "over_cautious"
                        else:
                            u[1] += 1
                            u[0] += direct == "unsafe"
                    unsafe_case[cid], cautious_case[cid] = tuple(u), tuple(o)
                    tally["cases"] += 1
                    tally["direct_cases_answered"] += parsed is not None
                    tally["direct_cases_fully_right_by_class"] += parsed is not None and all(
                        klass(parsed["decisions"][d]["box_supported"], parsed["decisions"][d]["diamond_supported"]) == g
                        for d, g in gold[cid][state_name].items())
                    tally["direct_cases_exact_object"] += row.get("correct") is True
                    tally["pipeline_cases_with_verdict"] += verdicts is not None
                rows[f"{arm}/{phase}"] = {**tally, "direct_unsafe_interval": bootstrap(unsafe_case, strata),
                                          "direct_over_cautious_interval": bootstrap(cautious_case, strata)}
        a2[model] = rows
    out["A2_direct_vs_pipeline"] = a2

    # A3: copy-link capture on compiled model families
    def links(graphs):
        sets = [{(r["id"], p) for r in g["evidence"] for p in r["parents"]} for g in graphs]
        return set.intersection(*sets), set.union(*sets)

    a3 = {}
    for cond in ("strict_source_ir", "nl_projection"):
        for model in PRIMARY:
            tally = Counter()
            for (m, cid, c, phase), row in first.items():
                if m != model or c != cond:
                    continue
                gold_certain, gold_possible = links([x["graph"] for x in corpus[cid]["evaluation"]["source_family"]])
                tally["gold_certain_links_scheduled"] += len(gold_certain)
                if not row.get("candidates"):
                    continue
                mine_certain, _ = links([x["graph"] for x in row["candidates"]])
                tally["gold_certain_links_in_compiled"] += len(gold_certain)
                tally["captured"] += len(gold_certain & mine_certain)
                tally["model_certain_links"] += len(mine_certain)
                tally["model_links_gold_possible"] += len(mine_certain & gold_possible)
                gold_kind = {r["id"]: r["kind"] for r in corpus[cid]["evaluation"]["source_family"][0]["graph"]["evidence"]}
                for r in row["candidates"][0]["graph"]["evidence"]:
                    if gold_kind.get(r["id"]) != r["kind"]:
                        tally[f"kind_{gold_kind.get(r['id'])}_as_{r['kind']}"] += 1
            a3[f"{cond}|{model}"] = dict(tally)
    out["A3_copy_links"] = a3

    # A4: baselines on the authored families
    a4 = defaultdict(Counter)
    changed_cases = defaultdict(set)
    for cid, case in corpus.items():
        graphs = [x["graph"] for x in case["evaluation"]["source_family"]]
        for s in STATES:
            methods = {"no_lineage": family_classes([strip_lineage(g) for g in graphs], case, s),
                       "withdraw_downstream": downstream_classes(graphs, case, s),
                       "single_reading": family_classes(graphs[:1], case, s),
                       "naive_gate": naive_gate_classes(graphs, case, s)}
            for name, verdicts in methods.items():
                for d, g in gold[cid][s].items():
                    result = compare(verdicts[d], g)
                    for key in (name, f"{name}|{strata[cid]}"):
                        a4[key]["pairs"] += 1
                        a4[key][result] += 1
                    if result != "agree":
                        changed_cases[name].add(cid)
    out["A4_baselines_on_authored_families"] = {k: dict(v) for k, v in sorted(a4.items())}
    out["A4_cases_changed"] = {k: sorted(v) for k, v in changed_cases.items()}

    # A5: static checks on authored families and compiled model families
    a5 = Counter()
    for cid, case in corpus.items():
        graphs = [x["graph"] for x in case["evaluation"]["source_family"]]
        a5["cases"] += 1
        a5["cases_with_several_readings"] += len(graphs) > 1
        a5["cases_with_unknown_ancestry"] += any(r["kind"] == "unknown" for g in graphs for r in g["evidence"])
        a5["cases_with_copies"] += any(r["kind"] == "copy" for g in graphs for r in g["evidence"])
        a5["cases_with_multi_parent_copy"] += any(len(r["parents"]) > 1 for g in graphs for r in g["evidence"])
        a5["cases_with_negative_warrant"] += any(r["negative"] != {"const": False} for g in graphs for r in g["claims"])
        a5["cases_with_undercutter"] += any('"unless"' in json.dumps(r) for g in graphs for r in g["claims"])
        if len(graphs) > 1:
            a5["multi_reading_cases_where_readings_never_differ_in_class"] += all(
                len({json.dumps(family_classes([g], case, s), sort_keys=True) for g in graphs}) == 1 for s in STATES)
    a5["decision_state_pairs"] = sum(len(v) for g in gold.values() for v in g.values())
    for name in ("ASSERT", "SPLIT", "WITHHOLD"):
        a5["gold_pairs_" + name] = sum(c == name for g in gold.values() for v in g.values() for c in v.values())
    out["A5_static"] = dict(a5)

    # A6: casebook of the twelve bridge cases
    casebook = []
    for cid in sorted(c for c in corpus if c.startswith("ECO")):
        case = corpus[cid]
        graph = case["evaluation"]["source_family"][0]["graph"]
        kinds = Counter(r["kind"] for r in graph["evidence"])
        casebook.append({"case": cid, "title": case["title"], "documents": len(case["public"]["source_documents"]),
                         "roots": kinds["root"], "copies": kinds["copy"], "unknown": kinds["unknown"],
                         "claims": len(graph["claims"]), "decisions": len(graph["decisions"]),
                         "gold": {s: dict(Counter(gold[cid][s].values())) for s in STATES},
                         "changed_by": sorted(name for name, ids in changed_cases.items() if cid in ids),
                         "strict_ir": {m: status((m, cid, "strict_source_ir", "extract")) for m in PRIMARY}})
    out["A6_casebook"] = casebook

    # A7: engine checks on the authored families
    a7 = Counter()
    for cid, case in corpus.items():
        ev = case["events"]
        state = {k: set(v) for k, v in ev["states"]["initial"].items()}
        state["revoked_documents"] |= set(ev["withdrawal"]["add_document_vetoes"])
        state["revoked_passages"] |= set(ev["withdrawal"]["add_passage_vetoes"])
        a7["cases"] += 1
        a7["withdrawn_state_reached_by_events"] += state == {k: set(v) for k, v in ev["states"]["withdrawn"].items()}
        state["revoked_documents"] -= set(ev["restoration"]["clear_document_vetoes"])
        state["revoked_passages"] -= set(ev["restoration"]["clear_passage_vetoes"])
        a7["restored_state_reached_by_events"] += state == {k: set(v) for k, v in ev["states"]["restored"].items()}
        graphs = [x["graph"] for x in case["evaluation"]["source_family"]]
        for s in STATES:
            x = exclusions(case, s)
            excluded = set(x["document_vetoes"]) | set(x["passage_vetoes"])
            one = tiered_v6h.family_supervaluation(graphs, **x)
            two = tiered_v6h.family_supervaluation(deepcopy(graphs), **x)
            a7["evaluations"] += 1
            a7["evaluations_identical_twice"] += json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
            for graph in graphs:
                prepared = tiered_v6h.validate(graph)
                for bits in product((False, True), repeat=len(prepared[-1])):
                    world = tiered_v6h._concrete(prepared, {}, excluded, dict(zip(prepared[-1], bits)))
                    labels = world["arbitration"]
                    attacked = {t for _, t in labels["attacks"]}
                    a7["worlds"] += 1
                    a7["arguments"] += len(world["arguments"])
                    a7["attacks"] += len(labels["attacks"])
                    a7["labels_out"] += len(labels["out"])
                    a7["labels_undecided"] += len(labels["undecided"])
                    a7["accepted_but_attacked"] += len(set(labels["in"]) & attacked)
                    a7["unattacked_not_accepted"] += len({a["id"] for a in world["arguments"]} - attacked - set(labels["in"]))
    out["A7_engine_checks"] = dict(a7)

    (ROOT / "post_sweep" / "out" / "zero_call.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")

    # ---------------------------------------------------------------- markdown
    tables = ROOT / "paper_build" / "tables"
    note = "Produced by `post_sweep/zero_call_analyses.py`. Post hoc analyses fixed in `prereg/post_sweep_rules.md`; no model call."
    md = ["# Pipeline table: strict source-IR output run through the engine at the three case states", "", note,
          "A pair is one decision at one state. ASSERT means supported under every reading. Unsafe = the pipeline asserts a "
          "decision the authored family does not.", "",
          "| Model | Slots | Admitted, bare JSON | Admitted, fenced | Rejected | Missing | Admitted and exact | Admitted, not exact | "
          "Unsafe pairs | Authored-ASSERT pairs the pipeline asserts [95% interval] |", "|---|---|---|---|---|---|---|---|---|---|"]
    for model in PRIMARY + [DIAGNOSTIC]:
        t = Counter(a1[model])  # absent categories read as zero
        n, d = t["asserted_of_gold_assert"]
        md.append(f"| {model} | {t['slots']} | {t['slot_admitted_bare']} | {t['slot_admitted_fenced']} | {t['slot_rejected']} | "
                  f"{t['slot_missing']} | {t['admitted_and_exact']} | {t['admitted_not_exact']} | "
                  f"{t['unsafe_of_gold_not_assert'][0]} of {t['unsafe_of_gold_not_assert'][1]} | {fmt(n, d, t['asserted_of_gold_assert_interval'])} |")
    md += ["", "Compiled families by arm (all models): " + "; ".join(
        f"{k}: {v['compiled']} compiled, {v['exact']} exact" for k, v in sorted(compiled.items())) + ".", ""]
    (tables / "zero_call_pipeline.md").write_text("\n".join(md), encoding="utf-8", newline="\n")

    md = ["# Direct answers against the pipeline on the 12 commitment cases", "", note,
          "Direct = the model's own verdict in that arm, classed from its box and diamond fields. Pipeline = the same model's "
          "strict-IR output run through the engine at the same state. Pairs are decisions (58 per phase). Intervals resample cases.", "",
          "| Model | Arm and phase | Cases answered | Direct: unsafe of authored not-ASSERT | Direct: over-cautious of authored ASSERT | "
          "Direct: no answer (pairs) | Pipeline: unsafe | Pipeline: no verdict (pairs) |", "|---|---|---|---|---|---|---|---|"]
    for model in PRIMARY:
        for name, t in a2[model].items():
            t = Counter(t)  # absent categories read as zero
            not_assert = t["gold_SPLIT"] + t["gold_WITHHOLD"]
            md.append(f"| {model} | {name} | {t['direct_cases_answered']} of {t['cases']} | "
                      f"{fmt(t['direct_unsafe'], not_assert, t['direct_unsafe_interval'])} | "
                      f"{fmt(t['direct_over_cautious'], t['gold_ASSERT'], t['direct_over_cautious_interval'])} | "
                      f"{t['direct_no_answer']} | {t['pipeline_unsafe']} | {t['pipeline_no_verdict']} |")
    md.append("")
    (tables / "zero_call_direct_vs_pipeline.md").write_text("\n".join(md), encoding="utf-8", newline="\n")

    md = ["# Baselines on the authored families (mechanism checks)", "", note,
          "These hold by construction of the cases; they show which mechanism each family of cases needs, not an effect size.", "",
          "| Baseline | Pairs | Agree with the engine | Unsafe | Over-cautious | Other difference | Cases changed |", "|---|---|---|---|---|---|---|"]
    for name in ("no_lineage", "withdraw_downstream", "single_reading", "naive_gate"):
        t = a4[name]
        md.append(f"| {name} | {t['pairs']} | {t['agree']} | {t['unsafe']} | {t['over_cautious']} | {t['other_difference']} | {len(changed_cases[name])} |")
    md += ["", "By case family (unsafe / over-cautious pairs):", "", "| Baseline | " + " | ".join(sorted(set(strata.values()))) + " |",
           "|---|" + "---|" * len(set(strata.values()))]
    for name in ("no_lineage", "withdraw_downstream", "single_reading", "naive_gate"):
        md.append(f"| {name} | " + " | ".join(
            f"{a4[f'{name}|{fam}']['unsafe']} / {a4[f'{name}|{fam}']['over_cautious']} of {a4[f'{name}|{fam}']['pairs']}"
            for fam in sorted(set(strata.values()))) + " |")
    md += ["", "Structure of the 60 authored cases: " + "; ".join(f"{k} {v}" for k, v in sorted(a5.items())) + ".", "",
           "Engine checks on the authored families: " + "; ".join(f"{k} {v}" for k, v in sorted(a7.items())) + ".", ""]
    (tables / "zero_call_baselines.md").write_text("\n".join(md), encoding="utf-8", newline="\n")

    md = ["# Casebook: the twelve bridge cases", "", note,
          "Each case wraps excerpts of a real published source in authored administrative records and rules.", "",
          "| Case | Title | Docs | Roots / copies | Authored classes at initial, withdrawn, restored | Baselines that change a verdict | "
          + " | ".join(PRIMARY) + " |", "|---|---|---|---|---|---|" + "---|" * len(PRIMARY)]
    for row in casebook:
        classes_text = "; ".join(",".join(f"{k}:{v}" for k, v in sorted(row["gold"][s].items())) for s in STATES)
        md.append(f"| {row['case']} | {row['title']} | {row['documents']} | {row['roots']} / {row['copies']} | {classes_text} | "
                  f"{', '.join(row['changed_by']) or 'none'} | " + " | ".join(row["strict_ir"][m] for m in PRIMARY) + " |")
    md.append("")
    (tables / "zero_call_casebook.md").write_text("\n".join(md), encoding="utf-8", newline="\n")

    for name in ("zero_call_pipeline.md", "zero_call_direct_vs_pipeline.md", "zero_call_baselines.md", "zero_call_casebook.md"):
        print((tables / name).read_text(encoding="utf-8"))
    print(json.dumps(out["A3_copy_links"], indent=1))


if __name__ == "__main__":
    main()
