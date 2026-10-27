"""Download the YuNet face detector into the package assets and verify its SHA-256."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cyclop_windows.camera import MODEL_NAME, MODEL_SHA256, download_model, sha256  # noqa: E402

if __name__ == "__main__":
    assets = Path(__file__).resolve().parents[1] / "cyclop_windows" / "assets"
    target = assets / MODEL_NAME
    if target.is_file() and sha256(target) == MODEL_SHA256:
        print(f"{MODEL_NAME} already present and verified")
    else:
        download_model(assets)
        print(f"Downloaded and verified {target} ({MODEL_SHA256[:12]}…)")
