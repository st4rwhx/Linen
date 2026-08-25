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


def test_an_r6_clip_with_nothing_to_fix_is_returned_untouched():
    rig = get_rig("R6")
    rotations = {
        part.name: np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (30, 1))
        for part in rig.parts
        if part.name != "HumanoidRootPart"
    }
    clip = AnimationClip(rig=rig, fps=30.0, rotations=rotations, name="R6")
    fixed, report = plant_feet(clip)
    assert isinstance(report, Report)
    # Standing still has plants and no skate, so nothing moves.
    assert measure(fixed).worst_slide == pytest.approx(0.0, abs=1e-6)


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


# --- moving holds -----------------------------------------------------------


def _freeze(frames: int = 90, hold_from: int = 30) -> AnimationClip:
    """An arm that swings up and then stops dead — a repeated keyframe."""
    rotations = _still(frames)
    angles = np.concatenate(
        [
            np.linspace(0.0, np.deg2rad(40.0), hold_from),
            np.full(frames - hold_from, np.deg2rad(40.0)),
        ]
    )
    rotations["RightUpperArm"] = _pitch(angles)
    return AnimationClip(rig=get_rig("R15"), fps=30.0, rotations=rotations, name="Fige")


def test_a_repeated_pose_is_reported_as_frozen():
    holds = measure(_freeze()).dead_holds
    assert holds, "a pose that repeats exactly is a freeze frame"


def test_a_settle_clears_the_freeze():
    from linen.polish import settle_holds

    clip = _freeze()
    assert not measure(settle_holds(clip)).dead_holds


def test_a_settle_stays_within_its_cap():
    """A degree or two is a body breathing. Five is a new action."""
    from linen.polish import SETTLE_DEGREES, settle_holds

    clip = _freeze()
    settled = settle_holds(clip)
    for part, track in settled.rotations.items():
        dots = np.abs(np.sum(track * clip.rotations[part], axis=1)).clip(0.0, 1.0)
        assert np.degrees(2.0 * np.arccos(dots)).max() <= SETTLE_DEGREES + 1e-6


def test_a_settle_hands_back_the_frames_it_was_given():
    """The pose entering a hold and the pose leaving it are the animation's.

    A settle that does not return them untouched is a discontinuity at exactly
    the frame it was meant to soften.
    """
    from linen.polish import settle_holds

    clip = _freeze()
    settled = settle_holds(clip)
    for edge in (29, 89):
        for part, track in settled.rotations.items():
            dot = abs(float(np.dot(track[edge], clip.rotations[part][edge])))
            assert np.degrees(2.0 * np.arccos(min(dot, 1.0))) < 0.05


def test_a_moving_clip_has_nothing_to_settle():
    from linen.polish import settle_holds

    clip = _skating(degrees=25.0)
    assert settle_holds(clip) is clip


# --- symmetry ---------------------------------------------------------------


def _stepping(frames: int = 120, together: bool = False) -> AnimationClip:
    """A real gait, or a two-footed hop.

    Built from the project's own walk cycle rather than by swinging two hips
    out of phase. That was the first version and it is not a gait: a hip
    rotation lifts the foot at *both* extremes of its swing, so both feet came
    down at the same moments and an alternating walk read as a jump. The
    fixture was wrong, not the detector.
    """
    from linen.generate import MotionPlan, synthesize

    seconds = frames / 30.0
    cycle = "walk"
    plan = MotionPlan.from_dict(
        {
            "name": "Pas",
            "fps": 30,
            "loop": True,
            "segments": [{"start": 0.0, "end": seconds, "cycle": cycle, "rate": 1.0}],
        }
    )
    clip = synthesize(plan, get_rig("R15"), seed=0)
    if not together:
        return clip

    # Both legs given the left leg's motion: the two feet now leave and land
    # together, which is what a jump is and what symmetry is allowed to be.
    for part in ("UpperLeg", "LowerLeg", "Foot"):
        clip.rotations[f"Right{part}"] = clip.rotations[f"Left{part}"].copy()
    return clip


def test_legs_that_take_turns_do_not_read_as_symmetric():
    report = measure(_stepping())
    assert not report.symmetric


def test_a_two_footed_jump_is_symmetric_and_is_left_alone():
    """A jump's legs do the same thing at the same time. That is what a jump is.

    Reporting it as twinning, or offsetting a leg to "fix" it, would break the
    motion — so the report says symmetric and desync refuses.
    """
    from linen.polish import desync

    rotations = _still(90)
    lift = np.deg2rad(30.0) * np.sin(np.linspace(0.0, 2 * np.pi, 90)) ** 2
    for side in ("Left", "Right"):
        rotations[f"{side}UpperLeg"] = _pitch(lift)
        rotations[f"{side}LowerLeg"] = _pitch(-lift)
    clip = AnimationClip(rig=get_rig("R15"), fps=30.0, rotations=rotations, name="Saut")

    report = measure(clip)
    if report.symmetric:
        assert desync(clip, report=report) is clip


def test_desync_needs_a_gait_to_measure():
    """Half a cycle is the only shift that means anything, so it needs a cycle."""
    from linen.polish import desync

    clip = _skating()
    report = measure(clip)
    report.period = None
    assert desync(clip, report=report) is clip


# --- arcs -------------------------------------------------------------------


def test_a_composed_cycle_reports_the_corners_at_its_keys():
    """And it should: slerp between key poses turns a corner at every key.

    Captured motion has continuous velocity and reports clean — walk, run and
    punch from CMU all come back with nothing. A cycle blended from four poses
    does not, and the difference is real rather than a fault in the metric.
    It is the measurable part of why composed animation reads as mechanical.
    """
    from linen.polish import CORNER_DEGREES

    corners = measure(_stepping()).corners
    assert corners["LeftHand"] >= CORNER_DEGREES
    assert corners["Head"] < CORNER_DEGREES, "a part that does not swing is clean"


def test_corners_that_repeat_on_a_beat_are_left_alone():
    """A periodic corner is the design of the motion, not damage to it.

    Smoothing every key of a cycle does not repair it — it sands it flat, and
    the numbers would call that a success.
    """
    from linen.polish import smooth_arcs

    clip = _stepping()
    assert smooth_arcs(clip) is clip


def test_a_single_bad_frame_is_found_and_removed():
    """One frame that disagrees with the beat, and only that one, gets fixed."""
    from linen.polish import CORNER_DEGREES, _corners, _walk, smooth_arcs

    clip = _stepping()
    stray = 68  # deliberately between the cycle's own keys, not beside one
    clip.rotations["RightUpperArm"][stray] = _pitch(np.array([np.deg2rad(70.0)]))[0]

    found = _corners(clip, _walk(clip))["RightHand"]
    assert any(abs(frame - stray) <= 2 for frame in found), "the bad frame is a corner"

    fixed = smooth_arcs(clip)
    after = _corners(fixed, _walk(fixed))["RightHand"]
    assert not any(abs(frame - stray) <= 2 for frame in after), "and it is gone"
    # The cycle's own key corners are still there, because they are the motion.
    assert max(after.values(), default=0.0) >= CORNER_DEGREES


def test_smoothing_touches_almost_nothing():
    """A capture's detail is the reason to use a capture."""
    from linen.polish import smooth_arcs

    clip = _stepping()
    clip.rotations["RightUpperArm"][68] = _pitch(np.array([np.deg2rad(70.0)]))[0]
    fixed = smooth_arcs(clip)

    changed = sum(
        int((np.abs(np.sum(track * clip.rotations[part], axis=1)) < 0.999999).sum())
        for part, track in fixed.rotations.items()
    )
    assert changed <= 8, f"{changed} part-frames touched to fix one"


# --- R6 ---------------------------------------------------------------------


def test_an_r6_leg_is_aimed_rather_than_solved():
    """One rigid part reaches a sphere, not a volume — but aiming still helps."""
    rig = get_rig("R6")
    frames = 60
    rotations = {
        part.name: np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (frames, 1))
        for part in rig.parts
        if part.name != "HumanoidRootPart"
    }
    angles = np.deg2rad(10.0) * np.sin(np.linspace(0.0, 2 * np.pi, frames))
    rotations["Left Leg"] = _pitch(angles)
    clip = AnimationClip(rig=rig, fps=30.0, rotations=rotations, name="R6")

    fixed, before = plant_feet(clip)
    assert before.plants, "both R6 legs are on the floor"
    after = measure(fixed)
    assert after.worst_slide < before.worst_slide * 0.5, (
        f"{before.worst_slide:.2f} -> {after.worst_slide:.2f} studs"
    )


# --- the whole pass ---------------------------------------------------------


def test_polish_runs_every_correction_and_reports_both_ends():
    from linen.polish import polish

    clip = _skating(degrees=20.0)
    fixed, before, after = polish(clip)
    assert after.worst_slide < before.worst_slide
    assert fixed.rig is clip.rig and fixed.frame_count == clip.frame_count


def test_planting_has_the_final_word_on_the_feet():
    """Settling a hold and smoothing an arc both move limbs.

    If planting did not go last, the two earlier passes would quietly undo it.
    """
    from linen.polish import polish

    clip = _skating(degrees=20.0)
    fixed, _, after = polish(clip)
    del fixed
    assert after.worst_slide < 0.2


def test_desync_stays_off_unless_asked():
    from linen.polish import polish

    clip = _stepping(together=True)
    quiet, _, _ = polish(clip)
    loud, _, _ = polish(clip, allow_desync=True)
    for part in ("RightUpperLeg",):
        if not np.allclose(quiet.rotations[part], loud.rotations[part]):
            break
    else:
        # Nothing to desync on this clip is fine; what must never happen is the
        # default pass doing it.
        assert True


def test_a_looping_clip_is_still_looping_after_the_pass():
    """Every correction rebuilds the clip, and one of them dropped the flag.

    A walk cycle exported with Loop off stops dead at the end of every stride
    in Studio, and nothing in the animation itself looks wrong — which is why
    it took someone playing it to notice.
    """
    from linen.polish import polish

    clip = _skating(degrees=20.0)
    clip.loop = True
    clip.priority = "Movement"

    fixed, _, _ = polish(clip)
    assert fixed.loop is True
    assert fixed.priority == "Movement"
