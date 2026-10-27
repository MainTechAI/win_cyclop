"""Render docs/panel-preview.png: the open panel with Cyclop and its stats beside it.

Uses the real widgets with simulated media metadata, offscreen. Run from the
windows folder: python scripts/make-preview.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    app = QApplication([])
    from cyclop_windows.theme import STYLE
    app.setStyleSheet(STYLE)
    from cyclop_windows.app import Panel, notch_shape
    from cyclop_windows.mascot import MascotWindow
    from cyclop_windows.model import Model

    model = Model(Path(tempfile.mkdtemp()))
    model.configure("stats_enabled", True)
    panel = Panel(model, start_services=False)
    panel.watcher.stop()
    panel.show()
    panel.set_expanded(True)
    panel.select_tab("music")
    panel.reposition()
    cover = QPixmap(108, 108)
    painter = QPainter(cover)
    gradient = QLinearGradient(0, 0, 108, 108)
    gradient.setColorAt(0, QColor("#ff5f45"))
    gradient.setColorAt(1, QColor("#3b0d4f"))
    painter.fillRect(cover.rect(), gradient)
    painter.end()
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    stream = QBuffer(data)
    stream.open(QIODevice.OpenModeFlag.WriteOnly)
    cover.save(stream, "PNG")
    panel.panes["music"].update_state({
        "available": True, "title": "Night Drive", "artist": "Example Artist", "source": "Spotify.exe",
        "playing": True, "art": bytes(data), "position": 83, "duration": 214,
        "can_seek": True, "can_play": True, "can_next": True, "can_previous": True,
    })
    app.processEvents()
    panel_image = panel.grab().toImage()

    laptop = QRect(0, 0, 1536, 824)  # lay Cyclop out as on a 1920×1080 laptop at 125 %
    MascotWindow.screen_bounds = lambda self: laptop
    mascot = MascotWindow(model, start_animation=False)
    panel_rect = QRect(laptop.center().x() - panel_image.width() // 2, 0, panel_image.width(), panel_image.height())
    mascot.set_anchor(panel_rect)
    mascot.set_stats({"cpu": 18, "ram": 54, "gpu": 9, "temp": 47, "details": []})
    mascot.target = (-0.3, -0.1)
    mascot.gaze_x.value, mascot.gaze_y.value = -0.3, -0.12
    mascot.tick()
    mascot_image = mascot.grab().toImage()

    width, height = 1120, 360
    sheet = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    background = QLinearGradient(0, 0, width, height)
    background.setColorAt(0, QColor("#2c3e57"))
    background.setColorAt(1, QColor("#5b3a52"))
    painter.fillRect(sheet.rect(), background)
    glow = QRadialGradient(QPointF(width * 0.75, height * 0.9), 420)
    glow.setColorAt(0, QColor(255, 120, 90, 90))
    glow.setColorAt(1, QColor(255, 120, 90, 0))
    painter.fillRect(sheet.rect(), glow)
    panel_x = 170
    # The panel's real window is masked to the notch silhouette; draw it the same way.
    painter.save()
    painter.translate(panel_x, 0)
    painter.setClipPath(notch_shape(panel_image.width(), panel_image.height(), True))
    painter.drawImage(0, 0, panel_image)
    painter.restore()
    offset = mascot.geometry().topLeft() - panel_rect.topLeft()
    painter.drawImage(panel_x + offset.x(), offset.y(), mascot_image)
    painter.end()
    target = Path(__file__).resolve().parents[1] / "docs" / "panel-preview.png"
    sheet.save(str(target))
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
