import struct
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap

from cyclop_windows.app import Cyclop, LEFT, Panel, RIGHT
from cyclop_windows.core import (
    DEFAULTS, cycle, lookup_word, normalise_config, parse_command, parse_hotkey, parse_wiktionary, stat_color, stat_label,
)
from cyclop_windows.model import Model

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows integration")


# ---------------------------------------------------------------- pure logic
def test_hotkeys_parse_to_win32_codes():
    assert parse_hotkey("Ctrl+Shift+X") == (0x0002 | 0x0004, ord("X"))
    assert parse_hotkey("Ctrl+Alt+Space") == (0x0002 | 0x0001, 0x20)
    assert parse_hotkey("Win+F12") == (0x0008, 0x7B)
    assert parse_hotkey("Meta+1") == (0x0008, ord("1"))
    for bad in ("X", "Ctrl+", "Hyper+X", "Ctrl+Tilde"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)


def test_tab_cycle_wraps_around_in_both_directions():
    order = ["a", "b", "c"]
    assert cycle(order, "c", 1) == "a"
    assert cycle(order, "a", -1) == "c"
    assert cycle(order, "b", 1) == "c"
    assert cycle(order, "missing", 1) == "a"


@pytest.mark.parametrize("spoken, expected", [
    ("Open Notepad.", {"action": "open", "name": "Notepad", "target": "notepad.exe"}),
    ("открой калькулятор", {"action": "open", "name": "Calculator", "target": "calc.exe"}),
    ("launch task manager please", {"action": "open", "name": "Task Manager", "target": "taskmgr.exe"}),
    ("Show notes", {"action": "tab", "tab": "notes"}),
    ("search for cognitive fit theory", {"action": "search", "query": "cognitive fit theory"}),
    ("найди погоду в Лаппеенранте", {"action": "search", "query": "погоду в лаппеенранте"}),
    ("Volume up", {"action": "key", "key": "volume_up"}),
    ("сделай тише", {"action": "key", "key": "volume_down"}),
    ("next track", {"action": "key", "key": "next"}),
    ("pause", {"action": "key", "key": "play"}),
    ("lock the computer", {"action": "lock"}),
    ("не засыпай", {"action": "awake", "value": True}),
    ("start recording", {"action": "record"}),
])
def test_voice_commands_map_to_allow_listed_actions(spoken, expected):
    assert parse_command(spoken) == expected


def test_unknown_speech_never_becomes_an_action():
    assert parse_command("rm -rf everything now")["action"] == "none"
    assert parse_command("open the pod bay doors")["action"] == "none"
    assert parse_command("")["action"] == "none"


def test_wiktionary_definitions_are_flattened_to_plain_text():
    payload = {"en": [{"partOfSpeech": "Noun", "definitions": [
        {"definition": "A <a href='x'>one-eyed</a> giant &amp; smith."}, {"definition": ""}]}],
        "ru": [{"partOfSpeech": "Noun", "definitions": [{"definition": "ignored when English exists"}]}]}
    assert parse_wiktionary(payload) == [("Noun", "A one-eyed giant & smith.")]
    assert parse_wiktionary({"ru": [{"partOfSpeech": "Verb", "definitions": [{"definition": "to read"}]}]}) == [("Verb", "to read")]
    assert lookup_word("  “cyclops”, ") == "cyclops"
    assert lookup_word("one two three four") is None


def test_config_repairs_bad_values_and_keeps_unknown_keys():
    config = normalise_config({"mascot_autohide_seconds": 0, "stats_items": ["cpu", "fan"], "voice_enabled": "yes",
                               "hotkeys": {"ocr": "Ctrl+Shift+O", "bogus": "X"}, "mascot_iris": "Plaid", "future": 1})
    assert config["mascot_autohide_seconds"] == 2
    assert config["stats_items"] == ["cpu"]
    assert config["voice_enabled"] is DEFAULTS["voice_enabled"]
    assert config["hotkeys"]["ocr"] == "Ctrl+Shift+O" and "bogus" not in config["hotkeys"]
    assert config["hotkeys"]["panel"] == "Ctrl+Alt+Space"
    assert config["mascot_iris"] == "Red" and config["future"] == 1


def test_stat_colours_and_labels():
    assert stat_color("cpu", 10) == "#6ee07a"
    assert stat_color("cpu", 65) == "#ffcc4d"
    assert stat_color("ram", 95) == "#ff5f57"
    assert stat_color("temp", 85) == "#ff5f57"
    assert stat_label("temp", 52.4) == "Temp 52°"
    assert stat_label("gpu", None) == "GPU –"


def test_media_sources_map_to_audio_processes():
    from cyclop_windows.system import process_for_source
    assert process_for_source("Chrome") == "chrome.exe"
    assert process_for_source("MSEdge") == "msedge.exe"
    assert process_for_source("Spotify.exe") == "spotify.exe"
    assert process_for_source("308046B0AF4A39CB") == "firefox.exe"
    assert process_for_source("") == ""


def test_recordings_round_trip_as_16_bit_wav(tmp_path):
    import numpy as np
    from cyclop_windows.speech import SAMPLE_RATE, read_wav, write_wav
    tone = (0.5 * np.sin(np.linspace(0, 2 * np.pi * 440, SAMPLE_RATE))).astype("float32")
    path = write_wav(tmp_path / "a" / "tone.wav", tone)
    loaded = read_wav(path)
    assert len(loaded) == SAMPLE_RATE
    assert abs(float(loaded.max()) - 0.5) < 0.01


# ---------------------------------------------------------------- panel behaviour
def make_panel(app, tmp_path):
    model = Model(tmp_path)
    panel = Panel(model, start_services=False)
    panel.watcher.stop()
    panel.show()
    return model, panel


def test_tray_or_hotkey_open_stays_open_while_pointer_is_elsewhere(app, tmp_path, monkeypatch):
    model, panel = make_panel(app, tmp_path)
    try:
        outside = panel.display().availableGeometry().bottomRight() - QPoint(2, 2)
        monkeypatch.setattr("cyclop_windows.app.QCursor.pos", staticmethod(lambda: outside))
        panel.set_expanded(True, focus=True, sticky=True)  # what a tray click does
        for _ in range(20):
            panel.pointer_tick()
        assert panel.expanded, "a tray click must not open and instantly close the panel"
        panel.set_expanded(False)
        panel.set_expanded(True)  # hover-open is not sticky
        for _ in range(6):
            panel.pointer_tick()
        assert not panel.expanded
        # After the pointer visits a sticky panel, leaving closes it as usual.
        panel.set_expanded(True, focus=True, sticky=True)
        panel.reposition()
        inside = panel.geometry().center()
        monkeypatch.setattr("cyclop_windows.app.QCursor.pos", staticmethod(lambda: inside))
        panel.pointer_tick()
        panel.pointer_tick()
        assert not panel.sticky
        monkeypatch.setattr("cyclop_windows.app.QCursor.pos", staticmethod(lambda: outside))
        for _ in range(6):
            panel.pointer_tick()
        assert not panel.expanded
    finally:
        panel.shutdown()
        panel.close()


def test_tabs_cycle_in_a_loop_and_skip_hidden_tabs(app, tmp_path):
    model, panel = make_panel(app, tmp_path)
    try:
        panel.set_expanded(True)
        order = [key for key in LEFT + RIGHT]
        panel.select_tab(order[-1])
        panel.cycle_tab(1)
        assert panel.current_tab == order[0]
        panel.cycle_tab(-1)
        assert panel.current_tab == order[-1]
        model.configure("disabled_tabs", ["shelf"])
        panel.select_tab("music")
        panel.cycle_tab(1)
        assert panel.current_tab == "clipboard"
        panel.wheel_cycle(-120)
        assert panel.current_tab == "snippets"
        panel.wheel_cycle(120)
        assert panel.current_tab == "clipboard"
        model.configure("tab_cycling", False)
        panel.cycle_tab(1)
        assert panel.current_tab == "clipboard"
    finally:
        panel.shutdown()
        panel.close()


def test_every_feature_toggle_is_in_settings(app, tmp_path):
    model, panel = make_panel(app, tmp_path)
    try:
        settings = panel.panes["settings"]
        for key in ("tab_cycling", "mascot_enabled", "mascot_autohide", "mascot_follow_cursor", "stats_enabled",
                    "ocr_enabled", "lookup_enabled", "lookup_online", "voice_enabled", "awake_enabled", "volume_enabled"):
            control = settings.controls[key]
            control.setChecked(not control.isChecked())
            assert model.config[key] == control.isChecked()
    finally:
        panel.shutdown()
        panel.close()


def test_controller_registers_only_enabled_shortcuts_and_awake_follows_toggle(app, tmp_path):
    model = Model(tmp_path)
    cyclop = Cyclop(model, start_services=False)
    try:
        assert set(cyclop.hotkeys.actions) == {"panel", "ocr", "define", "translate"}
        model.configure("voice_enabled", True)
        assert "voice" in cyclop.hotkeys.actions
        model.configure("ocr_enabled", False)
        assert "ocr" not in cyclop.hotkeys.actions
        cyclop.set_awake(True)
        assert cyclop.awake and cyclop.awake_action.isChecked()
        model.configure("awake_enabled", False)
        assert not cyclop.awake
        cyclop.quick.sync()
        assert not cyclop.quick.tiles["awake"].isVisible() or not cyclop.quick.isVisible()
    finally:
        cyclop.shutdown()
        cyclop.panel.close()


def test_unrecognised_voice_command_is_reported_not_executed(app, tmp_path):
    model = Model(tmp_path)
    cyclop = Cyclop(model, start_services=False)
    try:
        messages = []
        cyclop.notify = lambda text, seconds=3.5: messages.append(text)
        cyclop.execute(parse_command("open the pod bay doors"), "open the pod bay doors")
        assert messages and "Didn't catch" in messages[0]
        cyclop.execute({"action": "tab", "tab": "notes"})
        assert cyclop.panel.expanded and cyclop.panel.current_tab == "notes"
    finally:
        cyclop.shutdown()
        cyclop.panel.close()


# ---------------------------------------------------------------- mascot and icon
def test_eye_orb_is_a_shaded_sphere_with_transparent_corners(app):
    from cyclop_windows.mascot import EyeRenderer
    renderer = EyeRenderer(96)
    image = renderer.render(gaze=(0.3, -0.2), openness=0.5)
    assert image.size().width() == 96
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(48, 48).alpha() == 255
    top, bottom = image.pixelColor(48, 14), image.pixelColor(48, 84)
    assert top.lightness() != bottom.lightness()  # lit from above, not a flat disc


def test_mascot_slides_away_when_idle_and_shows_stats(app, tmp_path):
    from cyclop_windows.mascot import MascotWindow
    model = Model(tmp_path)
    model.configure("stats_enabled", True)
    mascot = MascotWindow(model, start_animation=False)
    try:
        mascot.slide.setDuration(1)
        mascot.set_stats({"cpu": 12, "ram": 50, "gpu": 3, "temp": 48, "details": ["detail"]})
        mascot.tick()
        assert not mascot.frame.isNull()
        assert mascot.footer_height() > 0 and mascot.width() >= mascot.footer_width()
        shown_y = mascot.y()
        mascot.set_tucked(True)
        mascot.slide.setCurrentTime(mascot.slide.duration())
        assert mascot.offset == 1.0 and mascot.y() < shown_y
        mascot.reveal()
        mascot.slide.setCurrentTime(mascot.slide.duration())
        assert mascot.offset == 0.0
        model.configure("mascot_autohide", False)
        mascot.set_tucked(True)
        assert not mascot.tucked
        model.configure("mascot_enabled", False)
        assert not mascot.isVisible()
    finally:
        mascot.shutdown()
        mascot.close()


def test_ico_contains_every_size(tmp_path, app):
    from cyclop_windows.mascot import write_ico
    path = tmp_path / "cyclop.ico"
    write_ico(path)
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind, count) == (0, 1, 9)
    first_offset = struct.unpack_from("<I", data, 6 + 12)[0]
    assert data[first_offset:first_offset + 8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- text capture
def text_image(text="Cyclop 2026"):
    image = QImage(420, 90, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QColor("black"))
    painter.setFont(QFont("Segoe UI", 36))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return image


def test_region_selection_crops_the_frozen_screenshot(app):
    from cyclop_windows.capture import RegionSelector, prepare_for_ocr
    snapshot = QPixmap.fromImage(text_image())
    selector = RegionSelector(snapshot=snapshot)
    results = []
    selector.selected.connect(results.append)
    selector.accept_area(QRect(10, 10, 200, 50))
    assert results and results[0].width() == 200 and results[0].height() == 50
    png = prepare_for_ocr(results[0])
    assert png.startswith(b"\x89PNG")
    upscaled = QImage.fromData(png)
    assert upscaled.width() > 200  # small regions are enlarged for better recognition


@windows_only
def test_windows_ocr_reads_rendered_text():
    from cyclop_windows.capture import prepare_for_ocr
    from cyclop_windows.services import ocr_languages, ocr_png
    if not ocr_languages():
        pytest.skip("No Windows OCR language installed on this machine")
    text = ocr_png(prepare_for_ocr(text_image("Cyclop 2026")))
    simplified = text.lower().replace("i", "l").replace("|", "l").replace(" ", "")
    assert "cyclop" in simplified and "2026" in simplified, repr(text)


@windows_only
def test_windows_power_counters_and_hotkeys():
    from cyclop_windows.windows import HotkeyFilter, PerformanceCounters, keep_awake
    assert keep_awake(True)
    assert keep_awake(False)
    counters = PerformanceCounters()
    try:
        assert isinstance(counters.sample(), dict)
    finally:
        counters.close()
    hotkeys = HotkeyFilter()
    try:
        assert hotkeys.set("ocr", "Ctrl+Shift+Alt+F11", lambda: None) is None
        assert hotkeys.is_registered("ocr")
    finally:
        hotkeys.close()
