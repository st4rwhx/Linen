from __future__ import annotations

import numpy as np
import pytest

from linen.math3d import (
    cframe_components,
    euler_degrees_to_quat,
    mat_to_quat,
    normalize,
    orthonormal_basis,
    quat_angle,
    quat_slerp,
    quat_to_mat,
    unroll_quaternions,
)


def random_rotations(count: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    q = normalize(rng.normal(size=(count, 4)))
    return quat_to_mat(q)


def test_mat_quat_roundtrip_covers_all_pivot_branches():
    # 200 random rotations exercise every branch of the trace pivot, including
    # the near-180-degree cases where the naive formulation loses precision.
    matrices = random_rotations(200, seed=7)
    roundtripped = quat_to_mat(mat_to_quat(matrices))
    assert np.allclose(matrices, roundtripped, atol=1e-9)


def test_mat_to_quat_handles_half_turns():
    for axis in np.eye(3):
        matrix = quat_to_mat(np.concatenate([axis, [0.0]]))  # 180 degrees
        assert np.allclose(quat_to_mat(mat_to_quat(matrix)), matrix, atol=1e-9)


def test_euler_matches_roblox_angle_order():
    # CFrame.Angles(x, y, z) is Rx * Ry * Rz; a 90 degree Y turn must send
    # +X to -Z, not +Z.
    matrix = quat_to_mat(euler_degrees_to_quat(np.array([0.0, 90.0, 0.0])))
    assert np.allclose(matrix @ np.array([1.0, 0.0, 0.0]), [0.0, 0.0, -1.0], atol=1e-9)


def test_orthonormal_basis_is_right_handed():
    rng = np.random.default_rng(3)
    primary = normalize(rng.normal(size=(50, 3)))
    hint = normalize(rng.normal(size=(50, 3)))
    basis = orthonormal_basis(primary, hint)
    assert np.allclose(np.linalg.det(basis), 1.0, atol=1e-9)
    assert np.allclose(basis[:, :, 1], primary, atol=1e-9)


def test_orthonormal_basis_survives_colinear_hint():
    primary = np.tile([0.0, 1.0, 0.0], (3, 1))
    basis = orthonormal_basis(primary, primary)
    assert np.all(np.isfinite(basis))
    assert np.allclose(np.linalg.det(basis), 1.0, atol=1e-9)


def test_slerp_endpoints_and_midpoint():
    a = euler_degrees_to_quat(np.array([0.0, 0.0, 0.0]))[None]
    b = euler_degrees_to_quat(np.array([90.0, 0.0, 0.0]))[None]
    assert np.allclose(quat_angle(quat_slerp(a, b, 0.0), a), 0.0, atol=1e-9)
    assert np.allclose(quat_angle(quat_slerp(a, b, 1.0), b), 0.0, atol=1e-9)
    mid = quat_slerp(a, b, 0.5)
    assert np.allclose(np.rad2deg(quat_angle(mid, a)), 45.0, atol=1e-6)


def test_unroll_quaternions_removes_sign_flips():
    q = euler_degrees_to_quat(np.linspace([0, 0, 0], [180, 0, 0], 50))
    flipped = q.copy()
    flipped[25:] *= -1.0
    unrolled = unroll_quaternions(flipped)
    steps = np.sum(unrolled[1:] * unrolled[:-1], axis=-1)
    assert np.all(steps > 0)


def test_cframe_components_are_row_major():
    rotation = quat_to_mat(euler_degrees_to_quat(np.array([0.0, 90.0, 0.0])))
    values = cframe_components(np.array([1.0, 2.0, 3.0]), rotation)
    assert values[:3] == [1.0, 2.0, 3.0]
    assert values[3:] == pytest.approx(list(rotation.reshape(9)))
