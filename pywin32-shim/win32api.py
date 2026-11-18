"""Subset of pywin32's win32api used by Deluge, implemented with ctypes.

Only the four entry points Deluge actually calls are provided:
SetConsoleCtrlHandler, GetFileAttributes, GetLastError and CloseHandle.
"""

import ctypes
from ctypes import wintypes

from _win32_lasterror import get_last_error, set_last_error

_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

# BOOL WINAPI HandlerRoutine(DWORD dwCtrlType)
PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

_kernel32.SetConsoleCtrlHandler.argtypes = [PHANDLER_ROUTINE, wintypes.BOOL]
_kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL

_kernel32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetFileAttributesW.restype = wintypes.DWORD

_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

# The OS keeps only a pointer to the handler, so the ctypes trampolines have to
# outlive this call or the process faults when the console is closed.
_handlers = []


def SetConsoleCtrlHandler(handler, add=True):
    """Register a console control handler.

    Deluge calls this both as SetConsoleCtrlHandler(fn) and as
    SetConsoleCtrlHandler(fn, True), so `add` defaults to True.
    """

    def _trampoline(ctrl_type):
        result = handler(ctrl_type)
        # pywin32 treats a None return as "not handled", matching Win32.
        return bool(result)

    routine = PHANDLER_ROUTINE(_trampoline)
    if add:
        _handlers.append(routine)
    ok = _kernel32.SetConsoleCtrlHandler(routine, bool(add))
    set_last_error(ctypes.get_last_error())
    if not ok:
        # A GUI process with no console legitimately has nothing to hook; that
        # is not worth taking the whole UI down for.
        if add:
            _handlers.remove(routine)
        return False
    return True


def GetFileAttributes(filepath):
    """Return the file attribute bitmask for `filepath`.

    pywin32 raises on failure; Deluge's only caller guards against
    AttributeError/AssertionError, so an unreadable or vanished path would
    escape as an unhandled exception there. Returning 0 (no attributes set)
    keeps the file chooser alive and simply reports the entry as not hidden.
    """
    attrs = _kernel32.GetFileAttributesW(filepath)
    set_last_error(ctypes.get_last_error())
    if attrs == INVALID_FILE_ATTRIBUTES:
        return 0
    return attrs


def GetLastError():
    return get_last_error()


def CloseHandle(handle):
    if not handle:
        return
    ok = _kernel32.CloseHandle(wintypes.HANDLE(int(handle)))
    set_last_error(ctypes.get_last_error())
    return bool(ok)
