from __future__ import annotations

import numpy as np
import pytest
from conftest import make_track

from linen.math3d import euler_degrees_to_quat, quat_angle
from linen.retarget import LandmarkTrack, SolveOptions, solve_clip
from linen.retarget.landmarks import MEDIAPIPE_POSE
from linen.rigs import R6, R15

STILL = SolveOptions(smoothing_frames=0)


def max_angle_deg(clip, part: str) -> float:
    identity = np.tile([0.0, 0.0, 0.0, 1.0], (clip.frame_count, 1))
    return float(np.rad2deg(quat_angle(clip.rotations[part], identity)).max())


def test_rest_pose_solves_to_identity_on_every_joint(rest_track):
    clip = solve_clip(R15, rest_track, STILL)
    worst = {part: max_angle_deg(clip, part) for part in R15.animated_parts}
    assert max(worst.values()) < 1.0, worst


def test_rest_pose_solves_to_identity_on_r6(rest_track):
    clip = solve_clip(R6, rest_track, STILL)
    assert max(max_angle_deg(clip, part) for part in R6.animated_parts) < 1.0


def test_t_pose_matches_the_authored_t_pose():
    # The retargeter and the pose book have to agree on which way is which; if
    # they disagree, mocap and prompt-driven clips would mirror each other.
    track = make_track(
        {
            "left_elbow": (-0.50, 1.40, 0.0),
            "left_wrist": (-0.75, 1.40, 0.0),
            "left_index": (-0.85, 1.40, 0.0),
            "left_pinky": (-0.85, 1.40, 0.0),
            "right_elbow": (0.50, 1.40, 0.0),
            "right_wrist": (0.75, 1.40, 0.0),
            "right_index": (0.85, 1.40, 0.0),
            "right_pinky": (0.85, 1.40, 0.0),
        }
    )
    clip = solve_clip(R15, track, STILL)

    expected_left = euler_degrees_to_quat(np.array([0.0, 0.0, -90.0]))
    expected_right = euler_degrees_to_quat(np.array([0.0, 0.0, 90.0]))
    assert np.rad2deg(quat_angle(clip.rotations["LeftUpperArm"][0], expected_left)) < 1.0
    assert np.rad2deg(quat_angle(clip.rotations["RightUpperArm"][0], expected_right)) < 1.0


def test_forward_arm_raise_is_positive_x():
    track = make_track(
        {
            "left_elbow": (-0.20, 1.40, -0.28),
            "left_wrist": (-0.20, 1.40, -0.52),
            "left_index": (-0.20, 1.40, -0.65),
            "left_pinky": (-0.20, 1.40, -0.65),
        }
    )
    clip = solve_clip(R15, track, STILL)
    expected = euler_degrees_to_quat(np.array([90.0, 0.0, 0.0]))
    assert np.rad2deg(quat_angle(clip.rotations["LeftUpperArm"][0], expected)) < 2.0


def test_bent_elbow_bends_forwards_not_backwards():
    track = make_track(
        {
            "left_wrist": (-0.20, 1.12, -0.24),
            "left_index": (-0.20, 1.12, -0.34),
            "left_pinky": (-0.20, 1.12, -0.34),
        }
    )
    clip = solve_clip(R15, track, STILL)
    expected = euler_degrees_to_quat(np.array([90.0, 0.0, 0.0]))
    assert np.rad2deg(quat_angle(clip.rotations["LeftLowerArm"][0], expected)) < 3.0


def test_bent_knee_bends_backwards():
    track = make_track(
        {
            "left_ankle": (-0.10, 0.50, 0.42),
            "left_heel": (-0.10, 0.53, 0.48),
            "left_foot_index": (-0.10, 0.45, 0.30),
        }
    )
    clip = solve_clip(R15, track, STILL)
    # Knee flexion is a negative X rotation; the sign is what the pose book and
    # the chain-normal inversion both depend on.
    expected = euler_degrees_to_quat(np.array([-90.0, 0.0, 0.0]))
    assert np.rad2deg(quat_angle(clip.rotations["LeftLowerLeg"][0], expected)) < 5.0


def test_solution_is_scale_invariant(rest_track):
    small = solve_clip(R15, rest_track, STILL)
    giant = solve_clip(R15, rest_track.scaled(3.7), STILL)
    for part in R15.animated_parts:
        assert np.allclose(small.rotations[part], giant.rotations[part], atol=1e-6)


def test_untracked_landmarks_hold_the_parent_pose():
    positions = make_track().positions.copy()
    positions[:, MEDIAPIPE_POSE.index("left_elbow"), :] = np.nan
    clip = solve_clip(R15, LandmarkTrack(positions, 30.0), STILL)
    assert np.all(np.isfinite(clip.rotations["LeftUpperArm"]))
    assert max_angle_deg(clip, "LeftUpperArm") < 1.0


def test_short_dropouts_are_interpolated_but_long_ones_are_not():
    positions = make_track(frames=120).positions.copy()
    index = MEDIAPIPE_POSE.index("left_knee")
    positions[10:15, index, :] = np.nan  # 5 frames: filled
    positions[40:100, index, :] = np.nan  # 60 frames: left alone
    track = LandmarkTrack(positions, 30.0).fill_gaps(max_gap_frames=30)
    assert np.all(np.isfinite(track.positions[10:15, index]))
    assert np.all(np.isnan(track.positions[40:100, index]))


def test_root_motion_is_off_by_default_and_relative_when_on():
    # Walk the whole body one metre along -Z over the take.
    frames = 30
    positions = make_track(frames=frames).positions.copy()
    drift = np.linspace(0.0, -1.0, frames)
    positions[:, :, 2] += drift[:, None]
    track = LandmarkTrack(positions, 30.0)

    assert solve_clip(R15, track, STILL).root_positions is None

    clip = solve_clip(R15, track, SolveOptions(root_motion=True, smoothing_frames=0))
    assert clip.root_positions is not None
    # Relative to the first frame, and in studs rather than metres.
    assert np.allclose(clip.root_positions[0], 0.0)
    assert clip.root_positions[-1][2] == pytest.approx(-1.0 * R15.studs_per_metre, abs=1e-6)
    assert np.allclose(clip.root_positions[:, :2], 0.0, atol=1e-9)


def test_empty_recording_is_rejected():
    empty = LandmarkTrack(np.zeros((0, len(MEDIAPIPE_POSE), 3)), 30.0)
    with pytest.raises(ValueError, match="empty recording"):
        solve_clip(R15, empty)
