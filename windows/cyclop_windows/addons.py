"""Optional features that are downloaded only when you turn them on.

Speech recognition (≈190 MB) and webcam gaze (≈110 MB) are most of what the app
would otherwise unpack on every launch, while they are off for most people. The
release publishes them as zips next to the exe; the exact sizes and SHA-256
hashes are built into the app (assets/addons.json), so a download is installed
only if it is byte-for-byte the file that release was tested with.

From source (pip) the packages are simply installed: pip install -e .[speech,camera]
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from urllib.request import Request, urlopen
import zipfile

from PySide6.QtCore import QObject, Signal

from . import __version__
from .core import data_directory

RELEASE_URL = "https://github.com/MainTechAI/win_cyclop/releases/download/windows-v{version}/{file}"


@dataclass(frozen=True)
class Addon:
    name: str
    title: str
    modules: tuple[str, ...]       # importable once installed
    requirements: tuple[str, ...]  # pip distributions it is built from


ADDONS = {
    "speech": Addon("speech", "Speech recognition", ("faster_whisper",), ("faster-whisper",)),
    "camera": Addon("camera", "Webcam gaze", ("cv2",), ("opencv-python-headless",)),
}
_lock = threading.Lock()
_activated: set[str] = set()
_dll_handles = []


def manifest() -> dict:
    """Downloads available for this build, or {} (running from source, or a build without add-ons)."""
    path = Path(__file__).with_name("assets") / "addons.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def folder(name: str, root: Path | None = None) -> Path:
    return (root or data_directory()) / "addons" / f"{name}-{__version__}"


def installed(name: str, root: Path | None = None) -> bool:
    return (folder(name, root) / "cyclop-addon.json").is_file()


def activate(name: str, root: Path | None = None) -> bool:
    """Make an installed add-on importable. Cheap; safe to call often."""
    if name in _activated:
        return True
    if not installed(name, root):
        return False
    path = str(folder(name, root))
    with _lock:
        if name not in _activated:
            if path not in sys.path:
                sys.path.append(path)     # after the app's own modules, which always win
            if hasattr(os, "add_dll_directory"):
                try:
                    _dll_handles.append(os.add_dll_directory(path))
                except OSError:
                    pass
            importlib.invalidate_caches()
            _activated.add(name)
    return True


def ready(name: str, root: Path | None = None) -> bool:
    """Whether the feature's packages can be imported now (installed with pip, or a downloaded add-on)."""
    activate(name, root)
    try:
        return all(importlib.util.find_spec(module) is not None for module in ADDONS[name].modules)
    except (ImportError, ValueError):
        return False


def downloadable(name: str) -> bool:
    return name in manifest()


def download_size(name: str) -> str:
    entry = manifest().get(name)
    return f"{entry['size'] / 2**20:.0f} MB" if entry else ""


def _source(entry) -> str:
    # CI installs from the freshly built files instead of the (not yet published) release.
    local = os.environ.get("CYCLOP_ADDON_SOURCE")
    if local:
        return str(Path(local) / entry["file"])
    return RELEASE_URL.format(version=__version__, file=entry["file"])


def install(name: str, progress=None, root: Path | None = None) -> Path:
    """Download, verify and unpack an add-on (blocking: run it on a worker thread)."""
    entry = manifest().get(name)
    if not entry:
        raise RuntimeError(f"{ADDONS[name].title} isn't available as a download for this build")
    target = folder(name, root)
    if installed(name, root):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    source = _source(entry)
    size, expected = int(entry["size"]), str(entry["sha256"]).lower()
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".{name}-") as work:
        archive = Path(work) / entry["file"]
        digest = hashlib.sha256()
        received = 0
        if source.startswith("https://"):
            request = Request(source, headers={"User-Agent": f"CyclopWindows/{__version__}"})
            stream = urlopen(request, timeout=30)
        else:
            stream = open(source, "rb")
        with stream, archive.open("wb") as output:
            while True:
                block = stream.read(1 << 18)
                if not block:
                    break
                received += len(block)
                if received > size:
                    raise RuntimeError("The download is larger than expected")
                digest.update(block)
                output.write(block)
                if progress:
                    progress(received / size)
        if received != size or digest.hexdigest() != expected:
            raise RuntimeError("The download didn't match this version's checksum, so it wasn't installed")
        unpacked = Path(work) / "unpacked"
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                path = Path(member.filename)
                if path.is_absolute() or ".." in path.parts or ":" in member.filename:
                    raise RuntimeError("The add-on contains an unsafe path")
            bundle.extractall(unpacked)
        if not (unpacked / "cyclop-addon.json").is_file():
            raise RuntimeError("The add-on is incomplete")
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        os.replace(unpacked, target)
    # Add-ons of older versions are not used any more.
    for old in target.parent.glob(f"{name}-*"):
        if old != target and old.is_dir():
            shutil.rmtree(old, ignore_errors=True)
    return target


def remove(name: str, root: Path | None = None) -> bool:
    """Delete a downloaded add-on (takes effect after Cyclop restarts if it is in use)."""
    if name in _activated:
        return False
    path = folder(name, root)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


class Installer(QObject):
    """Downloads add-ons in the background, one request per add-on at a time."""
    progress = Signal(str, float)
    finished = Signal(str)
    failed = Signal(str, str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.busy: dict[str, list] = {}

    def ensure(self, name: str, then=None, otherwise=None) -> bool:
        """True if the feature can be used now. Otherwise starts the download (when this build
        offers one) and calls `then()` once it's ready or `otherwise(error)` if it fails."""
        if ready(name, self.model.store.directory):
            return True
        if not downloadable(name):
            if otherwise:
                otherwise(f"{ADDONS[name].title} isn't installed. From source: pip install -e .[{name}]")
            return False
        waiting = self.busy.get(name)
        if waiting is not None:
            if (then, otherwise) not in waiting:
                waiting.append((then, otherwise))
            return False
        self.busy[name] = [(then, otherwise)]
        root = self.model.store.directory
        self.progress.emit(name, 0.0)

        def work():
            install(name, lambda fraction: self.progress.emit(name, fraction), root)
            if not ready(name, root):
                raise RuntimeError("The add-on was installed but can't be loaded")
            return name

        def done(_result):
            callbacks = self.busy.pop(name, [])
            self.finished.emit(name)
            for then_, _ in callbacks:
                if then_:
                    then_()

        def failed(error):
            callbacks = self.busy.pop(name, [])
            self.failed.emit(name, error)
            for _, otherwise_ in callbacks:
                if otherwise_:
                    otherwise_(error)
        self.model.run_job(work, done, failed)
        return False
