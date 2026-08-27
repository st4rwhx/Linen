"""Make a hand actually land on the other character.

This is the thing no library and no generation service can do, and it is the
reason a fight written from generic clips reads as two people shadow-boxing.
A capture is *solo*: it knows what a body doing a shove looks like, and it
cannot know that this hand has to close on that collar, on a character of that
height, standing there. Buying better clips does not fix it, because the
information is not in any clip.

It is fixable here, though, and cheaply, because the scene already knows
everything the solve needs: where both actors stand, how they face, and where
every joint of both bodies is on every frame. What is missing is only the last
step — bending one arm so the hand arrives.

The solve is the same analytic two-bone IK the foot planting uses, pointed at
an arm: bend the elbow to put the wrist at the right distance, then swing the
whole arm to aim it. An arm that cannot reach is aimed as far as it goes and
the shortfall is reported in studs, never hidden — a limb here has a fixed
length and pretending otherwise would mean stretching a part.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..clip import AnimationClip
from ..math3d import mat_to_quat, quat_slerp, quat_to_mat
from ..rigs.kinematics import place_rotations

#: Arm chains that can be solved. R6 has one rigid part per arm — no elbow
#: exists to bend — so it is aimed instead, the best a rigid limb can do.
CHAINS: dict[str, tuple[str, str, str]] = {
    "LeftHand": ("LeftUpperArm", "LeftLowerArm", "LeftHand"),
    "RightHand": ("RightUpperArm", "RightLowerArm", "RightHand"),
    "Left Arm": ("Left Arm", "Left Arm", "Left Arm"),
    "Right Arm": ("Right Arm", "Right Arm", "Right Arm"),
}

#: Seconds spent easing the reach in and out. Snapping an arm onto a target
#: reads as a glitch even when the target is right.
BLEND_SECONDS = 0.12


@dataclass
class Reach:
    """One hand asked to be somewhere, and how close it got."""

    actor: str
    limb: str
    target: str
    start: float
    stop: float
    #: Studs between where the hand ended and where it was asked to be, worst
    #: frame of the hold. Zero means it arrived.
    shortfall: float = 0.0

    def line(self) -> str:
        verdict = (
            "atteint" if self.shortfall < 0.15 else f"a {self.shortfall:.2f} stud pres"
        )
        return (
            f"{self.actor}.{self.limb} -> {self.target} "
            f"[{self.start:.2f}-{self.stop:.2f}s] {verdict}"
        )


def base_frame(position, facing_yaw: float) -> tuple[np.ndarray, np.ndarray]:
    """Where an actor stands, as a rotation and a translation.

    A scene places actors in the world; a clip stores rotations relative to the
    actor's own root. Contact needs both bodies in one frame, and this is the
    conversion between them.
    """
    angle = np.radians(float(facing_yaw))
    cos, sin = np.cos(angle), np.sin(angle)
    rotation = np.array([[cos, 0.0, sin], [0.0, 1.0, 0.0], [-sin, 0.0, cos]])
    return rotation, np.asarray(position, dtype=float)


def world_point(clip: AnimationClip, frame: int, part: str, base) -> np.ndarray:
    """Where a part's centre is in the world on this frame."""
    rotation, origin = base
    pose = {name: track[frame] for name, track in clip.rotations.items()}
    placed = place_rotations(clip.rig, pose)
    local, _ = placed[part]
    return rotation @ np.asarray(local, dtype=float) + origin


def solve_reach(
    clip: AnimationClip,
    base,
    limb: str,
    targets: dict[int, np.ndarray],
    *,
    blend_frames: int,
) -> tuple[AnimationClip, float]:
    """Bend one arm so its hand reaches `targets`, frame by frame.

    ``targets`` maps a frame to a world point. Frames outside it are untouched
    except for the blend either side, which is what keeps the correction from
    reading as a snap.
    """
    chain = CHAINS.get(limb)
    if chain is None or not targets:
        return clip, 0.0

    upper, lower, hand = chain
    if upper not in clip.rotations:
        return clip, 0.0

    rotation, origin = base
    rotations = {name: track.copy() for name, track in clip.rotations.items()}
    rigid = upper == lower  # an R6 arm: aim only, there is no elbow

    span = sorted(targets)
    first, last = span[0], span[-1]
    worst = 0.0

    for frame in range(max(first - blend_frames, 0), min(last + blend_frames + 1, clip.frame_count)):
        target = targets.get(frame, targets[min(max(frame, first), last)])
        weight = _weight(frame, first, last, blend_frames)
        if weight <= 1e-6:
            continue

        pose = {name: track[frame] for name, track in rotations.items()}
        placed = place_rotations(clip.rig, pose)

        # Into the actor's own frame: the clip's kinematics live there, and
        # solving in the world would need the root's placement threaded through
        # every step for no gain.
        local_target = rotation.T @ (np.asarray(target, dtype=float) - origin)

        solved = _aim(clip, pose, placed, chain, local_target, rigid)
        if solved is None:
            continue
        for part, value in solved.items():
            rotations[part][frame] = quat_slerp(
                rotations[part][frame][None], value[None], np.array([weight])
            )[0]

        if first <= frame <= last:
            pose = {name: track[frame] for name, track in rotations.items()}
            reached = place_rotations(clip.rig, pose)[hand][0]
            worst = max(worst, float(np.linalg.norm(reached - local_target)))

    fixed = AnimationClip(
        rig=clip.rig,
        fps=clip.fps,
        rotations=rotations,
        name=clip.name,
        metadata=dict(clip.metadata),
        loop=clip.loop,
        priority=clip.priority,
    )
    return fixed, worst


def _weight(frame: int, first: int, last: int, blend: int) -> float:
    """Full inside the hold, easing to nothing over `blend` frames either side.

    The same C1 curve the foot planting uses, so a hand and a foot corrected on
    the same frames ease together rather than fighting.
    """
    if first <= frame <= last:
        return 1.0
    distance = first - frame if frame < first else frame - last
    if distance >= blend or blend <= 0:
        return 0.0
    t = distance / blend
    return float(2.0 * t**3 - 3.0 * t**2 + 1.0)


def _aim(
    clip: AnimationClip,
    pose: dict[str, np.ndarray],
    placed,
    chain: tuple[str, str, str],
    target: np.ndarray,
    rigid: bool,
) -> dict[str, np.ndarray] | None:
    """Two-bone IK on an arm, or a plain aim when there is no elbow."""
    upper, lower, hand = chain
    shoulder = _joint(clip, placed, upper)
    parent = clip.rig.part(upper).parent
    parent_world = placed[parent][1]

    if rigid:
        # R6: hand and arm are the same rigid part, so the best that can be
        # done is to point it at the target. The shortfall is radial and stays
        # in the report.
        tip = placed[hand][0]
        align = _between(tip - shoulder, target - shoulder)
        world = align @ placed[upper][1]
        return {upper: mat_to_quat(parent_world.T @ world)}

    upper_length = float(np.linalg.norm(_joint(clip, placed, lower) - shoulder))
    lower_length = float(np.linalg.norm(placed[hand][0] - _joint(clip, placed, lower)))
    if upper_length < 1e-6 or lower_length < 1e-6:
        return None

    reach = target - shoulder
    distance = float(np.linalg.norm(reach))
    if distance < 1e-6:
        return None

    # Clamped inside the arm's own reach: a Roblox part has a fixed size, so an
    # unreachable target is met as closely as a straight arm allows.
    span = float(
        np.clip(
            distance,
            abs(upper_length - lower_length) + 1e-3,
            upper_length + lower_length - 1e-3,
        )
    )
    cosine = (upper_length**2 + lower_length**2 - span**2) / (
        2.0 * upper_length * lower_length
    )
    bend = float(np.pi - np.arccos(np.clip(cosine, -1.0, 1.0)))

    trial = dict(pose)
    trial[lower] = _axis_angle(_elbow_hinge(clip, placed, chain), bend)

    bent = place_rotations(clip.rig, trial)
    align = _between(bent[hand][0] - shoulder, reach)
    trial[upper] = mat_to_quat(parent_world.T @ (align @ bent[upper][1]))
    return {upper: trial[upper], lower: trial[lower]}


def _elbow_hinge(clip: AnimationClip, placed, chain: tuple[str, str, str]) -> np.ndarray:
    """Which way the elbow folds, read off the pose rather than declared.

    An elbow that is already bent says where its hinge is. One that is straight
    says nothing, so the arm's own sideways axis stands in — an elbow that folds
    the wrong way is instantly readable as wrong, and a default beats a guess
    that flips between frames.
    """
    upper, lower, hand = chain
    shoulder = _joint(clip, placed, upper)
    elbow = _joint(clip, placed, lower)
    wrist = placed[hand][0]

    normal = np.cross(elbow - shoulder, wrist - elbow)
    size = float(np.linalg.norm(normal))
    if size > 1e-4:
        return normal / size
    return placed[upper][1] @ np.array([1.0, 0.0, 0.0])


def _joint(clip: AnimationClip, placed, part: str) -> np.ndarray:
    """Where a part meets its parent, in the actor's frame."""
    definition = clip.rig.part(part)
    parent_position, parent_rotation = placed[definition.parent]
    return parent_position + parent_rotation @ np.asarray(definition.pivot, dtype=float)


def _between(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """The rotation taking one direction onto another."""
    a = source / max(float(np.linalg.norm(source)), 1e-9)
    b = target / max(float(np.linalg.norm(target)), 1e-9)
    axis = np.cross(a, b)
    size = float(np.linalg.norm(axis))
    if size < 1e-9:
        return np.eye(3) if float(a @ b) > 0 else -np.eye(3) + 2.0 * np.outer(a, a)
    return _matrix(axis / size, float(np.arctan2(size, float(a @ b))))


def _matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    cos, sin = np.cos(angle), np.sin(angle)
    cross = np.array(
        [[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]]
    )
    return cos * np.eye(3) + sin * cross + (1.0 - cos) * np.outer(axis, axis)


def _axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    return mat_to_quat(_matrix(axis, angle)[None])[0]


__all__ = [
    "BLEND_SECONDS",
    "CHAINS",
    "Reach",
    "base_frame",
    "quat_to_mat",
    "solve_reach",
    "world_point",
]
