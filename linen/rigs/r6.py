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

PARTS: tuple[Part, ...] = (
    Part("HumanoidRootPart", None, None, aim_axis=_UP, size=(2.0, 2.0, 1.0)),
    Part("Torso", "HumanoidRootPart", "RootJoint", aim_axis=_UP, size=(2.0, 2.0, 1.0)),
    Part("Head", "Torso", "Neck", aim_axis=_UP, size=(2.0, 1.0, 1.0), rest_offset=(0.0, 1.5, 0.0)),
    Part(
        "Left Arm",
        "Torso",
        "Left Shoulder",
        aim_axis=_DOWN,
        size=(1.0, 2.0, 1.0),
        rest_offset=(-1.5, 0.0, 0.0),
    ),
    Part(
        "Right Arm",
        "Torso",
        "Right Shoulder",
        aim_axis=_DOWN,
        size=(1.0, 2.0, 1.0),
        rest_offset=(1.5, 0.0, 0.0),
    ),
    Part(
        "Left Leg",
        "Torso",
        "Left Hip",
        aim_axis=_DOWN,
        size=(1.0, 2.0, 1.0),
        rest_offset=(-0.5, -2.0, 0.0),
    ),
    Part(
        "Right Leg",
        "Torso",
        "Right Hip",
        aim_axis=_DOWN,
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
