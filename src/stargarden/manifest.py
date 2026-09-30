"""Assets manifest: what sounds exist and how they should be played.

Lives at `<assets_root>/manifest.toml`, next to the audio files it references,
so the whole assets directory can be rsync'd to the Pi as a unit.
"""

import random
import tomllib
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class ManifestError(Exception):
    pass


# What the decoder (libsndfile, see audio/decode.py) reads. AAC/M4A is not among them:
# scripts/convert_music.py turns those into MP3.
AUDIO_SUFFIXES = frozenset({".wav", ".wave", ".flac", ".ogg", ".oga", ".opus", ".mp3", ".aif", ".aiff", ".aifc", ".caf", ".w64", ".rf64"})


class DiscreteMotion(StrEnum):
    STATIC = "static"  # plays from one random spot
    FLYBY = "flyby"  # travels across the space
    CIRCLE = "circle"  # arcs around the space


@dataclass(frozen=True)
class BedEntry:
    path: Path
    weight: float = 1.0
    gain: float = 1.0


@dataclass(frozen=True)
class DiscreteEntry:
    path: Path
    weight: float = 1.0
    gain: float = 1.0
    motion: DiscreteMotion = DiscreteMotion.STATIC


@dataclass(frozen=True)
class MusicEntry:
    path: Path
    id: str  # the manifest's `file` value: stable across machines, unlike the absolute path
    title: str
    theme: str | None = None  # show lighting theme; random from the pool if None
    gain: float = 1.0
    bpm: float | None = None  # the track's tempo, when detection gets it wrong; otherwise detected and cached (audio/tempo.py)

    def __post_init__(self) -> None:
        if self.bpm is not None and (isinstance(self.bpm, bool) or not isinstance(self.bpm, int | float) or self.bpm <= 0):
            raise ValueError(f"{self.title}: bpm must be a positive number, got {self.bpm!r}")
        if self.bpm is not None:
            object.__setattr__(self, "bpm", float(self.bpm))


@dataclass(frozen=True)
class Manifest:
    root: Path
    beds: tuple[BedEntry, ...]
    discretes: tuple[DiscreteEntry, ...]
    music: tuple[MusicEntry, ...]
    thunder: tuple[DiscreteEntry, ...] = ()

    def pick_thunder(self, rng: random.Random, avoid: DiscreteEntry | None = None) -> DiscreteEntry | None:
        return _weighted_pick(rng, self.thunder, avoid)

    def pick_bed(self, rng: random.Random, avoid: BedEntry | None = None) -> BedEntry | None:
        return _weighted_pick(rng, self.beds, avoid)

    def pick_discrete(self, rng: random.Random) -> DiscreteEntry | None:
        return _weighted_pick(rng, self.discretes, None)

    def pick_music(self, rng: random.Random, avoid: MusicEntry | None = None, enabled: Collection[str] | None = None) -> MusicEntry | None:
        """A random track, not `avoid` if there is a choice, and only from the `enabled`
        ids when given (the whole list if that leaves nothing)."""
        if not self.music:
            return None
        pool = [m for m in self.music if enabled is None or m.id in enabled] or list(self.music)
        candidates = [m for m in pool if m is not avoid] or pool
        return rng.choice(candidates)

    def track(self, id: str) -> MusicEntry:
        for m in self.music:
            if m.id == id:
                return m
        raise KeyError(f"unknown track {id!r}")


def _weighted_pick(rng: random.Random, entries: tuple, avoid: Any):
    candidates = [e for e in entries if e is not avoid] or list(entries)
    if not candidates:
        return None
    return rng.choices(candidates, weights=[e.weight for e in candidates], k=1)[0]


def _entry(root: Path, raw: dict[str, Any], where: str) -> dict[str, Any]:
    if "file" not in raw:
        raise ManifestError(f"{where}: missing 'file'")
    path = root / raw["file"]
    if not path.exists():
        raise ManifestError(f"{where}: file not found: {path}")
    if path.suffix.lower() not in AUDIO_SUFFIXES:
        raise ManifestError(
            f"{where}: {path.name}: not a format the program can decode ({', '.join(sorted(AUDIO_SUFFIXES))});"
            " scripts/convert_music.py converts m4a to mp3"
        )
    out = {k: v for k, v in raw.items() if k != "file"}
    out["path"] = path
    return out


def load_manifest(root: Path) -> Manifest:
    manifest_path = root / "manifest.toml"
    if not manifest_path.exists():
        raise ManifestError(f"no manifest at {manifest_path}")
    with open(manifest_path, "rb") as f:
        raw = tomllib.load(f)
    if len({m.get("file") for m in raw.get("music", [])}) != len(raw.get("music", [])):
        raise ManifestError(f"{manifest_path}: music: the same file is listed twice")
    try:
        beds = tuple(BedEntry(**_entry(root, b, f"beds[{i}]")) for i, b in enumerate(raw.get("beds", [])))
        discretes = tuple(
            DiscreteEntry(**{**_entry(root, d, f"discretes[{i}]"), "motion": DiscreteMotion(d.get("motion", "static"))})
            for i, d in enumerate(raw.get("discretes", []))
        )
        music = tuple(
            MusicEntry(**{"title": m.get("file", ""), "id": m.get("file", ""), **_entry(root, m, f"music[{i}]")})
            for i, m in enumerate(raw.get("music", []))
        )
        thunder = tuple(
            DiscreteEntry(**{**_entry(root, d, f"thunder[{i}]"), "motion": DiscreteMotion(d.get("motion", "static"))})
            for i, d in enumerate(raw.get("thunder", []))
        )
    except (TypeError, ValueError) as e:
        raise ManifestError(f"{manifest_path}: {e}") from None
    return Manifest(root=root, beds=beds, discretes=discretes, music=music, thunder=thunder)
