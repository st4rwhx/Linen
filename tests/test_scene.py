from __future__ import annotations

import json

import numpy as np
import pytest

from linen.clip import IDENTITY_QUAT
from linen.math3d import quat_angle
from linen.scene import Scene, SceneError, build_scene, scene_script
from linen.scene.schema import json_schema

OFFLINE = {"planner": "offline"}

DUET = {
    "name": "Duet",
    "fps": 30,
    "actors": [
        {"name": "Alice", "rig": "R15", "position": [0, 0, 0], "facing": "Bob"},
        {"name": "Bob", "rig": "R6", "position": [0, 0, -6], "facing": "Alice"},
    ],
    "cues": [
        {"id": "a_walk", "actor": "Alice", "at": 0.0, "prompt": "marche", "duration": 1.5},
        {"id": "a_punch", "actor": "Alice", "after": "a_walk", "prompt": "coup de poing droite"},
        {"id": "b_wait", "actor": "Bob", "at": 0.0, "prompt": "reste immobile", "duration": 1.4},
        {"id": "b_flinch", "actor": "Bob", "with": "a_punch", "offset": 0.3, "prompt": "encaisse"},
    ],
}


def scene(**overrides) -> Scene:
    data = json.loads(json.dumps(DUET))
    data.update(overrides)
    return Scene.from_dict(data)


# --- scheduling ------------------------------------------------------------
def test_after_anchors_to_the_end_of_another_cue():
    built = build_scene(scene(), **OFFLINE)
    by_id = {entry.cue.id: entry for entry in built.schedule}
    assert by_id["a_punch"].start == pytest.approx(by_id["a_walk"].end)


def test_with_anchors_to_the_start_of_another_cue():
    built = build_scene(scene(), **OFFLINE)
    by_id = {entry.cue.id: entry for entry in built.schedule}
    assert by_id["b_flinch"].start == pytest.approx(by_id["a_punch"].start + 0.3)


def test_retiming_the_cause_retimes_the_reaction():
    # The whole point of anchoring: lengthen the walk and the flinch follows,
    # because it hangs off the punch rather than off the clock.
    early = build_scene(scene(), **OFFLINE)
    data = json.loads(json.dumps(DUET))
    data["cues"][0]["duration"] = 4.0
    late = build_scene(Scene.from_dict(data), **OFFLINE)

    def flinch(built):
        return next(e for e in built.schedule if e.cue.id == "b_flinch").start

    assert flinch(late) - flinch(early) == pytest.approx(2.5, abs=1e-6)


def test_an_unanchored_cue_follows_that_actor_previous_one():
    built = build_scene(
        Scene.from_dict(
            {
                "name": "Chain",
                "actors": [{"name": "Solo"}],
                "cues": [
                    {"actor": "Solo", "prompt": "marche", "duration": 1.0},
                    {"actor": "Solo", "prompt": "saute"},
                    {"actor": "Solo", "prompt": "celebre"},
                ],
            }
        ),
        **OFFLINE,
    )
    starts = [entry.start for entry in built.schedule]
    assert starts == sorted(starts)
    assert starts[1] == pytest.approx(1.0)


def test_a_negative_offset_can_start_a_cue_before_its_anchor():
    built = build_scene(
        Scene.from_dict(
            {
                "name": "Brace",
                "actors": [{"name": "A"}, {"name": "B"}],
                "cues": [
                    {"id": "hit", "actor": "A", "at": 2.0, "prompt": "coup de poing"},
                    {"actor": "B", "with": "hit", "offset": -0.4, "prompt": "accroupi"},
                ],
            }
        ),
        **OFFLINE,
    )
    assert next(e for e in built.schedule if e.cue.actor == "B").start == pytest.approx(1.6)


def test_an_offset_before_the_start_of_the_scene_is_rejected():
    with pytest.raises(SceneError, match="before the scene begins"):
        build_scene(
            Scene.from_dict(
                {
                    "name": "TooEarly",
                    "actors": [{"name": "A"}, {"name": "B"}],
                    "cues": [
                        {"id": "hit", "actor": "A", "at": 0.2, "prompt": "coup de poing"},
                        {"actor": "B", "with": "hit", "offset": -3.0, "prompt": "accroupi"},
                    ],
                }
            ),
            **OFFLINE,
        )


def test_cues_waiting_on_each_other_are_reported_as_a_loop():
    with pytest.raises(SceneError, match="loop"):
        build_scene(
            Scene.from_dict(
                {
                    "name": "Deadlock",
                    "actors": [{"name": "A"}],
                    "cues": [
                        {"id": "one", "actor": "A", "after": "two", "prompt": "marche"},
                        {"id": "two", "actor": "A", "after": "one", "prompt": "saute"},
                    ],
                }
            ),
            **OFFLINE,
        )


def test_an_actor_cannot_play_two_cues_at_once():
    with pytest.raises(SceneError, match="double-booked"):
        build_scene(
            Scene.from_dict(
                {
                    "name": "Clash",
                    "actors": [{"name": "A"}],
                    "cues": [
                        {"id": "x", "actor": "A", "at": 0.0, "prompt": "marche", "duration": 3.0},
                        {"id": "y", "actor": "A", "at": 1.0, "prompt": "saute"},
                    ],
                }
            ),
            **OFFLINE,
        )


# --- validation ------------------------------------------------------------
def test_a_cue_for_an_unknown_actor_is_rejected():
    with pytest.raises(SceneError, match="not in the cast"):
        scene(cues=[{"actor": "Carol", "prompt": "marche"}])


def test_facing_someone_absent_is_rejected():
    with pytest.raises(SceneError, match="not in the cast"):
        scene(actors=[{"name": "Alice", "facing": "Ghost"}])


def test_an_actor_cannot_face_itself():
    with pytest.raises(SceneError, match="cannot face itself"):
        scene(actors=[{"name": "Alice", "facing": "Alice"}])


def test_an_anchor_to_a_missing_cue_lists_the_real_ones():
    with pytest.raises(SceneError, match="Known cues"):
        scene(cues=[{"id": "solo", "actor": "Alice", "after": "nope", "prompt": "marche"}])


def test_an_unknown_rig_is_rejected():
    with pytest.raises(SceneError, match="unknown rig"):
        scene(actors=[{"name": "Alice", "rig": "R20"}])


def test_ids_are_generated_when_omitted():
    parsed = Scene.from_dict(
        {
            "name": "Auto",
            "actors": [{"name": "A"}],
            "cues": [{"actor": "A", "prompt": "marche"}, {"actor": "A", "prompt": "saute"}],
        }
    )
    assert [cue.id for cue in parsed.cues] == ["A_0", "A_1"]


def test_scene_survives_a_json_roundtrip():
    original = scene()
    assert Scene.from_dict(original.to_dict()).to_dict() == original.to_dict()


def test_the_schema_offers_both_rigs():
    actors = json_schema()["properties"]["actors"]["items"]["properties"]
    assert set(actors["rig"]["enum"]) == {"R15", "R6"}


# --- the built clips -------------------------------------------------------
def test_each_actor_gets_one_clip_spanning_the_whole_scene():
    built = build_scene(scene(), **OFFLINE)
    assert set(built.clips) == {"Alice", "Bob"}
    for clip in built.clips.values():
        assert clip.duration == pytest.approx(built.duration, abs=1.0 / 30.0)


def test_actors_keep_their_own_rig():
    built = build_scene(scene(), **OFFLINE)
    assert built.clips["Alice"].rig.name == "R15"
    assert built.clips["Bob"].rig.name == "R6"
    assert "Left Arm" in built.clips["Bob"].rotations


def test_a_cue_actually_animates_its_actor_at_the_right_moment():
    built = build_scene(scene(), **OFFLINE)
    punch = next(e for e in built.schedule if e.cue.id == "a_punch")
    clip = built.clips["Alice"]

    frame = int((punch.start + punch.end) / 2 * clip.fps)
    rest = IDENTITY_QUAT
    assert np.rad2deg(quat_angle(clip.rotations["RightUpperArm"][frame], rest)) > 30.0


def test_an_actor_holds_its_last_pose_rather_than_snapping_to_rest():
    built = build_scene(scene(), **OFFLINE)
    clip = built.clips["Bob"]
    # Bob's flinch is the last thing he does; the tail must not jump to rest.
    tail = clip.rotations["Torso"][-1]
    just_before = clip.rotations["Torso"][-6]
    assert np.rad2deg(quat_angle(tail, just_before)) < 2.0


def test_every_built_clip_is_finite():
    built = build_scene(scene(), **OFFLINE)
    for clip in built.clips.values():
        for track in clip.rotations.values():
            assert np.all(np.isfinite(track))


def test_building_is_deterministic():
    first = build_scene(scene(), **OFFLINE)
    second = build_scene(scene(), **OFFLINE)
    for actor, clip in first.clips.items():
        for part, track in clip.rotations.items():
            assert np.array_equal(track, second.clips[actor].rotations[part])


# --- the Studio script -----------------------------------------------------
def test_the_script_stages_every_actor_and_lists_every_cue():
    built = build_scene(scene(), **OFFLINE)
    script = scene_script(built)
    for name in ("Alice", "Bob"):
        assert f'name = "{name}"' in script
    for cue in ("a_walk", "a_punch", "b_wait", "b_flinch"):
        assert f'id = "{cue}"' in script


def test_the_script_registers_sequences_instead_of_requiring_an_upload():
    script = scene_script(build_scene(scene(), **OFFLINE))
    assert "KeyframeSequenceProvider:RegisterKeyframeSequence" in script
    assert "Studio-only" in script


def test_the_script_starts_every_track_on_the_same_frame():
    script = scene_script(build_scene(scene(), **OFFLINE))
    assert "track:Play(0)" in script


def test_quotes_in_a_prompt_cannot_break_the_generated_lua():
    built = build_scene(
        Scene.from_dict(
            {
                "name": 'He said "go"',
                "actors": [{"name": "A"}],
                "cues": [{"actor": "A", "prompt": 'il dit "salut" puis marche'}],
            }
        ),
        **OFFLINE,
    )
    script = scene_script(built)
    assert '\\"go\\"' in script
    assert '\\"salut\\"' in script
