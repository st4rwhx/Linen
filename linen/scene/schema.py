"""Several rigs, one timeline: the scene description.

A single animation answers "what does this character do". A cinematic answers
"what do these characters do *to each other*, and when", and the second question
is mostly about scheduling. So a scene is a cast plus a list of cues, and a cue
can be anchored to another cue rather than to the clock — which is how a
reaction lands a frame or two after the punch that caused it, and stays there
when you retime the punch.

What this deliberately does not attempt is solved contact. Making a hand
actually land on another character's shoulder, for two rigs of unknown
proportions, needs an IK solver with collision awareness. Cues give you the
staging and the timing, which is most of what reads as interaction on screen;
the last few centimetres are a manual nudge in the Animation Editor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..generate.timing import STRATEGIES
from ..rigs import RIGS
from .events import Event, EventError, Prop, Shot, event_from_dict

Vec3 = tuple[float, float, float]

MAX_ACTORS = 12
MAX_CUES = 200
MAX_SCENE_SECONDS = 600.0


class SceneError(ValueError):
    """A scene that cannot be built, phrased for whoever wrote it."""


@dataclass
class Actor:
    """One character in the scene."""

    name: str
    rig: str = "R15"
    #: Spawn position in studs, Roblox axes.
    position: Vec3 = (0.0, 0.0, 0.0)
    #: Another actor's name to face, or a yaw in degrees. Facing an actor is
    #: usually what you mean, and it survives moving either of them.
    facing: str | float | None = None

    def validate(self, cast: set[str]) -> None:
        if not self.name.strip():
            raise SceneError("an actor needs a name")
        if self.rig.upper() not in RIGS:
            raise SceneError(
                f"{self.name}: unknown rig {self.rig!r}; "
                f"choose from {', '.join(sorted(RIGS))}"
            )
        if len(self.position) != 3:
            raise SceneError(f"{self.name}: position needs three numbers")
        if isinstance(self.facing, str):
            if self.facing == self.name:
                raise SceneError(f"{self.name} cannot face itself")
            if self.facing not in cast:
                raise SceneError(
                    f"{self.name} faces {self.facing!r}, who is not in the cast"
                )


@dataclass
class Cue:
    """One actor doing one thing, placed on the scene's timeline."""

    actor: str
    #: What to animate. Either a prompt for the planner or an inline plan.
    prompt: str | None = None
    plan: dict[str, Any] | None = None
    #: Referred to by other cues' ``after`` / ``with``. Defaults to
    #: ``<actor>_<index>``.
    id: str = ""
    #: Absolute start, in seconds.
    at: float | None = None
    #: Start when the named cue *ends*. A reaction to a completed action.
    after: str | None = None
    #: Start when the named cue *starts*. Two things happening together.
    with_: str | None = None
    #: Shifts whichever anchor was used. Negative overlaps the anchor.
    offset: float = 0.0
    #: Target length, as in `linen prompt --duration`.
    duration: float | None = None
    fit: str = "auto"
    loop: bool = False

    def validate(self, cast: set[str]) -> None:
        if self.actor not in cast:
            raise SceneError(f"cue {self.id!r} is for {self.actor!r}, who is not in the cast")
        if (self.prompt is None) == (self.plan is None):
            raise SceneError(f"cue {self.id!r} needs exactly one of 'prompt' or 'plan'")
        anchors = [self.at is not None, self.after is not None, self.with_ is not None]
        if sum(anchors) > 1:
            raise SceneError(
                f"cue {self.id!r} sets more than one of 'at', 'after' and 'with'"
            )
        if self.fit not in STRATEGIES:
            raise SceneError(
                f"cue {self.id!r}: unknown fit {self.fit!r}; "
                f"expected one of {', '.join(STRATEGIES)}"
            )
        if self.duration is not None and self.duration <= 0:
            raise SceneError(f"cue {self.id!r}: duration must be positive")


@dataclass
class Scene:
    name: str
    actors: list[Actor]
    cues: list[Cue]
    fps: float = 30.0
    notes: str = ""
    #: Objects characters hold, drop or throw.
    props: list[Prop] = field(default_factory=list)
    #: Camera setups the director may cut to.
    shots: list[Shot] = field(default_factory=list)
    #: Sound, effects, expressions, props, camera and dialogue, each anchored
    #: to a cue rather than to the clock.
    events: list[Event] = field(default_factory=list)

    def validate(self) -> None:
        if not self.name.strip():
            raise SceneError("a scene needs a name")
        if not self.actors:
            raise SceneError("a scene needs at least one actor")
        if len(self.actors) > MAX_ACTORS:
            raise SceneError(f"{len(self.actors)} actors; keep it under {MAX_ACTORS}")
        if not self.cues:
            raise SceneError("a scene needs at least one cue")
        if len(self.cues) > MAX_CUES:
            raise SceneError(f"{len(self.cues)} cues; keep it under {MAX_CUES}")
        if not 1.0 <= self.fps <= 120.0:
            raise SceneError(f"fps {self.fps} is outside the usable range 1-120")

        cast = {actor.name for actor in self.actors}
        if len(cast) != len(self.actors):
            raise SceneError("two actors share a name")
        for actor in self.actors:
            actor.validate(cast)

        self._assign_ids()
        seen: set[str] = set()
        for cue in self.cues:
            if cue.id in seen:
                raise SceneError(f"two cues share the id {cue.id!r}")
            seen.add(cue.id)
            cue.validate(cast)

        for cue in self.cues:
            for anchor in (cue.after, cue.with_):
                if anchor is not None and anchor not in seen:
                    raise SceneError(
                        f"cue {cue.id!r} is anchored to {anchor!r}, which does not exist. "
                        f"Known cues: {', '.join(sorted(seen))}"
                    )

        # Props, shots and events raise EventError; whoever wrote the scene does
        # not care which module noticed, so they all surface as SceneError.
        shot_ids = {shot.id for shot in self.shots}
        prop_names = {prop.name for prop in self.props}
        try:
            for prop in self.props:
                prop.validate(cast)
            for shot in self.shots:
                shot.validate()
            for event in self.events:
                event.validate(cast, seen, shot_ids, prop_names)
        except EventError as exc:
            raise SceneError(str(exc)) from None

    def _assign_ids(self) -> None:
        counters: dict[str, int] = {}
        for cue in self.cues:
            if not cue.id:
                index = counters.get(cue.actor, 0)
                cue.id = f"{cue.actor}_{index}"
                counters[cue.actor] = index + 1

    def actor(self, name: str) -> Actor:
        for actor in self.actors:
            if actor.name == name:
                return actor
        raise SceneError(f"no actor named {name!r}")

    def cues_for(self, actor: str) -> list[Cue]:
        return [cue for cue in self.cues if cue.actor == actor]

    # -- serialisation ----------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scene:
        if not isinstance(data, dict):
            raise SceneError(f"expected a JSON object, got {type(data).__name__}")
        unknown = set(data) - {
            "name", "actors", "cues", "fps", "notes", "props", "shots", "events",
        }
        if unknown:
            raise SceneError(f"unexpected field(s): {', '.join(sorted(unknown))}")

        try:
            actors = [Actor(**_tuple_position(a)) for a in data.get("actors", [])]
            cues = [Cue(**_rename_with(c)) for c in data.get("cues", [])]
            props = [Prop(**_tuple_field(p, "grip")) for p in data.get("props", [])]
            shots = [Shot(**_tuple_field(s, "position", "drift", "follow_offset")) for s in data.get("shots", [])]
            events = [event_from_dict(e) for e in data.get("events", [])]
        except TypeError as exc:
            raise SceneError(f"malformed actor or cue: {exc}") from None

        scene = cls(
            name=str(data.get("name", "Scene")),
            actors=actors,
            cues=cues,
            fps=float(data.get("fps", 30.0)),
            notes=str(data.get("notes", "")),
            props=props,
            shots=shots,
            events=events,
        )
        scene.validate()
        return scene

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "fps": self.fps,
            "notes": self.notes,
            "actors": [
                {
                    "name": a.name,
                    "rig": a.rig,
                    "position": list(a.position),
                    **({"facing": a.facing} if a.facing is not None else {}),
                }
                for a in self.actors
            ],
            "cues": [
                {
                    key.rstrip("_"): value
                    for key, value in vars(cue).items()
                    if value is not None and not (key == "offset" and value == 0.0)
                }
                for cue in self.cues
            ],
            # Props, shots and events used to be dropped here, which made
            # `--save-scene` write a file missing the camera, the props and
            # every sound — and reading it back gave a scene that built and was
            # not the one that was written.
            **({"props": [_plain(p) for p in self.props]} if self.props else {}),
            **({"shots": [_plain(s) for s in self.shots]} if self.shots else {}),
            **({"events": [_plain(e) for e in self.events]} if self.events else {}),
        }


def _plain(item: Any) -> dict[str, Any]:
    """One dataclass as JSON, without the fields nobody set.

    Writing every default back out would turn a four-line shot into twelve and
    bury what the author actually chose.
    """
    from dataclasses import fields

    out: dict[str, Any] = {}
    for spec in fields(item):
        value = getattr(item, spec.name)
        if value is None or value == spec.default:
            continue
        out[spec.name.rstrip("_")] = list(value) if isinstance(value, tuple) else value
    return out


def _tuple_field(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    """JSON has no tuples, so the vector fields arrive as lists."""
    out = dict(data)
    for key in keys:
        if key in out and out[key] is not None:
            out[key] = tuple(float(v) for v in out[key])
    return out


def _tuple_position(actor: dict[str, Any]) -> dict[str, Any]:
    data = dict(actor)
    if "position" in data:
        data["position"] = tuple(float(v) for v in data["position"])
    return data


def _rename_with(cue: dict[str, Any]) -> dict[str, Any]:
    """``with`` is a Python keyword, so the field is ``with_`` internally."""
    data = dict(cue)
    if "with" in data:
        data["with_"] = data.pop("with")
    return data


def json_schema() -> dict[str, Any]:
    """JSON Schema for providers that support structured output."""
    return {
        "type": "object",
        "required": ["name", "actors", "cues"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "fps": {"type": "number", "minimum": 1, "maximum": 120},
            "notes": {"type": "string"},
            "actors": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_ACTORS,
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "rig": {"type": "string", "enum": sorted(RIGS)},
                        "position": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "facing": {"type": "string"},
                    },
                },
            },
            "cues": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["actor", "prompt"],
                    "additionalProperties": False,
                    "properties": {
                        "actor": {"type": "string"},
                        "prompt": {"type": "string"},
                        "id": {"type": "string"},
                        "at": {"type": "number", "minimum": 0},
                        "after": {"type": "string"},
                        "with": {"type": "string"},
                        "offset": {"type": "number"},
                        "duration": {"type": "number", "minimum": 0.1},
                        "loop": {"type": "boolean"},
                    },
                },
            },
        },
    }
