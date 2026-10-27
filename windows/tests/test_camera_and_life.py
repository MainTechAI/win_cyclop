"""Webcam gaze (without a real camera) and the mascot's behaviours."""
import math
import time

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt

from cyclop_windows.camera import GazeCalibrator, FaceTracker, eye_features, find_model, pupil_offset
from cyclop_windows.model import Model


def eye_patch(dx=0.0, size=(15, 31)):
    height, width = size
    patch = np.full(size, 200.0, dtype="float32")
    cx, cy = (width - 1) / 2 * (1 + dx), (height - 1) / 2
    yy, xx = np.mgrid[0:height, 0:width]
    patch[(xx - cx) ** 2 + (yy - cy) ** 2 <= 9] = 20.0
    return patch


def test_pupil_offset_finds_the_dark_iris():
    assert pupil_offset(eye_patch(0.0))[0] == pytest.approx(0.0, abs=0.08)
    assert pupil_offset(eye_patch(0.5))[0] > 0.3
    assert pupil_offset(eye_patch(-0.5))[0] < -0.3
    assert pupil_offset(np.full((10, 20), 128.0)) is None  # no contrast


def test_eye_features_are_mirrored_to_the_users_view():
    # Face on the right of the camera image = the user's left = screen left.
    face = np.array([400, 100, 120, 150, 430, 160, 490, 160, 460, 190, 440, 220, 480, 220, 0.9], dtype="float32")
    features = eye_features(face, (640, 480))
    assert features[0] < 0.5 and 0 < features[1] < 1 and features[2] == pytest.approx(120 / 640)
    turned = face.copy()
    turned[8] += 20  # nose moved towards the image right
    assert eye_features(turned, (640, 480))[3] < features[3]


def test_calibrator_learns_from_mouse_samples():
    rng = np.random.default_rng(3)
    calibrator = GazeCalibrator()
    true = np.array([[0.1, -0.8], [0.9, 0.1], [0.05, 0.6], [0.4, 0.0], [0.0, 0.3], [0.5, 0.05], [0.0, 0.4]])
    for _ in range(80):
        features = rng.uniform(-1, 1, 7)
        target = np.clip(0.5 + features @ true * 0.3, 0, 1)
        calibrator.add(features, target + rng.normal(0, 0.01, 2))
    assert calibrator.calibrated and calibrator.error < 0.08
    probe = rng.uniform(-1, 1, 7)
    expected = np.clip(0.5 + probe @ true * 0.3, 0, 1)
    estimate = calibrator.predict(probe)
    assert math.dist(estimate, expected) < 0.12
    calibrator.reset()
    assert calibrator.predict(probe) is None


def test_calibrator_does_not_learn_from_a_still_pointer():
    calibrator = GazeCalibrator()
    rng = np.random.default_rng(1)
    for _ in range(60):
        calibrator.add(rng.uniform(-1, 1, 7), (0.5, 0.5))
    assert not calibrator.calibrated


def test_tracker_reports_a_missing_camera_instead_of_crashing(app, tmp_path):
    tracker = FaceTracker(tmp_path / "missing.onnx", camera_index=9)
    errors = []
    tracker.failed.connect(errors.append)
    tracker.run()  # synchronously: no camera 9 exists on test machines
    assert errors


def test_bundled_face_model_loads_when_present():
    path = find_model()
    if path is None:
        pytest.skip("Face model not fetched (CI downloads and verifies it)")
    import cv2
    detector = cv2.FaceDetectorYN.create(str(path), "", (320, 240), 0.7, 0.3, 50)
    _, faces = detector.detect(np.zeros((240, 320, 3), dtype="uint8"))
    assert faces is None or len(faces) == 0


# ---------------------------------------------------------------- behaviours
@pytest.fixture
def mascot(app, tmp_path):
    from cyclop_windows.mascot import MascotWindow
    model = Model(tmp_path)
    window = MascotWindow(model, start_animation=False)
    window.tick()
    yield window
    window.shutdown()
    window.close()


def move_pointer(monkeypatch, mascot, point, seconds=0.06):
    monkeypatch.setattr("cyclop_windows.mascot.QCursor.pos", staticmethod(lambda: QPoint(point)))
    mascot.last_pointer_time = time.monotonic() - seconds
    mascot.pointer_tick()


def test_eye_follows_the_pointer_anywhere_on_screen(mascot, monkeypatch):
    bounds = mascot.screen_bounds()
    far_left = QPoint(bounds.left() + 2, bounds.bottom() - 2)
    move_pointer(monkeypatch, mascot, far_left)
    for _ in range(10):
        mascot.tick()
    assert mascot.target[0] < -0.2 and mascot.target[1] < -0.1, "looks down-left at a far pointer"


def test_startle_dizzy_and_annoyed(mascot, monkeypatch):
    center = mascot.eye_center_global()
    move_pointer(monkeypatch, mascot, center + QPoint(600, 250))
    move_pointer(monkeypatch, mascot, center + QPoint(120, 40), seconds=0.06)  # darts in
    assert time.monotonic() < mascot.startle_until
    for step in range(60):  # circle around the eye
        angle = step / 60 * 2 * math.pi * 2.6
        move_pointer(monkeypatch, mascot, center + QPoint(int(200 * math.cos(angle)), int(200 * math.sin(angle))))
    assert time.monotonic() < mascot.dizzy_until
    annoyed = [mascot.register_click() for _ in range(4)]
    assert annoyed[-1] and time.monotonic() < mascot.annoyed_until


def test_reads_along_while_typing(mascot):
    mascot.last_pointer_move = time.monotonic() - 10
    mascot.last_typing = mascot.reading_start = time.monotonic()
    mascot.tick()
    assert mascot.target[1] == pytest.approx(-0.22)


def test_looks_at_the_user_and_where_they_look(mascot):
    mascot.last_pointer_move = time.monotonic() - 10
    mascot.set_face((0.2, 0.5))
    mascot.tick()
    assert mascot.target[0] < -0.1, "looks towards the user's face on the left"
    bounds = mascot.screen_bounds()
    mascot.set_user_gaze(QPoint(bounds.right() - 5, bounds.bottom() - 5))
    mascot.tick()
    assert mascot.target[0] > 0.1, "follows the estimated gaze to the right"


def test_idle_life_hunts_yawns_and_sleeps(mascot):
    now = time.monotonic()
    import random
    random.seed(4)
    names = set()
    for _ in range(40):
        mascot.choose_behaviour(now)
        names.add(mascot.behaviour)
    assert {"hunt", "look_around", "tilt"} <= names
    mascot.behaviour = None
    mascot.last_pointer_move = mascot.last_typing = now - 1000
    mascot.tick()
    assert mascot.yawn_started is not None
    mascot.next_z = 0
    mascot.tick()
    assert mascot.zs


def test_tuck_hides_the_whole_eye_and_leaves_a_handle(mascot):
    mascot.model.configure("stats_enabled", False)
    mascot.slide.setDuration(1)
    mascot.set_tucked(True)
    mascot.slide.setCurrentTime(mascot.slide.duration())
    eye_bottom = mascot.mapToGlobal(mascot.orb_rect().bottomLeft().toPoint()).y()
    assert eye_bottom <= mascot.screen_bounds().top(), "no half-visible eye"
    handle_top = mascot.mapToGlobal(mascot.handle_rect().topLeft().toPoint()).y()
    assert handle_top >= mascot.screen_bounds().top() - 1
    assert mascot.hits_body(mascot.handle_rect().center())
    assert not mascot.grab().isNull()
