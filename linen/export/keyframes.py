"""Pick which sampled frames actually need to become keyframes.

A 60 fps, ten-second take is 600 frames; written out verbatim that is ~9 000
poses on an R15 rig, which loads slowly in the Animation Editor and is
miserable to hand-tweak afterwards.  Roblox interpolates between keyframes
anyway, so we keep only the frames the interpolation cannot reproduce.

The algorithm is Ramer-Douglas-Peucker adapted to rotations: assume a straight
slerp between the two endpoints, find the frame that deviates most, and if that
deviation exceeds the tolerance, split there and recurse.  Turning points are
kept by construction, which is what stops a reduced clip from cutting the top
off a fast arm swing.
"""

from __future__ import annotations

import numpy as np

from ..clip import AnimationClip
from ..math3d import quat_angle, quat_slerp, unroll_quaternions


def reduce_keyframes(
    clip: AnimationClip,
    *,
    angular_tolerance_deg: float = 1.0,
    position_tolerance_studs: float = 0.02,
) -> list[int]:
    """Frame indices to keep, always including the first and last."""
    frames = clip.frame_count
    if frames <= 2:
        return list(range(frames))

    tolerance = np.deg2rad(angular_tolerance_deg)
    keep = {0, frames - 1}

    for track in clip.rotations.values():
        _split_rotations(unroll_quaternions(track), 0, frames - 1, tolerance, keep)

    if clip.root_positions is not None:
        _split_positions(
            clip.root_positions, 0, frames - 1, position_tolerance_studs, keep
        )

    return sorted(keep)


def _split_rotations(
    track: np.ndarray, lo: int, hi: int, tolerance: float, keep: set[int]
) -> None:
    def error(a: int, b: int, idx: np.ndarray) -> np.ndarray:
        t = (idx - a) / (b - a)
        predicted = quat_slerp(
            np.tile(track[a], (idx.size, 1)), np.tile(track[b], (idx.size, 1)), t
        )
        return quat_angle(predicted, track[idx])

    _split(lo, hi, tolerance, keep, error)


def _split_positions(
    track: np.ndarray, lo: int, hi: int, tolerance: float, keep: set[int]
) -> None:
    def error(a: int, b: int, idx: np.ndarray) -> np.ndarray:
        t = ((idx - a) / (b - a))[:, None]
        predicted = track[a] * (1 - t) + track[b] * t
        return np.linalg.norm(predicted - track[idx], axis=-1)

    _split(lo, hi, tolerance, keep, error)


def _split(lo: int, hi: int, tolerance: float, keep: set[int], error) -> None:
    """Iterative Ramer-Douglas-Peucker.

    An explicit worklist rather than recursion: a long take with continuous
    motion splits once per frame in the worst case, which would blow Python's
    recursion limit on anything over a minute.
    """
    pending = [(lo, hi)]
    while pending:
        a, b = pending.pop()
        if b - a < 2:
            continue
        idx = np.arange(a + 1, b)
        deviation = error(a, b, idx)
        worst = int(np.argmax(deviation))
        if deviation[worst] <= tolerance:
            continue
        split = int(idx[worst])
        keep.add(split)
        pending.append((a, split))
        pending.append((split, b))
