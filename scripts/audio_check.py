"""Find the sound card and put a tone on each of its channels.

    uv run scripts/audio_check.py              # list output devices; mark the one the config picks
    uv run scripts/audio_check.py --tone       # a 1 s tone on each channel of that device in turn
    uv run scripts/audio_check.py --quad       # FL, FR, RL, RR through the config's channel_map and speakers
    uv run scripts/audio_check.py --device USB --tone   # a specific device (name substring or index)

Uses the same device selection and channel placement as the program
(`configs/dev.toml` unless --config), so what sounds right here is what the
program will do.
"""

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stargarden.audio.backends import SounddeviceBackend  # noqa: E402
from stargarden.config import load_config  # noqa: E402

CORNERS = ("front left", "front right", "rear left", "rear right")


def tone(samplerate: int, seconds: float, hz: float) -> np.ndarray:
    t = np.arange(int(samplerate * seconds)) / samplerate
    env = np.minimum(1.0, np.minimum(t, seconds - t) / 0.02)  # 20 ms ramps, no clicks
    return (0.3 * np.sin(2 * np.pi * hz * t) * env).astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", type=Path, default=Path("configs/dev.toml"))
    parser.add_argument("--device", help="name substring or index; default: what the config picks")
    parser.add_argument("--tone", action="store_true", help="tone on each device channel in turn")
    parser.add_argument("--quad", action="store_true", help="tone at each corner through the channel map")
    parser.add_argument("--seconds", type=float, default=1.0)
    args = parser.parse_args()

    import sounddevice as sd

    cfg = load_config(args.config).audio
    if args.device is not None:
        cfg = replace(cfg, device=int(args.device) if args.device.isdigit() else args.device)
    backend = SounddeviceBackend(cfg)

    print("output devices:")
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0:
            mark = "->" if i == backend.device or (backend.device is None and i == sd.default.device[1]) else "  "
            print(f" {mark} [{i:2d}] {dev['name']}  ({dev['max_output_channels']} out, {dev['default_samplerate']:.0f} Hz)")
    how = "stereo fold" if backend.fold else f"quad on channels {list(cfg.channel_map)} of {backend.channels}"
    print(f"config picks: {backend.device_name}  ({how})")

    if not (args.tone or args.quad):
        return
    with sd.OutputStream(device=backend.device, channels=backend.channels, samplerate=cfg.samplerate, dtype="float32") as stream:
        if args.tone:
            for ch in range(backend.channels):
                print(f"  channel {ch + 1} of {backend.channels}", flush=True)
                block = np.zeros((int(cfg.samplerate * args.seconds), backend.channels), np.float32)
                block[:, ch] = tone(cfg.samplerate, args.seconds, 330 * 2 ** (ch / 4))  # rising pitch, channel by channel
                stream.write(block)
                time.sleep(0.2)
        if args.quad:
            for corner in range(4):
                print(f"  {CORNERS[corner]}", flush=True)
                quad = np.zeros((int(cfg.samplerate * args.seconds), 4), np.float32)
                quad[:, corner] = tone(cfg.samplerate, args.seconds, 440.0)
                block = np.zeros((quad.shape[0], backend.channels), np.float32)
                backend.place(quad, block)
                stream.write(block)
                time.sleep(0.2)


if __name__ == "__main__":
    main()
