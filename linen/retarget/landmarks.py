"""MediaPipe pose landmarks and the FreeMoCap arrays that carry them."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..math3d import normalize

#: The 33 MediaPipe Pose landmarks, in index order. Left/right are the
#: *subject's* own left and right, which is also how Roblox names its parts, so
#: the two line up without a mirror step.
MEDIAPIPE_POSE: tuple[str, ...] = (
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
)

INDEX: dict[str, int] = {name: i for i, name in enumerate(MEDIAPIPE_POSE)}

#: Rotations that bring a source capture into Roblox space (X right, Y up,
#: Z backwards, right-handed).  FreeMoCap writes Z-up data once its recording
#: has been aligned to a ground plane, which is the common case.
AXIS_CONVENTIONS: dict[str, np.ndarray] = {
    # (x, y, z) -> (x, z, -y)
    "z_up": np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]]),
    # already Roblox-like
    "y_up": np.eye(3),
    # MediaPipe's own world-landmark frame: Y grows downwards, Z towards camera
    "mediapipe_world": np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]]),
}


@dataclass
class LandmarkTrack:
    """Landmark positions over time, in Roblox axes and in metres.

    ``positions`` is ``(frames, landmarks, 3)`` and may contain NaN for frames
    where a landmark was not reconstructed; :meth:`fill_gaps` deals with those.
    """

    positions: np.ndarray
    fps: float
    names: tuple[str, ...] = MEDIAPIPE_POSE

    def __post_init__(self) -> None:
        self.positions = np.asarray(self.positions, dtype=float)
        if self.positions.ndim != 3 or self.positions.shape[2] != 3:
            raise ValueError(
                f"expected positions shaped (frames, landmarks, 3), got {self.positions.shape}"
            )
        if self.positions.shape[1] != len(self.names):
            raise ValueError(
                f"{self.positions.shape[1]} landmarks but {len(self.names)} names"
            )
        if self.fps <= 0:
            raise ValueError(f"fps must be positive, got {self.fps}")

    @property
    def frame_count(self) -> int:
        return self.positions.shape[0]

    @property
    def duration(self) -> float:
        return self.frame_count / self.fps

    def point(self, *names: str) -> np.ndarray:
        """Mean position of the named landmarks, ``(frames, 3)``.

        NaNs are ignored where at least one of the named landmarks is present,
        which keeps a midpoint like the pelvis usable when one hip drops out.
        """
        idx = [self.names.index(n) for n in names]
        stack = self.positions[:, idx, :]
        with warnings.catch_warnings():
            # An all-NaN frame is a landmark that was never reconstructed; NaN
            # is the answer we want, and the solver holds the parent's pose for
            # those frames rather than trusting the result.
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmean(stack, axis=1)

    def direction(self, origin: tuple[str, ...], tip: tuple[str, ...]) -> np.ndarray:
        return normalize(self.point(*tip) - self.point(*origin))

    def fill_gaps(self, max_gap_frames: int = 30) -> LandmarkTrack:
        """Linearly interpolate NaN runs shorter than ``max_gap_frames``.

        Longer dropouts are left as NaN on purpose: inventing half a second of
        motion is worse than letting the solver hold the last good pose, and it
        keeps the failure visible.  Leading and trailing gaps are held rather
        than extrapolated.
        """
        filled = self.positions.copy()
        frames = np.arange(self.frame_count)
        for lm in range(filled.shape[1]):
            for axis in range(3):
                column = filled[:, lm, axis]
                good = ~np.isnan(column)
                if not good.any() or good.all():
                    continue
                interpolated = np.interp(frames, frames[good], column[good])
                gap_ok = _gap_mask(good, max_gap_frames)
                column[gap_ok & ~good] = interpolated[gap_ok & ~good]
        return LandmarkTrack(filled, self.fps, self.names)

    def to_roblox_axes(self, convention: str) -> LandmarkTrack:
        try:
            rotation = AXIS_CONVENTIONS[convention]
        except KeyError:
            raise ValueError(
                f"unknown axis convention {convention!r}; "
                f"expected one of {', '.join(sorted(AXIS_CONVENTIONS))}"
            ) from None
        return LandmarkTrack(self.positions @ rotation.T, self.fps, self.names)

    def scaled(self, factor: float) -> LandmarkTrack:
        return LandmarkTrack(self.positions * factor, self.fps, self.names)


def _gap_mask(good: np.ndarray, max_gap: int) -> np.ndarray:
    """Frames that sit inside a NaN run of at most ``max_gap`` frames.

    Runs touching either end of the take are excluded — those are extrapolation,
    not interpolation.
    """
    allowed = np.zeros_like(good)
    start: int | None = None
    for i, is_good in enumerate(good):
        if not is_good and start is None:
            start = i
        elif is_good and start is not None:
            if start > 0 and i - start <= max_gap:
                allowed[start:i] = True
            start = None
    return allowed


def load_freemocap(
    path: str | Path,
    fps: float,
    *,
    units: str = "mm",
    convention: str = "z_up",
) -> LandmarkTrack:
    """Load a FreeMoCap body recording into Roblox axes and metres.

    Accepts ``mediapipe_body_3d_xyz.npy`` (frames x landmarks x 3) or the
    matching ``.csv``, which FreeMoCap writes one row per frame with three
    columns per landmark.
    """
    path = Path(path)
    if path.suffix == ".npy":
        raw = np.load(path)
    elif path.suffix == ".csv":
        raw = np.loadtxt(path, delimiter=",", skiprows=1)
    else:
        raise ValueError(f"expected a .npy or .csv recording, got {path.suffix!r}")

    raw = np.asarray(raw, dtype=float)
    if raw.ndim == 2:
        if raw.shape[1] % 3:
            raise ValueError(f"{path.name}: {raw.shape[1]} columns is not a multiple of 3")
        raw = raw.reshape(raw.shape[0], raw.shape[1] // 3, 3)
    if raw.shape[1] < len(MEDIAPIPE_POSE):
        raise ValueError(
            f"{path.name}: {raw.shape[1]} landmarks, need at least {len(MEDIAPIPE_POSE)} "
            "— point this at the body file, not a hand or face file"
        )

    scale = {"mm": 0.001, "cm": 0.01, "m": 1.0}
    if units not in scale:
        raise ValueError(f"unknown units {units!r}; expected one of {', '.join(scale)}")

    body = raw[:, : len(MEDIAPIPE_POSE), :] * scale[units]
    return LandmarkTrack(body, fps).to_roblox_axes(convention)
