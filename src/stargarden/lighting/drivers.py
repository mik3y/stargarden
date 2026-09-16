"""DMX output drivers."""

import logging
import threading
import time

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


class EnttecOpenDriver(DmxDriver):
    """Enttec Open DMX USB (and other bare FTDI FT232R widgets).

    The widget has no DMX engine of its own: it is an RS-485 transmitter behind
    a plain UART, so the host generates the DMX512 signal itself. Each frame is
    a break (the UART held low), a mark-after-break, and then the start code and
    512 slots at 250 kbaud 8N2. A frame takes ~23 ms on the wire, and fixtures
    expect the stream to keep coming, so a dedicated thread transmits the latest
    universe back to back; `send` only swaps in a new frame. That decouples the
    render loop from the blocking serial I/O and keeps the wire alive (holding
    the last look) if the render loop ever stalls, as the Pro's engine would.

    `port = "auto"` picks the first FTDI FT232R serial port, preferring one that
    names Enttec or DMX. A widget that is missing or unplugged is logged once
    and retried every couple of seconds, so a laptop without one still runs.
    """

    name = "enttec_open"
    BAUD = 250_000
    BREAK_S = 176e-6  # spec minimum 92 µs; sleep granularity only lengthens it
    MAB_S = 12e-6  # mark after break; spec minimum 12 µs
    RETRY_S = 2.0  # reopen interval after a serial error (widget missing or unplugged)
    FTDI_VID, FT232R_PID = 0x0403, 0x6001

    def __init__(self, port: str) -> None:
        self._port = port
        self.port: str | None = None  # the device actually opened
        self._serial = None
        self._frame = bytes(UNIVERSE_SIZE)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failed = False
        self.frames_sent = 0

    def open(self) -> None:
        try:
            self._open_port()
        except Exception:  # keep running; the transmitter thread retries
            self._fail()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dmx-tx", daemon=True)
        self._thread.start()

    def send(self, universe: bytes) -> None:
        self._frame = bytes(universe)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._serial is not None:
            try:
                self._transmit(self._frame)  # whatever was last sent, normally the engine's blackout
            except Exception:  # best effort on the way out
                log.debug("dmx: final frame not sent", exc_info=True)
            self._close_port()

    # -- serial ---------------------------------------------------------------

    def _resolve_port(self) -> str:
        if self._port != "auto":
            return self._port
        import serial
        from serial.tools import list_ports

        found = [p for p in list_ports.comports() if (p.vid, p.pid) == (self.FTDI_VID, self.FT232R_PID)]
        if not found:
            raise serial.SerialException("no FTDI FT232R serial port found (is the widget plugged in?)")

        def rank(p) -> tuple[bool, bool]:
            text = " ".join(filter(None, (p.manufacturer, p.product, p.description))).lower()
            return (not ("enttec" in text or "dmx" in text), not p.device.startswith("/dev/cu."))  # macOS: cu.* over tty.*

        return min(found, key=rank).device

    def _open_port(self) -> None:
        import serial  # pyserial; imported lazily so dev machines needn't have it working

        port = self._resolve_port()
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = self.BAUD
        ser.bytesize = serial.EIGHTBITS
        ser.parity = serial.PARITY_NONE
        ser.stopbits = serial.STOPBITS_TWO
        ser.write_timeout = 1.0
        ser.rts = False  # as OLA does; some clones gate the RS-485 driver on it
        ser.open()
        self._serial = ser
        self.port = ser.port
        log.info("dmx: opened %s (open dmx, %d baud 8N2)", ser.port, self.BAUD)

    def _close_port(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def _transmit(self, frame: bytes) -> None:
        """One DMX frame: break, mark after break, start code, slots; returns once it is on the wire."""
        ser = self._serial
        ser.break_condition = True
        time.sleep(self.BREAK_S)
        ser.break_condition = False
        time.sleep(self.MAB_S)
        ser.write(b"\x00" + frame)  # null start code + slots
        ser.flush()  # wait for the UART to drain, so the next break can't clip this frame
        self.frames_sent += 1

    def _fail(self) -> None:
        if not self._failed:
            log.error("dmx: %s unavailable; retrying every %.0fs", self._port, self.RETRY_S, exc_info=True)
        self._failed = True
        self._close_port()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._serial is None:
                    if self._failed:
                        self._stop.wait(self.RETRY_S)
                        if self._stop.is_set():
                            break
                    self._open_port()
                self._transmit(self._frame)
                self._failed = False
            except Exception:  # serial errors must not kill the transmitter
                self._fail()


class EnttecProDriver(DmxDriver):
    """Enttec DMX USB Pro (and compatibles): "Output Only Send DMX" packets.

    The widget's own engine generates the DMX signal from the last universe it
    was given, so the host just sends snapshots.
    """

    name = "enttec_pro"
    _START, _END, _LABEL_SEND_DMX = 0x7E, 0xE7, 6

    def __init__(self, port: str) -> None:
        self._port = port
        self._serial = None

    def open(self) -> None:
        import serial  # pyserial; imported lazily so dev machines needn't have it working

        self._serial = serial.Serial(self._port, baudrate=57600, timeout=1)
        log.info("dmx: opened %s (usb pro)", self._port)

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
        case "enttec_open":
            return EnttecOpenDriver(cfg.port)
        case "enttec_pro":
            return EnttecProDriver(cfg.port)
    raise ValueError(f"unknown lighting driver {cfg.driver!r}")
