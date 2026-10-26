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

DEFAULTS = {
    "clipboard_enabled": False,
    "capture_images": False,
    "hover_open": True,
    "hover_tabs": True,
    "screen": "",
    "disabled_tabs": [],
    "calendar_path": "",
}


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
