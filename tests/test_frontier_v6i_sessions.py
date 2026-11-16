"""Prospective v6i projection checks; no provider access or result inspection."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import unittest

from retrace.adaption_v6h import PRIMARY_MODELS, build_body
from scripts import build_frontier_v6i_sessions as builder

ROOT = Path(__file__).resolve().parents[1]


class V6iSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((ROOT / "data/frontier-v6h-corpus.json").read_text(encoding="utf-8"))
        cls.old = json.loads((ROOT / "data/frontier-v6h-sessions.json").read_text(encoding="utf-8"))
        cls.design, cls.slots = builder.build(cls.corpus, cls.old)
        cls.by_id = {s["slot_id"]: s for s in cls.slots}
        cls.old_by_id = {s["slot_id"]: s for s in cls.old}
        cls.cases = {c["id"]: c for c in cls.corpus["cases"]}

    def row(self, cid, condition, phase=None, model=builder.SECONDARY_MODEL):
        matches = [s for s in self.slots if s["case_id"] == cid and s["model"] == model and s["condition"] == condition and (phase is None or s["phase"] == phase)]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_exact_grid_and_all_model_case_primary_coverage(self):
        self.assertEqual(len(self.slots), 1800)
        self.assertEqual(len(self.by_id), 1800)
        self.assertEqual(Counter(s["condition"] for s in self.slots), Counter(builder.EXPECTED_COUNTS))
        self.assertEqual(Counter(s["model"] for s in self.slots), Counter({
            "deepseek-v4-flash": 276, "gemma-4-31b-it": 612,
            "glm-5.3-flash": 276, "qwen3.8-27b": 276, "glm-5.2": 276, "qwen3.5-397b": 84}))
        for model in PRIMARY_MODELS:
            for cid in self.cases:
                self.row(cid, "strict_source_ir", model=model)
                self.row(cid, "adversarial_refuter", model=model)

    def test_subset_strata_and_graph_reading_counts_are_explicit(self):
        subsets = self.design["subsets"]
        self.assertEqual(subsets["temporal"], subsets["oracle_assisted"])
        self.assertEqual(subsets["temporal"], subsets["long_gemma"])
        self.assertEqual(subsets["temporal"], subsets["qwen_diagnostic"])
        for key in ("temporal", "oracle_assisted", "long_gemma", "qwen_diagnostic"):
            self.assertEqual(Counter(self.cases[c]["family_id"] for c in subsets[key]), Counter({f"F{i}": 2 for i in range(1, 7)}))
            self.assertTrue(all(self.cases[c]["partition"] == "synthetic" for c in subsets[key]))
        self.assertEqual(self.design["subset_counts"]["nl_projection"]["partitions"], {"ecological": 6, "synthetic": 24})
        self.assertEqual(self.design["subset_counts"]["sfr_gemma"]["partitions"], {"ecological": 6, "synthetic": 18})
        k = subsets["k10_gemma"]
        self.assertEqual(Counter(len(self.cases[c]["evaluation"]["source_family"]) > 1 for c in k), Counter({True: 10, False: 2}))
        self.assertNotIn("V6H-F5-06", self.design["k10_ambiguity_case_ids"])

    def test_selected_original_rows_unchanged_except_namespace_and_sfr(self):
        for row in self.slots:
            if row["condition"] in ("sfr_probe", "sfr_backtranslation"):
                continue
            if row["model"] == builder.DIAGNOSTIC_MODEL and row["condition"] == "strict_source_ir":
                original = self.old_by_id[row["slot_id"].replace("v6i::" + builder.DIAGNOSTIC_MODEL, "v6h::" + builder.SECONDARY_MODEL, 1)]
                expected = builder._rewrite(original)
                expected.update(slot_id=row["slot_id"], model=builder.DIAGNOSTIC_MODEL, max_output_tokens=16384)
            else:
                original = self.old_by_id[row["slot_id"].replace("v6i::", "v6h::", 1)]
                expected = builder._rewrite(original)
            self.assertEqual(row, expected)

    def test_dependencies_are_present_earlier_same_model_and_case(self):
        seen = {}
        for row in self.slots:
            deps = row.get("history_from", []) + ([row["input_from"]["slot_id"]] if "input_from" in row else [])
            for dep in deps:
                self.assertIn(dep, seen)
                self.assertEqual((seen[dep]["model"], seen[dep]["case_id"]), (row["model"], row["case_id"]))
            seen[row["slot_id"]] = row
        cid = self.design["subsets"]["temporal"][0]
        init = self.row(cid, "commitment", "hist_init")
        withdrawn = self.row(cid, "commitment", "hist_withdrawn")
        restored = self.row(cid, "commitment", "hist_restored")
        body = build_body(restored, {init["slot_id"]: {"actual_input": "ACTUAL SOURCE", "output_text": "WRONG INITIAL ANSWER"}, withdrawn["slot_id"]: {"actual_input": "ACTUAL EVENT", "output_text": "WRONG WITHDRAWN ANSWER"}})
        self.assertEqual([m["content"] for m in body["input"]], ["ACTUAL SOURCE", "WRONG INITIAL ANSWER", "ACTUAL EVENT", "WRONG WITHDRAWN ANSWER", restored["input"]])

    def test_nl_projection_has_only_actual_account_and_no_source_fallback(self):
        cid = self.design["subsets"]["nl_projection"][0]
        nl = self.row(cid, "nl_source")
        projection = self.row(cid, "nl_projection")
        self.assertEqual(projection["input"], "")
        self.assertEqual(projection["input_from"], {"slot_id": nl["slot_id"], "mode": "assistant_output_only"})
        body = build_body(projection, {nl["slot_id"]: {"actual_input": "DO NOT COPY ORIGINAL SOURCE", "output_text": "ACTUAL INCOMPLETE ACCOUNT"}})
        self.assertEqual(body["input"], [{"role": "user", "content": "ACTUAL INCOMPLETE ACCOUNT"}])

    def test_oracle_and_assistance_are_separate_matched_declarations(self):
        for cid in self.design["subsets"]["oracle_assisted"]:
            a = json.loads(self.row(cid, "oracle_ir_consumption")["input"])
            b = json.loads(self.row(cid, "symbolic_assistance")["input"])
            self.assertNotIn("deterministic_declared_support", a)
            self.assertIn("deterministic_declared_support", b)
            self.assertEqual(a["declared_source_ir"], self.cases[cid]["evaluation"]["reference_ir"])
            for key in a:
                self.assertEqual(a[key], b[key])

    def test_sfr_balancing_is_evaluation_side_and_prospective(self):
        rows = self.design["sfr_assignments_evaluation_only"]
        for key in ("source_fact_is_root", "first_arm_prefers_yes", "yes_gloss_is_dax", "yes_gloss_displayed_first"):
            self.assertEqual(Counter(r[key] for r in rows), Counter({True: 12, False: 12}))
        self.assertEqual(Counter(r["authored_seed_kind"] for r in rows), Counter({"deficient": 12, "faithful_complete": 12}))
        self.assertEqual(rows, builder.sfr_assignments(self.corpus["cases"], self.design["subsets"]["sfr_gemma"]))
        for row in rows:
            graph_rows = [next(e for e in g["graph"]["evidence"] if e["id"] == row["entity_id"]) for g in self.cases[row["case_id"]]["evaluation"]["source_family"]]
            self.assertEqual({e["kind"] == "root" and e["parents"] == [] for e in graph_rows}, {row["source_fact_is_root"]})
        for row in self.slots:
            if row["condition"] not in ("sfr_probe", "sfr_backtranslation"):
                continue
            self.assertNotIn("source_fact_is_root", row["input"])
            self.assertNotIn("authored_seed_kind", row["input"])

    def test_preference_pair_only_preference_changes_neutrals_byte_identical(self):
        for cid in self.design["subsets"]["sfr_gemma"]:
            rows = {arm: self.row(cid, "sfr_probe", arm) for arm in ("a", "b", "neutral_a", "neutral_b")}
            a, b = json.loads(rows["a"]["input"]), json.loads(rows["b"]["input"])
            self.assertEqual({k for k in a if a[k] != b[k]}, {"reviewer_preference"})
            neutral = {k: v for k, v in a.items() if k != "reviewer_preference"}
            self.assertEqual(json.loads(rows["neutral_a"]["input"]), neutral)
            self.assertEqual(rows["neutral_a"]["input"], rows["neutral_b"]["input"])
            self.assertEqual(len({r["instructions"] for r in rows.values()}), 1)
            for r in rows.values():
                self.assertNotIn("history_from", r)
                self.assertNotIn("input_from", r)

    def test_all_four_backtranslations_are_blind_and_use_own_raw_probe(self):
        for cid in self.design["subsets"]["sfr_gemma"]:
            for arm in ("a", "b", "neutral_a", "neutral_b"):
                p = self.row(cid, "sfr_probe", arm)
                b = self.row(cid, "sfr_backtranslation", arm)
                self.assertEqual(b["input_from"], {"slot_id": p["slot_id"], "mode": "assistant_output_with_fixed_prefix"})
                self.assertEqual(set(json.loads(b["input"])), {"glosses", "task"})
                self.assertEqual(json.loads(b["input"])["glosses"], json.loads(p["input"])["glosses"])
                raw = '{"choice":"dax","extra":"PRESERVE MALFORMED"}'
                body = build_body(b, {p["slot_id"]: {"actual_input": "SOURCE AND PREFERENCE NOT COPIED", "output_text": raw}})
                self.assertEqual(body["input"], [{"role": "user", "content": b["input"] + "\n\n" + raw}])

    def test_k10_calls_independent_long_pairs_share_short_source_and_state(self):
        for cid in self.design["subsets"]["k10_gemma"]:
            rows = [s for s in self.slots if s["case_id"] == cid and s["condition"] == "sample_graph"]
            self.assertEqual(len(rows), 10)
            self.assertEqual({s["model"] for s in rows}, {builder.SECONDARY_MODEL})
            self.assertEqual(len({(s["input"], s["instructions"], s["temperature"], s["max_output_tokens"]) for s in rows}), 1)
            self.assertTrue(all("history_from" not in s and "input_from" not in s for s in rows))
        for cid in self.design["subsets"]["long_gemma"]:
            long = json.loads(self.row(cid, "long_commitment")["input"])
            short = json.loads(self.row(cid, "commitment", "fresh_withdrawn")["input"])
            self.assertEqual(long["source_documents"][1:-1], short["source_documents"])
            self.assertEqual(long["current_exclusions"], short["current_exclusions"])
            self.row(cid, "strict_source_ir")
            self.row(cid, "long_source_ir")

    def test_source_hidden_annotations_do_not_enter_projection(self):
        mutated = deepcopy(self.corpus)
        for case in mutated["cases"]:
            case["evaluation"]["state_gold"] = "HIDDEN_STATE_MARKER"
            case["evaluation"]["reference_ir"] = "HIDDEN_REFERENCE_MARKER"
            case["evaluation"]["never_project"] = "HIDDEN_ANNOTATION_MARKER"
        _, actual = builder.build(mutated, self.old)
        self.assertEqual(actual, self.slots)
        for row in actual:
            self.assertNotIn("HIDDEN_", row["input"])

    def test_duplicate_or_missing_original_slots_reject(self):
        with self.assertRaisesRegex(ValueError, "8148"):
            builder.build(self.corpus, self.old[:-1])
        changed = list(self.old)
        changed[-1] = changed[0]
        with self.assertRaisesRegex(ValueError, "8148"):
            builder.build(self.corpus, changed)


if __name__ == "__main__":
    unittest.main()
