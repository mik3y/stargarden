from pathlib import Path

import pytest

from stargarden.config import AudioMode, ConfigError, SensorRole, load_config

CONFIGS = Path(__file__).resolve().parent.parent / "configs"


def test_dev_config_loads() -> None:
    cfg = load_config(CONFIGS / "dev.toml")
    assert cfg.audio.mode is AudioMode.QUAD and cfg.audio.channel_map == (1, 2, 5, 6)
    assert (cfg.lighting.driver, cfg.lighting.port) == ("enttec_open", "auto")
    assert [f.address for f in cfg.lighting.fixtures] == [1, 39, 77, 115]  # the same four bars as production
    assert cfg.assets_root == (CONFIGS / ".." / "assets-dev")
    assert cfg.schedule.enabled is False
    assert cfg.lightning.states == ("presence",) and cfg.lightning.mean_interval_s == 120
    assert cfg.audio.speakers[2] == (-1.0, -1.0)
    assert (cfg.web.enabled, cfg.web.host, cfg.web.port) == (True, "127.0.0.1", 7710)


def test_production_config_loads() -> None:
    cfg = load_config(CONFIGS / "production.toml")
    assert cfg.presence.source == "ble"
    assert [(f.type, f.mode, f.address) for f in cfg.lighting.fixtures] == [("jolt_bar_fx2", "38ch", a) for a in (1, 39, 77, 115)]
    assert len({f.position for f in cfg.lighting.fixtures}) == 4  # one bar per corner
    assert cfg.presence.sensors[0].role is SensorRole.PLATFORM
    assert cfg.audio.levels.music == 0.9
    assert cfg.lightning.mean_interval_s == 1200 and cfg.lightning.thunder_delay_s == (0.3, 2.5)
    assert cfg.web.host == "0.0.0.0"  # the laptop on the Pi's hotspot reaches the console
    assert cfg.assets_root == Path.home() / "stargarden-assets"  # "~" expands, whoever the service user is


def test_defaults_and_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text("[timers]\nshow_delay_s = 5\n")
    cfg = load_config(path)
    assert cfg.timers.show_delay_s == 5.0
    assert cfg.timers.show_repeat_delay_s == 900.0
    assert cfg.presence.vacancy_timeout_s == 900.0
    assert cfg.lighting.peak == 1.0

    path.write_text("[lighting]\npeak = 1.5\n")
    with pytest.raises(ConfigError, match="lighting.peak"):
        load_config(path)

    path.write_text("[timers]\nshow_dely_s = 5\n")
    with pytest.raises(ConfigError, match="unknown keys"):
        load_config(path)

    path.write_text("[audio]\nchannel_map = [1, 2, 5]\n")
    with pytest.raises(ConfigError, match="channel_map"):
        load_config(path)
    path.write_text("[audio]\nchannel_map = [1, 2, 5, 6]\n")
    assert load_config(path).audio.channel_map == (1, 2, 5, 6)
    path.write_text("[audio]\nmode = 'octo'\n")
    with pytest.raises(ConfigError, match="expected one of"):
        load_config(path)
