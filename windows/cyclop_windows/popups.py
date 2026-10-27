"""Selection grabbing and the floating define/translate window."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QTimer, Qt, Signal, QObject
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from .core import lookup_word, translation_direction
from .services import fetch_definition, translate_offline
from . import windows as win


class SelectionGrabber(QObject):
    """Reads the foreground app's selected text via a synthetic Ctrl+C.

    Waits for the hotkey's modifier keys to be released (otherwise the app would
    receive Ctrl+Alt+C), copies, reads the text, then restores the clipboard.
    """
    grabbed = Signal(str)
    failed = Signal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.poll)
        self.phase = "idle"
        self.ticks = 0
        self.saved = None
        self.sequence = 0

    def start(self):
        if self.phase != "idle":
            return
        self.phase = "release"
        self.ticks = 0
        self.timer.start()

    def poll(self):
        self.ticks += 1
        if self.phase == "release":
            if win.modifiers_down() and self.ticks < 40:
                return
            self.saved = _snapshot(QGuiApplication.clipboard().mimeData())
            self.model.suppress_capture = True
            self.sequence = win.clipboard_sequence()
            win.send_copy()
            self.phase = "copy"
            self.ticks = 0
        elif self.phase == "copy":
            changed = win.clipboard_sequence() != self.sequence
            if not changed and self.ticks < 16:
                return
            text = QGuiApplication.clipboard().text() if changed else ""
            self.finish()
            if text.strip():
                self.grabbed.emit(text.strip())
            else:
                self.failed.emit("Select some text first, then press the shortcut")

    def finish(self):
        self.timer.stop()
        if self.saved is not None and self.phase == "copy":
            QGuiApplication.clipboard().setMimeData(self.saved)
        self.saved = None
        self.phase = "idle"
        QTimer.singleShot(200, lambda: setattr(self.model, "suppress_capture", False))


def _snapshot(data):
    copy = QMimeData()
    if data is not None:
        for fmt in data.formats():
            copy.setData(fmt, data.data(fmt))
    return copy


class LookupPopup(QFrame):
    """A small dark window near the cursor showing a definition or translation."""
    closed = Signal()

    def __init__(self, model, text, mode="define"):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.model = model
        self.text = text
        self.setObjectName("popup")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet("QFrame#popup { background: #111214; border: 1px solid #2c2d31; border-radius: 10px; }")
        self.setMinimumWidth(360)
        self.setMaximumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        self.heading = QLabel()
        self.heading.setObjectName("heading")
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setMinimumHeight(120)
        self.body.setStyleSheet("QTextBrowser { background: transparent; border: 0; }")
        self.editor = QPlainTextEdit(text)
        self.editor.setMaximumHeight(70)
        self.editor.setAccessibleName("Text to translate")
        self.editor.hide()
        self.status = QLabel()
        self.status.setObjectName("secondary")
        layout.addWidget(self.heading)
        layout.addWidget(self.title)
        layout.addWidget(self.editor)
        layout.addWidget(self.body, 1)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.define_button = QPushButton("Define")
        self.translate_button = QPushButton("Translate")
        copy_button = QPushButton("Copy result")
        close_button = QPushButton("Close")
        self.define_button.clicked.connect(lambda: self.show_mode("define"))
        self.translate_button.clicked.connect(lambda: self.show_mode("translate"))
        copy_button.clicked.connect(lambda: model.copy(self.body.toPlainText()))
        close_button.clicked.connect(self.close)
        for control in (self.define_button, self.translate_button):
            buttons.addWidget(control)
        buttons.addStretch()
        buttons.addWidget(copy_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        self.retranslate = QTimer(self)
        self.retranslate.setSingleShot(True)
        self.retranslate.setInterval(600)
        self.retranslate.timeout.connect(self.translate)
        self.editor.textChanged.connect(self.retranslate.start)
        self.generation = 0
        self.show_mode(mode)

    def place_near_cursor(self):
        self.adjustSize()
        position = QCursor.pos() + QPoint(16, 18)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x = min(max(bounds.left() + 8, position.x()), bounds.right() - self.width() - 8)
        y = position.y() if position.y() + self.height() < bounds.bottom() else QCursor.pos().y() - self.height() - 12
        self.move(x, max(bounds.top() + 8, y))

    def show_mode(self, mode):
        self.mode = mode
        self.generation += 1
        self.define_button.setEnabled(mode != "define")
        self.translate_button.setEnabled(mode != "translate")
        if mode == "define":
            self.editor.hide()
            self.heading.setText("DEFINITION")
            self.title.setText(self.text if len(self.text) < 80 else self.text[:77] + "…")
            self.title.show()
            self.define()
        else:
            self.heading.setText("TRANSLATION")
            self.title.hide()
            self.editor.blockSignals(True)
            self.editor.setPlainText(self.text)
            self.editor.blockSignals(False)
            self.editor.show()
            self.translate()

    def define(self):
        term = lookup_word(self.text)
        if term is None:
            self.body.setPlainText("Definitions work for a single word or a short term. Use Translate for longer text.")
            self.status.setText("")
            return
        if not self.model.config["lookup_online"]:
            self.body.setPlainText("Online dictionary lookups are turned off in Settings → Features.")
            return
        generation = self.generation
        self.body.setPlainText("Looking up…")
        self.status.setText("Wiktionary · only the selected word is sent")

        def done(entries):
            if generation != self.generation:
                return
            if not entries:
                self.body.setPlainText(f"No dictionary entry for “{term}”.")
                return
            html, last = [], None
            for part, definition in entries:
                if part != last:
                    html.append(f"<p style='color:#8c8c8c;margin:8px 0 2px'>{_escape(part)}</p>")
                    last = part
                html.append(f"<p style='margin:2px 0'>• {_escape(definition)}</p>")
            self.body.setHtml("".join(html))

        def failed(error):
            if generation == self.generation:
                self.body.setPlainText(f"Could not reach the dictionary: {error}")
        self.model.run_job(lambda: fetch_definition(term), done, failed)

    def translate(self):
        text = self.editor.toPlainText().strip() if self.editor.isVisible() else self.text
        if not text:
            self.body.clear()
            return
        text = text[:5000]
        generation = self.generation = self.generation + 1
        source, target = translation_direction(text)
        self.status.setText(f"Offline · {source.upper()} → {target.upper()}")
        self.body.setPlainText("Translating…")

        def done(result):
            if generation == self.generation:
                self.body.setPlainText(result)

        def failed(error):
            if generation == self.generation:
                self.body.setPlainText(error)
        self.model.run_job(lambda: translate_offline(text, source, target), done, failed)

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
