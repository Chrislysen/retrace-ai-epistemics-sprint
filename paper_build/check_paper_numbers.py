#!/usr/bin/env python3
"""Check that the numbers of the abstract and of Section 4.5 in the built report are the ones the score files give.

Sprint addition, written with AI assistance on Monday 16 November 2026. No model call.

    python paper_build/check_paper_numbers.py [paper_build/RETRACE_v3.docx]

Each line below builds a phrase from the score files of the scaling run and its extension and looks for it in the text
of the Word file. A phrase that is not found is reported: either the text or the data changed. It covers the main
text; the tables of Appendix H are generated from the same files by scale_paper_numbers.py.
"""
import html
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCALE = ROOT / "post_sweep" / "out" / "scale"
G, G26, GLM = "gemma-4-31b-it", "gemma-4-26b-a4b-it", "glm-53-flash"
REASONING = ["qwen3.8-27b", "deepseek-v4-flash", "glm-53-flash"]
SIZES = ["S", "M", "L"]


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = xml.replace("</w:p>", "\n")
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return re.sub(r"[ \t ]+", " ", text.replace("’", "'").replace("‘", "'"))


def main():
    docx = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "paper_build" / "RETRACE_v3.docx"
    text = docx_text(docx)
    score = json.loads((SCALE / "score.json").read_text(encoding="utf-8"))
    ext = json.loads((SCALE / "ext" / "score_ext.json").read_text(encoding="utf-8"))["parts"]
    paths = json.loads((SCALE / "error_paths.json").read_text(encoding="utf-8"))["models"]
    rows = json.loads((SCALE / "ext" / "score_withdrawal.json").read_text(encoding="utf-8"))["rows"]

    def cell(model, size, condition):
        return score["models"][model]["cells"][f"{size}|{condition}"]

    def total(model, condition, key):
        return sum(cell(model, s, condition).get(key, 0) for s in SIZES)

    def ext_total(part, model, condition, key, groups=SIZES):
        return sum(ext[part][model]["cells"][f"{g}|{condition}"].get(key, 0) for g in groups)

    def asserted(part, model, group, condition):
        c = ext[part][model]["cells"][f"{group}|{condition}"]
        return (c.get("copy_mediated_asserted", 0) + c.get("direct_asserted", 0), c.get("copy_mediated_of", 0) + c.get("direct_of", 0))

    def w(model, route, size="all"):
        return next(r for r in rows if r["model"] == model and r["route"].startswith(route) and r["size"] == size)

    ANSWER, WORKING, SEARCH = "Named by the model, answer only", "Named by the model, working first", "Searched"
    ga, gw, glm = w(G, ANSWER), w(G, WORKING), w(GLM, ANSWER)
    g26a, g26w = w(G26, ANSWER), w(G26, WORKING)
    xl_rows = json.loads((SCALE / "ext" / "score_withdrawal_xl.json").read_text(encoding="utf-8"))["rows"]

    def wx(model, route):
        return next(r for r in xl_rows if r["model"] == model and r["route"].startswith(route) and r["size"] == "all")

    def share(row):
        of = row.get("answered_one", 0) + row.get("answered_more", 0)
        return round(100 * (row.get("smallest_one", 0) + row.get("smallest_more", 0)) / of) if of else None
    split = paths[G]
    mid = (split["formal_fresh|L|unsupported_copy_mediated|asserted"] + split["formal_fresh|L|unsupported_direct|asserted"],
           split["formal_fresh|L|unsupported_copy_mediated|answered"] + split["formal_fresh|L|unsupported_direct|answered"])
    low, high = asserted("copyshare", G, "C0", "formal_fresh"), asserted("copyshare", G, "C8", "formal_fresh")
    direct_usable = sum(total(m, c, "usable") for m in REASONING for c in ("formal_fresh", "prose_fresh"))
    direct_wrong = sum(total(m, c, "errors_usable") for m in REASONING for c in ("formal_fresh", "prose_fresh"))
    stream = {m: [ext["stream"][m]["cells"][f"{s}|prose_extract"] for s in SIZES] for m in REASONING if m in ext.get("stream", {})}
    accepted = sum(total(m, "prose_extract", "usable") for m in REASONING) + sum(c["usable"] for cells in stream.values() for c in cells)
    identical = sum(total(m, "prose_extract", "graph_exact") for m in REASONING) + sum(c.get("graph_exact", 0) for cells in stream.values() for c in cells)
    deepseek = stream.get("deepseek-v4-flash", [])
    xl = ext["xl"][G]["cells"]
    xl_prose, xl_work, xl_comp = xl["XL|prose_fresh"], ext["xl_working"][G]["cells"]["XL|prose_working"], xl["XL|prose_extract"]
    shares = [round(100 * cell(G, s, "prose_fresh")["errors_usable"] / cell(G, s, "prose_fresh")["decisions_usable"]) for s in SIZES]
    shares.append(round(100 * xl_prose["errors_usable"] / xl_prose["decisions_usable"]))
    rep = ext["repeat"]
    differ = sum(c.get("decisions_that_differ", 0) for m in rep.values() for c in m["comparison_with_first_run"].values())
    in_both = sum(c.get("decisions_in_both", 0) for m in rep.values() for c in m["comparison_with_first_run"].values())
    all_cells = [score["models"][m]["cells"][f"{s}|prose_extract"] for m in score["models"] for s in SIZES]
    all_cells += [c for part in ("stream", "copyshare", "repeat", "xl") for m in ext.get(part, {}).values()
                  for k, c in m["cells"].items() if k.endswith("|prose_extract")]
    accepted_all = sum(c["usable"] for c in all_cells)
    inexact_all = accepted_all - sum(c.get("graph_exact", 0) for c in all_cells)
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}
    phrases = [
        f"a second run of both Gemma models changed {differ} of {in_both:,} decisions",
        f"{words.get(inexact_all, inexact_all)} of the {accepted_all} accepted declarations misstated",
        "and on none of twelve cases with 80 records" if (xl_prose["fully_correct"], xl_prose["usable"]) == (0, 12) else "GEMMA AT 80 RECORDS: CHECK THE SENTENCE",
        "per decision it was wrong on {}, {}, {} and {} percent".format(*shares),
        f"working still got {xl_work['decisions_usable'] - xl_work['errors_usable']} of {xl_work['decisions_usable']} decisions right",
        f"{12 - xl_work['usable']} of its 12 answers ran out of output",
        "Gemma-26B's then got {} of {} wrong".format(ext["xl_working"][G26]["cells"]["XL|prose_working"]["errors_usable"], ext["xl_working"][G26]["cells"]["XL|prose_working"]["decisions_usable"]),
        "none of its twelve declarations at that size was accepted" if ext["xl"][G26]["cells"]["XL|prose_extract"]["usable"] == 0 else "GEMMA-26B HAS AN ACCEPTED DECLARATION AT 80 RECORDS",
        f"all {accepted} of the reasoning models'" if accepted == identical else "A REASONING MODEL'S ACCEPTED DECLARATION IS NOT IDENTICAL TO THE REFERENCE",
        f"got {total(G, 'prose_fresh', 'errors_usable')} of {total(G, 'prose_fresh', 'decisions_usable')} and "
        f"{total(G26, 'prose_fresh', 'errors_usable')} of {total(G26, 'prose_fresh', 'decisions_usable')} decisions wrong",
        f"named one for {gw['smallest_one'] + gw['smallest_more']} of {gw['answered_one'] + gw['answered_more']} and "
        f"{g26w['smallest_one'] + g26w['smallest_more']} of {g26w['answered_one'] + g26w['answered_more']} decisions",
        f"Gemma-26B a smallest one for {g26a['smallest_one'] + g26a['smallest_more']}",
        f"Gemma-26B named a smallest set for {g26w['smallest_one'] + g26w['smallest_more']} of {g26w['answered_one'] + g26w['answered_more']} "
        f"decisions and ran out of output in {g26w['cases'] - g26w['usable']} of {g26w['cases']} cases",
        f"in {w(G, SEARCH)['usable']}, {w(G26, SEARCH)['usable']} and {w(GLM, SEARCH)['usable']} of the 36 cases"
        if all(w(m, SEARCH)["smallest_one"] + w(m, SEARCH)["smallest_more"] == w(m, SEARCH)["answered_one"] + w(m, SEARCH)["answered_more"]
               for m in (G, G26, GLM)) else "A SEARCHED SET FOR A SUPPORTED DECISION IS NOT SMALLEST",
        "Gemma was fully correct from prose on {}, {} and {} of 12 cases".format(*[cell(G, s, "prose_fresh")["fully_correct"] for s in SIZES]),
        "correct from prose on {}, {} and {} cases".format(*[cell(G26, s, "prose_fresh")["fully_correct"] for s in SIZES]),
        f"made no wrong decision in {direct_usable} direct answers" if direct_wrong == 0 else "REASONING MODELS HAVE WRONG DECISIONS",
        f"Gemma got {ext_total('working', G, 'prose_working', 'errors_usable')} of {ext_total('working', G, 'prose_working', 'decisions_usable')} "
        f"decisions wrong and Gemma-26B {ext_total('working', G26, 'prose_working', 'errors_usable')} of "
        f"{ext_total('working', G26, 'prose_working', 'decisions_usable')}",
        f"all {total(G, 'prose_extract', 'usable')} of Gemma's",
        f"of Gemma-26B's {total(G26, 'prose_extract', 'usable')}",
        f"refused {36 - total(G26, 'prose_extract', 'usable') - total(G26, 'prose_extract', 'provider_failures')} of Gemma-26B's 36 declarations",
        f"it asserted {low[0]} of {low[1]} unsupported decisions with no copies, {mid[0]} of {mid[1]} with 40 percent and {high[0]} of {high[1]} with 80 percent",
        f"named a valid set for {ga['valid_one'] + ga['valid_more']} of {ga['answered_one'] + ga['answered_more']} supported decisions and a smallest one for "
        f"{ga['smallest_one'] + ga['smallest_more']}",
        f"nearly always valid ({gw['valid_one'] + gw['valid_more']} of {gw['answered_one'] + gw['answered_more']}) but smallest for only "
        f"{gw['smallest_one'] + gw['smallest_more']}",
        "and the share fell with size: {}, {} and {} percent at 10, 20 and 40 records and {} percent at 80".format(*[share(w(G, WORKING, s)) for s in SIZES], share(wx(G, WORKING))),
        f"where {wx(G, WORKING)['cases'] - wx(G, WORKING)['usable']} of its 12 answers also ran out of output",
        f"and in {wx(G, SEARCH)['usable']} of Gemma's 12 at 80 records" if share(wx(G, SEARCH)) == 100 else "SEARCH AT 80 RECORDS IS NOT EXACT",
        f"without an answer in {glm['cases'] - glm['usable']} of {glm['cases']} cases and named a smallest set for "
        f"{glm['smallest_one'] + glm['smallest_more']} of {glm['answered_one'] + glm['answered_more']} decisions",
    ]
    missing = [p for p in phrases if p not in text]
    for p in phrases:
        print(("found    " if p in text else "MISSING  ") + p)
    print(f"{len(phrases) - len(missing)} of {len(phrases)} phrases found in {docx.name}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
