"""Small color helpers. Colors are (r, g, b) floats in 0..1."""

import colorsys
import math

RGB = tuple[float, float, float]

BLACK: RGB = (0.0, 0.0, 0.0)


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def mix(a: RGB, b: RGB, t: float) -> RGB:
    t = clamp01(t)
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def scale(c: RGB, k: float) -> RGB:
    return (clamp01(c[0] * k), clamp01(c[1] * k), clamp01(c[2] * k))


def hsv(h: float, s: float, v: float) -> RGB:
    return colorsys.hsv_to_rgb(h % 1.0, clamp01(s), clamp01(v))


def sample_palette(palette: tuple[RGB, ...], u: float) -> RGB:
    """Sample a cyclic palette at position u in [0, 1) with cosine interpolation."""
    n = len(palette)
    if n == 1:
        return palette[0]
    pos = (u % 1.0) * n
    i = int(pos)
    frac = pos - i
    smooth = 0.5 - 0.5 * math.cos(frac * math.pi)
    return mix(palette[i % n], palette[(i + 1) % n], smooth)


def rgb_to_rgbw(c: RGB) -> tuple[float, float, float, float]:
    """Pull the common component out into a white channel."""
    w = min(c)
    return (c[0] - w, c[1] - w, c[2] - w, w)
