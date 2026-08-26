"""The files shipped in `examples/` must agree with each other.

Every demo is a pair: a `.html` you look at, and a `.rbxmx` you import. The
whole point of looking first is that the page tells you what Studio will do —
which only holds if the two carry the same motion. They are generated together
today, so nothing stops one half from being regenerated without the other.
This is what catches that.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from linen.math3d import quat_to_mat

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# The two files write rotations in different forms and at different precisions
# — quaternions at five decimals in the page, a rotation matrix at six in the
# file — so they cannot agree to the bit. A tenth of a degree is invisible and
# well under any real mistake.
TOLERANCE_DEGREES = 0.1


def _page(path: Path) -> dict:
    text = path.read_text()
    match = re.search(r"const DATA = (\{.*?\});\n", text, re.DOTALL)
    assert match is not None, f"{path.name} carries no animation payload"
    return json.loads(match.group(1))


def _keyframes(path: Path) -> list[tuple[float, dict[str, np.ndarray]]]:
    root = ET.parse(path).getroot()
    frames = []
    for keyframe in (i for i in root.iter("Item") if i.get("class") == "Keyframe"):
        time = float(keyframe.find("Properties/float[@name='Time']").text)
        poses = {}
        for pose in (i for i in keyframe.iter("Item") if i.get("class") == "Pose"):
            name = pose.find("Properties/string[@name='Name']").text
            cframe = pose.find("Properties/CoordinateFrame[@name='CFrame']")
            poses[name] = np.array(
                [[float(cframe.find(f"R{r}{c}").text) for c in range(3)] for r in range(3)]
            )
        frames.append((time, poses))
    return frames


# One folder holds animations that were never meant to be looked at here:
# `R15_converties` is a game's own R6 animations converted to R15, on request,
# with their original names and nothing else beside them. A conversion has no
# page because there is nothing to preview that the game does not already have.
# The pairing promise below is about what this project publishes as a demo.
UNPAIRED = {"R15_converties"}


def _keyframe_sequences() -> list[Path]:
    """Every shipped `.rbxmx` that holds an animation, not a set of parts."""
    found = []
    for path in sorted(EXAMPLES.rglob("*.rbxmx")):
        first = ET.parse(path).getroot().find("Item")
        if first is not None and first.get("class") == "KeyframeSequence":
            found.append(path)
    return found


def _animations() -> list[Path]:
    """The animations this project ships to be looked at before importing."""
    return [p for p in _keyframe_sequences() if p.parent.name not in UNPAIRED]


def _converted() -> list[Path]:
    """The animations converted for someone else's game, which ship alone."""
    return [p for p in _keyframe_sequences() if p.parent.name in UNPAIRED]


def _page_for(rbxmx: Path) -> tuple[Path, str | None]:
    """The page that shows this file, and which actor in it, if several.

    Two shapes ship: `Walk.rbxmx` beside `Walk.html`, and a cinematic's
    `Disarm_Hero.rbxmx` beside the one `Disarm.html` that plays the whole cast.
    """
    same = rbxmx.with_suffix(".html")
    if same.exists():
        return same, None
    scene, _, actor = rbxmx.stem.rpartition("_")
    page = rbxmx.with_name(f"{scene}.html")
    assert page.exists(), f"{rbxmx.name} has no page beside it — look before you import"
    return page, actor


def test_every_shipped_animation_has_a_page() -> None:
    animations = _animations()
    assert len(animations) >= 10, "the shipped examples went missing"
    for path in animations:
        _page_for(path)


@pytest.mark.parametrize("rbxmx", _animations(), ids=lambda p: p.stem)
def test_the_file_moves_like_the_page_beside_it(rbxmx: Path) -> None:
    page_path, actor_name = _page_for(rbxmx)
    page = _page(page_path)
    actors = page["actors"]
    if actor_name is None:
        actor = actors[0]
    else:
        actor = next((a for a in actors if a["name"] == actor_name), None)
        assert actor is not None, f"{page_path.name} shows no actor named {actor_name!r}"

    fps = page["fps"]
    rotations = {
        part: np.asarray(track, dtype=float).reshape(-1, 4)
        for part, track in actor["rotations"].items()
    }

    worst = 0.0
    compared = 0
    for time, poses in _keyframes(rbxmx):
        frame = round(time * fps)
        for part, matrix in poses.items():
            track = rotations.get(part)
            if track is None:  # the root carries no rotation of its own
                continue
            assert frame < len(track), f"{rbxmx.name} runs past the page at {time:.2f}s"
            expected = quat_to_mat(track[frame][None])[0]
            cosine = (np.trace(expected.T @ matrix) - 1.0) / 2.0
            worst = max(worst, float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))))
            compared += 1

    assert compared > 0, f"{rbxmx.name} and {page_path.name} share no joint"
    assert worst < TOLERANCE_DEGREES, (
        f"{rbxmx.name} is {worst:.2f} deg off {page_path.name} — one of the two "
        f"was regenerated without the other"
    )


def _pose_parents(path: Path) -> dict[str, str | None]:
    """Every posed joint in the file, and the joint it hangs from.

    Roblox reads a `Keyframe` as a tree: a `Pose` rotates the joint between
    itself and its parent. A pose in the wrong place turns the wrong joint.
    """
    root = ET.parse(path).getroot()
    parents: dict[str, str | None] = {}

    def walk(item: ET.Element, above: str | None) -> None:
        for child in item.findall("Item"):
            if child.get("class") != "Pose":
                continue
            name = child.find("Properties/string[@name='Name']").text
            parents[name] = above
            walk(child, name)

    for keyframe in (i for i in root.iter("Item") if i.get("class") == "Keyframe"):
        walk(keyframe, None)
    return parents


@pytest.mark.parametrize("rbxmx", _converted(), ids=lambda p: p.stem)
def test_a_converted_animation_hangs_its_joints_where_an_r15_rig_does(rbxmx: Path) -> None:
    """A conversion has no page, so this is what stands in for looking at it.

    Studio does not complain about a joint that does not exist on the rig, nor
    about one hung in the wrong place — it plays what it can and quietly drops
    the rest. Either way the limb stops moving and nothing says why.
    """
    from linen.rigs import get_rig

    rig = {part.name: part.parent for part in get_rig("R15").parts}
    hands = {"LeftHand", "RightHand"}

    frames = _keyframes(rbxmx)
    assert frames, f"{rbxmx.name} carries no keyframe"

    parents = _pose_parents(rbxmx)
    for name, parent in parents.items():
        if name in rig:
            assert parent == rig[name], (
                f"{rbxmx.name} hangs {name} from {parent!r}, an R15 rig hangs it "
                f"from {rig[name]!r}"
            )
            continue
        # Anything else is a held Tool: on Roblox the Handle is welded to the
        # hand and the source animation moved it, so it is carried, not
        # invented. A Tool can be several parts deep — a blade on a handle —
        # so what matters is that the hand is somewhere above it.
        held, seen = parent, {name}
        while held is not None and held not in hands and held not in seen:
            seen.add(held)
            held = parents.get(held)
        assert held in hands, (
            f"{rbxmx.name} poses {name!r} under {parent!r} — no R15 joint has "
            f"that name and no hand holds it"
        )

    assert set(parents) & set(rig), f"{rbxmx.name} poses nothing an R15 rig would move"

    times = [time for time, _ in frames]
    assert times == sorted(times), f"{rbxmx.name} has its keyframes out of order"
