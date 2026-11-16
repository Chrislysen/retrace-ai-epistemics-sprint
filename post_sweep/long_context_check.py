#!/usr/bin/env python3
"""
Long documents: direct answers versus the declaration route, from the released per-slot scores.

Usage:   python3 long_context_check.py <path-to-extracted-artifact>
Needs:   Python 3.11+, standard library only. No network, no model calls.
Reads:   results/frontier-v6n/composite/score-audits.json   (view "first_attempt")
         data/frontier-v6h-corpus.json                       (authored families, for the reference verdicts)

The frozen design holds a matched subset of 12 cases that Gemma also received with 16,384-token
document bodies. Each case has four first-attempt slots:

  short direct        commitment / fresh_withdrawn        the model states the verdicts itself
  short declaration   strict_source_ir / extract          the model declares, the engine computes
  long direct         long_commitment / fresh_withdrawn
  long declaration    long_source_ir / extract

All four are compared at the withdrawn state.

  direct answer   "fully correct" is the released field `correct`: every decision equals the authored
                  verdict. That field tolerates an outer code fence (frontier_v6h_eval._score_slot sets
                  correct = parsed == wanted for verdict conditions).
  declaration     "fully correct" is semantic_admission_event_fidelity.states.withdrawn.exact: the
                  engine's verdicts from the admitted declaration equal the authored verdicts. An outer
                  fence is tolerated here too. Under the frozen bare-JSON endpoint (correct =
                  semantic_correct and strict_bare_json) every Gemma declaration scores zero, which
                  this script prints as well.

Wrong direct verdicts are classified against reference verdicts recomputed with the released engine:
  dropped   the authored family supports the decision under every reading and the answer does not say so
  extra     the answer says supported under every reading and the authored family does not
  other     same every-reading flag, a different detail

The last section is a sensitivity only. The frozen wrapper rule accepts a code fence when the closing
fence stands on its own line. Some refused outputs close the fence on the last line of the JSON. The
section reports what a tolerant unwrap would have admitted. It changes no frozen result.
"""
import collections
import json
import sys

MODEL = "gemma-4-31b-it"


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = sys.argv[1]
    sys.path.insert(0, root)
    from retrace.frontier_v6h_eval import expected_verdict

    audits = json.load(open(root + "/results/frontier-v6n/composite/score-audits.json", encoding="utf-8"))
    rows = [r for r in audits if r["view"] == "first_attempt"]
    corpus = json.load(open(root + "/data/frontier-v6h-corpus.json", encoding="utf-8"))
    cases_by_id = {c["id"]: c for c in corpus["cases"]}

    # 1. Field meanings: reproduce counts the paper already reports.
    primary = [r for r in rows if r["condition"] == "strict_source_ir" and r["model"] != "qwen3.5-397b"]
    counts = (len(primary), sum(r["provider_completed"] for r in primary), sum(r["schema_valid"] for r in primary),
              sum(r["semantic_correct"] for r in primary), sum(r["correct"] is True for r in primary))
    print("Check of field meanings against the paper (Section 4.1):")
    print("  primary declaration slots %d, completed %d, admitted %d, exact family %d, exact in bare JSON %d" % counts)
    ok = counts == (300, 210, 181, 181, 139)

    g = [r for r in rows if r["model"] == MODEL]

    def pick(condition, phase):
        return {r["case_id"]: r for r in g if r["condition"] == condition and r["phase"] == phase}

    long_decl, long_direct = pick("long_source_ir", "extract"), pick("long_commitment", "fresh_withdrawn")
    cases = sorted(long_decl)
    short_decl = {c: r for c, r in pick("strict_source_ir", "extract").items() if c in long_decl}
    short_direct = {c: r for c, r in pick("commitment", "fresh_withdrawn").items() if c in long_decl}
    ok = ok and len(cases) == 12 and set(long_direct) == set(cases) == set(short_decl) == set(short_direct)

    # 2. Reference verdicts, recomputed and cross-checked against every released fully correct answer.
    gold = {c: expected_verdict(cases_by_id[c], "withdrawn") for c in cases}
    agree = 0
    for r in rows:
        if r["phase"] == "fresh_withdrawn" and r["case_id"] in gold and r["correct"] is True \
                and r["condition"] in ("commitment", "long_commitment", "diagnostic_commitment"):
            ok = ok and r["parsed"] == gold[r["case_id"]]
            agree += 1
    print("  reference verdicts recomputed for 12 cases; they equal all %d released fully correct direct answers" % agree)

    def outcome_direct(r):
        if not r["schema_valid"]:
            return "no usable answer"
        return "fully correct" if r["correct"] is True else "wrong somewhere"

    def outcome_decl(r):
        if not r["schema_valid"]:
            return "no usable answer"
        return "fully correct" if r["semantic_admission_event_fidelity"]["states"]["withdrawn"]["exact"] else "wrong somewhere"

    def decisions_direct(r):
        return r["correct_decisions"], r["decision_denominator"]

    def decisions_decl(r):
        w = r["semantic_admission_event_fidelity"]["states"]["withdrawn"]
        return w["correct_decisions"], w["decision_denominator"]

    cells = [("short", "direct answer", short_direct, outcome_direct, decisions_direct),
             ("short", "declaration + engine", short_decl, outcome_decl, decisions_decl),
             ("long", "direct answer", long_direct, outcome_direct, decisions_direct),
             ("long", "declaration + engine", long_decl, outcome_decl, decisions_decl)]

    print()
    print("Matched 12 cases, %s, withdrawn state, first attempt" % MODEL)
    print("  %-7s %-22s %14s %16s %17s %17s" % ("docs", "route", "fully correct", "wrong somewhere", "no usable answer", "decisions right"))
    per_case = {}
    for docs, route, table, outcome, decisions in cells:
        tally = collections.Counter(outcome(table[c]) for c in cases)
        right = sum(decisions(table[c])[0] for c in cases)
        total = sum(decisions(table[c])[1] for c in cases)
        print("  %-7s %-22s %11d/12 %13d/12 %14d/12 %14d/%d" % (docs, route, tally["fully correct"], tally["wrong somewhere"],
                                                               tally["no usable answer"], right, total))
        for c in cases:
            per_case.setdefault(c, {})[(docs, route)] = outcome(table[c]) == "fully correct"

    print()
    for docs in ("short", "long"):
        p = collections.Counter((per_case[c][(docs, "declaration + engine")], per_case[c][(docs, "direct answer")]) for c in cases)
        print("  %-5s paired by case: declaration only %d, direct only %d, both %d, neither %d"
              % (docs, p[(True, False)], p[(False, True)], p[(True, True)], p[(False, False)]))

    print()
    print("Declarations in detail")
    for docs, table in (("short", short_decl), ("long", long_decl)):
        admitted = [table[c] for c in cases if table[c]["schema_valid"]]
        refused = collections.Counter(table[c]["error"] for c in cases if not table[c]["schema_valid"])
        partial = [r["case_id"] for r in admitted if not r["semantic_correct"]]
        print("  %-5s admitted %d (exact family %d; verdicts right at all three states %d), refused %d %s"
              % (docs, len(admitted), sum(r["semantic_correct"] for r in admitted),
                 sum(r["semantic_admission_event_fidelity"]["exact_all_three"] for r in admitted), sum(refused.values()), dict(refused)))
        for c in partial:
            f = table[c]["family"]
            print("        admitted without the exact family: %s (%d of %d readings, %d spurious)"
                  % (c, f["correct_distinct"], f["expected_distinct"], f["spurious_distinct"]))
        print("        in bare JSON %d/12; frozen bare-JSON endpoint %d/12"
              % (sum(table[c]["strict_bare_json"] for c in cases), sum(table[c]["correct"] is True for c in cases)))

    print()
    print("Direct answers in detail")
    for docs, table in (("short", short_direct), ("long", long_direct)):
        kinds = collections.Counter()
        with_extra = 0
        for c in cases:
            r = table[c]
            if not r["schema_valid"]:
                continue
            mine = collections.Counter()
            for d, want in gold[c]["decisions"].items():
                got = r["parsed"]["decisions"][d]
                if got == want:
                    mine["right"] += 1
                elif got["box_supported"] and not want["box_supported"]:
                    mine["extra"] += 1
                elif want["box_supported"] and not got["box_supported"]:
                    mine["dropped"] += 1
                else:
                    mine["other"] += 1
            ok = ok and mine["right"] == r["correct_decisions"]
            kinds.update(mine)
            with_extra += mine["extra"] > 0
        print("  %-5s parsed %d, in bare JSON %d; wrong decisions: dropped %d, extra %d, other %d; answers with an extra assertion %d"
              % (docs, sum(table[c]["schema_valid"] for c in cases), sum(table[c]["strict_bare_json"] for c in cases),
                 kinds["dropped"], kinds["extra"], kinds["other"], with_extra))

    # 3. Sensitivity only: the frozen wrapper rule accepts a fence when the closing ``` stands on its own
    #    line (retrace/frontier_v6c_io.parse_object). Some refused outputs close the fence on the JSON's
    #    last line. This section asks what those outputs contain. It changes no frozen result.
    import re
    from retrace.frontier_v6h_eval import compile_ir, family_score, _event_fidelity

    outputs = {}
    with open(root + "/results/frontier-v6n/composite/slot-outcomes.jsonl", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            outputs[row["slot_id"]] = row.get("output_text") or ""
    dossiers = {c["case_id"]: c["source_documents"]
                for c in json.load(open(root + "/data/frontier-v6h-dossiers.json", encoding="utf-8"))["cases"]}

    def unwrap(text):
        stripped = text.strip()
        match = re.match(r"^```(?:json)?[ \t]*\r?\n?(.*?)\r?\n?[ \t]*```$", stripped, re.S)
        return match.group(1).strip() if match else stripped

    def closes_on_json_line(text):
        stripped = text.strip()
        lines = stripped.splitlines()
        return stripped.startswith("```") and stripped.endswith("```") and not (lines and lines[-1].strip() == "```")

    def rescore(r, tolerant):
        case = cases_by_id[r["case_id"]]
        documents = dossiers[case["id"]] if r["condition"].startswith("long_") else case["public"]["source_documents"]
        text = outputs[r["slot_id"]]
        try:
            result = compile_ir(unwrap(text) if tolerant else text, documents, case["public"]["registry"])
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
            return None
        score = family_score(result["candidates"], case["evaluation"]["source_family"])
        reference = {s: expected_verdict(case, s) for s in ("initial", "withdrawn", "restored")}
        fidelity = _event_fidelity(result["candidates"], case, reference)
        return {"exact": bool(score["exact_family"] and not result["registry_coverage_gaps"]),
                "all_three": fidelity["exact_all_three"], "withdrawn": fidelity["states"]["withdrawn"]["exact"]}

    print()
    print("Sensitivity only: refused outputs whose closing fence shares a line with the JSON")
    groups = [("primary route, 300 slots", [r for r in primary if r["provider_completed"]]),
              ("matched 12, short declarations", [short_decl[c] for c in cases]),
              ("matched 12, long declarations", [long_decl[c] for c in cases])]
    for label, group in groups:
        for r in group:  # the frozen admission must be reproduced before anything is varied
            ok = ok and (rescore(r, False) is not None) == bool(r["schema_valid"])
        refused = [r for r in group if not r["schema_valid"]]
        glued = [r for r in refused if closes_on_json_line(outputs[r["slot_id"]])]
        rescued = [x for x in (rescore(r, True) for r in refused) if x is not None]
        print("  %-31s refused %2d, of which fence closed on the JSON line %2d; a tolerant unwrap would admit %2d "
              "(exact family %d, verdicts right at all three states %d)"
              % (label, len(refused), len(glued), len(rescued), sum(x["exact"] for x in rescued), sum(x["all_three"] for x in rescued)))

    print()
    print("[%s] internal consistency (paper counts reproduced, reference verdicts agree, per-decision counts agree,"
          " frozen admission reproduced)" % ("PASS" if ok else "FAIL"))
    print("       Python %s" % sys.version.split()[0])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
