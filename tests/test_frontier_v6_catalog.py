"""Temporary fixtures only; never writes a product catalog or empirical result."""
from collections import Counter
from copy import deepcopy
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from retrace.source_ir_v6e_prompt import example, IR_V6E_INSTRUCTIONS
from retrace.source_ir_v6d import model_source
from retrace.server_v6d import catalog_manifest, catalog_entry, recorded_provenance, HandlerV6d
from scripts.build_frontier_v6_catalog import build_catalog, encoded


def fixture(root):
    docs, registry, ir = example()
    case = {"id": "fixture-case", "family": "HIDDEN_FAMILY_POISON", "title": "HIDDEN_TITLE_POISON",
            "public": {"source_documents": docs, "registry": registry}, "events": {"document_groups": []},
            "evaluation": {"source_family": "HIDDEN_GOLD_POISON", "reference_ir": "HIDDEN_IR_POISON"},
            "authored_seed_pool": {"candidates": "HIDDEN_SEED_POISON"}}
    slots, records, requests = [], [], []
    for number in range(10):
        arm = "adversarial_refuter" if number == 1 else "long_source_ir" if number == 2 else "source_ir"
        phase = "counter_read" if arm == "adversarial_refuter" else "extract"
        payload = model_source(docs, registry)
        if arm == "adversarial_refuter": payload["supplied_candidates"] = ["CONTROLLED_SEED_NOT_PRODUCT"]
        slot = {"slot_id": f"fixture-slot-{number}", "case_id": "fixture-case", "model": f"fixture-model-{number}",
                "condition": arm, "phase": phase, "max_output_tokens": 65536, "instructions": "Fixed fixture instructions",
                "input": json.dumps(payload)}
        slots.append(slot)
        if number in (6, 7):
            if number == 7: requests.append({"slot_id": slot["slot_id"]})
            continue
        record = {key: slot[key] for key in ("slot_id", "case_id", "model", "condition", "phase")}
        record.update(issued=True, http_status=200, response_status="completed", error=None, terminal_valid=True,
                      output_text=json.dumps(ir), partial_output_text="", raw_response="PRESERVED_RAW_PROVIDER_BODY",
                      usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30})
        if number == 1: record["output_text"] = '{"status":"no_counter_reading"}'
        elif number == 2: record.update(response_status="incomplete", output_text="", partial_output_text=json.dumps(ir), model_outcome="truncated_max_output_tokens")
        elif number == 3: record["output_text"] = '{"schema":'
        elif number == 4:
            broken = deepcopy(ir); del broken["propositions"][0]["kind"]; record["output_text"] = json.dumps(broken)
        elif number == 5: record.update(http_status=429, error="http_429", terminal_valid=False)
        elif number == 8:
            unknown = deepcopy(ir)
            origin = next(row for row in unknown["propositions"] if row["target"] == "EXB" and row["kind"] == "origin")
            origin["kind"] = "unknown_ancestry"; origin["body"] = {"description": "Supplied model asserts unresolved origin"}
            record["output_text"] = json.dumps(unknown)
        elif number == 9:
            missing = deepcopy(ir)
            missing["entities"] = [row for row in missing["entities"] if row["id"] != "EXB"]
            missing["propositions"] = [row for row in missing["propositions"] if row["target"] != "EXB"]
            next(row for row in missing["propositions"] if row["kind"] == "support")["body"] = {"expr": {"ref": "EXA"}}
            record["output_text"] = json.dumps(missing)
        records.append(record); requests.append({"slot_id": slot["slot_id"]})
    values = {"corpus.json": {"cases": [case]}, "dossiers.json": {"cases": [{"case_id": "fixture-case", "source_documents": docs}]}, "sessions.json": slots}
    for name, value in values.items(): (root / name).write_bytes(encoded(value))
    (root / "responses.jsonl").write_bytes(b"".join(encoded(row) for row in records))
    (root / "requests.jsonl").write_bytes(b"".join(encoded(row) for row in requests))
    freeze = {"files": [{"path": name, "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()} for name in values]}
    (root / "freeze.json").write_bytes(encoded(freeze))
    return {"root": root, "corpus_path": root / "corpus.json", "dossiers_path": root / "dossiers.json",
            "sessions_path": root / "sessions.json", "response_paths": [root / "responses.jsonl"],
            "output_directory": root / "catalog", "request_paths": [root / "requests.jsonl"],
            "requests_complete": True, "run_closed": True, "freeze_paths": [root / "freeze.json"], "workspace_root": root, "require_primary": False}


def build(arguments): return build_catalog(**{key: value for key, value in arguments.items() if key != "root"})


class CatalogTests(unittest.TestCase):
    def test_every_scheduled_outcome_remains_visible_and_raw_is_not_repaired(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); manifest = build(args)
            self.assertEqual(manifest["scheduled_catalog_slots"], 10)
            self.assertEqual(manifest["status_counts"], dict(Counter(["compiled_ir", "abstention", "truncated", "invalid_json_object", "invalid_ir",
                                                                      "operational_or_accounting_failure", "unissued", "issued_missing_response", "unresolved_structure", "compiled_inventory_gap"])))
            entries = [catalog_entry(row["id"], args["output_directory"]) for row in manifest["entries"]]
            truncated = next(row for row in entries if row["outcome"]["status"] == "truncated")
            self.assertFalse(truncated["outcome"]["loadable_ir"])
            self.assertIsNone(truncated["outcome"]["source_ir"])
            self.assertTrue(truncated["raw"]["partial_output_text"].startswith('{'))
            self.assertEqual(truncated["raw"]["raw_response"], "PRESERVED_RAW_PROVIDER_BODY")
            failed = next(row for row in entries if row["outcome"]["status"] == "operational_or_accounting_failure")
            self.assertFalse(failed["outcome"]["loadable_ir"])
            self.assertTrue(failed["raw"]["output_text"])
            self.assertEqual(sum(row["outcome"]["loadable_ir"] for row in entries), 3)

    def test_hidden_gold_and_authored_seeds_never_enter_entries(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); manifest = build(args)
            for row in manifest["entries"]:
                text = (args["output_directory"] / row["path"]).read_text(encoding="utf-8")
                for poison in ("HIDDEN_FAMILY_POISON", "HIDDEN_TITLE_POISON", "HIDDEN_GOLD_POISON", "HIDDEN_IR_POISON", "HIDDEN_SEED_POISON", "CONTROLLED_SEED_NOT_PRODUCT"):
                    self.assertNotIn(poison, text)
            self.assertEqual({r["role"] for r in manifest["inputs"]}, {"corpus", "dossiers", "sessions", "responses", "requests", "freeze"})

    def test_missing_record_is_not_assumed_unissued_without_complete_journals(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); args.update(request_paths=[], requests_complete=False, run_closed=False)
            result = build(args)
            self.assertEqual(result["status_counts"]["pending_or_unissued_or_missing_response"], 2)
            self.assertEqual(result["publication_status"], "provisional_snapshot")
            self.assertNotIn("unissued", result["status_counts"])

    def test_provisional_journal_snapshot_keeps_issued_and_unknown_slots_pending(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); args["run_closed"] = False
            result = build(args)
            self.assertEqual(result["scheduled_catalog_slots"], 10)
            self.assertEqual(result["status_counts"]["pending_or_missing_response"], 1)
            self.assertEqual(result["status_counts"]["pending_or_unissued_or_missing_response"], 1)
            self.assertEqual(result["publication_status"], "provisional_snapshot")

    def test_duplicate_or_unknown_response_aborts_without_publishing(self):
        for mutate in ("duplicate", "unknown"):
            with TemporaryDirectory() as directory:
                args = fixture(Path(directory)); path = args["response_paths"][0]
                row = json.loads(path.read_text().splitlines()[0])
                if mutate == "unknown": row["slot_id"] = "not-scheduled"
                with path.open("ab") as stream: stream.write(encoded(row))
                with self.assertRaises(ValueError): build(args)
                self.assertFalse(args["output_directory"].exists())

    def test_freeze_change_and_mismatched_public_source_are_rejected(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); args["corpus_path"].write_text('{}')
            with self.assertRaisesRegex(ValueError, "Frozen input changed"): build(args)
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); values = json.loads(args["sessions_path"].read_text())
            values[0]["input"] = json.dumps({"source_segments": [], "registry": {}})
            args["sessions_path"].write_bytes(encoded(values)); args["freeze_paths"] = []
            with self.assertRaisesRegex(ValueError, "does not match"): build(args)

    def test_entries_and_manifest_paths_are_hash_bound_and_bounded(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); result = build(args); row = result["entries"][0]
            original = (args["output_directory"] / row["path"]).read_bytes()
            (args["output_directory"] / row["path"]).write_bytes(original + b' ')
            with self.assertRaisesRegex(ValueError, "hash or size"): catalog_entry(row["id"], args["output_directory"])
            with self.assertRaises(ValueError): catalog_entry("../../corpus.json", args["output_directory"])
            manifest_path = args["output_directory"] / "manifest.json"
            manifest = json.loads(manifest_path.read_text()); manifest["entries"][0]["path"] = "../corpus.json"
            manifest_path.write_bytes(encoded(manifest))
            with self.assertRaisesRegex(ValueError, "Unsafe"): catalog_manifest(args["output_directory"])

    def test_exported_bundle_must_match_before_recorded_label_is_assigned(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); manifest = build(args)
            entry = catalog_entry(manifest["entries"][0]["id"], args["output_directory"])
            with patch('retrace.server_v6d.CATALOG_ROOT', args["output_directory"]):
                self.assertEqual(recorded_provenance(entry["bundle"])["entry_id"], entry["id"])
                changed = deepcopy(entry["bundle"]); changed["title"] = "edited"
                self.assertIsNone(recorded_provenance(changed))

    def test_manifest_identity_cannot_relabel_hashed_entry(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); manifest = build(args)
            manifest["entries"][0]["model"] = "different-model"
            (args["output_directory"] / "manifest.json").write_bytes(encoded(manifest))
            with self.assertRaisesRegex(ValueError, "index differs"):
                catalog_entry(manifest["entries"][0]["id"], args["output_directory"])

    def test_output_directory_is_exclusive_and_primary_requires_real_freeze(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); build(args)
            with self.assertRaisesRegex(ValueError, "new directory"): build(args)
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); args.update(require_primary=True, freeze_paths=[])
            with self.assertRaisesRegex(ValueError, "freeze"): build(args)

    def test_manifest_is_lazy_and_complete_counts_are_consistent(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); result = build(args)
            for row in result["entries"]:
                self.assertNotIn("bundle", row); self.assertNotIn("source_ir", row); self.assertNotIn("raw", row)
            self.assertEqual(sum(value["scheduled"] for value in result["by_model"].values()), 10)
            self.assertEqual(sum(value["scheduled"] for value in result["by_arm"].values()), 10)
            self.assertEqual(result["publication_status"], "closed_run_snapshot")

    def test_oversized_manifest_is_rejected_before_reading(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            with (folder / "manifest.json").open("wb") as stream: stream.truncate(4_194_305)
            with patch.object(Path, "open", side_effect=AssertionError("oversized file must not be read")):
                with self.assertRaisesRegex(ValueError, "size bound"): catalog_manifest(folder)

    def test_http_serves_only_known_catalog_ids_and_current_prompt(self):
        with TemporaryDirectory() as directory:
            args = fixture(Path(directory)); manifest = build(args)
            server = ThreadingHTTPServer(('127.0.0.1', 0), HandlerV6d)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            def request(route, body=None):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET' if body is None else 'POST', route, body=json.dumps(body) if body else None)
                response = connection.getresponse(); status = response.status; value = json.loads(response.read()); connection.close(); return status, value
            try:
                with patch('retrace.server_v6d.CATALOG_ROOT', args["output_directory"]):
                    self.assertEqual(request('/api/v6d/catalog')[1]['scheduled_catalog_slots'], 10)
                    self.assertEqual(request('/api/v6d/catalog/' + manifest['entries'][0]['id'])[0], 200)
                    self.assertEqual(request('/api/v6d/catalog/' + '0'*24)[0], 404)
                    self.assertEqual(request('/api/v6d/catalog/%2e%2e/corpus.json')[0], 404)
                    docs, registry, _ = example()
                    status, data = request('/api/v6d/source', {'brief': {'source_documents': docs, 'registry': registry}})
                    self.assertEqual(status, 200); self.assertEqual(data['instructions'], IR_V6E_INSTRUCTIONS)
            finally: server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
