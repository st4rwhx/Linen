from __future__ import annotations

import numpy as np
import pytest

from linen.retarget.landmarks import MEDIAPIPE_POSE, LandmarkTrack

#: A figure standing in the R15 rest pose, in Roblox axes (metres): arms hanging
#: straight down, legs straight, feet pointing along -Z.  Retargeting this must
#: come back as the identity on every joint, which is the single strongest check
#: that the solver's basis conventions match the rig's.
REST_LANDMARKS: dict[str, tuple[float, float, float]] = {
    "nose": (0.0, 1.62, -0.10),
    "left_ear": (-0.08, 1.65, 0.0),
    "right_ear": (0.08, 1.65, 0.0),
    "left_shoulder": (-0.20, 1.40, 0.0),
    "right_shoulder": (0.20, 1.40, 0.0),
    "left_elbow": (-0.20, 1.12, 0.0),
    "right_elbow": (0.20, 1.12, 0.0),
    "left_wrist": (-0.20, 0.88, 0.0),
    "right_wrist": (0.20, 0.88, 0.0),
    "left_index": (-0.20, 0.75, 0.0),
    "right_index": (0.20, 0.75, 0.0),
    "left_pinky": (-0.20, 0.75, 0.0),
    "right_pinky": (0.20, 0.75, 0.0),
    "left_hip": (-0.10, 0.92, 0.0),
    "right_hip": (0.10, 0.92, 0.0),
    "left_knee": (-0.10, 0.50, 0.0),
    "right_knee": (0.10, 0.50, 0.0),
    "left_ankle": (-0.10, 0.08, 0.0),
    "right_ankle": (0.10, 0.08, 0.0),
    "left_heel": (-0.10, 0.05, 0.06),
    "right_heel": (0.10, 0.05, 0.06),
    "left_foot_index": (-0.10, 0.05, -0.14),
    "right_foot_index": (0.10, 0.05, -0.14),
}


def make_track(
    overrides: dict[str, tuple[float, float, float]] | None = None, frames: int = 12
) -> LandmarkTrack:
    """A still landmark track, optionally with some landmarks moved."""
    positions = np.full((frames, len(MEDIAPIPE_POSE), 3), np.nan)
    merged = dict(REST_LANDMARKS)
    merged.update(overrides or {})
    for name, value in merged.items():
        positions[:, MEDIAPIPE_POSE.index(name), :] = value
    return LandmarkTrack(positions, fps=30.0)


@pytest.fixture
def rest_track() -> LandmarkTrack:
    return make_track()
