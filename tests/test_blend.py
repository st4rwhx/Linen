"""Reading meshes out of a .blend, and fitting them onto the rig.

Nobody wants a 2 MB rig committed as a fixture, so the reader is exercised
against a .blend built here, byte by byte: a real header, a real DNA1 block
describing real structs, real blocks addressed by the pointers between them.
It is small, but it goes through the same path a Blender file does — the DNA
is parsed, field offsets are computed from declarations, pointers are followed
and CustomData layers are matched by name.

The layout it declares is Blender 4.x's: positions in a ``position`` attribute
layer, corners in ``.corner_vert``, faces as an offset array.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from linen.export.skin import SkinError, _fit, _simplify, _to_roblox, skin_from_blend
from linen.rigs import get_rig
from linen.sources.blend import BlendError, read_blend

# --- a .blend, written here ------------------------------------------------

#: (type, name) per struct, in declaration order. Sizes are derived from these,
#: exactly as the reader derives them, so the two cannot drift apart.
STRUCTS: dict[str, list[tuple[str, str]]] = {
    "ID": [("char", "name[66]"), ("char", "_pad[2]")],
    "CustomDataLayer": [
        ("int", "type"), ("int", "offset"), ("int", "flag"), ("int", "active"),
        ("int", "active_rnd"), ("int", "active_clone"), ("int", "active_mask"),
        ("int", "uid"), ("char", "name[68]"), ("char", "_pad1[4]"),
        ("void", "*data"), ("void", "*sharing_info"),
    ],
    "CustomData": [
        ("CustomDataLayer", "*layers"), ("int", "totlayer"), ("int", "maxlayer"),
        ("int", "totsize"), ("void", "*pool"), ("void", "*external"),
    ],
    "Mesh": [
        ("ID", "id"), ("int", "totvert"), ("int", "totedge"), ("int", "totpoly"),
        ("int", "totloop"), ("int", "*poly_offset_indices"),
        ("CustomData", "vdata"), ("CustomData", "edata"),
        ("CustomData", "pdata"), ("CustomData", "ldata"),
        ("void", "*mvert"), ("void", "*mloop"), ("void", "*mpoly"),
    ],
    "Object": [
        ("ID", "id"), ("void", "*data"), ("float", "loc[3]"), ("float", "size[3]"),
        ("float", "quat[4]"), ("float", "rot[3]"), ("float", "rotAxis[3]"),
        ("float", "rotAngle"), ("short", "rotmode"), ("char", "_pad[6]"),
    ],
}

BASE_SIZES = {"char": 1, "short": 2, "int": 4, "float": 4, "void": 0}
POINTER = 8


def _count(name: str) -> int:
    total = 1
    rest = name
    while "[" in rest:
        start, end = rest.index("["), rest.index("]")
        total *= int(rest[start + 1 : end])
        rest = rest[end + 1 :]
    return total


def _sizes() -> dict[str, int]:
    sizes = dict(BASE_SIZES)
    for name in ("ID", "CustomDataLayer", "CustomData", "Mesh", "Object"):
        total = 0
        for type_name, field in STRUCTS[name]:
            unit = POINTER if field.startswith("*") else sizes[type_name]
            total += unit * _count(field)
        sizes[name] = total
    return sizes


def _dna() -> bytes:
    sizes = _sizes()
    types = list(BASE_SIZES) + ["ID", "CustomDataLayer", "CustomData", "Mesh", "Object"]
    names: list[str] = []
    for fields in STRUCTS.values():
        for _, field in fields:
            if field not in names:
                names.append(field)

    def block(tag: bytes, payload: bytes) -> bytes:
        return tag + payload

    def strings(items: list[str]) -> bytes:
        out = struct.pack("<i", len(items))
        for item in items:
            out += item.encode() + b"\0"
        return out

    def pad(data: bytes) -> bytes:
        return data + b"\0" * ((4 - len(data) % 4) % 4)

    body = b"SDNA" + block(b"NAME", pad(strings(names)))
    body += block(b"TYPE", pad(strings(types)))
    body += block(b"TLEN", pad(struct.pack(f"<{len(types)}H", *(sizes[t] for t in types))))

    packed = struct.pack("<i", len(STRUCTS))
    for name, fields in STRUCTS.items():
        packed += struct.pack("<HH", types.index(name), len(fields))
        for type_name, field in fields:
            packed += struct.pack("<HH", types.index(type_name), names.index(field))
    body += block(b"STRC", packed)
    return body


def _sdna_index(name: str) -> int:
    return list(STRUCTS).index(name)


class _Writer:
    """Blocks and the addresses that point between them."""

    def __init__(self) -> None:
        self.blocks: list[bytes] = []
        self.next = 0x1000

    def add(self, code: bytes, payload: bytes, sdna: int = 0, count: int = 1) -> int:
        address = self.next
        self.next += max(len(payload), 8) + 8
        self.blocks.append(
            code.ljust(4, b"\0")
            + struct.pack("<i", len(payload))
            + struct.pack("<Q", address)
            + struct.pack("<ii", sdna, count)
            + payload
        )
        return address

    def build(self) -> bytes:
        return (
            b"BLENDER-v404"
            + b"".join(self.blocks)
            + b"ENDB"
            + struct.pack("<i", 0)
            + struct.pack("<Q", 0)
            + struct.pack("<ii", 0, 0)
        )


def _custom_data(layers_address: int, count: int) -> bytes:
    return struct.pack("<Q", layers_address) + struct.pack("<iii", count, count, 0) + b"\0" * 16


def _layer(kind: int, name: str, data_address: int) -> bytes:
    return (
        struct.pack("<8i", kind, 0, 0, 0, 0, 0, 0, 0)
        + name.encode().ljust(68, b"\0")
        + b"\0" * 4
        + struct.pack("<Q", data_address)
        + struct.pack("<Q", 0)
    )


def tiny_blend(
    part: str = "LeftHand",
    *,
    vertices: list[tuple[float, float, float]] | None = None,
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> bytes:
    """One object holding one square-based pyramid, as a real .blend."""
    if vertices is None:
        # A unit cube's worth of extent, so the fit is easy to reason about.
        vertices = [
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (0, 0, 1),
        ]
    faces = [(0, 1, 2, 3), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    corners = [index for face in faces for index in face]
    offsets = [0]
    for face in faces:
        offsets.append(offsets[-1] + len(face))

    writer = _Writer()
    positions = writer.add(
        b"DATA", struct.pack(f"<{len(vertices) * 3}f", *[v for p in vertices for v in p])
    )
    corner_data = writer.add(b"DATA", struct.pack(f"<{len(corners)}i", *corners))
    offset_data = writer.add(b"DATA", struct.pack(f"<{len(offsets)}i", *offsets))

    position_layer = writer.add(b"DATA", _layer(48, "position", positions))
    corner_layer = writer.add(b"DATA", _layer(11, ".corner_vert", corner_data))
    empty = writer.add(b"DATA", _layer(0, "", 0))

    mesh = struct.pack("<66s2x", f"ME{part}".encode())
    mesh += struct.pack("<iiii", len(vertices), 0, len(faces), len(corners))
    mesh += struct.pack("<Q", offset_data)
    mesh += _custom_data(position_layer, 1)
    mesh += _custom_data(empty, 0)
    mesh += _custom_data(empty, 0)
    mesh += _custom_data(corner_layer, 1)
    mesh += struct.pack("<QQQ", 0, 0, 0)
    mesh_address = writer.add(b"ME\0\0", mesh, _sdna_index("Mesh"))

    obj = struct.pack("<66s2x", f"OB{part}".encode())
    obj += struct.pack("<Q", mesh_address)
    obj += struct.pack("<3f", *location)
    obj += struct.pack("<3f", *scale)
    obj += struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)
    obj += struct.pack("<3f", 0.0, 0.0, 0.0)
    obj += struct.pack("<3f", 0.0, 0.0, 1.0)
    obj += struct.pack("<f", 0.0)
    obj += struct.pack("<h6x", 0)
    writer.add(b"OB\0\0", obj, _sdna_index("Object"))

    writer.add(b"DNA1", _dna())
    return writer.build()


@pytest.fixture
def blend_file(tmp_path):
    def write(name: str = "rig.blend", **kwargs) -> str:
        path = tmp_path / name
        path.write_bytes(tiny_blend(**kwargs))
        return str(path)

    return write


# --- the reader ------------------------------------------------------------
def test_a_mesh_object_is_read_with_its_name_geometry_and_faces(blend_file):
    meshes = read_blend(blend_file())
    assert set(meshes) == {"OBLeftHand"}

    mesh = meshes["OBLeftHand"]
    assert len(mesh.vertices) == 5
    # A quad and four triangles fan out to six triangles.
    assert len(mesh.triangles) == 6
    assert mesh.triangles.max() < len(mesh.vertices)


def test_n_gons_are_fan_triangulated_rather_than_dropped(blend_file):
    mesh = read_blend(blend_file())["OBLeftHand"]
    quad = {tuple(sorted(t)) for t in mesh.triangles[:2]}
    assert quad == {(0, 1, 2), (0, 2, 3)}, "the base quad must become two triangles"


def test_the_object_transform_is_rebuilt_from_loc_and_scale(blend_file):
    """Blender 4 stopped saving the evaluated matrix; only loc/rot/scale survive."""
    mesh = read_blend(blend_file(location=(2.0, 0.0, 5.0), scale=(2.0, 2.0, 2.0)))
    world = mesh["OBLeftHand"].world_vertices
    assert world.min(axis=0) == pytest.approx([0.0, -2.0, 3.0])
    assert world.max(axis=0) == pytest.approx([4.0, 2.0, 7.0])


def test_a_file_that_is_not_a_blend_says_so(tmp_path):
    path = tmp_path / "nope.blend"
    path.write_bytes(b"this is not a blend file at all")
    with pytest.raises(BlendError, match="ne ressemble pas"):
        read_blend(path)


def test_a_zstandard_blend_explains_how_to_re_export(tmp_path):
    """The common failure: Blender compresses by default and Python cannot."""
    path = tmp_path / "compressed.blend"
    path.write_bytes(b"\x28\xb5\x2f\xfd" + b"\0" * 64)
    with pytest.raises(BlendError, match="Compresser"):
        read_blend(path)


# --- fitting onto the rig --------------------------------------------------
def test_a_skin_part_is_scaled_into_the_box_linen_measured(blend_file):
    skin = skin_from_blend(blend_file(), rig="R15")
    assert skin["rig"] == "R15"
    assert set(skin["parts"]) == {"LeftHand"}

    vertices = np.asarray(skin["parts"]["LeftHand"]["vertices"]).reshape(-1, 3)
    size = get_rig("R15").part("LeftHand").size
    span = vertices.max(axis=0) - vertices.min(axis=0)
    assert span == pytest.approx(np.asarray(size), abs=1e-3)
    assert vertices.mean(axis=0) == pytest.approx([0, 0, 0], abs=0.5)


def test_the_part_it_is_fitted_to_is_the_one_it_is_named_after(blend_file):
    """Names carry the mapping; nothing here is positional."""
    skin = skin_from_blend(blend_file(part="Head"), rig="R15")
    vertices = np.asarray(skin["parts"]["Head"]["vertices"]).reshape(-1, 3)
    span = vertices.max(axis=0) - vertices.min(axis=0)
    assert span == pytest.approx(np.asarray(get_rig("R15").part("Head").size), abs=1e-3)


def test_the_parts_a_skin_does_not_cover_are_reported_not_hidden(blend_file):
    skin = skin_from_blend(blend_file(), rig="R15")
    assert "Head" in skin["missing"]
    assert "LeftHand" not in skin["missing"]


def test_a_file_with_no_roblox_part_names_says_what_it_found(blend_file):
    with pytest.raises(SkinError, match="Cube"):
        skin_from_blend(blend_file(part="Cube"), rig="R15")


def test_r6_names_do_not_silently_match_r15_geometry(blend_file):
    with pytest.raises(SkinError):
        skin_from_blend(blend_file(part="LeftHand"), rig="R6")


# --- axes ------------------------------------------------------------------
def test_blender_z_up_becomes_roblox_y_up_without_mirroring():
    """Swapping Y and Z alone flips handedness, and a mirrored rig is subtle.

    Left has to stay on the left, so the mapping is (x, y, z) -> (x, z, -y),
    whose determinant is +1.
    """
    up = _to_roblox(np.array([[0.0, 0.0, 1.0]]))
    assert up[0] == pytest.approx([0.0, 1.0, 0.0]), "Blender +Z is Roblox up"

    front = _to_roblox(np.array([[0.0, -1.0, 0.0]]))
    assert front[0] == pytest.approx([0.0, 0.0, 1.0])

    left = _to_roblox(np.array([[-1.0, 0.0, 0.0]]))
    assert left[0] == pytest.approx([-1.0, 0.0, 0.0]), "left must stay left"

    basis = _to_roblox(np.eye(3))
    assert np.linalg.det(basis) == pytest.approx(1.0), "the mapping must not mirror"


# --- decimation ------------------------------------------------------------
def _grid_part(steps: int = 22) -> dict:
    """A dense plate: enough triangles that clustering has something to do."""
    xs = np.linspace(-0.5, 0.5, steps)
    grid = np.array([(x, y, 0.02 * (x + y)) for x in xs for y in xs])
    triangles = []
    for i in range(steps - 1):
        for j in range(steps - 1):
            a = i * steps + j
            triangles += [a, a + 1, a + steps, a + 1, a + steps + 1, a + steps]
    return {
        "vertices": [float(v) for v in grid.reshape(-1)],
        "triangles": triangles,
    }


def test_decimation_reduces_the_count_and_keeps_the_shape():
    part = _grid_part()
    before = len(part["triangles"]) // 3
    reduced = _simplify(part, 0.25)
    after = len(reduced["triangles"]) // 3

    assert after < before, "a budget that bites has to actually reduce"
    assert after > 0, "and must not delete the part"

    original = np.asarray(part["vertices"]).reshape(-1, 3)
    kept = np.asarray(reduced["vertices"]).reshape(-1, 3)
    assert kept.min(axis=0) == pytest.approx(original.min(axis=0), abs=0.08)
    assert kept.max(axis=0) == pytest.approx(original.max(axis=0), abs=0.08)


def test_decimation_never_emits_a_degenerate_triangle():
    reduced = _simplify(_grid_part(), 0.2)
    triangles = np.asarray(reduced["triangles"]).reshape(-1, 3)
    assert len(triangles), "something must survive"
    assert (triangles[:, 0] != triangles[:, 1]).all()
    assert (triangles[:, 1] != triangles[:, 2]).all()
    assert (triangles[:, 0] != triangles[:, 2]).all()
    assert triangles.max() < len(reduced["vertices"]) // 3


def test_a_skin_already_inside_its_budget_is_left_alone(blend_file):
    skin = skin_from_blend(blend_file(), rig="R15", budget=10_000)
    assert len(skin["parts"]["LeftHand"]["triangles"]) // 3 == 6


def test_the_budget_is_reported_so_a_heavy_rig_is_visible(blend_file):
    skin = skin_from_blend(blend_file(), rig="R15")
    assert skin["triangles"] == 6


# --- what the viewer gets --------------------------------------------------
def test_a_fitted_part_is_plain_json_the_page_can_hold(blend_file):
    import json

    skin = skin_from_blend(blend_file(), rig="R15")
    round_tripped = json.loads(json.dumps(skin))
    assert round_tripped["parts"]["LeftHand"]["triangles"]


def test_fitting_a_flat_mesh_does_not_divide_by_zero():
    """A plane has zero extent on one axis, and rigs do contain flat pieces."""
    flat = type("M", (), {
        "world_vertices": np.array([[0.0, 0, 0], [1.0, 0, 0], [1.0, 1.0, 0]]),
        "triangles": np.array([[0, 1, 2]]),
    })()
    fitted = _fit(flat, (1.0, 1.0, 1.0))
    assert all(np.isfinite(fitted["vertices"]))
