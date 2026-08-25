"""Read a Collada (.dae) motion capture export, without Blender.

This exists to remove the one manual step from the only route to realistic
animation that is actually open. Mixamo's library is real capture, cleaned by
professional animators, and free for unlimited commercial use — but it exports
FBX and Collada, not BVH, so the documented path went through Blender.

Collada is the better target of the two, and not by a small margin. FBX encodes
animation as per-channel curves, and reading them back correctly means
reproducing rotation order, pre- and post-rotation, and time modes; getting any
of those wrong yields a skeleton that looks almost right, which is the worst
possible failure. A Collada export from Mixamo bakes **a full 4x4 matrix per
joint per frame**. There is nothing left to interpret.

What comes out is the same three things :func:`linen.sources.to_landmark_track`
already takes from a BVH — joint names, a frame rate, and world positions per
frame — so every stage after this one is the code that was already there.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: Collada namespaces its elements, and the version varies between exporters.
_NAMESPACE = re.compile(r"^\{[^}]*\}")

#: Mixamo prefixes every joint with this, and which separator it uses depends
#: on the exporter: the FBX side writes ``mixamorig:Hips``, the Collada side
#: writes ``mixamorig_Hips``. Both are stripped, so the existing "mixamo"
#: skeleton mapping matches without a second set of names to maintain.
_MIXAMO_PREFIXES = ("mixamorig:", "mixamorig_")

#: Frame rate used when a file's own timing cannot be read. Mixamo's own
#: default, and the rate everything else in Linen assumes.
DEFAULT_FPS = 30.0


class ColladaError(ValueError):
    """A file that cannot be read, phrased for whoever exported it."""


@dataclass
class ColladaMotion:
    """A skeleton and its baked animation, in the file's own units.

    Deliberately the same surface a ``BvhMotion`` presents — ``names``, ``fps``
    and :meth:`world_positions` — so the loader below is the only new code and
    the retargeting path is untouched.
    """

    joints: list[str]
    parents: list[int]
    #: ``(frames, joints, 4, 4)`` local transforms, one per joint per frame.
    locals: np.ndarray
    frame_time: float

    @property
    def fps(self) -> float:
        return 1.0 / self.frame_time

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.joints)

    def world_positions(self) -> np.ndarray:
        """Forward kinematics: ``(frames, joints, 3)`` in the file's units."""
        frames = self.locals.shape[0]
        world = np.zeros((frames, len(self.joints), 4, 4))
        for index, parent in enumerate(self.parents):
            local = self.locals[:, index]
            world[:, index] = local if parent < 0 else world[:, parent] @ local
        return world[:, :, :3, 3]


def _tag(element: ET.Element) -> str:
    return _NAMESPACE.sub("", element.tag)


def _find(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _tag(child) == name:
            return child
    return None


def _findall(parent: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in parent if _tag(child) == name]


def _floats(text: str | None) -> np.ndarray:
    return np.fromstring((text or "").strip().replace("\n", " "), sep=" ")


def read_collada(path: str | Path) -> ColladaMotion:
    """Parse a baked Collada animation into a skeleton and its motion."""
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ColladaError(f"{path.name}: not readable XML ({exc})") from None

    scenes = _find(root, "library_visual_scenes")
    if scenes is None:
        raise ColladaError(
            f"{path.name}: no library_visual_scenes, so there is no skeleton in it"
        )

    joints: list[str] = []
    parents: list[int] = []
    rest: list[np.ndarray] = []
    ids: list[str] = []
    for scene in _findall(scenes, "visual_scene"):
        for node in _findall(scene, "node"):
            _walk(node, -1, joints, parents, rest, ids)
    if not joints:
        raise ColladaError(
            f"{path.name}: no JOINT nodes. Export it with the skeleton — on "
            f"Mixamo that is Collada, and 'Without Skin' still keeps the bones."
        )

    curves, frame_time = _animation(root, ids)
    frames = max((len(track) for track in curves.values()), default=1)

    locals_ = np.zeros((frames, len(joints), 4, 4))
    for index, matrix in enumerate(rest):
        track = curves.get(ids[index])
        locals_[:, index] = np.broadcast_to(matrix, (frames, 4, 4)) if track is None else track

    return ColladaMotion(
        joints=joints, parents=parents, locals=locals_, frame_time=frame_time
    )


def _walk(
    node: ET.Element,
    parent: int,
    joints: list[str],
    parents: list[int],
    rest: list[np.ndarray],
    ids: list[str],
) -> None:
    """Collect the JOINT nodes of the scene, depth first.

    Nodes that are not joints are still descended into: an exporter is free to
    park the skeleton under a transform node, and Mixamo does.
    """
    index = parent
    if node.get("type") == "JOINT":
        name = node.get("sid") or node.get("name") or node.get("id") or ""
        for prefix in _MIXAMO_PREFIXES:
            name = name.removeprefix(prefix)
        index = len(joints)
        joints.append(name)
        parents.append(parent)
        rest.append(_matrix_of(node))
        ids.append(node.get("id") or name)

    for child in _findall(node, "node"):
        _walk(child, index, joints, parents, rest, ids)


def _matrix_of(node: ET.Element) -> np.ndarray:
    """The node's own bind transform, as a 4x4."""
    matrix = _find(node, "matrix")
    if matrix is not None:
        values = _floats(matrix.text)
        if values.size == 16:
            return values.reshape(4, 4)
    return np.eye(4)


def _animation(root: ET.Element, ids: list[str]) -> tuple[dict[str, np.ndarray], float]:
    """Per joint id, ``(frames, 4, 4)`` local transforms, and the frame time."""
    library = _find(root, "library_animations")
    if library is None:
        raise ColladaError(
            "no library_animations: this file has a skeleton but no motion on it"
        )

    curves: dict[str, np.ndarray] = {}
    times: np.ndarray | None = None

    for animation in _flatten(library):
        sources = {
            source.get("id", ""): source for source in _findall(animation, "source")
        }
        sampler = _find(animation, "sampler")
        channel = _find(animation, "channel")
        if sampler is None or channel is None:
            continue

        target = (channel.get("target") or "").split("/")[0]
        if target not in ids:
            continue

        inputs = {
            (item.get("semantic") or ""): (item.get("source") or "").lstrip("#")
            for item in _findall(sampler, "input")
        }
        stamps = _values(sources.get(inputs.get("INPUT", "")))
        matrices = _values(sources.get(inputs.get("OUTPUT", "")))
        if stamps is None or matrices is None or matrices.size % 16:
            continue

        curves[target] = matrices.reshape(-1, 4, 4)
        if times is None or len(stamps) > len(times):
            times = stamps

    if not curves or times is None or len(times) < 2:
        raise ColladaError(
            "the animation carries no baked joint matrices. Export it from "
            "Mixamo as Collada rather than converting it by hand — a curve-based "
            "export needs interpreting, and a baked one does not."
        )

    span = float(times[-1] - times[0])
    frame_time = span / max(len(times) - 1, 1) if span > 0 else 1.0 / DEFAULT_FPS
    return curves, frame_time


def _flatten(element: ET.Element) -> list[ET.Element]:
    """Every ``animation`` element, including the nested ones.

    Exporters differ: some write one flat list, some group per joint and nest a
    second level inside.
    """
    found = []
    for child in _findall(element, "animation"):
        found.append(child)
        found += _flatten(child)
    return found


def _values(source: ET.Element | None) -> np.ndarray | None:
    if source is None:
        return None
    array = _find(source, "float_array")
    return None if array is None else _floats(array.text)


def load_collada(
    path: str | Path,
    *,
    skeleton: str = "mixamo",
    units: str = "cm",
    fps: float | None = None,
):
    """A Collada file as a landmark track, ready for the retargeter."""
    from .skeletons import get_skeleton, to_landmark_track

    return to_landmark_track(
        read_collada(path), get_skeleton(skeleton), units=units, fps=fps
    )
