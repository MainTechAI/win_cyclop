"""A short-lived red sonar mark on the desktop where Cyclop is looking."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

RED = QColor("#ff3b30")


def logical_point(x, y):
    """Convert physical screen pixels (Win32) to Qt's logical coordinates."""
    for screen in QGuiApplication.screens():
        ratio = screen.devicePixelRatio() or 1.0
        geometry = screen.geometry()
        native_left, native_top = geometry.x() * ratio, geometry.y() * ratio
        if native_left <= x < native_left + geometry.width() * ratio and native_top <= y < native_top + geometry.height() * ratio:
            return QPoint(int(geometry.x() + (x - native_left) / ratio), int(geometry.y() + (y - native_top) / ratio))
    ratio = QGuiApplication.primaryScreen().devicePixelRatio() or 1.0
    return QPoint(int(x / ratio), int(y / ratio))


class SonarMark(QWidget):
    """Expanding red rings and a crosshair that fade out; never takes clicks or focus."""
    SIZE = 120
    LIFE = 1.3

    def __init__(self, point: QPoint):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(QRect(point.x() - self.SIZE // 2, point.y() - self.SIZE // 2, self.SIZE, self.SIZE))
        self.started = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.step)
        self.timer.start(16)

    def age(self):
        return (time.monotonic() - self.started) / self.LIFE

    def step(self):
        if self.age() >= 1:
            self.timer.stop()
            self.close()
            return
        self.update()

    def paintEvent(self, event):
        t = min(1.0, self.age())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.SIZE / 2, self.SIZE / 2)
        fade = (1 - t) ** 1.3
        for offset in (0.0, 0.25):
            ring_t = max(0.0, min(1.0, (t - offset) / (1 - offset)))
            if ring_t <= 0:
                continue
            radius = 6 + (self.SIZE / 2 - 8) * (1 - (1 - ring_t) ** 2)
            painter.setPen(QPen(QColor(RED.red(), RED.green(), RED.blue(), int(220 * (1 - ring_t))), 2.2 - ring_t))
            painter.drawEllipse(center, radius, radius)
        painter.setPen(QPen(QColor(RED.red(), RED.green(), RED.blue(), int(230 * fade)), 1.6))
        arm = 9 + 4 * math.sin(t * math.pi)
        gap = 4
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            painter.drawLine(QPointF(center.x() + dx * gap, center.y() + dy * gap),
                             QPointF(center.x() + dx * (gap + arm), center.y() + dy * (gap + arm)))
        painter.setBrush(QColor(RED.red(), RED.green(), RED.blue(), int(255 * fade)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 2.4, 2.4)
