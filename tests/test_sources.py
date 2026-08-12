from __future__ import annotations

import numpy as np
import pytest

from linen.math3d import quat_angle
from linen.retarget import SolveOptions, solve_clip
from linen.rigs import R15
from linen.sources import BvhError, get_skeleton, load_bvh, parse_bvh, to_landmark_track

STILL = SolveOptions(smoothing_frames=0)

# A minimal Mixamo-named skeleton standing in the Roblox rest pose: arms down,
# legs straight, toes forward along -Z. Offsets are in centimetres.
REST_BVH = """\
HIERARCHY
ROOT Hips
{
  OFFSET 0.00 92.00 0.00
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  JOINT Spine
  {
    OFFSET 0.00 24.00 0.00
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT Neck
    {
      OFFSET 0.00 24.00 0.00
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT Head
      {
        OFFSET 0.00 8.00 0.00
        CHANNELS 3 Zrotation Xrotation Yrotation
        End Site
        {
          OFFSET 0.00 17.00 0.00
        }
      }
    }
    JOINT LeftArm
    {
      OFFSET -20.00 24.00 0.00
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT LeftForeArm
      {
        OFFSET 0.00 -28.00 0.00
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT LeftHand
        {
          OFFSET 0.00 -24.00 0.00
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {
            OFFSET 0.00 -13.00 0.00
          }
        }
      }
    }
    JOINT RightArm
    {
      OFFSET 20.00 24.00 0.00
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT RightForeArm
      {
        OFFSET 0.00 -28.00 0.00
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT RightHand
        {
          OFFSET 0.00 -24.00 0.00
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {
            OFFSET 0.00 -13.00 0.00
          }
        }
      }
    }
  }
  JOINT LeftUpLeg
  {
    OFFSET -10.00 0.00 0.00
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT LeftLeg
    {
      OFFSET 0.00 -42.00 0.00
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT LeftFoot
      {
        OFFSET 0.00 -42.00 0.00
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT LeftToeBase
        {
          OFFSET 0.00 -8.00 -14.00
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {
            OFFSET 0.00 0.00 -5.00
          }
        }
      }
    }
  }
  JOINT RightUpLeg
  {
    OFFSET 10.00 0.00 0.00
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT RightLeg
    {
      OFFSET 0.00 -42.00 0.00
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT RightFoot
      {
        OFFSET 0.00 -42.00 0.00
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT RightToeBase
        {
          OFFSET 0.00 -8.00 -14.00
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {
            OFFSET 0.00 0.00 -5.00
          }
        }
      }
    }
  }
}
MOTION
Frames: 3
Frame Time: 0.0333333
{rows}
"""

JOINT_COUNT = 23  # 18 channelled joints plus 5 end sites
CHANNELS = 6 + 17 * 3


def bvh_text(rows: list[list[float]] | None = None) -> str:
    # str.format is unusable here — the hierarchy is full of literal braces.
    rows = rows or [[0.0] * CHANNELS for _ in range(3)]
    body = "\n".join(" ".join(f"{v:.4f}" for v in row) for row in rows)
    return REST_BVH.replace("{rows}", body)


@pytest.fixture
def rest_bvh(tmp_path):
    path = tmp_path / "rest.bvh"
    path.write_text(bvh_text())
    return path


# --- parsing ---------------------------------------------------------------
def test_hierarchy_and_motion_are_parsed(rest_bvh):
    motion = parse_bvh(rest_bvh)
    assert len(motion.joints) == JOINT_COUNT
    assert motion.values.shape == (3, CHANNELS)
    assert motion.fps == pytest.approx(30.0, rel=1e-4)
    assert "LeftForeArm" in motion.names
    assert "LeftToeBase_End" in motion.names


def test_forward_kinematics_places_joints_where_the_offsets_say(rest_bvh):
    world = parse_bvh(rest_bvh).world_positions()
    names = parse_bvh(rest_bvh).names
    at = {name: world[0, i] for i, name in enumerate(names)}
    assert np.allclose(at["Hips"], [0, 92, 0])
    assert np.allclose(at["LeftArm"], [-20, 140, 0])
    assert np.allclose(at["LeftHand"], [-20, 88, 0])
    assert np.allclose(at["LeftToeBase"], [-10, 0, -14])


def test_channel_order_is_honoured(rest_bvh, tmp_path):
    # 90 degrees on LeftArm's *Z* channel must swing the arm sideways. Applied
    # as an X rotation instead it would swing forwards, and nothing downstream
    # would notice — the pose stays plausible, it is just the wrong one.
    skeleton = parse_bvh(rest_bvh)
    arm = skeleton.joints[skeleton.names.index("LeftArm")]
    assert arm.channels[0] == "Zrotation"

    row = [0.0] * CHANNELS
    row[arm.channel_start] = 90.0
    path = tmp_path / "bent.bvh"
    path.write_text(bvh_text([row] * 3))

    motion = parse_bvh(path)
    hand = motion.world_positions()[0, motion.names.index("LeftHand")]
    assert abs(hand[2]) < 1e-6, "arm should not have moved forwards or back"
    assert hand[0] > -20.0, "arm should have swung sideways"


def test_a_file_without_motion_is_rejected(tmp_path):
    path = tmp_path / "broken.bvh"
    path.write_text("HIERARCHY\nROOT Hips\n{\nOFFSET 0 0 0\n}\n")
    with pytest.raises(BvhError, match="no MOTION"):
        parse_bvh(path)


def test_a_channel_count_mismatch_is_reported(tmp_path):
    path = tmp_path / "short.bvh"
    path.write_text(bvh_text([[0.0] * (CHANNELS - 2) for _ in range(3)]))
    with pytest.raises(BvhError, match="channels but each motion row"):
        parse_bvh(path)


# --- mapping ---------------------------------------------------------------
def test_mapping_fills_the_landmarks_the_rigs_need(rest_bvh):
    track = load_bvh(rest_bvh)
    for landmark in ("left_shoulder", "left_knee", "left_foot_index", "left_ear"):
        column = track.point(landmark)
        assert np.all(np.isfinite(column)), landmark


def test_units_are_converted_to_metres(rest_bvh):
    track = load_bvh(rest_bvh, units="cm")
    # The hip line sits 92 cm up in the file.
    assert track.point("left_hip", "right_hip")[0][1] == pytest.approx(0.92)


def test_reconstructed_heel_sits_under_the_ankle_at_toe_height(rest_bvh):
    track = load_bvh(rest_bvh)
    heel = track.point("left_heel")[0]
    ankle = track.point("left_ankle")[0]
    toe = track.point("left_foot_index")[0]
    assert heel[0] == pytest.approx(ankle[0])
    assert heel[2] == pytest.approx(ankle[2])
    assert heel[1] == pytest.approx(toe[1])


def test_a_skeleton_missing_joints_names_them(tmp_path):
    path = tmp_path / "legless.bvh"
    path.write_text(bvh_text().replace("LeftUpLeg", "Bone12").replace("LeftLeg", "Bone13"))
    with pytest.raises(ValueError, match="left_hip"):
        load_bvh(path)


def test_an_unknown_skeleton_lists_the_known_ones():
    with pytest.raises(ValueError, match="unknown skeleton"):
        get_skeleton("openpose")


def test_smpl_and_humanml3d_are_aliases_of_mixamo():
    assert get_skeleton("smpl") is get_skeleton("mixamo")
    assert get_skeleton("humanml3d") is get_skeleton("mixamo")


# --- end to end ------------------------------------------------------------
def test_a_rest_pose_bvh_retargets_to_near_identity(rest_bvh):
    # The same guarantee the FreeMoCap path has: a neutral standing skeleton
    # must not introduce rotations of its own on the way in.
    clip = solve_clip(R15, load_bvh(rest_bvh), STILL)
    identity = np.tile([0.0, 0.0, 0.0, 1.0], (clip.frame_count, 1))
    worst = {
        part: float(np.rad2deg(quat_angle(clip.rotations[part], identity)).max())
        for part in R15.animated_parts
    }
    assert max(worst.values()) < 2.0, worst


def test_bvh_and_freemocap_paths_agree_on_the_same_pose(rest_bvh):
    from conftest import make_track

    bvh_clip = solve_clip(R15, load_bvh(rest_bvh), STILL)
    mocap_clip = solve_clip(R15, make_track(frames=3), STILL)
    for part in R15.animated_parts:
        delta = np.rad2deg(quat_angle(bvh_clip.rotations[part][0], mocap_clip.rotations[part][0]))
        assert delta < 2.0, (part, delta)


def test_fps_can_be_overridden(rest_bvh):
    assert load_bvh(rest_bvh, fps=24.0).fps == 24.0


def test_mapping_reports_what_it_resolved(rest_bvh):
    motion = parse_bvh(rest_bvh)
    resolved = get_skeleton("mixamo").resolve(motion.names)
    assert resolved["left_ankle"] == "LeftFoot"
    assert resolved["left_foot_index"] == "LeftToeBase"
    # No finger joints in this file, and the rigs cope without them.
    assert "left_pinky" not in resolved


def test_track_can_be_solved_without_the_optional_hand_landmarks(rest_bvh):
    track = load_bvh(rest_bvh)
    clip = solve_clip(R15, track, STILL)
    assert np.all(np.isfinite(clip.rotations["LeftHand"]))


def test_to_landmark_track_rejects_unknown_units(rest_bvh):
    with pytest.raises(ValueError, match="unknown units"):
        to_landmark_track(parse_bvh(rest_bvh), get_skeleton("mixamo"), units="furlongs")


# --- the Roblox-named skeleton ---------------------------------------------
R15_BVH = REST_BVH.replace("LeftArm", "LeftUpperArm").replace("RightArm", "RightUpperArm") \
    .replace("LeftForeArm", "LeftLowerArm").replace("RightForeArm", "RightLowerArm") \
    .replace("LeftUpLeg", "LeftUpperLeg").replace("RightUpLeg", "RightUpperLeg") \
    .replace("JOINT LeftLeg", "JOINT LeftLowerLeg").replace("JOINT RightLeg", "JOINT RightLowerLeg") \
    .replace("LeftToeBase", "LeftToe").replace("RightToeBase", "RightToe")


def r15_bvh_text() -> str:
    rows = [[0.0] * CHANNELS for _ in range(3)]
    body = "\n".join(" ".join(f"{v:.4f}" for v in row) for row in rows)
    return R15_BVH.replace("{rows}", body)


@pytest.fixture
def r15_bvh(tmp_path):
    path = tmp_path / "roblox.bvh"
    path.write_text(r15_bvh_text())
    return path


def test_a_bvh_with_roblox_part_names_is_understood(r15_bvh):
    # What a Blender R15 rig's deform bones are called, and what Roblox's own
    # exporters emit — the practical route for Mixamo motion, since Mixamo
    # exports FBX and DAE and never BVH.
    motion = parse_bvh(r15_bvh)
    resolved = get_skeleton("r15").resolve(motion.names)
    assert resolved["left_shoulder"] == "LeftUpperArm"
    assert resolved["left_ankle"] == "LeftFoot"
    assert get_skeleton("r15").missing_required(motion.names) == []


def test_roblox_and_blender_r15_are_aliases():
    assert get_skeleton("roblox") is get_skeleton("r15")
    assert get_skeleton("blender-r15") is get_skeleton("r15")


def test_a_roblox_named_rest_pose_retargets_to_near_identity(r15_bvh):
    clip = solve_clip(R15, load_bvh(r15_bvh, skeleton="r15"), STILL)
    identity = np.tile([0.0, 0.0, 0.0, 1.0], (clip.frame_count, 1))
    worst = max(
        float(np.rad2deg(quat_angle(clip.rotations[p], identity)).max())
        for p in R15.animated_parts
    )
    assert worst < 2.0


def test_the_mixamo_mapping_does_not_swallow_a_roblox_named_file(r15_bvh):
    # Wrong --skeleton should fail loudly rather than half-resolve and produce
    # a character animating only from the waist up.
    with pytest.raises(ValueError, match="left_hip|left_shoulder"):
        load_bvh(r15_bvh, skeleton="mixamo")
