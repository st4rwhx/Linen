"""Reading Roblox's binary model format, and moving an R6 animation to R15.

The fixtures here build a ``.rbxm`` byte by byte, so what the reader should
find is known before it runs. That matters more than usual: the format stores
property arrays column-wise and transformed, and read naively it decodes to
plausible-looking noise rather than to an error — which is why the checks below
are on the *values*, not on whether parsing completed.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from linen.convert import R6_TO_R15, ConvertError, classify, convert_file
from linen.sources.rbxm import MAGIC, RbxmError, lz4_decompress, read_rbxm


def _interleave(values: list[int]) -> bytes:
    """Column-major bytes, the layout the format stores arrays in."""
    raw = [struct.pack(">I", value) for value in values]
    return bytes(row[position] for position in range(4) for row in raw)


def _zigzag(values: list[int]) -> bytes:
    return _interleave([(value << 1) ^ (value >> 31) for value in values])


def _rotate_floats(values: list[float]) -> bytes:
    packed = [struct.unpack(">I", struct.pack(">f", value))[0] for value in values]
    return _interleave([((value << 1) | (value >> 31)) & 0xFFFFFFFF for value in packed])


def _chunk(name: bytes, payload: bytes) -> bytes:
    return name + struct.pack("<III", 0, len(payload), 0) + payload


def _text(value: str) -> bytes:
    data = value.encode("utf8")
    return struct.pack("<I", len(data)) + data


def _inst(index: int, class_name: str, referents: list[int]) -> bytes:
    return _chunk(
        b"INST",
        struct.pack("<I", index)
        + _text(class_name)
        + b"\x00"
        + struct.pack("<I", len(referents))
        + _zigzag(_deltas(referents)),
    )


def _deltas(values: list[int]) -> list[int]:
    out, previous = [], 0
    for value in values:
        out.append(value - previous)
        previous = value
    return out


def _prop_string(index: int, name: str, values: list[str]) -> bytes:
    return _chunk(
        b"PROP",
        struct.pack("<I", index) + _text(name) + b"\x01" + b"".join(_text(v) for v in values),
    )


def _prop_float(index: int, name: str, values: list[float]) -> bytes:
    return _chunk(
        b"PROP", struct.pack("<I", index) + _text(name) + b"\x04" + _rotate_floats(values)
    )


def _prop_bool(index: int, name: str, values: list[bool]) -> bytes:
    return _chunk(
        b"PROP",
        struct.pack("<I", index)
        + _text(name)
        + b"\x02"
        + bytes(1 if v else 0 for v in values),
    )


def _prop_cframe(index: int, name: str, frames: list[tuple[np.ndarray, tuple]]) -> bytes:
    body = b""
    for rotation, _ in frames:
        body += b"\x00" + struct.pack("<9f", *np.asarray(rotation).reshape(-1))
    for axis in range(3):
        body += _rotate_floats([float(position[axis]) for _, position in frames])
    return _chunk(b"PROP", struct.pack("<I", index) + _text(name) + b"\x10" + body)


def _prnt(pairs: list[tuple[int, int]]) -> bytes:
    children = [child for child, _ in pairs]
    parents = [parent for _, parent in pairs]
    return _chunk(
        b"PRNT",
        b"\x00" + struct.pack("<I", len(pairs)) + _zigzag(_deltas(children)) + _zigzag(_deltas(parents)),
    )


def _pitch(degrees: float) -> np.ndarray:
    angle = np.radians(degrees)
    cos, sin = np.cos(angle), np.sin(angle)
    return np.array([[1.0, 0.0, 0.0], [0.0, cos, -sin], [0.0, sin, cos]])


def write_rbxm(path, *, parts=("Torso", "Left Arm"), angles=(0.0, 30.0), loop=True) -> None:
    """A one-keyframe R6 animation, built by hand.

    ``HumanoidRootPart`` roots the pose tree, the named parts hang off the
    torso, and each carries a known rotation about X.
    """
    poses = ["HumanoidRootPart", *parts]
    # referents: 0 sequence, 1 keyframe, 2.. poses
    pose_refs = list(range(2, 2 + len(poses)))

    body = b"".join(
        [
            _inst(0, "KeyframeSequence", [0]),
            _inst(1, "Keyframe", [1]),
            _inst(2, "Pose", pose_refs),
            _prop_string(0, "Name", ["Take"]),
            _prop_bool(0, "Loop", [loop]),
            _prop_string(1, "Name", ["Keyframe"]),
            _prop_float(1, "Time", [0.0]),
            _prop_string(2, "Name", poses),
            _prop_cframe(
                2,
                "CFrame",
                [(np.eye(3), (0.0, 0.0, 0.0))]
                + [(_pitch(angle), (0.0, 0.0, 0.0)) for angle in angles],
            ),
            _prnt(
                [(0, -1), (1, 0), (pose_refs[0], 1)]
                # Everything hangs off HumanoidRootPart, which is where an R6
                # keyframe roots its tree.
                + [(ref, pose_refs[0]) for ref in pose_refs[1:]]
            ),
            _chunk(b"END\x00", b"</roblox>"),
        ]
    )
    header = MAGIC + struct.pack("<II", 3, 2 + len(poses)) + b"\x00" * 8
    path.write_bytes(header + body)


# --- the reader -------------------------------------------------------------


def test_lz4_handles_an_overlapping_back_reference():
    """The copy has to be a loop: a match may read what it is still writing.

    Sliced instead, a run-length repeat comes back truncated and silently
    wrong rather than raising.
    """
    # literal "ab", then a match of length 6 at offset 2 -> "ababababa"
    block = bytes([0x22, ord("a"), ord("b"), 0x02, 0x00])
    assert lz4_decompress(block, 8) == b"abababab"


def test_something_that_is_not_a_binary_model_says_so(tmp_path):
    path = tmp_path / "take.rbxm"
    path.write_bytes(b"<roblox version=\"4\">")
    with pytest.raises(RbxmError, match="not a binary Roblox model"):
        read_rbxm(path)


def test_the_tree_comes_back_with_its_names_and_hierarchy(tmp_path):
    path = tmp_path / "take.rbxm"
    write_rbxm(path)
    roots = read_rbxm(path)
    assert len(roots) == 1
    sequence = roots[0]
    assert sequence.class_name == "KeyframeSequence"
    assert sequence.name == "Take"
    assert sequence.properties["Loop"] is True
    assert next(pose.name for pose in sequence.of_class("Pose")) == "HumanoidRootPart"


def test_the_rotations_decode_to_the_angles_that_were_written(tmp_path):
    """Not "it parsed" — the numbers have to be the ones that went in."""
    path = tmp_path / "take.rbxm"
    write_rbxm(path, parts=("Torso", "Left Arm"), angles=(12.0, 47.0))
    poses = {p.name: p for p in read_rbxm(path)[0].of_class("Pose")}

    for name, expected in (("Torso", 12.0), ("Left Arm", 47.0)):
        rotation, _ = poses[name].properties["CFrame"]
        angle = np.degrees(np.arccos(np.clip((np.trace(rotation) - 1) / 2, -1, 1)))
        assert angle == pytest.approx(expected, abs=1e-3)


# --- the conversion ---------------------------------------------------------


def test_an_r6_character_animation_is_recognised(tmp_path):
    path = tmp_path / "take.rbxm"
    write_rbxm(path)
    assert classify(read_rbxm(path)[0]) == "character"


def test_a_weapon_rig_is_refused_and_says_why(tmp_path):
    """Its pose tree is rooted on a custom part, so there is no R15 shaped like it.

    Renaming the parts would produce a file that imports and does nothing,
    which is worse than refusing.
    """
    path = tmp_path / "gun.rbxm"
    write_rbxm(path, parts=("AnimBase", "Grip"), angles=(5.0, 9.0))
    # AnimBase is not a body part, so the root of the tree is not a character.
    assert classify(read_rbxm(path)[0]) == "character"  # HumanoidRootPart still roots it

    with pytest.raises(ConvertError, match="rooted on a custom part"):
        convert_file(_viewmodel(tmp_path), tmp_path / "out.rbxmx")


def _viewmodel(tmp_path):
    """A pose tree with no character at the root at all."""
    path = tmp_path / "viewmodel.rbxm"
    poses = ["AnimBase", "Grip"]
    pose_refs = [2, 3]
    body = b"".join(
        [
            _inst(0, "KeyframeSequence", [0]),
            _inst(1, "Keyframe", [1]),
            _inst(2, "Pose", pose_refs),
            _prop_string(0, "Name", ["Gun"]),
            _prop_string(1, "Name", ["Keyframe"]),
            _prop_float(1, "Time", [0.0]),
            _prop_string(2, "Name", poses),
            _prop_cframe(2, "CFrame", [(np.eye(3), (0.0, 0.0, 0.0))] * 2),
            _prnt([(0, -1), (1, 0), (2, 1), (3, 2)]),
            _chunk(b"END\x00", b"</roblox>"),
        ]
    )
    path.write_bytes(MAGIC + struct.pack("<II", 3, 4) + b"\x00" * 8 + body)
    return path


def test_the_pose_is_reproduced_exactly(tmp_path):
    """The whole point: an R6 shoulder angle becomes the same R15 angle."""
    source = tmp_path / "take.rbxm"
    write_rbxm(source, parts=("Torso", "Left Arm"), angles=(12.0, 47.0))
    convert_file(source, tmp_path / "out.rbxmx")

    poses = {}
    for item in ET.parse(tmp_path / "out.rbxmx").getroot().iter("Item"):
        if item.get("class") != "Pose":
            continue
        name = item.find("Properties/string[@name='Name']").text
        cframe = item.find("Properties/CoordinateFrame[@name='CFrame']")
        poses[name] = np.array(
            [[float(cframe.find(f"R{r}{c}").text) for c in range(3)] for r in range(3)]
        )

    for r6, expected in (("Torso", 12.0), ("Left Arm", 47.0)):
        matrix = poses[R6_TO_R15[r6]]
        angle = np.degrees(np.arccos(np.clip((np.trace(matrix) - 1) / 2, -1, 1)))
        assert angle == pytest.approx(expected, abs=1e-3)


def test_the_tree_matches_the_r15_rig(tmp_path):
    """The editor resolves poses by walking the hierarchy, so it has to match.

    Written by hand the first time, the table stopped at the shoulder, and a
    tool held in the hand came out as a sibling of the character rather than on
    the end of the arm. It is taken from the rig now.
    """
    source = tmp_path / "take.rbxm"
    write_rbxm(source, parts=("Torso", "Left Arm"))
    convert_file(source, tmp_path / "out.rbxmx")

    parents = {}
    def walk(node, parent=None):
        name = node.find("Properties/string[@name='Name']")
        if node.get("class") == "Pose" and name is not None:
            parents[name.text] = parent
            parent = name.text
        for child in node.findall("Item"):
            walk(child, parent)

    walk(ET.parse(tmp_path / "out.rbxmx").getroot())
    assert parents["LowerTorso"] == "HumanoidRootPart"
    assert parents["UpperTorso"] == "LowerTorso", "R6 has no waist, so it rests here"
    assert parents["LeftUpperArm"] == "UpperTorso"


def test_a_held_object_ends_up_on_the_hand(tmp_path):
    """On R6 a tool welds to the whole arm; the R15 part that reaches there is the hand."""
    source = tmp_path / "take.rbxm"
    write_rbxm(source, parts=("Torso", "Left Arm", "Handle"), angles=(0.0, 20.0, 0.0))
    report = convert_file(source, tmp_path / "out.rbxmx")
    assert "Handle" in report.carried
    assert "Handle" not in R6_TO_R15, "it is not a body part and keeps its name"
