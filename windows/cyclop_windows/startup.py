"""Startup timing: when each stage was reached, in ms since Cyclop was launched.

The one-file exe first runs a small bootloader that unpacks the app and then starts
it as a child process with the same name, so "launched" is the bootloader's start.
"""
from __future__ import annotations

import time

marks: dict[str, float] = {}


def mark(name: str):
    marks.setdefault(name, time.time())


def launched_at() -> float | None:
    try:
        import psutil
        process = psutil.Process()
        created = process.create_time()
        parent = process.parent()
        if parent is not None and parent.name().lower() == process.name().lower():
            created = parent.create_time()
        return created
    except Exception:
        return None


def report() -> dict[str, int]:
    origin = launched_at() or min(marks.values(), default=time.time())
    return {name: round((moment - origin) * 1000) for name, moment in sorted(marks.items(), key=lambda item: item[1])}
