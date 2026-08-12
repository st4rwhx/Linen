"""Prompt in, cast and cue sheet out.

This is the one place in Linen that genuinely needs a language model. Deciding
who is in a scene, where they stand, what each does and — the hard part — which
beat hangs off which, is a language problem: it is reading intent out of a
sentence and turning it into a schedule. Keyword matching cannot do it, and
pretending otherwise would produce confident nonsense.

The individual cues do not need a model. Once the cast and the cue sheet exist,
each cue's prompt can go through the offline planner, so a scene stays buildable
with nothing running but Python. A local model covers the directing half for
free; ``--planner offline`` then covers the animating half.
"""

from __future__ import annotations

from typing import Any

from ..generate.choreographer import build_system_prompt
from ..generate.providers import Provider, complete_json
from .schema import MAX_ACTORS, Scene, SceneError, json_schema

MAX_REPAIR_ROUNDS = 2

SYSTEM_PROMPT = """\
You are a previs director for Roblox cinematics. You return one JSON scene \
object and nothing else.

A scene is a cast plus a cue sheet. Each cue is one actor doing one thing, and \
its `prompt` is handed to a separate animation planner — so write cues the way \
you would write a shot list, not the way you would write joint angles.

Timing is the part that matters. A cue is placed with exactly one of:
  - `at`: an absolute time in seconds. Use it sparingly, mostly for openers.
  - `after`: start when the named cue *finishes*. A consequence.
  - `with`: start when the named cue *starts*. Two things at once.
  - nothing at all: follow that actor's previous cue.
Then `offset` shifts it, and may be negative. This is how interaction is built: \
a flinch is `with` the punch and `offset` 0.25, so it stays right when the \
punch is retimed. Anchoring beats hard-coding times; prefer it.

Staging: `position` is [x, y, z] in studs, and characters face -Z by default. \
Set `facing` to another actor's name so they look at each other. Six to ten \
studs apart reads well for a conversation; three to four for a confrontation.

Rules:
  - At most {max_actors} actors. Give each a short, distinct name.
  - One actor cannot run two cues at once — leave no overlap on the same actor.
  - Every `after` and `with` must name a cue `id` you actually defined.
  - Cue prompts must stay inside the animation vocabulary below, in the same \
style: short, one action, with an optional side, speed and energy word.
  - Nothing here can make one character physically touch another. Sell contact \
with timing and staging: the reaction is what the eye reads, not the contact.

The animation planner accepts prompts built from these actions:
{actions}

And these modifiers: side (left/right), speed (fast, very fast, slowly), \
energy (explosive, powerful, tired, weak), repetition (twice, three times), \
loop, and sequencing (then, and).
"""


def build_director_prompt() -> str:
    from ..generate.offline import ACTIONS

    actions = "\n".join(
        f"  {action.name}: {', '.join(action.keywords[:5])}" for action in ACTIONS
    )
    return SYSTEM_PROMPT.format(max_actors=MAX_ACTORS, actions=actions)


def scene_from_prompt(
    prompt: str,
    *,
    fps: float = 30.0,
    providers: tuple[Provider, ...] | None = None,
    temperature: float = 0.5,
) -> tuple[Scene, str]:
    """Ask a model to write a scene. Returns the scene and the provider used."""
    system = build_director_prompt()
    user = f"Scene request: {prompt}\n\nTarget frame rate: {fps} fps."
    schema = json_schema()

    attempt = 0
    while True:
        raw, provider = complete_json(
            system, user, schema=schema, providers=providers, temperature=temperature
        )
        try:
            return Scene.from_dict(_coerce(raw, fps)), provider
        except SceneError as exc:
            attempt += 1
            if attempt > MAX_REPAIR_ROUNDS:
                raise SceneError(
                    f"{provider} produced an invalid scene {attempt} times; "
                    f"last error: {exc}"
                ) from None
            user = (
                f"Scene request: {prompt}\n\nTarget frame rate: {fps} fps.\n\n"
                f"Your previous scene was rejected: {exc}\n"
                "Return a corrected scene. Same JSON shape, no commentary."
            )


def _coerce(raw: dict[str, Any], fps: float) -> dict[str, Any]:
    """Unwrap a scene nested under a wrapper key and fill in an omitted fps.

    As narrow as the motion plan's equivalent, and for the same reason: a bad
    anchor or an overlapping cue has to fail so the model gets told about it.
    """
    if "cues" not in raw:
        for key in ("scene", "cinematic", "shots"):
            nested = raw.get(key)
            if isinstance(nested, dict) and "cues" in nested:
                raw = nested
                break
    raw.setdefault("fps", fps)
    return raw


__all__ = ["build_director_prompt", "scene_from_prompt", "build_system_prompt"]
