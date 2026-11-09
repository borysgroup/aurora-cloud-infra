"""Printable ISO-profile threads as meshes (manifold3d), for the all-printed stud mount.

A single-start thread is invariant under a screw motion, so its solid is the extrusion of one cross-section with a
twist of 360 deg per pitch. The cross-section is the "cam" r(theta) = R((-p theta / 2 pi) mod p), with R(u) the axial
profile over one pitch: crest flat, flank, root flat, flank (60 deg included angle, ISO 68-1 proportions).

    external thread  = the extruded profile, unioned onto a part (a printed screw's shank)
    internal thread  = the same profile grown by the allowance, subtracted from a part (a "tap")

The CadQuery parts carry plain cylinders/holes; the threads are added at mesh level when the STLs are written, because
that is what the slicer reads. Allowances are radial, per side, and are the main knob for fit on a given printer.
"""

from __future__ import annotations

import math

import manifold3d as m3d
import numpy as np

H_FACTOR = math.sqrt(3) / 2          # fundamental triangle height / pitch


def iso_radii(d, p):
    """(major radius, minor radius) of the basic ISO external profile: d3 = d - 1.22687 p."""
    return d / 2.0, (d - 1.22687 * p) / 2.0


def _profile(p, r_maj, r_min, crest=1 / 8, n=720):
    """Radius vs axial position u in [0, p): crest flat at r_maj (width crest*p), 60 deg flanks, root flat at r_min."""
    run = (r_maj - r_min) * math.tan(math.radians(30.0))          # axial run of one flank
    wc = crest * p
    wr = p - wc - 2 * run
    if wr < 0:
        raise ValueError("thread depth too large for the pitch")
    u = (np.arange(n) + 0.5) / n * p
    r = np.empty(n)
    a, b, c = wc, wc + run, wc + run + wr
    r[u < a] = r_maj
    m = (u >= a) & (u < b)
    r[m] = r_maj - (u[m] - a) / run * (r_maj - r_min)
    m = (u >= b) & (u < c)
    r[m] = r_min
    m = u >= c
    r[m] = r_min + (u[m] - c) / run * (r_maj - r_min)
    return r


def thread_solid(d, p, length, grow=0.0, n=96, per_pitch=20, d_minor=None):
    """Right-hand thread solid along +z from z = 0 to `length`, ISO profile of nominal diameter d, pitch p,
    every radius grown by `grow` (negative for an external allowance). d_minor overrides the basic minor diameter."""
    r_maj, r_min = iso_radii(d, p)
    if d_minor is not None:
        r_min = d_minor / 2.0
    r_maj, r_min = r_maj + grow, r_min + grow
    prof = _profile(p, r_maj, r_min, n=n)                          # R(u), u = (k + 0.5) p / n
    theta = 2 * math.pi * (np.arange(n) + 0.5) / n
    # at z = 0 the point at angle theta has u = (-p theta / 2 pi) mod p, i.e. profile index n - k
    idx = (n - np.arange(n) - 1) % n
    r = prof[idx]
    pts = np.column_stack([r * np.cos(theta), r * np.sin(theta)])
    cs = m3d.CrossSection([pts.tolist()])
    turns = length / p
    solid = m3d.Manifold.extrude(cs, length, n_divisions=max(1, int(math.ceil(turns * per_pitch))),
                                 twist_degrees=360.0 * turns)
    return solid


def cone(d0, d1, h):
    """Frustum along +z from diameter d0 at z = 0 to d1 at z = h."""
    return m3d.Manifold.cylinder(h, d0 / 2.0, d1 / 2.0, 96)


def frame(m, origin, axis):
    """Move a solid built along +z from the origin so that it starts at `origin` and runs along unit `axis`."""
    ax = np.asarray(axis, float)
    ax = ax / np.linalg.norm(ax)
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(z, ax)
    s, c = np.linalg.norm(v), float(np.dot(z, ax))
    if s < 1e-12:
        R = np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    else:
        k = v / s
        K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        R = np.eye(3) + s * K + (1 - c) * K @ K
    M = np.hstack([R, np.asarray(origin, float).reshape(3, 1)])
    return m.transform(M.tolist())


def external(d, p, length, allowance, chamfer=True):
    """External thread for a printed screw along +z from 0 to `length`: radii reduced by `allowance`, 45 deg chamfer
    at the tip (z = length) down to just below the root."""
    t = thread_solid(d, p, length, grow=-allowance)
    if chamfer:
        r_maj = d / 2 - allowance
        r_min = iso_radii(d, p)[1] - allowance
        ch = r_maj - r_min + 0.3
        keep = m3d.Manifold.cylinder(length - ch, r_maj + 1, r_maj + 1, 96).translate([0, 0, -1.0]) + cone(
            2 * (r_maj + 1), 2 * (r_maj - ch), ch + 1).translate([0, 0, length - ch - 1])
        t = t ^ keep
    return t


def tap(d, p, length, allowance, entry_chamfer=0.6, blind=False, d_minor=None):
    """Internal-thread cutter: the basic profile grown by `allowance`, from z = 0 (the entry, with a 45 deg
    countersink) to z = length. A through cutter overshoots both ends by 1 mm; a blind one stops at `length`."""
    over = 1.0
    t = thread_solid(d, p, length + (over if blind else 2 * over), grow=allowance, d_minor=d_minor) \
        .translate([0, 0, -over])
    r_maj = d / 2 + allowance
    if entry_chamfer > 0:
        t = t + cone(2 * (r_maj + entry_chamfer + over), 2 * (r_maj - 0.4), entry_chamfer + over + 0.4) \
            .translate([0, 0, -over])
    return t


def to_manifold(verts, faces):
    mesh = m3d.Mesh(vert_properties=np.asarray(verts, np.float32), tri_verts=np.asarray(faces, np.uint32))
    m = m3d.Manifold(mesh)
    if m.status() != m3d.Error.NoError:
        raise ValueError(f"mesh is not manifold: {m.status()}")
    return m


def to_arrays(m):
    mesh = m.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts)


if __name__ == "__main__":
    # self-check: handedness and radii
    s = thread_solid(8.0, 1.25, 5.0)
    v, f = to_arrays(s)
    r = np.hypot(v[:, 0], v[:, 1])
    print("M8 thread solid: r %.3f..%.3f, vol %.1f mm3, tris %d" % (r.min(), r.max(), s.volume(), len(f)))
    # right hand: the crest at z advances counter-clockwise (seen from +z) by 2 pi z / p
    for z in (0.3, 0.3 + 1.25 / 4):
        sl = s.slice(z).to_polygons()[0]
        pts = np.asarray(sl)
        rr = np.hypot(pts[:, 0], pts[:, 1])
        k = np.argmax(rr)
        print("z=%.4f crest at %.1f deg" % (z, math.degrees(math.atan2(pts[k, 1], pts[k, 0]))))
