"""Background work. Workers emit data, never touch widgets."""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import queue
import sys
import threading
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QRunnable, QThread, Signal


class JobSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = JobSignals()

    def run(self):
        try:
            self.signals.result.emit(self.function())
        except Exception as exc:
            self.signals.error.emit(str(exc) or type(exc).__name__)
        finally:
            self.signals.finished.emit()


def fetch_rates():
    # Fixed public endpoint: amounts, clipboard and notes are never transmitted.
    request = Request("https://api.frankfurter.dev/v2/rates?base=EUR", headers={"User-Agent": "CyclopWindows/0.1"})
    with urlopen(request, timeout=15) as response:
        payload = response.read(1_000_001)
    if len(payload) > 1_000_000:
        raise ValueError("Exchange-rate response exceeds size limit")
    rows = json.loads(payload)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Unexpected exchange-rate response")
    rates, dates = {"EUR": 1}, []
    for row in rows:
        code, rate = str(row["quote"]).upper(), float(row["rate"])
        if len(code) == 3 and 0 < rate < 1e12:
            rates[code] = rate
            dates.append(str(row["date"]))
    if len(rates) < 2:
        raise ValueError("No valid exchange rates received")
    return {"rates": rates, "date": min(dates), "fetched_at": datetime.now().timestamp()}


def translate_offline(text, source, target):
    try:
        import argostranslate.translate
    except ImportError as exc:
        raise RuntimeError("Offline translation is not installed. See README: Translation setup.") from exc
    languages = {language.code: language for language in argostranslate.translate.get_installed_languages()}
    if source not in languages or target not in languages:
        raise RuntimeError(f"Install an Argos {source} → {target} model first. See README: Translation setup.")
    translation = languages[source].get_translation(languages[target])
    if translation is None:
        raise RuntimeError(f"No installed {source} → {target} translation model")
    return translation.translate(text)


class MediaWorker(QThread):
    """Owns WinRT objects on one MTA thread, including all transport commands."""
    state = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.commands = queue.Queue(maxsize=20)
        self.stop_event = threading.Event()
        self.enabled = threading.Event()
        self.enabled.set()
        self.last_art_key = None
        self.art = b""

    def command(self, name, value=None):
        try:
            self.commands.put_nowait((name, value))
        except queue.Full:
            pass

    def stop(self):
        self.stop_event.set()

    def run(self):
        if sys.platform != "win32":
            self.state.emit({"available": False, "message": "Windows media sessions are available on Windows 11."})
            return
        try:
            from winrt.runtime import init_apartment, uninit_apartment, ApartmentType
            init_apartment(ApartmentType.MULTI_THREADED)
            try:
                asyncio.run(self.watch())
            finally:
                uninit_apartment()
        except Exception as exc:
            self.error.emit(f"Windows media unavailable: {exc}")

    async def watch(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status
        from winrt.windows.storage.streams import Buffer, InputStreamOptions

        manager = await asyncio.wait_for(Manager.request_async(), 5)
        while not self.stop_event.is_set():
            if not self.enabled.is_set():
                await asyncio.sleep(.25)
                continue
            try:
                session = manager.get_current_session()
                if session is None:
                    self.state.emit({"available": False, "message": "Play something in Spotify, a browser, or another media app."})
                    while not self.commands.empty():
                        self.commands.get_nowait()
                else:
                    while not self.commands.empty():
                        command, value = self.commands.get_nowait()
                        methods = {"play": session.try_toggle_play_pause_async, "next": session.try_skip_next_async, "previous": session.try_skip_previous_async}
                        if command == "seek":
                            operation = session.try_change_playback_position_async(int(value * 10_000_000))
                        elif command in methods:
                            operation = methods[command]()
                        else:
                            continue
                        if not await asyncio.wait_for(operation, 3):
                            self.error.emit("This player declined the requested media control.")
                    properties = await asyncio.wait_for(session.try_get_media_properties_async(), 3)
                    playback = session.get_playback_info()
                    timeline = session.get_timeline_properties()
                    art_key = (session.source_app_user_model_id, properties.title, properties.artist, properties.album_title)
                    if art_key != self.last_art_key:
                        self.art = b""
                        if properties.thumbnail:
                            try:
                                stream = await asyncio.wait_for(properties.thumbnail.open_read_async(), 3)
                                try:
                                    if 0 < stream.size <= 4_000_000:
                                        buffer = await asyncio.wait_for(stream.read_async(Buffer(stream.size), stream.size, InputStreamOptions.READ_AHEAD), 3)
                                        self.art = bytes(buffer)
                                finally:
                                    stream.close()
                            except Exception:
                                self.art = b""
                        self.last_art_key = art_key
                    controls = playback.controls
                    self.state.emit({
                        "available": True, "title": properties.title or "Unknown title", "artist": properties.artist,
                        "album": properties.album_title, "source": session.source_app_user_model_id,
                        "playing": playback.playback_status == Status.PLAYING, "art": self.art,
                        "position": timeline.position.total_seconds(), "duration": timeline.end_time.total_seconds(),
                        "can_seek": controls.is_playback_position_enabled,
                        "can_play": controls.is_play_pause_toggle_enabled,
                        "can_next": controls.is_next_enabled, "can_previous": controls.is_previous_enabled,
                    })
            except Exception as exc:
                self.error.emit(f"Media session changed or is unavailable: {exc}")
            await asyncio.sleep(.5)
