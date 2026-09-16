import wave
from pathlib import Path

import numpy as np
import pytest


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def write_wav(path: Path, data: np.ndarray, rate: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    """A tiny assets directory with one bed, one discrete, and one track."""
    root = tmp_path / "assets"
    ramp = np.linspace(-0.5, 0.5, 4800, dtype=np.float32)
    write_wav(root / "beds" / "bed.wav", np.stack([ramp, -ramp], axis=1), 48000)
    write_wav(root / "discretes" / "ping.wav", ramp[:, None], 48000)
    write_wav(root / "music" / "song.wav", np.stack([ramp, ramp], axis=1), 44100)
    (root / "manifest.toml").write_text(
        """
[[beds]]
file = "beds/bed.wav"
[[discretes]]
file = "discretes/ping.wav"
motion = "flyby"
[[music]]
file = "music/song.wav"
title = "Song"
theme = "aurora"
[[thunder]]
file = "discretes/ping.wav"
"""
    )
    return root
