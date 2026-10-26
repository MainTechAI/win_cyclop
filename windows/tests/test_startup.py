"""Exercise the real event loop, tray lifecycle and clean application exit."""
import json
import os
import subprocess
import sys


def test_startup_report_and_clean_exit(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "cyclop_windows", "--smoke-test"],
        env=os.environ | {"QT_QPA_PLATFORM": "offscreen", "CYCLOP_DATA_DIR": str(tmp_path)},
        capture_output=True, text=True, timeout=25,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "startup-check.json").read_text())
    assert report["success"] is True
    assert report["pane_count"] == 10
    assert (tmp_path / "startup-panel.png").stat().st_size > 0
    assert not (tmp_path / "instance.lock").exists()
