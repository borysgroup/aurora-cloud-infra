"""Division model, shared by plumbline.py, intrinsics.py and register_chamber.py.

Pixel coordinates p_d (distorted, as streamed) and p_u (ideal pinhole) are related about the
distortion centre c (taken as the principal point) by

    p_u - c = (p_d - c) / (1 + l1 * r_d**2 + l2 * r_d**4),   r_d = |p_d - c| / NORM

with NORM = 1000 px, so (l1, l2) do not depend on the focal length. l1 < 0 is barrel distortion.
`lam` is either a scalar l1 or a pair (l1, l2).
"""
import numpy as np

NORM = 1000.0


def _l(lam):
    lam = np.atleast_1d(np.asarray(lam, float))
    return float(lam[0]), float(lam[1]) if lam.size > 1 else 0.0


def undistort_px(pd, c, lam):
    l1, l2 = _l(lam)
    pd = np.asarray(pd, float)
    d = (pd - c) / NORM
    r2 = (d ** 2).sum(-1, keepdims=True)
    return c + NORM * d / (1.0 + l1 * r2 + l2 * r2 ** 2)


def distort_px(pu, c, lam, iters=30):
    """Inverse of undistort_px (Newton on the radius)."""
    l1, l2 = _l(lam)
    pu = np.asarray(pu, float)
    u = (pu - c) / NORM
    ru = np.sqrt((u ** 2).sum(-1, keepdims=True))
    rd = ru / (1 + np.sqrt(np.maximum(1 - 4 * l1 * ru ** 2, 0))) * 2 if l1 != 0 else ru.copy()
    for _ in range(iters):   # solve g(rd) = rd - ru (1 + l1 rd^2 + l2 rd^4) = 0
        g = rd - ru * (1 + l1 * rd ** 2 + l2 * rd ** 4)
        dg = 1 - ru * (2 * l1 * rd + 4 * l2 * rd ** 3)
        rd = rd - g / np.where(np.abs(dg) < 1e-9, 1e-9, dg)
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(ru > 0, rd / ru, 1.0)
    return c + NORM * u * s


def opencv_coeffs(lam, f, r_max_px):
    """Least-squares fit of OpenCV's (k1, k2, p1, p2, k3) to the division model for focal length f (px),
    over distorted radii 0..r_max_px. Returns (dist, max error in px)."""
    l1, l2 = _l(lam)
    rd = np.linspace(0, r_max_px, 400) / NORM
    ru = rd / (1 + l1 * rd ** 2 + l2 * rd ** 4)
    xu, xd = ru * NORM / f, rd * NORM / f
    A = np.stack([xu ** 3, xu ** 5, xu ** 7], 1)
    k = np.linalg.lstsq(A, xd - xu, rcond=None)[0]
    err = np.abs(xu + A @ k - xd).max() * f
    return np.array([k[0], k[1], 0.0, 0.0, k[2]]), float(err)


def opencv_rational(lam, f, r_max_px):
    """Same, with OpenCV's rational model (k1, k2, p1, p2, k3, k4, k5, k6): x_d = x_u (1+k1 r2+k2 r4+k3 r6) /
    (1+k4 r2+k5 r4+k6 r6). Fitted by linear least squares; returns (dist[8], max error px)."""
    l1, l2 = _l(lam)
    rd = np.linspace(1e-3, r_max_px, 400) / NORM
    ru = rd / (1 + l1 * rd ** 2 + l2 * rd ** 4)
    xu, xd = ru * NORM / f, rd * NORM / f
    s = xd / xu       # = (1 + k1 r2 + k2 r4 + k3 r6) / (1 + k4 r2 + k5 r4 + k6 r6), r2 = xu^2
    r2 = xu ** 2
    A = np.stack([r2, r2 ** 2, r2 ** 3, -s * r2, -s * r2 ** 2, -s * r2 ** 3], 1)
    k = np.linalg.lstsq(A, s - 1, rcond=None)[0]
    num = 1 + k[0] * r2 + k[1] * r2 ** 2 + k[2] * r2 ** 3
    den = 1 + k[3] * r2 + k[4] * r2 ** 2 + k[5] * r2 ** 3
    err = np.abs(xu * num / den - xd).max() * f
    return np.array([k[0], k[1], 0.0, 0.0, k[2], k[3], k[4], k[5]]), float(err)
