"""Prompt in, validated motion plan out.

The model is given the pose vocabulary and asked for a schedule.  When the plan
comes back invalid — a hallucinated pose name, overlapping segments — the
validator's message is handed straight back to the model for one repair round,
which fixes the large majority of failures without a second provider.
"""

from __future__ import annotations

from typing import Any

from . import posebook
from .offline import plan_offline
from .providers import NoProviderConfigured, Provider, ProviderError, complete_json
from .schema import EASINGS, LAYER_KINDS, PRIORITIES, MotionPlan, PlanError, json_schema

MAX_REPAIR_ROUNDS = 2

SYSTEM_PROMPT = """\
You are an animation director for Roblox characters. You do not produce joint \
rotations. You produce a schedule — a JSON motion plan — that a deterministic \
synthesiser turns into an animation.

Return one JSON object and nothing else.

The plan has segments laid out on a timeline in seconds. Each segment holds \
either a single `pose` or a repeating `cycle`, and blends in from the previous \
segment over `blend_in` seconds using `easing`.

Available poses:
{poses}

Available cycles:
{cycles}

Easings: {easings}
  - `anticipate` pulls back before the move; use it before an impact or a jump.
  - `overshoot` settles past the target; use it when something lands or stops.
Layers (secondary motion, keep amplitudes near 0.3-0.8): {layers}
Priorities: {priorities}

How to make it read well:
- Anticipation, action, settle. A punch is windup (anticipate) -> extend \
(short, ease_out) -> recover (overshoot). Never cut straight to the action pose.
- Contrast the timing. Fast beats are 0.08-0.2s, holds are 0.3-0.8s. \
Uniform spacing is what makes an animation look procedural.
- Hold the extremes. A pose the eye cannot rest on does not register.
- Give a looping animation `loop: true`, matching first and last segments, and \
priority `Idle` or `Movement`. One-shot actions get `Action`.
- Add a `breathing` or `sway` layer to anything that idles, or it looks frozen.
- Keep the whole plan under 12 seconds unless asked otherwise.

Only use pose and cycle names from the lists above. If the request needs \
something the vocabulary cannot express, get as close as you can with what \
exists and say so in `notes`.\
"""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT.format(
        poses="  " + ", ".join(posebook.pose_names()),
        cycles="  "
        + ", ".join(
            f"{name} (~{cycle.default_rate} Hz)" for name, cycle in sorted(posebook.CYCLES.items())
        ),
        easings=", ".join(EASINGS),
        layers=", ".join(LAYER_KINDS),
        priorities=", ".join(PRIORITIES),
    )


PLANNERS = ("auto", "model", "offline")


def plan_for_prompt(
    prompt: str,
    *,
    fps: float = 30.0,
    planner: str = "auto",
    providers: tuple[Provider, ...] | None = None,
    temperature: float = 0.4,
) -> tuple[MotionPlan, str]:
    """Plan ``prompt``, choosing between a language model and the offline path.

    ``auto`` prefers a model — a local one first, since that is free and stays
    on the machine — and falls back to :func:`plan_offline` when none answers,
    so the command always produces an animation. ``offline`` never touches the
    network at all.
    """
    if planner not in PLANNERS:
        raise ValueError(
            f"unknown planner {planner!r}; expected one of {', '.join(PLANNERS)}"
        )

    if planner == "offline":
        return plan_offline(prompt, fps=fps), "offline"

    try:
        return plan_from_prompt(
            prompt, fps=fps, providers=providers, temperature=temperature
        )
    except (NoProviderConfigured, ProviderError, PlanError):
        if planner == "model":
            raise
        return plan_offline(prompt, fps=fps), "offline"


def plan_from_prompt(
    prompt: str,
    *,
    fps: float = 30.0,
    providers: tuple[Provider, ...] | None = None,
    temperature: float = 0.4,
) -> tuple[MotionPlan, str]:
    """Ask a model for a plan for ``prompt``. Returns the plan and the provider."""
    system = build_system_prompt()
    user = f"Animation request: {prompt}\n\nTarget frame rate: {fps} fps."
    schema = json_schema()

    attempt = 0
    provider_used = ""
    while True:
        raw, provider_used = complete_json(
            system, user, schema=schema, providers=providers, temperature=temperature
        )
        try:
            plan = MotionPlan.from_dict(_coerce(raw, fps))
        except PlanError as exc:
            attempt += 1
            if attempt > MAX_REPAIR_ROUNDS:
                raise PlanError(
                    f"{provider_used} produced an invalid plan {attempt} times; "
                    f"last error: {exc}"
                ) from None
            user = (
                f"Animation request: {prompt}\n\nTarget frame rate: {fps} fps.\n\n"
                f"Your previous plan was rejected: {exc}\n"
                "Return a corrected plan. Same JSON shape, no commentary."
            )
            continue
        return plan, provider_used


def _coerce(raw: dict[str, Any], fps: float) -> dict[str, Any]:
    """Nudge the near-misses models reliably produce into the plan's shape.

    Deliberately narrow: it fills in an omitted fps and unwraps a plan nested
    under a wrapper key.  Anything else — a bad pose name, a bad timeline — is
    left to fail validation so the model gets told about it and can fix it,
    rather than being silently papered over here.
    """
    if "segments" not in raw:
        for key in ("plan", "motion_plan", "animation"):
            nested = raw.get(key)
            if isinstance(nested, dict) and "segments" in nested:
                raw = nested
                break
    raw.setdefault("fps", fps)
    return raw
