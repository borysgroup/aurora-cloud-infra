"""Small geometry helpers for the Aurora camera-layout render (PyVista)."""

import numpy as np
import pyvista as pv


def box(center, size):
    cx, cy, cz = center
    sx, sy, sz = size
    return pv.Box(bounds=(cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, cz - sz / 2, cz + sz / 2))


def box_from(lo, hi):
    return pv.Box(bounds=(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]))


def cyl(center, direction, radius, height, res=48, capping=True):
    return pv.Cylinder(center=center, direction=direction, radius=radius, height=height,
                       resolution=res, capping=capping)


def ring(center, normal, r_in, r_out, thickness, res=64):
    """Annulus extruded along its normal (glove ports, tape rolls, door flanges)."""
    disc = pv.Disc(center=(0, 0, 0), inner=r_in, outer=r_out, normal=(0, 0, 1), c_res=res)
    solid = disc.extrude((0, 0, thickness), capping=True)
    solid.translate((0, 0, -thickness / 2), inplace=True)
    return _orient(solid, normal).translate(center, inplace=False)


def tube_path(points, radius, res=24):
    spline = pv.Spline(np.asarray(points, dtype=float), 120)
    return spline.tube(radius=radius, n_sides=res)


def _orient(mesh, normal):
    """Rotate a mesh built around +Z so that +Z points along `normal`."""
    n = np.asarray(normal, dtype=float)
    n /= np.linalg.norm(n)
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(z, n)
    s, c = np.linalg.norm(v), float(np.dot(z, n))
    if s < 1e-9:
        return mesh if c > 0 else mesh.rotate_x(180, inplace=False)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    r = np.eye(3) + vx + vx @ vx * ((1 - c) / s**2)
    t = np.eye(4)
    t[:3, :3] = r
    return mesh.transform(t, inplace=False)


def look_frame(direction, up_hint=(0, 0, 1)):
    """Orthonormal (right, up, forward) frame for a camera looking along `direction`."""
    f = np.asarray(direction, dtype=float)
    f /= np.linalg.norm(f)
    u = np.asarray(up_hint, dtype=float)
    if abs(np.dot(u, f)) > 0.98:  # looking straight up/down: borrow +Y as "up"
        u = np.array([0.0, 1.0, 0.0])
    r = np.cross(f, u)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return r, u, f


def frustum(origin, direction, hfov_deg, vfov_deg, length, up_hint=(0, 0, 1)):
    """Pyramid from the camera origin along `direction`, sized by the field of view."""
    o = np.asarray(origin, dtype=float)
    r, u, f = look_frame(direction, up_hint)
    hw = np.tan(np.radians(hfov_deg / 2)) * length
    hh = np.tan(np.radians(vfov_deg / 2)) * length
    c = o + f * length
    corners = [c + r * hw + u * hh, c - r * hw + u * hh, c - r * hw - u * hh, c + r * hw - u * hh]
    pts = np.vstack([o, corners])
    faces = np.hstack([[3, 0, 1, 2], [3, 0, 2, 3], [3, 0, 3, 4], [3, 0, 4, 1], [4, 1, 2, 3, 4]])
    return pv.PolyData(pts, faces)


def frustum_edges(origin, direction, hfov_deg, vfov_deg, length, up_hint=(0, 0, 1)):
    fr = frustum(origin, direction, hfov_deg, vfov_deg, length, up_hint)
    p = fr.points
    lines = np.hstack([[2, 0, 1], [2, 0, 2], [2, 0, 3], [2, 0, 4],
                       [2, 1, 2], [2, 2, 3], [2, 3, 4], [2, 4, 1]])
    return pv.PolyData(p, lines=lines)
