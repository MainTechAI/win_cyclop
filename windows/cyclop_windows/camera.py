"""Opt-in webcam gaze: Cyclop looks where you look.

Pipeline (all on this PC; frames and features are never saved or sent):

1. ``FaceTracker`` grabs low-resolution webcam frames and runs the YuNet face
   detector, which returns a face box plus eye, nose and mouth landmarks.
2. ``eye_features`` turns one detection into a small feature vector: head
   position, head turn (nose versus eyes) and pupil offsets inside each eye.
3. ``GazeCalibrator`` learns, continuously, a mapping from those features to a
   point on the screen. While you move the mouse you are almost always looking
   at the pointer, so every mouse movement is a free calibration sample. Ridge
   regression on recent samples keeps adapting as you shift in your chair.

A webcam cannot track gaze precisely; expect accuracy of roughly a screen
region, improving with use. When the estimate is not yet reliable, Cyclop
simply looks at you (your face position) instead.
"""
from __future__ import annotations

from collections import deque
import hashlib
import math
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QThread, Signal

MODEL_NAME = "face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
MODEL_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/"
             "48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_detection_yunet/" + MODEL_NAME)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def find_model(data_directory: Path | None = None) -> Path | None:
    """The bundled detector model, or a verified copy previously downloaded."""
    candidates = [Path(__file__).resolve().parent / "assets" / MODEL_NAME]
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, Path(sys._MEIPASS) / "cyclop_windows" / "assets" / MODEL_NAME)
    if data_directory is not None:
        candidates.append(data_directory / "models" / MODEL_NAME)
    for path in candidates:
        if path.is_file() and sha256(path) == MODEL_SHA256:
            return path
    return None


def download_model(destination_folder: Path) -> Path:
    """Fetch the MIT-licensed YuNet model (232 KB) and verify its pinned SHA-256."""
    from urllib.request import Request, urlopen
    destination_folder.mkdir(parents=True, exist_ok=True)
    request = Request(MODEL_URL, headers={"User-Agent": "CyclopWindows/0.2"})
    with urlopen(request, timeout=30) as response:
        payload = response.read(2_000_001)
    if hashlib.sha256(payload).hexdigest() != MODEL_SHA256:
        raise RuntimeError("Downloaded face model failed its integrity check")
    path = destination_folder / MODEL_NAME
    path.write_bytes(payload)
    return path


# ---------------------------------------------------------------- features
def pupil_offset(gray_eye):
    """Offset of the darkest blob (the pupil/iris) from the patch centre, in [-1, 1].

    ``gray_eye`` is a small grayscale numpy array centred on an eye landmark.
    Returns (dx, dy) or None when the patch has no usable contrast.
    """
    import numpy as np
    patch = np.asarray(gray_eye, dtype="float32")
    if patch.ndim != 2 or patch.shape[0] < 6 or patch.shape[1] < 6:
        return None
    low, high = np.percentile(patch, 5), np.percentile(patch, 60)
    if high - low < 12:
        return None
    mask = patch <= low + (high - low) * 0.35
    if mask.sum() < 3:
        return None
    ys, xs = np.nonzero(mask)
    weights = (low + (high - low) * 0.35 - patch[ys, xs]) + 1.0
    cx = float((xs * weights).sum() / weights.sum())
    cy = float((ys * weights).sum() / weights.sum())
    half_w, half_h = (patch.shape[1] - 1) / 2, (patch.shape[0] - 1) / 2
    return ((cx - half_w) / half_w, (cy - half_h) / half_h)


def eye_features(face, frame_size, gray=None):
    """Feature vector for one YuNet detection.

    ``face`` holds [x, y, w, h, right eye x, y, left eye x, y, nose x, y,
    mouth right x, y, mouth left x, y, score] in pixels. Positions are mirrored
    so that moving to your left reads as moving left on the screen.
    """
    width, height = frame_size
    x, y, w, h = face[0:4]
    right_eye, left_eye, nose = (face[4], face[5]), (face[6], face[7]), (face[8], face[9])
    interocular = math.hypot(left_eye[0] - right_eye[0], left_eye[1] - right_eye[1]) or 1.0
    mid = ((right_eye[0] + left_eye[0]) / 2, (right_eye[1] + left_eye[1]) / 2)
    face_x = 1 - (x + w / 2) / width   # mirrored
    face_y = (y + h / 2) / height
    size = w / width
    yaw = -(nose[0] - mid[0]) / interocular    # head turn
    pitch = (nose[1] - mid[1]) / interocular   # head nod
    pupils = []
    if gray is not None:
        radius = max(3, int(interocular * 0.22))
        for ex, ey in (right_eye, left_eye):
            ex, ey = int(round(ex)), int(round(ey))
            patch = gray[max(0, ey - radius // 2): ey + radius // 2 + 1, max(0, ex - radius): ex + radius + 1]
            pupils.append(pupil_offset(patch))
    pupil_x = [-p[0] for p in pupils if p is not None]  # mirrored
    pupil_y = [p[1] for p in pupils if p is not None]
    px = sum(pupil_x) / len(pupil_x) if pupil_x else 0.0
    py = sum(pupil_y) / len(pupil_y) if pupil_y else 0.0
    return [face_x, face_y, size, yaw, pitch, px, py]


class GazeCalibrator:
    """Learns features → screen point from mouse-pointer ground truth (ridge regression)."""
    MIN_SAMPLES = 30

    def __init__(self, capacity=600, ridge=0.05):
        self.samples = deque(maxlen=capacity)
        self.ridge = ridge
        self.weights = None
        self.error = None
        self.lock = threading.Lock()

    @staticmethod
    def design(features):
        f = list(features)
        # Bias, linear terms and the two most useful interactions.
        return [1.0] + f + [f[3] * f[5], f[4] * f[6]]

    def add(self, features, target):
        """``target`` is the pointer position normalised to the virtual desktop [0, 1]²."""
        with self.lock:
            self.samples.append((self.design(features), (float(target[0]), float(target[1]))))
            if len(self.samples) >= self.MIN_SAMPLES and len(self.samples) % 10 == 0:
                self._fit()

    def _spread(self):
        import numpy as np
        targets = np.array([t for _, t in self.samples])
        return float(targets.std(axis=0).min()) if len(targets) else 0.0

    def _fit(self):
        import numpy as np
        if self._spread() < 0.06:
            return  # the pointer stayed in one place: nothing to learn yet
        x = np.array([d for d, _ in self.samples], dtype="float64")
        y = np.array([t for _, t in self.samples], dtype="float64")
        # Newer samples count more: posture and lighting drift.
        age = np.arange(len(x))[::-1]
        weight = np.exp(-age / 300.0)
        scale = x.std(axis=0)
        scale[0] = 1.0
        scale[scale < 1e-6] = 1.0
        xs = x / scale
        a = xs.T @ (xs * weight[:, None]) + self.ridge * np.eye(xs.shape[1])
        a[0, 0] -= self.ridge  # do not shrink the bias
        b = xs.T @ (y * weight[:, None])
        try:
            solved = np.linalg.solve(a, b)
        except np.linalg.LinAlgError:
            return
        self.weights = (solved, scale)
        predicted = xs @ solved
        self.error = float(np.sqrt(((predicted - y) ** 2).sum(axis=1)).mean())

    @property
    def calibrated(self):
        return self.weights is not None and self.error is not None and self.error < 0.35

    @property
    def progress(self):
        return min(1.0, len(self.samples) / self.MIN_SAMPLES)

    def predict(self, features):
        import numpy as np
        with self.lock:
            if not self.calibrated:
                return None
            solved, scale = self.weights
            point = (np.array(self.design(features)) / scale) @ solved
        return (min(1.0, max(0.0, float(point[0]))), min(1.0, max(0.0, float(point[1]))))

    def reset(self):
        with self.lock:
            self.samples.clear()
            self.weights = self.error = None


# ---------------------------------------------------------------- capture thread
class FaceTracker(QThread):
    """Reads the webcam at ~10 fps and emits one observation per frame."""
    observation = Signal(object)  # dict or None when no face is visible
    failed = Signal(str)

    def __init__(self, model_path: Path, camera_index=0, parent=None):
        super().__init__(parent)
        self.model_path = model_path
        self.camera_index = camera_index
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            import cv2
        except Exception as exc:
            self.failed.emit(f"Camera support is unavailable: {exc}")
            return
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        capture = cv2.VideoCapture(self.camera_index, backend)
        if not capture.isOpened():
            self.failed.emit("No camera found, or another app is using it")
            return
        try:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            detector = None
            misses = 0
            while not self.stop_event.is_set():
                started = time.monotonic()
                ok, frame = capture.read()
                if not ok or frame is None:
                    misses += 1
                    if misses > 30:
                        self.failed.emit("The camera stopped sending frames")
                        return
                    self.stop_event.wait(0.1)
                    continue
                misses = 0
                height, width = frame.shape[:2]
                scale = 320 / width
                small = cv2.resize(frame, (320, int(round(height * scale))))
                if detector is None:
                    detector = cv2.FaceDetectorYN.create(str(self.model_path), "", (small.shape[1], small.shape[0]), 0.7, 0.3, 50)
                _, faces = detector.detect(small)
                if faces is None or len(faces) == 0:
                    self.observation.emit(None)
                else:
                    face = max(faces, key=lambda f: f[2] * f[3]) / scale  # largest face, full-resolution coords
                    face[14] = face[14] * scale  # keep the score unscaled
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    features = eye_features(face, (width, height), gray)
                    self.observation.emit({"features": features, "face": (features[0], features[1]),
                                           "time": time.monotonic()})
                self.stop_event.wait(max(0.0, 0.1 - (time.monotonic() - started)))
        except Exception as exc:
            self.failed.emit(f"Camera error: {exc}")
        finally:
            capture.release()
