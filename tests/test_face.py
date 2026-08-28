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


# --- what the deep audit found ----------------------------------------------


def test_no_two_keys_disagree_about_one_control_on_one_frame():
    """The script drives the face by walking the keys in time order.

    Two keys at the same instant with different values leave it to decide by
    list position which one wins, and nothing about the list position means
    anything. It happened whenever a beat landed inside its own ease of the
    start of the scene: the ease-from key clamped to zero, onto its target.
    """
    import json
    from pathlib import Path

    scene = Scene.from_dict(json.loads(Path("examples/contre.scene.json").read_text()))
    for actor, track in build_scene(scene, planner="offline").faces.items():
        seen: dict[tuple[float, str], float] = {}
        for key in sorted(track.keys, key=lambda k: (k.at, k.control)):
            slot = (round(key.at, 4), key.control)
            assert abs(seen.get(slot, key.value) - key.value) < 1e-9, (
                f"{actor}: {key.control} is both {seen[slot]} and {key.value} at {key.at}"
            )
            seen[slot] = key.value


def test_no_cinematic_opens_on_a_character_with_its_eyes_shut():
    """The first actor's blink offset was zero, so it blinked at exactly 0.000.

    With no room ahead of it to ease into, that is not a blink — it is a
    cinematic whose first frame is a face with its eyes closed.
    """
    for offset in (0.0, 1.3, 2.6, 3.9, 4.0, 8.0):
        first = min(when for when, poses in blinks(20.0, offset) if poses)
        assert first > 0.2, f"offset {offset} blinks at {first}"


def test_a_short_scene_still_blinks():
    """Pushing the first blink away from zero must not push it off the end."""
    for offset in (0.0, 1.3, 2.6):
        assert [when for when, poses in blinks(3.5, offset) if poses], offset


def test_a_blink_during_a_wince_returns_the_eyes_to_the_wince():
    """`pain` holds the lids at 0.8. Opening a blink back to zero pops the eyes
    wide open in the middle of it, which reads as the expression dropping."""
    scene = Scene.from_dict(
        {
            "name": "Coup",
            "actors": [{"name": "Hero", "rig": "R15"}],
            "cues": [{"id": "beat", "actor": "Hero", "at": 0.0, "prompt": "il encaisse",
                      "duration": 6.0}],
            "events": [{"kind": "face", "actor": "Hero", "cue": "beat", "offset": 4.2,
                        "expression": "pain"}],
        }
    )
    keys = sorted(build_scene(scene, planner="offline").faces["Hero"].keys,
                  key=lambda k: (k.at, k.control))
    lid = [(k.at, k.value) for k in keys if k.control == "LeftEyeClosed"]
    winced = [at for at, value in lid if abs(value - 0.8) < 1e-6]
    assert winced, "the wince has to reach the lids at all"
    after = [value for at, value in lid if at > max(winced)]
    assert not after or after[-1] > 0.5, (
        f"the eyes end up at {after[-1]} with the wince still on: {lid}"
    )


def test_a_key_written_after_the_track_is_built_cannot_carry_a_stale_value():
    """Every key carries the value of every control the face is already holding.

    So a beat written into the middle of an already-built track is computed
    against a face that no longer exists. The blinks used to be added last,
    and a line spoken four seconds later still believed the eyes were held
    half shut by an expression a blink had long since released — the eyes
    snapped shut mid-sentence. Everything is laid out and applied in time
    order now, so there is no "later pass" to disagree with.
    """
    scene = Scene.from_dict(
        {
            "name": "Suite",
            "actors": [{"name": "Hero", "rig": "R15"}],
            "cues": [{"id": "beat", "actor": "Hero", "at": 0.0, "prompt": "il parle",
                      "duration": 8.0}],
            "events": [
                {"kind": "face", "actor": "Hero", "cue": "beat", "offset": 1.0,
                 "expression": "pain"},
                {"kind": "face", "actor": "Hero", "cue": "beat", "offset": 2.0,
                 "expression": "neutral"},
                {"kind": "line", "actor": "Hero", "cue": "beat", "offset": 5.5,
                 "text": "je vais bien"},
            ],
        }
    )
    keys = sorted(build_scene(scene, planner="offline").faces["Hero"].keys,
                  key=lambda k: (k.at, k.control))
    during = [
        (k.at, k.value)
        for k in keys
        if k.control == "LeftEyeClosed" and 5.4 < k.at < 7.0 and k.value > 0.5
    ]
    assert not during, f"the eyes close during the line, four seconds late: {during}"
