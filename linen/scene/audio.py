"""Spot the cinematic: work out what it needs to be heard, and when.

In film and game post-production this is a *spotting session*: the director and
the supervising sound editor watch the cut and mark every place the soundtrack
has to do something, producing a **spotting sheet** — cues labelled DX, FX, BG,
FOL, MUS. Nobody counts frames by hand; the picture tells you where the cues go.

That is exactly the problem here, and the picture is already in the file. The
clips carry every part's rotation on every frame, so forward kinematics gives
the world position of both fists on every frame of the take. A fist that
accelerates, then stops dead inside another actor's chest, *is* a punch landing
— the frame it happens on is a measurement, not a guess. A sole that comes down
and goes still is a footstep. A prop that leaves a hand under an impulse has a
solved flight time already (see :mod:`staging`), so its clatter is known too.

So this derives the cue list, and asks the one thing it genuinely cannot know:
which audio file to play. That comes back as a small mapping file with a named
slot per sound the scene needs — ``punch_impact``, ``footstep``,
``tension_drone`` — each with a description of the sound wanted and the search
terms that find one in the Creator Store. Fill in the ids once and every future
build of the scene keeps them, however much the timing moves.

Two decisions worth stating.

**Whiffs are cues too.** A swing that connects and a swing that misses are
different sounds — impact versus whoosh — and a scene that never solves contact
would otherwise be silent. Both are detected: the strike frame comes from the
hand's own deceleration, and whether a body was in reach at that frame decides
which slot it lands in.

**Intensity is continuous.** Every hit carries how hard it was, from the closing
speed. Middleware calls this an RTPC; Rockstar's "Gunfight Conductor" drives the
RDR2 score off one. Here it varies each hit's volume and pitch — playing one
sample at one level is what makes game combat sound like a stapler — and it
accumulates into a tension curve that the ambience beds ride.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..rigs import get_rig
from ..rigs.kinematics import place_rotations
from .build import BuiltScene

# -- what counts as a hit -----------------------------------------------------

#: Parts that can strike something, per rig family.
STRIKERS: dict[str, tuple[str, ...]] = {
    "hand": ("LeftHand", "RightHand", "Left Arm", "Right Arm"),
    "foot": ("LeftFoot", "RightFoot", "Left Leg", "Right Leg"),
}

#: Parts worth hitting: the mass of the body, not its limbs.
TARGETS: tuple[str, ...] = ("Head", "UpperTorso", "LowerTorso", "Torso")

#: A striker must exceed this, in studs per second, for the swing to read as a
#: strike at all.
#:
#: Measured across every action the planner can produce, on both rigs: a walk
#: swings the hand at 4-6, a run at 20, a sit at 22 — and a punch at 62 on R15,
#: 116 on R6. The gap either side of 28 is wide enough that no locomotion ever
#: reaches it and no strike ever falls short.
STRIKE_SPEED = 28.0

#: How long after the peak the impact is looked for, in seconds. Past this the
#: limb is recovering, not landing.
STRIKE_SETTLE = 0.20

#: How far in front of its own chest the limb must finish, as a fraction of the
#: actor's height.
#:
#: Speed alone is not enough: a wave, a jump and a celebration all fling a limb
#: past 50 studs a second without striking anything. What separates them is
#: *direction*. A strike ends out in front — punch and point finish 2.0 to 2.3
#: studs ahead of the chest, while a wave finishes at 0.9, a jump at 0.2, and a
#: flinch at -1.3, behind it. Measuring the reach rather than the arm's
#: extension is the correction that matters: an arm is the same length hanging
#: down as thrown forward, so distance from the chest barely moves.
STRIKE_REACH = 0.36

#: A one-frame spike is a blend between two cues, not a punch. A real swing is
#: still moving on the frames either side of its peak.
SUSTAIN = 0.5

#: Surface gap, in studs, under which a strike is touching its target.
CONTACT_GAP = 0.75

#: Studs above its own lowest point at which a sole counts as touching down.
#:
#: Contact is found the way gait analysis finds it: at the bottom of the sole's
#: vertical travel, where its downward velocity crosses zero. Waiting for the
#: foot to go *still* instead would find nothing here — these clips carry no
#: root translation, so the character walks on the spot and the planted foot
#: slides backwards under it at two or three studs a second, exactly like a
#: treadmill. Height bottoming out is true either way.
PLANT_HEIGHT = 0.12

#: The foot has to have been lifted this far since the last touchdown, or a
#: shuffle inside one stance phase counts as a second step.
STEP_CLEARANCE = 0.12

#: Below this drop speed a landing is a step, above it a landing.
LAND_SPEED = 6.0

#: The head falling at least this far, this fast, is a body going down.
FALL_DROP = 1.4
FALL_SPEED = 7.0

#: Hits closer together than this are one event heard twice.
MERGE_SECONDS = 0.10


@dataclass
class Hit:
    """One moment a sound has to happen."""

    slot: str
    time: float
    #: Whose animation carries it, when one does. A hit bound to an actor
    #: becomes a KeyframeMarker in that actor's clip and is therefore
    #: frame-exact; one without rides the director's clock.
    actor: str | None = None
    #: Where to play it from, so it is positional rather than flat.
    part: str = ""
    #: 0..1. Drives volume and pitch, and feeds the tension curve.
    intensity: float = 1.0
    #: Who this was done *to*, when it was done to someone. The contact test
    #: already knows; keeping it turns "who is losing this fight" into
    #: arithmetic instead of an assumption that only holds for two actors.
    target: str | None = None
    #: Why this was spotted, for the sheet.
    why: str = ""


@dataclass
class SoundSlot:
    """A named sound the cinematic needs — and the id to be pasted in.

    This is the unit the mapping file is written in. It exists so that the
    question put to whoever is building the scene is "what does a punch sound
    like here", once, rather than "what plays at frame 61".
    """

    name: str
    #: Spotting-sheet category: DX dialogue, FX effects, FOL foley,
    #: BG backgrounds, MUS music. The same codes a sound editor uses.
    category: str
    #: What sound belongs here, in the sheet's own words.
    description: str
    #: Keywords that find one in the Creator Store's free audio.
    search: str = ""
    #: Something Roblox already ships, where it does. These need no upload, no
    #: moderation and no account standing — the scene makes noise immediately.
    default: str = ""
    #: Held for a span rather than struck at an instant.
    loop: bool = False
    base_volume: float = 1.0
    hits: list[Hit] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.hits)


#: The catalogue. Every slot the spotter can produce, with what to look for.
#: Defaults point at ``rbxasset://`` paths, which are files inside the Roblox
#: client rather than uploaded assets — always present, never moderated.
CATALOGUE: tuple[SoundSlot, ...] = (
    SoundSlot(
        "punch_impact", "FX",
        "Impact d'un poing sur un corps — sourd, court, avec du grave",
        "punch impact flesh hit body", base_volume=1.0,
    ),
    SoundSlot(
        "kick_impact", "FX",
        "Impact d'un pied — plus lourd et plus long qu'un poing",
        "kick impact body thud heavy", base_volume=1.0,
    ),
    SoundSlot(
        "swing_whoosh", "FX",
        "Coup qui fend l'air sans toucher — souffle bref et tendu",
        "whoosh swing air fast movement", base_volume=0.7,
    ),
    SoundSlot(
        "footstep", "FOL",
        "Un pas. Prends-en plusieurs variantes si tu peux, sinon la hauteur "
        "varie toute seule à chaque pas",
        "footstep concrete walk",
        default="rbxasset://sounds/action_footsteps_plastic.mp3",
        base_volume=0.5,
    ),
    SoundSlot(
        "jump_land", "FOL",
        "Réception au sol après un saut ou une chute — poids qui arrive",
        "landing thud boots impact ground",
        default="rbxasset://sounds/action_jump_land.mp3",
        base_volume=0.8,
    ),
    SoundSlot(
        "body_fall", "FX",
        "Un corps qui s'effondre au sol — masse molle, pas un objet",
        "body fall ground heavy collapse", base_volume=1.0,
    ),
    SoundSlot(
        "effort", "DX",
        "Souffle ou grognement d'effort du personnage qui frappe ou encaisse",
        "male grunt effort pain exhale",
        default="rbxasset://sounds/uuhhh.mp3",
        base_volume=0.6,
    ),
    SoundSlot(
        "prop_throw", "FX",
        "Objet qui quitte la main et fend l'air",
        "throw whoosh object metal", base_volume=0.8,
    ),
    SoundSlot(
        "prop_impact", "FX",
        "L'objet arrive sur le décor — impact sec puis rebond/ferraille",
        "metal impact concrete clatter debris", base_volume=1.0,
    ),
    SoundSlot(
        "prop_drop", "FX",
        "Objet lâché au sol, plus discret que jeté",
        "object drop floor clatter light", base_volume=0.7,
    ),
    SoundSlot(
        "dialogue", "DX",
        "Les répliques. C'est ici que vont tes rendus ElevenLabs — une piste "
        "par réplique, listées ci-dessous dans l'ordre",
        "", base_volume=1.0,
    ),
    SoundSlot(
        "ambient_bed", "BG",
        "Le fond permanent du lieu : air, salle, extérieur. Sans lui la scène "
        "sonne comme une cabine",
        "room tone ambience loop background",
        loop=True, base_volume=0.35,
    ),
    SoundSlot(
        "tension_drone", "MUS",
        "Nappe grave et tenue, qui monte quand ça chauffe. C'est elle qui fait "
        "que le spectateur sait que ça va mal se passer",
        "tension drone low sustained dark loop",
        loop=True, base_volume=0.5,
    ),
    SoundSlot(
        "riser", "MUS",
        "Montée juste avant le point culminant — 1 à 2 secondes qui gonflent",
        "riser build swell tension rise", base_volume=0.7,
    ),
    SoundSlot(
        "sting", "MUS",
        "Frappe musicale sur le pic : le coup qui compte, pas les autres",
        "impact sting orchestral hit braam", base_volume=0.9,
    ),
    SoundSlot(
        "heartbeat", "MUS",
        "Battement de cœur lent sous la scène, pour le personnage qui prend "
        "cher. C'est ce qui fait sentir qu'on est mal en point",
        "heartbeat slow pulse deep loop",
        loop=True, base_volume=0.6,
    ),
)


@dataclass
class Ambience:
    """A bed held over a span, rather than a sound struck at an instant."""

    slot: str
    start: float
    stop: float
    #: Volume follows the tension curve between these two, so a drone swells
    #: into a fight instead of being switched on.
    low: float
    high: float
    why: str = ""


@dataclass
class SpottingSheet:
    scene_name: str
    slots: list[SoundSlot] = field(default_factory=list)
    ambience: list[Ambience] = field(default_factory=list)
    #: (time, 0..1) sampled across the take.
    tension: list[tuple[float, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def used(self) -> list[SoundSlot]:
        return [s for s in self.slots if s.hits or any(a.slot == s.name for a in self.ambience)]

    def slot(self, name: str) -> SoundSlot | None:
        return next((s for s in self.slots if s.name == name), None)

    @property
    def peak_tension(self) -> float:
        return max((value for _, value in self.tension), default=0.0)

    # -- output -----------------------------------------------------------
    def sheet(self) -> str:
        """The spotting sheet, meant to be read next to the mapping file."""
        lines = [f"Conduite son — {self.scene_name}", ""]
        used = self.used()
        if not used:
            lines.append("  Rien à sonoriser : la scène ne contient ni impact, "
                         "ni pas, ni objet, ni réplique.")
            return "\n".join(lines)

        lines.append(f"{'slot':<16}{'cat':<5}{'n':>3}  {'quand':<28}il te faut")
        for slot in used:
            when = _when_summary(slot, self.ambience)
            count = str(slot.count) if slot.count else "-"
            lines.append(
                f"{slot.name:<16}{slot.category:<5}{count:>3}  {when:<28}{slot.description}"
            )

        lines.append("")
        lines.append("Tension (0-1, échantillonnée) :")
        lines.append("  " + _sparkline(self.tension))
        lines.append(f"  pic à {self.peak_tension:.2f}")

        missing = [s for s in used if not s.default]
        if missing:
            lines.append("")
            lines.append("À trouver dans le Creator Store (Toolbox > Creator Store > Audio) :")
            for slot in missing:
                if slot.search:
                    lines.append(f"  {slot.name:<16} cherche : {slot.search}")
                else:
                    lines.append(f"  {slot.name:<16} (à toi de le produire)")

        shipped = [s for s in used if s.default]
        if shipped:
            lines.append("")
            lines.append("Déjà couverts par des sons livrés avec Roblox (rien à uploader) :")
            for slot in shipped:
                lines.append(f"  {slot.name:<16} {slot.default}")

        if self.warnings:
            lines.append("")
            lines.append("Avertissements :")
            for warning in self.warnings:
                lines.append(f"  {warning}")
        return "\n".join(lines)

    def mapping(self, existing: dict[str, str] | None = None) -> dict:
        """The slot-to-asset file, preserving anything already filled in."""
        existing = existing or {}
        sounds: dict[str, str] = {}
        notes: dict[str, str] = {}
        for slot in self.used():
            sounds[slot.name] = existing.get(slot.name) or slot.default or ""
            notes[slot.name] = slot.description
        return {
            "scene": self.scene_name,
            "//": "Colle un rbxassetid:// en face de chaque slot. Les slots "
                  "remplis sont conservés quand la scène est régénérée.",
            "sounds": sounds,
            "notes": notes,
        }


def _when_summary(slot: SoundSlot, ambience: list[Ambience]) -> str:
    spans = [a for a in ambience if a.slot == slot.name]
    if spans:
        return f"{spans[0].start:.2f}-{spans[-1].stop:.2f}s (nappe)"
    if not slot.hits:
        return "-"
    times = [f"{hit.time:.2f}" for hit in slot.hits[:3]]
    more = "..." if slot.count > 3 else ""
    return f"{', '.join(times)}{more}s"


def _sparkline(tension: list[tuple[float, float]], width: int = 48) -> str:
    if not tension:
        return ""
    blocks = " ▁▂▃▄▅▆▇█"
    values = [value for _, value in tension]
    step = max(len(values) / width, 1.0)
    out = []
    for i in range(min(width, len(values))):
        window = values[int(i * step) : max(int((i + 1) * step), int(i * step) + 1)]
        level = max(window) if window else 0.0
        out.append(blocks[min(int(level * (len(blocks) - 1)), len(blocks) - 1)])
    return "".join(out)


# -- the spotter --------------------------------------------------------------


def spot_scene(built: BuiltScene, *, mapping: dict[str, str] | None = None) -> SpottingSheet:
    """Watch the take and mark every place a sound has to happen."""
    scene = built.scene
    sheet = SpottingSheet(scene_name=scene.name)
    sheet.slots = [
        SoundSlot(
            s.name, s.category, s.description, s.search, s.default, s.loop, s.base_volume
        )
        for s in CATALOGUE
    ]

    tracked = _track_actors(built)
    strikes = _spot_strikes(built, tracked, sheet)
    ground = _spot_feet(built, tracked)
    hits = _ground_wins(strikes, ground) + ground
    hits += _spot_falls(built, tracked)
    hits += _spot_events(built, sheet)

    for hit in _merge(hits):
        slot = sheet.slot(hit.slot)
        if slot is not None:
            slot.hits.append(hit)
    for slot in sheet.slots:
        slot.hits.sort(key=lambda h: h.time)

    sheet.tension = _tension_curve(built, sheet)
    _choose_ambience(built, sheet)

    if mapping is not None:
        silent = [
            slot.name
            for slot in sheet.used()
            if not mapping.get(slot.name) and not slot.default
        ]
        if silent:
            sheet.warnings.append(
                f"{len(silent)} slot(s) sans identifiant audio, muets pour "
                f"l'instant : {', '.join(silent)}"
            )
    return sheet


@dataclass
class _Tracked:
    """One actor's body, placed in the world on every frame."""

    name: str
    #: part -> (frames, 3) world position of the part's centre, in studs.
    positions: dict[str, np.ndarray]
    #: part -> (frames, 3) world position of the part's far end.
    #:
    #: Limbs hang along their own -Y, so this is the fist at the end of an arm
    #: and the sole under a foot. It matters most on R6, where one part is the
    #: whole arm and its centre sits a full stud short of the knuckles — using
    #: centres there, a punch reads as a miss and a step never touches down.
    tips: dict[str, np.ndarray]
    radii: dict[str, float]
    fps: float
    #: Unit vector the actor faces, in world space.
    forward: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, -1.0]))
    #: Standing height in studs, so thresholds scale with the rig.
    height: float = 5.0

    @property
    def frames(self) -> int:
        return len(next(iter(self.positions.values())))

    @property
    def core(self) -> str:
        return "UpperTorso" if "UpperTorso" in self.positions else "Torso"

    def striker(self, part: str) -> np.ndarray:
        return self.tips[part]

    def reach(self, part: str) -> np.ndarray:
        """How far in front of its own chest a limb is, per frame."""
        if self.core not in self.positions:
            return np.zeros(self.frames)
        return (self.striker(part) - self.positions[self.core]) @ self.forward


def _track_actors(built: BuiltScene) -> dict[str, _Tracked]:
    """Forward kinematics across the whole take, in world space.

    The clips are rotation-only, so this is the body's shape over time with the
    actor's staging applied — which is all a contact test needs.
    """
    scene = built.scene
    tracked: dict[str, _Tracked] = {}

    for actor in scene.actors:
        clip = built.clips.get(actor.name)
        if clip is None:
            continue
        rig = get_rig(actor.rig)
        origin, yaw = _actor_transform(scene, actor)

        names = [part.name for part in rig.parts]
        half = {p.name: float(p.size[1]) / 2.0 for p in rig.parts}
        positions = {name: np.zeros((clip.frame_count, 3)) for name in names}
        tips = {name: np.zeros((clip.frame_count, 3)) for name in names}

        for frame in range(clip.frame_count):
            placed = place_rotations(
                rig, {part: track[frame] for part, track in clip.rotations.items()}
            )
            for name in names:
                centre, rotation = placed[name]
                positions[name][frame] = origin + yaw @ centre
                tips[name][frame] = origin + yaw @ (
                    centre + rotation @ np.array([0.0, -half[name], 0.0])
                )

        rest = place_rotations(rig, {})
        top = max(float(pos[1]) + rig.part(name).size[1] / 2.0 for name, (pos, _) in rest.items())
        floor = min(float(pos[1]) - rig.part(name).size[1] / 2.0 for name, (pos, _) in rest.items())

        tracked[actor.name] = _Tracked(
            name=actor.name,
            positions=positions,
            tips=tips,
            radii={p.name: float(np.mean(p.size)) / 2.0 for p in rig.parts},
            fps=clip.fps,
            forward=yaw @ np.array([0.0, 0.0, -1.0]),
            height=max(top - floor, 1.0),
        )
    return tracked


def _actor_transform(scene, actor) -> tuple[np.ndarray, np.ndarray]:
    """Where an actor stands and which way they face, as the player stages it.

    A rig's forward is -Z, so the yaw is the one that turns -Z onto the facing
    direction. Getting this wrong mirrors every contact test front-to-back.
    """
    origin = np.asarray(actor.position, dtype=float)
    direction: np.ndarray | None = None

    if isinstance(actor.facing, str):
        other = next((a for a in scene.actors if a.name == actor.facing), None)
        if other is not None:
            delta = np.asarray(other.position, dtype=float) - origin
            delta[1] = 0.0
            if float(np.linalg.norm(delta)) > 1e-6:
                direction = delta / float(np.linalg.norm(delta))
    elif isinstance(actor.facing, (int, float)):
        angle = np.radians(float(actor.facing))
        direction = np.array([np.sin(angle), 0.0, -np.cos(angle)])

    if direction is None:
        return origin, np.eye(3)

    theta = float(np.arctan2(-direction[0], -direction[2]))
    cos, sin = np.cos(theta), np.sin(theta)
    yaw = np.array([[cos, 0.0, sin], [0.0, 1.0, 0.0], [-sin, 0.0, cos]])
    return origin, yaw


def _speed(positions: np.ndarray, fps: float) -> np.ndarray:
    """Per-frame speed in studs/s, same length as the input."""
    if len(positions) < 2:
        return np.zeros(len(positions))
    delta = np.linalg.norm(np.diff(positions, axis=0), axis=1) * fps
    return np.concatenate([delta[:1], delta])


def _spot_strikes(
    built: BuiltScene, tracked: dict[str, _Tracked], sheet: SpottingSheet
) -> list[Hit]:
    """Find every swing, and decide whether it connected.

    The strike frame is where the limb stops, not where it is fastest: a fist
    reaches peak speed mid-flight and gives that speed up over two or three
    frames on contact. That deceleration is the frame the sound belongs on.
    """
    hits: list[Hit] = []
    for name, body in tracked.items():
        others = [other for key, other in tracked.items() if key != name]
        for kind, candidates in STRIKERS.items():
            for part in candidates:
                if part not in body.positions:
                    continue
                path = body.striker(part)
                speed = _speed(path, body.fps)
                reach = body.reach(part) / body.height
                for frame in _strike_frames(speed, reach, body.fps):
                    time = frame / body.fps
                    gap, victim, hit_part = _closest_body(path[frame], frame, others)
                    peak = float(np.max(speed[max(frame - 6, 0) : frame + 1]))
                    # A thrust that just clears the bar is a shove; the hardest
                    # blows the planner produces run past 110 studs a second.
                    intensity = float(np.clip((peak - STRIKE_SPEED) / 60.0, 0.15, 1.0))

                    if gap is not None and gap <= CONTACT_GAP and victim is not None:
                        slot = "punch_impact" if kind == "hand" else "kick_impact"
                        struck: str | None = victim
                        why = (
                            f"{part} de {name} touche {victim}.{hit_part} "
                            f"à {peak:.0f} studs/s"
                        )
                    else:
                        slot = "swing_whoosh"
                        struck = None
                        nearest = "" if gap is None else f", personne à moins de {gap:.1f} studs"
                        why = f"{part} de {name} fend l'air à {peak:.0f} studs/s{nearest}"

                    hits.append(
                        Hit(slot=slot, time=time, actor=name, part=part,
                            intensity=intensity, target=struck, why=why)
                    )
                    # A hard blow is worth a breath from whoever threw it.
                    if slot != "swing_whoosh" and intensity > 0.5:
                        hits.append(
                            Hit(slot="effort", time=max(time - 0.08, 0.0), actor=name,
                                part="Head", intensity=intensity * 0.8,
                                why=f"effort de {name} sur son coup")
                        )
    if not hits:
        return hits

    connected = sum(1 for h in hits if h.slot in ("punch_impact", "kick_impact"))
    whiffs = sum(1 for h in hits if h.slot == "swing_whoosh")
    if whiffs and not connected:
        sheet.warnings.append(
            f"{whiffs} coup(s) détecté(s) mais aucun ne touche : les acteurs sont "
            f"trop loin l'un de l'autre. Rapproche-les dans 'position' et les "
            f"souffles deviendront des impacts"
        )
    return hits


def _strike_frames(speed: np.ndarray, reach: np.ndarray, fps: float) -> list[int]:
    """Frames where a limb was thrown out in front and then stopped.

    Three things have to hold at once, and dropping any one of them floods the
    sheet with false hits: the limb must be fast, it must finish *in front of*
    its owner, and its peak must last longer than a single frame.
    """
    frames: list[int] = []
    window = max(round(STRIKE_SETTLE * fps), 2)
    frame = 1
    while frame < len(speed) - 1:
        if speed[frame] < STRIKE_SPEED or not (
            speed[frame] >= speed[frame - 1] and speed[frame] >= speed[frame + 1]
        ):
            frame += 1
            continue

        peak = float(speed[frame])
        neighbours = speed[max(frame - 2, 0) : frame + 3]
        if float(np.mean(neighbours)) < peak * SUSTAIN:
            frame += 1
            continue

        # The impact is the hardest braking after the peak, not the moment the
        # limb finally comes to rest. Waiting for rest puts the sound on the
        # end of the follow-through, by which time the fist has been pulled
        # back and the whole reason for the sound has left the frame.
        tail = speed[frame : min(frame + window + 1, len(speed))]
        if len(tail) < 2:
            break
        landing = frame + int(np.argmin(np.diff(tail))) + 1

        # Reach is judged across the throw, not only on the impact frame: a
        # punch that overshoots and snaps back still finished out in front.
        if float(np.max(reach[frame : landing + 1])) >= STRIKE_REACH:
            frames.append(landing)
        frame = landing + window
    return frames


def _closest_body(
    point: np.ndarray, frame: int, others: list[_Tracked]
) -> tuple[float | None, str | None, str]:
    """Surface gap to the nearest strikeable mass on this frame, and whose.

    Compared on the same frame index throughout: every clip in a scene spans
    the whole take, so the indices line up by construction. Taking the nearest
    over the whole clip instead would call a punch a hit because the victim
    walked through that spot two seconds later.
    """
    best: float | None = None
    who: str | None = None
    where = ""
    for other in others:
        for target in TARGETS:
            if target not in other.positions:
                continue
            index = min(frame, other.frames - 1)
            gap = float(np.linalg.norm(other.positions[target][index] - point))
            gap -= other.radii.get(target, 0.5)
            if best is None or gap < best:
                best, who, where = gap, other.name, target
    return best, who, where


def _spot_feet(built: BuiltScene, tracked: dict[str, _Tracked]) -> list[Hit]:
    """Every time a sole comes down and stays down."""
    hits: list[Hit] = []
    for name, body in tracked.items():
        soles = [p for p in ("LeftFoot", "RightFoot", "Left Leg", "Right Leg")
                 if p in body.positions]
        if not soles:
            continue
        # The underside of the foot, not its centre: that is what the ground
        # meets, and on R6 the two are a whole stud apart.
        floor = min(float(body.tips[p][:, 1].min()) for p in soles)

        for part in soles:
            height = body.tips[part][:, 1] - floor
            drop = -np.gradient(height) * body.fps

            for frame in _touchdowns(height):
                landing = float(np.max(drop[max(frame - 3, 0) : frame + 1]))
                heavy = landing >= LAND_SPEED
                hits.append(
                    Hit(
                        slot="jump_land" if heavy else "footstep",
                        time=float(frame) / body.fps,
                        actor=name,
                        part=part,
                        intensity=float(np.clip(landing / 14.0, 0.25, 1.0)),
                        why=(
                            f"{part} de {name} se pose à {landing:.0f} studs/s"
                            if heavy
                            else f"pas de {name} ({part})"
                        ),
                    )
                )
    return hits


def _touchdowns(height: np.ndarray) -> list[int]:
    """Frames where a sole bottoms out near the ground, having been lifted.

    The clearance check between one touchdown and the next is what stops a
    stance-phase wobble from being heard as a second step.
    """
    frames: list[int] = []
    peak_since = float(height[0]) if len(height) else 0.0
    for frame in range(1, len(height) - 1):
        peak_since = max(peak_since, float(height[frame]))
        low = height[frame] <= height[frame - 1] and height[frame] < height[frame + 1]
        if not low or height[frame] > PLANT_HEIGHT:
            continue
        if peak_since - float(height[frame]) < STEP_CLEARANCE:
            continue
        frames.append(frame)
        peak_since = float(height[frame])
    return frames


def _spot_falls(built: BuiltScene, tracked: dict[str, _Tracked]) -> list[Hit]:
    """A body going down: the head drops far, fast, and stops.

    The clips carry no root translation, so a fall shows up as the head coming
    down through the hips and knees folding — which is exactly what it is.
    """
    hits: list[Hit] = []
    for name, body in tracked.items():
        if "Head" not in body.positions:
            continue
        height = body.positions["Head"][:, 1]
        drop = -np.gradient(height) * body.fps
        frame = 1
        while frame < len(drop) - 1:
            if drop[frame] < FALL_SPEED:
                frame += 1
                continue
            stop = next(
                (f for f in range(frame + 1, len(drop)) if drop[f] <= FALL_SPEED * 0.3),
                len(drop) - 1,
            )
            fallen = float(height[frame] - height[stop])
            if fallen >= FALL_DROP:
                hits.append(
                    Hit(
                        slot="body_fall",
                        time=float(stop) / body.fps,
                        actor=name,
                        part="LowerTorso" if "LowerTorso" in body.positions else "Torso",
                        intensity=float(np.clip(fallen / 3.0, 0.3, 1.0)),
                        why=f"{name} descend de {fallen:.1f} studs en chute",
                    )
                )
            frame = stop + 1
    return hits


def _spot_events(built: BuiltScene, sheet: SpottingSheet) -> list[Hit]:
    """Sounds the written scene already implies: props and dialogue.

    A throw's flight time is already solved by the set plan, so the clatter
    against the wall is placed by the same arithmetic rather than by ear.
    """
    scene = built.scene
    starts = {entry.cue.id: entry.start for entry in built.schedule}
    hits: list[Hit] = []

    for event in scene.events:
        when = starts[event.cue] + event.offset
        if event.kind == "prop" and event.action == "throw":
            hits.append(
                Hit(slot="prop_throw", time=when, actor=event.actor,
                    part="RightHand", intensity=0.8,
                    why=f"{event.prop} quitte la main")
            )
        elif event.kind == "prop" and event.action == "release":
            hits.append(
                Hit(slot="prop_drop", time=when, actor=event.actor,
                    part="RightHand", intensity=0.6,
                    why=f"{event.prop} est lâché")
            )
        elif event.kind == "vfx" and event.at_part:
            hits.append(
                Hit(slot="prop_impact", time=when, actor=None, part=event.at_part,
                    intensity=0.9, why=f"impact sur {event.at_part}")
            )
        elif event.kind == "line":
            slot = sheet.slot("dialogue")
            if slot is not None:
                slot.description = _dialogue_note(scene)
            hits.append(
                Hit(slot="dialogue", time=when, actor=event.actor, part="Head",
                    intensity=1.0, why=f"« {(event.text or '')[:40]} »")
            )
    return hits


def _dialogue_note(scene) -> str:
    """List the lines, so each ElevenLabs render has an obvious home."""
    lines = [e.text for e in scene.events if e.kind == "line" and e.text]
    listed = "; ".join(f"{i + 1}. {text}" for i, text in enumerate(lines))
    return f"Une piste par réplique, dans cet ordre — {listed}"


#: A limb that touched the ground this recently was carrying weight, not
#: throwing a blow.
GROUNDED_SECONDS = 0.20


def _ground_wins(strikes: list[Hit], ground: list[Hit]) -> list[Hit]:
    """Drop strikes by a limb that was busy landing.

    A tucked leg on a jump reaches kicking speed and finishes in front, which
    is a strike by every kinematic test — right up until you notice the same
    foot touched down three hundredths of a second earlier.
    """
    return [
        strike
        for strike in strikes
        if not any(
            contact.actor == strike.actor
            and contact.part == strike.part
            and abs(contact.time - strike.time) <= GROUNDED_SECONDS
            for contact in ground
        )
    ]


def _merge(hits: list[Hit]) -> list[Hit]:
    """One physical event heard once, even when two detectors saw it."""
    ordered = sorted(hits, key=lambda h: (h.slot, h.actor or "", h.time))
    kept: list[Hit] = []
    for hit in ordered:
        clash = next(
            (
                k
                for k in kept
                if k.slot == hit.slot
                and k.actor == hit.actor
                and abs(k.time - hit.time) < MERGE_SECONDS
            ),
            None,
        )
        if clash is None:
            kept.append(hit)
        elif hit.intensity > clash.intensity:
            clash.intensity = hit.intensity
            clash.why = hit.why
    return sorted(kept, key=lambda h: h.time)


# -- tension ------------------------------------------------------------------

#: How much each kind of hit raises the temperature, and how fast it cools.
WEIGHTS: dict[str, float] = {
    "punch_impact": 0.55,
    "kick_impact": 0.6,
    "body_fall": 0.5,
    "prop_impact": 0.45,
    "prop_throw": 0.2,
    "swing_whoosh": 0.18,
    "jump_land": 0.12,
    "dialogue": 0.05,
}

#: Seconds for a jolt to fall to a third of itself. Tension outlives the blow
#: that caused it — that is the whole point of scoring a fight.
COOLING = 2.6

#: The curve is sampled at this rate: fine enough to swell, coarse enough that
#: the generated table stays readable.
SAMPLE_RATE = 8.0


def _tension_curve(built: BuiltScene, sheet: SpottingSheet) -> list[tuple[float, float]]:
    """How wound-up the scene is, moment to moment.

    This is the one continuous value the whole soundtrack rides — middleware
    would call it an RTPC. It rises on impacts and decays between them, so a
    drone swells into an exchange and thins out afterwards without anybody
    drawing an envelope.
    """
    duration = built.duration
    if duration <= 0:
        return []
    samples = max(round(duration * SAMPLE_RATE) + 1, 2)
    times = np.linspace(0.0, duration, samples)
    curve = np.zeros(samples)

    for slot in sheet.slots:
        weight = WEIGHTS.get(slot.name)
        if weight is None:
            continue
        for hit in slot.hits:
            # Jolt on the frame, then an exponential tail. Impacts before the
            # hit do not exist, so the rise is a step and only the fall decays.
            delta = times - hit.time
            curve += np.where(delta >= 0, weight * hit.intensity * np.exp(-delta / COOLING), 0.0)

    # A cut is a small jolt of its own: editing raises tension even in silence.
    for when, event in built.director:
        if getattr(event, "kind", "") == "camera":
            delta = times - when
            curve += np.where(delta >= 0, 0.08 * np.exp(-delta / COOLING), 0.0)

    # Soft saturation rather than a clamp. Jolts have to accumulate — a flurry
    # is tenser than one blow — but a plain sum pegs at the ceiling after three
    # of them and the curve goes flat, which is the same as having no curve.
    # This keeps every extra hit worth something and never quite reaches 1.
    curve = 1.0 - np.exp(-curve)
    return [(float(t), float(round(v, 3))) for t, v in zip(times, curve)]


#: Above this, sustained, the scene has earned a drone.
DRONE_TENSION = 0.30
#: Above this, a moment is a peak worth a sting and a run-up.
PEAK_TENSION = 0.62
#: Seconds of run-up before a peak.
RISER_LEAD = 1.4

#: Punishment taken, summed over intensities, before an actor is in enough
#: trouble to be worth a heartbeat. One solid landed blow clears it.
HEARTBEAT_TENSION = 0.4


def _choose_ambience(built: BuiltScene, sheet: SpottingSheet) -> None:
    """Pick the beds the scene has argued for, and say why it argued."""
    duration = built.duration
    if duration <= 0:
        return
    curve = sheet.tension

    sheet.ambience.append(
        Ambience("ambient_bed", 0.0, duration, 0.8, 1.0,
                 "toute la scène a besoin d'un fond, sinon elle sonne en cabine")
    )

    for start, stop in _spans_above(curve, DRONE_TENSION, min_length=0.8):
        # The drone starts before the trouble does: arriving with the first
        # punch announces it, arriving early makes the punch inevitable.
        sheet.ambience.append(
            Ambience("tension_drone", max(start - 1.0, 0.0), min(stop + 1.2, duration),
                     0.25, 1.0,
                     f"tension au-dessus de {DRONE_TENSION:g} de {start:.2f}s à {stop:.2f}s")
        )

    for time, value in _peaks(curve, PEAK_TENSION):
        slot = sheet.slot("riser")
        if slot is not None and time >= RISER_LEAD * 0.5:
            slot.hits.append(
                Hit("riser", max(time - RISER_LEAD, 0.0), None, "", value,
                    f"montée vers le pic de {time:.2f}s")
            )
        sting = sheet.slot("sting")
        if sting is not None:
            sting.hits.append(
                Hit("sting", time, None, "", value, f"pic de tension à {value:.2f}")
            )

    # Whoever takes the beating gets the heartbeat. The request was "qu'on
    # sente que le personnage est mal en point"; this is that, made countable.
    # Every landed blow already names its victim, so this is a tally, not a
    # guess — which is what makes it hold with three actors in the room.
    taken: dict[str, float] = {}
    thrown: dict[str, float] = {}
    for slot in sheet.slots:
        if slot.name in ("punch_impact", "kick_impact"):
            for hit in slot.hits:
                if hit.actor:
                    thrown[hit.actor] = thrown.get(hit.actor, 0.0) + hit.intensity
                if hit.target:
                    taken[hit.target] = taken.get(hit.target, 0.0) + hit.intensity
        elif slot.name == "body_fall":
            for hit in slot.hits:
                if hit.actor:
                    taken[hit.actor] = taken.get(hit.actor, 0.0) + hit.intensity

    worst = max(taken, key=lambda name: taken[name], default=None)
    losing = (
        worst is not None
        and taken[worst] >= HEARTBEAT_TENSION
        and thrown.get(worst, 0.0) < taken[worst]
    )
    if losing:
        sheet.ambience.append(
            Ambience("heartbeat", 0.0, duration, 0.0, 0.9,
                     f"{worst} encaisse plus qu'il ne donne — le cœur monte "
                     f"avec la tension")
        )


def _spans_above(
    curve: list[tuple[float, float]], threshold: float, *, min_length: float
) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for time, value in curve:
        if value >= threshold and start is None:
            start = time
        elif value < threshold and start is not None:
            if time - start >= min_length:
                spans.append((start, time))
            start = None
    if start is not None and curve and curve[-1][0] - start >= min_length:
        spans.append((start, curve[-1][0]))
    return spans


#: Two stings a third of a second apart are one dramatic moment scored twice.
#: A peak has to stand alone to be worth marking.
PEAK_SEPARATION = 2.0


def _peaks(curve: list[tuple[float, float]], threshold: float) -> list[tuple[float, float]]:
    """The moments that matter: local maxima, thinned so each stands alone."""
    found: list[tuple[float, float]] = []
    for i in range(1, len(curve) - 1):
        _, before = curve[i - 1]
        time, value = curve[i]
        _, after = curve[i + 1]
        if value >= threshold and value >= before and value > after:
            found.append((time, value))

    kept: list[tuple[float, float]] = []
    for time, value in sorted(found, key=lambda p: -p[1]):
        if all(abs(time - other) >= PEAK_SEPARATION for other, _ in kept):
            kept.append((time, value))
    return sorted(kept)


# -- wiring it back into the scene --------------------------------------------


def apply_spotting(built: BuiltScene, sheet: SpottingSheet) -> None:
    """Write the spotted hits into the build, so they play frame-exact.

    A hit that belongs to an actor becomes a ``KeyframeMarker`` in that actor's
    clip — the same mechanism an authored event uses, and the same one Wwise
    reaches for when a footstep is fired from an animation notify rather than
    from a timer. It therefore survives publishing and stays put if the clip is
    retimed in Studio. A hit with nobody to carry it rides the director clock.
    """
    fps = built.scene.fps
    for slot in sheet.slots:
        for hit in slot.hits:
            value = f"{hit.slot}|{hit.intensity:.3f}|{hit.part}"
            if hit.actor is None:
                built.director.append((round(hit.time, 4), _SpotEvent(value)))
                continue
            frame = round(hit.time * fps)
            by_frame = built.markers.setdefault(hit.actor, {})
            by_frame.setdefault(frame, []).append(("linen_spot", value))
    built.director.sort(key=lambda pair: pair[0])


@dataclass
class _SpotEvent:
    """A derived hit on the director's clock.

    Deliberately not an :class:`~linen.scene.events.Event`: those are what the
    author wrote, and validate as such. These are measurements, and quacking
    like an Event is all the emitter needs.
    """

    value: str
    kind: str = "spot"
    actor: str | None = None

    def marker_value(self) -> str:
        return self.value


# -- the mapping file ---------------------------------------------------------


def read_mapping(path: str | Path) -> dict[str, str]:
    """Slot to asset id, from a previous build. Missing file means empty."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: fichier audio illisible ({exc})") from None
    # A malformed file is refused rather than ignored: silently starting from
    # scratch would throw away ids that took real work to gather.
    try:
        return {str(k): str(v) for k, v in data.get("sounds", {}).items() if v}
    except AttributeError:
        raise ValueError(
            f"{path}: 'sounds' doit être un objet slot -> identifiant"
        ) from None


def write_mapping(sheet: SpottingSheet, path: str | Path) -> Path:
    """Write the slot file, keeping every id already filled in."""
    path = Path(path)
    existing = read_mapping(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sheet.mapping(existing), indent=2, ensure_ascii=False) + "\n")
    return path
