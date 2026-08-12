"""Render frames of a clip to a PNG contact sheet, so a human can look at it.

Every other check in this repository asks whether the numbers are consistent.
This one asks the only question that finally matters — does it *look* like the
thing it claims to be — and it is the check the project went longest without.

    python tools/render_frames.py examples/starter/R15/Walk.rbxmx.plan.json

Draws the rig as depth-sorted boxes, which is what a Roblox character is, so a
walk that reads as a walk here reads as one in Studio.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from linen.clip import AnimationClip  # noqa: E402
from linen.generate import MotionPlan, synthesize  # noqa: E402
from linen.math3d import quat_to_mat  # noqa: E402
from linen.rigs import RigDefinition, get_rig  # noqa: E402

#: Unit cube corners and the four corners of each face, wound consistently so
#: face normals point outwards.
_CORNERS = np.array(
    [
        [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
        [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
    ],
    dtype=float,
) * 0.5
_FACES = (
    (0, 1, 2, 3),  # -Z, the character's front
    (5, 4, 7, 6),  # +Z
    (4, 0, 3, 7),  # -X
    (1, 5, 6, 2),  # +X
    (3, 2, 6, 7),  # +Y
    (4, 5, 1, 0),  # -Y
)
_LIGHT = np.array([0.4, 0.8, 0.45])
_LIGHT = _LIGHT / np.linalg.norm(_LIGHT)


def part_transforms(
    clip: AnimationClip, frame: int
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """World position and rotation of every part at ``frame``.

    Mirrors :func:`linen.rigs.kinematics.forward_kinematics`, but reads the
    clip's quaternions instead of an authored pose: a joint frame sitting at the
    pivot, rotated, then the part's centre offset inside it.
    """
    rig: RigDefinition = clip.rig
    placed: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for part in rig.parts:
        if part.parent is None:
            root = np.zeros(3)
            if clip.root_positions is not None:
                root = clip.root_positions[frame]
            placed[part.name] = (root, np.eye(3))
            continue

        track = clip.rotations.get(part.name)
        local = np.eye(3) if track is None else quat_to_mat(track[frame])

        parent_position, parent_rotation = placed[part.parent]
        pivot = np.asarray(part.pivot, dtype=float)
        offset = np.asarray(part.rest_offset, dtype=float) - pivot

        joint = parent_position + parent_rotation @ pivot
        rotation = parent_rotation @ local
        placed[part.name] = (joint + rotation @ offset, rotation)

    return placed


def draw_frame(ax, clip: AnimationClip, frame: int, azimuth: float = 35.0) -> None:
    """Paint one frame: boxes, depth-sorted, lit from one side."""
    yaw = np.deg2rad(azimuth)
    pitch = np.deg2rad(12.0)
    # Camera basis: yaw about world up, then a slight downward tilt.
    forward = np.array(
        [np.sin(yaw) * np.cos(pitch), -np.sin(pitch), np.cos(yaw) * np.cos(pitch)]
    )
    right = np.cross(np.array([0.0, 1.0, 0.0]), forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)

    placed = part_transforms(clip, frame)
    quads: list[tuple[float, np.ndarray, tuple[float, float, float]]] = []
    for part in clip.rig.parts:
        if part.parent is None:
            continue  # the root is the physics capsule, invisible on a character
        position, rotation = placed[part.name]
        size = np.asarray(part.size, dtype=float)
        corners = (rotation @ (_CORNERS * size).T).T + position

        if part.name == "Head":
            base = np.array([0.86, 0.72, 0.42])
        elif any(k in part.name for k in ("Arm", "Leg", "Hand", "Foot")):
            base = np.array([0.35, 0.55, 0.78])
        else:
            base = np.array([0.82, 0.82, 0.85])

        for face in _FACES:
            points = corners[list(face)]
            normal = np.cross(points[1] - points[0], points[2] - points[0])
            norm = np.linalg.norm(normal)
            if norm < 1e-9:
                continue
            normal /= norm
            if normal @ forward > 0:
                continue  # facing away from the camera

            shade = 0.42 + 0.58 * max(normal @ _LIGHT, 0.0)
            screen = np.stack([points @ right, points @ up], axis=-1)
            quads.append((float(np.mean(points @ forward)), screen, tuple(base * shade)))

    # Painter's algorithm: furthest first.
    for depth, screen, colour in sorted(quads, key=lambda q: -q[0]):
        ax.add_patch(Polygon(screen, closed=True, facecolor=colour, edgecolor="#1b1b22",
                             linewidth=0.4))

    # The root sits at the origin — root motion is not baked — so the body hangs
    # from y=0: the head reaches about +2.8 and the soles about -3.8. Framing
    # from zero upwards, as one instinctively does, cuts the legs off entirely.
    ground = -2.435
    ax.plot([-2.4, 2.4], [ground, ground], color="#3a3d4a", linewidth=1.0, zorder=-10)
    ax.set_xlim(-2.2, 2.2)
    ax.set_ylim(ground - 0.35, 2.9)
    ax.set_aspect("equal")
    ax.axis("off")


def contact_sheet(clip: AnimationClip, out: Path, columns: int = 6) -> Path:
    """One row of evenly spaced frames across the clip."""
    count = min(columns, clip.frame_count)
    frames = np.linspace(0, clip.frame_count - 1, count).round().astype(int)

    fig, axes = plt.subplots(1, count, figsize=(1.75 * count, 3.6))
    if count == 1:
        axes = [axes]
    fig.patch.set_facecolor("#12131a")

    for ax, frame in zip(axes, frames):
        ax.set_facecolor("#12131a")
        draw_frame(ax, clip, int(frame))
        ax.set_title(f"{frame / clip.fps:.2f}s", color="#9aa0b4", fontsize=8)

    fig.suptitle(
        f"{clip.name} — {clip.rig.name}, {clip.frame_count} frames, {clip.duration:.2f}s",
        color="#e6e8f0",
        fontsize=11,
    )
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def load_clip(path: Path, rig: str) -> AnimationClip:
    plan = MotionPlan.from_dict(json.loads(path.read_text()))
    return synthesize(plan, get_rig(rig))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="a motion plan JSON")
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--rig", default="R15")
    parser.add_argument("--columns", type=int, default=6)
    args = parser.parse_args()

    clip = load_clip(args.plan, args.rig)
    print(contact_sheet(clip, args.out, args.columns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
