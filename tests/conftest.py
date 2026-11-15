import logging
from pathlib import Path

import pytest

from stargarden.config import Config, load_config


@pytest.fixture(autouse=True)
def restore_root_logger():
    """`install_log_buffer` replaces the root logger's handlers and level; put them back after each test."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers, root.level = handlers, level


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """One generic wash on the console driver, a 100 s sunset, and a state file in the test's own directory."""
    path = tmp_path / "cfg.toml"
    path.write_text(
        f"""
[state]
path = "{tmp_path}/state.json"
[sunset]
leg_s = 100
dusk_level = 0.4
[lighting]
driver = "console"
fps = 60
[[lighting.fixtures]]
name = "a"
type = "generic"
mode = "dim_rgbw"
address = 1
[web]
enabled = false
"""
    )
    return load_config(path)
