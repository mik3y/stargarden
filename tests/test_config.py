from pathlib import Path

import pytest

from stargarden.config import AudioMode, ConfigError, SensorRole, load_config

CONFIGS = Path(__file__).resolve().parent.parent / "configs"


def test_dev_config_loads() -> None:
    cfg = load_config(CONFIGS / "dev.toml")
    assert cfg.audio.mode is AudioMode.STEREO
    assert (cfg.lighting.driver, cfg.lighting.port) == ("enttec_open", "auto")
    assert len(cfg.lighting.fixtures) == 5
    assert (cfg.lighting.fixtures[0].type, cfg.lighting.fixtures[0].mode) == ("generic", "dim_rgbw")
    assert (cfg.lighting.fixtures[4].type, cfg.lighting.fixtures[4].mode) == ("jolt_bar_fx2", "38ch")
    assert cfg.lighting.fixtures[0].position == (-0.8, 0.8)
    assert cfg.assets_root == (CONFIGS / ".." / "assets-dev")
    assert cfg.schedule.enabled is False
    assert cfg.lightning.states == ("presence",) and cfg.lightning.mean_interval_s == 120
    assert cfg.audio.speakers[2] == (-1.0, -1.0)


def test_production_config_loads() -> None:
    cfg = load_config(CONFIGS / "production.toml")
    assert cfg.presence.source == "ble"
    assert cfg.presence.sensors[0].role is SensorRole.PLATFORM
    assert cfg.audio.levels.music == 0.9
    assert cfg.lightning.mean_interval_s == 1200 and cfg.lightning.thunder_delay_s == (0.3, 2.5)


def test_defaults_and_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text("[timers]\nshow_delay_s = 5\n")
    cfg = load_config(path)
    assert cfg.timers.show_delay_s == 5.0
    assert cfg.timers.show_repeat_delay_s == 900.0
    assert cfg.presence.vacancy_timeout_s == 900.0

    path.write_text("[timers]\nshow_dely_s = 5\n")
    with pytest.raises(ConfigError, match="unknown keys"):
        load_config(path)

    path.write_text("[audio]\nmode = 'octo'\n")
    with pytest.raises(ConfigError, match="expected one of"):
        load_config(path)
