from __future__ import annotations

import numpy as np
import pytest

from linen.clip import IDENTITY_QUAT
from linen.generate import synthesize
from linen.generate.choreographer import plan_for_prompt
from linen.generate.offline import ACTIONS, action_names, normalize, plan_offline
from linen.generate.posebook import CYCLES, POSES
from linen.generate.providers import BY_NAME, PROVIDERS, configured_providers
from linen.math3d import quat_angle
from linen.rigs import R6, R15


# --- vocabulary integrity --------------------------------------------------
def _both_sides(template: str) -> list[str]:
    if "{side}" not in template:
        return [template]
    return [template.format(side=side) for side in ("left", "right")]


def test_every_action_only_uses_poses_and_cycles_that_exist():
    for action in ACTIONS:
        for beat in action.beats:
            for cycle in _both_sides(beat.cycle or ""):
                if cycle:
                    assert cycle in CYCLES, (action.name, cycle)
            for pose in _both_sides(beat.pose or ""):
                if pose:
                    assert pose in POSES, (action.name, pose)


def test_sided_actions_declare_themselves_as_such():
    # A action offering a left/right choice has to template *every* beat that
    # picks a side; a wave whose cycle is hardcoded right would silently ignore
    # "de la main gauche".
    for action in ACTIONS:
        templated = any(
            "{side}" in (beat.pose or "") or "{side}" in (beat.cycle or "")
            for beat in action.beats
        )
        assert templated == action.sided, action.name


def test_keywords_do_not_collide_between_actions():
    seen: dict[str, str] = {}
    for action in ACTIONS:
        for keyword in action.keywords:
            assert keyword not in seen, (keyword, seen.get(keyword), action.name)
            seen[keyword] = action.name


# --- parsing ---------------------------------------------------------------
def test_accents_are_stripped_so_french_matches():
    assert normalize("Célèbre la Victoire") == "celebre la victoire"


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("salue de la main", ["wave"]),
        ("wave hello", ["wave"]),
        ("marche tranquillement", ["walk"]),
        ("il court vite", ["run"]),
        ("saute", ["jump"]),
        ("accroupi derriere le mur", ["crouch"]),
        ("assieds toi", ["sit"]),
        ("un coup de poing", ["punch"]),
        ("il pointe vers l'avant", ["point"]),
        ("celebre la victoire", ["celebrate"]),
        ("reste immobile", ["idle"]),
    ],
)
def test_single_actions_are_recognised(prompt, expected):
    plan = plan_offline(prompt)
    assert [a for a in action_names() if a in plan.notes.split(":")[1]] or plan.notes
    assert all(name in plan.notes for name in expected), plan.notes


def test_sequences_are_ordered_as_written():
    plan = plan_offline("saute puis salue et ensuite marche")
    assert "jump -> wave -> walk" in plan.notes


def test_repeats_are_honoured():
    once = plan_offline("saute")
    twice = plan_offline("saute deux fois")
    assert "jump x2" in twice.notes
    assert len(twice.segments) == 2 * len(once.segments)
    assert twice.duration == pytest.approx(2 * once.duration, rel=1e-6)


def test_speed_words_scale_the_timing():
    normal = plan_offline("un coup de poing")
    fast = plan_offline("un coup de poing tres rapide")
    slow = plan_offline("un coup de poing lentement")
    assert fast.duration < normal.duration < slow.duration


def test_energy_words_scale_the_amplitude():
    assert plan_offline("celebre de facon explosive").energy > 1.0
    assert plan_offline("celebre mollement, fatigue").energy < 1.0


def test_side_words_pick_the_arm():
    left = plan_offline("coup de poing gauche")
    right = plan_offline("coup de poing droite")
    assert any(s.pose == "punch_left_extend" for s in left.segments)
    assert any(s.pose == "punch_right_extend" for s in right.segments)


def test_side_words_also_pick_the_waving_hand():
    assert any(s.cycle == "wave_left" for s in plan_offline("salue de la main gauche").segments)
    assert any(s.cycle == "wave_right" for s in plan_offline("salue de la main droite").segments)


def test_a_left_wave_moves_the_left_arm():
    clip = synthesize(plan_offline("salue de la main gauche"), R15)
    rest = np.tile(IDENTITY_QUAT, (clip.frame_count, 1))
    left = np.rad2deg(quat_angle(clip.rotations["LeftUpperArm"], rest)).max()
    right = np.rad2deg(quat_angle(clip.rotations["RightUpperArm"], rest)).max()
    assert left > 90.0
    assert right < left


def test_gestures_default_to_the_right_side():
    assert any(s.pose == "punch_right_extend" for s in plan_offline("punch").segments)


def test_loop_is_only_offered_when_every_action_can_loop():
    assert plan_offline("marche en boucle").loop
    assert plan_offline("un idle en boucle").loop
    # A jump has a landing; looping it would snap the character back mid-air.
    assert not plan_offline("saute en boucle").loop


def test_priority_follows_what_the_animation_is_for():
    assert plan_offline("reste immobile en boucle").priority == "Idle"
    assert plan_offline("marche en boucle").priority == "Movement"
    assert plan_offline("un coup de poing").priority == "Action"


def test_a_slower_cycle_lowers_its_rate_rather_than_stretching_the_clip():
    slow = plan_offline("marche lentement")
    cycle = next(s for s in slow.segments if s.cycle == "walk")
    assert cycle.rate is not None
    assert cycle.rate < CYCLES["walk"].default_rate


def test_an_unrecognised_prompt_falls_back_and_says_so():
    plan = plan_offline("fais un salto arriere vrille")
    assert plan.segments
    assert "recognised nothing" in plan.notes
    assert "jump" in plan.notes  # the notes list what it does know


# --- the plans are actually usable -----------------------------------------
def test_offline_plans_synthesise_on_both_rigs():
    for prompt in ("saute puis salue", "marche en boucle", "coup de poing gauche"):
        plan = plan_offline(prompt)
        for rig in (R15, R6):
            clip = synthesize(plan, rig)
            assert clip.frame_count > 1
            assert set(clip.rotations) == set(rig.animated_parts)
            for track in clip.rotations.values():
                assert np.all(np.isfinite(track))


def test_a_planned_jump_actually_bends_the_knees():
    clip = synthesize(plan_offline("saute"), R15)
    rest = np.tile(IDENTITY_QUAT, (clip.frame_count, 1))
    assert np.rad2deg(quat_angle(clip.rotations["LeftLowerLeg"], rest)).max() > 45.0


def test_offline_planning_is_deterministic():
    first = plan_offline("saute deux fois puis celebre")
    second = plan_offline("saute deux fois puis celebre")
    assert first.to_dict() == second.to_dict()


# --- planner selection -----------------------------------------------------
def test_offline_planner_never_touches_the_network(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("the offline planner must not open a connection")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    plan, source = plan_for_prompt("saute puis salue", planner="offline")
    assert source == "offline"
    assert plan.segments


def test_auto_falls_back_to_offline_when_no_model_answers(monkeypatch):
    for provider in PROVIDERS:
        monkeypatch.delenv(provider.env_key, raising=False)
    monkeypatch.setenv("LINEN_LOCAL_BASE_URL", "http://127.0.0.1:1/v1")

    plan, source = plan_for_prompt("marche en boucle", planner="auto")
    assert source == "offline"
    assert plan.loop


def test_model_planner_refuses_to_fall_back(monkeypatch):
    for provider in PROVIDERS:
        monkeypatch.delenv(provider.env_key, raising=False)
    monkeypatch.setenv("LINEN_LOCAL_BASE_URL", "http://127.0.0.1:1/v1")

    with pytest.raises(RuntimeError):
        plan_for_prompt("marche", planner="model")


def test_an_unknown_planner_is_rejected():
    with pytest.raises(ValueError, match="unknown planner"):
        plan_for_prompt("marche", planner="telepathy")


# --- the local provider ----------------------------------------------------
def test_a_local_server_is_always_in_the_chain_and_comes_first(monkeypatch):
    for provider in PROVIDERS:
        monkeypatch.delenv(provider.env_key, raising=False)
    chain = configured_providers()
    assert chain, "the local provider needs no key, so the chain is never empty"
    assert chain[0].name == "local"


def test_the_local_endpoint_is_overridable(monkeypatch):
    monkeypatch.setenv("LINEN_LOCAL_BASE_URL", "http://192.168.1.9:1234/v1")
    monkeypatch.setenv("LINEN_LOCAL_MODEL", "qwen2.5:14b")
    local = BY_NAME["local"]
    assert local.endpoint == "http://192.168.1.9:1234/v1"
    assert local.model == "qwen2.5:14b"


def test_a_local_server_gets_a_short_timeout():
    # A model that is not running should cost a moment, not the full timeout.
    assert BY_NAME["local"].timeout < BY_NAME["gemini"].timeout
