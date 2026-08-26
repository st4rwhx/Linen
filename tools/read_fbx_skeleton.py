"""Read joint positions out of a binary FBX, to check a rig against the source.

Roblox publishes its Classic mannequin as an FBX reference file, which makes it
the authoritative answer to "how long is an R15 forearm" — a question this
project had previously answered from memory, and answered wrong by a factor of
two.

Only what is needed to walk the skeleton is implemented: the node tree, the
handful of property types Roblox's exporter emits, ``Model`` nodes with their
local translations, and the ``Connections`` block that says which joint hangs
off which. Meshes, materials and animation are skipped.

    python tools/read_fbx_skeleton.py ClassicMannequin.fbx
"""

from __future__ import annotations

import argparse
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"Kaydara FBX Binary  \x00"
#: Arrays are length-prefixed and optionally deflated; scalars are not.
_SCALAR = {"Y": ("h", 2), "C": ("?", 1), "I": ("i", 4), "F": ("f", 4), "D": ("d", 8), "L": ("q", 8)}
_ARRAY = {"f": ("f", 4), "d": ("d", 8), "l": ("q", 8), "i": ("i", 4), "b": ("b", 1)}


class FbxError(ValueError):
    pass


@dataclass
class Node:
    name: str
    properties: list = field(default_factory=list)
    children: list[Node] = field(default_factory=list)

    def find(self, name: str) -> Node | None:
        for child in self.children:
            if child.name == name:
                return child
        return None

    def find_all(self, name: str) -> list[Node]:
        return [child for child in self.children if child.name == name]


def parse(path: Path) -> tuple[Node, int]:
    data = path.read_bytes()
    if not data.startswith(MAGIC):
        raise FbxError(f"{path.name}: not a binary FBX (ASCII FBX is not supported)")
    version = struct.unpack_from("<I", data, 23)[0]
    # 7500 moved the record offsets from 32-bit to 64-bit.
    wide = version >= 7500

    root = Node("Root")
    offset = 27
    while True:
        node, offset, ended = _read_node(data, offset, wide)
        if ended:
            break
        root.children.append(node)
    return root, version


def _read_node(data: bytes, offset: int, wide: bool) -> tuple[Node, int, bool]:
    fmt = "<QQQB" if wide else "<IIIB"
    size = 25 if wide else 13
    end_offset, property_count, _property_len, name_len = struct.unpack_from(fmt, data, offset)
    offset += size

    if end_offset == 0:
        return Node(""), offset, True  # the null record that closes a list

    name = data[offset : offset + name_len].decode("utf-8", "replace")
    offset += name_len

    node = Node(name)
    for _ in range(property_count):
        value, offset = _read_property(data, offset)
        node.properties.append(value)

    # Anything left before end_offset is a nested node list.
    while offset < end_offset - size:
        child, offset, ended = _read_node(data, offset, wide)
        if ended:
            break
        node.children.append(child)

    return node, end_offset, False


def _read_property(data: bytes, offset: int):
    code = chr(data[offset])
    offset += 1

    if code in _SCALAR:
        fmt, width = _SCALAR[code]
        (value,) = struct.unpack_from("<" + fmt, data, offset)
        return value, offset + width

    if code in _ARRAY:
        fmt, width = _ARRAY[code]
        length, encoding, compressed = struct.unpack_from("<III", data, offset)
        offset += 12
        payload = data[offset : offset + compressed]
        offset += compressed
        if encoding == 1:
            payload = zlib.decompress(payload)
        return list(struct.unpack_from("<" + fmt * length, payload, 0)), offset

    if code in ("S", "R"):
        (length,) = struct.unpack_from("<I", data, offset)
        offset += 4
        raw = data[offset : offset + length]
        offset += length
        return (raw.decode("utf-8", "replace") if code == "S" else raw), offset

    raise FbxError(f"unknown property type {code!r} at byte {offset - 1}")


@dataclass
class Joint:
    uid: int
    name: str
    kind: str
    translation: tuple[float, float, float]
    parent: int | None = None


def skeleton(root: Node) -> dict[int, Joint]:
    """Every Model node, with its local translation and its parent."""
    objects = root.find("Objects")
    if objects is None:
        raise FbxError("no Objects section")

    joints: dict[int, Joint] = {}
    for model in objects.find_all("Model"):
        uid, raw_name, kind = model.properties[0], model.properties[1], model.properties[2]
        # FBX names arrive as "Name\x00\x01Model"; keep the readable half.
        name = raw_name.split("\x00")[0]

        translation = (0.0, 0.0, 0.0)
        properties = model.find("Properties70")
        if properties is not None:
            for entry in properties.find_all("P"):
                if entry.properties and entry.properties[0] == "Lcl Translation":
                    translation = tuple(float(v) for v in entry.properties[4:7])
        joints[uid] = Joint(uid, name, kind, translation)

    connections = root.find("Connections")
    if connections is not None:
        for entry in connections.find_all("C"):
            if entry.properties and entry.properties[0] == "OO":
                child, parent = entry.properties[1], entry.properties[2]
                if child in joints and parent in joints:
                    joints[child].parent = parent

    return joints


def world_positions(joints: dict[int, Joint]) -> dict[str, tuple[float, float, float]]:
    """Accumulate local translations down each chain."""
    resolved: dict[int, tuple[float, float, float]] = {}

    def place(uid: int) -> tuple[float, float, float]:
        if uid in resolved:
            return resolved[uid]
        joint = joints[uid]
        base = (0.0, 0.0, 0.0) if joint.parent is None else place(joint.parent)
        resolved[uid] = tuple(b + t for b, t in zip(base, joint.translation))
        return resolved[uid]

    return {joints[uid].name: place(uid) for uid in joints}


def part_bounds(root: Node) -> dict[str, tuple[tuple[float, float, float], ...]]:
    """Axis-aligned bounds of every mesh, keyed by the part it belongs to.

    Roblox's mannequin ships geometry rather than a skeleton, so the honest way
    to get a limb's length is to measure its mesh. The bounds give both the
    part's size and where it sits, which is exactly the pair the rig needs.
    """
    objects = root.find("Objects")
    if objects is None:
        raise FbxError("no Objects section")

    meshes: dict[int, tuple[tuple[float, ...], tuple[float, ...]]] = {}
    for geometry in objects.find_all("Geometry"):
        vertices = geometry.find("Vertices")
        if vertices is None or not vertices.properties:
            continue
        flat = vertices.properties[0]
        xs, ys, zs = flat[0::3], flat[1::3], flat[2::3]
        if not xs:
            continue
        meshes[geometry.properties[0]] = (
            (min(xs), min(ys), min(zs)),
            (max(xs), max(ys), max(zs)),
        )

    names: dict[int, str] = {}
    for model in objects.find_all("Model"):
        names[model.properties[0]] = model.properties[1].split("\x00")[0]

    bounds: dict[str, tuple[tuple[float, float, float], ...]] = {}
    connections = root.find("Connections")
    if connections is not None:
        for entry in connections.find_all("C"):
            if entry.properties and entry.properties[0] == "OO":
                child, parent = entry.properties[1], entry.properties[2]
                if child in meshes and parent in names:
                    bounds[names[parent]] = meshes[child]
    return bounds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--filter", default="", help="only show joints containing this")
    parser.add_argument(
        "--bounds", action="store_true", help="measure each mesh instead of walking joints"
    )
    args = parser.parse_args()

    if args.bounds:
        root, version = parse(args.file)
        bounds = part_bounds(root)
        print(f"{args.file.name}: FBX {version}, {len(bounds)} meshes")
        print(f"{'part':<20} {'size x':>8} {'size y':>8} {'size z':>8} {'centre y':>9}")
        for name in sorted(bounds):
            (lo, hi) = bounds[name]
            size = tuple(h - l for l, h in zip(lo, hi))
            print(
                f"{name:<20} {size[0]:8.3f} {size[1]:8.3f} {size[2]:8.3f} "
                f"{(lo[1] + hi[1]) / 2:9.3f}"
            )
        lows = [b[0][1] for b in bounds.values()]
        highs = [b[1][1] for b in bounds.values()]
        print(f"\ntotal height = {max(highs) - min(lows):.3f}  (sole {min(lows):.3f})")
        return 0

    root, version = parse(args.file)
    joints = skeleton(root)
    positions = world_positions(joints)

    print(f"{args.file.name}: FBX {version}, {len(joints)} models")
    by_name = {joints[u].name: joints[u] for u in joints}
    for name in sorted(positions):
        if args.filter and args.filter.lower() not in name.lower():
            continue
        x, y, z = positions[name]
        parent = by_name[name].parent
        parent_name = joints[parent].name if parent in joints else "-"
        print(f"  {name:<22} {x:8.3f} {y:8.3f} {z:8.3f}   <- {parent_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
