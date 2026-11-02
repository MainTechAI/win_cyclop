"""Profile Cyclop's start-up and rank what it spends time on.

    python scripts/profile-startup.py [--seconds 4] [--json out.json]

Starts the real app (with the user's settings in CYCLOP_DATA_DIR, or a fresh data
folder), times every feature as it is created and the background work each one
starts (WinRT media, PDH/NVIDIA sensors, the eye's first frames…), and prints them
ranked by cost. Each line: label, wall ms, and which thread it ran on.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import functools
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
T0 = time.perf_counter()
costs: dict[str, float] = defaultdict(float)
threads: dict[str, str] = {}
moments: dict[str, float] = {}
lock = threading.Lock()


def at(name):
    moments.setdefault(name, (time.perf_counter() - T0) * 1000)


def timed(owner, attribute, label):
    original = getattr(owner, attribute)

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            with lock:
                costs[label] += (time.perf_counter() - start) * 1000
                threads[label] = "main" if threading.current_thread() is threading.main_thread() else "background"
    setattr(owner, attribute, wrapper)


def timed_import(name, label):
    start = time.perf_counter()
    __import__(name)
    costs[label] += (time.perf_counter() - start) * 1000
    threads[label] = "main"


parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=float, default=4.0)
parser.add_argument("--json")
parser.add_argument("--log", help="write all output and any error here")
args = parser.parse_args()
if args.log:
    import faulthandler
    import traceback
    log = open(args.log, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    faulthandler.enable(log)

    def failed(kind, value, trace):
        traceback.print_exception(kind, value, trace, file=log)
        log.flush()
        os._exit(1)
    sys.excepthook = failed

timed_import("PySide6.QtWidgets", "import Qt (PySide6)")
timed_import("numpy", "import numpy")
timed_import("cyclop_windows.app", "import Cyclop modules")
at("imports done")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from cyclop_windows import app as A, camera, features, mascot, panes, popups, services, system, windows  # noqa: E402

for owner, attribute, label in [
    (panes.MediaPane, "__init__", "Music tab (widgets)"), (panes.ShelfPane, "__init__", "Shelf tab"),
    (panes.ClipboardPane, "__init__", "Clipboard tab"), (panes.SnippetsPane, "__init__", "Snippets tab"),
    (panes.CalendarPane, "__init__", "Calendar tab"), (panes.TranslatePane, "__init__", "Translate tab"),
    (panes.NotesPane, "__init__", "Notes tab"), (panes.CurrencyPane, "__init__", "Currency tab"),
    (panes.TeleprompterPane, "__init__", "Teleprompter tab"), (features.OcrPane, "__init__", "Text capture tab"),
    (features.RecorderPane, "__init__", "Recorder tab"), (features.SettingsPane, "__init__", "Settings tab"),
    (features.QuickSettings, "__init__", "Quick settings popup"), (features.VolumeControls, "__init__", "Volume controls"),
    (system.Volume, "__init__", "Volume check"), (mascot.MascotWindow, "__init__", "Cyclop eye window"),
    (mascot.EyeRenderer, "__init__", "Eye renderer setup"), (mascot.MascotWindow, "render_frame", "Eye frames (first seconds)"),
    (mascot.MascotWindow, "paintEvent", "Eye painting (first seconds)"), (mascot.MascotWindow, "tick", "Eye animation ticks (first seconds)"),
    (popups.SelectionGrabber, "__init__", "Selection lookup"), (camera.GazeCalibrator, "__init__", "Gaze calibrator"),
    (A.Cyclop, "build_tray", "Tray icon and menu"), (A.Cyclop, "register_hotkeys", "Global hotkeys"),
    (A.Cyclop, "update_camera", "Webcam check"), (windows.HotkeyFilter, "__init__", "Hotkey filter"),
    (system.StatsSampler, "__init__", "Stats sensors init (psutil, PDH, NVIDIA)"),
    (system.StatsSampler, "sample", "Stats sampling (first seconds)"),
    (A.Panel, "__init__", "Panel (all tabs)"), (A.Cyclop, "__init__", "Cyclop() total"),
]:
    if hasattr(owner, attribute):
        timed(owner, attribute, label)

# The media worker: time from its start to the first answer from Windows media sessions.
original_run = services.MediaWorker.run


def media_run(self):
    start = time.perf_counter()
    self.state.connect(lambda *_: costs.setdefault("Media sessions: first answer (WinRT)", (time.perf_counter() - start) * 1000), )
    self.playing.connect(lambda *_: costs.setdefault("Media sessions: first answer (WinRT)", (time.perf_counter() - start) * 1000))
    threads["Media sessions: first answer (WinRT)"] = "background"
    return original_run(self)


services.MediaWorker.run = media_run

app = QApplication(sys.argv[:1])
app.setQuitOnLastWindowClosed(False)
start = time.perf_counter()
app.setStyleSheet(A.STYLE)
costs["QApplication + style"] = (time.perf_counter() - start) * 1000
threads["QApplication + style"] = "main"
directory = A.data_directory()
directory.mkdir(parents=True, exist_ok=True)
model = A.Model(directory)
at("app ready")
cyclop = A.Cyclop(model)
at("features built")
cyclop.show()
at("shown")

try:
    import psutil
    process = psutil.Process()
    cpu_start = sum(process.cpu_times()[:2])
except Exception:
    process = None
gaps = []
last = [time.perf_counter()]


def heartbeat():
    now = time.perf_counter()
    if now - last[0] > 0.05:
        gaps.append(round((now - last[0]) * 1000))
    last[0] = now
    if "eye painted" not in moments and costs.get("Eye painting (first seconds)"):
        at("eye painted")


beat = QTimer()
beat.setInterval(10)
beat.timeout.connect(heartbeat)
beat.start()
QTimer.singleShot(int(args.seconds * 1000), cyclop.request_quit)
app.exec()
cpu = (sum(process.cpu_times()[:2]) - cpu_start) * 1000 if process else None
cyclop.shutdown()

ranked = sorted(costs.items(), key=lambda item: -item[1])
report = {
    "python": sys.version.split()[0], "platform": sys.platform,
    "moments_ms": {name: round(value) for name, value in sorted(moments.items(), key=lambda item: item[1])},
    "ranked_ms": [[name, round(value, 1), threads.get(name, "?")] for name, value in ranked],
    "first_seconds": {"seconds": args.seconds, "cpu_ms": round(cpu) if cpu is not None else None, "ui_stalls_over_50ms_ms": gaps[:12]},
}
for name, value in report["moments_ms"].items():
    print(f"at {value:6.0f} ms  {name}")
for name, value, where in report["ranked_ms"]:
    print(f"{value:8.1f} ms  {where:10s} {name}")
print("first seconds:", report["first_seconds"])
if args.json:
    Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
os._exit(0)
