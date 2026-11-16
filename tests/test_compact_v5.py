"""Generic language-extension checks, not repaired or rescored v4 outcomes."""
import hashlib
import itertools
import unittest

from retrace.compact_v4 import compile_ambiguity as compile_v4
from retrace.compact_v5 import CompactV5Error, compile_ambiguity


def equivalent(test, local, standalone):
    result, reference = compile_ambiguity(local), compile_v4(standalone)
    for key in ("candidates", "questions", "uncertainty_count", "expected_candidate_count"):
        test.assertEqual(result[key], reference[key])
    test.assertEqual(compile_v4(result["canonical_v4"])["candidates"], result["candidates"])
    return result


class CompactV5Tests(unittest.TestCase):
    def test_all_six_families_are_equivalent_under_systematic_id_renaming(self):
        for index in range(12):
            a, b, c, d, target, decision = [f"N{index}_{name}" for name in ("A", "B", "C", "D", "T", "Q")]
            roots = "\n".join(f"E {name} R {int(position % 2 == 0)} -" for position, name in enumerate((a, b, c, d))) + "\n"
            families = [
                ("AMBIGUOUS_GATE", f"{a}, {b}"), ("UNSPECIFIED_SOURCE", a),
                ("UNSPECIFIED_CHOICE", f"{a}, {b}"), ("AMBIGUOUS_QUALIFIER", f"{a}, {b}, {c}"),
                ("OPTIONAL_ROUTE", f"{a}, {b}, {c}; {d}"),
            ]
            for operator, arguments in families:
                local = roots + f"C {target} {operator}({arguments})\nD {decision} {target}\nEND"
                old = roots + f"C {target} ?\nD {decision} {target}\n{operator}({target}: {arguments})\nEND"
                equivalent(self, local, old)
            for active in (0, 1):
                tail = f"C claim_{index} {target}\nD {decision} claim_{index}\nEND"
                local = roots + f"E {target} ? {active} UNVERIFIED_INDEPENDENCE({a})\n" + tail
                old = roots + f"E {target} ? {active} -\n" + tail.removesuffix("END") + f"UNVERIFIED_INDEPENDENCE({target}, {a})\nEND"
                equivalent(self, local, old)
                for kind in ("C", "?"):
                    local = roots + f"E {target} {kind} {active} UNSPECIFIED_CHOICE({a}, {b})\n" + tail
                    old = roots + f"E {target} ? {active} -\n" + tail.removesuffix("END") + f"UNSPECIFIED_CHOICE({target}: {a}, {b})\nEND"
                    equivalent(self, local, old)

    def test_matching_redundant_evidence_target_is_explicitly_classified(self):
        for operator, arguments in (("UNVERIFIED_INDEPENDENCE", "A"), ("UNSPECIFIED_CHOICE", "A, B")):
            prefix = "E A R 0 -\nE B R 1 -\n"
            tail = "\nC c N\nD d c\nEND"
            simple = prefix + f"E N ? 1 {operator}({arguments})" + tail
            repeated = prefix + f"E N ? 1 {operator}(N, {arguments})" + tail
            first, second = compile_ambiguity(simple), compile_ambiguity(repeated)
            self.assertEqual(first["candidates"], second["candidates"])
            self.assertEqual(first["questions"], second["questions"])
            self.assertEqual(second["transformations"][0]["classification"], "node_local_evidence_redundant_target")
            self.assertTrue(second["transformations"][0]["redundant_target_validated"])

    def test_all_sixteen_assignments_survive_mixed_local_and_standalone_forms(self):
        local = """E A R 1 -
E B R 0 -
E N ? 1 UNVERIFIED_INDEPENDENCE(A)
C first AMBIGUOUS_GATE(A, B)
C second UNSPECIFIED_SOURCE(N)
C third ?
D d first+second+third
UNSPECIFIED_CHOICE(third: A, B)
END"""
        old = """E A R 1 -
E B R 0 -
E N ? 1 -
C first ?
C second ?
C third ?
D d first+second+third
UNVERIFIED_INDEPENDENCE(N, A)
AMBIGUOUS_GATE(first: A, B)
UNSPECIFIED_SOURCE(second: N)
UNSPECIFIED_CHOICE(third: A, B)
END"""
        result = equivalent(self, local, old)
        self.assertEqual(result["candidate_count"], 16)
        self.assertEqual({tuple(candidate["assignment"].values()) for candidate in result["candidates"]},
                         set(itertools.product((False, True), repeat=4)))

    def test_fixed_and_standalone_v4_inputs_pass_without_transformation(self):
        examples = ["E A R 1 -\nC c A\nD d c\nEND",
                    "E A R 1 -\nE B R 0 -\nC c ?\nD d c\nAMBIGUOUS_GATE(c: A, B)\nEND"]
        for source in examples:
            result = compile_ambiguity(source)
            self.assertEqual(result["canonical_v4"], source)
            self.assertEqual(result["transformations"], [])
            self.assertEqual(result["transformation_classification"], "identity_v4")
            self.assertEqual(result["candidates"], compile_v4(source)["candidates"])

    def test_original_bytes_fences_and_physical_line_mapping_are_preserved(self):
        source = "\r\n```text\r\nE A R 1 -\r\nC c UNSPECIFIED_SOURCE(A)\r\nD d c\r\nEND\r\n```\r\n"
        result = compile_ambiguity(source)
        self.assertEqual(result["source_text"], source)
        self.assertEqual(result["source_text_sha256"], hashlib.sha256(source.encode()).hexdigest())
        self.assertFalse(result["strict_bare"])
        self.assertTrue(result["outer_fence_removed"])
        self.assertEqual(result["transformations"][0]["source_line"], 4)
        self.assertEqual(result["transformations"][0]["canonical_lines"], [4, 5])
        self.assertEqual([row["source_line"] for row in result["line_mapping"] if row["canonical_line"] in (4, 5)], [4, 4])

    def test_extra_missing_mismatched_or_ambiguous_evidence_arguments_reject(self):
        prefix = "E A R 1 -\nE B R 1 -\n"
        tail = "\nC c N\nD d c\nEND"
        bad = ["E N ? 1 UNVERIFIED_INDEPENDENCE(other, A)",
               "E N ? 1 UNVERIFIED_INDEPENDENCE(N, A, B)",
               "E N ? 1 UNVERIFIED_INDEPENDENCE()", "E N C 1 UNVERIFIED_INDEPENDENCE(A)",
               "E N R 1 UNSPECIFIED_CHOICE(A, B)", "E N ? 1 UNSPECIFIED_CHOICE(other, A, B)",
               "E N ? 1 UNSPECIFIED_CHOICE(A)", "E N ? 1 UNSPECIFIED_CHOICE(N, A, B, A)",
               "E N ? 1 UNSPECIFIED_CHOICE(A: B)", "E N ? 1 UNSPECIFIED_CHOICE(A, A)"]
        for row in bad:
            with self.subTest(row=row), self.assertRaises(ValueError):
                compile_ambiguity(prefix + row + tail)

    def test_claim_redundant_target_unknown_operator_and_competing_fixed_rule_reject(self):
        prefix = "E A R 1 -\nE B R 1 -\n"
        bad = ["C c AMBIGUOUS_GATE(c: A, B)", "C c UNSPECIFIED_CHOICE(c, A, B)",
               "C c UNKNOWN_GATE(A, B)", "C c UNVERIFIED_INDEPENDENCE(A)",
               "C c AMBIGUOUS_GATE(A, B)\nC c A",
               "C c AMBIGUOUS_GATE(A, B)\nUNSPECIFIED_SOURCE(c: A)"]
        for middle in bad:
            with self.subTest(middle=middle), self.assertRaises(ValueError):
                compile_ambiguity(prefix + middle + "\nD d c\nEND")

    def test_any_branch_cycle_rejects_and_error_maps_to_original_source(self):
        source = "E A R 1 -\nC X UNSPECIFIED_CHOICE(A, Y)\nC Y UNSPECIFIED_CHOICE(A, X)\nD d X\nEND"
        with self.assertRaises(CompactV5Error) as caught:
            compile_ambiguity(source)
        self.assertEqual(caught.exception.code, "invalid_branch")
        self.assertEqual(caught.exception.assignment, {"resolve_X": True, "resolve_Y": True})
        self.assertIn(caught.exception.line_number, (2, 3))

    def test_fences_junk_truncation_and_typed_registry_are_not_repaired(self):
        valid = "E A R 1 -\nC c UNSPECIFIED_SOURCE(A)\nD d c\nEND"
        bad = ["Explanation\n" + valid, valid + "\nC extra UNSPECIFIED_SOURCE(A)",
               valid.removesuffix("END"), "```json\n" + valid + "\n```",
               "```text\n```\n" + valid + "\n```", valid.replace("SOURCE(A)", "SOURCE(missing)")]
        for source in bad:
            with self.assertRaises(ValueError):
                compile_ambiguity(source)
        with self.assertRaises(ValueError):
            compile_ambiguity(valid, {"evidence": ["A"], "claims": ["other"], "decisions": ["d"]})


if __name__ == "__main__":
    unittest.main()
