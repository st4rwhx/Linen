"""Making a hand land on the other character.

This is the one thing no capture library and no generation service can do. A
capture is solo: it knows what a body doing a shove looks like, and it cannot
know that this hand must close on that collar, on a character of that height,
standing there. The information is not in any clip, at any price — but it is
in the scene, which knows where both bodies are on every frame.
"""
from __future__ import annotations

import numpy as np
import pytest

from linen.clip import IDENTITY_QUAT, AnimationClip
from linen.rigs import get_rig
from linen.rigs.kinematics import place_rotations
from linen.scene import Scene, SceneError, build_scene
from linen.scene.contact import base_frame, solve_reach


def _still(rig_name: str = "R15", frames: int = 30) -> AnimationClip:
    rig = get_rig(rig_name)
    return AnimationClip(
        rig=rig,
        fps=30.0,
        rotations={p: np.tile(IDENTITY_QUAT, (frames, 1)) for p in rig.animated_parts},
        name="Still",
    )


def _hand(clip: AnimationClip, frame: int, part: str = "RightHand") -> np.ndarray:
    pose = {name: track[frame] for name, track in clip.rotations.items()}
    return place_rotations(clip.rig, pose)[part][0]


def test_a_reachable_target_is_reached_exactly():
    clip = _still()
    target = np.array([0.5, 0.9, -1.2])
    fixed, shortfall = solve_reach(
        clip, base_frame((0, 0, 0), 0.0), "RightHand", {f: target for f in range(8, 18)},
        blend_frames=3,
    )
    assert shortfall < 1e-3
    assert np.allclose(_hand(fixed, 12), target, atol=1e-3)


def test_an_unreachable_target_is_reported_in_studs_not_absorbed():
    """A Roblox part has a fixed size. Stretching one is not an option, so an
    arm that cannot reach is aimed as far as it goes and says how far short."""
    clip = _still()
    near, far = np.array([0.4, 0.9, -1.2]), np.array([0.4, 0.9, -4.0])
    _, close = solve_reach(clip, base_frame((0, 0, 0), 0.0), "RightHand", {10: near}, blend_frames=2)
    _, distant = solve_reach(clip, base_frame((0, 0, 0), 0.0), "RightHand", {10: far}, blend_frames=2)
    assert close < 1e-3
    assert distant > 1.0, "an arm three studs too short must say so"


def test_the_correction_eases_in_and_out_instead_of_snapping():
    clip = _still()
    target = np.array([0.5, 0.9, -1.2])
    fixed, _ = solve_reach(
        clip, base_frame((0, 0, 0), 0.0), "RightHand", {f: target for f in range(15, 20)},
        blend_frames=6,
    )
    # Untouched well before, fully there inside, and monotone in between: a
    # hand that teleports onto its mark reads as a glitch even when the mark
    # is right.
    assert np.allclose(_hand(fixed, 0), _hand(_still(), 0), atol=1e-6)
    assert np.allclose(_hand(fixed, 17), target, atol=1e-3)
    approach = [float(np.linalg.norm(_hand(fixed, f) - target)) for f in range(9, 16)]
    assert approach == sorted(approach, reverse=True), approach


def test_frames_outside_the_hold_and_its_blend_are_left_alone():
    clip = _still()
    fixed, _ = solve_reach(
        clip, base_frame((0, 0, 0), 0.0), "RightHand", {12: np.array([0.5, 0.9, -1.2])},
        blend_frames=3,
    )
    for frame in (0, 1, 25, 29):
        assert np.allclose(_hand(fixed, frame), _hand(clip, frame), atol=1e-9)


def test_the_other_arm_is_not_moved():
    clip = _still()
    fixed, _ = solve_reach(
        clip, base_frame((0, 0, 0), 0.0), "RightHand", {12: np.array([0.5, 0.9, -1.2])},
        blend_frames=3,
    )
    assert np.allclose(_hand(fixed, 12, "LeftHand"), _hand(clip, 12, "LeftHand"), atol=1e-9)


def test_where_the_actor_stands_is_part_of_the_answer():
    """The same world target needs a different arm depending on where you are.

    Solving in the actor's own frame without the staging would put every hand
    in the same place regardless of who is standing where.
    """
    clip = _still()
    target = np.array([0.5, 0.9, -1.2])
    here, _ = solve_reach(clip, base_frame((0, 0, 0), 0.0), "RightHand", {12: target}, blend_frames=2)
    away, _ = solve_reach(clip, base_frame((3, 0, 0), 0.0), "RightHand", {12: target}, blend_frames=2)
    assert not np.allclose(_hand(here, 12), _hand(away, 12), atol=1e-3)


def _fight(**contact) -> Scene:
    event = {
        "kind": "contact",
        "actor": "Hero",
        "cue": "push",
        "limb": "RightHand",
        "hold": 0.4,
        "target_actor": "Enemy",
        "target_part": "UpperTorso",
    }
    event.update(contact)
    return Scene.from_dict(
        {
            "name": "Prise",
            "actors": [
                {"name": "Hero", "rig": "R15", "position": [0, 2.44, 0], "facing": "Enemy"},
                {"name": "Enemy", "rig": "R15", "position": [0, 2.44, -1.5], "facing": "Hero"},
            ],
            "cues": [
                {"id": "push", "actor": "Hero", "at": 0.0, "prompt": "coup de poing"},
                {"id": "take", "actor": "Enemy", "at": 0.0, "prompt": "il encaisse"},
            ],
            "events": [event],
        }
    )


def test_a_scene_solves_its_contacts_into_the_animation():
    built = build_scene(_fight(), planner="offline")
    assert len(built.reaches) == 1
    reach = built.reaches[0]
    assert reach.actor == "Hero" and reach.target == "Enemy.UpperTorso"
    assert reach.shortfall < 1.0, reach.line()

    # And it actually changed the clip: without the contact the hand is
    # somewhere else entirely.
    plain = build_scene(
        Scene.from_dict({**_fight().to_dict(), "events": []}), planner="offline"
    )
    frame = round(0.2 * 30)
    assert not np.allclose(
        _hand(built.clips["Hero"], frame), _hand(plain.clips["Hero"], frame), atol=1e-3
    )


def test_a_contact_is_not_also_fired_as_a_marker():
    """It is solved into the animation. A marker would tell the runtime to do
    a thing that has already been done."""
    built = build_scene(_fight(), planner="offline")
    for by_frame in built.markers.values():
        for entries in by_frame.values():
            assert all("contact" not in name for name, _ in entries)


def test_reaching_for_a_part_the_rig_does_not_have_says_so():
    with pytest.raises(SceneError, match="not a part of a R15 rig"):
        build_scene(_fight(target_part="Tail"), planner="offline")


def test_reaching_for_the_scenery_is_refused_rather_than_aimed_at_the_origin():
    with pytest.raises(SceneError, match="not solved yet"):
        build_scene(_fight(target_actor=None, target_part="Mur"), planner="offline")


def test_an_unknown_limb_names_the_ones_that_exist():
    from linen.scene.schema import SceneError as SchemaError

    with pytest.raises(SchemaError, match="unknown limb"):
        _fight(limb="RightFoot").validate()


def test_nobody_reaches_for_themselves():
    from linen.scene.schema import SceneError as SchemaError

    with pytest.raises(SchemaError, match="cannot reach for themselves"):
        _fight(target_actor="Hero").validate()


def test_an_r6_arm_is_aimed_because_it_has_no_elbow_to_bend():
    """One rigid part from shoulder to fingertips: the hand reaches a sphere
    and nothing inside it. Aiming is the best a rigid limb can do."""
    clip = _still("R6")
    target = np.array([0.5, 0.9, -1.2])
    fixed, shortfall = solve_reach(
        clip, base_frame((0, 0, 0), 0.0), "Right Arm", {12: target}, blend_frames=2
    )
    moved = _hand(fixed, 12, "Right Arm")
    assert not np.allclose(moved, _hand(clip, 12, "Right Arm"), atol=1e-3)
    assert shortfall >= 0.0


# --- the camera -------------------------------------------------------------


def _script(scene, tmp_path):
    from linen.scene import build_scene, write_scene_script

    built = build_scene(scene, planner="offline")
    return write_scene_script(built, tmp_path / "S.client.luau").read_text()


def _with_shot(**shot):
    base = {"id": "wide", "position": [7, 4, 4], "look_at": "Hero"}
    base.update(shot)
    return Scene.from_dict(
        {
            "name": "Plan",
            "actors": [{"name": "Hero", "rig": "R15"}],
            "cues": [{"id": "beat", "actor": "Hero", "at": 0.0, "prompt": "marche"}],
            "shots": [base],
            "events": [{"kind": "camera", "shot": "wide", "cue": "beat"}],
        }
    )


def test_the_camera_refuses_to_run_on_a_server(tmp_path):
    """`workspace.CurrentCamera` is nil on a server.

    The same code as a Script stages every body and then shows nobody
    anything, with no error — which is how this fails without looking like a
    failure. It has to say so instead.
    """
    script = _script(_with_shot(), tmp_path)
    assert "RunService:IsClient()" in script
    assert "StarterPlayerScripts" in script
    assert script.index("RunService:IsClient()") < script.index(
        "local camera = workspace.CurrentCamera"
    ), "the guard has to come before the camera is reached for"


def test_an_orbit_and_a_follow_reach_the_script(tmp_path):
    script = _script(_with_shot(kind="orbit", orbit_speed=30), tmp_path)
    assert 'kind = "orbit"' in script and "orbitSpeed = 30" in script
    assert "BindToRenderStep" in script, (
        "an orbit has to be driven per frame; a tween to a fixed CFrame cannot "
        "follow a subject that moves"
    )


def test_a_follow_offset_survives_the_json_round_trip(tmp_path):
    import json

    scene = _with_shot(kind="follow", follow_offset=[2.0, 1.5, 6.0], follow_lag=0.4)
    again = Scene.from_dict(json.loads(json.dumps(scene.to_dict())))
    assert again.shots[0].follow_offset == (2.0, 1.5, 6.0)
    assert "followOffset = Vector3.new(2, 1.5, 6)" in _script(again, tmp_path)


def test_an_orbit_that_does_not_turn_is_rejected():
    with pytest.raises(SceneError, match="static shot written the hard way"):
        _with_shot(kind="orbit", orbit_speed=0).validate()


def test_an_unknown_shot_kind_names_the_ones_that_exist():
    with pytest.raises(SceneError, match="unknown kind"):
        _with_shot(kind="dolly").validate()


def test_the_render_loop_is_torn_down_when_the_scene_ends(tmp_path):
    """A bound render step outlives the scene and keeps the camera hostage."""
    script = _script(_with_shot(), tmp_path)
    assert "UnbindFromRenderStep" in script
    assert "releaseCamera()" in script
