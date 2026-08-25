from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from linen.export.luau import rig_limits_module
from linen.generate.posebook import POSES
from linen.math3d import euler_degrees_to_quat, quat_multiply, quat_to_mat, swing_twist
from linen.rigs import R6, R15, get_rig
from linen.rigs.limits import R15_LIMITS, JointKind, limits_for, validate_all

#: A pose may lean a hinge slightly off its axis without looking wrong, but a
#: hinge carrying real off-axis rotation is a ball joint in disguise.
HINGE_OFF_AXIS_TOLERANCE_DEG = 25.0
HINGE_AXIS = np.array([1.0, 0.0, 0.0])


# --- the decomposition itself ----------------------------------------------
def test_a_pure_twist_reads_as_twist_and_no_swing():
    q = euler_degrees_to_quat(np.array([0.0, 40.0, 0.0]))
    swing, twist = swing_twist(q, np.array([0.0, 1.0, 0.0]))
    assert np.rad2deg(swing[0]) == pytest.approx(0.0, abs=1e-6)
    assert np.rad2deg(twist[0]) == pytest.approx(40.0, abs=1e-6)


def test_a_pure_swing_reads_as_swing_and_no_twist():
    q = euler_degrees_to_quat(np.array([30.0, 0.0, 0.0]))
    swing, twist = swing_twist(q, np.array([0.0, 1.0, 0.0]))
    assert np.rad2deg(swing[0]) == pytest.approx(30.0, abs=1e-6)
    assert np.rad2deg(twist[0]) == pytest.approx(0.0, abs=1e-6)


def test_swing_and_twist_recompose_into_the_original_rotation():
    rng = np.random.default_rng(11)
    axis = np.array([0.0, -1.0, 0.0])
    for angles in rng.uniform(-120.0, 120.0, size=(40, 3)):
        q = euler_degrees_to_quat(angles)
        swing, twist = swing_twist(q, axis)
        # Rebuilding from the two parts must land back on the same orientation.
        twist_q = np.concatenate(
            [axis * np.sin(twist[0] / 2.0), [np.cos(twist[0] / 2.0)]]
        )
        rebuilt_swing = quat_multiply(q[None], _conj(twist_q)[None])
        combined = quat_multiply(rebuilt_swing, twist_q[None])[0]
        assert np.allclose(quat_to_mat(combined), quat_to_mat(q), atol=1e-8)
        assert np.rad2deg(swing[0]) <= 180.0 + 1e-6


def _conj(q):
    return np.concatenate([-q[:3], q[3:]])


# --- the data --------------------------------------------------------------
def test_all_limits_are_internally_consistent():
    validate_all()


def test_every_animated_joint_of_both_rigs_has_a_limit():
    for rig in (R15, R6):
        table = limits_for(rig.name)
        for part in rig.parts[1:]:
            assert part.joint in table, (rig.name, part.joint)


def test_elbows_and_knees_are_hinges_not_cones():
    # A ball-and-socket elbow bends sideways, and under an impulse it will.
    for joint in ("LeftElbow", "RightElbow", "LeftKnee", "RightKnee"):
        assert R15_LIMITS[joint].kind is JointKind.HINGE, joint


def test_knees_flex_backwards_and_elbows_forwards():
    assert R15_LIMITS["LeftElbow"].upper > 0 and R15_LIMITS["LeftElbow"].lower == 0
    assert R15_LIMITS["LeftKnee"].lower < 0 and R15_LIMITS["LeftKnee"].upper == 0


def test_neither_hinge_hyperextends():
    for joint in ("LeftElbow", "LeftKnee"):
        limit = R15_LIMITS[joint]
        assert limit.lower == 0.0 or limit.upper == 0.0, joint


def test_the_root_is_welded_rather_than_constrained():
    assert R15_LIMITS["Root"].kind is JointKind.FIXED


def test_the_two_sides_of_the_body_match():
    for joint, limit in R15_LIMITS.items():
        if not joint.startswith("Left"):
            continue
        other = R15_LIMITS["Right" + joint[len("Left") :]]
        assert other.kind is limit.kind
        assert other.responsiveness == limit.responsiveness
        assert other.max_torque == limit.max_torque
        if limit.kind is JointKind.HINGE:
            # Not mirrored: both elbows hinge about their own local +X, and
            # reflecting a pose leaves the X term alone.
            assert (other.lower, other.upper) == (limit.lower, limit.upper)
        else:
            assert other.swing == limit.swing
            assert other.twist == (-limit.twist[1], -limit.twist[0])


def test_proximal_joints_carry_more_torque_than_distal_ones():
    # A wrist driven as hard as a hip reads as stiff, and a hip driven as
    # softly as a wrist cannot hold the body up.
    assert R15_LIMITS["LeftHip"].max_torque > R15_LIMITS["LeftKnee"].max_torque
    assert R15_LIMITS["LeftKnee"].max_torque > R15_LIMITS["LeftAnkle"].max_torque
    assert R15_LIMITS["LeftShoulder"].max_torque > R15_LIMITS["LeftWrist"].max_torque


# --- the generated runtime module ------------------------------------------
def test_the_checked_in_luau_matches_the_python_it_is_generated_from():
    """The physics rig and the animation rig have to stay one system.

    The runtime reads its joint limits from generated Luau. Left to drift, the
    constraints would allow something the poses never do, or forbid something
    they rely on, and the symptom would show up as a snapping ragdoll with no
    obvious cause.
    """
    checked_in = Path(__file__).resolve().parent.parent / "runtime" / "RigLimits.luau"
    assert checked_in.exists(), "run `python -m linen.export.luau runtime/RigLimits.luau`"
    assert checked_in.read_text() == rig_limits_module(), (
        "runtime/RigLimits.luau is stale — regenerate it with "
        "`python -m linen.export.luau runtime/RigLimits.luau`"
    )


def test_the_generated_module_uses_hinges_for_hinge_joints():
    module = rig_limits_module()
    elbow = module.split('["LeftElbow"]')[1][:200]
    assert 'kind = "hinge"' in elbow
    shoulder = module.split('["LeftShoulder"]')[1][:200]
    assert 'kind = "ball"' in shoulder


# --- the two halves have to agree ------------------------------------------
@pytest.mark.parametrize("pose_name", sorted(POSES))
def test_no_authored_pose_asks_for_something_the_joints_forbid(pose_name):
    """The cross-check that makes the physics rig and the pose book one system.

    A pose outside the constraint's range looks fine while an Animator drives
    it and snaps the instant physics takes over — the exact artefact the limits
    exist to prevent, surfacing far from its cause.
    """
    rig = get_rig("R15")
    table = limits_for("R15")

    for part_name, angles in POSES[pose_name].items():
        part = rig.part(part_name)
        limit = table[part.joint]
        if limit.kind is JointKind.FIXED:
            continue

        q = euler_degrees_to_quat(np.array(angles))
        axis = np.array(HINGE_AXIS if limit.kind is JointKind.HINGE else part.aim_axis)
        swing, twist = swing_twist(q, axis)
        swing_deg, twist_deg = float(np.rad2deg(swing[0])), float(np.rad2deg(twist[0]))

        if limit.kind is JointKind.HINGE:
            assert limit.lower - 1e-6 <= twist_deg <= limit.upper + 1e-6, (
                f"{pose_name}/{part_name}: {twist_deg:.1f} deg outside hinge "
                f"{limit.lower}..{limit.upper}"
            )
            assert swing_deg <= HINGE_OFF_AXIS_TOLERANCE_DEG, (
                f"{pose_name}/{part_name}: {swing_deg:.1f} deg off the hinge axis"
            )
        else:
            assert swing_deg <= limit.swing + 1e-6, (
                f"{pose_name}/{part_name}: swing {swing_deg:.1f} deg exceeds "
                f"{limit.swing} on {limit.joint}"
            )
            assert limit.twist[0] - 1e-6 <= twist_deg <= limit.twist[1] + 1e-6, (
                f"{pose_name}/{part_name}: twist {twist_deg:.1f} deg outside "
                f"{limit.twist} on {limit.joint}"
            )


def test_the_checked_in_motion_data_matches_the_python_it_is_generated_from():
    from linen.export.luau import motion_data_module

    checked_in = Path(__file__).resolve().parent.parent / "runtime" / "MotionData.luau"
    assert checked_in.exists(), "run `python -m linen.export.luau runtime`"
    assert checked_in.read_text() == motion_data_module(), (
        "runtime/MotionData.luau is stale — regenerate it with "
        "`python -m linen.export.luau runtime`"
    )
