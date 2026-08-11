from __future__ import annotations

import json

import numpy as np
import pytest

from linen.clip import IDENTITY_QUAT
from linen.generate import MotionPlan, PlanError, build_system_prompt, synthesize
from linen.generate.choreographer import _coerce
from linen.generate.posebook import CYCLES, POSES, mirror
from linen.generate.providers import _parse_json
from linen.generate.schema import json_schema
from linen.math3d import quat_angle
from linen.rigs import R6, R15

WAVE_PLAN = {
    "name": "Wave",
    "fps": 30,
    "loop": False,
    "priority": "Action",
    "segments": [
        {"start": 0.0, "end": 0.4, "pose": "stand_relaxed", "easing": "ease_out"},
        {"start": 0.4, "end": 1.8, "cycle": "wave", "rate": 2.0, "blend_in": 0.2},
        {"start": 1.8, "end": 2.4, "pose": "stand_relaxed", "easing": "overshoot"},
    ],
    "layers": [{"kind": "breathing", "amplitude": 0.5, "rate": 0.3}],
}


def plan(**overrides) -> MotionPlan:
    data = json.loads(json.dumps(WAVE_PLAN))
    data.update(overrides)
    return MotionPlan.from_dict(data)


# --- pose book -------------------------------------------------------------
def test_mirroring_is_an_involution():
    for name, pose in POSES.items():
        assert mirror(mirror(pose)) == pose, name


def test_mirroring_swaps_sides_and_flips_only_y_and_z():
    assert mirror({"LeftUpperArm": (10.0, 20.0, 30.0)}) == {
        "RightUpperArm": (10.0, -20.0, -30.0)
    }


def test_cycles_only_reference_poses_that_exist():
    for cycle in CYCLES.values():
        for phase, pose in cycle.keys:
            assert 0.0 <= phase < 1.0, cycle.name
            assert pose in POSES, pose


def test_every_pose_targets_real_r15_parts():
    known = set(R15.animated_parts)
    for name, pose in POSES.items():
        assert set(pose) <= known, (name, set(pose) - known)


# --- schema ----------------------------------------------------------------
def test_a_hallucinated_pose_name_is_rejected_with_the_vocabulary():
    with pytest.raises(PlanError, match="unknown pose 'backflip'"):
        plan(segments=[{"start": 0.0, "end": 1.0, "pose": "backflip"}])


def test_a_segment_needs_exactly_one_of_pose_or_cycle():
    with pytest.raises(PlanError, match="exactly one"):
        plan(segments=[{"start": 0.0, "end": 1.0}])
    with pytest.raises(PlanError, match="exactly one"):
        plan(segments=[{"start": 0.0, "end": 1.0, "pose": "sit", "cycle": "walk"}])


def test_overlapping_segments_are_rejected():
    with pytest.raises(PlanError, match="overlap"):
        plan(
            segments=[
                {"start": 0.0, "end": 1.0, "pose": "sit"},
                {"start": 0.5, "end": 1.5, "pose": "crouch"},
            ]
        )


def test_segments_are_sorted_on_validation():
    parsed = plan(
        segments=[
            {"start": 1.0, "end": 2.0, "pose": "crouch"},
            {"start": 0.0, "end": 1.0, "pose": "sit"},
        ]
    )
    assert [s.pose for s in parsed.segments] == ["sit", "crouch"]


def test_unknown_top_level_fields_are_rejected():
    with pytest.raises(PlanError, match="unexpected field"):
        plan(joint_angles={"LeftHand": [1, 2, 3]})


def test_plan_survives_a_json_roundtrip():
    original = plan()
    assert MotionPlan.from_dict(original.to_dict()).to_dict() == original.to_dict()


def test_schema_enumerates_the_real_vocabulary():
    schema = json_schema()
    items = schema["properties"]["segments"]["items"]["properties"]
    assert set(items["pose"]["enum"]) == set(POSES)
    assert set(items["cycle"]["enum"]) == set(CYCLES)


def test_system_prompt_lists_every_pose():
    prompt = build_system_prompt()
    for name in POSES:
        assert name in prompt


# --- synthesis -------------------------------------------------------------
def test_synthesis_is_deterministic():
    a = synthesize(plan(layers=[{"kind": "noise", "amplitude": 0.4}]), R15, seed=3)
    b = synthesize(plan(layers=[{"kind": "noise", "amplitude": 0.4}]), R15, seed=3)
    for part in R15.animated_parts:
        assert np.array_equal(a.rotations[part], b.rotations[part])


def test_clip_length_and_metadata_follow_the_plan():
    clip = synthesize(plan(), R15)
    assert clip.frame_count == 73  # 2.4s at 30 fps, inclusive of both ends
    assert clip.duration == pytest.approx(2.4)
    assert clip.name == "Wave"
    assert clip.metadata["plan"]["name"] == "Wave"


def test_a_wave_moves_the_right_arm_and_leaves_the_legs_alone():
    clip = synthesize(plan(layers=[]), R15)
    rest = np.tile(IDENTITY_QUAT, (clip.frame_count, 1))
    arm = np.rad2deg(quat_angle(clip.rotations["RightUpperArm"], rest)).max()
    assert arm > 90.0
    # The feet appear in neither stand_relaxed nor the wave poses, so they must
    # sit exactly at rest; the knees carry stand_relaxed's couple of degrees.
    assert np.allclose(clip.rotations["LeftFoot"], IDENTITY_QUAT)
    assert np.rad2deg(quat_angle(clip.rotations["LeftLowerLeg"], rest)).max() < 3.0


def test_energy_scales_the_deviation_from_rest():
    quiet = synthesize(plan(energy=0.5, layers=[]), R15)
    loud = synthesize(plan(energy=1.5, layers=[]), R15)
    rest = np.tile(IDENTITY_QUAT, (quiet.frame_count, 1))
    assert (
        np.rad2deg(quat_angle(quiet.rotations["RightUpperArm"], rest)).max()
        < np.rad2deg(quat_angle(loud.rotations["RightUpperArm"], rest)).max()
    )


def test_a_looping_clip_ends_where_it_starts():
    clip = synthesize(
        plan(
            loop=True,
            priority="Movement",
            segments=[{"start": 0.0, "end": 2.0, "cycle": "walk", "rate": 1.0}],
            layers=[],
        ),
        R15,
    )
    assert clip.loop
    for part in R15.animated_parts:
        assert np.rad2deg(quat_angle(clip.rotations[part][0], clip.rotations[part][-1])) < 1e-3


def test_walk_cycle_moves_the_legs_out_of_phase():
    clip = synthesize(
        plan(segments=[{"start": 0.0, "end": 2.0, "cycle": "walk"}], layers=[]), R15
    )
    left = clip.rotations["LeftUpperLeg"]
    right = clip.rotations["RightUpperLeg"]
    assert np.rad2deg(quat_angle(left, right)).max() > 20.0


def test_r6_receives_the_poses_its_rig_can_carry():
    clip = synthesize(plan(layers=[]), R6)
    assert set(clip.rotations) == set(R6.animated_parts)
    rest = np.tile(IDENTITY_QUAT, (clip.frame_count, 1))
    assert np.rad2deg(quat_angle(clip.rotations["Right Arm"], rest)).max() > 90.0


def test_layers_are_small_next_to_the_poses():
    bare = synthesize(plan(layers=[]), R15)
    layered = synthesize(plan(layers=[{"kind": "sway", "amplitude": 0.6}]), R15)
    delta = np.rad2deg(
        quat_angle(bare.rotations["UpperTorso"], layered.rotations["UpperTorso"])
    )
    assert 0.0 < delta.max() < 10.0


# --- provider plumbing -----------------------------------------------------
def test_fenced_json_from_a_chatty_model_is_recovered():
    raw = 'Sure!\n```json\n{"name": "Idle", "segments": []}\n```\nHope that helps.'
    assert _parse_json("test", raw) == {"name": "Idle", "segments": []}


def test_a_response_without_json_names_the_provider():
    with pytest.raises(RuntimeError, match="test: no JSON object"):
        _parse_json("test", "I cannot help with that.")


def test_a_plan_nested_under_a_wrapper_key_is_unwrapped():
    coerced = _coerce({"plan": dict(WAVE_PLAN)}, fps=24.0)
    assert "segments" in coerced


def test_coercion_does_not_paper_over_a_bad_pose_name():
    # The model has to be told, so it can fix it on the repair round.
    with pytest.raises(PlanError, match="unknown pose"):
        MotionPlan.from_dict(
            _coerce({"name": "x", "segments": [{"start": 0, "end": 1, "pose": "moonwalk"}]}, 30.0)
        )
