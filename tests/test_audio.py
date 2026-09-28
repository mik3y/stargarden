import math
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from stargarden.audio.dsp import Fader, LinearResampler
from stargarden.audio.mixer import Layer, Mixer, PointPan, Spread, Voice
from stargarden.audio.panner import SpeakerLayout, fold_to_stereo, quad_gains, spread_gains
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


def test_speaker_layout_reorders_outputs_by_position() -> None:
    quad = np.array([[1.0, 2.0, 3.0, 4.0]], np.float32)  # FL, FR, RL, RR
    assert SpeakerLayout().identity and SpeakerLayout().to_outputs(quad).tolist() == [[1, 2, 3, 4]]
    swapped = SpeakerLayout(((-1, -1), (1, 1), (-1, 1), (1, -1)))  # output 1 is cabled to the rear-left speaker
    assert swapped.to_outputs(quad).tolist() == [[3, 2, 1, 4]]
    with pytest.raises(ValueError, match="corners"):
        SpeakerLayout(((-1, 1), (-1, 1), (-1, -1), (1, -1)))


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
    chunks = []
    for _ in range(40):  # two full loops of the 4800-frame bed, paced like real playback
        chunks.append(looped.read(256))
        time.sleep(0.005)
    data = np.concatenate(chunks)
    assert not looped.finished and looped.underrun_frames == 0
    assert data[0, 0] == pytest.approx(-0.5, abs=1e-3)
    assert data[4799, 0] == pytest.approx(0.5, abs=1e-3) and data[4800, 0] == pytest.approx(-0.5, abs=1e-3)  # seamless wrap
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


class _FakeStream:
    def __init__(self, **kw) -> None:
        self.kw = kw
        self.device = kw["device"]
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        pass


class _FakeSounddevice:
    """Enough of the sounddevice module for the backend: a device list and an OutputStream."""

    def __init__(self, devices: list[tuple[str, int]], default: int = 0) -> None:
        self._devices = [{"name": n, "max_output_channels": c, "default_samplerate": 48000.0} for n, c in devices]
        self._default = default
        self.streams: list[_FakeStream] = []

    def query_devices(self, device=None, kind=None):
        if device is None and kind is None:
            return self._devices
        return self._devices[self._default if device is None else device]

    def OutputStream(self, **kw) -> _FakeStream:  # noqa: N802 - mirrors sounddevice
        stream = _FakeStream(**kw)
        self.streams.append(stream)
        return stream


@pytest.fixture
def fake_sd(monkeypatch: pytest.MonkeyPatch):
    def install(devices: list[tuple[str, int]], default: int = 0) -> _FakeSounddevice:
        fake = _FakeSounddevice(devices, default)
        monkeypatch.setitem(sys.modules, "sounddevice", fake)
        return fake

    return install


def _run_callback(fake: _FakeSounddevice, quad: np.ndarray) -> np.ndarray:
    stream = fake.streams[-1]
    out = np.zeros((quad.shape[0], stream.kw["channels"]), np.float32)
    stream.kw["callback"](out, quad.shape[0], None, None)
    return out


def test_quad_picks_a_usb_card_and_places_the_four_mixes(fake_sd) -> None:
    from stargarden.audio.backends import SounddeviceBackend
    from stargarden.config import AudioConfig, AudioMode

    fake = fake_sd([("MacBook Pro Speakers", 2), ("HDMI", 8), ("USB Sound Device", 8)], default=0)
    backend = SounddeviceBackend(AudioConfig(mode=AudioMode.QUAD, channel_map=(1, 2, 5, 6)))
    assert (backend.device, backend.channels, backend.fold, backend.device_name) == (2, 8, False, "USB Sound Device")
    quad = np.array([[0.1, 0.2, 0.3, 0.4]], np.float32)  # FL, FR, RL, RR
    backend.start(lambda frames: quad)
    assert fake.streams[-1].kw["channels"] == 8 and fake.streams[-1].started
    out = _run_callback(fake, quad)
    assert out[0].tolist() == pytest.approx([0.1, 0.2, 0.0, 0.0, 0.3, 0.4, 0.0, 0.0])  # FL FR on 1-2, RL RR on 5-6
    backend.stop()


def test_quad_falls_back_to_stereo_on_a_laptop(fake_sd, caplog) -> None:
    from stargarden.audio.backends import SounddeviceBackend
    from stargarden.config import AudioConfig, AudioMode

    fake = fake_sd([("MacBook Pro Speakers", 2)])
    backend = SounddeviceBackend(AudioConfig(mode=AudioMode.QUAD, channel_map=(1, 2, 5, 6)))
    assert (backend.device, backend.channels, backend.fold) == (None, 2, True)
    assert "folding quad to stereo" in caplog.text
    backend.start(lambda frames: np.array([[1.0, 0.0, 0.0, 0.0]], np.float32))
    out = _run_callback(fake, np.array([[1.0, 0.0, 0.0, 0.0]], np.float32))
    assert out.shape == (1, 2) and out[0, 0] > 0 and out[0, 1] == 0
    with pytest.raises(ValueError, match="no output device"):
        SounddeviceBackend(AudioConfig(backend="sounddevice", mode=AudioMode.QUAD, channel_map=(1, 2, 5, 6)))


def test_named_device_must_have_the_channels(fake_sd) -> None:
    from stargarden.audio.backends import SounddeviceBackend
    from stargarden.config import AudioConfig, AudioMode

    fake_sd([("Built-in", 2), ("Scarlett 4i4", 4)])
    backend = SounddeviceBackend(AudioConfig(device="scarlett", mode=AudioMode.QUAD))
    assert (backend.device, backend.channels) == (1, 4)
    with pytest.raises(ValueError, match="needs 6"):
        SounddeviceBackend(AudioConfig(device="scarlett", mode=AudioMode.QUAD, channel_map=(1, 2, 5, 6)))
    with pytest.raises(ValueError, match="no output device matching"):
        SounddeviceBackend(AudioConfig(device="motu", mode=AudioMode.QUAD))
