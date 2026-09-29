"""Console settings that outlive a run: the audio levels, the lighting peak, and
which programs are out of the random rotation.

The config file is the committed, deployed source of defaults; this is the
layer of overrides made from a console, kept in a small JSON file outside the
code directory (`[state] path`, `~/.local/state/stargarden/state.json` by
default) so a deploy's rsync never touches it. Only what was changed is
stored, and disabled programs are stored rather than enabled ones, so a
program added in a later deploy joins the rotation by itself. Delete the file
to go back to the config.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Overrides:
    levels: dict[str, float] = field(default_factory=dict)  # audio layer name → level
    peak: float | None = None
    disabled_themes: set[str] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return not self.levels and self.peak is None and not self.disabled_themes

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.levels:
            out["levels"] = dict(sorted(self.levels.items()))
        if self.peak is not None:
            out["peak"] = self.peak
        if self.disabled_themes:
            out["disabled_themes"] = sorted(self.disabled_themes)
        return out

    @classmethod
    def from_json(cls, data: Any) -> Overrides:
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        levels = data.get("levels", {})
        if not isinstance(levels, dict) or not all(isinstance(k, str) and _is_number(v) for k, v in levels.items()):
            raise ValueError("levels: expected {name: number}")
        peak = data.get("peak")
        if peak is not None and not _is_number(peak):
            raise ValueError("peak: expected a number")
        disabled = data.get("disabled_themes", [])
        if not isinstance(disabled, list) or not all(isinstance(n, str) for n in disabled):
            raise ValueError("disabled_themes: expected a list of names")
        return cls({k: float(v) for k, v in levels.items()}, None if peak is None else float(peak), set(disabled))


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


class StateStore:
    """Reads and writes the overrides file; a missing or unreadable file is empty overrides."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Overrides:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return Overrides()
        except (OSError, ValueError) as e:
            log.warning("state: ignoring %s: %s", self.path, e)
            return Overrides()
        try:
            overrides = Overrides.from_json(data)
        except ValueError as e:
            log.warning("state: ignoring %s: %s", self.path, e)
            return Overrides()
        log.info("state: loaded %s", self.path)
        return overrides

    def save(self, overrides: Overrides) -> None:
        """Write atomically (temp file, then rename), or remove the file when nothing is overridden."""
        if overrides.empty:
            self.clear()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(overrides.to_json(), f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
