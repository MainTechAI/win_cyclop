from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl, Qt
from PySide6.QtTest import QTest

from cyclop_windows.app import Panel, TABS
from cyclop_windows.model import Model


def create_panel(app, tmp_path):
    model = Model(tmp_path)
    panel = Panel(model, start_services=False)
    panel.watcher.stop()
    panel.show()
    panel.set_expanded(True)
    panel.reposition()
    app.processEvents()
    return model, panel


def test_all_panes_render_and_privacy_cover(app, tmp_path):
    model, panel = create_panel(app, tmp_path)
    try:
        for key in TABS:
            panel.select_tab(key)
            panel.reposition()
            app.processEvents()
            assert panel.stack.currentWidget() is panel.panes[key]
            assert not panel.grab().isNull()
            assert panel.panes[key].width() > 300
        panel.set_private(True)
        assert panel.stack.currentWidget() is panel.cover
        panel.set_private(False)
        assert panel.stack.currentWidget() is panel.panes[panel.current_tab]
        panel.set_expanded(False)
        panel.reposition()
        assert panel.width() == 192 and panel.height() == 28
        assert not panel.body.isVisible()
    finally:
        panel.shutdown()
        panel.close()


def test_notes_persist_without_losing_pending_edits_on_switch(app, tmp_path):
    model, panel = create_panel(app, tmp_path)
    try:
        notes = panel.panes["notes"]
        notes.new()
        notes.text.setPlainText("First note\nDetails")
        notes.new()
        notes.text.setPlainText("Second note")
        notes.select.setCurrentIndex(0)
        assert notes.text.toPlainText() == "First note\nDetails"
        notes.flush()
        loaded = model.store.load("notes", [])
        assert [n["text"] for n in loaded] == ["First note\nDetails", "Second note"]
    finally:
        panel.shutdown()
        panel.close()


def test_clipboard_capture_is_opt_in_and_not_persisted(app, tmp_path):
    model = Model(tmp_path)
    app.clipboard().setText("ignored")
    app.processEvents()
    assert model.history.items == []
    model.configure("clipboard_enabled", True)
    app.clipboard().setText("captured")
    app.processEvents()
    assert model.history.items == ["captured"]
    model.configure("disabled_tabs", ["clipboard"])
    app.clipboard().setText("paused")
    app.processEvents()
    assert model.history.items == ["captured"]
    assert not (tmp_path / "clipboard.json").exists()
    model.configure("clipboard_enabled", False)
    app.clipboard().dataChanged.disconnect(model.capture_clipboard)


def test_shelf_removal_does_not_delete_original(app, tmp_path):
    model = Model(tmp_path / "data")
    file = tmp_path / "important.txt"
    file.write_text("keep me")
    model.add_files([str(file)])
    model.remove_files([str(file)])
    assert file.read_text() == "keep me"
    assert model.shelf == []
    app.clipboard().dataChanged.disconnect(model.capture_clipboard)


def test_disabling_current_tab_selects_an_available_tab(app, tmp_path):
    model, panel = create_panel(app, tmp_path)
    try:
        panel.select_tab("clipboard")
        model.configure("disabled_tabs", ["clipboard"])
        assert panel.current_tab != "clipboard"
        assert not panel.buttons["clipboard"].isVisible()
    finally:
        panel.shutdown()
        panel.close()


def test_currency_supports_reverse_input(app, tmp_path):
    model, panel = create_panel(app, tmp_path)
    try:
        currency = panel.panes["currency"]
        currency.loaded({"rates": {"EUR": 1, "USD": 1.1}, "date": "2026-10-26"})
        currency.amount.setText("100")
        currency.convert()
        assert currency.result.text() == "110.00"
        currency.result.setText("55")
        currency.convert(True)
        assert currency.amount.text() == "50.00"
    finally:
        panel.shutdown()
        panel.close()


def test_hover_and_pin_state(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QCursor
    from PySide6.QtCore import QPoint
    model, panel = create_panel(app, tmp_path)
    try:
        panel.set_expanded(False)
        panel.reposition()
        monkeypatch.setattr(QCursor, "pos", lambda: panel.geometry().center())
        for _ in range(3):
            panel.pointer_tick()
        assert panel.expanded
        panel.reposition()
        panel.set_pinned(True)
        monkeypatch.setattr(QCursor, "pos", lambda: QPoint(-1000, -1000))
        for _ in range(10):
            panel.pointer_tick()
        assert panel.expanded
        panel.set_pinned(False)
        panel.pointer_tick()
        assert not panel.expanded
    finally:
        panel.shutdown()
        panel.close()


def test_teleprompter_scrolls_and_stops_when_hidden(app, tmp_path):
    model, panel = create_panel(app, tmp_path)
    try:
        panel.select_tab("teleprompter")
        panel.reposition()
        prompter = panel.panes["teleprompter"]
        prompter.text.setPlainText("A line for the camera.\n" * 100)
        app.processEvents()
        prompter.toggle()
        assert prompter.running
        prompter.last_time -= 1
        prompter.tick()
        assert prompter.text.verticalScrollBar().value() >= 30
        panel.select_tab("music")
        assert not prompter.running
    finally:
        panel.shutdown()
        panel.close()
