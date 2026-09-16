import logging

import pytest

from stargarden.config import SensorConfig, SensorRole
from stargarden.presence.ble import BlePresenceSource
from stargarden.presence.bthome import parse_bthome
from stargarden.presence.model import OccupancyModel


def test_platform_latches_and_times_out(clock) -> None:
    m = OccupancyModel(vacancy_timeout_s=100, clock=clock)
    assert not m.occupied
    m.motion(SensorRole.PLATFORM)
    assert m.occupied
    assert m.hold_remaining() == 100
    clock.advance(99)
    assert m.occupied
    clock.advance(2)
    assert not m.occupied
    assert m.hold_remaining() is None


def test_walkway_refreshes_but_does_not_start(clock) -> None:
    m = OccupancyModel(vacancy_timeout_s=100, clock=clock)
    m.motion(SensorRole.WALKWAY)
    assert not m.occupied
    assert m.last_approach == clock.t
    m.motion(SensorRole.PLATFORM)
    clock.advance(90)
    m.motion(SensorRole.WALKWAY)
    clock.advance(90)
    assert m.occupied  # walkway motion extended the hold
    assert m.seconds_since(SensorRole.PLATFORM) == 180


def test_bthome_motion_packet() -> None:
    # device info (v2, unencrypted), packet id 7, battery 100%, illuminance, motion on
    payload = bytes([0x40, 0x00, 0x07, 0x01, 0x64, 0x05, 0x10, 0x27, 0x00, 0x21, 0x01])
    reading = parse_bthome(payload)
    assert reading is not None
    assert reading.packet_id == 7
    assert reading.motion is True
    assert not reading.encrypted

    assert parse_bthome(bytes([0x41, 0x00, 0x01])).encrypted
    assert parse_bthome(bytes([0x20])) is None  # v1
    assert parse_bthome(bytes([0x40, 0x21, 0x00])).motion is False


class _Adv:
    def __init__(self, payload: bytes | None, name: str = "SBMO-003Z", rssi: int = -60) -> None:
        self.service_data = {} if payload is None else {"0000fcd2-0000-1000-8000-00805f9b34fb": payload}
        self.local_name = name
        self.rssi = rssi


class _Device:
    def __init__(self, address: str) -> None:
        self.address = address


def _bthome(packet_id: int, motion: bool) -> bytes:
    return bytes([0x40, 0x00, packet_id, 0x21, int(motion)])  # v2, unencrypted; packet id; motion


@pytest.mark.asyncio
async def test_ble_source_logs_discovery_and_motion(caplog) -> None:
    caplog.set_level(logging.INFO, logger="stargarden.presence.ble")
    model = OccupancyModel(60.0)
    source = BlePresenceSource(model, (SensorConfig(SensorRole.PLATFORM, "aa:bb:cc:dd:ee:01", "platform"),))
    dev = _Device("AA:BB:CC:DD:EE:01")

    source._on_advertisement(dev, _Adv(_bthome(1, False)))
    source._on_advertisement(dev, _Adv(_bthome(1, False)))  # the same packet again: no second discovery line
    assert [r.message for r in caplog.records] == ["ble: found platform sensor platform at AA:BB:CC:DD:EE:01 (rssi -60)"]
    assert not model.occupied

    source._on_advertisement(dev, _Adv(_bthome(2, True)))
    source._on_advertisement(dev, _Adv(_bthome(2, True)))  # rebroadcast of the motion packet counts once
    assert caplog.records[-1].message == "ble: motion at platform sensor platform" and len(caplog.records) == 2
    assert model.occupied

    source._on_advertisement(_Device("11:22:33:44:55:66"), _Adv(_bthome(9, True), name="SBMO-003Z"))
    source._on_advertisement(_Device("11:22:33:44:55:66"), _Adv(_bthome(10, True)))
    unknown = [r.message for r in caplog.records if "unconfigured" in r.message]
    assert unknown == ["ble: unconfigured BTHome device 11:22:33:44:55:66 (SBMO-003Z, rssi -60)"]
    source._on_advertisement(_Device("77:88:99:AA:BB:CC"), _Adv(None))  # not BTHome at all: silent
    assert len(caplog.records) == 3
