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


def test_duration_has_no_ten_second_ceiling(monkeypatch, tmp_path, capsys):
    _no_models(monkeypatch)
    out = tmp_path / "long.rbxmx"
    assert main(
        ["prompt", "marche", "--planner", "offline", "--duration", "45", "-o", str(out)]
    ) == 0
    assert "45.00s" in capsys.readouterr().out


def test_duration_auto_keeps_the_natural_length(monkeypatch, tmp_path, capsys):
    _no_models(monkeypatch)
    main(["prompt", "marche", "--planner", "offline", "-o", str(tmp_path / "a.rbxmx")])
    assert "fitted to" not in capsys.readouterr().out


def test_a_nonsense_duration_is_rejected(monkeypatch, tmp_path, capsys):
    _no_models(monkeypatch)
    assert main(
        ["prompt", "marche", "--planner", "offline", "--duration", "bientot", "-o", str(tmp_path / "x.rbxmx")]
    ) == 1
    assert "expects seconds or 'auto'" in capsys.readouterr().err


def test_motion_loop_marks_the_clip_as_looping(monkeypatch, tmp_path):
    _no_models(monkeypatch)
    out = tmp_path / "loop.rbxmx"
    main(
        ["prompt", "marche", "--planner", "offline", "--motion", "loop", "--duration", "6", "-o", str(out)]
    )
    assert '<bool name="Loop">true</bool>' in out.read_text()


def test_motion_natural_bakes_root_translation_on_a_capture(tmp_path, recording):
    out = tmp_path / "moved.rbxmx"
    assert main(
        ["retarget", str(recording), "--fps", "30", "--motion", "natural", "-o", str(out)]
    ) == 0
    assert out.exists()


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


def _no_models(monkeypatch) -> None:
    from linen.generate import providers

    for provider in providers.PROVIDERS:
        monkeypatch.delenv(provider.env_key, raising=False)
    monkeypatch.setenv("LINEN_LOCAL_BASE_URL", "http://127.0.0.1:1/v1")


def test_prompt_still_works_with_no_key_and_no_local_model(monkeypatch, tmp_path, capsys):
    # The headline guarantee: prompt to animation, entirely offline and free.
    _no_models(monkeypatch)
    out = tmp_path / "wave.rbxmx"
    assert main(["prompt", "salue puis marche", "-o", str(out)]) == 0
    assert out.read_text().startswith("<?xml")
    assert "plan from offline" in capsys.readouterr().out


def test_forcing_a_model_planner_fails_loudly_instead(monkeypatch, tmp_path, capsys):
    _no_models(monkeypatch)
    assert main(
        ["prompt", "salue", "--planner", "model", "-o", str(tmp_path / "x.rbxmx")]
    ) == 1
    assert "unreachable" in capsys.readouterr().err


def test_offline_planner_writes_both_rigs_in_one_run(monkeypatch, tmp_path, capsys):
    _no_models(monkeypatch)
    assert main(
        ["prompt", "saute", "--planner", "offline", "--rig", "both", "-o", str(tmp_path / "j.rbxmx")]
    ) == 0
    assert (tmp_path / "j.R15.rbxmx").exists()
    assert (tmp_path / "j.R6.rbxmx").exists()
    out = capsys.readouterr().out
    assert "R15" in out and "R6" in out


def test_retarget_writes_both_rigs_in_one_run(tmp_path, recording):
    assert main(
        ["retarget", str(recording), "--fps", "30", "--rig", "both", "-o", str(tmp_path / "t.rbxmx")]
    ) == 0
    assert "Left Arm" in (tmp_path / "t.R6.rbxmx").read_text()
    assert "LeftUpperArm" in (tmp_path / "t.R15.rbxmx").read_text()


def test_scene_writes_one_animation_per_actor_plus_a_script(monkeypatch, tmp_path, capsys):
    _no_models(monkeypatch)
    scene = tmp_path / "duel.json"
    scene.write_text(
        json.dumps(
            {
                "name": "Duel",
                "actors": [
                    {"name": "Alice", "rig": "R15", "facing": "Bob"},
                    {"name": "Bob", "rig": "R6", "position": [0, 0, -6], "facing": "Alice"},
                ],
                "cues": [
                    {"id": "hit", "actor": "Alice", "at": 0.5, "prompt": "coup de poing"},
                    {"actor": "Bob", "with": "hit", "offset": 0.3, "prompt": "encaisse"},
                ],
            }
        )
    )
    out = tmp_path / "build"
    assert main(["scene", str(scene), "--planner", "offline", "-o", str(out)]) == 0

    assert (out / "Duel_Alice.rbxmx").exists()
    assert "Left Arm" in (out / "Duel_Bob.rbxmx").read_text()
    script = (out / "Duel.server.luau").read_text()
    assert "RegisterKeyframeSequence" in script
    assert "2 actors" in capsys.readouterr().out


def test_scene_needs_exactly_one_source(monkeypatch, tmp_path, capsys):
    _no_models(monkeypatch)
    assert main(["scene", "-o", str(tmp_path / "out")]) == 1
    assert "either a scene file or --from-prompt" in capsys.readouterr().err


def test_directing_a_scene_from_a_prompt_needs_a_model(monkeypatch, tmp_path, capsys):
    _no_models(monkeypatch)
    assert main(
        ["scene", "--from-prompt", "deux personnes discutent", "-o", str(tmp_path / "out")]
    ) == 1
    assert "unreachable" in capsys.readouterr().err


def test_vocabulary_lists_poses_and_cycles(capsys):
    assert main(["vocabulary"]) == 0
    out = capsys.readouterr().out
    assert "stand_relaxed" in out
    assert "walk" in out
