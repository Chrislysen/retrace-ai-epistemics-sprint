"""Require a console-free actual worker, then inhibit only idle system sleep."""
from contextlib import contextmanager
import ctypes
import os
from scripts.host_guard_v6m import keep_system_awake as idle_guard


def console_state():
    if os.name != 'nt':
        raise RuntimeError('Windows console verification required')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetConsoleWindow.restype = ctypes.c_void_p
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(ctypes.c_uint), ctypes.c_uint]
    kernel.GetConsoleProcessList.restype = ctypes.c_uint
    window = kernel.GetConsoleWindow()
    ids = (ctypes.c_uint * 2)()
    ctypes.set_last_error(0)
    count = kernel.GetConsoleProcessList(ids, 2)
    error = ctypes.get_last_error()
    return {'console_window_present': bool(window), 'console_process_count': count,
            'console_query_error': error,
            'console_free_verified': not window and count == 0 and error == 6}


@contextmanager
def keep_system_awake(*, _console=None, _idle=None):
    state = (_console or console_state)()
    if state.get('console_free_verified') is not True:
        raise RuntimeError('Actual worker has a console; no inference started')
    with (_idle or idle_guard)() as idle:
        yield {**idle, **state, 'signal_handlers_changed': False, 'job_controls_bypassed': False}
