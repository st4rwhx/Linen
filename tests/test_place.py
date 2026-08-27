"""Staging a scene in a real place rather than in a void.

A cinematic written against a blank stage plays, and every position in it is
wrong for the game it was written for. That failure costs an evening because
nothing about it looks like a failure: the file imports, the script runs, the
characters move. So the place is read first, and what does not line up is said
out loud before anything is generated.
"""
from __future__ import annotations

import json

import pytest

from linen.scene import Scene
from linen.scene.place import BEGIN, END, PlaceError, parse_place, stage_in

SURVEYED = {
    "place": "Ma Partie",
    "placeId": 123,
    "rigs": [
        {"name": "Hero", "rig": "R15", "position": [10, 3, -4], "yaw": 90},
        {"name": "Thug", "rig": "R6", "position": [10, 3, -10], "yaw": -90},
    ],
    "landmarks": [
        {"name": "Wall", "class": "Part", "position": [14, 5, -7], "size": [1, 10, 20]}
    ],
    "sounds": [{"name": "Ambience", "id": "rbxassetid://9", "parent": "Workspace"}],
}


def _scene() -> Scene:
    return Scene.from_dict(
        {
            "name": "Duel",
            "actors": [
                {"name": "Hero", "rig": "R15", "position": [0, 0, 0], "facing": "Thug"},
                {"name": "Thug", "rig": "R15", "position": [0, 0, -6], "facing": "Hero"},
            ],
            "cues": [{"actor": "Hero", "at": 0.0, "prompt": "marche"}],
            "shots": [
                {"id": "wide", "position": [7, 4, 0], "look_at": "Hero"},
                {"id": "wall", "position": [8, 4, 2], "look_at": "Wall"},
            ],
        }
    )


def test_the_console_noise_around_the_survey_is_harmless():
    """People paste the whole Output window, and that has to be fine."""
    pasted = (
        "  15:02:11.204  Auto-Recovery file was created\n"
        f"  15:02:12.001  {BEGIN}\n"
        f"  15:02:12.002  {json.dumps(SURVEYED)}\n"
        f"  15:02:12.003  {END}\n"
        "  15:02:13.000  something else entirely\n"
    )
    place = parse_place(pasted)
    assert [r.name for r in place.rigs] == ["Hero", "Thug"]
    assert place.rig("Thug").rig == "R6"
    assert place.landmark("Wall").size == (1.0, 10.0, 20.0)


def test_the_bare_json_works_too():
    place = parse_place(json.dumps(SURVEYED))
    assert place.name == "Ma Partie"
    assert place.place_id == 123


def test_an_empty_or_wrong_paste_says_what_to_copy():
    with pytest.raises(PlaceError, match="empty"):
        parse_place("   \n  ")
    with pytest.raises(PlaceError, match="not the survey"):
        parse_place("Linen: la scene est incomplete")


def test_actors_are_moved_onto_the_real_rigs():
    scene = _scene()
    stage_in(scene, parse_place(json.dumps(SURVEYED)))
    assert scene.actor("Hero").position == (10.0, 3.0, -4.0)
    assert scene.actor("Thug").position == (10.0, 3.0, -10.0)


def test_facing_another_actor_survives_being_moved():
    """It is a relationship, not an angle: moving either end keeps it true."""
    scene = _scene()
    stage_in(scene, parse_place(json.dumps(SURVEYED)))
    assert scene.actor("Hero").facing == "Thug"


def test_a_written_yaw_gives_way_to_the_rig_that_is_actually_there():
    scene = _scene()
    scene.actor("Hero").facing = 12.0
    stage_in(scene, parse_place(json.dumps(SURVEYED)))
    assert scene.actor("Hero").facing == 90.0


def test_the_place_decides_which_rig_a_character_is():
    """The scene said R15 and the model in the place is R6.

    Believing the scene here writes an R15 animation onto an R6 body, which
    imports and then moves nothing: R6 has none of those joint names.
    """
    scene = _scene()
    notes = stage_in(scene, parse_place(json.dumps(SURVEYED)))
    assert scene.actor("Thug").rig == "R6"
    assert any("R6" in note and "Thug" in note for note in notes)


def test_an_actor_with_no_rig_in_the_place_keeps_its_position_and_is_reported():
    scene = _scene()
    scene.actors[0].name = "Heroine"
    scene.actors[1].facing = None
    scene.cues[0].actor = "Heroine"
    notes = stage_in(scene, parse_place(json.dumps(SURVEYED)))
    assert scene.actor("Heroine").position == (0.0, 0.0, 0.0)
    assert any("Heroine" in note and "aucun rig" in note for note in notes)


def test_a_shot_aimed_at_nothing_is_reported_before_anything_is_generated():
    scene = _scene()
    scene.shots[1].look_at = "Mur"  # named in French; the place calls it Wall
    notes = stage_in(scene, parse_place(json.dumps(SURVEYED)))
    assert any("Mur" in note for note in notes)


def test_a_shot_aimed_at_a_real_landmark_is_not_reported():
    scene = _scene()
    notes = stage_in(scene, parse_place(json.dumps(SURVEYED)))
    assert not any("wall" in note and "vise" in note for note in notes)


def test_the_survey_script_is_read_only():
    """It runs in someone's open place. It must not be able to change it."""
    from linen.scene.place import SURVEY

    for destructive in (":Destroy()", ":Remove()", "Instance.new", ".Parent =", ":Clone()"):
        assert destructive not in SURVEY, f"the survey must not {destructive}"
    assert SURVEY.count("print(") >= 1


def test_the_timestamps_studio_puts_on_every_copied_line_come_off():
    """Copying from the Output window gives `15:02:12.002  {...}`, not `{...}`.

    This is what the paste actually looks like, so it is what has to parse.
    """
    place = parse_place(f'  15:02:12.002  {json.dumps(SURVEYED)}')
    assert place.name == "Ma Partie"


def test_a_scene_built_against_a_place_reaches_the_script_that_way(tmp_path, capsys):
    """The whole bridge, once: survey in, real rigs and published ids out."""
    from linen.cli import main

    place = tmp_path / "place.json"
    place.write_text(
        f"  15:02:12.001  {BEGIN}\n  15:02:12.002  {json.dumps(SURVEYED)}\n"
        f"  15:02:12.003  {END}\n"
    )
    manifest = tmp_path / "publish.json"
    manifest.write_text(
        json.dumps({"creator": "user:1", "assets": {"Duel_Hero.rbxmx": "999"}})
    )
    scene = tmp_path / "duel.scene.json"
    scene.write_text(json.dumps(_scene().to_dict()))

    out = tmp_path / "out"
    assert (
        main(
            [
                "scene", str(scene), "--place", str(place), "--animations", str(manifest),
                "--planner", "offline", "--no-audio", "-o", str(out),
            ]
        )
        == 0
    )

    script = (out / "Duel.server.luau").read_text()
    assert '["Hero"] = "rbxassetid://999"' in script, "the published id must reach the script"
    assert "Thug" not in script.split("ANIMATION_IDS")[1].split("}")[0], (
        "an actor with no published id must be absent, not present and empty"
    )
    assert "Vector3.new(10, 3, -4)" in script, "the rig's real position, not the written one"
    assert 'rig = "R6"' in script, "the place said R6, so the script must stage R6"

    printed = capsys.readouterr().out
    assert "1/2 animations publiees" in printed
    assert "Thug" in printed


def test_the_survey_survives_being_flattened_onto_one_line():
    """Studio's Command Bar may collapse a paste, and a `--` comment then eats
    everything after it — the whole script, silently, with no output at all.

    Block comments are immune, so the script uses only those. This checks the
    property rather than the style: with every `--[[ ]]` region removed, no
    `--` may remain.
    """
    import re

    from linen.scene.place import SURVEY

    bare = re.sub(r"--\[\[.*?\]\]", " ", SURVEY, flags=re.DOTALL)
    # The markers are `--LINEN-PLACE-...--`, which is a `--` inside a string
    # literal and therefore not a comment at all. Quoted text goes too.
    bare = re.sub(r'"[^"\n]*"', '""', bare)
    assert "--" not in bare, (
        "a line comment outside a block would swallow a flattened paste: "
        + repr(next(line for line in bare.splitlines() if "--" in line))
    )


def test_the_flattened_survey_still_reaches_its_print():
    """Everything the script needs must survive losing its newlines."""
    from linen.scene.place import SURVEY

    flat = " ".join(SURVEY.split())
    assert flat.count("print(") == 3, "the three prints must still be there"
    assert flat.rstrip().endswith(f'print("{END}")')


def test_a_name_shared_by_several_objects_is_flagged_not_silently_framed():
    """Three parts called `Handle` in one place is ordinary.

    The camera will frame one of them, and not necessarily the one that was
    meant — so it says which one it took and where.
    """
    surveyed = dict(SURVEYED)
    surveyed["landmarks"] = [
        {"name": "Handle", "class": "MeshPart", "position": [-15, 5.5, -3.5], "size": [1, 1, 1]},
        {"name": "Handle", "class": "MeshPart", "position": [-15, 4.1, -3.5], "size": [1, 1, 1]},
    ]
    scene = _scene()
    scene.shots[1].look_at = "Handle"
    notes = stage_in(scene, parse_place(json.dumps(surveyed)))
    assert any("2 objets" in note and "Handle" in note for note in notes)


def test_the_ground_and_the_plugin_junk_are_not_offered_as_camera_targets():
    """Read off a real survey: a baseplate, terrain, a spawn and a Moon gizmo.

    None of those is something a camera is pointed at, and they crowd out what
    is — a place only reports sixty landmarks.
    """
    from linen.scene.place import SURVEY

    for excluded in ("Terrain", "Baseplate", "SpawnLocation"):
        assert f"{excluded} = true" in SURVEY, f"{excluded} must be filtered out"
    assert "MAX_LANDMARK_STUDS" in SURVEY, "a 2048-stud baseplate is not a landmark"
    assert "insideRig" in SURVEY, "a tool's Handle belongs to whoever holds it"


def test_a_rig_is_read_at_its_root_not_at_the_model_pivot():
    """The staging script positions a character by its HumanoidRootPart.

    A Model's pivot is a different point — on a rig from the Rig Builder it
    sits near the floor — so reading the pivot and staging to the root buries
    the character a couple of studs into the ground. Seen on a real place:
    a rig reported at y=0.13 whose root belongs at y=2.43.
    """
    from linen.scene.place import SURVEY

    assert "HumanoidRootPart" in SURVEY
    root = SURVEY.index('model:FindFirstChild("HumanoidRootPart")')
    pivot = SURVEY.index("model:GetPivot()")
    assert root < pivot, "the root is the first choice; the pivot is the fallback"


def test_a_plugins_scratch_object_is_not_offered_as_a_camera_target():
    """Moon Animator leaves a `MegMoAnimatorGizmoProxy` at the origin.

    Read off a real survey: after the ground and the tools were filtered, that
    was the only thing left — a plugin's leftovers standing in for the set.
    """
    from linen.scene.place import SURVEY

    assert "isPluginJunk" in SURVEY
    for needle in ("Gizmo", "Proxy", "MoonAnimator", "MegMo"):
        assert f'"{needle}"' in SURVEY
    assert "Transparency < 1" in SURVEY, "nor anything nobody can see"
