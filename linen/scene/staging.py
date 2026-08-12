"""Work out what the set has to be, from what the scene does.

The question this answers: *a cinematic is written, so where do I put the wall?*

You do not guess, and you do not place it and then tune the throw until it
looks right. The scene already contains the answer. A pistol leaves a hand at a
known instant with a known impulse; the impact effect fires at another known
instant; Roblox's gravity is 196.2 studs per second squared. Integrate between
the two and the wall's position is not a preference, it is a solution.

The same holds for the rest of the set. Actors and their reach give the floor
its extent. Camera positions give the volume that must stay clear. Every
``source``, ``effect`` and ``at_part`` the scene names is something that has to
exist before it will play.

So this produces a build sheet — and a blockout of grey placeholders, correctly
named and correctly placed, to drop into Studio and replace with real art.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..rigs import get_rig
from ..rigs.kinematics import forward_kinematics
from .build import BuiltScene
from .events import Event

#: Roblox's default Workspace.Gravity, in studs per second squared — about
#: twice Earth's. A trajectory computed with 9.81 lands nowhere near.
GRAVITY = 196.2

#: Roblox part density, used to turn a placeholder's size into a mass.
DEFAULT_DENSITY = 0.7

#: Studs of clearance around the acting area, so nobody's swing clips scenery.
ACTING_MARGIN = 4.0


@dataclass
class Placement:
    """Something the set needs, and where."""

    name: str
    kind: str
    position: tuple[float, float, float]
    size: tuple[float, float, float] = (4.0, 4.0, 1.0)
    #: Why the scene needs it, in the build sheet's own words.
    reason: str = ""
    #: True when the position is solved rather than assumed.
    derived: bool = True


@dataclass
class SetPlan:
    scene_name: str
    placements: list[Placement] = field(default_factory=list)
    #: Named things the scene references but cannot place for you.
    required_assets: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def sheet(self) -> str:
        """The build sheet, as text meant to be read next to Studio."""
        lines = [f"Plateau — {self.scene_name}", ""]
        if self.placements:
            lines.append(f"{'objet':<16}{'type':<10}{'position (studs)':<26}pourquoi")
            for p in sorted(self.placements, key=lambda x: x.kind):
                position = f"({p.position[0]:.1f}, {p.position[1]:.1f}, {p.position[2]:.1f})"
                mark = "" if p.derived else "  (approx.)"
                lines.append(f"{p.name:<16}{p.kind:<10}{position:<26}{p.reason}{mark}")
        if self.required_assets:
            lines.append("")
            lines.append("À fournir toi-même (la scène les nomme, elle ne peut pas les créer) :")
            for name, why in self.required_assets:
                lines.append(f"  {name:<38} {why}")
        if self.warnings:
            lines.append("")
            lines.append("Avertissements :")
            for warning in self.warnings:
                lines.append(f"  {warning}")
        return "\n".join(lines)


def plan_set(built: BuiltScene) -> SetPlan:
    """Derive the set from the scene, solving what can be solved."""
    scene = built.scene
    plan = SetPlan(scene_name=scene.name)
    starts = {entry.cue.id: entry.start for entry in built.schedule}

    _place_floor(built, plan)
    _place_impacts(built, plan, starts)
    _collect_assets(built, plan)
    _check_camera_clearance(built, plan)
    return plan


def _standing_height(actor) -> float:
    """How far an actor's root sits above the ground when standing.

    A Roblox character's position is its *root*, not its feet — the root sits
    at hip height. Place an actor at y=0 on a floor at y=0 and half the body is
    underground, which is invisible in the scene file and obvious the second it
    plays.
    """
    rig = get_rig(actor.rig)
    placed = forward_kinematics(rig, {})
    foot = next((n for n in ("LeftFoot", "Left Leg") if n in placed), None)
    if foot is None:
        return 0.0
    return float(-(placed[foot][0][1] - rig.part(foot).size[1] / 2.0))


def _place_floor(built: BuiltScene, plan: SetPlan) -> None:
    """The acting area: everyone's position, plus room to move."""
    scene = built.scene

    for actor in scene.actors:
        standing = _standing_height(actor)
        if actor.position[1] < standing - 0.1:
            plan.warnings.append(
                f"{actor.name} est placé à y={actor.position[1]:.1f} mais sa racine "
                f"doit être à {standing:.2f} pour poser les pieds sur un sol à y=0 "
                f"— il est enterré de {standing - actor.position[1]:.1f} studs"
            )
    points = [np.asarray(actor.position, dtype=float) for actor in scene.actors]
    if not points:
        return
    stacked = np.stack(points)
    low, high = stacked.min(axis=0), stacked.max(axis=0)
    centre = (low + high) / 2.0
    span = (high - low) + 2 * ACTING_MARGIN
    # The floor goes under the actors' feet, not under their roots.
    ground = float(low[1] - max((_standing_height(a) for a in scene.actors), default=0.0))

    plan.placements.append(
        Placement(
            name="Floor",
            kind="sol",
            position=(float(centre[0]), ground - 0.5, float(centre[2])),
            size=(float(max(span[0], 12.0)), 1.0, float(max(span[2], 12.0))),
            reason=f"{len(scene.actors)} acteurs + {ACTING_MARGIN:g} studs de marge",
        )
    )


def _place_impacts(built: BuiltScene, plan: SetPlan, starts: dict[str, float]) -> None:
    """Solve where a thrown prop actually arrives, and put the target there.

    Flight is a plain parabola: the prop leaves the hand at the throw event and
    the impact effect names the instant it lands. Two known times and a known
    gravity leave one unknown, which is the position — so the wall goes where
    the maths says, not where it looked about right.
    """
    scene = built.scene
    throws = [e for e in scene.events if e.kind == "prop" and e.action == "throw"]
    impacts = [e for e in scene.events if e.kind == "vfx" and e.at_part]

    for throw in throws:
        launch = starts[throw.cue] + throw.offset
        prop = next((p for p in scene.props if p.name == throw.prop), None)
        if prop is None or throw.impulse is None:
            continue

        holder = throw.actor or prop.held_by
        origin = _hand_position(scene, holder, prop.attach_to)
        if origin is None:
            plan.warnings.append(
                f"{throw.prop} : impossible de situer la main de {holder!r}, "
                f"trajectoire non calculée"
            )
            continue

        mass = _mass_of(prop)
        velocity = np.asarray(throw.impulse, dtype=float) / mass

        # The impact that follows this throw most closely is the one it causes.
        landing = min(
            (e for e in impacts if starts[e.cue] + e.offset > launch),
            key=lambda e: starts[e.cue] + e.offset,
            default=None,
        )
        if landing is None:
            plan.warnings.append(
                f"{throw.prop} est lancé mais aucun événement vfx ne dit où il "
                f"atterrit — ajoute-en un pour que le mur soit calculable"
            )
            continue

        flight = starts[landing.cue] + landing.offset - launch
        position = _ballistic(origin, velocity, flight)

        plan.placements.append(
            Placement(
                name=landing.at_part or "Target",
                kind="cible",
                position=tuple(float(v) for v in position),
                size=(8.0, 8.0, 1.0),
                reason=(
                    f"{throw.prop} lancé à {launch:.2f}s, impact à "
                    f"{starts[landing.cue] + landing.offset:.2f}s "
                    f"({flight:.2f}s de vol)"
                ),
            )
        )
        if position[1] < 0:
            plan.warnings.append(
                f"{throw.prop} passe sous le sol avant l'impact "
                f"(y={position[1]:.1f}) — augmente l'impulsion verticale ou "
                f"avance l'événement d'impact"
            )


def _ballistic(origin: np.ndarray, velocity: np.ndarray, seconds: float) -> np.ndarray:
    """Where a free body is after ``seconds``, under Roblox gravity."""
    fall = np.array([0.0, 0.5 * GRAVITY * seconds * seconds, 0.0])
    return origin + velocity * seconds - fall


def _hand_position(scene, actor_name: str | None, part_name: str) -> np.ndarray | None:
    """Where an actor's hand is, in world studs, from the rig's own geometry."""
    if actor_name is None:
        return None
    actor = next((a for a in scene.actors if a.name == actor_name), None)
    if actor is None:
        return None
    rig = get_rig(actor.rig)
    if part_name not in {p.name for p in rig.parts}:
        return None
    local, _ = forward_kinematics(rig, {})[part_name]
    return np.asarray(actor.position, dtype=float) + local


def _mass_of(prop) -> float:
    """Roblox mass is volume times density, and density defaults to 0.7."""
    volume = 1.0 * 0.3 * 0.5  # a pistol-sized placeholder
    return max(volume * DEFAULT_DENSITY, 1e-3)


def _collect_assets(built: BuiltScene, plan: SetPlan) -> None:
    """Everything the scene names but cannot bring into existence."""
    scene = built.scene
    for prop in scene.props:
        plan.required_assets.append((prop.source, f"modèle de l'accessoire {prop.name}"))
    effects = {e.effect for e in scene.events if e.kind == "vfx" and e.effect}
    for effect in sorted(effects):
        plan.required_assets.append((effect, "ParticleEmitter ou effet nommé"))
    sounds = {e.asset for e in scene.events if e.kind == "sound" and e.asset}
    for asset in sorted(sounds):
        if asset.endswith("://0") or asset == "0":
            plan.warnings.append(
                "un événement sonore pointe encore sur rbxassetid://0 — "
                "remplace-le par un vrai identifiant"
            )
        else:
            plan.required_assets.append((asset, "audio publié"))


def _check_camera_clearance(built: BuiltScene, plan: SetPlan) -> None:
    """A shot aimed at something the scene never places is a black frame."""
    scene = built.scene
    known = {a.name for a in scene.actors} | {p.name for p in plan.placements}
    for shot in scene.shots:
        if shot.look_at not in known:
            plan.warnings.append(
                f"le plan {shot.id!r} vise {shot.look_at!r}, que la scène ne "
                f"place pas — construis-le, ou vise un acteur"
            )
        if shot.position[1] < 0.5:
            plan.warnings.append(
                f"le plan {shot.id!r} est à {shot.position[1]:.1f} studs de haut, "
                f"probablement sous le sol"
            )


def blockout(plan: SetPlan) -> str:
    """A Roblox model of grey placeholders, as .rbxmx.

    Correctly named and correctly placed, so the scene plays the moment it is
    dropped in — then each block gets replaced by real art at leisure.
    """
    from xml.etree import ElementTree as ET

    from ..export.rbxmx import _ROBLOX_ATTRS, _Referents, _bool, _string

    referents = _Referents()
    root = ET.Element("roblox", _ROBLOX_ATTRS)
    model = ET.SubElement(root, "Item", {"class": "Model", "referent": referents.take()})
    _string(ET.SubElement(model, "Properties"), "Name", f"{plan.scene_name}_Blockout")

    for placement in plan.placements:
        part = ET.SubElement(model, "Item", {"class": "Part", "referent": referents.take()})
        properties = ET.SubElement(part, "Properties")
        _string(properties, "Name", placement.name)
        _bool(properties, "Anchored", True)
        _vector3(properties, "size", placement.size)
        _cframe_at(properties, placement.position)
        _color(properties, (0.45, 0.45, 0.48))

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode")


def _vector3(parent, name: str, value: tuple[float, float, float]) -> None:
    from xml.etree import ElementTree as ET

    element = ET.SubElement(parent, "Vector3", {"name": name})
    for tag, component in zip(("X", "Y", "Z"), value):
        ET.SubElement(element, tag).text = f"{component:g}"


def _cframe_at(parent, position: tuple[float, float, float]) -> None:
    from xml.etree import ElementTree as ET

    element = ET.SubElement(parent, "CoordinateFrame", {"name": "CFrame"})
    tags = ("X", "Y", "Z", "R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")
    values = (*position, 1, 0, 0, 0, 1, 0, 0, 0, 1)
    for tag, value in zip(tags, values):
        ET.SubElement(element, tag).text = f"{value:g}"


def _color(parent, rgb: tuple[float, float, float]) -> None:
    from xml.etree import ElementTree as ET

    element = ET.SubElement(parent, "Color3uint8", {"name": "Color3uint8"})
    packed = (
        (255 << 24)
        | (int(rgb[0] * 255) << 16)
        | (int(rgb[1] * 255) << 8)
        | int(rgb[2] * 255)
    )
    element.text = str(packed)
