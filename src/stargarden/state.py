"""Console settings that outlive a run: the lighting peak, the sunset's length
and dusk level, the place it is held at, the program showing, the patterns'
tempo, and the pin spots' level and color.

The config file is the committed, deployed source of defaults; this is the
layer of overrides made from the console, kept in a small JSON file outside the
code directory (`[state] path`, `~/.local/state/stargarden/state.json` by
default) so a deploy's rsync never touches it. Only what was changed is
stored. Delete the file to go back to the config.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

NAMES = ("program", "spot_color")  # the overrides that are names; the rest are numbers


@dataclass
class Overrides:
    peak: float | None = None
    leg_s: float | None = None
    dusk_level: float | None = None
    hold: float | None = None  # the place the sunset is held at, 0..1; None while it runs
    tempo: float | None = None
    spot_level: float | None = None
    program: str | None = None  # a dance pattern's name; None for the sunset
    spot_color: str | None = None

    def to_json(self) -> dict[str, float | str]:
        """The overrides that are set."""
        return {name: value for name, value in asdict(self).items() if value is not None}

    @classmethod
    def from_json(cls, data: Any) -> Overrides:
        """Overrides from a parsed file, ignoring names since dropped."""
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        values = {}
        for f in fields(cls):
            value = data.get(f.name)
            if value is None:
                continue
            if f.name in NAMES:
                if not isinstance(value, str):
                    raise ValueError(f"{f.name}: expected a name")
                values[f.name] = value
            elif isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{f.name}: expected a number")
            else:
                values[f.name] = float(value)
        return cls(**values)


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
        data = overrides.to_json()
        if not data:
            self.clear()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
