"""The stock Roblox R15 rig: 15 body parts plus a HumanoidRootPart.

Joint names are the ``Motor6D.Name`` values ``Humanoid:BuildRigFromAttachments``
produces, and pose names are the part names — that pairing is what lets the
Animation Editor load an exported ``KeyframeSequence`` onto a rig it did not
create.

Part sizes are the defaults of the Studio "Build Rig" R15 block character,
rounded to two decimals.  They only drive the preview skeleton; an animation
retargeted onto a differently proportioned avatar is unaffected because we
solve and export rotations, never positions.
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
        size=(2.0, 0.4, 1.0),
        rest_offset=(0.0, 0.0, 0.0),
    ),
    Part(
        "UpperTorso",
        "LowerTorso",
        "Waist",
        aim_axis=_UP,
        size=(2.0, 1.6, 1.0),
        rest_offset=(0.0, 1.0, 0.0),
    ),
    Part(
        "Head",
        "UpperTorso",
        "Neck",
        aim_axis=_UP,
        size=(2.0, 1.0, 1.0),
        rest_offset=(0.0, 1.3, 0.0),
    ),
    # --- left arm -------------------------------------------------------
    Part(
        "LeftUpperArm",
        "UpperTorso",
        "LeftShoulder",
        aim_axis=_DOWN,
        size=(1.0, 1.21, 1.0),
        rest_offset=(-1.5, 0.4, 0.0),
    ),
    Part(
        "LeftLowerArm",
        "LeftUpperArm",
        "LeftElbow",
        aim_axis=_DOWN,
        size=(1.0, 1.16, 1.0),
        rest_offset=(0.0, -1.19, 0.0),
    ),
    Part(
        "LeftHand",
        "LeftLowerArm",
        "LeftWrist",
        aim_axis=_DOWN,
        roll_axis=_BACK,
        size=(1.0, 0.62, 1.0),
        rest_offset=(0.0, -0.89, 0.0),
    ),
    # --- right arm ------------------------------------------------------
    Part(
        "RightUpperArm",
        "UpperTorso",
        "RightShoulder",
        aim_axis=_DOWN,
        size=(1.0, 1.21, 1.0),
        rest_offset=(1.5, 0.4, 0.0),
    ),
    Part(
        "RightLowerArm",
        "RightUpperArm",
        "RightElbow",
        aim_axis=_DOWN,
        size=(1.0, 1.16, 1.0),
        rest_offset=(0.0, -1.19, 0.0),
    ),
    Part(
        "RightHand",
        "RightLowerArm",
        "RightWrist",
        aim_axis=_DOWN,
        roll_axis=_BACK,
        size=(1.0, 0.62, 1.0),
        rest_offset=(0.0, -0.89, 0.0),
    ),
    # --- left leg -------------------------------------------------------
    Part(
        "LeftUpperLeg",
        "LowerTorso",
        "LeftHip",
        aim_axis=_DOWN,
        size=(1.0, 1.55, 1.0),
        rest_offset=(-0.5, -0.98, 0.0),
    ),
    Part(
        "LeftLowerLeg",
        "LeftUpperLeg",
        "LeftKnee",
        aim_axis=_DOWN,
        size=(1.0, 1.51, 1.0),
        rest_offset=(0.0, -1.53, 0.0),
    ),
    Part(
        "LeftFoot",
        "LeftLowerLeg",
        "LeftAnkle",
        aim_axis=_FORWARD,
        roll_axis=_UP,
        size=(1.0, 0.94, 1.0),
        rest_offset=(0.0, -1.22, 0.0),
    ),
    # --- right leg ------------------------------------------------------
    Part(
        "RightUpperLeg",
        "LowerTorso",
        "RightHip",
        aim_axis=_DOWN,
        size=(1.0, 1.55, 1.0),
        rest_offset=(0.5, -0.98, 0.0),
    ),
    Part(
        "RightLowerLeg",
        "RightUpperLeg",
        "RightKnee",
        aim_axis=_DOWN,
        size=(1.0, 1.51, 1.0),
        rest_offset=(0.0, -1.53, 0.0),
    ),
    Part(
        "RightFoot",
        "RightLowerLeg",
        "RightAnkle",
        aim_axis=_FORWARD,
        roll_axis=_UP,
        size=(1.0, 0.94, 1.0),
        rest_offset=(0.0, -1.22, 0.0),
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
