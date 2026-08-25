"""Export a clip as a Moon Animator 2 save, so a human can finish it by hand.

Everything else Linen writes is *final*: a ``KeyframeSequence`` goes into the
Animation Editor and is played, not worked on. That is the wrong shape for the
one thing generation cannot do. A retargeted capture is a solid base and a poor
performance — the timing is real but the intent is not, and putting the intent
in is what animators are for. Moon Animator is where Roblox animators actually
work, so that is where a generated base has to land.

The save format is not documented, but it does not have to be guessed at
either: MaximumADHD's *Moonlite*, an open-source runtime player for these
saves, reads it in full, and this writer is built against what that reader
requires.

A save is a ``StringValue``, normally under ``ServerStorage.MoonAnimator2Saves``,
and it is two things at once:

* ``.Value`` is JSON — ``Information`` (``Length`` in frames, ``Looped``,
  ``FPS``) and ``Items``, one entry per animated object, each carrying the
  path to it.
* its **children** are the actual motion, as an Instance tree. One folder per
  item, named by that item's index in ``Items``. A rig item holds a ``Rig``
  folder of ``_joint`` folders, each with ``_hier`` (a dotted chain of part
  names), ``default``, and ``_keyframes``.

A keyframe pack is a folder named by its start frame, holding ``Values`` —
children named ``0``, ``1``, … for successive frames — and optionally ``Eases``
indexed the same way.

The one piece of arithmetic that matters: **Moon stores a joint's animated
C1**, not the transform an animation applies. Given the joint's rest C1 as
``default``, the reader recovers ``Transform = c1:Inverse() * default``, so
this writes ``c1 = default * Transform:Inverse()``.

Which is exactly why the save is built by a script in Studio rather than
written whole here. ``default`` is the real ``Motor6D.C1`` of the real rig, and
Linen does not know it — its own rig geometry is derived for drawing and says
so. Reading it off the rig in place is correct on a stock R15 and on a custom
one, which a table of assumed offsets would not be.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from ..math3d import cframe_components, quat_to_mat, unroll_quaternions
from .keyframes import _split_rotations

#: What Moon Animator opens with. A save may declare any rate; this is only
#: the default when the clip has nothing better to offer.
DEFAULT_FPS = 60.0

_ROBLOX_ATTRS = {
    "xmlns:xmime": "http://www.w3.org/2005/05/xmlmime",
    "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xsi:noNamespaceSchemaLocation": "http://www.roblox.com/roblox.xsd",
    "version": "4",
}


def moon_payload(
    clip,
    *,
    name: str | None = None,
    fps: float | None = None,
    angular_tolerance_deg: float = 1.0,
) -> dict[str, Any]:
    """The motion, on Moon's frame grid, reduced to editable keyframes.

    Reduction is not a size optimisation here. A capture at 120 Hz opened as
    one keyframe per frame is not an animation someone can edit — it is a wall
    of keys, and moving any of them does nothing visible. Keeping only the
    frames the motion actually turns on is what makes the timeline workable.

    And it is reduced **per part**, not per clip. A ``KeyframeSequence`` poses
    the whole body at once, so its keyframes are shared and every part gets one
    wherever any part needs one. Moon gives each joint its own track, so a head
    that never turns should carry two keys and not five hundred — otherwise the
    timeline is unreadable in exactly the place it needs to be read.
    """
    rate = float(fps or clip.fps or DEFAULT_FPS)
    scale = rate / float(clip.fps)
    tolerance = np.deg2rad(angular_tolerance_deg)

    tracks: dict[str, list[list]] = {}
    for part, track in clip.rotations.items():
        frames = len(track)
        if frames < 2:
            kept = list(range(frames))
        else:
            keep = {0, frames - 1}
            _split_rotations(unroll_quaternions(track), 0, frames - 1, tolerance, keep)
            kept = sorted(keep)

        keys = []
        for frame in kept:
            matrix = quat_to_mat(np.asarray(track[frame])[None])[0]
            components = cframe_components((0.0, 0.0, 0.0), matrix)
            keys.append([round(frame * scale), [round(float(v), 6) for v in components]])
        tracks[part] = _dedupe(keys)

    length = max((keys[-1][0] for keys in tracks.values() if keys), default=0)
    return {
        "name": name or clip.name or "Linen",
        "fps": rate,
        "length": int(length),
        "looped": bool(getattr(clip, "loop", False)),
        "tracks": tracks,
    }


def _dedupe(keys: list[list]) -> list[list]:
    """Two source frames can round onto one Moon frame; keep the first."""
    seen: set[int] = set()
    out = []
    for frame, components in keys:
        if frame in seen:
            continue
        seen.add(frame)
        out.append([frame, components])
    return out


def moon_module(payload: dict[str, Any]) -> str:
    """The motion as a Luau table, for the builder script to read."""
    lines = [
        "--!strict",
        "-- Generated by Linen. The motion only: no rig, no assumptions about one.",
        "--",
        "-- Each key is a frame and the 12 CFrame components of the transform the",
        "-- animation applies to that part's joint — the same thing a",
        "-- KeyframeSequence Pose carries.",
        "--",
        "-- Named fields rather than {frame, components}: a mixed array infers as",
        "-- the type of its first element, so every key in the file came back as a",
        "-- type error under strict mode.",
        "",
        "export type Key = { frame: number, cframe: { number } }",
        "export type Motion = {",
        "\tName: string,",
        "\tFPS: number,",
        "\tLength: number,",
        "\tLooped: boolean,",
        "\tTracks: { [string]: { Key } },",
        "}",
        "",
        "local motion: Motion = {",
        f"\tName = {_quote(payload['name'])},",
        f"\tFPS = {_number(payload['fps'])},",
        f"\tLength = {payload['length']},",
        f"\tLooped = {'true' if payload['looped'] else 'false'},",
        "",
        "\tTracks = {",
    ]
    for part in sorted(payload["tracks"]):
        keys = payload["tracks"][part]
        lines.append(f"\t\t[{_quote(part)}] = {{")
        for frame, components in keys:
            numbers = ", ".join(_number(value) for value in components)
            lines.append(f"\t\t\t{{ frame = {frame}, cframe = {{{numbers}}} }},")
        lines.append("\t\t},")
    lines += ["\t},", "}", "", "return motion", ""]
    return "\n".join(lines)


#: The builder. Written out in full rather than assembled, because it is meant
#: to be read by whoever runs it: it touches their place, and a script that
#: creates instances in ServerStorage should not be opaque.
_BUILDER = '''--!strict
-- Generated by Linen. Run this once, in Studio, with the rig in the Workspace.
--
--   1. Drag this folder into ServerStorage (anywhere works).
--   2. Right-click the script > Run Script. Or paste it in the Command Bar.
--   3. Open Moon Animator > Load > "{name}".
--
-- It builds a Moon Animator 2 save out of the motion in the Motion module and
-- the joints of the rig as it actually is. Nothing is uploaded and nothing
-- outside ServerStorage.MoonAnimator2Saves is touched.

local ServerStorage = game:GetService("ServerStorage")
local HttpService = game:GetService("HttpService")

-- `script.Parent` is `Instance?` to the type checker, and this script is only
-- ever run from inside the folder Linen wrote, so say so rather than index
-- through a maybe-nil.
local folder = assert(script.Parent, "Linen: lance le script depuis le dossier Linen_*")
local Motion = require(folder:WaitForChild("Motion"))

local RIG_NAME = "{rig}"

local function findRig(): Model
\tlocal named = workspace:FindFirstChild(RIG_NAME)

\tif named and named:IsA("Model") and named:FindFirstChildWhichIsA("Humanoid") then
\t\treturn named
\tend

\tfor _, model in workspace:GetChildren() do
\t\tif model:IsA("Model") and model:FindFirstChildWhichIsA("Humanoid") then
\t\t\treturn model
\t\tend
\tend

\terror(
\t\t"Linen: aucun rig dans le Workspace. Construis-en un (Avatar > Rig Builder "
\t\t.. "> R15) puis relance le script."
\t)
end

-- Every Motor6D, keyed by the name of the part it drives. This is the same
-- key Moon's own reader uses, which is why the hierarchy below is written in
-- part names rather than joint names.
local function motorsByPart(rig: Model): {{ [string]: Motor6D }}
\tlocal motors: {{ [string]: Motor6D }} = {{}}

\tfor _, descendant in rig:GetDescendants() do
\t\tif descendant:IsA("Motor6D") and descendant.Part1 then
\t\t\tmotors[(descendant.Part1 :: BasePart).Name] = descendant
\t\tend
\tend

\treturn motors
end

-- "LowerTorso.UpperTorso.RightUpperArm": the chain of driven parts down to
-- this one. It stops at the highest part that is itself driven by a joint,
-- because that is where Moon's reader starts walking.
local function hierarchy(motors: {{ [string]: Motor6D? }}, part: string): string
\tlocal chain = {{ part }}
\tlocal motor = motors[part]

\twhile motor and motor.Part0 do
\t\tlocal parent = (motor.Part0 :: BasePart).Name

\t\tif motors[parent] == nil then
\t\t\tbreak
\t\tend

\t\ttable.insert(chain, 1, parent)
\t\tmotor = motors[parent]
\tend

\treturn table.concat(chain, ".")
end

local function pathOf(instance: Instance): ({{ string }}, {{ string }})
\tlocal names, classes = {{}}, {{}}
\tlocal current: Instance? = instance

\twhile current do
\t\ttable.insert(names, 1, current.Name)
\t\ttable.insert(classes, 1, current.ClassName)
\t\tcurrent = current.Parent
\tend

\treturn names, classes
end

local function value(class: string, name: string, parent: Instance): any
\tlocal instance = Instance.new(class)
\tinstance.Name = name
\tinstance.Parent = parent
\treturn instance
end

local function folder(name: string, parent: Instance): Folder
\tlocal instance = Instance.new("Folder")
\tinstance.Name = name
\tinstance.Parent = parent
\treturn instance
end

local function toCFrame(components: {{ any }}): CFrame
\treturn CFrame.new(
\t\tcomponents[1], components[2], components[3],
\t\tcomponents[4], components[5], components[6],
\t\tcomponents[7], components[8], components[9],
\t\tcomponents[10], components[11], components[12]
\t)
end

local rig = findRig()
local motors = motorsByPart(rig)

local saves = ServerStorage:FindFirstChild("MoonAnimator2Saves")

if not saves then
\tsaves = folder("MoonAnimator2Saves", ServerStorage)
end

assert(saves)

local existing = saves:FindFirstChild(Motion.Name)

if existing then
\texisting:Destroy()
end

local save = Instance.new("StringValue")
save.Name = Motion.Name

local names, classes = pathOf(rig)

save.Value = HttpService:JSONEncode({{
\tInformation = {{
\t\tLength = Motion.Length,
\t\tLooped = Motion.Looped,
\t\tFPS = Motion.FPS,
\t}},

\tItems = {{
\t\t{{
\t\t\tPath = {{
\t\t\t\tItemType = "Rig",
\t\t\t\tInstanceNames = names,
\t\t\t\tInstanceTypes = classes,
\t\t\t}},
\t\t}},
\t}},
}})

-- "1" is the index of the single item declared above.
local item = folder("1", save)
local rigFolder = folder("Rig", item)

local written, skipped = 0, {{}}

for part, keys in Motion.Tracks do
\tlocal motor = motors[part]

\tif not motor then
\t\ttable.insert(skipped, part)
\t\tcontinue
\tend

\tlocal joint = folder("_joint", rigFolder)
\tlocal default = motor.C1

\tlocal hier = value("StringValue", "_hier", joint)
\thier.Value = hierarchy(motors, part)

\tlocal rest = value("CFrameValue", "default", joint)
\trest.Value = default

\tlocal keyframes = folder("_keyframes", joint)

\tfor _, key in keys do
\t\tlocal frame = key.frame
\t\tlocal transform = toCFrame(key.cframe)

\t\t-- Moon stores the joint's animated C1. Its reader recovers the
\t\t-- transform as `c1:Inverse() * default`, so this is that, inverted.
\t\tlocal pack = folder(tostring(frame), keyframes)
\t\tlocal values = folder("Values", pack)

\t\tlocal at = value("CFrameValue", "0", values)
\t\tat.Value = default * transform:Inverse()

\t\tlocal eases = folder("Eases", pack)
\t\tlocal ease = folder("0", eases)
\t\tlocal easeType = value("StringValue", "Type", ease)
\t\teaseType.Value = "Linear"

\t\tlocal params = folder("Params", ease)
\t\tlocal direction = value("StringValue", "Direction", params)
\t\tdirection.Value = "InOut"
\tend

\twritten += 1
end

save.Parent = saves

print(
\t`Linen: "{{Motion.Name}}" -> ServerStorage.MoonAnimator2Saves ({{written}} `
\t.. `articulations, {{Motion.Length}} images a {{Motion.FPS}} fps). `
\t.. `Ouvre Moon Animator > Load.`
)

if #skipped > 0 then
\twarn(
\t\t`Linen: {{#skipped}} parties absentes du rig et ignorees : `
\t\t.. table.concat(skipped, ", ")
\t)
end
'''


def moon_builder(payload: dict[str, Any], *, rig_name: str = "Dummy") -> str:
    return _BUILDER.format(name=payload["name"], rig=rig_name)


def build_moon_save(clip, **kwargs) -> ET.ElementTree:
    """A folder holding the motion and the script that installs it."""
    rig_name = kwargs.pop("rig_name", "Dummy")
    payload = moon_payload(clip, **kwargs)

    root = ET.Element("roblox", _ROBLOX_ATTRS)
    referent = iter(f"RBX{index}" for index in range(10_000))

    top = ET.SubElement(root, "Item", {"class": "Folder", "referent": next(referent)})
    properties = ET.SubElement(top, "Properties")
    ET.SubElement(properties, "string", {"name": "Name"}).text = (
        f"Linen_{payload['name']}"
    )

    for class_name, name, source in (
        ("ModuleScript", "Motion", moon_module(payload)),
        ("Script", "InstallerLinen", moon_builder(payload, rig_name=rig_name)),
    ):
        item = ET.SubElement(top, "Item", {"class": class_name, "referent": next(referent)})
        props = ET.SubElement(item, "Properties")
        ET.SubElement(props, "string", {"name": "Name"}).text = name
        ET.SubElement(props, "ProtectedString", {"name": "Source"}).text = source

    return ET.ElementTree(root)


def write_moon(clip, path: str | Path, **kwargs) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    build_moon_save(clip, **kwargs).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _quote(text: str) -> str:
    return json.dumps(str(text))


def _number(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"
