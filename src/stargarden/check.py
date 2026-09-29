"""The setup check: corner by corner, a soft tone on that speaker and, on that
bar, dim red, green, blue, white across its columns left to right, a second
each, round and round.

For wiring up the site: it shows which output feeds which speaker, which DMX
address lights which bar, which way round the bar hangs (red is its left end),
and that its white cells answer. Corner N is audio output N (the mixer's FL,
FR, RL, RR in order) and the Nth fixture in the patch. The program is pinned
to OFF while the check runs, so nothing else plays or lights; the colors are
an overlay, exempt from the master fade, so they show at once. Stopping hands
the forced state back to what it was.
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
from .lighting.color import RGB
from .lighting.fixtures import CellKind, Fixture, FixtureFrame

log = logging.getLogger(__name__)

COLORS: tuple[RGB, ...] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0))  # by column, left to right
WHITE_COLUMN = 3  # the column whose white cells light too
LEVEL = 0.3  # dim: enough to tell the color, not to light the trees
STEP_S = 1.0  # per corner
CORNERS = 4
PITCHES_HZ = (330.0, 392.0, 440.0, 523.0)  # rising by corner, so the ear can count along
TONE_S = 0.5
TONE_GAIN = 0.3


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


def columns(fixture: Fixture) -> dict[str, int]:
    """Each cell's column, left to right, from its position in the fixture; white
    cells take the column of the color cells they sit among."""
    xs = sorted({c.position[0] for c in fixture.mode.color_cells}) or [0.5]
    out = {}
    for cell in fixture.mode.cells:
        out[cell.name] = min(range(len(xs)), key=lambda i: abs(xs[i] - cell.position[0]))
    return out


class CheckOverlay:
    """Everything dark but one fixture, showing COLORS across its columns, until told it is done."""

    def __init__(self, patch: Patch) -> None:
        self._columns = [columns(f) for f in patch.fixtures]
        self.fixture: int | None = None
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
                col = self._columns[i][cell.name] % len(COLORS)
                if cell.kind is CellKind.WHITE:
                    state.intensity = LEVEL if col == WHITE_COLUMN else 0.0
                else:
                    state.color, state.intensity = COLORS[col], LEVEL


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
        self._overlay = CheckOverlay(self._patch)
        self._lighting.add_overlay(self._overlay)
        self._task = asyncio.get_running_loop().create_task(self._run(self._overlay))
        log.info("check: on; a tone on each speaker and red/green/blue/white left to right on each bar, corner by corner")

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
                overlay.fixture = k if k < len(self._patch) else None
                if k < CORNERS:
                    self._beep(k)
                await asyncio.sleep(STEP_S)

    def _beep(self, k: int) -> None:
        rate = self._audio.cfg.samplerate
        clip = ClipSource(tone(rate, PITCHES_HZ[k], TONE_S, TONE_GAIN))
        self._audio.mixer.add(Layer.DISCRETES, Voice(f"check:{k + 1}", clip, Channel(k), rate))
