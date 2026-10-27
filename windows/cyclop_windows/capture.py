"""Freeze-frame region selection for text capture (image → text)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

OCR_MAX_DIMENSION = 2600  # Windows.Media.Ocr rejects larger images


class RegionSelector(QWidget):
    """Covers the screen under the cursor with a frozen screenshot.

    Drag to select a rectangle; Escape or right-click cancels. The selected
    pixels (in device resolution) are emitted as a QImage.
    """
    selected = Signal(QImage, QRect)  # pixels, and the area in global screen coordinates
    cancelled = Signal()

    def __init__(self, screen=None, snapshot=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("Select an area to capture text")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        screen = screen or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.screen_ref = screen
        self.snapshot = snapshot if snapshot is not None else screen.grabWindow(0)
        self.setGeometry(screen.geometry())
        self.origin = None
        self.current = None
        self.finished = False

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.grabKeyboard()

    def selection(self) -> QRect:
        if self.origin is None or self.current is None:
            return QRect()
        return QRect(self.origin, self.current).normalized()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.snapshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        area = self.selection()
        if area.isValid() and area.width() > 1:
            ratio = self.snapshot.devicePixelRatio() or 1.0
            source = QRect(int(area.x() * ratio), int(area.y() * ratio), int(area.width() * ratio), int(area.height() * ratio))
            painter.drawPixmap(area, self.snapshot, source)
            painter.setPen(QPen(QColor("#ff3b30"), 2))
            painter.drawRect(area.adjusted(0, 0, -1, -1))
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(area.bottomLeft() + QPoint(4, 16), f"{source.width()} × {source.height()}")
        else:
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect().adjusted(0, 60, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             "Drag around the text to capture · Esc to cancel")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.cancel()
            return
        self.origin = self.current = event.position().toPoint()
        self.update()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        self.current = event.position().toPoint()
        area = self.selection()
        if area.width() < 4 or area.height() < 4:
            self.origin = self.current = None
            self.update()
            return
        self.accept_area(area)

    def accept_area(self, area: QRect):
        image = crop(self.snapshot.toImage(), area, self.snapshot.devicePixelRatio() or 1.0)
        global_area = area.translated(self.geometry().topLeft())
        self.finish()
        self.selected.emit(image, global_area)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()

    def cancel(self):
        self.finish()
        self.cancelled.emit()

    def finish(self):
        if not self.finished:
            self.finished = True
            self.releaseKeyboard()
            self.close()
            self.deleteLater()


class ScanOverlay(QWidget):
    """Red sonar sweep over the area being read: a scan line, echo rings and a frame.

    Transparent for input, so it never blocks the desktop; fades out when done.
    """
    RED = QColor("#ff3b30")

    def __init__(self, area: QRect):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(area.adjusted(-6, -6, 6, 6))
        self.started = time.monotonic()
        self.ending = None
        self.success = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.step)
        self.timer.start(16)

    def finish(self, success=True):
        """Flash white when text was found, then fade out."""
        if self.ending is None:
            self.ending = time.monotonic()
            self.success = success

    def step(self):
        if self.ending is not None and time.monotonic() - self.ending > 0.45:
            self.timer.stop()
            self.close()
            return
        self.update()

    def paintEvent(self, event):
        now = time.monotonic()
        age = now - self.started
        fade = 1.0 if self.ending is None else max(0.0, 1 - (now - self.ending) / 0.45)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        red = self.RED

        def colour(alpha):
            return QColor(red.red(), red.green(), red.blue(), int(alpha * fade))
        painter.fillRect(area, colour(26))
        # Sweeping scan line with a glowing trail, bouncing top ↔ bottom.
        period = 1.3
        phase = (age % period) / period
        t = phase * 2 if phase < 0.5 else 2 - phase * 2
        y = area.top() + area.height() * (0.5 - 0.5 * math.cos(t * math.pi))
        downward = phase < 0.5
        trail = min(60.0, area.height() * 0.5)
        gradient = QLinearGradient(0, y, 0, y - trail if downward else y + trail)
        gradient.setColorAt(0, colour(110))
        gradient.setColorAt(1, colour(0))
        painter.fillRect(QRectF(area.left(), min(y, y - trail if downward else y + trail), area.width(), trail).intersected(area), gradient)
        painter.setPen(QPen(colour(235), 2))
        painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        # Echo rings from the centre, like a sonar contact.
        center = area.center()
        reach = math.hypot(area.width(), area.height()) / 2
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for offset in (0.0, 0.45, 0.9):
            ring_t = ((age + offset) % 1.35) / 1.35
            painter.setPen(QPen(colour(160 * (1 - ring_t)), 1.6))
            painter.save()
            painter.setClipRect(area)
            painter.drawEllipse(center, reach * ring_t, reach * ring_t)
            painter.restore()
        # Corner brackets frame the target.
        if self.ending is not None and self.success:
            painter.fillRect(area, QColor(255, 255, 255, int(60 * fade)))
        painter.setPen(QPen(colour(255), 2.5))
        size = min(18.0, area.width() / 4, area.height() / 4)
        for corner, dx, dy in ((area.topLeft(), 1, 1), (area.topRight(), -1, 1), (area.bottomLeft(), 1, -1), (area.bottomRight(), -1, -1)):
            painter.drawLine(corner, corner + QPointF(size * dx, 0))
            painter.drawLine(corner, corner + QPointF(0, size * dy))


def crop(image: QImage, area: QRect, ratio: float) -> QImage:
    source = QRect(int(area.x() * ratio), int(area.y() * ratio), int(area.width() * ratio), int(area.height() * ratio))
    return image.copy(source.intersected(image.rect()))


def prepare_for_ocr(image: QImage, invert: bool | None = None) -> bytes:
    """Make a screen region easy for Windows OCR and encode it as PNG.

    Converts to grayscale, turns light-on-dark (dark mode) into dark-on-light,
    enlarges small or thin regions so glyphs are ~20+ px tall, adds a quiet
    margin, and keeps within the engine's size limit.
    """
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    if invert is None:
        invert = is_dark(gray)
    if invert:
        gray.invertPixels()
    width, height = max(1, gray.width()), max(1, gray.height())
    factor = max(1.0, 900 / max(width, height), 72 / min(width, height))
    factor = min(factor, 4.0)
    if factor > 1.0:
        gray = gray.scaled(int(width * factor), int(height * factor), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    margin = 24
    limit = OCR_MAX_DIMENSION - 2 * margin
    if max(gray.width(), gray.height()) > limit:
        gray = gray.scaled(limit, limit, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    padded = QImage(gray.width() + 2 * margin, gray.height() + 2 * margin, QImage.Format.Format_Grayscale8)
    padded.fill(QColor(0, 0, 0) if is_dark(gray) else QColor(255, 255, 255))
    painter = QPainter(padded)
    painter.drawImage(margin, margin, gray)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    padded.save(buffer, "PNG")
    return bytes(data)


def is_dark(image: QImage) -> bool:
    """True when the region is mostly dark (light text on a dark background)."""
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    sample = gray.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
    total = sum(sample.pixelColor(x, y).value() for y in range(sample.height()) for x in range(sample.width()))
    return total / (sample.width() * sample.height()) < 128


def ocr_variants(image: QImage) -> list[bytes]:
    """The best guess first, then the opposite polarity as a fallback."""
    dark = is_dark(image)
    return [prepare_for_ocr(image, invert=dark), prepare_for_ocr(image, invert=not dark)]
