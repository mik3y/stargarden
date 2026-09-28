"""Stargarden: sound and lighting for a nighttime forest installation."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .manifest import Manifest, ManifestError, load_manifest

DEFAULT_CONFIG = Path("configs/dev.toml")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stargarden", description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"config file (default: {DEFAULT_CONFIG})")
    parser.add_argument("--headless", action="store_true", help="no terminal console (for systemd); the web console still serves")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--seed", type=int, help="seed the random generator for reproducible runs")
    args = parser.parse_args(argv)

    from .app import Stargarden
    from .console import Console, install_log_buffer

    buffer = install_log_buffer(args.log_level.upper(), stderr=args.headless)

    try:
        config = load_config(args.config)
    except (ConfigError, OSError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(config.assets_root)
    except ManifestError as e:
        logging.getLogger(__name__).warning("assets: %s; running without audio content", e)
        manifest = Manifest(config.assets_root, (), (), ())

    program = Stargarden(config, manifest, seed=args.seed)
    console = Console(program, buffer)
    background = []
    if config.web.enabled:
        from .web import WebConsole

        background.append(WebConsole(console, config.web).run())
    foreground = None
    if not args.headless:
        from .tui import StargardenApp

        foreground = StargardenApp(console).run_async()
    try:
        asyncio.run(program.run(foreground=foreground, background=background))
    except KeyboardInterrupt:
        pass
    return 0
