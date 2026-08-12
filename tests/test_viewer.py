"""The 3D viewer: what gets baked into the page, and what must not break it.

The page itself is JavaScript and cannot be exercised here. What *can* be
pinned is the payload — the geometry, the staging and the timeline the page
draws from — and the handful of ways a scene's own content could break the
HTML it is embedded in.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from linen.export import clip_payload, scene_payload, viewer_html
from linen.export.viewer import standing_height
from linen.generate import plan_offline, synthesize
from linen.rigs import get_rig
from linen.scene import (
    Scene,
    apply_spotting,
    build_scene,
    plan_set,
    spot_scene,
)

OFFLINE = {"planner": "offline"}
DISARM = json.loads(Path("examples/disarm.scene.json").read_text())


def _clip(prompt: str = "marche", rig: str = "R15"):
    return synthesize(plan_offline(prompt, fps=30), get_rig(rig))


def _scene():
    built = build_scene(Scene.from_dict(json.loads(json.dumps(DISARM))), **OFFLINE)
    sheet = spot_scene(built)
    apply_spotting(built, sheet)
    return scene_payload(built, sheet=sheet, set_plan=plan_set(built))


# --- a single clip ---------------------------------------------------------
def test_a_clip_payload_carries_its_rig_and_every_frame():
    clip = _clip()
    payload = clip_payload(clip)

    assert payload["rigs"]["R15"]["parts"], "the page has to draw something"
    actor = payload["actors"][0]
    for part, track in actor["rotations"].items():
        assert len(track) == clip.frame_count * 4, f"{part} is not one quaternion per frame"


def test_a_clip_stands_on_the_ground_rather_than_through_it():
    """A Roblox character's position is its root, at hip height.

    Drawn with the root on the grid, the legs are buried and it reads as a bug
    in the animation rather than in the viewer.
    """
    payload = clip_payload(_clip())
    assert payload["actors"][0]["position"][1] == pytest.approx(
        standing_height(get_rig("R15")), abs=0.01
    )


def test_standing_height_matches_the_rig_it_is_measured_from():
    for name in ("R15", "R6"):
        height = standing_height(get_rig(name))
        assert 1.5 < height < 3.5, f"{name} root at {height:.2f} studs is not hip height"


def test_a_clip_alone_has_no_scene_furniture():
    payload = clip_payload(_clip())
    assert payload["set"] == [] and payload["shots"] == [] and payload["cues"] == []
    assert payload["duration"] > 0


# --- a whole scene ---------------------------------------------------------
def test_a_scene_payload_carries_the_cast_the_set_and_the_timeline():
    payload = _scene()
    assert {a["name"] for a in payload["actors"]} == {"Hero", "Thug"}
    assert {s["name"] for s in payload["set"]} >= {"Floor", "Wall"}
    assert [c["id"] for c in payload["cues"]], "the timeline lanes need cues"
    assert payload["tension"], "the timeline draws the tension curve"


def test_both_rigs_in_one_scene_are_both_included():
    data = json.loads(json.dumps(DISARM))
    data["actors"][1]["rig"] = "R6"
    built = build_scene(Scene.from_dict(data), **OFFLINE)
    payload = scene_payload(built)
    assert set(payload["rigs"]) == {"R15", "R6"}


def test_facing_becomes_the_same_heading_the_studio_player_uses():
    """A viewer that faces people differently shows a scene nobody will get.

    Hero stands at z=0 facing Thug at z=-2.4, which is straight down -Z: the
    rig's own forward, so no rotation at all. Thug faces back, a half turn.
    """
    payload = _scene()
    by_name = {a["name"]: a for a in payload["actors"]}
    assert by_name["Hero"]["yaw"] == pytest.approx(0.0, abs=0.5)
    assert abs(by_name["Thug"]["yaw"]) == pytest.approx(180.0, abs=0.5)


def test_authored_and_spotted_events_share_one_sorted_timeline():
    payload = _scene()
    kinds = {e["kind"] for e in payload["events"]}
    assert "camera" in kinds and "line" in kinds, "authored beats"
    assert "spot" in kinds, "derived sound"
    times = [e["t"] for e in payload["events"]]
    assert times == sorted(times)


def test_every_camera_event_names_a_shot_the_page_can_find():
    """The director camera matches events to shots by this exact label."""
    payload = _scene()
    ids = {s["id"] for s in payload["shots"]}
    for event in payload["events"]:
        if event["kind"] == "camera":
            assert event["label"].startswith("plan ")
            assert event["label"][5:] in ids


def test_a_scene_with_no_shots_or_set_still_produces_a_page():
    data = json.loads(json.dumps(DISARM))
    data["shots"] = []
    data["events"] = [e for e in data["events"] if e["kind"] != "camera"]
    built = build_scene(Scene.from_dict(data), **OFFLINE)
    html = viewer_html(scene_payload(built))
    assert "<canvas id=\"stage\">" in html


# --- the page --------------------------------------------------------------
def test_the_page_is_self_contained():
    """No CDN, no fetch, no sibling files: it has to work by double-clicking."""
    html = viewer_html(_scene())
    assert not re.search(r'src\s*=\s*["\']https?://', html)
    assert not re.search(r'href\s*=\s*["\']https?://', html)
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html


def test_the_data_is_baked_in_and_parses():
    html = viewer_html(_scene())
    match = re.search(r"const DATA = (\{.*?\});\n", html, re.DOTALL)
    assert match, "the payload must be inline"
    assert json.loads(match.group(1).replace("<\\/", "</"))["actors"]


def test_a_scene_name_with_markup_cannot_escape_the_title():
    data = json.loads(json.dumps(DISARM))
    data["name"] = "<script>alert(1)</script>"
    built = build_scene(Scene.from_dict(data), **OFFLINE)
    html = viewer_html(scene_payload(built))
    assert "<title>&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_a_closing_script_tag_in_dialogue_cannot_end_the_block_early():
    """The payload is inside <script>, so its own content must not close it."""
    data = json.loads(json.dumps(DISARM))
    for event in data["events"]:
        if event["kind"] == "line":
            event["text"] = "watch out </script><script>alert(1)</script>"
    built = build_scene(Scene.from_dict(data), **OFFLINE)
    html = viewer_html(scene_payload(built))

    body = html.split("const DATA = ", 1)[1].split(";\n", 1)[0]
    assert "</script>" not in body
    assert "<\\/script>" in body


def test_the_lane_colours_the_page_uses_cover_every_event_kind():
    from linen.export.viewer import LANES
    from linen.scene.events import KINDS

    assert set(KINDS) <= set(LANES)
    assert "spot" in LANES, "derived sound needs a colour too"
