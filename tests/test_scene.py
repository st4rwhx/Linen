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


# --- events, props, shots ---------------------------------------------------
DISARM = json.loads(__import__("pathlib").Path("examples/disarm.scene.json").read_text())


def test_the_full_cinematic_scenario_builds():
    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    assert set(built.clips) == {"Hero", "Thug"}
    assert built.markers, "actor-bound events must become keyframe markers"
    assert built.director, "camera cuts and world effects go on the director clock"


def _marker_names(built) -> set[str]:
    return {
        name
        for frames in built.markers.values()
        for entries in frames.values()
        for name, _ in entries
    }


def test_events_bound_to_an_actor_become_markers_in_that_actors_animation():
    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    assert {"linen_prop", "linen_face", "linen_line"} <= _marker_names(built)


def test_an_authored_sound_event_still_rides_its_actors_animation():
    """Spotting derives most sounds now, but a hand-placed one must still work."""
    data = json.loads(json.dumps(DUET))
    data["events"] = [
        {
            "kind": "sound",
            "cue": "a_punch",
            "offset": 0.1,
            "actor": "Alice",
            "asset": "rbxassetid://12345",
        }
    ]
    built = build_scene(Scene.from_dict(data), **OFFLINE)
    assert "linen_sound" in _marker_names(built)


def test_camera_cuts_have_no_actor_so_they_ride_the_director_clock():
    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    kinds = {event.kind for _, event in built.director}
    assert "camera" in kinds
    assert "vfx" in kinds


def test_retiming_a_cue_moves_every_event_hanging_off_it():
    """The whole point of anchoring events rather than timestamping them."""
    early = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    data = json.loads(json.dumps(DISARM))
    next(c for c in data["cues"] if c["id"] == "approach")["duration"] = 3.2
    late = build_scene(Scene.from_dict(data), **OFFLINE)

    def camera_times(built):
        return [t for t, e in built.director if e.kind == "camera"]

    shift = 3.2 - 1.2
    assert camera_times(late) == pytest.approx([t + shift for t in camera_times(early)])


def test_a_marker_forces_its_frame_to_survive_keyframe_reduction():
    from linen.export import build_keyframe_sequence, reduce_keyframes

    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    clip = built.clips["Hero"]
    markers = built.markers["Hero"]
    reduced = reduce_keyframes(clip, angular_tolerance_deg=1.0)

    tree = build_keyframe_sequence(clip, frames=reduced, markers=markers)
    times = {
        item.find("Properties").find("string[@name='Name']").text
        for item in tree.getroot().find("Item").findall("Item")
    }
    for frame in markers:
        assert f"Keyframe{frame}" in times, "an event on a dropped keyframe never fires"


def test_an_event_naming_an_unknown_shot_is_rejected():
    data = json.loads(json.dumps(DISARM))
    data["events"].append({"kind": "camera", "cue": "disarm", "shot": "nope"})
    with pytest.raises(SceneError, match="known shots"):
        Scene.from_dict(data)


def test_an_unknown_expression_lists_the_real_ones():
    data = json.loads(json.dumps(DISARM))
    data["events"].append(
        {"kind": "face", "cue": "settle", "actor": "Hero", "expression": "constipated"}
    )
    with pytest.raises(SceneError, match="unknown expression"):
        Scene.from_dict(data)


def test_a_prop_held_by_someone_absent_is_rejected():
    data = json.loads(json.dumps(DISARM))
    data["props"][0]["held_by"] = "Ghost"
    with pytest.raises(SceneError, match="not in the cast"):
        Scene.from_dict(data)


# --- the set plan -----------------------------------------------------------
def test_the_wall_position_is_solved_from_the_throw_not_assumed():
    """The answer to 'where do I put the wall'.

    Launch instant, impulse and impact instant are all known, and Roblox's
    gravity is a constant — so the target's position is a solution, not a
    preference.
    """
    from linen.scene import GRAVITY, plan_set

    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    plan = plan_set(built)
    wall = next(p for p in plan.placements if p.name == "Wall")

    assert wall.derived
    assert "de vol" in wall.reason
    # Thrown towards -Z from around the origin, so it lands well ahead and
    # somewhere a wall could plausibly be.
    assert wall.position[2] < -8
    assert 0 < wall.position[1] < 8
    assert GRAVITY == 196.2


def test_doubling_the_flight_time_moves_the_wall_further_out():
    from linen.scene import plan_set

    def wall_z(impact_offset: float) -> float:
        data = json.loads(json.dumps(DISARM))
        for event in data["events"]:
            if event["kind"] == "vfx":
                event["offset"] = impact_offset
        built = build_scene(Scene.from_dict(data), **OFFLINE)
        return next(p for p in plan_set(built).placements if p.name == "Wall").position[2]

    assert wall_z(0.60) < wall_z(0.46)


def test_a_throw_with_no_impact_event_says_the_wall_cannot_be_placed():
    from linen.scene import plan_set

    data = json.loads(json.dumps(DISARM))
    data["events"] = [e for e in data["events"] if e["kind"] != "vfx"]
    plan = plan_set(build_scene(Scene.from_dict(data), **OFFLINE))
    assert any("aucun événement vfx" in w for w in plan.warnings)


def test_an_actor_standing_at_the_origin_is_reported_as_buried():
    """A Roblox character's position is its root, which sits at hip height."""
    from linen.scene import plan_set

    data = json.loads(json.dumps(DISARM))
    data["actors"][0]["position"] = [0, 0, 0]
    plan = plan_set(build_scene(Scene.from_dict(data), **OFFLINE))
    assert any("enterré" in w for w in plan.warnings)


def test_the_build_sheet_lists_what_the_scene_cannot_create():
    from linen.scene import plan_set

    plan = plan_set(build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE))
    named = {name for name, _ in plan.required_assets}
    assert "ReplicatedStorage.Props.Pistol" in named
    assert "WallImpact" in named


def test_a_shot_aimed_at_nothing_is_reported():
    from linen.scene import plan_set

    data = json.loads(json.dumps(DISARM))
    data["shots"].append({"id": "void", "position": [0, 5, 20], "look_at": "Nothing"})
    plan = plan_set(build_scene(Scene.from_dict(data), **OFFLINE))
    assert any("Nothing" in w for w in plan.warnings)


def test_the_blockout_names_its_parts_as_the_scene_expects_them():
    from xml.etree import ElementTree as ET

    from linen.scene import blockout, plan_set

    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    root = ET.fromstring(blockout(plan_set(built)))
    names = {
        item.find("Properties").find("string[@name='Name']").text
        for item in root.iter("Item")
        if item.get("class") == "Part"
    }
    assert {"Wall", "Floor"} <= names


# --- the player -------------------------------------------------------------
def test_the_player_connects_one_marker_signal_per_event_kind():
    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    script = scene_script(built)
    assert 'GetMarkerReachedSignal("linen_" .. kind)' in script
    for kind in ("sound", "vfx", "face", "line", "prop", "camera"):
        assert f'"{kind}"' in script


def test_the_player_carries_the_shots_props_and_director_clock():
    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    script = scene_script(built)
    assert 'id = "wall"' in script and 'id = "two_shot"' in script
    assert 'name = "Pistol"' in script
    assert "local DIRECTOR" in script
    assert "EXPRESSIONS" in script and "LipCornerPuller" in script


def test_the_player_reports_what_is_missing_rather_than_half_playing():
    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    script = scene_script(built)
    assert "table.insert(missing" in script
    assert "est incomplète" in script
