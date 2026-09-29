"""The setup check: corner by corner, a soft tone on that speaker and a dim red,
green, blue, white sequence on that bar, round and round.

For wiring up the site: it shows which output feeds which speaker, which DMX
address lights which bar, and that a bar's white cells answer. Corner N is
audio output N (the mixer's FL, FR, RL, RR in order) and the Nth fixture in the
patch. The program is pinned to OFF while the check runs, so nothing else
plays or lights; the colors are an overlay, exempt from the master fade, so
they show at once. Stopping hands the forced state back to what it was.
"""

import asyncio
import logging

import numpy as np

from .audio import AudioEngine, Layer
from .audio.mixer import Spatializer, Voice
from .audio.panner import CHANNELS
from .audio.sources import ClipSource
from .conductor import Conductor, State
from .lighting import LightingEngine, Patch
from .lighting.color import BLACK, RGB
from .lighting.fixtures import CellKind, FixtureFrame

log = logging.getLogger(__name__)

COLORS: tuple[tuple[str, RGB], ...] = (
    ("red", (1.0, 0.0, 0.0)),
    ("green", (0.0, 1.0, 0.0)),
    ("blue", (0.0, 0.0, 1.0)),
    ("white", (1.0, 1.0, 1.0)),
)
LEVEL = 0.3  # dim: enough to tell the color, not to light the trees
STEP_S = 1.5  # per color, so a corner takes six seconds
CORNERS = 4
PITCHES_HZ = (330.0, 392.0, 440.0, 523.0)  # rising by corner, so the ear can count along
TONE_S = 0.6
TONE_GAIN = 0.25


class Channel(Spatializer):
    """A mono source on one of the four outputs only."""

    def __init__(self, index: int) -> None:
        self._index = index

    def apply(self, block: np.ndarray, t0: float, samplerate: int) -> np.ndarray:
        out = np.zeros((len(block), CHANNELS), dtype=np.float32)
        out[:, self._index] = block[:, 0] if block.shape[1] == 1 else block.mean(axis=1)
        return out


def tone(samplerate: int, hz: float, seconds: float, gain: float) -> np.ndarray:
    """A sine with 20 ms ramps, as a mono (n, 1) block."""
    t = np.arange(int(samplerate * seconds)) / samplerate
    env = np.minimum(1.0, np.minimum(t, seconds - t) / 0.02)
    return (gain * np.sin(2 * np.pi * hz * t) * env).astype(np.float32)[:, None]


class CheckOverlay:
    """Everything dark but one fixture in one color, until told it is done."""

    def __init__(self) -> None:
        self.fixture: int | None = None
        self.color: RGB = BLACK
        self.white = False  # the white step also lights the fixture's white cells
        self.done = False

    def finished(self, t: float) -> bool:
        return self.done

    def apply(self, frames: list[FixtureFrame], patch: Patch, t: float) -> None:
        for i, (fixture, frame) in enumerate(zip(patch.fixtures, frames, strict=True)):
            for cell in fixture.mode.cells:
                state = frame[cell.name]
                state.intensity, state.strobe = 0.0, 0.0
                if i != self.fixture:
                    continue
                if cell.kind is CellKind.WHITE:
                    state.intensity = LEVEL if self.white else 0.0
                else:
                    state.color, state.intensity = self.color, LEVEL


class SetupCheck:
    def __init__(self, conductor: Conductor, lighting: LightingEngine, audio: AudioEngine, patch: Patch) -> None:
        self._conductor = conductor
        self._lighting = lighting
        self._audio = audio
        self._patch = patch
        self._task: asyncio.Task | None = None
        self._overlay: CheckOverlay | None = None
        self._restore: State | None = None
        self.corner: int | None = None  # 0-based, while running

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._restore = self._conductor.forced
        self._conductor.force(State.OFF)
        self._overlay = CheckOverlay()
        self._lighting.add_overlay(self._overlay)
        self._task = asyncio.get_running_loop().create_task(self._run(self._overlay))
        log.info("check: on; a tone on each speaker and red/green/blue/white on each bar, corner by corner")

    def stop(self) -> None:
        if not self.running:
            return
        assert self._task is not None and self._overlay is not None
        self._task.cancel()
        self._overlay.done = True
        self._task, self._overlay, self.corner = None, None, None
        self._conductor.force(self._restore)
        log.info("check: off")

    async def _run(self, overlay: CheckOverlay) -> None:
        corners = max(CORNERS, len(self._patch))
        while True:
            for k in range(corners):
                self.corner = k
                fixture = self._patch.fixtures[k].name if k < len(self._patch) else "no fixture"
                log.info("check: corner %d: speaker %d, %s", k + 1, k + 1, fixture)
                for name, color in COLORS:
                    overlay.fixture = k if k < len(self._patch) else None
                    overlay.color, overlay.white = color, name == "white"
                    if k < CORNERS:
                        self._beep(k)
                    await asyncio.sleep(STEP_S)

    def _beep(self, k: int) -> None:
        rate = self._audio.cfg.samplerate
        clip = ClipSource(tone(rate, PITCHES_HZ[k], TONE_S, TONE_GAIN))
        self._audio.mixer.add(Layer.DISCRETES, Voice(f"check:{k + 1}", clip, Channel(k), rate))
