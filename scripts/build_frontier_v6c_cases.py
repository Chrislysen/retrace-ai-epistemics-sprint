"""Deterministic authoring of forty-eight source-defined frontier diagnostics.

No model calls, tokenizer estimates, source recognizer, or old compiler edits.
The manual topology recipes and prose realization are inspectable here. Hidden
families are constructed from recipes, never supplied to the extraction arm.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026111408
FAMILIES = (
    "protected_alternatives_nested_dags", "shared_origin_copies", "high_multiplicity",
    "dormant_prerequisite_masking", "unanimous_omission_traps", "partial_multiparent_restoration",
)
LONG_POSITIONS = (0, 3, 4, 7)
PHASES = {
    "hist_init": "initial", "hist_withdrawn": "withdrawn", "hist_restored": "restored",
    "evt_no_commit": "withdrawn", "fresh_withdrawn": "withdrawn", "fresh_restored": "restored",
}

# Four substantive root records per narrative; independent and unavailable
# controls are added separately. These are benign fictional administrative rules.
CONTEXTS = (
    (
        ("Folded-star workshop", "A craft club is arranging a table of folded paper stars for an open afternoon.", ["cutting inventory", "crease check", "table-space check", "colour layout"]),
        ("Miniature canal display", "A model makers' room is preparing a small canal scene for a local exhibition.", ["bridge sketch", "towpath sketch", "lock layout", "label placement"]),
        ("Poetry cabinet", "A reading group is placing short poems in a cabinet with two interchangeable display layouts.", ["poem list", "mounting list", "cabinet spacing", "caption list"]),
        ("Lantern trail", "A park arts group is assembling a decorative lantern trail inside a fenced exhibition area.", ["lantern count", "hanger count", "colour card", "path sketch"]),
        ("Chess-piece gallery", "A games club is cataloguing handmade chess pieces for a small display.", ["piece inventory", "tray index", "board sketch", "caption proof"]),
        ("Seed-packet mosaic", "A garden club is mounting empty seed packets as an illustrated wall mosaic.", ["packet index", "panel drawing", "frame measurements", "colour arrangement"]),
        ("Ceramic handle exhibit", "A pottery class is arranging a teaching exhibit of decorative handles.", ["handle inventory", "shelf sketch", "caption draft", "spacing check"]),
        ("Toy observatory", "A school hobby group is placing a nonfunctional toy observatory on a display bench.", ["dome inventory", "base inventory", "sign layout", "bench sketch"]),
    ),
    (
        ("Marionette register", "A puppetry club maintains a single register and several derived display slips.", ["string inventory", "costume inventory", "stand list", "caption proof"]),
        ("Postcard drawers", "A collector is preparing a drawer guide for a fictional postcard exhibition.", ["drawer tally", "divider tally", "topic list", "drawer plan"]),
        ("Weather-vane models", "A craft fair is displaying miniature weather vanes that are not used as instruments.", ["model tally", "base tally", "finishing list", "table drawing"]),
        ("Button-board catalog", "A sewing circle is documenting decorative button boards for a meeting.", ["button tally", "board tally", "thread list", "caption check"]),
        ("Stage-door labels", "A drama club is preparing temporary labels for a model of a theatre building.", ["door inventory", "letter inventory", "model plan", "label proof"]),
        ("Woven bookmark rack", "A library craft group is displaying woven bookmarks on a wooden rack.", ["bookmark tally", "rack tally", "pattern list", "caption list"]),
        ("Wooden harbour scene", "A workshop is assembling a tabletop harbour from wooden offcuts.", ["boat count", "pier count", "colour plan", "layout sketch"]),
        ("Embossed-paper collection", "A print club is arranging a demonstration of embossed paper patterns.", ["pattern index", "sheet index", "mount list", "cabinet drawing"]),
    ),
    (
        ("Clock-face exhibition", "A design class has incomplete instructions for an exhibit of decorative clock faces.", ["dial check", "number check", "mount check", "caption check"]),
        ("Sound-postcard cabinet", "An archive is organising fictional sound-postcard labels; no audio content is assessed.", ["label index", "sleeve index", "cabinet sketch", "display list"]),
        ("Paper bridge contest", "A hobby club is arranging demonstration paper bridges without load testing.", ["span drawing", "fold drawing", "base drawing", "caption draft"]),
        ("Story-stone display", "A reading circle is displaying painted stones associated with invented stories.", ["stone index", "story index", "tray map", "caption proof"]),
        ("Model tram archive", "A model tram collection has several unresolved choices in its display paperwork.", ["car index", "track sketch", "label check", "cabinet check"]),
        ("Knotted-cord sampler", "A textile class is mounting a sampler of decorative knots.", ["cord list", "knot list", "mount check", "caption plan"]),
        ("Painted-tile route", "An arts workshop is placing painted tiles along an indoor demonstration route.", ["tile index", "pattern index", "route drawing", "caption list"]),
        ("Folded-map cabinet", "A local history club is displaying invented maps made for a storytelling exercise.", ["map index", "fold index", "shelf sketch", "caption proof"]),
    ),
    (
        ("Shadow-puppet cabinet", "A puppetry class is waiting for a withdrawn administrative record before reopening its cabinet paperwork.", ["cabinet release", "figure tally", "screen sketch", "caption proof"]),
        ("Model windmill shelf", "A model-making group has temporarily suspended one source sheet for a decorative windmill shelf.", ["shelf release", "sail count", "base count", "label check"]),
        ("Mosaic alphabet", "A lettering workshop is assembling an alphabet mosaic while one source sheet is excluded.", ["panel release", "letter inventory", "spacing plan", "colour proof"]),
        ("Paper theatre scenes", "A class is sorting paper theatre scenes under a temporarily excluded administrative prerequisite.", ["scene release", "backdrop tally", "prop tally", "caption list"]),
        ("Pressed-leaf artwork", "An arts group is arranging old pressed leaves as artwork, without making biological claims.", ["frame release", "leaf index", "mount index", "caption check"]),
        ("Toy railway signs", "A railway hobby group is preparing toy signs with one source document temporarily withdrawn.", ["sign release", "post tally", "letter tally", "layout plan"]),
        ("Fabric pennant wall", "A textile club is arranging decorative pennants while an administrative source remains excluded.", ["wall release", "pennant tally", "hanger tally", "caption proof"]),
        ("Painted-box catalogue", "A workshop is cataloguing painted boxes after one administrative document was excluded.", ["catalogue release", "box tally", "lid tally", "shelf plan"]),
    ),
    (
        ("Museum-ticket collage", "An art club is assembling a collage from invented museum tickets.", ["ticket inventory", "mounting check", "colour proof", "caption list"]),
        ("Chess-clock prop", "A theatre group is displaying a nonfunctional chess-clock prop.", ["face inventory", "button inventory", "stand check", "label proof"]),
        ("Postage-pattern sampler", "A design club is mounting invented postage patterns as a sampler.", ["pattern index", "border index", "panel check", "caption proof"]),
        ("Lantern-box shelf", "A workshop is arranging decorative lantern boxes on an indoor shelf.", ["box count", "panel count", "shelf sketch", "label list"]),
        ("Archive ribbon display", "A reading room is displaying decorative ribbons in an archive-themed cabinet.", ["ribbon tally", "drawer index", "mount list", "caption proof"]),
        ("Model ferry pier", "A model-making club is cataloguing a small ferry-pier scene.", ["pier tally", "ferry tally", "sign list", "table sketch"]),
        ("Marbled-paper folder", "A print club is arranging marbled-paper samples in a display folder.", ["sheet index", "pattern list", "folder check", "caption proof"]),
        ("Storybook window", "A reading group is arranging a window display for an invented storybook.", ["character list", "scene list", "window plan", "caption check"]),
    ),
    (
        ("Badge-board restoration", "A club is restoring selected paperwork for a decorative badge board after exclusions.", ["badge tally", "board tally", "mount check", "caption proof"]),
        ("Model-garden tray", "A hobby group is restoring only some inputs for a miniature garden tray.", ["tree count", "path count", "bench count", "tray sketch"]),
        ("Paper-mask cabinet", "A theatre class is reinstating selected records for a cabinet of paper masks.", ["mask tally", "strap tally", "shelf plan", "label proof"]),
        ("Stamp-shape mosaic", "An arts club is restoring selected documents for a mosaic of invented stamp shapes.", ["shape index", "colour index", "border check", "caption proof"]),
        ("Toy-book shelf", "A workshop is repairing the paperwork for a shelf of miniature toy books.", ["volume count", "shelf count", "cover list", "spine proof"]),
        ("Decorative spool rack", "A textile club is reinstating some records for a rack of empty decorative spools.", ["spool tally", "rack tally", "thread-colour list", "caption check"]),
        ("Model station clock", "A model railway group is restoring selected records for a nonfunctional station clock.", ["face inventory", "hand inventory", "mount plan", "caption proof"]),
        ("Folded-fan collection", "A craft club is restoring some paperwork for a folded-paper fan collection.", ["fan index", "fold index", "mount check", "caption proof"]),
    ),
)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def fixed_point(graph, excluded=()):
    """Independent synchronous interpretation used only for authored gold."""
    values = {r["id"]: False for k in ("evidence", "claims", "decisions") for r in graph[k]}
    excluded = set(excluded)
    for _ in range(len(values) + 2):
        new = {}
        for row in graph["evidence"]:
            new[row["id"]] = row["active"] and row["id"] not in excluded and (row["kind"] == "root" or all(values[p] for p in row["parents"]))
        for row in graph["claims"]:
            new[row["id"]] = any(all(values[p] for p in route) for route in row["supports"])
        for row in graph["decisions"]:
            new[row["id"]] = all(values[p] for p in row["requires"])
        if new == values:
            return {"all_nodes": new, "decisions": {r["id"]: new[r["id"]] for r in graph["decisions"]}}
        values = new
    raise ValueError("Authored graph failed to converge")


def recipe(family, index):
    """Eight manually distinct compositions per family, sharing only controls."""
    r = {"copies": {}, "claims": {}, "choices": [], "main": "t", "withdraw": ["a", "b", "c"],
         "restore": ["a", "c"], "initial": [], "document_veto": [], "restore_documents": [],
         "groups": [], "mutant": ("conjoin", "t"), "aux": "a"}
    c, p = r["claims"], r["copies"]
    def axis(target, kind, *args):
        r["choices"].append({"target": target, "kind": kind, "args": list(args)})
        if kind in ("independence", "copy_choice"):
            p[target] = []
        else:
            c[target] = []
    if family == 0:
        if index == 0: c.update(x=[["a"], ["b"]], y=[["c", "d"]], t=[["x", "y"]]); r["mutant"] = ("conjoin", "x")
        elif index == 1: c.update(x=[["a", "b"]], y=[["x"], ["c"]], t=[["y", "d"]]); r.update(withdraw=["b", "c", "d"], restore=["b", "d"], aux="d", mutant=("conjoin", "y"))
        elif index == 2: c.update(x=[["a"], ["b"]], y=[["c"], ["d"]], t=[["x", "y"]]); r.update(restore=["b"], aux="b", mutant=("conjoin", "y"))
        elif index == 3: p.update(p=["a"], q=["b"]); c.update(x=[["p", "c"]], y=[["q", "d"]], t=[["x"], ["y"]]); r.update(restore=["b"], aux="b")
        elif index == 4: c.update(x=[["a", "b"]], y=[["b", "c"]], z=[["x"], ["y"]], t=[["z", "d"]]); r.update(withdraw=["b", "d"], restore=["d"], aux="d", mutant=("conjoin", "z"))
        elif index == 5: c.update(x=[["a"], ["b"]], y=[["x", "c"]], z=[["y"], ["d"]], t=[["z", "b"]]); r.update(withdraw=["b", "c"], restore=["c"], aux="c", mutant=("conjoin", "z"))
        elif index == 6: c.update(x=[["a", "c"]], y=[["b"], ["x"]], z=[["y", "d"]], t=[["z"], ["a", "b"]]); r.update(withdraw=["b", "d"], restore=["b"], aux="b")
        else: p.update(p=["a", "b"], q=["c"]); c.update(x=[["p"], ["q"]], t=[["x", "d"]]); r.update(withdraw=["a", "c", "d"], restore=["c", "d"], aux="d", mutant=("conjoin", "x"))
    elif family == 1:
        if index == 0: p.update(p=["a"], q=["a"]); c["t"] = [["p"], ["q"]]; r.update(withdraw=["a", "c"], restore=["a"])
        elif index == 1: p.update(p=["a"], q=["p"]); c["t"] = [["p"], ["q"]]; r.update(withdraw=["p", "c"], restore=["p"], aux="p")
        elif index == 2: p.update(p=["a"], q=["a"], r=["b"]); c.update(x=[["p"], ["q"]], t=[["x", "r"]]); r.update(restore=["a", "b"], aux="b")
        elif index == 3: p.update(p=["a", "b"], q=["a", "c"]); c["t"] = [["p"], ["q"]]; r.update(withdraw=["a", "b"], restore=["a"])
        elif index == 4: p.update(p=["a"], q=["a"], r=["p", "q"]); c["t"] = [["r"]]; r.update(withdraw=["p", "c"], restore=["c"], aux="c")
        elif index == 5: p.update(p=["a", "b"], q=["a", "b"], r=["p"]); c["t"] = [["r"], ["q"]]; r.update(withdraw=["b", "q", "c"], restore=["b"], aux="b")
        elif index == 6: p.update(p=["a"], q=["b"], r=["p", "q"], s=["a"]); c["t"] = [["r"], ["s"]]; r.update(withdraw=["a", "q", "c"], restore=["a"])
        else: p.update(p=["a"], q=["p", "b"], r=["a", "c"]); c.update(x=[["q"], ["r"]], t=[["x", "d"]]); r.update(withdraw=["p", "c", "d"], restore=["c", "d"], aux="d")
        r["mutant"] = ("root", "p")
    elif family == 2:
        if index == 0:
            axis("x", "choice", "a", "b"); axis("y", "gate", "c", "d"); axis("t", "qualifier", "x", "y", "a")
        elif index == 1:
            axis("p", "independence", "a"); axis("x", "gate", "p", "b"); axis("t", "choice", "x", "c")
        elif index == 2:
            axis("x", "gate", "a", "b"); axis("y", "choice", "c", "d"); axis("z", "optional", "x", "y", "safe"); axis("t", "qualifier", "z", "c", "b")
        elif index == 3:
            axis("p", "copy_choice", "a", "b"); axis("x", "choice", "p", "c"); axis("y", "gate", "x", "d"); axis("t", "qualifier", "y", "b", "c")
        elif index == 4:
            axis("x", "qualifier", "a", "b", "c"); axis("y", "optional", "x", "d", "b"); axis("z", "gate", "y", "a"); axis("t", "choice", "z", "c")
        elif index == 5:
            axis("x", "choice", "a", "b"); axis("y", "gate", "x", "c"); axis("z", "qualifier", "y", "d", "b"); axis("w", "optional", "a", "z", "c"); axis("t", "choice", "w", "d")
        elif index == 6:
            axis("x", "gate", "a", "c"); axis("y", "choice", "b", "d"); axis("z", "gate", "x", "y"); axis("w", "qualifier", "z", "a", "b"); axis("t", "optional", "w", "c", "d")
        else:
            axis("p", "independence", "a"); axis("x", "choice", "p", "b"); axis("y", "qualifier", "x", "c", "d"); axis("z", "optional", "y", "a", "b"); axis("t", "gate", "z", "c")
        r.update(mutant=("omit_alternatives", "t"), withdraw=["a", "c", "d"], restore=["a"])
    elif family == 3:
        if index == 0: c.update(x=[["a", "b"]], t=[["x"], ["a", "c"]]); r["mutant"] = ("conjoin", "t")
        elif index == 1: p.update(p=["a", "b"], q=["a", "c"]); c["t"] = [["p"], ["q"]]
        elif index == 2: c.update(x=[["b"], ["c"]], t=[["a", "x", "d"]]); r["mutant"] = ("conjoin", "x")
        elif index == 3: c.update(x=[["b", "c"]], y=[["x"], ["d"]], t=[["a", "y"]]); r["mutant"] = ("conjoin", "y")
        elif index == 4: p.update(p=["b"], q=["c"]); c.update(x=[["p"], ["q"]], t=[["a", "x"]]); r["mutant"] = ("conjoin", "x")
        elif index == 5: c.update(x=[["b"], ["c"]], y=[["a", "d"]], t=[["x", "y"]]); r["mutant"] = ("conjoin", "x")
        elif index == 6: c.update(x=[["a", "b"]], y=[["a", "c"]], z=[["x"], ["y"]], t=[["z", "d"]]); r["mutant"] = ("conjoin", "z")
        else: p.update(p=["a", "b"], q=["p", "c"]); c["t"] = [["q"], ["a", "d"]]
        r.update(initial=["a"], document_veto=["a"], restore_documents=["a"], withdraw=["b"], restore=[], aux="a")
    elif family == 4:
        if index == 0: p.update(p=["a"], q=["a"]); c.update(x=[["p"], ["q"]], t=[["x", "c"]]); r["mutant"] = ("root", "p")
        elif index == 1: c["t"] = [["a", "b"]]; r["mutant"] = ("split", "t")
        elif index == 2: c.update(x=[["a"], ["b"]], t=[["x", "c"]]); r["mutant"] = ("split", "t")
        elif index == 3: p.update(p=["a", "b"], q=["a", "c"]); c["t"] = [["p"], ["q"]]
        elif index == 4: c.update(x=[["a", "b"]], y=[["b", "c"]], t=[["x"], ["y"]]); r["mutant"] = ("flatten", "t")
        elif index == 5: p.update(p=["a"], q=["p"]); c["t"] = [["q"]]
        elif index == 6: c.update(t=[["a"]], second=[["b", "c"]]); r["extra_requirement"] = "second"; r["mutant"] = ("drop_requirement", "decision_main")
        else: axis("x", "choice", "a", "b"); c["t"] = [["x", "c"]]
    else:
        if index == 0: p.update(p=["a", "b"], q=["a", "c"]); c["t"] = [["p"]]; r.update(withdraw=["b"], document_veto=["a"], restore_documents=["a"], restore=[], aux="q")
        elif index == 1: p.update(p=["a", "b"], q=["b", "c"]); c["t"] = [["p", "q"]]; r.update(restore=["a", "c"], aux="c")
        elif index == 2: p.update(p=["a", "b"], q=["p", "c"]); c["t"] = [["q"]]; r.update(withdraw=["a", "b"], restore=["a"])
        elif index == 3: p.update(p=["a", "b"], q=["a", "c"], r=["p", "q"]); c["t"] = [["r"]]; r.update(withdraw=["b", "c"], restore=["b"], aux="p")
        elif index == 4: p.update(p=["a", "b", "c"]); c["t"] = [["p"]]; r.update(groups=[["b", "d"]], document_veto=["b"], withdraw=["c"], restore_documents=["b"], restore=[], aux="d")
        elif index == 5: p.update(p=["a", "b"], q=["a", "b"]); c["t"] = [["p"], ["q"]]; r.update(document_veto=["a"], withdraw=["p"], restore_documents=["a"], restore=[], aux="q")
        elif index == 6: p.update(p=["a", "b"], q=["p", "c"], r=["a", "c"]); c["t"] = [["q"], ["r"]]; r.update(document_veto=["a"], withdraw=["c"], restore=["c"], aux="c")
        else: p.update(p=["a", "b"], q=["b", "c"]); c["t"] = [["p", "q"]]; r.update(document_veto=["a"], withdraw=["a", "b"], restore_documents=["a"], restore=["b"], aux="q")
        r["mutant"] = ("drop_parent", "p")
    c.update(protected=[["t"], ["safe"]], stable=[["safe"]], unavailable=[["dead"]], auxiliary=[[r["aux"]]])
    return r


def option_bodies(axis):
    a = axis["args"]
    kind = axis["kind"]
    if kind == "independence": return [{"kind": "copy", "parents": [a[0]]}, {"kind": "root", "parents": []}]
    if kind == "copy_choice": return [{"kind": "copy", "parents": [a[0]]}, {"kind": "copy", "parents": [a[1]]}]
    if kind == "choice": return [{"supports": [[a[0]]]}, {"supports": [[a[1]]]}]
    if kind == "gate": return [{"supports": [[a[0], a[1]]]}, {"supports": [[a[0]], [a[1]]]}]
    if kind == "qualifier": return [{"supports": [[a[0]], [a[1], a[2]]]}, {"supports": [[a[0], a[2]], [a[1], a[2]]]}]
    if kind == "optional": return [{"supports": [[x] for x in a[:-1]]}, {"supports": [[x] for x in a]}]
    raise ValueError("Unknown authored choice")


def expression(routes):
    if not routes: return {"none": True}
    parts = [{"ref": route[0]} if len(route) == 1 else {"all": [{"ref": x} for x in route]} for route in routes]
    return parts[0] if len(parts) == 1 else {"any": parts}


def build_case(family, index, rng, all_ids):
    spec = recipe(family, index)
    title, introduction, root_labels = CONTEXTS[family][index]
    case_id = f"frontier-v6c-{family+1:02d}-{index+1:02d}"
    def opaque():
        while True:
            value = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
            if value not in all_ids: all_ids.add(value); return value
    evidence_keys = ["a", "b", "c", "d", "safe", "dead"] + list(spec["copies"])
    claim_keys = list(spec["claims"])
    decision_keys = ["decision_main", "decision_protected", "decision_stable", "decision_unavailable", "decision_auxiliary"]
    ids = {key: opaque() for key in evidence_keys + claim_keys + decision_keys}
    labels = dict(zip(("a", "b", "c", "d"), root_labels))
    labels.update(safe="supplementary inspection", dead="legacy annotation")
    for n, key in enumerate(spec["copies"]):
        labels[key] = ["working note", "display slip", "desk digest", "parallel insert"][n]
    for n, key in enumerate(claim_keys): labels[key] = f"{title.lower()} review {n+1}"
    labels.update(decision_main="release the principal display entry", decision_protected="release the companion summary",
                  decision_stable="release the supplementary inspection entry", decision_unavailable="release the legacy entry",
                  decision_auxiliary="release the desk entry")
    graph = {"evidence": [{"id": ids[k], "kind": "copy" if k in spec["copies"] and spec["copies"][k] else "root",
                           "active": k != "dead", "parents": [ids[x] for x in spec["copies"].get(k, [])]} for k in evidence_keys],
             "claims": [{"id": ids[k], "supports": [[ids[x] for x in route] for route in spec["claims"][k]]} for k in claim_keys],
             "decisions": [{"id": ids[k], "requires": [ids[x] for x in ({"decision_main": ["t"] + ([spec["extra_requirement"]] if "extra_requirement" in spec else []),
                             "decision_protected": ["protected"], "decision_stable": ["stable"], "decision_unavailable": ["unavailable"], "decision_auxiliary": ["auxiliary"]}[k])]} for k in decision_keys]}
    axes = []
    for n, axis in enumerate(spec["choices"]):
        bodies = option_bodies(axis)
        mapped = []
        for body in bodies:
            mapped.append({"kind": body["kind"], "parents": [ids[x] for x in body["parents"]]} if "kind" in body
                          else {"supports": [[ids[x] for x in route] for route in body["supports"]]})
        axes.append({"id": f"axis-{n+1}", "target": ids[axis["target"]], "semantic_key": axis["target"], "kind": axis["kind"],
                     "args": [ids[x] for x in axis["args"]], "options": mapped})
    graphs = []
    for bits in itertools.product((False, True), repeat=len(axes)):
        current = copy.deepcopy(graph)
        by_id = {row["id"]: row for category in current for row in current[category]}
        for axis, bit in zip(axes, bits): by_id[axis["target"]].update(copy.deepcopy(axis["options"][int(bit)]))
        for category in current: rng.shuffle(current[category])
        graphs.append({"id": "reading-" + ("".join("1" if bit else "0" for bit in bits) or "fixed"), "graph": current,
                       "assignment": {axis["id"]: "option-1" if bit else "option-0" for axis, bit in zip(axes, bits)}})

    # Per-record documents keep document and passage vetoes distinct. One
    # restoration fixture groups two original records in one physical document.
    groups = [list(group) for group in spec["groups"]]
    grouped = {key for group in groups for key in group}
    groups.extend([[key] for key in evidence_keys if key not in grouped])
    key_document = {}
    def document_id(purpose):
        # Hash the private authoring identity; public IDs contain no case/family.
        return "doc" + hashlib.sha256((case_id + ":" + purpose).encode()).hexdigest()[:18]
    for number, keys in enumerate(groups):
        for key in keys: key_document[key] = document_id(f"source-{number+1}")
    axis_by_key = {axis["semantic_key"]: axis for axis in axes}
    sentences = {}
    def name(key): return f"{labels[key]} ({ids[key]})"
    def joined(keys): return " and ".join(name(key) for key in keys)
    for key in evidence_keys:
        active = "locally eligible at baseline" if key != "dead" else "locally ineligible at baseline"
        start = [f"The {name(key)} is evidence that is {active}.", f"Evidence {ids[key]}, the {labels[key]}, is {active}.",
                 f"For the {labels[key]}, evidence identifier {ids[key]} is {active}.", f"Under identifier {ids[key]}, the {labels[key]} is {active} evidence.",
                 f"At the initial inventory, the {labels[key]} bears evidence ID {ids[key]} and is {active}.",
                 f"The register identifies the {labels[key]} as evidence {ids[key]}; this record is {active}.",
                 f"Evidence item {ids[key]} concerns the {labels[key]}. Its local status is {active}.",
                 f"For evidence {ids[key]} (the {labels[key]}), record the baseline status as {active}."][index]
        if key in axis_by_key:
            axis = next(a for a in spec["choices"] if a["target"] == key)
            if axis["kind"] == "independence":
                body = f"Its production history is unresolved: it could be a copy with {name(axis['args'][0])} as its sole direct parent, or an independent original without parents. Both histories are admitted; no source fact selects one."
            else:
                body = f"It is certainly a copy, but its sole direct parent is unknown: exactly one of {name(axis['args'][0])} and {name(axis['args'][1])} was used. These are alternative histories, not two joint parents and not permission to switch sources by availability."
        elif key in spec["copies"]:
            parents = spec["copies"][key]
            body = [f"It is a copy compiled from {joined(parents)}; these are exactly its direct parents. It adds no observation and requires every listed parent to be usable.",
                    f"The production ledger assigns {joined(parents)} as its complete set of direct inputs. It is a derivative, not a new observation, and all those inputs are jointly required for usability.",
                    f"All its content is reproduced from {joined(parents)}. Those listed records are its direct parents, with no additional inputs; the derivative is usable only when every parent is usable.",
                    f"This derived record combines {joined(parents)} without making a new observation. Each named input is a required direct parent; none may be substituted or omitted.",
                    f"Its direct inputs are {joined(parents)}. Those sources jointly supplied the record, which contains no independent observation. Every one must remain usable for this copy to be usable; there are no other parents.",
                    f"The complete immediate source set is {joined(parents)}. This item merely carries their material forward. It is a copy requiring all of them, rather than an additional observation of the subject.",
                    f"A transcription assembled from {joined(parents)} produced this evidence. The named records are all and only its direct parents, and each is required. Nothing in the transcription supplies a separate observation.",
                    f"This record reproduces material from {joined(parents)}. The reproduction adds no new observation; its complete parent list is the named inputs, all of which are required for it to be usable."][index]
        else:
            body = ["It is an original observation with no parent records.", "The register classifies it as an independent original and lists no parents.",
                    "Its origin is original rather than copied; its parent set is empty.", "It comes from its own observation, not another registered record, and has no parents.",
                    "No other evidence produced this item: it is an original observation with an empty parent list.",
                    "The record arose independently as an original observation. There is no direct source record on which its usability depends.",
                    "This item records a direct observation of its own, not a transcription; its complete set of parents is empty.",
                    "The origin ledger records an independent original here. The item has no evidence parents."][index]
        sentences[key] = start + " " + body
    for key in claim_keys:
        if key in axis_by_key:
            a = next(a for a in spec["choices"] if a["target"] == key); args = a["args"]
            lead = f"Claim {ids[key]} is the {labels[key]}. Its complete support rule has exactly two unresolved readings. "
            if a["kind"] == "choice":
                body = f"A fixed nomination selected either {name(args[0])} alone or {name(args[1])} alone as the sole sufficient warrant. Which was nominated is unstated. This is not a rule allowing whichever one is currently available, and it does not require them jointly."
            elif a["kind"] == "gate":
                body = f"One reading requires {joined(args)} jointly as the only sufficient bundle. The other makes {name(args[0])} alone and {name(args[1])} alone interchangeable sufficient routes. Neither reading has been established over the other."
            elif a["kind"] == "qualifier":
                body = f"The rule names {name(args[0])} or {name(args[1])}, with {name(args[2])} as a qualifier. The qualifier either applies only to the second route, giving the first item alone or the second and qualifier together, or it applies to both routes, requiring the qualifier together with whichever item is used. The scope is not resolved."
            else:
                body = f"The fixed sufficient routes are each of {joined(args[:-1])} alone. The only uncertainty is whether {name(args[-1])} alone is also a sufficient route. One reading includes that additional singleton route and the other does not; the fixed routes remain in both."
            sentences[key] = lead + body
        else:
            routes = spec["claims"][key]
            bundles = [joined(route) for route in routes]
            if not bundles:
                sentences[key] = f"Claim {ids[key]}, the {labels[key]}, has no admitted sufficient route."
            elif len(bundles) == 1:
                lead = [f"The only sufficient warrant for claim {ids[key]}, the {labels[key]}, is ", f"Claim {ids[key]} ({labels[key]}) has one complete support bundle: ",
                        f"To support the {labels[key]}, claim {ids[key]}, the register requires ", f"For claim {ids[key]}, named {labels[key]}, the sole admitted combination is ",
                        f"Claim {ids[key]} concerns the {labels[key]}. Its one sufficient route consists of ",
                        f"The {labels[key]} is claim {ids[key]}; the entire and only warrant is ",
                        f"For the {labels[key]} (claim {ids[key]}), the complete supporting bundle contains ",
                        f"The ledger gives claim {ids[key]}, the {labels[key]}, one route and no others: "][index]
                sentences[key] = lead + bundles[0] + ". This entire bundle is sufficient, each member is required within it, and no other support route is admitted."
            else:
                leads = [f"Claim {ids[key]}, the {labels[key]}, has these complete sufficient bundles: ",
                         f"The {labels[key]} is claim {ids[key]}. The ledger admits the following alternative warrants: ",
                         f"For claim {ids[key]} ({labels[key]}), the complete list of sufficient routes is ",
                         f"There is more than one route to claim {ids[key]}, the {labels[key]}: ",
                         f"The {labels[key]}, registered as claim {ids[key]}, can be supported through these routes: ",
                         f"Claim {ids[key]} names the {labels[key]}. Choose any one of these complete bundles: ",
                         f"These are all the admitted warrants for the {labels[key]}, claim {ids[key]}: ",
                         f"The support ledger for claim {ids[key]} ({labels[key]}) lists the alternatives "]
                sentences[key] = leads[index] + "; alternatively, ".join(bundles) + ". Each entire bundle is sufficient, and every member is required within its bundle. These alternatives are exhaustive; members of different bundles are not all jointly required."
    requirements = {row["id"]: row["requires"] for row in graph["decisions"]}
    reverse_ids = {value: key for key, value in ids.items()}
    for key in decision_keys:
        needed = [reverse_ids[x] for x in requirements[ids[key]]]
        sentences[key] = f"Decision {ids[key]} is to {labels[key]}. Its complete prerequisite set is {joined(needed)}. Every named review is required and there are no other decision prerequisites."

    documents, citations = [], {}
    for keys in groups:
        docid = key_document[keys[0]]
        text = "\n\n".join(sentences[key] for key in keys)
        documents.append({"id": docid, "title": title + " — source record", "text": text})
        for key in keys:
            start = text.index(sentences[key]); citations[ids[key]] = [{"document_id": docid, "start": start, "end": start+len(sentences[key]), "quote": sentences[key]}]
    ledger_keys = claim_keys + decision_keys
    rng.shuffle(ledger_keys)
    ledger = "\n\n".join(sentences[key] for key in ledger_keys)
    ledger_id = document_id("rules")
    documents.append({"id": ledger_id, "title": title + " — warrant ledger", "text": ledger})
    for key in ledger_keys:
        start = ledger.index(sentences[key]); citations[ids[key]] = [{"document_id": ledger_id, "start": start, "end": start+len(sentences[key]), "quote": sentences[key]}]
    frame = introduction + " This fictional register is complete for the evidence, reviews and decisions named here. A record's baseline local eligibility is distinct from later document or passage exclusions. An excluded record cannot be used; clearing one exclusion leaves all other exclusions and original ineligibility in force. Unsupported is not a declaration of falsity. Copies require their own local eligibility and all direct parents; review bundles and decision prerequisites are interpreted only as explicitly stated."
    if len(axes) > 1:
        frame += " The unresolved production and support choices stated in this register are independent: every combination of their two readings is admitted, with no hidden coupling or preferred assignment."
    elif axes:
        frame += " Both readings of the single unresolved choice are admitted; the register does not select an actual reading."
    else:
        frame += " There is no unstated choice of production history or support rule."
    frameid = document_id("context")
    documents.append({"id": frameid, "title": title + " — scope", "text": frame})
    # Scope controls use existing IDs only. Their false historical/proposed/
    # hypothetical edges must not leak into current graphs. A current negative
    # relation is source-grounded and anaphorically bound to the named original.
    note_id = document_id("filing-note")
    antecedent = f"The {name('b')} is the evidence record discussed in this filing note."
    denial = [
        f"That record does not have {name('a')} as a direct parent; the two inventories were made separately.",
        f"For that record, {name('a')} is not a direct parent, even though both names appear on the folder.",
        f"The label on that record does not establish a direct-parent link to {name('a')}; the current register explicitly excludes that link.",
        f"The current note denies that {name('a')} is a direct parent of that record. A matching shelf location does not change this.",
        f"That record has no direct-parent relation to {name('a')}. The quoted suggestion below was not adopted.",
        f"Treat that record as having no direct parent {name('a')}; shared typography is merely a filing convention.",
        f"For clarity, that record does not derive directly from {name('a')}. Their IDs being printed together supplies no such relation.",
        f"The current instruction explicitly rules out {name('a')} as a direct parent of that record; an earlier annotation to the contrary is obsolete.",
    ][index]
    if index in (0, 4, 7):
        aside = f'An archived draft said, "The {name("b")} was copied directly from {name("a")}." That quotation records a discarded draft only; it is not an authoritative description of current provenance.'
        aside_scope, aside_kind, aside_target = "historical", "dependency", ids["b"]
        aside_body = {"relation": "parent", "refs": [ids["a"]]}
    elif index in (1, 5):
        aside = f"In a hypothetical filing exercise, imagine that the {name('dead')} alone sufficed for the {name('t')}. This supposition is not a current support route and does not amend any rule above."
        aside_scope, aside_kind, aside_target = "hypothetical", "dependency", ids["t"]
        aside_body = {"relation": "sufficient_route", "refs": [ids["dead"]]}
    elif index in (2, 6):
        aside = f"A proposed revision would make the {name('b')} a copy whose sole parent was {name('a')}. The revision has not been adopted. The current original-source declarations remain authoritative."
        aside_scope, aside_kind, aside_target = "proposed", "origin", ids["b"]
        aside_body = {"kind": "copy", "parents": [ids["a"]]}
    else:
        aside = f"For a hypothetical rearrangement, suppose decision {ids['decision_main']} required only the {name('stable')}. This is a classroom counterexample, not a change to its listed current prerequisites."
        aside_scope, aside_kind, aside_target = "hypothetical", "requirement", ids["decision_main"]
        aside_body = {"requires": [ids["stable"]]}
    note_text = antecedent + " " + denial + "\n\n" + aside
    def note_citation(text):
        start = note_text.index(text)
        return {"document_id": note_id, "start": start, "end": start + len(text), "quote": text}
    mention = "That record" if "That record" in denial else "that record"
    binding = {"id": "binding-filing-record", "entity": ids["b"], "mention": note_citation(mention), "antecedent": note_citation(antecedent)}
    scope_annotations = [
        {"kind": "dependency", "target": ids["b"], "body": {"relation": "parent", "refs": [ids["a"]]},
         "scope": "current", "polarity": "deny", "citation": note_citation(denial), "bindings": [binding["id"]]},
        {"kind": aside_kind, "target": aside_target, "body": aside_body,
         "scope": aside_scope, "polarity": "assert", "citation": note_citation(aside), "bindings": []},
    ]
    rng.shuffle(documents)
    # Preserve the earlier draft's PRNG stream and node IDs while inserting the
    # new scope note in a deterministic, varied position.
    documents.insert(index % (len(documents) + 1), {"id": note_id, "title": title + " — filing clarification", "text": note_text})
    document_groups = [{"id": key_document[keys[0]], "label": title + " source sheet " + str(n+1), "evidence_ids": [ids[k] for k in keys]} for n, keys in enumerate(groups)]
    def docs_for(keys): return sorted({key_document[k] for k in keys})
    initial_docs = docs_for(spec["initial"])
    withdrawn_docs = sorted(set(initial_docs + docs_for(spec["document_veto"])))
    withdrawn_passages = sorted(ids[k] for k in spec["withdraw"])
    restored_docs = sorted(set(withdrawn_docs) - set(docs_for(spec["restore_documents"])))
    restored_passages = sorted(set(withdrawn_passages) - {ids[k] for k in spec["restore"]})
    states = {"initial": {"revoked_documents": initial_docs, "revoked_passages": []},
              "withdrawn": {"revoked_documents": withdrawn_docs, "revoked_passages": withdrawn_passages},
              "restored": {"revoked_documents": restored_docs, "revoked_passages": restored_passages}}
    def excluded(state):
        return sorted(set(state["revoked_passages"]) | {eid for doc in document_groups if doc["id"] in state["revoked_documents"] for eid in doc["evidence_ids"]})
    state_gold = {}
    for state_name, state in states.items():
        omitted = excluded(state)
        rows = {reading["id"]: fixed_point(reading["graph"], omitted) for reading in graphs}
        consensus = {}
        for did in ids.values():
            if did not in rows[graphs[0]["id"]]["decisions"]: continue
            values = {row["decisions"][did] for row in rows.values()}
            consensus[did] = "supported" if values == {True} else "unsupported" if values == {False} else "disputed"
        state_gold[state_name] = {"excluded_evidence_ids": omitted, "candidate_states": rows, "decision_consensus": consensus}
    # Primary extraction never receives these authored seeds. The separate
    # refutation arm explicitly labels their provenance as constructed inputs.
    # Alternate the parity across families so a shared wording style does not
    # predict the controlled seed label. Long selections remain two of each.
    seed_kind = "deficient" if (index + family) % 2 == 0 else "faithful_complete"
    seed_count = max(2, len(graphs))
    if seed_kind == "faithful_complete":
        seeds = [{"id": f"authored-seed-{n+1:02d}", "graph": copy.deepcopy(graphs[n % len(graphs)]["graph"])} for n in range(seed_count)]
    else:
        mutant = copy.deepcopy(graphs[0]["graph"])
        byid = {row["id"]: row for category in mutant for row in mutant[category]}
        kind, target_key = spec["mutant"]
        row = byid[ids[target_key]]
        if kind == "root": row.update(kind="root", parents=[])
        elif kind == "drop_parent": row["parents"] = row["parents"][:-1]
        elif kind == "conjoin": row["supports"] = [list(dict.fromkeys(x for route in row["supports"] for x in route))]
        elif kind == "split": row["supports"] = [[item] for item in row["supports"][0]]
        elif kind == "flatten": row["supports"] = [[ids[x]] for x in ("a", "b", "c")]
        elif kind == "drop_requirement": row["requires"] = row["requires"][:1]
        elif kind != "omit_alternatives": raise ValueError("Unknown seed mutation")
        seeds = [{"id": f"authored-seed-{n+1:02d}", "graph": copy.deepcopy(mutant)} for n in range(seed_count)]
    registry = {"evidence": [ids[x] for x in evidence_keys], "claims": [ids[x] for x in claim_keys], "decisions": [ids[x] for x in decision_keys]}
    for value in registry.values(): rng.shuffle(value)
    # A source-cited IR is evaluation-only and can independently test the new
    # compiler against the hand-authored Boolean families, including u=5.
    ir = {"schema": "retrace.source-ir.v6c", "entities": [], "bindings": [binding], "choices": [],
          "combination": {"mode": "cartesian", "assignments": [], "citations": [{"document_id": frameid, "quote": frame}] if axes else []}, "propositions": []}
    for category, singular in (("evidence", "evidence"), ("claims", "claim"), ("decisions", "decision")):
        for row in graph[category]: ir["entities"].append({"id": row["id"], "type": singular, "operational": True, "citations": citations[row["id"]]})
    def proposition(kind, target, body, when=None):
        ir["propositions"].append({"id": f"p{len(ir['propositions'])+1}", "kind": kind, "target": target, "body": body,
                                   "scope": "current", "polarity": "assert", "when": when or {}, "citations": citations[target], "bindings": []})
    axis_targets = {axis["target"] for axis in axes}
    for row in graph["evidence"]:
        proposition("eligibility", row["id"], {"active": row["active"]})
        if row["id"] not in axis_targets: proposition("origin", row["id"], {"kind": row["kind"], "parents": row["parents"]})
    for row in graph["claims"]:
        if row["id"] not in axis_targets: proposition("support", row["id"], {"expr": expression(row["supports"])})
    for row in graph["decisions"]: proposition("requirement", row["id"], {"requires": row["requires"]})
    for axis in axes:
        ir["choices"].append({"id": axis["id"], "options": ["option-0", "option-1"], "citations": citations[axis["target"]]})
        for number, body in enumerate(axis["options"]):
            proposition("origin" if "kind" in body else "support", axis["target"], body if "kind" in body else {"expr": expression(body["supports"])}, {axis["id"]: f"option-{number}"})
    for annotation in scope_annotations:
        ir["propositions"].append({"id": f"p{len(ir['propositions'])+1}", "kind": annotation["kind"], "target": annotation["target"],
                                   "body": annotation["body"], "scope": annotation["scope"], "polarity": annotation["polarity"],
                                   "when": {}, "citations": [annotation["citation"]], "bindings": annotation["bindings"]})
    phases = {phase: {"state_name": name, "state": states[name]} for phase, name in PHASES.items()}
    events = {"states": states, "document_groups": document_groups,
              "withdrawal": {"add_document_vetoes": sorted(set(withdrawn_docs)-set(initial_docs)), "add_passage_vetoes": withdrawn_passages},
              "restoration": {"clear_document_vetoes": docs_for(spec["restore_documents"]), "clear_passage_vetoes": sorted(ids[k] for k in spec["restore"])},
              "semantics": "Each state lists all currently active vetoes. A record is usable only if its original active flag is true, every applicable document/passage veto is off, and all parents are usable. Restoration clears only named vetoes and never changes original local activity."}
    return {"id": case_id, "family": FAMILIES[family], "within_family_index": index+1, "title": title,
            "public": {"source_documents": documents, "registry": registry}, "events": events, "phases": phases,
            "authored_seed_pool": {"provenance": "Constructed diagnostic candidates, not observed model outputs or independent votes.", "candidates": seeds},
            "long_context_selected": index in LONG_POSITIONS,
            "evaluation": {"fictional": True, "source_family": graphs, "choice_axes": axes, "uncertainty_count": len(axes),
                           "reference_ir": ir, "grounded_citations": citations, "state_gold": state_gold,
                           "source_scope_annotations": scope_annotations,
                           "seed_kind": seed_kind, "seed_defect_recipe": list(spec["mutant"]) if seed_kind == "deficient" else None,
                           "source_recipe": spec, "semantic_key_ids": ids,
                           "no_single_actual_assignment_asserted": bool(axes),
                           "phase_semantics": "Unanimous support is conditional on all authored source interpretations; no hidden branch is selected as actual.",
                           "restoration_remaining_vetoes": states["restored"],
                           "max_evidence_ids": len(evidence_keys), "max_originals_in_any_candidate": max(sum(r["kind"] == "root" for r in g["graph"]["evidence"]) for g in graphs)}}


def build_corpus():
    rng, ids = random.Random(SEED), set()
    cases = [build_case(family, index, rng, ids) for family in range(6) for index in range(8)]
    return {"schema": "retrace.frontier-v6c-staged.v1", "construction_seed": SEED, "status": "staged_pending_independent_source_and_ir_audit",
            "family_order": list(FAMILIES), "cases_per_family": 8, "base_case_count": 48,
            "long_context_subset_ids": [case["id"] for case in cases if case["long_context_selected"]],
            "long_context_measurement": {"owner": "separate dossier builder", "target_reference_tokens": 16384,
                                         "reference_encoding": "cl100k_base", "measured_here": False,
                                         "provider_token_counts": None, "word_counts_are_not_token_counts": True},
            "phase_names": list(PHASES), "cases": cases,
            "scope": ["Controlled synthetic prose with manually varied finite topology recipes, not a natural-language population sample; family structures, prose styles and derived variants are dependent design units.",
                      "Main extraction and commitment inputs receive only public source documents, typed registry and the appropriate event state, never evaluation fields or authored seeds.",
                      "Authored seed pools are separate controlled-refutation inputs: four deficient and four faithful complete pools per family, identified only evaluation-side.",
                      "Five binary choices produce all thirty-two assignment branches. No pruning by current support, branch deduplication or unverified actual interpretation.",
                      "Long dossiers require separately measured reference token counts; provider input usage must be recorded independently."]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    corpus = build_corpus()
    text = json.dumps(corpus, ensure_ascii=False, indent=2) + "\n"
    path = ROOT / "data/frontier-v6c-staged.json"
    if args.check_only:
        if path.read_text(encoding="utf-8") != text: raise ValueError("Staged frontier corpus differs from the deterministic authoring source")
    else:
        with path.open("x", encoding="utf-8") as handle: handle.write(text)
    print(json.dumps({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "cases": len(corpus["cases"]),
                      "long_subset": len(corpus["long_context_subset_ids"]), "maximum_evidence": max(c["evaluation"]["max_evidence_ids"] for c in corpus["cases"]),
                      "family_candidates": sum(len(c["evaluation"]["source_family"]) for c in corpus["cases"])}, indent=2))


if __name__ == "__main__":
    main()
