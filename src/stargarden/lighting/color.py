"""Small color helpers. Colors are (r, g, b) floats in 0..1."""

RGB = tuple[float, float, float]

BLACK: RGB = (0.0, 0.0, 0.0)


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def mix(a: RGB, b: RGB, t: float) -> RGB:
    t = clamp01(t)
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def rgb_to_rgbw(c: RGB) -> tuple[float, float, float, float]:
    """Pull the common component out into a white channel."""
    w = min(c)
    return (c[0] - w, c[1] - w, c[2] - w, w)
