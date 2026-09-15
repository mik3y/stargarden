from stargarden.config import SensorRole
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
