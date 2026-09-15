"""Quad spatialization math. Channel order: FL, FR, RL, RR.

Positions are (x, y) with x from -1 (left) to 1 (right) and y from -1 (rear)
to 1 (front); the platform is at the origin.
"""

import math

import numpy as np

FRONT_LEFT, FRONT_RIGHT, REAR_LEFT, REAR_RIGHT = range(4)
CHANNELS = 4

# Stereo simulation of the quad field: rear speakers fold into the front pair
# a little quieter, coefficients chosen so a centered source keeps its power.
STEREO_FOLD = np.array([[0.8, 0.0, 0.6, 0.0], [0.0, 0.8, 0.0, 0.6]], dtype=np.float32)


def quad_gains(x: float, y: float) -> np.ndarray:
    """Equal-power gains for a point source; sum of squares is always 1."""
    px = (max(-1.0, min(1.0, x)) + 1.0) * math.pi / 4  # 0..pi/2
    py = (max(-1.0, min(1.0, y)) + 1.0) * math.pi / 4
    left, right = math.cos(px), math.sin(px)
    rear, front = math.cos(py), math.sin(py)
    return np.array([left * front, right * front, left * rear, right * rear], dtype=np.float32)


def spread_gains(rear_amount: float) -> tuple[float, float]:
    """(front, rear) gains for spreading a stereo pair; 0 = front only, 1 = rear only."""
    a = max(0.0, min(1.0, rear_amount)) * math.pi / 2
    return math.cos(a), math.sin(a)


def fold_to_stereo(quad: np.ndarray) -> np.ndarray:
    return quad @ STEREO_FOLD.T
