"""R6 does not measure its joint rotations in the part's own axes.

Roblox composes a joint as ``parent * C0 * Transform * C1:Inverse()``. R15
builds every joint axis-aligned, so ``Transform`` is the local rotation and can
be written straight out. R6 builds its shoulders and hips a quarter turn about
Y, so a leg stepping forward is stored as a rotation about the pose's Z. Write
the local rotation there instead and the file still imports, still plays, and
sends the step sideways — which is why this needs a test rather than a look.

The expectations here are read off animations Roblox's own editor wrote, in
`examples/`: in a run, R6 legs are 0.85-0.99 Z-dominant.
"""
from __future__ import annotations

import numpy as np

from linen.clip import AnimationClip
from linen.export.rbxmx import build_keyframe_sequence
from linen.math3d import mat_to_quat
from linen.rigs import get_rig


def _axis(matrix: np.ndarray) -> np.ndarray:
    """The rotation's axis, scaled by its angle in degrees."""
    angle = np.arccos(np.clip((np.trace(matrix) - 1.0) / 2.0, -1.0, 1.0))
    if angle < 1e-9:
        return np.zeros(3)
    axis = np.array(
        [
            matrix[2, 1] - matrix[1, 2],
            matrix[0, 2] - matrix[2, 0],
            matrix[1, 0] - matrix[0, 1],
        ]
    ) / (2.0 * np.sin(angle))
    return axis * np.degrees(angle)


def _swing(rig_name: str, part: str, degrees: float) -> np.ndarray:
    """Write a one-part clip that swings `part` forward, and read the pose back."""
    rig = get_rig(rig_name)
    angle = np.radians(degrees)
    forward = np.array(
        [[1.0, 0.0, 0.0], [0.0, np.cos(angle), -np.sin(angle)], [0.0, np.sin(angle), np.cos(angle)]]
    )
    rotations = {
        p.name: np.tile(mat_to_quat(np.eye(3)[None])[0], (2, 1)) for p in rig.parts[1:]
    }
    rotations[part] = np.tile(mat_to_quat(forward[None])[0], (2, 1))
    clip = AnimationClip(rig=rig, fps=30.0, rotations=rotations, name="Swing")

    tree = build_keyframe_sequence(clip)
    for pose in (i for i in tree.getroot().iter("Item") if i.get("class") == "Pose"):
        if pose.find("Properties/string[@name='Name']").text != part:
            continue
        cframe = pose.find("Properties/CoordinateFrame[@name='CFrame']")
        return np.array(
            [[float(cframe.find(f"R{r}{c}").text) for c in range(3)] for r in range(3)]
        )
    raise AssertionError(f"{part} never reached the file")


def test_an_r6_leg_swinging_forward_is_written_about_z() -> None:
    axis = _axis(_swing("R6", "Left Leg", 40.0))
    assert abs(axis[2]) > 0.9 * np.linalg.norm(axis), (
        f"an R6 hip stores a forward swing about Z; this wrote {axis.round(1)}"
    )


def test_an_r15_leg_swinging_forward_is_written_about_x() -> None:
    axis = _axis(_swing("R15", "LeftUpperLeg", 40.0))
    assert abs(axis[0]) > 0.9 * np.linalg.norm(axis), (
        f"an R15 hip is axis-aligned, so a forward swing stays on X; got {axis.round(1)}"
    )


def test_an_r6_torso_leaning_forward_stays_on_x() -> None:
    # The root joint is turned about the Y/Z diagonal, not about Y, so a lean
    # survives on X where a yaw would move to Z. Roblox's own prone and crouch
    # poses store their torso lean on X, which is what pins this one down.
    axis = _axis(_swing("R6", "Torso", 30.0))
    assert abs(axis[0]) > 0.9 * np.linalg.norm(axis), (
        f"an R6 root stores a lean about X; this wrote {axis.round(1)}"
    )


def test_left_and_right_are_mirrored_not_shared() -> None:
    """A symmetric pose must come out mirrored in the file, as Roblox writes it.

    Both sides swing the same way in the world, so the stored rotations must
    differ — give the two joints the same frame and they come out identical,
    which is the bug that makes one arm swing backwards.
    """
    left = _axis(_swing("R6", "Left Arm", 35.0))
    right = _axis(_swing("R6", "Right Arm", 35.0))
    assert np.allclose(left, -right, atol=1e-6), (
        f"left {left.round(1)} and right {right.round(1)} are not mirror images"
    )


def test_every_joint_frame_is_a_rotation() -> None:
    for name in ("R6", "R15"):
        for part in get_rig(name).parts:
            axes = np.asarray(part.joint_frame, dtype=float)
            assert np.allclose(axes @ axes.T, np.eye(3)), f"{name}/{part.name} is not orthonormal"
            assert np.linalg.det(axes) > 0, f"{name}/{part.name} mirrors instead of rotating"
