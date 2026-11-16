"""Source-IR mechanics, with independent truth-table and scope controls."""
from copy import deepcopy
import itertools
import json
import unittest

from retrace.source_ir_v6c import SourceIRError, compile_source_ir, audit_source_ir


TEXT = ("E1 is an original. E2 is an original. E3 is a copy of E1. "
        "C1 accepts E3 alone or E2 alone. C2 accepts E1 alone. D1 requires C1. "
        "All evidence is locally eligible. These are current rules.")
DOCS = [{"id": "source", "text": TEXT}]


def cite(text=TEXT):
    return {"document_id": "source", "quote": text}


def prop(ident, kind, target, body, **extra):
    return {"id": ident, "kind": kind, "target": target, "body": body,
            "scope": "current", "polarity": "assert", "when": {}, "citations": [cite()], "bindings": [], **extra}


def fixture():
    data = {"schema": "retrace.source-ir.v6c", "entities": [], "bindings": [], "choices": [],
            "combination": {"mode": "cartesian", "assignments": [], "citations": []}, "propositions": []}
    for ident, kind in (("E1","evidence"),("E2","evidence"),("E3","evidence"),("C1","claim"),("C2","claim"),("D1","decision")):
        data["entities"].append({"id": ident, "type": kind, "operational": True, "citations": [cite()]})
    for ident in ("E1", "E2", "E3"):
        data["propositions"].append(prop("active_"+ident, "eligibility", ident, {"active": True}))
        data["propositions"].append(prop("origin_"+ident, "origin", ident, {"kind": "copy" if ident == "E3" else "root", "parents": ["E1"] if ident == "E3" else []}))
    data["propositions"] += [prop("support_C1", "support", "C1", {"expr": {"any": [{"ref":"E3"}, {"ref":"E2"}]}}),
                             prop("support_C2", "support", "C2", {"expr": {"ref":"E1"}}),
                             prop("requires_D1", "requirement", "D1", {"requires":["C1"]})]
    return data


def definition(data, ident):
    return next(row for row in data["propositions"] if row["id"] == ident)


def choice_fixture(count):
    text = "R is an eligible original. C is the review. D requires C. "
    text += " ".join(f"X{i} is eligible and may independently be an original or a copy of R." for i in range(count))
    text += " All choices combine independently. C accepts any X record alone."
    docs = [{"id": "source", "text": text}]
    data = {"schema":"retrace.source-ir.v6c", "entities": [], "bindings":[], "choices":[],
            "combination":{"mode":"cartesian", "assignments":[], "citations":[cite(text)] if count > 1 else []}, "propositions":[]}
    for ident, typ in [("R","evidence"),("C","claim"),("D","decision")]+[(f"X{i}","evidence")for i in range(count)]:
        data["entities"].append({"id":ident,"type":typ,"operational":True,"citations":[cite(text)]})
    def add(pid, kind, target, body, when=None):
        data["propositions"].append(prop(pid,kind,target,body,when=when or {},citations=[cite(text)]))
    add("aR","eligibility","R",{"active":True}); add("oR","origin","R",{"kind":"root","parents":[]})
    for i in range(count):
        ident, axis = f"X{i}", f"u{i}"
        data["choices"].append({"id":axis,"options":["copy","original"],"citations":[cite(text)]})
        add("a"+ident,"eligibility",ident,{"active":True})
        add("copy"+ident,"origin",ident,{"kind":"copy","parents":["R"]},{axis:"copy"})
        add("original"+ident,"origin",ident,{"kind":"root","parents":[]},{axis:"original"})
    expr = {"ref":"X0"} if count == 1 else {"any":[{"ref":f"X{i}"}for i in range(count)]}
    add("support","support","C",{"expr":expr}); add("requirement","requirement","D",{"requires":["C"]})
    return data, docs


class SourceIRV6cTests(unittest.TestCase):
    def test_necessary_is_not_vacuous_through_an_impossible_conjunction(self):
        data=fixture()
        definition(data,"support_C2")["body"]={"expr":{"none":True}}
        definition(data,"support_C1")["body"]={"expr":{"all":[{"ref":"C2"},{"ref":"E1"}]}}
        data["propositions"].append(prop("needed","dependency","C1",{"relation":"necessary","refs":["E1"]}))
        with self.assertRaisesRegex(SourceIRError,"constraint_conflict"):
            compile_source_ir(data,DOCS)
        definition(data,"needed")["polarity"]="deny"
        compile_source_ir(data,DOCS)

    def test_necessary_ignores_impossible_disjunction_branch(self):
        data=fixture()
        definition(data,"support_C2")["body"]={"expr":{"none":True}}
        definition(data,"support_C1")["body"]={"expr":{"any":[{"ref":"C2"},{"ref":"E1"}]}}
        data["propositions"].append(prop("needed","dependency","C1",{"relation":"necessary","refs":["E1"]}))
        compile_source_ir(data,DOCS)
        definition(data,"needed")["body"]["refs"]=["C2"]
        with self.assertRaisesRegex(SourceIRError,"constraint_conflict"):
            compile_source_ir(data,DOCS)

    def test_covered_family_with_an_extra_world_is_not_a_clean_match(self):
        data=fixture()
        candidates=compile_source_ir(data,DOCS)["candidates"]
        extra=deepcopy(candidates[0]);extra["id"]="extra"
        extra["graph"]["evidence"][0]["active"]=False
        audit=audit_source_ir(data,DOCS,candidates+[extra])
        self.assertEqual(audit["gaps"],[])
        self.assertEqual(audit["missing_worlds"],[])
        self.assertEqual(audit["status"],"unlicensed_by_declared_contract")
        self.assertEqual(audit["extra_supplied_worlds"],[{"candidate_id":"extra","matching_world_ids":[],"status":"unlicensed_by_declared_contract"}])

    def test_registry_disposition_does_not_assume_current_source_truth(self):
        data=fixture()
        registry={"evidence":["E1","E2","E3","OLD9"],"claims":["C1","C2"],"decisions":["D1"]}
        result=compile_source_ir(data,DOCS,registry)
        self.assertEqual(next(x for x in result["registry_disposition"]if x["id"]=="OLD9")["status"],"absent_from_ir")
        self.assertEqual(result["status"],"compiled")

    def test_complete_graph_original_flags_and_no_input_mutation(self):
        data = fixture(); definition(data,"active_E1")["body"]["active"] = False
        before = deepcopy((data,DOCS))
        result = compile_source_ir(data,DOCS)
        self.assertEqual(result["status"],"compiled")
        self.assertEqual(result["candidate_count"],1)
        e1 = next(n for n in result["candidates"][0]["graph"]["evidence"] if n["id"]=="E1")
        self.assertFalse(e1["active"])
        self.assertEqual((data,DOCS),before)

    def test_two_sufficient_assertions_stay_two_routes(self):
        data = fixture()
        result = compile_source_ir(data,DOCS)
        c1 = next(n for n in result["candidates"][0]["graph"]["claims"] if n["id"]=="C1")
        self.assertEqual(c1["supports"],[["E2"],["E3"]])
        definition(data,"support_C1")["body"]={"expr":{"all":[{"ref":"E2"},{"ref":"E3"}]}}
        changed = compile_source_ir(data,DOCS)["candidates"][0]["graph"]
        self.assertEqual(next(n for n in changed["claims"] if n["id"]=="C1")["supports"],[["E2","E3"]])

    def test_shared_qualifier_survives_distribution(self):
        data=fixture()
        definition(data,"support_C1")["body"]={"expr":{"all":[{"any":[{"ref":"E2"},{"ref":"E3"}]},{"ref":"E1"}]}}
        graph=compile_source_ir(data,DOCS)["candidates"][0]["graph"]
        self.assertEqual(next(n for n in graph["claims"]if n["id"]=="C1")["supports"],[["E1","E2"],["E1","E3"]])

    def test_dnf_against_independent_truth_tables_no_absorption(self):
        expressions=[{"all":[{"any":[{"ref":"E1"},{"ref":"E2"}]},{"any":[{"ref":"E1"},{"ref":"E3"}]}]},
                     {"any":[{"none":True},{"all":[{"ref":"E1"},{"ref":"E2"}]}]},
                     {"all":[{"none":True},{"ref":"E1"}]}]
        def direct(expr,truth):
            if "ref"in expr:return truth[expr["ref"]]
            if "none"in expr:return False
            if "all"in expr:return all(direct(x,truth)for x in expr["all"])
            return any(direct(x,truth)for x in expr["any"])
        for expression in expressions:
            data=fixture();definition(data,"support_C1")["body"]={"expr":expression}
            graph=compile_source_ir(data,DOCS)["candidates"][0]["graph"]
            routes=next(n for n in graph["claims"]if n["id"]=="C1")["supports"]
            for bits in itertools.product((False,True),repeat=3):
                truth=dict(zip(("E1","E2","E3"),bits))
                self.assertEqual(direct(expression,truth),any(all(truth[x]for x in route)for route in routes))
            if expression is expressions[0]:self.assertEqual(len(routes),4)

    def test_five_independent_choices_retain_all_32_assignments(self):
        data,docs=choice_fixture(5)
        result=compile_source_ir(data,docs)
        self.assertEqual(result["assignment_count"],32)
        self.assertEqual(result["candidate_count"],32)
        self.assertEqual(len({json.dumps(c["graph"],sort_keys=True)for c in result["candidates"]}),32)
        audit=audit_source_ir(data,docs,result["candidates"])
        self.assertEqual(audit["status"],"represented_declared_contract")

    def test_graph_equivalent_branches_not_deduplicated(self):
        data,docs=choice_fixture(1)
        definition(data,"copyX0")["body"]={"kind":"root","parents":[]}
        result=compile_source_ir(data,docs)
        self.assertEqual(result["candidate_count"],2)
        self.assertEqual(result["candidates"][0]["graph"],result["candidates"][1]["graph"])

    def test_coupled_assignment_list_is_explicit_and_unpruned(self):
        data,docs=choice_fixture(2)
        data["combination"]={"mode":"listed","assignments":[{"u0":"copy","u1":"copy"},{"u0":"original","u1":"original"}],"citations":[cite(docs[0]["text"])]}
        self.assertEqual(compile_source_ir(data,docs)["candidate_count"],2)
        data["combination"]["assignments"].append(deepcopy(data["combination"]["assignments"][0]))
        with self.assertRaises(SourceIRError):compile_source_ir(data,docs)

    def test_one_bad_branch_rejects_whole_family(self):
        data,docs=choice_fixture(2)
        definition(data,"copyX0")["body"]={"kind":"copy","parents":["X1"]}
        definition(data,"copyX1")["body"]={"kind":"copy","parents":["X0"]}
        with self.assertRaisesRegex(SourceIRError,"cycle"):compile_source_ir(data,docs)

    def test_scoped_negation_does_not_erase_positive_rule(self):
        data=fixture()
        data["propositions"].append(prop("not_E2","dependency","E3",{"relation":"parent","refs":["E2"]},polarity="deny"))
        result=compile_source_ir(data,DOCS)
        self.assertEqual(result["worlds"][0]["constraint_checks"],[{"proposition_id":"not_E2","status":"verified"}])
        self.assertEqual(next(n for n in result["candidates"][0]["graph"]["evidence"]if n["id"]=="E3")["parents"],["E1"])

    def test_denial_negates_one_group_not_each_operand(self):
        data=fixture()
        data["propositions"].append(prop("not_both","dependency","E3",{"relation":"parent","refs":["E1","E2"]},polarity="deny"))
        compile_source_ir(data,DOCS)
        data["propositions"].append(prop("not_E1","dependency","E3",{"relation":"parent","refs":["E1"]},polarity="deny"))
        with self.assertRaisesRegex(SourceIRError,"constraint_conflict"):compile_source_ir(data,DOCS)

    def test_historical_hypothetical_and_proposed_rules_are_not_current_definitions(self):
        for scope in ("historical","hypothetical","proposed"):
            data=fixture()
            data["propositions"].append(prop("other_origin","origin","E3",{"kind":"root","parents":[]},scope=scope))
            result=compile_source_ir(data,DOCS)
            self.assertEqual(next(n for n in result["candidates"][0]["graph"]["evidence"]if n["id"]=="E3")["kind"],"copy")
            audit=audit_source_ir(data,DOCS,result["candidates"])
            self.assertEqual(next(o for o in audit["obligations"]if o["proposition_id"]=="other_origin")["status"],"excluded_by_scope")

    def test_nonoperational_historical_entity_not_inserted(self):
        docs=deepcopy(DOCS);docs[0]["text"] += " OLD9 names a historical example."
        data=fixture();data["entities"].append({"id":"OLD9","type":"evidence","operational":False,"citations":[cite("OLD9 names a historical example.")]})
        data["propositions"].append(prop("old_origin","origin","OLD9",{"kind":"root","parents":[]},scope="historical",citations=[cite("OLD9 names a historical example.")]))
        data["propositions"].append(prop("not_old","dependency","E3",{"relation":"parent","refs":["OLD9"]},polarity="deny"))
        result=compile_source_ir(data,docs)
        self.assertNotIn("OLD9",[n["id"]for n in result["candidates"][0]["graph"]["evidence"]])

    def test_explicit_binding_links_cited_mention_and_antecedent(self):
        docs=deepcopy(DOCS);docs[0]["text"] += " The digest needs the first record."
        data=fixture()
        data["bindings"]=[{"id":"digest","entity":"E3","mention":cite("The digest"),"antecedent":cite("E3 is a copy of E1.")}]
        data["propositions"].append(prop("bound_parent","dependency","E3",{"relation":"parent","refs":["E1"]},bindings=["digest"],citations=[cite("The digest needs the first record.")]))
        result=compile_source_ir(data,docs)
        self.assertEqual(result["bindings"][0]["mention"]["quote"],"The digest")
        data["propositions"][-1]["citations"]=[cite("E1 is an original.")]
        with self.assertRaisesRegex(SourceIRError,"binding_citation"):compile_source_ir(data,docs)

    def test_unknown_ancestor_never_becomes_root_or_partial_family(self):
        data=fixture();data["propositions"]=[p for p in data["propositions"]if p["id"]!="origin_E3"]
        data["propositions"].append(prop("unknown","unknown_ancestry","E3",{"description":"unidentified desk tally"}))
        result=compile_source_ir(data,DOCS)
        self.assertEqual(result["status"],"unresolved_structure")
        self.assertEqual(result["candidates"],[])
        self.assertIsNone(result["worlds"][0]["graph"])
        supplied=compile_source_ir(fixture(),DOCS)["candidates"]
        self.assertEqual(audit_source_ir(data,DOCS,supplied)["status"],"unresolved")

    def test_unknown_in_one_assignment_withholds_all_executable_candidates(self):
        data,docs=choice_fixture(1)
        data["propositions"]=[p for p in data["propositions"]if p["id"]!="copyX0"]
        data["propositions"].append(prop("unknown","unknown_ancestry","X0",{"description":"unidentified ancestor"},when={"u0":"copy"},citations=[cite(docs[0]["text"])]))
        result=compile_source_ir(data,docs)
        self.assertEqual(result["assignment_count"],2)
        self.assertEqual({w["status"]for w in result["worlds"]},{"complete","unresolved_ancestry"})
        self.assertEqual(result["candidates"],[])

    def test_unknown_does_not_hide_unrelated_known_contradiction(self):
        data=fixture();data["propositions"]=[p for p in data["propositions"]if p["id"]!="origin_E3"]
        data["propositions"].append(prop("unknown","unknown_ancestry","E3",{"description":"unidentified ancestor"}))
        data["propositions"].append(prop("false_parent","dependency","E1",{"relation":"parent","refs":["E2"]}))
        with self.assertRaisesRegex(SourceIRError,"constraint_conflict"):compile_source_ir(data,DOCS)

    def test_proposition_union_does_not_imply_whole_world_coverage(self):
        data=fixture();proper=compile_source_ir(data,DOCS)["candidates"][0]["graph"]
        left,right=deepcopy(proper),deepcopy(proper)
        next(n for n in left["claims"]if n["id"]=="C1")["supports"]=[["E1"]]
        next(n for n in right["claims"]if n["id"]=="C2")["supports"]=[["E2"]]
        audit=audit_source_ir(data,DOCS,[{"id":"left","graph":left},{"id":"right","graph":right}])
        self.assertEqual(audit["gaps"],[])
        self.assertEqual(len(audit["missing_worlds"]),1)
        self.assertEqual(audit["status"],"gap_and_unlicensed_worlds")

    def test_missing_source_node_reported_without_reference_graph(self):
        data=fixture();proper=compile_source_ir(data,DOCS)["candidates"][0]["graph"]
        # C2 is not required by the current decision, so this remains a valid DAG.
        proper["claims"]=[n for n in proper["claims"]if n["id"]!="C2"]
        audit=audit_source_ir(data,DOCS,[{"id":"omitted","graph":proper}])
        self.assertTrue(any(g["target"]=="C2"for g in audit["gaps"]))
        self.assertEqual(audit["source_completeness"],"unknown")
        self.assertFalse(audit["reference_graph_used"])

    def test_source_identifier_can_be_absent_from_supplied_registry(self):
        data=fixture()
        registry={"evidence":["E1","E2","E3"],"claims":["C1"],"decisions":["D1"]}
        result=compile_source_ir(data,DOCS,registry)
        self.assertIn("C2",[n["id"]for n in result["candidates"][0]["graph"]["claims"]])

    def test_clause_explosion_rejected_instead_of_truncated(self):
        text=" ".join(f"N{i} is an eligible original."for i in range(18))+" C is the claim. D is the decision."
        data={"schema":"retrace.source-ir.v6c","entities":[],"bindings":[],"choices":[],
              "combination":{"mode":"cartesian","assignments":[],"citations":[]},"propositions":[]}
        for i in range(18):
            ident=f"N{i}"
            data["entities"].append({"id":ident,"type":"evidence","operational":True,"citations":[cite(text)]})
            data["propositions"] += [prop("a"+ident,"eligibility",ident,{"active":True},citations=[cite(text)]),
                                     prop("o"+ident,"origin",ident,{"kind":"root","parents":[]},citations=[cite(text)])]
        for ident,typ in (("C","claim"),("D","decision")):
            data["entities"].append({"id":ident,"type":typ,"operational":True,"citations":[cite(text)]})
        expression={"all":[{"any":[{"ref":f"N{2*i}"},{"ref":f"N{2*i+1}"}]}for i in range(9)]}
        data["propositions"] += [prop("sc","support","C",{"expr":expression},citations=[cite(text)]),
                                 prop("rd","requirement","D",{"requires":["C"]},citations=[cite(text)])]
        with self.assertRaisesRegex(SourceIRError,"clause_bound"):compile_source_ir(data,[{"id":"source","text":text}])

    def test_deep_or_cyclic_python_payload_has_controlled_validation_error(self):
        data=fixture();data["self"]=data
        with self.assertRaises(SourceIRError):compile_source_ir(data,DOCS)

    def test_exact_quotes_are_not_semantic_entailment(self):
        data=fixture()
        # Citation is genuine but does not justify the deliberately wrong root.
        definition(data,"origin_E3")["body"]={"kind":"root","parents":[]}
        result=compile_source_ir(data,DOCS)
        self.assertEqual(result["status"],"compiled")
        self.assertTrue(any("semantic entailment"in s for s in result["scope"]))

    def test_repeated_quote_requires_offsets_unicode_offsets_are_codepoints(self):
        docs=deepcopy(DOCS);docs[0]["text"]="🧭 "+TEXT+" E1 is an original."
        data=fixture();data["entities"][0]["citations"]=[cite("E1 is an original.")]
        with self.assertRaisesRegex(SourceIRError,"citation_ambiguous"):compile_source_ir(data,docs)
        data["entities"][0]["citations"]=[{"document_id":"source","quote":"E1 is an original.","start":2,"end":20}]
        result=compile_source_ir(data,docs)
        self.assertEqual(result["entities"][0]["citations"][0]["start"],2)
        data["entities"][0]["citations"][0]["start"]=3
        with self.assertRaisesRegex(SourceIRError,"citation_slice"):compile_source_ir(data,docs)

    def test_strict_json_duplicatekeys_nonfinite_and_no_fence_repair(self):
        raw=json.dumps(fixture())
        for text in ('{"schema":"x",'+raw[1:], raw.replace('true','NaN',1), '```json\n'+raw+'\n```'):
            with self.assertRaises(ValueError):compile_source_ir(text,DOCS)
        self.assertEqual(compile_source_ir(raw,DOCS)["status"],"compiled")

    def test_duplicate_definitions_invalid_types_and_missing_fields(self):
        variants=[]
        data=fixture(); duplicate=deepcopy(data["propositions"][0]);duplicate["id"]="duplicate";data["propositions"].append(duplicate);variants.append(data)
        data=fixture();definition(data,"active_E1")["body"]["active"]=1;variants.append(data)
        data=fixture();data["entities"][0]["type"]=[];variants.append(data)
        data=fixture();data["propositions"][0]["bindings"]=[[]];variants.append(data)
        data=fixture();data["propositions"][0].pop("scope");variants.append(data)
        data=fixture();data["propositions"][0]["scope"]=[];variants.append(data)
        for data in variants:
            with self.assertRaises(ValueError):compile_source_ir(data,DOCS)

    def test_bounds_and_no_silent_choice_truncation(self):
        data,docs=choice_fixture(6)
        with self.assertRaisesRegex(SourceIRError,"choices"):compile_source_ir(data,docs)
        data=fixture();expr={"ref":"E1"}
        for _ in range(18):expr={"any":[expr,{"ref":"E2"}]}
        definition(data,"support_C1")["body"]={"expr":expr}
        with self.assertRaisesRegex(SourceIRError,"expression_bound"):compile_source_ir(data,DOCS)
        with self.assertRaisesRegex(SourceIRError,"source_limit"):compile_source_ir(fixture(),[{"id":"source","text":"x"*524289}])


if __name__ == "__main__":
    unittest.main()
