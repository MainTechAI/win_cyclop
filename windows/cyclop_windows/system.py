"""System monitoring and audio-session volume. Every call degrades to "unavailable"."""
from __future__ import annotations

import sys
import threading
import time

from PySide6.QtCore import QThread, Signal


class StatsWorker(QThread):
    """Samples CPU, memory, GPU and temperature off the GUI thread."""
    sample = Signal(object)

    def __init__(self, parent=None, interval=2.0):
        super().__init__(parent)
        self.interval = interval
        self.stop_event = threading.Event()
        self.enabled = threading.Event()

    def stop(self):
        self.stop_event.set()
        self.enabled.set()

    def run(self):
        sampler = StatsSampler()
        try:
            while not self.stop_event.is_set():
                if not self.enabled.wait(0.5):
                    continue
                self.sample.emit(sampler.sample())
                if self.stop_event.wait(self.interval):
                    break
        finally:
            sampler.close()


class StatsSampler:
    """One source of CPU, memory, GPU and temperature readings."""

    def __init__(self):
        try:
            import psutil
            psutil.cpu_percent(None)
        except Exception:
            psutil = None
        self.psutil = psutil
        self.counters = None
        if sys.platform == "win32":
            try:
                from .windows import PerformanceCounters
                self.counters = PerformanceCounters()
            except Exception:
                self.counters = None
        self.nvml = _Nvml()

    def sample(self) -> dict:
        values = {"cpu": None, "ram": None, "gpu": None, "temp": None, "details": []}
        try:
            if self.psutil:
                values["cpu"] = self.psutil.cpu_percent(None)
                memory = self.psutil.virtual_memory()
                values["ram"] = memory.percent
                values["details"].append(f"Memory {memory.used / 2**30:.1f} of {memory.total / 2**30:.1f} GB")
            native = self.counters.sample() if self.counters else {}
            gpu_util, gpu_temp, gpu_name = self.nvml.sample()
            values["gpu"] = native.get("gpu", gpu_util)
            if gpu_name:
                values["details"].append(f"{gpu_name}: {gpu_util:.0f}% · {gpu_temp:.0f}°C" if gpu_temp is not None and gpu_util is not None else gpu_name)
            if "temp" in native:
                values["temp"] = native["temp"]
                values["details"].append(f"Thermal zone {native['temp']:.0f}°C")
            elif gpu_temp is not None:
                values["temp"] = gpu_temp
                values["details"].append("Temperature reported by the GPU")
            else:
                values["details"].append("Windows exposes no temperature sensor to apps on this PC")
        except Exception as exc:  # never let a sensor take the worker down
            values["details"].append(f"Stats error: {exc}")
        return values

    def close(self):
        if self.counters:
            self.counters.close()
        self.nvml.close()


def sample_once(delay=0.5) -> dict:
    """A single reading (used by the startup self-check)."""
    sampler = StatsSampler()
    try:
        time.sleep(delay)
        return sampler.sample()
    finally:
        sampler.close()


class _Nvml:
    """NVIDIA GPU utilisation and temperature, when the NVIDIA driver is present."""
    def __init__(self):
        self.handle = None
        self.name = ""
        try:
            import pynvml
            pynvml.nvmlInit()
            self.pynvml = pynvml
            self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(self.handle)
            self.name = name.decode() if isinstance(name, bytes) else str(name)
        except Exception:
            self.handle = None

    def sample(self):
        if self.handle is None:
            return None, None, ""
        try:
            utilisation = float(self.pynvml.nvmlDeviceGetUtilizationRates(self.handle).gpu)
            temperature = float(self.pynvml.nvmlDeviceGetTemperature(self.handle, self.pynvml.NVML_TEMPERATURE_GPU))
            return utilisation, temperature, self.name
        except Exception:
            return None, None, self.name

    def close(self):
        if self.handle is not None:
            try:
                self.pynvml.nvmlShutdown()
            except Exception:
                pass
            self.handle = None


# ---------------------------------------------------------------- volume
APP_ALIASES = {
    "chrome": "chrome.exe", "msedge": "msedge.exe", "edge": "msedge.exe", "spotify": "spotify.exe",
    "firefox": "firefox.exe", "308046b0af4a39cb": "firefox.exe", "opera": "opera.exe", "brave": "brave.exe",
    "vlc": "vlc.exe", "zunemusic": "microsoft.media.player.exe", "zunevideo": "video.ui.exe",
    "telegram": "telegram.exe", "discord": "discord.exe", "yandex": "browser.exe",
}


def process_for_source(source: str) -> str:
    """Best-effort match of a media session's app id to an audio-session process name."""
    token = source.split("!")[0].lower()
    for alias, process in APP_ALIASES.items():
        if alias in token:
            return process
    stem = token.rsplit("\\", 1)[-1]
    return stem if stem.endswith(".exe") else stem + ".exe" if stem else ""


class Volume:
    """Master output volume and per-app session volume through Windows Core Audio."""

    def __init__(self):
        self.available = False
        self.error = ""
        if sys.platform != "win32":
            self.error = "Volume control is available on Windows"
            return
        # Check that the Core Audio bindings are installed without importing them yet:
        # comtypes is loaded when a volume slider is first shown.
        import importlib.util
        try:
            self.available = importlib.util.find_spec("pycaw") is not None and importlib.util.find_spec("comtypes") is not None
        except (ImportError, ValueError):
            self.available = False
        if not self.available:
            self.error = "Volume control unavailable: pycaw is not installed"

    def _endpoint(self):
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        device = AudioUtilities.GetSpeakers()
        endpoint = getattr(device, "EndpointVolume", None)
        if endpoint is None:
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = cast(interface, POINTER(IAudioEndpointVolume))
        return endpoint

    def master(self) -> float | None:
        if not self.available:
            return None
        try:
            return float(self._endpoint().GetMasterVolumeLevelScalar())
        except Exception:
            return None

    def set_master(self, value: float):
        if self.available:
            try:
                self._endpoint().SetMasterVolumeLevelScalar(max(0.0, min(1.0, value)), None)
            except Exception:
                pass

    def sessions(self) -> list[tuple[str, float]]:
        """(process name, volume) for apps that currently own an audio session."""
        if not self.available:
            return []
        try:
            from pycaw.pycaw import AudioUtilities
            result = {}
            for session in AudioUtilities.GetAllSessions():
                if session.Process is None:
                    continue
                name = session.Process.name()
                if name.lower() not in result:
                    result[name.lower()] = (name, float(session.SimpleAudioVolume.GetMasterVolume()))
            return sorted(result.values(), key=lambda item: item[0].lower())
        except Exception:
            return []

    def set_app(self, process: str, value: float) -> bool:
        if not self.available or not process:
            return False
        try:
            from pycaw.pycaw import AudioUtilities
            changed = False
            for session in AudioUtilities.GetAllSessions():
                if session.Process is not None and session.Process.name().lower() == process.lower():
                    session.SimpleAudioVolume.SetMasterVolume(max(0.0, min(1.0, value)), None)
                    changed = True
            return changed
        except Exception:
            return False
