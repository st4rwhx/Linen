"""Turn a validated :class:`~linen.generate.schema.MotionPlan` into a clip.

Nothing here talks to a network.  Given the same plan and seed it produces the
same animation, which means a plan can be committed to a repository, reviewed
in a diff, and re-synthesised later — and it means the whole text-to-animation
path can be tested without an API key.
"""

from __future__ import annotations

import numpy as np

from ..clip import IDENTITY_QUAT, AnimationClip
from ..math3d import euler_degrees_to_quat, mat_to_quat, quat_slerp, quat_to_mat
from ..rigs import RigDefinition
from . import posebook
from .posebook import PoseData
from .schema import Layer, MotionPlan, Segment

#: Which R15 part drives each R6 part. R6 has no elbows, knees, wrists or
#: ankles, so their motion is genuinely dropped rather than approximated.
R6_FROM_R15: dict[str, str] = {
    "Torso": "UpperTorso",
    "Head": "Head",
    "Left Arm": "LeftUpperArm",
    "Right Arm": "RightUpperArm",
    "Left Leg": "LeftUpperLeg",
    "Right Leg": "RightUpperLeg",
}


def synthesize(
    plan: MotionPlan, rig: RigDefinition, *, seed: int = 0
) -> AnimationClip:
    """Synthesise ``plan`` onto ``rig``."""
    plan.validate()

    frames = plan.frame_count
    times = np.arange(frames) / plan.fps
    parts = rig.animated_parts

    tracks = _schedule(plan, parts, rig, times)

    if not np.isclose(plan.energy, 1.0):
        identity = np.tile(IDENTITY_QUAT, (frames, 1))
        tracks = {
            part: quat_slerp(identity, track, plan.energy)
            for part, track in tracks.items()
        }

    for layer in plan.layers:
        tracks = _apply_layer(tracks, layer, rig, times, seed)

    clip = AnimationClip(
        rig=rig,
        fps=plan.fps,
        rotations=tracks,
        name=plan.name,
        loop=plan.loop,
        priority=plan.priority,
        metadata={"source": "synth", "plan": plan.to_dict()},
    )
    return clip.with_loop_seam() if plan.loop else clip


# ---------------------------------------------------------------------------
# scheduling
# ---------------------------------------------------------------------------
def _schedule(
    plan: MotionPlan, parts: tuple[str, ...], rig: RigDefinition, times: np.ndarray
) -> dict[str, np.ndarray]:
    segments = plan.segments
    starts = np.array([s.start for s in segments])

    # Which segment owns each frame. Frames that fall in a gap between segments
    # keep evaluating the previous one, so a held pose stays held and a cycle
    # keeps cycling rather than snapping to rest.
    owner = np.clip(np.searchsorted(starts, times, side="right") - 1, 0, len(segments) - 1)

    tracks = {part: np.tile(IDENTITY_QUAT, (times.size, 1)) for part in parts}

    for index, segment in enumerate(segments):
        mask = owner == index
        if not mask.any():
            continue
        local_times = times[mask]
        values = _evaluate(segment, parts, rig, local_times)

        if index > 0 and segment.blend_in > 0:
            blend = (local_times - segment.start) < segment.blend_in
            if blend.any():
                previous = _evaluate(segments[index - 1], parts, rig, local_times[blend])
                u = _ease(
                    np.clip((local_times[blend] - segment.start) / segment.blend_in, 0.0, 1.0),
                    segment.easing,
                )
                for part in parts:
                    values[part][blend] = quat_slerp(previous[part], values[part][blend], u)

        for part in parts:
            tracks[part][mask] = values[part]

    return tracks


def _evaluate(
    segment: Segment, parts: tuple[str, ...], rig: RigDefinition, times: np.ndarray
) -> dict[str, np.ndarray]:
    """Sample a segment at absolute ``times``, which may run past its end."""
    if segment.pose is not None:
        pose = _pose_quaternions(posebook.resolve_pose(segment.pose), parts, rig)
        return {part: np.tile(pose[part], (times.size, 1)) for part in parts}

    cycle = posebook.CYCLES[segment.cycle]
    rate = segment.rate if segment.rate is not None else cycle.default_rate
    phase = ((times - segment.start) * rate) % 1.0

    keys = list(cycle.keys) + [(1.0, cycle.keys[0][1])]
    phases = np.array([p for p, _ in keys])
    quats = [_pose_quaternions(posebook.resolve_pose(name), parts, rig) for _, name in keys]

    upper = np.clip(np.searchsorted(phases, phase, side="right"), 1, len(keys) - 1)
    lower = upper - 1
    span = phases[upper] - phases[lower]
    t = np.where(span > 0, (phase - phases[lower]) / np.where(span > 0, span, 1.0), 0.0)

    out: dict[str, np.ndarray] = {}
    for part in parts:
        stacked = np.stack([q[part] for q in quats])
        out[part] = quat_slerp(stacked[lower], stacked[upper], t)
    return out


def _pose_quaternions(
    pose: PoseData, parts: tuple[str, ...], rig: RigDefinition
) -> dict[str, np.ndarray]:
    adapted = adapt_pose_to_rig(pose, rig)
    return {
        part: euler_degrees_to_quat(np.array(adapted.get(part, (0.0, 0.0, 0.0))))
        for part in parts
    }


def adapt_pose_to_rig(pose: PoseData, rig: RigDefinition) -> PoseData:
    """Map an R15-authored pose onto ``rig``.

    R15 passes through untouched.  R6 takes each part from its nearest R15
    equivalent; the segments R6 does not have are dropped, because folding an
    elbow bend into a rigid arm bends the shoulder in a way that reads worse
    than not bending at all.
    """
    if rig.name == "R15":
        return pose
    if rig.name == "R6":
        return {
            part: pose[source] for part, source in R6_FROM_R15.items() if source in pose
        }
    raise ValueError(f"no pose mapping for rig {rig.name!r}")


def _ease(u: np.ndarray, kind: str) -> np.ndarray:
    """Easing curves on a normalised 0-1 parameter.

    ``anticipate`` and ``overshoot`` deliberately leave the 0-1 range: pulling
    back before a move and settling past its target is most of what separates
    an animation that reads as intentional from one that reads as a lerp.
    """
    if kind == "linear":
        return u
    if kind == "ease_in":
        return u * u
    if kind == "ease_out":
        return 1.0 - (1.0 - u) ** 2
    if kind == "ease_in_out":
        return u * u * (3.0 - 2.0 * u)
    if kind == "anticipate":
        return u * u * (2.70158 * u - 1.70158)
    if kind == "overshoot":
        v = u - 1.0
        return 1.0 + v * v * (2.70158 * v + 1.70158)
    raise ValueError(f"unknown easing {kind!r}")


# ---------------------------------------------------------------------------
# secondary motion
# ---------------------------------------------------------------------------
def _apply_layer(
    tracks: dict[str, np.ndarray],
    layer: Layer,
    rig: RigDefinition,
    times: np.ndarray,
    seed: int,
) -> dict[str, np.ndarray]:
    offsets = _layer_offsets(layer, rig, times, seed)
    if not offsets:
        return tracks

    out = dict(tracks)
    for part, degrees in offsets.items():
        if part not in out:
            continue
        # Composed in the part's own frame, so a layer reads as the joint
        # moving a little further rather than the whole limb being re-aimed.
        combined = quat_to_mat(out[part]) @ quat_to_mat(euler_degrees_to_quat(degrees))
        out[part] = mat_to_quat(combined)
    return out


def _layer_offsets(
    layer: Layer, rig: RigDefinition, times: np.ndarray, seed: int
) -> dict[str, np.ndarray]:
    wave = np.sin(2.0 * np.pi * layer.rate * times)
    amp = layer.amplitude
    zeros = np.zeros_like(times)

    def euler(x=zeros, y=zeros, z=zeros) -> np.ndarray:
        return np.stack([x, y, z], axis=-1)

    torso = "Torso" if rig.name == "R6" else "UpperTorso"
    pelvis = "Torso" if rig.name == "R6" else "LowerTorso"

    if layer.kind == "breathing":
        return {
            torso: euler(x=-1.8 * amp * wave),
            "Head": euler(x=0.8 * amp * wave),
        }
    if layer.kind == "sway":
        slow = np.sin(2.0 * np.pi * layer.rate * times * 0.5)
        return {
            pelvis: euler(z=1.6 * amp * wave),
            torso: euler(z=-1.0 * amp * wave, y=1.2 * amp * slow),
            "Head": euler(z=0.6 * amp * wave),
        }
    if layer.kind == "head_turn":
        return {"Head": euler(y=9.0 * amp * wave, x=2.0 * amp * np.cos(wave))}
    if layer.kind == "noise":
        rng = np.random.default_rng(seed)
        offsets: dict[str, np.ndarray] = {}
        for part in rig.animated_parts:
            raw = rng.normal(0.0, 1.0, (times.size, 3))
            offsets[part] = _smooth_columns(raw, window=9) * 1.5 * amp
        return offsets
    raise ValueError(f"unknown layer kind {layer.kind!r}")


def _smooth_columns(values: np.ndarray, window: int) -> np.ndarray:
    """Moving average per column — white noise on joints looks like a seizure."""
    if window <= 1 or values.shape[0] < window:
        return values
    pad = window // 2
    padded = np.pad(values, ((pad, pad), (0, 0)), mode="edge")
    kernel = np.ones(window) / window
    return np.stack(
        [np.convolve(padded[:, i], kernel, mode="valid")[: values.shape[0]] for i in range(3)],
        axis=-1,
    )
