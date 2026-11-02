"""PyInstaller entry point (absolute import works outside a package)."""
import os
import sys

from cyclop_windows import startup

startup.mark("python")
# Time-zone data ships as one zip (see cyclop.spec); zoneinfo reads it from there.
_tzdata = os.path.join(getattr(sys, "_MEIPASS", ""), "tzdata.zip")
if os.path.isfile(_tzdata):
    sys.path.append(_tzdata)
from cyclop_windows.app import main  # noqa: E402

if __name__ == "__main__":
    main()
