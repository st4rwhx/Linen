"""The motion plan: the only thing a language model is ever asked to produce.

A plan is a *schedule*, not motion data.  It says which poses and cycles from
:mod:`linen.generate.posebook` play when, how they are eased into each other,
and what secondary motion sits on top.  Everything numeric and body-shaped is
resolved afterwards by :mod:`linen.generate.synth`, which is why the pipeline
degrades gracefully: a mediocre plan produces a plain animation rather than a
broken one, and a plan can be written by hand when no API key is available.

The plan is validated strictly.  Models hallucinate pose names, and a silent
fallback to rest would look like a bug in the exporter three stages later.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from . import posebook

EASINGS: tuple[str, ...] = (
    "linear",
    "ease_in",
    "ease_out",
    "ease_in_out",
    "anticipate",
    "overshoot",
)
LAYER_KINDS: tuple[str, ...] = ("breathing", "sway", "head_turn", "noise")
PRIORITIES: tuple[str, ...] = ("Idle", "Movement", "Action", "Action2", "Action3", "Action4")

#: Generous rather than tight. The hosted generators stop at ten seconds
#: because that is as much as a motion diffusion model's training window held;
#: composing from a pose vocabulary has no such window, so this exists only to
#: catch a typo in a duration, not to ration anything.
MAX_DURATION_SECONDS = 600.0


class PlanError(ValueError):
    """A plan that cannot be synthesised, with a message meant for the model."""


@dataclass
class Segment:
    start: float
    end: float
    #: Exactly one of these is set.
    pose: str | None = None
    cycle: str | None = None
    #: Cycles per second; defaults to the cycle's own suggested rate.
    rate: float | None = None
    easing: str = "ease_in_out"
    #: Seconds spent blending in from whatever came before.
    blend_in: float = 0.15

    def validate(self) -> None:
        if self.end <= self.start:
            raise PlanError(
                f"segment ends at {self.end} which is not after its start {self.start}"
            )
        if (self.pose is None) == (self.cycle is None):
            raise PlanError("each segment needs exactly one of 'pose' or 'cycle'")
        if self.pose is not None and self.pose not in posebook.POSES:
            raise PlanError(
                f"unknown pose {self.pose!r}; choose from: {', '.join(posebook.pose_names())}"
            )
        if self.cycle is not None and self.cycle not in posebook.CYCLES:
            raise PlanError(
                f"unknown cycle {self.cycle!r}; choose from: {', '.join(posebook.cycle_names())}"
            )
        if self.easing not in EASINGS:
            raise PlanError(
                f"unknown easing {self.easing!r}; choose from: {', '.join(EASINGS)}"
            )
        if self.rate is not None and not 0.05 <= self.rate <= 12.0:
            raise PlanError(f"rate {self.rate} is outside the usable range 0.05-12 Hz")
        if self.blend_in < 0:
            raise PlanError(f"blend_in cannot be negative, got {self.blend_in}")


@dataclass
class Layer:
    """Secondary motion added on top of the scheduled poses."""

    kind: str
    amplitude: float = 0.5
    rate: float = 0.3

    def validate(self) -> None:
        if self.kind not in LAYER_KINDS:
            raise PlanError(
                f"unknown layer {self.kind!r}; choose from: {', '.join(LAYER_KINDS)}"
            )
        if not 0.0 <= self.amplitude <= 2.0:
            raise PlanError(f"layer amplitude {self.amplitude} is outside 0-2")
        if not 0.0 < self.rate <= 8.0:
            raise PlanError(f"layer rate {self.rate} is outside 0-8 Hz")


@dataclass
class MotionPlan:
    name: str
    segments: list[Segment]
    fps: float = 30.0
    loop: bool = False
    priority: str = "Action"
    layers: list[Layer] = field(default_factory=list)
    #: Scales every pose's deviation from rest. 1.0 is as authored.
    energy: float = 1.0
    #: Free-text rationale from the model; kept for debugging, never executed.
    notes: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise PlanError("plan needs a non-empty name")
        if not self.segments:
            raise PlanError("plan needs at least one segment")
        if not 1.0 <= self.fps <= 120.0:
            raise PlanError(f"fps {self.fps} is outside the usable range 1-120")
        if self.priority not in PRIORITIES:
            raise PlanError(
                f"unknown priority {self.priority!r}; choose from: {', '.join(PRIORITIES)}"
            )
        if not 0.1 <= self.energy <= 2.0:
            raise PlanError(f"energy {self.energy} is outside 0.1-2.0")

        for segment in self.segments:
            segment.validate()
        for layer in self.layers:
            layer.validate()

        ordered = sorted(self.segments, key=lambda s: s.start)
        for previous, current in itertools.pairwise(ordered):
            if current.start < previous.end - 1e-6:
                raise PlanError(
                    f"segments overlap: one ends at {previous.end}, "
                    f"the next starts at {current.start}"
                )
        self.segments = ordered

        if self.duration > MAX_DURATION_SECONDS:
            raise PlanError(
                f"plan runs {self.duration:.1f}s; keep it under {MAX_DURATION_SECONDS:.0f}s"
            )

    @property
    def duration(self) -> float:
        return max((s.end for s in self.segments), default=0.0)

    @property
    def frame_count(self) -> int:
        return max(round(self.duration * self.fps) + 1, 1)

    # -- serialisation ----------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MotionPlan:
        if not isinstance(data, dict):
            raise PlanError(f"expected a JSON object, got {type(data).__name__}")
        unknown = set(data) - {
            "name",
            "segments",
            "fps",
            "loop",
            "priority",
            "layers",
            "energy",
            "notes",
        }
        if unknown:
            raise PlanError(f"unexpected field(s): {', '.join(sorted(unknown))}")

        try:
            segments = [Segment(**s) for s in data.get("segments", [])]
            layers = [Layer(**layer) for layer in data.get("layers", [])]
        except TypeError as exc:
            raise PlanError(f"malformed segment or layer: {exc}") from None

        plan = cls(
            name=str(data.get("name", "Animation")),
            segments=segments,
            fps=float(data.get("fps", 30.0)),
            loop=bool(data.get("loop", False)),
            priority=str(data.get("priority", "Action")),
            layers=layers,
            energy=float(data.get("energy", 1.0)),
            notes=str(data.get("notes", "")),
        )
        plan.validate()
        return plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "fps": self.fps,
            "loop": self.loop,
            "priority": self.priority,
            "energy": self.energy,
            "notes": self.notes,
            "segments": [
                {k: v for k, v in vars(s).items() if v is not None} for s in self.segments
            ],
            "layers": [vars(layer) for layer in self.layers],
        }


def json_schema() -> dict[str, Any]:
    """JSON Schema for providers that support structured output.

    Enumerating the pose and cycle vocabulary here is what keeps a model from
    inventing ``"pose": "backflip"``; providers without schema support get the
    same list in the prompt instead.
    """
    return {
        "type": "object",
        "required": ["name", "segments"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "fps": {"type": "number", "minimum": 1, "maximum": 120},
            "loop": {"type": "boolean"},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "energy": {"type": "number", "minimum": 0.1, "maximum": 2.0},
            "notes": {"type": "string"},
            "segments": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["start", "end"],
                    "additionalProperties": False,
                    "properties": {
                        "start": {"type": "number", "minimum": 0},
                        "end": {"type": "number", "minimum": 0},
                        "pose": {"type": "string", "enum": list(posebook.pose_names())},
                        "cycle": {"type": "string", "enum": list(posebook.cycle_names())},
                        "rate": {"type": "number", "minimum": 0.05, "maximum": 12},
                        "easing": {"type": "string", "enum": list(EASINGS)},
                        "blend_in": {"type": "number", "minimum": 0, "maximum": 2},
                    },
                },
            },
            "layers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kind"],
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"type": "string", "enum": list(LAYER_KINDS)},
                        "amplitude": {"type": "number", "minimum": 0, "maximum": 2},
                        "rate": {"type": "number", "minimum": 0.01, "maximum": 8},
                    },
                },
            },
        },
    }
