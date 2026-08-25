"""Reading a Collada motion export, without Blender in the way.

The files here are written by hand, so the answer is known before the parser
runs. That matters more than usual for this format: a mocap importer that is
subtly wrong produces a skeleton which looks almost right, and almost right is
the hardest kind of wrong to notice.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from linen.sources.collada import ColladaError, read_collada

_HEADER = """<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
"""


def _matrix(*rows: tuple[float, ...]) -> str:
    return " ".join(f"{value:g}" for row in rows for value in row)


def _identity(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> str:
    return _matrix((1, 0, 0, x), (0, 1, 0, y), (0, 0, 1, z), (0, 0, 0, 1))


def write_dae(
    path,
    *,
    frames: int = 4,
    fps: float = 30.0,
    swing_degrees: float = 0.0,
    prefix: str = "mixamorig:",
    nested: bool = False,
    animated: bool = True,
) -> None:
    """Three joints: a hip, a bone below it, and a tip below that.

    ``swing_degrees`` rotates the middle bone about X. The **tip** is what
    traces an arc trigonometry can predict, and that is the point of having
    three: a joint's own rotation moves its children, not itself, so a
    two-joint skeleton would have sat perfectly still however hard it turned.
    The first version of this test asserted otherwise and was wrong.
    """
    times = " ".join(f"{index / fps:g}" for index in range(frames))
    angles = np.linspace(0.0, math.radians(swing_degrees), frames)

    baked = []
    for angle in angles:
        cos, sin = math.cos(angle), math.sin(angle)
        baked.append(
            _matrix((1, 0, 0, 0), (0, cos, -sin, -10), (0, sin, cos, 0), (0, 0, 0, 1))
        )

    animation = f"""
      <animation id="anim_bone">
        <source id="bone_time">
          <float_array id="bone_time_a" count="{frames}">{times}</float_array>
        </source>
        <source id="bone_pose">
          <float_array id="bone_pose_a" count="{frames * 16}">{" ".join(baked)}</float_array>
        </source>
        <sampler id="bone_sampler">
          <input semantic="INPUT" source="#bone_time"/>
          <input semantic="OUTPUT" source="#bone_pose"/>
        </sampler>
        <channel source="#bone_sampler" target="bone/transform"/>
      </animation>
"""
    if nested:
        animation = f"<animation id='outer'>{animation}</animation>"

    body = f"""
  <library_animations>{animation if animated else ""}</library_animations>
  <library_visual_scenes>
    <visual_scene id="Scene">
      <node id="Armature" name="Armature" type="NODE">
        <matrix sid="transform">{_identity()}</matrix>
        <node id="hips" sid="{prefix}Hips" name="{prefix}Hips" type="JOINT">
          <matrix sid="transform">{_identity(0, 100, 0)}</matrix>
          <node id="bone" sid="{prefix}Spine" name="{prefix}Spine" type="JOINT">
            <matrix sid="transform">{_identity(0, -10, 0)}</matrix>
            <node id="tip" sid="{prefix}Head" name="{prefix}Head" type="JOINT">
              <matrix sid="transform">{_identity(0, -10, 0)}</matrix>
            </node>
          </node>
        </node>
      </node>
    </visual_scene>
  </library_visual_scenes>
</COLLADA>
"""
    path.write_text(_HEADER + body)


def test_the_skeleton_and_its_hierarchy_come_back(tmp_path):
    path = tmp_path / "take.dae"
    write_dae(path)
    motion = read_collada(path)
    assert motion.names == ("Hips", "Spine", "Head"), "the mixamorig: prefix goes"
    assert motion.parents == [-1, 0, 1]


def test_the_frame_rate_is_read_from_the_timestamps(tmp_path):
    path = tmp_path / "take.dae"
    write_dae(path, frames=7, fps=60.0)
    assert read_collada(path).fps == pytest.approx(60.0)


def test_a_joint_that_swings_traces_the_arc_geometry_says_it_should(tmp_path):
    """Checked against trigonometry, not against the parser's own output."""
    path = tmp_path / "take.dae"
    write_dae(path, frames=5, swing_degrees=90.0)
    world = read_collada(path).world_positions()

    # The hip sits 100 up, the bone 10 below it, the tip 10 below that.
    assert world[0, 0] == pytest.approx([0.0, 100.0, 0.0])
    assert world[0, 1] == pytest.approx([0.0, 90.0, 0.0])
    assert world[0, 2] == pytest.approx([0.0, 80.0, 0.0])

    # A quarter turn about X swings the tip from under the bone to behind it,
    # while the bone itself does not move at all.
    assert world[-1, 1] == pytest.approx([0.0, 90.0, 0.0], abs=1e-6)
    assert world[-1, 2] == pytest.approx([0.0, 90.0, -10.0], abs=1e-6)

    # And the path between is an arc of constant radius, not a straight line.
    radius = np.linalg.norm(world[:, 2] - world[:, 1], axis=1)
    assert np.allclose(radius, 10.0, atol=1e-6)


def test_a_joint_with_no_curve_holds_its_bind_pose(tmp_path):
    path = tmp_path / "take.dae"
    write_dae(path, frames=6, swing_degrees=45.0)
    world = read_collada(path).world_positions()
    assert np.allclose(world[:, 0], world[0, 0]), "the hip has no animation on it"


def test_animations_nested_one_level_deep_are_still_found(tmp_path):
    """Exporters differ: some write a flat list, some group per joint."""
    path = tmp_path / "take.dae"
    write_dae(path, frames=5, swing_degrees=30.0, nested=True)
    assert read_collada(path).locals.shape[0] == 5


def test_a_file_without_the_mixamo_prefix_still_reads(tmp_path):
    path = tmp_path / "take.dae"
    write_dae(path, prefix="")
    assert read_collada(path).names == ("Hips", "Spine", "Head")


def test_a_file_with_no_motion_says_so(tmp_path):
    path = tmp_path / "still.dae"
    write_dae(path, animated=False)
    with pytest.raises(ColladaError, match="no baked joint matrices"):
        read_collada(path)


def test_a_file_that_is_not_collada_says_so(tmp_path):
    path = tmp_path / "broken.dae"
    path.write_text("<?xml version='1.0'?><nope/>")
    with pytest.raises(ColladaError, match="no library_visual_scenes"):
        read_collada(path)


def test_something_that_is_not_xml_at_all_says_so(tmp_path):
    path = tmp_path / "broken.dae"
    path.write_bytes(b"\x00\x01 not xml")
    with pytest.raises(ColladaError, match="not readable XML"):
        read_collada(path)


def _mixamo_dae(path, frames: int = 24, fps: float = 30.0) -> None:
    """A full Mixamo-shaped skeleton walking, written by hand.

    Twenty-one joints under the ``mixamorig:`` prefix, which is what a Mixamo
    Collada export actually contains — enough for the skeleton mapping to
    resolve every landmark it needs, so the whole command runs.
    """
    chain = [
        ("Hips", None, (0, 100, 0)), ("Spine", "Hips", (0, 10, 0)),
        ("Spine1", "Spine", (0, 10, 0)), ("Neck", "Spine1", (0, 12, 0)),
        ("Head", "Neck", (0, 6, 0)),
        ("LeftShoulder", "Spine1", (4, 8, 0)), ("LeftArm", "LeftShoulder", (6, 0, 0)),
        ("LeftForeArm", "LeftArm", (14, 0, 0)), ("LeftHand", "LeftForeArm", (12, 0, 0)),
        ("RightShoulder", "Spine1", (-4, 8, 0)), ("RightArm", "RightShoulder", (-6, 0, 0)),
        ("RightForeArm", "RightArm", (-14, 0, 0)), ("RightHand", "RightForeArm", (-12, 0, 0)),
        ("LeftUpLeg", "Hips", (5, -2, 0)), ("LeftLeg", "LeftUpLeg", (0, -18, 0)),
        ("LeftFoot", "LeftLeg", (0, -18, 0)), ("LeftToeBase", "LeftFoot", (0, -3, 6)),
        ("RightUpLeg", "Hips", (-5, -2, 0)), ("RightLeg", "RightUpLeg", (0, -18, 0)),
        ("RightFoot", "RightLeg", (0, -18, 0)), ("RightToeBase", "RightFoot", (0, -3, 6)),
    ]
    kids: dict[str | None, list] = {}
    for name, parent, offset in chain:
        kids.setdefault(parent, []).append((name, offset))

    def cell(angle: float, offset) -> str:
        cos, sin = math.cos(angle), math.sin(angle)
        return _matrix(
            (1, 0, 0, offset[0]), (0, cos, -sin, offset[1]),
            (0, sin, cos, offset[2]), (0, 0, 0, 1),
        )

    phase = np.linspace(0.0, 4 * math.pi, frames)
    swing = {
        "LeftUpLeg": 0.45 * np.sin(phase), "RightUpLeg": -0.45 * np.sin(phase),
        "LeftArm": -0.35 * np.sin(phase), "RightArm": 0.35 * np.sin(phase),
        "LeftLeg": -0.5 * np.clip(np.sin(phase), 0, None),
        "RightLeg": -0.5 * np.clip(-np.sin(phase), 0, None),
    }

    def node(name: str, offset) -> str:
        inner = "".join(node(kid, kid_offset) for kid, kid_offset in kids.get(name, []))
        return (
            f'<node id="{name}" sid="mixamorig:{name}" type="JOINT">'
            f'<matrix sid="transform">{cell(0.0, offset)}</matrix>{inner}</node>'
        )

    animations = []
    for name, angles in swing.items():
        offset = next(o for n, _, o in chain if n == name)
        times = " ".join(f"{index / fps:g}" for index in range(frames))
        poses = " ".join(cell(float(angle), offset) for angle in angles)
        animations.append(
            f'<animation id="a_{name}">'
            f'<source id="t_{name}"><float_array count="{frames}">{times}</float_array></source>'
            f'<source id="p_{name}"><float_array count="{frames * 16}">{poses}</float_array></source>'
            f'<sampler id="s_{name}">'
            f'<input semantic="INPUT" source="#t_{name}"/>'
            f'<input semantic="OUTPUT" source="#p_{name}"/></sampler>'
            f'<channel source="#s_{name}" target="{name}/transform"/></animation>'
        )

    path.write_text(
        _HEADER
        + f'<library_animations>{"".join(animations)}</library_animations>'
        + '<library_visual_scenes><visual_scene id="Scene">'
        + f'<node id="Armature" type="NODE">{node("Hips", (0, 100, 0))}</node>'
        + "</visual_scene></library_visual_scenes></COLLADA>"
    )


def test_a_mixamo_shaped_export_maps_onto_the_rig(tmp_path):
    from linen.sources import load_collada

    path = tmp_path / "walk.dae"
    _mixamo_dae(path)
    track = load_collada(path, units="cm")
    assert track.positions.shape[0] == 24
    assert np.isfinite(track.positions).any()


def test_the_command_takes_a_dae_without_being_told(tmp_path):
    """The suffix already says which format it is. Asking twice invites a wrong answer."""
    from linen.cli import main

    path = tmp_path / "walk.dae"
    _mixamo_dae(path)
    out = tmp_path / "walk.rbxmx"
    assert main(["bvh", str(path), "--units", "cm", "--no-viewer", "-o", str(out)]) == 0
    assert out.read_text().startswith("<?xml")
    assert "LeftUpperArm" in out.read_text()
