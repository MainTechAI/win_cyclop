"""System monitoring and audio-session volume. Every call degrades to "unavailable"."""
from __future__ import annotations

import sys
import threading

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
        try:
            import psutil
        except ImportError:
            psutil = None
        counters = None
        if sys.platform == "win32":
            from .windows import PerformanceCounters
            counters = PerformanceCounters()
        nvml = _Nvml()
        if psutil:
            psutil.cpu_percent(None)
        try:
            while not self.stop_event.is_set():
                if not self.enabled.wait(0.5):
                    continue
                if self.stop_event.wait(self.interval):
                    break
                values = {"cpu": None, "ram": None, "gpu": None, "temp": None, "details": []}
                if psutil:
                    values["cpu"] = psutil.cpu_percent(None)
                    memory = psutil.virtual_memory()
                    values["ram"] = memory.percent
                    values["details"].append(f"Memory {memory.used / 2**30:.1f} of {memory.total / 2**30:.1f} GB")
                native = counters.sample() if counters else {}
                gpu_util, gpu_temp, gpu_name = nvml.sample()
                values["gpu"] = native.get("gpu", gpu_util)
                if gpu_name:
                    values["details"].append(f"{gpu_name}: {gpu_util:.0f}% · {gpu_temp:.0f}°C" if gpu_temp is not None else gpu_name)
                if "temp" in native:
                    values["temp"] = native["temp"]
                    values["details"].append(f"Thermal zone {native['temp']:.0f}°C")
                elif gpu_temp is not None:
                    values["temp"] = gpu_temp
                    values["details"].append("Temperature reported by the GPU")
                else:
                    values["details"].append("Windows exposes no temperature sensor to apps on this PC")
                self.sample.emit(values)
        finally:
            if counters:
                counters.close()
            nvml.close()


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
        try:
            from pycaw.pycaw import AudioUtilities  # noqa: F401
            self.available = True
        except Exception as exc:
            self.error = f"Volume control unavailable: {exc}"

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
