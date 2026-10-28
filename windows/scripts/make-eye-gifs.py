"""Record every Cyclop eye animation as a looping GIF for the README.

The real widgets are rendered offscreen while a simulated clock drives them, so
the GIFs show exactly what the app does. Run from the windows folder:

    python -m pip install pillow
    python scripts/make-eye-gifs.py            # all animations
    python scripts/make-eye-gifs.py hunt roll  # just these

Output: docs/eye/<name>.gif
"""
from __future__ import annotations

import math
import os
import random
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1.5")   # crisper GIFs; shown at 2/3 size in the README
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FPS = 20
OUT = ROOT / "docs" / "eye"


class Clock:
    """Replaces time.monotonic so every animation advances in exact frame steps."""
    def __init__(self):
        self.now = 10_000.0
        self.real = time.monotonic
        time.monotonic = lambda: self.now


clock = Clock()
app = QApplication([])

from cyclop_windows.theme import STYLE  # noqa: E402
app.setStyleSheet(STYLE)
import cyclop_windows.mascot as mascot_module  # noqa: E402
from cyclop_windows import behaviour  # noqa: E402
from cyclop_windows.capture import ScanOverlay  # noqa: E402
from cyclop_windows.model import Model  # noqa: E402
from cyclop_windows.sonar import SonarMark  # noqa: E402

SCREEN = QRect(0, 0, 1536, 824)            # lay Cyclop out as on a 1920×1080 laptop at 125 %
NOTCH = QRect(SCREEN.center().x() - 96, 0, 192, 28)
cursor = {"pos": QPoint(700, 520)}
mascot_module.MascotWindow.screen_bounds = lambda self: SCREEN
mascot_module.QCursor.pos = staticmethod(lambda: QPoint(cursor["pos"]))
mascot_module.last_input_tick = lambda: 0
mascot_module.foreground_window = lambda: None
mascot_module.caret_position = lambda: None


def background(width, height):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor("#2c3e57"))
    gradient.setColorAt(1, QColor("#56384f"))
    painter.fillRect(image.rect(), gradient)
    painter.end()
    return image


def new_mascot(stats=False, **config):
    model = Model(Path(tempfile.mkdtemp()))
    model.configure("stats_enabled", stats)
    model.configure("mascot_marks", False)       # marks are separate windows; shown in their own GIF
    model.configure("mascot_autohide", False)
    model.configure("mascot_peek", False)
    for key, value in config.items():
        model.configure(key, value)
    window = mascot_module.MascotWindow(model, start_animation=False)
    window.set_anchor(NOTCH)
    window.last_pointer_move = window.last_typing = clock.now - 3
    window.engine.next_act = clock.now + 3600   # acts only when a scene asks for one
    window.intro_pinged = True                   # no stray pings: each GIF shows one thing
    window.next_ping = clock.now + 3600
    window.next_peek = clock.now + 3600
    window.tick()
    window.pings = []
    return window


def canvas_for(window, height=None):
    """The top strip of the screen around Cyclop, with the eye at its real height."""
    width = max(window.width(), 180) + 24
    return width, height or (window.y() + window.height() + 6)


def compose(window, size, extra=None):
    width, height = size
    frame = background(width, height)
    painter = QPainter(frame)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    picture = window.grab().toImage()
    painter.drawImage(QPointF((width - window.width()) / 2, window.y() - SCREEN.y()), picture)
    if extra:
        extra(painter, width, height)
    painter.end()
    return frame


def record(name, seconds, setup=None, step=None, window=None, size=None, stats=False, config=None):
    window = window or new_mascot(stats, **(config or {}))
    if setup:
        setup(window)
    size = size or canvas_for(window, 150 if not stats else 160)
    frames = []
    started = clock.now
    for index in range(int(seconds * FPS)):
        clock.now += 1 / FPS
        elapsed = clock.now - started
        if step:
            step(window, elapsed)
        window.tick()
        frames.append(compose(window, size))
    window.shutdown()
    window.close()
    save(name, frames)


def save(name, frames):
    from PIL import Image
    images = []
    for frame in frames:
        rgba = frame.convertToFormat(QImage.Format.Format_RGBA8888)
        image = Image.frombuffer("RGBA", (rgba.width(), rgba.height()), bytes(rgba.constBits()), "raw", "RGBA",
                                 rgba.bytesPerLine(), 1).convert("RGB")
        images.append(image)
    # One shared palette, built from frames across the whole clip, keeps colours steady
    # (a single frame can miss colours that appear later, e.g. the eye in a peek).
    samples = images[::max(1, len(images) // 8)]
    strip = Image.new("RGB", (samples[0].width, samples[0].height * len(samples)))
    for index, sample in enumerate(samples):
        strip.paste(sample, (0, index * sample.height))
    palette_source = strip.quantize(colors=160, method=Image.Quantize.MEDIANCUT)
    quantized = [image.quantize(palette=palette_source, dither=Image.Dither.NONE) for image in images]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.gif"
    quantized[0].save(path, save_all=True, append_images=quantized[1:], duration=int(1000 / FPS), loop=0,
                      optimize=True, disposal=1)
    print(f"{path.relative_to(ROOT)}  {len(frames)} frames  {path.stat().st_size // 1024} KB")


# ---------------------------------------------------------------- scenes
def act_scene(name, seed=3):
    def setup(window):
        window.last_pointer_move = window.last_typing = clock.now - 30
        window.engine.start(behaviour.ACTS[name](random.Random(seed)), clock.now + 0.4)
    act = behaviour.ACTS[name](random.Random(seed))
    return lambda: record(name.replace("_", "-"), act.duration + 0.9, setup)


def scene_follow():
    def step(window, t):
        angle = t / 3.6 * 2 * math.pi
        cursor["pos"] = QPoint(int(768 + 650 * math.cos(angle)), int(470 + 300 * math.sin(angle)))
        window.last_pointer_move = clock.now
    record("follow", 3.6, step=step)


def scene_reading():
    def step(window, t):
        window.last_pointer_move = clock.now - 10
        window.last_typing = clock.now
    record("reading", 3.0, step=step)


def scene_caret():
    def step(window, t):
        window.last_pointer_move = clock.now - 10
        window.last_typing = clock.now
        window.caret_point = QPoint(int(150 + 260 * ((t * 1.1) % 1.0)), 700 if t < 1.6 else 730)
        window.caret_time = clock.now
    record("caret", 3.0, step=step)


def scene_window_glance():
    def step(window, t):
        window.last_pointer_move = clock.now - 10
        if abs(t - 0.3) < 0.5 / FPS:
            window.notice(QPoint(120, 360), 1.2)
        if abs(t - 1.8) < 0.5 / FPS:
            window.notice(QPoint(1420, 300), 1.2)
    record("window-glance", 3.3, step=step)


def scene_startle():
    def step(window, t):
        if t < 0.6:
            cursor["pos"] = QPoint(1300, 650)
        elif t < 0.7:
            cursor["pos"] = QPoint(window.eye_center_global().x() + 70, 110)
        window.last_pointer_time = clock.now - 0.06
        window.pointer_tick()
    record("startle", 2.0, step=step)


def scene(name, seconds, start, step=None, **kwargs):
    def setup(window):
        window.last_pointer_move = window.last_typing = clock.now - 10
        start(window)
    return lambda: record(name, seconds, setup, step, **kwargs)


def scene_sleep():
    def setup(window):
        window.engine.energy = 0.0
        window.last_pointer_move = window.last_typing = clock.now - 600
        window.next_z = clock.now
    record("sleep", 4.5, setup)


def scene_listening():
    def setup(window):
        window.set_state("listening")
        window.say("Listening…", 30)

    def step(window, t):
        window.set_level(abs(math.sin(t * 5.3)) * (0.5 + 0.5 * math.sin(t * 1.7)))
    record("listening", 3.0, setup, step)


def scene_scanning():
    def setup(window):
        window.look_at(QPoint(300, 600))
        window.set_state("scanning")
    record("scanning", 2.6, setup)


def scene_tuck_and_peek():
    window = new_mascot(stats=True)
    window.set_stats({"cpu": 18, "ram": 54, "gpu": 9, "temp": 47, "details": []})
    ease = lambda x: 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2

    def step(window, t):
        window.last_pointer_move = clock.now - 10
        # 0–0.8 s shown, slide up, rest, peek out halfway, look around, tuck back.
        if t < 0.8:
            offset = 0.0
        elif t < 1.3:
            offset = ease((t - 0.8) / 0.5)
        elif t < 2.2:
            offset = 1.0
        elif t < 2.6:
            offset = 1.0 - 0.5 * ease((t - 2.2) / 0.4)
        elif t < 4.6:
            offset = 0.5
        elif t < 5.0:
            offset = 0.5 + 0.5 * ease((t - 4.6) / 0.4)
        else:
            offset = 1.0
        window.tucked = offset > 0.6 or 2.2 <= t < 4.6
        window.peeking = 2.2 <= t < 4.6
        if abs(t - 2.2) < 0.5 / FPS:
            window.engine.start(behaviour.Act("peek", [
                behaviour.Beat(0.5, ("rel", 0.0, -0.25), open=0.6),
                behaviour.Beat(0.7, ("rel", -0.34, -0.2), ping=True),
                behaviour.Beat(0.7, ("rel", 0.34, -0.2), ping=True),
                behaviour.Beat(0.5, ("cursor",)),
            ]), clock.now)
        window._slid(offset)
    record("tuck-and-peek", 5.6, step=step, window=window, size=(window.width() + 24, 150))


def scene_wake_up():
    window = new_mascot()
    window.intro_started = clock.now
    window.intro_pinged = False
    window.offset = 1.0

    def step(window, t):
        x = min(1.0, t / 0.7)
        window._slid(1.0 - (1 - (1 - x) ** 3))
        if t > 2.5:
            cursor["pos"] = QPoint(500, 600)
    record("wake-up", 3.0, step=step, window=window)


def scene_sonar_mark():
    mark = SonarMark(QPoint(90, 70))
    frames = []
    started = clock.now
    while clock.now - started < SonarMark.LIFE + 0.3:
        clock.now += 1 / FPS
        frame = background(180, 140)
        painter = QPainter(frame)
        painter.drawImage(QPointF(30, 10), mark.grab().toImage())
        painter.end()
        frames.append(frame)
        if clock.now - started > SonarMark.LIFE:
            mark.started = clock.now  # loop the mark for the GIF
    mark.close()
    save("sonar-mark", frames)


def scene_text_capture():
    area = QRect(20, 20, 300, 90)
    overlay = ScanOverlay(area)
    frames = []
    started = clock.now
    while clock.now - started < 2.6:
        clock.now += 1 / FPS
        if clock.now - started > 2.0:
            overlay.finish(True)
        frame = QImage(340, 130, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(QColor("#ffffff"))
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#202020"))
        painter.setFont(QFont("DejaVu Sans", 11))
        painter.drawText(QRectF(34, 34, 280, 70), Qt.TextFlag.TextWordWrap,
                         "Select any area of the screen: Cyclop reads the text and copies it.")
        painter.drawImage(QPointF(area.x() - 6, area.y() - 6), overlay.grab().toImage())
        painter.end()
        frames.append(frame)
    overlay.close()
    save("text-capture", frames)


SCENES = {
    "wake-up": scene_wake_up,
    "follow": scene_follow,
    "reading": scene_reading,
    "caret": scene_caret,
    "window-glance": scene_window_glance,
    **{name.replace("_", "-"): act_scene(name) for name in behaviour.ACTS},
    "startle": scene_startle,
    "dizzy": scene("dizzy", 3.4, lambda w: w.get_dizzy()),
    "giggle": scene("giggle", 1.8, lambda w: w.tickle()),
    "annoyed": scene("annoyed", 2.4, lambda w: [w.register_click() for _ in range(4)]),
    "happy": scene("happy", 1.4, lambda w: w.happy()),
    "gulp": scene("gulp", 1.6, lambda w: w.gulp(), lambda w, t: w.gulp() if abs(t - 0.8) < 0.5 / FPS else None),
    "music": scene("music", 3.0, lambda w: w.set_media({"available": True, "playing": True})),
    "strained": scene("strained", 2.6, lambda w: w.set_stats({"cpu": 97, "ram": 60, "gpu": 40, "temp": 92, "details": []})),
    "sleep": scene_sleep,
    "listening": scene_listening,
    "thinking": scene("thinking", 2.6, lambda w: w.set_state("thinking")),
    "scanning": scene_scanning,
    "error": scene("error", 1.6, lambda w: w.set_state("error")),
    "tuck-and-peek": scene_tuck_and_peek,
    "sonar-mark": scene_sonar_mark,
    "text-capture": scene_text_capture,
}


if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SCENES)
    for name in wanted:
        random.seed(7)
        cursor["pos"] = QPoint(700, 520)
        SCENES[name]()
