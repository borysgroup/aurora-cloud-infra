"""Detailed part geometry for the glovebox reconstruction: fillets and chamfers, real holes, threads,
revolved profiles, chain links and decals. Everything is in mm and returns trimesh meshes.

Shapes follow catalogue drawings where a part is a standard one (NEMA 17/23 flanges, SFU1605 ball
screw and nut, BK12/BF12 end supports, HGR15 rails, Thorlabs metric breadboards, Panduit Type G duct,
igus-style chain links); sizes are given next to each function.
"""
import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.geometry import box as sbox
from shapely.ops import unary_union

Z = np.array([0.0, 0.0, 1.0])


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def frame(origin, x_axis, z_axis):
    """4x4 transform whose local z is z_axis and local x is x_axis (made orthogonal), at origin."""
    z = unit(z_axis)
    x = np.asarray(x_axis, float)
    x = unit(x - (x @ z) * z)
    y = np.cross(z, x)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, z, origin
    return T


def any_perp(z):
    z = unit(z)
    a = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    return unit(np.cross(np.cross(z, a), z) * -1)


def tf(m, T):
    m = m.copy() if isinstance(m, trimesh.Trimesh) else m
    m.apply_transform(T)
    return m


def cat(ms):
    ms = [m for m in ms if m is not None and len(m.faces)]
    return trimesh.util.concatenate(ms)


# ---- 2D profiles ----------------------------------------------------------------------------------------

def rrect(lx, ly, r, cx=0.0, cy=0.0, n=6):
    r = max(0.0, min(r, lx / 2 - 1e-3, ly / 2 - 1e-3))
    if r <= 0:
        return sbox(cx - lx / 2, cy - ly / 2, cx + lx / 2, cy + ly / 2)
    return sbox(cx - lx / 2 + r, cy - ly / 2 + r, cx + lx / 2 - r, cy + ly / 2 - r).buffer(r, quad_segs=n)


def crect(lx, ly, c, cx=0.0, cy=0.0):
    """Rectangle with 45 degree corner chamfers of leg c."""
    a, b = lx / 2, ly / 2
    pts = [(-a + c, -b), (a - c, -b), (a, -b + c), (a, b - c), (a - c, b), (-a + c, b), (-a, b - c), (-a, -b + c)]
    return Polygon([(x + cx, y + cy) for x, y in pts])


def circ(r, cx=0.0, cy=0.0, n=32):
    return Point(cx, cy).buffer(r, quad_segs=max(3, n // 4))


def gear(r_root, r_tip, teeth, cx=0.0, cy=0.0, per=6):
    th = np.linspace(0, 2 * np.pi, teeth * per, endpoint=False)
    r = np.where((np.arange(len(th)) % per) < per / 2, r_tip, r_root)
    return Polygon(np.c_[cx + r * np.cos(th), cy + r * np.sin(th)])


def extrude(poly, h, T=None, z0=0.0):
    """Extrude a shapely polygon (holes allowed) from z0 to z0 + h in its local frame, then place it."""
    if poly.geom_type == "MultiPolygon":
        return cat([extrude(p, h, T, z0) for p in poly.geoms])
    m = trimesh.creation.extrude_polygon(poly, h)
    if z0:
        m.apply_translation((0, 0, z0))
    if T is not None:
        m.apply_transform(T)
    return m


def revolve(rz, T=None, sections=64):
    """Revolve a (radius, z) polyline about local z (closed solids need r = 0 at both ends)."""
    m = trimesh.creation.revolve(np.asarray(rz, float), sections=sections)
    if T is not None:
        m.apply_transform(T)
    return m


def fillet_profile(pts, r, n=5):
    """Round the corners of a (r, z) polyline with arcs of radius r (ends left sharp)."""
    P = np.asarray(pts, float)
    out = [P[0]]
    for i in range(1, len(P) - 1):
        a, b, c = P[i - 1], P[i], P[i + 1]
        u, v = unit(a - b), unit(c - b)
        ang = np.arccos(np.clip(u @ v, -1, 1))
        if ang > np.radians(175) or r <= 0:
            out.append(b)
            continue
        d = min(r / np.tan(ang / 2), 0.45 * np.linalg.norm(a - b), 0.45 * np.linalg.norm(c - b))
        p0, p1 = b + u * d, b + v * d
        for s in np.linspace(0, 1, n):
            q = (1 - s) ** 2 * p0 + 2 * (1 - s) * s * b + s ** 2 * p1   # quadratic Bezier through the corner
            out.append(q)
    out.append(P[-1])
    return np.array(out)


# ---- 3D primitives with rounded edges -------------------------------------------------------------------

def round_box(size, r, T=None, n=10):
    """Box with every edge rounded to radius r (hull of corner spheres)."""
    lx, ly, lz = size
    r = max(0.05, min(r, lx / 2 - 0.01, ly / 2 - 0.01, lz / 2 - 0.01))
    s = trimesh.creation.uv_sphere(radius=r, count=[n, n]).vertices
    pts = [s + (sx * (lx / 2 - r), sy * (ly / 2 - r), sz * (lz / 2 - r))
           for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    m = trimesh.convex.convex_hull(np.vstack(pts))
    if T is not None:
        m.apply_transform(T)
    return m


def box_at(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return trimesh.creation.box(extents=hi - lo, transform=trimesh.transformations.translation_matrix((lo + hi) / 2))


def cylinder(p0, p1, r, n=32):
    return trimesh.creation.cylinder(radius=r, segment=[np.asarray(p0, float), np.asarray(p1, float)], sections=n)


def rounded_cylinder(p0, p1, r, fr, n=48):
    """Cylinder whose two end edges are rounded to fr."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    L = np.linalg.norm(p1 - p0)
    fr = min(fr, r * 0.9, L / 2 * 0.9)
    prof = fillet_profile([(0, 0), (r, 0), (r, L), (0, L)], fr)
    return revolve(prof, frame(p0, any_perp(p1 - p0), p1 - p0), n)


def sweep_circle(points, r, n=12):
    """Tube of radius r along a polyline, with parallel-transported rings (no kinks at the joints)."""
    P = np.asarray(points, float)
    t = np.gradient(P, axis=0)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    nrm = any_perp(t[0])
    rings = []
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    for i in range(len(P)):
        if i:
            nrm = nrm - (nrm @ t[i]) * t[i]
            nrm = unit(nrm)
        b = np.cross(t[i], nrm)
        rings.append(P[i] + r * (np.outer(np.cos(th), nrm) + np.outer(np.sin(th), b)))
    V = np.vstack(rings + [P[0][None], P[-1][None]])
    F = []
    for i in range(len(P) - 1):
        for k in range(n):
            a, b2 = i * n + k, i * n + (k + 1) % n
            c, d = a + n, b2 + n
            F += [[a, b2, d], [a, d, c]]
    c0, c1 = len(V) - 2, len(V) - 1
    for k in range(n):
        F.append([c0, (k + 1) % n, k])
        F.append([c1, (len(P) - 1) * n + k, (len(P) - 1) * n + (k + 1) % n])
    m = trimesh.Trimesh(V, np.array(F), process=False)
    m.fix_normals()
    return m


def spline(points, per=10):
    """Catmull-Rom through the points."""
    P = np.asarray(points, float)
    if len(P) < 3:
        return np.linspace(P[0], P[-1], per + 1)
    Q = np.vstack([P[0], P, P[-1]])
    out = []
    for i in range(1, len(Q) - 2):
        p0, p1, p2, p3 = Q[i - 1], Q[i], Q[i + 1], Q[i + 2]
        for s in np.linspace(0, 1, per, endpoint=False):
            s2, s3 = s * s, s * s * s
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s2
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * s3))
    out.append(P[-1])
    return np.array(out)


def resample(P, step):
    P = np.asarray(P, float)
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    s = np.arange(0, d[-1] + 1e-9, step)
    return np.c_[[np.interp(s, d, P[:, k]) for k in range(3)]].T, s


# ---- fasteners -------------------------------------------------------------------------------------------

def cap_screw(p, axis, d=6.0, head_h=None):
    """ISO 4762 socket head cap screw head (M6: head 10 x 6), hex socket as a dark recess."""
    a = unit(axis)
    k = d if head_h is None else head_h
    T = frame(np.asarray(p, float), any_perp(a), a)
    head = revolve(fillet_profile([(0, 0), (0.75 * d, 0), (0.83 * d, 0.0), (0.83 * d, k), (0, k)], 0.6), T, 24)
    hexa = extrude(Polygon([(0.43 * d * np.cos(t), 0.43 * d * np.sin(t)) for t in np.radians(np.arange(0, 360, 60))]),
                   0.55 * d, T, k - 0.5 * d)
    return head, hexa


def acorn_nut(p, axis, d=6.0):
    a = unit(axis)
    T = frame(np.asarray(p, float), any_perp(a), a)
    s = 1.7 * d / 2 / np.cos(np.radians(30))
    hexa = extrude(Polygon([(s * np.cos(t), s * np.sin(t)) for t in np.radians(np.arange(0, 360, 60))]), 0.8 * d, T)
    dome = revolve([(0, 0.8 * d)] + [(0.8 * d * np.cos(t), 0.8 * d + 0.8 * d * np.sin(t))
                                     for t in np.linspace(0, np.pi / 2, 7)][::-1][:-1] + [(0, 1.6 * d)], T, 24)
    return cat([hexa, dome])


# ---- breadboard with real M6 holes ----------------------------------------------------------------------

def breadboard(x0, y0, sx, sy, z_top, t=12.7, pitch=25.0, edge=12.5, hole_r=3.0, skin=4.0, corner_r=2.0):
    """Thorlabs metric breadboard: black anodised skin with M6 tapped holes on a 25 mm grid, 12.5 mm from
    the edges (hole depth shown 4 mm, the tapped cups are blind). Returns (plate, hole floors)."""
    outline = rrect(sx, sy, corner_r, x0 + sx / 2, y0 + sy / 2)
    xs = np.arange(x0 + edge, x0 + sx - edge + 1e-6, pitch)
    ys = np.arange(y0 + edge, y0 + sy - edge + 1e-6, pitch)
    holes = [circ(hole_r, x, y, 16) for x in xs for y in ys]
    skin_poly = outline.difference(unary_union(holes))
    top = extrude(skin_poly, skin, z0=z_top - skin)
    core = extrude(outline, t - skin, z0=z_top - t)
    floors = cat([extrude(circ(hole_r * 0.98, x, y, 12), 0.2, z0=z_top - skin) for x in xs for y in ys])
    return cat([top, core]), floors


# ---- NEMA stepper ---------------------------------------------------------------------------------------

NEMA = {17: dict(size=42.3, hole=31.0, boss_r=11.0, boss_h=2.0, shaft_r=2.5, cap=8.0, chamfer=4.6),
        23: dict(size=57.2, hole=47.14, boss_r=19.05, boss_h=1.6, shaft_r=3.175, cap=10.0, chamfer=5.6)}


def stepper(face_center, axis, frame_size, length, xdir=None, shaft_len=20.0, cable_side=None):
    """NEMA 17/23 hybrid stepper, face at face_center, shaft along axis. Returns dict of meshes by finish:
    caps (die-cast end caps), stator (laminated stack with grooves), shaft, boss, holes, cable."""
    S = NEMA[frame_size]
    a = unit(axis)
    x = any_perp(a) if xdir is None else xdir
    T = frame(np.asarray(face_center, float), x, a)
    s, c, cap = S["size"], S["chamfer"], S["cap"]
    hole_pts = [(sx * S["hole"] / 2, sy * S["hole"] / 2) for sx in (-1, 1) for sy in (-1, 1)]
    front = crect(s, s, c).difference(unary_union([circ(1.6 if frame_size == 17 else 2.55, *h, 12)
                                                   for h in hole_pts]))
    caps = [extrude(front, cap, T, -cap), extrude(crect(s, s, c), cap, T, -length)]
    stack_len = length - 2 * cap
    n_seg = 3
    seg = stack_len / n_seg
    stator = []
    for i in range(n_seg):
        z0 = -length + cap + i * seg
        stator.append(extrude(crect(s - 0.4, s - 0.4, c + 2.2), seg - 0.8, T, z0 + 0.4))
        stator.append(extrude(crect(s - 2.0, s - 2.0, c + 2.6), 0.8 if i < n_seg - 1 else 0.4, T, z0 + seg - 0.4))
    boss = revolve(fillet_profile([(0, 0), (S["boss_r"], 0), (S["boss_r"], S["boss_h"]), (0, S["boss_h"])], 0.4),
                   T, 48)
    sh = circ(S["shaft_r"], n=24).difference(sbox(S["shaft_r"] - 0.5, -10, 10, 10))   # D flat
    shaft = extrude(sh, shaft_len, T, S["boss_h"])
    holes = cat([extrude(circ(1.5 if frame_size == 17 else 2.4, *h, 12), 0.3, T, -3.2) for h in hole_pts])
    # cable exit on the side of the rear cap, with four leads
    side = np.array(cable_side if cable_side is not None else -T[:3, 1])
    exit_c = np.asarray(face_center) - a * (length - cap / 2) + unit(side) * (s / 2 + 2.5)
    xb = T[:3, 0]
    exit_box = trimesh.creation.box(extents=(12, 5, cap * 0.8), transform=frame(exit_c, xb, a))
    leads = []
    for k, col in enumerate(("#c02020", "#2050c0", "#20a040", "#101010")):
        p0 = exit_c + unit(side) * 2 + xb * (k - 1.5) * 2.4
        leads.append((col, sweep_circle(spline([p0, p0 + unit(side) * 15 - a * 4, p0 + unit(side) * 30 - a * 20],
                                                  6), 0.8, 8)))
    return dict(caps=cat(caps), stator=cat(stator), boss=boss, shaft=shaft, holes=holes, exit=exit_box, leads=leads,
                T=T, size=s, length=length)


# ---- ball screw axis ------------------------------------------------------------------------------------

def threaded_rod(p0, p1, d=16.0, lead=5.0, depth=1.3, n_theta=28, per_lead=9):
    """Ball screw shaft with a single-start rounded (gothic-arch-like) groove."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    L = np.linalg.norm(p1 - p0)
    ns = max(2, int(L / lead * per_lead) + 1)
    s = np.linspace(0, L, ns)
    th = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
    S, TH = np.meshgrid(s, th, indexing="ij")
    phase = (TH / (2 * np.pi) - S / lead) % 1.0
    g = np.clip(1 - ((phase - 0.5) / 0.32) ** 2, 0, None) ** 0.5       # round groove 0.64 of the lead wide
    R = d / 2 - depth * g
    V = np.c_[(R * np.cos(TH)).ravel(), (R * np.sin(TH)).ravel(), S.ravel()]
    F = []
    for i in range(ns - 1):
        for k in range(n_theta):
            a, b = i * n_theta + k, i * n_theta + (k + 1) % n_theta
            F += [[a, b, b + n_theta], [a, b + n_theta, a + n_theta]]
    c0, c1 = len(V), len(V) + 1
    V = np.vstack([V, [0, 0, 0], [0, 0, L]])
    for k in range(n_theta):
        F.append([c0, (k + 1) % n_theta, k])
        F.append([c1, (ns - 1) * n_theta + k, (ns - 1) * n_theta + (k + 1) % n_theta])
    m = trimesh.Trimesh(V, np.array(F), process=False)
    m.fix_normals()
    m.apply_transform(frame(p0, any_perp(p1 - p0), p1 - p0))
    return m


def ball_nut(center, axis, up):
    """SFU1605 nut: body 28 x 42 mm, flange 48 x 10 mm with two flats (40 mm) and six 5.5 mm holes."""
    a = unit(axis)
    T = frame(np.asarray(center, float) - a * 21, up, a)
    body = revolve(fillet_profile([(8.2, 0), (14, 0), (14, 32), (8.2, 32)], 0.8), T, 48)
    fl = circ(24, n=48).intersection(sbox(-20, -30, 20, 30))
    fl = fl.difference(unary_union([circ(2.75, 19 * np.cos(t), 19 * np.sin(t), 12)
                                    for t in np.radians([30, 90, 150, 210, 270, 330])]))
    flange = extrude(fl.difference(circ(8.2, n=32)), 10, T, 32)
    wiper = revolve([(8.1, 0), (9.5, 0), (9.5, 3), (8.1, 3)], frame(np.asarray(center, float) - a * 24, up, a), 32)
    return body, flange, wiper


def end_support(center, axis, up, fixed=True):
    """BK12 (fixed) / BF12 (floating) end support: 60 x 25 x 43 mm block, shaft 25 mm above the base."""
    a, u = unit(axis), unit(up)
    w = np.cross(u, a)
    L = 25.0 if fixed else 20.0
    T = frame(np.asarray(center, float) - u * 25, w, a)          # local x across, y up, z along the shaft
    prof = Polygon([(-30, 0), (30, 0), (30, 8), (17, 8), (17, 40), (13, 43), (-13, 43), (-17, 40), (-17, 8),
                    (-30, 8)])
    prof = prof.difference(circ(7.5, 0, 25, 32))
    return extrude(prof, L, T, -L / 2)


def axis_module(name, p0, p1, z, up=(0, 0, 1), base_w=90.0, rail_gap=64.0, carriage_at=0.5, motor=None):
    """One ball-screw linear axis: aluminium base with two HGR15 rails, SFU1605 screw (16 mm, 5 mm lead)
    between BK12/BF12 supports, a ball nut under an aluminium carriage plate on four rail blocks, and a
    jaw coupling to the motor. Returns a list of (name, mesh, material)."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    v = np.r_[p1 - p0, 0]
    L = np.linalg.norm(v)
    a = unit(v)
    u = unit(up)
    w = np.cross(u, a)
    c = np.r_[(p0 + p1) / 2, z]
    out = []
    # base plate (bead blasted) with chamfered top edges, slot pattern underneath not shown
    T = frame(c - u * 12, w, a)
    base = extrude(crect(base_w, 24, 1.5), L + 40, T, -(L + 40) / 2)
    out.append((name + " base", base, "alu_blasted"))
    # HGR15 rails: 15 wide x 15 tall, top with chamfers and a neck groove, steel ground finish
    rail = Polygon([(-7.5, 0), (7.5, 0), (7.5, 9.5), (6.5, 10.5), (7.5, 11.5), (7.5, 14.3), (6.8, 15), (-6.8, 15),
                    (-7.5, 14.3), (-7.5, 11.5), (-6.5, 10.5), (-7.5, 9.5)])
    for side in (-1, 1):
        q = c + w * side * rail_gap / 2
        out.append((name + " rail", extrude(rail, L + 30, frame(q, w, a), -(L + 30) / 2), "steel_ground"))
        # rail bolts: counterbored M4 heads every 60 mm
        heads = []
        for s in np.arange(-L / 2, L / 2, 60.0):
            heads.append(cylinder(q + a * s + u * 15.0, q + a * s + u * 15.2, 3.4, 12))
        out.append((name + " rail bolts", cat(heads), "black_oxide"))
    # screw, journals, supports
    s0, s1 = np.r_[p0, z + 22], np.r_[p1, z + 22]
    out.append((name + " screw", threaded_rod(s0 + a * 12, s1 - a * 12, 16, 5, 1.3), "steel_ground"))
    out.append((name + " screw journals", cat([cylinder(s0 - a * 18, s0 + a * 12, 6, 24),
                                              cylinder(s1 - a * 12, s1 + a * 14, 5, 24)]), "steel_ground"))
    out.append((name + " end supports", cat([end_support(s0, a, u, True), end_support(s1, a, u, False)]),
                "black_oxide"))
    out.append((name + " lock nut", cylinder(s0 - a * 16, s0 - a * 8, 11, 6), "black_oxide"))
    # carriage: four HGH15 blocks (34 wide, 61 long, 24 tall incl. rail) and a plate
    pc = s0 + (s1 - s0) * carriage_at
    blocks, seals = [], []
    for side in (-1, 1):
        for off in (-22, 22):
            q = np.r_[pc[:2], z] + w * side * rail_gap / 2 + a * off
            blocks.append(round_box((34, 39, 19), 1.2, frame(q + u * 18.5, w, u)))
            for e in (-1, 1):
                seals.append(round_box((32, 4, 16), 1.0, frame(q + u * 18.5 + a * e * 21.5, w, u)))
    out.append((name + " rail blocks", cat(blocks), "steel_ground"))
    out.append((name + " block seals", cat(seals), "black_plastic"))
    q = np.r_[pc[:2], z]
    plate = round_box((base_w + 4, 100, 10), 1.5, frame(q + u * 33, w, u))
    out.append((name + " carriage plate", plate, "alu_blasted"))
    body, flange, wiper = ball_nut(pc, a, u)
    out.append((name + " ball nut", cat([body, flange]), "black_oxide"))
    out.append((name + " nut wiper", wiper, "black_plastic"))
    return out


# ---- igus-style drag chain ------------------------------------------------------------------------------

def drag_chain(points, width=26.0, height=18.0, pitch=17.0, normal=None):
    """Chain links along a smoothed path: two side plates per link (rounded, overlapping) and a top and
    bottom crossbar every link. normal: the chain's bending-plane normal (defaults to the best-fit plane)."""
    P = spline(points, 12)
    P, _ = resample(P, pitch / 4)
    if normal is None:
        Q = P - P.mean(0)
        normal = np.linalg.svd(Q)[2][2]
    nrm = unit(normal)
    C, _ = resample(P, pitch)
    plates, bars = [], []
    for i in range(len(C) - 1):
        t = unit(C[i + 1] - C[i])
        hgt = unit(np.cross(nrm, t))
        mid = (C[i] + C[i + 1]) / 2
        for side in (-1, 1):
            Tp = frame(mid + nrm * side * (width / 2 - 1.5), t, nrm)
            plates.append(extrude(rrect(pitch + 4, height, 4.5), 3.0, Tp, -1.5))
        for hs in (-1, 1):
            Tb = frame(mid + hgt * hs * (height / 2 - 1.5), t, hgt)
            bars.append(extrude(rrect(pitch * 0.45, width - 3, 1.0), 3.0, Tb, -1.5))
    return cat(plates), cat(bars)


# ---- slotted wiring duct --------------------------------------------------------------------------------

def slotted_duct(p0, p1, w=32.0, h=54.0, up=(0, 0, 1), slot_pitch=12.7, slot_w=5.0, wall=1.8, base_h=12.0):
    """Panduit Type G (1 x 2 in) duct without its cover: base, two finger walls, open slots."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    v = p1 - p0
    L = np.linalg.norm(v)
    a, u = unit(v), unit(up)
    n = np.cross(u, a)
    out = [box_local(p0 + v / 2 + u * (wall / 2), a, n, u, (L, w, wall))]
    for side in (-1, 1):
        wc = p0 + v / 2 + n * side * (w / 2 - wall / 2)
        out.append(box_local(wc + u * (base_h / 2), a, n, u, (L, wall, base_h)))
        for s in np.arange(0, L, slot_pitch):
            fl = min(slot_pitch - slot_w, L - s)
            if fl <= 0.5:
                continue
            fc = p0 + a * (s + fl / 2) + n * side * (w / 2 - wall / 2) + u * (base_h + (h - base_h) / 2)
            out.append(box_local(fc, a, n, u, (fl, wall, h - base_h)))
        # the lip that holds the cover
        lc = p0 + v / 2 + n * side * (w / 2 - wall - 0.6) + u * (h - 2.5)
        out.append(box_local(lc, a, n, u, (L, 1.2, 1.6)))
    return cat(out)


def box_local(c, a, n, u, size):
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = a, n, u, c
    return trimesh.creation.box(extents=size, transform=T)


# ---- decals ---------------------------------------------------------------------------------------------

def quad(center, x_axis, normal, w, h, lift=0.3):
    """A textured rectangle w x h (mm) centred on center, lying on the face with outward normal, x_axis
    along its width; lifted off the face by `lift`. Returns (mesh, uv)."""
    nrm = unit(normal)
    x = unit(np.asarray(x_axis, float) - (np.asarray(x_axis, float) @ nrm) * nrm)
    y = np.cross(nrm, x)
    c = np.asarray(center, float) + nrm * lift
    V = np.array([c - x * w / 2 - y * h / 2, c + x * w / 2 - y * h / 2, c + x * w / 2 + y * h / 2,
                  c - x * w / 2 + y * h / 2])
    F = np.array([[0, 1, 2], [0, 2, 3]])
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1.0]])
    return trimesh.Trimesh(V, F, process=False), uv


def text_polys(text, height, font="DejaVu Sans", weight="bold", spacing=0.0):
    """Text outline as shapely polygons (mm), baseline at y = 0, left edge at x = 0."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    tp = TextPath((0, 0), text, size=height, prop=FontProperties(family=font, weight=weight))
    polys = []
    for verts in tp.to_polygons(closed_only=True):
        if len(verts) >= 3:
            polys.append(Polygon(verts).buffer(0))
    # even-odd: outer rings minus the counters
    polys.sort(key=lambda p: -p.area)
    shapes = []
    for p in polys:
        hit = [i for i, s in enumerate(shapes) if s.contains(p)]
        if hit:
            shapes[hit[0]] = shapes[hit[0]].difference(p)
        else:
            shapes.append(p)
    return unary_union(shapes)


def text_mesh(text, height, depth, T, font="DejaVu Sans", weight="bold", anchor="center"):
    poly = text_polys(text, height, font, weight)
    minx, miny, maxx, maxy = poly.bounds
    dx = -(minx + maxx) / 2 if anchor == "center" else -minx
    poly = affinity.translate(poly, dx, -(miny + maxy) / 2)
    return extrude(poly, depth, T)
