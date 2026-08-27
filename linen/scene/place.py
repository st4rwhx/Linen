"""What is actually in the place, so a scene can be staged in it.

Without this a cinematic is written in a void: made-up actor names at made-up
coordinates, with the camera framed on nothing. It plays, and every position in
it is wrong for the game it was written for — which is the failure that costs a
whole evening, because the file imports and the script runs.

So the place gets read first. `SURVEY` is a Luau script that walks the open
place and prints one JSON object: the rigs and which of R6/R15 they are, the
landmarks worth pointing a camera at, and the sounds already there. Paste it in
the Command Bar, or let a Studio MCP `run_code` run it — either way the answer
comes back as text, and :func:`read_place` takes it with or without the console
noise around it.

Nothing here talks to Studio. This project cannot reach a machine it is not
running on, so the transport is a human or an MCP server, and what is written
here is only the two ends: what to ask for, and what to do with the answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Vec3 = tuple[float, float, float]

BEGIN = "--LINEN-PLACE-BEGIN--"
END = "--LINEN-PLACE-END--"

#: Run in Studio. Prints one JSON object between two markers.
SURVEY = f"""\
--!strict
-- Linen: survey the open place, so a scene can be staged in it rather than in
-- a void. Paste this into the Command Bar (View > Command Bar) and press
-- Enter, then copy everything between the two markers into a file.
--
-- It reads. It changes nothing.

local Workspace = game:GetService("Workspace")

local MAX_LANDMARKS = 60
local MAX_SOUNDS = 40

local function round(value: number): number
\treturn math.floor(value * 100 + 0.5) / 100
end

local function vec(v: Vector3): {{ number }}
\treturn {{ round(v.X), round(v.Y), round(v.Z) }}
end

-- A rig is a Model with a Humanoid. Which rig it is comes from the parts it
-- has: only R15 splits the torso in two, and only R6 has a part called Torso.
local function rigKind(model: Model): string?
\tif model:FindFirstChild("UpperTorso") and model:FindFirstChild("LowerTorso") then
\t\treturn "R15"
\telseif model:FindFirstChild("Torso") then
\t\treturn "R6"
\tend
\treturn nil
end

local rigs = {{}}
local landmarks = {{}}
local sounds = {{}}

for _, descendant in Workspace:GetDescendants() do
\tif descendant:IsA("Humanoid") then
\t\tlocal model = descendant.Parent
\t\tif model and model:IsA("Model") then
\t\t\tlocal pivot = model:GetPivot()
\t\t\tlocal _, yaw = pivot:ToOrientation()
\t\t\ttable.insert(rigs, {{
\t\t\t\tname = model.Name,
\t\t\t\trig = rigKind(model) or "unknown",
\t\t\t\tposition = vec(pivot.Position),
\t\t\t\tyaw = round(math.deg(yaw)),
\t\t\t\tisPlayer = game:GetService("Players"):GetPlayerFromCharacter(model) ~= nil,
\t\t\t}})
\t\tend
\telseif descendant:IsA("Sound") and descendant.SoundId ~= "" then
\t\tif #sounds < MAX_SOUNDS then
\t\t\ttable.insert(sounds, {{
\t\t\t\tname = descendant.Name,
\t\t\t\tid = descendant.SoundId,
\t\t\t\tparent = descendant.Parent and descendant.Parent.Name or "",
\t\t\t}})
\t\tend
\tend
end

-- Landmarks are what a camera can be pointed at and what a scene can be placed
-- against. Anonymous scenery is not one: a hundred parts called "Part" tell you
-- nothing, so they are left out and only what someone bothered to name is kept.
local anonymous = {{ Part = true, Wedge = true, MeshPart = true, Union = true, Model = true }}
for _, child in Workspace:GetDescendants() do
\tif #landmarks >= MAX_LANDMARKS then
\t\tbreak
\tend
\tlocal keep = false
\tlocal position, size
\tif child:IsA("BasePart") and not child.Parent:FindFirstChildOfClass("Humanoid") then
\t\tkeep = not anonymous[child.Name]
\t\tposition, size = child.Position, child.Size
\telseif child:IsA("Model") and child.PrimaryPart and not child:FindFirstChildOfClass("Humanoid") then
\t\tkeep = not anonymous[child.Name]
\t\tlocal box, extent = child:GetBoundingBox()
\t\tposition, size = box.Position, extent
\tend
\tif keep and position and size then
\t\ttable.insert(landmarks, {{
\t\t\tname = child.Name,
\t\t\tclass = child.ClassName,
\t\t\tposition = vec(position),
\t\t\tsize = vec(size),
\t\t}})
\tend
end

print("{BEGIN}")
print(game:GetService("HttpService"):JSONEncode({{
\tplace = game.Name,
\tplaceId = game.PlaceId,
\trigs = rigs,
\tlandmarks = landmarks,
\tsounds = sounds,
}}))
print("{END}")
"""


class PlaceError(ValueError):
    """A survey that cannot be read, phrased for whoever ran it."""


@dataclass(frozen=True)
class Rig:
    """A character already standing in the place."""

    name: str
    rig: str
    position: Vec3
    yaw: float = 0.0
    is_player: bool = False


@dataclass(frozen=True)
class Landmark:
    """Something named that a camera can look at or a scene can sit against."""

    name: str
    class_name: str
    position: Vec3
    size: Vec3


@dataclass
class Place:
    """One reading of a Studio place. A snapshot, not a connection."""

    name: str = ""
    place_id: int = 0
    rigs: list[Rig] = field(default_factory=list)
    landmarks: list[Landmark] = field(default_factory=list)
    sounds: list[dict[str, str]] = field(default_factory=list)

    def rig(self, name: str) -> Rig | None:
        for entry in self.rigs:
            if entry.name == name:
                return entry
        return None

    def landmark(self, name: str) -> Landmark | None:
        for entry in self.landmarks:
            if entry.name == name:
                return entry
        return None

    @property
    def names(self) -> set[str]:
        """Everything a scene may refer to by name."""
        return {r.name for r in self.rigs} | {p.name for p in self.landmarks}

    def line(self) -> str:
        return (
            f"{self.name or 'place'}: {len(self.rigs)} rigs, "
            f"{len(self.landmarks)} reperes, {len(self.sounds)} sons"
        )


def parse_place(text: str) -> Place:
    """Read a survey, with or without the console output around it.

    Studio prints timestamps and whatever else is running, and people paste the
    lot. Cutting at the markers is what makes that harmless.
    """
    if BEGIN in text and END in text:
        text = text.split(BEGIN, 1)[1].split(END, 1)[0]
    # Studio's Output window prefixes every copied line with a timestamp, so
    # what lands between the markers is `15:02:12.002  {"place": ...}` rather
    # than the object. Cutting to the outermost braces takes that off, and also
    # survives a paste with no markers at all.
    opened, closed = text.find("{"), text.rfind("}")
    if opened != -1 and closed > opened:
        text = text[opened : closed + 1]
    text = text.strip()
    if not text:
        raise PlaceError(
            "the survey is empty. Run the script in the Command Bar and copy "
            "everything the Output window prints, markers included."
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlaceError(
            f"this is not the survey's JSON ({exc}). Copy from {BEGIN} to {END}, "
            f"or save the Output window's text as-is — both work."
        ) from None
    if not isinstance(data, dict):
        raise PlaceError(f"expected a JSON object, got {type(data).__name__}")

    return Place(
        name=str(data.get("place", "")),
        place_id=int(data.get("placeId", 0) or 0),
        rigs=[_rig(entry) for entry in data.get("rigs", [])],
        landmarks=[_landmark(entry) for entry in data.get("landmarks", [])],
        sounds=[
            {str(k): str(v) for k, v in entry.items()} for entry in data.get("sounds", [])
        ],
    )


def read_place(path: Path) -> Place:
    return parse_place(Path(path).read_text(encoding="utf-8"))


def _vec(value: Any, where: str) -> Vec3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise PlaceError(f"{where}: expected three numbers, got {value!r}")
    return (float(value[0]), float(value[1]), float(value[2]))


def _rig(entry: Any) -> Rig:
    if not isinstance(entry, dict) or "name" not in entry:
        raise PlaceError(f"a rig in the survey has no name: {entry!r}")
    return Rig(
        name=str(entry["name"]),
        rig=str(entry.get("rig", "unknown")).upper(),
        position=_vec(entry.get("position", [0, 0, 0]), str(entry["name"])),
        yaw=float(entry.get("yaw", 0.0) or 0.0),
        is_player=bool(entry.get("isPlayer", False)),
    )


def _landmark(entry: Any) -> Landmark:
    if not isinstance(entry, dict) or "name" not in entry:
        raise PlaceError(f"a landmark in the survey has no name: {entry!r}")
    return Landmark(
        name=str(entry["name"]),
        class_name=str(entry.get("class", "")),
        position=_vec(entry.get("position", [0, 0, 0]), str(entry["name"])),
        size=_vec(entry.get("size", [1, 1, 1]), str(entry["name"])),
    )


def stage_in(scene, place: Place) -> list[str]:
    """Move the scene onto the place's real rigs, and say what does not line up.

    An actor whose name matches a rig takes that rig's position and facing: the
    scene was written against a blank stage, and this is what puts it on the
    real one. An actor with no rig keeps its written position, because inventing
    one would be worse than an honest warning.

    Returns notes to print. It does not raise: a scene half-matched to a place
    is still worth building, and the notes are what say which half.
    """
    notes: list[str] = []

    for actor in scene.actors:
        found = place.rig(actor.name)
        if found is None:
            notes.append(
                f"{actor.name}: aucun rig de ce nom dans la place — la position "
                f"ecrite dans la scene est gardee"
            )
            continue
        actor.position = found.position
        # Facing another actor is a relationship and survives being moved, so
        # it is left alone; a written yaw is replaced by the rig's real one.
        if not isinstance(actor.facing, str):
            actor.facing = found.yaw
        if found.rig in ("R6", "R15") and found.rig != actor.rig.upper():
            notes.append(
                f"{actor.name}: la scene dit {actor.rig.upper()}, le rig dans la "
                f"place est {found.rig} — c'est {found.rig} qui gagne"
            )
            actor.rig = found.rig
        notes.append(
            f"{actor.name}: place sur le rig reel a "
            f"({found.position[0]:g}, {found.position[1]:g}, {found.position[2]:g})"
        )

    known = place.names | {actor.name for actor in scene.actors}
    for shot in scene.shots:
        if shot.look_at and shot.look_at not in known:
            notes.append(
                f"plan {shot.id}: vise {shot.look_at!r}, qui n'existe ni dans la "
                f"place ni dans le casting — le cadrage sera faux"
            )
    return notes
