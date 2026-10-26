from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from cyclop_windows.core import (
    Store, ClipboardHistory, calendar_events, convert_currency,
    meeting_link, normalise_paths, sensitive_formats, translation_direction,
)


def test_atomic_unicode_roundtrip(tmp_path):
    store = Store(tmp_path)
    original = [{"title": "Адрес", "text": "Lappeenranta\nSuomi"}]
    store.save("snippets", original)
    assert store.load("snippets", []) == original
    assert not list(tmp_path.glob(".snippets-*"))


def test_corrupt_json_is_preserved(tmp_path):
    (tmp_path / "notes.json").write_text("broken}")
    store = Store(tmp_path)
    assert store.load("notes", []) == []
    backups = list(tmp_path.glob("notes.invalid-*.json"))
    assert len(backups) == 1 and backups[0].read_text() == "broken}"
    assert store.warnings


def test_history_is_bounded_deduplicated_and_session_only():
    history = ClipboardHistory(3)
    for value in ["one", "two", "three", "four", "two"]:
        history.add(value)
    assert history.items == ["two", "four", "three"]
    assert not history.add("two")
    assert not history.add(" ")
    assert not history.add("x" * 100001)
    assert ClipboardHistory().items == []


def test_secret_format_policy():
    assert sensitive_formats(["ExcludeClipboardContentFromMonitorProcessing"])
    assert sensitive_formats(["org.nspasteboard.ConcealedType", "text/plain"])
    assert not sensitive_formats(["text/plain"])


def test_shelf_only_keeps_existing_unique_paths(tmp_path):
    file = tmp_path / "file.txt"
    file.touch()
    assert normalise_paths([str(file), str(file), str(tmp_path / "missing")]) == [str(file)]


def test_conversion_and_invalid_values():
    rates = {"EUR": 1, "USD": 1.1, "GBP": .88}
    assert convert_currency("100", "USD", "GBP", rates) == "80.00"
    assert convert_currency("12,5", "EUR", "USD", rates) == "13.75"
    for value in ("NaN", "Infinity", "hello", ""):
        with pytest.raises(ValueError):
            convert_currency(value, "EUR", "USD", rates)
    with pytest.raises(ValueError):
        convert_currency("1", "EUR", "XYZ", rates)


def test_meeting_links_reject_lookalike_domains_and_schemes():
    assert meeting_link("Join https://meet.google.com/abc-defg-hij.") == "https://meet.google.com/abc-defg-hij"
    assert meeting_link("https://zoom.us.evil.example/j/123") is None
    assert meeting_link("file:///tmp/a.exe") is None
    assert meeting_link("https://evilzoom.us/a") is None
    assert meeting_link("https://sub.zoom.us/j/123") == "https://sub.zoom.us/j/123"


def test_translation_direction():
    assert translation_direction("Привет") == ("ru", "en")
    assert translation_direction("Hello") == ("en", "ru")


def test_calendar_recurrence_timezone_cancellation_and_all_day():
    data = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Cyclop//Tests//EN\r
BEGIN:VEVENT\r
UID:recurring\r
DTSTART:20261025T100000Z\r
DTEND:20261025T110000Z\r
RRULE:FREQ=DAILY;COUNT=4\r
EXDATE:20261027T100000Z\r
SUMMARY:Daily meeting\r
DESCRIPTION:Join https://meet.google.com/abc-defg-hij\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:all-day\r
DTSTART;VALUE=DATE:20261028\r
DTEND;VALUE=DATE:20261029\r
SUMMARY:Conference\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:cancelled\r
DTSTART:20261026T100000Z\r
DTEND:20261026T110000Z\r
STATUS:CANCELLED\r
SUMMARY:Cancelled\r
END:VEVENT\r
END:VCALENDAR\r
"""
    events = calendar_events(data, datetime(2026, 10, 26, 8, tzinfo=timezone.utc))
    assert [e.title for e in events] == ["Daily meeting", "Conference", "Daily meeting"]
    assert events[0].link == "https://meet.google.com/abc-defg-hij"
    assert events[1].all_day
    assert all(e.start.tzinfo is not None for e in events)


def test_calendar_size_limit():
    with pytest.raises(ValueError, match="10 MB"):
        calendar_events(b"x" * 10_000_001)


def test_calendar_rejects_unbounded_high_frequency_expansion():
    data = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x\r\nDTSTART:20261026T080000Z\r\nRRULE:FREQ=SECONDLY\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    with pytest.raises(ValueError, match="recurrences"):
        calendar_events(data, datetime(2026, 10, 26, 8, tzinfo=timezone.utc))
