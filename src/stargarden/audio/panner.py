"""Quad spatialization math. Channel order: FL, FR, RL, RR.

Positions are (x, y) with x from -1 (left) to 1 (right) and y from -1 (rear)
to 1 (front); the platform is at the origin.
"""

import math

import numpy as np

FRONT_LEFT, FRONT_RIGHT, REAR_LEFT, REAR_RIGHT = range(4)
CHANNELS = 4
CORNERS = ((-1.0, 1.0), (1.0, 1.0), (-1.0, -1.0), (1.0, -1.0))  # canonical FL, FR, RL, RR positions

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


class SpeakerLayout:
    """Maps the mixer's canonical FL/FR/RL/RR columns onto output channels by
    where each output's speaker actually stands."""

    def __init__(self, positions: tuple[tuple[float, float], ...] = CORNERS) -> None:
        if len(positions) != CHANNELS:
            raise ValueError(f"expected {CHANNELS} speaker positions, got {len(positions)}")
        # for each output channel, the canonical corner nearest its speaker
        self.columns = tuple(min(range(CHANNELS), key=lambda c: math.dist(CORNERS[c], pos)) for pos in positions)
        if len(set(self.columns)) != CHANNELS:
            raise ValueError(f"speaker positions {positions} do not cover the four corners")
        self.identity = self.columns == tuple(range(CHANNELS))

    def to_outputs(self, quad: np.ndarray) -> np.ndarray:
        return quad if self.identity else quad[:, self.columns]
