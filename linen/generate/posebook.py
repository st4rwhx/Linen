"""A curated vocabulary of key poses, and cycles built from them.

This is the piece that makes free, text-driven animation actually work.  A
language model asked for raw joint angles produces noise; asked to *choose and
time* poses from a named vocabulary, it does well, because that is a planning
problem rather than a numerical one.  So the model never emits rotations — it
emits a schedule over these names, and the quality floor is set here, by hand,
once.

Poses are per-part XYZ Euler angles in degrees relative to the rig's rest pose,
matching ``CFrame.Angles(x, y, z)``.  Unlisted parts stay at rest.  For an R15
part whose bone hangs along local -Y:

* positive X swings the bone forwards (shoulder flexion, elbow bend),
* negative X swings it backwards (knee flexion),
* the sign of Z abducts towards the character's right,
* Y twists the bone about its own length.

Left-side poses are authored and their right-side counterparts derived, so the
two never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Angles = tuple[float, float, float]
PoseData = dict[str, Angles]


def mirror(pose: PoseData) -> PoseData:
    """Reflect a pose across the character's sagittal plane.

    Reflecting about the YZ plane negates the Y and Z Euler terms and leaves X
    alone, and swaps the Left/Right part names.  The prefix swap also covers
    R6's spaced spelling, since "Left Arm"[4:] is " Arm".
    """
    mirrored: PoseData = {}
    for part, (rx, ry, rz) in pose.items():
        if part.startswith("Left"):
            name = "Right" + part[len("Left") :]
        elif part.startswith("Right"):
            name = "Left" + part[len("Right") :]
        else:
            name = part
        mirrored[name] = (rx, -ry, -rz)
    return mirrored


def blend_poses(a: PoseData, b: PoseData, t: float) -> PoseData:
    """Linear blend in Euler space, for authoring convenience only.

    Runtime interpolation happens on quaternions in :mod:`linen.generate.synth`;
    this exists so derived poses in this file stay one line long.
    """
    parts = set(a) | set(b)
    out: PoseData = {}
    for part in parts:
        pa = a.get(part, (0.0, 0.0, 0.0))
        pb = b.get(part, (0.0, 0.0, 0.0))
        out[part] = tuple(x + (y - x) * t for x, y in zip(pa, pb))  # type: ignore[assignment]
    return out


# ---------------------------------------------------------------------------
# static poses
# ---------------------------------------------------------------------------
REST: PoseData = {}

STAND_RELAXED: PoseData = {
    # Arms never hang perfectly flat on a real body; a few degrees of abduction
    # and elbow bend is the difference between "posed" and "mannequin".
    "LeftUpperArm": (2.0, 0.0, -7.0),
    "LeftLowerArm": (9.0, 0.0, -3.0),
    "LeftHand": (4.0, 0.0, 0.0),
    "RightUpperArm": (2.0, 0.0, 7.0),
    "RightLowerArm": (9.0, 0.0, 3.0),
    "RightHand": (4.0, 0.0, 0.0),
    "UpperTorso": (2.0, 0.0, 0.0),
    "LeftUpperLeg": (-1.0, 0.0, -1.0),
    "RightUpperLeg": (-1.0, 0.0, 1.0),
    "LeftLowerLeg": (-2.0, 0.0, 0.0),
    "RightLowerLeg": (-2.0, 0.0, 0.0),
}

T_POSE: PoseData = {
    "LeftUpperArm": (0.0, 0.0, -90.0),
    "RightUpperArm": (0.0, 0.0, 90.0),
}

CROUCH: PoseData = {
    "LowerTorso": (25.0, 0.0, 0.0),
    "UpperTorso": (15.0, 0.0, 0.0),
    "Head": (-20.0, 0.0, 0.0),
    "LeftUpperLeg": (55.0, 0.0, -6.0),
    "RightUpperLeg": (55.0, 0.0, 6.0),
    "LeftLowerLeg": (-95.0, 0.0, 0.0),
    "RightLowerLeg": (-95.0, 0.0, 0.0),
    "LeftFoot": (40.0, 0.0, 0.0),
    "RightFoot": (40.0, 0.0, 0.0),
    "LeftUpperArm": (-25.0, 0.0, -12.0),
    "RightUpperArm": (-25.0, 0.0, 12.0),
    "LeftLowerArm": (35.0, 0.0, 0.0),
    "RightLowerArm": (35.0, 0.0, 0.0),
}

JUMP_TAKEOFF: PoseData = {
    "LowerTorso": (-8.0, 0.0, 0.0),
    "UpperTorso": (-6.0, 0.0, 0.0),
    "LeftUpperArm": (-70.0, 0.0, -14.0),
    "RightUpperArm": (-70.0, 0.0, 14.0),
    "LeftLowerArm": (12.0, 0.0, 0.0),
    "RightLowerArm": (12.0, 0.0, 0.0),
    "LeftUpperLeg": (-12.0, 0.0, -3.0),
    "RightUpperLeg": (-12.0, 0.0, 3.0),
    "LeftFoot": (-30.0, 0.0, 0.0),
    "RightFoot": (-30.0, 0.0, 0.0),
}

JUMP_APEX: PoseData = {
    "UpperTorso": (6.0, 0.0, 0.0),
    "LeftUpperArm": (-120.0, 0.0, -25.0),
    "RightUpperArm": (-120.0, 0.0, 25.0),
    "LeftLowerArm": (25.0, 0.0, 0.0),
    "RightLowerArm": (25.0, 0.0, 0.0),
    "LeftUpperLeg": (35.0, 0.0, -5.0),
    "RightUpperLeg": (20.0, 0.0, 5.0),
    "LeftLowerLeg": (-55.0, 0.0, 0.0),
    "RightLowerLeg": (-30.0, 0.0, 0.0),
}

LAND: PoseData = blend_poses(CROUCH, STAND_RELAXED, 0.35)

SIT: PoseData = {
    "LowerTorso": (8.0, 0.0, 0.0),
    "LeftUpperLeg": (88.0, 0.0, -5.0),
    "RightUpperLeg": (88.0, 0.0, 5.0),
    "LeftLowerLeg": (-88.0, 0.0, 0.0),
    "RightLowerLeg": (-88.0, 0.0, 0.0),
    "LeftUpperArm": (10.0, 0.0, -9.0),
    "RightUpperArm": (10.0, 0.0, 9.0),
    "LeftLowerArm": (20.0, 0.0, 0.0),
    "RightLowerArm": (20.0, 0.0, 0.0),
}

# The wave lives in elbow *flexion* plus forearm twist, not in bending the
# forearm sideways — an elbow is a hinge, and a pose that ignores that reads
# fine under an Animator and snaps the moment the ragdoll takes over.
_WAVE_LEFT_UP: PoseData = {
    "LeftUpperArm": (0.0, 0.0, -150.0),
    "LeftLowerArm": (55.0, -15.0, 0.0),
    "LeftHand": (0.0, 0.0, -12.0),
    "UpperTorso": (0.0, -6.0, 0.0),
}
_WAVE_LEFT_OUT: PoseData = {
    "LeftUpperArm": (0.0, 0.0, -150.0),
    "LeftLowerArm": (100.0, 15.0, 0.0),
    "LeftHand": (0.0, 0.0, 12.0),
    "UpperTorso": (0.0, -6.0, 0.0),
}

_PUNCH_LEFT_WINDUP: PoseData = {
    "UpperTorso": (0.0, 28.0, 0.0),
    "LowerTorso": (0.0, 10.0, 0.0),
    "LeftUpperArm": (-20.0, 0.0, -30.0),
    "LeftLowerArm": (110.0, 0.0, 0.0),
    "RightUpperArm": (35.0, 0.0, 18.0),
    "RightLowerArm": (80.0, 0.0, 0.0),
    "LeftUpperLeg": (-6.0, 0.0, -4.0),
}
_PUNCH_LEFT_EXTEND: PoseData = {
    "UpperTorso": (4.0, -32.0, 0.0),
    "LowerTorso": (0.0, -14.0, 0.0),
    "LeftUpperArm": (88.0, 0.0, -14.0),
    "LeftLowerArm": (6.0, 0.0, 0.0),
    "LeftHand": (0.0, 0.0, 0.0),
    "RightUpperArm": (10.0, 0.0, 22.0),
    "RightLowerArm": (95.0, 0.0, 0.0),
    "LeftUpperLeg": (10.0, 0.0, -4.0),
    "RightUpperLeg": (-10.0, 0.0, 4.0),
}

_POINT_LEFT: PoseData = {
    "UpperTorso": (0.0, -10.0, 0.0),
    "LeftUpperArm": (80.0, 0.0, -10.0),
    "LeftLowerArm": (8.0, 0.0, 0.0),
    "LeftHand": (5.0, 0.0, 0.0),
}

# --- reaction and conversation --------------------------------------------
STEP_BACK: PoseData = {
    "LowerTorso": (-6.0, 0.0, 0.0),
    "UpperTorso": (-4.0, 0.0, 0.0),
    "Head": (3.0, 0.0, 0.0),
    "LeftUpperLeg": (-30.0, 0.0, -4.0),
    "LeftLowerLeg": (-24.0, 0.0, 0.0),
    "LeftFoot": (-12.0, 0.0, 0.0),
    "RightUpperLeg": (14.0, 0.0, 4.0),
    "RightLowerLeg": (-10.0, 0.0, 0.0),
    "LeftUpperArm": (-18.0, 0.0, -15.0),
    "LeftLowerArm": (32.0, 0.0, 0.0),
    "RightUpperArm": (-18.0, 0.0, 15.0),
    "RightLowerArm": (32.0, 0.0, 0.0),
}

#: Taking a hit: the torso folds away from the impact and the head goes with
#: it, which is what sells a punch that never actually touches anything.
FLINCH: PoseData = {
    "LowerTorso": (-12.0, 8.0, 0.0),
    "UpperTorso": (-18.0, 14.0, 0.0),
    "Head": (16.0, 22.0, 0.0),
    "LeftUpperArm": (-48.0, 0.0, -30.0),
    "LeftLowerArm": (100.0, 0.0, 0.0),
    "RightUpperArm": (-42.0, 0.0, 26.0),
    "RightLowerArm": (96.0, 0.0, 0.0),
    "LeftUpperLeg": (12.0, 0.0, -6.0),
    "LeftLowerLeg": (-20.0, 0.0, 0.0),
    "RightUpperLeg": (-14.0, 0.0, 6.0),
    "RightLowerLeg": (-12.0, 0.0, 0.0),
}

_TALK_OPEN: PoseData = {
    "UpperTorso": (2.0, -5.0, 0.0),
    "Head": (-3.0, -7.0, 0.0),
    "LeftUpperArm": (30.0, 0.0, -24.0),
    "LeftLowerArm": (72.0, -20.0, 0.0),
    "LeftHand": (0.0, 0.0, -12.0),
    "RightUpperArm": (20.0, 0.0, 20.0),
    "RightLowerArm": (56.0, 20.0, 0.0),
}
_TALK_CLOSE: PoseData = {
    "UpperTorso": (2.0, 6.0, 0.0),
    "Head": (2.0, 8.0, 0.0),
    "LeftUpperArm": (16.0, 0.0, -14.0),
    "LeftLowerArm": (50.0, -10.0, 0.0),
    "RightUpperArm": (34.0, 0.0, 18.0),
    "RightLowerArm": (80.0, 12.0, 0.0),
    "RightHand": (0.0, 0.0, 10.0),
}

# R15 has no jaw, so "talking" is gesture and head motion. A dynamic head's
# FaceControls would carry the mouth, and that is a separate rig entirely.
_NOD_DOWN: PoseData = {"Head": (22.0, 0.0, 0.0), "UpperTorso": (3.0, 0.0, 0.0)}
_NOD_UP: PoseData = {"Head": (-8.0, 0.0, 0.0)}
_SHAKE_LEFT: PoseData = {"Head": (0.0, 26.0, 0.0), "UpperTorso": (0.0, 5.0, 0.0)}

CELEBRATE: PoseData = {
    "UpperTorso": (-8.0, 0.0, 0.0),
    "Head": (-12.0, 0.0, 0.0),
    "LeftUpperArm": (-10.0, 0.0, -160.0),
    "RightUpperArm": (-10.0, 0.0, 160.0),
    "LeftLowerArm": (0.0, 0.0, -20.0),
    "RightLowerArm": (0.0, 0.0, 20.0),
    "LeftUpperLeg": (-4.0, 0.0, -6.0),
    "RightUpperLeg": (-4.0, 0.0, 6.0),
}

# --- locomotion keys -------------------------------------------------------
# A gait cycle is four keys: left contact, left passing, right contact (the
# mirror of left contact), right passing.  Authoring half of it and mirroring
# the rest is what keeps a walk symmetric.
_WALK_CONTACT_LEFT: PoseData = {
    "LowerTorso": (3.0, -4.0, 0.0),
    "UpperTorso": (2.0, 5.0, 0.0),
    "LeftUpperLeg": (26.0, 0.0, -3.0),
    "LeftLowerLeg": (-6.0, 0.0, 0.0),
    "LeftFoot": (6.0, 0.0, 0.0),
    "RightUpperLeg": (-22.0, 0.0, 3.0),
    "RightLowerLeg": (-16.0, 0.0, 0.0),
    "RightFoot": (-14.0, 0.0, 0.0),
    "LeftUpperArm": (-24.0, 0.0, -8.0),
    "LeftLowerArm": (16.0, 0.0, 0.0),
    "RightUpperArm": (26.0, 0.0, 8.0),
    "RightLowerArm": (24.0, 0.0, 0.0),
}
_WALK_PASS_LEFT: PoseData = {
    "LowerTorso": (3.0, 0.0, 0.0),
    "UpperTorso": (2.0, 0.0, 0.0),
    "LeftUpperLeg": (4.0, 0.0, -3.0),
    "LeftLowerLeg": (-4.0, 0.0, 0.0),
    "LeftFoot": (0.0, 0.0, 0.0),
    "RightUpperLeg": (2.0, 0.0, 3.0),
    "RightLowerLeg": (-38.0, 0.0, 0.0),
    "RightFoot": (12.0, 0.0, 0.0),
    "LeftUpperArm": (-4.0, 0.0, -8.0),
    "LeftLowerArm": (14.0, 0.0, 0.0),
    "RightUpperArm": (4.0, 0.0, 8.0),
    "RightLowerArm": (16.0, 0.0, 0.0),
}
_RUN_CONTACT_LEFT: PoseData = {
    "LowerTorso": (12.0, -6.0, 0.0),
    "UpperTorso": (10.0, 8.0, 0.0),
    "Head": (-10.0, 0.0, 0.0),
    "LeftUpperLeg": (42.0, 0.0, -3.0),
    "LeftLowerLeg": (-22.0, 0.0, 0.0),
    "LeftFoot": (10.0, 0.0, 0.0),
    "RightUpperLeg": (-38.0, 0.0, 3.0),
    "RightLowerLeg": (-58.0, 0.0, 0.0),
    "RightFoot": (-20.0, 0.0, 0.0),
    "LeftUpperArm": (-62.0, 0.0, -12.0),
    "LeftLowerArm": (85.0, 0.0, 0.0),
    "RightUpperArm": (58.0, 0.0, 12.0),
    "RightLowerArm": (80.0, 0.0, 0.0),
}
_RUN_PASS_LEFT: PoseData = {
    "LowerTorso": (12.0, 0.0, 0.0),
    "UpperTorso": (10.0, 0.0, 0.0),
    "Head": (-10.0, 0.0, 0.0),
    "LeftUpperLeg": (6.0, 0.0, -3.0),
    "LeftLowerLeg": (-14.0, 0.0, 0.0),
    "LeftFoot": (4.0, 0.0, 0.0),
    "RightUpperLeg": (14.0, 0.0, 3.0),
    "RightLowerLeg": (-105.0, 0.0, 0.0),
    "RightFoot": (18.0, 0.0, 0.0),
    "LeftUpperArm": (-25.0, 0.0, -12.0),
    "LeftLowerArm": (80.0, 0.0, 0.0),
    "RightUpperArm": (20.0, 0.0, 12.0),
    "RightLowerArm": (80.0, 0.0, 0.0),
}

POSES: dict[str, PoseData] = {
    "rest": REST,
    "stand_relaxed": STAND_RELAXED,
    "t_pose": T_POSE,
    "crouch": CROUCH,
    "jump_takeoff": JUMP_TAKEOFF,
    "jump_apex": JUMP_APEX,
    "land": LAND,
    "sit": SIT,
    "celebrate": CELEBRATE,
    "step_back": STEP_BACK,
    "flinch": FLINCH,
    "talk_open": _TALK_OPEN,
    "talk_close": _TALK_CLOSE,
    "nod_down": _NOD_DOWN,
    "nod_up": _NOD_UP,
    "shake_left": _SHAKE_LEFT,
    "shake_right": mirror(_SHAKE_LEFT),
    "wave_left_up": _WAVE_LEFT_UP,
    "wave_left_out": _WAVE_LEFT_OUT,
    "wave_right_up": mirror(_WAVE_LEFT_UP),
    "wave_right_out": mirror(_WAVE_LEFT_OUT),
    "punch_left_windup": _PUNCH_LEFT_WINDUP,
    "punch_left_extend": _PUNCH_LEFT_EXTEND,
    "punch_right_windup": mirror(_PUNCH_LEFT_WINDUP),
    "punch_right_extend": mirror(_PUNCH_LEFT_EXTEND),
    "point_left": _POINT_LEFT,
    "point_right": mirror(_POINT_LEFT),
    "walk_contact_left": _WALK_CONTACT_LEFT,
    "walk_pass_left": _WALK_PASS_LEFT,
    "walk_contact_right": mirror(_WALK_CONTACT_LEFT),
    "walk_pass_right": mirror(_WALK_PASS_LEFT),
    "run_contact_left": _RUN_CONTACT_LEFT,
    "run_pass_left": _RUN_PASS_LEFT,
    "run_contact_right": mirror(_RUN_CONTACT_LEFT),
    "run_pass_right": mirror(_RUN_PASS_LEFT),
}


@dataclass(frozen=True)
class Cycle:
    """A looping sequence of poses at fractional phases of one cycle."""

    name: str
    keys: tuple[tuple[float, str], ...]
    #: Suggested cycles per second, used when a plan does not specify one.
    default_rate: float = 1.0
    tags: tuple[str, ...] = field(default=())


CYCLES: dict[str, Cycle] = {
    "walk": Cycle(
        "walk",
        (
            (0.0, "walk_contact_left"),
            (0.25, "walk_pass_left"),
            (0.5, "walk_contact_right"),
            (0.75, "walk_pass_right"),
        ),
        default_rate=0.9,
        tags=("locomotion",),
    ),
    "run": Cycle(
        "run",
        (
            (0.0, "run_contact_left"),
            (0.25, "run_pass_left"),
            (0.5, "run_contact_right"),
            (0.75, "run_pass_right"),
        ),
        default_rate=1.6,
        tags=("locomotion",),
    ),
    # Both hands, because a plan that asks to wave with the left one and gets
    # the right one back is worse than not offering the choice at all.
    "wave_left": Cycle(
        "wave_left",
        ((0.0, "wave_left_up"), (0.5, "wave_left_out")),
        default_rate=2.0,
        tags=("gesture",),
    ),
    "wave_right": Cycle(
        "wave_right",
        ((0.0, "wave_right_up"), (0.5, "wave_right_out")),
        default_rate=2.0,
        tags=("gesture",),
    ),
    "talk": Cycle(
        "talk",
        ((0.0, "talk_open"), (0.5, "talk_close")),
        default_rate=1.1,
        tags=("gesture", "conversation"),
    ),
    "nod": Cycle(
        "nod",
        ((0.0, "nod_up"), (0.5, "nod_down")),
        default_rate=1.5,
        tags=("gesture", "conversation"),
    ),
    "shake_head": Cycle(
        "shake_head",
        ((0.0, "shake_left"), (0.5, "shake_right")),
        default_rate=1.8,
        tags=("gesture", "conversation"),
    ),
}

#: Kept so plans written against the single-handed vocabulary still load.
CYCLES["wave"] = CYCLES["wave_right"]


def pose_names() -> tuple[str, ...]:
    return tuple(sorted(POSES))


def cycle_names() -> tuple[str, ...]:
    return tuple(sorted(CYCLES))


def resolve_pose(name: str) -> PoseData:
    try:
        return POSES[name]
    except KeyError:
        raise KeyError(
            f"unknown pose {name!r}; the vocabulary is: {', '.join(pose_names())}"
        ) from None
