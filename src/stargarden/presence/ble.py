"""Passive BLE scanner feeding Shelly BLU Motion advertisements into the model."""

import asyncio
import logging

from ..config import SensorConfig
from .bthome import BTHOME_SERVICE_UUID, parse_bthome
from .model import OccupancyModel

log = logging.getLogger(__name__)


class BlePresenceSource:
    def __init__(self, model: OccupancyModel, sensors: tuple[SensorConfig, ...]) -> None:
        self._model = model
        self._sensors = {s.address.upper(): s for s in sensors}
        self._last_packet: dict[str, int | None] = {}
        self.last_seen: dict[str, float] = {}

    async def run(self) -> None:
        from bleak import BleakScanner  # imported lazily: needs a BLE stack

        if not self._sensors:
            log.warning("ble: no sensors configured; scanner idle")
            return
        log.info("ble: scanning for %d sensor(s)", len(self._sensors))
        async with BleakScanner(self._on_advertisement, service_uuids=[BTHOME_SERVICE_UUID]):
            while True:
                await asyncio.sleep(3600)

    def _on_advertisement(self, device, advertisement) -> None:
        address = device.address.upper()
        sensor = self._sensors.get(address)
        if sensor is None:
            return
        payload = advertisement.service_data.get(BTHOME_SERVICE_UUID)
        if payload is None:
            return
        reading = parse_bthome(payload)
        if reading is None:
            return
        if reading.encrypted:
            log.warning("ble: %s is broadcasting encrypted BTHome; disable encryption in the Shelly app", address)
            return
        self.last_seen[address] = asyncio.get_event_loop().time()
        if reading.packet_id is not None and reading.packet_id == self._last_packet.get(address):
            return  # same packet rebroadcast
        self._last_packet[address] = reading.packet_id
        if reading.motion:
            log.debug("ble: motion from %s (%s)", sensor.name or address, sensor.role)
            self._model.motion(sensor.role)
