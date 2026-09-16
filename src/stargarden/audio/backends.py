"""Output backends: PortAudio via `sounddevice`, or a silent real-time clock."""

import logging
import threading
import time
from collections.abc import Callable

import numpy as np

from ..config import AudioConfig, AudioMode
from .panner import SpeakerLayout, fold_to_stereo

log = logging.getLogger(__name__)

Render = Callable[[int], np.ndarray]


class AudioBackend:
    name = "audio"

    def start(self, render: Render) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class NullBackend(AudioBackend):
    """Pulls frames at real-time pace and discards them, so playback timing,
    fades, and track-finished events still happen without a sound device."""

    name = "null"

    def __init__(self, samplerate: int, blocksize: int) -> None:
        self._samplerate = samplerate
        self._blocksize = blocksize
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, render: Render) -> None:
        period = self._blocksize / self._samplerate

        def loop() -> None:
            next_t = time.monotonic()
            while not self._stop.is_set():
                render(self._blocksize)
                next_t += period
                delay = next_t - time.monotonic()
                if delay > 0:
                    self._stop.wait(delay)
                else:
                    next_t = time.monotonic()

        self._thread = threading.Thread(target=loop, name="audio:null", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)


class SounddeviceBackend(AudioBackend):
    name = "sounddevice"

    def __init__(self, cfg: AudioConfig) -> None:
        import sounddevice as sd

        self._sd = sd
        self._cfg = cfg
        self._channels = 4 if cfg.mode is AudioMode.QUAD else 2
        self._layout = SpeakerLayout(cfg.speakers)
        self._device = self._resolve_device(cfg.device)
        self._stream = None

    def _resolve_device(self, wanted: str | int | None) -> int | None:
        if wanted is None or wanted == "":
            return None
        devices = self._sd.query_devices()
        if isinstance(wanted, int):
            return wanted
        for i, dev in enumerate(devices):
            if wanted.lower() in dev["name"].lower() and dev["max_output_channels"] > 0:
                return i
        raise ValueError(f"no output device matching {wanted!r}")

    def start(self, render: Render) -> None:
        fold = self._channels == 2

        def callback(outdata: np.ndarray, frames: int, _time, status) -> None:
            if status:
                log.warning("audio: %s", status)
            quad = render(frames)
            outdata[:] = fold_to_stereo(quad) if fold else self._layout.to_outputs(quad)

        self._stream = self._sd.OutputStream(
            samplerate=self._cfg.samplerate,
            blocksize=self._cfg.blocksize,
            channels=self._channels,
            dtype="float32",
            device=self._device,
            callback=callback,
        )
        self._stream.start()
        info = self._sd.query_devices(self._stream.device, "output")
        log.info("audio: %s, %d ch @ %d Hz", info["name"], self._channels, self._cfg.samplerate)

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def make_backend(cfg: AudioConfig) -> AudioBackend:
    if cfg.backend == "null":
        return NullBackend(cfg.samplerate, cfg.blocksize)
    try:
        return SounddeviceBackend(cfg)
    except (ImportError, OSError, ValueError) as e:
        if cfg.backend == "sounddevice":
            raise
        log.warning("audio: no sound device (%s); running silent", e)
        return NullBackend(cfg.samplerate, cfg.blocksize)
