"""Small Windows integration boundary; imported safely on other systems for tests."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter


def clipboard_is_private() -> bool:
    if sys.platform != "win32":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    for name in ("ExcludeClipboardContentFromMonitorProcessing", "org.nspasteboard.ConcealedType"):
        if user32.IsClipboardFormatAvailable(user32.RegisterClipboardFormatW(name)):
            return True
    # Honor apps that explicitly opt out of Windows clipboard history.
    fmt = user32.RegisterClipboardFormatW("CanIncludeInClipboardHistory")
    if not user32.IsClipboardFormatAvailable(fmt):
        return False
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    if not user32.OpenClipboard(None):
        return True  # Busy/private clipboard: skip rather than bypass policy.
    try:
        handle = user32.GetClipboardData(fmt)
        if not handle or kernel32.GlobalSize(handle) < 4:
            return True
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return True
        try:
            return ctypes.c_uint32.from_address(pointer).value == 0
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


class HotkeyFilter(QAbstractNativeEventFilter):
    ID = 0xC710

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = False
        if sys.platform == "win32":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            self.registered = bool(user32.RegisterHotKey(None, self.ID, 0x4000 | 0x0001 | 0x0002, 0x20))

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == self.ID:
                self.callback()
                return True, 0
        return False, 0

    def close(self):
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.ID)
            self.registered = False
