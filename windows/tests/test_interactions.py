"""Regression tests for clipping, hidden dialogs and dead dropdowns."""
import ctypes
import sys

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit, QPlainTextEdit, QPushButton

from cyclop_windows.app import Panel
from cyclop_windows.model import Model
from cyclop_windows.widgets import PanelFileDialog


def open_panel(app, tmp_path, tab):
    model = Model(tmp_path)
    panel = Panel(model, start_services=False)
    panel.watcher.stop()
    panel.show()
    panel.select_tab(tab)
    panel.set_expanded(True)
    panel.reposition()
    app.processEvents()
    return model, panel


def native_point(widget, pos):
    """Map a Qt point without turning ordinary child widgets into HWNDs."""
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    window = widget.window()
    handle = int(window.winId())
    local = widget.mapTo(window, pos)
    scale = window.devicePixelRatioF()
    point = wintypes.POINT(round(local.x() * scale), round(local.y() * scale))
    assert user32.ClientToScreen(handle, ctypes.byref(point))
    return user32, handle, point


def assert_native_hit(widget):
    """On Windows, prove no topmost panel covers this control."""
    if sys.platform != "win32" or QApplication.platformName() != "windows":
        return
    from ctypes import wintypes
    user32, handle, point = native_point(widget, widget.rect().center())
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    hit = user32.WindowFromPoint(point)
    assert hit and user32.GetAncestor(hit, 2) == user32.GetAncestor(handle, 2)


def mouse_click(widget, pos=None):
    """Use the Windows input path, including popup capture, on desktop runs."""
    pos = pos or widget.rect().center()
    if sys.platform == "win32" and QApplication.platformName() == "windows":
        from ctypes import wintypes
        user32, handle, point = native_point(widget, pos)
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        assert user32.SetCursorPos(point.x, point.y)
        QTest.qWait(50)
        user32.mouse_event(2, 0, 0, 0, 0)
        QTest.qWait(30)
        user32.mouse_event(4, 0, 0, 0, 0)
        QTest.qWait(50)
    else:
        QTest.mouseMove(widget, pos)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=pos)


def test_long_media_title_fits_and_full_text_is_available(app, tmp_path):
    model, panel = open_panel(app, tmp_path, "music")
    try:
        media = panel.panes["music"]
        title = "ДЕНЬ 170. ВЭЛС ВЫКАНУЛ НА ПУТИНА/УНИЧТОЖЕНИЕ ЗАВОДОВ РФ/ПЕНСИОННАЯ СИБИРИЛИЗАЦИЯ/" * 3
        media.update_state({"available": True, "title": title, "artist": "Майкл Наки", "source": "Brave", "can_play": True})
        app.processEvents()
        assert media.title.toolTip() == title
        assert media.title.text().endswith("…")
        assert len(media.title.text().splitlines()) == 2
        assert media.title.height() >= 2 * media.title.fontMetrics().lineSpacing()
        for line in media.title.text().splitlines():
            assert media.title.fontMetrics().horizontalAdvance(line) <= media.title.width()
        for widget in (media.title, media.artist, media.source, media.controls["play"], media.seek):
            top = widget.mapTo(media, QPoint(0, 0))
            assert top.y() >= 0
            assert top.y() + widget.height() <= media.height()
        assert media.title.geometry().bottom() < media.artist.geometry().top()
        assert media.source.geometry().bottom() < media.controls["play"].geometry().top()
    finally:
        panel.shutdown()
        panel.close()


def test_snippet_dialog_edit_save_cancel_and_rail_recovery(app, tmp_path):
    model, panel = open_panel(app, tmp_path, "snippets")
    failures = []
    try:
        pane = panel.panes["snippets"]
        def fill_dialog():
            dialog = QApplication.activeModalWidget()
            try:
                assert dialog is not None
                assert dialog.parentWidget() is panel
                assert dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
                title = dialog.findChild(QLineEdit)
                text = dialog.findChild(QPlainTextEdit)
                assert_native_hit(title)
                QTest.mouseClick(title, Qt.MouseButton.LeftButton)
                QTest.keyClicks(title, "Meeting intro")
                QTest.mouseClick(text.viewport(), Qt.MouseButton.LeftButton)
                QTest.keyClicks(text, "Hello from Cyclop")
                panel.buttons["currency"].hover_select()
                panel.pointer_tick()
                assert panel.current_tab == "snippets" and panel.expanded
                QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton)
            except BaseException as exc:
                failures.append(exc)
                if dialog:
                    dialog.reject()
        QTimer.singleShot(100, fill_dialog)
        add = next(b for b in pane.findChildren(QPushButton) if b.text() == "+ Add")
        QTest.mouseClick(add, Qt.MouseButton.LeftButton)
        assert not failures, failures
        assert model.store.load("snippets", []) == [{"title": "Meeting intro", "text": "Hello from Cyclop"}]
        QTimer.singleShot(100, lambda: QApplication.activeModalWidget().reject())
        QTest.mouseClick(add, Qt.MouseButton.LeftButton)
        assert len(model.snippets) == 1
        assert QApplication.activeModalWidget() is None
        QTest.mouseClick(panel.buttons["currency"], Qt.MouseButton.LeftButton)
        assert panel.current_tab == "currency"
    finally:
        panel.shutdown()
        panel.close()


def test_currency_dropdown_before_download_and_after_failure(app, tmp_path, monkeypatch):
    model, panel = open_panel(app, tmp_path, "currency")
    pane = panel.panes["currency"]
    try:
        assert pane.source.currentText() == "EUR"
        assert pane.target.currentText() == "USD"
        assert pane.result.text() == ""
        assert "Fetch rates" in pane.result.placeholderText()
        mouse_click(pane.source)
        app.processEvents()
        assert QApplication.activePopupWidget() is not None
        panel.buttons["notes"].hover_select()
        assert panel.current_tab == "currency"
        view = pane.source.view()
        index = pane.source.model().index(pane.source.findText("GBP"), 0)
        view.scrollTo(index)
        # Qt briefly ignores releases after opening a combo popup to avoid
        # selecting an item with the click that opened it.
        QTest.qWait(250)
        assert_native_hit(view.viewport())
        item_rect = view.visualRect(index).intersected(view.viewport().rect())
        assert not item_rect.isEmpty()
        mouse_click(view.viewport(), item_rect.center())
        app.processEvents()
        assert pane.source.currentText() == "GBP", (view.geometry(), view.viewport().rect(), item_rect, view.currentIndex().row())
        assert QApplication.activePopupWidget() is None
        monkeypatch.setattr(model, "run_job", lambda function, done, failed: failed("Network unavailable"))
        QTest.mouseClick(pane.refresh_button, Qt.MouseButton.LeftButton)
        assert pane.refresh_button.isEnabled()
        assert "Network unavailable" in pane.message.text()
        assert pane.source.count() > 1 and pane.result.text() == ""
        pane.loaded({"rates": {"EUR": 1, "USD": 1.1, "GBP": .8}, "date": "2026-10-27"})
        assert pane.source.currentText() == "GBP"
        pane.amount.selectAll()
        QTest.keyClicks(pane.amount, "80")
        assert pane.result.text() == "110.00"
        QTest.mouseClick(panel.buttons["notes"], Qt.MouseButton.LeftButton)
        assert panel.current_tab == "notes"
    finally:
        pane.source.hidePopup()
        panel.shutdown()
        panel.close()


def test_file_picker_is_owned_topmost_and_dismissible(app, tmp_path):
    model, panel = open_panel(app, tmp_path, "shelf")
    dialog = PanelFileDialog(panel.panes["shelf"], "Add test files")
    try:
        dialog.show()
        QTest.qWait(100)
        assert dialog.parentWidget() is panel
        assert dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert dialog.testOption(PanelFileDialog.Option.DontUseNativeDialog)
        assert_native_hit(dialog.findChild(QLineEdit))
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert not dialog.isVisible()
        QTest.mouseClick(panel.buttons["music"], Qt.MouseButton.LeftButton)
        assert panel.current_tab == "music"
    finally:
        dialog.close()
        panel.shutdown()
        panel.close()


def test_tab_clicks_during_resize_and_fast_expand(app, tmp_path):
    model, panel = open_panel(app, tmp_path, "music")
    try:
        QTest.mouseClick(panel.buttons["notes"], Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel.buttons["currency"], Qt.MouseButton.LeftButton)
        QTest.qWait(160)
        assert panel.current_tab == "currency"
        assert panel.geometry() == panel.target_rect()
        assert panel.body.isVisible()
        panel.set_expanded(False)
        QTest.qWait(110)
        assert panel.height() == 28
        panel.set_expanded(True)
        QTest.qWait(160)
        assert panel.body.isVisible() and panel.height() == 264
    finally:
        panel.shutdown()
        panel.close()
