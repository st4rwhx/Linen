from __future__ import annotations

import numpy as np
import pytest

from linen.generate.posebook import CYCLES, POSES, resolve_pose
from linen.generate.stride import all_strides, cycle_stride, locomotion_strides
from linen.rigs import R15, get_rig
from linen.rigs.kinematics import forward_kinematics, sole_positions, step_length


# --- forward kinematics ----------------------------------------------------
def test_the_rest_pose_stacks_the_parts_where_the_offsets_say():
    placed = forward_kinematics(R15, {})
    root, _ = placed["HumanoidRootPart"]
    assert np.allclose(root, 0.0)

    # UpperTorso sits one stud above LowerTorso, which sits at the root.
    assert placed["UpperTorso"][0][1] == pytest.approx(1.0)
    # The head is above the chest, the feet below the hips.
    assert placed["Head"][0][1] > placed["UpperTorso"][0][1]
    assert placed["LeftFoot"][0][1] < placed["LeftUpperLeg"][0][1]


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
    # And the foot has swung backwards, not stayed put.
    assert bent["LeftFoot"][0][2] > rest["LeftFoot"][0][2] + 1.0


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


def test_strides_land_in_a_plausible_range_for_roblox():
    # Roblox's default WalkSpeed is 16 studs/s. A walk that naturally covered
    # that much would leave no reason to ever blend to a run, and one that
    # covered a fraction of it would be played at a comical rate.
    strides = locomotion_strides()
    assert 4.0 < strides["walk"].speed < 12.0
    assert strides["walk"].speed < 16.0 < strides["run"].speed * 1.4


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
