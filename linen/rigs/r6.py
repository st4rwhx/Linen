"""The classic Roblox R6 rig: six body parts plus a HumanoidRootPart.

R6 part names contain spaces ("Left Arm"), and its joints are named differently
from R15's — ``RootJoint`` rather than ``Root``, ``Left Shoulder`` rather than
``LeftShoulder``.  Getting these strings wrong produces a KeyframeSequence that
imports without complaint and then animates nothing, so they are spelled out
here once and never rebuilt from R15 by string surgery.

With one rigid part per limb there is no elbow or knee to solve: the arm bone
runs shoulder-to-wrist and the leg bone hip-to-ankle, and the twist comes from
the shoulder and hip lines.  Bend detail is genuinely lost — that is a property
of R6, not of the retargeter.
"""

from __future__ import annotations

from .definition import BoneSource, Part, RigDefinition, Roll

_UP = (0.0, 1.0, 0.0)
_DOWN = (0.0, -1.0, 0.0)

# The frames R6 measures its joint rotations in — the rotation half of each
# ``Motor6D.C0``, which R6 shares with its ``C1``.  R15 has none of this: every
# R15 joint is built axis-aligned, so its poses are local rotations as written.
#
# Shoulders and hips are turned a quarter turn about Y, so a limb swinging
# forwards is stored as a rotation about the pose's **Z**, not its X.  That is
# visible in any R6 animation Roblox itself wrote: across the run and crouch
# cycles in `examples/`, the legs are 0.85-0.99 Z-dominant while the torso,
# whose joint is turned differently, is X-dominant.  Writing the local rotation
# straight out sends a forward step sideways.
_LEFT_LIMB = ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
_RIGHT_LIMB = ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
# Root and neck: a half turn about the diagonal between +Y and +Z, which leaves
# a forward lean on X and sends a yaw to Z.
_SPINE = ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))

PARTS: tuple[Part, ...] = (
    Part("HumanoidRootPart", None, None, aim_axis=_UP, size=(2.0, 2.0, 1.0)),
    Part(
        "Torso",
        "HumanoidRootPart",
        "RootJoint",
        aim_axis=_UP,
        joint_frame=_SPINE,
        size=(2.0, 2.0, 1.0),
    ),
    Part(
        "Head",
        "Torso",
        "Neck",
        aim_axis=_UP,
        joint_frame=_SPINE,
        size=(2.0, 1.0, 1.0),
        rest_offset=(0.0, 1.5, 0.0),
    ),
    Part(
        "Left Arm",
        "Torso",
        "Left Shoulder",
        aim_axis=_DOWN,
        joint_frame=_LEFT_LIMB,
        size=(1.0, 2.0, 1.0),
        rest_offset=(-1.5, 0.0, 0.0),
    ),
    Part(
        "Right Arm",
        "Torso",
        "Right Shoulder",
        aim_axis=_DOWN,
        joint_frame=_RIGHT_LIMB,
        size=(1.0, 2.0, 1.0),
        rest_offset=(1.5, 0.0, 0.0),
    ),
    Part(
        "Left Leg",
        "Torso",
        "Left Hip",
        aim_axis=_DOWN,
        joint_frame=_LEFT_LIMB,
        size=(1.0, 2.0, 1.0),
        rest_offset=(-0.5, -2.0, 0.0),
    ),
    Part(
        "Right Leg",
        "Torso",
        "Right Hip",
        aim_axis=_DOWN,
        joint_frame=_RIGHT_LIMB,
        size=(1.0, 2.0, 1.0),
        rest_offset=(0.5, -2.0, 0.0),
    ),
)

_SHOULDERS = ("left_shoulder", "right_shoulder")
_HIPS = ("left_hip", "right_hip")

SOURCES: tuple[BoneSource, ...] = (
    BoneSource("Torso", _HIPS, _SHOULDERS, Roll.LATERAL, lateral=("left_hip", "right_hip")),
    BoneSource(
        "Head",
        _SHOULDERS,
        ("left_ear", "right_ear"),
        Roll.LATERAL,
        lateral=("left_ear", "right_ear"),
    ),
    BoneSource(
        "Left Arm", ("left_shoulder",), ("left_wrist",), Roll.LATERAL, lateral=_SHOULDERS
    ),
    BoneSource(
        "Right Arm", ("right_shoulder",), ("right_wrist",), Roll.LATERAL, lateral=_SHOULDERS
    ),
    BoneSource("Left Leg", ("left_hip",), ("left_ankle",), Roll.LATERAL, lateral=_HIPS),
    BoneSource("Right Leg", ("right_hip",), ("right_ankle",), Roll.LATERAL, lateral=_HIPS),
)

R6 = RigDefinition(name="R6", parts=PARTS, sources=SOURCES)
