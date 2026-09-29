"""Measure the tempo of show tracks the way the program does.

    uv run scripts/bpm.py FILE...                       # detect each file's BPM
    uv run scripts/bpm.py --config configs/dev.toml     # every music entry in the config's manifest
    uv run scripts/bpm.py --range 60 120 FILE           # fold into a different octave

With --config, each track is reported the way a show would see it: the
manifest's `bpm` override, the cached measurement, or a fresh one (which is
written to the cache, `bpm.json` next to the config's state file; the cache is
per machine, so this seeds a laptop's, not the Pi's). Bare files are always
measured and never cached. If a number is wrong to your ears, put a `bpm =` on
the track's manifest entry.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stargarden.audio.tempo import BPM_RANGE, TempoCache, detect_file_bpm  # noqa: E402
from stargarden.config import load_config  # noqa: E402
from stargarden.manifest import load_manifest  # noqa: E402


def measure(path: Path, lo: float, hi: float) -> tuple[float | None, float]:
    started = time.monotonic()
    bpm = detect_file_bpm(path, lo, hi)
    return bpm, time.monotonic() - started


def report(label: str, bpm: float | None, source: str, took: float | None = None) -> None:
    value = f"{bpm:6.1f} bpm" if bpm is not None else "     — (no measurable tempo)"
    timing = f"  ({took:.1f}s)" if took is not None else ""
    print(f"{value}  {label}  [{source}]{timing}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="*", type=Path, help="audio files to measure")
    parser.add_argument("--config", type=Path, help="measure the config's manifest music instead, using its cache")
    parser.add_argument("--range", nargs=2, type=float, default=BPM_RANGE, metavar=("LO", "HI"), help="fold tempos into [LO, HI)")
    args = parser.parse_args()
    lo, hi = args.range
    if not args.files and args.config is None:
        parser.error("give files to measure, or --config")

    for path in args.files:
        bpm, took = measure(path, lo, hi)
        report(path.name, bpm, "measured", took)

    if args.config is not None:
        config = load_config(args.config)
        manifest = load_manifest(config.assets_root)
        cache = TempoCache(config.state.path.with_name("bpm.json"), config.assets_root)
        for entry in manifest.music:
            if entry.bpm is not None:
                report(entry.title, entry.bpm, "manifest")
                continue
            known, bpm = cache.lookup(entry.path)
            if known:
                report(entry.title, bpm, "cached")
                continue
            bpm, took = measure(entry.path, lo, hi)
            cache.put(entry.path, bpm)
            report(entry.title, bpm, "measured", took)
        print(f"cache: {cache.path}")


if __name__ == "__main__":
    main()
