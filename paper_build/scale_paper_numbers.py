#!/usr/bin/env python3
"""Turn post_sweep/out/scale/score.json into the numbers and the table used in Section 4.5 and Appendix H.

Sprint addition, written with AI assistance on Monday 16 November 2026. No model call.

    python paper_build/scale_paper_numbers.py

Prints every figure the text quotes and writes paper_build/tables/scale_table_h1.json, the table item that
build_v1.ps1 reads through v1_edits.json. Nothing is typed by hand into that table.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
score = json.loads((ROOT / "post_sweep" / "out" / "scale" / "score.json").read_text(encoding="utf-8"))
NAMES = [("gemma-4-31b-it", "Gemma"), ("gemma-4-26b-a4b-it", "Gemma-26B"), ("qwen3.8-27b", "Qwen27B"), ("deepseek-v4-flash", "DeepSeek"),
         ("glm-53-flash", "GLM-Flash")]
CONDITIONS = [("formal_fresh", "Direct, formal ledger"), ("prose_fresh", "Direct, from prose"), ("prose_extract", "Compiled from prose")]
SIZES = ["S", "M", "L"]
REASONING = ["qwen3.8-27b", "deepseek-v4-flash", "glm-53-flash"]


def cell(model, size, condition):
    return score["models"][model]["cells"][f"{size}|{condition}"]


def seconds(model, size, condition):
    e = score["models"][model]["effort"].get(f"{size}|{condition}")
    return e["median_seconds"] if e else None


def tokens(model, size, condition):
    e = score["models"][model]["effort"].get(f"{size}|{condition}")
    return e["median_output_tokens"] if e else None


ext_path = ROOT / "post_sweep" / "out" / "scale" / "ext" / "score_ext.json"
ext = json.loads(ext_path.read_text(encoding="utf-8")) if ext_path.exists() else {"parts": {}}


def ext_cells(part, model):
    return ext["parts"].get(part, {}).get(model, {}).get("cells")


def show_seconds(values):
    return ", ".join("–" if x is None else f"{x:.0f}" if x >= 10 else f"{x:.1f}" for x in values)


def ext_row(name, label, cells, groups, condition):
    """One table row from cells of the extension's scorer."""
    picked = [cells.get(f"{g}|{condition}") for g in groups]
    wrong = sum(c.get("errors_usable", 0) for c in picked if c)
    of = sum(c.get("decisions_usable", 0) for c in picked if c)
    secs = [None if not c or c.get("median_seconds_x10") is None else c["median_seconds_x10"] / 10 for c in picked]
    return [name, label] + ["–" if not c else f"{c['fully_correct']} / {c['usable']}" for c in picked] + [f"{wrong} of {of}", show_seconds(secs)]


rows = [["Model", "Condition", "10 records", "20 records", "40 records", "Wrong decisions in usable answers", "Median seconds at 10, 20, 40"]]
stream_notes = []
for model, name in NAMES:
    if model not in score["models"]:
        continue
    for condition, label in CONDITIONS:
        cells = [cell(model, s, condition) for s in SIZES]
        wrong = sum(c.get("errors_usable", 0) for c in cells)
        of = sum(c.get("decisions_usable", 0) for c in cells)
        secs = [seconds(model, s, condition) for s in SIZES]
        rows.append([name, label] + [f"{c['fully_correct']} / {c['usable']}" for c in cells] + [f"{wrong} of {of}", show_seconds(secs)])
        # rows of the extension follow the row they belong with
        if condition == "prose_fresh" and ext_cells("working", model):
            rows.append(ext_row(name, "From prose, working first", ext_cells("working", model), SIZES, "prose_working"))
        if condition == "prose_extract" and ext_cells("stream", model):
            rows.append(ext_row(name, "Compiled, streamed", ext_cells("stream", model), SIZES, "prose_extract"))
            sent = sum((ext_cells("stream", model).get(f"{s}|prose_extract") or {}).get("issued", 0) for s in SIZES)
            if sent < 36:
                stream_notes.append(f" {name}'s streamed row covers the {sent} compilations issued before the stop.")
item = {"kind": "table", "like": 3, "widths": [70, 122, 43, 43, 43, 70, 77], "rows": rows,
        "caption": "Table H1. Scaling run and its extension: fully correct cases / usable answers, of twelve scheduled, by size. "
                   "Wrong decisions are counted in usable answers over the three sizes. Seconds are medians over requests that "
                   "returned an answer. Gemma-26B, the rows with working shown first and the streamed compilations belong to the extension."
                   + "".join(stream_notes)}
(ROOT / "paper_build" / "tables" / "scale_table_h1.json").write_text(json.dumps(item, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

# Table H2: copy share at 40 records (part E4). The 40 percent column is the main run's 40-record set.
share_rows = [["Model", "Condition", "No copies", "40% copies", "80% copies", "Unsupported decisions asserted, at 0%, 40%, 80% copies",
               "Of these copy-mediated, at 40% and 80%"]]
paths_file = ROOT / "post_sweep" / "out" / "scale" / "error_paths.json"
paths = json.loads(paths_file.read_text(encoding="utf-8")) if paths_file.exists() else {"models": {}}
SHARE_CONDITIONS = [("formal_fresh", "Direct, formal ledger"), ("prose_fresh", "Direct, from prose"),
                    ("prose_working", "From prose, working first"), ("prose_extract", "Compiled from prose")]
for model, name in NAMES:
    share = ext_cells("copyshare", model)
    if not share:
        continue
    share_working = ext_cells("copyshare_working", model) or {}
    main_working = ext_cells("working", model) or {}
    split = paths["models"].get(model, {})
    for condition, label in SHARE_CONDITIONS:
        source = share_working if condition == "prose_working" else share
        low, high = source.get(f"C0|{condition}"), source.get(f"C8|{condition}")
        if condition == "prose_working":
            mid = main_working.get("L|prose_working")
            mid_copy = (mid.get("copy_mediated_asserted", 0), mid.get("copy_mediated_of", 0))
            mid_direct = (mid.get("direct_asserted", 0), mid.get("direct_of", 0))
        else:
            mid = cell(model, "L", condition)
            mid_copy = (split.get(f"{condition}|L|unsupported_copy_mediated|asserted", 0), split.get(f"{condition}|L|unsupported_copy_mediated|answered", 0))
            mid_direct = (split.get(f"{condition}|L|unsupported_direct|asserted", 0), split.get(f"{condition}|L|unsupported_direct|answered", 0))
        pair = lambda c, key: (c.get(f"{key}_asserted", 0), c.get(f"{key}_of", 0))  # noqa: E731
        both = lambda p, q: f"{p[0] + q[0]} of {p[1] + q[1]}"  # noqa: E731
        fmt = lambda p: f"{p[0]} of {p[1]}"  # noqa: E731
        share_rows.append([name, label, f"{low['fully_correct']} / {low['usable']}", f"{mid['fully_correct']} / {mid['usable']}",
                           f"{high['fully_correct']} / {high['usable']}",
                           f"{both(pair(low, 'direct'), pair(low, 'copy_mediated'))}; {both(mid_direct, mid_copy)}; {both(pair(high, 'direct'), pair(high, 'copy_mediated'))}",
                           f"{fmt(mid_copy)}; {fmt(pair(high, 'copy_mediated'))}"])
if len(share_rows) > 1:
    share_item = {"kind": "table", "like": 3, "widths": [70, 118, 40, 40, 40, 88, 72], "rows": share_rows,
                  "caption": "Table H2. Copy share at 40 records (extension, part E4): fully correct cases / usable answers of twelve, and "
                             "unsupported decisions that a usable answer asserted, in all and for the copy-mediated ones. The 40 percent column "
                             "is the main run's 40-record set."}
    (ROOT / "paper_build" / "tables" / "scale_table_h2.json").write_text(json.dumps(share_item, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("--- Table H2 ---")
    for r in share_rows:
        print(" | ".join(r))
    print()
for r in rows:
    print(" | ".join(r))
print()

for model, name in NAMES:
    if model not in score["models"]:
        print(f"{name}: not run")
        continue
    m = score["models"][model]
    print(f"== {name}: requests {m['requests_issued']}, rejected 429 {m['requests_rejected_with_429']}, slots with a record {m['slots_with_an_answer_record']}, "
          f"scorer disagreements {m['scorer_disagreements']}, errors {m['errors']}, response models {m['response_models']}, cost {m['observed_cost_credits']}")
    for condition, label in CONDITIONS:
        for s in SIZES:
            c = cell(model, s, condition)
            print(f"   {s} {label:26s} issued {c['issued']:2d} usable {c['usable']:2d} provider failures {c['provider_failures']:2d} "
                  f"other unusable {c['issued'] - c['usable'] - c['provider_failures']:2d} not issued {c['cases'] - c['issued']:2d} | fully correct {c['fully_correct']:2d} | "
                  f"wrong in usable {c.get('errors_usable', 0)} of {c.get('decisions_usable', 0)} | unsafe {c.get('unsafe', 0)} of {c.get('unsupported_targets', 0)} "
                  f"(withdrawn still asserted {c.get('missed', 0)} of {c.get('missed_of', 0)}, never supported {c.get('never_accepted', 0)} of {c.get('never_accepted_of', 0)}) | "
                  f"dropped {c.get('dropped', 0)} of {c.get('supported_targets', 0)} (surviving alternative {c.get('protected_dropped', 0)} of {c.get('protected_dropped_of', 0)}, "
                  f"untouched {c.get('unaffected_dropped', 0)} of {c.get('unaffected_dropped_of', 0)}) | graph exact {c.get('graph_exact', '')} "
                  f"accepted graph with a wrong decision {c.get('accepted_graph_wrong_decision', '')} | tokens {tokens(model, s, condition)} seconds {seconds(model, s, condition)}")
    for condition, label in CONDITIONS:
        cs = [cell(model, s, condition) for s in SIZES]
        rates = ", ".join(f"{100 * c.get('errors_usable', 0) / c['decisions_usable']:.1f}%" if c.get("decisions_usable") else "–" for c in cs)
        print(f"   {label}: wrong decisions per usable decision at S, M, L: {rates}; over the three sizes "
              f"{sum(c.get('errors_usable', 0) for c in cs)} of {sum(c.get('decisions_usable', 0) for c in cs)}; "
              f"fully correct {sum(c['fully_correct'] for c in cs)} of {sum(c['usable'] for c in cs)} usable, {sum(c['cases'] for c in cs)} scheduled")
    for s in SIZES:
        k = m["compiled_minus_prose"][s]
        u = k["both_usable"]
        print(f"   {s} compiled minus prose: fully correct {k['fully_correct_compiled']} vs {k['fully_correct_prose']}; compiled right and prose wrong {k['compiled_right_prose_wrong']}, "
              f"reverse {k['prose_right_compiled_wrong']}; accuracy difference {k['accuracy_difference_points_all_scheduled']:+.1f} {k['interval_95']}; "
              f"both usable: {u['cases']} cases, unsafe prose {u['unsafe_prose']} compiled {u['unsafe_compiled']} of {u['unsupported_decisions']}, "
              f"fully correct prose {u['fully_correct_prose']} compiled {u['fully_correct_compiled']}")
print()

have = [m for m in REASONING if m in score["models"]]
print(f"== reasoning models with data: {have}")
for condition, label in CONDITIONS:
    line = []
    for s in SIZES:
        cs = [cell(m, s, condition) for m in have]
        line.append(f"{s}: usable {sum(c['usable'] for c in cs)} of {sum(c['cases'] for c in cs)}, fully correct {sum(c['fully_correct'] for c in cs)}, "
                    f"wrong decisions {sum(c.get('errors_usable', 0) for c in cs)} of {sum(c.get('decisions_usable', 0) for c in cs)}, "
                    f"provider failures {sum(c['provider_failures'] for c in cs)}, not issued {sum(c['cases'] - c['issued'] for c in cs)}, "
                    f"median seconds {[seconds(m, s, condition) for m in have]}")
    print(f"   {label}:\n      " + "\n      ".join(line))
direct = [cell(m, s, c) for m in have for s in SIZES for c in ("formal_fresh", "prose_fresh")]
print(f"   direct answers, both kinds, all sizes: usable {sum(c['usable'] for c in direct)} of {sum(c['cases'] for c in direct)}, fully correct {sum(c['fully_correct'] for c in direct)}, "
      f"wrong decisions {sum(c.get('errors_usable', 0) for c in direct)} of {sum(c.get('decisions_usable', 0) for c in direct)}")
compiled = [cell(m, s, "prose_extract") for m in have for s in SIZES]
print(f"   compiled, all sizes: usable {sum(c['usable'] for c in compiled)} of {sum(c['cases'] for c in compiled)}, fully correct {sum(c['fully_correct'] for c in compiled)}, "
      f"graph exact {sum(c.get('graph_exact', 0) for c in compiled)}, wrong decisions {sum(c.get('errors_usable', 0) for c in compiled)} of {sum(c.get('decisions_usable', 0) for c in compiled)}")
everything = [score["models"][m]["cells"][k] for m in score["models"] for k in score["models"][m]["cells"] if k.endswith("prose_extract")]
print(f"   all models, compiled: usable {sum(c['usable'] for c in everything)}, graph exact {sum(c.get('graph_exact', 0) for c in everything)}, "
      f"accepted graph with a wrong decision {sum(c.get('accepted_graph_wrong_decision', 0) for c in everything)}, wrong decisions {sum(c.get('errors_usable', 0) for c in everything)} "
      f"of {sum(c.get('decisions_usable', 0) for c in everything)}")
print()
print("requests:", json.dumps(score.get("requests"), indent=0).replace("\n", " "))
print("scorer disagreements in all:", score["scorer_disagreements"])

# The sums that Section 4.5 and Appendix H quote for the three reasoning models together.
if have:
    def total(condition, key, size=None):
        return sum(cell(m, s, condition).get(key, 0) for m in have for s in (SIZES if size is None else [size]))
    print()
    print("reasoning models together (of", 12 * len(have), "cases per size):")
    print("   usable compilations at S, M, L:", [total("prose_extract", "usable", s) for s in SIZES])
    print("   usable direct answers from prose at S, M, L:", [total("prose_fresh", "usable", s) for s in SIZES])
    print("   usable direct answers from the ledger at S, M, L:", [total("formal_fresh", "usable", s) for s in SIZES])
    for m in have:
        name = dict(NAMES)[m]
        print(f"   {name}: usable direct answers, ledger {sum(cell(m, s, 'formal_fresh')['usable'] for s in SIZES)} and prose "
              f"{sum(cell(m, s, 'prose_fresh')['usable'] for s in SIZES)} of 36; usable compilations {[cell(m, s, 'prose_extract')['usable'] for s in SIZES]}; "
              f"other unusable (not a provider failure) {sum(cell(m, s, c)['issued'] - cell(m, s, c)['usable'] - cell(m, s, c)['provider_failures'] for s in SIZES for c, _ in CONDITIONS)}; "
              f"wrong decisions in usable answers {sum(cell(m, s, c).get('errors_usable', 0) for s in SIZES for c, _ in CONDITIONS)}")
    wrong_any = sum(cell(m, s, c).get("errors_usable", 0) for m in have for s in SIZES for c, _ in CONDITIONS)
    print("   wrong decisions in any usable answer of a reasoning model:", wrong_any)
r = score["requests"]
print(f"all requests, connection tests included: {r['runs_requests'] + r['smoke_requests']}; HTTP 429: {r['runs_http_429'] + r['smoke_http_429']}; "
      f"HTTP 504: {r['runs_http_504'] + r['smoke_http_504']}; observed token cost {(r['runs_observed_cost_credits_x10000'] + r['smoke_observed_cost_credits_x10000']) / 10000:.2f} credits")
print("requests per model:", {dict(NAMES)[m]: score["models"][m]["requests_issued"] for m in score["models"]},
      "| HTTP 504 per model:", {dict(NAMES)[m]: score["models"][m]["errors"].get("http_error 504", 0) for m in score["models"]})

# Table H3: the smallest further withdrawal (part E5), over the three sizes and at 40 records.
withdrawal_path = ROOT / "post_sweep" / "out" / "scale" / "ext" / "score_withdrawal.json"
if withdrawal_path.exists():
    withdrawal = json.loads(withdrawal_path.read_text(encoding="utf-8"))
    called = {r["model"] for r in withdrawal["rows"] if r.get("requests_sent")}
    table = [["Model", "How the set was found", "Usable /36", "One record needed: valid, smallest, of", "More needed: valid, smallest, of",
              "More needed at 40 records: valid, smallest, of", "Cases with every set smallest /36"]]
    names = dict(NAMES)
    order = {"Named by the model, answer only": 0, "Named by the model, working first": 1, "Searched in the model's accepted declaration (no call)": 2}
    short = {"Named by the model, answer only": "Named by the model, answer only", "Named by the model, working first": "Named by the model, working first",
             "Searched in the model's accepted declaration (no call)": "Searched in its accepted declarations, no call"}
    picked = [r for r in withdrawal["rows"] if r["model"] in called]
    for model, _ in NAMES:
        for route in sorted({r["route"] for r in picked if r["model"] == model}, key=lambda x: order[x]):
            whole = next(r for r in picked if r["model"] == model and r["route"] == route and r["size"] == "all")
            large = next(r for r in picked if r["model"] == model and r["route"] == route and r["size"] == "L")
            g = lambda row, key: row.get(key, 0)  # noqa: E731
            table.append([names[model], short[route], f"{g(whole, 'usable')}",
                          f"{g(whole, 'valid_one')}, {g(whole, 'smallest_one')}, {g(whole, 'answered_one')}",
                          f"{g(whole, 'valid_more')}, {g(whole, 'smallest_more')}, {g(whole, 'answered_more')}",
                          f"{g(large, 'valid_more')}, {g(large, 'smallest_more')}, {g(large, 'answered_more')}",
                          f"{g(whole, 'cases_all_smallest')}"])
            print(f"E5 {names[model]} | {route} | all sizes: usable {g(whole, 'usable')} of {g(whole, 'cases')}; one-record decisions valid {g(whole, 'valid_one')} "
                  f"smallest {g(whole, 'smallest_one')} of {g(whole, 'answered_one')}; more-record decisions valid {g(whole, 'valid_more')} smallest "
                  f"{g(whole, 'smallest_more')} of {g(whole, 'answered_more')}; empty sets right {g(whole, 'empty_correct')} of {g(whole, 'answered_none')}; "
                  f"cases with every set smallest {g(whole, 'cases_all_smallest')}; tokens {whole.get('median_output_tokens')}, seconds {whole.get('median_seconds')}; "
                  f"errors {whole.get('errors')}; outputs without the object {whole.get('outputs_without_the_object')}; one-record decisions with a valid but larger set "
                  f"{g(whole, 'valid_but_larger_one')}, of which one named record alone would have sufficed {g(whole, 'padded_one')}")
            for size in SIZES:
                row = next(r for r in picked if r["model"] == model and r["route"] == route and r["size"] == size)
                print(f"      {size}: usable {g(row, 'usable')}/{g(row, 'cases')}; one: {g(row, 'valid_one')}/{g(row, 'smallest_one')} of {g(row, 'answered_one')}; "
                      f"more: {g(row, 'valid_more')}/{g(row, 'smallest_more')} of {g(row, 'answered_more')}; every set smallest in {g(row, 'cases_all_smallest')} cases")
    if len(table) > 1:
        parts = "parts E5 and E6" if "gemma-4-26b-a4b-it" in called else "part E5"
        h3 = {"kind": "table", "like": 3, "widths": [66, 126, 40, 64, 58, 62, 52], "rows": table,
              "caption": f"Table H3. The smallest further withdrawal (extension, {parts}), over the 128 supported decisions of the 36 cases: sets that "
                         "are valid, sets that are smallest, and decisions answered. A set is valid when the decision has no support after it is withdrawn."}
        (ROOT / "paper_build" / "tables" / "scale_table_h3.json").write_text(json.dumps(h3, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print("--- Table H3 ---")
        for r in table:
            print(" | ".join(r))
    print("E5 requests:", withdrawal.get("requests"))

# Accepted declarations everywhere a compilation was scored: main design, streamed repeats (E3), copy-share cases (E4).
print("--- accepted declarations ---")
grand = {"accepted": 0, "identical": 0, "correct": 0}
by_group = {}
lines_out = []
for model, name in NAMES:
    if model in score["models"]:
        cells = [cell(model, s, "prose_extract") for s in SIZES]
        lines_out.append(("main design", model, name, 36, cells))
    for part, label in (("stream", "streamed repeat"), ("copyshare", "copy-share cases"), ("repeat", "second run"), ("xl", "80-record cases")):
        part_cells = ext_cells(part, model)
        if part_cells:
            cells = [v for k, v in part_cells.items() if k.endswith("|prose_extract")]
            lines_out.append((label, model, name, sum(c.get("issued", 0) for c in cells), cells))
for label, model, name, sent, cells in lines_out:
    a = sum(c["usable"] for c in cells)
    e = sum(c.get("graph_exact", 0) for c in cells)
    f = sum(c["fully_correct"] for c in cells)
    print(f"{label:18s} {name:10s} issued {sent:3d}  accepted {a:3d}  identical to the reference {e:3d}  fully correct {f:3d}")
    group = "reasoning models" if model in REASONING else name
    g = by_group.setdefault((group, label), [0, 0, 0])
    g[0] += a; g[1] += e; g[2] += f
    grand["accepted"] += a; grand["identical"] += e; grand["correct"] += f
for (group, label), g in by_group.items():
    print(f"   {group}, {label}: accepted {g[0]}, identical {g[1]}, fully correct {g[2]}")
print("all accepted declarations:", grand)

# Part E7: the second run of the main design, beside the first (prereg/scale_extension_addendum_5.md).
print("--- E7 second run ---")
for model, name in NAMES:
    part = ext["parts"].get("repeat", {}).get(model)
    if not part:
        continue
    print(f"{name}: requests {part['requests_sent']}, errors {part['errors']}, scorer disagreements {part['scorer_disagreements']}")
    for condition, label in CONDITIONS:
        second = [part["cells"][f"{s}|{condition}"] for s in SIZES]
        first = [cell(model, s, condition) for s in SIZES]
        c = part["comparison_with_first_run"][condition]
        print(f"   {label:24s} fully correct run 1 {[x['fully_correct'] for x in first]} run 2 {[x['fully_correct'] for x in second]}; "
              f"usable run 1 {sum(x['usable'] for x in first)} run 2 {sum(x['usable'] for x in second)}; wrong decisions in usable answers run 1 "
              f"{sum(x.get('errors_usable', 0) for x in first)} of {sum(x.get('decisions_usable', 0) for x in first)}, run 2 "
              f"{sum(x.get('errors_usable', 0) for x in second)} of {sum(x.get('decisions_usable', 0) for x in second)}; usable in both "
              f"{c.get('usable_in_both', 0)}, first only {c.get('usable_in_first_only', 0)}, second only {c.get('usable_in_second_only', 0)}, "
              f"neither {c.get('usable_in_neither', 0)}; decisions that differ {c.get('decisions_that_differ', 0)} of "
              f"{c.get('decisions_in_both', 0)} in {c.get('slots_with_a_difference', 0)} slots; fully correct in both "
              f"{c.get('fully_correct_in_both', 0)}, first only {c.get('fully_correct_in_first_only', 0)}, second only "
              f"{c.get('fully_correct_in_second_only', 0)}")

# Part E8: 80 records. Table H4 (the four routes) and Table H5 (the search task).
xl_rows = [["Model", "Condition", "Fully correct / usable, of 12", "Wrong decisions in usable answers", "Unsupported decisions asserted",
            "Median output tokens", "Median seconds"]]
print("--- E8 80 records ---")
for model, name in NAMES:
    direct, working = ext_cells("xl", model), ext_cells("xl_working", model)
    if not direct:
        continue
    for condition, label, source in (("formal_fresh", "Direct, formal ledger", direct), ("prose_fresh", "Direct, from prose", direct),
                                     ("prose_working", "From prose, working first", working or {}),
                                     ("prose_extract", "Compiled from prose", direct)):
        c = source.get(f"XL|{condition}")
        if not c:
            continue
        asserted = c.get("copy_mediated_asserted", 0) + c.get("direct_asserted", 0)
        of = c.get("copy_mediated_of", 0) + c.get("direct_of", 0)
        secs = c.get("median_seconds_x10")
        xl_rows.append([name, label, f"{c['fully_correct']} / {c['usable']}", f"{c.get('errors_usable', 0)} of {c.get('decisions_usable', 0)}",
                        f"{asserted} of {of}", f"{c.get('median_output_tokens', '–')}", "–" if secs is None else show_seconds([secs / 10])])
        print(f"{name} | {label}: issued {c['issued']}, usable {c['usable']}, fully correct {c['fully_correct']}, wrong {c.get('errors_usable', 0)} of "
              f"{c.get('decisions_usable', 0)} (unsafe {c.get('unsafe', 0)} of {c.get('unsafe_of', 0)}, dropped {c.get('dropped', 0)} of {c.get('dropped_of', 0)}), "
              f"asserted copy-mediated {c.get('copy_mediated_asserted', 0)} of {c.get('copy_mediated_of', 0)}, direct {c.get('direct_asserted', 0)} of "
              f"{c.get('direct_of', 0)}, provider failures {c['provider_failures']}, graph exact {c.get('graph_exact', '-')}, tokens "
              f"{c.get('median_output_tokens')}, seconds {None if secs is None else secs / 10}")
    for part_name in ("xl", "xl_working"):
        p = ext["parts"].get(part_name, {}).get(model)
        if p:
            print(f"   {part_name}: requests {p['requests_sent']}, errors {p['errors']}, no final answer object {p['no_final_answer_object']}, "
                  f"scorer disagreements {p['scorer_disagreements']}")
if len(xl_rows) > 1:
    h4 = {"kind": "table", "like": 3, "widths": [60, 118, 62, 66, 66, 50, 46], "rows": xl_rows,
          "caption": "Table H4. Twelve cases with 80 records (extension, part E8): fully correct cases / usable answers, wrong decisions in "
                     "usable answers, and unsupported decisions that a usable answer asserted. All requests of this part were streamed."}
    (ROOT / "paper_build" / "tables" / "scale_table_h4.json").write_text(json.dumps(h4, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("--- Table H4 ---")
    for r in xl_rows:
        print(" | ".join(r))

xl_search_path = ROOT / "post_sweep" / "out" / "scale" / "ext" / "score_withdrawal_xl.json"
if xl_search_path.exists():
    xl_search = json.loads(xl_search_path.read_text(encoding="utf-8"))
    order5 = {"Named by the model, answer only": 0, "Named by the model, working first": 1, "Searched in the model's accepted declaration (no call)": 2}
    short5 = {"Named by the model, answer only": "Named by the model, answer only", "Named by the model, working first": "Named by the model, working first",
              "Searched in the model's accepted declaration (no call)": "Searched in its accepted declarations, no call"}
    table5 = [["Model", "How the set was found", "Usable /12", "One record needed: valid, smallest, of", "More needed: valid, smallest, of",
               "No support: empty set given, of", "Cases with every set smallest /12"]]
    for model, name in NAMES:
        for route in sorted({r["route"] for r in xl_search["rows"] if r["model"] == model}, key=lambda x: order5[x]):
            whole = next(r for r in xl_search["rows"] if r["model"] == model and r["route"] == route and r["size"] == "all")
            g = lambda key: whole.get(key, 0)  # noqa: E731
            table5.append([name, short5[route], f"{g('usable')}", f"{g('valid_one')}, {g('smallest_one')}, {g('answered_one')}",
                           f"{g('valid_more')}, {g('smallest_more')}, {g('answered_more')}", f"{g('empty_correct')}, {g('answered_none')}",
                           f"{g('cases_all_smallest')}"])
            print(f"E8 search {name} | {route}: usable {g('usable')} of {g('cases')}; one-record valid {g('valid_one')} smallest {g('smallest_one')} of "
                  f"{g('answered_one')}; more-record valid {g('valid_more')} smallest {g('smallest_more')} of {g('answered_more')}; empty sets right "
                  f"{g('empty_correct')} of {g('answered_none')}; cases with every set smallest {g('cases_all_smallest')}; tokens "
                  f"{whole.get('median_output_tokens')}, seconds {whole.get('median_seconds')}; errors {whole.get('errors')}; outputs without the object "
                  f"{whole.get('outputs_without_the_object')}; oversized one-record sets {g('valid_but_larger_one')}, padded {g('padded_one')}")
    if len(table5) > 1:
        h5 = {"kind": "table", "like": 3, "widths": [64, 126, 40, 66, 60, 60, 52], "rows": table5,
              "caption": "Table H5. The smallest further withdrawal at 80 records (extension, part E8), over the 93 supported and 51 unsupported "
                         "decisions of the twelve cases: sets that are valid, sets that are smallest, and decisions answered."}
        (ROOT / "paper_build" / "tables" / "scale_table_h5.json").write_text(json.dumps(h5, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print("--- Table H5 ---")
        for r in table5:
            print(" | ".join(r))

# The size trend of the search task: share of supported decisions (in usable answers) that got a smallest set, by size.
print("--- smallest sets by size ---")
if withdrawal_path.exists():
    both = [(r, s) for r in withdrawal["rows"] for s in SIZES if r["size"] == s]
    if xl_search_path.exists():
        both += [(r, "XL") for r in xl_search["rows"] if r["size"] == "XL"]
    for model, name in NAMES:
        for route in ("Named by the model, answer only", "Named by the model, working first", "Searched in the model's accepted declaration (no call)"):
            parts_by_size = []
            for size in SIZES + ["XL"]:
                row = next((r for r, s in both if s == size and r["model"] == model and r["route"] == route), None)
                if row is None:
                    continue
                got = row.get("smallest_one", 0) + row.get("smallest_more", 0)
                of = row.get("answered_one", 0) + row.get("answered_more", 0)
                parts_by_size.append(f"{size}: {got} of {of} ({round(100 * got / of) if of else '-'}%), usable {row.get('usable', 0)} of {row.get('cases', 0)}, "
                                     f"every set smallest in {row.get('cases_all_smallest', 0)} cases")
            if parts_by_size:
                print(f"{name} | {route} | " + "; ".join(parts_by_size))
