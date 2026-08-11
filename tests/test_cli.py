from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import REST_LANDMARKS
from linen.cli import main
from linen.retarget.landmarks import MEDIAPIPE_POSE

PLAN = {
    "name": "Idle",
    "fps": 30,
    "loop": True,
    "priority": "Idle",
    "segments": [{"start": 0.0, "end": 1.0, "pose": "stand_relaxed"}],
    "layers": [{"kind": "breathing", "amplitude": 0.5, "rate": 0.3}],
}


@pytest.fixture
def recording(tmp_path):
    """A FreeMoCap-shaped file: Z-up, millimetres, one landmark block per frame."""
    frames = 40
    positions = np.full((frames, len(MEDIAPIPE_POSE), 3), np.nan)
    for name, (x, y, z) in REST_LANDMARKS.items():
        positions[:, MEDIAPIPE_POSE.index(name), :] = np.array([x, -z, y]) * 1000.0
    path = tmp_path / "mediapipe_body_3d_xyz.npy"
    np.save(path, positions)
    return path


def test_retarget_writes_an_animation_and_a_preview(tmp_path, recording, capsys):
    out = tmp_path / "take.rbxmx"
    preview = tmp_path / "take.json"
    assert main(
        [
            "retarget",
            str(recording),
            "--fps",
            "30",
            "-o",
            str(out),
            "--preview",
            str(preview),
        ]
    ) == 0
    assert out.read_text().startswith("<?xml")

    clip = json.loads(preview.read_text())
    assert clip["rig"] == "R15"
    assert clip["frameCount"] == 40
    assert len(clip["rotations"]["LeftUpperArm"]) == 40 * 4
    assert "keyframes" in capsys.readouterr().out


def test_retarget_onto_r6(tmp_path, recording):
    out = tmp_path / "take6.rbxmx"
    assert main(["retarget", str(recording), "--fps", "30", "--rig", "R6", "-o", str(out)]) == 0
    assert "Left Arm" in out.read_text()


def test_zero_tolerance_keeps_every_frame(tmp_path, recording, capsys):
    out = tmp_path / "dense.rbxmx"
    main(["retarget", str(recording), "--fps", "30", "-o", str(out), "--tolerance", "0"])
    assert "40 frames -> 40 keyframes" in capsys.readouterr().out


def test_bvh_from_a_text_to_motion_tool_becomes_a_roblox_animation(tmp_path, capsys):
    from test_sources import bvh_text

    source = tmp_path / "generated.bvh"
    source.write_text(bvh_text())
    out = tmp_path / "generated.rbxmx"

    assert main(["bvh", str(source), "-o", str(out), "--units", "cm"]) == 0
    assert out.read_text().startswith("<?xml")
    assert "generated.rbxmx: R15" in capsys.readouterr().out


def test_bvh_with_an_unknown_skeleton_lists_the_known_ones(tmp_path, capsys):
    from test_sources import bvh_text

    source = tmp_path / "generated.bvh"
    source.write_text(bvh_text())
    assert main(
        ["bvh", str(source), "--skeleton", "openpose", "-o", str(tmp_path / "x.rbxmx")]
    ) == 1
    assert "unknown skeleton" in capsys.readouterr().err


def test_synth_needs_no_network(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(PLAN))
    out = tmp_path / "idle.rbxmx"
    assert main(["synth", str(plan), "-o", str(out)]) == 0
    assert "<bool name=\"Loop\">true</bool>" in out.read_text()


def test_an_invalid_plan_reports_the_reason(tmp_path, capsys):
    plan = tmp_path / "bad.json"
    plan.write_text(json.dumps({**PLAN, "segments": [{"start": 0, "end": 1, "pose": "moonwalk"}]}))
    assert main(["synth", str(plan), "-o", str(tmp_path / "x.rbxmx")]) == 1
    assert "unknown pose 'moonwalk'" in capsys.readouterr().err


def test_an_unknown_rig_is_rejected(tmp_path, recording, capsys):
    assert main(
        ["retarget", str(recording), "--fps", "30", "--rig", "R20", "-o", str(tmp_path / "x")]
    ) == 1
    assert "unknown rig" in capsys.readouterr().err


def test_prompt_without_any_key_says_what_to_do(monkeypatch, tmp_path, capsys):
    from linen.generate import providers

    for provider in providers.PROVIDERS:
        monkeypatch.delenv(provider.env_key, raising=False)
    assert main(["prompt", "a happy wave", "-o", str(tmp_path / "x.rbxmx")]) == 1
    assert "no API key found" in capsys.readouterr().err


def test_vocabulary_lists_poses_and_cycles(capsys):
    assert main(["vocabulary"]) == 0
    out = capsys.readouterr().out
    assert "stand_relaxed" in out
    assert "walk" in out
