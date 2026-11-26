"""Primitive solids for the glovebox reconstruction (trimesh), each tagged with a name and colour."""
import numpy as np
import trimesh

Z = np.array([0.0, 0.0, 1.0])


def _rgba(hexcol, alpha=255):
    h = hexcol.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)] + [alpha], np.uint8)


class Part:
    """A named mesh with a colour (used by the quick pyvista renders), a finish from materials.M (used by
    the glTF export and Blender) and, for decals, a texture image with per-vertex uv."""

    def __init__(self, name, mesh, color, group, source="", material=None, image=None, uv=None):
        if image is None:
            mesh.visual.face_colors = _rgba(color)
        self.name, self.mesh, self.color, self.group, self.source = name, mesh, color, group, source
        from materials import for_colour
        self.material = material or for_colour(color) or "paint"
        self.image, self.uv = image, uv


def _frame(origin, z_axis=Z, yaw_deg=0.0):
    """4x4 transform: local z along z_axis, rotated by yaw about it, origin at origin."""
    z = np.asarray(z_axis, float); z /= np.linalg.norm(z)
    a = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(a, z); x /= np.linalg.norm(x)
    if np.allclose(z, Z):
        x = np.array([1.0, 0, 0])
    y = np.cross(z, x)
    c, s = np.cos(np.radians(yaw_deg)), np.sin(np.radians(yaw_deg))
    x, y = c * x + s * y, -s * x + c * y
    T = np.eye(4); T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, z, origin
    return T


def box(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return trimesh.creation.box(extents=hi - lo, transform=trimesh.transformations.translation_matrix((lo + hi) / 2))


def obox(center, size, yaw_deg=0.0):
    """Box of size (l, w, h) centred at center, turned by yaw about z."""
    T = _frame(center, Z, yaw_deg)
    return trimesh.creation.box(extents=size, transform=T)


def cyl(p0, p1, r, sections=40):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    return trimesh.creation.cylinder(radius=r, segment=[p0, p1], sections=sections)


def ring(center, axis, r_in, r_out, t, sections=48):
    m = trimesh.creation.annulus(r_min=r_in, r_max=r_out, height=t, sections=sections)
    m.apply_transform(_frame(center, axis))
    return m


def slot(a, b, w, z0, z1, sections=24):
    """Link from a to b (xy) with rounded ends: width w, between heights z0 and z1."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    v = b - a
    mid = (a + b) / 2
    yaw = np.degrees(np.arctan2(v[1], v[0]))
    h = z1 - z0
    parts = [obox((mid[0], mid[1], (z0 + z1) / 2), (np.linalg.norm(v), w, h), yaw),
             cyl((a[0], a[1], z0), (a[0], a[1], z1), w / 2, sections),
             cyl((b[0], b[1], z0), (b[0], b[1], z1), w / 2, sections)]
    return trimesh.util.concatenate(parts)


def rounded_box(center, size, r, yaw_deg=0.0, sections=12):
    """Box with its four vertical edges rounded to radius r."""
    l, w, h = size
    c = np.asarray(center, float)
    core = [obox(c, (l - 2 * r, w, h), yaw_deg), obox(c, (l, w - 2 * r, h), yaw_deg)]
    T = _frame(c, Z, yaw_deg)
    for sx in (-1, 1):
        for sy in (-1, 1):
            p = T @ np.array([sx * (l / 2 - r), sy * (w / 2 - r), 0, 1.0])
            core.append(cyl((p[0], p[1], c[2] - h / 2), (p[0], p[1], c[2] + h / 2), r, sections))
    return trimesh.util.concatenate(core)


def tube(points, r, sections=16):
    """Round tube through 3D points (polyline, smoothed with a Catmull-Rom spline)."""
    P = np.asarray(points, float)
    if len(P) > 2:
        Q = [P[0]] * 1 + list(P) + [P[-1]]
        Q = np.array(Q)
        out = []
        for i in range(1, len(Q) - 2):
            p0, p1, p2, p3 = Q[i - 1], Q[i], Q[i + 1], Q[i + 2]
            for s in np.linspace(0, 1, 8, endpoint=False):
                s2, s3 = s * s, s * s * s
                out.append(0.5 * ((2 * p1) + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s2
                                  + (-p0 + 3 * p1 - 3 * p2 + p3) * s3))
        out.append(P[-1])
        P = np.array(out)
    segs = [cyl(a, b, r, sections) for a, b in zip(P[:-1], P[1:]) if np.linalg.norm(b - a) > 1e-6]
    segs += [trimesh.creation.icosphere(subdivisions=1, radius=r).apply_translation(p) for p in P[1:-1]]
    return trimesh.util.concatenate(segs)


def hole_grid(origin, u, v, nu, nv, pitch, r=3.3, depth=0.4):
    """Dark discs marking tapped holes on a plate: origin is the first hole centre on the top face."""
    o, u, v = (np.asarray(x, float) for x in (origin, u, v))
    n = np.cross(u, v); n /= np.linalg.norm(n)
    base = trimesh.creation.cylinder(radius=r, height=depth, sections=12)
    out = []
    for i in range(nu):
        for j in range(nv):
            p = o + i * pitch * u + j * pitch * v + n * depth / 2
            m = base.copy(); m.apply_transform(_frame(p, n)); out.append(m)
    return trimesh.util.concatenate(out)


def stepper(face_center, axis, size, length, shaft_len=20, shaft_r=3.175):
    """NEMA stepper: square body of side `size` behind the face, plus a shaft out of the face."""
    a = np.asarray(axis, float); a /= np.linalg.norm(a)
    f = np.asarray(face_center, float)
    body = trimesh.creation.box(extents=(size, size, length))
    body.apply_transform(_frame(f - a * length / 2, a))
    shaft = cyl(f, f + a * shaft_len, shaft_r, 16)
    boss = cyl(f, f + a * 2, 11.0 if size < 50 else 19.0, 24)
    return trimesh.util.concatenate([body, shaft, boss])
