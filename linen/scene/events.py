"""What happens *around* the bodies: sound, effects, props, faces, camera, lines.

A cinematic is not only who moves. It is a gunshot landing on the frame the
hand opens, a wall puff on the frame the pistol hits it, an expression turning
smug half a second before the line, and a camera that cuts to the wall and back.
Those are all the same kind of thing — something fired at an instant — so they
are one list here rather than five subsystems.

The instant is expressed the way cue timing already is: anchored to a cue, not
to the clock. Retime the disarm and the gunshot, the impact, the camera cut and
the line all move with it. That is the difference between a cinematic you can
edit and one you have to rebuild.

Roblox has a frame-accurate mechanism for exactly this: a ``KeyframeMarker``
parented to a ``Keyframe`` fires ``AnimationTrack:GetMarkerReachedSignal(name)``
with an optional value when playback reaches it. Events bound to an actor are
written into that actor's animation as markers, so they stay correct even if
someone retimes the clip in Studio afterwards. Events with no actor — a camera
cut, a wall effect — have no animation to ride, and go on the director's clock
in the generated scene script.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: What an event does when it fires.
KINDS: tuple[str, ...] = (
    #: Play a Sound. `asset` is an rbxassetid, which is where ElevenLabs
    #: material lands once uploaded.
    "sound",
    #: Emit a ParticleEmitter burst, or enable a named effect.
    "vfx",
    #: Set a facial expression. Needs a dynamic head; ignored on a blocky one.
    "face",
    #: Attach, release or throw a prop.
    "prop",
    #: Cut or move to a named shot.
    "camera",
    #: Show a line of dialogue.
    "line",
    #: Land a hand on another character, or on something in the place. Unlike
    #: every other kind here this one *changes the animation*: it is solved
    #: into the clip rather than fired at playback, because where a hand has to
    #: be is not something a capture of one person can know.
    "contact",
)

#: FaceControls is a 50-pose FACS rig. These are the presets the director may
#: name; each maps to a blend of poses in the runtime, so a scene stays
#: readable instead of listing FACS coefficients.
EXPRESSIONS: tuple[str, ...] = (
    "neutral",
    "smug",
    "angry",
    "afraid",
    "surprised",
    "pain",
    "determined",
    "laughing",
    "sad",
)

PROP_ACTIONS: tuple[str, ...] = ("attach", "release", "throw")

#: How a camera behaves for the length of a shot.
SHOT_KINDS: tuple[str, ...] = ("static", "orbit", "follow")


class EventError(ValueError):
    """An event that cannot be played, phrased for whoever wrote the scene."""


@dataclass
class Shot:
    """One camera setup.

    ``look_at`` names an actor or a prop, so a shot keeps framing its subject
    when the staging moves — the same reason cues anchor to each other.
    """

    id: str
    position: tuple[float, float, float]
    look_at: str
    fov: float = 55.0
    #: Seconds to travel from the previous shot. Zero is a cut.
    blend: float = 0.0
    #: Drift towards this offset over the shot, in studs. A shot that is
    #: perfectly still reads as a screenshot, not a camera.
    drift: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: How the camera behaves for the length of the shot.
    #:
    #: ``static`` holds the written position and drifts. ``orbit`` revolves
    #: around the subject — the shot that sells a reveal, and the one people
    #: mean by "cinematic". ``follow`` keeps a fixed offset from the subject,
    #: so a moving character stays framed the same way.
    #:
    #: The last two need the camera re-aimed every frame against where the
    #: subject *is now*, which a tween to a fixed CFrame cannot do.
    kind: str = "static"
    #: orbit — degrees per second, signed. Slow is cinematic; fast is a
    #: music video. 20 to 40 reads as deliberate.
    orbit_speed: float = 25.0
    #: orbit — studs from the subject. Taken from `position` when zero, so a
    #: shot can be written by placing the camera rather than by arithmetic.
    orbit_radius: float = 0.0
    #: follow — where to sit relative to the subject, in studs. The subject's
    #: own facing is ignored on purpose: a camera that yaws with a turning
    #: character makes the viewer seasick.
    follow_offset: tuple[float, float, float] = (0.0, 3.0, 8.0)
    #: follow — seconds of lag. Zero is welded to the subject and reads as
    #: rigid; a little lag is what makes a follow look operated.
    follow_lag: float = 0.25

    def validate(self) -> None:
        if not self.id.strip():
            raise EventError("a shot needs an id")
        if self.kind not in SHOT_KINDS:
            raise EventError(
                f"shot {self.id!r}: unknown kind {self.kind!r}; "
                f"choose from {', '.join(SHOT_KINDS)}"
            )
        if self.kind == "orbit" and abs(self.orbit_speed) < 1e-6:
            raise EventError(
                f"shot {self.id!r} orbits at 0 deg/s, which is a static shot "
                f"written the hard way"
            )
        if self.follow_lag < 0:
            raise EventError(f"shot {self.id!r}: follow_lag cannot be negative")
        if len(self.position) != 3:
            raise EventError(f"shot {self.id!r}: position needs three numbers")
        if not 5.0 <= self.fov <= 120.0:
            raise EventError(f"shot {self.id!r}: fov {self.fov} is outside 5-120")
        if self.blend < 0:
            raise EventError(f"shot {self.id!r}: blend cannot be negative")


@dataclass
class Prop:
    """An object a character can hold, drop or throw."""

    name: str
    #: Where the model lives in the place, e.g. "ReplicatedStorage.Props.Pistol".
    source: str
    #: Actor holding it at the start, if any.
    held_by: str | None = None
    #: Which part it is welded to while held.
    attach_to: str = "RightHand"
    #: Offset from that part's pivot, in studs.
    grip: tuple[float, float, float] = (0.0, -0.3, 0.0)

    def validate(self, cast: set[str]) -> None:
        if not self.name.strip():
            raise EventError("a prop needs a name")
        if not self.source.strip():
            raise EventError(f"prop {self.name!r}: needs a source path")
        if self.held_by is not None and self.held_by not in cast:
            raise EventError(
                f"prop {self.name!r} is held by {self.held_by!r}, who is not in the cast"
            )


@dataclass
class Event:
    """Something fired at an instant, anchored to a cue."""

    kind: str
    #: The cue this hangs off. Its start is the reference point.
    cue: str
    #: Seconds after that cue starts. Negative fires before it.
    offset: float = 0.0
    #: The actor this belongs to, when it belongs to one. An event with an
    #: actor becomes a KeyframeMarker in that actor's animation; one without
    #: goes on the director's clock.
    actor: str | None = None

    # -- per-kind payload -------------------------------------------------
    #: sound
    asset: str | None = None
    volume: float = 1.0
    #: vfx — a named effect in the place, and optionally where to put it.
    effect: str | None = None
    at_part: str | None = None
    #: face
    expression: str | None = None
    #: prop
    prop: str | None = None
    action: str | None = None
    impulse: tuple[float, float, float] | None = None
    #: camera
    shot: str | None = None
    #: line
    text: str | None = None
    #: contact — which hand, and what it lands on.
    limb: str | None = None
    #: The actor being touched, or None for something in the place.
    target_actor: str | None = None
    #: The part of them, or the landmark's name.
    target_part: str | None = None
    #: How long a line stays up, or an expression holds.
    hold: float = 2.0

    def validate(self, cast: set[str], cue_ids: set[str], shots: set[str], props: set[str]) -> None:
        if self.kind not in KINDS:
            raise EventError(f"unknown event kind {self.kind!r}; expected one of {', '.join(KINDS)}")
        if self.cue not in cue_ids:
            raise EventError(
                f"{self.kind} event is anchored to cue {self.cue!r}, which does not exist. "
                f"Known cues: {', '.join(sorted(cue_ids))}"
            )
        if self.actor is not None and self.actor not in cast:
            raise EventError(f"{self.kind} event names {self.actor!r}, who is not in the cast")

        if self.kind == "sound" and not self.asset:
            raise EventError("a sound event needs an 'asset' — an rbxassetid")
        if self.kind == "vfx" and not self.effect:
            raise EventError("a vfx event needs an 'effect' name")
        if self.kind == "face":
            if self.actor is None:
                raise EventError("a face event needs an 'actor'")
            if self.expression not in EXPRESSIONS:
                raise EventError(
                    f"unknown expression {self.expression!r}; "
                    f"choose from {', '.join(EXPRESSIONS)}"
                )
        if self.kind == "prop":
            if self.prop not in props:
                raise EventError(
                    f"prop event names {self.prop!r}; known props: "
                    f"{', '.join(sorted(props)) or 'none'}"
                )
            if self.action not in PROP_ACTIONS:
                raise EventError(
                    f"unknown prop action {self.action!r}; "
                    f"choose from {', '.join(PROP_ACTIONS)}"
                )
            if self.action == "attach" and self.actor is None:
                raise EventError("attaching a prop needs an 'actor' to attach it to")
        if self.kind == "camera" and self.shot not in shots:
            raise EventError(
                f"camera event names shot {self.shot!r}; known shots: "
                f"{', '.join(sorted(shots)) or 'none'}"
            )
        if self.kind == "line" and not (self.text or "").strip():
            raise EventError("a line event needs 'text'")
        if self.kind == "contact":
            from .contact import CHAINS

            if self.actor is None:
                raise EventError("a contact event needs the 'actor' doing the reaching")
            if self.limb not in CHAINS:
                raise EventError(
                    f"contact event: unknown limb {self.limb!r}; "
                    f"choose from {', '.join(sorted(CHAINS))}"
                )
            if not (self.target_part or "").strip():
                raise EventError(
                    "a contact event needs a 'target_part' — the part of the other "
                    "character, or the name of something in the place"
                )
            if self.target_actor is not None and self.target_actor not in cast:
                raise EventError(
                    f"contact event reaches for {self.target_actor!r}, who is not "
                    f"in the cast"
                )
            if self.target_actor == self.actor:
                raise EventError(f"{self.actor} cannot reach for themselves")
            if self.hold <= 0:
                raise EventError("a contact event needs a positive 'hold'")

    @property
    def marker_name(self) -> str:
        """The KeyframeMarker name this becomes, when it rides an animation."""
        return f"linen_{self.kind}"

    def marker_value(self) -> str:
        """The single string a KeyframeMarker can carry.

        Roblox passes one value with the signal, so the payload is packed into
        it and unpacked by the runtime. Keeping it to one field is what lets a
        published animation carry its own events with nothing alongside.
        """
        payload = {
            "sound": self.asset,
            "vfx": f"{self.effect}|{self.at_part or ''}",
            "face": f"{self.expression}|{self.hold:g}",
            "prop": f"{self.prop}|{self.action}|{_vector(self.impulse)}",
            "camera": self.shot,
            "line": f"{self.text}|{self.hold:g}",
        }[self.kind]
        return str(payload)


def _vector(value: tuple[float, float, float] | None) -> str:
    return "" if value is None else ",".join(f"{v:g}" for v in value)


def event_from_dict(data: dict[str, Any]) -> Event:
    """Parse one event, tolerating the tuple fields arriving as lists."""
    payload = dict(data)
    for key in ("impulse",):
        if payload.get(key) is not None:
            payload[key] = tuple(float(v) for v in payload[key])
    try:
        return Event(**payload)
    except TypeError as exc:
        raise EventError(f"malformed event: {exc}") from None
