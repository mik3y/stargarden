from pathlib import Path

import pytest

from stargarden.config import ConfigError, load_config

CONFIGS = Path(__file__).resolve().parent.parent / "configs"


def test_dev_config_loads() -> None:
    cfg = load_config(CONFIGS / "dev.toml")
    assert (cfg.lighting.driver, cfg.lighting.port) == ("enttec_open", "auto")
    assert [f.address for f in cfg.lighting.fixtures] == [1, 39, 77, 115]  # the same four bars as production
    assert cfg.sunset.leg_s == 60
    assert (cfg.web.enabled, cfg.web.host, cfg.web.port) == (True, "127.0.0.1", 7710)
    assert cfg.state.path == Path.home() / ".local/state/stargarden/state.json"  # outside the repo, "~" expanded


def test_production_config_loads() -> None:
    cfg = load_config(CONFIGS / "production.toml")
    assert [(f.type, f.mode, f.address) for f in cfg.lighting.fixtures] == [("jolt_bar_fx2", "38ch", a) for a in (1, 39, 77, 115)]
    assert (cfg.sunset.leg_s, cfg.sunset.dusk_level) == (900, 0.35)  # 15 minutes out, 15 back
    assert cfg.web.host == "0.0.0.0"  # a phone on the Pi's hotspot reaches the console


def test_defaults_and_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text("[sunset]\nleg_s = 300\n")
    cfg = load_config(path)
    assert cfg.sunset.leg_s == 300.0 and cfg.sunset.dusk_level == 0.35
    assert cfg.lighting.peak == 1.0

    path.write_text("[state]\npath = 'overrides.json'\n")
    assert load_config(path).state.path == tmp_path / "overrides.json"  # relative to the config file

    for bad, match in (
        ("[lighting]\npeak = 1.5\n", "lighting.peak"),
        ("[sunset]\nleg_s = 1\n", "sunset.leg_s"),
        ("[sunset]\ndusk_level = 0\n", "sunset.dusk_level"),
        ("[sunset]\nleg = 5\n", "unknown keys"),
        ("[audio]\nmode = 'quad'\n", "unknown sections"),  # a config from the forest
    ):
        path.write_text(bad)
        with pytest.raises(ConfigError, match=match):
            load_config(path)
