import unittest
from scripts.host_guard_v6m import keep_system_awake, CONTINUOUS, SYSTEM_REQUIRED


class HostGuardTests(unittest.TestCase):
    def test_only_system_idle_is_requested_and_prior_state_restored(self):
        calls=[]
        def api(value):
            calls.append(value)
            return CONTINUOUS
        with keep_system_awake(_set_state=api) as status:
            self.assertTrue(status['system_idle_inhibited'])
            self.assertFalse(status['display_required'])
            self.assertFalse(status['manual_sleep_or_restart_prevented'])
        self.assertEqual(calls,[CONTINUOUS|SYSTEM_REQUIRED,CONTINUOUS])

    def test_failure_before_yield_does_not_admit_work(self):
        entered=False
        with self.assertRaisesRegex(RuntimeError,'no inference'):
            with keep_system_awake(_set_state=lambda _:0):
                entered=True
        self.assertFalse(entered)

    def test_body_failure_still_restores_exact_prior_state(self):
        calls=[]
        def api(value):
            calls.append(value)
            return CONTINUOUS|SYSTEM_REQUIRED
        with self.assertRaisesRegex(ValueError,'invented'):
            with keep_system_awake(_set_state=api):
                raise ValueError('invented')
        self.assertEqual(calls,[CONTINUOUS|SYSTEM_REQUIRED]*2)


if __name__=='__main__':unittest.main()
