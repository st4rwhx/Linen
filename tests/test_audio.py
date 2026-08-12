"""The spotting pass: what it hears, and what it must not hear.

Every failure this file guards against is one the pass actually made while it
was being written. It heard eleven punches in a stroll, it pegged the tension
curve flat at its ceiling, it scored one dramatic beat twice, and it called a
punch a hit because the victim walked through that spot two seconds later.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest

from linen.scene import (
    CATALOGUE,
    Scene,
    apply_spotting,
    build_scene,
    read_mapping,
    scene_script,
    spot_scene,
    write_mapping,
)

OFFLINE = {"planner": "offline"}

DISARM = json.loads(Path("examples/disarm.scene.json").read_text())


def _built(**overrides):
    data = json.loads(json.dumps(DISARM))
    data.update(overrides)
    return build_scene(Scene.from_dict(data), **OFFLINE)


def _sheet(built=None):
    built = built or _built()
    return built, spot_scene(built)


# --- the catalogue ---------------------------------------------------------
def test_every_slot_is_named_once_and_says_what_it_wants():
    names = [slot.name for slot in CATALOGUE]
    assert len(names) == len(set(names)), "two slots share a name"
    for slot in CATALOGUE:
        assert slot.description.strip(), f"{slot.name} does not say what it needs"
        assert slot.category in {"DX", "FX", "FOL", "BG", "MUS"}, slot.category


def test_shipped_defaults_point_at_client_files_not_uploads():
    """rbxasset:// paths live in the client: no upload, no moderation, no wait.

    An rbxassetid:// default would be somebody's asset, which can be taken
    down; that is not a default a project should ship.
    """
    for slot in CATALOGUE:
        if slot.default:
            assert slot.default.startswith("rbxasset://"), slot.name


def test_slots_the_catalogue_offers_are_all_reachable():
    """A slot no detector can ever fill is a promise the sheet cannot keep."""
    from linen.scene import audio

    emitted = {"riser", "sting"}  # placed by the ambience pass
    emitted |= {bed.slot for bed in _sheet()[1].ambience}
    source = Path(audio.__file__).read_text()
    for slot in CATALOGUE:
        assert slot.name in emitted or f'"{slot.name}"' in source, (
            f"nothing can ever produce {slot.name}"
        )


# --- what it hears ---------------------------------------------------------
def test_a_punch_that_reaches_registers_as_an_impact():
    _, sheet = _sheet()
    impacts = sheet.slot("punch_impact").hits
    assert impacts, "the disarm's punch is in range and must register as a hit"
    assert all(0.0 < hit.time < 4.8 for hit in impacts)
    assert "Thug" in impacts[0].why, "the sheet must say who was hit"


def test_a_punch_is_timed_to_the_impact_not_the_end_of_the_follow_through():
    """The sound belongs where the fist stops, not where the arm comes to rest.

    Placed at rest, it fires two tenths late — by then the fist has been pulled
    back and the reason for the sound has left the frame.
    """
    built, sheet = _sheet()
    punch = sheet.slot("punch_impact").hits[0]
    disarm = next(e for e in built.schedule if e.cue.id == "disarm")
    assert disarm.start <= punch.time <= disarm.start + 0.5, (
        f"punch at {punch.time:.2f}s, cue runs {disarm.start:.2f}-{disarm.end:.2f}s"
    )


def test_r6_is_spotted_from_its_fists_and_soles_not_its_part_centres():
    """One R6 part is a whole arm, and its centre is a stud short of the fist.

    Measuring from centres, an R6 punch reads as a miss and an R6 foot never
    reaches the ground — the rig came out silent while R15 worked.
    """
    data = json.loads(json.dumps(DISARM))
    for actor in data["actors"]:
        actor["rig"] = "R6"
    sheet = spot_scene(build_scene(Scene.from_dict(data), **OFFLINE))

    assert sheet.slot("footstep").hits, "R6 must hear its own feet"
    assert sheet.slot("punch_impact").hits or sheet.slot("swing_whoosh").hits


def test_pulling_the_actors_apart_turns_every_impact_into_a_whoosh():
    """The distance test is real, not decoration."""
    data = json.loads(json.dumps(DISARM))
    data["actors"][1]["position"] = [0, 2.44, -9]
    far = spot_scene(build_scene(Scene.from_dict(data), **OFFLINE))

    assert not far.slot("punch_impact").hits
    assert far.slot("swing_whoosh").hits
    assert any("trop loin" in warning for warning in far.warnings), (
        "a fight where nothing connects has to say so"
    )


def test_a_walk_is_not_a_flurry_of_punches():
    """The bug that made this pass worth writing carefully.

    Arms swing on every walk cycle. Without the extension test, a stroll across
    the set spotted eleven strikes and the sheet became noise.
    """
    data = json.loads(json.dumps(DISARM))
    data["cues"] = [
        {"id": "walk", "actor": "Hero", "at": 0.0, "prompt": "marche", "duration": 4.0},
        {"id": "wait", "actor": "Thug", "at": 0.0, "prompt": "reste immobile", "duration": 4.0},
    ]
    data["events"] = []
    data["props"] = []
    sheet = spot_scene(build_scene(Scene.from_dict(data), **OFFLINE))

    strikes = (
        sheet.slot("punch_impact").hits
        + sheet.slot("kick_impact").hits
        + sheet.slot("swing_whoosh").hits
    )
    assert not strikes, f"a walk spotted {len(strikes)} strikes"
    assert sheet.slot("footstep").hits, "but it must still hear the feet"


def _step_rate(prompt: str, duration: float = 4.0) -> float:
    built = build_scene(
        Scene.from_dict(
            {
                "name": "Gait",
                "fps": 30,
                "actors": [{"name": "A", "rig": "R15", "position": [0, 2.44, 0]}],
                "cues": [{"actor": "A", "at": 0.0, "prompt": prompt, "duration": duration}],
            }
        ),
        **OFFLINE,
    )
    return len(spot_scene(built).slot("footstep").hits) / built.duration


def test_footsteps_land_at_a_plausible_rate():
    """A walk is about two steps a second. Anything else is a broken detector."""
    rate = _step_rate("marche")
    assert 1.4 <= rate <= 2.6, f"{rate:.1f} steps/s is not a walk"


def test_a_run_steps_faster_than_a_walk_and_standing_still_does_not_step():
    assert _step_rate("court") > _step_rate("marche") * 1.3
    assert _step_rate("reste immobile") == 0.0


def test_the_step_rate_does_not_depend_on_how_long_the_cue_runs():
    """A detector keyed to cycle boundaries rather than the ground drifts here."""
    short, long = _step_rate("marche", 2.2), _step_rate("marche", 6.0)
    assert abs(short - long) < 0.4, f"{short:.2f}/s over 2.2s, {long:.2f}/s over 6s"


#: Everything the offline planner can produce that is genuinely a thrust.
#: Both are a limb driven forward and stopped, and no kinematic test separates
#: them — a grab and a jab look the same from the skeleton out.
THRUSTS = {"punch", "point"}


@pytest.mark.parametrize("rig", ["R15", "R6"])
def test_only_actual_thrusts_are_heard_as_strikes(rig):
    """The sweep that set every threshold in the strike detector.

    A wave, a jump and a celebration all fling a limb past fifty studs a second
    without hitting anything, so speed alone spots four false strikes. A tucked
    leg on a jump passes even the direction test, and is only ruled out by
    having touched the ground a moment earlier. Each of those was a real bug.
    """
    from linen.generate.offline import ACTIONS

    for action in ACTIONS:
        sheet = spot_scene(
            build_scene(
                Scene.from_dict(
                    {
                        "name": "Sweep",
                        "fps": 30,
                        "actors": [{"name": "A", "rig": rig, "position": [0, 3, 0]}],
                        "cues": [{"actor": "A", "at": 0.0, "prompt": action.keywords[0]}],
                    }
                ),
                **OFFLINE,
            )
        )
        strikes = (
            sheet.slot("punch_impact").hits
            + sheet.slot("kick_impact").hits
            + sheet.slot("swing_whoosh").hits
        )
        if action.name in THRUSTS:
            assert strikes, f"{rig} {action.name!r} is a thrust and must be heard"
        else:
            assert not strikes, (
                f"{rig} {action.name!r} spotted {len(strikes)} strike(s): "
                + ", ".join(hit.why for hit in strikes)
            )


def test_a_thrown_prop_is_heard_leaving_and_arriving():
    _, sheet = _sheet()
    throw = sheet.slot("prop_throw").hits
    impact = sheet.slot("prop_impact").hits
    assert throw and impact
    assert throw[0].time < impact[0].time, "it must leave before it lands"


def test_every_line_gets_its_own_slot_entry_in_order():
    _, sheet = _sheet()
    dialogue = sheet.slot("dialogue")
    spoken = [e for e in DISARM["events"] if e["kind"] == "line"]
    assert len(dialogue.hits) == len(spoken)
    assert dialogue.hits == sorted(dialogue.hits, key=lambda h: h.time)
    for line in spoken:
        assert line["text"][:20] in dialogue.description


def test_a_hit_is_only_reported_once_even_when_two_detectors_see_it():
    _, sheet = _sheet()
    for slot in sheet.slots:
        for a, b in pairwise(slot.hits):
            if a.actor == b.actor:
                assert b.time - a.time >= 0.09, f"{slot.name} fires twice at {a.time:.2f}s"


# --- tension ---------------------------------------------------------------
def test_the_tension_curve_has_a_shape_rather_than_a_ceiling():
    """Summing jolts pegged it flat at 1.0, which is the same as having none."""
    _, sheet = _sheet()
    values = [value for _, value in sheet.tension]
    assert values, "a scene with impacts must have a curve"
    assert max(values) < 1.0, "the curve must never saturate"
    assert max(values) - min(values) > 0.2, "a flat curve scores nothing"


def test_tension_rises_after_a_blow_and_not_before_it():
    _, sheet = _sheet()
    punch = sheet.slot("punch_impact").hits[0]
    before = [v for t, v in sheet.tension if t < punch.time - 0.5]
    after = [v for t, v in sheet.tension if punch.time <= t <= punch.time + 0.5]
    assert max(after) > max(before), "a punch must raise the temperature"


def test_more_blows_mean_more_tension():
    quiet = spot_scene(
        build_scene(
            Scene.from_dict(
                {
                    "name": "Quiet",
                    "fps": 30,
                    "actors": [{"name": "A", "rig": "R15", "position": [0, 2.44, 0]}],
                    "cues": [
                        {"actor": "A", "at": 0.0, "prompt": "reste immobile", "duration": 3.0}
                    ],
                }
            ),
            **OFFLINE,
        )
    )
    _, loud = _sheet()
    assert loud.peak_tension > quiet.peak_tension


def test_one_dramatic_beat_is_scored_once():
    """Two stings a third of a second apart is one moment counted twice."""
    _, sheet = _sheet()
    times = [hit.time for hit in sheet.slot("sting").hits]
    for a, b in pairwise(times):
        assert b - a >= 1.9, f"stings at {a:.2f}s and {b:.2f}s are the same beat"


def test_a_quiet_scene_asks_for_a_bed_but_not_a_drone():
    sheet = spot_scene(
        build_scene(
            Scene.from_dict(
                {
                    "name": "Quiet",
                    "fps": 30,
                    "actors": [{"name": "A", "rig": "R15", "position": [0, 2.44, 0]}],
                    "cues": [
                        {"actor": "A", "at": 0.0, "prompt": "reste immobile", "duration": 3.0}
                    ],
                }
            ),
            **OFFLINE,
        )
    )
    beds = {bed.slot for bed in sheet.ambience}
    assert "ambient_bed" in beds, "every scene needs a floor of room tone"
    assert "tension_drone" not in beds, "nothing happened; do not score it"


def test_the_heartbeat_goes_to_whoever_is_taking_the_beating():
    """"Qu'on sente que le personnage est mal en point", counted rather than guessed."""
    _, sheet = _sheet()
    heartbeat = next((bed for bed in sheet.ambience if bed.slot == "heartbeat"), None)
    assert heartbeat is not None, "someone is being punched; score it"
    assert "Thug" in heartbeat.why, "Hero throws the punch, Thug receives it"


def test_a_landed_blow_records_who_it_landed_on():
    _, sheet = _sheet()
    punch = sheet.slot("punch_impact").hits[0]
    assert punch.actor == "Hero"
    assert punch.target == "Thug"


def test_a_whiff_has_no_victim():
    data = json.loads(json.dumps(DISARM))
    data["actors"][1]["position"] = [0, 2.44, -9]
    sheet = spot_scene(build_scene(Scene.from_dict(data), **OFFLINE))
    assert all(hit.target is None for hit in sheet.slot("swing_whoosh").hits)


def test_a_scene_where_nobody_is_hit_gets_no_heartbeat():
    sheet = spot_scene(
        build_scene(
            Scene.from_dict(
                {
                    "name": "Quiet",
                    "fps": 30,
                    "actors": [{"name": "A", "rig": "R15", "position": [0, 2.44, 0]}],
                    "cues": [
                        {"actor": "A", "at": 0.0, "prompt": "marche", "duration": 3.0}
                    ],
                }
            ),
            **OFFLINE,
        )
    )
    assert not any(bed.slot == "heartbeat" for bed in sheet.ambience)


def test_the_drone_arrives_before_the_trouble_does():
    _, sheet = _sheet()
    drone = next(bed for bed in sheet.ambience if bed.slot == "tension_drone")
    punch = sheet.slot("punch_impact").hits[0]
    assert drone.start < punch.time, "arriving with the punch announces it"


# --- the mapping file ------------------------------------------------------
def test_pasted_ids_survive_a_rebuild(tmp_path):
    path = tmp_path / "Disarm.audio.json"
    _, sheet = _sheet()
    write_mapping(sheet, path)

    data = json.loads(path.read_text())
    data["sounds"]["punch_impact"] = "rbxassetid://999"
    path.write_text(json.dumps(data))

    _, again = _sheet()
    write_mapping(again, path)
    assert read_mapping(path)["punch_impact"] == "rbxassetid://999"


def test_a_malformed_mapping_is_refused_rather_than_silently_dropped(tmp_path):
    path = tmp_path / "broken.audio.json"
    path.write_text('{"sounds": ["not", "an", "object"]}')
    with pytest.raises(ValueError, match="slot"):
        read_mapping(path)

    path.write_text("{not json")
    with pytest.raises(ValueError, match="illisible"):
        read_mapping(path)


def test_a_missing_mapping_is_simply_empty(tmp_path):
    assert read_mapping(tmp_path / "nothing.json") == {}


def test_the_sheet_says_which_slots_are_still_silent():
    built = _built()
    sheet = spot_scene(built, mapping={})
    silent = [s for s in sheet.used() if not s.default]
    assert silent
    assert any("sans identifiant" in warning for warning in sheet.warnings)


def test_slots_covered_by_roblox_are_not_reported_as_missing():
    built = _built()
    sheet = spot_scene(built, mapping={})
    assert sheet.slot("footstep").default
    assert "footstep" not in "".join(sheet.warnings)


# --- wiring back into the build --------------------------------------------
def test_spotted_hits_ride_the_animation_so_they_stay_frame_exact():
    built, sheet = _sheet()
    apply_spotting(built, sheet)

    names = {
        name
        for frames in built.markers.values()
        for entries in frames.values()
        for name, _ in entries
    }
    assert "linen_spot" in names


def test_a_marker_carries_its_slot_intensity_and_part():
    built, sheet = _sheet()
    apply_spotting(built, sheet)

    values = [
        value
        for frames in built.markers.values()
        for entries in frames.values()
        for name, value in entries
        if name == "linen_spot"
    ]
    assert values
    for value in values:
        slot, intensity, _part = value.split("|")
        assert sheet.slot(slot) is not None, slot
        assert 0.0 < float(intensity) <= 1.0


def test_hits_with_nobody_to_carry_them_go_on_the_director_clock():
    built, sheet = _sheet()
    before = len(built.director)
    apply_spotting(built, sheet)
    assert len(built.director) > before
    assert built.director == sorted(built.director, key=lambda pair: pair[0])


def test_retiming_a_cue_moves_the_sounds_it_caused():
    """Derived cues anchor the same way authored ones do."""
    early = spot_scene(_built())
    data = json.loads(json.dumps(DISARM))
    next(c for c in data["cues"] if c["id"] == "approach")["duration"] = 3.2
    late = spot_scene(build_scene(Scene.from_dict(data), **OFFLINE))

    shift = 3.2 - 1.2
    assert late.slot("punch_impact").hits[0].time == pytest.approx(
        early.slot("punch_impact").hits[0].time + shift, abs=0.1
    )


# --- the generated script --------------------------------------------------
def test_the_script_carries_the_soundtrack_tables():
    built, sheet = _sheet()
    apply_spotting(built, sheet)
    script = scene_script(built, sheet=sheet, mapping={"punch_impact": "rbxassetid://7"})

    assert "local SOUNDS" in script
    assert "local AMBIENCE" in script
    assert "local TENSION" in script
    assert 'asset = "rbxassetid://7"' in script
    assert 'playSpot(' in script


def test_a_script_built_without_spotting_still_declares_the_tables():
    """The player reads them unconditionally, so they must always exist."""
    built = _built()
    script = scene_script(built)
    assert "local SOUNDS" in script
    assert "local TENSION" in script


@pytest.mark.parametrize(
    "table", ["STAGE", "CUES", "SHOTS", "PROPS", "DIRECTOR", "SOUNDS", "AMBIENCE", "TENSION"]
)
def test_every_generated_table_declares_its_type(table):
    """An unannotated empty table is a strict-mode error the moment it is read.

    A scene with no props emits `local PROPS = {}`, and Luau then refuses
    `for _, prop in PROPS do` — "cannot iterate over a table without indexer".
    Verified against the real Luau compiler: every scene without props or
    shots lit up in strict mode until these were annotated.
    """
    script = scene_script(_built())
    assert f"local {table}: " in script, f"{table} is emitted without a type"


def test_quotes_in_a_slot_or_asset_cannot_break_the_script():
    built, sheet = _sheet()
    script = scene_script(built, sheet=sheet, mapping={"punch_impact": 'a"b\\c'})
    assert 'a\\"b\\\\c' in script
