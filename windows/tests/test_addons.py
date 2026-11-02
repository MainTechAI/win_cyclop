"""Optional features downloaded on demand: verified, safely unpacked, importable, and never in the way."""
import hashlib
import json
import sys
import time
import zipfile

import pytest

from cyclop_windows import addons, __version__
from cyclop_windows.model import Model


@pytest.fixture
def fake_addon(tmp_path, monkeypatch):
    """A tiny add-on zip with one module, offered by this 'build'."""
    source = tmp_path / "release"
    source.mkdir()
    module = f"cyclop_addon_probe_{time.monotonic_ns()}"

    def make(entries=None, tamper=False):
        archive = source / "CyclopProbe.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, text in (entries or {f"{module}/__init__.py": "VALUE = 42\n"}).items():
                bundle.writestr(name, text)
            bundle.writestr("cyclop-addon.json", json.dumps({"name": "probe"}))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        entry = {"file": archive.name, "size": archive.stat().st_size, "sha256": ("0" * 64) if tamper else digest}
        monkeypatch.setattr(addons, "manifest", lambda: {"probe": entry})
        return entry

    monkeypatch.setenv("CYCLOP_ADDON_SOURCE", str(source))
    monkeypatch.setitem(addons.ADDONS, "probe", addons.Addon("probe", "Probe", (module,), ("probe",)))
    paths = list(sys.path)
    yield make, module, tmp_path / "data"
    sys.path[:] = paths
    addons._activated.discard("probe")


def test_addon_installs_verified_and_becomes_importable(fake_addon):
    make, module, root = fake_addon
    make()
    assert not addons.ready("probe", root)
    progress = []
    target = addons.install("probe", progress.append, root)
    assert target == root / "addons" / f"probe-{__version__}"
    assert progress and progress[-1] == 1.0
    assert addons.ready("probe", root)
    assert __import__(module).VALUE == 42
    # The app's own modules keep priority over anything in an add-on.
    assert sys.path.index(str(target)) == len(sys.path) - 1


def test_tampered_download_is_not_installed(fake_addon):
    make, _module, root = fake_addon
    make(tamper=True)
    with pytest.raises(RuntimeError, match="checksum"):
        addons.install("probe", None, root)
    assert not addons.installed("probe", root)
    assert not list((root / "addons").glob("probe-*"))


def test_addon_with_unsafe_paths_is_refused(fake_addon):
    make, _module, root = fake_addon
    make({"../outside.py": "x = 1\n"})
    with pytest.raises(RuntimeError, match="unsafe"):
        addons.install("probe", None, root)
    assert not (root / "outside.py").exists() and not (root / "addons" / "outside.py").exists()


def test_installing_removes_add_ons_of_older_versions(fake_addon):
    make, _module, root = fake_addon
    make()
    old = root / "addons" / "probe-0.0.1"
    old.mkdir(parents=True)
    (old / "cyclop-addon.json").write_text("{}")
    addons.install("probe", None, root)
    assert not old.exists()


def test_background_installer_reports_progress_and_runs_the_waiting_action(app, fake_addon):
    make, _module, root = fake_addon
    make()
    model = Model(root)
    installer = addons.Installer(model)
    events, ran = [], []
    installer.progress.connect(lambda name, fraction: events.append(fraction))
    installer.finished.connect(lambda name: events.append(name))
    assert installer.ensure("probe", lambda: ran.append(True)) is False
    assert installer.ensure("probe", lambda: ran.append(True)) is False   # a second request waits for the same download
    deadline = time.monotonic() + 10
    while "probe" not in events and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert events[0] == 0.0 and "probe" in events and len(ran) == 2
    assert installer.ensure("probe") is True


def test_missing_add_on_without_a_download_explains_how_to_install(app, tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "manifest", lambda: {})
    monkeypatch.setitem(addons.ADDONS, "probe", addons.Addon("probe", "Probe", ("no_such_module_here",), ("probe",)))
    errors = []
    assert addons.Installer(Model(tmp_path)).ensure("probe", otherwise=errors.append) is False
    assert "pip install -e .[probe]" in errors[0]


def test_settings_explain_downloads_when_add_ons_are_not_installed(app, tmp_path, monkeypatch):
    """Built without speech and camera packages (as the release is), Settings still opens."""
    from cyclop_windows.app import TABS
    from cyclop_windows.features import SettingsPane
    monkeypatch.setattr(addons, "ready", lambda name, root=None: False)
    monkeypatch.setattr(addons, "manifest", lambda: {"speech": {"size": 80 * 2**20}, "camera": {"size": 45 * 2**20}})
    pane = SettingsPane(Model(tmp_path), TABS)
    assert "downloads once (80 MB)" in pane.addon_status["speech"].text()
    assert "downloads once (45 MB)" in pane.addon_status["camera"].text()
    pane.show_addon("speech", "Speech recognition: downloading… 50%")
    assert pane.addon_status["speech"].text().endswith("50%")
