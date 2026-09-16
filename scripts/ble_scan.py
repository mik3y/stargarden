"""List Shelly BLU (BTHome v2) sensors in range, with the address to put in config.

    uv run scripts/ble_scan.py [--all] [--seconds N]

Prints every BTHome advertiser as it is seen: the address (on macOS a
CoreBluetooth UUID, on Linux the MAC), signal strength, name, and the decoded
payload (packet id, motion, encryption). Wave a hand at the sensor and its
motion flag flips to 1. `--all` lists every BLE advertiser, not just BTHome.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stargarden.presence.bthome import BTHOME_SERVICE_UUID, parse_bthome  # noqa: E402


async def scan(seconds: float, everything: bool) -> None:
    from bleak import BleakScanner

    seen: dict[str, float] = {}
    t0 = time.monotonic()

    def on_advertisement(device, advertisement) -> None:
        payload = advertisement.service_data.get(BTHOME_SERVICE_UUID)
        if payload is None and not everything:
            return
        address = device.address.upper()
        name = advertisement.local_name or device.name or ""
        stamp = f"{time.monotonic() - t0:6.1f}s"
        if payload is None:
            if address not in seen:
                print(f"{stamp}  {address}  rssi {advertisement.rssi:4d}  {name}")
            seen[address] = time.monotonic()
            return
        reading = parse_bthome(payload)
        decoded = (
            "not BTHome v2"
            if reading is None
            else (
                "ENCRYPTED (disable encryption in the Shelly app)"
                if reading.encrypted
                else f"packet {reading.packet_id}  motion {int(reading.motion) if reading.motion is not None else '-'}"
            )
        )
        new = "  <-- new" if address not in seen else ""
        seen[address] = time.monotonic()
        print(f"{stamp}  {address}  rssi {advertisement.rssi:4d}  {name:<14} {decoded}  [{payload.hex()}]{new}")

    print(f"scanning for {'all BLE' if everything else 'BTHome'} advertisers for {seconds:.0f}s (ctrl-c to stop)...", flush=True)
    async with BleakScanner(on_advertisement):  # unfiltered: macOS only filters on advertised service UUIDs, not service data
        await asyncio.sleep(seconds)
    if not seen:
        print("nothing seen. is Bluetooth on, and does your terminal have Bluetooth permission (System Settings > Privacy & Security)?")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--all", action="store_true", help="list every BLE advertiser, not just BTHome")
    args = parser.parse_args()
    try:
        asyncio.run(scan(args.seconds, args.all))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
