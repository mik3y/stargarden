import math
import time
from pathlib import Path

import numpy as np
import pytest

from stargarden.audio.dsp import Fader, LinearResampler
from stargarden.audio.mixer import Layer, Mixer, PointPan, Spread, Voice
from stargarden.audio.panner import fold_to_stereo, quad_gains, spread_gains
from stargarden.audio.sources import ClipSource, StreamSource


def test_quad_gains_preserve_power() -> None:
    for x, y in [(0, 0), (-1, 1), (1, -1), (0.3, -0.7), (1, 1)]:
        g = quad_gains(x, y)
        assert math.isclose(float((g**2).sum()), 1.0, abs_tol=1e-6)
    fl, fr, rl, rr = quad_gains(-1, 1)
    assert fl == pytest.approx(1.0) and fr == pytest.approx(0.0) and rl == pytest.approx(0.0)
    front, rear = spread_gains(0.5)
    assert math.isclose(front**2 + rear**2, 1.0)


def test_fold_to_stereo_shape_and_rear_attenuation() -> None:
    quad = np.zeros((4, 4), np.float32)
    quad[0, 0] = 1.0  # FL
    quad[1, 2] = 1.0  # RL
    stereo = fold_to_stereo(quad)
    assert stereo.shape == (4, 2)
    assert stereo[0, 0] > stereo[1, 0] > 0 and stereo[1, 1] == 0


def test_fader_ramps_then_holds() -> None:
    f = Fader(1000, 0.0)
    f.set(1.0, 0.01)  # 10 frames
    a = f.process(4)
    b = f.process(10)
    assert a[-1] == pytest.approx(0.4)
    assert b[5] == pytest.approx(1.0) and b[-1] == 1.0
    assert f.done
    assert (f.process(3) == 1.0).all()


def test_resampler_is_continuous() -> None:
    rs = LinearResampler(44100, 48000)
    t = np.arange(44100) / 44100
    signal = np.sin(2 * math.pi * 5 * t).astype(np.float32)[:, None]
    out = np.concatenate([rs.process(signal[i : i + 1000]) for i in range(0, 44100, 1000)])
    assert abs(len(out) - 48000) < 3
    expected = np.sin(2 * math.pi * 5 * np.arange(len(out)) / 48000)
    assert np.abs(out[:, 0] - expected).max() < 0.01


def test_clip_source_loops_and_finishes() -> None:
    data = np.arange(5, dtype=np.float32)[:, None]
    one_shot = ClipSource(data)
    assert one_shot.read(3)[:, 0].tolist() == [0, 1, 2]
    assert one_shot.read(3)[:, 0].tolist() == [3, 4, 0]
    assert one_shot.finished
    looped = ClipSource(data, loop=True)
    assert looped.read(7)[:, 0].tolist() == [0, 1, 2, 3, 4, 0, 1]
    assert not looped.finished


def test_stream_source_reads_wav_and_resamples(assets: Path) -> None:
    src = StreamSource(assets / "music" / "song.wav", 48000, loop=False, blocksize=512)
    total = 0
    deadline = time.monotonic() + 5
    while not src.finished and time.monotonic() < deadline:
        src.read(256)
        total += 256
        time.sleep(0.001)  # don't outrun the decoder; underruns are counted, not decoded audio
    assert src.finished
    decoded = total - src.underrun_frames
    assert abs(decoded - 4800 * 48000 / 44100) < 300  # length converted to 48k, within a block
    src.close()

    looped = StreamSource(assets / "beds" / "bed.wav", 48000, loop=True, blocksize=512)
    time.sleep(0.05)
    a = looped.read(4800)
    b = looped.read(4800)
    assert not looped.finished
    assert a[0, 0] == pytest.approx(-0.5, abs=1e-3)
    assert b[0, 0] == pytest.approx(-0.5, abs=1e-3)
    looped.close()


def test_mixer_pans_ducks_and_reports_finished() -> None:
    mixer = Mixer(1000, {Layer.BED: 1.0, Layer.DISCRETES: 1.0, Layer.MUSIC: 0.5})
    clip = ClipSource(np.ones((100, 1), np.float32))
    voice = Voice("ping", clip, PointPan(lambda t: (-1.0, 1.0)), 1000)
    finished = []
    voice.on_finished = finished.append
    mixer.add(Layer.DISCRETES, voice)
    out = mixer.render(50)
    assert out[:, 0].mean() == pytest.approx(1.0)  # hard front-left
    assert out[:, 1:].max() < 1e-6
    assert not finished
    mixer.render(50)
    assert finished == [voice]
    assert mixer.voices(Layer.DISCRETES) == []

    bed = Voice("bed", ClipSource(np.ones((1000, 2), np.float32), loop=True), Spread(rear=0.0), 1000)
    mixer.add(Layer.BED, bed)
    assert mixer.render(10)[:, 0].mean() == pytest.approx(1.0)
    mixer.duck(Layer.BED, 0.25, 0.0)
    assert mixer.render(10)[-1, 0] == pytest.approx(0.25)
    mixer.set_level(Layer.BED, 0.0, 0.0)
    assert mixer.render(10)[-1].max() == 0.0


def test_voice_fade_out_finishes() -> None:
    v = Voice("v", ClipSource(np.ones((10_000, 2), np.float32), loop=True), Spread(), 1000)
    v.fade_out(0.01)
    v.render(5)
    assert not v.finished
    v.render(10)
    assert v.finished
