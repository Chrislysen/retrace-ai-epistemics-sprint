#!/usr/bin/env python3
"""Generate the cases of the scaling run (prereg/scale_rules.md) and their sessions. No model call.

Sprint addition, written with AI assistance on Monday 16 November 2026.

    python post_sweep/scale_cases.py

Cases are in the schema of data/prose-holdout.json. The prose is composed from sentence templates copied from the
first-day packets. Reference decisions come from the first-day engine (retrace/core.py, through prose_eval.gold_for)
and must agree with the independent evaluator of post_sweep/recompute_prose24.py on every case.
Sessions come from the project's own retrace/prose_sessions.make_prose_sessions, unchanged; three of its five
conditions are kept.

Output: post_sweep/out/scale/corpus.json, post_sweep/out/scale/sessions.json, post_sweep/out/scale/cases_summary.json
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "post_sweep"))

from recompute_prose24 import reference as independent_reference  # noqa: E402
from retrace.prose_eval import gold_for  # noqa: E402
from retrace.prose_sessions import DECISION_INSTRUCTIONS, make_prose_sessions  # noqa: E402

SEED = 20261116
PER_SIZE = 12
SIZES = {"S": {"records": 10, "claims": 5, "decisions": 6, "revoke": 1, "min_lost": 1},
         "M": {"records": 20, "claims": 10, "decisions": 8, "revoke": 2, "min_lost": 2},
         "L": {"records": 40, "claims": 20, "decisions": 10, "revoke": 3, "min_lost": 2}}
KEEP_CONDITIONS = ("formal_fresh", "prose_fresh", "prose_extract")
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

DOMAINS = ["Harbour survey", "Orchard irrigation", "Archive digitisation", "Glasshouse trial", "Tramway signalling",
           "Reservoir monitoring", "Kiln commissioning", "Bindery restoration", "Observatory retrofit", "Apiary relocation",
           "Canal dredging", "Printworks audit"]
PLACES = ["north quay", "south quay", "east bank", "west bank", "upper yard", "lower yard", "main hall", "side annex",
          "old store", "new store", "pump house", "gate lodge", "long shed", "corner bay", "central floor", "outer ring",
          "first terrace", "second terrace", "rear lane", "front court", "mill race", "signal cabin", "drying loft", "cold room"]
ROOT_KINDS = ["bench note", "inspection sheet", "field log", "calibration slip", "survey card", "sample tally",
              "meter reading", "site sketch", "checklist return", "duty-roster extract"]
COPY_KINDS = ["digest", "excerpt", "summary sheet", "circulating copy", "planning extract"]
TOPICS = ["main works", "reserve works", "access route", "shared setup", "night shift", "materials", "drainage", "signage",
          "staffing", "storage", "handover", "safety margin", "public notice", "equipment", "weather window",
          "east section", "west section", "pilot phase", "second phase", "contingency", "budget line", "permit",
          "survey scope", "closing"]
ACTIONS = ["approve the main pilot", "approve the paired session", "approve the reserve work", "approve the expanded session",
           "retain the route plan", "approve the narrow trial", "approve the night schedule", "open the second phase",
           "retain the storage plan", "issue the public notice", "confirm the handover date", "adopt the contingency plan"]
SCOPE = ("This fictional {domain} packet defines a closed review. Evidence records and claims have separate identifiers; "
         "a decision identifier labels an action whose support is being assessed, not an instruction to carry it out. "
         "A locally unavailable record cannot be used. A copy also requires all its listed parents and contributes no new "
         "observation. Use only the exhaustive routes in this packet. Missing support does not establish falsity. Apply any "
         "later eligibility notice to the named record versions only. In the criteria, an evidence item is usable under the "
         "record rules; a claim used as an item is usable exactly when that claim is supported.")


def listing(ids):
    return ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]


def route_text(route):
    return f"item {route[0]} is usable" if len(route) == 1 else f"items {listing(route)} are all usable together"


def claims_text(ids):
    return f"claim {ids[0]} is supported" if len(ids) == 1 else f"claims {listing(ids)} are all supported"


def new_id(rng, used):
    while True:
        ident = "".join(rng.choice(ALPHABET) for _ in range(6))
        if ident not in used and any(ch.isalpha() for ch in ident):
            used.add(ident)
            return ident


def build_graph(rng, size):
    spec = SIZES[size]
    used = set()
    n = spec["records"]
    n_copy = round(0.4 * n)
    kinds = ["root"] * (n - n_copy) + ["copy"] * n_copy
    # roots first for the first third, then mixed, so that copies of copies occur
    head = max(2, (n - n_copy) // 2)
    order = kinds[:head] + rng.sample(kinds[head:], len(kinds) - head)
    places = rng.sample(PLACES, len(PLACES))
    labels = set()
    evidence = []
    inactive_budget = max(1, round(0.1 * n))
    for position, kind in enumerate(order):
        ident = new_id(rng, used)
        while True:
            label = f"{rng.choice(places)} {rng.choice(COPY_KINDS if kind == 'copy' else ROOT_KINDS)}"
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
    if all(row["active"] for row in evidence):   # at least one record unavailable from the start
        rng.choice([row for row in evidence if row["kind"] == "root"])["active"] = False
    topics = rng.sample(TOPICS, spec["claims"])
    claims = []
    record_ids = [row["id"] for row in evidence]
    for topic in topics:
        ident = new_id(rng, used)
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
    actions = rng.sample(ACTIONS, spec["decisions"])
    decisions = []
    claim_ids = [c["id"] for c in claims]
    for action in actions:
        count = min(len(claim_ids), rng.choices((1, 2, 3), weights=(45, 45, 10))[0])
        decisions.append({"id": new_id(rng, used), "label": action, "requires": rng.sample(claim_ids, count)})
    usable_now = [row["id"] for row in evidence if row["active"]]
    revoke = sorted(rng.sample(usable_now, spec["revoke"]))
    return {"evidence": evidence, "claims": claims, "decisions": decisions, "revoke": revoke}


def interesting(item, size):
    gold = gold_for(item)
    final = gold["final"]
    return (sum(final.values()) >= 2 and sum(not v for v in final.values()) >= 2 and len(gold["lost"]) >= SIZES[size]["min_lost"]
            and len(gold["protected"]) >= 1 and len(gold["initially_unsupported"]) >= 1)


def prose(rng, case, domain, used):
    register = ["This register describes initial local availability before any later eligibility notice."]
    rows = []
    for row in case["evidence"]:
        if row["kind"] == "copy":
            word = "record" if len(row["parents"]) == 1 else "records"
            rows.append(f"Record {row['id']}, the {row['label']}, is locally available at the start but is a copy drawn only "
                        f"from {word} {listing(row['parents'])}; every named parent is required for its use.")
        elif row["active"]:
            rows.append(f"Record {row['id']} is the {row['label']}; it is an original observation record, available from the start.")
        else:
            rows.append(f"Record {row['id']} is the {row['label']}; it is an original observation record, not available at the "
                        "start and never released by this packet.")
    rng.shuffle(rows)
    criteria = []
    for claim in case["claims"]:
        routes = [route_text(route) for route in claim["supports"]]
        if len(routes) == 1:
            criteria.append(rng.choice([
                f"For claim {claim['id']}, \"{claim['label']}\", the listed warrant is complete: it is supported if and only if "
                f"{routes[0]}. No other route is authorised.",
                f"The dossier defines claim {claim['id']} as \"{claim['label']}\". Its complete eligibility rule is this: support "
                f"requires and is supplied by the condition that {routes[0]}. Treat the listed routes as exhaustive.",
                f"The review heading \"{claim['label']}\" has identifier {claim['id']}. It may be retained on the following "
                f"exhaustive basis: support requires and is supplied by the condition that {routes[0]}."]))
        else:
            text = (f"Claim {claim['id']} records \"{claim['label']}\". Under the agreed review policy, one complete route is "
                    f"enough, namely {routes[0]}; a separate complete route is that {routes[1]}")
            if len(routes) == 3:
                text += f"; a further complete route is that {routes[2]}"
            criteria.append(text + ". These are the only sufficient routes.")
    rng.shuffle(criteria)
    checklist = []
    for decision in case["decisions"]:
        needs = claims_text(decision["requires"])
        checklist.append(rng.choice([
            f"Decision {decision['id']}, \"{decision['label']}\", is supported exactly when {needs}. There are no additional "
            "prerequisites.",
            f"To support decision {decision['id']} (\"{decision['label']}\"), the complete requirement is that {needs}; "
            "satisfying that requirement is also sufficient."]))
    rng.shuffle(checklist)
    documents = [
        {"id": "doc-" + new_id(rng, used), "title": "Review scope memorandum", "text": SCOPE.format(domain=domain.lower())},
        {"id": "doc-" + new_id(rng, used), "title": f"{domain} source register", "text": " ".join(register + rows)},
        {"id": "doc-" + new_id(rng, used), "title": "Review criteria memorandum", "text": " ".join(criteria)},
        {"id": "doc-" + new_id(rng, used), "title": "Authorisation checklist", "text": " ".join(checklist)}]
    rng.shuffle(documents)
    labels = {row["id"]: row["label"] for row in case["evidence"]}
    named = [f"{ident}, the {labels[ident]}" for ident in case["revoke"]]
    if len(named) == 1:
        event = (f"The registrar withdraws evidence record {named[0]}. This update applies to that exact record, not to the "
                 f"entire {domain.lower()} project or to other observations.")
    else:
        event = (f"The registrar withdraws evidence records {'; '.join(named[:-1])}; and {named[-1]}. This update applies to "
                 f"those exact records, not to the entire {domain.lower()} project or to other observations.")
    event += (" No other local availability flag or review rule changes. The notice removes a warrant; it does not assert "
              "that any described physical result is false.")
    return documents, event


def main():
    master = random.Random(SEED)
    corpus, tries = [], {}
    for size in SIZES:
        for number in range(1, PER_SIZE + 1):
            domain = DOMAINS[number - 1]
            for attempt in range(1, 4001):
                rng = random.Random(master.getrandbits(64))
                case = build_graph(rng, size)
                ident = f"scale-{size}-{number:02d}"
                item = {"id": ident, "family": f"size_{size}", "title": f"{domain}: review packet {size}{number}", "case": case,
                        "domain": domain}
                try:
                    keep = interesting(item, size)
                except ValueError:
                    keep = False
                if keep:
                    break
            else:
                raise SystemExit(f"no acceptable case for {ident}")
            tries[ident] = attempt
            used = {row["id"] for kind in ("evidence", "claims", "decisions") for row in case[kind]}
            item["documents"], item["event_text"] = prose(rng, case, domain, used)
            item["decision_questions"] = [{"id": d["id"], "text": f"Is the decision to {d['label']} currently supported under this packet?"}
                                          for d in case["decisions"]]
            words = sum(len(doc["text"].split()) for doc in item["documents"])
            item["review_notes"] = {"synthetic": True, "design_seed": SEED, "size": size, "prose_word_count": words,
                                    "limitations": "Fictional generated prose from sentence templates; not natural documents."}
            corpus.append(item)

    # checks: two evaluators agree; every node is named in its defining sentence exactly once
    summary = {"seed": SEED, "cases": len(corpus), "by_size": {}, "generation_attempts": tries, "evaluator_disagreements": 0,
               "prose_structure_problems": []}
    for item in corpus:
        gold, mine = gold_for(item), independent_reference(item)
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
        size = item["review_notes"]["size"]
        s = summary["by_size"].setdefault(size, {"cases": 0, "words": [], "copies": 0, "two_parent_copies": 0, "copy_of_copy": 0,
                                                 "claims_using_a_claim": 0, "decisions": 0, "supported_after": 0, "lost": 0,
                                                 "protected": 0, "never_supported": 0})
        kinds = {row["id"]: row["kind"] for row in item["case"]["evidence"]}
        claim_ids = {row["id"] for row in item["case"]["claims"]}
        s["cases"] += 1
        s["words"].append(item["review_notes"]["prose_word_count"])
        s["copies"] += sum(k == "copy" for k in kinds.values())
        s["two_parent_copies"] += sum(len(row["parents"]) == 2 for row in item["case"]["evidence"])
        s["copy_of_copy"] += sum(any(kinds[p] == "copy" for p in row["parents"]) for row in item["case"]["evidence"])
        s["claims_using_a_claim"] += sum(any(ref in claim_ids for route in row["supports"] for ref in route)
                                         for row in item["case"]["claims"])
        s["decisions"] += len(gold["final"])
        s["supported_after"] += sum(gold["final"].values())
        s["lost"] += len(gold["lost"])
        s["protected"] += len(gold["protected"])
        s["never_supported"] += len(gold["initially_unsupported"])
    for s in summary["by_size"].values():
        s["words_min_max"] = [min(s["words"]), max(s["words"])]
        del s["words"]
    if summary["evaluator_disagreements"] or summary["prose_structure_problems"]:
        print(json.dumps(summary, indent=1))
        raise SystemExit("case set rejected")

    sessions = [s for s in make_prose_sessions(corpus) if s["condition"] in KEEP_CONDITIONS]
    out = ROOT / "post_sweep" / "out" / "scale"
    out.mkdir(parents=True, exist_ok=True)
    texts = {"corpus.json": json.dumps(corpus, indent=1, ensure_ascii=False) + "\n",
             "sessions.json": json.dumps({"instructions": DECISION_INSTRUCTIONS, "sessions": sessions}, ensure_ascii=False) + "\n"}
    for name, text in texts.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
        summary[name + "_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    summary["sessions"] = len(sessions)
    summary["requests_per_model"] = sum(len(s["steps"]) for s in sessions)
    summary["longest_prompt_chars"] = max(len(s["steps"][0]["input"]) for s in sessions)
    (out / "cases_summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
