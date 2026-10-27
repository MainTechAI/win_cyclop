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
    """Owns every global shortcut. Each named action has one Win32 hotkey id."""
    BASE_ID = 0xC710
    MOD_NOREPEAT = 0x4000

    def __init__(self, callback=None):
        super().__init__()
        self.actions: dict[str, tuple[int, object]] = {}
        self.registered_ids: set[int] = set()
        self.user32 = None
        if sys.platform == "win32":
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        if callback is not None:
            self.set("panel", "Ctrl+Alt+Space", callback)

    @property
    def registered(self):
        return self.is_registered("panel")

    def is_registered(self, name):
        entry = self.actions.get(name)
        return bool(entry and entry[0] in self.registered_ids)

    def set(self, name, text, callback):
        """Register or replace a hotkey. Returns None, or a message explaining the failure."""
        from .core import parse_hotkey
        self.remove(name)
        identifier = self._id(name)
        self.actions[name] = (identifier, callback)
        try:
            modifiers, key = parse_hotkey(text)
        except ValueError as exc:
            return str(exc)
        if self.user32 is None:
            return None
        if self.user32.RegisterHotKey(None, identifier, modifiers | self.MOD_NOREPEAT, key):
            self.registered_ids.add(identifier)
            return None
        return f"{text} is already used by another app"

    def _id(self, name):
        from .core import HOTKEYS
        names = list(HOTKEYS)
        if name not in names:
            raise KeyError(f"Unknown hotkey action: {name}")
        return self.BASE_ID + names.index(name)

    def remove(self, name):
        entry = self.actions.pop(name, None)
        if entry and entry[0] in self.registered_ids:
            self.user32.UnregisterHotKey(None, entry[0])
            self.registered_ids.discard(entry[0])

    def trigger(self, name):
        entry = self.actions.get(name)
        if entry:
            entry[1]()

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312:
                for identifier, callback in list(self.actions.values()):
                    if msg.wParam == identifier:
                        callback()
                        return True, 0
        return False, 0

    def close(self):
        for name in list(self.actions):
            self.remove(name)


# ---------------------------------------------------------------- power, keys, shell
ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002


def keep_awake(enabled: bool) -> bool:
    """Prevent sleep and screen-off while enabled. Applies to the calling (GUI) thread."""
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
    kernel32.SetThreadExecutionState.restype = wintypes.DWORD
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if enabled else 0)
    return kernel32.SetThreadExecutionState(flags) != 0


VK = {"volume_mute": 0xAD, "mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
      "next": 0xB0, "previous": 0xB1, "play": 0xB3, "control": 0x11, "c": 0x43}
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002


def press_key(name: str, repeat: int = 1):
    if sys.platform != "win32":
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    code = VK[name]
    for _ in range(repeat):
        user32.keybd_event(code, 0, KEYEVENTF_EXTENDEDKEY, 0)
        user32.keybd_event(code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


def modifiers_down() -> bool:
    if sys.platform != "win32":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAsyncKeyState.restype = ctypes.c_short
    return any(user32.GetAsyncKeyState(code) & 0x8000 for code in (0x10, 0x11, 0x12, 0x5B, 0x5C))


def send_copy():
    """Synthesise Ctrl+C in the foreground app to read its current selection."""
    if sys.platform != "win32":
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.keybd_event(VK["control"], 0, 0, 0)
    user32.keybd_event(VK["c"], 0, 0, 0)
    user32.keybd_event(VK["c"], 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK["control"], 0, KEYEVENTF_KEYUP, 0)


def clipboard_sequence() -> int:
    if sys.platform != "win32":
        return 0
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    return int(user32.GetClipboardSequenceNumber())


def lock_workstation() -> bool:
    if sys.platform != "win32":
        return False
    return bool(ctypes.WinDLL("user32", use_last_error=True).LockWorkStation())


def open_target(target: str):
    """ShellExecute an allow-listed program, settings URI or web URL."""
    import os
    if sys.platform != "win32":
        raise RuntimeError("Opening apps is available on Windows")
    try:
        os.startfile(target)
    except OSError:
        if target == "wt.exe":
            os.startfile("cmd.exe")
        else:
            raise


# ---------------------------------------------------------------- performance counters
PDH_FMT_DOUBLE, PDH_FMT_NOCAP100, PDH_MORE_DATA = 0x00000200, 0x00008000, 0x800007D2


class _PdhUnion(ctypes.Union):
    _fields_ = [("longValue", ctypes.c_long), ("doubleValue", ctypes.c_double),
                ("largeValue", ctypes.c_longlong), ("stringValue", ctypes.c_void_p)]


class _PdhValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("value", _PdhUnion)]


class _PdhItem(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _PdhValue)]


class PerformanceCounters:
    """GPU 3D-engine utilisation and ACPI thermal zones through PDH (no admin rights)."""
    PATHS = {
        "gpu": r"\GPU Engine(*engtype_3D)\Utilization Percentage",
        "thermal": r"\Thermal Zone Information(*)\Temperature",
    }

    def __init__(self):
        self.query = None
        self.counters = {}
        if sys.platform != "win32":
            return
        try:
            self.pdh = ctypes.WinDLL("pdh")
            self.pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
            self.pdh.PdhOpenQueryW.restype = wintypes.DWORD
            self.pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
            self.pdh.PdhAddEnglishCounterW.restype = wintypes.DWORD
            self.pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            self.pdh.PdhCollectQueryData.restype = wintypes.DWORD
            self.pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            self.pdh.PdhGetFormattedCounterArrayW.restype = wintypes.DWORD
            self.pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
            query = ctypes.c_void_p()
            if self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0:
                return
            self.query = query
            for name, path in self.PATHS.items():
                counter = ctypes.c_void_p()
                if self.pdh.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(counter)) == 0:
                    self.counters[name] = counter
            self.pdh.PdhCollectQueryData(query)
        except (OSError, AttributeError):
            self.query = None

    def _values(self, counter):
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = self.pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, ctypes.byref(size), ctypes.byref(count), None)
        if status != PDH_MORE_DATA or size.value == 0:
            return []
        buffer = (ctypes.c_byte * size.value)()
        if self.pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, ctypes.byref(size), ctypes.byref(count), buffer) != 0:
            return []
        items = ctypes.cast(buffer, ctypes.POINTER(_PdhItem))
        return [items[i].FmtValue.value.doubleValue for i in range(count.value) if items[i].FmtValue.CStatus in (0, 1)]

    def sample(self) -> dict:
        if self.query is None:
            return {}
        if self.pdh.PdhCollectQueryData(self.query) != 0:
            return {}
        result = {}
        if "gpu" in self.counters:
            values = self._values(self.counters["gpu"])
            if values:
                result["gpu"] = min(100.0, sum(values))
        if "thermal" in self.counters:
            values = [v - 273.15 if v > 200 else v for v in self._values(self.counters["thermal"])]
            values = [v for v in values if 5 < v < 125]
            if values:
                result["temp"] = max(values)
        return result

    def close(self):
        if self.query is not None:
            self.pdh.PdhCloseQuery(self.query)
            self.query = None


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def last_input_tick() -> int:
    """Tick count of the last keyboard or mouse input anywhere (0 if unknown)."""
    if sys.platform != "win32":
        return 0
    info = _LastInputInfo(ctypes.sizeof(_LastInputInfo), 0)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LastInputInfo)]
    if user32.GetLastInputInfo(ctypes.byref(info)):
        return int(info.dwTime)
    return 0
