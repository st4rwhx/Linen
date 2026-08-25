"""Measuring and fixing the defects an animator judges by eye.

The clips here are built so the answer is known in advance: a leg is swung by a
stated angle, so the slide it produces is a number geometry can predict. A
cleanup checked only against real capture tells you it changed something, not
that it changed the right thing.
"""

from __future__ import annotations

import numpy as np
import pytest

from linen.clip import AnimationClip
from linen.polish import Report, _sole, _walk, measure, plant_feet
from linen.rigs import get_rig


def _still(frames: int, fps: float = 30.0) -> dict[str, np.ndarray]:
    rig = get_rig("R15")
    return {
        part.name: np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (frames, 1))
        for part in rig.parts
        if part.name != "HumanoidRootPart"
    }


def _pitch(angle: np.ndarray) -> np.ndarray:
    """Rotation about the rig's own X, which is how a leg swings."""
    half = angle / 2.0
    return np.stack(
        [np.sin(half), np.zeros_like(half), np.zeros_like(half), np.cos(half)], axis=1
    )


def _skating(frames: int = 60, degrees: float = 12.0, fps: float = 30.0) -> AnimationClip:
    """A left leg that rocks back and forth while both feet stay on the floor.

    The swing is a **sine**, not a ramp, and that distinction is the whole test.
    A foot travelling at a constant speed under a fixed pelvis is not skating —
    it is a correct in-place walk, and the first version of this fixture built
    exactly that and then asserted it was a defect. Skate is a planted foot
    disagreeing with the ground about how fast it is moving, so the fixture has
    to move it unevenly.
    """
    rotations = _still(frames, fps)
    angles = np.deg2rad(degrees) * np.sin(np.linspace(0.0, 2 * np.pi, frames))
    rotations["LeftUpperLeg"] = _pitch(angles)
    rotations["LeftLowerLeg"] = _pitch(-angles)  # shin counters: the foot stays flat
    return AnimationClip(rig=get_rig("R15"), fps=fps, rotations=rotations, name="Skate")


def _slide_of(clip: AnimationClip, part: str = "LeftFoot") -> float:
    placed = _walk(clip)
    soles = np.array([_sole(clip, frame, part) for frame in placed])
    flat = soles[:, [0, 2]]
    return float(np.linalg.norm(flat - flat[0], axis=1).max())


# --- measurement ------------------------------------------------------------


def test_a_planted_foot_that_travels_is_reported():
    clip = _skating()
    report = measure(clip)
    assert report.plants, "both feet are on the floor for the whole clip"
    assert report.worst_slide > 0.4, "a leg rocking 12 degrees drags the foot"


def test_a_clip_that_does_not_move_has_no_skate():
    clip = AnimationClip(
        rig=get_rig("R15"), fps=30.0, rotations=_still(40), name="Immobile"
    )
    assert measure(clip).worst_slide == pytest.approx(0.0, abs=1e-6)


def test_the_reported_slide_matches_the_geometry():
    """The number has to be the distance the sole actually covers."""
    clip = _skating(degrees=15.0)
    measured = measure(clip).worst_slide
    actual = _slide_of(clip)
    # The report is peak-to-peak about the plant's own centre line: the sole
    # rocks ``actual`` studs to each side of it, so the figure quoted is twice
    # the excursion from any one frame.
    assert measured == pytest.approx(2.0 * actual, rel=0.1)


def test_a_foot_travelling_at_a_steady_speed_is_not_skating():
    """That is what a correct in-place cycle looks like, and it must score 0.

    The pelvis is nailed in a Roblox animation, so a properly planted foot
    slides backwards at exactly walking speed and the engine cancels it.
    Calling that a defect would "fix" every good walk into a moon walk.
    """
    frames = 60
    rotations = _still(frames)
    angles = np.linspace(0.0, np.deg2rad(20.0), frames)
    rotations["LeftUpperLeg"] = _pitch(angles)
    rotations["LeftLowerLeg"] = _pitch(-angles)
    rotations["RightUpperLeg"] = _pitch(angles)
    rotations["RightLowerLeg"] = _pitch(-angles)
    clip = AnimationClip(rig=get_rig("R15"), fps=30.0, rotations=rotations, name="Glisse")
    assert measure(clip).worst_slide < 0.05


def test_a_frozen_pose_is_reported_as_a_dead_hold():
    clip = AnimationClip(
        rig=get_rig("R15"), fps=30.0, rotations=_still(40), name="Fige"
    )
    holds = measure(clip).dead_holds
    assert holds and holds[0] == (0, 39)


def test_a_leg_that_swings_is_not_a_dead_hold():
    assert not measure(_skating(degrees=30.0)).dead_holds


def test_two_limbs_moving_together_is_reported_as_twinning():
    frames = 60
    rotations = _still(frames)
    angles = np.deg2rad(20.0) * np.sin(np.linspace(0.0, 4 * np.pi, frames))
    rotations["LeftUpperArm"] = _pitch(angles)
    rotations["RightUpperArm"] = _pitch(angles)  # same phase, same direction
    clip = AnimationClip(rig=get_rig("R15"), fps=30.0, rotations=rotations, name="Twin")
    assert measure(clip).twinning["UpperArm"] > 0.95


def test_limbs_in_opposition_are_not_twinning():
    """A healthy walk swings the arms against each other, and must score 0.

    This is the check that caught the first version of the metric, which
    compared angular *speed*: in a proper gait both arms peak at the same
    instant, so a correct walk scored 0.93 and read as the worst defect in the
    clip.
    """
    frames = 60
    rotations = _still(frames)
    angles = np.deg2rad(20.0) * np.sin(np.linspace(0.0, 4 * np.pi, frames))
    rotations["LeftUpperArm"] = _pitch(angles)
    rotations["RightUpperArm"] = _pitch(-angles)
    clip = AnimationClip(rig=get_rig("R15"), fps=30.0, rotations=rotations, name="Walk")
    assert measure(clip).twinning["UpperArm"] == pytest.approx(0.0, abs=1e-6)


def test_the_report_prints_something_useful():
    lines = measure(_skating()).lines()
    assert lines[0].startswith("R15")
    assert any("appuis" in line for line in lines)


# --- correction -------------------------------------------------------------


def test_planting_removes_almost_all_of_the_skate():
    clip = _skating()
    fixed, before = plant_feet(clip)
    after = measure(fixed)
    assert after.worst_slide < before.worst_slide * 0.25, (
        f"{before.worst_slide:.2f} -> {after.worst_slide:.2f} studs"
    )


def test_planting_leaves_the_upper_body_alone():
    """A foot plant is a leg problem. Touching the torso would be a bug."""
    clip = _skating()
    fixed, _ = plant_feet(clip)
    for part in ("UpperTorso", "LowerTorso", "Head", "LeftUpperArm"):
        assert np.allclose(fixed.rotations[part], clip.rotations[part])


def test_planting_returns_usable_rotations():
    fixed, _ = plant_feet(_skating())
    for part, track in fixed.rotations.items():
        assert np.isfinite(track).all(), part
        assert np.allclose(np.linalg.norm(track, axis=1), 1.0, atol=1e-5), part


def test_planting_does_not_make_the_motion_jerkier():
    """A correction that fixes the numbers and adds a hitch is not a fix."""
    clip = _skating(degrees=20.0)
    fixed, _ = plant_feet(clip)

    def jerk(target: AnimationClip) -> float:
        worst = 0.0
        for track in target.rotations.values():
            dots = np.abs(np.sum(track[:-1] * track[1:], axis=1)).clip(0.0, 1.0)
            step = np.degrees(2.0 * np.arccos(dots))
            if len(step) > 1:
                worst = max(worst, float(np.abs(np.diff(step)).max()))
        return worst

    assert jerk(fixed) <= jerk(clip) + 1.0


def test_a_clip_with_nothing_planted_comes_back_untouched():
    clip = AnimationClip(
        rig=get_rig("R15"),
        fps=30.0,
        rotations={"Head": np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (10, 1))},
        name="Tete",
    )
    fixed, report = plant_feet(clip)
    assert fixed is clip
    assert not report.plants


def test_r6_is_measured_but_not_solved():
    """One rigid leg part has no knee, so there is nothing to solve with."""
    rig = get_rig("R6")
    rotations = {
        part.name: np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (30, 1))
        for part in rig.parts
        if part.name != "HumanoidRootPart"
    }
    clip = AnimationClip(rig=rig, fps=30.0, rotations=rotations, name="R6")
    fixed, report = plant_feet(clip)
    assert fixed is clip
    assert isinstance(report, Report), "it still gets measured"


def test_the_blend_is_the_papers_cubic():
    """a(t) = 2t^3 - 3t^2 + 1: one at zero, zero at one, flat at both."""
    from linen.polish import Plant, _blend_weight

    plant = Plant(part="LeftFoot", start=10, stop=20, target=np.zeros((10, 3)), slide=0.0)
    assert _blend_weight(15, plant, 5) == 1.0        # inside
    assert _blend_weight(10, plant, 5) == 1.0        # first frame of the plant
    assert _blend_weight(19, plant, 5) == 1.0        # last frame of the plant
    assert _blend_weight(5, plant, 5) == pytest.approx(0.0)
    assert _blend_weight(25, plant, 5) == pytest.approx(0.0)
    # Flat at the ends: the step away from 1 is much smaller than the step in
    # the middle of the ramp, which is what C1 continuity buys.
    near = 1.0 - _blend_weight(9, plant, 5)
    middle = _blend_weight(8, plant, 5) - _blend_weight(7, plant, 5)
    assert near < middle
