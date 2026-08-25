"""The one animation representation every stage of the pipeline speaks.

Retargeted mocap, procedurally synthesised motion and library clips all land
here, and the exporter only knows how to read this.  Rotations are *local to
the parent part* and expressed as deviations from the rig's rest pose, which is
exactly what a Roblox ``Pose.CFrame`` stores.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .math3d import normalize, quat_slerp, unroll_quaternions
from .rigs import RigDefinition

IDENTITY_QUAT = np.array([0.0, 0.0, 0.0, 1.0])


@dataclass
class AnimationClip:
    """A sampled animation for one rig."""

    rig: RigDefinition
    fps: float
    #: part name -> ``(frames, 4)`` local rotations as xyzw quaternions.
    rotations: dict[str, np.ndarray]
    #: Optional ``(frames, 3)`` HumanoidRootPart translation in studs.
    root_positions: np.ndarray | None = None
    name: str = "Animation"
    loop: bool = False
    priority: str = "Action"
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.fps <= 0:
            raise ValueError(f"fps must be positive, got {self.fps}")
        known = set(self.rig.animated_parts)
        for part, track in self.rotations.items():
            if part not in known:
                raise ValueError(f"{part!r} is not an animated part of rig {self.rig.name}")
            self.rotations[part] = np.asarray(track, dtype=float)
            if self.rotations[part].shape != (self.frame_count, 4):
                raise ValueError(
                    f"{part!r}: expected ({self.frame_count}, 4) quaternions, "
                    f"got {self.rotations[part].shape}"
                )
        if self.root_positions is not None:
            self.root_positions = np.asarray(self.root_positions, dtype=float)
            if self.root_positions.shape != (self.frame_count, 3):
                raise ValueError(
                    f"root_positions should be ({self.frame_count}, 3), "
                    f"got {self.root_positions.shape}"
                )

    @property
    def frame_count(self) -> int:
        first = next(iter(self.rotations.values()))
        return int(np.asarray(first).shape[0])

    @property
    def duration(self) -> float:
        """Seconds from the first frame to the last.

        A one-frame clip is a static pose of length zero, and an N-frame clip
        spans N-1 intervals — off-by-one here shows up as a clip that plays a
        frame too slowly.
        """
        return max(self.frame_count - 1, 0) / self.fps

    @property
    def times(self) -> np.ndarray:
        return np.arange(self.frame_count) / self.fps

    @classmethod
    def rest(cls, rig: RigDefinition, frames: int, fps: float = 30.0, **kwargs) -> AnimationClip:
        """A clip holding the rig's rest pose, useful as a base to layer onto."""
        rotations = {
            part: np.tile(IDENTITY_QUAT, (frames, 1)) for part in rig.animated_parts
        }
        return cls(rig=rig, fps=fps, rotations=rotations, **kwargs)

    def resampled(self, fps: float) -> AnimationClip:
        """Resample to a new frame rate, slerping rotations."""
        if fps <= 0:
            raise ValueError(f"fps must be positive, got {fps}")
        if np.isclose(fps, self.fps) or self.frame_count < 2:
            return self

        new_count = max(round(self.duration * fps) + 1, 1)
        source = np.linspace(0.0, self.frame_count - 1, new_count)
        lo = np.floor(source).astype(int)
        hi = np.minimum(lo + 1, self.frame_count - 1)
        t = source - lo

        rotations = {}
        for part, track in self.rotations.items():
            unrolled = unroll_quaternions(track)
            rotations[part] = quat_slerp(unrolled[lo], unrolled[hi], t)

        root = None
        if self.root_positions is not None:
            root = (
                self.root_positions[lo] * (1 - t)[:, None]
                + self.root_positions[hi] * t[:, None]
            )

        return AnimationClip(
            rig=self.rig,
            fps=fps,
            rotations=rotations,
            root_positions=root,
            name=self.name,
            loop=self.loop,
            priority=self.priority,
            metadata=dict(self.metadata),
        )

    def sliced(self, start: int, stop: int) -> AnimationClip:
        return AnimationClip(
            rig=self.rig,
            fps=self.fps,
            rotations={p: t[start:stop] for p, t in self.rotations.items()},
            root_positions=None
            if self.root_positions is None
            else self.root_positions[start:stop],
            name=self.name,
            loop=self.loop,
            priority=self.priority,
            metadata=dict(self.metadata),
        )

    def with_loop_seam(self, blend_frames: int = 6) -> AnimationClip:
        """Cross-fade the tail into the head so the clip loops without a pop.

        The last ``blend_frames`` frames are blended towards the first frame,
        weighted so the very last frame matches the first exactly.
        """
        if blend_frames <= 0 or self.frame_count <= blend_frames + 1:
            return self

        rotations = {}
        weights = np.linspace(0.0, 1.0, blend_frames + 1)[1:]
        for part, track in self.rotations.items():
            blended = unroll_quaternions(track).copy()
            tail = blended[-blend_frames:]
            head = np.tile(blended[0], (blend_frames, 1))
            blended[-blend_frames:] = quat_slerp(tail, head, weights)
            rotations[part] = normalize(blended)

        clip = AnimationClip(
            rig=self.rig,
            fps=self.fps,
            rotations=rotations,
            root_positions=self.root_positions,
            name=self.name,
            loop=True,
            priority=self.priority,
            metadata=dict(self.metadata),
        )
        return clip
