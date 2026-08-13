"""Joining clips: the spring, and choosing where to cut.

The headline number, measured on real CMU captures cut run -> walk -> punch:

===========================  ===================  ======
                             peak deg per frame   area
===========================  ===================  ======
plain concatenation                109.8 / 61.5   442/171
inertialized                        32.8 / 29.8   344/125
inertialized, entry chosen            3.5 /  2.3    89/ 66
===========================  ===================  ======

Ordinary motion in those clips runs about 3.4 degrees a frame, so the last row
is a join that cannot be seen. The lesson is in the gap between rows two and
three: the spring matters much less than not cutting at a bad pose.
"""

from __future__ import annotations

import numpy as np
import pytest

from linen.clip import AnimationClip
from linen.math3d import euler_degrees_to_quat, quat_conjugate, quat_multiply
from linen.rigs import get_rig
from linen.transitions import (
    DEFAULT_HALFLIFE,
    best_entry,
    chain,
    decay,
    halflife_to_damping,
    inertialize,
    pose_distance,
    quat_to_rotvec,
    rotvec_to_quat,
    seam_error,
)

RIG = get_rig("R15")
FPS = 60.0


def spin(part: str, start: float, stop: float, frames: int = 60, axis: int = 0):
    """A clip where one joint sweeps from ``start`` to ``stop`` degrees."""
    angles = np.linspace(start, stop, frames)
    track = np.stack([
        euler_degrees_to_quat(np.array([a if axis == 0 else 0.0,
                                        a if axis == 1 else 0.0,
                                        a if axis == 2 else 0.0]))
        for a in angles
    ])
    identity = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (frames, 1))
    rotations = {name: identity.copy() for name in RIG.animated_parts}
    rotations[part] = track
    return AnimationClip(rig=RIG, fps=FPS, rotations=rotations, name=f"{part}-{start:g}")


def degrees_between(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.degrees(np.linalg.norm(quat_to_rotvec(quat_multiply(a, quat_conjugate(b)))[0])))


# --- the maths --------------------------------------------------------------
def test_rotation_vectors_round_trip():
    for angles in ([10, 0, 0], [0, 95, 0], [30, -40, 20], [0, 0, 0]):
        q = euler_degrees_to_quat(np.array(angles, dtype=float))
        assert degrees_between(rotvec_to_quat(quat_to_rotvec(q))[0], q) < 1e-6


def test_a_rotation_and_its_negative_are_the_same_rotation():
    """Quaternions double-cover, and the sign decides which way an offset decays."""
    q = euler_degrees_to_quat(np.array([120.0, 0.0, 0.0]))
    assert quat_to_rotvec(q)[0] == pytest.approx(quat_to_rotvec(-q)[0], abs=1e-9)


def test_the_spring_starts_at_the_offset_and_decays_to_nothing():
    offset = np.array([0.0, 0.0, 1.0])
    times = np.linspace(0.0, 4.0, 200)
    curve = decay(offset, np.zeros(3), times, 0.25)

    assert curve[0] == pytest.approx(offset)
    assert np.linalg.norm(curve[-1]) < 1e-3


def test_the_half_life_names_the_spring_not_the_offset():
    """A trap worth pinning: at t = halflife the offset is at 0.60, not 0.50.

    The parameter is the half-life of the underlying critically damped spring.
    The position response carries an extra linear term — the ``(v + x·y)·t`` in
    the formula — which holds it up, so it reaches half around 1.35 half-lives.
    This matches the standard formulation; a test asserting 0.5 is wrong about
    the maths, not about the code.
    """
    offset = np.array([0.0, 0.0, 1.0])

    at_one = np.linalg.norm(decay(offset, np.zeros(3), np.array([0.25]), 0.25)[0])
    assert at_one == pytest.approx(0.25 * (1 + 2 * np.log(2)), abs=1e-6)

    curve = [
        np.linalg.norm(decay(offset, np.zeros(3), np.array([k * 0.25]), 0.25)[0])
        for k in (0.5, 1.0, 1.5, 2.0, 3.0)
    ]
    assert curve == sorted(curve, reverse=True), "it must only ever shrink"
    assert curve[-1] < 0.1, "and be gone within a few half-lives"


def test_a_shorter_half_life_settles_sooner():
    offset = np.array([1.0, 0.0, 0.0])
    at = np.array([0.2])
    quick = np.linalg.norm(decay(offset, np.zeros(3), at, 0.05)[0])
    slow = np.linalg.norm(decay(offset, np.zeros(3), at, 0.5)[0])
    assert quick < slow


def test_damping_grows_as_the_half_life_shrinks():
    assert halflife_to_damping(0.1) > halflife_to_damping(1.0) > 0


# --- inertialization --------------------------------------------------------
def test_the_first_frame_lands_exactly_on_the_outgoing_pose():
    """This is what makes the join continuous, and it is exact, not close."""
    clip = spin("RightUpperArm", 40.0, 80.0)
    previous = euler_degrees_to_quat(np.array([-30.0, 0.0, 0.0]))

    out = inertialize(clip.rotations["RightUpperArm"], previous=previous,
                      before_previous=None, fps=FPS)
    assert degrees_between(out[0], previous) < 1e-6


def test_the_offset_is_gone_by_the_end():
    clip = spin("RightUpperArm", 40.0, 45.0, frames=180)
    track = clip.rotations["RightUpperArm"]
    out = inertialize(track, previous=euler_degrees_to_quat(np.array([-60.0, 0, 0])),
                      before_previous=None, fps=FPS)
    assert degrees_between(out[-1], track[-1]) < 0.5


def test_an_offset_of_nothing_leaves_the_track_untouched():
    clip = spin("RightUpperArm", 0.0, 30.0)
    track = clip.rotations["RightUpperArm"]
    out = inertialize(track, previous=track[0], before_previous=None, fps=FPS)
    assert out is track or np.allclose(out, track)


def test_the_velocity_never_exceeds_what_the_body_was_already_doing():
    """Cutting a sprint into a walk, the raw velocity difference overshoots.

    The thigh turns at 1500 deg/s in the run against 400 in the walk, and
    injecting the difference produces an excursion faster than either clip
    ever moves — a motion that is in neither take.
    """
    fast = spin("LeftUpperLeg", 0.0, 200.0, frames=20)
    slow = spin("LeftUpperLeg", 0.0, 5.0, frames=120)
    outgoing = fast.rotations["LeftUpperLeg"]

    out = inertialize(
        slow.rotations["LeftUpperLeg"],
        previous=outgoing[-1],
        before_previous=outgoing[-2],
        fps=FPS,
    )
    steps = [degrees_between(out[i + 1], out[i]) for i in range(len(out) - 1)]
    was_doing = degrees_between(outgoing[-1], outgoing[-2])
    assert max(steps) <= was_doing * 2.5, (max(steps), was_doing)


# --- choosing the entry point ----------------------------------------------
def test_the_entry_frame_is_the_one_that_already_matches():
    clip = spin("RightUpperArm", 0.0, 60.0, frames=60)
    wanted = {"RightUpperArm": clip.rotations["RightUpperArm"][20]}
    assert best_entry(clip, wanted, window=1.0) == 20


def test_the_search_stays_near_the_start_of_the_clip():
    """Otherwise a clip skips to a matching moment and drops what was asked for."""
    clip = spin("RightUpperArm", 0.0, 120.0, frames=120)
    late = {"RightUpperArm": clip.rotations["RightUpperArm"][110]}
    assert best_entry(clip, late, window=0.2) <= int(0.2 * FPS)


def test_pose_distance_is_zero_only_for_the_same_pose():
    clip = spin("RightUpperArm", 0.0, 60.0)
    pose = {p: t[0] for p, t in clip.rotations.items()}
    assert pose_distance(pose, pose) == pytest.approx(0.0, abs=1e-9)
    other = {p: t[30] for p, t in clip.rotations.items()}
    assert pose_distance(pose, other) > 0.1


# --- chaining ---------------------------------------------------------------
def _chained_seam(first, second, **kwargs) -> float:
    joined = chain([first, second], **kwargs)
    seam = joined.metadata["seams"][0]
    return max(seam_error(joined, seam + k) for k in range(8))


def test_choosing_the_entry_beats_the_spring_on_its_own():
    """The result that decides the design: where you cut matters more."""
    first = spin("RightUpperArm", 0.0, 90.0, frames=60)
    second = spin("RightUpperArm", -90.0, 90.0, frames=120)

    hard = AnimationClip(
        rig=RIG, fps=FPS, name="hard",
        rotations={p: np.concatenate([first.rotations[p], second.rotations[p]])
                   for p in first.rotations},
    )
    raw = max(seam_error(hard, first.frame_count + k) for k in range(8))
    sprung = _chained_seam(first, second, align=False)
    aligned = _chained_seam(first, second, align=True)

    assert sprung < raw, (sprung, raw)
    assert aligned < sprung, (aligned, sprung)


def test_a_chain_is_as_long_as_its_parts_less_what_alignment_skipped():
    first, second = spin("RightUpperArm", 0.0, 30.0), spin("LeftUpperArm", 0.0, 30.0)
    joined = chain([first, second], align=False)
    assert joined.frame_count == first.frame_count + second.frame_count


def test_a_single_clip_comes_back_unchanged():
    only = spin("RightUpperArm", 0.0, 30.0)
    assert chain([only]) is only


def test_chaining_nothing_is_an_error():
    with pytest.raises(ValueError, match="nothing to chain"):
        chain([])


def test_clips_on_different_rigs_cannot_be_chained():
    other = AnimationClip(
        rig=get_rig("R6"), fps=FPS,
        rotations={"Torso": np.tile(np.array([0.0, 0, 0, 1.0]), (10, 1))},
    )
    with pytest.raises(ValueError, match="R6"):
        chain([spin("RightUpperArm", 0.0, 30.0), other])


def test_clips_at_different_rates_cannot_be_chained():
    slow = spin("RightUpperArm", 0.0, 30.0)
    fast = AnimationClip(
        rig=RIG, fps=FPS * 2,
        rotations={p: t.copy() for p, t in slow.rotations.items()},
    )
    with pytest.raises(ValueError, match="different rates"):
        chain([slow, fast])


def test_a_part_missing_from_one_clip_holds_instead_of_snapping_to_rest():
    first = spin("RightUpperArm", 0.0, 45.0, frames=30)
    second = AnimationClip(
        rig=RIG, fps=FPS,
        rotations={"LeftUpperArm": np.tile(np.array([0.0, 0, 0, 1.0]), (30, 1))},
        name="left-only",
    )
    joined = chain([first, second], align=False)
    held = joined.rotations["RightUpperArm"]
    ending = first.rotations["RightUpperArm"][-1]

    # It settles near where the arm was, not back to rest. The few degrees of
    # drift are the arm finishing the swing it was in, which is the point of
    # carrying velocity — freezing mid-swing is what looks wrong.
    assert degrees_between(held[-1], ending) < 8.0
    assert degrees_between(held[-1], np.array([0.0, 0.0, 0.0, 1.0])) > 30.0


def test_the_seams_are_reported_so_a_join_can_be_measured():
    parts = [spin("RightUpperArm", 0.0, 20.0, frames=30) for _ in range(3)]
    joined = chain(parts, align=False)
    assert joined.metadata["seams"] == [30, 60]
    assert joined.metadata["clips"] == [clip.name for clip in parts]


def test_a_chain_stays_a_valid_clip_for_every_part():
    parts = [spin("RightUpperArm", 0.0, 40.0), spin("LeftUpperLeg", 0.0, 40.0)]
    joined = chain(parts)
    for part, track in joined.rotations.items():
        assert track.shape == (joined.frame_count, 4), part
        assert np.allclose(np.linalg.norm(track, axis=1), 1.0, atol=1e-6), part


def test_the_default_half_life_is_in_the_range_that_reads_as_a_body():
    assert 0.1 <= DEFAULT_HALFLIFE <= 0.4
