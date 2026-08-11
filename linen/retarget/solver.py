"""Turn tracked landmarks into per-joint local rotations for a Roblox rig.

The solve is rotation-only and therefore scale-free: whoever stood in front of
the cameras, tall or short, drives the same rig without a calibration pass.
Positions are only consulted to derive directions.

Per part, per frame:

1. aim the bone at ``tip - origin``;
2. resolve the twist from the part's :class:`~linen.rigs.definition.Roll`;
3. express the resulting world rotation relative to the parent's;
4. subtract the rest pose, which for the stock rigs is the identity.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..clip import AnimationClip
from ..math3d import (
    mat_inv,
    mat_to_quat,
    normalize,
    orthonormal_basis,
    swing_rotation,
    unroll_quaternions,
)
from ..rigs import RigDefinition, Roll
from .landmarks import LandmarkTrack

#: Below this, a three-joint chain is straight enough that its plane normal is
#: numerical noise and we fall back to the parent's twist.
_CHAIN_DEGENERATE = 0.15


@dataclass
class SolveOptions:
    #: Bake HumanoidRootPart translation into the clip.  Off by default: a
    #: Roblox ``Humanoid`` drives the character's position itself, and a baked
    #: root fights it.  Turn it on for cutscenes driven by an AnimationTrack.
    root_motion: bool = False
    #: Frames of moving-average smoothing applied to the solved rotations.
    #: Zero disables it.  Odd values keep the filter centred.
    smoothing_frames: int = 5
    #: Interpolate landmark dropouts up to this many frames.
    max_gap_frames: int = 30


def solve_clip(
    rig: RigDefinition,
    track: LandmarkTrack,
    options: SolveOptions | None = None,
    *,
    name: str = "Retargeted",
) -> AnimationClip:
    """Retarget a landmark track onto ``rig``."""
    options = options or SolveOptions()
    track = track.fill_gaps(options.max_gap_frames)

    frames = track.frame_count
    if frames == 0:
        raise ValueError("cannot retarget an empty recording")

    world: dict[str, np.ndarray] = {}
    identity = np.tile(np.eye(3), (frames, 1, 1))
    world[rig.root.name] = _root_world_rotation(track, identity)

    rotations: dict[str, np.ndarray] = {}
    for part in rig.parts[1:]:
        parent_world = world[part.parent]
        source = rig.source(part.name)
        if source is None:
            # No landmarks drive this part: hold the rest pose and pass the
            # parent's frame down so children still resolve.
            world[part.name] = parent_world
            rotations[part.name] = mat_to_quat(identity)
            continue

        bone = track.direction(source.origin, source.tip)
        hint = _twist_hint(track, source, bone, parent_world)

        aim = np.broadcast_to(np.asarray(part.aim_axis, dtype=float), (frames, 3))
        roll = np.broadcast_to(np.asarray(part.roll_axis, dtype=float), (frames, 3))
        rest = orthonormal_basis(aim, roll)
        part_world = orthonormal_basis(bone, hint) @ mat_inv(rest)

        # When the twist hint collapses onto the bone the roll is not in the
        # data at all — an arm held straight out along its own bend axis. Swing
        # the parent's frame onto the bone instead of letting the basis pick an
        # arbitrary world axis and pop between frames.
        undetermined = np.linalg.norm(np.cross(hint, bone), axis=-1) < 1e-3
        if undetermined.any():
            swung = swing_rotation(_apply(parent_world, aim), bone) @ parent_world
            part_world = np.where(undetermined[:, None, None], swung, part_world)

        # Frames whose landmarks never came back stay at the parent's pose
        # rather than snapping to whatever a NaN-derived basis produced.
        untracked = ~np.isfinite(part_world).all(axis=(1, 2))
        if untracked.any():
            part_world = np.where(untracked[:, None, None], parent_world, part_world)

        world[part.name] = part_world
        rotations[part.name] = mat_to_quat(mat_inv(parent_world) @ part_world)

    if options.smoothing_frames > 1:
        rotations = {
            part: smooth_rotations(track_, options.smoothing_frames)
            for part, track_ in rotations.items()
        }

    root_positions = _root_translation(rig, track) if options.root_motion else None

    return AnimationClip(
        rig=rig,
        fps=track.fps,
        rotations=rotations,
        root_positions=root_positions,
        name=name,
        metadata={"source": "retarget", "frames": frames},
    )


def _twist_hint(
    track: LandmarkTrack,
    source,
    bone: np.ndarray,
    parent_world: np.ndarray,
) -> np.ndarray:
    """Where the part's :attr:`~linen.rigs.definition.Part.roll_axis` points.

    Each :class:`~linen.rigs.definition.Roll` names a different part-space axis,
    so the returned world direction must be read against the matching one: the
    sideways sources give local +X, hands give their back, feet their up.
    """
    if source.roll is Roll.PARENT_BACK:
        return parent_world[..., 2]
    if source.roll is Roll.PARENT_UP:
        return parent_world[..., 1]

    if source.roll is Roll.LATERAL:
        left, right = source.lateral
        return normalize(track.point(right) - track.point(left))

    # Roll.CHAIN_PLANE: the normal of the plane through the hinge's three
    # landmarks is the hinge axis, which is the part's local +X.
    proximal, middle, distal = source.plane
    x_axis = np.cross(
        track.direction((proximal,), (middle,)), track.direction((middle,), (distal,))
    )
    if source.invert_chain_normal:
        x_axis = -x_axis
    # A straight limb has no plane; borrow the parent's hinge axis so the twist
    # stays continuous through the extended pose instead of spinning.
    straight = np.linalg.norm(x_axis, axis=-1) < _CHAIN_DEGENERATE
    return np.where(straight[:, None], parent_world[..., 0], normalize(x_axis))


def _apply(rotations: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    """Rotate a stack of vectors by a stack of matrices."""
    return np.einsum("nij,nj->ni", rotations, vectors)


def _root_world_rotation(track: LandmarkTrack, identity: np.ndarray) -> np.ndarray:
    """Orientation of the HumanoidRootPart: body yaw only, kept upright.

    Roblox's root part is the physics capsule.  Letting it pitch and roll with
    the pelvis makes the character lean into the floor, so we keep world up and
    take only the heading.
    """
    hips_right = normalize(track.point("right_hip") - track.point("left_hip"))
    flat = hips_right.copy()
    flat[:, 1] = 0.0
    flat = normalize(flat)

    up = np.broadcast_to(np.array([0.0, 1.0, 0.0]), flat.shape)
    rotation = orthonormal_basis(up, np.cross(flat, up))
    degenerate = ~np.isfinite(rotation).all(axis=(1, 2))
    if degenerate.any():
        rotation = np.where(degenerate[:, None, None], identity, rotation)
    return rotation


def _root_translation(rig: RigDefinition, track: LandmarkTrack) -> np.ndarray:
    """Pelvis translation in studs, with the first frame taken as the origin.

    The height offset is dropped rather than guessed: it depends on the target
    avatar's leg length, which we deliberately do not know.
    """
    pelvis = track.point("left_hip", "right_hip") * rig.studs_per_metre
    first_valid = np.argmax(np.isfinite(pelvis).all(axis=1))
    return pelvis - pelvis[first_valid]


def smooth_rotations(quaternions: np.ndarray, window: int) -> np.ndarray:
    """Centred moving average over quaternions, renormalised.

    Averaging quaternions componentwise is only valid for rotations that are
    close together, which is why the sequence is sign-unrolled first and why
    the window should stay small.  For a 30 fps capture, 5 frames takes the
    tracker's jitter off without visibly softening a fast punch.
    """
    quaternions = np.asarray(quaternions, dtype=float)
    if window <= 1 or quaternions.shape[0] < window:
        return quaternions

    unrolled = unroll_quaternions(quaternions)
    pad = window // 2
    padded = np.pad(unrolled, ((pad, pad), (0, 0)), mode="edge")
    kernel = np.ones(window) / window
    averaged = np.stack(
        [np.convolve(padded[:, i], kernel, mode="valid") for i in range(4)], axis=-1
    )
    return normalize(averaged[: quaternions.shape[0]])
