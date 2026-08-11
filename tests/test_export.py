from __future__ import annotations

from xml.etree import ElementTree as ET

import numpy as np
import pytest

from linen.clip import AnimationClip
from linen.export import build_keyframe_sequence, reduce_keyframes, write_rbxmx
from linen.math3d import euler_degrees_to_quat
from linen.rigs import R6, R15


def ramp_clip(rig=R15, frames: int = 60, part: str = "LeftUpperArm") -> AnimationClip:
    clip = AnimationClip.rest(rig, frames, fps=30.0, name="Ramp")
    angles = np.zeros((frames, 3))
    angles[:, 0] = np.linspace(0.0, 90.0, frames)
    clip.rotations[part] = euler_degrees_to_quat(angles)
    return clip


def test_pose_tree_mirrors_the_rig_hierarchy():
    tree = build_keyframe_sequence(ramp_clip(), frames=[0])
    keyframe = tree.getroot().find("Item").find("Item")
    root_pose = keyframe.find("Item")

    assert _name(root_pose) == "HumanoidRootPart"
    children = {_name(item) for item in root_pose.findall("Item")}
    assert children == {"LowerTorso"}

    lower = root_pose.find("Item")
    assert {_name(item) for item in lower.findall("Item")} == {
        "UpperTorso",
        "LeftUpperLeg",
        "RightUpperLeg",
    }


def test_every_part_gets_exactly_one_pose_per_keyframe():
    tree = build_keyframe_sequence(ramp_clip(), frames=[0, 10, 20])
    keyframes = tree.getroot().find("Item").findall("Item")
    assert len(keyframes) == 3
    for keyframe in keyframes:
        poses = [item for item in keyframe.iter("Item") if item.get("class") == "Pose"]
        assert len(poses) == len(R15.parts)


def test_referents_are_unique():
    tree = build_keyframe_sequence(ramp_clip(), frames=[0, 5])
    referents = [item.get("referent") for item in tree.getroot().iter("Item")]
    assert len(referents) == len(set(referents))


def test_r6_uses_its_own_part_and_joint_names():
    tree = build_keyframe_sequence(ramp_clip(R6, part="Left Arm"), frames=[0])
    names = {
        _name(item) for item in tree.getroot().iter("Item") if item.get("class") == "Pose"
    }
    assert names == {p.name for p in R6.parts}
    assert "Left Arm" in names


def test_priority_and_loop_are_written_as_roblox_expects():
    clip = ramp_clip()
    clip.loop = True
    clip.priority = "Idle"
    root = build_keyframe_sequence(clip, frames=[0]).getroot()
    properties = root.find("Item").find("Properties")
    assert properties.find("bool[@name='Loop']").text == "true"
    assert properties.find("token[@name='Priority']").text == "0"


def test_unknown_priority_is_rejected():
    clip = ramp_clip()
    clip.priority = "Urgent"
    with pytest.raises(ValueError, match="unknown priority"):
        build_keyframe_sequence(clip, frames=[0])


def test_keyframe_times_follow_the_frame_rate():
    tree = build_keyframe_sequence(ramp_clip(), frames=[0, 15, 30])
    times = [
        float(item.find("Properties").find("float[@name='Time']").text)
        for item in tree.getroot().find("Item").findall("Item")
    ]
    assert times == pytest.approx([0.0, 0.5, 1.0])


def test_reduction_keeps_only_the_ends_of_a_still_clip():
    still = AnimationClip.rest(R15, 120, fps=60.0)
    assert reduce_keyframes(still) == [0, 119]


def test_reduction_keeps_the_extremes_of_a_swing():
    frames = 61
    clip = AnimationClip.rest(R15, frames, fps=30.0)
    angles = np.zeros((frames, 3))
    # Up and back down: the peak at the midpoint is exactly what a naive
    # every-Nth-frame decimation would be free to miss.
    angles[:, 0] = 90.0 * np.sin(np.linspace(0.0, np.pi, frames))
    clip.rotations["LeftUpperArm"] = euler_degrees_to_quat(angles)

    kept = reduce_keyframes(clip, angular_tolerance_deg=1.0)
    assert 2 < len(kept) < frames
    assert min(abs(k - 30) for k in kept) <= 1


def test_a_constant_rate_turn_needs_no_interior_keyframes():
    # Roblox slerps between poses, and a constant-rate turn *is* a slerp, so
    # keeping any interior frame would be pure file size.
    assert reduce_keyframes(ramp_clip(frames=120)) == [0, 119]


def test_reduction_respects_its_tolerance():
    frames = 120
    clip = AnimationClip.rest(R15, frames, fps=30.0)
    angles = np.zeros((frames, 3))
    eased = np.linspace(0.0, 1.0, frames)
    angles[:, 0] = 90.0 * eased * eased * (3.0 - 2.0 * eased)
    clip.rotations["LeftUpperArm"] = euler_degrees_to_quat(angles)

    loose = reduce_keyframes(clip, angular_tolerance_deg=10.0)
    tight = reduce_keyframes(clip, angular_tolerance_deg=0.1)
    assert len(loose) < len(tight) <= frames


def test_written_file_parses_and_declares_the_roblox_schema(tmp_path):
    path = write_rbxmx(ramp_clip(), tmp_path / "nested" / "swing.rbxmx")
    assert path.exists()
    root = ET.parse(path).getroot()
    assert root.tag == "roblox"
    assert root.get("version") == "4"
    assert root.find("Item").get("class") == "KeyframeSequence"


def test_every_written_cframe_is_a_proper_rotation():
    # Studio accepts a malformed matrix without complaint and then renders a
    # sheared limb, so the check has to happen on this side.
    tree = build_keyframe_sequence(ramp_clip(), frames=[0, 20, 40, 59])
    for element in tree.getroot().iter("CoordinateFrame"):
        values = [float(element.find(tag).text) for tag in _CFRAME_TAGS]
        matrix = np.array(values[3:]).reshape(3, 3)
        assert np.allclose(matrix @ matrix.T, np.eye(3), atol=1e-5)
        assert np.linalg.det(matrix) == pytest.approx(1.0, abs=1e-5)


def test_non_finite_rotations_are_refused():
    clip = ramp_clip()
    clip.rotations["LeftUpperArm"][5] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        build_keyframe_sequence(clip, frames=[5])


_CFRAME_TAGS = (
    "X", "Y", "Z",
    "R00", "R01", "R02",
    "R10", "R11", "R12",
    "R20", "R21", "R22",
)


def _name(item: ET.Element) -> str:
    return item.find("Properties").find("string[@name='Name']").text
