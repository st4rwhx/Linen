"""Measure what a professional animator judges by eye, then fix it exactly.

This is the module that answers "can this be better than a good animator?" —
and the answer is: on the things that can be *measured*, yes, and not by being
cleverer. An animator eyeballs a planted foot and stops when it looks still. A
number does not stop. Nobody working by hand knows their foot slides 1.8 studs
per step, because nobody working by hand can know that.

So this does two separate things, and keeps them separate on purpose:

**Measurement.** :func:`measure` reports the defects that are known tells of
amateur animation — foot skate, joints bending the wrong way, dead holds,
twinning — as numbers, on any clip, from any source. Numbers are what let a
change be defended instead of argued about.

**Correction.** :func:`plant_feet` removes foot skate exactly, with the analytic
inverse kinematics from *Footskate Cleanup for Motion Capture Editing* (Kovar,
Schreiner and Gleicher, SIGGRAPH Symposium on Computer Animation 2002). Their
C1-continuous blend function, ``a(t) = 2t^3 - 3t^2 + 1``, is what keeps the
correction from popping at the ends of a plant, and it is used here unchanged.

Two departures from the paper, both forced and both stated where they bite:

The paper is free to translate the root when a target is out of reach. A Linen
clip exported in place has its pelvis nailed — that is what makes it a Roblox
animation rather than a cutscene — so an unreachable target is clamped to full
extension instead, and the residual is reported rather than hidden.

And the paper stretches a limb as a last resort. Roblox parts have fixed sizes,
so that option does not exist here at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .clip import AnimationClip
from .math3d import mat_to_quat, quat_to_mat
from .rigs.kinematics import place_rotations

#: How far above the stance level a sole may sit and still count as planted, as
#: a fraction of the rig's standing height. The same test the sound spotter
#: uses to place a footstep, for the same reason: a footstep and a foot plant
#: are the same event.
PLANT_HEIGHT = 0.07

#: A plant shorter than this is noise — a toe brushing past, not weight on the
#: ground — and locking it would fight the motion rather than clean it.
#: In **seconds**, deliberately: three frames is a real threshold at 30 fps and
#: a twenty-fifth of a step at CMU's 120, and having it in frames let a
#: correction's own blend-out register as a fresh four-frame plant.
MIN_PLANT_SECONDS = 0.10

#: How long a correction takes to fade in and out around a plant, in seconds
#: for the same reason.
BLEND_SECONDS = 0.08

#: Below this angular speed, in degrees per second summed over the rig, nothing
#: is moving. A held pose that is *perfectly* still reads as a freeze frame;
#: animators call the fix a moving hold.
DEAD_HOLD_DEGREES = 2.0

#: Leg chains, hip to ankle. R6 has one rigid leg part and therefore no knee,
#: so it can be measured but not solved.
LEG_CHAINS = {
    "Left": ("LeftUpperLeg", "LeftLowerLeg", "LeftFoot"),
    "Right": ("RightUpperLeg", "RightLowerLeg", "RightFoot"),
}


@dataclass
class Plant:
    """One stretch of frames where a foot is carrying weight.

    ``target`` is a *trajectory*, not a point, and that is the whole subtlety
    of measuring skate on a Roblox animation. An in-place cycle has its pelvis
    nailed, so a correctly planted foot does not stand still in rig space — it
    travels backwards at exactly the speed the character walks, and the engine
    cancels that by moving the character forwards. Demanding a stationary sole
    would "fix" a perfect walk into a moon walk.

    Skate is therefore the deviation from that straight line, not the length of
    it.
    """

    part: str
    start: int
    stop: int
    #: Where the sole should be on each frame of the plant, ``(n, 3)``.
    target: np.ndarray
    #: Peak-to-peak departure from that line, horizontally, in studs.
    slide: float

    @property
    def frames(self) -> int:
        return self.stop - self.start


@dataclass
class Report:
    """What is wrong with a clip, in numbers."""

    rig: str
    frames: int
    plants: list[Plant] = field(default_factory=list)
    #: Worst and mean horizontal slide over a plant, in studs.
    worst_slide: float = 0.0
    mean_slide: float = 0.0
    #: Frames where a knee or elbow is straighter than a joint should be.
    hyperextended: dict[str, int] = field(default_factory=dict)
    #: Runs of frames in which nothing moves at all.
    dead_holds: list[tuple[int, int]] = field(default_factory=list)
    #: 0..1 per limb pair. 1 is both sides doing the same thing at the same
    #: time, which is the single most robotic thing a body can do.
    twinning: dict[str, float] = field(default_factory=dict)

    def lines(self) -> list[str]:
        out = [f"{self.rig}, {self.frames} images"]
        if self.plants:
            out.append(
                f"  appuis          {len(self.plants)} — glissement max "
                f"{self.worst_slide:.2f} studs, moyen {self.mean_slide:.2f}"
            )
        else:
            out.append("  appuis          aucun détecté")
        if self.hyperextended:
            worst = ", ".join(
                f"{part} {count}" for part, count in sorted(self.hyperextended.items())
            )
            out.append(f"  hyperextension  {worst}")
        if self.dead_holds:
            total = sum(stop - start for start, stop in self.dead_holds)
            out.append(
                f"  poses figées    {len(self.dead_holds)} ({total} images sans "
                f"le moindre mouvement)"
            )
        for pair, value in sorted(self.twinning.items()):
            if value >= 0.9:
                out.append(f"  symétrie        {pair} à {value:.2f} — les deux côtés font la même chose")
        return out


def measure(clip: AnimationClip) -> Report:
    """Everything wrong with ``clip`` that can be put a number on."""
    placed = _walk(clip)
    report = Report(rig=clip.rig.name, frames=clip.frame_count)

    report.plants = _plants(clip, placed)
    slides = [plant.slide for plant in report.plants]
    if slides:
        report.worst_slide = float(max(slides))
        report.mean_slide = float(np.mean(slides))

    report.hyperextended = _hyperextension(clip, placed)
    report.dead_holds = _dead_holds(clip)
    report.twinning = _twinning(clip)
    return report


# -- geometry ----------------------------------------------------------------


def _walk(clip: AnimationClip) -> list[dict[str, tuple[np.ndarray, np.ndarray]]]:
    """Every frame placed, once. Everything below reads from this."""
    return [
        place_rotations(
            clip.rig, {part: track[frame] for part, track in clip.rotations.items()}
        )
        for frame in range(clip.frame_count)
    ]


def _joint_positions(
    clip: AnimationClip, placed: dict[str, tuple[np.ndarray, np.ndarray]], part: str
) -> np.ndarray:
    """Where a part's own joint sits — its pivot, not its centre."""
    definition = clip.rig.part(part)
    if definition.parent is None:
        return np.zeros(3)
    parent_position, parent_rotation = placed[definition.parent]
    return parent_position + parent_rotation @ np.asarray(definition.pivot, dtype=float)


def _sole(clip: AnimationClip, placed, part: str) -> np.ndarray:
    position, rotation = placed[part]
    half = clip.rig.part(part).size[1] / 2.0
    return position + rotation @ np.array([0.0, -half, 0.0])


def _standing_height(rig) -> float:
    rest = place_rotations(rig, {})
    top = max(pos[1] + rig.part(name).size[1] / 2.0 for name, (pos, _) in rest.items())
    low = min(pos[1] - rig.part(name).size[1] / 2.0 for name, (pos, _) in rest.items())
    return float(max(top - low, 1.0))


# -- measurement -------------------------------------------------------------


def _plants(clip: AnimationClip, placed) -> list[Plant]:
    feet = [chain[2] for chain in LEG_CHAINS.values() if chain[2] in clip.rotations]
    feet += [p for p in ("Left Leg", "Right Leg") if p in clip.rotations]
    if not feet:
        return []

    soles = {part: np.array([_sole(clip, frame, part) for frame in placed]) for part in feet}
    lower = np.minimum.reduce([values[:, 1] for values in soles.values()])
    stance = float(np.median(lower))
    lift = PLANT_HEIGHT * _standing_height(clip.rig)

    grounded = {part: values[:, 1] <= stance + lift for part, values in soles.items()}
    shortest = max(round(MIN_PLANT_SECONDS * clip.fps), 2)

    spans: list[tuple[str, int, int]] = []
    for part, flags in grounded.items():
        spans += [
            (part, start, stop)
            for start, stop in _runs(flags)
            if stop - start >= shortest
        ]

    drift = _ground_velocity(soles, spans)

    plants: list[Plant] = []
    for part, start, stop in spans:
        span = soles[part][start:stop]
        steps = np.arange(stop - start)[:, None]

        # The line the sole should be on: the plant's own average, carried
        # along at the speed the whole body agrees the ground is moving.
        line = span.mean(axis=0) + drift * (steps - steps.mean())
        line[:, 1] = span[:, 1]  # a heel may lift; it may not wander

        error = np.linalg.norm((span - line)[:, [0, 2]], axis=1)
        plants.append(
            Plant(
                part=part,
                start=start,
                stop=stop,
                target=line,
                slide=float(error.max() * 2.0),
            )
        )
    return sorted(plants, key=lambda plant: (plant.start, plant.part))


def _ground_velocity(
    soles: dict[str, np.ndarray], spans: list[tuple[str, int, int]]
) -> np.ndarray:
    """How fast the ground passes under the character, per frame, in rig space.

    Measured from the plants themselves, and from each plant's *average*
    velocity rather than its individual frames. Both choices were forced by
    getting it wrong first: sampling every frame whose sole is low includes the
    swing leg passing through, which travels at roughly twice ground speed and
    dragged the estimate up by half. The result was a correction that pulled
    every foot further than it had gone — measured skate went up, not down.

    Taking the median across plants is the definition of the fix, too: skate is
    the feet disagreeing about how fast the ground moves, so the consensus is
    what the outliers get pulled back to.
    """
    samples = []
    for part, start, stop in spans:
        span = soles[part][start:stop]
        if len(span) < 2:
            continue
        samples.append((span[-1] - span[0]) / (len(span) - 1))
    if not samples:
        return np.zeros(3)
    velocity = np.median(np.array(samples), axis=0)
    velocity[1] = 0.0
    return velocity


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Maximal half-open ranges where ``flags`` is true."""
    out: list[tuple[int, int]] = []
    start = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            out.append((start, index))
            start = None
    if start is not None:
        out.append((start, len(flags)))
    return out


#: Hinges, as (upper, middle, tip) chains with the direction the joint is
#: supposed to point. A knee leads forwards, an elbow trails backwards; either
#: one pointing the other way is the joint bending backwards.
_HINGES = (
    ("LeftUpperLeg", "LeftLowerLeg", "LeftFoot", 1.0),
    ("RightUpperLeg", "RightLowerLeg", "RightFoot", 1.0),
    ("LeftUpperArm", "LeftLowerArm", "LeftHand", -1.0),
    ("RightUpperArm", "RightLowerArm", "RightHand", -1.0),
)

#: How far past the straight line a joint has to go, in studs, before it counts
#: as bending backwards rather than simply being extended.
BACKWARDS_STUDS = 0.05


def _hyperextension(clip: AnimationClip, placed) -> dict[str, int]:
    """Frames where a knee or elbow bends the wrong way.

    Not "frames where the limb is straight" — that was the first version and it
    flagged every rig standing at rest, which is every rig. A straight limb is
    normal. The defect is the joint crossing to the wrong *side* of the line
    from its root to its tip, and which side is wrong depends on the joint:
    a knee leads the line, an elbow trails it.

    Judged against the body's own forward direction, so a character that turns
    is not suddenly full of broken knees.
    """
    counts: dict[str, int] = {}
    core = "UpperTorso" if "UpperTorso" in {p.name for p in clip.rig.parts} else "Torso"

    for upper, middle, tip, direction in _HINGES:
        if not {upper, middle, tip} <= set(clip.rotations):
            continue
        wrong = 0
        for frame in placed:
            if core not in frame:
                continue
            forward = frame[core][1] @ np.array([0.0, 0.0, -1.0])
            root = _joint_positions(clip, frame, upper)
            joint = _joint_positions(clip, frame, middle)
            end = _joint_positions(clip, frame, tip)

            line = end - root
            length = float(np.linalg.norm(line))
            if length < 1e-6:
                continue
            along = (joint - root) @ line / length**2
            offset = (joint - root) - along * line
            if (offset @ forward) * direction < -BACKWARDS_STUDS:
                wrong += 1
        if wrong:
            counts[middle] = wrong
    return counts


def _dead_holds(clip: AnimationClip) -> list[tuple[int, int]]:
    if clip.frame_count < 2:
        return []
    speed = np.zeros(clip.frame_count - 1)
    for track in clip.rotations.values():
        dots = np.abs(np.sum(track[:-1] * track[1:], axis=1)).clip(0.0, 1.0)
        speed += np.degrees(2.0 * np.arccos(dots)) * clip.fps
    return [
        (start, stop)
        for start, stop in _runs(speed < DEAD_HOLD_DEGREES)
        if stop - start >= clip.fps * 0.25
    ]


def _twinning(clip: AnimationClip) -> dict[str, float]:
    """How much the two sides of the body do the same thing at the same time.

    Mirrored is fine — that is what walking is. *Simultaneous* is not: a body
    whose arms swing forward together reads as a mechanism.

    So this correlates the **signed** swing of the two sides, not their speed.
    Comparing speeds was the first thing tried here and it is wrong: in a
    healthy alternating walk both limbs reach peak speed at the same instant,
    passing through the middle of their swing, so a perfect gait scored 0.93
    and looked like the worst defect in the clip. Signed swing has a proper
    alternating gait at -1, and only genuine lockstep at +1.
    """
    out: dict[str, float] = {}
    for left, right in (
        ("LeftUpperArm", "RightUpperArm"),
        ("LeftUpperLeg", "RightUpperLeg"),
    ):
        if left not in clip.rotations or right not in clip.rotations:
            continue
        a, b = (_swing(clip.rotations[name]) for name in (left, right))
        if a.std() < 1e-6 or b.std() < 1e-6:
            continue
        out[left.replace("Left", "")] = float(
            np.clip(np.corrcoef(a, b)[0, 1], 0.0, 1.0)
        )
    return out


def _swing(track: np.ndarray) -> np.ndarray:
    """Signed forward/backward swing of a limb, in radians.

    A Roblox limb hangs along -Y and swings about its own X, so the
    quaternion's x term carries the sign of the swing directly.
    """
    track = np.asarray(track, dtype=float)
    sign = np.where(track[:, 3] < 0.0, -1.0, 1.0)
    return 2.0 * np.arcsin(np.clip(track[:, 0] * sign, -1.0, 1.0))


# -- correction --------------------------------------------------------------


def plant_feet(
    clip: AnimationClip, *, blend_frames: int | None = None
) -> tuple[AnimationClip, Report]:
    """Put every planted foot exactly where it belongs, and say by how much.

    Returns the corrected clip and the report *of the original*, so the caller
    can measure the result and state the difference rather than assert it.
    """
    before = measure(clip)
    if not before.plants or clip.rig.name != "R15":
        return clip, before

    if blend_frames is None:
        blend_frames = max(round(BLEND_SECONDS * clip.fps), 1)

    rotations = {part: track.copy() for part, track in clip.rotations.items()}
    fixed = AnimationClip(
        rig=clip.rig,
        fps=clip.fps,
        rotations=rotations,
        name=clip.name,
        metadata=dict(clip.metadata),
    )
    if clip.root_positions is not None:
        fixed.root_positions = clip.root_positions.copy()

    lengths = _bone_lengths(clip.rig)

    for plant in before.plants:
        chain = _chain_for(plant.part)
        if chain is None:
            continue

        # Exact across the plant, faded across the frames on either side of it.
        # Fading *inside* the plant was the first version and it is wrong: the
        # frames a plant most needs fixed are its first and last, where the
        # foot arrives and leaves, and a fade there leaves the visible skate
        # untouched while correcting the middle nobody was looking at.
        low = max(plant.start - blend_frames, 0)
        high = min(plant.stop + blend_frames, clip.frame_count)

        # One hinge for the whole plant, read from the frame where the knee is
        # most bent. Reading it per frame was the first version, and a knee
        # passing through straight mid-plant flipped the axis from one side to
        # the other — a 38 deg/frame snap that the numbers called a success.
        hinge = _knee_hinge(clip.rotations[chain[1]][low:high])

        for frame in range(low, high):
            weight = _blend_weight(frame, plant, blend_frames)
            if weight <= 1e-6:
                continue

            pose = {part: track[frame] for part, track in rotations.items()}
            placed = place_rotations(fixed.rig, pose)
            solved = _solve_leg(
                fixed, pose, placed, chain, lengths[plant.part],
                _target_at(plant, frame, fixed, placed), hinge,
            )
            if solved is None:
                continue

            for part, target in zip(chain, solved):
                rotations[part][frame] = _slerp(rotations[part][frame], target, weight)

    return fixed, before


def _chain_for(foot: str) -> tuple[str, str, str] | None:
    for chain in LEG_CHAINS.values():
        if chain[2] == foot:
            return chain
    return None


def _bone_lengths(rig) -> dict[str, tuple[float, float]]:
    """Thigh and shin lengths, pivot to pivot, measured on the rig at rest."""
    rest = place_rotations(rig, {})
    out: dict[str, tuple[float, float]] = {}
    for thigh, shin, foot in LEG_CHAINS.values():
        if not {thigh, shin, foot} <= {part.name for part in rig.parts}:
            continue
        hip = rest[rig.part(thigh).parent][0] + rest[rig.part(thigh).parent][1] @ np.asarray(
            rig.part(thigh).pivot, dtype=float
        )
        knee = rest[thigh][0] + rest[thigh][1] @ np.asarray(rig.part(shin).pivot, dtype=float)
        ankle = rest[shin][0] + rest[shin][1] @ np.asarray(rig.part(foot).pivot, dtype=float)
        out[foot] = (
            float(np.linalg.norm(knee - hip)),
            float(np.linalg.norm(ankle - knee)),
        )
    return out


def _solve_leg(
    clip: AnimationClip,
    pose: dict[str, np.ndarray],
    placed,
    chain: tuple[str, str, str],
    lengths: tuple[float, float],
    target_sole: np.ndarray,
    hinge: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Two-bone analytic IK: bend the knee, aim the leg, keep the foot flat.

    Steps 2 to 4 of the paper's Figure 5. Step 5, stretching the limb, has no
    equivalent here — a Roblox part has a fixed size — so an out-of-reach
    target is met as closely as a straight leg allows, and what is left over
    stays in the report instead of being quietly absorbed.

    Where the paper derives the ankle position in closed form, this re-runs the
    rig's own forward kinematics between steps. It is a few more matrix
    multiplies and it cannot disagree with the exporter about where a limb is,
    which the closed form can.
    """
    thigh, shin, foot = chain
    thigh_length, shin_length = lengths
    if thigh_length < 1e-6 or shin_length < 1e-6:
        return None

    hip = _joint_positions(clip, placed, thigh)
    parent_world = placed[clip.rig.part(thigh).parent][1]
    foot_rotation = placed[foot][1]

    # Where the ankle has to be for the sole to land on the target, with the
    # foot left at the angle the animation already gave it: a plant fixes where
    # a foot is, never how it is tilted.
    definition = clip.rig.part(foot)
    inside = (
        np.asarray(definition.rest_offset, dtype=float)
        - np.asarray(definition.pivot, dtype=float)
        + np.array([0.0, -definition.size[1] / 2.0, 0.0])
    )
    target_ankle = np.asarray(target_sole, dtype=float) - foot_rotation @ inside

    reach = target_ankle - hip
    distance = float(np.linalg.norm(reach))
    if distance < 1e-6:
        return None

    span = float(
        np.clip(
            distance,
            abs(thigh_length - shin_length) + 1e-3,
            thigh_length + shin_length - 1e-3,
        )
    )
    cosine = (thigh_length**2 + shin_length**2 - span**2) / (
        2.0 * thigh_length * shin_length
    )
    # The angle the shin turns away from straight, so a fully extended leg is 0.
    bend = float(np.pi - np.arccos(np.clip(cosine, -1.0, 1.0)))

    trial = dict(pose)
    trial[shin] = _axis_angle(hinge, bend)

    bent = place_rotations(clip.rig, trial)
    ankle_now = _joint_positions(clip, bent, foot)

    align = _rotation_between(ankle_now - hip, reach)
    thigh_world = align @ bent[thigh][1]
    trial[thigh] = mat_to_quat(parent_world.T @ thigh_world)

    aimed = place_rotations(clip.rig, trial)
    return (
        trial[thigh],
        trial[shin],
        mat_to_quat(aimed[shin][1].T @ foot_rotation),
    )


def _knee_hinge(track: np.ndarray) -> np.ndarray:
    """The axis a knee turns on across a plant, from where it is most bent.

    Reading the hinge off the animation rather than declaring one keeps
    whatever knee direction the capture or the animator chose, including a knee
    turned out. Taking it from the single most bent frame — rather than frame
    by frame — is what keeps it continuous: near straight there is no direction
    to read, and a knee passing through straight would otherwise flip from one
    side to the other. That flip measured 38 deg in a single frame, and every
    number in the report called it a success.
    """
    track = np.asarray(track, dtype=float)
    if track.ndim == 1:
        track = track[None]
    signed = track[:, :3] * np.where(track[:, 3:4] >= 0.0, 1.0, -1.0)
    norms = np.linalg.norm(signed, axis=1)
    best = int(np.argmax(norms))
    if norms[best] > 1e-6 and 2.0 * np.arcsin(min(norms[best], 1.0)) > np.deg2rad(2.0):
        return signed[best] / norms[best]
    return np.array([1.0, 0.0, 0.0])


def _axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=float)
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
    half = angle / 2.0
    return np.array([*(axis * np.sin(half)), np.cos(half)])


def _rotation_between(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Shortest rotation taking ``source`` onto ``target``, as a matrix."""
    a = source / max(float(np.linalg.norm(source)), 1e-12)
    b = target / max(float(np.linalg.norm(target)), 1e-12)
    axis = np.cross(a, b)
    sine = float(np.linalg.norm(axis))
    cosine = float(np.clip(a @ b, -1.0, 1.0))
    if sine < 1e-9:
        if cosine > 0.0:
            return np.eye(3)
        fallback = np.array([1.0, 0.0, 0.0])
        if abs(a @ fallback) > 0.9:
            fallback = np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, fallback)
        axis /= np.linalg.norm(axis)
        return quat_to_mat(_axis_angle(axis, np.pi))
    axis = axis / sine
    return quat_to_mat(_axis_angle(axis, float(np.arctan2(sine, cosine))))


def _blend_weight(frame: int, plant: Plant, blend: int) -> float:
    """1 across the plant, easing to 0 over ``blend`` frames on either side.

    ``a(t) = 2t^3 - 3t^2 + 1`` is the paper's blend: the unique cubic that is 1
    at 0, 0 at 1, and flat at both, so the correction arrives and leaves with
    no kink in the velocity — which is what stops a fixed plant from popping
    into the swing that follows it.
    """
    if plant.start <= frame < plant.stop:
        return 1.0
    if blend <= 0:
        return 0.0
    away = plant.start - frame if frame < plant.start else frame - plant.stop + 1
    t = min(away / blend, 1.0)
    return float(2.0 * t**3 - 3.0 * t**2 + 1.0)


def _target_at(plant: Plant, frame: int, clip: AnimationClip, placed) -> np.ndarray:
    """Where the sole should be on ``frame``, inside the plant or just outside.

    Outside, the line is extended rather than dropped: a foot approaching a
    plant should already be heading for it, which is what an approach *is*.
    The height always comes from the animation, never from the line — lifting
    a heel is motion, not error.
    """
    inside = frame - plant.start
    if 0 <= inside < len(plant.target):
        return plant.target[inside]

    step = (
        plant.target[-1] - plant.target[0]
    ) / max(len(plant.target) - 1, 1)
    anchor = plant.target[0] if inside < 0 else plant.target[-1]
    base = plant.start if inside < 0 else plant.stop - 1
    extended = anchor + step * (frame - base)
    extended[1] = _sole(clip, placed, plant.part)[1]
    return extended


def _slerp(current: np.ndarray, target: np.ndarray, weight: float) -> np.ndarray:
    from .math3d import quat_slerp

    return quat_slerp(np.asarray(current)[None], np.asarray(target)[None],
                      np.array([weight]))[0]
