"""The generated Luau has to be structurally sound, and nothing else checks it.

Every other test on the scene script greps it for substrings. A missing `end`,
an unbalanced brace, or a table the body iterates but the generator forgot to
emit would all pass those and then fail in Studio — as a syntax error nobody
sees until they paste it, or as "attempt to iterate over a nil value" halfway
through a cinematic.

There is no Luau parser here, so this checks the properties a parser would
catch first, on real generated output rather than on a fixture.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from linen.scene import Scene, build_scene, write_scene_script

RUNTIME = Path(__file__).resolve().parent.parent / "runtime"

#: Globals Roblox provides. Everything else in SHOUTING_CASE that the body
#: uses must be a table this generator actually wrote.
PROVIDED = {"CFrame", "TweenInfo", "Vector3", "Enum", "Instance", "UDim2", "UDim", "Color3"}


def _strip(source: str) -> str:
    """Comments and string literals out, so keywords inside them do not count."""
    without = re.sub(r"--\[\[.*?\]\]", " ", source, flags=re.DOTALL)
    without = re.sub(r"--[^\n]*", " ", without)
    without = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', without)
    without = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", without)
    return re.sub(r"`(?:[^`\\]|\\.)*`", "``", without)


def blocks(source: str) -> tuple[int, int]:
    """How many blocks open, and how many `end` close them.

    Luau's `if cond then a else b` is an *expression* and takes no `end`, so
    those are counted out — a naive count reads ten of them as ten missing
    `end`s and cries wolf on a file that is perfectly balanced.
    """
    body = _strip(source)
    expression_ifs = len(re.findall(r"(?:[=(,]|\breturn\b)\s*\bif\b", body))
    statement_ifs = len(re.findall(r"\bif\b", body)) - expression_ifs
    opened = len(re.findall(r"\b(?:function|for|while)\b", body)) + statement_ifs
    return opened, len(re.findall(r"\bend\b", body))


def _scene() -> Scene:
    return Scene.from_dict(
        {
            "name": "Complete",
            "actors": [
                {"name": "Hero", "rig": "R15", "position": [0, 2.44, 0], "facing": "Enemy"},
                {"name": "Enemy", "rig": "R15", "position": [0, 2.44, -6], "facing": "Hero"},
            ],
            "props": [
                {"name": "Couteau", "source": "ReplicatedStorage.Couteau", "held_by": "Enemy"}
            ],
            "cues": [
                {"id": "walk", "actor": "Enemy", "at": 0.0, "prompt": "marche",
                 "duration": 1.5, "move_to": "Hero", "stop_at": 1.5},
                {"id": "hit", "actor": "Enemy", "after": "walk", "prompt": "coup de poing"},
                {"id": "wait", "actor": "Hero", "at": 0.0, "prompt": "il reste immobile",
                 "duration": 1.5},
                {"id": "take", "actor": "Hero", "after": "wait", "prompt": "il encaisse"},
            ],
            "shots": [
                {"id": "wide", "position": [7, 4, 4], "look_at": "Hero"},
                {"id": "turn", "position": [6, 4, 3], "look_at": "Enemy", "kind": "orbit",
                 "orbit_speed": 25.0},
                {"id": "chase", "position": [4, 4, 3], "look_at": "Hero", "kind": "follow"},
            ],
            "events": [
                {"kind": "camera", "shot": "wide", "cue": "walk"},
                {"kind": "camera", "shot": "turn", "cue": "hit"},
                {"kind": "camera", "shot": "chase", "cue": "take"},
                {"kind": "face", "actor": "Enemy", "cue": "hit", "expression": "angry"},
                {"kind": "face", "actor": "Hero", "cue": "take", "expression": "pain"},
                {"kind": "line", "actor": "Enemy", "cue": "hit", "text": "Tu peux rien faire"},
                {"kind": "vfx", "cue": "hit", "effect": "Impact"},
                {"kind": "prop", "prop": "Couteau", "action": "release", "actor": "Enemy",
                 "cue": "hit"},
                {"kind": "contact", "actor": "Enemy", "cue": "hit", "limb": "RightHand",
                 "hold": 0.2, "target_actor": "Hero", "target_part": "Head"},
            ],
        }
    )


@pytest.fixture(scope="module")
def script(tmp_path_factory) -> str:
    """One scene exercising every kind at once, generated for real."""
    built = build_scene(_scene(), planner="offline")
    out = tmp_path_factory.mktemp("luau") / "Complete.client.luau"
    return write_scene_script(built, out).read_text()


def test_every_block_is_closed(script):
    opened, closed = blocks(script)
    assert opened == closed, f"{opened} blocks opened, {closed} closed"


@pytest.mark.parametrize("pair", [("(", ")"), ("{", "}"), ("[", "]")])
def test_the_brackets_balance(script, pair):
    body = _strip(script)
    left, right = pair
    assert body.count(left) == body.count(right), f"{left}{right}"


def test_every_table_the_body_uses_is_one_the_generator_wrote(script):
    """A table referenced but never emitted fails as "attempt to iterate over a
    nil value", halfway through a cinematic, in Studio."""
    body = _strip(script)
    used = set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", body))
    declared = set(re.findall(r"\blocal\s+([A-Z][A-Z0-9_]{2,})", body))
    missing = used - declared - PROVIDED
    assert not missing, f"used but never declared: {sorted(missing)}"


def test_the_tables_this_scene_needs_are_all_there(script):
    for table in ("STAGE", "CUES", "SHOTS", "DIRECTOR", "MOVES", "FACES", "ANIMATION_IDS"):
        assert f"local {table}" in script, table


def test_nothing_is_left_as_a_template_placeholder(script):
    """A `{name}` that never got substituted is a syntax error in Luau."""
    for leftover in ("__", "{name}", "{folder}", "None", "nan"):
        assert leftover not in script, leftover


def test_the_checked_in_runtime_modules_are_balanced_too():
    for path in sorted(RUNTIME.glob("*.luau")):
        opened, closed = blocks(path.read_text())
        assert opened == closed, f"{path.name}: {opened} opened, {closed} closed"


def test_the_moon_installer_is_balanced(tmp_path):
    """It is Luau too, and nothing else looks at its shape."""
    import numpy as np

    from linen.clip import IDENTITY_QUAT, AnimationClip
    from linen.export.moon import write_moon
    from linen.rigs import get_rig

    rig = get_rig("R15")
    clip = AnimationClip(
        rig=rig,
        fps=30.0,
        rotations={p: np.tile(IDENTITY_QUAT, (4, 1)) for p in rig.animated_parts},
        name="Petit",
    )
    path = write_moon(clip, tmp_path / "petit.moon.rbxmx")
    tree = ET.parse(path)
    luau = [
        node.text or ""
        for node in tree.getroot().iter("ProtectedString")
        if node.get("name") == "Source"
    ]
    assert luau, "the installer script went missing from the Moon save"
    for chunk in luau:
        opened, closed = blocks(chunk)
        assert opened == closed, f"{opened} opened, {closed} closed"
