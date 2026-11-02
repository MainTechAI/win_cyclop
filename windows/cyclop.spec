# PyInstaller build of Cyclop for Windows.
#
#   set CYCLOP_BUILD=onedir   (or onefile)
#   python -m PyInstaller --noconfirm --clean cyclop.spec
#
# Speech recognition and webcam support are not part of the app: they are add-ons
# (scripts/build-addons.py writes dist/addons/pyinstaller-args.txt, read here), so
# the exe has far less to unpack every time it starts.
import importlib.util
import os
from pathlib import Path
import zipfile

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

# Time-zone data (Calendar) is ~600 tiny files; as one zip it unpacks at once and Python reads it
# in place (scripts/launch.py puts it on sys.path).
tz = importlib.util.find_spec("tzdata")
if tz is not None:
    tz_root = Path(tz.submodule_search_locations[0])
    tz_zip = Path(workpath) / "tzdata.zip"
    tz_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(tz_zip, "w", zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(tz_root.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts:
                bundle.write(file, Path("tzdata") / file.relative_to(tz_root))
    datas.append((str(tz_zip), "."))
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
    excludes=excludes + ["PySide6.QtNetwork", "tzdata"],
    noarchive=False,
)


def unused(entry):
    """Files that no feature of the app uses."""
    name = entry[0].replace("\\", "/").lower()
    base = name.rsplit("/", 1)[-1]
    return (base == "opengl32sw.dll"                           # software OpenGL: Cyclop draws without OpenGL
            or "pyside6/translations/" in name                 # Qt's own dialog translations: the app is English
            or (base.startswith("api-ms-win-") and "/" not in name)  # Windows 10/11 resolve these API sets itself
            or "/plugins/generic/" in name                     # TUIO network touch input (needs Qt networking)
            or base in ("qt6network.dll", "qdirect2d.dll")     # unused Qt networking; experimental Direct2D backend
            or "/plugins/networkinformation/" in name or "/plugins/tls/" in name)


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
