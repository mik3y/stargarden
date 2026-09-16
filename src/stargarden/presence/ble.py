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
        self._unknown: set[str] = set()
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
        payload = advertisement.service_data.get(BTHOME_SERVICE_UUID)
        if payload is None:
            return
        sensor = self._sensors.get(address)
        if sensor is None:
            if address not in self._unknown:  # once per device: the address to put in config
                self._unknown.add(address)
                log.info("ble: unconfigured BTHome device %s (%s, rssi %s)", address, advertisement.local_name or "?", advertisement.rssi)
            return
        reading = parse_bthome(payload)
        if reading is None:
            return
        if reading.encrypted:
            log.warning("ble: %s is broadcasting encrypted BTHome; disable encryption in the Shelly app", address)
            return
        label = f"{sensor.role} sensor {sensor.name or address}"
        if address not in self.last_seen:
            log.info("ble: found %s at %s (rssi %s)", label, address, advertisement.rssi)
        self.last_seen[address] = asyncio.get_event_loop().time()
        if reading.packet_id is not None and reading.packet_id == self._last_packet.get(address):
            return  # same packet rebroadcast
        self._last_packet[address] = reading.packet_id
        if reading.motion:
            log.info("ble: motion at %s", label)
            self._model.motion(sensor.role)
