from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
import uuid

from PySide6.QtCore import Qt, QMimeData, QTimer, QUrl, QSize
from PySide6.QtGui import QDrag, QPixmap, QDesktopServices, QImageReader, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QSlider,
    QListWidget, QListWidgetItem, QAbstractItemView, QFileDialog, QFileIconProvider,
    QLineEdit, QPlainTextEdit, QTextEdit, QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox,
    QDialog, QDialogButtonBox, QFormLayout, QScrollArea, QApplication,
)

from .core import calendar_events, convert_currency, seconds_label, translation_direction
from .services import MediaWorker, fetch_rates, translate_offline
from .theme import icon
from .widgets import ElidedLabel, PanelComboBox, PanelDialog, PanelFileDialog


def label(text, secondary=False):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    if secondary:
        result.setObjectName("secondary")
    result.setWordWrap(True)
    return result


def button(text, action, tooltip=None):
    result = QPushButton(text)
    result.clicked.connect(action)
    if tooltip:
        result.setToolTip(tooltip)
    return result


def row(*widgets):
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        if widget is None:
            layout.addStretch()
        else:
            layout.addWidget(widget)
    return layout


class Pane(QWidget):
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 3, 0, 0)
        self.layout.setSpacing(8)

    def activated(self, active):
        pass


class MediaPane(Pane):
    def __init__(self, model, start_service=True, volume=None):
        super().__init__(model)
        self.art = QLabel()
        self.art.setFixedSize(108, 108)
        self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art.setPixmap(icon("music", "#555", 80).pixmap(80, 80))
        self.title = ElidedLabel("Nothing playing", lines=2)
        self.title.setObjectName("title")
        self.artist = ElidedLabel("Play media in an app that supports Windows media controls.")
        self.source = ElidedLabel()
        self.artist.setObjectName("secondary")
        self.source.setObjectName("secondary")
        detail = QVBoxLayout()
        detail.addWidget(self.title)
        detail.addWidget(self.artist)
        detail.addWidget(self.source)
        detail.addStretch()
        self.worker = MediaWorker(self)
        self.controls = {}
        controls = QHBoxLayout()
        controls.addStretch()
        for key, name in (("previous", "Previous track"), ("play", "Play / pause"), ("next", "Next track")):
            control = QToolButton()
            control.setIcon(icon(key))
            control.setToolTip(name)
            control.setAccessibleName(name)
            control.setFixedSize(42, 36)
            control.clicked.connect(lambda checked=False, command=key: self.worker.command(command))
            controls.addWidget(control)
            self.controls[key] = control
        controls.addStretch()
        detail.addLayout(controls)
        body = QHBoxLayout()
        body.addWidget(self.art)
        body.addSpacing(12)
        body.addLayout(detail, 1)
        self.layout.addLayout(body)
        self.elapsed, self.remaining = label("0:00", True), label("0:00", True)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setAccessibleName("Playback position")
        self.duration = 0
        self.seek.sliderReleased.connect(lambda: self.worker.command("seek", self.seek.value() / 1000 * self.duration))
        self.layout.addLayout(row(self.elapsed, self.seek, self.remaining))
        self.volume = None
        if volume is not None:
            from .features import VolumeControls
            self.volume = VolumeControls(model, volume)
            self.layout.addWidget(self.volume)
            show = lambda: self.volume.setVisible(bool(model.config["volume_enabled"]) and volume.available)
            model.config_changed.connect(show)
            show()
        self.layout.addStretch()
        self.worker.state.connect(self.update_state)
        self.worker.error.connect(self.media_error)
        self.previous_art = None
        self.update_state({"available": False})
        if start_service:
            self.worker.start()

    def media_error(self, text):
        self.source.setText(text)
        self.source.setToolTip(text)

    def update_state(self, state):
        available = state.get("available", False)
        self.title.setText(state.get("title", "Nothing playing"))
        self.artist.setText(state.get("artist", state.get("message", "Play media in an app that supports Windows media controls.")))
        self.source.setText(state.get("source", "").split("!")[0])
        if self.volume is not None and available:
            self.volume.set_media_source(state.get("source", ""))
        self.controls["play"].setIcon(icon("pause" if state.get("playing") else "play"))
        for name, control in self.controls.items():
            control.setEnabled(available and state.get("can_" + name, False))
        self.seek.setEnabled(available and state.get("can_seek", False))
        self.duration = max(0, state.get("duration", 0))
        position = max(0, state.get("position", 0))
        if not self.seek.isSliderDown():
            self.seek.setValue(int(1000 * position / self.duration) if self.duration else 0)
        self.elapsed.setText(seconds_label(position))
        self.remaining.setText(seconds_label(self.duration))
        art = state.get("art", b"")
        if art != self.previous_art:
            self.previous_art = art
            pixmap = QPixmap()
            if art and pixmap.loadFromData(art):
                self.art.setPixmap(pixmap.scaled(108, 108, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                self.art.setPixmap(icon("music", "#555", 80).pixmap(80, 80))

    def activated(self, active):
        if active:
            self.worker.enabled.set()
        else:
            self.worker.enabled.clear()
        if self.volume is not None:
            self.volume.activated(active)


class ShelfList(QListWidget):
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setIconSize(QSize(58, 58))
        self.setGridSize(QSize(112, 110))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.model.add_files(u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile())
            event.acceptProposedAction()

    def startDrag(self, actions):
        paths = [i.data(Qt.ItemDataRole.UserRole) for i in self.selectedItems()]
        if not paths:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        drag.setMimeData(mime)
        drag.setPixmap(icon("folder", size=40).pixmap(40, 40))
        drag.exec(Qt.DropAction.CopyAction)


class ShelfPane(Pane):
    def __init__(self, model):
        super().__init__(model)
        self.list = ShelfList(model)
        self.hint = label("Drop files here. Ctrl-click selects several; drag them out to copy.", True)
        self.layout.addWidget(self.hint)
        self.layout.addWidget(self.list, 1)
        self.layout.addLayout(row(button("Add files", self.add_files), None, button("Remove selected", self.remove)))
        self.list.itemDoubleClicked.connect(self.open_file)
        model.shelf_changed.connect(self.refresh)
        self.refresh()

    def add_files(self):
        dialog = PanelFileDialog(self, "Add files to shelf")
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        if dialog.exec():
            self.model.add_files(dialog.selectedFiles())
        dialog.deleteLater()

    def remove(self):
        self.model.remove_files([i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()])

    def open_file(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        # Reveal in Explorer instead of launching arbitrary executables.
        if Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
        else:
            self.model.status.emit("The original file was moved or deleted")

    def refresh(self):
        self.list.clear()
        for path in self.model.shelf:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path + "\nDouble-click to open containing folder")
            item.setIcon(icon("folder"))
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                reader = QImageReader(path)
                size = reader.size()
                if size.isValid() and size.width() * size.height() <= 40_000_000:
                    reader.setScaledSize(size.scaled(58, 58, Qt.AspectRatioMode.KeepAspectRatio))
                    image = reader.read()
                    if not image.isNull():
                        from PySide6.QtGui import QIcon
                        item.setIcon(QIcon(QPixmap.fromImage(image)))
            self.list.addItem(item)


class ClipboardPane(Pane):
    def __init__(self, model):
        super().__init__(model)
        self.toggle = QCheckBox("Capture clipboard text")
        self.toggle.setChecked(bool(model.config["clipboard_enabled"]))
        self.toggle.toggled.connect(lambda checked: model.configure("clipboard_enabled", checked))
        self.layout.addLayout(row(self.toggle, None, button("Clear", self.clear)))
        self.layout.addWidget(label("Last 40 copies, kept in memory only. Click to copy again. Pause before copying secrets.", True))
        self.list = QListWidget()
        self.list.itemClicked.connect(lambda item: model.copy(item.data(Qt.ItemDataRole.UserRole)))
        self.layout.addWidget(self.list, 1)
        model.clipboard_changed.connect(self.refresh)
        model.config_changed.connect(self.sync)
        self.refresh()

    def sync(self):
        self.toggle.blockSignals(True)
        self.toggle.setChecked(bool(self.model.config["clipboard_enabled"]))
        self.toggle.blockSignals(False)

    def clear(self):
        self.model.history.items.clear()
        self.refresh()

    def refresh(self):
        self.list.clear()
        for text in self.model.history.items:
            item = QListWidgetItem(text.replace("\n", "  ")[:160])
            item.setData(Qt.ItemDataRole.UserRole, text)
            self.list.addItem(item)


class SnippetsPane(Pane):
    def __init__(self, model):
        super().__init__(model)
        self.layout.addLayout(row(label("Your reusable text", True), None, button("+ Add", self.add)))
        self.list = QListWidget()
        self.list.itemClicked.connect(lambda item: model.copy(item.data(Qt.ItemDataRole.UserRole)["text"]))
        self.layout.addWidget(self.list, 1)
        self.layout.addLayout(row(label("Click to copy", True), None, button("Edit", self.edit), button("Remove", self.remove)))
        model.snippets_changed.connect(self.refresh)
        self.refresh()

    def editor(self, snippet=None):
        dialog = PanelDialog(self)
        dialog.setWindowTitle("Edit snippet" if snippet else "Add snippet")
        dialog.resize(430, 290)
        layout = QFormLayout(dialog)
        title = QLineEdit(snippet["title"] if snippet else "")
        text = QPlainTextEdit(snippet["text"] if snippet else "")
        layout.addRow("Name", title)
        layout.addRow("Text", text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        title.setFocus()
        value = None
        if dialog.exec() and text.toPlainText().strip():
            value = {"title": title.text().strip() or "Untitled", "text": text.toPlainText()}
        dialog.deleteLater()
        return value

    def add(self):
        value = self.editor()
        if value:
            self.model.snippets.append(value)
            self.save()

    def edit(self):
        index = self.list.currentRow()
        if index >= 0:
            value = self.editor(self.model.snippets[index])
            if value:
                self.model.snippets[index] = value
                self.save()

    def remove(self):
        index = self.list.currentRow()
        if index >= 0:
            del self.model.snippets[index]
            self.save()

    def save(self):
        self.model.persist("snippets", self.model.snippets)
        self.model.snippets_changed.emit()

    def refresh(self):
        self.list.clear()
        for snippet in self.model.snippets:
            item = QListWidgetItem(f'{snippet["title"]}   ·   {snippet["text"].replace(chr(10), " ")[:100]}')
            item.setData(Qt.ItemDataRole.UserRole, snippet)
            self.list.addItem(item)


class CalendarPane(Pane):
    def __init__(self, model):
        super().__init__(model)
        self.message = label("Import an .ics calendar exported from Outlook, Google Calendar, or another calendar.", True)
        self.layout.addWidget(self.message)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.join)
        self.layout.addWidget(self.list, 1)
        self.layout.addLayout(row(button("Import .ics", self.choose), button("Refresh", self.refresh), None, button("Join selected", self.join_selected)))
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self.refresh)
        self.busy = False

    def activated(self, active):
        if active:
            self.refresh()
            self.timer.start()
        else:
            self.timer.stop()

    def choose(self):
        dialog = PanelFileDialog(self, "Choose calendar", "iCalendar (*.ics)")
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        if dialog.exec():
            self.model.configure("calendar_path", dialog.selectedFiles()[0])
            self.refresh()
        dialog.deleteLater()

    def refresh(self):
        path = self.model.config.get("calendar_path")
        if not path or self.busy:
            return
        self.busy = True
        def load():
            with Path(path).open("rb") as stream:
                return calendar_events(stream.read(10_000_001))
        self.model.run_job(load, self.loaded, self.failed)

    def failed(self, error):
        self.busy = False
        self.list.clear()
        self.message.setText("Could not read calendar: " + error)

    def loaded(self, meetings):
        self.busy = False
        self.list.clear()
        self.message.setText("Next 7 days · local calendar file · double-click a meeting to join" if meetings else "No upcoming events in the next 7 days")
        for meeting in meetings:
            when = meeting.start.strftime("%a %d %b · All day" if meeting.all_day else "%a %d %b · %H:%M")
            item = QListWidgetItem(f'{when}  |  {meeting.title}' + ("  ↗" if meeting.link else ""))
            item.setData(Qt.ItemDataRole.UserRole, meeting.link)
            item.setToolTip(meeting.link or "No supported meeting URL in this event")
            self.list.addItem(item)

    def join_selected(self):
        item = self.list.currentItem()
        if item:
            self.join(item)

    def join(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            self.model.status.emit("This event has no supported meeting link")


class TranslatePane(Pane):
    def __init__(self, model):
        super().__init__(model)
        self.message = label("Offline · automatic English ↔ Russian · requires Argos language models", True)
        self.layout.addWidget(self.message)
        self.source, self.target = QPlainTextEdit(), QPlainTextEdit()
        self.source.setPlaceholderText("Type something to translate…")
        self.target.setPlaceholderText("Translation")
        self.source.setAccessibleName("Text to translate")
        self.target.setAccessibleName("Translation result")
        self.target.setReadOnly(True)
        self.layout.addLayout(row(self.source, self.target), 1)
        self.layout.addLayout(row(button("Translate", self.translate), None, button("Copy", lambda: model.copy(self.target.toPlainText()))))
        self.generation = 0
        self.active = False
        self.busy = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(650)
        self.timer.timeout.connect(self.translate)
        self.source.textChanged.connect(self.changed)

    def changed(self):
        self.generation += 1
        if not self.source.toPlainText().strip():
            self.target.clear()
        if self.active:
            self.timer.start()

    def activated(self, active):
        self.active = active
        if not active:
            self.timer.stop()

    def translate(self):
        text = self.source.toPlainText().strip()
        if not text or self.busy:
            return
        if len(text) > 5000:
            self.message.setText("Please use at most 5,000 characters")
            return
        self.busy = True
        generation = self.generation
        source, target = translation_direction(text)
        self.message.setText(f"Translating locally · {source.upper()} → {target.upper()}")
        def done(result, error=False):
            self.busy = False
            if generation == self.generation:
                if error:
                    self.message.setText(result)
                else:
                    self.target.setPlainText(result)
                    self.message.setText(f"Offline · {source.upper()} → {target.upper()}")
            elif self.active:
                self.timer.start()
        self.model.run_job(lambda: translate_offline(text, source, target), done, lambda error: done(error, True))


class CurrencyPane(Pane):
    def __init__(self, model):
        super().__init__(model)
        self.cache = model.store.load("rates", {})
        self.rates = self.cache.get("rates", {})
        self.message = label("Daily rates from Frankfurter. Fetch rates to begin; amounts stay on your computer.", True)
        self.layout.addWidget(self.message)
        self.source, self.target = PanelComboBox(), PanelComboBox()
        self.source.setAccessibleName("Source currency")
        self.target.setAccessibleName("Target currency")
        self.source.setMinimumWidth(76)
        self.target.setMinimumWidth(76)
        self.amount, self.result = QLineEdit("1"), QLineEdit()
        self.amount.setAccessibleName("Source amount")
        self.result.setAccessibleName("Converted amount")
        self.layout.addLayout(row(self.source, self.amount, label("→"), self.target, self.result))
        self.layout.addStretch()
        self.refresh_button = button("Fetch rates", self.fetch)
        self.layout.addLayout(row(self.refresh_button, None, button("Swap", self.swap)))
        self.source.currentTextChanged.connect(lambda: self.convert(False))
        self.target.currentTextChanged.connect(lambda: self.convert(False))
        self.amount.textEdited.connect(lambda: self.convert(False))
        self.result.textEdited.connect(lambda: self.convert(True))
        self.populate()

    def populate(self):
        previous_source = self.source.currentText() or "EUR"
        previous_target = self.target.currentText() or "USD"
        for control, selection in ((self.source, previous_source), (self.target, previous_target)):
            control.blockSignals(True)
            control.clear()
            # Currency choices are useful before the first download. Never
            # invent rates: conversion remains empty until real rates arrive.
            control.addItems(sorted(self.rates) if self.rates else
                             ["AUD", "BRL", "CAD", "CHF", "CNY", "DKK", "EUR", "GBP", "INR",
                              "JPY", "KRW", "NOK", "NZD", "PLN", "SEK", "TRY", "USD", "ZAR"])
            control.setCurrentText(selection)
            control.blockSignals(False)
        if self.rates:
            self.message.setText(f'Frankfurter · rates dated {self.cache.get("date", "unknown")} · cached locally')
        self.result.setPlaceholderText("Fetch rates first" if not self.rates else "Converted amount")
        self.convert(False)

    def fetch(self):
        self.refresh_button.setEnabled(False)
        self.message.setText("Fetching public daily exchange rates…")
        self.model.run_job(fetch_rates, self.loaded, self.failed)

    def loaded(self, cache):
        self.refresh_button.setEnabled(True)
        self.cache, self.rates = cache, cache["rates"]
        self.model.persist("rates", cache)
        self.populate()

    def failed(self, error):
        self.refresh_button.setEnabled(True)
        self.message.setText("Could not refresh rates. " + (f'Using cache dated {self.cache.get("date")}. ' if self.rates else "") + error)

    def convert(self, reverse=False):
        source, target = self.source.currentText(), self.target.currentText()
        entry, output = (self.result, self.amount) if reverse else (self.amount, self.result)
        if reverse:
            source, target = target, source
        try:
            output.setText(convert_currency(entry.text(), source, target, self.rates))
        except ValueError:
            output.clear()

    def swap(self):
        source, target, value = self.source.currentText(), self.target.currentText(), self.result.text()
        self.source.blockSignals(True)
        self.target.blockSignals(True)
        self.source.setCurrentText(target)
        self.target.setCurrentText(source)
        self.source.blockSignals(False)
        self.target.blockSignals(False)
        self.amount.setText(value or "1")
        self.convert()


class NotesPane(Pane):
    def __init__(self, model):
        super().__init__(model)
        self.select = PanelComboBox()
        self.layout.addLayout(row(self.select, button("+ New", self.new), button("Remove", self.remove)))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("A thought worth keeping…")
        self.layout.addWidget(self.text, 1)
        saved_hint = label("Saved on this computer", True)
        saved_hint.setWordWrap(False)
        self.layout.addLayout(row(saved_hint, None, button("Copy", lambda: model.copy(self.text.toPlainText()))))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.flush)
        self.current_id = None
        self.select.currentIndexChanged.connect(self.load)
        self.text.textChanged.connect(self.changed)
        self.refresh()

    def refresh(self, selected=None):
        self.select.blockSignals(True)
        self.select.clear()
        for note in self.model.notes:
            title = note["text"].split("\n")[0][:45] or "Untitled note"
            self.select.addItem(title, note["id"])
        if selected:
            self.select.setCurrentIndex(self.select.findData(selected))
        self.select.blockSignals(False)
        self.load()

    def load(self):
        self.current_id = self.select.currentData()
        note = next((n for n in self.model.notes if n["id"] == self.current_id), None)
        self.text.blockSignals(True)
        self.text.setPlainText(note["text"] if note else "")
        self.text.setEnabled(note is not None)
        self.text.blockSignals(False)

    def new(self):
        self.flush()
        note = {"id": uuid.uuid4().hex, "text": ""}
        self.model.notes.append(note)
        self.refresh(note["id"])
        self.flush()
        self.text.setFocus()

    def changed(self):
        for note in self.model.notes:
            if note["id"] == self.current_id:
                note["text"] = self.text.toPlainText()
                self.select.setItemText(self.select.currentIndex(), note["text"].split("\n")[0][:45] or "Untitled note")
                self.timer.start()
                break

    def remove(self):
        if self.current_id:
            self.model.notes = [n for n in self.model.notes if n["id"] != self.current_id]
            self.refresh()
            self.flush()

    def flush(self):
        self.timer.stop()
        self.model.persist("notes", self.model.notes)


class TeleprompterPane(Pane):
    def __init__(self, model):
        super().__init__(model)
        self.text = QTextEdit()
        self.text.setAcceptRichText(False)
        self.text.setPlainText(str(model.prompter.get("text", "")))
        self.text.setPlaceholderText("Paste your script here. Press Start to scroll beside your camera.")
        self.text.setFont(QFont("Segoe UI", 20))
        self.layout.addWidget(self.text, 1)
        self.speed = QSpinBox()
        self.speed.setRange(5, 150)
        self.speed.setSuffix(" px/s")
        self.speed.setValue(int(model.prompter.get("speed", 35)))
        self.start = button("Start", self.toggle)
        self.layout.addLayout(row(self.start, button("Reset", self.reset), None, label("Speed", True), self.speed))
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self.flush)
        self.text.textChanged.connect(lambda: self.save_timer.start())
        self.speed.valueChanged.connect(lambda: self.save_timer.start())
        self.position = 0.0
        self.last_time = time.monotonic()

    @property
    def running(self):
        return self.timer.isActive()

    def toggle(self):
        if self.running:
            self.pause()
        else:
            bar = self.text.verticalScrollBar()
            if bar.maximum() == 0:
                self.model.status.emit("The script fits on screen; add more text to scroll")
                return
            self.position = float(bar.value())
            self.last_time = time.monotonic()
            self.text.setReadOnly(True)
            self.start.setText("Pause")
            self.timer.start()

    def pause(self):
        self.timer.stop()
        self.text.setReadOnly(False)
        self.start.setText("Start")

    def reset(self):
        self.pause()
        self.text.verticalScrollBar().setValue(0)

    def tick(self):
        now = time.monotonic()
        self.position += self.speed.value() * (now - self.last_time)
        self.last_time = now
        bar = self.text.verticalScrollBar()
        bar.setValue(int(self.position))
        if bar.value() >= bar.maximum():
            self.pause()

    def activated(self, active):
        if not active:
            self.pause()

    def flush(self):
        self.save_timer.stop()
        self.model.persist("prompter", {"text": self.text.toPlainText(), "speed": self.speed.value()})
