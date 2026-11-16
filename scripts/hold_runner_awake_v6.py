"""Hold a temporary system-sleep lease only while one verified runner lives.

Does not change power settings or keep the display awake. User-initiated sleep
is not prevented. The OS releases the lease when this helper exits.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise RuntimeError('This scoped helper is Windows-only')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.QueryFullProcessImageNameW.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.SetThreadExecutionState.argtypes = [wintypes.DWORD]
    api.SetThreadExecutionState.restype = wintypes.DWORD
    handle = api.OpenProcess(0x100000 | 0x1000, False, args.pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        text = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(text))
        if not api.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        if Path(text.value).resolve() != Path(sys.executable).resolve():
            raise ValueError('Target must use this study Python executable')
        with args.journal.open('x', encoding='utf-8', newline='\n') as journal:
            def record(event):
                journal.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                                          'pid': args.pid, 'event': event}) + '\n')
                journal.flush()
            if not api.SetThreadExecutionState(0x80000000 | 0x1):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                record('system_sleep_lease_acquired_display_unchanged')
                while True:
                    state = api.WaitForSingleObject(handle, 60000)
                    if state == 0:
                        record('runner_exited')
                        break
                    if state != 258:
                        raise ctypes.WinError(ctypes.get_last_error())
            finally:
                api.SetThreadExecutionState(0x80000000)
                record('system_sleep_lease_released')
    finally:
        api.CloseHandle(handle)


if __name__ == '__main__':
    main()
