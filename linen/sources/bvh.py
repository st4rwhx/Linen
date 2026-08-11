"""Read BVH, the interchange format every text-to-motion tool speaks.

DeepMotion's SayMotion exports it, and the open text-to-motion models
(MoMask, MDM and friends) all have a BVH writer because HumanML3D-derived
skeletons convert to it directly.  Parsing it here is what lets Linen sit
downstream of any of them rather than competing with them: their model
generates the motion, this turns it into a Roblox ``KeyframeSequence``.

Only joint *positions* are extracted.  A BVH's rotations are expressed against
its own rest pose and channel order, so consuming them directly would tie the
retargeter to each exporter's conventions; running forward kinematics and
handing world positions to the same solver the mocap path uses keeps one code
path and one set of conventions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..math3d import euler_xyz_to_mat

_ROTATION_AXIS = {"Xrotation": 0, "Yrotation": 1, "Zrotation": 2}
_POSITION_AXIS = {"Xposition": 0, "Yposition": 1, "Zposition": 2}


class BvhError(ValueError):
    pass


@dataclass
class Joint:
    name: str
    offset: np.ndarray
    parent: int | None
    channels: list[str] = field(default_factory=list)
    #: Index of this joint's first channel in a motion row.
    channel_start: int = 0


@dataclass
class BvhMotion:
    joints: list[Joint]
    #: ``(frames, channels)`` raw motion data.
    values: np.ndarray
    frame_time: float

    @property
    def fps(self) -> float:
        return 1.0 / self.frame_time

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(joint.name for joint in self.joints)

    def world_positions(self) -> np.ndarray:
        """Forward kinematics: ``(frames, joints, 3)`` in the file's units."""
        frames = self.values.shape[0]
        positions = np.zeros((frames, len(self.joints), 3))
        rotations = np.zeros((frames, len(self.joints), 3, 3))

        for index, joint in enumerate(self.joints):
            local_rotation = _channel_rotation(joint, self.values)
            translation = np.broadcast_to(joint.offset, (frames, 3)).copy()

            for offset, channel in enumerate(joint.channels):
                axis = _POSITION_AXIS.get(channel)
                if axis is not None:
                    translation[:, axis] += self.values[:, joint.channel_start + offset]

            if joint.parent is None:
                positions[:, index] = translation
                rotations[:, index] = local_rotation
            else:
                parent_rotation = rotations[:, joint.parent]
                positions[:, index] = positions[:, joint.parent] + np.einsum(
                    "nij,nj->ni", parent_rotation, translation
                )
                rotations[:, index] = parent_rotation @ local_rotation

        return positions


def _channel_rotation(joint: Joint, values: np.ndarray) -> np.ndarray:
    """Compose a joint's rotation channels in the order the file declares them.

    BVH almost always lists ZXY, and applying them as XYZ instead silently
    produces a plausible-looking but wrong pose, so the order is honoured
    rather than assumed.
    """
    frames = values.shape[0]
    rotation = np.tile(np.eye(3), (frames, 1, 1))
    for offset, channel in enumerate(joint.channels):
        axis = _ROTATION_AXIS.get(channel)
        if axis is None:
            continue
        angles = np.zeros((frames, 3))
        angles[:, axis] = np.deg2rad(values[:, joint.channel_start + offset])
        rotation = rotation @ euler_xyz_to_mat(angles)
    return rotation


def parse_bvh(path: str | Path) -> BvhMotion:
    """Parse a BVH file into its skeleton and motion table."""
    text = Path(path).read_text(errors="replace")
    head, _, tail = text.partition("MOTION")
    if not tail:
        raise BvhError(f"{path}: no MOTION section; is this really a BVH file?")

    joints = _parse_hierarchy(head, path)
    values, frame_time = _parse_motion(tail, path)

    expected = sum(len(joint.channels) for joint in joints)
    if values.shape[1] != expected:
        raise BvhError(
            f"{path}: hierarchy declares {expected} channels but each motion row "
            f"has {values.shape[1]}"
        )
    return BvhMotion(joints, values, frame_time)


def _parse_hierarchy(text: str, path: str | Path) -> list[Joint]:
    tokens = text.replace("{", " { ").replace("}", " } ").split()
    joints: list[Joint] = []
    stack: list[int] = []
    channel_cursor = 0
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if token in ("ROOT", "JOINT"):
            parent = stack[-1] if stack else None
            joints.append(Joint(tokens[index + 1], np.zeros(3), parent))
            stack.append(len(joints) - 1)
            index += 2
        elif token == "End":
            # End sites carry an offset but no channels. They are real points —
            # a toe tip, a fingertip — and mappings reference them, so they
            # become joints with an empty channel list.
            parent = stack[-1]
            joints.append(Joint(f"{joints[parent].name}_End", np.zeros(3), parent))
            stack.append(len(joints) - 1)
            index += 2
        elif token == "OFFSET":
            joints[stack[-1]].offset = np.array(
                [float(v) for v in tokens[index + 1 : index + 4]]
            )
            index += 4
        elif token == "CHANNELS":
            count = int(tokens[index + 1])
            joint = joints[stack[-1]]
            joint.channels = tokens[index + 2 : index + 2 + count]
            joint.channel_start = channel_cursor
            channel_cursor += count
            index += 2 + count
        elif token == "}":
            stack.pop()
            index += 1
        else:
            index += 1

    if not joints:
        raise BvhError(f"{path}: HIERARCHY section contains no joints")
    return joints


def _parse_motion(text: str, path: str | Path) -> tuple[np.ndarray, float]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    frame_time = 1.0 / 30.0
    rows: list[list[float]] = []

    for line in lines:
        lowered = line.lower()
        if lowered.startswith("frames:"):
            continue
        if lowered.startswith("frame time:"):
            frame_time = float(line.split(":", 1)[1])
            continue
        try:
            rows.append([float(value) for value in line.split()])
        except ValueError:
            raise BvhError(f"{path}: cannot read motion row {line[:60]!r}") from None

    if not rows:
        raise BvhError(f"{path}: MOTION section has no frames")
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        raise BvhError(f"{path}: motion rows have inconsistent widths {sorted(widths)}")
    if frame_time <= 0:
        raise BvhError(f"{path}: frame time {frame_time} is not positive")

    return np.array(rows), frame_time
