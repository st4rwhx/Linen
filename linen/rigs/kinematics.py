"""Forward kinematics on a rig: where does each part actually end up?

The exporter never needs this — a Roblox pose is a local rotation and the engine
places the parts. But several things do need to know where a posed body's feet
are, and the most important is stride: how far a walk cycle *carries* the
character. Get that wrong and the runtime plays the walk at the wrong rate, and
the feet skate across the ground.

So this is the one place the preview geometry earns its keep. The numbers are
approximate — they are Studio's stock R15 proportions — and any avatar with
different limb lengths strides differently. What matters is the ratio: the
runtime divides real ground speed by this, so a consistent error in the rig's
scale cancels out.
"""

from __future__ import annotations

import numpy as np

from ..math3d import euler_degrees_to_quat, quat_to_mat
from .definition import RigDefinition


def forward_kinematics(
    rig: RigDefinition, pose: dict[str, tuple[float, float, float]]
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Place every part of ``rig`` in its rest space under ``pose``.

    ``pose`` maps part names to XYZ Euler degrees, as the pose book stores them;
    parts it omits stay at rest. Returns part name to ``(position, rotation)``
    in studs, with the root at the origin.

    The chain is the same one the viewport draws: a joint frame at the pivot
    that the pose rotates, then the part's centre offset within it. Rotating
    about the part's centre instead would swing a bent knee away from the thigh.
    """
    placed: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for part in rig.parts:
        angles = pose.get(part.name, (0.0, 0.0, 0.0))
        local = quat_to_mat(euler_degrees_to_quat(np.array(angles, dtype=float)))

        if part.parent is None:
            placed[part.name] = (np.zeros(3), local)
            continue

        parent_position, parent_rotation = placed[part.parent]
        pivot = np.asarray(part.pivot, dtype=float)
        offset = np.asarray(part.rest_offset, dtype=float) - pivot

        joint_position = parent_position + parent_rotation @ pivot
        rotation = parent_rotation @ local
        placed[part.name] = (joint_position + rotation @ offset, rotation)

    return placed


def sole_positions(
    rig: RigDefinition, pose: dict[str, tuple[float, float, float]]
) -> dict[str, np.ndarray]:
    """The bottom of each foot, which is what actually touches the ground."""
    placed = forward_kinematics(rig, pose)
    soles: dict[str, np.ndarray] = {}
    for name in ("LeftFoot", "RightFoot", "Left Leg", "Right Leg"):
        if name not in placed:
            continue
        position, rotation = placed[name]
        half_height = rig.part(name).size[1] / 2.0
        soles[name] = position + rotation @ np.array([0.0, -half_height, 0.0])
    return soles


def step_length(rig: RigDefinition, pose: dict[str, tuple[float, float, float]]) -> float:
    """Forward distance between the two feet in a pose, in studs.

    Measured along the character's facing (-Z), which is the axis a step covers.
    Lateral separation is stance width, not stride, and including it would
    inflate every cycle's speed.
    """
    soles = sole_positions(rig, pose)
    if len(soles) < 2:
        return 0.0
    forward = [float(position[2]) for position in soles.values()]
    return abs(max(forward) - min(forward))
