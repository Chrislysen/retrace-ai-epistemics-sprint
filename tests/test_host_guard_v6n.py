from contextlib import contextmanager
import unittest
from scripts.host_guard_v6n import keep_system_awake


class ConsoleHostGuardTests(unittest.TestCase):
    def test_attached_console_blocks_before_idle_or_network(self):
        with self.assertRaisesRegex(RuntimeError, 'console'):
            with keep_system_awake(_console=lambda: {'console_free_verified': False},
                                   _idle=lambda: self.fail('Idle guard must not start')):
                self.fail('Guard must not yield')

    def test_no_console_preserves_explicit_control_paths(self):
        calls = []
        @contextmanager
        def idle():
            calls.append('begin')
            try:
                yield {'system_idle_inhibited': True}
            finally:
                calls.append('restore')
        with keep_system_awake(_console=lambda: {'console_free_verified': True}, _idle=idle) as state:
            self.assertFalse(state['signal_handlers_changed'])
            self.assertFalse(state['job_controls_bypassed'])
        self.assertEqual(calls, ['begin', 'restore'])


if __name__ == '__main__':
    unittest.main()
