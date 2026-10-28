from __future__ import annotations

import argparse
import json
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

from datetime import datetime
import time
from urllib.parse import quote_plus

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from .camera import FaceTracker, GazeCalibrator, download_model, find_model
from .capture import RegionSelector, ScanOverlay, ocr_variants
from .popups import LookupPopup, SelectionGrabber
from .services import ocr_png
from .speech import Transcriber
from .system import StatsWorker, sample_once
from .windows import keep_awake, lock_workstation, open_target, press_key

from .core import DEFAULT_LEFT, DEFAULT_RIGHT, HOTKEYS, IRIS_COLORS, cycle, data_directory, parse_command
from .features import OcrPane, QuickSettings, RecorderPane, SettingsPane
from .mascot import MascotWindow, app_icon
from .model import Model
from .panes import (
    MediaPane, ShelfPane, ClipboardPane, SnippetsPane, CalendarPane, TranslatePane,
    CurrencyPane, NotesPane, TeleprompterPane,
)
from .speech import Recorder
from .system import Volume
from .theme import STYLE, icon
from .windows import HotkeyFilter

TABS = {
    "music": "Music", "shelf": "Shelf", "clipboard": "Clipboard", "snippets": "Snippets",
    "calendar": "Calendar", "translate": "Translate", "notes": "Notes",
    "currency": "Currency", "teleprompter": "Teleprompter", "ocr": "Text capture",
    "recorder": "Recorder", "settings": "Settings",
}
LEFT, RIGHT = DEFAULT_LEFT, DEFAULT_RIGHT  # default arrangement; users can rearrange in Settings
TALL = {"notes", "teleprompter", "settings", "recorder"}


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
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.hover_select)
        self.clicked.connect(self.click_select)

    def hover_select(self):
        if not QApplication.activeModalWidget() and not QApplication.activePopupWidget() and self.isVisible():
            self.panel.select_tab(self.key)

    def click_select(self):
        self.timer.stop()
        self.panel.select_tab(self.key)

    def enterEvent(self, event):
        if self.panel.model.config["hover_tabs"] and not QApplication.activeModalWidget() and not QApplication.activePopupWidget():
            self.timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.timer.stop()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        self.timer.stop()
        self.panel.wheel_cycle(event.angleDelta().y())
        event.accept()


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
    geometry_changed = Signal(QRect)
    quick_requested = Signal(QPoint)

    def __init__(self, model, start_services=True, volume=None, recorder=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.model = model
        self.volume = volume or Volume()
        self.recorder = recorder or Recorder(self)
        self.setWindowTitle("Cyclop for Windows")
        self.setWindowIcon(app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.expanded = False
        self.sticky = False  # opened by click/hotkey: stay open until visited or dismissed
        self.was_active = False
        self.wheel_accumulator = 0
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
        self.quick_button = QToolButton(self)
        self.quick_button.setIcon(icon("quick"))
        self.quick_button.setStyleSheet("padding: 3px;")
        self.quick_button.setToolTip("Quick settings")
        self.quick_button.setAccessibleName("Quick settings")
        self.quick_button.clicked.connect(lambda: self.quick_requested.emit(self.quick_button.mapToGlobal(QPoint(self.quick_button.width() // 2, self.quick_button.height() + 4))))
        self.body = QWidget(self)
        self.body.setObjectName("content")
        body_layout = QHBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        self.buttons = {key: RailButton(key, self) for key in TABS}
        self.rails = {"left": self.rail(), "right": self.rail()}
        self.arranged = None
        body_layout.addLayout(self.rails["left"])
        self.stack = QStackedWidget()
        self.panes = {
            "music": MediaPane(model, start_services, self.volume), "shelf": ShelfPane(model),
            "clipboard": ClipboardPane(model), "snippets": SnippetsPane(model),
            "calendar": CalendarPane(model), "translate": TranslatePane(model),
            "notes": NotesPane(model), "currency": CurrencyPane(model),
            "teleprompter": TeleprompterPane(model), "ocr": OcrPane(model),
            "recorder": RecorderPane(model, self.recorder), "settings": SettingsPane(model, TABS),
        }
        for pane in self.panes.values():
            self.stack.addWidget(pane)
        self.cover = QLabel("Contents hidden\nClick the eye button to reveal")
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setObjectName("secondary")
        self.stack.addWidget(self.cover)
        body_layout.addWidget(self.stack, 1)
        body_layout.addLayout(self.rails["right"])
        self.animation = QPropertyAnimation(self, b"geometry", self)
        self.animation.setDuration(120)
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
        for sequence, step in (("Ctrl+Tab", 1), ("Ctrl+Shift+Tab", -1), ("Ctrl+Backtab", -1), ("Ctrl+PgDown", 1), ("Ctrl+PgUp", -1)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(lambda step=step: self.cycle_tab(step))
        QApplication.instance().focusWindowChanged.connect(self.focus_window_changed)
        QApplication.instance().screenAdded.connect(self.screens_changed)
        QApplication.instance().screenRemoved.connect(self.screens_changed)
        for screen in QApplication.screens():
            screen.geometryChanged.connect(self.reposition)
            screen.availableGeometryChanged.connect(self.reposition)
        self.config_changed()
        self.animation_done()
        self.reposition()

    def rail(self):
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        return layout

    def arrange_rails(self):
        """Put the rail buttons in the user's order (Settings → Panel tabs)."""
        layout = self.model.config["tab_layout"]
        if layout == self.arranged:
            return
        self.arranged = {side: list(keys) for side, keys in layout.items()}
        for side, rail in self.rails.items():
            while rail.count():
                rail.takeAt(0)
            for key in layout[side]:
                rail.addWidget(self.buttons[key])
            rail.addStretch()

    def visible_tabs(self, side):
        disabled = self.model.config["disabled_tabs"]
        return [key for key in self.model.config["tab_layout"][side] if key not in disabled]

    def display(self):
        chosen = self.model.config.get("screen")
        return next((s for s in QApplication.screens() if s.name() == chosen), QApplication.primaryScreen())

    def target_rect(self):
        bounds = self.display().availableGeometry()
        width = min(644, bounds.width()) if self.expanded else 192
        if self.current_tab in TALL:
            height = 420
        elif self.current_tab == "music" and self.model.config["volume_enabled"] and self.volume.available:
            height = 318
        else:
            height = 264
        # Tall enough for the longest rail, however the user arranged it.
        longest = max(len(self.visible_tabs("left")), len(self.visible_tabs("right")))
        height = max(height, 34 + longest * 32 + 26)
        height = height if self.expanded else 28
        height = min(height, bounds.height())
        return QRect(bounds.x() + (bounds.width() - width) // 2, bounds.y(), width, height)

    def reposition(self, *args):
        self.animation.stop()
        self.setGeometry(self.target_rect())
        self.animation_done()

    def screens_changed(self, *args):
        self.reposition()

    def config_changed(self):
        self.arrange_rails()
        disabled = self.model.config["disabled_tabs"]
        for key, control in self.buttons.items():
            control.setVisible(key not in disabled)
        if self.current_tab in disabled:
            self.current_tab = self.tab_order()[0] if self.tab_order() else "settings"
        self.select_tab(self.current_tab)
        self.reposition()

    def select_tab(self, key):
        if key in self.model.config["disabled_tabs"]:
            return
        old = self.current_tab
        self.current_tab = key
        self.header.setText(TABS[key].upper() + ("  ›" if self.model.config["tab_cycling"] else ""))
        self.stack.setCurrentWidget(self.cover if self.private else self.panes[key])
        for name, control in self.buttons.items():
            control.setChecked(name == key)
        for name, pane in self.panes.items():
            pane.activated(self.expanded and not self.private and name == key)
        if self.expanded and old != key:
            self.animate()

    def tab_order(self):
        """Visible tabs in rail order: down the left rail, then down the right one."""
        return self.visible_tabs("left") + self.visible_tabs("right")

    def cycle_tab(self, step=1):
        """Move to the next/previous visible tab; past the last one wraps to the first."""
        if not self.expanded or not self.model.config["tab_cycling"]:
            return
        self.select_tab(cycle(self.tab_order(), self.current_tab, step))

    def wheel_cycle(self, delta):
        self.wheel_accumulator += delta
        while abs(self.wheel_accumulator) >= 120:
            step = -1 if self.wheel_accumulator > 0 else 1
            self.wheel_accumulator += 120 * step
            self.cycle_tab(step)

    def set_expanded(self, value, focus=False, sticky=None):
        if value:
            # Opening by click, tray or hotkey keeps the panel open even though the
            # pointer is elsewhere (e.g. on the tray icon). Hover-opening is not sticky.
            self.sticky = bool(focus) if sticky is None else sticky
        if self.expanded == value:
            if value and focus:
                self.activateWindow()
            return
        self.expanded = value
        self.was_active = False
        if not value:
            self.panes["teleprompter"].pause()
            self.body.hide()
            self.header.hide()
            self.pin_button.hide()
            self.privacy_button.hide()
            self.quick_button.hide()
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
        target = self.target_rect()
        if self.geometry() == target:
            self.animation_done()
            return
        self.animation.setDuration(120 if self.expanded else 90)
        self.animation.setStartValue(self.geometry())
        self.animation.setEndValue(target)
        self.animation.start()

    def animation_done(self):
        for widget in (self.body, self.header, self.pin_button, self.privacy_button, self.quick_button, self.status):
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
            for control in self.buttons.values():
                control.timer.stop()
            return
        if self.isActiveWindow():
            self.was_active = True
        inside = self.geometry().contains(QCursor.pos())
        if inside:
            self.outside_ticks = 0
            self.inside_ticks += 1
            if self.expanded and self.inside_ticks >= 2:
                self.sticky = False
            if not self.expanded and self.inside_ticks >= 2 and self.model.config["hover_open"]:
                self.set_expanded(True)
        else:
            self.inside_ticks = 0
            self.outside_ticks += 1
            editing = self.isActiveWindow() and isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QTextEdit))
            reading = self.panes["teleprompter"].running
            if self.expanded and self.outside_ticks >= 5 and not self.pinned and not self.sticky and not editing and not reading:
                self.set_expanded(False)

    def focus_window_changed(self, window):
        # A sticky panel closes when the user clicks into another application.
        if (window is None and self.expanded and self.sticky and self.was_active and not self.pinned
                and not QApplication.activeModalWidget() and not QApplication.activePopupWidget()
                and not self.panes["teleprompter"].running):
            self.set_expanded(False)

    def mousePressEvent(self, event):
        if not self.expanded:
            self.set_expanded(True, focus=True)
        elif event.button() == Qt.MouseButton.LeftButton and self.header.geometry().contains(event.position().toPoint()):
            self.cycle_tab(1)
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        if self.expanded and event.position().y() < 34:
            self.wheel_cycle(event.angleDelta().y())
            event.accept()
        else:
            super().wheelEvent(event)

    def moveEvent(self, event):
        self.geometry_changed.emit(self.geometry())
        super().moveEvent(event)

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
        self.quick_button.setGeometry(width - 117, 3, 25, 23)
        self.privacy_button.setGeometry(width - 87, 3, 25, 23)
        self.pin_button.setGeometry(width - 57, 3, 25, 23)
        self.body.setGeometry(26, 34, max(0, width - 52), max(0, height - 60))
        self.status.setGeometry(68, height - 24, max(0, width - 136), 18)
        # Match the input region to the visible silhouette, including during animation.
        self.setMask(QRegion(notch_shape(width, height, self.expanded).toFillPolygon().toPolygon()))
        self.geometry_changed.emit(self.geometry())
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.black)
        painter.drawPath(notch_shape(self.width(), self.height(), self.expanded))
        if not self.expanded:
            app_icon(IRIS_COLORS[self.model.config["mascot_iris"]]).paint(painter, self.width() // 2 - 9, 5, 18, 18)

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
        self.recorder.cancel()
        worker = self.panes["music"].worker
        worker.stop()
        # Keep QThread alive until its bounded WinRT operations finish.
        worker.wait(15_000)
        if worker.isRunning():
            worker.wait()
        self.model.pool.waitForDone()


class Cyclop(QObject):
    """Connects the panel, mascot, tray, global shortcuts and background features."""

    def __init__(self, model, start_services=True):
        super().__init__()
        self.model = model
        self.start_services = start_services
        self.panel = Panel(model, start_services)
        self.recorder = self.panel.recorder
        self.volume = self.panel.volume
        self.mascot = MascotWindow(model, start_animation=start_services)
        self.mascot.clicked.connect(self.mascot_clicked)
        self.mascot.menu_requested.connect(lambda position: self.menu.popup(position))
        self.panel.geometry_changed.connect(self.mascot.set_anchor)
        self.mascot.set_anchor(self.panel.geometry())
        self.quick = QuickSettings(model, {
            "awake": self.set_awake, "ocr": lambda checked: self.start_ocr(), "voice": lambda checked: self.toggle_voice(),
            "record": lambda checked: self.toggle_recording(), "private": self.panel.privacy_button.setChecked,
            "pin": self.panel.pin_button.setChecked, "state": self.quick_state,
        }, self.volume)
        self.panel.quick_requested.connect(self.quick.popup)
        self.awake = False
        self.voice_active = False
        self.selector = None
        self.popup = None
        self.grabber = SelectionGrabber(model, self)
        self.grabber.grabbed.connect(self.show_lookup)
        self.grabber.failed.connect(self.notify)
        self.lookup_mode = "define"
        self.recorder.level.connect(lambda level: self.mascot.set_level(level) if self.voice_active else None)
        self.recorder.finished.connect(self.voice_recorded)
        self.recorder.failed.connect(lambda error: self.voice_failed(error) if self.voice_active else None)
        ocr = self.panel.panes["ocr"]
        ocr.capture_requested.connect(self.start_ocr)
        ocr.translate_requested.connect(lambda text: self.show_lookup(text, "translate") if text.strip() else None)
        self.panel.panes["settings"].hotkey_changed.connect(self.register_hotkeys)
        self.stats = StatsWorker(self)
        self.stats.sample.connect(self.mascot.set_stats)
        # Cyclop reacts to what you do: it gulps copied things and bobs to music.
        QApplication.clipboard().dataChanged.connect(self.clipboard_changed)
        media = self.panel.panes["music"].worker
        media.state.connect(self.mascot.set_media)
        media.background.set()
        # Opt-in webcam gaze, calibrated continuously from mouse movement.
        self.calibrator = GazeCalibrator()
        self.tracker = None
        self.camera_error = ""
        self.camera_fetching = False
        self.observations = 0
        self.mascot.tucked_changed.connect(lambda tucked: self.update_camera())
        self.camera_retry = QTimer(self)
        self.camera_retry.setSingleShot(True)
        self.camera_retry.timeout.connect(self.retry_camera)
        self.panel.panes["settings"].calibration_reset.connect(self.reset_calibration)
        self.hotkeys = HotkeyFilter()
        self.hotkey_signature = None
        self.build_tray()
        model.config_changed.connect(self.config_changed)
        self.config_changed()

    # ------------------------------------------------------------ tray and menus
    def build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(IRIS_COLORS[self.model.config["mascot_iris"]]), self)
        self.tray.setToolTip("Cyclop")
        menu = self.menu = QMenu()
        menu.addAction("Open / collapse", self.panel.toggle)
        menu.addAction("Quick settings…", lambda: self.quick.popup(QCursor.pos()))
        self.awake_action = menu.addAction(icon("awake"), "Keep awake")
        self.awake_action.setCheckable(True)
        self.awake_action.toggled.connect(self.set_awake)
        self.ocr_action = menu.addAction(icon("ocr"), "Capture text from screen", self.start_ocr)
        self.voice_action = menu.addAction(icon("mic"), "Voice command", self.toggle_voice)
        menu.addAction("Settings", self.open_settings)
        menu.addSeparator()
        hide = menu.addAction("Hide contents")
        hide.setCheckable(True)
        hide.toggled.connect(self.panel.privacy_button.setChecked)
        self.panel.privacy_button.toggled.connect(hide.setChecked)
        self.capture_action = menu.addAction("Capture clipboard text")
        self.capture_action.setCheckable(True)
        self.capture_action.toggled.connect(lambda value: self.model.configure("clipboard_enabled", value))
        self.mascot_action = menu.addAction("Show Cyclop mascot")
        self.mascot_action.setCheckable(True)
        self.mascot_action.toggled.connect(lambda value: self.model.configure("mascot_enabled", value))
        menu.addSeparator()
        menu.addAction("Quit Cyclop", self.request_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Sticky: the pointer is on the taskbar, so hover logic must not close it.
            self.panel.set_expanded(not self.panel.expanded, focus=True, sticky=True)

    def request_quit(self):
        self.panel.shutting_down = True
        QApplication.instance().quit()

    def open_settings(self):
        self.panel.select_tab("settings")
        self.panel.set_expanded(True, focus=True, sticky=True)

    def notify(self, text, seconds=3.5):
        if self.model.config["mascot_enabled"] and self.mascot.isVisible():
            self.mascot.say(text, seconds)
        elif self.tray.isVisible():
            self.tray.showMessage("Cyclop", text, QSystemTrayIcon.MessageIcon.NoIcon, int(seconds * 1000))
        self.panel.notify(text)

    def quick_state(self):
        return {"awake": self.awake, "record": self.recorder.recording and not self.voice_active,
                "private": self.panel.private, "pin": self.panel.pinned}

    # ------------------------------------------------------------ configuration
    def config_changed(self):
        config = self.model.config
        for action, value in ((self.capture_action, config["clipboard_enabled"]), (self.mascot_action, config["mascot_enabled"])):
            action.blockSignals(True)
            action.setChecked(bool(value))
            action.blockSignals(False)
        self.awake_action.setVisible(config["awake_enabled"])
        if not config["awake_enabled"] and self.awake:
            self.set_awake(False)
        self.voice_action.setVisible(config["voice_enabled"])
        self.tray.setIcon(app_icon(IRIS_COLORS[config["mascot_iris"]]))
        self.panel.setWindowIcon(app_icon(IRIS_COLORS[config["mascot_iris"]]))
        stats = config["mascot_enabled"] and config["stats_enabled"] and bool(config["stats_items"])
        if stats:
            self.stats.enabled.set()
            if self.start_services and not self.stats.isRunning():
                self.stats.start()
        else:
            self.stats.enabled.clear()
        self.update_camera()
        if not config["voice_enabled"] and self.voice_active:
            self.voice_active = False
            self.recorder.cancel()
            self.mascot.set_state("idle")
        signature = (tuple(sorted(config["hotkeys"].items())), config["ocr_enabled"], config["lookup_enabled"], config["voice_enabled"])
        if signature != self.hotkey_signature:
            self.register_hotkeys()
        self.panel.update()

    def register_hotkeys(self):
        config = self.model.config
        self.hotkey_signature = (tuple(sorted(config["hotkeys"].items())), config["ocr_enabled"], config["lookup_enabled"], config["voice_enabled"])
        wanted = {
            "panel": (True, self.hotkey_toggle),
            "ocr": (config["ocr_enabled"], self.start_ocr),
            "define": (config["lookup_enabled"], lambda: self.start_lookup("define")),
            "translate": (config["lookup_enabled"], lambda: self.start_lookup("translate")),
            "voice": (config["voice_enabled"], self.toggle_voice),
        }
        errors = []
        for name, (enabled, callback) in wanted.items():
            if enabled:
                error = self.hotkeys.set(name, config["hotkeys"][name], callback)
                if error:
                    errors.append(f"{HOTKEYS[name][0]}: {error}")
            else:
                self.hotkeys.remove(name)
        self.hotkey_errors = errors
        self.panel.panes["settings"].show_hotkey_errors(errors)
        self.tray.setToolTip("Cyclop · " + config["hotkeys"]["panel"])
        return errors

    def hotkey_toggle(self):
        self.panel.set_expanded(not self.panel.expanded, focus=True, sticky=True)

    def clipboard_changed(self):
        if not self.model.suppress_capture and self.model.config["mascot_enabled"]:
            self.mascot.gulp()

    # ------------------------------------------------------------ webcam gaze
    def camera_wanted(self):
        config = self.model.config
        return bool(self.start_services and config["camera_follow"] and config["mascot_enabled"]
                    and not self.mascot.tucked)

    def update_camera(self):
        """Run the camera only while it is wanted and Cyclop is visible; release it otherwise."""
        if not self.camera_wanted():
            if not self.model.config["camera_follow"]:
                self.camera_error = ""
                self.camera_retry.stop()
                self.set_camera_status("Cyclop learns where you look from your mouse movements once the webcam option is on.")
            self.stop_camera()
            return
        if self.tracker is not None and self.tracker.camera_index != self.model.config["camera_index"]:
            self.stop_camera()  # a different camera was chosen
            self.camera_error = ""
        if self.tracker is not None or self.camera_fetching or self.camera_error:
            return
        path = find_model(self.model.store.directory)
        if path is None:
            self.camera_fetching = True
            self.set_camera_status("Downloading the face detector (232 KB, verified)…")

            def fetched(result):
                self.camera_fetching = False
                self.update_camera()

            def failed(error):
                self.camera_fetching = False
                self.camera_failed(f"Could not get the face detector: {error}")
            self.model.run_job(lambda: download_model(self.model.store.directory / "models"), fetched, failed)
            return
        self.tracker = FaceTracker(path, self.model.config["camera_index"], self)
        self.tracker.observation.connect(self.camera_observation)
        self.tracker.failed.connect(self.camera_failed)
        self.tracker.opened.connect(lambda name: self.set_camera_status(f"Using {name}. " + self.calibration_text()))
        self.tracker.start()
        self.set_camera_status("Opening the camera…")

    def stop_camera(self):
        if self.tracker is not None:
            tracker, self.tracker = self.tracker, None
            tracker.stop()
            tracker.wait(3000)
            self.mascot.set_face(None)
            self.mascot.set_user_gaze(None)

    def camera_failed(self, error):
        first = not self.camera_error
        self.camera_error = error
        self.stop_camera()
        self.set_camera_status(error)
        if first:
            self.notify("Camera unavailable — Cyclop follows the mouse for now", 5)
        # Try again later (e.g. once a video call or the Camera app closes).
        self.camera_retry.start(20_000)

    def retry_camera(self):
        if self.model.config["camera_follow"] and self.camera_error:
            self.camera_error = ""
            self.update_camera()

    def camera_observation(self, observation):
        if observation is None:
            self.mascot.set_face(None)
            self.mascot.set_user_gaze(None)
            return
        features = observation["features"]
        self.mascot.set_face(observation["face"])
        desktop = QApplication.primaryScreen().virtualGeometry()
        now = time.monotonic()
        # You look at the pointer while moving it: that is a calibration sample.
        if now - self.mascot.last_pointer_move < 0.25 and 50 < self.mascot.pointer_speed < 2500:
            pointer = QCursor.pos()
            self.calibrator.add(features, ((pointer.x() - desktop.x()) / max(1, desktop.width()),
                                           (pointer.y() - desktop.y()) / max(1, desktop.height())))
        estimate = self.calibrator.predict(features)
        if estimate is None:
            self.mascot.set_user_gaze(None)
        else:
            self.mascot.set_user_gaze(QPoint(int(desktop.x() + estimate[0] * desktop.width()),
                                             int(desktop.y() + estimate[1] * desktop.height())))
        self.observations += 1
        if self.observations % 20 == 0:
            self.set_camera_status(self.calibration_text())

    def calibration_text(self):
        calibrator = self.calibrator
        if calibrator.calibrated:
            return f"Watching where you look · calibrated (typical error {calibrator.error * 100:.0f}% of the screen). Keeps improving as you use the mouse."
        return f"Learning where you look: {int(calibrator.progress * 100)}% · just use the mouse normally; until then Cyclop looks at you."

    def set_camera_status(self, text):
        self.panel.panes["settings"].camera_status.setText(text)

    def reset_calibration(self):
        self.calibrator.reset()
        self.camera_error = ""
        self.camera_retry.stop()
        self.set_camera_status(self.calibration_text())
        self.update_camera()

    # ------------------------------------------------------------ keep awake
    def set_awake(self, value):
        value = bool(value) and self.model.config["awake_enabled"]
        if value == self.awake:
            return
        self.awake = value
        keep_awake(value)
        self.awake_action.blockSignals(True)
        self.awake_action.setChecked(value)
        self.awake_action.blockSignals(False)
        self.notify("Staying awake — sleep is blocked" if value else "Sleep allowed again")

    # ------------------------------------------------------------ mascot & voice
    def mascot_clicked(self):
        if self.model.config["voice_enabled"]:
            self.toggle_voice()
        else:
            self.panel.set_expanded(not self.panel.expanded, focus=True, sticky=True)

    def toggle_voice(self):
        if self.voice_active:
            self.recorder.stop()
            return
        if not self.model.config["voice_enabled"]:
            self.notify("Voice commands are off — turn them on in Settings → Features")
            return
        if not Transcriber.available():
            self.notify("Speech recognition isn't installed in this build")
            return
        if self.recorder.recording:
            self.notify("The recorder is busy")
            return
        self.voice_active = True
        self.mascot.set_state("listening")
        self.mascot.say("Listening…", 8)
        self.recorder.start(command_mode=True, max_seconds=8)
        if not self.recorder.recording:
            self.voice_active = False
            self.mascot.set_state("idle")

    def voice_failed(self, error):
        self.voice_active = False
        self.mascot.set_state("idle")
        self.notify(error, 5)

    def voice_recorded(self, samples):
        if not self.voice_active:
            return
        self.voice_active = False
        self.mascot.set_state("thinking")
        self.mascot.say("Thinking…", 30)
        size, language = self.model.config["whisper_model"], self.model.config["speech_language"]
        models = self.model.store.directory / "models"

        def done(text):
            self.mascot.set_state("idle")
            self.execute(parse_command(text), text)

        def failed(error):
            self.mascot.set_state("idle")
            self.notify(f"Speech recognition failed: {error}", 6)
        self.model.run_job(lambda: Transcriber.transcribe(samples, models, size, language), done, failed)

    def execute(self, intent, heard=""):
        """Run an allow-listed action through the Windows API and say what happened."""
        action = intent.get("action")
        try:
            if action != "none":
                self.mascot.happy()
            if action == "open":
                open_target(intent["target"])
                self.notify(f"Opening {intent['name']}")
            elif action == "search":
                QDesktopServices.openUrl(QUrl("https://www.bing.com/search?q=" + quote_plus(intent["query"])))
                self.notify(f"Searching for {intent['query']}")
            elif action == "tab":
                self.panel.select_tab(intent["tab"])
                self.panel.set_expanded(True, focus=True, sticky=True)
                self.notify(f"Showing {TABS[intent['tab']]}")
            elif action == "key":
                key = intent["key"]
                press_key(key, 5 if key in ("volume_up", "volume_down") else 1)
                self.notify({"volume_up": "Louder", "volume_down": "Quieter", "mute": "Mute toggled",
                             "next": "Next track", "previous": "Previous track", "play": "Play / pause"}[key])
            elif action == "lock":
                self.notify("Locking the PC")
                QTimer.singleShot(400, lock_workstation)
            elif action == "ocr":
                QTimer.singleShot(300, self.start_ocr)
            elif action == "awake":
                self.set_awake(intent["value"])
            elif action == "time":
                self.notify(datetime.now().strftime("It's %H:%M"))
            elif action == "record":
                self.panel.select_tab("recorder")
                self.panel.set_expanded(True, focus=True, sticky=True)
                if not self.recorder.recording:
                    self.panel.panes["recorder"].toggle()
            elif action == "panel":
                self.panel.set_expanded(bool(intent["value"]), focus=bool(intent["value"]))
            else:
                self.notify(f"Didn't catch a command: “{heard.strip()[:60]}”" if heard.strip() else "I didn't hear anything", 5)
        except Exception as exc:
            self.mascot.set_state("error")
            QTimer.singleShot(1500, lambda: self.mascot.set_state("idle"))
            self.notify(f"Couldn't do that: {exc}", 5)

    def toggle_recording(self):
        self.panel.select_tab("recorder")
        self.panel.set_expanded(True, focus=True, sticky=True)
        self.panel.panes["recorder"].toggle()

    # ------------------------------------------------------------ text capture (image → text)
    def start_ocr(self):
        if self.selector is not None:
            return
        self.panel.set_expanded(False)
        self.panel.reposition()
        mascot_visible = self.mascot.isVisible()
        self.mascot.hide()

        def show_selector():
            self.selector = RegionSelector()
            self.selector.selected.connect(self.recognise)
            self.selector.cancelled.connect(lambda: self.finish_selection(mascot_visible))
            self.selector.selected.connect(lambda image, area: self.finish_selection(mascot_visible))
            self.selector.show()
        # Let the panel collapse and the mascot disappear before the freeze-frame.
        QTimer.singleShot(150, show_selector)

    def finish_selection(self, mascot_visible):
        self.selector = None
        if mascot_visible:
            self.mascot.apply_config()

    def recognise(self, image, area=None):
        pane = self.panel.panes["ocr"]
        pane.busy()
        # Red sonar sweeps the selected area while Cyclop stares at it and reads.
        overlay = None
        if area is not None and not area.isEmpty():
            overlay = ScanOverlay(area)
            overlay.show()
            self.mascot.look_at(area.center())
        self.mascot.set_state("scanning")
        variants = ocr_variants(image)

        def read_text():
            text = ""
            for png in variants:  # retry with inverted colours if nothing was found
                text = ocr_png(png)
                if text.strip():
                    break
            return text

        def done(text):
            if overlay is not None:
                overlay.finish(bool(text))
            self.mascot.set_state("idle")
            pane.show_result(image, text)
            if text:
                self.model.copy(text)
                self.mascot.happy()
                self.notify(f"Copied {len(text)} characters")
            else:
                self.notify("No text found in that area")

        def failed(error):
            if overlay is not None:
                overlay.finish(False)
            self.mascot.set_state("error")
            QTimer.singleShot(1200, lambda: self.mascot.set_state("idle"))
            pane.show_error(error)
            self.notify(error, 6)
        self.model.run_job(read_text, done, failed)

    # ------------------------------------------------------------ define / translate selection
    def start_lookup(self, mode):
        self.lookup_mode = mode
        self.grabber.start()

    def show_lookup(self, text, mode=None):
        if self.popup is not None:
            self.popup.close()
        self.popup = LookupPopup(self.model, text, mode or self.lookup_mode)
        self.popup.closed.connect(lambda: setattr(self, "popup", None))
        self.popup.place_near_cursor()
        self.popup.show()

    # ------------------------------------------------------------ lifecycle
    def show(self):
        self.tray.show()
        self.panel.show()
        self.mascot.apply_config()
        app = QApplication.instance()
        app.installNativeEventFilter(self.hotkeys)

    def shutdown(self):
        self.hotkeys.close()
        if self.awake:
            keep_awake(False)
        self.camera_retry.stop()
        self.stop_camera()
        self.mascot.shutdown()
        self.stats.stop()
        self.stats.wait(5000)
        if self.popup is not None:
            self.popup.close()
        self.panel.shutdown()
        self.tray.hide()


def main():
    parser = argparse.ArgumentParser(description="Cyclop for Windows 11")
    parser.add_argument("--expanded", action="store_true", help="Open the panel at launch")
    parser.add_argument("--smoke-test", action="store_true", help="Render the packaged UI, write a startup report and exit")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("CyclopWindows")
    app.setOrganizationName("MainTechAI")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    app.setWindowIcon(app_icon())
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, "Cyclop", "Cyclop is already running. Use the tray icon or its shortcut.")
        return
    model = Model(directory)
    cyclop = Cyclop(model)
    panel = cyclop.panel

    def shutdown():
        cyclop.shutdown()
        lock.unlock()
    app.aboutToQuit.connect(shutdown)
    cyclop.show()
    if args.expanded or args.smoke_test:
        panel.set_expanded(True, focus=True)
    if sys.platform == "win32" and cyclop.hotkey_errors:
        cyclop.tray.showMessage("Cyclop shortcuts", "\n".join(cyclop.hotkey_errors))
    if model.store.warnings:
        cyclop.tray.showMessage("Cyclop recovered saved data", "\n".join(model.store.warnings))
    if args.smoke_test:
        def verify_startup():
            try:
                panel.watcher.stop()
                panel.set_expanded(True)
                panel.reposition()
                picture = panel.grab()
                if picture.isNull() or not panel.body.isVisible():
                    raise RuntimeError("The expanded panel did not render")
                cyclop.mascot.tick()
                if model.config["mascot_enabled"] and cyclop.mascot.frame.isNull():
                    raise RuntimeError("The mascot did not render")
                report = {
                    "success": True, "platform": sys.platform,
                    "width": panel.width(), "height": panel.height(),
                    "pane_count": len(panel.panes), "hotkey_registered": cyclop.hotkeys.registered,
                    "hotkeys": {name: cyclop.hotkeys.is_registered(name) for name in HOTKEYS},
                    "mascot_rendered": not cyclop.mascot.frame.isNull(),
                    "speech_available": Transcriber.available(),
                    "volume_available": cyclop.volume.available,
                    "stats": {key: value for key, value in sample_once().items() if key != "details"},
                    "face_model_bundled": find_model() is not None,
                }
                (directory / "startup-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                picture.save(str(directory / "startup-panel.png"))
                cyclop.mascot.grab().save(str(directory / "startup-mascot.png"))
                cyclop.request_quit()
            except Exception as exc:
                (directory / "startup-check.json").write_text(json.dumps({"success": False, "error": str(exc)}), encoding="utf-8")
                app.exit(1)
        QTimer.singleShot(2000, verify_startup)
    sys.exit(app.exec())
