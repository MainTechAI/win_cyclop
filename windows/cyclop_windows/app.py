from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from PySide6.QtCore import (
    QEasingCurve, QEvent, QLockFile, QPoint, QRect, QPropertyAnimation, QTimer, Qt,
)
from PySide6.QtGui import QAction, QCursor, QKeySequence, QPainter, QPainterPath, QRegion, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
    QStackedWidget, QSystemTrayIcon, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .core import data_directory
from .model import Model
from .panes import (
    MediaPane, ShelfPane, ClipboardPane, SnippetsPane, CalendarPane, TranslatePane,
    CurrencyPane, NotesPane, TeleprompterPane, SettingsPane,
)
from .theme import STYLE, icon
from .windows import HotkeyFilter

TABS = {
    "music": "Music", "shelf": "Shelf", "clipboard": "Clipboard", "snippets": "Snippets",
    "calendar": "Calendar", "translate": "Translate", "notes": "Notes",
    "currency": "Currency", "teleprompter": "Teleprompter", "settings": "Settings",
}
LEFT = ["music", "shelf", "clipboard", "snippets", "calendar", "translate"]
RIGHT = ["notes", "currency", "teleprompter", "settings"]


class RailButton(QToolButton):
    def __init__(self, key, panel):
        super().__init__()
        self.panel = panel
        self.key = key
        self.setObjectName("rail")
        self.setIcon(icon(key))
        self.setToolTip(TABS[key])
        self.setAccessibleName(TABS[key])
        self.setCheckable(True)
        self.setFixedSize(30, 28)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(170)
        self.timer.timeout.connect(lambda: panel.select_tab(key))
        self.clicked.connect(lambda: panel.select_tab(key))

    def enterEvent(self, event):
        if self.panel.model.config["hover_tabs"]:
            self.timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.timer.stop()
        super().leaveEvent(event)


def notch_shape(width, height, expanded=True):
    """Port of Cyclop's MIT-licensed NotchShape.swift (concave shoulders)."""
    top, bottom = (12, 22) if expanded else (6, 9)
    left, right = top, width - top
    path = QPainterPath()
    path.moveTo(0, 0)
    path.quadTo(left, 0, left, top)
    path.lineTo(left, height - bottom)
    path.quadTo(left, height, left + bottom, height)
    path.lineTo(right - bottom, height)
    path.quadTo(right, height, right, height - bottom)
    path.lineTo(right, top)
    path.quadTo(right, 0, width, 0)
    path.closeSubpath()
    return path


class Panel(QWidget):
    def __init__(self, model, start_services=True):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.model = model
        self.setWindowTitle("Cyclop for Windows")
        self.setWindowIcon(icon("eye", "#ffffff"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.expanded = False
        self.pinned = False
        self.private = False
        self.current_tab = "music"
        self.shutting_down = False
        self.outside_ticks = 0
        self.inside_ticks = 0
        self.header = QLabel(self)
        self.header.setObjectName("heading")
        self.header.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.status = QLabel(self)
        self.status.setObjectName("secondary")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.pin_button = QToolButton(self)
        self.pin_button.setIcon(icon("pin"))
        self.pin_button.setCheckable(True)
        self.pin_button.setStyleSheet("padding: 3px;")
        self.pin_button.setToolTip("Keep panel open")
        self.pin_button.setAccessibleName("Keep panel open")
        self.pin_button.toggled.connect(self.set_pinned)
        self.privacy_button = QToolButton(self)
        self.privacy_button.setIcon(icon("eye"))
        self.privacy_button.setCheckable(True)
        self.privacy_button.setStyleSheet("padding: 3px;")
        self.privacy_button.setToolTip("Hide panel contents")
        self.privacy_button.setAccessibleName("Hide panel contents")
        self.privacy_button.toggled.connect(self.set_private)
        self.body = QWidget(self)
        self.body.setObjectName("content")
        body_layout = QHBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        self.buttons = {}
        body_layout.addLayout(self.rail(LEFT))
        self.stack = QStackedWidget()
        self.panes = {
            "music": MediaPane(model, start_services), "shelf": ShelfPane(model),
            "clipboard": ClipboardPane(model), "snippets": SnippetsPane(model),
            "calendar": CalendarPane(model), "translate": TranslatePane(model),
            "notes": NotesPane(model), "currency": CurrencyPane(model),
            "teleprompter": TeleprompterPane(model), "settings": SettingsPane(model, TABS),
        }
        for pane in self.panes.values():
            self.stack.addWidget(pane)
        self.cover = QLabel("Contents hidden\nClick the eye button to reveal")
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setObjectName("secondary")
        self.stack.addWidget(self.cover)
        body_layout.addWidget(self.stack, 1)
        body_layout.addLayout(self.rail(RIGHT))
        self.animation = QPropertyAnimation(self, b"geometry", self)
        self.animation.setDuration(220)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.animation_done)
        self.status_timer = QTimer(self)
        self.status_timer.setSingleShot(True)
        self.status_timer.timeout.connect(lambda: self.status.clear())
        model.status.connect(self.notify)
        model.config_changed.connect(self.config_changed)
        self.watcher = QTimer(self)
        self.watcher.setInterval(50)
        self.watcher.timeout.connect(self.pointer_tick)
        self.watcher.start()
        self.escape = QShortcut(QKeySequence("Escape"), self)
        self.escape.activated.connect(lambda: self.set_expanded(False))
        QApplication.instance().screenAdded.connect(self.screens_changed)
        QApplication.instance().screenRemoved.connect(self.screens_changed)
        for screen in QApplication.screens():
            screen.geometryChanged.connect(self.reposition)
            screen.availableGeometryChanged.connect(self.reposition)
        self.config_changed()
        self.animation_done()
        self.reposition()

    def rail(self, keys):
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        for key in keys:
            control = RailButton(key, self)
            self.buttons[key] = control
            layout.addWidget(control)
        layout.addStretch()
        return layout

    def display(self):
        chosen = self.model.config.get("screen")
        return next((s for s in QApplication.screens() if s.name() == chosen), QApplication.primaryScreen())

    def target_rect(self):
        bounds = self.display().availableGeometry()
        width = min(644, bounds.width()) if self.expanded else 192
        height = (420 if self.current_tab in {"notes", "teleprompter", "settings"} else 264) if self.expanded else 28
        height = min(height, bounds.height())
        return QRect(bounds.x() + (bounds.width() - width) // 2, bounds.y(), width, height)

    def reposition(self, *args):
        self.animation.stop()
        self.setGeometry(self.target_rect())
        self.animation_done()

    def screens_changed(self, *args):
        self.reposition()

    def config_changed(self):
        disabled = self.model.config["disabled_tabs"]
        for key, control in self.buttons.items():
            control.setVisible(key not in disabled)
        if self.current_tab in disabled:
            self.current_tab = next(key for key in TABS if key not in disabled)
        self.select_tab(self.current_tab)
        self.reposition()

    def select_tab(self, key):
        if key in self.model.config["disabled_tabs"]:
            return
        old = self.current_tab
        self.current_tab = key
        self.header.setText(TABS[key].upper())
        self.stack.setCurrentWidget(self.cover if self.private else self.panes[key])
        for name, control in self.buttons.items():
            control.setChecked(name == key)
        for name, pane in self.panes.items():
            pane.activated(self.expanded and not self.private and name == key)
        if self.expanded and old != key:
            self.animate()

    def set_expanded(self, value, focus=False):
        if self.expanded == value:
            if value and focus:
                self.activateWindow()
            return
        self.expanded = value
        if not value:
            self.panes["teleprompter"].pause()
            self.body.hide()
            self.header.hide()
            self.pin_button.hide()
            self.privacy_button.hide()
            self.status.hide()
            self.clearFocus()
        else:
            self.show()
            self.raise_()
        self.select_tab(self.current_tab)
        self.animate()
        if focus:
            self.activateWindow()
        self.inside_ticks = self.outside_ticks = 0

    def animate(self):
        self.animation.stop()
        self.animation.setStartValue(self.geometry())
        self.animation.setEndValue(self.target_rect())
        self.animation.start()

    def animation_done(self):
        for widget in (self.body, self.header, self.pin_button, self.privacy_button, self.status):
            widget.setVisible(self.expanded)
        self.update()

    def set_pinned(self, value):
        self.pinned = value

    def set_private(self, value):
        self.private = value
        self.select_tab(self.current_tab)

    def toggle(self):
        self.set_expanded(not self.expanded, focus=True)

    def pointer_tick(self):
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            self.outside_ticks = 0
            return
        inside = self.geometry().contains(QCursor.pos())
        if inside:
            self.outside_ticks = 0
            self.inside_ticks += 1
            if not self.expanded and self.inside_ticks >= 3 and self.model.config["hover_open"]:
                self.set_expanded(True)
        else:
            self.inside_ticks = 0
            self.outside_ticks += 1
            editing = self.isActiveWindow() and isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QTextEdit))
            reading = self.panes["teleprompter"].running
            if self.expanded and self.outside_ticks >= 7 and not self.pinned and not editing and not reading:
                self.set_expanded(False)

    def mousePressEvent(self, event):
        if not self.expanded:
            self.set_expanded(True, focus=True)
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        if "shelf" not in self.model.config["disabled_tabs"] and event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            self.set_expanded(True)
            self.select_tab("shelf")
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.model.add_files(u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile())
            event.acceptProposedAction()

    def notify(self, text):
        self.status.setText(text[:100])
        self.status.setToolTip(text)
        self.status_timer.start(6000)

    def resizeEvent(self, event):
        width, height = self.width(), self.height()
        self.header.setGeometry(28, 5, max(120, width - 160), 20)
        self.privacy_button.setGeometry(width - 87, 3, 25, 23)
        self.pin_button.setGeometry(width - 57, 3, 25, 23)
        self.body.setGeometry(26, 34, max(0, width - 52), max(0, height - 60))
        self.status.setGeometry(68, height - 24, max(0, width - 136), 18)
        # Match the input region to the visible silhouette, including during animation.
        self.setMask(QRegion(notch_shape(width, height, self.expanded).toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.black)
        painter.drawPath(notch_shape(self.width(), self.height(), self.expanded))
        if not self.expanded:
            icon("eye", "#555", 18).paint(painter, self.width() // 2 - 9, 4, 18, 18)

    def closeEvent(self, event):
        if not self.shutting_down:
            self.set_expanded(False)
            event.ignore()
        else:
            event.accept()

    def shutdown(self):
        self.shutting_down = True
        self.watcher.stop()
        self.panes["notes"].flush()
        self.panes["teleprompter"].flush()
        worker = self.panes["music"].worker
        worker.stop()
        # Keep QThread alive until its bounded WinRT operations finish.
        worker.wait(15_000)
        if worker.isRunning():
            worker.wait()
        self.model.pool.waitForDone()


def main():
    parser = argparse.ArgumentParser(description="Cyclop for Windows 11")
    parser.add_argument("--expanded", action="store_true", help="Open the panel at launch")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("CyclopWindows")
    app.setOrganizationName("MainTechAI")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, "Cyclop", "Cyclop is already running. Use the tray icon or Ctrl+Alt+Space.")
        return
    model = Model(directory)
    panel = Panel(model)
    tray = QSystemTrayIcon(icon("eye", "#dddddd"), app)
    tray.setToolTip("Cyclop · Ctrl+Alt+Space")
    menu = QMenu()
    menu.addAction("Open / collapse", panel.toggle)
    def settings():
        panel.select_tab("settings")
        panel.set_expanded(True, focus=True)
    menu.addAction("Settings", settings)
    hide = menu.addAction("Hide contents")
    hide.setCheckable(True)
    hide.toggled.connect(panel.privacy_button.setChecked)
    panel.privacy_button.toggled.connect(hide.setChecked)
    capture = menu.addAction("Capture clipboard text")
    capture.setCheckable(True)
    capture.setChecked(bool(model.config["clipboard_enabled"]))
    capture.toggled.connect(lambda value: model.configure("clipboard_enabled", value))
    def sync_capture():
        capture.blockSignals(True)
        capture.setChecked(bool(model.config["clipboard_enabled"]))
        capture.blockSignals(False)
    model.config_changed.connect(sync_capture)
    menu.addSeparator()
    menu.addAction("Quit Cyclop", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: panel.toggle() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    hotkey = HotkeyFilter(panel.toggle)
    app.installNativeEventFilter(hotkey)
    def shutdown():
        hotkey.close()
        panel.shutdown()
        tray.hide()
        lock.unlock()
    app.aboutToQuit.connect(shutdown)
    panel.show()
    if args.expanded:
        panel.set_expanded(True, focus=True)
    if sys.platform == "win32" and not hotkey.registered:
        tray.showMessage("Cyclop", "Ctrl+Alt+Space is in use. Open Cyclop from this tray icon.")
    if model.store.warnings:
        tray.showMessage("Cyclop recovered saved data", "\n".join(model.store.warnings))
    sys.exit(app.exec())
