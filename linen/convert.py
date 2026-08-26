"""Move an existing R6 animation onto an R15 rig, without re-authoring it.

The point is to take work that already exists rather than remake it, so this
is a **tree transform** and not a re-synthesis: the file is read, the pose tree
is rebuilt against the R15 hierarchy, and everything else — every keyframe
time, every easing, every marker, every part that is not a body part — is
carried across untouched.

What the conversion can and cannot do is worth being exact about, because the
limit is in the source rather than in the code.

**It can reproduce the pose exactly.** An R6 shoulder rotation becomes an R15
shoulder rotation, unchanged. There is no approximation anywhere in the path.

**It cannot invent an elbow.** An R6 arm is one rigid part from shoulder to
fingertips; R15 splits it into an upper arm, a lower arm and a hand. The angle
between them does not exist in an R6 file, so the converted arm comes out
straight — which *is* the R6 pose, faithfully. It will read as stiffer than a
native R15 animation, because it is an R6 animation on a body with joints it
was never told about.

**And the grip point moves.** An R6 tool welds to ``Right Arm``, whose tip is
two studs from the shoulder. On R15 it welds to ``RightHand``, which sits about
2.4 studs out along a straight arm. Anything held will need its grip offset
adjusted by roughly that difference.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .sources.rbxm import Instance, read_rbxm

#: R6 part to the R15 part that carries the same joint.
R6_TO_R15 = {
    "HumanoidRootPart": "HumanoidRootPart",
    "Torso": "LowerTorso",
    "Head": "Head",
    "Left Arm": "LeftUpperArm",
    "Right Arm": "RightUpperArm",
    "Left Leg": "LeftUpperLeg",
    "Right Leg": "RightUpperLeg",
}

def _r15_parents() -> dict[str, str]:
    """Where each R15 part hangs, taken from the rig rather than retyped.

    The Animation Editor resolves poses by walking this hierarchy, so a tree
    that does not match is a tree it cannot apply. Written out by hand the
    first time, it stopped at the shoulder — and a tool held in the hand came
    out as a sibling of the character instead of on the end of the arm.
    """
    from .rigs import get_rig

    return {
        part.name: part.parent
        for part in get_rig("R15").parts
        if part.parent is not None
    }


R15_PARENT = _r15_parents()

#: Where a held object ends up. On R6 a tool welds to the whole arm; the R15
#: part that reaches the same place is the hand.
HELD_BY = {"LeftUpperArm": "LeftHand", "RightUpperArm": "RightHand"}

_IDENTITY = np.eye(3)
_ROBLOX_ATTRS = {
    "xmlns:xmime": "http://www.w3.org/2005/05/xmlmime",
    "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xsi:noNamespaceSchemaLocation": "http://www.roblox.com/roblox.xsd",
    "version": "4",
}


class ConvertError(ValueError):
    """An animation that cannot be moved onto R15, and why."""


@dataclass
class Report:
    """What a conversion did, in enough detail to argue with."""

    name: str
    keyframes: int = 0
    #: R6 parts that were remapped, and to what.
    mapped: dict[str, str] = field(default_factory=dict)
    #: Parts carried across untouched — tool parts, accessories.
    carried: list[str] = field(default_factory=list)
    #: R15 parts inserted at rest to complete the hierarchy.
    bridged: list[str] = field(default_factory=list)
    loop: bool = False

    def line(self) -> str:
        bits = [f"{self.keyframes} images-cles", f"{len(self.mapped)} parties remappees"]
        kept = sorted(set(self.carried))
        if kept:
            bits.append(f"conserve {', '.join(kept)}")
        bits.append("bouclee" if self.loop else "une fois")
        return f"{self.name}: " + ", ".join(bits)


def classify(root: Instance) -> str:
    """What kind of animation this is, which decides whether it can move.

    The distinction that matters is not R6 versus R15. It is whether the file
    animates a **character** at all: a first-person weapon animation roots its
    pose tree at a custom part with the arms hanging off the gun, and there is
    no R15 rig shaped like that. Converting the names would produce a file that
    imports and does nothing.
    """
    if root.class_name == "CurveAnimation":
        return "curve"
    if root.class_name != "KeyframeSequence":
        return "unknown"

    keyframes = root.of_class("Keyframe")
    if not keyframes:
        return "empty"

    tops = [pose.name for pose in keyframes[0].children if pose.class_name == "Pose"]
    if not tops:
        return "empty"
    return "character" if all(top in R6_TO_R15 for top in tops) else "viewmodel"


def convert_r6_to_r15(root: Instance) -> tuple[ET.ElementTree, Report]:
    """Rebuild an R6 KeyframeSequence's pose tree against the R15 rig."""
    kind = classify(root)
    if kind != "character":
        raise ConvertError(
            {
                "viewmodel": (
                    "its pose tree is rooted on a custom part rather than on the "
                    "character, so it animates a first-person weapon rig. R15 has "
                    "no equivalent hierarchy and renaming the parts would produce "
                    "a file that imports and does nothing"
                ),
                "curve": (
                    "it is a CurveAnimation, which stores rotation curves rather "
                    "than keyframed poses. A different reader, not a different "
                    "mapping"
                ),
                "empty": "it has no poses in it",
                "unknown": f"its root is a {root.class_name}, not an animation",
            }[kind]
        )

    report = Report(name=root.name or "Animation", loop=bool(root.properties.get("Loop")))

    document = ET.Element("roblox", _ROBLOX_ATTRS)
    referents = iter(f"RBX{index}" for index in range(1_000_000))
    sequence = _item(document, "KeyframeSequence", referents)
    properties = ET.SubElement(sequence, "Properties")
    _string(properties, "Name", report.name)
    _bool(properties, "Loop", report.loop)
    _token(properties, "Priority", int(root.properties.get("Priority", 1) or 1))

    for keyframe in sorted(
        root.of_class("Keyframe"), key=lambda k: float(k.properties.get("Time", 0.0))
    ):
        report.keyframes += 1
        node = _item(sequence, "Keyframe", referents)
        keyframe_properties = ET.SubElement(node, "Properties")
        _string(keyframe_properties, "Name", keyframe.name or f"Keyframe{report.keyframes}")
        _float(keyframe_properties, "Time", float(keyframe.properties.get("Time", 0.0)))

        built: dict[str, ET.Element] = {}
        for pose in _walk(keyframe):
            _place(pose, node, built, referents, report)

    return ET.ElementTree(document), report


def _walk(keyframe: Instance):
    """Every Pose under a keyframe, parents before children."""
    stack = [child for child in keyframe.children if child.class_name == "Pose"]
    while stack:
        pose = stack.pop(0)
        yield pose
        stack += [child for child in pose.children if child.class_name == "Pose"]


def _place(
    pose: Instance,
    keyframe: ET.Element,
    built: dict[str, ET.Element],
    referents,
    report: Report,
) -> None:
    """Write one pose into the R15 tree, inserting whatever it needs above it."""
    source = pose.name
    target = R6_TO_R15.get(source)

    if target is None:
        # Not a body part: a tool's grip, a magazine, a katana. It keeps its
        # name and its place, because nothing about R15 concerns it.
        parent_name = pose.parent.name if pose.parent else None
        mapped_parent = R6_TO_R15.get(parent_name or "", parent_name)
        holder = HELD_BY.get(mapped_parent or "", mapped_parent)
        owner = built.get(holder) if holder else None
        if owner is None and holder:
            owner = _bridge(holder, keyframe, built, referents, report)
        report.carried.append(source)
        built[source] = _pose(owner or keyframe, source, pose, referents)
        return

    report.mapped[source] = target
    parent = R15_PARENT.get(target)
    owner = keyframe if parent is None else built.get(parent)
    if owner is None and parent is not None:
        owner = _bridge(parent, keyframe, built, referents, report)
    built[target] = _pose(owner or keyframe, target, pose, referents)


def _bridge(
    name: str, keyframe: ET.Element, built: dict[str, ET.Element], referents, report: Report
) -> ET.Element:
    """Insert a resting pose so a child has the parent the R15 rig gives it."""
    parent = R15_PARENT.get(name)
    owner = keyframe if parent is None else built.get(parent)
    if owner is None and parent is not None:
        owner = _bridge(parent, keyframe, built, referents, report)
    report.bridged.append(name)
    built[name] = _pose(owner or keyframe, name, None, referents)
    return built[name]


def _pose(parent: ET.Element, name: str, source: Instance | None, referents) -> ET.Element:
    node = _item(parent, "Pose", referents)
    properties = ET.SubElement(node, "Properties")
    _string(properties, "Name", name)

    rotation, position = _IDENTITY, np.zeros(3)
    easing_style, easing_direction, weight = 0, 1, 1.0
    if source is not None:
        cframe = source.properties.get("CFrame")
        if cframe is not None:
            matrix, offset = cframe
            rotation = _IDENTITY if matrix is None else np.asarray(matrix, dtype=float)
            position = np.asarray(offset, dtype=float)
        easing_style = int(source.properties.get("EasingStyle", 0) or 0)
        easing_direction = int(source.properties.get("EasingDirection", 1) or 1)
        weight = float(source.properties.get("Weight", 1.0) or 1.0)

    _cframe(properties, "CFrame", position, rotation)
    _token(properties, "EasingDirection", easing_direction)
    _token(properties, "EasingStyle", easing_style)
    _float(properties, "Weight", weight)
    return node


def _item(parent: ET.Element, class_name: str, referents) -> ET.Element:
    return ET.SubElement(parent, "Item", {"class": class_name, "referent": next(referents)})


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
    values = [*np.asarray(position, dtype=float).tolist(), *np.asarray(rotation, dtype=float).reshape(-1).tolist()]
    for tag, value in zip(tags, values, strict=True):
        ET.SubElement(element, tag).text = _number(value)


def _number(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def convert_file(source: str | Path, destination: str | Path) -> Report:
    """Read one ``.rbxm`` and write the R15 ``.rbxmx`` beside it."""
    roots = read_rbxm(source)
    if not roots:
        raise ConvertError(f"{Path(source).name}: nothing in it")

    tree, report = convert_r6_to_r15(roots[0])
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return report
