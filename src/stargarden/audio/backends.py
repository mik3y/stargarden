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
    """PortAudio output. In quad mode the stream is opened with all of the device's
    output channels and the four mixes are placed on the channels named by
    `channel_map` (front pair and surround pair of a 7.1 card, say), the rest
    silent. With no device configured, the first device with enough outputs is
    used, USB devices first; if there is none and the backend is "auto", the
    quad field is folded to stereo on the default device instead of going silent.
    """

    name = "sounddevice"

    def __init__(self, cfg: AudioConfig) -> None:
        import sounddevice as sd

        self._sd = sd
        self._cfg = cfg
        self._layout = SpeakerLayout(cfg.speakers)
        self._slots = tuple(c - 1 for c in cfg.channel_map)  # device channels (0-based) for outputs 1-4
        self.device, self.channels = self._choose(cfg)
        self.fold = self.channels == 2
        info = sd.query_devices(self.device, "output") if self.device is not None else sd.query_devices(kind="output")
        self.device_name: str = info["name"]
        self._stream = None

    def _choose(self, cfg: AudioConfig) -> tuple[int | None, int]:
        """(device index or None for the default, channels to open)."""
        devices = self._sd.query_devices()
        quad = cfg.mode is AudioMode.QUAD
        needed = max(self._slots) + 1 if quad else 2
        if cfg.device not in (None, ""):
            index = self._resolve_device(cfg.device, devices)
            outs = devices[index]["max_output_channels"]
            if outs < needed:
                raise ValueError(f"{devices[index]['name']!r} has {outs} output channel(s); this channel map needs {needed}")
            return index, (outs if quad else 2)
        if not quad:
            return None, 2
        capable = [i for i, d in enumerate(devices) if d["max_output_channels"] >= needed]
        capable.sort(key=lambda i: "usb" not in devices[i]["name"].lower())  # stable: USB first, then device order
        if capable:
            return capable[0], devices[capable[0]]["max_output_channels"]
        if cfg.backend == "sounddevice":
            raise ValueError(f"no output device with {needed} channels for quad; set audio.device or audio.channel_map")
        log.warning("audio: no output device with %d channels; folding quad to stereo on the default device", needed)
        return None, 2

    def _resolve_device(self, wanted: str | int, devices) -> int:
        if isinstance(wanted, int):
            return wanted
        for i, dev in enumerate(devices):
            if wanted.lower() in dev["name"].lower() and dev["max_output_channels"] > 0:
                return i
        raise ValueError(f"no output device matching {wanted!r}")

    def place(self, quad: np.ndarray, out: np.ndarray) -> None:
        """Write the mixer's FL/FR/RL/RR block into an output block of `self.channels` columns."""
        if self.fold:
            out[:] = fold_to_stereo(quad)
        else:
            out.fill(0.0)
            out[:, list(self._slots)] = self._layout.to_outputs(quad)

    def start(self, render: Render) -> None:
        def callback(outdata: np.ndarray, frames: int, _time, status) -> None:
            if status:
                log.warning("audio: %s", status)
            self.place(render(frames), outdata)

        self._stream = self._sd.OutputStream(
            samplerate=self._cfg.samplerate,
            blocksize=self._cfg.blocksize,
            channels=self.channels,
            dtype="float32",
            device=self.device,
            callback=callback,
        )
        self._stream.start()
        if self.fold:
            log.info("audio: %s, stereo @ %d Hz", self.device_name, self._cfg.samplerate)
        else:
            log.info(
                "audio: %s, quad on channels %s of %d @ %d Hz",
                self.device_name,
                list(self._cfg.channel_map),
                self.channels,
                self._cfg.samplerate,
            )

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
