from pathlib import Path

import pytest

from stargarden.config import ConfigError, FixtureRole, SpotColor, load_config

CONFIGS = Path(__file__).resolve().parent.parent / "configs"


def test_dev_config_loads() -> None:
    cfg = load_config(CONFIGS / "dev.toml")
    assert (cfg.lighting.driver, cfg.lighting.port) == ("enttec_open", "auto")
    assert [f.address for f in cfg.lighting.fixtures] == [1, 39, 77, 115, 161]  # the same rig as production
    assert cfg.sunset.leg_s == 60
    assert (cfg.web.enabled, cfg.web.host, cfg.web.port) == (True, "127.0.0.1", 7710)
    assert cfg.state.path == Path.home() / ".local/state/stargarden/state.json"  # outside the repo, "~" expanded


def test_production_config_loads() -> None:
    cfg = load_config(CONFIGS / "production.toml")
    *bars, spots = cfg.lighting.fixtures
    assert [(f.type, f.mode, f.address, f.role) for f in bars] == [("jolt_bar_fx2", "38ch", a, FixtureRole.BAR) for a in (1, 39, 77, 115)]
    assert (spots.type, spots.mode, spots.address, spots.role) == ("pinspot_q1z", "4ch", 161, FixtureRole.SPOT)  # clear of the bars
    assert (cfg.lighting.tempo_bpm, cfg.lighting.spot_level, cfg.lighting.spot_color) == (100, 1.0, SpotColor.WHITE)
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
        ("[lighting]\ntempo_bpm = 500\n", "lighting.tempo_bpm"),
        ("[lighting]\nspot_color = 'green'\n", "expected one of"),
        ("[[lighting.fixtures]]\nname = 'a'\ntype = 'generic'\naddress = 1\nrole = 'laser'\n", "expected one of"),
        ("[audio]\nmode = 'quad'\n", "unknown sections"),  # a config from the forest
    ):
        path.write_text(bad)
        with pytest.raises(ConfigError, match=match):
            load_config(path)
