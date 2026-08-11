"""Rig description shared by the retargeter, the exporter and the viewport.

A rig is a tree of *parts* joined by ``Motor6D`` instances.  Roblox stores an
animation as a ``KeyframeSequence`` of ``Pose`` instances that mirror the part
tree, and each ``Pose.CFrame`` is a transform applied *on top of* the joint's
rest pose rather than an absolute orientation.  That single fact is what makes
this pipeline tractable: we never need the rig's real part sizes to produce a
valid animation, only its topology.  Sizes live here purely so the viewport can
draw something recognisable.

Both stock rigs rest with every part axis-aligned — arms and legs hang straight
down — so a part's rest rotation is the identity and the pose we export is
exactly the local rotation we solve for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

Vec3 = tuple[float, float, float]


class Roll(str, Enum):
    """How a bone's twist around its own length is resolved.

    Aiming a bone at a target pins only two of three rotational degrees of
    freedom.  Left unconstrained, the remaining twist wanders between frames
    and elbows flip inside out, so every bone names a source for it.
    """

    #: Sideways axis from a left/right landmark pair — shoulders, hips, ears.
    #: Supplies the part's local +X (the character's own right).
    LATERAL = "lateral"
    #: Normal of the plane through this bone and the next one down the chain.
    #: This is what makes elbows and knees hinge the way real ones do.
    #: Supplies the part's local +X.
    CHAIN_PLANE = "chain_plane"
    #: Copy the parent's local +Z (its back). For hands, which barely have
    #: usable landmarks of their own.
    PARENT_BACK = "parent_back"
    #: Use the parent's local +Y as this part's back. Feet point forwards, so
    #: their own "back" is the shin's up axis.
    PARENT_UP = "parent_up"


@dataclass(frozen=True)
class Part:
    """One rigid body in the rig."""

    name: str
    #: Parent part, or ``None`` for the root.
    parent: str | None
    #: ``Motor6D.Name`` of the joint attaching this part to its parent.
    joint: str | None
    #: Direction, in the part's own rest space, that the bone extends towards.
    #: R15 limbs hang downwards, so their bone runs along local -Y.
    aim_axis: Vec3 = (0.0, -1.0, 0.0)
    #: The part-space axis whose *world* direction the twist source supplies.
    #: :attr:`Roll.LATERAL` and :attr:`Roll.CHAIN_PLANE` both hand back a
    #: sideways axis, so those parts reference local +X; hands reference their
    #: back and feet their up.  Solving pairs ``(aim_axis, roll_axis)`` in part
    #: space against ``(bone direction, twist hint)`` in world space, so the two
    #: must describe the same pair of directions or every limb comes out
    #: mirrored.  Must not be colinear with ``aim_axis``.
    roll_axis: Vec3 = (1.0, 0.0, 0.0)
    #: Approximate rest size in studs. Preview only — never used for export.
    size: Vec3 = (1.0, 1.0, 1.0)
    #: Offset from the parent part's centre to this part's centre in the rest
    #: pose, in studs. Preview only.
    rest_offset: Vec3 = (0.0, 0.0, 0.0)

    @property
    def pivot(self) -> Vec3:
        """Where the joint sits, relative to the parent's centre. Preview only.

        A joint attaches at the end of the part its bone points away from — the
        shoulder at the top of an arm that hangs down — so the pivot is the
        part's centre walked back along :attr:`aim_axis` by half the part's
        extent on that axis.  Real rigs carry this in the Motor6D's C0/C1; we
        derive it because the exporter never needs it and only the viewport
        would notice it being slightly off.
        """
        extent = sum(abs(a) * s for a, s in zip(self.aim_axis, self.size)) / 2.0
        return tuple(o - a * extent for o, a in zip(self.rest_offset, self.aim_axis))  # type: ignore[return-value]


@dataclass(frozen=True)
class BoneSource:
    """How to reconstruct a part's world orientation from tracked landmarks.

    ``origin`` and ``tip`` name landmarks, averaged when several are given, so
    the bone direction is ``mean(tip) - mean(origin)``.
    """

    part: str
    origin: tuple[str, ...]
    tip: tuple[str, ...]
    roll: Roll = Roll.LATERAL
    #: For :attr:`Roll.LATERAL` — the landmark pair ``(left, right)`` whose
    #: difference points along the character's own right.
    lateral: tuple[str, str] | None = None
    #: For :attr:`Roll.CHAIN_PLANE` — the three landmarks spanning the hinge,
    #: e.g. shoulder/elbow/wrist.  Both bones either side of a hinge quote the
    #: same triple, because it is the hinge that fixes their shared twist: a
    #: shin's roll comes from the knee, not from where the toes point.
    plane: tuple[str, str, str] | None = None
    #: Knees hinge backwards where elbows hinge forwards, which flips the sign
    #: of the chain normal.
    invert_chain_normal: bool = False


@dataclass(frozen=True)
class RigDefinition:
    name: str
    parts: tuple[Part, ...]
    sources: tuple[BoneSource, ...]
    #: Roblox's own conversion is 1 stud = 0.28 m; used for root translation.
    studs_per_metre: float = 1.0 / 0.28

    _by_name: dict[str, Part] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_name", {p.name: p for p in self.parts})
        if len(self._by_name) != len(self.parts):
            raise ValueError(f"{self.name}: duplicate part names")
        seen: set[str] = set()
        for part in self.parts:
            if part.parent is None:
                if seen:
                    raise ValueError(f"{self.name}: more than one root part")
            elif part.parent not in seen:
                raise ValueError(
                    f"{self.name}: {part.name!r} precedes its parent {part.parent!r}; "
                    "parts must be listed parent-first"
                )
            seen.add(part.name)
        for source in self.sources:
            if source.part not in seen:
                raise ValueError(f"{self.name}: source targets unknown part {source.part!r}")
            if source.roll is Roll.LATERAL and not source.lateral:
                raise ValueError(f"{self.name}: {source.part!r} needs a lateral pair")
            if source.roll is Roll.CHAIN_PLANE and not source.plane:
                raise ValueError(f"{self.name}: {source.part!r} needs a hinge plane")

    @property
    def root(self) -> Part:
        return self.parts[0]

    def part(self, name: str) -> Part:
        return self._by_name[name]

    def children(self, name: str) -> tuple[Part, ...]:
        return tuple(p for p in self.parts if p.parent == name)

    def source(self, part: str) -> BoneSource | None:
        for source in self.sources:
            if source.part == part:
                return source
        return None

    @property
    def animated_parts(self) -> tuple[str, ...]:
        """Every part below the root, parent before child."""
        return tuple(p.name for p in self.parts[1:])
