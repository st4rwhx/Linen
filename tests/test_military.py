"""The soldier vocabulary, and what makes it read as one.

Style is a set of poses, not a filter, so what is checked here is the poses:
that the weapon owns the upper body, that owning it does not mean freezing it,
and that loading this vocabulary does not quietly change what every other
prompt resolves to.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from linen.generate import MotionPlan, military, synthesize
from linen.generate.posebook import CYCLES, POSES, resolve_pose
from linen.rigs import get_rig

PLANS = sorted(Path("examples/military").glob("*.plan.json"))


@pytest.fixture(autouse=True)
def registered():
    """Register for the test, and put the shared vocabulary back afterwards.

    The registration mutates module-level dictionaries the whole planner reads,
    which is exactly why it is opt-in — left on, it changed which clip an
    unrelated prompt came back with.
    """
    poses, cycles = dict(POSES), dict(CYCLES)
    military.register()
    yield
    POSES.clear(), POSES.update(poses)
    CYCLES.clear(), CYCLES.update(cycles)


def test_every_cycle_names_poses_that_exist():
    for name, cycle in military.CYCLES.items():
        for _, pose in cycle.keys:
            assert pose in POSES, f"{name} names {pose!r}, which is not a pose"


def test_the_carry_is_asymmetric():
    """A rifle is shouldered on one side. A symmetric carry is a mime's."""
    pose = military.LOW_READY
    assert pose["LeftUpperArm"] != pose["RightUpperArm"]
    assert pose["LeftLowerArm"] != pose["RightLowerArm"]


def test_both_hands_are_brought_in_front_of_the_chest():
    """The single thing an audience reads before anything else."""
    from linen.rigs.kinematics import forward_kinematics

    placed = forward_kinematics(get_rig("R15"), resolve_pose("mil_low_ready"))
    chest, rotation = placed["UpperTorso"]
    forward = rotation @ np.array([0.0, 0.0, -1.0])
    for hand in ("LeftHand", "RightHand"):
        reach = (placed[hand][0] - chest) @ forward
        assert reach > 0.4, f"{hand} is only {reach:.2f} studs in front of the chest"


def _cycle_clip(cycle: str, rate: float, seconds: float = 3.0):
    plan = MotionPlan.from_dict(
        {
            "name": cycle,
            "fps": 30,
            "loop": True,
            "segments": [{"start": 0.0, "end": seconds, "cycle": cycle, "rate": rate}],
        }
    )
    return synthesize(plan, get_rig("R15"), seed=0)


def _range(track: np.ndarray, axis: int) -> float:
    sign = np.where(track[:, 3] < 0.0, -1.0, 1.0)
    angles = np.degrees(2.0 * np.arcsin(np.clip(track[:, axis] * sign, -1.0, 1.0)))
    return float(angles.max() - angles.min())


@pytest.mark.parametrize(
    ("cycle", "rate", "least"), [("mil_patrol", 0.95, 30.0), ("mil_advance", 1.55, 55.0)]
)
def test_the_legs_actually_take_a_stride(cycle, rate, least):
    """A tactical walk is shorter than a civilian one, not a shuffle.

    The first version came out at 29 degrees of hip swing against the pose
    book's 48, and on screen the legs barely parted.
    """
    clip = _cycle_clip(cycle, rate)
    assert _range(clip.rotations["LeftUpperLeg"], 0) >= least


@pytest.mark.parametrize(("cycle", "rate"), [("mil_patrol", 0.95), ("mil_advance", 1.55)])
def test_the_carry_rides_the_body_rather_than_being_welded_to_it(cycle, rate):
    """Locked completely, the arms measured 0.0 degrees across a whole cycle.

    That is the exact signature this project's own polish pass calls a frozen
    pose, and it reads as a mannequin being slid along the floor. The weapon
    still has to lead the body — so the torso turns, the arms take half of it,
    and the head takes the opposite, because the eyes are aimed.
    """
    clip = _cycle_clip(cycle, rate)
    torso = _range(clip.rotations["UpperTorso"], 1)
    arm = _range(clip.rotations["LeftUpperArm"], 1)

    assert torso > 3.0, "the body has to work under the weapon"
    assert 0.2 < arm < torso, "the weapon rides the body, and lags it"
    assert _range(clip.rotations["Head"], 1) > 3.0, "the head holds its own line"


def test_the_carry_does_not_swing_like_an_arm():
    """The one thing that separates a soldier from a person walking."""
    civilian = _cycle_clip("walk", 0.9)
    soldier = _cycle_clip("mil_patrol", 0.95)
    assert _range(soldier.rotations["LeftUpperArm"], 0) < 0.25 * _range(
        civilian.rotations["LeftUpperArm"], 0
    )


@pytest.mark.parametrize("path", PLANS, ids=lambda p: p.stem)
def test_every_shipped_plan_builds(path):
    plan = MotionPlan.from_dict(json.loads(path.read_text()))
    for rig in ("R15", "R6"):
        clip = synthesize(plan, get_rig(rig), seed=0)
        assert clip.frame_count > 1
        for part, track in clip.rotations.items():
            assert np.isfinite(track).all(), f"{path.stem}/{rig}: {part}"


def test_the_vocabulary_is_not_loaded_unless_it_is_asked_for():
    """Registering it globally changed which clip an unrelated prompt returned.

    A style is something you opt into, not something that redefines the words
    everyone else is using.
    """
    from linen.cli import _load_vocabularies

    poses = dict(POSES)
    for name in list(military.POSES):
        POSES.pop(name, None)
    try:
        _load_vocabularies(None)
        assert "mil_low_ready" not in POSES
        _load_vocabularies(["military"])
        assert "mil_low_ready" in POSES
    finally:
        POSES.clear(), POSES.update(poses)
