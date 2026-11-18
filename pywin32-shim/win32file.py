"""Subset of pywin32's win32file used by Deluge (free-space query)."""

import ctypes
from ctypes import wintypes

from _win32_lasterror import set_last_error

_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

_kernel32.GetDiskFreeSpaceExW.argtypes = [
    wintypes.LPCWSTR,
    ctypes.POINTER(ctypes.c_ulonglong),
    ctypes.POINTER(ctypes.c_ulonglong),
    ctypes.POINTER(ctypes.c_ulonglong),
]
_kernel32.GetDiskFreeSpaceExW.restype = wintypes.BOOL


def GetDiskFreeSpaceEx(path):
    """Return (free_to_caller, total_bytes, total_free) for `path`."""
    free_to_caller = ctypes.c_ulonglong(0)
    total_bytes = ctypes.c_ulonglong(0)
    total_free = ctypes.c_ulonglong(0)
    ok = _kernel32.GetDiskFreeSpaceExW(
        str(path),
        ctypes.byref(free_to_caller),
        ctypes.byref(total_bytes),
        ctypes.byref(total_free),
    )
    err = ctypes.get_last_error()
    set_last_error(err)
    if not ok:
        raise OSError(0, ctypes.FormatError(err), path, err)
    return (free_to_caller.value, total_bytes.value, total_free.value)
