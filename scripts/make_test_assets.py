"""Synthesize a small set of stand-in sounds and a manifest into assets-dev/
so the program has something to play without the real (private) content.

    uv run python scripts/make_test_assets.py
"""

import math
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent / "assets-dev"
RATE = 48000
rng = np.random.default_rng(7)


def write_wav(path: Path, data: np.ndarray, rate: int = RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    print(f"wrote {path.relative_to(ROOT.parent)} ({len(data) / rate:.1f}s)")


def lowpass_noise(n: int, cutoff_hz: float, rate: int) -> np.ndarray:
    noise = rng.standard_normal(n).astype(np.float32)
    alpha = 1.0 - math.exp(-2 * math.pi * cutoff_hz / rate)
    out = np.empty_like(noise)
    acc = 0.0
    for i, x in enumerate(noise):
        acc += alpha * (x - acc)
        out[i] = acc
    return out / (np.abs(out).max() or 1.0)


def bed(seconds: float, cutoff: float, rate: int) -> np.ndarray:
    n = int(seconds * rate)
    t = np.arange(n) / rate
    left = lowpass_noise(n, cutoff, rate)
    right = lowpass_noise(n, cutoff, rate)
    swell = 0.6 + 0.4 * np.sin(2 * math.pi * t / 11.0)
    # short loop-friendly fades at both ends
    env = np.minimum(1.0, np.minimum(t, seconds - t) / 0.5)
    return (np.stack([left, right], axis=1) * (swell * env)[:, None] * 0.4).astype(np.float32)


def tone(freqs: list[float], seconds: float, attack: float = 0.02, release: float = 0.3) -> np.ndarray:
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    sig = sum(np.sin(2 * math.pi * f * t) for f in freqs) / len(freqs)
    env = np.minimum(1.0, t / attack) * np.minimum(1.0, (seconds - t) / release)
    return (sig * env).astype(np.float32)


def owl() -> np.ndarray:
    def hoot(f: float, s: float) -> np.ndarray:
        return tone([f, f * 2.01], s)

    gap = np.zeros(int(0.15 * RATE), np.float32)
    return np.concatenate([hoot(330, 0.35), gap, hoot(300, 0.6)])[:, None] * 0.7


def chirp() -> np.ndarray:
    n = int(0.4 * RATE)
    t = np.arange(n) / RATE
    f = 2200 + 1500 * np.sin(2 * math.pi * 6 * t)
    env = np.sin(math.pi * t / 0.4)
    return (np.sin(2 * math.pi * np.cumsum(f) / RATE) * env)[:, None].astype(np.float32) * 0.5


def flap() -> np.ndarray:
    parts = []
    for _ in range(6):
        burst = lowpass_noise(int(0.09 * RATE), 900, RATE) * np.hanning(int(0.09 * RATE))
        parts += [burst, np.zeros(int(0.06 * RATE), np.float32)]
    return np.concatenate(parts)[:, None].astype(np.float32) * 0.6


def music(seconds: float, root: float) -> np.ndarray:
    chords = [[1, 5 / 4, 3 / 2], [9 / 8, 4 / 3, 5 / 3], [5 / 6, 1, 5 / 4], [3 / 4, 1, 3 / 2]]
    beat = 0.5
    out = np.zeros((int(seconds * RATE), 2), np.float32)
    i = 0
    pos = 0
    while pos < len(out):
        chord = chords[(i // 4) % len(chords)]
        f = root * chord[i % 3] * (2 if i % 8 == 7 else 1)
        note = tone([f, f * 2], beat * 1.8, attack=0.01, release=0.6) * 0.35
        pan = 0.5 + 0.4 * math.sin(i * 0.9)
        n = min(len(note), len(out) - pos)
        out[pos : pos + n, 0] += note[:n] * (1 - pan)
        out[pos : pos + n, 1] += note[:n] * pan
        pos += int(beat * RATE)
        i += 1
    t = np.arange(len(out)) / RATE
    env = np.minimum(1.0, np.minimum(t / 2.0, (seconds - t) / 4.0))
    return out * env[:, None]


def main() -> None:
    write_wav(ROOT / "beds" / "night-forest.wav", bed(40, 600, RATE))
    write_wav(ROOT / "beds" / "creek.wav", bed(30, 2500, 44100), rate=44100)  # exercises resampling
    write_wav(ROOT / "discretes" / "owl.wav", owl())
    write_wav(ROOT / "discretes" / "chirp.wav", chirp())
    write_wav(ROOT / "discretes" / "flap.wav", flap())
    write_wav(ROOT / "music" / "drift.wav", music(45, 220))
    write_wav(ROOT / "music" / "lantern.wav", music(40, 165))
    (ROOT / "manifest.toml").write_text(
        """# Synthesized stand-in content (see scripts/make_test_assets.py).

[[beds]]
file = "beds/night-forest.wav"
weight = 2.0

[[beds]]
file = "beds/creek.wav"

[[discretes]]
file = "discretes/owl.wav"
motion = "static"

[[discretes]]
file = "discretes/chirp.wav"
motion = "circle"

[[discretes]]
file = "discretes/flap.wav"
motion = "flyby"
weight = 1.5

[[music]]
file = "music/drift.wav"
title = "Drift"
theme = "aurora"

[[music]]
file = "music/lantern.wav"
title = "Lantern"
"""
    )
    print(f"wrote {ROOT.relative_to(ROOT.parent) / 'manifest.toml'}")


if __name__ == "__main__":
    main()
