from __future__ import annotations

import math

import numpy as np


def normalize_vector(v) -> np.ndarray:
    arr = np.asarray(v, dtype=float)
    norm = float(np.linalg.norm(arr))
    if norm == 0:
        raise ValueError("cannot normalize a zero vector")
    return arr / norm


def deg_to_rad(deg: float) -> float:
    return math.radians(deg)


def rotation_z(deg: float) -> np.ndarray:
    rad = deg_to_rad(deg)
    cos_v = math.cos(rad)
    sin_v = math.sin(rad)
    return np.array(
        [
            [cos_v, -sin_v, 0.0],
            [sin_v, cos_v, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )


def rotation_y(deg: float) -> np.ndarray:
    rad = deg_to_rad(deg)
    cos_v = math.cos(rad)
    sin_v = math.sin(rad)
    return np.array(
        [
            [cos_v, 0.0, sin_v],
            [0.0, 1.0, 0.0],
            [-sin_v, 0.0, cos_v],
        ],
        dtype=float,
    )


def to_list(v) -> list[float]:
    return np.asarray(v, dtype=float).tolist()

