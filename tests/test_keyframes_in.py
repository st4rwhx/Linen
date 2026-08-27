"""Reading a Roblox animation back, so work made anywhere else can be used.

The pose vocabulary here knows twelve verbs. A service that sells generated R15
motion, a Mixamo clip imported and saved out of Studio, a fight beat somebody
keyed by hand in Moon Animator — every one of those is better at what it does
than the twelve verbs, and every one comes out of Studio as a KeyframeSequence.

Reading that back is what lets a scene be assembled out of them. It is the
difference between Linen having to be good at inventing movement and Linen
having to be good at arranging it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from linen.export.rbxmx import write_rbxmx
from linen.sources.keyframes import KeyframeSequenceError, read_keyframe_sequence

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_a_shipped_r15_animation_comes_back_as_itself():
    clip = read_keyframe_sequence(EXAMPLES / "starter/R15/Walk.rbxmx")
    assert clip.rig.name == "R15"
    assert clip.loop is True
    assert clip.frame_count > 1


def test_an_r6_animation_is_recognised_as_r6():
    """Guessing wrong writes an R15 animation onto an R6 body.

    That imports, plays, and moves nothing — R6 has none of those joint names —
    so the rig is counted from the joints the file poses, never assumed.
    """
    clip = read_keyframe_sequence(EXAMPLES / "starter/Zombie/zombie_walk.R6.rbxmx")
    assert clip.rig.name == "R6"


def test_writing_a_clip_and_reading_it_back_gives_the_same_motion(tmp_path):
    """The round trip is what everything downstream rests on.

    Both rigs, because R6 stores its rotations in a turned joint frame and R15
    does not — a round trip that only worked on R15 would look fine here and
    lose every R6 animation silently.
    """
    from linen.clip import AnimationClip
    from linen.math3d import mat_to_quat
    from linen.rigs import get_rig

    for rig_name in ("R15", "R6"):
        rig = get_rig(rig_name)
        frames = 24
        angles = np.linspace(0.0, np.radians(50.0), frames)
        swing = np.stack(
            [
                np.array(
                    [
                        [1.0, 0.0, 0.0],
                        [0.0, np.cos(a), -np.sin(a)],
                        [0.0, np.sin(a), np.cos(a)],
                    ]
                )
                for a in angles
            ]
        )
        moving = rig.animated_parts[3]
        rotations = {
            part: mat_to_quat(np.tile(np.eye(3), (frames, 1, 1))) for part in rig.animated_parts
        }
        rotations[moving] = mat_to_quat(swing)
        original = AnimationClip(rig=rig, fps=30.0, rotations=rotations, name="Swing")

        path = tmp_path / f"swing.{rig_name}.rbxmx"
        write_rbxmx(original, path, frames=list(range(frames)))
        back = read_keyframe_sequence(path, fps=30.0)

        assert back.rig.name == rig_name
        assert back.frame_count == frames
        worst = max(
            float(
                np.degrees(
                    2.0
                    * np.arccos(
                        np.clip(np.abs(np.sum(original.rotations[part] * back.rotations[part], axis=1)), 0, 1)
                    )
                ).max()
            )
            for part in rig.animated_parts
        )
        assert worst < 0.2, f"{rig_name} lost {worst:.2f} deg through the round trip"


def test_keyframes_between_the_stored_ones_are_interpolated_not_held(tmp_path):
    """Roblox slerps between keyframes; holding each pose then jumping is the
    staircase a KeyframeSequence exists to avoid."""
    from linen.clip import AnimationClip
    from linen.math3d import mat_to_quat
    from linen.rigs import get_rig

    rig = get_rig("R15")
    ends = np.stack(
        [
            np.eye(3),
            np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]),  # 90 deg
        ]
    )
    rotations = {part: mat_to_quat(np.tile(np.eye(3), (2, 1, 1))) for part in rig.animated_parts}
    rotations["LeftUpperArm"] = mat_to_quat(ends)
    # Two keyframes a second apart, read back at 30 fps: 31 frames, and the
    # middle one must be halfway round, not still at the start.
    sparse = AnimationClip(rig=rig, fps=1.0, rotations=rotations, name="Sweep")
    path = tmp_path / "sweep.rbxmx"
    write_rbxmx(sparse, path, frames=[0, 1])

    back = read_keyframe_sequence(path, fps=30.0)
    middle = back.rotations["LeftUpperArm"][15]
    angle = np.degrees(2.0 * np.arccos(min(abs(float(middle[3])), 1.0)))
    assert 40.0 < angle < 50.0, f"the midpoint is at {angle:.1f} deg, not halfway"


def test_something_that_is_not_an_animation_says_so(tmp_path):
    path = tmp_path / "model.rbxmx"
    path.write_text('<roblox version="4"><Item class="Part"/></roblox>')
    with pytest.raises(KeyframeSequenceError, match="KeyframeSequence"):
        read_keyframe_sequence(path)


def test_a_weapon_rig_is_refused_rather_than_mapped_onto_a_body(tmp_path):
    """A first-person viewmodel poses parts no character has.

    Renaming them to the nearest body joint produces a file that imports and
    does nothing, which is worse than a refusal that says why.
    """
    path = tmp_path / "viewmodel.rbxmx"
    path.write_text(
        '<roblox version="4"><Item class="KeyframeSequence"><Item class="Keyframe">'
        '<Properties><float name="Time">0</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">AnimBase</string>'
        '<CoordinateFrame name="CFrame"><X>0</X><Y>0</Y><Z>0</Z>'
        "<R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12>"
        "<R20>0</R20><R21>0</R21><R22>1</R22></CoordinateFrame></Properties></Item>"
        "</Item></Item></roblox>"
    )
    with pytest.raises(KeyframeSequenceError, match="weapon rig"):
        read_keyframe_sequence(path)


def test_a_library_can_be_built_from_finished_roblox_animations(tmp_path):
    """A game's own animations become material for its cinematics."""
    from linen.library import build_library

    folder = tmp_path / "mine"
    folder.mkdir()
    for name in ("CrouchMove", "Swim"):
        source = EXAMPLES / f"starter/R15_converties/{name}.rbxmx"
        (folder / f"{name}.rbxmx").write_bytes(source.read_bytes())

    library = build_library(folder)
    assert len(library.entries) == 2
    score, entry = library.search("crouch move")[0]
    assert entry.name == "CrouchMove" and score > 0


def test_a_scene_cue_can_be_answered_by_a_finished_animation(tmp_path):
    from linen.library import build_library
    from linen.scene import Scene, build_scene

    folder = tmp_path / "mine"
    folder.mkdir()
    source = EXAMPLES / "starter/R15_converties/CrouchMove.rbxmx"
    (folder / "CrouchMove.rbxmx").write_bytes(source.read_bytes())

    scene = Scene.from_dict(
        {
            "name": "Essai",
            "actors": [{"name": "Rig", "rig": "R15"}],
            "cues": [{"id": "a", "actor": "Rig", "at": 0.0, "prompt": "crouch move"}],
        }
    )
    built = build_scene(scene, planner="offline", library=build_library(folder))
    assert built.schedule[0].source == "library:CrouchMove"
    assert built.clips["Rig"].frame_count > 1


def test_an_animation_for_the_wrong_rig_is_refused_with_the_way_out(tmp_path):
    """An R6 clip on an R15 actor would import and move nothing."""
    from linen.library import build_library
    from linen.scene import Scene, SceneError, build_scene

    folder = tmp_path / "mine"
    folder.mkdir()
    source = EXAMPLES / "starter/Zombie/zombie_walk.R6.rbxmx"
    (folder / "zombie walk.rbxmx").write_bytes(source.read_bytes())

    scene = Scene.from_dict(
        {
            "name": "Essai",
            "actors": [{"name": "Rig", "rig": "R15"}],
            "cues": [{"id": "a", "actor": "Rig", "at": 0.0, "prompt": "zombie walk"}],
        }
    )
    with pytest.raises(SceneError, match="linen convert"):
        build_scene(scene, planner="offline", library=build_library(folder))
