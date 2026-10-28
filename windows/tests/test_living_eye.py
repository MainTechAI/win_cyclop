"""The behaviour engine and Cyclop's reactions to what happens on the PC."""
import random
import time

import pytest
from PySide6.QtCore import QPoint

from cyclop_windows.behaviour import ACTS, Beat, Engine, LIVELINESS, Wiggle, resolve_look
from cyclop_windows.core import normalise_config
from cyclop_windows.model import Model


def test_every_act_is_well_formed_and_varied():
    rng = random.Random(1)
    for name, build in ACTS.items():
        act = build(rng)
        assert act.name == name and act.beats and 0.5 < act.duration < 6
        assert all(beat.duration > 0 for beat in act.beats)
    engine = Engine("Lively", random.Random(2))
    chosen = set()
    for _ in range(60):
        chosen.add(engine.choose().name)
        engine.history.append(next(iter(chosen)))
    assert len(chosen) >= 6, "idle life is not one trick on repeat"


def test_engine_plays_acts_after_a_pause_and_tires_out():
    engine = Engine("Lively", random.Random(3))
    beat, _ = engine.update(10.0, idle_for=1.0)
    assert beat is None, "no act while the pointer is moving"
    beat, _ = engine.update(10.0, idle_for=LIVELINESS["Lively"][0] + 0.1)
    assert beat is not None and engine.act is not None
    end = 10.0 + engine.act.duration + 0.01
    assert engine.update(end, idle_for=99)[0] is None and engine.next_act > end
    engine.energy = 0.2
    assert all(engine.choose().name in {"yawn", "doze", "stretch", "nod", "peer"} for _ in range(20))
    engine.drain(10_000)
    assert engine.sleepy
    engine.refresh()
    assert not engine.sleepy


def test_beats_report_their_start_once():
    engine = Engine("Playful", random.Random(4))
    engine.update(0.0, idle_for=99)
    first = list(engine.started_beats)
    assert len(first) == 1
    engine.update(0.01, idle_for=99)
    assert engine.started_beats == []


def test_look_specs_resolve_to_gaze():
    cursor = (0.2, -0.1)
    screen = lambda fx, fy: (fx - 0.5, 0.5 - fy)
    assert resolve_look(("rel", 0.1, 0.2), 0, cursor, screen) == (0.1, 0.2)
    assert resolve_look(("cursor",), 0, cursor, screen) == cursor
    assert resolve_look(("screen", 1.0, 0.0), 0, cursor, screen) == (0.5, 0.5)
    assert resolve_look(("away",), 0, cursor, screen)[0] < 0
    start = resolve_look(("roll", 1), 0.0, cursor, screen)
    half = resolve_look(("roll", 1), 0.5, cursor, screen)
    assert start != half


def test_wiggling_the_pointer_is_detected():
    wiggle = Wiggle()
    now, triggered = 0.0, False
    for step in range(10):
        now += 0.08
        triggered = wiggle.feed(now, 60 if step % 2 else -60, 1500) or triggered
    assert triggered
    assert not Wiggle().feed(0.0, 2, 100)


def test_old_hide_delay_is_migrated_and_new_options_default_sensibly():
    old = normalise_config({"mascot_autohide_seconds": 8, "config_version": 3})
    assert old["mascot_autohide_seconds"] == 30
    chosen = normalise_config({"mascot_autohide_seconds": 8, "config_version": 4})
    assert chosen["mascot_autohide_seconds"] == 8, "a value set in 0.3 is kept"
    fresh = normalise_config({})
    assert fresh["mascot_size"] == "Medium" and fresh["mascot_liveliness"] == "Lively"
    assert fresh["mascot_peek"] and fresh["mascot_watch_windows"] and fresh["mascot_marks"]
    assert normalise_config({"mascot_size": "Huge"})["mascot_size"] == "Medium"


# ---------------------------------------------------------------- the window
@pytest.fixture
def mascot(app, tmp_path):
    from cyclop_windows.mascot import MascotWindow
    window = MascotWindow(Model(tmp_path), start_animation=False)
    window.tick()
    yield window
    window.shutdown()
    window.close()


def test_size_setting_changes_the_orb(mascot):
    mascot.model.configure("mascot_size", "Large")
    assert mascot.ORB == 120 and mascot.width() > 120 + 2 * 40
    mascot.tick()
    assert mascot.frame.width() >= 120
    mascot.model.configure("mascot_size", "Small")
    assert mascot.ORB == 72


def test_acts_drive_the_body_and_leave_sonar_marks(mascot):
    from cyclop_windows.behaviour import act_hunt
    now = time.monotonic()
    mascot.last_pointer_move = mascot.last_typing = now - 30
    mascot.engine.start(act_hunt(random.Random(5)), now - 0.6)  # into the stare
    mascot.tick()
    assert mascot.beat is not None and mascot.beat.mark
    mascot.engine.beat_started -= 1.2   # reach the pounce beat
    mascot.tick()
    assert mascot.marks, "hunting leaves a red mark on the screen"
    assert mascot.hop.velocity < 0, "it pounces"
    mascot.model.configure("mascot_marks", False)
    count = len(mascot.marks)
    mascot.sonar_mark(QPoint(10, 10))
    assert len(mascot.marks) == count


def test_peeks_out_while_tucked_and_tucks_back(mascot):
    mascot.slide.setDuration(1)
    mascot.set_tucked(True)
    mascot.slide.setCurrentTime(1)
    now = time.monotonic()
    mascot.next_peek = 0
    mascot.update_peek(now)
    assert mascot.peeking and mascot.engine.act is not None and mascot.engine.act.name == "peek"
    mascot.slide.setCurrentTime(1)
    assert 0.4 < mascot.offset < 0.6, "half of the eye shows"
    mascot.update_peek(now + 10)
    assert not mascot.peeking
    mascot.slide.setCurrentTime(1)
    assert mascot.offset == 1.0
    mascot.model.configure("mascot_peek", False)
    mascot.next_peek = 0
    mascot.update_peek(now + 20)
    assert not mascot.peeking


def test_reacts_to_copies_music_strain_windows_and_tickles(mascot, monkeypatch):
    mascot.gulp()
    assert mascot.squash.velocity > 0 and time.monotonic() < mascot.gulp_until
    mascot.set_media({"available": True, "playing": True})
    assert mascot.media_playing
    mascot.set_stats({"cpu": 97, "ram": 50, "gpu": 5, "temp": 90, "details": []})
    assert mascot.strained and mascot.hot
    dx, _ = mascot.body_offset(time.monotonic())
    mascot.notice(QPoint(5, 500), 1.0)
    mascot.last_pointer_move = mascot.last_typing = time.monotonic() - 30
    mascot.tick()
    assert mascot.target[0] < 0, "glances at the window it noticed"
    # Switching windows: the first sighting is remembered, the next one is noticed.
    windows = iter([(1, (0, 0, 800, 600), 99), (2, (900, 300, 1500, 900), 99)])
    monkeypatch.setattr("cyclop_windows.mascot.foreground_window", lambda: next(windows))
    mascot.glance_until = 0
    mascot.watch_windows(time.monotonic(), False)
    assert mascot.glance_until == 0
    mascot.watch_windows(time.monotonic(), False)
    assert mascot.glance_until > time.monotonic()
    mascot.tickle()
    assert time.monotonic() < mascot.tickle_until


def test_watches_the_text_cursor_while_typing(mascot, monkeypatch):
    monkeypatch.setattr("cyclop_windows.mascot.caret_position", lambda: (5, 700))
    monkeypatch.setattr("cyclop_windows.mascot.foreground_window", lambda: None)
    now = time.monotonic()
    mascot.watch_windows(now, True)
    assert mascot.caret_point is not None
    mascot.last_pointer_move = now - 10
    mascot.last_typing = now
    mascot.tick()
    assert mascot.target[0] < 0 and mascot.target[1] < 0, "looks down-left at the caret"


def test_long_titles_without_spaces_wrap_and_elide(app):
    from cyclop_windows.widgets import ElidedLabel
    label = ElidedLabel("POV_You're_on_a_mission_with_the_Task_force_" * 3, lines=2)
    label.resize(220, 40)
    label.reflow()
    lines = label.text().splitlines()
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert all(label.fontMetrics().horizontalAdvance(line) <= label.contentsRect().width() + 1 for line in lines)
