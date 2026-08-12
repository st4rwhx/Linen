"""The stock Roblox R15 rig: 15 body parts plus a HumanoidRootPart.

Joint names are the ``Motor6D.Name`` values ``Humanoid:BuildRigFromAttachments``
produces, and pose names are the part names — that pairing is what lets the
Animation Editor load an exported ``KeyframeSequence`` onto a rig it did not
create.

Part sizes and offsets are **measured**, not estimated: they come from Roblox's
own ``ClassicMannequin.fbx`` reference file, read by ``tools/read_fbx_skeleton.py``
and reproducible from it.  The figure comes out 4.98 studs tall, which is what
Roblox documents.

Two corrections are applied to the raw measurements.  The mannequin is modelled
in an A-pose while the rig rests with its arms down, so each shoulder joint is
recovered from the A-posed arm centre and the arm re-hung vertically.  And the
mannequin's left side is +X where a Roblox character's own left is -X, so the
sides are mirrored.

None of this reaches the exported animation, which is rotations only — but it is
not decoration either.  Stride is measured by posing this geometry, and stride
is what the runtime divides ground speed by to stop the feet skating, so limb
lengths that are wrong here produce feet that slide there.  Two earlier versions
of this file were wrong — once by a factor of two — and neither error surfaced
until the rig was finally drawn and then measured against the source.
"""

from __future__ import annotations

from .definition import BoneSource, Part, RigDefinition, Roll

_UP = (0.0, 1.0, 0.0)
_DOWN = (0.0, -1.0, 0.0)
_FORWARD = (0.0, 0.0, -1.0)
_BACK = (0.0, 0.0, 1.0)

PARTS: tuple[Part, ...] = (
    Part("HumanoidRootPart", None, None, aim_axis=_UP, size=(2.0, 2.0, 1.0)),
    Part(
        "LowerTorso",
        "HumanoidRootPart",
        "Root",
        aim_axis=_UP,
        size=(1.33, 0.41, 0.72),
        rest_offset=(0.0, 0.0, 0.0),
    ),
    Part(
        "UpperTorso",
        "LowerTorso",
        "Waist",
        aim_axis=_UP,
        size=(1.30, 1.70, 0.84),
        rest_offset=(0.0, 0.794, 0.051),
    ),
    Part(
        "Head",
        "UpperTorso",
        "Neck",
        aim_axis=_UP,
        size=(1.15, 1.18, 1.13),
        rest_offset=(0.0, 1.16, -0.067),
    ),
    # --- left arm -------------------------------------------------------
    # The mannequin is modelled in an A-pose while the rig rests with arms
    # down, so the shoulder joint is recovered from the A-posed centre and the
    # arm re-hung vertically. Bone lengths are the A-pose centre spacings,
    # which the rotation leaves unchanged.
    Part(
        "LeftUpperArm",
        "UpperTorso",
        "LeftShoulder",
        aim_axis=_DOWN,
        size=(0.75, 0.89, 0.58),
        rest_offset=(-0.678, -0.146, 0.0),
    ),
    Part(
        "LeftLowerArm",
        "LeftUpperArm",
        "LeftElbow",
        aim_axis=_DOWN,
        size=(0.66, 0.90, 0.59),
        rest_offset=(0.0, -0.680, 0.0),
    ),
    Part(
        "LeftHand",
        "LeftLowerArm",
        "LeftWrist",
        aim_axis=_DOWN,
        roll_axis=_BACK,
        size=(0.55, 0.59, 0.53),
        rest_offset=(0.0, -0.694, 0.0),
    ),
    # --- right arm ------------------------------------------------------
    Part(
        "RightUpperArm",
        "UpperTorso",
        "RightShoulder",
        aim_axis=_DOWN,
        size=(0.75, 0.89, 0.58),
        rest_offset=(0.678, -0.146, 0.0),
    ),
    Part(
        "RightLowerArm",
        "RightUpperArm",
        "RightElbow",
        aim_axis=_DOWN,
        size=(0.66, 0.90, 0.59),
        rest_offset=(0.0, -0.680, 0.0),
    ),
    Part(
        "RightHand",
        "RightLowerArm",
        "RightWrist",
        aim_axis=_DOWN,
        roll_axis=_BACK,
        size=(0.55, 0.59, 0.53),
        rest_offset=(0.0, -0.694, 0.0),
    ),
    # --- left leg -------------------------------------------------------
    # Legs are modelled vertical, so these offsets are the measurements
    # unchanged, only mirrored: the mannequin's left is +X, a Roblox
    # character's own left is -X.
    Part(
        "LeftUpperLeg",
        "LowerTorso",
        "LeftHip",
        aim_axis=_DOWN,
        size=(0.66, 1.66, 0.66),
        rest_offset=(-0.328, -0.831, 0.011),
    ),
    Part(
        "LeftLowerLeg",
        "LeftUpperLeg",
        "LeftKnee",
        aim_axis=_DOWN,
        size=(0.61, 1.17, 0.61),
        rest_offset=(-0.025, -0.903, -0.021),
    ),
    Part(
        "LeftFoot",
        "LeftLowerLeg",
        "LeftAnkle",
        aim_axis=_FORWARD,
        roll_axis=_UP,
        size=(0.61, 0.56, 0.86),
        rest_offset=(0.0, -0.421, -0.112),
    ),
    # --- right leg ------------------------------------------------------
    Part(
        "RightUpperLeg",
        "LowerTorso",
        "RightHip",
        aim_axis=_DOWN,
        size=(0.66, 1.66, 0.66),
        rest_offset=(0.328, -0.831, 0.011),
    ),
    Part(
        "RightLowerLeg",
        "RightUpperLeg",
        "RightKnee",
        aim_axis=_DOWN,
        size=(0.61, 1.17, 0.61),
        rest_offset=(0.025, -0.903, -0.021),
    ),
    Part(
        "RightFoot",
        "RightLowerLeg",
        "RightAnkle",
        aim_axis=_FORWARD,
        roll_axis=_UP,
        size=(0.61, 0.56, 0.86),
        rest_offset=(0.0, -0.421, -0.112),
    ),
)

_HIPS = ("left_hip", "right_hip")
_SHOULDERS = ("left_shoulder", "right_shoulder")

_LEFT_ELBOW = ("left_shoulder", "left_elbow", "left_wrist")
_RIGHT_ELBOW = ("right_shoulder", "right_elbow", "right_wrist")
_LEFT_KNEE = ("left_hip", "left_knee", "left_ankle")
_RIGHT_KNEE = ("right_hip", "right_knee", "right_ankle")

SOURCES: tuple[BoneSource, ...] = (
    # The pelvis reads off the hip line; the chest off the shoulder line, so a
    # twisted torso survives retargeting instead of collapsing into one rigid
    # block the way a single-spine solve would.
    BoneSource("LowerTorso", _HIPS, _SHOULDERS, Roll.LATERAL, lateral=("left_hip", "right_hip")),
    BoneSource(
        "UpperTorso",
        _HIPS,
        _SHOULDERS,
        Roll.LATERAL,
        lateral=("left_shoulder", "right_shoulder"),
    ),
    BoneSource(
        "Head",
        _SHOULDERS,
        ("left_ear", "right_ear"),
        Roll.LATERAL,
        lateral=("left_ear", "right_ear"),
    ),
    # Upper and lower limb quote the same hinge plane: the elbow sets the twist
    # for both the upper arm and the forearm, and the knee for both leg bones.
    BoneSource(
        "LeftUpperArm",
        ("left_shoulder",),
        ("left_elbow",),
        Roll.CHAIN_PLANE,
        plane=_LEFT_ELBOW,
    ),
    BoneSource(
        "LeftLowerArm", ("left_elbow",), ("left_wrist",), Roll.CHAIN_PLANE, plane=_LEFT_ELBOW
    ),
    BoneSource("LeftHand", ("left_wrist",), ("left_index", "left_pinky"), Roll.PARENT_BACK),
    BoneSource(
        "RightUpperArm",
        ("right_shoulder",),
        ("right_elbow",),
        Roll.CHAIN_PLANE,
        plane=_RIGHT_ELBOW,
    ),
    BoneSource(
        "RightLowerArm",
        ("right_elbow",),
        ("right_wrist",),
        Roll.CHAIN_PLANE,
        plane=_RIGHT_ELBOW,
    ),
    BoneSource("RightHand", ("right_wrist",), ("right_index", "right_pinky"), Roll.PARENT_BACK),
    # Knees hinge the opposite way from elbows, which flips the plane normal.
    BoneSource(
        "LeftUpperLeg",
        ("left_hip",),
        ("left_knee",),
        Roll.CHAIN_PLANE,
        plane=_LEFT_KNEE,
        invert_chain_normal=True,
    ),
    BoneSource(
        "LeftLowerLeg",
        ("left_knee",),
        ("left_ankle",),
        Roll.CHAIN_PLANE,
        plane=_LEFT_KNEE,
        invert_chain_normal=True,
    ),
    BoneSource("LeftFoot", ("left_heel",), ("left_foot_index",), Roll.PARENT_UP),
    BoneSource(
        "RightUpperLeg",
        ("right_hip",),
        ("right_knee",),
        Roll.CHAIN_PLANE,
        plane=_RIGHT_KNEE,
        invert_chain_normal=True,
    ),
    BoneSource(
        "RightLowerLeg",
        ("right_knee",),
        ("right_ankle",),
        Roll.CHAIN_PLANE,
        plane=_RIGHT_KNEE,
        invert_chain_normal=True,
    ),
    BoneSource("RightFoot", ("right_heel",), ("right_foot_index",), Roll.PARENT_UP),
)

R15 = RigDefinition(name="R15", parts=PARTS, sources=SOURCES)
