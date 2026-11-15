"""Stargarden: a permanent sunset on four DMX light bars."""

import argparse
import asyncio
import sys
from pathlib import Path

from .app import Stargarden
from .config import ConfigError, load_config
from .console import Console, install_log_buffer
from .web import WebConsole

DEFAULT_CONFIG = Path("configs/dev.toml")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stargarden", description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"config file (default: {DEFAULT_CONFIG})")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    buffer = install_log_buffer(args.log_level.upper())
    try:
        config = load_config(args.config)
    except (ConfigError, OSError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    program = Stargarden(config)
    console = Console(program, buffer)
    background = [WebConsole(console, config.web).run()] if config.web.enabled else []
    try:
        asyncio.run(program.run(background=background))
    except KeyboardInterrupt:
        pass
    return 0
