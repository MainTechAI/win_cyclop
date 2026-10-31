"""Microphone recording and offline Whisper transcription."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading
import time
import wave

from PySide6.QtCore import QObject, QTimer, Signal

SAMPLE_RATE = 16_000
MODEL_SIZES = {"tiny": "≈75 MB, fastest", "base": "≈145 MB, balanced", "small": "≈480 MB, most accurate"}


def write_wav(path: Path, samples) -> Path:
    """Write mono float32 samples in [-1, 1] as 16-bit PCM."""
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(pcm.tobytes())
    return path


def read_wav(path: Path):
    import numpy as np
    with wave.open(str(path), "rb") as stream:
        if stream.getsampwidth() != 2:
            raise ValueError("Only 16-bit WAV recordings are supported")
        channels, rate = stream.getnchannels(), stream.getframerate()
        data = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype("float32") / 32768
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        positions = np.linspace(0, len(data) - 1, int(len(data) * SAMPLE_RATE / rate))
        data = np.interp(positions, np.arange(len(data)), data).astype("float32")
    return data


class Recorder(QObject):
    """Captures the default microphone. Emits a smoothed level for animations.

    In command mode recording stops automatically after a pause in speech, or
    after ``max_seconds``. Audio is kept in memory until ``finished``.
    """
    level = Signal(float)
    finished = Signal(object)  # numpy array of float32 samples
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stream = None
        self.chunks = []
        self.lock = threading.Lock()
        self.started_at = 0.0
        self.current_level = 0.0
        self.heard_speech = False
        self.quiet_since = None
        self.command_mode = False
        self.max_seconds = 0
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)

    @property
    def recording(self):
        return self.stream is not None

    @property
    def elapsed(self):
        return time.monotonic() - self.started_at if self.recording else 0.0

    def start(self, command_mode=False, max_seconds=0):
        if self.recording:
            return
        try:
            import sounddevice
        except Exception as exc:
            self.failed.emit(f"Microphone support is unavailable: {exc}")
            return
        self.chunks = []
        self.command_mode = command_mode
        self.max_seconds = max_seconds
        self.heard_speech = False
        self.quiet_since = None
        self.current_level = 0.0

        def callback(indata, frames, timing, status):
            block = indata[:, 0].copy()
            with self.lock:
                self.chunks.append(block)
                self.current_level = float((block ** 2).mean() ** 0.5)

        try:
            self.stream = sounddevice.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback, blocksize=800)
            self.stream.start()
        except Exception as exc:
            self.stream = None
            self.failed.emit(f"Could not open the microphone: {exc}")
            return
        self.started_at = time.monotonic()
        self.timer.start()

    def tick(self):
        with self.lock:
            level = self.current_level
        self.level.emit(min(1.0, level * 12))
        if self.command_mode:
            speaking = level > 0.02
            if speaking:
                self.heard_speech = True
                self.quiet_since = None
            elif self.heard_speech:
                self.quiet_since = self.quiet_since or time.monotonic()
                if time.monotonic() - self.quiet_since > 1.1:
                    self.stop()
                    return
            elif self.elapsed > 5:
                self.stop()
                return
        if self.max_seconds and self.elapsed >= self.max_seconds:
            self.stop()

    def stop(self):
        if not self.recording:
            return
        import numpy as np
        self.timer.stop()
        try:
            self.stream.stop()
            self.stream.close()
        finally:
            self.stream = None
        with self.lock:
            samples = np.concatenate(self.chunks) if self.chunks else np.zeros(0, dtype="float32")
            self.chunks = []
        self.level.emit(0.0)
        self.finished.emit(samples)

    def cancel(self):
        if self.recording:
            self.timer.stop()
            try:
                self.stream.stop()
                self.stream.close()
            finally:
                self.stream = None
            self.chunks = []
            self.level.emit(0.0)


class Transcriber:
    """Lazy faster-whisper model, cached per size. Runs on worker threads only."""
    _lock = threading.Lock()
    _models: dict[str, object] = {}
    _last_used = 0.0
    _active = 0          # transcriptions in progress: their model must not be released

    @classmethod
    def available(cls) -> bool:
        """Whether speech recognition is installed, without loading it (it costs ~40 MB of RAM
        and a second of start-up; it is imported only when you first record or speak)."""
        import importlib.util
        try:
            return importlib.util.find_spec("faster_whisper") is not None
        except (ImportError, ValueError):
            return False

    @classmethod
    def release_idle(cls, idle_seconds=300) -> bool:
        """Free the speech model's memory (hundreds of MB) after a few unused minutes.
        The next voice command or transcription loads it again."""
        # Never wait here: this runs on the GUI thread, and the lock is held while a model
        # loads (the first time that includes a download). If it is busy, try next minute.
        if not cls._lock.acquire(blocking=False):
            return False
        try:
            if not cls._models or cls._active or time.monotonic() - cls._last_used < idle_seconds:
                return False
            cls._models.clear()
        finally:
            cls._lock.release()
        import gc
        gc.collect()
        return True

    @classmethod
    def transcribe(cls, samples, model_dir: Path, size="base", language="auto") -> str:
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise RuntimeError("Speech recognition is not installed. Run: pip install -e .[speech]") from exc
        if len(samples) < SAMPLE_RATE * 0.3:
            return ""
        with cls._lock:
            model = cls._models.get(size)
            if model is None:
                model_dir.mkdir(parents=True, exist_ok=True)
                model = WhisperModel(size, device="cpu", compute_type="int8", download_root=str(model_dir))
                cls._models[size] = model
            cls._active += 1
        try:
            segments, _info = model.transcribe(samples, language=None if language == "auto" else language,
                                               beam_size=1, vad_filter=False, condition_on_previous_text=False)
            return " ".join(segment.text.strip() for segment in segments).strip()
        finally:
            with cls._lock:
                cls._active -= 1
                cls._last_used = time.monotonic()


def recording_path(directory: Path) -> Path:
    return directory / "recordings" / f"Recording-{datetime.now():%Y%m%d-%H%M%S}.wav"
