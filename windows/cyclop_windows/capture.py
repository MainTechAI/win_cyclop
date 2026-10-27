"""Freeze-frame region selection for text capture (image → text)."""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

OCR_MAX_DIMENSION = 2600  # Windows.Media.Ocr rejects larger images


class RegionSelector(QWidget):
    """Covers the screen under the cursor with a frozen screenshot.

    Drag to select a rectangle; Escape or right-click cancels. The selected
    pixels (in device resolution) are emitted as a QImage.
    """
    selected = Signal(QImage)
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
        self.finish()
        self.selected.emit(image)

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


def crop(image: QImage, area: QRect, ratio: float) -> QImage:
    source = QRect(int(area.x() * ratio), int(area.y() * ratio), int(area.width() * ratio), int(area.height() * ratio))
    return image.copy(source.intersected(image.rect()))


def prepare_for_ocr(image: QImage) -> bytes:
    """Scale small text up (OCR likes ~20 px glyphs) and large regions down; encode PNG."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    longest = max(image.width(), image.height())
    if longest and longest < 900:
        factor = min(3.0, 900 / longest)
        image = image.scaled(int(image.width() * factor), int(image.height() * factor),
                             Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if max(image.width(), image.height()) > OCR_MAX_DIMENSION:
        image = image.scaled(OCR_MAX_DIMENSION, OCR_MAX_DIMENSION, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)
