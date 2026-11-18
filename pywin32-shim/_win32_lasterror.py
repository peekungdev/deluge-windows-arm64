"""Shared last-error slot for the minimal pywin32 shim.

pywin32's win32api.GetLastError() returns the calling thread's real
GetLastError(). Under ctypes an intervening FFI call can clobber that value
before Python gets to read it, so every shim entry point that Deluge pairs
with a GetLastError() check records the error here instead.
"""

import threading

_state = threading.local()


def set_last_error(err):
    _state.value = err


def get_last_error():
    return getattr(_state, 'value', 0)
