"""Read Roblox's binary model format, enough to get an animation out of it.

A ``.rbxm`` is what Studio writes when you save an animation to a file, and it
is a binary container rather than the XML ``.rbxmx`` Linen exports. Reading it
matters for one reason: it is the format a game's existing animations are
already in, so it is the only way to take work that exists and move it.

The layout is a header, then a run of chunks — ``META``, ``INST``, ``PROP``,
``PRNT``, ``END`` — each optionally LZ4-compressed. ``INST`` declares a class
and the instances of it, ``PROP`` carries one property across every instance of
one class, and ``PRNT`` wires the tree.

The part that is easy to get wrong is that properties are stored **column-wise
and transformed**: a float array is byte-interleaved and has its sign bit
rotated to the bottom, and an integer array is interleaved and zigzagged. Read
naively it decodes to plausible-looking noise, which is why the tests check
CFrames for being real rotation matrices rather than for merely parsing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: What every binary model starts with.
MAGIC = b"<roblox!\x89\xff\r\n\x1a\n\x00\x00"

#: Property type tags, of the handful an animation uses.
STRING, BOOL, INT32, FLOAT32, FLOAT64 = 0x01, 0x02, 0x03, 0x04, 0x05
CFRAME, ENUM, REFERENT = 0x10, 0x12, 0x13


class RbxmError(ValueError):
    """A file that cannot be read, phrased for whoever exported it."""


class UnknownProperty(RbxmError):
    """A property whose type this reader has no decoder for.

    This is the one failure that is safe to skip: an animation needs `Name`,
    `CFrame`, `Time` and the easing, and a file carrying a `Font` or a
    `SecurityCapabilities` beside them is still perfectly readable. Every other
    failure means a column this reader claimed to understand did not decode,
    and skipping those is how an animation silently arrives empty.
    """


@dataclass
class Instance:
    """One object out of the file, with its properties and its children."""

    referent: int
    class_name: str
    properties: dict[str, object] = field(default_factory=dict)
    children: list[Instance] = field(default_factory=list)
    parent: Instance | None = None

    @property
    def name(self) -> str:
        value = self.properties.get("Name")
        return value if isinstance(value, str) else ""

    def of_class(self, class_name: str) -> list[Instance]:
        """Every descendant of ``class_name``, depth first."""
        found = []
        for child in self.children:
            if child.class_name == class_name:
                found.append(child)
            found += child.of_class(class_name)
        return found


def lz4_decompress(source: bytes, size: int) -> bytes:
    """LZ4 block format, which is what the chunks use.

    Written out rather than depended on: the block format is a token byte, a
    run of literals and a back-reference, and the back-reference may overlap
    what it is still writing — which is why the copy is a loop and not a slice.
    """
    out = bytearray()
    index = 0
    while index < len(source) and len(out) < size:
        token = source[index]
        index += 1

        literals = token >> 4
        if literals == 15:
            while True:
                extra = source[index]
                index += 1
                literals += extra
                if extra != 255:
                    break
        out += source[index : index + literals]
        index += literals

        if index >= len(source):
            break

        offset = source[index] | (source[index + 1] << 8)
        index += 2
        if offset == 0:
            raise RbxmError("LZ4 stream has a zero back-reference")

        length = token & 15
        if length == 15:
            while True:
                extra = source[index]
                index += 1
                length += extra
                if extra != 255:
                    break
        length += 4

        start = len(out) - offset
        for step in range(length):
            out.append(out[start + step])
    return bytes(out)


def _chunks(data: bytes):
    offset = 32
    while offset < len(data):
        name = data[offset : offset + 4]
        offset += 4
        compressed, raw, _ = struct.unpack_from("<III", data, offset)
        offset += 12
        payload = data[offset : offset + (compressed or raw)]
        offset += compressed or raw
        yield name, (lz4_decompress(payload, raw) if compressed else payload)
        if name == b"END\x00":
            return


def _string(data: bytes, offset: int) -> tuple[str, int]:
    (length,) = struct.unpack_from("<I", data, offset)
    text = data[offset + 4 : offset + 4 + length]
    return text.decode("utf8", "replace"), offset + 4 + length


def _deinterleave(data: bytes, count: int) -> np.ndarray:
    """Undo the column-major byte layout the format stores arrays in.

    Four bytes of each value are written together with the other values' bytes
    of the same position, because that compresses far better. Read in order
    instead of transposed, every number comes out wrong but nothing errors.
    """
    if count == 0:
        return np.zeros((0, 4), dtype=np.uint8)
    block = np.frombuffer(data[: count * 4], dtype=np.uint8)
    return block.reshape(4, count).T


def _floats(data: bytes, count: int) -> np.ndarray:
    """A float array, de-interleaved and with its sign bit rotated back."""
    raw = _deinterleave(data, count).astype(np.uint32)
    packed = (raw[:, 0] << 24) | (raw[:, 1] << 16) | (raw[:, 2] << 8) | raw[:, 3]
    # Stored rotated left by one so the sign ends up in the low bit; small
    # positive numbers then share a leading zero byte and compress.
    rotated = ((packed >> 1) | (packed << 31)).astype(np.uint32)
    return rotated.view(np.float32).astype(float)


def _ints(data: bytes, count: int) -> np.ndarray:
    """An int array, de-interleaved and un-zigzagged."""
    raw = _deinterleave(data, count).astype(np.uint32)
    packed = (raw[:, 0] << 24) | (raw[:, 1] << 16) | (raw[:, 2] << 8) | raw[:, 3]
    # Un-zigzag in **signed** space. Done on the unsigned type, negating the low
    # bit yields 4294967295 rather than -1, and every negative value comes back
    # as itself plus 2^32 — which does not error, it just silently produces
    # referents four billion apart and an empty tree.
    signed = packed.astype(np.int64)
    return (signed >> 1) ^ (-(signed & 1))


#: The six axis-aligned unit vectors, in the order the format numbers them.
_AXES = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
    (-1.0, 0.0, 0.0),
    (0.0, -1.0, 0.0),
    (0.0, 0.0, -1.0),
)


def _rotation_ids() -> dict[int, np.ndarray]:
    """The axis-aligned rotations the format writes as a single byte.

    A CFrame whose rotation happens to be axis-aligned is stored as one id
    instead of nine floats, and the id is built from the first two rows of the
    matrix: ``first * 6 + second + 1``, indexing the six unit vectors above.
    Rows that are parallel describe no rotation and are skipped, which is what
    leaves the 24 ids the format documents, running from 0x02 to 0x23 — and
    both ends of that range fall out of this arithmetic rather than being
    asserted, which is the check that the formula is the right one.

    Only ``0x02`` — the identity — has been seen in a real animation, across
    every file this was built against. The identity is its own transpose, so
    that much is convention-proof; the other 23 entries assume the id is built
    from rows, the order the nine floats are stored in.
    """
    table: dict[int, np.ndarray] = {}
    for first, row in enumerate(_AXES):
        for second, column in enumerate(_AXES):
            third = np.cross(row, column)
            if not third.any():  # parallel rows describe no rotation
                continue
            table[first * 6 + second + 1] = np.array([row, column, third])
    return table


ROTATION_IDS = _rotation_ids()


def _special(identifier: int) -> np.ndarray | None:
    """The axis-aligned rotation an id stands for, or ``None`` for nine floats."""
    if identifier == 0:
        return None
    rotation = ROTATION_IDS.get(identifier)
    if rotation is None:
        raise RbxmError(
            f"CFrame carries the packed rotation id {identifier:#04x}, which is "
            f"outside the {min(ROTATION_IDS):#04x}-{max(ROTATION_IDS):#04x} the "
            f"format defines — the file is not being read where it is claimed."
        )
    return rotation


def _values(kind: int, data: bytes, offset: int, count: int):
    """Decode one property column. Returns the values and the new offset."""
    if kind == STRING:
        out = []
        for _ in range(count):
            text, offset = _string(data, offset)
            out.append(text)
        return out, offset

    if kind == BOOL:
        out = [bool(data[offset + i]) for i in range(count)]
        return out, offset + count

    if kind in (INT32, ENUM):
        block = data[offset : offset + count * 4]
        return list(_ints(block, count)), offset + count * 4

    if kind == FLOAT32:
        block = data[offset : offset + count * 4]
        return list(_floats(block, count)), offset + count * 4

    if kind == FLOAT64:
        out = list(struct.unpack_from(f"<{count}d", data, offset))
        return out, offset + count * 8

    if kind == REFERENT:
        block = data[offset : offset + count * 4]
        return list(np.cumsum(_ints(block, count))), offset + count * 4

    if kind == CFRAME:
        rotations = []
        for _ in range(count):
            identifier = data[offset]
            offset += 1
            if identifier == 0:
                cells = struct.unpack_from("<9f", data, offset)
                offset += 36
                rotations.append(np.array(cells).reshape(3, 3))
            else:
                rotations.append(_special(identifier))
        positions = []
        for _ in range(3):
            block = data[offset : offset + count * 4]
            positions.append(_floats(block, count))
            offset += count * 4
        stacked = np.stack(positions, axis=1) if count else np.zeros((0, 3))
        return list(zip(rotations, stacked, strict=False)), offset

    raise UnknownProperty(f"property type {kind:#04x} is not one this reader handles")


def read_rbxm(path: str | Path) -> list[Instance]:
    """Every root instance in a binary model file."""
    path = Path(path)
    data = path.read_bytes()
    if not data:
        # An archive that could not decompress this entry leaves a name and no
        # bytes. Saying "not a Roblox model" of an empty file sends whoever
        # reads it looking at the wrong thing.
        raise RbxmError(
            f"{path.name}: the file is empty — 0 bytes. It did not come out of "
            f"whatever archive it was in; re-export it, or send it as a .zip."
        )
    if not data.startswith(MAGIC):
        raise RbxmError(
            f"{path.name}: not a binary Roblox model. An XML .rbxmx starts with "
            f"'<roblox' and is read by the exporter instead."
        )

    classes: dict[int, tuple[str, list[int]]] = {}
    instances: dict[int, Instance] = {}
    roots: list[Instance] = []

    for name, body in _chunks(data):
        if name == b"INST":
            (index,) = struct.unpack_from("<I", body, 0)
            class_name, offset = _string(body, 4)
            offset += 1  # is-service flag
            (count,) = struct.unpack_from("<I", body, offset)
            offset += 4
            referents = list(np.cumsum(_ints(body[offset : offset + count * 4], count)))
            classes[index] = (class_name, referents)
            for referent in referents:
                instances[int(referent)] = Instance(int(referent), class_name)

        elif name == b"PROP":
            (index,) = struct.unpack_from("<I", body, 0)
            prop, offset = _string(body, 4)
            kind = body[offset]
            offset += 1
            if index not in classes:
                continue
            _, referents = classes[index]
            try:
                values, _ = _values(kind, body, offset, len(referents))
            except UnknownProperty:
                continue  # a type no animation needs; the rest of the file stands
            for referent, value in zip(referents, values, strict=False):
                instances[int(referent)].properties[prop] = value

        elif name == b"PRNT":
            offset = 1  # version byte
            (count,) = struct.unpack_from("<I", body, offset)
            offset += 4
            children = np.cumsum(_ints(body[offset : offset + count * 4], count))
            offset += count * 4
            parents = np.cumsum(_ints(body[offset : offset + count * 4], count))
            for child, parent in zip(children, parents, strict=False):
                node = instances.get(int(child))
                if node is None:
                    continue
                if int(parent) == -1:
                    roots.append(node)
                else:
                    owner = instances.get(int(parent))
                    if owner is not None:
                        node.parent = owner
                        owner.children.append(node)

    return roots
