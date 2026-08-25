"""Minimal 3D math in Roblox conventions.

Roblox uses a right-handed, Y-up coordinate system where a part's "front"
faces -Z.  A ``CFrame`` is a rigid transform stored as a position plus a 3x3
rotation matrix whose columns are the local X, Y and Z axes expressed in the
parent space.

Everything here is vectorised over a leading frame axis where it makes sense,
because retargeting runs over thousands of frames.
"""

from __future__ import annotations

import numpy as np

EPS = 1e-8


# --------------------------------------------------------------------------
# vectors
# --------------------------------------------------------------------------
def normalize(v: np.ndarray, axis: int = -1) -> np.ndarray:
    """Unit vectors along ``axis``; zero-length vectors are left at zero."""
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return np.divide(v, n, out=np.zeros_like(v), where=n > EPS)


def orthonormal_basis(primary: np.ndarray, hint: np.ndarray) -> np.ndarray:
    """Build a rotation matrix whose local Y axis is ``primary``.

    ``hint`` disambiguates the roll around ``primary``: the local Z axis is
    pulled as close to ``hint`` as orthogonality allows.  Both arguments are
    ``(..., 3)``; the result is ``(..., 3, 3)`` with axes as *columns*.

    Roblox limb parts hang along their own -Y, so "primary" is the direction
    the bone points *from* its joint, negated by the caller when needed.
    """
    y = normalize(primary)
    h = normalize(hint)

    # x = y X h, falling back to a stable axis when y and h are colinear.
    x = np.cross(y, h)
    degenerate = np.linalg.norm(x, axis=-1) < 1e-4
    if np.any(degenerate):
        fallback = np.broadcast_to(np.array([1.0, 0.0, 0.0]), y.shape).copy()
        alt = np.cross(y, fallback)
        # if y is also colinear with X, use Z instead
        still = np.linalg.norm(alt, axis=-1) < 1e-4
        if np.any(still):
            alt = np.where(
                still[..., None],
                np.cross(y, np.broadcast_to(np.array([0.0, 0.0, 1.0]), y.shape)),
                alt,
            )
        x = np.where(degenerate[..., None], alt, x)
    x = normalize(x)
    z = normalize(np.cross(x, y))
    return np.stack([x, y, z], axis=-1)


# --------------------------------------------------------------------------
# rotations
# --------------------------------------------------------------------------
def mat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.matmul(a, b)


def mat_inv(r: np.ndarray) -> np.ndarray:
    """Inverse of a rotation matrix, i.e. its transpose."""
    return np.swapaxes(r, -1, -2)


def mat_to_quat(r: np.ndarray) -> np.ndarray:
    """Rotation matrices ``(..., 3, 3)`` to quaternions ``(..., 4)`` as xyzw.

    Uses the branch-free trace formulation with the largest-diagonal pivot so
    it stays conditioned near 180 degree rotations.
    """
    r = np.asarray(r, dtype=float)
    m00, m01, m02 = r[..., 0, 0], r[..., 0, 1], r[..., 0, 2]
    m10, m11, m12 = r[..., 1, 0], r[..., 1, 1], r[..., 1, 2]
    m20, m21, m22 = r[..., 2, 0], r[..., 2, 1], r[..., 2, 2]
    trace = m00 + m11 + m22

    q = np.empty(r.shape[:-2] + (4,), dtype=float)

    t0 = trace > 0.0
    t1 = ~t0 & (m00 >= m11) & (m00 >= m22)
    t2 = ~t0 & ~t1 & (m11 >= m22)
    t3 = ~t0 & ~t1 & ~t2

    # Each branch is evaluated for every element and then masked, so the three
    # inapplicable ones routinely divide by a zero pivot. Those results are
    # discarded; only the selected branch's pivot is guaranteed non-zero.
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.sqrt(np.maximum(trace + 1.0, 0.0)) * 2.0
        q[t0] = np.stack(
            [
                (m21 - m12) / s,
                (m02 - m20) / s,
                (m10 - m01) / s,
                0.25 * s,
            ],
            axis=-1,
        )[t0]

        s = np.sqrt(np.maximum(1.0 + m00 - m11 - m22, 0.0)) * 2.0
        q[t1] = np.stack(
            [0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s], axis=-1
        )[t1]

        s = np.sqrt(np.maximum(1.0 + m11 - m00 - m22, 0.0)) * 2.0
        q[t2] = np.stack(
            [(m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s], axis=-1
        )[t2]

        s = np.sqrt(np.maximum(1.0 + m22 - m00 - m11, 0.0)) * 2.0
        q[t3] = np.stack(
            [(m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s], axis=-1
        )[t3]

    return normalize(q)


def quat_to_mat(q: np.ndarray) -> np.ndarray:
    """Quaternions ``(..., 4)`` as xyzw to rotation matrices ``(..., 3, 3)``."""
    q = normalize(np.asarray(q, dtype=float))
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return np.stack(
        [
            np.stack([1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)], axis=-1),
            np.stack([2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)], axis=-1),
            np.stack([2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)], axis=-1),
        ],
        axis=-2,
    )


def swing_rotation(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Shortest-arc rotation matrices taking ``source`` onto ``target``.

    "Swing" as opposed to twist: this is the rotation with no component about
    the target direction itself, which is the right answer whenever the twist
    is genuinely undetermined — an arm held straight out along its own bend
    axis, say — because any other choice invents a roll the data never had.
    """
    a = normalize(np.asarray(source, dtype=float))
    b = normalize(np.asarray(target, dtype=float))
    axis = np.cross(a, b)
    w = 1.0 + np.sum(a * b, axis=-1)

    # Antiparallel inputs leave the axis at zero and the arc genuinely
    # ambiguous; any perpendicular gives a valid half turn, so pick one.
    opposed = w < 1e-8
    if np.any(opposed):
        alt = np.cross(a, np.broadcast_to(np.array([1.0, 0.0, 0.0]), a.shape))
        weak = np.linalg.norm(alt, axis=-1) < 1e-4
        if np.any(weak):
            alt = np.where(
                weak[..., None],
                np.cross(a, np.broadcast_to(np.array([0.0, 0.0, 1.0]), a.shape)),
                alt,
            )
        axis = np.where(opposed[..., None], alt, axis)
        w = np.where(opposed, 0.0, w)

    return quat_to_mat(np.concatenate([axis, w[..., None]], axis=-1))


def euler_xyz_to_mat(angles: np.ndarray) -> np.ndarray:
    """Euler angles in radians ``(..., 3)`` to rotation matrices.

    The composition order is ``Rx @ Ry @ Rz``, matching ``CFrame.Angles(x, y, z)``
    so that authored pose data reads the same here as it would in Studio.
    """
    angles = np.asarray(angles, dtype=float)
    x, y, z = angles[..., 0], angles[..., 1], angles[..., 2]
    cx, sx = np.cos(x), np.sin(x)
    cy, sy = np.cos(y), np.sin(y)
    cz, sz = np.cos(z), np.sin(z)

    zeros, ones = np.zeros_like(cx), np.ones_like(cx)
    rx = np.stack(
        [
            np.stack([ones, zeros, zeros], -1),
            np.stack([zeros, cx, -sx], -1),
            np.stack([zeros, sx, cx], -1),
        ],
        -2,
    )
    ry = np.stack(
        [
            np.stack([cy, zeros, sy], -1),
            np.stack([zeros, ones, zeros], -1),
            np.stack([-sy, zeros, cy], -1),
        ],
        -2,
    )
    rz = np.stack(
        [
            np.stack([cz, -sz, zeros], -1),
            np.stack([sz, cz, zeros], -1),
            np.stack([zeros, zeros, ones], -1),
        ],
        -2,
    )
    return rx @ ry @ rz


def euler_degrees_to_quat(angles: np.ndarray) -> np.ndarray:
    """Convenience for authored pose data, which is written in degrees."""
    return mat_to_quat(euler_xyz_to_mat(np.deg2rad(np.asarray(angles, dtype=float))))


def quat_slerp(a: np.ndarray, b: np.ndarray, t: float | np.ndarray) -> np.ndarray:
    """Shortest-arc spherical interpolation between quaternions."""
    a = normalize(np.asarray(a, dtype=float))
    b = normalize(np.asarray(b, dtype=float))
    dot = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(dot < 0.0, -b, b)
    dot = np.abs(dot).clip(0.0, 1.0)

    t = np.asarray(t, dtype=float)
    if t.ndim < a.ndim:
        t = t[..., None]

    theta = np.arccos(dot)
    sin_theta = np.sin(theta)
    close = sin_theta < 1e-6
    # linear fallback keeps near-identical rotations numerically sane
    lerped = a + (b - a) * t
    wa = np.where(close, 0.0, np.sin((1.0 - t) * theta) / np.where(close, 1.0, sin_theta))
    wb = np.where(close, 0.0, np.sin(t * theta) / np.where(close, 1.0, sin_theta))
    slerped = a * wa + b * wb
    return normalize(np.where(close, lerped, slerped))


def swing_twist(q: np.ndarray, axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split rotations into swing and twist about ``axis``, in radians.

    A joint limit is not one number: a shoulder tilts within a cone *and*
    rotates about the bone's own length, and those are bounded separately. This
    is the decomposition that lets a pose be checked against both — and the same
    one a BallSocketConstraint applies, with its UpperAngle bounding the swing
    and its twist limits the rest.

    Returns ``(swing_angle, twist_angle)``. The twist is signed about ``axis``;
    the swing is unsigned, being the size of a tilt in some direction.
    """
    q = normalize(np.atleast_2d(np.asarray(q, dtype=float)))
    a = normalize(np.asarray(axis, dtype=float).reshape(3))

    projection = np.sum(q[..., :3] * a, axis=-1, keepdims=True) * a
    twist = normalize(np.concatenate([projection, q[..., 3:]], axis=-1))
    # A rotation exactly 180 degrees off-axis leaves nothing to project; the
    # twist is undefined there, so call it zero rather than propagate a NaN.
    degenerate = np.linalg.norm(twist[..., :3], axis=-1) + np.abs(twist[..., 3]) < 1e-8
    twist = np.where(degenerate[..., None], np.array([0.0, 0.0, 0.0, 1.0]), twist)

    swing = quat_multiply(q, quat_conjugate(twist))

    twist_angle = 2.0 * np.arctan2(
        np.sum(twist[..., :3] * a, axis=-1), twist[..., 3]
    )
    twist_angle = (twist_angle + np.pi) % (2.0 * np.pi) - np.pi
    swing_angle = 2.0 * np.arccos(np.abs(swing[..., 3]).clip(0.0, 1.0))
    return swing_angle, twist_angle


def quat_conjugate(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=float)
    return np.concatenate([-q[..., :3], q[..., 3:]], axis=-1)


def quat_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product of xyzw quaternions, ``a`` applied after ``b``."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    av, aw = a[..., :3], a[..., 3:]
    bv, bw = b[..., :3], b[..., 3:]
    return np.concatenate(
        [aw * bv + bw * av + np.cross(av, bv), aw * bw - np.sum(av * bv, axis=-1, keepdims=True)],
        axis=-1,
    )


def quat_angle(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Absolute angle in radians between two orientations."""
    dot = np.abs(np.sum(normalize(a) * normalize(b), axis=-1)).clip(0.0, 1.0)
    return 2.0 * np.arccos(dot)


def unroll_quaternions(q: np.ndarray) -> np.ndarray:
    """Flip signs along the frame axis so successive quaternions stay close.

    A quaternion and its negation describe the same rotation, but a sign flip
    mid-sequence makes any downstream filtering or curve fitting produce a
    360 degree spin.  This walks the sequence once and fixes the hemisphere.
    """
    q = np.array(q, dtype=float, copy=True)
    if q.shape[0] < 2:
        return q
    flips = np.cumprod(
        np.where(np.sum(q[1:] * q[:-1], axis=-1, keepdims=True) < 0.0, -1.0, 1.0),
        axis=0,
    )
    q[1:] *= flips
    return q


# --------------------------------------------------------------------------
# CFrame
# --------------------------------------------------------------------------
def cframe(position: np.ndarray, rotation: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(position, dtype=float), np.asarray(rotation, dtype=float)


def cframe_components(position: np.ndarray, rotation: np.ndarray) -> list[float]:
    """The 12 floats Roblox serialises a CFrame as.

    Order is ``x, y, z, R00, R01, R02, R10, R11, R12, R20, R21, R22`` — the
    rotation is written row-major, matching ``CFrame.new(...)``'s 12-argument
    constructor and the ``<CoordinateFrame>`` XML element.
    """
    p = np.asarray(position, dtype=float).reshape(3)
    r = np.asarray(rotation, dtype=float).reshape(3, 3)
    return [float(v) for v in (*p, *r.reshape(9))]


IDENTITY_ROTATION = np.eye(3)
ZERO_POSITION = np.zeros(3)

