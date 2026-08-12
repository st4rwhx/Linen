"""Write an :class:`~linen.clip.AnimationClip` as a Roblox ``.rbxmx`` file.

The output is a ``KeyframeSequence`` holding one ``Keyframe`` per retained
frame, each with a tree of ``Pose`` instances mirroring the rig's part tree.
Roblox's Animation Editor loads this with *Import > From File*, and from there
it publishes like any hand-made animation.

Note on Open Cloud: the Assets API accepts animation uploads, but the
documentation is explicit that ``.rbxm``/``.rbxmx`` files edited outside Studio
may be rejected, so treat Studio import as the supported route and Open Cloud
as a convenience that may or may not accept a given file.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

from ..clip import AnimationClip
from ..math3d import cframe_components, quat_to_mat
from ..rigs import Part, RigDefinition
from .keyframes import reduce_keyframes

#: Enum.AnimationPriority
PRIORITIES: dict[str, int] = {
    "Idle": 0,
    "Movement": 1,
    "Action": 2,
    "Action2": 3,
    "Action3": 4,
    "Action4": 5,
    "Core": 1000,
}

#: Enum.PoseEasingStyle / Enum.PoseEasingDirection
EASING_STYLES: dict[str, int] = {
    "Linear": 0,
    "Constant": 1,
    "Elastic": 2,
    "Cubic": 3,
    "Bounce": 4,
    "CubicV2": 5,
}
EASING_DIRECTIONS: dict[str, int] = {"In": 0, "Out": 1, "InOut": 2}

_ROBLOX_ATTRS = {
    "xmlns:xmime": "http://www.w3.org/2005/05/xmlmime",
    "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xsi:noNamespaceSchemaLocation": "http://www.roblox.com/roblox.xsd",
    "version": "4",
}


class _Referents:
    """Roblox needs a unique ``referent`` per instance in the file."""

    def __init__(self) -> None:
        self._next = 0

    def take(self) -> str:
        value = f"RBX{self._next}"
        self._next += 1
        return value


def build_keyframe_sequence(
    clip: AnimationClip,
    *,
    easing_style: str = "Linear",
    easing_direction: str = "Out",
    angular_tolerance_deg: float = 1.0,
    position_tolerance_studs: float = 0.02,
    frames: list[int] | None = None,
    markers: dict[int, list[tuple[str, str]]] | None = None,
) -> ET.ElementTree:
    """Build the XML tree for ``clip``.

    ``frames`` overrides keyframe reduction when you want every sampled frame,
    e.g. ``list(range(clip.frame_count))``.

    ``markers`` maps a frame to ``(name, value)`` pairs written as
    ``KeyframeMarker`` instances. At runtime Roblox fires
    ``AnimationTrack:GetMarkerReachedSignal(name)`` with the value the moment
    playback reaches that keyframe — which is how a gunshot lands on the frame
    the hand opens rather than a tenth of a second around it. Markers force
    their frame to be kept even when reduction would otherwise drop it, since
    an event on a discarded keyframe simply never fires.
    """
    if easing_style not in EASING_STYLES:
        raise ValueError(
            f"unknown easing style {easing_style!r}; "
            f"expected one of {', '.join(EASING_STYLES)}"
        )
    if easing_direction not in EASING_DIRECTIONS:
        raise ValueError(
            f"unknown easing direction {easing_direction!r}; "
            f"expected one of {', '.join(EASING_DIRECTIONS)}"
        )
    if clip.priority not in PRIORITIES:
        raise ValueError(
            f"unknown priority {clip.priority!r}; expected one of {', '.join(PRIORITIES)}"
        )

    # Checked here rather than left to the number formatter: a NaN quaternion
    # normalises to zero and then reads back as the identity, so a limb that
    # failed to solve would export as a silently unanimated part.
    for part, track in clip.rotations.items():
        if not np.isfinite(track).all():
            bad = int(np.argmax(~np.isfinite(track).all(axis=-1)))
            raise ValueError(f"{part!r} has non-finite rotations, first at frame {bad}")
    if clip.root_positions is not None and not np.isfinite(clip.root_positions).all():
        raise ValueError("root_positions contain non-finite values")

    markers = markers or {}

    if frames is None:
        frames = reduce_keyframes(
            clip,
            angular_tolerance_deg=angular_tolerance_deg,
            position_tolerance_studs=position_tolerance_studs,
        )
    # A marker on a frame reduction discarded would never fire, so the frames
    # events need are non-negotiable.
    if markers:
        frames = sorted(set(frames) | {f for f in markers if 0 <= f < clip.frame_count})
    if not frames:
        raise ValueError("no keyframes to write")

    unknown = {f for f in markers if not 0 <= f < clip.frame_count}
    if unknown:
        raise ValueError(
            f"markers fall outside the clip's {clip.frame_count} frames: "
            f"{sorted(unknown)}"
        )

    referents = _Referents()
    root = ET.Element("roblox", _ROBLOX_ATTRS)

    sequence = ET.SubElement(
        root, "Item", {"class": "KeyframeSequence", "referent": referents.take()}
    )
    properties = ET.SubElement(sequence, "Properties")
    _string(properties, "Name", clip.name)
    _bool(properties, "Loop", clip.loop)
    _token(properties, "Priority", PRIORITIES[clip.priority])

    # Precompute rotation matrices once rather than per keyframe per part.
    matrices = {part: quat_to_mat(track) for part, track in clip.rotations.items()}

    for frame in frames:
        keyframe = ET.SubElement(
            sequence, "Item", {"class": "Keyframe", "referent": referents.take()}
        )
        keyframe_props = ET.SubElement(keyframe, "Properties")
        _string(keyframe_props, "Name", f"Keyframe{frame}")
        _float(keyframe_props, "Time", frame / clip.fps)

        _write_pose(
            keyframe,
            clip,
            clip.rig.root,
            frame,
            matrices,
            referents,
            EASING_STYLES[easing_style],
            EASING_DIRECTIONS[easing_direction],
        )

        for name, value in markers.get(frame, ()):
            marker = ET.SubElement(
                keyframe, "Item", {"class": "KeyframeMarker", "referent": referents.take()}
            )
            marker_props = ET.SubElement(marker, "Properties")
            _string(marker_props, "Name", name)
            _string(marker_props, "Value", value)

    ET.indent(root, space="  ")
    return ET.ElementTree(root)


def _write_pose(
    parent: ET.Element,
    clip: AnimationClip,
    part: Part,
    frame: int,
    matrices: dict[str, np.ndarray],
    referents: _Referents,
    easing_style: int,
    easing_direction: int,
) -> None:
    rig: RigDefinition = clip.rig
    pose = ET.SubElement(parent, "Item", {"class": "Pose", "referent": referents.take()})
    properties = ET.SubElement(pose, "Properties")
    _string(properties, "Name", part.name)

    if part.parent is None:
        position = (
            clip.root_positions[frame]
            if clip.root_positions is not None
            else np.zeros(3)
        )
        rotation = np.eye(3)
    else:
        position = np.zeros(3)
        track = matrices.get(part.name)
        rotation = np.eye(3) if track is None else track[frame]

    _cframe(properties, "CFrame", position, rotation)
    _token(properties, "EasingDirection", easing_direction)
    _token(properties, "EasingStyle", easing_style)
    _float(properties, "Weight", 1.0)

    for child in rig.children(part.name):
        _write_pose(
            pose, clip, child, frame, matrices, referents, easing_style, easing_direction
        )


def write_rbxmx(clip: AnimationClip, path: str | Path, **kwargs) -> Path:
    """Write ``clip`` to ``path`` and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = build_keyframe_sequence(clip, **kwargs)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


# --------------------------------------------------------------------------
# property serialisation
# --------------------------------------------------------------------------
def _string(parent: ET.Element, name: str, value: str) -> None:
    ET.SubElement(parent, "string", {"name": name}).text = value


def _bool(parent: ET.Element, name: str, value: bool) -> None:
    ET.SubElement(parent, "bool", {"name": name}).text = "true" if value else "false"


def _token(parent: ET.Element, name: str, value: int) -> None:
    ET.SubElement(parent, "token", {"name": name}).text = str(value)


def _float(parent: ET.Element, name: str, value: float) -> None:
    ET.SubElement(parent, "float", {"name": name}).text = _number(value)


def _cframe(parent: ET.Element, name: str, position, rotation) -> None:
    element = ET.SubElement(parent, "CoordinateFrame", {"name": name})
    tags = ("X", "Y", "Z", "R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")
    for tag, value in zip(tags, cframe_components(position, rotation)):
        ET.SubElement(element, tag).text = _number(value)


def _number(value: float) -> str:
    """Roblox's parser wants plain decimals, and `-0` reads badly in diffs."""
    value = float(value)
    if not np.isfinite(value):
        raise ValueError(f"refusing to write non-finite value {value}")
    if value == 0.0:
        return "0"
    return f"{value:.6f}".rstrip("0").rstrip(".")
