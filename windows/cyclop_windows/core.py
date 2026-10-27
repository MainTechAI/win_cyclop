"""UI-independent persistence, clipboard policy, calendar and conversion logic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
import copy
import json
import math
import os
import re
import tempfile

HOTKEYS = {
    "panel": ("Show or hide the panel", "Ctrl+Alt+Space"),
    "ocr": ("Capture text from a screen area", "Ctrl+Shift+X"),
    "define": ("Define the selected word", "Ctrl+Alt+D"),
    "translate": ("Translate the selected text", "Ctrl+Alt+T"),
    "voice": ("Listen for a voice command", "Ctrl+Alt+V"),
}

IRIS_COLORS = {"Red": "#ff3b30", "Teal": "#3fd6c6", "Violet": "#9b7bff", "Amber": "#ffb347", "Green": "#6ee07a", "Blue": "#5aa9ff"}

DEFAULTS = {
    "clipboard_enabled": False,
    "capture_images": False,
    "hover_open": True,
    "hover_tabs": True,
    "screen": "",
    "disabled_tabs": [],
    "calendar_path": "",
    # Panel behaviour
    "tab_cycling": True,
    # Mascot
    "mascot_enabled": True,
    "mascot_autohide": True,
    "mascot_autohide_seconds": 8,
    "mascot_follow_cursor": True,
    "mascot_iris": "Red",
    # System stats under the mascot
    "stats_enabled": True,
    "stats_items": ["cpu", "ram", "gpu", "temp"],
    # Features
    "ocr_enabled": True,
    "lookup_enabled": True,
    "lookup_online": True,
    "voice_enabled": False,
    "awake_enabled": True,
    "volume_enabled": True,
    "whisper_model": "base",
    "speech_language": "auto",
    "hotkeys": {key: value[1] for key, value in HOTKEYS.items()},
    "config_version": 3,
}
CONFIG_VERSION = 3

STAT_KEYS = {"cpu": "CPU", "ram": "RAM", "gpu": "GPU", "temp": "Temp"}


def normalise_config(config: dict) -> dict:
    """Repair types of user-editable values so a bad file can never crash startup."""
    result = copy.deepcopy(DEFAULTS)
    version = config.get("config_version", 1) if isinstance(config.get("config_version"), int) else 1
    for key, value in config.items():
        if key not in DEFAULTS:
            result[key] = value
        elif isinstance(DEFAULTS[key], bool):
            result[key] = bool(value) if isinstance(value, (bool, int)) else DEFAULTS[key]
        elif isinstance(DEFAULTS[key], int):
            result[key] = int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else DEFAULTS[key]
        elif isinstance(value, type(DEFAULTS[key])):
            result[key] = value
    result["mascot_autohide_seconds"] = min(120, max(2, result["mascot_autohide_seconds"]))
    result["stats_items"] = [item for item in result["stats_items"] if item in STAT_KEYS]
    hotkeys = dict(DEFAULTS["hotkeys"])
    hotkeys.update({k: v for k, v in result["hotkeys"].items() if k in HOTKEYS and isinstance(v, str)})
    result["hotkeys"] = hotkeys
    if result["mascot_iris"] not in IRIS_COLORS:
        result["mascot_iris"] = DEFAULTS["mascot_iris"]
    if result["whisper_model"] not in ("tiny", "base", "small"):
        result["whisper_model"] = DEFAULTS["whisper_model"]
    if result["speech_language"] not in ("auto", "en", "ru"):
        result["speech_language"] = "auto"
    if version < 3:
        # 0.2.0 saved stats as off by default; 0.2.1 shows them unless turned off since.
        result["stats_enabled"] = True
    result["config_version"] = CONFIG_VERSION
    return result


MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008, "meta": 0x0008}
NAMED_KEYS = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
              "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E, "home": 0x24, "end": 0x23,
              "pgup": 0x21, "pageup": 0x21, "pgdown": 0x22, "pagedown": 0x22,
              "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
              "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
              ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC}


def parse_hotkey(text: str) -> tuple[int, int]:
    """Convert "Ctrl+Shift+X" into Win32 RegisterHotKey (modifiers, virtual key)."""
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+")]
    if len(parts) < 2 or not all(parts):
        raise ValueError("Use at least one modifier and one key, e.g. Ctrl+Shift+X")
    *mods, key = parts
    modifiers = 0
    for mod in mods:
        if mod not in MODIFIERS:
            raise ValueError(f"Unknown modifier: {mod}")
        modifiers |= MODIFIERS[mod]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", key):
        vk = 0x6F + int(key[1:])
    elif key in NAMED_KEYS:
        vk = NAMED_KEYS[key]
    else:
        raise ValueError(f"Unsupported key: {key}")
    return modifiers, vk


def cycle(order: list[str], current: str, step: int) -> str:
    """Next item in a ring: moving past the last tab returns to the first."""
    if not order:
        return current
    if current not in order:
        return order[0]
    return order[(order.index(current) + step) % len(order)]


def stat_color(key: str, value: float | None) -> str:
    if value is None:
        return "#6b6b6b"
    low, high = (60, 80) if key == "temp" else (50, 80)
    return "#6ee07a" if value < low else "#ffcc4d" if value < high else "#ff5f57"


def stat_label(key: str, value: float | None) -> str:
    if value is None:
        return f"{STAT_KEYS[key]} –"
    return f"{STAT_KEYS[key]} {value:.0f}°" if key == "temp" else f"{STAT_KEYS[key]} {value:.0f}%"


# ---------------------------------------------------------------- voice commands
APPS = {
    "notepad": ("Notepad", "notepad.exe"), "блокнот": ("Notepad", "notepad.exe"),
    "calculator": ("Calculator", "calc.exe"), "калькулятор": ("Calculator", "calc.exe"),
    "explorer": ("File Explorer", "explorer.exe"), "files": ("File Explorer", "explorer.exe"), "проводник": ("File Explorer", "explorer.exe"),
    "paint": ("Paint", "mspaint.exe"), "пейнт": ("Paint", "mspaint.exe"),
    "task manager": ("Task Manager", "taskmgr.exe"), "диспетчер задач": ("Task Manager", "taskmgr.exe"),
    "settings": ("Settings", "ms-settings:"), "настройки": ("Settings", "ms-settings:"), "параметры": ("Settings", "ms-settings:"),
    "terminal": ("Terminal", "wt.exe"), "терминал": ("Terminal", "wt.exe"),
    "browser": ("Browser", "https://www.bing.com"), "браузер": ("Browser", "https://www.bing.com"),
    "youtube": ("YouTube", "https://www.youtube.com"), "ютуб": ("YouTube", "https://www.youtube.com"),
    "snipping tool": ("Snipping Tool", "ms-screenclip:"), "ножницы": ("Snipping Tool", "ms-screenclip:"),
}

TAB_WORDS = {
    "music": "music", "музыка": "music", "media": "music", "shelf": "shelf", "полка": "shelf",
    "clipboard": "clipboard", "буфер": "clipboard", "snippets": "snippets", "calendar": "calendar",
    "календарь": "calendar", "translator": "translate", "переводчик": "translate", "notes": "notes",
    "заметки": "notes", "currency": "currency", "валюта": "currency", "валюты": "currency",
    "teleprompter": "teleprompter", "телесуфлер": "teleprompter", "recorder": "recorder",
    "диктофон": "recorder", "запись": "recorder",
}

_PHRASES = [
    (r"\b(volume up|louder|turn it up|громче|прибавь)\b", {"action": "key", "key": "volume_up"}),
    (r"\b(volume down|quieter|turn it down|тише|убавь)\b", {"action": "key", "key": "volume_down"}),
    (r"\b(mute|unmute|выключи звук|включи звук|без звука)\b", {"action": "key", "key": "mute"}),
    (r"\b(next( track| song)?|skip|следующ\w*|дальше)\b", {"action": "key", "key": "next"}),
    (r"\b(previous( track| song)?|go back|предыдущ\w*|назад)\b", {"action": "key", "key": "previous"}),
    (r"\b(pause|play|resume|stop the music|пауза|продолжи|воспроизвед\w*|стоп)\b", {"action": "key", "key": "play"}),
    (r"\b(lock( the)?( screen| computer| pc)?|заблокируй|блокировка)\b", {"action": "lock"}),
    (r"\b(capture text|read the screen|text capture|распознай|скопируй текст с экрана)\b", {"action": "ocr"}),
    (r"\b(stay awake|keep awake|не засыпай|не спи)\b", {"action": "awake", "value": True}),
    (r"\b(allow sleep|you can sleep|можно спать|разреши сон)\b", {"action": "awake", "value": False}),
    (r"\b(what time|time is it|который час|сколько времени)\b", {"action": "time"}),
    (r"\b(start recording|record audio|начни запись|запиши)\b", {"action": "record"}),
    (r"\b(hide|close the panel|скрой|закрой панель)\b", {"action": "panel", "value": False}),
]


def parse_command(text: str) -> dict:
    """Map a transcript onto an allow-listed action. Unknown speech never runs anything."""
    spoken = " ".join(re.sub(r"[^\w\s'-]", " ", text.lower()).split())
    if not spoken:
        return {"action": "none", "text": text}
    search = re.match(r"^(?:please )?(?:search(?: for)?|google|look up|найди|поищи|загугли)\s+(.+)$", spoken)
    if search:
        return {"action": "search", "query": search.group(1)}
    opening = re.match(r"^(?:please )?(?:open|launch|start|run|show|открой|запусти|покажи|включи)\s+(?:the |my )?(.+)$", spoken)
    if opening:
        target = opening.group(1).strip()
        for word, tab in TAB_WORDS.items():
            if target == word or target.startswith(word + " "):
                return {"action": "tab", "tab": tab}
        for word in sorted(APPS, key=len, reverse=True):
            if target == word or target.startswith(word):
                name, command = APPS[word]
                return {"action": "open", "name": name, "target": command}
    for pattern, intent in _PHRASES:
        if re.search(pattern, spoken):
            return dict(intent)
    return {"action": "none", "text": text}


# ---------------------------------------------------------------- dictionary
def lookup_word(text: str) -> str | None:
    """A definable term: one word or a short hyphenated/compound expression."""
    term = text.strip().strip(".,;:!?\"'«»“”„‘’()[]{} ")
    if not term or len(term) > 48 or "\n" in term or len(term.split()) > 3:
        return None
    return term


def parse_wiktionary(payload: dict, prefer: tuple[str, ...] = ("en", "ru")) -> list[tuple[str, str]]:
    """Flatten Wiktionary REST definitions into (part of speech, plain text) pairs."""
    entries = []
    languages = list(prefer) + [code for code in payload if code not in prefer]
    for code in languages:
        for entry in payload.get(code, []) if isinstance(payload.get(code), list) else []:
            part = str(entry.get("partOfSpeech", ""))
            for definition in entry.get("definitions", [])[:4]:
                plain = re.sub(r"<[^>]+>", "", str(definition.get("definition", "")))
                plain = " ".join(plain.replace("&nbsp;", " ").replace("&amp;", "&").split())
                if plain:
                    entries.append((part, plain))
        if entries:
            break
    return entries[:8]


def data_directory() -> Path:
    root = os.environ.get("CYCLOP_DATA_DIR")
    if root:
        return Path(root)
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "CyclopWindows"


class Store:
    """Atomic JSON writes; corrupt data is preserved for recovery, never overwritten."""
    def __init__(self, directory: Path | None = None):
        self.directory = directory or data_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.warnings: list[str] = []

    def load(self, name: str, fallback):
        path = self.directory / f"{name}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, type(fallback)):
                raise ValueError("Unexpected document structure")
            return data
        except FileNotFoundError:
            return copy.deepcopy(fallback)
        except (ValueError, OSError) as exc:
            if path.exists():
                backup = path.with_name(f"{name}.invalid-{datetime.now():%Y%m%d-%H%M%S-%f}.json")
                path.replace(backup)
                self.warnings.append(f"Recovered {name}; original saved as {backup.name}: {exc}")
            return copy.deepcopy(fallback)

    def save(self, name: str, value):
        fd, temporary = tempfile.mkstemp(prefix=f".{name}-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f"{name}.json")
        finally:
            Path(temporary).unlink(missing_ok=True)


class ClipboardHistory:
    """Session-only, bounded and deduplicated. Never written to disk."""
    def __init__(self, limit=40):
        self.limit = limit
        self.items: list[str] = []

    def add(self, text: str) -> bool:
        if not text.strip() or len(text) > 100_000:
            return False
        if self.items and self.items[0] == text:
            return False
        if text in self.items:
            self.items.remove(text)
        self.items.insert(0, text)
        del self.items[self.limit:]
        return True


SECRET_FORMATS = {
    "excludeclipboardcontentfrommonitorprocessing",
    "org.nspasteboard.concealedtype",
    "application/x-keepassxc",
}


def sensitive_formats(formats) -> bool:
    return bool(SECRET_FORMATS.intersection(str(f).lower() for f in formats))


def normalise_paths(paths) -> list[str]:
    result, seen = [], set()
    for value in paths:
        path = Path(value).expanduser().resolve()
        key = os.path.normcase(str(path))
        if path.exists() and key not in seen:
            result.append(str(path))
            seen.add(key)
    return result


def convert_currency(amount: str, source: str, target: str, rates: dict) -> str:
    try:
        number = Decimal(amount.strip().replace(",", "."))
        base, quote = Decimal(str(rates[source])), Decimal(str(rates[target]))
        if not number.is_finite() or not base.is_finite() or not quote.is_finite() or base <= 0 or quote <= 0:
            raise ValueError("Invalid amount or exchange rate")
        return f"{number * quote / base:.2f}"
    except (InvalidOperation, KeyError, ZeroDivisionError) as exc:
        raise ValueError("Enter a number and select supported currencies") from exc


def translation_direction(text: str) -> tuple[str, str]:
    return ("ru", "en") if re.search(r"[А-Яа-яЁё]", text) else ("en", "ru")


MEETING_HOSTS = ("zoom.us", "zoom.com", "meet.google.com", "teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft", "webex.com", "whereby.com", "meet.jit.si", "telemost.yandex.ru", "discord.com", "discord.gg")


def meeting_link(text: str) -> str | None:
    for match in re.findall(r"https://[^\s<>\"']+", text):
        url = match.rstrip(".,;)]}")
        host = (urlparse(url).hostname or "").lower()
        if any(host == allowed or host.endswith("." + allowed) for allowed in MEETING_HOSTS):
            return url
    return None


@dataclass(frozen=True)
class Meeting:
    title: str
    start: datetime
    end: datetime
    link: str | None
    all_day: bool


def calendar_events(payload: bytes, now: datetime | None = None) -> list[Meeting]:
    from icalendar import Calendar
    import recurring_ical_events

    if len(payload) > 10_000_000:
        raise ValueError("Calendar is larger than the 10 MB limit")
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        raise ValueError("Calendar range must include a timezone")
    end_range = now + timedelta(days=7)
    calendar = Calendar.from_ical(payload)
    components = list(calendar.walk("VEVENT"))
    if len(components) > 2000:
        raise ValueError("Calendar contains more than 2,000 event definitions")
    for event in components:
        rule = event.get("RRULE")
        if rule and any(str(freq).upper() in {"SECONDLY", "MINUTELY"} for freq in rule.get("FREQ", [])):
            raise ValueError("Second-by-second and minute-by-minute calendar recurrences are not supported")
    result = []
    for event in recurring_ical_events.of(calendar).between(now - timedelta(days=1), end_range):
        if str(event.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start = event.decoded("DTSTART")
        all_day = not isinstance(start, datetime)
        end = event.decoded("DTEND", start + (timedelta(days=1) if all_day else timedelta(hours=1)))
        def aware(value):
            if not isinstance(value, datetime):
                value = datetime.combine(value, time.min)
            return value.replace(tzinfo=now.tzinfo) if value.tzinfo is None else value.astimezone(now.tzinfo)
        start, end = aware(start), aware(end)
        if end <= now or start > end_range:
            continue
        body = " ".join(str(event.get(key, "")) for key in ("URL", "DESCRIPTION", "LOCATION"))
        result.append(Meeting(str(event.get("SUMMARY", "Untitled event")), start, end, meeting_link(body), all_day))
    return sorted(result, key=lambda meeting: meeting.start)[:200]


def seconds_label(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "0:00"
    value = int(seconds)
    return f"{value // 60}:{value % 60:02}"
