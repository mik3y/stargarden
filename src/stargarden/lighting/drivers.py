"""DMX output drivers."""

import logging

from ..config import LightingConfig
from .fixtures import UNIVERSE_SIZE

log = logging.getLogger(__name__)


class DmxDriver:
    name = "dmx"

    def open(self) -> None:
        pass

    def send(self, universe: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class NullDriver(DmxDriver):
    name = "null"

    def send(self, universe: bytes) -> None:
        pass


class ConsoleDriver(DmxDriver):
    """No hardware; keeps the latest frame for the console to inspect."""

    name = "console"

    def __init__(self) -> None:
        self.frame = bytes(UNIVERSE_SIZE)

    def send(self, universe: bytes) -> None:
        self.frame = universe


class EnttecProDriver(DmxDriver):
    """Enttec DMX USB Pro (and compatibles): "Output Only Send DMX" packets."""

    name = "enttec_pro"
    _START, _END, _LABEL_SEND_DMX = 0x7E, 0xE7, 6

    def __init__(self, port: str) -> None:
        self._port = port
        self._serial = None

    def open(self) -> None:
        import serial  # pyserial; imported lazily so dev machines needn't have it working

        self._serial = serial.Serial(self._port, baudrate=57600, timeout=1)
        log.info("dmx: opened %s", self._port)

    def send(self, universe: bytes) -> None:
        if self._serial is None:
            return
        data = b"\x00" + universe  # DMX start code + slots
        header = bytes((self._START, self._LABEL_SEND_DMX, len(data) & 0xFF, len(data) >> 8))
        self._serial.write(header + data + bytes((self._END,)))

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None


def make_driver(cfg: LightingConfig) -> DmxDriver:
    match cfg.driver:
        case "null":
            return NullDriver()
        case "console":
            return ConsoleDriver()
        case "enttec_pro":
            return EnttecProDriver(cfg.port)
    raise ValueError(f"unknown lighting driver {cfg.driver!r}")
