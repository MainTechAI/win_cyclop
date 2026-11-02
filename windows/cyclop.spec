# PyInstaller build of Cyclop for Windows.
#
#   set CYCLOP_BUILD=onedir   (or onefile)
#   python -m PyInstaller --noconfirm --clean cyclop.spec
#
# Speech recognition and webcam support are not part of the app: they are add-ons
# (scripts/build-addons.py writes dist/addons/pyinstaller-args.txt, read here), so
# the exe has far less to unpack every time it starts.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH)
MODE = os.environ.get("CYCLOP_BUILD", "onedir")
ARGS = ROOT / "dist" / "addons" / "pyinstaller-args.txt"

excludes, hidden = [], []
if ARGS.exists():
    for line in ARGS.read_text(encoding="utf-8").splitlines():
        option, _, value = line.partition("=")
        if option == "--exclude-module":
            excludes.append(value)
        elif option == "--hidden-import":
            hidden.append(value)

datas = [(str(ROOT / "cyclop_windows" / "assets"), "cyclop_windows/assets")] + copy_metadata("cyclop-windows")
if MODE == "onefile":
    datas += [(str(ROOT / "dist" / "CyclopWindows" / "licenses"), "licenses"), (str(ROOT.parent / "LICENSE"), "."),
              (str(ROOT / "THIRD_PARTY_NOTICES.md"), ".")]

a = Analysis(
    [str(ROOT / "scripts" / "launch.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=collect_submodules("winrt") + hidden,
    # PySide6 imports QtNetwork only to look for an OpenSSL folder, and copes with it missing;
    # Cyclop uses no Qt networking (its few web requests use Python's urllib).
    excludes=excludes + ["PySide6.QtNetwork"],
    noarchive=False,
)


def unused(entry):
    """Files that no feature of the app uses."""
    name = entry[0].replace("\\", "/").lower()
    return (name.endswith("/opengl32sw.dll")                  # software OpenGL: Cyclop draws without OpenGL
            or "pyside6/translations/" in name)                # Qt's own dialog translations: the app is English


a.binaries = [entry for entry in a.binaries if not unused(entry)]
a.datas = [entry for entry in a.datas if not unused(entry)]
pyz = PYZ(a.pure)
options = dict(name="CyclopWindows", debug=False, strip=False, upx=False, console=False,
               icon=str(ROOT / "cyclop_windows" / "assets" / "cyclop.ico"))
if MODE == "onefile":
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **options)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **options)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CyclopWindows")
