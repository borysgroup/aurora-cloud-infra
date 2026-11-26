"""The two calibrated Amcrest cameras (../vision/out/cameras.json): projection, back-projection and
two-view triangulation in the aurora_chamber frame (mm; x from the antechamber-end wall, y from the
open side, z up from the deck)."""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "vision"))
from lensmodel import distort_px, undistort_px  # noqa: E402

CAL = json.load(open(os.path.join(HERE, "..", "vision", "out", "cameras.json")))
C = np.array(CAL["division_model"]["centre"])
LAM = (CAL["division_model"]["l1"], CAL["division_model"]["l2"])
F = CAL["f_px"]


class Cam:
    def __init__(self, name):
        c = CAL["cameras"][name]
        self.name, self.R, self.t = name, np.array(c["R"]), np.array(c["t"])
        self.centre = -self.R.T @ self.t
        self.f = F

    def project(self, X, distorted=True):
        X = np.atleast_2d(np.asarray(X, float))
        Xc = (self.R @ X.T).T + self.t
        uv = C + self.f * Xc[:, :2] / Xc[:, 2:3]
        return (distort_px(uv, C, LAM) if distorted else uv), Xc[:, 2]

    def ray(self, px):
        """Unit direction (world) of the ray through a distorted pixel."""
        u = undistort_px(np.atleast_2d(np.asarray(px, float)), C, LAM)
        d = np.c_[(u - C) / self.f, np.ones(len(u))]
        d = (self.R.T @ d.T).T
        return d / np.linalg.norm(d, axis=1, keepdims=True)

    def on_plane_z(self, px, z):
        """Where the rays through pixels meet the horizontal plane at height z."""
        d = self.ray(px)
        s = (z - self.centre[2]) / d[:, 2]
        return self.centre + s[:, None] * d


CAM0, CAM1 = Cam("cam0"), Cam("cam1")


def triangulate(px0, px1):
    """Midpoint of the closest approach of the two rays; returns (point, gap_mm)."""
    d0, d1 = CAM0.ray(px0)[0], CAM1.ray(px1)[0]
    o0, o1 = CAM0.centre, CAM1.centre
    w = o0 - o1
    a, b, c, d, e = d0 @ d0, d0 @ d1, d1 @ d1, d0 @ w, d1 @ w
    den = a * c - b * b
    s, t = (b * e - c * d) / den, (a * e - b * d) / den
    p0, p1 = o0 + s * d0, o1 + t * d1
    return (p0 + p1) / 2, float(np.linalg.norm(p0 - p1))
