"""Widgets that fit inside the notch and work above its topmost window."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QTextLayout, QTextOption
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QLabel, QSizePolicy


class ElidedLabel(QLabel):
    """Reserve complete text lines, with the full text available as a tooltip."""

    def __init__(self, text="", lines=1):
        super().__init__()
        self.lines = lines
        self.full_text = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setText(text)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self.reflow()

    def reflow(self):
        metrics = self.fontMetrics()
        self.setFixedHeight(metrics.lineSpacing() * self.lines + 2)
        text = " ".join(self.full_text.split())
        width = max(1, self.contentsRect().width())
        layout = QTextLayout(text, self.font())
        option = QTextOption()
        # Long titles without spaces (e.g. "a_file_name_like_this") must still wrap.
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        rendered = []
        for index in range(self.lines):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            start = line.textStart()
            if index == self.lines - 1:
                rendered.append(metrics.elidedText(text[start:], Qt.TextElideMode.ElideRight, width))
            else:
                rendered.append(text[start:start + line.textLength()].rstrip())
        layout.endLayout()
        super().setText("\n".join(rendered))

    def resizeEvent(self, event):
        self.reflow()
        super().resizeEvent(event)

    def changeEvent(self, event):
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and hasattr(self, "full_text"):
            self.reflow()
        super().changeEvent(event)


class PanelDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent.window(), Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowModality(Qt.WindowModality.WindowModal)

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()


class PanelFileDialog(QFileDialog):
    def __init__(self, parent, title, name_filter=""):
        super().__init__(parent.window(), title, "", name_filter)
        # Use an owned Qt window so Windows cannot put a native picker behind
        # the always-on-top panel while that picker blocks panel interaction.
        self.setOption(QFileDialog.Option.DontUseNativeDialog)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowModality(Qt.WindowModality.WindowModal)

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()


class PanelComboBox(QComboBox):
    def showPopup(self):
        view = self.view()
        # Leave room for the item text and scrollbar on Windows as well as the
        # compact closed selector. Otherwise the popup can clip its item area.
        view.setMinimumWidth(max(self.width(), view.sizeHintForColumn(0) +
                                 view.verticalScrollBar().sizeHint().width() + 2 * view.frameWidth()))
        # Preserve Qt.Popup (including outside-click dismissal) and explicitly
        # put its separate native window in the same topmost band as the panel.
        view.window().setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        super().showPopup()
