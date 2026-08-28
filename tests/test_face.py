"""A face generated from the scene, not captured from a webcam.

Studio can turn a webcam into facial keyframes, and for someone acting their
own scene that is the best tool there is. It is the wrong tool for a pipeline
whose point is that a written scene comes out finished: it puts a person back
in the loop for every beat.

So the performance is built from what the scene already says — expressions from
`face` events, mouths from the dialogue's own letters, blinks from the fact that
faces blink.
"""
from __future__ import annotations

import pytest

from linen.scene import Scene, build_scene
from linen.scene.face import (
    CONTROLS,
    EXPRESSIONS,
    OPTIONAL,
    REQUIRED,
    FaceTrack,
    blinks,
    speak,
    visemes,
)


def test_every_pose_named_here_is_one_roblox_actually_has():
    """Fifty FACS controls, verbatim from the avatar reference.

    An invented property name is set with pcall and vanishes: the face plays,
    nothing moves, and nothing says why.
    """
    assert len(CONTROLS) == 50
    assert len(REQUIRED) == 17 and len(OPTIONAL) == 33
    invented = {c for poses in EXPRESSIONS.values() for c in poses} - CONTROLS
    assert not invented, invented


def test_the_expressions_lean_on_the_poses_every_published_head_has():
    """A head only has to ship the required seventeen to be on the Marketplace.

    An expression built entirely from optional poses does nothing on most
    heads, so each one must be recognisable from the required set alone.
    """
    for name, poses in EXPRESSIONS.items():
        if not poses:
            continue
        required = sum(1 for control in poses if control in REQUIRED)
        assert required >= 1, f"{name} does nothing on a minimally-compliant head"


def test_a_line_moves_the_mouth_through_its_own_syllables():
    shapes = visemes("Tu peux rien faire")
    assert shapes, "a line with words must produce mouth shapes"
    assert set(shapes) <= set("AEOMFC")
    # Open on vowels, closed on the p of "peux", teeth on the f of "faire".
    assert "A" in shapes or "E" in shapes or "O" in shapes
    assert "M" in shapes and "F" in shapes


def test_a_run_of_vowels_is_one_shape_not_three_flutters():
    assert visemes("oui") == ["O", "M"]


def test_silence_produces_no_mouth():
    assert visemes("...") == []
    assert visemes("") == []


def test_speaking_returns_when_the_mouth_finishes():
    track = FaceTrack(actor="Hero")
    end = speak(track, 2.0, "Tu peux rien faire")
    assert end > 2.0
    assert track.keys and min(key.at for key in track.keys) >= 0.0


def test_a_new_expression_releases_the_one_before_it():
    """Otherwise a raised brow from three beats ago is still raised under a
    smile, and the face slowly accumulates into a grimace."""
    track = FaceTrack(actor="Hero")
    track.add(0.0, EXPRESSIONS["angry"])
    track.add(2.0, EXPRESSIONS["laughing"])
    released = [k for k in track.keys if k.control == "Corrugator" and k.at >= 2.0]
    assert released and released[-1].value == 0.0


def test_a_cast_does_not_blink_in_unison():
    first = [when for when, poses in blinks(10.0, 0.0) if poses]
    second = [when for when, poses in blinks(10.0, 1.3) if poses]
    assert first and second and first != second


def test_a_scene_comes_out_with_a_performance_on_it():
    scene = Scene.from_dict(
        {
            "name": "Mot",
            "actors": [{"name": "Hero", "rig": "R15"}],
            "cues": [{"id": "beat", "actor": "Hero", "at": 0.0, "prompt": "il parle", "duration": 3.0}],
            "events": [
                {"kind": "face", "actor": "Hero", "cue": "beat", "expression": "angry"},
                {"kind": "line", "actor": "Hero", "cue": "beat", "offset": 0.5,
                 "text": "Tu peux rien faire"},
            ],
        }
    )
    built = build_scene(scene, planner="offline")
    track = built.faces["Hero"]
    assert "Corrugator" in track.controls(), "the anger has to reach the face"
    assert "JawDrop" in track.controls(), "the line has to move the jaw"
    assert "LeftEyeClosed" in track.controls(), "a face that never blinks is a corpse"


def test_the_performance_reaches_the_script(tmp_path):
    from linen.scene import write_scene_script

    scene = Scene.from_dict(
        {
            "name": "Mot",
            "actors": [{"name": "Hero", "rig": "R15"}],
            "cues": [{"id": "beat", "actor": "Hero", "at": 0.0, "prompt": "il parle", "duration": 2.0}],
            "events": [{"kind": "face", "actor": "Hero", "cue": "beat", "expression": "sad"}],
        }
    )
    script = write_scene_script(build_scene(scene, planner="offline"), tmp_path / "S.client.luau").read_text()
    assert "local FACES" in script
    assert 'control = "LeftInnerBrowRaiser"' in script
    assert "driveFaces" in script, "the curve has to be driven, not set once"
    assert "AudioTextToSpeech" in script, "a line is spoken, not only printed"


def test_the_marker_no_longer_fights_the_curve(tmp_path):
    """Setting the expression on the marker as well would stamp over the ease."""
    from linen.scene import write_scene_script

    scene = Scene.from_dict(
        {
            "name": "Mot",
            "actors": [{"name": "Hero", "rig": "R15"}],
            "cues": [{"id": "beat", "actor": "Hero", "at": 0.0, "prompt": "marche"}],
            "events": [{"kind": "face", "actor": "Hero", "cue": "beat", "expression": "angry"}],
        }
    )
    script = write_scene_script(build_scene(scene, planner="offline"), tmp_path / "S.client.luau").read_text()
    assert "setExpression(" not in script


@pytest.mark.parametrize("name", sorted(EXPRESSIONS))
def test_no_pose_is_outside_the_zero_to_one_range(name):
    """FaceControls clamps, so a value over one is a silent truncation."""
    for control, value in EXPRESSIONS[name].items():
        assert 0.0 <= value <= 1.0, f"{name}.{control} = {value}"
