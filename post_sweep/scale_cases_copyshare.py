#!/usr/bin/env python3
"""Cases for part E4 of the extension (prereg/scale_extension_addendum_1.md): 40 records, two shares of copies.
No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026.

    python post_sweep/scale_cases_copyshare.py

The main run's 40-record cases have 40 percent copies. This script generates twelve cases with no copies and twelve with
80 percent copies, otherwise as in post_sweep/scale_cases.py: same sizes (40 records, 20 claims, 10 decisions, 3 records
withdrawn), same acceptance filter, same prose templates, same reference engine and independent check. build_graph below
is that script's function with the share of copies as a parameter; nothing else in it is changed. The main run's files
are not touched.

Output, under post_sweep/out/scale/ext/: corpus_copyshare.json, sessions_copyshare.json (three first-day conditions),
sessions_copyshare_working.json (the visible-working instruction of part E2), cases_copyshare_summary.json
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

import scale_cases as base  # noqa: E402
from recompute_prose24 import supported  # noqa: E402
from scale_ext_sessions import derive  # noqa: E402

SEED = 2026111602
PER_SHARE = 12
SHARES = {"C0": 0.0, "C8": 0.8}
SIZE = "L"


def build_graph(rng, size, share):
    """scale_cases.build_graph with `share` in place of the constant 0.4."""
    spec = base.SIZES[size]
    used = set()
    n = spec["records"]
    n_copy = round(share * n)
    kinds = ["root"] * (n - n_copy) + ["copy"] * n_copy
    head = max(2, (n - n_copy) // 2)
    order = kinds[:head] + rng.sample(kinds[head:], len(kinds) - head)
    places = rng.sample(base.PLACES, len(base.PLACES))
    labels = set()
    evidence = []
    inactive_budget = max(1, round(0.1 * n))
    for position, kind in enumerate(order):
        ident = base.new_id(rng, used)
        while True:
            label = f"{rng.choice(places)} {rng.choice(base.COPY_KINDS if kind == 'copy' else base.ROOT_KINDS)}"
            if label not in labels:
                labels.add(label)
                break
        if kind == "root":
            active = True
            if inactive_budget and position >= head and rng.random() < 0.3:
                active, inactive_budget = False, inactive_budget - 1
            evidence.append({"id": ident, "label": label, "kind": "root", "parents": [], "active": active})
        else:
            pool = [row["id"] for row in evidence]
            copies = [row["id"] for row in evidence if row["kind"] == "copy"]
            count = 2 if (len(pool) >= 2 and rng.random() < 0.3) else 1
            parents = []
            while len(parents) < count:
                source = copies if (copies and rng.random() < 0.35) else pool
                pick = rng.choice(source)
                if pick not in parents:
                    parents.append(pick)
            evidence.append({"id": ident, "label": label, "kind": "copy", "parents": parents, "active": True})
    if all(row["active"] for row in evidence):
        rng.choice([row for row in evidence if row["kind"] == "root"])["active"] = False
    topics = rng.sample(base.TOPICS, spec["claims"])
    claims = []
    record_ids = [row["id"] for row in evidence]
    for topic in topics:
        ident = base.new_id(rng, used)
        routes = []
        for _ in range(rng.choices((1, 2, 3), weights=(40, 45, 15))[0]):
            for _attempt in range(20):
                width = rng.choices((1, 2, 3), weights=(35, 50, 15))[0]
                route = []
                while len(route) < width:
                    earlier = [c["id"] for c in claims]
                    pick = rng.choice(earlier) if (earlier and rng.random() < 0.2) else rng.choice(record_ids)
                    if pick not in route:
                        route.append(pick)
                if sorted(route) not in [sorted(r) for r in routes]:
                    routes.append(route)
                    break
        claims.append({"id": ident, "label": f"{topic} review", "supports": routes})
    actions = rng.sample(base.ACTIONS, spec["decisions"])
    decisions = []
    claim_ids = [c["id"] for c in claims]
    for action in actions:
        count = min(len(claim_ids), rng.choices((1, 2, 3), weights=(45, 45, 10))[0])
        decisions.append({"id": base.new_id(rng, used), "label": action, "requires": rng.sample(claim_ids, count)})
    usable_now = [row["id"] for row in evidence if row["active"]]
    revoke = sorted(rng.sample(usable_now, spec["revoke"]))
    return {"evidence": evidence, "claims": claims, "decisions": decisions, "revoke": revoke}


def copies_as_records(case):
    flat = {name: [dict(row) for row in case[name]] for name in ("evidence", "claims", "decisions")}
    for row in flat["evidence"]:
        row["kind"], row["parents"] = "root", []
    return flat


def main():
    master = random.Random(SEED)
    corpus, tries = [], {}
    for tag, share in SHARES.items():
        for number in range(1, PER_SHARE + 1):
            domain = base.DOMAINS[number - 1]
            for attempt in range(1, 20001):
                rng = random.Random(master.getrandbits(64))
                case = build_graph(rng, SIZE, share)
                ident = f"scale-{tag}-{number:02d}"
                item = {"id": ident, "family": f"copyshare_{tag}", "title": f"{domain}: review packet {tag}-{number}",
                        "case": case, "domain": domain}
                try:
                    keep = base.interesting(item, SIZE)
                except ValueError:
                    keep = False
                if keep:
                    break
            else:
                raise SystemExit(f"no acceptable case for {ident}")
            tries[ident] = attempt
            used = {row["id"] for kind in ("evidence", "claims", "decisions") for row in case[kind]}
            item["documents"], item["event_text"] = base.prose(rng, case, domain, used)
            item["decision_questions"] = [{"id": d["id"], "text": f"Is the decision to {d['label']} currently supported under this packet?"}
                                          for d in case["decisions"]]
            words = sum(len(doc["text"].split()) for doc in item["documents"])
            item["review_notes"] = {"synthetic": True, "design_seed": SEED, "size": SIZE, "copy_share": share, "set": tag,
                                    "prose_word_count": words,
                                    "limitations": "Fictional generated prose from sentence templates; not natural documents."}
            corpus.append(item)

    summary = {"seed": SEED, "cases": len(corpus), "by_set": {}, "generation_attempts": tries, "evaluator_disagreements": 0,
               "prose_structure_problems": []}
    for item in corpus:
        gold, mine = base.gold_for(item), base.independent_reference(item)
        if gold["initial"] != mine["initial"] or gold["final"] != mine["final"] or gold["lost"] != mine["lost"] \
                or gold["protected"] != mine["protected"]:
            summary["evaluator_disagreements"] += 1
        text = " ".join(doc["text"] for doc in item["documents"])
        for row in item["case"]["evidence"]:
            if text.count(f"Record {row['id']}") != 1:
                summary["prose_structure_problems"].append([item["id"], row["id"]])
        for row in item["case"]["claims"]:
            if text.count(f"laim {row['id']}") + text.count(f"identifier {row['id']}") < 1:
                summary["prose_structure_problems"].append([item["id"], row["id"]])
        for row in item["case"]["decisions"]:
            if text.count(f"ecision {row['id']}") != 1:
                summary["prose_structure_problems"].append([item["id"], row["id"]])
        case = item["case"]
        after, flat_after = supported(case, case["revoke"]), supported(copies_as_records(case), case["revoke"])
        s = summary["by_set"].setdefault(item["review_notes"]["set"], {
            "cases": 0, "copy_share": item["review_notes"]["copy_share"], "words": [], "copies": 0, "decisions": 0,
            "supported_after": 0, "lost": 0, "protected": 0, "never_supported": 0,
            "unsupported_copy_mediated": 0, "unsupported_direct": 0})
        s["cases"] += 1
        s["words"].append(item["review_notes"]["prose_word_count"])
        s["copies"] += sum(row["kind"] == "copy" for row in case["evidence"])
        s["decisions"] += len(gold["final"])
        s["supported_after"] += sum(gold["final"].values())
        s["lost"] += len(gold["lost"])
        s["protected"] += len(gold["protected"])
        s["never_supported"] += len(gold["initially_unsupported"])
        s["unsupported_copy_mediated"] += sum((not after[d]) and flat_after[d] for d in after)
        s["unsupported_direct"] += sum((not after[d]) and not flat_after[d] for d in after)
    for s in summary["by_set"].values():
        s["words_min_max"] = [min(s["words"]), max(s["words"])]
        del s["words"]
    if summary["evaluator_disagreements"] or summary["prose_structure_problems"]:
        print(json.dumps(summary, indent=1))
        raise SystemExit("case set rejected")

    sessions = [s for s in base.make_prose_sessions(corpus) if s["condition"] in base.KEEP_CONDITIONS]
    manifest = {"instructions": base.DECISION_INSTRUCTIONS, "sessions": sessions}
    text, working, _ = derive(manifest)
    out = ROOT / "post_sweep" / "out" / "scale" / "ext"
    out.mkdir(parents=True, exist_ok=True)
    texts = {"corpus_copyshare.json": json.dumps(corpus, indent=1, ensure_ascii=False) + "\n",
             "sessions_copyshare.json": json.dumps(manifest, ensure_ascii=False) + "\n",
             "sessions_copyshare_working.json": json.dumps({"instructions": text, "sessions": working}, ensure_ascii=False) + "\n"}
    for name, body in texts.items():
        (out / name).write_text(body, encoding="utf-8", newline="\n")
        summary[name + "_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    summary["sessions"] = len(sessions)
    summary["working_sessions"] = len(working)
    (out / "cases_copyshare_summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
