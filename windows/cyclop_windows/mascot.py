"""Cyclop's mascot: a floating eye orb, ray-traced per pixel and animated.

The orb is real 3D geometry (a sphere) shaded with key/fill lights, Blinn-Phong
specular, a studio softbox reflection, fresnel rim light and ambient occlusion.
The iris is a glowing spherical cap that rotates over the sphere to look around;
eyelids are spherical shells that close over it. Rendering ~110×110 pixels with
numpy takes about a millisecond per frame, so no GPU context is needed inside the
translucent always-on-top window.
"""
from __future__ import annotations

import math
import random
import struct
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal, QEasingCurve, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .core import IRIS_COLORS, STAT_KEYS, stat_color, stat_label
from .windows import last_input_tick


def _hex_rgb(value: str):
    color = QColor(value)
    return (color.redF() ** 2.2, color.greenF() ** 2.2, color.blueF() ** 2.2)


def _norm(v):
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / length for c in v)


class EyeRenderer:
    """Per-pixel shading of the orb. Static geometry is precomputed once per size."""

    RADIUS = 0.82
    SOCKET, IRIS, PUPIL = 0.64, 0.47, 0.17  # angular radii in radians

    def __init__(self, size: int):
        import numpy as np
        self.np = np
        self.size = size
        coords = (np.arange(size, dtype="float32") + 0.5) / size * 2 - 1
        u, v = np.meshgrid(coords, -coords)
        self.u, self.v = u, v
        d = np.sqrt(u * u + v * v)
        self.d = d
        pixel = 2.0 / size
        self.coverage = np.clip((self.RADIUS - d) / pixel + 0.5, 0, 1)
        inside = d < self.RADIUS
        z = np.sqrt(np.clip(self.RADIUS ** 2 - d * d, 0, None))
        self.n = np.stack([u, v, z], axis=-1) / self.RADIUS
        self.inside = inside
        n = self.n
        view = np.array([0, 0, 1], dtype="float32")
        key = np.array(_norm((-0.55, 0.72, 0.62)), dtype="float32")
        fill = np.array(_norm((0.7, -0.35, 0.55)), dtype="float32")
        ndl_key = np.clip(n @ key, 0, None)
        ndl_fill = np.clip(n @ fill, 0, None)
        half = key + view
        half /= np.linalg.norm(half)
        ndh = np.clip(n @ half, 0, None)
        self.spec_sharp = ndh ** 120
        self.spec_broad = ndh ** 14
        self.diffuse = ndl_key * 0.9 + ndl_fill * 0.25 + 0.06
        self.fresnel = (1 - np.clip(n[..., 2], 0, 1)) ** 3
        reflect = 2 * n[..., 2:3] * n - view
        ellipse = ((reflect[..., 0] + 0.24) / 0.34) ** 2 + ((reflect[..., 1] - 0.80) / 0.16) ** 2
        self.softbox = self._smooth(1.0, 0.55, ellipse)
        self.occlusion = 0.55 + 0.45 * self._smooth(-1.0, 0.35, n[..., 1])
        # Halo outside the sphere (iris-coloured glow) uses distance from the rim.
        self.halo = np.exp(-np.clip(d - self.RADIUS, 0, None) * 9) * (d >= self.RADIUS - 0.02)
        albedo = np.array([0.045, 0.05, 0.065], dtype="float32")
        body = albedo * (self.diffuse * self.occlusion)[..., None]
        body += (0.9 * self.spec_sharp + 0.12 * self.spec_broad)[..., None]
        body += (0.32 * self.softbox)[..., None] * np.array([0.85, 0.9, 1.0], dtype="float32")
        self.body = body.astype("float32")
        self.cos_socket = math.cos(self.SOCKET)
        flat = lambda a: np.ascontiguousarray(a.reshape(-1), dtype="float32")
        self.n_flat = np.where(inside[..., None], n, 0).reshape(-1, 3).astype("float32")
        self.diffuse_flat, self.spec_sharp_flat, self.spec_broad_flat = flat(self.diffuse), flat(self.spec_sharp), flat(self.spec_broad)
        self.softbox_flat, self.occlusion_flat = flat(self.softbox), flat(self.occlusion)

    def _smooth(self, edge0, edge1, x):
        np = self.np
        t = np.clip((x - edge0) / (edge1 - edge0), 0, 1)
        return t * t * (3 - 2 * t)

    def render(self, gaze=(0.0, 0.0), openness=1.0, iris="#ff3b30", glow=0.6, pupil=1.0, spin=0.0, seam=0.0) -> QImage:
        np = self.np
        iris_rgb = np.array(_hex_rgb(iris), dtype="float32")
        # --- body (everywhere): glossy obsidian; only the rim light depends on the iris.
        color = self.body + self.fresnel[..., None] * (0.35 * iris_rgb * glow + 0.06)
        # --- the eye itself is computed only for pixels inside the socket cap.
        g = np.array(_norm((gaze[0], gaze[1], 1.0)), dtype="float32")
        t1 = np.cross(np.array([0, 1, 0], dtype="float32"), g)
        t1 /= np.linalg.norm(t1)
        t2 = np.cross(g, t1)
        cos_angle = self.n_flat @ g
        index = np.nonzero(cos_angle > self.cos_socket)[0]
        if index.size:
            n = self.n_flat[index]
            diffuse, spec_sharp, spec_broad = self.diffuse_flat[index], self.spec_sharp_flat[index], self.spec_broad_flat[index]
            softbox, occlusion = self.softbox_flat[index], self.occlusion_flat[index]
            angle = np.arccos(np.clip(cos_angle[index], -1, 1))
            x_local, y_local = n @ t1, n @ t2
            # Socket: brushed gunmetal with machined grooves and a bevel.
            rho_s = angle / self.SOCKET
            grooves = 0.82 + 0.18 * np.sin(rho_s * 70)
            eye = np.array([0.16, 0.17, 0.19], dtype="float32") * (diffuse * grooves)[:, None]
            eye += (0.6 * spec_broad + 0.8 * spec_sharp + 0.25 * self._smooth(0.9, 1.0, rho_s) * (1 - self._smooth(1.0, 1.02, rho_s)))[:, None]
            # Iris: emissive fibres, limbal ring and a pupil with depth.
            rho = angle / self.IRIS
            inside_iris = rho < 1
            if inside_iris.any():
                k = np.nonzero(inside_iris)[0]
                r = rho[k]
                phi = np.arctan2(y_local[k], x_local[k])
                fibres = 0.72 + 0.14 * (np.sin(phi * 37 + r * 9 + spin) + np.sin(phi * 23 - r * 5 - spin * 0.7))
                radial = 0.35 + 0.95 * np.clip(1 - r, 0, 1) ** 0.6
                limbal = 1 - 0.7 * self._smooth(0.78, 1.0, r)
                value = iris_rgb * (fibres * radial * limbal * (0.7 + 1.4 * glow))[:, None]
                value += np.array([1.0, 0.97, 0.85], dtype="float32") * (0.5 * glow * (1 - self._smooth(0.0, 0.55, r)))[:, None]
                pupil_radius = self.PUPIL * pupil / self.IRIS
                in_pupil = r < pupil_radius
                value[in_pupil] = np.array([0.004, 0.005, 0.008], dtype="float32") + iris_rgb * 0.05 * glow
                value *= (0.35 + 0.65 * self._smooth(pupil_radius * 0.85, pupil_radius * 1.1, r))[:, None]
                # Cornea: a glass dome reflecting the studio light.
                value += (0.9 * spec_sharp[k] + 0.38 * softbox[k] + 0.2 * spec_broad[k])[:, None]
                eye[k] = value
            # Eyelids: shells closing from the top and bottom over the socket.
            if openness < 0.999:
                reach = math.sin(self.SOCKET) * 1.05
                edge = openness * reach
                curve = 0.18 * (x_local / reach) ** 2
                top_edge = edge - curve * openness
                bottom_edge = -edge * 0.92 + curve * openness * 0.6
                lid = (y_local > top_edge) | (y_local < bottom_edge)
                if lid.any():
                    lid_color = np.array([0.05, 0.055, 0.07], dtype="float32") * (diffuse * occlusion)[:, None]
                    lid_color += (0.85 * spec_sharp + 0.1 * spec_broad + 0.3 * softbox)[:, None]
                    distance = np.minimum(np.abs(y_local - top_edge), np.abs(y_local - bottom_edge))
                    lid_color += iris_rgb * (np.exp(-distance * 90) * (0.35 + seam) * glow)[:, None]
                    eye[lid] = lid_color[lid]
            flat = color.reshape(-1, 3)
            flat[index] = eye
        # --- tone map, gamma, coverage and halo.
        color = color / (1 + 0.55 * color)
        color = np.clip(color, 0, 1) ** (1 / 2.2)
        alpha = self.coverage
        halo = self.halo * (0.30 * glow) * (1 - alpha)
        halo_rgb = np.clip(iris_rgb ** (1 / 2.2), 0, 1)
        rgb = color * alpha[..., None] + halo_rgb * halo[..., None]
        total = alpha + halo
        rgba = np.empty((self.size, self.size, 4), dtype="uint8")
        rgba[..., :3] = np.clip(rgb * 255 + 0.5, 0, 255)
        rgba[..., 3] = np.clip(total * 255 + 0.5, 0, 255)
        rgba[..., :3] = np.minimum(rgba[..., :3], rgba[..., 3:4])
        image = QImage(rgba.data, self.size, self.size, self.size * 4, QImage.Format.Format_RGBA8888_Premultiplied)
        return image.copy()


# ---------------------------------------------------------------- flat 2D icon
def paint_flat_eye(painter: QPainter, rect: QRectF, iris="#ff3b30"):
    """The mascot as a flat icon: same silhouette and palette, no 3D shading."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(rect.width(), rect.height())
    c = rect.center()
    r = side * 0.47
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#14161b"))
    painter.drawEllipse(c, r, r)
    if side >= 24:
        painter.setPen(QPen(QColor(iris).darker(160), max(1.0, side * 0.025)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(c, r * 0.97, r * 0.97)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3b4049"))
        painter.drawEllipse(c, r * 0.66, r * 0.66)
    painter.setBrush(QColor(iris))
    painter.drawEllipse(c, r * 0.5, r * 0.5)
    if side >= 20:
        painter.setBrush(QColor(iris).lighter(140))
        painter.drawEllipse(c, r * 0.3, r * 0.3)
    painter.setBrush(QColor("#05070a"))
    painter.drawEllipse(c, r * 0.19, r * 0.19)
    painter.setBrush(QColor(255, 255, 255, 235))
    painter.drawEllipse(QPointF(c.x() - r * 0.2, c.y() - r * 0.22), r * 0.09, r * 0.09)
    painter.restore()


def flat_eye_image(size: int, iris="#ff3b30") -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    paint_flat_eye(painter, QRectF(0, 0, size, size), iris)
    painter.end()
    return image


_ICONS: dict[str, QIcon] = {}


def app_icon(iris="#ff3b30") -> QIcon:
    if iris in _ICONS:
        return _ICONS[iris]
    result = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        result.addPixmap(QPixmap.fromImage(flat_eye_image(size, iris)))
    _ICONS[iris] = result
    return result


def write_ico(path, iris="#ff3b30", sizes=(16, 20, 24, 32, 40, 48, 64, 128, 256)):
    """Write a multi-resolution .ico with PNG-compressed entries (Vista+ format)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    blobs = []
    for size in sizes:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        flat_eye_image(size, iris).save(buffer, "PNG")
        blobs.append((size, bytes(data)))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries, payload = b"", b""
    for size, blob in blobs:
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(blob), offset + len(payload))
        payload += blob
    with open(path, "wb") as stream:
        stream.write(header + entries + payload)


# ---------------------------------------------------------------- animated window
class Spring:
    """Critically damped spring for natural, fast-settling eye movements."""
    def __init__(self, value=0.0, speed=18.0):
        self.value, self.velocity, self.speed = value, 0.0, speed

    def step(self, target, dt):
        omega = self.speed
        x = self.value - target
        exp = math.exp(-omega * dt)
        temp = (self.velocity + omega * x) * dt
        self.velocity = (self.velocity - omega * temp) * exp
        self.value = target + (x + temp) * exp
        return self.value


SONAR = "#ff3b30"


class MascotWindow(QWidget):
    """Always-on-top living eye beside the notch.

    Where it looks, in priority order: an area it is scanning, the mouse pointer
    while you move it, the text you are typing (reading along), where your eyes
    look (opt-in webcam, self-calibrated from mouse movement), your face, then
    its own idle life. It breathes, floats, tilts, hops, startles, gets dizzy,
    gets annoyed, hunts, yawns and sleeps, scans with red sonar, and tucks itself
    neatly above the screen edge when idle.
    """
    clicked = Signal()
    menu_requested = Signal(QPoint)
    tucked_changed = Signal(bool)

    ORB = 84
    MARGIN = 34   # room around the orb for sonar rings and z's
    SLEEP_AFTER = 90.0
    IDLE_AFTER = 6.0  # pointer stillness before idle behaviours start

    def __init__(self, model, start_animation=True):
        # Not WindowDoesNotAcceptFocus: a click must reach and activate Cyclop so the
        # panel it opens can take the foreground.
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.model = model
        self.setWindowTitle("Cyclop")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.anchor = QRect()
        self.orb_left = float(self.MARGIN)      # orb position inside the window
        self.footer_left = 0.0                  # stats pill position inside the window
        self.state = "idle"
        self.level = 0.0
        self.stats = {}
        self.caption = ""
        self.caption_timer = QTimer(self)
        self.caption_timer.setSingleShot(True)
        self.caption_timer.timeout.connect(self.clear_caption)
        self.tucked = False
        self.offset = 0.0  # 0 = fully shown, 1 = tucked
        self.renderer = None
        self.frame = QImage()
        self.dpr = 1.0
        now = time.monotonic()
        self.gaze_x, self.gaze_y = Spring(0, 22), Spring(0, 22)
        self.target = (0.0, 0.0)
        self.look_target = None       # global point to stare at (scanned area)
        self.glance = (0.0, 0.0)       # small offsets that keep a steady stare alive
        self.next_glance = now + 2.0
        self.next_saccade = 0.0
        self.next_blink = now + 2.0
        self.blink_started = None
        self.spin = 0.0
        self.last = now
        self.started = now
        self.last_render = 0.0
        self.last_signature = None
        # Body language
        self.hop = Spring(0.0, 9.0)        # vertical offset in px
        self.squash = Spring(0.0, 11.0)    # >0 squashed, <0 stretched
        self.tilt = Spring(0.0, 6.0)       # degrees
        self.lean_x = Spring(0.0, 5.0)     # px towards something interesting
        self.tilt_target = 0.0
        self.behaviour, self.behaviour_until = None, 0.0
        self.behaviour_point = None
        self.next_behaviour = now + random.uniform(4, 7)
        self.happy_until = 0.0
        self.shake_until = 0.0
        self.startle_until = 0.0
        self.dizzy_until = 0.0
        self.annoyed_until = 0.0
        self.yawn_started = None
        self.was_sleepy = False
        self.intro_started = now
        self.intro_pinged = False
        # Pointer, keyboard and camera senses
        self.last_pointer, self.last_pointer_move = QCursor.pos(), now
        self.last_pointer_time = now
        self.pointer_speed = 0.0
        self.orbit_angle = None
        self.orbit_total, self.orbit_started = 0.0, now
        self.near = False
        self.input_tick = 0
        self.last_typing = -1e9  # "never", whatever the clock origin
        self.reading_start = now
        self.clicks: list[float] = []
        self.face = None             # (x, y) in [0, 1], mirrored camera coordinates
        self.face_time = 0.0
        self.face_absent_since = now
        self.user_gaze = None        # global point the user is estimated to look at
        self.user_gaze_time = 0.0
        # Sonar
        self.pings: list[float] = []
        self.next_ping = now + 1.5
        self.sweep_angle = 0.0
        self.sweeping_until = 0.0
        self.zs: list[tuple[float, float]] = []  # (start time, x jitter) of sleep z's
        self.next_z = now
        self.press_pos = None
        self.press_time = 0.0
        self.last_click = 0.0
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(lambda: self.set_tucked(True))
        self.slide = QVariantAnimation(self)
        self.slide.setDuration(420)
        self.slide.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.slide.valueChanged.connect(self._slid)
        self.frame_timer = QTimer(self)
        self.frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.frame_timer.timeout.connect(self.tick)
        self.pointer = QTimer(self)
        self.pointer.setInterval(60)
        self.pointer.timeout.connect(self.pointer_tick)
        model.config_changed.connect(self.apply_config)
        # Wake-up intro: start tucked away with closed lids and slide in.
        self.offset = 1.0 if start_animation else 0.0
        self.apply_config()
        if start_animation:
            self.slide.setDuration(700)
            self.slide.setStartValue(1.0)
            self.slide.setEndValue(0.0)
            self.slide.start()
            self.slide.finished.connect(lambda: self.slide.setDuration(420))
            self.frame_timer.start(33)
            self.pointer.start()
        else:
            self.intro_started = now - 10

    # ------------------------------------------------------------ configuration & layout
    @property
    def iris(self):
        base = IRIS_COLORS[self.model.config["mascot_iris"]]
        if self.state == "error":
            return "#ffb347"
        if self.state == "listening" or time.monotonic() < self.annoyed_until:
            return QColor(base).lighter(130).name()
        return base

    def stats_visible(self):
        return bool(self.model.config["stats_enabled"] and self.model.config["stats_items"])

    def footer_font(self):
        font = QFont("Segoe UI", 8)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def footer_parts(self):
        if self.caption:
            return [(self.caption, "#f0f0f0")]
        if not self.stats_visible():
            return []
        parts = [(stat_label(key, self.stats.get(key)), stat_color(key, self.stats.get(key)))
                 for key in STAT_KEYS if key in self.model.config["stats_items"]]
        if self.offset > 0.5:
            parts.insert(0, ("●", SONAR))  # the tucked eye, as a red dot
        return parts

    def footer_width(self):
        from PySide6.QtGui import QFontMetrics
        parts = self.footer_parts()
        if not parts:
            return 0
        metrics = QFontMetrics(self.footer_font())
        # Reserve room for the widest value ("100%", "100°") so the window does not jitter.
        widest = sum(metrics.horizontalAdvance(text if (self.caption or text == "●") else text.split(" ")[0] + " 100%") for text, _ in parts)
        return min(360, widest + 9 * (len(parts) - 1) + 32)

    def footer_height(self):
        return 22 if (self.stats_visible() or self.caption) else 0

    def orb_rect(self) -> QRectF:
        return QRectF(self.orb_left, self.MARGIN, self.ORB, self.ORB)

    def footer_rect(self) -> QRectF:
        return QRectF(self.footer_left, self.MARGIN + self.ORB + 6, max(1, self.footer_width()), self.footer_height() - 2)

    def handle_rect(self) -> QRectF:
        """The slim glowing tab left at the screen edge when tucked without stats."""
        return QRectF(self.orb_rect().center().x() - 22, self.MARGIN + self.ORB + 6, 44, 7)

    def apply_config(self):
        config = self.model.config
        if not config["mascot_enabled"]:
            self.hide()
            return
        self.reposition()
        self.show()
        self.reset_hide_timer()

    def set_anchor(self, rect: QRect):
        self.anchor = QRect(rect)
        self.reposition()
        if self.isVisible():
            self.raise_()  # never end up underneath the panel

    def screen_bounds(self):
        screen = QApplication.screenAt(self.anchor.center()) if not self.anchor.isNull() else None
        return (screen or QApplication.primaryScreen()).availableGeometry()

    def layout_global(self):
        """Global x of the eye centre and of the stats pill, plus the side it sits on.

        The eye stays put whether the panel is open or closed: it sits just beside
        where the *expanded* panel ends, so clicking it twice in the same spot works.
        The stats pill hangs below the eye but is pushed outwards so it never slides
        under the notch or the open panel.
        """
        bounds = self.screen_bounds()
        anchor = self.anchor if not self.anchor.isNull() else QRect(bounds.center().x() - 96, bounds.y(), 192, 28)
        notch_center = anchor.center().x()
        half_panel = min(644, bounds.width()) // 2
        gap = 12 + self.ORB / 2
        pill = self.footer_width()
        right_side = notch_center + half_panel + gap + self.ORB / 2 + 4 <= bounds.right()
        if right_side:
            eye = notch_center + half_panel + gap
            avoid = notch_center + half_panel + 6           # keep everything right of this
        elif notch_center - half_panel - gap - self.ORB / 2 - 4 >= bounds.left():
            eye = notch_center - half_panel - gap
            avoid = notch_center - half_panel - 6           # keep everything left of this
        else:  # narrow screen: overlap the panel, but stay on top of it (see set_anchor)
            eye = min(bounds.right() - self.ORB / 2 - 4, notch_center + 96 + gap)
            avoid = None
        pill_left = eye - pill / 2
        if avoid is not None and right_side:
            pill_left = max(pill_left, avoid)
        elif avoid is not None:
            pill_left = min(pill_left, avoid - pill)
        pill_left = max(bounds.left() + 2, min(pill_left, bounds.right() - pill - 2))
        return eye, pill_left, pill, (avoid, right_side)

    def reposition(self):
        bounds = self.screen_bounds()
        eye, pill_left, pill, (avoid, right_side) = self.layout_global()
        orb_left_global = eye - self.ORB / 2
        left = min(orb_left_global - self.MARGIN, pill_left if pill else orb_left_global)
        right = max(orb_left_global + self.ORB + self.MARGIN, pill_left + pill if pill else 0)
        if avoid is not None and right_side:
            left = max(left, avoid)    # no invisible margin over the open panel
        elif avoid is not None:
            right = min(right, avoid)
        left, right = int(math.floor(left)), int(math.ceil(right))
        self.orb_left = orb_left_global - left
        self.footer_left = pill_left - left
        width = max(1, right - left)
        height = max(self.ORB + 2 * self.MARGIN, self.MARGIN + self.ORB + 8 + self.footer_height())
        shown_top = bounds.y() + 4
        # Tucked: the whole eye sits above the screen edge; the stats pill (or a
        # slim red handle) is left docked at the top edge.
        tucked_top = bounds.y() - self.ORB - 6
        orb_top = shown_top + (tucked_top - shown_top) * self.offset
        self.setGeometry(left, int(round(orb_top - self.MARGIN)), width, int(height))

    def _slid(self, value):
        self.offset = float(value)
        self.reposition()
        self.update()

    def set_tucked(self, tucked):
        if not self.model.config["mascot_autohide"] and tucked:
            return
        busy = self.state in ("listening", "thinking", "scanning")
        if tucked and (busy or self.underMouse() or time.monotonic() - self.last_pointer_move < 1.0 and self.near):
            self.reset_hide_timer()
            return
        if tucked == self.tucked:
            return
        self.tucked = tucked
        self.slide.stop()
        self.slide.setStartValue(self.offset)
        self.slide.setEndValue(1.0 if tucked else 0.0)
        self.slide.start()
        if tucked:
            self.pings.clear()
            self.sweeping_until = 0.0
        else:
            self.wake()
        self.apply_config()
        self.tucked_changed.emit(tucked)

    def reset_hide_timer(self):
        if self.model.config["mascot_autohide"]:
            self.hide_timer.start(int(self.model.config["mascot_autohide_seconds"] * 1000))
        else:
            self.hide_timer.stop()

    def reveal(self):
        self.set_tucked(False)
        self.reset_hide_timer()

    def hover_zone(self) -> QRect:
        """Where hovering brings Cyclop back: the eye, or the docked pill/handle."""
        if self.tucked:
            area = self.footer_rect() if self.footer_height() else self.handle_rect()
            top_left = self.mapToGlobal(area.topLeft().toPoint())
            return QRect(top_left, QSize(int(area.width()), int(area.height()))).adjusted(-10, -6, 10, 10)
        orb = self.orb_rect()
        return QRect(self.mapToGlobal(orb.topLeft().toPoint()), QSize(self.ORB, self.ORB)).adjusted(-10, -6, 10, 10)

    def eye_center_global(self) -> QPoint:
        return self.mapToGlobal(self.orb_rect().center().toPoint())

    # ------------------------------------------------------------ senses
    def pointer_tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        position = QCursor.pos()
        dt = max(1e-3, now - self.last_pointer_time)
        delta = position - self.last_pointer
        distance_moved = math.hypot(delta.x(), delta.y())
        self.pointer_speed = distance_moved / dt
        center = self.eye_center_global()
        before = math.hypot(self.last_pointer.x() - center.x(), self.last_pointer.y() - center.y())
        distance = math.hypot(position.x() - center.x(), position.y() - center.y())
        if distance_moved > 3:
            self.last_pointer_move = now
            # Startle: the pointer darts straight at the eye.
            approach = (before - distance) / dt
            if approach > 2200 and distance < 260 and now > self.startle_until + 2:
                self.startle()
            # Dizzy: circling the pointer around the eye.
            angle = math.atan2(position.y() - center.y(), position.x() - center.x())
            if distance < 320 and self.orbit_angle is not None:
                step = (angle - self.orbit_angle + math.pi) % (2 * math.pi) - math.pi
                if now - self.orbit_started > 3.0:
                    self.orbit_total, self.orbit_started = 0.0, now
                self.orbit_total += step
                if abs(self.orbit_total) > 2.2 * 2 * math.pi:
                    self.get_dizzy()
                    self.orbit_total = 0.0
            self.orbit_angle = angle if distance < 320 else None
        self.last_pointer, self.last_pointer_time = position, now
        # Typing: input happened but the pointer did not move.
        tick = last_input_tick()
        if tick and tick != self.input_tick:
            if self.input_tick and distance_moved <= 3:
                if now - self.last_typing > 2.0:
                    self.reading_start = now
                self.last_typing = now
            self.input_tick = tick
        if self.hover_zone().contains(position):
            self.reveal()
        near = distance < 160
        if near and not self.near:
            self.perk_up()
        self.near = near

    def set_face(self, point):
        """Face position from the webcam, (x, y) in [0, 1] mirrored, or None."""
        now = time.monotonic()
        if point is not None:
            if self.face is None and now - self.face_absent_since > 20 and now - self.started > 5:
                self.greet()
            self.face, self.face_time = point, now
        else:
            if self.face is not None:
                self.face_absent_since = now
            self.face = None

    def set_user_gaze(self, point):
        """Where the user is estimated to look (global screen point), or None."""
        self.user_gaze = QPoint(point) if point is not None else None
        self.user_gaze_time = time.monotonic()

    # ------------------------------------------------------------ moods & reactions
    def set_state(self, state):
        previous, self.state = self.state, state
        if state in ("listening", "thinking", "scanning"):
            self.reveal()
            self.wake()
        if state == "scanning":
            self.sweeping_until = time.monotonic() + 3600
            self.ping()
        elif previous == "scanning":
            self.sweeping_until = time.monotonic() + 0.4
            self.look_target = None
        if state == "error":
            self.shake_until = time.monotonic() + 0.6
        if state == "idle":
            self.reset_hide_timer()

    def set_level(self, level):
        self.level = level

    def set_stats(self, values):
        self.stats = values or {}
        details = values.get("details", []) if values else []
        self.setToolTip("\n".join(details))
        self.update()

    def say(self, text, seconds=3.5):
        self.caption = text
        self.apply_config()
        self.reveal()
        self.caption_timer.start(int(seconds * 1000))
        self.update()

    def clear_caption(self):
        self.caption = ""
        self.apply_config()
        self.update()

    def look_at(self, point: QPoint | None):
        self.look_target = QPoint(point) if point is not None else None

    def ping(self):
        """Send out a red sonar pulse (two rings)."""
        now = time.monotonic()
        self.pings = [p for p in self.pings if now - p < 2.0] + [now, now + 0.28]

    def happy(self):
        """Delighted bounce: squash, hop, squint and a sonar ping."""
        now = time.monotonic()
        self.wake()
        self.happy_until = now + 0.9
        self.squash.velocity += 2.6
        self.hop.velocity -= 70
        self.ping()

    def greet(self):
        self.happy()
        self.next_blink = time.monotonic()

    def startle(self):
        now = time.monotonic()
        self.wake()
        self.startle_until = now + 0.8
        self.hop.velocity -= 110
        self.squash.velocity -= 3.0
        self.next_blink = now + 0.9

    def get_dizzy(self):
        now = time.monotonic()
        self.wake()
        self.dizzy_until = now + 3.2
        self.reveal()

    def perk_up(self):
        if self.state in ("listening", "thinking", "scanning"):
            return
        self.wake()
        self.hop.velocity -= 28
        self.next_blink = time.monotonic() + 0.05

    def wake(self):
        self.last_pointer_move = time.monotonic()
        self.yawn_started = None

    def register_click(self):
        now = time.monotonic()
        self.clicks = [c for c in self.clicks if now - c < 2.0] + [now]
        if len(self.clicks) >= 4:
            self.annoyed_until = now + 2.2
            self.shake_until = now + 0.5
            self.clicks.clear()
            return True
        return False

    @property
    def sleepy(self):
        return (self.state == "idle" and not self.near and self.face is None and
                time.monotonic() - self.last_pointer_move > self.SLEEP_AFTER and
                time.monotonic() - self.last_typing > self.SLEEP_AFTER)

    def choose_behaviour(self, now):
        """Idle life: look around scanning, tilt the head, hop, hunt, or squint."""
        options = [("look_around", 3.2), ("tilt", 1.8), ("hop", 0.6), ("sonar", 1.6), ("squint", 1.2), ("hunt", 2.2)]
        weights = [4, 3, 2, 3, 2, 3]
        name, duration = random.choices(options, weights)[0]
        self.behaviour, self.behaviour_until = name, now + duration
        if name == "tilt":
            self.tilt_target = random.choice((-1, 1)) * random.uniform(7, 12)
        elif name == "hop":
            self.hop.velocity -= 55
            self.squash.velocity -= 1.6
        elif name in ("sonar", "look_around"):
            self.ping()
            if name == "look_around":
                self.sweeping_until = now + duration
        elif name == "hunt":
            # Pick a spot on the screen, ping at it and stare: something is there.
            bounds = self.screen_bounds()
            self.behaviour_point = QPoint(random.randint(bounds.left() + 40, bounds.right() - 40),
                                          random.randint(bounds.top() + 120, bounds.bottom() - 40))
            self.ping()
        self.next_behaviour = now + duration + random.uniform(3.5, 9.0)

    # ------------------------------------------------------------ animation
    def tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        dt = min(0.1, now - self.last)
        self.last = now
        resting = self.tucked and self.offset >= 0.999 and not self.pings
        wanted = 250 if resting else 33
        if self.frame_timer.interval() != wanted:
            self.frame_timer.setInterval(wanted)
        sleepy = self.sleepy
        if sleepy and not self.was_sleepy:
            self.yawn_started = now  # a big yawn before dozing off
        self.was_sleepy = sleepy
        pointer_active = now - self.last_pointer_move < 2.5
        typing = now - self.last_typing < 1.5 and not pointer_active
        dizzy = now < self.dizzy_until
        if self.behaviour and now >= self.behaviour_until:
            if self.behaviour == "hunt":
                self.hop.velocity -= 45  # "got it"
                self.ping()
            self.behaviour, self.behaviour_point = None, None
            self.tilt_target = 0.0
        idle_long = now - self.last_pointer_move > self.IDLE_AFTER and not typing
        if (not self.behaviour and not sleepy and not self.tucked and self.state == "idle" and idle_long
                and not dizzy and now >= self.next_behaviour):
            self.choose_behaviour(now)
        # Sonar: periodic pings while awake, continuous while scanning or listening.
        interval = 1.1 if self.state == "scanning" else (2.2 if self.state == "listening" else random.uniform(7, 12))
        if now >= self.next_ping and not sleepy and not self.tucked:
            if self.state in ("scanning", "listening") or random.random() < 0.6:
                self.ping()
            self.next_ping = now + interval
        self.pings = [p for p in self.pings if now - p < 1.6]
        sweeping = now < self.sweeping_until
        if sweeping:
            self.sweep_angle = (self.sweep_angle + dt * (260 if self.state == "scanning" else 150)) % 360
        # Small glances keep a steady stare alive.
        if now >= self.next_glance:
            self.glance = (random.uniform(-0.04, 0.04), random.uniform(-0.03, 0.03)) if random.random() < 0.7 else (0.0, 0.0)
            self.next_glance = now + random.uniform(0.6, 2.4)
        # ---------------- gaze, in priority order
        camera_gaze = self.user_gaze is not None and now - self.user_gaze_time < 0.6
        camera_face = self.face is not None and now - self.face_time < 0.6
        follow = self.model.config["mascot_follow_cursor"]
        lean = 0.0
        inspect_tilt = None
        if self.look_target is not None:
            self.target = self._target_towards(self.look_target, 1400)
        elif dizzy:
            spin = now * 9
            self.target = (0.32 * math.cos(spin), 0.24 * math.sin(spin))
        elif self.state == "thinking":
            self.target = (0.32 * math.cos(now * 2.4), 0.18 + 0.1 * math.sin(now * 2.4))
        elif follow and pointer_active:
            cursor = self._cursor_target()
            jitter = 0.012 * math.sin(now * 23)  # micro-saccades
            self.target = (cursor[0] + jitter, cursor[1] - jitter)
        elif typing:
            # Reading along: drift left → right across a line, then snap back.
            line = ((now - self.reading_start) % 2.4) / 2.4
            self.target = (-0.3 + 0.6 * line, -0.22)
        elif camera_gaze:
            gaze = self._target_towards(self.user_gaze, 1200)
            self.target = (gaze[0] + self.glance[0], gaze[1] + self.glance[1])
        elif camera_face:
            # Eye contact: look out at you, following your head.
            fx, fy = self.face
            self.target = ((fx - 0.5) * 0.7 + self.glance[0], (0.5 - fy) * 0.5 - 0.12 + self.glance[1])
        elif self.behaviour == "hunt" and self.behaviour_point is not None:
            self.target = self._target_towards(self.behaviour_point, 1300)
        elif sweeping:
            radians = math.radians(self.sweep_angle)
            self.target = (0.36 * math.cos(radians), 0.28 * math.sin(radians))
        elif sleepy:
            self.target = (0.0, -0.18)
        elif follow:
            # Pointer still: keep watching it, glancing now and then; lean in when close.
            cursor = self._cursor_target()
            self.target = (cursor[0] + self.glance[0], cursor[1] + self.glance[1])
            pointer = QCursor.pos()
            center = self.eye_center_global()
            if math.hypot(pointer.x() - center.x(), pointer.y() - center.y()) < 600:
                lean = max(-3.0, min(3.0, (pointer.x() - center.x()) / 80))
                inspect_tilt = max(-5.0, min(5.0, (pointer.x() - center.x()) / 60))
        elif now >= self.next_saccade:
            self.target = (random.uniform(-0.38, 0.38), random.uniform(-0.28, 0.3))
            self.next_saccade = now + random.uniform(1.1, 3.6)
        gx = self.gaze_x.step(self.target[0], dt)
        gy = self.gaze_y.step(self.target[1], dt)
        # ---------------- lids
        intro = now - self.intro_started
        if intro < 1.2:
            openness = min(1.0, max(0.05, (intro - 0.35) / 0.8))
        elif self.tucked:
            openness = 0.42
        elif self.yawn_started is not None and now - self.yawn_started < 2.2:
            phase = (now - self.yawn_started) / 2.2
            # Squeeze shut, then settle heavy-lidded.
            openness = 1.0 - 0.9 * math.sin(phase * math.pi) ** 2 if phase < 0.7 else 0.41 - 0.08 * (phase - 0.7) / 0.3
        elif sleepy:
            openness = 0.3 + 0.05 * math.sin(now * 0.8)
        elif now < self.startle_until:
            openness = 1.0
        elif now < self.annoyed_until or now < self.happy_until:
            openness = 0.55
        elif dizzy:
            openness = 0.62 + 0.15 * math.sin(now * 7)
        elif self.state == "thinking" or self.behaviour in ("squint", "hunt"):
            openness = 0.7
        else:
            openness = 1.0
        if now >= self.next_blink and self.blink_started is None and intro > 1.2:
            self.blink_started = now
        if self.blink_started is not None:
            length = 0.5 if sleepy else 0.17
            phase = (now - self.blink_started) / length
            if phase >= 1:
                self.blink_started = None
                gap = random.uniform(4.0, 8.0) if sleepy else (0.18 if random.random() < 0.15 else random.uniform(2.4, 6.0))
                self.next_blink = now + gap
            else:
                openness *= abs(math.cos(phase * math.pi)) ** 0.7
        if 1.2 <= intro < 1.6 and self.blink_started is None:
            self.next_blink = now  # wake-up double blink
        if intro >= 1.2 and not self.intro_pinged:
            self.intro_pinged = True
            self.ping()
        # ---------------- body
        if dizzy:
            self.tilt_target = 9 * math.sin(now * 6)
        elif self.behaviour != "tilt":
            self.tilt_target = inspect_tilt if inspect_tilt is not None else 0.0
        self.hop.step(0.0, dt)
        self.squash.step(0.0, dt)
        self.tilt.step(self.tilt_target, dt)
        self.lean_x.step(lean, dt)
        # Sleep z's float up from the eye.
        if sleepy and not self.tucked and now >= self.next_z:
            self.zs.append((now, random.uniform(-4, 4)))
            self.next_z = now + 1.4
        self.zs = [z for z in self.zs if now - z[0] < 2.6]
        # ---------------- glow and pupil
        rate = 0.8 if sleepy else 1.7
        breathe = 0.5 + 0.08 * math.sin((now - self.started) * rate)
        glow = breathe * (0.7 if sleepy else 1.0) + (0.45 * self.level + 0.15 if self.state == "listening" else 0)
        glow += 0.25 if self.state == "scanning" else 0
        glow += 0.35 if now < self.annoyed_until else 0
        hippus = 0.03 * math.sin(now * 0.9)
        pupil = 1.0 + hippus + (0.35 * self.level if self.state == "listening" else 0)
        pupil += 0.15 if self.near or abs(lean) > 1 else 0
        pupil -= 0.2 if self.state in ("thinking", "scanning") else 0
        pupil = 0.62 if now < self.startle_until else pupil
        pupil = 1.25 if self.yawn_started is not None and now - self.yawn_started < 2.2 else pupil
        self.spin += dt * (14 if dizzy else 3.5 if self.state in ("thinking", "scanning") else 0.25)
        signature = (round(gx, 3), round(gy, 3), round(openness, 2), round(pupil, 2), self.iris, self.state)
        moving = signature != self.last_signature or self.state in ("listening", "thinking", "scanning") or dizzy
        if moving or now - self.last_render > 0.12 or self.frame.isNull():
            self.last_signature = signature
            self.last_render = now
            self.render_frame(gx, gy, openness, glow, pupil)
        self.update()

    def _target_towards(self, point, reach):
        center = self.eye_center_global()
        dx, dy = point.x() - center.x(), point.y() - center.y()
        return (max(-0.42, min(0.42, dx / reach)), max(-0.32, min(0.36, -dy / (reach * 0.75))))

    def _cursor_target(self):
        """Gaze towards the pointer anywhere on the desktop."""
        position = QCursor.pos()
        center = self.eye_center_global()
        bounds = self.screen_bounds()
        reach_x = max(400.0, bounds.width() / 2)
        reach_y = max(300.0, bounds.height() * 0.8)
        dx, dy = position.x() - center.x(), position.y() - center.y()
        # Ease-out so small movements nearby still read clearly.
        ex = math.copysign(min(1.0, abs(dx) / reach_x) ** 0.7, dx)
        ey = math.copysign(min(1.0, abs(dy) / reach_y) ** 0.7, dy)
        return (0.42 * ex, max(-0.32, min(0.36, -0.36 * ey)))

    def render_frame(self, gx, gy, openness, glow, pupil):
        dpr = self.devicePixelRatioF() or 1.0
        size = int(self.ORB * dpr)
        if self.renderer is None or self.renderer.size != size:
            self.renderer = EyeRenderer(size)
        self.dpr = dpr
        self.frame = self.renderer.render((gx, gy), openness, self.iris, glow, pupil, self.spin,
                                          seam=0.4 if self.state in ("listening", "scanning") else 0.0)
        self.frame.setDevicePixelRatio(dpr)

    # ------------------------------------------------------------ painting & input
    def body_offset(self, now):
        float_x = 1.6 * math.sin((now - self.started) * 0.7) + self.lean_x.value
        bob = (0.8 if self.sleepy else 1.8) * math.sin((now - self.started) * (0.9 if self.sleepy else 1.6))
        shake = 4 * math.sin(now * 55) * max(0.0, (self.shake_until - now) / 0.6) if now < self.shake_until else 0.0
        if now < self.dizzy_until:
            float_x += 3 * math.sin(now * 5)
        return float_x + shake, bob + self.hop.value

    def paintEvent(self, event):
        now = time.monotonic()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        orb = self.orb_rect()
        dx, dy = self.body_offset(now)
        center = orb.center() + QPointF(dx, dy)
        if self.offset < 0.98:
            self.paint_sonar(painter, center, now)
            breathe = 1 + 0.018 * math.sin((now - self.started) * (0.8 if self.sleepy else 1.7))
            squash = max(-0.25, min(0.25, self.squash.value * 0.06))
            painter.save()
            painter.translate(center)
            painter.rotate(self.tilt.value)
            painter.scale(breathe * (1 + squash), breathe * (1 - squash))
            target = QRectF(-self.ORB / 2, -self.ORB / 2, self.ORB, self.ORB)
            if not self.frame.isNull():
                painter.drawImage(target, self.frame)
            else:
                paint_flat_eye(painter, target, self.iris)
            painter.restore()
            self.paint_zs(painter, center, now)
        if self.footer_height():
            self.paint_footer(painter, self.footer_rect())
        elif self.offset > 0.05:
            self.paint_handle(painter, now)

    def paint_handle(self, painter, now):
        """Slim glowing red tab at the screen edge: Cyclop is tucked up here."""
        area = self.handle_rect()
        alpha = min(1.0, self.offset * 1.4)
        pulse = 0.75 + 0.25 * math.sin(now * 2.2)
        red = QColor(SONAR)
        glow = QColor(red.red(), red.green(), red.blue(), int(70 * alpha * pulse))
        path = QPainterPath()
        path.addRoundedRect(area.adjusted(-4, -2, 4, 3), 6, 6)
        painter.fillPath(path, glow)
        core = QPainterPath()
        core.addRoundedRect(area, area.height() / 2, area.height() / 2)
        painter.fillPath(core, QColor(red.red(), red.green(), red.blue(), int(230 * alpha)))

    def paint_zs(self, painter, center, now):
        if not self.zs:
            return
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        for start, jitter in self.zs:
            t = (now - start) / 2.6
            x = center.x() + self.ORB * 0.32 + 14 * t + jitter
            y = center.y() - self.ORB * 0.36 - 30 * t
            size = 0.7 + 0.6 * t
            painter.save()
            painter.translate(x, y)
            painter.scale(size, size)
            painter.setPen(QColor(255, 120, 110, int(220 * (1 - t))))
            painter.drawText(QPointF(0, 0), "z")
            painter.restore()

    def paint_sonar(self, painter, center, now):
        red = QColor(SONAR)
        radius = self.ORB / 2
        reach = self.MARGIN - 2
        if now < self.sweeping_until:
            from PySide6.QtGui import QConicalGradient
            sweep = QConicalGradient(center, -self.sweep_angle)
            sweep.setColorAt(0.0, QColor(red.red(), red.green(), red.blue(), 120))
            sweep.setColorAt(0.16, QColor(red.red(), red.green(), red.blue(), 0))
            sweep.setColorAt(1.0, QColor(red.red(), red.green(), red.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(sweep)
            painter.drawEllipse(center, radius + reach, radius + reach)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(red.red(), red.green(), red.blue(), 55), 1))
            for fraction in (0.45, 1.0):
                painter.drawEllipse(center, radius + reach * fraction, radius + reach * fraction)
        for start in self.pings:
            age = now - start
            if age < 0:
                continue
            t = min(1.0, age / 1.4)
            ring = radius + reach * (1 - (1 - t) ** 2)
            alpha = int(200 * (1 - t) ** 1.4)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(red.red(), red.green(), red.blue(), alpha), 2.2 - 1.2 * t))
            painter.drawEllipse(center, ring, ring)

    def paint_footer(self, painter, area):
        painter.setFont(self.footer_font())
        metrics = painter.fontMetrics()
        parts = self.footer_parts()
        spacing = 9
        text_width = sum(metrics.horizontalAdvance(text) for text, _ in parts) + spacing * (len(parts) - 1)
        text_width = min(text_width, area.width() - 16)
        pill = QRectF(area.center().x() - text_width / 2 - 8, area.y(), text_width + 16, area.height())
        path = QPainterPath()
        path.addRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        painter.fillPath(path, QColor(8, 9, 11, 215))
        x = pill.x() + 8
        for text, color in parts:
            text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(pill.right() - x - 4))
            painter.setPen(QColor(color))
            painter.drawText(QRectF(x, pill.y(), pill.right() - x, pill.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            x += metrics.horizontalAdvance(text) + spacing

    def hits_body(self, pos: QPointF) -> bool:
        if self.offset > 0.5:  # tucked: the docked pill or handle is the target
            area = self.footer_rect() if self.footer_height() else self.handle_rect()
            return area.adjusted(-6, -6, 6, 6).contains(pos)
        orb = self.orb_rect().adjusted(-6, -6, 6, 6)
        center = orb.center()
        on_orb = math.hypot(pos.x() - center.x(), pos.y() - center.y()) <= orb.width() / 2
        return on_orb or (self.footer_height() > 0 and self.footer_rect().contains(pos))

    def mousePressEvent(self, event):
        self.reveal()
        self.wake()
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.hits_body(event.position()):
                self.press_pos = None
                return
            self.press_pos = event.position()
            self.press_time = time.monotonic()
            self.squash.velocity += 1.5  # it feels the press
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.press_pos is not None:
            moved = (event.position() - self.press_pos).manhattanLength()
            self.press_pos = None
            now = time.monotonic()
            if moved < 12:
                annoyed = self.register_click()
                if not annoyed:
                    self.happy()
                # One action per click; the second half of a double-click is absorbed.
                if now - self.last_click > 0.45:
                    self.last_click = now
                    self.clicked.emit()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        # Treat the second click of a double-click as a press so it is not lost,
        # and never let Qt's default turn one double-click into two toggles.
        self.mousePressEvent(event)

    def enterEvent(self, event):
        self.reveal()
        super().enterEvent(event)

    def shutdown(self):
        self.frame_timer.stop()
        self.pointer.stop()
        self.hide_timer.stop()
