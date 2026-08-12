"""Indexing a mocap library, and answering a prompt out of it.

The clips here are written by hand as BVH — a Mixamo-named skeleton with joint
angles driven by formulas — so the whole path runs with nothing downloaded: the
loader, the retarget solver, the measurement, and the search over the result.

The numbers the measurement produces were checked against the real CMU database
while this was written. Walking there comes out at 1.4 hip heights per second
and running at 3.9, which are the same figures biomechanics gives for a 0.9 m
hip at 1.3 and 3.5 m/s. That agreement is the reason to trust the measurement
at all, and the synthetic clips below are shaped to sit either side of it.
"""

from __future__ import annotations

import math

import pytest

from linen.library import (
    SYNONYMS,
    Entry,
    Library,
    LibraryError,
    build_library,
    describe,
    read_descriptions,
)

# --- writing a BVH by hand --------------------------------------------------

#: Mixamo-style names, which is also what CMU's BVH conversion uses.
_SKELETON = """HIERARCHY
ROOT Hips
{{
\tOFFSET 0 0 0
\tCHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation
\tJOINT Spine
\t{{
\t\tOFFSET 0 10 0
\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\tJOINT Neck
\t\t{{
\t\t\tOFFSET 0 20 0
\t\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\t\tJOINT Head
\t\t\t{{
\t\t\t\tOFFSET 0 8 0
\t\t\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\t\t\tEnd Site
\t\t\t\t{{
\t\t\t\t\tOFFSET 0 6 0
\t\t\t\t}}
\t\t\t}}
\t\t}}
{arms}
\t}}
{legs}
}}
MOTION
Frames: {frames}
Frame Time: {frame_time}
"""

_ARM = """\t\tJOINT {side}Arm
\t\t{{
\t\t\tOFFSET {x} 18 0
\t\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\t\tJOINT {side}ForeArm
\t\t\t{{
\t\t\t\tOFFSET {x2} 0 0
\t\t\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\t\t\tJOINT {side}Hand
\t\t\t\t{{
\t\t\t\t\tOFFSET {x2} 0 0
\t\t\t\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\t\t\t\tEnd Site
\t\t\t\t\t{{
\t\t\t\t\t\tOFFSET {x3} 0 0
\t\t\t\t\t}}
\t\t\t\t}}
\t\t\t}}
\t\t}}
"""

_LEG = """\tJOINT {side}UpLeg
\t{{
\t\tOFFSET {x} -2 0
\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\tJOINT {side}Leg
\t\t{{
\t\t\tOFFSET 0 -18 0
\t\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\t\tJOINT {side}Foot
\t\t\t{{
\t\t\t\tOFFSET 0 -18 0
\t\t\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\t\t\tEnd Site
\t\t\t\t{{
\t\t\t\t\tOFFSET 0 -3 6
\t\t\t\t}}
\t\t\t}}
\t\t}}
\t}}
"""

#: Every joint in the order its channels appear, so a motion row lines up.
_ORDER = [
    "Hips", "Spine", "Neck", "Head",
    "LeftArm", "LeftForeArm", "LeftHand",
    "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot",
    "RightUpLeg", "RightLeg", "RightFoot",
]


def write_bvh(
    path,
    *,
    frames: int = 60,
    fps: float = 60.0,
    stride: float = 0.0,
    swing: float = 0.0,
    hop: float = 0.0,
    reach: float = 0.0,
    cycles: float = 2.0,
) -> None:
    """A synthetic capture with the properties the index is supposed to find.

    ``stride`` drives forward travel, ``swing`` the leg angles, ``hop`` the
    hips leaving the ground, ``reach`` an arm thrown forward.
    """
    arms = "".join(
        _ARM.format(side=side, x=x, x2=x2, x3=x3)
        for side, x, x2, x3 in (("Left", 6, 14, 5), ("Right", -6, -14, -5))
    )
    legs = "".join(
        _LEG.format(side=side, x=x) for side, x in (("Left", 5), ("Right", -5))
    )
    header = _SKELETON.format(
        arms=arms, legs=legs, frames=frames, frame_time=f"{1.0 / fps:.6f}"
    )

    rows = []
    for frame in range(frames):
        phase = 2 * math.pi * cycles * frame / max(frames - 1, 1)
        values = []
        for joint in _ORDER:
            if joint == "Hips":
                # Position first: forward travel plus a vertical hop.
                values += [
                    0.0,
                    40.0 + hop * max(math.sin(phase * 2), 0.0),
                    -stride * frame,
                ]
            angles = [0.0, 0.0, 0.0]
            if joint == "LeftUpLeg":
                angles[2] = swing * math.sin(phase)
            elif joint == "RightUpLeg":
                angles[2] = -swing * math.sin(phase)
            elif joint == "LeftLeg":
                angles[2] = -abs(swing) * 0.6 * max(math.sin(phase), 0.0)
            elif joint == "RightLeg":
                angles[2] = -abs(swing) * 0.6 * max(-math.sin(phase), 0.0)
            elif joint in ("LeftArm", "RightArm"):
                angles[0] = reach * math.sin(phase)
            values += angles
        rows.append(" ".join(f"{value:.4f}" for value in values))

    path.write_text(header + "\n".join(rows) + "\n")


@pytest.fixture
def mocap(tmp_path):
    """A tiny library: something still, something walking, something running."""
    folder = tmp_path / "clips"
    folder.mkdir()
    write_bvh(folder / "idle.bvh", stride=0.0, swing=1.0, cycles=1.0)
    write_bvh(folder / "walk.bvh", stride=0.55, swing=22.0, cycles=2.0)
    write_bvh(folder / "run.bvh", stride=1.7, swing=42.0, hop=5.0, cycles=3.0)
    write_bvh(folder / "punch.bvh", stride=0.0, swing=2.0, reach=70.0, cycles=1.0)
    return folder


DESCRIPTIONS = {
    "idle": "stand still, wait",
    "walk": "walk forward",
    "run": "run fast",
    "punch": "punch, strike",
}


# --- building ---------------------------------------------------------------
def test_a_folder_of_captures_becomes_a_catalogue(mocap):
    library = build_library(mocap, descriptions=DESCRIPTIONS)
    assert {entry.name for entry in library.entries} == {"idle", "walk", "run", "punch"}
    for entry in library.entries:
        assert entry.duration > 0 and entry.frames > 1
        assert entry.terms, f"{entry.name} has nothing to search on"


def test_travel_separates_locomotion_from_work_done_on_the_spot(mocap):
    """The measurement that matters most: it is what "fast" and "still" mean."""
    by_name = {e.name: e for e in build_library(mocap, descriptions=DESCRIPTIONS).entries}
    assert by_name["idle"].travel < by_name["walk"].travel < by_name["run"].travel
    assert by_name["punch"].travel < by_name["walk"].travel


def test_a_capture_that_leaves_the_ground_is_marked_airborne(mocap):
    by_name = {e.name: e for e in build_library(mocap, descriptions=DESCRIPTIONS).entries}
    assert by_name["run"].airborne, "the hopping clip has a flight phase"
    assert not by_name["idle"].airborne
    assert not by_name["punch"].airborne


def test_airborne_is_measured_before_the_root_is_locked(mocap):
    """The export is rotation-only, so a retargeted run never leaves the floor.

    Measured on the retargeted clip instead of the capture, every run in CMU
    came back as never airborne and every long take came back as always
    airborne. Flight is real; it just is not in the clip that ships.
    """
    by_name = {e.name: e for e in build_library(mocap, descriptions=DESCRIPTIONS).entries}
    assert by_name["run"].bob > by_name["walk"].bob


def test_a_thrown_arm_shows_up_as_reach(mocap):
    by_name = {e.name: e for e in build_library(mocap, descriptions=DESCRIPTIONS).entries}
    assert by_name["punch"].reach > by_name["idle"].reach


def test_an_empty_folder_says_what_to_put_in_it(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    with pytest.raises(LibraryError, match="mocap"):
        build_library(empty)


def test_one_broken_file_does_not_sink_the_build(mocap):
    (mocap / "broken.bvh").write_text("this is not a bvh")
    skipped = []
    library = build_library(
        mocap,
        descriptions=DESCRIPTIONS,
        on_progress=lambda i, n, p, error=None: error and skipped.append(p.name),
    )
    assert "broken.bvh" in skipped
    assert len(library.entries) == 4, "the good clips still get indexed"


def test_filenames_become_searchable_when_there_is_no_description_file(mocap):
    library = build_library(mocap)
    run = next(e for e in library.entries if e.name == "run")
    assert "run" in run.terms


# --- the index file ---------------------------------------------------------
def test_an_index_survives_a_round_trip(mocap, tmp_path):
    built = build_library(mocap, descriptions=DESCRIPTIONS)
    path = built.save(tmp_path / "index.json")
    loaded = Library.load(path)

    assert len(loaded.entries) == len(built.entries)
    assert {e.name for e in loaded.entries} == {e.name for e in built.entries}


def test_clips_resolve_even_when_the_index_lives_somewhere_else(mocap, tmp_path):
    """`-o build/lib.json` pointing at a download folder is the normal case."""
    built = build_library(mocap, descriptions=DESCRIPTIONS)
    elsewhere = tmp_path / "build" / "index.json"
    library = Library.load(built.save(elsewhere))

    for entry in library.entries:
        assert library.resolve(entry).exists()


def test_a_moved_library_says_so_rather_than_failing_obscurely(mocap, tmp_path):
    built = build_library(mocap, descriptions=DESCRIPTIONS)
    library = Library.load(built.save(tmp_path / "index.json"))
    library.source = str(tmp_path / "gone")
    library.root = tmp_path / "gone"

    with pytest.raises(LibraryError, match="reconstruis"):
        library.resolve(library.entries[0])


def test_an_index_from_another_format_version_is_refused(tmp_path):
    path = tmp_path / "old.json"
    path.write_text('{"format": 0, "entries": []}')
    with pytest.raises(LibraryError, match="library build"):
        Library.load(path)


# --- descriptions -----------------------------------------------------------
def test_a_dataset_index_is_read_into_descriptions(tmp_path):
    path = tmp_path / "index.txt"
    path.write_text(
        "\n"
        "Subject #9 (running)\n"
        "\n"
        "09_01\trun\n"
        "09_02\trun, kick\n"
    )
    assert read_descriptions(path) == {"09_01": "run", "09_02": "run, kick"}


def test_an_index_with_no_usable_lines_says_what_was_expected(tmp_path):
    path = tmp_path / "index.txt"
    path.write_text("just some prose with no name and description pairs\n")
    with pytest.raises(LibraryError, match="09_02"):
        read_descriptions(path)


# --- searching --------------------------------------------------------------
def _search(mocap, prompt: str):
    return build_library(mocap, descriptions=DESCRIPTIONS).search(prompt)


def test_a_french_prompt_finds_an_english_description(mocap):
    """The failure that makes the whole idea useless if unfixed.

    Every commercially usable library is labelled in English — CMU's index is
    2435 lines of it — and the prompts are French. Without the synonym table,
    "marche" matched none of the 506 clips described as "walk".
    """
    hits = _search(mocap, "marche")
    assert hits, "a French prompt must reach an English library"
    assert hits[0][1].name == "walk"


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("cours vite", "run"),
        ("il marche", "walk"),
        ("coup de poing", "punch"),
        ("reste immobile", "idle"),
        ("run", "run"),
        ("punch", "punch"),
    ],
)
def test_prompts_land_on_the_clip_they_describe(mocap, prompt, expected):
    hits = _search(mocap, prompt)
    assert hits, f"{prompt!r} matched nothing"
    assert hits[0][1].name == expected, [h[1].name for h in hits]


def test_a_prompt_matching_no_word_returns_nothing_rather_than_guessing(mocap):
    """Shape must modulate the text score, never replace it.

    Added to it instead, a prompt whose words match nothing still ranked every
    clip by its adverbs — "coup de poing" came back with playground climbs,
    confidently.
    """
    assert _search(mocap, "photosynthese quantique") == []


def test_the_measurements_re_rank_clips_that_share_a_word(mocap):
    """"slowly" cannot be read off a label; it is read off the motion."""
    library = build_library(mocap, descriptions={**DESCRIPTIONS, "run": "walk fast"})
    slow = library.search("marche lentement")[0][1].name
    fast = library.search("marche vite")[0][1].name
    assert slow == "walk" and fast == "run", (slow, fast)


def test_a_focused_clip_beats_a_long_take_that_merely_mentions_it(mocap):
    library = build_library(
        mocap,
        descriptions={
            **DESCRIPTIONS,
            "idle": "climb, sit, dangle legs, rock back, lower self, punch, walk away",
        },
    )
    assert library.search("coup de poing")[0][1].name == "punch"


def test_search_is_capped_by_limit(mocap):
    library = build_library(mocap, descriptions=DESCRIPTIONS)
    assert len(library.search("walk run punch stand", limit=2)) == 2


def test_scores_come_back_in_order(mocap):
    hits = _search(mocap, "walk")
    assert [score for score, _ in hits] == sorted((s for s, _ in hits), reverse=True)


# --- the synonym table ------------------------------------------------------
def test_the_synonym_table_is_symmetric():
    """If "marche" reaches "walk", "walk" must reach "marche"."""
    for word, group in SYNONYMS.items():
        for other in group:
            assert word in SYNONYMS[other], f"{word} -> {other} is one-way"


def test_the_planner_vocabulary_is_covered_by_the_synonyms():
    """The two vocabularies must not drift apart."""
    from linen.generate.offline import ACTIONS
    from linen.library import _tokens

    for action in ACTIONS:
        words = _tokens(" ".join(action.keywords))
        for word in words:
            assert word in SYNONYMS, f"{action.name}: {word!r} reaches nothing"


# --- reporting --------------------------------------------------------------
def test_describe_says_what_was_measured(mocap):
    library = build_library(mocap, descriptions=DESCRIPTIONS)
    run = next(e for e in library.entries if e.name == "run")
    text = describe(run)
    assert "s" in text and ("pas/s" in text or "studs/s" in text)


def test_an_entry_with_nothing_measured_still_describes_cleanly():
    assert describe(Entry(path="a.bvh", name="a", description="", duration=1.0,
                          fps=30.0, frames=30)) == "1.0s"
