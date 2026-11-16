"""Temporary per-thread idle-sleep inhibition for the authorized serial job.

No display/away-mode flags or persistent Windows power-setting changes.
Manual sleep, a closed lid and restart are not prevented.
API: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate
"""
from contextlib import contextmanager
import ctypes
import os

CONTINUOUS = 0x80000000
SYSTEM_REQUIRED = 0x00000001


@contextmanager
def keep_system_awake(*, _set_state=None):
    if _set_state is None:
        if os.name != 'nt':
            raise RuntimeError('Windows host execution guard required for this run')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        _set_state = kernel.SetThreadExecutionState
        _set_state.argtypes = [ctypes.c_uint]
        _set_state.restype = ctypes.c_uint
    previous = _set_state(CONTINUOUS | SYSTEM_REQUIRED)
    if not previous:
        raise RuntimeError('Host idle-sleep request failed; no inference started')
    try:
        yield {'system_idle_inhibited': True, 'display_required': False,
               'away_mode_enabled': False, 'persistent_settings_changed': False,
               'manual_sleep_or_restart_prevented': False}
    finally:
        if not _set_state(previous):
            raise RuntimeError('Host execution-state restoration failed')
