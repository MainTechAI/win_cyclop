"""Panes and controls for text capture, recording, volume, quick settings and settings."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFile, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QListWidget,
    QListWidgetItem, QPlainTextEdit, QProgressBar, QScrollArea, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from .core import HOTKEYS, IRIS_COLORS, STAT_KEYS, parse_hotkey
from .panes import Pane, button, label, row
from .speech import MODEL_SIZES, Transcriber, read_wav, recording_path, write_wav
from .theme import icon
from .widgets import PanelComboBox


# ---------------------------------------------------------------- text capture
class OcrPane(Pane):
    """Image → text: select a screen area, recognise it offline, copy the result."""
    capture_requested = Signal()
    translate_requested = Signal(str)

    def __init__(self, model):
        super().__init__(model)
        self.message = label("", True)
        self.layout.addWidget(self.message)
        self.preview = QLabel()
        self.preview.setFixedSize(150, 96)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: #121212; border-radius: 6px;")
        self.preview.setPixmap(icon("ocr", "#444", 40).pixmap(40, 40))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Recognised text appears here and is copied automatically.")
        self.text.setAccessibleName("Recognised text")
        self.layout.addLayout(row(self.preview, self.text), 1)
        self.capture_button = button("Capture area", self.capture_requested.emit)
        self.layout.addLayout(row(self.capture_button, None, button("Translate", lambda: self.translate_requested.emit(self.text.toPlainText())),
                                  button("Copy", lambda: model.copy(self.text.toPlainText()))))
        model.config_changed.connect(self.refresh_hint)
        self.refresh_hint()

    def refresh_hint(self):
        shortcut = self.model.config["hotkeys"]["ocr"]
        enabled = self.model.config["ocr_enabled"]
        self.message.setText(f"{shortcut} anywhere, or Capture area · offline Windows OCR · text is copied" if enabled
                             else "Global shortcut is off in Settings → Features. Capture area still works.")

    def busy(self):
        self.message.setText("Recognising text…")

    def show_result(self, image, text):
        pixmap = QPixmap.fromImage(image).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pixmap)
        self.text.setPlainText(text)
        self.message.setText("Copied to clipboard" if text else "No text found in that area")

    def show_error(self, error):
        self.message.setText(error)


# ---------------------------------------------------------------- recorder
class RecorderPane(Pane):
    """Record the microphone to WAV files and transcribe them offline."""

    def __init__(self, model, recorder):
        super().__init__(model)
        self.recorder = recorder
        self.folder = model.store.directory / "recordings"
        self.record_button = QToolButton()
        self.record_button.setIcon(icon("record", "#ff4b3e"))
        self.record_button.setIconSize(QSize(18, 18))
        self.record_button.setText(" Record")
        self.record_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.record_button.clicked.connect(self.toggle)
        self.clock = label("0:00", True)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(6)
        self.layout.addLayout(row(self.record_button, self.clock, self.meter))
        self.list = QListWidget()
        self.list.setAccessibleName("Recordings")
        self.transcript = QPlainTextEdit()
        self.transcript.setPlaceholderText("Select a recording and press Transcribe")
        self.transcript.setAccessibleName("Transcript")
        self.layout.addLayout(row(self.list, self.transcript), 1)
        self.transcribe_button = button("Transcribe", self.transcribe)
        self.layout.addLayout(row(self.transcribe_button, button("Play", self.play), button("Delete", self.delete),
                                  None, button("Copy", lambda: model.copy(self.transcript.toPlainText())),
                                  button("Folder", self.open_folder)))
        self.status = label("", True)
        self.layout.addWidget(self.status)
        self.mine = False
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(250)
        self.clock_timer.timeout.connect(self.tick)
        recorder.level.connect(lambda level: self.meter.setValue(int(level * 100)) if self.mine else None)
        recorder.finished.connect(self.recorded)
        recorder.failed.connect(lambda error: self.status.setText(error) if self.mine else None)
        self.list.currentItemChanged.connect(self.load_transcript)
        self.refresh()

    def refresh(self, select=None):
        self.list.clear()
        files = sorted(self.folder.glob("*.wav"), reverse=True) if self.folder.exists() else []
        for path in files:
            item = QListWidgetItem(path.stem.replace("Recording-", ""))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.list.addItem(item)
            if select and path == select:
                self.list.setCurrentItem(item)
        if not files:
            self.status.setText("Recordings are saved on this computer. Transcription runs offline.")

    def selected(self):
        item = self.list.currentItem()
        return Path(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def toggle(self):
        if self.recorder.recording:
            if self.mine:
                self.recorder.stop()
            return
        self.mine = True
        self.recorder.start(command_mode=False, max_seconds=3 * 3600)
        if self.recorder.recording:
            self.record_button.setIcon(icon("stop", "#ff4b3e"))
            self.record_button.setText(" Stop")
            self.status.setText("Recording from the default microphone…")
            self.clock_timer.start()
        else:
            self.mine = False

    def tick(self):
        seconds = int(self.recorder.elapsed)
        self.clock.setText(f"{seconds // 60}:{seconds % 60:02}")

    def recorded(self, samples):
        if not self.mine:
            return
        self.mine = False
        self.clock_timer.stop()
        self.meter.setValue(0)
        self.record_button.setIcon(icon("record", "#ff4b3e"))
        self.record_button.setText(" Record")
        if len(samples) == 0:
            self.status.setText("Nothing was recorded")
            return
        try:
            path = write_wav(recording_path(self.model.store.directory), samples)
        except OSError as exc:
            self.status.setText(f"Could not save the recording: {exc}")
            return
        self.status.setText(f"Saved {path.name}")
        self.refresh(path)

    def transcript_path(self, path):
        return path.with_suffix(".txt")

    def load_transcript(self):
        path = self.selected()
        text = ""
        if path and self.transcript_path(path).exists():
            try:
                text = self.transcript_path(path).read_text(encoding="utf-8")
            except OSError:
                pass
        self.transcript.setPlainText(text)

    def transcribe(self):
        path = self.selected()
        if not path:
            self.status.setText("Select a recording first")
            return
        if not Transcriber.available():
            self.status.setText("Speech recognition is not installed. From source: pip install -e .[speech]")
            return
        size = self.model.config["whisper_model"]
        language = self.model.config["speech_language"]
        models = self.model.store.directory / "models"
        self.transcribe_button.setEnabled(False)
        self.status.setText(f"Transcribing offline with Whisper {size}… the first run downloads the model ({MODEL_SIZES[size].split(',')[0]})")

        def work():
            return Transcriber.transcribe(read_wav(path), models, size, language)

        def done(text):
            self.transcribe_button.setEnabled(True)
            try:
                self.transcript_path(path).write_text(text, encoding="utf-8")
            except OSError:
                pass
            if self.selected() == path:
                self.transcript.setPlainText(text or "(no speech detected)")
            self.status.setText("Transcript saved next to the recording")

        def failed(error):
            self.transcribe_button.setEnabled(True)
            self.status.setText(f"Transcription failed: {error}")
        self.model.run_job(work, done, failed)

    def play(self):
        path = self.selected()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def delete(self):
        path = self.selected()
        if not path:
            return
        for target in (path, self.transcript_path(path)):
            if target.exists() and not QFile.moveToTrash(str(target)):
                self.status.setText(f"Could not move {target.name} to the Recycle Bin")
                return
        self.status.setText(f"Moved {path.name} to the Recycle Bin")
        self.refresh()

    def open_folder(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))


# ---------------------------------------------------------------- volume
class VolumeControls(QWidget):
    """App volume (follows the playing media app) and overall output volume."""

    def __init__(self, model, volume):
        super().__init__()
        self.model = model
        self.volume = volume
        self.media_process = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.apps = PanelComboBox()
        self.apps.setAccessibleName("App whose volume to change")
        self.apps.setMinimumWidth(130)
        self.app_slider = self._slider("App volume")
        self.app_value = label("", True)
        self.master_slider = self._slider("Output volume")
        self.master_value = label("", True)
        icon_label = QLabel()
        icon_label.setPixmap(icon("volume", "#8c8c8c", 16).pixmap(16, 16))
        layout.addLayout(row(icon_label, self.apps, self.app_slider, self.app_value))
        output = label("Output", True)
        output.setFixedWidth(icon_label.sizeHint().width() + 136)
        layout.addLayout(row(output, self.master_slider, self.master_value))
        self.app_slider.valueChanged.connect(self.app_changed)
        self.master_slider.valueChanged.connect(self.master_changed)
        self.apps.activated.connect(lambda: self.refresh(keep=True))
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(lambda: self.refresh(keep=True))
        if not volume.available:
            for widget in (self.apps, self.app_slider, self.master_slider):
                widget.setEnabled(False)
            self.app_value.setText("")
            self.setToolTip(volume.error)

    def _slider(self, name):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setAccessibleName(name)
        return slider

    def set_media_source(self, source):
        from .system import process_for_source
        process = process_for_source(source) if source else ""
        if process != self.media_process:
            self.media_process = process
            self.refresh(keep=False)

    def refresh(self, keep=True):
        if not self.volume.available:
            return
        current = self.apps.currentData() if keep else None
        sessions = self.volume.sessions()
        self.apps.blockSignals(True)
        self.apps.clear()
        for name, value in sessions:
            self.apps.addItem(name.removesuffix(".exe").removesuffix(".EXE"), (name, value))
        names = [name.lower() for name, _ in sessions]
        wanted = (current[0] if current else self.media_process).lower()
        if wanted in names:
            self.apps.setCurrentIndex(names.index(wanted))
        self.apps.blockSignals(False)
        data = self.apps.currentData()
        self._set_slider(self.app_slider, data[1] if data else None, self.app_value)
        self.app_slider.setEnabled(data is not None)
        if not sessions:
            self.apps.addItem("No app is playing sound", None)
        self._set_slider(self.master_slider, self.volume.master(), self.master_value)

    def _set_slider(self, slider, value, text):
        if slider.isSliderDown():
            return
        slider.blockSignals(True)
        slider.setValue(int(round((value or 0) * 100)))
        slider.blockSignals(False)
        text.setText(f"{int(round((value or 0) * 100))}%" if value is not None else "–")

    def app_changed(self, value):
        data = self.apps.currentData()
        if data and self.volume.set_app(data[0], value / 100):
            self.app_value.setText(f"{value}%")

    def master_changed(self, value):
        self.volume.set_master(value / 100)
        self.master_value.setText(f"{value}%")

    def activated(self, active):
        if active and self.volume.available and self.model.config["volume_enabled"]:
            self.refresh(keep=True)
            self.timer.start()
        else:
            self.timer.stop()


# ---------------------------------------------------------------- quick settings flyout
class Tile(QToolButton):
    def __init__(self, key, text, checkable=False):
        super().__init__()
        self.setObjectName("tile")
        self.setIcon(icon(key, "#d0d0d0", 20))
        self.setIconSize(QSize(20, 20))
        self.setText(text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setCheckable(checkable)
        self.setFixedSize(92, 62)
        self.setAccessibleName(text)


class QuickSettings(QFrame):
    """A Windows 11-style quick settings flyout: toggle tiles and a volume slider."""

    def __init__(self, model, actions, volume):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("flyout")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.model = model
        self.actions = actions
        self.volume = volume
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        grid = self.grid = QGridLayout()
        grid.setSpacing(8)
        self.tiles = {
            "awake": Tile("awake", "Keep awake", True),
            "ocr": Tile("ocr", "Text capture"),
            "voice": Tile("mic", "Voice"),
            "record": Tile("recorder", "Record", True),
            "private": Tile("eye", "Hide contents", True),
            "pin": Tile("pin", "Keep open", True),
        }
        for index, (key, tile) in enumerate(self.tiles.items()):
            grid.addWidget(tile, index // 3, index % 3)
            tile.clicked.connect(lambda checked=False, key=key: self.activate(key, checked))
        layout.addLayout(grid)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setAccessibleName("Output volume")
        self.slider_value = label("", True)
        volume_icon = QLabel()
        volume_icon.setPixmap(icon("volume", "#b9b9b9", 18).pixmap(18, 18))
        layout.addLayout(row(volume_icon, self.slider, self.slider_value))
        self.slider.valueChanged.connect(self.set_volume)
        self.volume_row = [volume_icon, self.slider, self.slider_value]

    def activate(self, key, checked):
        action = self.actions.get(key)
        if action:
            if key in ("ocr", "voice"):
                self.close()
            action(checked)
        self.sync()

    def sync(self, states=None):
        config = self.model.config
        states = states or self.actions["state"]()
        visible = {"awake": config["awake_enabled"], "ocr": True, "voice": config["voice_enabled"],
                   "record": "recorder" not in config["disabled_tabs"], "private": True, "pin": True}
        shown = 0
        for key, tile in self.tiles.items():
            self.grid.removeWidget(tile)
            tile.setVisible(visible[key])
            if visible[key]:
                self.grid.addWidget(tile, shown // 3, shown % 3)
                shown += 1
            if tile.isCheckable():
                tile.blockSignals(True)
                tile.setChecked(bool(states.get(key)))
                tile.blockSignals(False)
        level = self.volume.master() if self.volume.available and config["volume_enabled"] else None
        for widget in self.volume_row:
            widget.setVisible(level is not None)
        if level is not None:
            self.slider.blockSignals(True)
            self.slider.setValue(int(round(level * 100)))
            self.slider.blockSignals(False)
            self.slider_value.setText(f"{int(round(level * 100))}%")

    def set_volume(self, value):
        self.volume.set_master(value / 100)
        self.slider_value.setText(f"{value}%")

    def popup(self, position):
        self.sync()
        self.adjustSize()
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x = min(max(bounds.left() + 8, position.x() - self.width() // 2), bounds.right() - self.width() - 8)
        y = position.y() if position.y() + self.height() < bounds.bottom() else position.y() - self.height()
        self.move(x, max(bounds.top() + 8, y))
        self.show()


# ---------------------------------------------------------------- settings
class TabArrangement(QWidget):
    """Reorder and show/hide the panel tabs. A divider row splits the left and right rails.

    Drag and drop works with the mouse; Move up / Move down work with the keyboard.
    Settings stays at the bottom of the right rail and cannot be hidden.
    """
    DIVIDER = "__divider__"
    ROW = 26

    def __init__(self, model, tab_names):
        super().__init__()
        self.model = model
        self.names = tab_names
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setAccessibleName("Panel tabs in order")
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setStyleSheet(
            "QListWidget::item { padding: 2px 6px; margin: 1px 0; }"
            "QListWidget::indicator { width: 13px; height: 13px; border: 1px solid #666; border-radius: 3px; background: #151515; }"
            "QListWidget::indicator:checked { background: #85a9df; border-color: #85a9df; }")
        self.list.setIconSize(QSize(16, 16))
        layout.addWidget(self.list)
        self.up = button("Move up", lambda: self.move(-1))
        self.down = button("Move down", lambda: self.move(1))
        layout.addLayout(row(self.up, self.down, None, button("Reset order", self.reset)))
        self.list.model().rowsMoved.connect(lambda *args: self.apply())
        self.list.itemChanged.connect(lambda item: self.apply())
        self.list.currentRowChanged.connect(lambda *args: self.update_buttons())
        self.refresh()

    def refresh(self):
        from PySide6.QtWidgets import QListWidgetItem
        config = self.model.config
        current = self.current_key()
        self.list.blockSignals(True)
        self.list.model().blockSignals(True)
        self.list.clear()
        movable = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        for side in ("left", "right"):
            if side == "right":
                divider = QListWidgetItem("──────  right rail  ──────")
                divider.setData(Qt.ItemDataRole.UserRole, self.DIVIDER)
                divider.setFlags(movable)
                divider.setForeground(QColor("#8c8c8c"))
                divider.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.list.addItem(divider)
            for key in config["tab_layout"][side]:
                item = QListWidgetItem(icon(key), self.names[key])
                item.setData(Qt.ItemDataRole.UserRole, key)
                if key == "settings":
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    item.setToolTip("Settings always stays at the bottom of the right rail")
                else:
                    item.setFlags(movable | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked if key in config["disabled_tabs"] else Qt.CheckState.Checked)
                self.list.addItem(item)
        row_height = self.list.sizeHintForRow(0) if self.list.count() else self.ROW
        self.list.setFixedHeight(self.list.count() * max(row_height, 18) + 2 * self.list.frameWidth() + 4)
        self.list.model().blockSignals(False)
        self.list.blockSignals(False)
        if current is not None:
            self.select(current)
        self.update_buttons()

    def current_key(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select(self, key):
        for index in range(self.list.count()):
            if self.list.item(index).data(Qt.ItemDataRole.UserRole) == key:
                self.list.setCurrentRow(index)
                return

    def order(self):
        return [self.list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.list.count())]

    def apply(self):
        """Store the list as the tab layout and the hidden set; the panel updates live."""
        from .core import normalise_layout
        keys = self.order()
        split = keys.index(self.DIVIDER) if self.DIVIDER in keys else len(keys)
        layout = normalise_layout({"left": keys[:split], "right": keys[split + 1:]})
        hidden = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            key = item.data(Qt.ItemDataRole.UserRole)
            if key not in (self.DIVIDER, "settings") and item.checkState() == Qt.CheckState.Unchecked:
                hidden.append(key)
        if sorted(hidden) != self.model.config["disabled_tabs"]:
            self.model.configure("disabled_tabs", sorted(hidden))
        if layout != self.model.config["tab_layout"]:
            self.model.configure("tab_layout", layout)
        self.refresh()  # show the repaired order (e.g. Settings back at the bottom)

    def move(self, step):
        row_index = self.list.currentRow()
        target = row_index + step
        key = self.current_key()
        if key in (None, "settings") or not 0 <= target < self.list.count():
            return
        if self.list.item(target).data(Qt.ItemDataRole.UserRole) == "settings":
            return
        self.list.model().blockSignals(True)
        item = self.list.takeItem(row_index)
        self.list.insertItem(target, item)
        self.list.model().blockSignals(False)
        self.apply()
        self.select(key)

    def update_buttons(self):
        key = self.current_key()
        row_index = self.list.currentRow()
        last_movable = self.list.count() - 2  # Settings is last
        self.up.setEnabled(key not in (None, "settings") and row_index > 0)
        self.down.setEnabled(key not in (None, "settings") and row_index < last_movable)

    def reset(self):
        from .core import DEFAULT_LEFT, DEFAULT_RIGHT
        self.model.configure("tab_layout", {"left": list(DEFAULT_LEFT), "right": list(DEFAULT_RIGHT)})
        self.refresh()


class SettingsPane(Pane):
    """Every feature can be switched on or off here; changes apply immediately."""
    hotkey_changed = Signal()
    calibration_reset = Signal()

    def __init__(self, model, tab_names):
        super().__init__(model)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        self.content = QVBoxLayout(body)
        self.content.setContentsMargins(0, 0, 7, 0)
        self.controls = {}

        self.section("PANEL")
        self.check("Open on hover", "hover_open")
        self.check("Switch tabs after hovering an icon", "hover_tabs")
        self.check("Cycle tabs in a loop (Ctrl+Tab, mouse wheel, click the title)", "tab_cycling")
        self.check("Save clipboard images to the shelf", "capture_images")
        self.screens = PanelComboBox()
        self.screens.addItem("Primary display", "")
        for screen in QApplication.screens():
            self.screens.addItem(screen.name(), screen.name())
        self.screens.setCurrentIndex(max(0, self.screens.findData(model.config["screen"])))
        self.screens.currentIndexChanged.connect(lambda: model.configure("screen", self.screens.currentData()))
        self.content.addLayout(row(label("Display", True), self.screens, None))

        self.section("CYCLOP MASCOT")
        self.check("Show the 3D Cyclop eye beside the notch", "mascot_enabled")
        self.check("Slide up out of the way when idle", "mascot_autohide")
        seconds = QSpinBox()
        seconds.setRange(2, 120)
        seconds.setSuffix(" s")
        seconds.setValue(int(model.config["mascot_autohide_seconds"]))
        seconds.valueChanged.connect(lambda value: model.configure("mascot_autohide_seconds", value))
        self.content.addLayout(row(label("Hide after", True), seconds, None))
        self.check("Eye follows the mouse pointer", "mascot_follow_cursor")
        iris = PanelComboBox()
        iris.addItems(list(IRIS_COLORS))
        iris.setCurrentText(model.config["mascot_iris"])
        iris.currentTextChanged.connect(lambda value: model.configure("mascot_iris", value))
        self.content.addLayout(row(label("Eye colour", True), iris, None))
        self.check("Look where I look, using the webcam (opt-in; video stays on this PC)", "camera_follow")
        camera = QSpinBox()
        camera.setRange(0, 9)
        camera.setPrefix("Camera ")
        camera.setValue(int(model.config["camera_index"]))
        camera.valueChanged.connect(lambda value: model.configure("camera_index", value))
        self.camera_status = label("Cyclop learns where you look from your mouse movements: move the mouse around normally for a minute.", True)
        self.content.addLayout(row(camera, button("Reset calibration", self.calibration_reset.emit), None))
        self.content.addWidget(self.camera_status)

        self.section("SYSTEM STATS UNDER CYCLOP")
        self.check("Show live system stats", "stats_enabled")
        stats_row = QHBoxLayout()
        for key, name in STAT_KEYS.items():
            control = QCheckBox(name)
            control.setChecked(key in model.config["stats_items"])
            control.toggled.connect(lambda checked, key=key: self.toggle_list("stats_items", key, checked, list(STAT_KEYS)))
            stats_row.addWidget(control)
        stats_row.addStretch()
        self.content.addLayout(stats_row)

        self.section("FEATURES")
        self.check("Text capture shortcut (image → text)", "ocr_enabled")
        self.check("Define / translate selected text shortcuts", "lookup_enabled")
        self.check("Allow online dictionary lookups (sends only the selected word to Wiktionary)", "lookup_online")
        self.check("Voice commands (offline Whisper; click Cyclop or use the shortcut)", "voice_enabled")
        self.check("Keep-awake tile in quick settings and tray", "awake_enabled")
        self.check("Volume sliders in Music and quick settings", "volume_enabled")
        whisper = PanelComboBox()
        for size, note in MODEL_SIZES.items():
            whisper.addItem(f"{size} · {note}", size)
        whisper.setCurrentIndex(max(0, whisper.findData(model.config["whisper_model"])))
        whisper.currentIndexChanged.connect(lambda: model.configure("whisper_model", whisper.currentData()))
        language = PanelComboBox()
        for name, code in (("Detect language", "auto"), ("English", "en"), ("Russian", "ru")):
            language.addItem(name, code)
        language.setCurrentIndex(max(0, language.findData(model.config["speech_language"])))
        language.currentIndexChanged.connect(lambda: model.configure("speech_language", language.currentData()))
        self.content.addLayout(row(label("Speech model", True), whisper, language, None))
        if not Transcriber.available():
            self.content.addWidget(label("Speech recognition is not installed in this build. From source: pip install -e .[speech]", True))

        self.section("SHORTCUTS")
        self.hotkey_status = label("", True)
        for key, (title, default) in HOTKEYS.items():
            editor = QKeySequenceEdit(QKeySequence(model.config["hotkeys"].get(key, default)))
            editor.setMaximumSequenceLength(1)
            editor.setAccessibleName(title)
            editor.editingFinished.connect(lambda key=key, editor=editor: self.set_hotkey(key, editor))
            reset = QToolButton()
            reset.setText("Reset")
            reset.clicked.connect(lambda checked=False, key=key, editor=editor, default=default: (editor.setKeySequence(QKeySequence(default)), self.set_hotkey(key, editor)))
            name = label(title, True)
            name.setFixedWidth(210)
            self.content.addLayout(row(name, editor, reset))
        self.content.addWidget(self.hotkey_status)

        self.section("PANEL TABS")
        self.content.addWidget(label("Drag tabs to rearrange them, or use the arrows. Tabs above the divider go on the left rail, "
                                     "tabs below it on the right. Untick a tab to hide it.", True))
        self.arrangement = TabArrangement(model, tab_names)
        self.content.addWidget(self.arrangement)
        self.content.addWidget(label("Escape collapses the panel. Clipboard history is session-only. Notes, snippets and recordings stay on this computer.\n"
                                     "Currency requests happen only when you press Fetch rates.", True))
        self.content.addWidget(button("Open data folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(model.store.directory)))))
        self.content.addStretch()
        from . import __version__
        self.version = label(f"Cyclop for Windows {__version__}", True)
        self.version.setWordWrap(False)
        self.version.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.version.setAccessibleName("Version")
        notes = button("Release notes", lambda: QDesktopServices.openUrl(
            QUrl(f"https://github.com/MainTechAI/win_cyclop/releases/tag/windows-v{__version__}")))
        latest = button("Latest version", lambda: QDesktopServices.openUrl(QUrl("https://github.com/MainTechAI/win_cyclop/releases/latest")))
        self.content.addSpacing(6)
        self.content.addLayout(row(self.version, None, notes, latest))
        scroll.setWidget(body)
        self.layout.addWidget(scroll)

    def section(self, text):
        heading = label(text, False)
        heading.setObjectName("heading")
        self.content.addSpacing(6)
        self.content.addWidget(heading)

    def check(self, title, key):
        control = QCheckBox(title)
        control.setChecked(bool(self.model.config[key]))
        control.toggled.connect(lambda checked, key=key: self.model.configure(key, checked))
        self.controls[key] = control
        self.content.addWidget(control)
        return control

    def toggle_list(self, key, item, checked, order):
        values = set(self.model.config[key])
        values.add(item) if checked else values.discard(item)
        self.model.configure(key, [value for value in order if value in values])

    def set_hotkey(self, key, editor):
        text = editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if not text:
            return
        try:
            parse_hotkey(text)
        except ValueError as exc:
            self.hotkey_status.setText(str(exc))
            editor.setKeySequence(QKeySequence(self.model.config["hotkeys"][key]))
            return
        hotkeys = dict(self.model.config["hotkeys"])
        hotkeys[key] = text
        self.model.configure("hotkeys", hotkeys)
        self.hotkey_changed.emit()

    def show_hotkey_errors(self, errors):
        self.hotkey_status.setText("\n".join(errors))
