"""Anatomical joint limits and drive gains, for physics-driven characters.

An active ragdoll is only as good as its constraints. Give every joint the same
cone and the character folds in ways a body cannot, which reads as the classic
limp-noodle ragdoll no matter how good the drive is. So each joint carries the
range a real one has, and — the part naive setups miss — the *right kind* of
constraint: an elbow is a hinge, not a cone. A ball-and-socket elbow can bend
sideways, and it will, at the first impulse.

These numbers are the data half of the runtime system. They are defined here,
tested here, and emitted to Luau, so the physics rig and the animation rig
cannot disagree about what a shoulder can do.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JointKind(str, Enum):
    """Which Roblox constraint expresses this joint."""

    #: BallSocketConstraint: a swing cone plus a twist range. Shoulders, hips,
    #: the spine, the neck.
    BALL = "ball"
    #: HingeConstraint: one axis, one range. Elbows and knees, which is the
    #: whole reason this enum exists.
    HINGE = "hinge"
    #: No constraint. The joint is welded during ragdoll — the root, which is
    #: the physics capsule rather than a body part.
    FIXED = "fixed"


@dataclass(frozen=True)
class JointLimit:
    """What one joint may do, and how hard it is driven back to its pose.

    Angles are degrees. For :attr:`JointKind.BALL`, ``swing`` is the half-angle
    of the cone the bone may tilt within and ``twist`` is the rotation about the
    bone's own length. For :attr:`JointKind.HINGE`, ``lower``/``upper`` bound
    the single axis and ``swing``/``twist`` are unused.
    """

    joint: str
    kind: JointKind
    swing: float = 0.0
    twist: tuple[float, float] = (0.0, 0.0)
    lower: float = 0.0
    upper: float = 0.0
    #: AlignOrientation Responsiveness driving this joint back to the animated
    #: pose. Proximal joints carry more mass and need more authority; a wrist
    #: driven as hard as a hip looks stiff.
    responsiveness: float = 25.0
    #: Newton-metres available to that drive. Zero means "let it hang".
    max_torque: float = 8000.0

    def validate(self) -> None:
        if self.kind is JointKind.HINGE:
            if self.lower >= self.upper:
                raise ValueError(
                    f"{self.joint}: hinge range {self.lower}..{self.upper} is empty"
                )
            if self.upper - self.lower > 180.0:
                raise ValueError(
                    f"{self.joint}: hinge range spans {self.upper - self.lower} degrees, "
                    "which no hinge joint in a body does"
                )
        elif self.kind is JointKind.BALL:
            if not 0.0 < self.swing <= 180.0:
                raise ValueError(f"{self.joint}: swing {self.swing} is outside 0-180")
            if self.twist[0] >= self.twist[1]:
                raise ValueError(
                    f"{self.joint}: twist range {self.twist} is empty"
                )
        if self.responsiveness < 0 or self.max_torque < 0:
            raise ValueError(f"{self.joint}: drive gains cannot be negative")


def _ball(
    joint: str,
    swing: float,
    twist: tuple[float, float],
    responsiveness: float,
    max_torque: float,
) -> JointLimit:
    return JointLimit(joint, JointKind.BALL, swing=swing, twist=twist,
                      responsiveness=responsiveness, max_torque=max_torque)


def _hinge(
    joint: str, lower: float, upper: float, responsiveness: float, max_torque: float
) -> JointLimit:
    return JointLimit(joint, JointKind.HINGE, lower=lower, upper=upper,
                      responsiveness=responsiveness, max_torque=max_torque)


def _mirror(limit: JointLimit) -> JointLimit:
    """The other side of the body, so the two can never drift apart."""
    from dataclasses import replace

    if limit.joint.startswith("Left"):
        name = "Right" + limit.joint[len("Left") :]
    elif limit.joint.startswith("Right"):
        name = "Left" + limit.joint[len("Right") :]
    else:
        return limit
    # A hinge's range does *not* mirror. Both elbows hinge about their own local
    # +X, and reflecting a pose leaves its X term alone while negating Y and Z —
    # so the flexion range is the same on both sides, and only the twist about
    # the bone, which rides on the Y term, changes sign.
    if limit.kind is JointKind.HINGE:
        return replace(limit, joint=name)
    return replace(limit, joint=name, twist=(-limit.twist[1], -limit.twist[0]))


# R15. Ranges are the usable end of normal human range of motion, widened
# enough that the authored pose book stays inside them — a pose the constraints
# forbid snaps the instant physics takes over, which is exactly the artefact
# this data exists to prevent.
_R15_LEFT: tuple[JointLimit, ...] = (
    # Shoulder: the most mobile joint in the body. Arms straight overhead is
    # ~170 degrees of abduction, and the pose book uses it.
    _ball("LeftShoulder", swing=170.0, twist=(-75.0, 75.0), responsiveness=30.0,
          max_torque=9000.0),
    # Elbow: flexion only. Hyperextension past zero is an injury, not a pose.
    _hinge("LeftElbow", lower=0.0, upper=150.0, responsiveness=35.0, max_torque=5000.0),
    _ball("LeftWrist", swing=70.0, twist=(-85.0, 85.0), responsiveness=45.0,
          max_torque=1500.0),
    # Hip: 95 degrees of flexion covers sitting.
    _ball("LeftHip", swing=100.0, twist=(-45.0, 50.0), responsiveness=28.0,
          max_torque=12000.0),
    # Knee: flexes backwards, hence the negative range.
    _hinge("LeftKnee", lower=-150.0, upper=0.0, responsiveness=32.0, max_torque=9000.0),
    _ball("LeftAnkle", swing=50.0, twist=(-25.0, 25.0), responsiveness=40.0,
          max_torque=3000.0),
)

R15_LIMITS: dict[str, JointLimit] = {
    limit.joint: limit
    for limit in (
        # The root is the physics capsule, not a body part: welding it is what
        # keeps a driven ragdoll upright instead of pivoting about its middle.
        JointLimit("Root", JointKind.FIXED),
        _ball("Waist", swing=40.0, twist=(-40.0, 40.0), responsiveness=22.0,
              max_torque=15000.0),
        _ball("Neck", swing=50.0, twist=(-70.0, 70.0), responsiveness=38.0,
              max_torque=4000.0),
        *_R15_LEFT,
        *(_mirror(limit) for limit in _R15_LEFT),
    )
}

# R6 has one part per limb, so its joints carry the whole limb's range and get
# no hinges at all. The shoulder cone has to cover what a shoulder *and* an
# elbow did, which is part of why R6 ragdolls read as looser.
R6_LIMITS: dict[str, JointLimit] = {
    limit.joint: limit
    for limit in (
        JointLimit("RootJoint", JointKind.FIXED),
        _ball("Neck", swing=50.0, twist=(-70.0, 70.0), responsiveness=38.0,
              max_torque=4000.0),
        _ball("Left Shoulder", swing=170.0, twist=(-75.0, 75.0), responsiveness=30.0,
              max_torque=9000.0),
        _ball("Right Shoulder", swing=170.0, twist=(-75.0, 75.0), responsiveness=30.0,
              max_torque=9000.0),
        _ball("Left Hip", swing=100.0, twist=(-45.0, 50.0), responsiveness=28.0,
              max_torque=12000.0),
        _ball("Right Hip", swing=100.0, twist=(-45.0, 50.0), responsiveness=28.0,
              max_torque=12000.0),
    )
}

LIMITS: dict[str, dict[str, JointLimit]] = {"R15": R15_LIMITS, "R6": R6_LIMITS}


def limits_for(rig_name: str) -> dict[str, JointLimit]:
    try:
        return LIMITS[rig_name.upper()]
    except KeyError:
        raise ValueError(
            f"no joint limits for rig {rig_name!r}; known: {', '.join(sorted(LIMITS))}"
        ) from None


def validate_all() -> None:
    for table in LIMITS.values():
        for limit in table.values():
            limit.validate()
