"""A cue answered by a real capture instead of by the pose vocabulary.

The vocabulary knows a dozen verbs — walk, punch, flinch — and draws them. A
fight is mostly verbs it has no word for: a grapple, a shove, a slam, a throw.
Asked for those, keyword matching falls back to something it does know, and the
scene comes out confidently playing the wrong movement. A library answers with
what a body actually did.
"""
from __future__ import annotations

import json

import pytest

from linen.library import build_library
from linen.scene import Scene, build_scene


@pytest.fixture
def library(tmp_path):
    from test_sources import bvh_text

    folder = tmp_path / "captures"
    folder.mkdir()
    for name in ("shove opponent", "walk forward"):
        (folder / f"{name}.bvh").write_text(bvh_text())
    return build_library(folder)


def _scene(prompt: str) -> Scene:
    return Scene.from_dict(
        {
            "name": "Bagarre",
            "actors": [{"name": "Hero", "rig": "R15"}],
            "cues": [{"id": "beat", "actor": "Hero", "at": 0.0, "prompt": prompt}],
        }
    )


def test_a_cue_that_matches_a_capture_is_played_by_it(library):
    built = build_scene(_scene("shove"), planner="offline", library=library)
    entry = built.schedule[0]
    assert entry.source.startswith("library:"), entry.source
    assert entry.capture is not None and entry.capture.endswith(".bvh")


def test_a_cue_the_library_cannot_answer_still_falls_back_to_the_vocabulary(library):
    """A scene mixes beats a library covers with beats it does not."""
    built = build_scene(_scene("il salue"), planner="offline", library=library)
    assert built.schedule[0].source == "offline"
    assert built.schedule[0].capture is None


def test_words_the_library_cannot_answer_get_no_capture(library):
    """A wrong capture reads worse than a drawn pose.

    It is confidently the wrong movement, where the drawn one is obviously a
    simple one — and only the second is something anyone looks at twice. The
    search refuses these itself; measured on a real eleven-clip index, "xyzzy
    quux" and "mange une pomme" came back with nothing while genuine matches
    scored 0.44 to 1.35.
    """
    for nonsense in ("xyzzy quux", "mange une pomme"):
        built = build_scene(_scene(nonsense), planner="offline", library=library)
        assert built.schedule[0].capture is None, nonsense


def test_without_a_library_nothing_changes(library):
    built = build_scene(_scene("shove"), planner="offline")
    assert built.schedule[0].source == "offline"


def test_the_capture_actually_reaches_the_clip(library):
    """The whole point: the animation carries the capture, not a drawn pose."""
    from_capture = build_scene(_scene("shove"), planner="offline", library=library)
    drawn = build_scene(_scene("shove"), planner="offline")
    a = from_capture.clips["Hero"].rotations["LeftUpperArm"]
    b = drawn.clips["Hero"].rotations["LeftUpperArm"]
    assert a.shape[0] > 0 and b.shape[0] > 0
    assert not (a.shape == b.shape and (a == b).all()), (
        "the capture made no difference to the animation"
    )


def test_a_library_indexes_the_format_mixamo_actually_exports(tmp_path):
    """Mixamo hands you Collada. A library that only reads .bvh sees none of it.

    Getting this wrong is invisible: the folder indexes, reports zero clips or
    raises "no .bvh here", and the obvious conclusion is that the download
    failed rather than that the indexer cannot read it.
    """
    from linen.sources import MOTION_SUFFIXES

    assert ".dae" in MOTION_SUFFIXES and ".bvh" in MOTION_SUFFIXES


def test_json_round_trip_of_a_library_backed_scene(library, tmp_path):
    scene = _scene("shove")
    again = Scene.from_dict(json.loads(json.dumps(scene.to_dict())))
    built = build_scene(again, planner="offline", library=library)
    assert built.schedule[0].source.startswith("library:")
