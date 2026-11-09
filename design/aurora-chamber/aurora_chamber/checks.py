"""Design checks against the chamber: clearance to the robot and to fixed equipment, and what a camera sees.

    import aurora_chamber as ac
    gap = ac.robot_clearance(my_mesh)            # mm to the Epson's swept volume, < 0 means it can be hit
    view = ac.camera_view(origin, target, ac.FOV["cm3"])
    cover = ac.view_coverage(view, ac.grid_on_rect(ac.TRAY_C + (0, 0, 14), (150, 120)))

Geometry can be an (N, 3) array, a PyVista mesh, or a list of meshes or (mesh, colour) pairs, all in the
scene frame (see params.py).
"""

from dataclasses import dataclass

import numpy as np
import pyvista as pv
import vtk

from . import robot
from .params import RISER_RANGE
from .primitives import look_frame

# Fields of view (deg, horizontal x vertical). Camera Module 3 and Module 3 Wide: Raspberry Pi product brief.
# HQ Camera with the 8-50 mm zoom at 12 mm: from the IMX477's 6.29 x 4.71 mm active area.
FOV = {
    "cm3": (66.0, 41.0),
    "cm3_wide": (102.0, 67.0),
    "hq_12mm": (2 * np.degrees(np.arctan(6.287 / 2 / 12.0)), 2 * np.degrees(np.arctan(4.712 / 2 / 12.0))),
    "hq_25mm": (2 * np.degrees(np.arctan(6.287 / 2 / 25.0)), 2 * np.degrees(np.arctan(4.712 / 2 / 25.0))),
}


def as_points(geom):
    """(N, 3) array of the vertices of `geom`."""
    if isinstance(geom, np.ndarray):
        return geom.reshape(-1, 3).astype(float)
    if isinstance(geom, pv.DataSet):
        return np.asarray(geom.points, float)
    pts = [as_points(g[0] if isinstance(g, tuple) else g) for g in geom]
    return np.vstack(pts) if pts else np.zeros((0, 3))


def _as_mesh(geom):
    if isinstance(geom, pv.DataSet):
        return geom.extract_surface(algorithm="dataset_surface").triangulate()
    meshes = [g[0] if isinstance(g, tuple) else g for g in geom]
    return pv.merge([m.extract_surface(algorithm="dataset_surface") for m in meshes]).triangulate()


def _band_radius(name, e):
    return {"shaft": e["shaft_r"], "arm 2": e["arm2_r"], "arm 1": e["arm1_r"], "duct": e["arch_r"]}[name]


def robot_clearance(geom, risers=RISER_RANGE, xy_margin=0.0):
    """Smallest 3D distance (mm) from `geom` to the Epson's swept volume; negative means inside it.

    The swept volume is the union over `risers` (default: 150 to 180 mm) of the bands in robot.py, each a
    vertical cylinder round J1. xy_margin grows every radius, e.g. by J1's +/-30 mm position uncertainty.
    Returns dict(gap, point, band, vertical_gap): vertical_gap is the old, z-only measure (the gap above or
    below the robot at the point's own x, y; None when no point is over the robot's reach).
    """
    pts = as_points(geom)
    risers = np.atleast_1d(risers).astype(float)
    lo, hi = robot.envelope(risers.min()), robot.envelope(risers.max())
    bands = []
    for name in ("shaft", "arm 2", "arm 1", "duct"):
        key = {"shaft": ("tool_low", "shaft_top"), "arm 2": ("arm2_low", "arm2_top"),
               "arm 1": ("arm1_low", "arm1_top"), "duct": ("arch_low", "arch_top")}[name]
        bands.append((name, _band_radius(name, lo) + xy_margin, lo[key[0]], max(lo[key[1]], hi[key[1]])))
    r = np.hypot(pts[:, 0] - robot.SCARA_XY[0], pts[:, 1] - robot.SCARA_XY[1])
    z = pts[:, 2]
    best = (np.inf, None, None)
    vgap = None
    for name, rad, z0, z1 in bands:
        dr = r - rad
        dz = np.maximum(z0 - z, z - z1)
        outside = np.where((dr > 0) | (dz > 0), np.hypot(np.maximum(dr, 0), np.maximum(dz, 0)), 0.0)
        inside = -np.minimum(-dr, -dz)            # penetration depth (negative) where dr <= 0 and dz <= 0
        d = np.where((dr > 0) | (dz > 0), outside, inside)
        i = int(np.argmin(d))
        if d[i] < best[0]:
            best = (float(d[i]), pts[i], name)
        over = dr <= 0
        if over.any():
            g = float(np.min(np.where(z[over] >= z1, z[over] - z1,
                                      np.where(z[over] <= z0, z0 - z[over], -np.minimum(z[over] - z0, z1 - z[over])))))
            vgap = g if vgap is None else min(vgap, g)
    return dict(gap=best[0], point=best[1], band=best[2], vertical_gap=vgap)


def fixed_clearance(geom, parts):
    """Smallest distance (mm) from the vertices of `geom` to each of `parts` (list of (mesh, colour) or meshes);
    returns sorted [(distance, index into parts)]. Unsigned: 0 means touching or inside."""
    pts = pv.PolyData(as_points(geom))
    out = []
    for k, p in enumerate(parts):
        m = (p[0] if isinstance(p, tuple) else p).extract_surface(algorithm="dataset_surface").triangulate()
        if m.n_points == 0:
            continue
        loc = vtk.vtkCellLocator()
        loc.SetDataSet(m)
        loc.BuildLocator()
        best = np.inf
        cp, cid, sid, d2 = [0.0, 0.0, 0.0], vtk.mutable(0), vtk.mutable(0), vtk.mutable(0.0)
        for q in np.asarray(pts.points):
            loc.FindClosestPoint(q, cp, cid, sid, d2)
            best = min(best, float(d2) ** 0.5)
        out.append((best, k))
    return sorted(out)


@dataclass
class CameraView:
    origin: np.ndarray
    direction: np.ndarray
    fov: tuple            # (horizontal, vertical) deg
    up_hint: tuple = (0, 0, 1)

    @property
    def frame(self):
        """(right, up, forward) unit vectors of the image."""
        return look_frame(self.direction, self.up_hint)

    @property
    def tilt(self):
        """Degrees below horizontal."""
        return float(np.degrees(np.arcsin(-self.direction[2] / np.linalg.norm(self.direction))))

    def footprint(self, distance):
        """Width and height (mm) of the view, square to the optical axis, at `distance`."""
        return tuple(2 * distance * np.tan(np.radians(f / 2)) for f in self.fov)

    def project(self, points):
        """Image coordinates in [-1, 1] (x right, y up) and depth along the axis for each point."""
        r, u, f = self.frame
        d = as_points(points) - self.origin
        depth = d @ f
        with np.errstate(divide="ignore", invalid="ignore"):
            x = (d @ r) / depth / np.tan(np.radians(self.fov[0] / 2))
            y = (d @ u) / depth / np.tan(np.radians(self.fov[1] / 2))
        return np.c_[x, y], depth

    def contains(self, points):
        """True for points inside the field of view (in front of the lens)."""
        xy, depth = self.project(points)
        return (depth > 0) & (np.abs(xy[:, 0]) <= 1) & (np.abs(xy[:, 1]) <= 1)


def camera_view(origin, target=None, fov=FOV["cm3"], up_hint=(0, 0, 1), direction=None):
    """A camera at `origin` looking at `target` (or along `direction`)."""
    o = np.asarray(origin, float)
    d = (np.asarray(target, float) - o) if direction is None else np.asarray(direction, float)
    return CameraView(o, d / np.linalg.norm(d), tuple(fov), tuple(up_hint))


def line_of_sight(origin, points, occluders, stop_short=3.0):
    """True for each point the origin can see past `occluders` (meshes or (mesh, colour) pairs). Each ray
    stops `stop_short` mm before its point, so the surface the point lies on doesn't block it."""
    mesh = _as_mesh(occluders)
    tree = vtk.vtkOBBTree()
    tree.SetDataSet(mesh)
    tree.BuildLocator()
    o = np.asarray(origin, float)
    out = []
    hits = vtk.vtkPoints()
    for q in as_points(points):
        d = q - o
        n = np.linalg.norm(d)
        end = o + d * max(n - stop_short, 0.0) / max(n, 1e-9)
        tree.IntersectWithLine(o, end, hits, None)
        out.append(hits.GetNumberOfPoints() == 0)
    return np.array(out, bool)


def view_coverage(view, points, occluders=None):
    """Fraction of `points` inside the view and, with occluders, the fraction also in line of sight."""
    pts = as_points(points)
    inside = view.contains(pts)
    res = dict(n=len(pts), in_view=float(inside.mean()) if len(pts) else 0.0, visible=None)
    if occluders is not None and len(pts):
        clear = np.zeros(len(pts), bool)
        if inside.any():
            clear[inside] = line_of_sight(view.origin, pts[inside], occluders)
        res["visible"] = float(clear.mean())
    return res


def grid_on_rect(center, size, n=(9, 7)):
    """Grid of points on a horizontal rectangle (for coverage checks), e.g. the top of the chip tray."""
    cx, cy, cz = np.asarray(center, float)
    xs = np.linspace(cx - size[0] / 2, cx + size[0] / 2, n[0])
    ys = np.linspace(cy - size[1] / 2, cy + size[1] / 2, n[1])
    gx, gy = np.meshgrid(xs, ys)
    return np.c_[gx.ravel(), gy.ravel(), np.full(gx.size, cz)]
