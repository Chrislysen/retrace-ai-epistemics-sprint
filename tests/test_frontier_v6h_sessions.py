"""Independent offline checks of the prospective v6h input/condition design."""
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import build_frontier_v6h_sessions as sessions
from retrace.adaption_v6h import PRIMARY_MODELS, build_body, validate_slots
from retrace.dossier_v6d import dossier_body
from retrace.source_ir_v6d import model_source
from retrace.source_ir_v6h import compile_ir
from retrace.prompts_v6h import (IR_INSTRUCTIONS, NL_INSTRUCTIONS, PROJECTION_INSTRUCTIONS,
    VERDICT_INSTRUCTIONS, EXAMPLE_DOCUMENTS, EXAMPLE_REGISTRY, example_ir)

ROOT=Path(__file__).resolve().parents[1]
ORDINARY={"commitment","sample_graph","strict_source_ir","nl_source","nl_projection",
          "long_commitment","long_source_ir","diagnostic_commitment","sfr_probe","sfr_backtranslation"}


class SessionProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=json.loads((ROOT/"data/frontier-v6h-corpus.json").read_text(encoding="utf-8"))
        cls.dossiers=json.loads((ROOT/"data/frontier-v6h-dossiers.json").read_text(encoding="utf-8"))
        cls.slots=sessions.build(cls.corpus,cls.dossiers)
        cls.by_id={s["slot_id"]:s for s in cls.slots}
        cls.cases={c["id"]:c for c in cls.corpus["cases"]}
        cls.groups=defaultdict(list)
        for slot in cls.slots:cls.groups[(slot["model"],slot["case_id"])].append(slot)

    def slot(self,cid,suffix,model=PRIMARY_MODELS[0]):
        return self.by_id[f"v6h::{model}::{cid}::{suffix}"]

    def test_exact_full_schedule_counts_and_prespecified_diagnostic(self):
        expected={"commitment":1800,"sample_graph":3000,"strict_source_ir":300,
                  "nl_source":300,"nl_projection":300,"oracle_ir_consumption":300,
                  "symbolic_assistance":300,"adversarial_refuter":300,"long_commitment":120,
                  "long_source_ir":120,"sfr_probe":600,"sfr_backtranslation":600,"diagnostic_commitment":108}
        self.assertEqual(len(self.slots),8148)
        self.assertEqual(len(self.by_id),8148)
        self.assertEqual(Counter(s["condition"] for s in self.slots),Counter(expected))
        self.assertEqual(Counter(s["model"] for s in self.slots),Counter({**{m:1608 for m in PRIMARY_MODELS},"qwen3.5-397b":108}))
        diagnostic={s["case_id"] for s in self.slots if s["condition"]=="diagnostic_commitment"}
        target={c["id"] for c in self.corpus["cases"] if c["partition"]=="synthetic" and c["within_family_index"] in (1,4,8)}
        self.assertEqual(diagnostic,target)
        self.assertEqual(Counter(self.cases[c]["family_id"] for c in diagnostic),Counter({f"F{i}":3 for i in range(1,7)}))

    def test_scheduled_dependencies_are_earlier_and_same_model_case(self):
        seen={}
        for slot in self.slots:
            dependencies=slot.get("history_from",[])+([slot["input_from"]["slot_id"]] if "input_from" in slot else [])
            for dep in dependencies:
                self.assertIn(dep,seen)
                self.assertEqual((seen[dep]["model"],seen[dep]["case_id"]),(slot["model"],slot["case_id"]))
            seen[slot["slot_id"]]=slot

    def test_six_phases_share_authoritative_state_and_only_history_has_dependencies(self):
        for (model,cid),group in self.groups.items():
            commitment={s["phase"]:s for s in group if s["condition"] in ("commitment","diagnostic_commitment")}
            self.assertEqual(set(commitment),set(sessions.PHASES))
            case=self.cases[cid]
            for phase,slot in commitment.items():
                payload=json.loads(slot["input"])
                self.assertEqual(payload["current_exclusions"],case["phases"][phase]["state"])
                self.assertEqual(payload["document_groups"],case["events"]["document_groups"])
                self.assertEqual(payload["requested_decisions"],case["public"]["registry"]["decisions"])
                expected={"hist_withdrawn":["hist_init"],"hist_restored":["hist_init","hist_withdrawn"]}.get(phase,[])
                self.assertEqual(slot.get("history_from",[]),[self.slot(cid,p,model)["slot_id"] for p in expected])
                self.assertEqual("source_documents" in payload,phase not in ("hist_withdrawn","hist_restored"))
            self.assertEqual(json.loads(commitment["evt_no_commit"]["input"])["initial_exclusions"],case["events"]["states"]["initial"])
            for key in ("current_exclusions","document_groups","requested_decisions"):
                self.assertEqual(json.loads(commitment["hist_withdrawn"]["input"])[key],json.loads(commitment["fresh_withdrawn"]["input"])[key])
                self.assertEqual(json.loads(commitment["hist_restored"]["input"])[key],json.loads(commitment["fresh_restored"]["input"])[key])

    def test_history_body_replays_actual_prior_inputs_and_raw_answers_only(self):
        cid=next(iter(self.cases));initial=self.slot(cid,"hist_init");withdrawn=self.slot(cid,"hist_withdrawn");restored=self.slot(cid,"hist_restored")
        completed={initial["slot_id"]:{"actual_input":"ACTUAL INITIAL INPUT","output_text":"ACTUAL ANSWER α, even if wrong"},
                   withdrawn["slot_id"]:{"actual_input":"ACTUAL WITHDRAWAL INPUT","output_text":"ACTUAL WITHDRAWAL ANSWER"}}
        body=build_body(restored,completed)
        self.assertEqual(body["input"],[{"role":"user","content":"ACTUAL INITIAL INPUT"},{"role":"assistant","content":"ACTUAL ANSWER α, even if wrong"},
                                          {"role":"user","content":"ACTUAL WITHDRAWAL INPUT"},{"role":"assistant","content":"ACTUAL WITHDRAWAL ANSWER"},
                                          {"role":"user","content":restored["input"]}])
        self.assertNotIn("evaluation",body)
        self.assertNotIn("metadata",body)
        self.assertFalse(body["store"]);self.assertFalse(body["agentic_memory"])
        self.assertIsNone(body["previous_response_id"]);self.assertEqual(body["tools"],[])

    def test_nl_projection_receives_only_the_actual_nl_output(self):
        for cid in self.cases:
            slot=self.slot(cid,"projection");prior=self.slot(cid,"nl")
            self.assertEqual(slot["input"],"")
            self.assertEqual(slot["input_from"],{"slot_id":prior["slot_id"],"mode":"assistant_output_only"})
            body=build_body(slot,{prior["slot_id"]:{"actual_input":"ORIGINAL SOURCE MUST NOT REAPPEAR","output_text":"Actual incomplete account with span-token s123."}})
            self.assertEqual(body["input"],[{"role":"user","content":"Actual incomplete account with span-token s123."}])
            self.assertNotIn("ORIGINAL SOURCE MUST NOT REAPPEAR",json.dumps(body))
            self.assertEqual(body["instructions"],PROJECTION_INSTRUCTIONS)
            self.assertNotIn("history_from",slot)

    def test_nl_and_strict_ir_start_from_exactly_the_same_segmented_source(self):
        for cid,case in self.cases.items():
            expected=model_source(case["public"]["source_documents"],case["public"]["registry"])
            self.assertEqual(json.loads(self.slot(cid,"strict-ir")["input"]),expected)
            self.assertEqual(json.loads(self.slot(cid,"nl")["input"]),expected)
            self.assertEqual(self.slot(cid,"strict-ir")["instructions"],IR_INSTRUCTIONS)
            self.assertEqual(self.slot(cid,"nl")["instructions"],NL_INSTRUCTIONS)

    def test_ten_samples_are_independent_identical_input_draws(self):
        for cid in self.cases:
            rows=[self.slot(cid,f"sample-{i:02}") for i in range(1,11)]
            self.assertEqual(len({(r["input"],r["instructions"],r["temperature"],r["max_output_tokens"]) for r in rows}),1)
            for row in rows:
                self.assertNotIn("history_from",row);self.assertNotIn("input_from",row)
                self.assertEqual(row["max_output_tokens"],16384)

    def test_hidden_markers_only_reach_explicit_oracle_or_refuter_conditions(self):
        corpus=deepcopy(self.corpus)
        for case in corpus["cases"]:
            case["evaluation"]["reference_ir"]["hidden_audit_marker"]="HIDDEN_ORACLE_MARKER"
            case["evaluation"]["state_gold"]="HIDDEN_OUTCOME_MARKER"
            case["evaluation"]["seed_kind"]="HIDDEN_SEED_KIND_MARKER"
            for row in case["evaluation"]["source_family"]:row["hidden_metadata"]="HIDDEN_FAMILY_MARKER"
            for row in case["authored_seed_pool"]["candidates"]:row["hidden_metadata"]="SUPPLIED_SEED_MARKER"
        mutated=sessions.build(corpus,self.dossiers)
        for original,slot in zip(self.slots,mutated):
            self.assertEqual(original["slot_id"],slot["slot_id"])
            if slot["condition"] in ORDINARY:self.assertEqual(original,slot)
            self.assertNotIn("HIDDEN_OUTCOME_MARKER",slot["input"])
            self.assertNotIn("HIDDEN_SEED_KIND_MARKER",slot["input"])
            self.assertNotIn("HIDDEN_FAMILY_MARKER",slot["input"])
            self.assertEqual("HIDDEN_ORACLE_MARKER" in slot["input"],slot["condition"] in ("oracle_ir_consumption","symbolic_assistance"))
            self.assertEqual("SUPPLIED_SEED_MARKER" in slot["input"],slot["condition"]=="adversarial_refuter")

    def test_oracle_and_assisted_share_declaration_but_only_assisted_gets_exact_verdict(self):
        for cid,case in self.cases.items():
            oracle=json.loads(self.slot(cid,"oracle-consume")["input"])
            assisted=json.loads(self.slot(cid,"assisted-consume")["input"])
            self.assertEqual(oracle["declared_source_ir"],case["evaluation"]["reference_ir"])
            for key,value in oracle.items():self.assertEqual(assisted[key],value)
            self.assertNotIn("deterministic_declared_support",oracle)
            self.assertEqual(assisted["deterministic_declared_support"],case["evaluation"]["state_gold"]["withdrawn"]["verdict"])

    def test_sfr_pair_changes_only_reviewer_preference_with_fixed_gloss_mapping(self):
        first_preferences=[]
        for cid,case in sorted(self.cases.items()):
            a=json.loads(self.slot(cid,"sfr-a")["input"]);b=json.loads(self.slot(cid,"sfr-b")["input"])
            self.assertEqual({k for k in a if a[k]!=b[k]},{"reviewer_preference"})
            self.assertEqual(set(a),set(b))
            self.assertEqual(self.slot(cid,"sfr-a")["instructions"],self.slot(cid,"sfr-b")["instructions"])
            _,_,glosses,tokens=sessions.sfr_packet(case)
            self.assertEqual(a["glosses"],glosses)
            self.assertEqual(b["glosses"],glosses)
            prefer_true=f"to be {tokens[True]};" in a["reviewer_preference"]
            first_preferences.append(prefer_true)
            self.assertEqual(f"to be {tokens[False]};" in a["reviewer_preference"],not prefer_true)
            self.assertEqual(f"to be {tokens[True]};" in b["reviewer_preference"],not prefer_true)
            self.assertIn("within this packet",a["question"])
            self.assertNotIn("independent original",a["question"])
        self.assertEqual(Counter(first_preferences),Counter({True:30,False:30}))

    def test_sfr_source_predicate_is_invariant_across_all_allowed_worlds(self):
        for case in self.cases.values():
            entity,gold,glosses,tokens=sessions.sfr_packet(case)
            expected=[]
            for world in case["evaluation"]["source_family"]:
                row=next(r for r in world["graph"]["evidence"] if r["id"]==entity)
                expected.append(row["kind"]=="root" and row["parents"]==[])
            self.assertEqual(set(expected),{gold})
            self.assertEqual(set(tokens.values()),{"dax","wug"})
            self.assertEqual({g["token"] for g in glosses},set(tokens.values()))

    def test_sfr_seed_is_deterministic_and_config_override_reaches_every_probe(self):
        case=next(iter(self.cases.values()))
        self.assertEqual(sessions.sfr_packet(case,777),sessions.sfr_packet(case,777))
        self.assertGreater(len({json.dumps(sessions.sfr_packet(case,s)[2],sort_keys=True) for s in range(20)}),1)
        config={**sessions.CONFIG,"sfr_order_seed":777}
        original=sessions.sfr_packet
        with patch.object(sessions,"sfr_packet",wraps=original) as spy:
            slots=sessions.build(self.corpus,self.dossiers,config)
        self.assertEqual(spy.call_count,300)
        self.assertTrue(all(call.args[1]==777 for call in spy.call_args_list))
        expected=original(case,777)[2]
        probe=next(r for r in slots if r["case_id"]==case["id"] and r["condition"]=="sfr_probe")
        self.assertEqual(json.loads(probe["input"])["glosses"],expected)

    def test_backtranslation_is_stateless_blind_gloss_plus_exact_probe_response(self):
        for cid in self.cases:
            for arm in ("a","b"):
                slot=self.slot(cid,"sfr-back-"+arm);probe=self.slot(cid,"sfr-"+arm)
                prefix=json.loads(slot["input"])
                self.assertEqual(set(prefix),{"glosses","task"})
                self.assertEqual(prefix["glosses"],json.loads(probe["input"])["glosses"])
                self.assertEqual(slot["input_from"],{"slot_id":probe["slot_id"],"mode":"assistant_output_with_fixed_prefix"})
                raw='{"choice":"dax","unrequested":"preserve malformed raw response"}'
                body=build_body(slot,{probe["slot_id"]:{"actual_input":"SOURCE AND PREFERENCE MUST NOT COPY","output_text":raw}})
                self.assertEqual(body["input"],[{"role":"user","content":slot["input"]+"\n\n"+raw}])
                self.assertNotIn("SOURCE AND PREFERENCE MUST NOT COPY",json.dumps(body))
                self.assertNotIn("history_from",slot)

    def test_long_conditions_use_same_source_middle_and_same_registry(self):
        for dossier in self.dossiers["cases"]:
            cid=dossier["case_id"];case=self.cases[cid]
            verdict=json.loads(self.slot(cid,"long-verdict")["input"])
            ir=json.loads(self.slot(cid,"long-ir")["input"])
            self.assertEqual(verdict["source_documents"],dossier["source_documents"])
            self.assertEqual(verdict["source_documents"][1:-1],[{"id":d["id"],"text":d["text"]} for d in case["public"]["source_documents"]])
            self.assertEqual(ir,model_source(dossier["source_documents"],case["public"]["registry"]))
            self.assertEqual(verdict["registry"],case["public"]["registry"])
            self.assertEqual(verdict["current_exclusions"],case["events"]["states"]["withdrawn"])

    def test_duplicate_dossier_cannot_silently_replace_a_case(self):
        dossiers=deepcopy(self.dossiers);dossiers["cases"].append(deepcopy(dossiers["cases"][0]))
        with self.assertRaisesRegex(ValueError,"Dossier set"):
            sessions.build(self.corpus,dossiers)

    def test_changed_wrapper_hash_source_or_reference_count_rejects(self):
        for mutation in ("wrapper","source","reported_tokens","encoding","self_consistent_wrong_length"):
            with self.subTest(mutation=mutation):
                dossiers=deepcopy(self.dossiers);row=dossiers["cases"][0]
                if mutation=="wrapper":row["source_documents"][0]["text"]+='tamper'
                elif mutation=="source":row["source_documents"][1]["text"]+='tamper'
                elif mutation=="reported_tokens":row["measurement"]["reference_tokens"]=16383
                elif mutation=="encoding":row["measurement"]["encoding"]="o200k_base"
                else:
                    row["source_documents"][0]["text"]+=" unique extra words"
                    row["measurement"]["dossier_utf8_sha256"]=sha256(dossier_body(row["source_documents"]).encode()).hexdigest()
                with self.assertRaisesRegex(ValueError,"Dossier"):
                    sessions.build(self.corpus,dossiers)

    def test_output_limits_and_temperature_are_condition_matched(self):
        for slot in self.slots:
            expected=16384 if slot["condition"] in ("sample_graph","diagnostic_commitment") else 32768 if slot["condition"] in ("strict_source_ir","nl_source","nl_projection","adversarial_refuter","long_source_ir") else 8192
            self.assertEqual(slot["max_output_tokens"],expected)
            self.assertEqual(slot["temperature"],1.)

    def test_prompt_example_is_valid_and_unknown_status_convention_matches_gold(self):
        result=compile_ir(example_ir(),EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)
        self.assertEqual(result["candidate_count"],1)
        case=self.cases["V6H-F5-06"];did=case["evaluation"]["semantic_key_ids"]["D"]
        verdict=sessions.verdict_from_family(case,"withdrawn")["decisions"][did]
        self.assertEqual(verdict,{"box_supported":False,"diamond_supported":True,"states":["insufficient_provenance"]})
        self.assertIn("AGGREGATED per-interpretation",VERDICT_INSTRUCTIONS)
        self.assertIn("does not list the underlying completion statuses",VERDICT_INSTRUCTIONS)

    def test_current_corpus_order_does_not_mutate_and_case_order_is_fixed(self):
        original_ids=[c["id"] for c in self.corpus["cases"]]
        orders={}
        for model in PRIMARY_MODELS:
            orders[model]=[s["case_id"] for s in self.slots if s["model"]==model and s["phase"]=="hist_init"]
        self.assertTrue(all(order==orders[PRIMARY_MODELS[0]] for order in orders.values()))
        self.assertEqual(set(orders[PRIMARY_MODELS[0]]),set(original_ids))
        self.assertEqual([c["id"] for c in self.corpus["cases"]],original_ids)
        self.assertNotEqual(orders[PRIMARY_MODELS[0]],original_ids)


if __name__=="__main__":unittest.main()
