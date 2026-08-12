"""Read meshes out of a ``.blend`` file, without Blender.

The viewer draws a Roblox character as boxes, because that is what a Block Rig
*is*. But a real rig is a mesh, and looking at grey boxes tells you less than
looking at the thing you are actually shipping. Blender rigs for R15 are common
and free — MrXen0's is one — and they store each of the fifteen parts as a
separate mesh object named exactly as Roblox names it. That is the whole reason
this is worth doing: the mapping is already correct, nothing has to be guessed.

A ``.blend`` is a self-describing dump of Blender's own memory. After a short
header it is a sequence of blocks, each carrying the address it was written
from, and one block — ``DNA1`` — holds the layout of every struct in the build
that saved it. Read that first and the rest becomes ordinary field access;
pointers between blocks are just those saved addresses.

What this reads is deliberately narrow: object names, their transforms, and
mesh positions and faces. No modifiers, no armature, no materials, no UVs.
Enough to draw the rig, which is the entire point.

Blender 4.x keeps mesh data in generic attribute layers rather than named
struct arrays, so positions come from a ``CD_PROP_FLOAT3`` layer called
``position`` and face corners from an int layer called ``.corner_vert``. The
3.x layout — ``MVert`` and ``MLoop`` arrays — is read too, because plenty of
rigs in circulation were saved by it.
"""

from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

#: CustomData layer types, from Blender's ``BKE_customdata.h``.
CD_PROP_FLOAT3 = 47
CD_PROP_INT32 = 11
CD_MVERT = 0
CD_MLOOP = 26


class BlendError(ValueError):
    """A .blend that cannot be read, phrased for whoever exported it."""


@dataclass
class Mesh:
    """One object's geometry, in that object's own local space."""

    name: str
    vertices: np.ndarray
    #: Triangle indices, (n, 3). Everything is triangulated on read, because
    #: the viewer sorts and fills flat polygons and an n-gon may not be flat.
    triangles: np.ndarray
    #: The object's own transform, 4x4, column-major as Blender stores it.
    matrix: np.ndarray = field(default_factory=lambda: np.eye(4))

    @property
    def world_vertices(self) -> np.ndarray:
        homogeneous = np.hstack([self.vertices, np.ones((len(self.vertices), 1))])
        return (homogeneous @ self.matrix.T)[:, :3]


# -- the container ------------------------------------------------------------


@dataclass
class _Block:
    code: bytes
    sdna: int
    count: int
    start: int
    size: int


class BlendFile:
    """A parsed .blend: its DNA, and its blocks by saved address."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        header = data[:12]
        if header[:7] != b"BLENDER":
            raise BlendError(
                "ce fichier ne commence pas par 'BLENDER' — ce n'est pas un .blend "
                "décompressé"
            )
        self.pointer = 8 if header[7:8] == b"-" else 4
        self.endian = "<" if header[8:9] == b"v" else ">"
        self.version = header[9:12].decode("ascii", "replace")

        self.blocks: list[_Block] = []
        self.by_address: dict[int, _Block] = {}
        self._scan()
        self._read_dna()

    def _scan(self) -> None:
        data = self.data
        offset = 12
        address = self.endian + ("Q" if self.pointer == 8 else "I")
        while offset + 20 <= len(data):
            code = data[offset : offset + 4]
            if code == b"ENDB":
                break
            size, = struct.unpack_from(self.endian + "i", data, offset + 4)
            old, = struct.unpack_from(address, data, offset + 8)
            sdna, count = struct.unpack_from(
                self.endian + "ii", data, offset + 8 + self.pointer
            )
            body = offset + 16 + self.pointer
            block = _Block(code, sdna, count, body, size)
            self.blocks.append(block)
            if old:
                self.by_address[old] = block
            offset = body + size

    def _read_dna(self) -> None:
        block = next((b for b in self.blocks if b.code == b"DNA1"), None)
        if block is None:
            raise BlendError("ce .blend ne contient pas de bloc DNA1")
        data = self.data
        base = block.start

        def aligned(offset: int) -> int:
            # Padding is measured from the start of the block, not the file.
            return base + (((offset - base) + 3) & ~3)

        def strings(offset: int) -> tuple[list[str], int]:
            count, = struct.unpack_from(self.endian + "i", data, offset)
            offset += 4
            out = []
            for _ in range(count):
                end = data.index(b"\0", offset)
                out.append(data[offset:end].decode("utf8", "replace"))
                offset = end + 1
            return out, aligned(offset)

        offset = base + 8  # "SDNA" "NAME"
        self.names, offset = strings(offset)
        offset = self._expect(offset, b"TYPE")
        self.types, offset = strings(offset)
        offset = self._expect(offset, b"TLEN")
        self.type_sizes = list(
            struct.unpack_from(f"{self.endian}{len(self.types)}H", data, offset)
        )
        offset = aligned(offset + 2 * len(self.types))
        offset = self._expect(offset, b"STRC")
        count, = struct.unpack_from(self.endian + "i", data, offset)
        offset += 4

        self.structs: list[tuple[int, list[tuple[int, int]]]] = []
        for _ in range(count):
            type_index, fields = struct.unpack_from(self.endian + "HH", data, offset)
            offset += 4
            raw = struct.unpack_from(f"{self.endian}{fields * 2}H", data, offset)
            offset += 4 * fields
            self.structs.append(
                (type_index, [(raw[i * 2], raw[i * 2 + 1]) for i in range(fields)])
            )
        self.struct_by_name = {
            self.types[s[0]]: index for index, s in enumerate(self.structs)
        }

    def _expect(self, offset: int, tag: bytes) -> int:
        if self.data[offset : offset + 4] != tag:
            raise BlendError(
                f"DNA corrompu : {tag!r} attendu, "
                f"{self.data[offset:offset + 4]!r} trouvé"
            )
        return offset + 4

    # -- field access ---------------------------------------------------
    def layout(self, struct_index: int) -> tuple[int, dict[str, tuple[int, str, str]]]:
        """Field name to (offset, type name, declaration) for one struct."""
        type_index, fields = self.structs[struct_index]
        offsets: dict[str, tuple[int, str, str]] = {}
        cursor = 0
        for field_type, field_name in fields:
            name = self.names[field_name]
            size = self._field_size(field_type, name)
            offsets[_bare(name)] = (cursor, self.types[field_type], name)
            cursor += size
        return self.type_sizes[type_index], offsets

    def _field_size(self, type_index: int, name: str) -> int:
        if name.startswith("*"):
            base = self.pointer
        else:
            base = self.type_sizes[type_index]
        return base * _array_length(name)

    def read(self, block: _Block, index: int = 0) -> dict[str, Any]:
        """One struct out of a block, as a plain dict of raw field values."""
        size, offsets = self.layout(block.sdna)
        base = block.start + index * size
        out: dict[str, Any] = {}
        for name, (offset, type_name, declaration) in offsets.items():
            out[name] = self._value(base + offset, type_name, declaration)
        return out

    def _value(self, offset: int, type_name: str, declaration: str) -> Any:
        count = _array_length(declaration)
        if declaration.startswith("*"):
            code = "Q" if self.pointer == 8 else "I"
            values = struct.unpack_from(self.endian + code * count, self.data, offset)
            return values[0] if count == 1 else list(values)

        code = {
            "char": "b", "uchar": "B", "short": "h", "ushort": "H",
            "int": "i", "uint": "I", "float": "f", "double": "d",
            "int64_t": "q", "uint64_t": "Q",
        }.get(type_name)
        if code is None:
            return None  # A nested struct; nothing here needs to read one whole.
        if type_name == "char" and count > 1:
            raw = self.data[offset : offset + count]
            return raw.split(b"\0", 1)[0].decode("utf8", "replace")
        values = struct.unpack_from(self.endian + code * count, self.data, offset)
        return values[0] if count == 1 else list(values)

    def field_offset(self, struct_index: int, path: str) -> tuple[int, str, str]:
        """Offset of a possibly nested field, e.g. ``id.name``."""
        cursor = 0
        current = struct_index
        parts = path.split(".")
        for step, name in enumerate(parts):
            _, offsets = self.layout(current)
            if name not in offsets:
                raise BlendError(f"champ {path!r} absent de ce .blend")
            offset, type_name, declaration = offsets[name]
            cursor += offset
            if step == len(parts) - 1:
                return cursor, type_name, declaration
            current = self.struct_by_name[type_name]
        raise BlendError(f"champ {path!r} absent de ce .blend")

    def get(self, block: _Block, path: str) -> Any:
        offset, type_name, declaration = self.field_offset(block.sdna, path)
        return self._value(block.start + offset, type_name, declaration)

    def follow(self, address: Any) -> _Block | None:
        return self.by_address.get(address) if address else None

    def blocks_of(self, code: bytes) -> list[_Block]:
        return [b for b in self.blocks if b.code[:2] == code]


def _bare(name: str) -> str:
    return name.lstrip("*").split("[")[0].split("(")[0].replace(")", "")


def _array_length(name: str) -> int:
    total = 1
    rest = name
    while "[" in rest:
        start = rest.index("[")
        end = rest.index("]", start)
        total *= int(rest[start + 1 : end])
        rest = rest[end + 1 :]
    return total


# -- reading meshes -----------------------------------------------------------


def read_blend(path: str | Path) -> dict[str, Mesh]:
    """Every mesh object in the file, by object name."""
    data = _open(Path(path))
    blend = BlendFile(data)

    meshes: dict[str, Mesh] = {}
    for block in blend.blocks_of(b"OB"):
        name = blend.get(block, "id.name")
        if not isinstance(name, str):
            continue
        mesh_block = blend.follow(blend.get(block, "data"))
        if mesh_block is None or mesh_block.code[:2] != b"ME":
            continue
        geometry = _read_mesh(blend, mesh_block)
        if geometry is None:
            continue
        geometry.name = name
        geometry.matrix = _object_matrix(blend, block)
        meshes[name] = geometry
    return meshes


def _open(path: Path) -> bytes:
    raw = path.read_bytes()
    if raw[:7] == b"BLENDER":
        return raw
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if raw[:4] == b"\x28\xb5\x2f\xfd":
        raise BlendError(
            f"{path.name} est compressé en Zstandard, que Python ne sait pas "
            f"décompresser ici. Dans Blender : Fichier > Enregistrer sous, "
            f"décoche « Compresser », enregistre, et repasse ce fichier-là."
        )
    raise BlendError(f"{path.name} ne ressemble pas à un fichier .blend")


def _object_matrix(blend: BlendFile, block: _Block) -> np.ndarray:
    """Build the object's transform from what the file actually stores.

    Blender 4.0 moved the evaluated ``object_to_world`` matrix into runtime
    data, which is not saved. What survives is loc/rot/scale, so the matrix is
    rebuilt from those — which is the same thing for an un-parented object at
    rest, and this reads rigs at rest.
    """
    location = np.asarray(blend.get(block, "loc") or [0, 0, 0], dtype=float)
    size = np.asarray(blend.get(block, "size") or [1, 1, 1], dtype=float)
    mode = blend.get(block, "rotmode") or 0

    if mode == 0:  # quaternion, stored wxyz
        w, x, y, z = blend.get(block, "quat") or [1, 0, 0, 0]
        rotation = _quat_matrix(x, y, z, w)
    elif mode < 0:  # axis-angle
        axis = np.asarray(blend.get(block, "rotAxis") or [0, 0, 1], dtype=float)
        rotation = _axis_angle(axis, float(blend.get(block, "rotAngle") or 0.0))
    else:
        rotation = _euler_matrix(blend.get(block, "rot") or [0, 0, 0], mode)

    matrix = np.eye(4)
    matrix[:3, :3] = rotation * size
    matrix[:3, 3] = location
    return matrix


def _quat_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    n = float(np.hypot(np.hypot(x, y), np.hypot(z, w))) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - w*z), 2*(x*z + w*y)],
        [2*(x*y + w*z), 1 - 2*(x*x + z*z), 2*(y*z - w*x)],
        [2*(x*z - w*y), 2*(y*z + w*x), 1 - 2*(x*x + y*y)],
    ])


def _axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    length = float(np.linalg.norm(axis))
    if length < 1e-9:
        return np.eye(3)
    axis = axis / length
    half = angle / 2.0
    return _quat_matrix(*(axis * np.sin(half)), float(np.cos(half)))


#: Blender's rotmode values are the axis order, 1 == XYZ through 6 == ZYX.
_EULER_ORDERS = {1: "XYZ", 2: "XZY", 3: "YXZ", 4: "YZX", 5: "ZXY", 6: "ZYX"}


def _euler_matrix(angles, mode: int) -> np.ndarray:
    order = _EULER_ORDERS.get(mode, "XYZ")
    axes = {
        "X": lambda a: np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]]),
        "Y": lambda a: np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]]),
        "Z": lambda a: np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]]),
    }
    by_axis = dict(zip("XYZ", angles))
    matrix = np.eye(3)
    # Blender applies the named order right to left.
    for axis in reversed(order):
        matrix = matrix @ axes[axis](float(by_axis[axis]))
    return matrix


def _read_mesh(blend: BlendFile, block: _Block) -> Mesh | None:
    total_vertices = blend.get(block, "totvert") or 0
    total_corners = blend.get(block, "totloop") or 0
    total_faces = blend.get(block, "totpoly") or 0
    if not total_vertices or not total_corners:
        return None

    positions = _vertex_positions(blend, block, total_vertices)
    corners = _corner_vertices(blend, block, total_corners)
    if positions is None or corners is None:
        return None

    offsets = _face_offsets(blend, block, total_faces, total_corners)
    triangles = _triangulate(corners, offsets)
    if not len(triangles):
        return None
    return Mesh(name="", vertices=positions, triangles=triangles)


def _vertex_positions(blend: BlendFile, block: _Block, count: int) -> np.ndarray | None:
    """Blender 4.x keeps these in a 'position' attribute; 3.x in MVert."""
    data = _layer(blend, block, "vdata", CD_PROP_FLOAT3, "position")
    if data is not None:
        return _floats(blend, data, count, 3)

    data = _layer(blend, block, "vdata", CD_MVERT, None) or blend.get(block, "mvert")
    target = blend.follow(data)
    if target is None:
        return None
    stride = blend.type_sizes[blend.structs[target.sdna][0]] if target.sdna else 12
    out = np.zeros((count, 3))
    for i in range(count):
        out[i] = struct.unpack_from(blend.endian + "fff", blend.data, target.start + i * stride)
    return out


def _corner_vertices(blend: BlendFile, block: _Block, count: int) -> np.ndarray | None:
    data = _layer(blend, block, "ldata", CD_PROP_INT32, ".corner_vert")
    if data is not None:
        target = blend.follow(data)
        if target is None:
            return None
        return np.asarray(
            struct.unpack_from(blend.endian + "i" * count, blend.data, target.start)
        )

    data = _layer(blend, block, "ldata", CD_MLOOP, None) or blend.get(block, "mloop")
    target = blend.follow(data)
    if target is None:
        return None
    stride = blend.type_sizes[blend.structs[target.sdna][0]] if target.sdna else 8
    return np.asarray([
        struct.unpack_from(blend.endian + "i", blend.data, target.start + i * stride)[0]
        for i in range(count)
    ])


def _face_offsets(
    blend: BlendFile, block: _Block, faces: int, corners: int
) -> np.ndarray:
    """Where each face starts in the corner array.

    Blender 4.x stores this directly. 3.x stored a loopstart per MPoly; falling
    back to quads is wrong, so the MPoly array is read when it is there.
    """
    pointer = blend.get(block, "poly_offset_indices")
    target = blend.follow(pointer)
    if target is not None and faces:
        return np.asarray(
            struct.unpack_from(blend.endian + "i" * (faces + 1), blend.data, target.start)
        )

    target = blend.follow(blend.get(block, "mpoly"))
    if target is not None and faces:
        stride = blend.type_sizes[blend.structs[target.sdna][0]] if target.sdna else 12
        starts = [
            struct.unpack_from(blend.endian + "i", blend.data, target.start + i * stride)[0]
            for i in range(faces)
        ]
        return np.asarray([*starts, corners])
    return np.asarray([0, corners])


def _layer(blend: BlendFile, block: _Block, which: str, kind: int, name: str | None):
    """The ``data`` pointer of one CustomData layer, or None.

    Matched on the layer's *name* whenever there is one, and only on the type
    number otherwise. The numbers are not stable: this file calls a float3
    layer type 48 where the constant in Blender's headers is 47, because the
    enum has had values inserted into it over the years. The names — the
    literal strings ``position`` and ``.corner_vert`` — have not moved.
    """
    try:
        base, _, _ = blend.field_offset(block.sdna, f"{which}.layers")
        total, _, _ = blend.field_offset(block.sdna, f"{which}.totlayer")
    except BlendError:
        return None

    code = "Q" if blend.pointer == 8 else "I"
    layers_pointer, = struct.unpack_from(blend.endian + code, blend.data, block.start + base)
    count, = struct.unpack_from(blend.endian + "i", blend.data, block.start + total)
    layers = blend.follow(layers_pointer)
    if layers is None or count <= 0:
        return None

    index = blend.struct_by_name["CustomDataLayer"]
    size, offsets = blend.layout(index)
    for i in range(count):
        start = layers.start + i * size
        if name is not None:
            raw = blend.data[start + offsets["name"][0] : start + offsets["name"][0] + 68]
            if raw.split(b"\0", 1)[0].decode("utf8", "replace") != name:
                continue
        else:
            layer_type, = struct.unpack_from(
                blend.endian + "i", blend.data, start + offsets["type"][0]
            )
            if layer_type != kind:
                continue
        pointer, = struct.unpack_from(
            blend.endian + code, blend.data, start + offsets["data"][0]
        )
        return pointer
    return None


def _floats(blend: BlendFile, pointer: int, count: int, width: int) -> np.ndarray | None:
    target = blend.follow(pointer)
    if target is None:
        return None
    values = struct.unpack_from(
        blend.endian + "f" * (count * width), blend.data, target.start
    )
    return np.asarray(values).reshape(count, width)


def _triangulate(corners: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    """Fan-triangulate every face. Convex enough for character meshes."""
    triangles: list[tuple[int, int, int]] = []
    for start, stop in pairwise(offsets):
        loop = corners[start:stop]
        for i in range(1, len(loop) - 1):
            triangles.append((int(loop[0]), int(loop[i]), int(loop[i + 1])))
    return np.asarray(triangles, dtype=int).reshape(-1, 3)
