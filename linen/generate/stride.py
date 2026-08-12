"""How far a gait cycle carries the character.

This is the number that kills foot sliding. A walk cycle animates at some
natural speed — the one implied by how far apart its contact poses put the feet
— and if the character's ground speed does not match, the feet skate. The fix
is not a better animation; it is playing the animation at ``groundSpeed /
naturalSpeed`` and letting the stride do the rest.

Deriving it from the poses rather than typing a number in means it stays right
when the poses are edited, which is the whole point: a wider contact pose is a
longer stride, automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..rigs import RigDefinition, get_rig
from ..rigs.kinematics import step_length
from .posebook import CYCLES, Cycle, resolve_pose


@dataclass(frozen=True)
class Stride:
    """What one turn of a gait cycle covers."""

    cycle: str
    #: Studs travelled per full cycle. Two steps for a normal gait.
    distance: float
    #: Studs per second at the cycle's own default rate.
    speed: float
    #: Steps in one cycle — two for a biped walk, and the reason `distance` is
    #: not just the widest contact pose.
    steps: int

    @property
    def playback_rate_for(self) -> float:
        return self.speed


def cycle_stride(cycle: Cycle, rig: RigDefinition) -> Stride:
    """Measure a cycle's stride by posing the rig at each of its keys.

    The widest key is the contact pose — the moment both feet are planted and
    furthest apart — and that separation is one step.
    """
    widest = 0.0
    for _, pose_name in cycle.keys:
        widest = max(widest, step_length(rig, resolve_pose(pose_name)))

    # A gait cycle is left contact, pass, right contact, pass: two steps. A
    # gesture cycle has no contacts and covers no ground.
    steps = 2 if widest > 0.05 else 0
    distance = widest * steps
    return Stride(
        cycle=cycle.name,
        distance=round(distance, 4),
        speed=round(distance * cycle.default_rate, 4),
        steps=steps,
    )


def all_strides(rig_name: str = "R15") -> dict[str, Stride]:
    rig = get_rig(rig_name)
    return {name: cycle_stride(cycle, rig) for name, cycle in sorted(CYCLES.items())}


def locomotion_strides(rig_name: str = "R15") -> dict[str, Stride]:
    """Only the cycles that actually move the character."""
    return {
        name: stride
        for name, stride in all_strides(rig_name).items()
        if stride.steps > 0
    }
