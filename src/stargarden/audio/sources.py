"""Sample sources: in-memory clips and disk-streamed files."""

import logging
import queue
import threading
from pathlib import Path

import numpy as np

from .decode import Reader, open_reader
from .dsp import LinearResampler

log = logging.getLogger(__name__)


class Source:
    channels: int

    def read(self, frames: int) -> np.ndarray:
        """Exactly `frames` frames (zero-padded once exhausted)."""
        raise NotImplementedError

    @property
    def finished(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ClipSource(Source):
    def __init__(self, data: np.ndarray, loop: bool = False) -> None:
        self._data = data
        self.channels = data.shape[1]
        self._loop = loop
        self._pos = 0

    @property
    def finished(self) -> bool:
        return not self._loop and self._pos >= len(self._data)

    def read(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, self.channels), dtype=np.float32)
        filled = 0
        while filled < frames and not self.finished:
            n = min(frames - filled, len(self._data) - self._pos)
            out[filled : filled + n] = self._data[self._pos : self._pos + n]
            filled += n
            self._pos += n
            if self._loop and self._pos >= len(self._data):
                self._pos = 0
        return out


class StreamSource(Source):
    """Decodes a file on a background thread into a small queue of blocks so the
    audio callback never touches the disk. Underruns produce silence."""

    def __init__(self, path: Path, samplerate: int, loop: bool = False, blocksize: int = 4096, depth: int = 8) -> None:
        self.path = path
        self._reader: Reader = open_reader(path)
        self.channels = self._reader.channels
        self._loop = loop
        self._blocksize = blocksize
        self._resampler = None
        if self._reader.samplerate != samplerate:
            log.warning("audio: resampling %s from %d to %d Hz", path.name, self._reader.samplerate, samplerate)
            self._resampler = LinearResampler(self._reader.samplerate, samplerate)
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=depth)
        self._pending = np.zeros((0, self.channels), dtype=np.float32)
        self._eof = False
        self._finished = False
        self._underrun_logged = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._fill, name=f"decode:{path.name}", daemon=True)
        self._thread.start()

    def _fill(self) -> None:
        try:
            while not self._stop.is_set():
                block = self._reader.read(self._blocksize)
                if len(block) == 0:
                    if not self._loop:
                        self._put(None)
                        return
                    self._reader.rewind()
                    continue
                if self._resampler is not None:
                    block = self._resampler.process(block)
                if len(block) and not self._put(block):
                    return
        except Exception:
            log.exception("audio: decode failed for %s", self.path)
            self._put(None)
        finally:
            self._reader.close()

    def _put(self, item: np.ndarray | None) -> bool:
        while not self._stop.is_set():
            try:
                self._queue.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    @property
    def finished(self) -> bool:
        return self._finished

    def read(self, frames: int) -> np.ndarray:
        while len(self._pending) < frames and not self._eof:
            try:
                block = self._queue.get_nowait()
            except queue.Empty:
                if not self._underrun_logged:
                    log.warning("audio: underrun streaming %s", self.path.name)
                    self._underrun_logged = True
                break
            if block is None:
                self._eof = True
                break
            self._pending = np.concatenate([self._pending, block])
        out = np.zeros((frames, self.channels), dtype=np.float32)
        n = min(frames, len(self._pending))
        out[:n] = self._pending[:n]
        self._pending = self._pending[n:]
        if self._eof and len(self._pending) == 0:
            self._finished = True
        return out

    def close(self) -> None:
        self._stop.set()
