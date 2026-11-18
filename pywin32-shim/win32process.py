"""Subset of pywin32's win32process used by Deluge (running-pid check)."""

import ctypes
from ctypes import wintypes

from _win32_lasterror import set_last_error

_psapi = ctypes.WinDLL('psapi', use_last_error=True)

_psapi.EnumProcesses.argtypes = [
    ctypes.POINTER(wintypes.DWORD),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
_psapi.EnumProcesses.restype = wintypes.BOOL


def EnumProcesses():
    """Return a tuple of the pids of all processes we can enumerate."""
    count = 1024
    while True:
        buf = (wintypes.DWORD * count)()
        needed = wintypes.DWORD(0)
        ok = _psapi.EnumProcesses(buf, ctypes.sizeof(buf), ctypes.byref(needed))
        set_last_error(ctypes.get_last_error())
        if not ok:
            return ()
        returned = needed.value // ctypes.sizeof(wintypes.DWORD)
        # A full buffer means the list was truncated; grow and retry.
        if returned < count:
            return tuple(buf[:returned])
        count *= 2
