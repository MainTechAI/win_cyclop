"""Package the optional features as add-ons that the app downloads only when they are turned on.

    python scripts/build-addons.py dist/addons

Each add-on is a zip of the installed Python packages it needs (copied from this
environment, exactly as tested) that the core app does not already contain. It
writes:

- dist/addons/Cyclop<Name>-<version>-win-x64.zip, one per add-on
- cyclop_windows/assets/addons.json: file names, sizes and SHA-256 hashes that the
  app checks before installing a download
- dist/addons/pyinstaller-args.txt: arguments for the core build, which leaves the
  add-on packages out and includes the standard-library and shared modules they need
"""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cyclop_windows import __version__  # noqa: E402
from cyclop_windows.addons import ADDONS  # noqa: E402

# Standard-library parts that no add-on uses and that would only add weight.
STDLIB_SKIP = {"tkinter", "turtle", "turtledemo", "idlelib", "test", "lib2to3", "ensurepip", "venv", "pydoc_data",
               "distutils", "curses", "readline", "msilib", "this", "antigravity", "xxlimited", "xxlimited_35",
               "xxsubtype", "_tkinter", "_testcapi", "_testinternalcapi", "_testbuffer", "_testimportmultiple",
               "_testmultiphase", "_testsinglephase", "_testclinic", "_xxtestfuzz", "_xxsubinterpreters", "_ctypes_test",
               "__phello__", "_pyrepl", "_testconsole"}


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def closure(roots: list[str], extras: dict[str, set[str]] | None = None) -> dict[str, metadata.Distribution]:
    """Every installed distribution needed by `roots` (requirement markers evaluated for this platform)."""
    found: dict[str, metadata.Distribution] = {}
    pending = [(root, (extras or {}).get(canonical(root), set())) for root in roots]
    while pending:
        name, wanted = pending.pop()
        key = canonical(name)
        if key in found:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        found[key] = dist
        for text in dist.requires or []:
            requirement = Requirement(text)
            if requirement.marker:
                environments = [dict(default_environment(), extra=extra) for extra in (wanted or {""})]
                if not any(requirement.marker.evaluate(environment) for environment in environments):
                    continue
            pending.append((requirement.name, set(requirement.extras)))
    return found


def top_level(dist: metadata.Distribution) -> set[str]:
    """Import names a distribution provides (from top_level.txt, else from its files)."""
    text = dist.read_text("top_level.txt")
    if text:
        return {line.strip() for line in text.splitlines() if line.strip()}
    names = set()
    for file in dist.files or []:
        first = file.parts[0]
        if first.endswith((".dist-info", ".data")) or first in ("..", "__pycache__") or first.endswith(".libs"):
            continue
        names.add(first[:-3] if first.endswith(".py") else first.split(".")[0])
    return names


def addon_files(dists):
    """(source path, path inside the zip) for every installed file of these distributions."""
    for dist in dists:
        base = Path(dist.locate_file(""))
        for file in dist.files or []:
            if file.parts[0] == ".." or "__pycache__" in file.parts or file.suffix == ".pyc":
                continue   # console scripts outside site-packages; bytecode is rebuilt on first use
            source = base / file
            if source.is_file():
                yield source, file.as_posix()


RUNTIME_DLL = re.compile(r"^(msvcp140(_\d|_atomic_wait|_codecvt_ids)?|vcruntime140(_1)?|vcomp140|concrt140)\.dll$", re.I)


def runtime_dlls(entries):
    """Microsoft C++ runtime DLLs the add-on's binaries import but don't ship (pip assumes the VC++
    redistributable is installed; a PC with only Cyclop may not have it). Windows only."""
    if sys.platform != "win32":
        return []
    import pefile
    shipped = {Path(name).name.lower() for _, name in entries}
    wanted, pending = set(), [source for source, name in entries if name.lower().endswith((".dll", ".pyd"))]
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    seen = set()
    while pending:
        binary = pending.pop()
        if binary in seen:
            continue
        seen.add(binary)
        try:
            pe = pefile.PE(str(binary), fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                                   pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        except Exception:
            continue
        for table in (getattr(pe, "DIRECTORY_ENTRY_IMPORT", []), getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])):
            for item in table:
                name = item.dll.decode(errors="ignore")
                if RUNTIME_DLL.match(name) and name.lower() not in shipped and name.lower() not in wanted:
                    found = system / name
                    if found.is_file():
                        wanted.add(name.lower())
                        pending.append(found)     # msvcp140_*.dll import vcruntime140.dll
    return [(system / name, name) for name in sorted(wanted)]


def write_zip(target: Path, entries, info: dict):
    target.parent.mkdir(parents=True, exist_ok=True)
    unpacked = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source, name in sorted(entries, key=lambda item: item[1]):
            entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            data = source.read_bytes()
            unpacked += len(data)
            archive.writestr(entry, data)
        entry = zipfile.ZipInfo("cyclop-addon.json", date_time=(2020, 1, 1, 0, 0, 0))
        archive.writestr(entry, json.dumps(info, indent=2, sort_keys=True))
    return unpacked


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def submodules(package: str, skip=lambda name: False) -> list[str]:
    from PyInstaller.utils.hooks import collect_submodules
    return collect_submodules(package, filter=lambda name: not skip(name))


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/addons")
    out.mkdir(parents=True, exist_ok=True)
    core = closure(["cyclop-windows"])
    core.pop("cyclop-windows", None)
    core_names = set().union(*(top_level(dist) for dist in core.values()))
    manifest, excluded, shared = {}, set(), set()
    for name, addon in ADDONS.items():
        needed = closure(list(addon.requirements))
        own = {key: dist for key, dist in needed.items() if key not in core}
        if not own:
            raise SystemExit(f"{name}: none of {addon.requirements} is installed in this environment")
        for key, dist in needed.items():
            if key in core:
                shared |= top_level(dist)    # e.g. numpy: the add-on uses the app's copy
        modules = set().union(*(top_level(dist) for dist in own.values())) - core_names
        excluded |= modules
        info = {"name": name, "app_version": __version__, "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                "packages": {dist.metadata["Name"]: dist.version for dist in own.values()}}
        filename = f"Cyclop{name.capitalize()}-{__version__}-win-x64.zip"
        entries = list(addon_files(own.values()))
        runtime = runtime_dlls(entries)
        info["runtime_dlls"] = [name for _, name in runtime]
        unpacked = write_zip(out / filename, entries + runtime, info)
        manifest[name] = {"file": filename, "size": (out / filename).stat().st_size, "unpacked": unpacked,
                          "sha256": sha256(out / filename), "packages": info["packages"]}
        print(f"{name}: {filename} {manifest[name]['size'] / 2**20:.1f} MB ({unpacked / 2**20:.0f} MB unpacked), "
              f"{len(own)} packages: {', '.join(sorted(info['packages']))}; C++ runtime: {info['runtime_dlls'] or 'none needed'}")
    # Add-ons import standard-library and shared modules (numpy…) from the app, so the app
    # must contain all of them, not only the ones its own code happens to use.
    hidden = set()
    for package in sorted(set(sys.stdlib_module_names) - STDLIB_SKIP):
        if package.startswith("_") or package in excluded:
            hidden.add(package)
            continue
        hidden.add(package)
        try:
            spec = importlib.util.find_spec(package)
        except (ImportError, ValueError):
            spec = None
        if spec is not None and spec.submodule_search_locations:
            hidden |= set(submodules(package, skip=lambda module: any(part in ("test", "tests", "idle_test") for part in module.split("."))))
    for package in sorted(shared - {"cyclop_windows"}):
        hidden |= set(submodules(package, skip=lambda module: any(part in ("tests", "testing", "f2py", "_pyinstaller") for part in module.split("."))))
    args = [f"--exclude-module={module}" for module in sorted(excluded | {"PIL"})]
    args += [f"--hidden-import={module}" for module in sorted(hidden) if module.split(".")[0] not in excluded]
    (out / "pyinstaller-args.txt").write_text("\n".join(args) + "\n", encoding="utf-8")
    (ROOT / "cyclop_windows" / "assets" / "addons.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"core build: {len(excluded)} add-on modules left out, {len(hidden)} standard/shared modules included")


if __name__ == "__main__":
    main()
