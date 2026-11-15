"""The setup check: fixture by fixture, dim red, green, blue, white across its
columns left to right, a second each, round and round.

For wiring up the site: it shows which DMX address lights which fixture, which
way round a bar hangs (red is its left end), and that its white cells answer.
Fixture N is the Nth in the patch. A pin spot has one column, so it shows red.
The colors are an overlay that darkens everything else and is exempt from the
master fade, so they show at once whether the lights are on or off.
"""

import asyncio
import logging

from .lighting import LightingEngine, Patch
from .lighting.color import RGB
from .lighting.fixtures import CellKind, Fixture, FixtureFrame

log = logging.getLogger(__name__)

COLORS: tuple[RGB, ...] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0))  # by column, left to right
WHITE_COLUMN = 3  # the column whose white cells light too
LEVEL = 0.3  # dim: enough to tell the color, not to light the room
STEP_S = 1.0  # per bar


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
    def __init__(self, lighting: LightingEngine, patch: Patch) -> None:
        self._lighting = lighting
        self._patch = patch
        self._task: asyncio.Task | None = None
        self._overlay: CheckOverlay | None = None
        self.bar: int | None = None  # 0-based, while running

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._overlay = CheckOverlay(self._patch)
        self._lighting.add_overlay(self._overlay)
        self._task = asyncio.get_running_loop().create_task(self._run(self._overlay))
        log.info("check: on; red/green/blue/white left to right on each fixture in turn")

    def stop(self) -> None:
        if not self.running:
            return
        assert self._task is not None and self._overlay is not None
        self._task.cancel()
        self._overlay.done = True
        self._task, self._overlay, self.bar = None, None, None
        log.info("check: off")

    async def _run(self, overlay: CheckOverlay) -> None:
        while True:
            for k, fixture in enumerate(self._patch.fixtures):
                self.bar = k
                log.info("check: fixture %d: %s", k + 1, fixture.name)
                overlay.fixture = k
                await asyncio.sleep(STEP_S)
            if not self._patch.fixtures:
                await asyncio.sleep(STEP_S)
