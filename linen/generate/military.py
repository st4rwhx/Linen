"""A pose vocabulary for a soldier, and the cycles built from it.

Style, in animation, is not a filter applied afterwards. It is a set of poses,
and the poses here are what separate a soldier from a person: **the weapon owns
the upper body**. A civilian's arms swing freely and counter the legs. A
soldier's arms are a closed triangle around a rifle, and they stay there while
everything below them works.

That single fact drives every pose in this file, and it is the one an audience
reads first, before stride length or knee bend or lean.

The rest is what the closed triangle costs the body, and it is all borrowed from
how soldiers are actually taught to move:

**The knees never lock.** Weight is carried low and the knees stay soft through
the whole gait, because a locked knee sends the shock straight up the spine and
into the sight picture. It is what makes a tactical walk read as deliberate
rather than slow.

**The head stays level.** Everything else may bob; the eyes do not, because the
eyes are aimed. The torso absorbs what the legs produce, which is the opposite
of an ordinary walk where the shoulders swing to counterbalance.

**Steps are shorter and flatter.** A long stride commits weight to a foot that
is not yet down. A soldier keeps a foot near the ground and rolls onto it.

Angles are per-part XYZ Euler degrees against the rig's rest pose, exactly as
in :mod:`linen.generate.posebook`. For an R15 limb hanging along local -Y,
positive X swings it forwards, and the sign of Z abducts it towards the
character's right.

Left-side poses are authored and the right derived where the pose is symmetric.
The weapon carry is **not** symmetric — a rifle is shouldered on one side — so
those poses are written out in full.
"""

from __future__ import annotations

from .posebook import Angles, Cycle, PoseData, blend_poses

#: A right-handed carry: firing hand at the grip by the right pectoral, support
#: hand forward and across on the handguard, both elbows down. Elbows down is
#: the detail that matters — flared elbows are the single clearest tell of
#: someone who has never held a rifle, and they are also what a naive
#: "arms forward" pose produces.
LOW_READY: PoseData = {
    "UpperTorso": (6.0, -8.0, 0.0),
    "Head": (-2.0, 8.0, 0.0),
    # Firing side: upper arm hangs close to the ribs, forearm folded up so the
    # hand sits at chest height.
    "RightUpperArm": (13.0, -10.0, 9.0),
    "RightLowerArm": (86.0, -30.0, 0.0),
    "RightHand": (0.0, -20.0, -12.0),
    # Support side: reaches forward and across the body, elbow lower than the
    # hand, which is what holding a handguard actually looks like.
    "LeftUpperArm": (36.0, 16.0, 22.0),
    "LeftLowerArm": (74.0, 22.0, 0.0),
    "LeftHand": (0.0, 10.0, 10.0),
}

#: Muzzle up and the stock into the shoulder pocket. Used at the top of a
#: scan and as the pose a jump lands back into.
HIGH_READY: PoseData = {
    "UpperTorso": (2.0, -10.0, 0.0),
    "Head": (0.0, 10.0, 0.0),
    "RightUpperArm": (26.0, -12.0, 20.0),
    "RightLowerArm": (92.0, -30.0, 0.0),
    "RightHand": (0.0, -22.0, -14.0),
    "LeftUpperArm": (58.0, 18.0, 16.0),
    "LeftLowerArm": (70.0, 22.0, 0.0),
    "LeftHand": (0.0, 12.0, 10.0),
}

#: Pulled in tight against the chest: through a jump, a fall, and a landing,
#: where a weapon left hanging would swing like a plank.
TUCKED: PoseData = {
    "UpperTorso": (10.0, -6.0, 0.0),
    "Head": (-4.0, 6.0, 0.0),
    "RightUpperArm": (12.0, -8.0, 10.0),
    "RightLowerArm": (96.0, -26.0, 0.0),
    "RightHand": (0.0, -18.0, -10.0),
    "LeftUpperArm": (34.0, 14.0, 10.0),
    "LeftLowerArm": (88.0, 18.0, 0.0),
    "LeftHand": (0.0, 8.0, 8.0),
}


def _carry(carry: PoseData, lower: PoseData, sway: float = 0.0) -> PoseData:
    """One pose: the weapon carry on top, the legs underneath.

    An explicit merge rather than a blend, because the carry has to win
    outright: a weapon that drifts with the gait is a weapon nobody is aiming.

    ``sway`` is the small amount the torso turns under it, in degrees, and it
    is what keeps the carry from being *welded*. Locked completely, the arms
    measured 0.0 degrees of range across a whole walk cycle — which is the
    exact signature this project's own polish pass calls a frozen pose, and it
    reads as a mannequin being slid along the floor.

    So the torso turns, the arms take **half** of it — the weapon lags the body
    slightly, which is what a mass held at arm's length does — and the head
    takes the opposite, because the eyes are aimed and stay aimed. That last
    one is the whole reason a soldier's walk looks different from a civilian's:
    everything moves except where he is looking.
    """
    posed = {**lower, **carry}
    if abs(sway) < 1e-9:
        return posed

    for part, share in (
        ("UpperTorso", 1.0),
        ("LeftUpperArm", 0.5),
        ("RightUpperArm", 0.5),
        ("Head", -1.0),
    ):
        rx, ry, rz = posed.get(part, (0.0, 0.0, 0.0))
        posed[part] = (rx, ry + sway * share, rz)
    return posed


# -- legs --------------------------------------------------------------------
#
# Knees stay bent everywhere. The numbers below never let a knee reach 0, and
# the stride is roughly two thirds of the civilian walk in `posebook`.

_PATROL_CONTACT_LEFT: PoseData = {
    "LowerTorso": (4.0, -3.0, 0.0),
    "LeftUpperLeg": (23.0, 0.0, -3.0),
    "LeftLowerLeg": (-13.0, 0.0, 0.0),
    "LeftFoot": (3.0, 0.0, 0.0),
    "RightUpperLeg": (-18.0, 0.0, 3.0),
    "RightLowerLeg": (-24.0, 0.0, 0.0),
    "RightFoot": (-8.0, 0.0, 0.0),
}

_PATROL_PASS_LEFT: PoseData = {
    "LowerTorso": (4.0, 0.0, 0.0),
    "LeftUpperLeg": (2.0, 0.0, -3.0),
    "LeftLowerLeg": (-15.0, 0.0, 0.0),
    "LeftFoot": (0.0, 0.0, 0.0),
    "RightUpperLeg": (6.0, 0.0, 3.0),
    "RightLowerLeg": (-44.0, 0.0, 0.0),
    "RightFoot": (10.0, 0.0, 0.0),
}

_ADVANCE_CONTACT_LEFT: PoseData = {
    "LowerTorso": (11.0, -3.0, 0.0),
    "LeftUpperLeg": (37.0, 0.0, -3.0),
    "LeftLowerLeg": (-20.0, 0.0, 0.0),
    "LeftFoot": (8.0, 0.0, 0.0),
    "RightUpperLeg": (-33.0, 0.0, 3.0),
    "RightLowerLeg": (-54.0, 0.0, 0.0),
    "RightFoot": (-16.0, 0.0, 0.0),
}

_ADVANCE_PASS_LEFT: PoseData = {
    "LowerTorso": (11.0, 0.0, 0.0),
    "LeftUpperLeg": (4.0, 0.0, -3.0),
    "LeftLowerLeg": (-18.0, 0.0, 0.0),
    "LeftFoot": (2.0, 0.0, 0.0),
    "RightUpperLeg": (16.0, 0.0, 3.0),
    "RightLowerLeg": (-96.0, 0.0, 0.0),
    "RightFoot": (16.0, 0.0, 0.0),
}


def _mirror_legs(pose: PoseData) -> PoseData:
    """Swap the legs only — the carry stays on the shoulder it belongs to."""
    out: PoseData = {}
    for part, (rx, ry, rz) in pose.items():
        if part.startswith("Left"):
            out["Right" + part[4:]] = (rx, -ry, -rz)
        elif part.startswith("Right"):
            out["Left" + part[5:]] = (rx, -ry, -rz)
        else:
            out[part] = (rx, -ry, -rz)
    return out


#: Weight on the right leg, left foot slightly out: a stance held for minutes,
#: not the parade rest of a rig at its origin.
_STANCE: PoseData = {
    "LowerTorso": (2.0, 0.0, -2.0),
    "LeftUpperLeg": (-2.0, 0.0, -7.0),
    "LeftLowerLeg": (-9.0, 0.0, 0.0),
    "LeftFoot": (3.0, -6.0, 0.0),
    "RightUpperLeg": (1.0, 0.0, 4.0),
    "RightLowerLeg": (-6.0, 0.0, 0.0),
    "RightFoot": (2.0, 4.0, 0.0),
}

_SCAN_LEFT: PoseData = {**_STANCE, "UpperTorso": (6.0, 4.0, 0.0), "Head": (-2.0, 22.0, 0.0)}
_SCAN_RIGHT: PoseData = {**_STANCE, "UpperTorso": (6.0, -18.0, 0.0), "Head": (-2.0, -14.0, 0.0)}

_CROUCH_LOAD: PoseData = {
    "LowerTorso": (16.0, 0.0, 0.0),
    "LeftUpperLeg": (34.0, 0.0, -4.0),
    "LeftLowerLeg": (-62.0, 0.0, 0.0),
    "LeftFoot": (26.0, 0.0, 0.0),
    "RightUpperLeg": (34.0, 0.0, 4.0),
    "RightLowerLeg": (-62.0, 0.0, 0.0),
    "RightFoot": (26.0, 0.0, 0.0),
}

_EXTEND: PoseData = {
    "LowerTorso": (4.0, 0.0, 0.0),
    "LeftUpperLeg": (-12.0, 0.0, -4.0),
    "LeftLowerLeg": (-4.0, 0.0, 0.0),
    "LeftFoot": (-18.0, 0.0, 0.0),
    "RightUpperLeg": (-12.0, 0.0, 4.0),
    "RightLowerLeg": (-4.0, 0.0, 0.0),
    "RightFoot": (-18.0, 0.0, 0.0),
}

#: Legs split fore and aft and knees soft: a soldier falling is looking for the
#: ground, not hanging in the air. It is also what makes a landing readable —
#: the pose already tells you which foot takes the weight.
_AIRBORNE: PoseData = {
    "LowerTorso": (8.0, 0.0, 0.0),
    "LeftUpperLeg": (26.0, 0.0, -6.0),
    "LeftLowerLeg": (-44.0, 0.0, 0.0),
    "LeftFoot": (10.0, 0.0, 0.0),
    "RightUpperLeg": (-6.0, 0.0, 6.0),
    "RightLowerLeg": (-30.0, 0.0, 0.0),
    "RightFoot": (2.0, 0.0, 0.0),
}

_ABSORB: PoseData = {
    "LowerTorso": (20.0, 0.0, 0.0),
    "LeftUpperLeg": (44.0, 0.0, -5.0),
    "LeftLowerLeg": (-78.0, 0.0, 0.0),
    "LeftFoot": (34.0, 0.0, 0.0),
    "RightUpperLeg": (40.0, 0.0, 5.0),
    "RightLowerLeg": (-72.0, 0.0, 0.0),
    "RightFoot": (32.0, 0.0, 0.0),
}


POSES: dict[str, PoseData] = {
    "mil_low_ready": _carry(LOW_READY, _STANCE),
    "mil_high_ready": _carry(HIGH_READY, _STANCE),
    "mil_scan_left": _carry(HIGH_READY, _SCAN_LEFT),
    "mil_scan_right": _carry(LOW_READY, _SCAN_RIGHT),
    "mil_patrol_contact_left": _carry(LOW_READY, _PATROL_CONTACT_LEFT, 4.0),
    "mil_patrol_pass_left": _carry(LOW_READY, _PATROL_PASS_LEFT, 0.0),
    "mil_patrol_contact_right": _carry(
        LOW_READY, _mirror_legs(_PATROL_CONTACT_LEFT), -4.0
    ),
    "mil_patrol_pass_right": _carry(LOW_READY, _mirror_legs(_PATROL_PASS_LEFT), 0.0),
    "mil_advance_contact_left": _carry(TUCKED, _ADVANCE_CONTACT_LEFT, 7.0),
    "mil_advance_pass_left": _carry(TUCKED, _ADVANCE_PASS_LEFT, 1.0),
    "mil_advance_contact_right": _carry(
        TUCKED, _mirror_legs(_ADVANCE_CONTACT_LEFT), -7.0
    ),
    "mil_advance_pass_right": _carry(TUCKED, _mirror_legs(_ADVANCE_PASS_LEFT), -1.0),
    "mil_crouch_load": _carry(TUCKED, _CROUCH_LOAD),
    "mil_extend": _carry(TUCKED, _EXTEND),
    "mil_airborne": _carry(TUCKED, _AIRBORNE),
    "mil_absorb": _carry(TUCKED, _ABSORB),
    "mil_settle": _carry(LOW_READY, blend_poses(_CROUCH_LOAD, _STANCE, 0.55)),
}


CYCLES: dict[str, Cycle] = {
    "mil_patrol": Cycle(
        "mil_patrol",
        (
            (0.0, "mil_patrol_contact_left"),
            (0.25, "mil_patrol_pass_left"),
            (0.5, "mil_patrol_contact_right"),
            (0.75, "mil_patrol_pass_right"),
        ),
        default_rate=0.95,
        tags=("locomotion", "military"),
    ),
    "mil_advance": Cycle(
        "mil_advance",
        (
            (0.0, "mil_advance_contact_left"),
            (0.25, "mil_advance_pass_left"),
            (0.5, "mil_advance_contact_right"),
            (0.75, "mil_advance_pass_right"),
        ),
        default_rate=1.55,
        tags=("locomotion", "military"),
    ),
    # Two scans and two holds, so the loop does not read as a metronome: the
    # eye notices a repeating interval long before it notices a repeating pose.
    "mil_watch": Cycle(
        "mil_watch",
        (
            (0.0, "mil_low_ready"),
            (0.3, "mil_scan_left"),
            (0.5, "mil_low_ready"),
            (0.72, "mil_scan_right"),
        ),
        default_rate=0.18,
        tags=("idle", "military"),
    ),
}


def register() -> None:
    """Make these available to the planner and to ``linen synth``.

    Kept as a call rather than an import side effect: a vocabulary that grows
    itself the moment a module is imported anywhere is a vocabulary nobody can
    reason about.
    """
    from . import posebook

    posebook.POSES.update(POSES)
    posebook.CYCLES.update(CYCLES)


__all__ = ["CYCLES", "HIGH_READY", "LOW_READY", "POSES", "TUCKED", "Angles", "register"]
