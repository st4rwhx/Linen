"""Join clips without a visible seam, the way shipped games do it.

Retrieval answers "il court" with one clip. It cannot answer "il court, il
s'arrête, il frappe", because that is three clips and the joins are the whole
problem: cut one capture to the next and the character teleports between poses.

The obvious fix — cross-fade the two clips over a few frames — is what most
tools do and it is worse than it looks. Blending two poses averages them, so a
leg mid-stride and a leg planted come out as a leg half-planted, and the result
floats. It also costs both clips being evaluated for the whole overlap.

**Inertialization** is what *Gears of War 4* replaced that with, and it is now
standard. It never blends. At the cut it measures how far the outgoing pose is
from the incoming one, and how fast that difference is changing, then plays the
incoming clip *plus* that difference, decayed to nothing by a critically damped
spring:

.. code-block:: text

    offset(t) = e^(−y·t) · (x + (v + x·y)·t)

``x`` is the pose offset at the cut, ``v`` the velocity offset, and ``y`` half
the damping implied by a half-life. Because the offset carries the outgoing
velocity, the body keeps moving the way it was and settles onto the new clip
instead of snapping to it. Only one clip is ever sampled, and no pose is ever
the average of two.

Everything here works on quaternions, since that is what a clip stores and what
Roblox plays. The offset is a rotation, so it is carried in rotation-vector
form — an axis scaled by an angle, which adds and decays like a vector — and
turned back into a quaternion to apply.
"""

from __future__ import annotations

import numpy as np

from .clip import AnimationClip
from .math3d import quat_conjugate, quat_multiply

#: Seconds for a transition offset to fall to half its size.
#:
#: A quarter second reads as a body correcting itself. Much shorter is a snap;
#: much longer and the character visibly drags the previous pose around.
DEFAULT_HALFLIFE = 0.25

#: Below this the offset is not worth carrying, and the arithmetic stops.
NEGLIGIBLE = 1e-4


def halflife_to_damping(halflife: float) -> float:
    """Damping of a critically damped spring with this half-life."""
    return 4.0 * np.log(2.0) / max(halflife, 1e-5)


def quat_to_rotvec(q: np.ndarray) -> np.ndarray:
    """Quaternion to axis-angle packed as one vector.

    Rotation vectors add and scale like ordinary vectors near the identity,
    which is exactly what a decaying offset needs; quaternions do not.
    """
    q = np.atleast_2d(np.asarray(q, dtype=float))
    # Same rotation, shortest way round: -q is q, and the sign decides whether
    # the offset decays towards zero or the long way round the sphere.
    q = np.where(q[:, 3:4] < 0, -q, q)
    w = np.clip(q[:, 3], -1.0, 1.0)
    angle = 2.0 * np.arccos(w)
    sine = np.sqrt(np.maximum(1.0 - w * w, 0.0))
    scale = np.where(sine < 1e-8, 2.0, angle / np.maximum(sine, 1e-8))
    return q[:, :3] * scale[:, None]


def rotvec_to_quat(v: np.ndarray) -> np.ndarray:
    """The inverse of :func:`quat_to_rotvec`."""
    v = np.atleast_2d(np.asarray(v, dtype=float))
    angle = np.linalg.norm(v, axis=1)
    half = angle / 2.0
    sine = np.where(angle < 1e-8, 0.5, np.sin(half) / np.maximum(angle, 1e-8))
    out = np.empty((len(v), 4))
    out[:, :3] = v * sine[:, None]
    out[:, 3] = np.cos(half)
    return out


def decay(offset: np.ndarray, velocity: np.ndarray, times: np.ndarray, halflife: float):
    """The critically damped spring, evaluated at ``times``.

    ``offset`` and ``velocity`` are ``(3,)`` rotation vectors; ``times`` is in
    seconds from the cut. Returns ``(len(times), 3)``.
    """
    y = halflife_to_damping(halflife) / 2.0
    times = np.asarray(times, dtype=float)[:, None]
    return np.exp(-y * times) * (offset[None, :] + (velocity + offset * y)[None, :] * times)


def inertialize(
    track: np.ndarray,
    *,
    previous: np.ndarray,
    before_previous: np.ndarray | None,
    fps: float,
    halflife: float = DEFAULT_HALFLIFE,
) -> np.ndarray:
    """Make ``track`` start from where the outgoing motion actually was.

    ``previous`` is the last pose of the outgoing clip and ``before_previous``
    the one before it, which is what gives the outgoing angular velocity. The
    returned track is the same motion, offset at the start and settling onto
    the original within a few half-lives.
    """
    track = np.asarray(track, dtype=float)
    if len(track) == 0:
        return track

    offset = quat_to_rotvec(quat_multiply(previous, quat_conjugate(track[0])))[0]

    velocity = np.zeros(3)
    if before_previous is not None:
        # Angular velocity of the outgoing clip, minus that of the incoming
        # one: it is the *difference* that has to decay, not the motion.
        out_rate = quat_to_rotvec(quat_multiply(previous, quat_conjugate(before_previous)))[0]
        in_rate = np.zeros(3)
        if len(track) > 1:
            in_rate = quat_to_rotvec(quat_multiply(track[1], quat_conjugate(track[0])))[0]
        velocity = (out_rate - in_rate) * fps

        # Carry the momentum the body had; never invent more. Cutting a sprint
        # into a walk, the thigh is turning at 1500 deg/s against the walk's
        # 400, and the raw difference injects an excursion faster than either
        # clip ever moves. Capping at the outgoing speed keeps the settle
        # physical — the leg finishes its swing — without inventing a motion
        # that is in neither take.
        cap = float(np.linalg.norm(out_rate)) * fps
        speed = float(np.linalg.norm(velocity))
        if speed > cap > 0:
            velocity *= cap / speed

    if np.linalg.norm(offset) < NEGLIGIBLE and np.linalg.norm(velocity) < NEGLIGIBLE:
        return track

    times = np.arange(len(track), dtype=float) / fps
    offsets = rotvec_to_quat(decay(offset, velocity, times, halflife))
    return quat_multiply(offsets, track)


def pose_distance(a: dict[str, np.ndarray], b: dict[str, np.ndarray]) -> float:
    """Total angle between two poses, in radians, over the parts they share."""
    total = 0.0
    for part, left in a.items():
        right = b.get(part)
        if right is None:
            continue
        delta = quat_multiply(left, quat_conjugate(right))
        total += float(np.linalg.norm(quat_to_rotvec(delta)[0]))
    return total


def best_entry(clip: AnimationClip, pose: dict[str, np.ndarray], *, window: float = 0.5) -> int:
    """The frame of ``clip`` that already looks most like ``pose``.

    This is the part of motion matching that does the real work, and it is
    easy to miss: the technique is not mainly about blending, it is about
    *not needing to*. Given a pose to continue from, search the incoming clip
    for the frame that already resembles it and start there. A join between
    two similar poses needs almost no correction; a join chosen arbitrarily
    needs a large one however good the spring is.

    Only the opening ``window`` seconds are searched, so a clip still starts
    near its beginning rather than skipping to some matching moment halfway
    through and throwing away what was asked for.
    """
    limit = max(min(int(window * clip.fps), clip.frame_count - 1), 1)
    best, best_score = 0, None
    for frame in range(limit):
        candidate = {part: track[frame] for part, track in clip.rotations.items()}
        score = pose_distance(pose, candidate)
        if best_score is None or score < best_score:
            best, best_score = frame, score
    return best


def chain(
    clips: list[AnimationClip],
    *,
    halflife: float = DEFAULT_HALFLIFE,
    align: bool = True,
    name: str | None = None,
) -> AnimationClip:
    """Play ``clips`` one after another, joined without a seam.

    Every clip after the first is inertialized onto the pose the previous one
    ended in, joint by joint. A part missing from one clip simply holds.
    """
    if not clips:
        raise ValueError("nothing to chain")
    if len(clips) == 1:
        return clips[0]

    first = clips[0]
    for clip in clips[1:]:
        if clip.rig.name != first.rig.name:
            raise ValueError(
                f"cannot chain a {first.rig.name} clip with a {clip.rig.name} one"
            )
        if abs(clip.fps - first.fps) > 1e-6:
            raise ValueError(
                f"cannot chain clips at different rates ({first.fps:g} and {clip.fps:g} fps)"
            )

    parts = sorted({part for clip in clips for part in clip.rotations})
    joined: dict[str, list[np.ndarray]] = {part: [] for part in parts}
    seams: list[int] = []
    length_so_far = 0

    for index, clip in enumerate(clips):
        start = 0
        if index > 0 and align:
            ending = {
                part: tracks[-1][-1] for part, tracks in joined.items() if tracks
            }
            if ending:
                start = best_entry(clip, ending)

        if index > 0:
            seams.append(length_so_far)

        for part in parts:
            track = clip.rotations.get(part)
            if track is not None:
                track = track[start:]
            if track is None or len(track) == 0:
                # Hold whatever this part was doing rather than snapping it to
                # rest, which is what a missing track would otherwise mean.
                held = joined[part][-1][-1] if joined[part] else np.array([0.0, 0, 0, 1.0])
                track = np.tile(held, (clip.frame_count, 1))
            if index > 0 and joined[part]:
                done = joined[part][-1]
                track = inertialize(
                    track,
                    previous=done[-1],
                    before_previous=done[-2] if len(done) > 1 else None,
                    fps=clip.fps,
                    halflife=halflife,
                )
            joined[part].append(track)
        length_so_far += len(joined[parts[0]][-1])

    return AnimationClip(
        rig=first.rig,
        fps=first.fps,
        rotations={part: np.concatenate(tracks) for part, tracks in joined.items()},
        name=name or first.name,
        metadata={
            "source": "chain",
            "clips": [clip.name for clip in clips],
            # Frame indices where one clip becomes the next, so a join can
            # be measured rather than eyeballed.
            "seams": seams,
        },
    )


def seam_error(clip: AnimationClip, frame: int) -> float:
    """Largest single-frame jump at ``frame``, in degrees.

    The number a join is judged by: a cut shows up as one frame where some
    joint moves far more than the frames around it.
    """
    if not 0 < frame < clip.frame_count:
        return 0.0
    worst = 0.0
    for track in clip.rotations.values():
        delta = quat_multiply(track[frame], quat_conjugate(track[frame - 1]))
        worst = max(worst, float(np.degrees(np.linalg.norm(quat_to_rotvec(delta)[0]))))
    return worst
