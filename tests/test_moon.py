"""Exporting a clip as a Moon Animator 2 save.

What can be checked here is the shape of what gets written and the arithmetic
the generated script performs. What cannot is Studio: whether Moon Animator
opens the result is a question only Moon Animator answers, and nothing in this
file pretends otherwise.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from linen.clip import AnimationClip
from linen.export.moon import (
    build_moon_save,
    moon_module,
    moon_payload,
    write_moon,
)
from linen.rigs import get_rig


def _spin(frames: int = 60, fps: float = 30.0) -> AnimationClip:
    """A rig turning its head steadily — enough motion to keep keyframes."""
    rig = get_rig("R15")
    rotations = {}
    for part in (p.name for p in rig.parts if p.name != "HumanoidRootPart"):
        rotations[part] = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (frames, 1))

    angles = np.linspace(0.0, np.pi / 2, frames)
    rotations["Head"] = np.stack(
        [np.zeros(frames), np.sin(angles / 2), np.zeros(frames), np.cos(angles / 2)],
        axis=1,
    )
    return AnimationClip(rig=rig, fps=fps, rotations=rotations, name="Tourne")


def test_the_payload_carries_every_animated_part():
    payload = moon_payload(_spin())
    assert "Head" in payload["tracks"]
    assert payload["tracks"]["Head"], "the part that moves has no keys"
    assert payload["name"] == "Tourne"


def test_keys_are_reduced_rather_than_one_per_frame():
    """A wall of keys is not an animation anyone can edit.

    This is the reason the export exists at all: opening a capture in Moon
    Animator is only useful if the timeline can be worked on afterwards.
    """
    clip = _spin(frames=120)
    payload = moon_payload(clip)
    assert len(payload["tracks"]["Head"]) < clip.frame_count / 2


def test_frames_land_on_the_moon_grid():
    """A 30 fps clip written at 60 fps has its keys at twice the index."""
    clip = _spin(frames=60, fps=30.0)
    slow = moon_payload(clip)
    fast = moon_payload(clip, fps=60.0)
    assert fast["fps"] == 60.0
    assert fast["length"] == pytest.approx(slow["length"] * 2, abs=1)


def test_frames_are_ordered_and_start_at_zero():
    for keys in moon_payload(_spin())["tracks"].values():
        indices = [frame for frame, _ in keys]
        assert indices[0] == 0
        assert indices == sorted(indices)
        assert len(set(indices)) == len(indices), "two keys on one frame"


def test_a_slower_grid_never_stacks_two_keys_on_one_frame():
    """Rounding 120 source frames onto 30 Moon frames collides by definition."""
    clip = _spin(frames=240, fps=120.0)
    for keys in moon_payload(clip, fps=30.0)["tracks"].values():
        indices = [frame for frame, _ in keys]
        assert len(set(indices)) == len(indices)


def test_the_module_is_a_luau_table_naming_the_clip():
    source = moon_module(moon_payload(_spin()))
    assert source.startswith("--!strict")
    assert '"Tourne"' in source
    assert "Tracks = {" in source
    assert '["Head"] = {' in source


def test_the_save_is_a_folder_holding_the_motion_and_its_installer(tmp_path):
    path = write_moon(_spin(), tmp_path / "take.moon.rbxmx")
    root = ET.parse(path).getroot()

    top = root.find("Item")
    assert top.get("class") == "Folder"

    children = {
        item.find("Properties/string[@name='Name']").text: item
        for item in top.findall("Item")
    }
    assert set(children) == {"Motion", "InstallerLinen"}
    assert children["Motion"].get("class") == "ModuleScript"
    assert children["InstallerLinen"].get("class") == "Script"

    for item in children.values():
        source = item.find("Properties/ProtectedString[@name='Source']")
        assert source is not None and source.text.strip()


def test_the_installer_names_the_clip_it_installs():
    tree = build_moon_save(_spin())
    sources = [
        element.text
        for element in tree.getroot().iter("ProtectedString")
        if element.get("name") == "Source"
    ]
    installer = next(text for text in sources if "MoonAnimator2Saves" in text)
    assert "Tourne" in installer
    assert "HttpService:JSONEncode" in installer


def test_the_installer_only_writes_where_it_says_it_does():
    """It creates instances in someone's place. It should touch one place."""
    tree = build_moon_save(_spin())
    installer = next(
        element.text
        for element in tree.getroot().iter("ProtectedString")
        if element.get("name") == "Source" and "MoonAnimator2Saves" in element.text
    )
    for service in ("ReplicatedStorage", "StarterPlayer", "Workspace:", "Lighting"):
        assert f"game:GetService(\"{service}\")" not in installer


# --- the arithmetic the installer performs ----------------------------------
#
# Moon stores a joint's *animated C1*, not the transform an animation applies.
# Its reader recovers the transform as `c1:Inverse() * default`, so the writer
# has to store `default * transform:Inverse()`. Getting that backwards produces
# a rig that is subtly and consistently wrong, which is exactly the kind of
# mistake that survives a visual check.


def _random_transform(seed: int) -> np.ndarray:
    generator = np.random.default_rng(seed)
    basis, _ = np.linalg.qr(generator.normal(size=(3, 3)))
    if np.linalg.det(basis) < 0:
        basis[:, 0] *= -1.0
    matrix = np.eye(4)
    matrix[:3, :3] = basis
    matrix[:3, 3] = generator.normal(size=3)
    return matrix


@pytest.mark.parametrize("seed", range(8))
def test_storing_the_animated_c1_round_trips_to_the_transform(seed):
    default = _random_transform(seed)
    transform = _random_transform(seed + 100)

    stored = default @ np.linalg.inv(transform)      # what the installer writes
    recovered = np.linalg.inv(stored) @ default      # what Moon's reader does

    assert np.allclose(recovered, transform, atol=1e-9)


def test_the_installer_writes_that_expression_and_not_its_inverse():
    tree = build_moon_save(_spin())
    installer = next(
        element.text
        for element in tree.getroot().iter("ProtectedString")
        if element.get("name") == "Source" and "MoonAnimator2Saves" in element.text
    )
    assert "default * transform:Inverse()" in installer


# --- strict-mode defects, locked in -----------------------------------------
#
# Each of these was a real type error found by running luau-lsp over the
# generated files with the Roblox API definitions loaded. Without those
# definitions every Vector3 subtraction also reports as an error, which is what
# hid them: 292 errors in the generated Luau, of which 6 were real.


def test_keys_are_named_rather_than_positional():
    """A mixed array infers as the type of its first element.

    ``{0, {…12 numbers…}}`` came back as 285 type errors — one per key — because
    the second entry is not a number. Named fields cost a few bytes and make the
    installer read as ``key.frame`` instead of ``key[1]``.
    """
    source = moon_module(moon_payload(_spin()))
    assert "export type Key = { frame: number, cframe: { number } }" in source
    assert "frame = 0, cframe = {" in source


def _installer() -> str:
    tree = build_moon_save(_spin())
    return next(
        element.text
        for element in tree.getroot().iter("ProtectedString")
        if element.get("name") == "Source" and "MoonAnimator2Saves" in element.text
    )


def test_the_motor_lookup_is_optional_and_guarded_without_comparing():
    """``{[string]: Motor6D}`` makes ``motor == nil`` itself a type error.

    Strict Luau refuses to compare a non-optional Motor6D against nil, so the
    map has to admit that a part may be missing — which it is, on any rig that
    does not have every part Linen animates.
    """
    installer = _installer()
    assert "{ [string]: Motor6D? }" in installer
    assert "if not motor then" in installer
    assert "motor == nil" not in installer


def test_the_script_asserts_its_own_folder_before_reading_through_it():
    """``script.Parent`` is ``Instance?``, and this one is run by hand."""
    installer = _installer()
    assert "assert(script.Parent" in installer
