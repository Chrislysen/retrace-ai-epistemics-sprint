"""Invented offline fixtures only. Run after the paid sweep has closed."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import check_frontier_v6n_post_sweep as check


class PostSweepTests(unittest.TestCase):
    def test_sequence_and_last_assignment_reconstruction_are_distinct_paths(self):
        actions = [("revoked_documents", "doc", True), ("revoked_passages", "A", True),
                   ("revoked_documents", "doc", False), ("answers", "q", True),
                   ("answers", "q", None)]
        state = check.empty_state()
        for index, action in enumerate(actions, 1):
            before = deepcopy(state)
            state = check.transition(state, action)
            self.assertEqual(before, check.fresh_state(actions[:index - 1]))
            self.assertEqual(state, check.fresh_state(actions[:index]))
        self.assertEqual(state["revoked_passages"], ["A"])
        self.assertEqual(state["revoked_documents"], [])
        self.assertIsNone(state["answers"]["q"])

    def test_frozen_workbench_sequence_matches_fresh_and_direct_semantics(self):
        result = check.event_sequence_checks()
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["steps"]), 17)
        self.assertFalse(result["incremental_kernel_present"])
        self.assertTrue(result["stale_declaration_rejected"])
        restored = result["steps"][3]["state"]
        self.assertEqual(restored["revoked_passages"], ["A"])
        self.assertEqual(restored["revoked_documents"], [])
        self.assertTrue(all(row["session_equals_fresh"] and row["wrapper_equals_direct"] for row in result["steps"]))

    def test_static_checks_parse_without_import_or_execution(self):
        result = check.syntax_checks({"sample.py": b"raise RuntimeError('never execute')  \n", "data.json": b"not python"})
        self.assertEqual(result["python_ast_file_count"], 1)
        self.assertEqual(result["trailing_whitespace"], [{"path": "sample.py", "trailing_whitespace_lines": [1]}])
        with self.assertRaises(SyntaxError):
            check.syntax_checks({"bad.py": b"def unfinished("})

    def plan(self, root):
        (root / "source.py").write_bytes(b"x = 1\n")
        return {"schema": "retrace.frontier-v6n-post-sweep-plan.v1", "source_bindings": {"source.py": check.binding(b"x = 1\n")},
                "frozen_aliases": {}, "source_freeze_sha256": "a" * 64, "runtime_audit_sha256": "b" * 64,
                "runtime_schedule_status": "completed", "frozen_files_checked": 1, "syntax_checks": {"passed": True},
                "cases": [{"id": "invented"}], "baselines": {"kind": "deterministic_synthetic_rule_baselines"},
                "event_sequence_vs_fresh": {"passed": True, "kind": "event_sequence_vs_fresh", "steps": [{"step": 1}]}}

    def test_publication_uses_only_exclusive_new_paths_and_binds_each_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan(root)
            result = check.publish(root, plan)
            self.assertEqual(result["provider_calls"], 0)
            self.assertFalse(result["network_used"])
            self.assertFalse(result["servers_started"])
            for name, expected in result["files"].items():
                self.assertEqual(check.binding((root / name).read_bytes()), expected)
            self.assertEqual(json.loads((root / check.OUTPUT / "checks.json").read_bytes()), result)
            with self.assertRaisesRegex(ValueError, "Exclusive"):
                check.publish(root, plan)

    def test_source_mutation_between_checks_and_publication_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan(root)
            (root / "source.py").write_bytes(b"x = 2\n")
            with self.assertRaisesRegex(ValueError, "Source changed"):
                check.publish(root, plan)
            self.assertFalse((root / check.OUTPUT).exists())

    def test_active_recovery_refused_before_any_audit_or_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "results/frontier-v6n/budget/active.lock"
            lock.parent.mkdir(parents=True)
            lock.write_bytes(b"")
            with patch.object(check, "event_sequence_checks", side_effect=AssertionError("not reached")):
                with self.assertRaisesRegex(ValueError, "still active"):
                    check.run(root, "a" * 64, "b" * 64)

    def test_unknown_alias_and_path_escape_rejected(self):
        with self.assertRaisesRegex(ValueError, "historical-lock aliases"):
            check.run(Path("."), "a" * 64, "b" * 64, frozen_aliases={"source": "replacement"})
        for value in ("../outside", "C:/outside", "nested\\file"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                check.relative(value)


if __name__ == "__main__":
    unittest.main()
