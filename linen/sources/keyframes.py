"""Read a Roblox animation back into a clip, whatever wrote it.

Every other reader here turns *capture* into motion. This one turns *a Roblox
animation* back into motion, which matters for a different reason: it is how
work made anywhere else gets into a Linen scene.

The pose vocabulary in this project knows twelve verbs. A service that sells
generated R15 motion, a Mixamo clip already imported and saved out of Studio, a
fight beat somebody keyed by hand in Moon Animator — all of those are better
than the twelve verbs at what they do, and all of them come out of Studio as a
``KeyframeSequence``. Reading that back means a scene can be assembled from
them, and Linen stops needing to be the thing that invents the movement.

Both containers are handled: ``.rbxmx`` is XML, ``.rbxm`` is the binary form,
and the R6 joint frames are taken off on the way in so what comes back is the
local rotation every other part of this project works in.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from ..clip import AnimationClip
from ..math3d import mat_to_quat
from ..rigs import RIGS, get_rig

#: What Studio writes when nobody set a frame rate. A KeyframeSequence stores
#: times in seconds, not frames, so a rate has to be chosen to resample onto.
DEFAULT_FPS = 30.0


class KeyframeSequenceError(ValueError):
    """An animation file that cannot be read, phrased for whoever exported it."""


def read_keyframe_sequence(path, *, fps: float | None = None) -> AnimationClip:
    """One `.rbxmx` or `.rbxm` animation as a clip.

    Keyframes are stored at arbitrary times and Roblox interpolates between
    them; a clip is a dense per-frame track. So this resamples, which is the
    same thing Studio does at playback and the reason the two agree.
    """
    path = Path(path)
    poses = _poses(path)
    if not poses:
        raise KeyframeSequenceError(
            f"{path.name}: no Keyframe/Pose tree here. A KeyframeSequence is "
            f"what the Animation Editor exports; a rig or a model is not one."
        )

    rig_name = _which_rig(poses)
    rig = get_rig(rig_name)
    frames_of = {part.name: np.asarray(part.joint_frame, dtype=float) for part in rig.parts}

    times = sorted(poses)
    rate = float(fps or DEFAULT_FPS)
    duration = times[-1] - times[0]
    count = max(round(duration * rate) + 1, 1)
    wanted = times[0] + np.arange(count) / rate

    rotations: dict[str, np.ndarray] = {}
    for part in rig.animated_parts:
        axes = frames_of.get(part, np.eye(3))
        # A pose absent from a keyframe is at rest, not missing: Roblox poses
        # every joint it is given and leaves the others where they were.
        sampled = np.stack(
            [
                # Out of the joint's own frame and back into the local rotation
                # every other part of this project speaks.
                axes @ poses[when].get(part, np.eye(3)) @ axes.T
                for when in times
            ]
        )
        quats = mat_to_quat(sampled)
        rotations[part] = _resample(quats, np.asarray(times, dtype=float), wanted)

    return AnimationClip(
        rig=rig,
        fps=rate,
        rotations=rotations,
        name=_name(path) or path.stem,
        metadata={"source": "keyframes", "file": path.name, "keyframes": len(times)},
        loop=_loop(path),
    )


def _resample(quats: np.ndarray, at: np.ndarray, wanted: np.ndarray) -> np.ndarray:
    """Slerp a sparse track onto an even one.

    Nearest-neighbour would hold each pose then jump, which is exactly the
    staircase a KeyframeSequence exists to avoid.
    """
    from ..math3d import quat_slerp, unroll_quaternions

    if len(at) == 1:
        return np.tile(quats[0], (len(wanted), 1))
    track = unroll_quaternions(quats)
    right = np.clip(np.searchsorted(at, wanted, side="right"), 1, len(at) - 1)
    left = right - 1
    span = at[right] - at[left]
    ratio = np.where(span > 1e-9, (wanted - at[left]) / np.where(span > 1e-9, span, 1.0), 0.0)
    return quat_slerp(track[left], track[right], ratio)


def _poses(path: Path) -> dict[float, dict[str, np.ndarray]]:
    """Time -> part -> rotation, from either container."""
    if path.suffix.lower() == ".rbxm":
        return _from_binary(path)
    return _from_xml(path)


def _from_xml(path: Path) -> dict[float, dict[str, np.ndarray]]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise KeyframeSequenceError(f"{path.name}: not readable XML ({exc})") from None

    found: dict[float, dict[str, np.ndarray]] = {}
    for keyframe in (i for i in root.iter("Item") if i.get("class") == "Keyframe"):
        time = keyframe.find("Properties/float[@name='Time']")
        at = float(time.text) if time is not None and time.text else 0.0
        entry = found.setdefault(at, {})
        for pose in (i for i in keyframe.iter("Item") if i.get("class") == "Pose"):
            name = pose.find("Properties/string[@name='Name']")
            cframe = pose.find("Properties/CoordinateFrame[@name='CFrame']")
            if name is None or name.text is None or cframe is None:
                continue
            entry[name.text] = np.array(
                [[float(cframe.find(f"R{r}{c}").text) for c in range(3)] for r in range(3)]
            )
    return found


def _from_binary(path: Path) -> dict[float, dict[str, np.ndarray]]:
    from .rbxm import RbxmError, read_rbxm

    try:
        roots = read_rbxm(path)
    except RbxmError as exc:
        raise KeyframeSequenceError(str(exc)) from None

    def walk(node):
        yield node
        for child in node.children:
            yield from walk(child)

    found: dict[float, dict[str, np.ndarray]] = {}
    for root in roots:
        for node in walk(root):
            if node.class_name != "Keyframe":
                continue
            at = float(node.properties.get("Time", 0.0) or 0.0)
            entry = found.setdefault(at, {})
            for pose in walk(node):
                if pose.class_name != "Pose":
                    continue
                cframe = pose.properties.get("CFrame")
                if cframe is None:
                    continue
                matrix, _offset = cframe
                entry[pose.name] = (
                    np.eye(3) if matrix is None else np.asarray(matrix, dtype=float)
                )
    return found


def _which_rig(poses: dict[float, dict[str, np.ndarray]]) -> str:
    """Which rig this animation was made for, from the joints it poses.

    Guessing wrong writes an R15 animation onto an R6 body, which imports and
    then moves nothing, so this counts rather than assumes.
    """
    named = {part for frame in poses.values() for part in frame}
    scored = {
        name: len(named & {part.name for part in get_rig(name).parts}) for name in RIGS
    }
    best = max(scored, key=lambda name: scored[name])
    if scored[best] == 0:
        raise KeyframeSequenceError(
            f"none of {sorted(named)[:6]} is a joint on R6 or R15 — this animates "
            f"something else, most likely a first-person weapon rig."
        )
    return best


def _name(path: Path) -> str:
    if path.suffix.lower() == ".rbxm":
        from .rbxm import read_rbxm

        for root in read_rbxm(path):
            if root.class_name == "KeyframeSequence" and root.name:
                return root.name
        return ""
    root = ET.parse(path).getroot()
    for item in root.iter("Item"):
        if item.get("class") != "KeyframeSequence":
            continue
        name = item.find("Properties/string[@name='Name']")
        return name.text or "" if name is not None else ""
    return ""


def _loop(path: Path) -> bool:
    if path.suffix.lower() == ".rbxm":
        from .rbxm import read_rbxm

        for root in read_rbxm(path):
            if root.class_name == "KeyframeSequence":
                return bool(root.properties.get("Loop", False))
        return False
    root = ET.parse(path).getroot()
    for item in root.iter("Item"):
        if item.get("class") != "KeyframeSequence":
            continue
        flag = item.find("Properties/bool[@name='Loop']")
        return flag is not None and (flag.text or "").strip() == "true"
    return False
