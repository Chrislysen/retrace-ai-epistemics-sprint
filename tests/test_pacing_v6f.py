"""Deterministic admission tests. No clocks, waits, credentials or API calls."""
from copy import deepcopy
import itertools
import json
import unittest

from retrace.pacing_v6f import AdmissionWindow, AdmissionDenied, estimate_request


class AdmissionWindowTests(unittest.TestCase):
    def test_exact_boundary_expires_and_rejection_consumes_no_start(self):
        window = AdmissionWindow(); window.record(0, 100000)
        self.assertEqual(window.delay(60, 1), 1)
        with self.assertRaises(AdmissionDenied) as error: window.record(60, 1)
        self.assertEqual(error.exception.delay_seconds, 1)
        self.assertEqual(len(window.records), 1)
        self.assertEqual(window.delay(61, 100000), 0)
        window.record(61, 100000)

    def test_combined_weights_release_only_enough_old_starts(self):
        window = AdmissionWindow()
        for now, weight in [(0, 20000), (5, 30000), (10, 40000)]: window.record(now, weight)
        self.assertEqual(window.delay(20, 35000), 46)  # 20k expiry alone is insufficient.
        window.record(66, 35000)
        self.assertEqual(window.delay(66, 25000), 0)
        window.record(66, 25000)
        self.assertEqual(window.delay(66, 1), 5)

    def test_ten_starts_bind_even_when_tokens_do_not(self):
        window = AdmissionWindow()
        for now in range(10): window.record(now, 1)
        self.assertEqual(window.delay(10, 1), 51)
        window.record(61, 1)
        self.assertEqual(window.delay(61, 1), 1)

    def test_solo_requires_cooldown_before_and_after(self):
        window = AdmissionWindow(); window.record(0, 1); window.record(3.1, 1)
        self.assertAlmostEqual(window.delay(4, 100001), 60.1)
        window.record(64.1, 125000)
        self.assertAlmostEqual(window.delay(100, 1), 25.1)
        self.assertAlmostEqual(window.delay(100, 100001), 25.1)
        window.record(125.1, 1)

    def test_fresh_solo_has_no_implicit_initial_cooldown(self):
        window = AdmissionWindow()
        self.assertEqual(window.delay(0, 125000), 0)
        window.record(0, 125000)
        self.assertEqual(window.delay(0, 1), 61)
        self.assertEqual(window.delay(61, 125000), 0)

    def test_large_admission_rejected_before_record_or_clock_changes(self):
        window = AdmissionWindow()
        for weight in (0, -1, True, 1.0, 125001, 10**100):
            with self.assertRaises(ValueError): window.record(100, weight)
        window.record(0, 1)
        self.assertEqual(window.records, ((0.0, 1),))

    def test_monotonic_watermark_includes_delay_queries(self):
        window = AdmissionWindow(); window.delay(10, 1)
        with self.assertRaisesRegex(ValueError, "backwards"): window.delay(9, 1)
        with self.assertRaisesRegex(ValueError, "backwards"): window.record(9, 1)
        window.record(10, 1)
        for invalid in (float('nan'), float('inf'), True, "11", 1e308):
            with self.assertRaises(ValueError): window.delay(invalid, 1)

    def test_delay_does_not_consume_admission(self):
        window = AdmissionWindow()
        for _ in range(20): self.assertEqual(window.delay(0, 100000), 0)
        self.assertEqual(window.records, ())
        window.record(0, 100000)

    def test_snapshot_conservatively_restores_relative_ages(self):
        window = AdmissionWindow(); window.record(0, 60000); window.record(5, 30000)
        snapshot = window.snapshot(20); original = deepcopy(snapshot)
        restored = AdmissionWindow.from_snapshot(json.loads(json.dumps(snapshot)), 1000)
        self.assertEqual(restored.delay(1000, 20000), 41)
        self.assertEqual(snapshot, original)
        self.assertEqual(restored.snapshot(1000), snapshot)
        solo = AdmissionWindow(); solo.record(0, 125000)
        restored_solo = AdmissionWindow.from_snapshot(solo.snapshot(1), 0)
        self.assertEqual(restored_solo.delay(0, 1), 60)

    def test_snapshot_rejects_changed_policy_and_impossible_history(self):
        window = AdmissionWindow(); window.record(0, 1); base = window.snapshot(0)
        changed = deepcopy(base); changed['token_budget'] = 999999
        with self.assertRaises(ValueError): AdmissionWindow.from_snapshot(changed, 10)
        for records in ([{'age_seconds': -1, 'weight': 1}], [{'age_seconds': 61, 'weight': 1}],
                        [{'age_seconds': 0, 'weight': 1}, {'age_seconds': 1, 'weight': 1}],
                        [{'age_seconds': 1, 'weight': 125000}, {'age_seconds': 0, 'weight': 1}],
                        [{'age_seconds': 0, 'weight': 10000}] * 11):
            changed = deepcopy(base); changed['records'] = records
            with self.assertRaises(ValueError): AdmissionWindow.from_snapshot(changed, 100)

    def test_observed_sized_sequence_is_delayed_prospectively(self):
        window = AdmissionWindow()
        for index in range(5): window.record(index * 3.1, 8192)
        # Even without input estimates, this conservative policy refuses the
        # earlier106496-output-token pattern inside one local window.
        self.assertGreater(window.delay(15.5, 65536), 0)
        window.record(61, 65536)
        self.assertGreater(window.delay(64.1, 65536), 0)

    def test_earliest_admission_matches_independent_release_scan(self):
        # Exercise count, weight and solo mixtures using a separate scalar rule.
        for weights in itertools.product((5000, 30000, 60000, 100001), repeat=3):
            window = AdmissionWindow(); now = 0.0
            for weight in weights:
                wait = window.delay(now, weight); target = now + wait
                boundaries = sorted({now} | {started + 61 for started, _ in window.records if started + 61 >= now})
                expected = None
                for candidate_time in boundaries:
                    active = [(t, w) for t, w in window.records if candidate_time - t < 61]
                    permitted = (not active if weight > 100000 else len(active) < 10 and sum(w for _, w in active) + weight <= 100000)
                    if permitted: expected = candidate_time; break
                self.assertEqual(target, expected)
                window.record(target, weight); now = target + 7


class EstimateTests(unittest.TestCase):
    def test_ceiling_and_output_reserve_are_exact_integers(self):
        for count, expected in [(0, 0), (1, 2), (2, 3), (3, 4), (4, 5), (5, 7)]:
            result = estimate_request('rule', [{'role': 'user', 'content': 'source'}], 100, token_counter=lambda text, n=count: n)
            self.assertEqual(result['weighted_input_tokens'], expected)
            self.assertEqual(result['weight'], expected + 100)
            self.assertFalse(result['quota_verified'])
            self.assertEqual(result['encoding'], 'injected_test_counter')

    def test_every_history_message_and_instruction_enters_counter(self):
        captured = []
        def counter(text): captured.append(json.loads(text)); return len(text)
        messages = [{'role': 'user', 'content': 'old source'}, {'role': 'assistant', 'content': 'earlier commitment'}, {'role': 'user', 'content': 'new event'}]
        result = estimate_request('complete instructions', messages, 20, token_counter=counter)
        self.assertEqual(captured, [{'instructions': 'complete instructions', 'input': messages}])
        self.assertNotIn('earlier commitment', json.dumps(result))

    def test_oversized_estimate_and_bad_text_input_reject_locally(self):
        with self.assertRaises(ValueError): estimate_request('', [{'role': 'user', 'content': 'x'}], 65536, token_counter=lambda _: 50000)
        result = estimate_request('', [{'role': 'user', 'content': 'x'}], 65536, token_counter=lambda _: 30000)
        self.assertTrue(result['solo_required'])
        for messages in ([], [{'role': 'user', 'content': ['image']}], [{'content': 'x'}]):
            with self.assertRaises(ValueError): estimate_request('', messages, 1, token_counter=lambda _: 0)
        for count in (-1, True, 1.5):
            with self.assertRaises(ValueError): estimate_request('', [{'role': 'user', 'content': 'x'}], 1, token_counter=lambda _, n=count: n)


if __name__ == '__main__': unittest.main()
