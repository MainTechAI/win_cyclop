from datetime import datetime
from pathlib import Path
import uuid

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import QApplication

from .core import Store, ClipboardHistory, normalise_config, normalise_paths, sensitive_formats
from .services import Job
from .windows import clipboard_is_private


class Model(QObject):
    shelf_changed = Signal()
    clipboard_changed = Signal()
    snippets_changed = Signal()
    config_changed = Signal()
    status = Signal(str)

    def __init__(self, directory=None):
        super().__init__()
        self.store = Store(directory)
        self.config = normalise_config(self.store.load("config", {}))
        if not isinstance(self.config.get("disabled_tabs"), list):
            self.config["disabled_tabs"] = []
        # Set while Cyclop itself reads the selection via a synthetic copy.
        self.suppress_capture = False
        self.shelf = normalise_paths(p for p in self.store.load("shelf", []) if isinstance(p, str))
        self.snippets = [s for s in self.store.load("snippets", []) if isinstance(s, dict) and isinstance(s.get("text"), str) and isinstance(s.get("title"), str)]
        self.notes = [n for n in self.store.load("notes", []) if isinstance(n, dict) and isinstance(n.get("text"), str) and isinstance(n.get("id"), str)]
        self.prompter = self.store.load("prompter", {"text": "", "speed": 35})
        self.history = ClipboardHistory()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.jobs = set()
        self.copying = False
        QApplication.clipboard().dataChanged.connect(self.capture_clipboard)

    def persist(self, name, value):
        try:
            self.store.save(name, value)
            return True
        except OSError as exc:
            self.status.emit(f"Could not save {name}: {exc}")
            return False

    def configure(self, key, value):
        self.config[key] = value
        self.persist("config", self.config)
        self.config_changed.emit()

    def run_job(self, function, success, failure=None):
        job = Job(function)
        self.jobs.add(job)
        job.signals.result.connect(success)
        job.signals.error.connect(failure or self.status.emit)
        job.signals.finished.connect(lambda: self.jobs.discard(job))
        self.pool.start(job)
        return job

    def copy(self, text):
        self.copying = True
        try:
            QApplication.clipboard().setText(text)
        finally:
            self.copying = False
        self.status.emit("Copied")

    def add_files(self, paths):
        self.shelf = normalise_paths(self.shelf + list(paths))
        self.persist("shelf", self.shelf)
        self.shelf_changed.emit()

    def remove_files(self, paths):
        self.shelf = [path for path in self.shelf if path not in paths]
        self.persist("shelf", self.shelf)
        self.shelf_changed.emit()

    def capture_clipboard(self):
        disabled = self.config["disabled_tabs"]
        capture_text = self.config["clipboard_enabled"] and "clipboard" not in disabled
        capture_image = self.config["capture_images"] and "shelf" not in disabled
        if self.copying or self.suppress_capture or not (capture_text or capture_image) or clipboard_is_private():
            return
        clipboard = QApplication.clipboard()
        data = clipboard.mimeData()
        if data is None or sensitive_formats(data.formats()):
            return
        if capture_image and data.hasImage():
            image = clipboard.image()
            if not image.isNull() and image.width() * image.height() <= 40_000_000:
                folder = self.store.directory / "screenshots"
                try:
                    folder.mkdir(exist_ok=True)
                    filename = folder / f"Screenshot-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.png"
                    if image.save(str(filename), "PNG"):
                        self.add_files([str(filename)])
                    else:
                        self.status.emit("Could not save the clipboard image")
                except OSError as exc:
                    self.status.emit(str(exc))
        elif capture_text and data.hasText() and self.history.add(data.text()):
            self.clipboard_changed.emit()
