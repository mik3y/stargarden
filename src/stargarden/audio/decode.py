"""Audio file readers. `soundfile` handles WAV/FLAC/OGG/MP3; a stdlib fallback
reads PCM WAV so a machine without libsndfile can still run the dev assets."""

import wave
from pathlib import Path

import numpy as np


class DecodeError(Exception):
    pass


class Reader:
    samplerate: int
    channels: int

    def read(self, frames: int) -> np.ndarray:
        """Up to `frames` frames as float32 (n, channels); fewer/empty at EOF."""
        raise NotImplementedError

    def rewind(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SoundFileReader(Reader):
    def __init__(self, path: Path) -> None:
        import soundfile

        self._sf = soundfile.SoundFile(str(path))
        self.samplerate = self._sf.samplerate
        self.channels = self._sf.channels

    def read(self, frames: int) -> np.ndarray:
        return self._sf.read(frames, dtype="float32", always_2d=True)

    def rewind(self) -> None:
        self._sf.seek(0)

    def close(self) -> None:
        self._sf.close()


class WaveReader(Reader):
    def __init__(self, path: Path) -> None:
        self._wav = wave.open(str(path), "rb")
        self.samplerate = self._wav.getframerate()
        self.channels = self._wav.getnchannels()
        self._width = self._wav.getsampwidth()

    def read(self, frames: int) -> np.ndarray:
        raw = self._wav.readframes(frames)
        if self._width == 2:
            data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        elif self._width == 4:
            data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
        elif self._width == 3:
            b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
            ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
            data = ints.astype(np.float32) / 8388608.0
        elif self._width == 1:
            data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            raise DecodeError(f"unsupported WAV sample width {self._width}")
        return data.reshape(-1, self.channels)

    def rewind(self) -> None:
        self._wav.rewind()

    def close(self) -> None:
        self._wav.close()


def open_reader(path: Path) -> Reader:
    try:
        return SoundFileReader(path)
    except (ImportError, OSError) as e:
        if path.suffix.lower() == ".wav":
            return WaveReader(path)
        raise DecodeError(f"cannot decode {path}: {e}") from None


def load_clip(path: Path) -> tuple[np.ndarray, int]:
    """Whole file as float32 (n, channels) plus its sample rate."""
    reader = open_reader(path)
    try:
        blocks = []
        while True:
            block = reader.read(1 << 16)
            if len(block) == 0:
                break
            blocks.append(block)
        data = np.concatenate(blocks) if blocks else np.zeros((0, reader.channels), np.float32)
        return data, reader.samplerate
    finally:
        reader.close()
