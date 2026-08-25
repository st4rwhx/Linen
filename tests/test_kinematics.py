from __future__ import annotations

import numpy as np
import pytest

from linen.generate.posebook import CYCLES, POSES, resolve_pose
from linen.generate.stride import all_strides, cycle_stride, locomotion_strides
from linen.rigs import R15, get_rig
from linen.rigs.kinematics import forward_kinematics, sole_positions, step_length

# --- forward kinematics ----------------------------------------------------
#: Measured from Roblox's own ClassicMannequin.fbx with
#: tools/read_fbx_skeleton.py. The rig is built from these, so they are the
#: check that it still matches its source.
MANNEQUIN_HEIGHT = 4.977
MANNEQUIN_ROOT_TO_SOLE = 2.433


def test_the_rest_pose_stacks_the_parts_where_the_offsets_say():
    placed = forward_kinematics(R15, {})
    root, _ = placed["HumanoidRootPart"]
    assert np.allclose(root, 0.0)

    assert placed["Head"][0][1] > placed["UpperTorso"][0][1] > placed["LowerTorso"][0][1]
    assert placed["LeftFoot"][0][1] < placed["LeftLowerLeg"][0][1] < placed["LeftUpperLeg"][0][1]
    assert placed["LeftHand"][0][1] < placed["LeftLowerArm"][0][1] < placed["LeftUpperArm"][0][1]


def test_the_rig_still_matches_the_mannequin_it_was_measured_from():
    """Guards the number every other measurement hangs off.

    The rig's proportions were wrong twice — once by a factor of two — and
    neither time did any test notice, because nothing compared them to anything
    outside the file. This does.
    """
    placed = forward_kinematics(R15, {})
    top = placed["Head"][0][1] + R15.part("Head").size[1] / 2
    sole = placed["LeftFoot"][0][1] - R15.part("LeftFoot").size[1] / 2

    assert top - sole == pytest.approx(MANNEQUIN_HEIGHT, abs=0.02)
    assert -sole == pytest.approx(MANNEQUIN_ROOT_TO_SOLE, abs=0.02)


def test_the_rest_pose_is_left_right_symmetric():
    placed = forward_kinematics(R15, {})
    for left, right in (
        ("LeftUpperArm", "RightUpperArm"),
        ("LeftFoot", "RightFoot"),
        ("LeftHand", "RightHand"),
    ):
        lp, rp = placed[left][0], placed[right][0]
        assert lp[0] == pytest.approx(-rp[0])
        assert lp[1] == pytest.approx(rp[1])
        assert lp[2] == pytest.approx(rp[2])


def test_a_joint_rotates_about_its_pivot_not_its_centre():
    """Rotating about the part's centre swings a bent knee off the thigh."""
    bent = forward_kinematics(R15, {"LeftLowerLeg": (-90.0, 0.0, 0.0)})
    rest = forward_kinematics(R15, {})

    # The knee itself must not move: only what hangs below it does.
    knee_bent = bent["LeftLowerLeg"][0] + bent["LeftLowerLeg"][1] @ np.array(
        [0.0, R15.part("LeftLowerLeg").size[1] / 2.0, 0.0]
    )
    knee_rest = rest["LeftLowerLeg"][0] + np.array(
        [0.0, R15.part("LeftLowerLeg").size[1] / 2.0, 0.0]
    )
    assert np.allclose(knee_bent, knee_rest, atol=1e-6)
    # And the foot has swung backwards by about the length of the shin, rather
    # than staying put. Expressed against the rig's own geometry so it keeps
    # meaning the same thing if the proportions are corrected again.
    shin = R15.part("LeftLowerLeg").size[1]
    swing = bent["LeftFoot"][0][2] - rest["LeftFoot"][0][2]
    assert swing > shin * 0.8, f"foot only moved {swing:.2f} for a {shin} shin"


def test_raising_an_arm_forward_moves_the_hand_forward():
    placed = forward_kinematics(R15, {"LeftUpperArm": (90.0, 0.0, 0.0)})
    rest = forward_kinematics(R15, {})
    # Roblox characters face -Z, so forward is decreasing Z.
    assert placed["LeftHand"][0][2] < rest["LeftHand"][0][2] - 1.0


def test_soles_sit_below_the_foot_parts():
    placed = forward_kinematics(R15, {})
    for name, sole in sole_positions(R15, {}).items():
        assert sole[1] < placed[name][0][1]


def test_forward_kinematics_never_produces_a_non_finite_placement():
    for name, pose in POSES.items():
        for part, (position, rotation) in forward_kinematics(R15, pose).items():
            assert np.all(np.isfinite(position)), (name, part)
            assert np.all(np.isfinite(rotation)), (name, part)


# --- stride ----------------------------------------------------------------
def test_a_contact_pose_separates_the_feet_and_a_passing_pose_does_not():
    contact = step_length(R15, resolve_pose("walk_contact_left"))
    passing = step_length(R15, resolve_pose("walk_pass_left"))
    assert contact > passing
    assert contact > 1.0


def test_running_strides_further_and_faster_than_walking():
    strides = all_strides()
    assert strides["run"].distance > strides["walk"].distance
    assert strides["run"].speed > strides["walk"].speed


def test_gesture_cycles_cover_no_ground():
    for name in ("wave_left", "wave_right", "talk", "nod", "shake_head"):
        stride = all_strides()[name]
        assert stride.steps == 0, name
        assert stride.distance == 0.0, name


def test_only_gaits_appear_among_the_locomotion_strides():
    assert set(locomotion_strides()) == {"walk", "run"}


CHARACTER_HEIGHT_STUDS = 5.0
ROBLOX_DEFAULT_WALKSPEED = 16.0


def test_gait_speeds_are_plausible_for_a_body_of_this_size():
    """Judged in body-heights per second, which is scale-free.

    A person walks at roughly 0.7-0.9 of their own height per second and runs at
    two to three. Measuring against Roblox's default WalkSpeed instead — the
    obvious thing to do — encodes that default as correct, and it is not.
    """
    strides = locomotion_strides()
    walk = strides["walk"].speed / CHARACTER_HEIGHT_STUDS
    run = strides["run"].speed / CHARACTER_HEIGHT_STUDS

    assert 0.55 < walk < 1.1, f"{walk:.2f} body-heights/s is not a walk"
    assert 1.5 < run < 3.2, f"{run:.2f} body-heights/s is not a run"
    assert run > walk * 2


def test_roblox_default_walkspeed_is_a_sprint_for_a_character_this_size():
    """Worth asserting, because it decides what the runtime should blend to.

    16 studs/s on a five-stud character is 3.2 body-heights per second, which is
    sprinting, not walking. So at Roblox's default the blend should sit on the
    run cycle — and the walk cycle only becomes usable once a game lowers
    WalkSpeed, which is the honest reading rather than stretching the walk to
    cover a speed no one walks at.
    """
    strides = locomotion_strides()
    assert ROBLOX_DEFAULT_WALKSPEED / CHARACTER_HEIGHT_STUDS > 3.0
    # The run must still reach it within the playback clamp the runtime applies.
    assert ROBLOX_DEFAULT_WALKSPEED / strides["run"].speed <= 2.2
    assert ROBLOX_DEFAULT_WALKSPEED / strides["walk"].speed > 2.2


def test_stride_follows_the_poses_rather_than_being_declared():
    """Widen the contact pose and the stride has to grow with it.

    The runtime divides ground speed by this number, so a stride that stopped
    tracking the poses would silently reintroduce the foot sliding it exists to
    remove.
    """
    from dataclasses import replace

    from linen.generate import posebook

    original = cycle_stride(CYCLES["walk"], R15)
    wider = dict(POSES)
    wider["walk_contact_left"] = {
        **POSES["walk_contact_left"],
        "LeftUpperLeg": (45.0, 0.0, -3.0),
        "RightUpperLeg": (-40.0, 0.0, 3.0),
    }

    saved = posebook.POSES
    try:
        posebook.POSES = wider  # type: ignore[assignment]
        stretched = cycle_stride(replace(CYCLES["walk"]), get_rig("R15"))
    finally:
        posebook.POSES = saved  # type: ignore[assignment]

    assert stretched.distance > original.distance
