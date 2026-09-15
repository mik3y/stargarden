"""Minimal BTHome v2 advertisement parser (what Shelly BLU sensors broadcast).

Only unencrypted payloads are supported. Objects appear in ascending id order;
each id has a fixed length, so we walk the payload with a length table and stop
at the first id we don't know.
"""

from dataclasses import dataclass

BTHOME_SERVICE_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"

_OBJECT_LENGTHS = {
    0x00: 1,  # packet id
    0x01: 1,  # battery %
    0x02: 2,  # temperature
    0x03: 2,  # humidity
    0x05: 3,  # illuminance
    0x0C: 2,  # voltage
    0x21: 1,  # motion
    0x2E: 1,  # humidity (8-bit)
    0x3A: 1,  # button event
    0x3F: 2,  # rotation
    0x45: 2,  # temperature (0.1)
}
_OBJ_PACKET_ID = 0x00
_OBJ_MOTION = 0x21


@dataclass(frozen=True)
class BTHomeReading:
    encrypted: bool
    packet_id: int | None
    motion: bool | None


def parse_bthome(payload: bytes) -> BTHomeReading | None:
    if not payload:
        return None
    info = payload[0]
    encrypted = bool(info & 0x01)
    version = info >> 5
    if version != 2:
        return None
    reading = BTHomeReading(encrypted=encrypted, packet_id=None, motion=None)
    if encrypted:
        return reading
    packet_id = None
    motion = None
    i = 1
    while i < len(payload):
        obj = payload[i]
        length = _OBJECT_LENGTHS.get(obj)
        if length is None or i + 1 + length > len(payload):
            break
        data = payload[i + 1 : i + 1 + length]
        if obj == _OBJ_PACKET_ID:
            packet_id = data[0]
        elif obj == _OBJ_MOTION:
            motion = bool(data[0])
        i += 1 + length
    return BTHomeReading(encrypted=encrypted, packet_id=packet_id, motion=motion)
