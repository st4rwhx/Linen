"""A motion planner that needs no model at all.

This is the path that makes "prompt to animation, fully local and free" true
without qualification: no API key, no GPU, no download, no network. It reads
the prompt for known actions and modifiers and assembles the same
:class:`~linen.generate.schema.MotionPlan` a language model would have written.

It is keyword matching, and saying so plainly matters — it does not understand
a sentence, it recognises words in it. What it does have is the part a language
model tends to get wrong anyway: the *timing*. Each action below is a hand-built
beat sheet — anticipation, action, settle, with contrasting durations — so a
recognised action comes out shaped like an animation rather than like a lerp
between two poses.

French and English are both matched, because "saute deux fois puis salue" should
work as well as "jump twice then wave".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .schema import Layer, MotionPlan, Segment

#: Words that separate one action from the next.
SEPARATORS = (
    "puis",
    "ensuite",
    "apres",
    "then",
    "after",
    "and then",
    "et",
    "and",
    ",",
    ";",
    ".",
)


@dataclass(frozen=True)
class Beat:
    """One entry in an action's beat sheet."""

    duration: float
    pose: str | None = None
    cycle: str | None = None
    easing: str = "ease_in_out"
    blend_in: float = 0.12
    rate: float | None = None


@dataclass(frozen=True)
class Action:
    name: str
    #: Accent-stripped, lowercase stems, matched at a word boundary and then as
    #: a prefix — "march" catches "marche", "marcher" and "marching", while
    #: "coup" does *not* fire inside "beaucoup". Plain substring matching gets
    #: that wrong often enough in French to be worth the regex.
    keywords: tuple[str, ...]
    beats: tuple[Beat, ...]
    priority: str = "Action"
    #: Has left/right variants named ``<pose>_left`` / ``<pose>_right``.
    sided: bool = False
    #: Can be the whole of a looping animation.
    loopable: bool = False
    layers: tuple[Layer, ...] = field(default=())


_IDLE_LAYERS = (Layer("breathing", 0.6, 0.25), Layer("sway", 0.35, 0.18))

ACTIONS: tuple[Action, ...] = (
    Action(
        "idle",
        ("idle", "attente", "repos", "immobile", "debout", "stand", "wait", "breath"),
        (Beat(2.4, pose="stand_relaxed", easing="ease_in_out"),),
        priority="Idle",
        loopable=True,
        layers=_IDLE_LAYERS,
    ),
    Action(
        "walk",
        ("marche", "marcher", "walk", "avance", "stroll"),
        (Beat(2.2, cycle="walk"),),
        priority="Movement",
        loopable=True,
    ),
    Action(
        "run",
        ("cour", "run", "sprint", "jogg", "fuit", "fuir", "dash"),
        (Beat(2.0, cycle="run"),),
        priority="Movement",
        loopable=True,
    ),
    Action(
        "wave",
        ("salut", "salue", "coucou", "wave", "hello", "hi ", "bonjour", "greet"),
        (
            Beat(0.22, pose="stand_relaxed", easing="ease_out"),
            Beat(1.5, cycle="wave_{side}", blend_in=0.18),
            Beat(0.40, pose="stand_relaxed", easing="overshoot", blend_in=0.30),
        ),
        sided=True,
    ),
    Action(
        "jump",
        ("saut", "jump", "bond", "hop", "leap"),
        (
            # Crouch is the anticipation; the take-off is short and the apex
            # hangs, which is what sells weight.
            Beat(0.16, pose="stand_relaxed", easing="ease_out"),
            Beat(0.16, pose="crouch", easing="anticipate", blend_in=0.14),
            Beat(0.10, pose="jump_takeoff", easing="ease_out", blend_in=0.08),
            Beat(0.34, pose="jump_apex", blend_in=0.10),
            Beat(0.14, pose="land", easing="ease_in", blend_in=0.08),
            Beat(0.38, pose="stand_relaxed", easing="overshoot", blend_in=0.28),
        ),
    ),
    Action(
        "crouch",
        ("accroupi", "baisse", "crouch", "duck", "squat"),
        (
            Beat(0.18, pose="stand_relaxed", easing="ease_out"),
            Beat(0.30, pose="crouch", easing="ease_out", blend_in=0.24),
            Beat(0.80, pose="crouch"),
            Beat(0.42, pose="stand_relaxed", easing="ease_in_out", blend_in=0.34),
        ),
    ),
    Action(
        "sit",
        ("assis", "assoit", "asseoir", "sit", "seated"),
        (
            Beat(0.20, pose="stand_relaxed", easing="ease_out"),
            Beat(0.26, pose="crouch", easing="ease_in", blend_in=0.20),
            Beat(0.34, pose="sit", easing="ease_out", blend_in=0.26),
            Beat(1.20, pose="sit"),
        ),
    ),
    Action(
        "punch",
        ("poing", "punch", "frappe", "coup", "hit", "strike", "attaque", "attack"),
        (
            Beat(0.15, pose="stand_relaxed", easing="ease_out"),
            Beat(0.15, pose="punch_{side}_windup", easing="anticipate", blend_in=0.13),
            Beat(0.09, pose="punch_{side}_extend", easing="ease_out", blend_in=0.07),
            Beat(0.13, pose="punch_{side}_windup", easing="ease_in", blend_in=0.10),
            Beat(0.34, pose="stand_relaxed", easing="overshoot", blend_in=0.28),
        ),
        sided=True,
    ),
    Action(
        "point",
        ("pointe", "montre", "designe", "point", "indicate", "aim"),
        (
            Beat(0.18, pose="stand_relaxed", easing="ease_out"),
            Beat(0.26, pose="point_{side}", easing="overshoot", blend_in=0.22),
            Beat(0.65, pose="point_{side}"),
            Beat(0.38, pose="stand_relaxed", easing="ease_in_out", blend_in=0.30),
        ),
        sided=True,
    ),
    Action(
        "celebrate",
        ("celebr", "victoire", "gagne", "bravo", "cheer", "win", "yay", "hourra"),
        (
            Beat(0.14, pose="stand_relaxed", easing="ease_out"),
            Beat(0.12, pose="crouch", easing="anticipate", blend_in=0.10),
            Beat(0.18, pose="celebrate", easing="ease_out", blend_in=0.10),
            Beat(0.85, pose="celebrate"),
            Beat(0.42, pose="stand_relaxed", easing="overshoot", blend_in=0.34),
        ),
    ),
    Action(
        "back",
        ("recul", "step back", "backward", "retraite", "eloigne", "back away"),
        (
            Beat(0.14, pose="stand_relaxed", easing="ease_out"),
            Beat(0.20, pose="step_back", easing="ease_out", blend_in=0.16),
            Beat(0.30, pose="step_back"),
            Beat(0.36, pose="stand_relaxed", easing="ease_in_out", blend_in=0.28),
        ),
    ),
    Action(
        "flinch",
        ("encaisse", "encaisser", "flinch", "recoil", "tressaill", "titube", "stagger"),
        (
            # Impact reactions are almost all snap and recovery: the pose the
            # eye reads is held for a tenth of a second and then bleeds off.
            Beat(0.10, pose="stand_relaxed", easing="ease_out"),
            Beat(0.07, pose="flinch", easing="ease_out", blend_in=0.05),
            Beat(0.16, pose="flinch"),
            Beat(0.45, pose="stand_relaxed", easing="overshoot", blend_in=0.38),
        ),
    ),
    Action(
        "talk",
        ("parle", "discute", "talk", "speak", "explique", "raconte", "converse"),
        (Beat(2.6, cycle="talk"),),
        loopable=True,
        layers=(Layer("breathing", 0.5, 0.28),),
    ),
    Action(
        "nod",
        ("hoche", "acquiesce", "nod", "approuve"),
        (Beat(1.4, cycle="nod"),),
        loopable=True,
    ),
    Action(
        "shake_head",
        ("secoue la tete", "shake", "refuse", "nie ", "desapprouve"),
        (Beat(1.2, cycle="shake_head"),),
        loopable=True,
    ),
    Action(
        "t_pose",
        ("t-pose", "t pose", "tpose", "bras en croix"),
        (Beat(1.0, pose="t_pose", easing="ease_in_out"),),
        loopable=True,
    ),
)

#: Applied to every beat duration. Under 1 means faster.
SPEED_WORDS: tuple[tuple[tuple[str, ...], float], ...] = (
    (("tres vite", "very fast", "tres rapide"), 0.6),
    (("vite", "rapide", "rapidement", "fast", "quick", "sprint", "energique"), 0.75),
    (("lent", "lentement", "doucement", "slow", "slowly", "calme"), 1.45),
)

#: Applied to the plan's energy, which scales every pose's deviation from rest.
ENERGY_WORDS: tuple[tuple[tuple[str, ...], float], ...] = (
    (("explosif", "puissant", "violent", "enorme", "explosive", "powerful", "big"), 1.4),
    (("energique", "enthousiaste", "excite", "energetic", "excited"), 1.2),
    (("fatigue", "mou", "triste", "tired", "lazy", "sad", "weak", "subtle"), 0.75),
)

LOOP_WORDS = ("boucle", "loop", "looping", "en continu", "repeat", "cycle")
LEFT_WORDS = ("gauche", "left")
RIGHT_WORDS = ("droite", "droit", "right")
REPEAT_WORDS = {
    "deux": 2, "twice": 2, "2": 2, "trois": 3, "3": 3, "thrice": 3,
    "quatre": 4, "4": 4, "cinq": 5, "5": 5,
}


def normalize(text: str) -> str:
    """Lowercase and strip accents, so "célèbre" matches the stem "celebr"."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def plan_offline(prompt: str, *, fps: float = 30.0, name: str | None = None) -> MotionPlan:
    """Build a plan from ``prompt`` with no model and no network."""
    text = normalize(prompt)
    speed = _first_match(text, SPEED_WORDS, default=1.0)
    energy = _first_match(text, ENERGY_WORDS, default=1.0)
    side = _side(text)
    wants_loop = any(word in text for word in LOOP_WORDS)

    clauses = _split_clauses(text)
    matched: list[tuple[Action, int]] = []
    for clause in clauses:
        action = _match_action(clause)
        if action is not None:
            matched.append((action, _repeat_count(clause)))

    unmatched = not matched
    if unmatched:
        matched = [(_action("idle"), 1)]

    segments: list[Segment] = []
    cursor = 0.0
    for action, repeats in matched:
        for _ in range(repeats):
            cursor = _emit(action, side, speed, segments, cursor)

    # Looping only makes sense when nothing in the sequence is a one-shot that
    # would snap back at the seam.
    loop = wants_loop and all(action.loopable for action, _ in matched)
    priority = _priority(matched, loop)
    layers = list(matched[0][0].layers) or _default_layers(matched)

    plan = MotionPlan(
        name=name or _name(prompt, matched),
        segments=segments,
        fps=fps,
        loop=loop,
        priority=priority,
        layers=layers,
        energy=round(min(max(energy, 0.1), 2.0), 3),
        notes=_notes(matched, unmatched, prompt, speed, side),
    )
    plan.validate()
    return plan


def _emit(
    action: Action, side: str, speed: float, segments: list[Segment], cursor: float
) -> float:
    for beat in action.beats:
        duration = max(beat.duration * speed, 0.05)
        pose = beat.pose.format(side=side) if beat.pose else None
        cycle = beat.cycle.format(side=side) if beat.cycle else None
        rate = beat.rate
        if cycle is not None and rate is None and speed != 1.0:
            # A cycle stretches by playing slower, not by lasting longer.
            from .posebook import CYCLES

            rate = round(CYCLES[cycle].default_rate / speed, 3)
        segments.append(
            Segment(
                start=round(cursor, 4),
                end=round(cursor + duration, 4),
                pose=pose,
                cycle=cycle,
                rate=rate,
                easing=beat.easing,
                blend_in=round(min(beat.blend_in * speed, duration), 4),
            )
        )
        cursor += duration
    return cursor


def _split_clauses(text: str) -> list[str]:
    pattern = "|".join(re.escape(sep) for sep in sorted(SEPARATORS, key=len, reverse=True))
    parts = [part.strip() for part in re.split(rf"\b(?:{pattern})\b|[,;.]", text)]
    return [part for part in parts if part]


def _match_action(clause: str) -> Action | None:
    """The action whose keyword appears earliest in the clause.

    Earliest rather than longest: in "cours puis saute", each clause has one
    verb, but a clause like "un salut avant de courir" should take the verb the
    sentence leads with.
    """
    best: tuple[int, Action] | None = None
    for action in ACTIONS:
        for keyword in action.keywords:
            found = re.search(rf"\b{re.escape(keyword)}", clause)
            if found and (best is None or found.start() < best[0]):
                best = (found.start(), action)
    return best[1] if best else None


def _repeat_count(clause: str) -> int:
    for word, count in REPEAT_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", clause):
            return count
    return 1


def _side(text: str) -> str:
    if any(word in text for word in LEFT_WORDS):
        return "left"
    if any(word in text for word in RIGHT_WORDS):
        return "right"
    return "right"


def _first_match(
    text: str, table: tuple[tuple[tuple[str, ...], float], ...], default: float
) -> float:
    for words, value in table:
        if any(word in text for word in words):
            return value
    return default


def _priority(matched: list[tuple[Action, int]], loop: bool) -> str:
    priorities = {action.priority for action, _ in matched}
    if priorities == {"Idle"}:
        return "Idle"
    if priorities <= {"Idle", "Movement"} and loop:
        return "Movement"
    return "Action"


def _default_layers(matched: list[tuple[Action, int]]) -> list[Layer]:
    # Locomotion carries its own motion; anything else would look frozen during
    # its holds without a little breathing under it.
    if all(action.priority == "Movement" for action, _ in matched):
        return []
    return [Layer("breathing", 0.45, 0.3)]


def _name(prompt: str, matched: list[tuple[Action, int]]) -> str:
    return "".join(action.name.replace("_", "").capitalize() for action, _ in matched)


def _notes(
    matched: list[tuple[Action, int]],
    unmatched: bool,
    prompt: str,
    speed: float,
    side: str,
) -> str:
    if unmatched:
        from .posebook import cycle_names

        return (
            f"Offline planner recognised nothing in {prompt!r} and fell back to an "
            f"idle. It matches keywords, not meaning — try naming an action: "
            f"{', '.join(a.name for a in ACTIONS)} (cycles: {', '.join(cycle_names())})."
        )
    sequence = " -> ".join(
        action.name if repeats == 1 else f"{action.name} x{repeats}"
        for action, repeats in matched
    )
    parts = [f"Offline planner: {sequence}"]
    if speed != 1.0:
        parts.append(f"timing x{speed}")
    if any(action.sided for action, _ in matched):
        parts.append(f"{side} side")
    return ", ".join(parts) + "."


def _action(name: str) -> Action:
    for action in ACTIONS:
        if action.name == name:
            return action
    raise KeyError(name)


def action_names() -> tuple[str, ...]:
    return tuple(action.name for action in ACTIONS)
