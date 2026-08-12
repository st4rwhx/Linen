from __future__ import annotations

import numpy as np
import pytest

from linen.generate import synthesize
from linen.generate.offline import plan_offline
from linen.generate.posebook import CYCLES
from linen.generate.schema import MAX_DURATION_SECONDS, PlanError
from linen.generate.timing import DURATION_PRESETS, fit_duration
from linen.rigs import R15


def walk_plan():
    return plan_offline("marche")


def punch_plan():
    return plan_offline("coup de poing")


# --- the headline: no ten second ceiling -----------------------------------
@pytest.mark.parametrize("target", [5.0, 10.0, 25.0, 30.0, 60.0, 120.0])
def test_any_duration_is_reachable(target):
    fitted = fit_duration(walk_plan(), target)
    assert fitted.duration == pytest.approx(target, abs=1e-3)


def test_the_only_cap_is_a_typo_guard_far_above_what_tools_allow():
    assert MAX_DURATION_SECONDS >= 600.0
    with pytest.raises(PlanError, match="keep it under"):
        fit_duration(walk_plan(), MAX_DURATION_SECONDS + 1.0)


def test_auto_means_leave_it_alone():
    plan = walk_plan()
    assert fit_duration(plan, None) is plan
    assert None in DURATION_PRESETS


# --- strategy selection ----------------------------------------------------
def test_a_cycle_gets_longer_without_getting_slower():
    natural = walk_plan()
    fitted = fit_duration(natural, 60.0)
    segment = next(s for s in fitted.segments if s.cycle == "walk")
    # Same cadence, more of it. A minute of walking, not one enormous step.
    assert segment.rate == next(s for s in natural.segments if s.cycle).rate
    assert "cycles extended" in fitted.notes


def test_a_one_shot_action_gets_longer_by_happening_again():
    fitted = fit_duration(punch_plan(), 10.0)
    assert "sequence repeated" in fitted.notes
    assert len(fitted.segments) > len(punch_plan().segments)
    assert fitted.duration == pytest.approx(10.0, abs=1e-3)


def test_shortening_scales_the_timing():
    fitted = fit_duration(punch_plan(), 0.4)
    assert "timing scaled" in fitted.notes
    assert fitted.duration == pytest.approx(0.4, abs=1e-3)


def test_a_repeat_blends_the_seam_between_passes():
    fitted = fit_duration(punch_plan(), 6.0, strategy="repeat")
    # The very first segment has nothing to blend from; every restart does.
    assert fitted.segments[0].blend_in == 0.0 or fitted.segments[0].start == 0.0
    restarts = [s for s in fitted.segments[1:] if s.pose == "stand_relaxed"]
    assert restarts and all(s.blend_in > 0 for s in restarts)


def test_stretching_a_cycle_too_far_names_the_better_strategy():
    with pytest.raises(PlanError, match="--fit cycle"):
        fit_duration(walk_plan(), 60.0, strategy="stretch")


def test_stretch_slows_a_cycle_when_the_factor_is_reasonable():
    fitted = fit_duration(walk_plan(), 4.4, strategy="stretch")
    segment = next(s for s in fitted.segments if s.cycle == "walk")
    assert segment.rate == pytest.approx(CYCLES["walk"].default_rate / 2.0, rel=1e-3)


def test_trim_cuts_at_the_target():
    fitted = fit_duration(punch_plan(), 0.3, strategy="trim")
    assert fitted.duration == pytest.approx(0.3, abs=1e-3)
    assert all(s.end <= 0.3 + 1e-6 for s in fitted.segments)


def test_trim_holds_the_last_segment_when_extending():
    fitted = fit_duration(punch_plan(), 4.0, strategy="trim")
    assert fitted.duration == pytest.approx(4.0, abs=1e-3)
    assert len(fitted.segments) == len(punch_plan().segments)


def test_an_unknown_strategy_is_rejected():
    with pytest.raises(PlanError, match="unknown fit strategy"):
        fit_duration(walk_plan(), 5.0, strategy="vibes")


def test_a_duration_below_the_minimum_is_rejected():
    with pytest.raises(PlanError, match="below the"):
        fit_duration(walk_plan(), 0.01)


# --- what comes out the other end ------------------------------------------
def test_a_long_fitted_plan_still_synthesises_cleanly():
    clip = synthesize(fit_duration(walk_plan(), 45.0), R15)
    assert clip.duration == pytest.approx(45.0, abs=0.05)
    for track in clip.rotations.values():
        assert np.all(np.isfinite(track))


def test_fitting_preserves_everything_that_is_not_timing():
    natural = plan_offline("marche en boucle")
    fitted = fit_duration(natural, 30.0)
    assert fitted.loop == natural.loop
    assert fitted.priority == natural.priority
    assert fitted.energy == natural.energy
    assert [layer.kind for layer in fitted.layers] == [
        layer.kind for layer in natural.layers
    ]


def test_the_note_records_what_was_done_to_the_timing():
    fitted = fit_duration(walk_plan(), 12.0)
    assert "Offline planner" in fitted.notes  # the original note survives
    assert "2.20s -> 12.00s" in fitted.notes
