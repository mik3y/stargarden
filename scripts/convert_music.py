"""Convert the m4a tracks in a music directory to mp3, next to the originals.

    uv run scripts/convert_music.py                      # every .m4a in assets-dev/music/ → .mp3
    uv run scripts/convert_music.py --delete             # and remove each .m4a once its .mp3 is written
    uv run scripts/convert_music.py --manifest           # also print [[music]] entries for the new files
    uv run scripts/convert_music.py some/other/dir       # another directory
    uv run scripts/convert_music.py --dry-run            # show what would run

Needs ffmpeg on the PATH (`brew install ffmpeg`). Encodes with LAME at VBR
quality 1 (about 220 kbps), keeping the tags; an existing .mp3 is left alone
unless --force. The program's decoder (libsndfile) reads mp3 but not m4a,
which is why the library is mp3.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "assets-dev" / "music"


def ffmpeg_command(src: Path, dst: Path, quality: int) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-q:a",
        str(quality),
        str(dst),
    ]


def title_of(path: Path) -> str:
    """The track's title tag (with the artist when there is one), or its stem."""
    if shutil.which("ffprobe") is None:
        return path.stem
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format_tags=title,artist", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        tags = {k.lower(): v for k, v in json.loads(out).get("format", {}).get("tags", {}).items()}
    except (subprocess.CalledProcessError, ValueError):
        return path.stem
    title = tags.get("title", "").strip() or path.stem
    artist = tags.get("artist", "").strip()
    return f"{title} ({artist})" if artist else title


def manifest_entry(directory: Path, mp3: Path) -> str:
    """A [[music]] entry for the manifest, with the path relative to the assets root (the directory's parent)."""
    rel = mp3.relative_to(directory.parent).as_posix() if mp3.is_relative_to(directory.parent) else mp3.name
    title = title_of(mp3).replace('"', '\\"')
    return f'[[music]]\nfile = "{rel}"\ntitle = "{title}"\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("directory", nargs="?", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--quality", type=int, default=1, help="LAME VBR quality, 0 (best) to 9; default 1")
    parser.add_argument("--force", action="store_true", help="re-encode even when the .mp3 exists")
    parser.add_argument("--delete", action="store_true", help="remove each .m4a after its .mp3 is written")
    parser.add_argument("--manifest", action="store_true", help="print [[music]] entries for the converted files")
    parser.add_argument("--dry-run", action="store_true", help="print the commands instead of running them")
    args = parser.parse_args()

    if not args.directory.is_dir():
        sys.exit(f"not a directory: {args.directory}")
    sources = sorted(p for p in args.directory.iterdir() if p.suffix.lower() == ".m4a")
    if not sources:
        print(f"no .m4a files in {args.directory}")
        return
    if not args.dry_run and shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on the PATH (brew install ffmpeg)")

    converted: list[Path] = []
    failed = 0
    for src in sources:
        dst = src.with_suffix(".mp3")
        if dst.exists() and not args.force:
            print(f"skip     {dst.name} (exists; --force to redo)")
            converted.append(dst)
            continue
        command = ffmpeg_command(src, dst, args.quality)
        if args.dry_run:
            print(" ".join(f'"{c}"' if " " in c else c for c in command))
            continue
        print(f"encode   {src.name} → {dst.name}", flush=True)
        result = subprocess.run(command)
        if result.returncode != 0 or not dst.exists():
            print(f"FAILED   {src.name}", file=sys.stderr)
            failed += 1
            continue
        converted.append(dst)
        if args.delete:
            src.unlink()
            print(f"removed  {src.name}")

    if args.manifest and converted:
        print("\n# manifest.toml entries; adjust the titles and add theme = / bpm = as wanted\n")
        print("\n".join(manifest_entry(args.directory, mp3) for mp3 in converted))
    if failed:
        sys.exit(f"{failed} file(s) failed")


if __name__ == "__main__":
    main()
