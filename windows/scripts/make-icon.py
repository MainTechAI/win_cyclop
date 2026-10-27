"""Regenerate the 2D Cyclop eye icon used for the .exe, tray and window."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402
from cyclop_windows.mascot import flat_eye_image, write_ico  # noqa: E402

if __name__ == "__main__":
    app = QApplication([])
    assets = Path(__file__).resolve().parents[1] / "cyclop_windows" / "assets"
    assets.mkdir(exist_ok=True)
    write_ico(assets / "cyclop.ico")
    flat_eye_image(256).save(str(assets / "cyclop.png"))
    print(f"Wrote {assets / 'cyclop.ico'}")
