"""Read and change a Shelly BLU Motion's settings over BLE, no Shelly app needed.

    uv run scripts/blu_config.py                       # find the sensor and show its settings
    uv run scripts/blu_config.py --led off --blind-time 30 --sensitivity high
    uv run scripts/blu_config.py --address <uuid or mac> --dump

The settings are plain GATT characteristics in Shelly's BLU service (documented
at shelly-api-docs.shelly.cloud/docs-ble/): readable by anyone, writable only by
a bonded central. To write, first put the sensor in pairing mode: hold its
button for more than 10 seconds (it stays there for a minute). macOS pairs by
itself when the first bonded write is attempted and may show a system prompt;
Linux pairs explicitly through BlueZ. The sensor keeps up to four bonds, so the
phone app and this laptop can both stay paired.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stargarden.presence.bthome import BTHOME_SERVICE_UUID, parse_bthome  # noqa: E402

SHELLY_SERVICE = "de8a5aac-a99b-c315-0c80-60d4cbb51225"
CHAR = {
    "sensitivity": "21b5b57b-da8d-4ea4-baf8-7654a2214650",  # 1 byte: 0 low, 1 medium, 2 high
    "blind_time": "219a1ecc-2567-4378-9dbd-0c97d10630ad",  # 2 bytes: 30..600 s
    "pulse_count": "22f36e64-e682-4fbc-8dd6-a87f6e7b7d92",  # 1 byte: 1..4 movements within 2 s before reporting
    "led": "24f52308-6cc6-4065-acf0-1d4574d9ba0f",  # 1 byte: 0 disables the red motion LED
    "beacon": "cb9e957e-952d-4761-a7e1-4416494a5bfa",  # 1 byte: periodic status packets
    "factory_reset": "b0a7e40f-2b87-49db-801c-eb3686a24bdb",  # write 1 (bonded)
    "sample_bthome": "d52246df-98ac-4d21-be1b-70d5f66a5ddb",  # read: an unencrypted BTHome payload
    "firmware": "00002a26-0000-1000-8000-00805f9b34fb",  # standard Device Information: Firmware Revision String
}
SENSITIVITY = {"low": 0, "medium": 1, "high": 2}
MOTION_MODEL = "SBMO"  # the BLU Motion advertises as SBMO-003Z


async def find(address: str | None, seconds: float):
    from bleak import BleakScanner

    def match(device, advertisement) -> bool:
        if address:
            return device.address.upper() == address.upper()
        name = (advertisement.local_name or device.name or "").upper()
        return name.startswith(MOTION_MODEL) or (
            BTHOME_SERVICE_UUID in advertisement.service_data and SHELLY_SERVICE in advertisement.service_uuids
        )

    print(f"looking for {address or 'a Shelly BLU Motion'} for up to {seconds:.0f}s...", flush=True)
    device = await BleakScanner.find_device_by_filter(match, timeout=seconds)
    if device is None:
        sys.exit("not found. is the sensor awake (press its button once) and within a few meters?")
    print(f"found {device.name or ''} {device.address}")
    return device


def show(values: dict[str, bytes | None]) -> None:
    def u8(b: bytes | None) -> str:
        return "?" if not b else str(b[0])

    sens = values["sensitivity"]
    sens_text = "?" if not sens else {v: k for k, v in SENSITIVITY.items()}.get(sens[0], str(sens[0]))
    blind = values["blind_time"]
    blind_text = "?" if not blind else f"{int.from_bytes(blind, 'little')} s (raw {blind.hex()})"
    fw = values["firmware"]
    sample = values["sample_bthome"]
    reading = parse_bthome(sample) if sample else None
    print(f"  firmware     {fw.decode(errors='replace') if fw else '?'}")
    print(f"  sensitivity  {sens_text}")
    print(f"  blind time   {blind_text}")
    print(f"  pulse count  {u8(values['pulse_count'])}")
    print(f"  motion led   {'on' if values['led'] and values['led'][0] else 'off' if values['led'] else '?'}")
    print(f"  beacon mode  {'on' if values['beacon'] and values['beacon'][0] else 'off' if values['beacon'] else '?'}")
    if reading is not None:
        print(f"  last sample  packet {reading.packet_id}, motion {reading.motion}, encrypted {reading.encrypted}  [{sample.hex()}]")


async def run(args: argparse.Namespace) -> None:
    from bleak import BleakClient

    device = await find(args.address, args.seconds)
    writes: list[tuple[str, bytes]] = []
    if args.sensitivity:
        writes.append(("sensitivity", bytes([SENSITIVITY[args.sensitivity]])))
    if args.blind_time is not None:
        if not 30 <= args.blind_time <= 600:
            sys.exit("blind time must be 30..600 seconds")
        writes.append(("blind_time", args.blind_time.to_bytes(2, "little")))
    if args.pulse_count is not None:
        if not 1 <= args.pulse_count <= 4:
            sys.exit("pulse count must be 1..4")
        writes.append(("pulse_count", bytes([args.pulse_count])))
    if args.led:
        writes.append(("led", bytes([args.led == "on"])))
    if args.beacon:
        writes.append(("beacon", bytes([args.beacon == "on"])))
    if args.factory_reset:
        writes.append(("factory_reset", b"\x01"))

    async with BleakClient(device, timeout=20.0) as client:
        print("connected")
        if args.dump:
            for service in client.services:
                print(f"service {service.uuid}  {service.description}")
                for ch in service.characteristics:
                    print(f"  {ch.uuid}  {','.join(ch.properties):<40} {ch.description}")
        if writes:
            try:
                paired = await client.pair()
                print(f"paired: {paired}")
            except NotImplementedError:
                print("(macOS pairs on the first bonded write; accept the prompt if one appears)")
            for name, data in writes:
                await client.write_gatt_char(CHAR[name], data, response=True)
                print(f"wrote {name} = {data.hex()}")
            if args.factory_reset:
                print("factory reset sent; the sensor drops all bonds and restarts")
                return
        values: dict[str, bytes | None] = {}
        for name in ("firmware", "sensitivity", "blind_time", "pulse_count", "led", "beacon", "sample_bthome"):
            try:
                values[name] = bytes(await client.read_gatt_char(CHAR[name]))
            except Exception as e:  # a characteristic this firmware lacks, or a bonded-only read
                values[name] = None
                if args.dump:
                    print(f"  ({name}: {e})")
        show(values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--address", help="the sensor's address (a CoreBluetooth UUID on macOS, a MAC on Linux); default: first BLU Motion seen"
    )
    parser.add_argument("--seconds", type=float, default=30.0, help="how long to look for the sensor")
    parser.add_argument("--sensitivity", choices=sorted(SENSITIVITY, key=SENSITIVITY.get))
    parser.add_argument("--blind-time", type=int, help="seconds after motion before it can report again, 30..600")
    parser.add_argument("--pulse-count", type=int, help="movements within 2 s before motion is reported, 1..4")
    parser.add_argument("--led", choices=("on", "off"), help="the red LED that flashes on motion")
    parser.add_argument("--beacon", choices=("on", "off"), help="periodic status packets, not only on motion")
    parser.add_argument("--factory-reset", action="store_true", help="restore defaults and drop all bonds")
    parser.add_argument("--dump", action="store_true", help="list every GATT service and characteristic")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
