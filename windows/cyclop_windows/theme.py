from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

STYLE = """
QWidget { color: #ededed; font-family: 'Segoe UI', 'DejaVu Sans'; font-size: 12px; }
QWidget#content, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
QLabel { background: transparent; }
QLabel#secondary { color: #8c8c8c; }
QLabel#heading { font-size: 10px; font-weight: 600; letter-spacing: 1px; color: #737373; }
QLabel#title { font-size: 21px; font-weight: 650; }
QPushButton, QToolButton { background: #191919; border: 0; border-radius: 7px; padding: 5px 9px; }
QPushButton:hover, QToolButton:hover { background: #2b2b2b; }
QPushButton:pressed, QToolButton:pressed { background: #353535; }
QPushButton:disabled, QToolButton:disabled { color: #565656; }
QToolButton#rail { background: transparent; padding: 5px; }
QToolButton#rail:checked { background: #272727; }
QToolButton#rail:hover { background: #1c1c1c; }
QPushButton:focus, QToolButton:focus, QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid #7e9cd2; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #121212; border: 1px solid #292929; border-radius: 6px; padding: 5px; selection-background-color: #34527b; }
QComboBox QAbstractItemView { background: #171717; selection-background-color: #333333; }
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { background: #151515; border-radius: 7px; padding: 8px; margin: 2px 0; }
QListWidget::item:selected { background: #303030; }
QListWidget::item:hover { background: #222222; }
QScrollBar:vertical { background: transparent; width: 5px; }
QScrollBar::handle:vertical { background: #353535; border-radius: 2px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSlider::groove:horizontal { height: 4px; background: #252525; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #c9c9c9; border-radius: 2px; }
QSlider::handle:horizontal { background: white; width: 8px; margin: -2px 0; border-radius: 4px; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #555; border-radius: 4px; background: #151515; }
QCheckBox::indicator:checked { background: #85a9df; border-color: #85a9df; }
QMenu { background: #161616; color: white; border: 1px solid #333; padding: 6px; }
QMenu::item { padding: 7px 20px; }
QMenu::item:selected { background: #333; border-radius: 4px; }
QDialog { background: #101010; }
QToolTip { color: #eee; background: #222; border: 1px solid #444; }
QToolButton#tile { background: #1d1e21; border: 1px solid #2a2b2f; border-radius: 8px; padding: 8px 4px; font-size: 11px; }
QToolButton#tile:hover { background: #26272b; }
QToolButton#tile:checked { background: #ff4b3e; color: #120604; border-color: #ff4b3e; font-weight: 600; }
QToolButton#tile:disabled { color: #5a5a5a; }
QFrame#flyout { background: #141518; border: 1px solid #2c2d31; border-radius: 12px; }
QProgressBar { background: #1b1b1b; border: 0; border-radius: 3px; height: 6px; text-align: center; }
QProgressBar::chunk { background: #ff4b3e; border-radius: 3px; }
QKeySequenceEdit, QKeySequenceEdit QLineEdit { background: #121212; }
"""

PATHS = {
    "music": '<path d="M9 18V5l11-2v13M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="16" rx="3" ry="2"/>',
    "shelf": '<path d="M3 10l4-6h10l4 6v9H3zM3 10h5l2 4h4l2-4h5"/>',
    "clipboard": '<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="2" width="6" height="5" rx="1"/><path d="M9 12h6M9 16h6"/>',
    "snippets": '<path d="M8 3h8l-2 5v4l4 3H6l4-3V8zM12 15v7"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6M17 2v6M3 10h18M7 14h2M12 14h2M17 14h1M7 18h2M12 18h2"/>',
    "translate": '<path d="M2 4h12M8 2v2M4 7c2 5 5 7 9 8M12 4c-1 5-4 9-9 12M14 21l4-11 4 11M15 18h6"/>',
    "notes": '<path d="M13 4H4v17h17v-9M9 16l1-5L19 2l3 3-9 9z"/>',
    "currency": '<path d="M19 6c-3-4-11-2-11 6s8 10 11 6M4 10h11M4 14h10"/>',
    "teleprompter": '<rect x="3" y="3" width="18" height="15" rx="2"/><path d="M7 7h10M7 11h8M9 22l3-4 3 4"/>',
    "settings": '<circle cx="12" cy="12" r="4"/><path d="M12 1v4M12 19v4M1 12h4M19 12h4M4 4l3 3M17 17l3 3M4 20l3-3M17 7l3-3"/>',
    "play": '<path d="M8 4l12 8-12 8z" fill="currentColor"/>',
    "pause": '<path d="M8 5v14M16 5v14" stroke-width="4"/>',
    "previous": '<path d="M19 5l-9 7 9 7zM5 5v14"/>',
    "next": '<path d="M5 5l9 7-9 7zM19 5v14"/>',
    "pin": '<path d="M8 3h8l-2 5v4l4 3H6l4-3V8zM12 15v7"/>',
    "eye": '<path d="M2 12c4-8 16-8 20 0-4 8-16 8-20 0z"/><circle cx="12" cy="12" r="3"/>',
    "close": '<path d="M6 6l12 12M6 18L18 6"/>',
    "folder": '<path d="M2 6h8l2 3h10v12H2z"/>',
    "ocr": '<path d="M3 8V4h4M17 4h4v4M21 16v4h-4M7 20H3v-4M8 9h8M12 9v7"/>',
    "recorder": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0014 0M12 18v4M8 22h8"/>',
    "mic": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0014 0M12 18v4"/>',
    "record": '<circle cx="12" cy="12" r="6" fill="currentColor"/>',
    "stop": '<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/>',
    "awake": '<path d="M4 9h12v6a5 5 0 01-5 5H9a5 5 0 01-5-5zM16 11h2a2 2 0 010 4h-2M8 2c-1 2 1 3 0 5M12 2c-1 2 1 3 0 5"/>',
    "quick": '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    "volume": '<path d="M4 9h4l5-4v14l-5-4H4zM16 9a4 4 0 010 6M18.5 6.5a8 8 0 010 11"/>',
    "define": '<path d="M4 4h6a3 3 0 013 3v13a2 2 0 00-2-2H4zM20 4h-6a3 3 0 00-3 3"/>',
}


def icon(name, color="#b9b9b9", size=24):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" color="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{PATHS.get(name, PATHS["eye"])}</svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
