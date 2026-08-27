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


def load_collada(path, *, skeleton: str = "mixamo", units: str = "cm", fps=None):
    """A Collada (.dae) capture as a landmark track.

    The route that skips Blender: Mixamo exports Collada directly, and a
    Collada export bakes a matrix per joint per frame, so there is nothing left
    to interpret.
    """
    from .collada import load_collada as _load

    return _load(path, skeleton=skeleton, units=units, fps=fps)


def load_bvh(path, *, skeleton: str = "mixamo", units: str = "cm", fps: float | None = None):
    """Parse a BVH file and map it onto MediaPipe landmark names."""
    motion = parse_bvh(path)
    return to_landmark_track(motion, get_skeleton(skeleton), units=units, fps=fps)


#: What a capture may arrive as. Mixamo exports Collada without Blender in the
#: way, so `.dae` is not an afterthought here — it is the format someone
#: building a library from Mixamo actually has on disk. `.rbxmx` and `.rbxm`
#: are not captures at all: they are finished Roblox animations, from a
#: service, from Studio, from somebody's hand in Moon Animator. Indexing them
#: is what lets a scene be assembled out of work made anywhere else.
MOTION_SUFFIXES = (".bvh", ".dae", ".rbxmx", ".rbxm")

#: The subset that is already a Roblox animation rather than a capture: no
#: skeleton to map, no retargeting to do, already on a rig.
ROBLOX_SUFFIXES = (".rbxmx", ".rbxm")


def load_motion(path, *, skeleton: str = "mixamo", units: str = "cm", fps=None):
    """A capture as a landmark track, whatever file it came in.

    Callers that hardcode `load_bvh` quietly exclude every Mixamo download,
    which is most of what a library is built from. A Roblox animation has no
    landmark track — it is already on a rig — so it is not accepted here; use
    :func:`linen.sources.keyframes.read_keyframe_sequence` for those.
    """
    from pathlib import Path as _Path

    suffix = _Path(path).suffix.lower()
    if suffix in ROBLOX_SUFFIXES:
        raise ValueError(
            f"{_Path(path).name} is a Roblox animation, not a capture. It is "
            f"already on a rig, so there is nothing to retarget; read it with "
            f"read_keyframe_sequence instead."
        )
    if suffix == ".dae":
        return load_collada(path, skeleton=skeleton, units=units, fps=fps)
    return load_bvh(path, skeleton=skeleton, units=units, fps=fps)
