"""Motion coming from somewhere other than FreeMoCap or the pose book.

Text-to-motion services and open models — SayMotion, MoMask, MDM, Mixamo
downloads — all emit humanoid skeletons rather than Roblox rigs.  This package
turns their output into the landmark tracks the retargeter already understands,
so Linen sits downstream of them instead of duplicating them.
"""

from __future__ import annotations

from .bvh import BvhError, BvhMotion, parse_bvh
from .skeletons import (
    MIXAMO,
    ROBLOX_R15,
    SKELETONS,
    SkeletonMapping,
    get_skeleton,
    to_landmark_track,
)

__all__ = [
    "MIXAMO",
    "ROBLOX_R15",
    "SKELETONS",
    "BvhError",
    "BvhMotion",
    "SkeletonMapping",
    "get_skeleton",
    "parse_bvh",
    "to_landmark_track",
]


def load_bvh(path, *, skeleton: str = "mixamo", units: str = "cm", fps: float | None = None):
    """Parse a BVH file and map it onto MediaPipe landmark names."""
    motion = parse_bvh(path)
    return to_landmark_track(motion, get_skeleton(skeleton), units=units, fps=fps)
