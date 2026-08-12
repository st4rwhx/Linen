"""Dress the rig in real geometry instead of boxes.

The viewer draws a Roblox character as a stack of boxes, which is honest — a
Block Rig *is* boxes — but it looks like a collision hull, and looking at a
collision hull tells you less about an animation than looking at the thing you
are shipping. Free Blender rigs for R15 exist, and they store each of the
fifteen parts as a separate mesh object named exactly as Roblox names it. The
mapping is already correct; nothing has to be guessed.

**The skeleton stays ours.** Each part's mesh is normalised into that part's own
box: recentred, then scaled so its bounding box matches the size Linen measured
off Roblox's own ClassicMannequin. The joints therefore land exactly where the
solver puts them, whatever proportions the donor rig happened to have, and the
skin cannot pull a limb out of its socket.

That is a display decision and it is the right one, for the same reason the
exporter only ever writes rotations: an animation is joint angles, so it plays
correctly on any avatar. A skin changes what you look at, never what ships.

Blender is Z-up and Roblox is Y-up, so the axes are permuted on the way in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..rigs import RigDefinition, get_rig
from ..sources.blend import BlendError, Mesh, read_blend

#: Blender's ID blocks carry a two-letter type prefix in the name.
ID_PREFIX = 2

#: Triangles the whole cast may cost in one frame.
#:
#: The viewer sorts and fills every face every frame on a 2D canvas, so this is
#: a frame-time budget wearing a different hat. Measured on this renderer:
#: boxes cost about 1 ms a frame, and MrXen0's R15 at 2762 triangles costs
#: 15 ms for two actors — enough to miss 60 fps before anything else happens.
#: Dividing by the cast is what keeps a four-hander playing at the same rate as
#: a solo take.
TRIANGLE_BUDGET = 3000


class SkinError(ValueError):
    """A rig file that cannot be used as a skin, phrased for whoever picked it."""


def skin_from_blend(
    path: str | Path,
    *,
    rig: str | RigDefinition = "R15",
    budget: int = TRIANGLE_BUDGET,
) -> dict[str, Any]:
    """Per-part geometry from a .blend, fitted to ``rig``'s own proportions."""
    definition = get_rig(rig) if isinstance(rig, str) else rig
    try:
        objects = read_blend(path)
    except BlendError as exc:
        raise SkinError(str(exc)) from None

    meshes = {name[ID_PREFIX:]: mesh for name, mesh in objects.items()}
    wanted = {part.name for part in definition.parts if part.parent is not None}
    matched = {name: mesh for name, mesh in meshes.items() if name in wanted}

    if not matched:
        offered = ", ".join(sorted(meshes)[:12]) or "aucun"
        raise SkinError(
            f"{Path(path).name} ne contient aucun objet portant un nom de partie "
            f"{definition.name}. Il faut un objet par partie, nommé exactement "
            f"comme Roblox les nomme ({', '.join(sorted(wanted)[:4])}…). "
            f"Objets trouvés : {offered}"
        )

    parts: dict[str, Any] = {}
    for name, mesh in matched.items():
        parts[name] = _fit(mesh, definition.part(name).size)

    total = sum(len(p["triangles"]) // 3 for p in parts.values())
    if budget > 0 and total > budget:
        parts = {n: _simplify(p, budget / total) for n, p in parts.items()}
        total = sum(len(p["triangles"]) // 3 for p in parts.values())

    return {
        "name": Path(path).stem,
        "triangles": total,
        "rig": definition.name,
        "parts": parts,
        "missing": sorted(wanted - set(matched)),
    }


def _fit(mesh: Mesh, size: tuple[float, float, float]) -> dict[str, Any]:
    """One mesh, in Roblox axes, centred and scaled into its part's box."""
    vertices = _to_roblox(mesh.world_vertices)
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    span = np.maximum(high - low, 1e-6)
    centre = (high + low) / 2.0

    scaled = (vertices - centre) * (np.asarray(size, dtype=float) / span)
    return {
        "vertices": [round(float(v), 4) for v in scaled.reshape(-1)],
        "triangles": [int(i) for i in mesh.triangles.reshape(-1)],
    }


def _to_roblox(vertices: np.ndarray) -> np.ndarray:
    """Blender is Z-up and faces -Y; Roblox is Y-up and faces -Z.

    ``(x, y, z) -> (x, z, -y)``, which keeps the handedness — and therefore
    keeps left on the left. Swapping Y and Z alone would mirror the rig, and a
    mirrored character is the kind of thing nobody notices until the text on a
    shirt is backwards.
    """
    out = np.empty_like(vertices)
    out[:, 0] = vertices[:, 0]
    out[:, 1] = vertices[:, 2]
    out[:, 2] = -vertices[:, 1]
    return out


def _simplify(part: dict[str, Any], keep: float) -> dict[str, Any]:
    """Vertex clustering: quantise to a grid, then drop collapsed triangles.

    Crude next to a proper edge-collapse, but it is stable, it never leaves
    holes bigger than a grid cell, and it needs no library. Character parts are
    chunky, so a grid a few dozen cells across the part keeps the silhouette.
    """
    vertices = np.asarray(part["vertices"], dtype=float).reshape(-1, 3)
    triangles = np.asarray(part["triangles"], dtype=int).reshape(-1, 3)
    if keep >= 1.0 or len(triangles) < 32:
        return part

    low, high = vertices.min(axis=0), vertices.max(axis=0)
    span = np.maximum(high - low, 1e-6)
    # Cells scale with the square root of the reduction, since triangle count
    # falls roughly with the square of the grid spacing.
    cells = max(round(24 * float(np.sqrt(keep))), 3)

    keys = np.floor((vertices - low) / span * cells).astype(int)
    keys = np.clip(keys, 0, cells - 1)
    flat = (keys[:, 0] * cells + keys[:, 1]) * cells + keys[:, 2]

    unique, inverse = np.unique(flat, return_inverse=True)
    merged = np.zeros((len(unique), 3))
    counts = np.zeros(len(unique))
    np.add.at(merged, inverse, vertices)
    np.add.at(counts, inverse, 1)
    merged /= counts[:, None]

    remapped = inverse[triangles]
    alive = (
        (remapped[:, 0] != remapped[:, 1])
        & (remapped[:, 1] != remapped[:, 2])
        & (remapped[:, 0] != remapped[:, 2])
    )
    return {
        "vertices": [round(float(v), 4) for v in merged.reshape(-1)],
        "triangles": [int(i) for i in remapped[alive].reshape(-1)],
    }


def load_skin(
    path: str | Path,
    *,
    rig: str | RigDefinition = "R15",
    budget: int = TRIANGLE_BUDGET,
) -> dict[str, Any]:
    """A skin from whatever format the file is, chosen by extension."""
    path = Path(path)
    if path.suffix.lower() == ".blend":
        return skin_from_blend(path, rig=rig, budget=budget)
    raise SkinError(
        f"{path.name} : format non géré. Donne un .blend enregistré sans "
        f"compression (Blender : Fichier > Enregistrer sous, décoche « Compresser »)."
    )
