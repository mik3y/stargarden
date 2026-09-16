import time

import pytest

from stargarden.config import LightingConfig
from stargarden.lighting.drivers import ConsoleDriver, EnttecOpenDriver, EnttecProDriver, NullDriver, make_driver
from stargarden.lighting.fixtures import UNIVERSE_SIZE


class FakeSerial:
    """Stands in for pyserial's Serial: records the line and byte traffic."""

    instances: list[FakeSerial] = []
    fail_after: int | None = None  # writes before raising, to simulate an unplugged widget

    def __init__(self, port: str | None = None, **kw) -> None:  # the Pro driver passes its settings to the constructor
        self.port = port
        self.events: list[tuple] = []
        self.is_open = port is not None
        self.writes = 0
        self._break = False
        FakeSerial.instances.append(self)

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False
        self.events.append(("close",))

    @property
    def break_condition(self) -> bool:
        return self._break

    @break_condition.setter
    def break_condition(self, value: bool) -> None:
        self._break = value
        self.events.append(("break", value))

    def write(self, data: bytes) -> int:
        if FakeSerial.fail_after is not None and self.writes >= FakeSerial.fail_after:
            raise OSError("device gone")
        self.writes += 1
        self.events.append(("write", bytes(data)))
        return len(data)

    def flush(self) -> None:
        self.events.append(("flush",))


@pytest.fixture
def fake_serial(monkeypatch: pytest.MonkeyPatch) -> type[FakeSerial]:
    import serial

    FakeSerial.instances = []
    FakeSerial.fail_after = None
    monkeypatch.setattr(serial, "Serial", FakeSerial)
    return FakeSerial


def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def test_make_driver() -> None:
    assert isinstance(make_driver(LightingConfig(driver="null")), NullDriver)
    assert isinstance(make_driver(LightingConfig(driver="console")), ConsoleDriver)
    assert isinstance(make_driver(LightingConfig(driver="enttec_open", port="/dev/x")), EnttecOpenDriver)
    assert isinstance(make_driver(LightingConfig(driver="enttec_pro", port="/dev/x")), EnttecProDriver)
    with pytest.raises(ValueError):
        make_driver(LightingConfig(driver="artnet"))


def test_open_dmx_port_settings(fake_serial: type[FakeSerial]) -> None:
    import serial

    driver = EnttecOpenDriver("/dev/ttyUSB9")
    driver.open()
    try:
        (ser,) = fake_serial.instances
        assert ser.is_open and ser.port == "/dev/ttyUSB9"
        assert (ser.baudrate, ser.bytesize, ser.parity, ser.stopbits) == (250_000, 8, serial.PARITY_NONE, serial.STOPBITS_TWO)
        assert ser.rts is False
    finally:
        driver.close()
    assert not ser.is_open


def test_open_dmx_frames_are_break_mab_startcode_slots(fake_serial: type[FakeSerial]) -> None:
    universe = bytes(range(256)) * 2
    driver = EnttecOpenDriver("/dev/ttyUSB9")
    driver.open()
    driver.send(universe)
    wait_for(lambda: driver.frames_sent >= 3)
    driver.close()
    (ser,) = fake_serial.instances

    writes = [e[1] for e in ser.events if e[0] == "write"]
    assert all(len(w) == 1 + UNIVERSE_SIZE and w[0] == 0 for w in writes)
    assert writes[-EnttecOpenDriver.FINAL_FRAMES :] == [b"\x00" + universe] * EnttecOpenDriver.FINAL_FRAMES  # repeated on close
    assert ser.events[-1] == ("close",)

    # every frame: break asserted, released, then the bytes, drained before the next break
    start = ser.events.index(("write", writes[-1]))
    assert ser.events[start - 2 : start + 2] == [("break", True), ("break", False), ("write", writes[-1]), ("flush",)]
    breaks = [i for i, e in enumerate(ser.events) if e == ("break", True)]
    for i in breaks[1:]:
        assert ser.events[i - 1] == ("flush",)


class FakePort:
    def __init__(self, device: str, vid: int | None, pid: int | None, description: str = "", manufacturer: str | None = None) -> None:
        self.device, self.vid, self.pid, self.description, self.manufacturer, self.product = (
            device,
            vid,
            pid,
            description,
            manufacturer,
            None,
        )


def test_open_dmx_auto_picks_the_enttec_ftdi_port(fake_serial: type[FakeSerial], monkeypatch: pytest.MonkeyPatch) -> None:
    from serial.tools import list_ports

    ports = [
        FakePort("/dev/cu.usbmodem1", 0x2341, 0x0043, "Arduino"),
        FakePort("/dev/tty.usbserial-A1", 0x0403, 0x6001, "FT232R USB UART"),
        FakePort("/dev/cu.usbserial-A1", 0x0403, 0x6001, "FT232R USB UART"),
        FakePort("/dev/tty.usbserial-EN1", 0x0403, 0x6001, "DMX USB", "ENTTEC"),
        FakePort("/dev/cu.usbserial-EN1", 0x0403, 0x6001, "DMX USB", "ENTTEC"),
    ]
    monkeypatch.setattr(list_ports, "comports", lambda: ports)
    driver = EnttecOpenDriver("auto")
    driver.open()
    driver.close()
    assert fake_serial.instances[0].port == "/dev/cu.usbserial-EN1" and driver.port == "/dev/cu.usbserial-EN1"

    monkeypatch.setattr(list_ports, "comports", lambda: ports[:3])
    driver = EnttecOpenDriver("auto")
    driver.open()
    driver.close()
    assert fake_serial.instances[1].port == "/dev/cu.usbserial-A1"


def test_open_dmx_without_widget_keeps_running_and_finds_it_later(
    fake_serial: type[FakeSerial], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from serial.tools import list_ports

    monkeypatch.setattr(EnttecOpenDriver, "RETRY_S", 0.01)
    monkeypatch.setattr(list_ports, "comports", lambda: [])
    driver = EnttecOpenDriver("auto")
    driver.open()  # must not raise: the rest of the program runs without lights
    try:
        driver.send(bytes(UNIVERSE_SIZE))
        time.sleep(0.05)
        assert not fake_serial.instances and driver.frames_sent == 0
        assert sum("unavailable" in r.message for r in caplog.records) == 1  # logged once, not every retry
        monkeypatch.setattr(list_ports, "comports", lambda: [FakePort("/dev/ttyUSB0", 0x0403, 0x6001)])
        wait_for(lambda: driver.frames_sent >= 2)
        assert driver.port == "/dev/ttyUSB0"
    finally:
        driver.close()


def test_open_dmx_keeps_streaming_without_new_frames(fake_serial: type[FakeSerial]) -> None:
    driver = EnttecOpenDriver("/dev/ttyUSB9")
    driver.open()
    try:
        wait_for(lambda: driver.frames_sent >= 5)  # nothing was ever sent; the wire still gets frames
        (ser,) = fake_serial.instances
        assert ser.events.count(("write", bytes(1 + UNIVERSE_SIZE))) >= 5
    finally:
        driver.close()


def test_open_dmx_reopens_after_serial_error(fake_serial: type[FakeSerial], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(EnttecOpenDriver, "RETRY_S", 0.01)
    fake_serial.fail_after = 2
    driver = EnttecOpenDriver("/dev/ttyUSB9")
    driver.open()
    try:
        wait_for(lambda: len(fake_serial.instances) >= 2)
        first = fake_serial.instances[0]
        assert not first.is_open and first.writes == 2
        fake_serial.fail_after = None
        wait_for(lambda: fake_serial.instances[-1].writes >= 2)
    finally:
        driver.close()


@pytest.mark.asyncio
async def test_engine_shutdown_leaves_the_wire_dark(fake_serial: type[FakeSerial]) -> None:
    import asyncio
    import random

    from stargarden.config import FixtureConfig
    from stargarden.lighting import LightingEngine, Patch
    from stargarden.lighting.themes import get_theme

    cfg = LightingConfig(driver="enttec_open", fixtures=(FixtureConfig("bar", "jolt_bar_fx2", 1, "38ch"),))
    engine = LightingEngine(Patch.from_config(cfg), EnttecOpenDriver("/dev/ttyUSB9"), cfg, get_theme("ember-waves"), random.Random(1))
    engine.fade_master(1.0, 0.0)
    task = asyncio.get_running_loop().create_task(engine.run())
    await asyncio.sleep(0.2)
    (ser,) = fake_serial.instances
    assert any(sum(e[1]) > 0 for e in ser.events if e[0] == "write")  # it was lit
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    writes = [e[1] for e in ser.events if e[0] == "write"]
    assert writes[-EnttecOpenDriver.FINAL_FRAMES :] == [bytes(1 + UNIVERSE_SIZE)] * EnttecOpenDriver.FINAL_FRAMES
    assert ser.events[-1] == ("close",) and not ser.is_open


def test_pro_driver_wraps_universe_in_send_dmx_packet(fake_serial: type[FakeSerial]) -> None:
    driver = EnttecProDriver("/dev/ttyUSB9")
    driver.open()
    universe = bytes(UNIVERSE_SIZE)
    driver.send(universe)
    driver.close()
    (ser,) = fake_serial.instances
    (packet,) = [e[1] for e in ser.events if e[0] == "write"]
    assert packet == bytes((0x7E, 6, 0x01, 0x02)) + b"\x00" + universe + bytes((0xE7,))
