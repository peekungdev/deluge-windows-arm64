"""Subset of pywin32's win32event used by Deluge (single-instance mutex)."""

import ctypes
from ctypes import wintypes

from _win32_lasterror import set_last_error

_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE


def CreateMutex(security_attributes, initial_owner, name):
    """Create a named mutex and record GetLastError for the caller.

    Deluge calls CreateMutex then immediately win32api.GetLastError() to detect
    ERROR_ALREADY_EXISTS, so the error code is stashed here before any other
    FFI call can overwrite the thread's real last-error value.
    """
    handle = _kernel32.CreateMutexW(None, bool(initial_owner), name)
    set_last_error(ctypes.get_last_error())
    return int(handle) if handle else 0
