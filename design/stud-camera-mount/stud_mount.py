"""Pan/tilt camera mount that hangs from one of the glovebox's welded ceiling studs (CadQuery).

Adapted from the stream-camera unit in vertical-cloud-lab/byu-vcl PR 318 (vertical-lab/services.py at fbc6614, MIT
licence): a printed head carries the cameras and the Pi and tilts between the arms of a yoke on two thumb knobs, and
the yoke pans on a bolt. Here the yoke hangs upside down and the ceiling stud is the pan bolt. A printed thumb nut on
the stud clamps the yoke against the ceiling; loosen it a quarter turn to pan, loosen the two side knobs to tilt.
Large knobs because the adjustments are made through the gloves. The Pi 5, HQ Camera and Camera Module 3 models are
byu-vcl's (after robot-arms PR 10, from Raspberry Pi's drawings); the Pi Zero 2 W model is from Raspberry Pi's
mechanical drawing.

Two heads share the yoke design:
  zero  Pi Zero 2 W + Camera Module 3 (unpacking, mother-tape prep);
  hq    Pi 5 + HQ Camera with the 8-50 mm zoom, and optionally a Camera Module 3 Wide on the Pi 5's second
        camera port (#16), on byu-vcl's head (overhead pick-and-place).

Frames, mm. Mount: origin where the stud leaves the ceiling, z up, so everything hangs at z < 0; the yoke pans about
z. The tilt axis is the x axis through (0, 0, -depth). Head: origin on the tilt axis; at tilt 0 the cameras look
along -y with z up, and a tilt of t degrees about +x turns the view t degrees down (90 = straight down).

Not measured: the stud's thread and length (STUD). M6 x 25 mm is assumed; check the real studs before printing.
"""

from __future__ import annotations

import math

import cadquery as cq

# ---------------------------------------------------------------------------------------------- parameters
STUD = dict(d=6.0, clear=6.6, length=25.0, nut_af=10.0, nut_t=5.0, weld_d=14.0, weld_h=1.5)   # assumed M6 x 25
KNOB = dict(d=34.0, h=13.0, flutes=10)                   # thumb nut on the stud (an M6 hex nut pressed in)
TILT = dict(clear=4.4, insert_d=5.6, insert_l=7.0, knob_d=24.0, knob_h=9.0, head_d=7.4, head_h=4.2)  # M4 + insert
PAD = dict(t=8.0, d=46.0, bar_w=24.0)                    # the yoke's top, against the ceiling
ARM_T = 5.0
SWING_CLEAR = 3.0                                        # head to stud tip / thumb nut, at any tilt

# --------------------------------------------------------------------------------------------- helpers


def cyl(d, h, x=0.0, y=0.0, z=0.0):
    return cq.Workplane("XY").circle(d / 2).extrude(h).translate((x, y, z))


def box(x0, y0, z0, x1, y1, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def xcyl(d, x0, x1, y, z):
    """Cylinder along x from x0 to x1."""
    lo, hi = min(x0, x1), max(x0, x1)
    return cq.Workplane("YZ").circle(d / 2).extrude(hi - lo).translate((lo, y, z))


def ycyl(d, y0, y1, x, z):
    """Cylinder along y from y0 to y1."""
    lo, hi = min(y0, y1), max(y0, y1)
    return cq.Workplane("XZ").circle(d / 2).extrude(-(hi - lo)).translate((x, lo, z))


def _rot(shape, steps):
    for axis, deg in steps:
        shape = shape.rotate((0, 0, 0), axis, deg)
    return shape


def _to_head(shape, at):
    """Board-frame part (board in x-y, parts on +z, optical axis -z) into the head frame: x -> -x, y -> z, z -> y
    (byu-vcl services._to_head), then moved to `at`."""
    return _rot(shape, [((1, 0, 0), -90), ((0, 1, 0), 180)]).translate(at)


def _poly_z(pts, z0, z1):
    return cq.Workplane("XY").workplane(offset=z0).polyline(pts).close().extrude(z1 - z0)


def _strip(pts, x, w=13.0, t=0.6):
    """A flat ribbon w wide (along x), through (y, z) waypoints, at x (byu-vcl services._strip)."""
    out = None
    for (y0, z0), (y1, z1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(y1 - y0, z1 - z0)
        seg = box(-w / 2, -t / 2, 0, w / 2, t / 2, L)
        seg = seg.rotate((0, 0, 0), (1, 0, 0), -math.degrees(math.atan2(y1 - y0, z1 - z0)))
        out = seg.translate((x, y0, z0)) if out is None else out.union(seg.translate((x, y0, z0)))
    return out


# ----------------------------------------------------------------------- vendor parts (byu-vcl, robot-arms)
HQ_BOARD, HQ_PITCH, HQ_PCB_T = 38.0, 30.0, 1.4
HQ_CS_SEAT, HQ_RING_D, HQ_HOUSING_D, HQ_HOUSING_FRONT = 14.43, 36.0, 34.8, 10.35
# 8-50 mm C-mount zoom (#16), (s0, s1, diameter) forward of the CS seat: the 5 mm C-CS adapter, then the lens.
# 68.3 mm long and 40-43 mm across, as in the layout render's camera_models.hq_camera; not measured.
LENS_ZOOM = dict(glass_d=30.0, profile=((0.0, 5.0, 31.0), (5.0, 12.0, 40.0), (12.0, 30.0, 43.0), (30.0, 35.0, 40.0),
                                        (35.0, 52.0, 43.0), (52.0, 73.3, 41.0)),
                 screws=((21.0, 200.0), (43.5, 160.0)), screw_tip_r=27.0)
CM3 = dict(w=25.0, h=23.862, lens_from_top=14.4, pcb_t=1.12, lens_h=8.3, housing=10.8, housing_d=4.07, lens_d=6.95)
PI5 = dict(w=85.0, h=56.0, t=1.6, holes=((3.5, 3.5), (3.5, 52.5), (61.5, 3.5), (61.5, 52.5)))
PIZ = dict(w=65.0, h=30.0, t=1.0, holes=((3.5, 3.5), (3.5, 26.5), (61.5, 3.5), (61.5, 26.5)))


def _hq_tripod_outline():
    half = [(9.91, -13.56), (12.07, -16.65), (11.467, -19.975), (8.88, -21.22), (6.985, -24.136), (6.985, -30.35)]
    return half + [(-x, y) for x, y in reversed(half)]


def hq_camera_parts():
    """HQ Camera with the zoom lens, camera frame: optical axis -z, PCB front face at z = 0 (byu-vcl)."""
    b, t = HQ_BOARD, HQ_PCB_T
    pcb = cq.Workplane("XY").box(b, b, t, centered=(True, True, False)).edges("|Z").fillet(1.0)
    for sx in (-1, 1):
        for sy in (-1, 1):
            pcb = pcb.cut(cyl(2.5, t + 2, x=sx * HQ_PITCH / 2, y=sy * HQ_PITCH / 2, z=-1))
    seat = -HQ_CS_SEAT
    mount = cyl(HQ_RING_D, 5.8, z=seat).union(cyl(HQ_HOUSING_D, -seat - 5.8, z=seat + 5.8))
    mount = mount.union(_poly_z(_hq_tripod_outline(), -HQ_HOUSING_FRONT, 0.0))
    mount = mount.union(box(-5.08, 16.0, -HQ_HOUSING_FRONT, 5.08, 21.55, 0.0))
    lens = cyl(25.4, 4.0, z=seat)
    for s0, s1, d in LENS_ZOOM["profile"]:
        lens = lens.union(cyl(d, s1 - s0, z=seat - s1))
    front = seat - LENS_ZOOM["profile"][-1][1]
    lens = lens.cut(cyl(LENS_ZOOM["glass_d"], 3.5, z=front - 1.0))
    screws = None
    for s, a in LENS_ZOOM["screws"]:
        r0 = next(d for s0, s1, d in LENS_ZOOM["profile"] if s0 <= s <= s1) / 2 - 0.5
        sc = cq.Workplane("YZ").circle(1.5).extrude(LENS_ZOOM["screw_tip_r"] - r0).translate((r0, 0, seat - s))
        sc = sc.rotate((0, 0, 0), (0, 0, 1), a)
        screws = sc if screws is None else screws.union(sc)
    glass = cyl(LENS_ZOOM["glass_d"] - 2, 0.6, z=front + 1.6)
    conn = box(-10, -b / 2 + 0.55, t, 10, -b / 2 + 6.25, t + 2.75)
    return {"HQ board": (pcb, "pcb"), "HQ connector": (conn, "white"), "HQ mount": (mount, "lens"),
            "zoom lens": (lens, "lens"), "lens screws": (screws, "steel"), "lens glass": (glass, "glass")}


def cm3_parts(wide=False):
    """Camera Module 3 (or Wide), camera frame: lens at the origin, optical axis -z, PCB front face at z = 0."""
    c = dict(CM3)
    if not wide:
        c.update(housing=8.5, lens_h=7.4, lens_d=6.0)
    top, bot = c["lens_from_top"], -(c["h"] - c["lens_from_top"])
    pcb = box(-c["w"] / 2, bot, 0, c["w"] / 2, top, c["pcb_t"])
    for sx in (-1, 1):
        for y in (top - 2.0, top - 14.5):
            pcb = pcb.cut(cyl(2.2, 4, x=sx * 10.5, y=y, z=-1))
    h = c["housing"] / 2
    module = box(-h, -h, -c["housing_d"], h, h, 0).union(cyl(c["lens_d"], c["lens_h"] - c["housing_d"],
                                                                 z=-c["lens_h"]))
    conn = box(-10, bot, c["pcb_t"], 10, bot + 5.71, c["pcb_t"] + 2.75)
    glass = cyl(c["lens_d"] - 2.0, 0.4, z=-c["lens_h"] - 0.2)
    tag = "Wide" if wide else "CM3"
    return {f"{tag} board": (pcb, "pcb"), f"{tag} connector": (conn, "white"), f"{tag} lens": (module, "lens"),
            f"{tag} glass": (glass, "glass")}


def pi5_parts():
    """Raspberry Pi 5 with its Active Cooler, board frame: x along 85, y along 56, parts on +z (byu-vcl)."""
    p, t = PI5, PI5["t"]
    board = cq.Workplane("XY").box(p["w"], p["h"], t, centered=False).edges("|Z").fillet(3.0)
    for u, v in p["holes"]:
        board = board.cut(cyl(2.7, t + 2, x=u, y=v, z=-1))
    ports = [box(64.0, 2.5, t, 87.0, 18.5, t + 13.5), box(69.5, 22.5, t, 87.0, 35.5, t + 16.0),
             box(69.5, 40.5, t, 87.0, 53.5, t + 16.0), box(6.7, -1.0, t, 15.7, 6.5, t + 3.3),
             box(22.8, -1.0, t, 28.8, 6.5, t + 3.0), box(36.2, -1.0, t, 42.2, 6.5, t + 3.0)]
    shells = ports[0]
    for q in ports[1:]:
        shells = shells.union(q)
    header = box(7.0, 50.0, t, 58.0, 55.0, t + 8.5)
    fpc = box(45.5, 4.0, t, 48.5, 17.0, t + 4.0).union(box(50.5, 4.0, t, 53.5, 17.0, t + 4.0))
    sink = box(4.0, 12.0, t + 1.0, 56.0, 50.0, t + 3.0)
    for i in range(9):
        sink = sink.union(box(4.0, 12.5 + i * 2.6, t + 3.0, 34.0, 13.5 + i * 2.6, t + 10.0))
    fan = box(35.0, 12.0, t + 3.0, 56.0, 50.0, t + 10.0).cut(cyl(17.0, 8.0, x=45.5, y=31.0, z=t + 3.6))
    hub = cyl(7.0, 6.2, x=45.5, y=31.0, z=t + 3.0)
    return {"Pi 5 board": (board, "pcb"), "Pi 5 ports": (shells, "port"), "Pi 5 header": (header, "black"),
            "Pi 5 camera connectors": (fpc, "white"), "Active Cooler": (sink.union(fan).union(hub), "cooler")}


def pi_zero_parts():
    """Raspberry Pi Zero 2 W, board frame: x along 65 (camera connector at x = 65), y along 30, parts on +z."""
    p, t = PIZ, PIZ["t"]
    board = cq.Workplane("XY").box(p["w"], p["h"], t, centered=False).edges("|Z").fillet(3.0)
    for u, v in p["holes"]:
        board = board.cut(cyl(2.75, t + 2, x=u, y=v, z=-1))
    sip = box(25.0, 8.5, t, 39.0, 22.5, t + 1.3)                                # RP3A0
    ports = [box(6.8, -0.5, t, 18.0, 7.0, t + 3.3),                             # mini HDMI
             box(37.4, -0.5, t, 45.4, 5.0, t + 2.6), box(50.0, -0.5, t, 58.0, 5.0, t + 2.6),   # micro USB, PWR
             box(-0.5, 10.5, t, 11.5, 22.5, t + 1.4)]                           # microSD
    shells = ports[0]
    for q in ports[1:]:
        shells = shells.union(q)
    csi = box(60.5, 6.7, t, 65.3, 23.3, t + 1.3)                                # 22-pin camera connector
    return {"Pi Zero board": (board, "pcb"), "Pi Zero SiP": (sip, "black"), "Pi Zero ports": (shells, "port"),
            "Pi Zero camera connector": (csi, "white")}


# ----------------------------------------------------------------------------------------------- heads
ZERO = dict(half=34.0, cheek_t=2.5, zmax=17.0, plate_t=2.5, back=(15.5, 18.0), lens_x=-14.0, lens_z=1.5,
            cm3_gap=1.5, pi_y=10.0, axis_y=9.0, boss_d=16.0, boss_t=1.0)
HQ = dict(plate=(-48.0, 48.0, -26.0, 26.0), plate_t=5.0, hq_x=-15.0, hq_standoff=4.0, wide_x=24.0, wide_z=2.0,
          pi_carrier_y=24.0, pi_standoff=5.0, axis_y=10.0, boss_d=18.0, boss_t=2.0)
HQ["nose_y"] = -(round(HQ_CS_SEAT - HQ["plate_t"] - HQ["hq_standoff"] + LENS_ZOOM["profile"][-1][1]))  # lens front


def head_zero_parts():
    """Pi Zero 2 W + Camera Module 3 head, head frame. A printed case (front plate, cheeks with the tilt bosses) and a
    back cover; the camera on four M2 screws behind the front plate, the Pi on M2.5 standoffs behind the camera."""
    h = ZERO
    a, zm, pt = h["half"], h["zmax"], h["plate_t"]
    ct = h["cheek_t"]
    case = box(-a - ct, 0, -zm, a + ct, pt, zm).edges("|Y").fillet(3.0)
    cheeks = box(-a - ct, pt, -zm, -a, h["back"][0], zm).union(box(a, pt, -zm, a + ct, h["back"][0], zm))
    case = case.union(cheeks)
    for sx in (-1, 1):                                               # tilt bosses with M4 heat-set inserts
        x0 = a + ct if sx > 0 else -a - ct - h["boss_t"]
        case = case.union(xcyl(h["boss_d"], x0, x0 + h["boss_t"], h["axis_y"], 0.0))
        xi = a + ct + h["boss_t"] if sx > 0 else -a - ct - h["boss_t"]
        case = case.cut(xcyl(TILT["insert_d"], xi, xi - sx * TILT["insert_l"], h["axis_y"], 0.0))
    lx, lz = h["lens_x"], h["lens_z"]
    case = case.cut(box(lx - 5.0, -1, lz - 5.0, lx + 5.0, pt + 1, lz + 5.0))          # window for the lens housing
    for sx in (-1, 1):
        for dz in (CM3["lens_from_top"] - 2.0, CM3["lens_from_top"] - 14.5):
            case = case.cut(ycyl(2.2, -1, pt + 1, lx + sx * 10.5, lz + dz))             # M2 screws for the camera
    case = case.cut(box(a - 1, h["pi_y"] - 1, -6.0, a + ct + 1, h["back"][0] + 1, 6.0))   # microSD slot
    back = box(-a - ct, h["back"][0], -zm, a + ct, h["back"][1], zm).edges("|Y").fillet(3.0)
    for i in range(5):                                                                # vents
        back = back.cut(box(-20 + i * 10, h["back"][0] - 1, -8, -16 + i * 10, h["back"][1] + 1, 8))
    p = {"case": (case, "petg"), "back cover": (back, "petg")}
    cam_at = (lx, pt + h["cm3_gap"], lz)                     # the camera's PCB front face
    for name, (s, m) in cm3_parts(wide=False).items():
        p[name] = (_to_head(s, cam_at), m)
    pi_at = (PIZ["w"] / 2, h["pi_y"], -PIZ["h"] / 2)         # board centred in x and z, parts toward the back
    for name, (s, m) in pi_zero_parts().items():
        p[name] = (_to_head(s, pi_at), m)
    stand = None
    for u, v in PIZ["holes"]:
        x, z = PIZ["w"] / 2 - u, v - PIZ["h"] / 2
        s = ycyl(4.5, pt, h["pi_y"], x, z)
        stand = s if stand is None else stand.union(s)
    p["standoffs"] = (stand, "steel")
    # the short 22-to-15-pin ribbon: down from the camera's connector, round to the Pi's camera connector
    cy = pt + h["cm3_gap"] + CM3["pcb_t"] + 1.5
    p["ribbon"] = (_strip([(cy, lz - 9.0), (cy, -zm + 2.5), (h["pi_y"] - 1.2, -zm + 2.5), (h["pi_y"] - 1.2, -6.0)],
                          x=-27.0, w=11.0), "ribbon")
    p["USB power lead"] = (ycyl(4.0, h["pi_y"] + 2.0, h["pi_y"] + 2.1, -21.5, -zm).union(
        cyl(4.0, 40.0, x=-21.5, y=h["pi_y"] + 3.5, z=-zm - 40.0)), "black")
    ay = h["axis_y"]
    return {n: (s.translate((0, -ay, 0)), m) for n, (s, m) in p.items() if s is not None}


def head_hq_parts(wide=True):
    """byu-vcl's head with the zoom lens in place of the 16 mm one: a PETG camera plate with the HQ Camera behind it,
    the Wide on a nose level with the lens's front, the Pi 5 on a carrier behind, cheeks with the tilt bosses."""
    h = HQ
    x0, x1, z0, z1 = h["plate"]
    pt = h["plate_t"]
    p = {}
    hq_at = (h["hq_x"], pt + h["hq_standoff"], 0.0)
    plate = box(x0, 0, z0, x1, pt, z1).edges("|Y").fillet(4.0)
    plate = plate.cut(cq.Workplane("XZ").circle(37.0 / 2).extrude(-pt - 2).translate((h["hq_x"], -1, 0)))
    foot = _to_head(_poly_z(_hq_tripod_outline(), -HQ_HOUSING_FRONT - 1, 2.0), hq_at)
    lock = _to_head(box(-6.1, 15.0, -HQ_HOUSING_FRONT - 1, 6.1, 22.6, 2.0), hq_at)
    plate = plate.cut(foot).cut(lock)
    p["camera plate"] = (plate, "petg")
    if wide:
        plate = plate.cut(box(h["wide_x"] - 12.0, -1, h["wide_z"] - 16.0, h["wide_x"] + 4.0, pt + 1,
                              h["wide_z"] - 13.0))
        p["camera plate"] = (plate, "petg")
        wx0, wx1 = h["wide_x"] - 14.0, h["wide_x"] + 18.0
        ny = h["nose_y"]
        nose = box(wx0, ny, h["wide_z"] - 16, wx1, ny + 5, h["wide_z"] + 16)
        nose = nose.cut(box(h["wide_x"] - 5.7, ny - 1, h["wide_z"] - 5.7, h["wide_x"] + 5.7, ny + 6,
                            h["wide_z"] + 5.7))
        nose = nose.union(box(wx0, ny, h["wide_z"] - 20, wx1, 0, h["wide_z"] - 16))
        nose = nose.union(box(wx1 - 4, ny + 5, h["wide_z"] - 16, wx1, 0, h["wide_z"] + 8))
        p["Wide nose"] = (nose, "petg")
        wide_at = (h["wide_x"], ny + 5 + 2.5, h["wide_z"])
        for name, (s, m) in cm3_parts(wide=True).items():
            p[name] = (_to_head(s, wide_at), m)
        zs = h["wide_z"] - 14.5
    carrier = box(x0, h["pi_carrier_y"], z0 - 4, x1, h["pi_carrier_y"] + 4, z1 + 4).edges("|Y").fillet(4.0)
    cheeks = box(x0, pt, z0, x0 + 4, h["pi_carrier_y"], z1).union(box(x1 - 4, pt, z0, x1, h["pi_carrier_y"], z1))
    for sx in (-1, 1):
        xb = x1 if sx > 0 else x0 - h["boss_t"]
        cheeks = cheeks.union(xcyl(h["boss_d"], xb, xb + h["boss_t"], h["axis_y"], 0.0))
        xi = x1 + h["boss_t"] if sx > 0 else x0 - h["boss_t"]
        cheeks = cheeks.cut(xcyl(TILT["insert_d"], xi, xi - sx * TILT["insert_l"], h["axis_y"], 0.0))
    p["Pi carrier"] = (carrier, "petg")
    p["cheeks"] = (cheeks, "petg")
    for name, (s, m) in hq_camera_parts().items():
        p[name] = (_to_head(s, hq_at), m)
    pi_y = h["pi_carrier_y"] + 4 + h["pi_standoff"]
    pi_at = (PI5["w"] / 2, pi_y, -PI5["h"] / 2)
    for name, (s, m) in pi5_parts().items():
        p[name] = (_rot(s, [((1, 0, 0), -90), ((0, 1, 0), 180)]).translate(pi_at), m)
    stand = None
    for u, v in PI5["holes"]:
        x, z = PI5["w"] / 2 - u, v - PI5["h"] / 2
        s = ycyl(6.0, h["pi_carrier_y"] + 4, h["pi_carrier_y"] + 4 + h["pi_standoff"], x, z)
        stand = s if stand is None else stand.union(s)
    for sx in (-1, 1):
        for sz in (-1, 1):
            stand = stand.union(ycyl(5.2, pt, pt + h["hq_standoff"], h["hq_x"] + sx * HQ_PITCH / 2,
                                     sz * HQ_PITCH / 2))
    p["standoffs"] = (stand, "steel")
    zr = z0 - 6.0
    yb = pi_y + PI5["t"] + 4.5
    p["HQ ribbon"] = (_strip([(hq_at[1] + 2.0, -HQ_BOARD / 2 + 3.0), (hq_at[1] + 2.0, zr), (yb, zr),
                              (yb, -PI5["h"] / 2 + 12.0)], x=-10.0), "ribbon")
    if wide:
        p["Wide ribbon"] = (_strip([(wide_at[1] + 2.0, h["wide_z"] - 9.0), (wide_at[1] + 2.0, zs), (pt + 3.0, zs),
                                    (pt + 3.0, zr - 1.2), (yb + 1.2, zr - 1.2), (yb + 1.2, -PI5["h"] / 2 + 12.0)],
                                   x=h["wide_x"] - 4.0), "ribbon")
    ay = h["axis_y"]
    return {n: (s.translate((0, -ay, 0)), m) for n, (s, m) in p.items() if s is not None}


# ------------------------------------------------------------------------------------- yoke, knobs, stud
def head_spec(kind):
    """(half-width at the bosses' faces, swing radius about the tilt axis) of a head."""
    if kind == "zero":
        h = ZERO
        half = h["half"] + h["cheek_t"] + h["boss_t"]
    else:
        h = HQ
        half = h["plate"][1] + h["boss_t"]
    return half, swing_radius(kind)


_SWING: dict = {}


def swing_radius(kind):
    """Largest distance of any head part from the tilt axis, from the tessellated head."""
    if kind not in _SWING:
        parts = head_zero_parts() if kind == "zero" else head_hq_parts()
        r = 0.0
        for name, (s, _) in parts.items():
            if "lead" in name:                      # cables bend out of the way
                continue
            for sol in s.vals():
                verts, _ = sol.tessellate(0.5)
                for v in verts:
                    r = max(r, math.hypot(v.y, v.z))
        _SWING[kind] = r
    return _SWING[kind]


def swing_radius_behind(kind):
    """Largest distance from the tilt axis of the part of the head behind it (y > 0): what swings up toward the
    ceiling when the camera looks down."""
    parts = head_zero_parts() if kind == "zero" else head_hq_parts()
    r = 0.0
    for name, (s, _) in parts.items():
        if "lead" in name:
            continue
        for sol in s.vals():
            verts, _ = sol.tessellate(0.5)
            for v in verts:
                if v.y > -12.0:
                    r = max(r, math.hypot(v.y, v.z))
    return r


def tilt_depth(kind):
    """Depth of the tilt axis below the ceiling: the head clears the stud's tip and the thumb nut when it looks
    anywhere from level to straight down. The zero head is small enough to clear them at any angle."""
    top = max(PAD["t"] + KNOB["h"], STUD["length"])
    r = swing_radius(kind) if kind == "zero" else swing_radius_behind(kind)
    return math.ceil(top + SWING_CLEAR + r)


def yoke(kind):
    """The yoke, mount frame: the pad against the ceiling with the stud through it (and a recess for the weld), a
    bar out to two arms that drop to the tilt axis, each with an M4 clearance hole."""
    half, _ = head_spec(kind)
    depth = tilt_depth(kind)
    a0, a1 = half + 0.5, half + 0.5 + ARM_T
    t, bw = PAD["t"], PAD["bar_w"]
    pad = cyl(PAD["d"], t, z=-t)
    bar = box(-a1, -bw / 2, -t, a1, bw / 2, 0).edges("|Z").fillet(3.0)
    y = pad.union(bar)
    br = 10.0
    for sx in (-1, 1):
        x0 = a0 if sx > 0 else -a1
        prof = [(-bw / 2, 0.0), (bw / 2, 0.0), (br, -depth), (-br, -depth)]
        arm = cq.Workplane("YZ").polyline(prof).close().extrude(ARM_T).translate((x0, 0, 0))
        arm = arm.union(xcyl(2 * br, x0, x0 + ARM_T, 0.0, -depth))
        y = y.union(arm)
        y = y.cut(xcyl(TILT["clear"], x0 - 1, x0 + ARM_T + 1, 0.0, -depth))
    y = y.cut(cyl(STUD["clear"], t + 2, z=-t - 1))
    y = y.cut(cyl(STUD["weld_d"], STUD["weld_h"], z=-STUD["weld_h"]))
    return y


def stud_knob():
    """Thumb nut, mount frame (its top against the pad): an M6 nut pressed into a hex pocket, the stud through."""
    k = KNOB
    z0 = -PAD["t"] - k["h"]
    knob = cyl(k["d"], k["h"], z=z0)
    for i in range(k["flutes"]):
        a = 2 * math.pi * i / k["flutes"]
        knob = knob.cut(cyl(6.0, k["h"] + 2, x=(k["d"] / 2 + 1.2) * math.cos(a), y=(k["d"] / 2 + 1.2) * math.sin(a),
                            z=z0 - 1))
    knob = knob.cut(cyl(STUD["clear"], k["h"] + 2, z=z0 - 1))
    hexp = (cq.Workplane("XY").polygon(6, (STUD["nut_af"] + 0.3) / math.cos(math.pi / 6))
            .extrude(STUD["nut_t"] + 0.3).translate((0, 0, -PAD["t"] - STUD["nut_t"] - 0.3)))
    return knob.cut(hexp)


def tilt_knobs(kind):
    """Two thumb knobs on M4 x 16 cap screws, mount frame, outside the yoke's arms on the tilt axis."""
    half, _ = head_spec(kind)
    depth = tilt_depth(kind)
    a1 = half + 0.5 + ARM_T
    t = TILT
    out, screws = None, None
    for sx in (-1, 1):
        x0 = a1 if sx > 0 else -a1 - t["knob_h"]
        k = xcyl(t["knob_d"], x0, x0 + t["knob_h"], 0.0, -depth)
        for i in range(8):
            a = 2 * math.pi * i / 8
            k = k.cut(xcyl(5.0, x0 - 1, x0 + t["knob_h"] + 1, (t["knob_d"] / 2 + 1.0) * math.cos(a),
                           -depth + (t["knob_d"] / 2 + 1.0) * math.sin(a)))
        out = k if out is None else out.union(k)
        xs = a1 + t["knob_h"] - 2.0 if sx > 0 else -a1 - t["knob_h"] + 2.0
        sc = xcyl(4.0, xs, -sx * (half - 6.0), 0.0, -depth)
        screws = sc if screws is None else screws.union(sc)
    return out, screws


def ceiling_stud():
    """The welded stud with its weld bead and a washer under the thumb nut's nut, mount frame."""
    stud = cyl(STUD["d"], STUD["length"], z=-STUD["length"])
    bead = cyl(STUD["weld_d"] - 3.0, STUD["weld_h"] - 0.3, z=-(STUD["weld_h"] - 0.3))
    return stud.union(bead)


# ---------------------------------------------------------------------------------------- assembly
def pose_matrix(pan_deg, tilt_deg, depth):
    """4x4 (row-major list) taking head-frame points to the mount frame."""
    p, t = math.radians(pan_deg), math.radians(tilt_deg)
    cp, sp, ct, st = math.cos(p), math.sin(p), math.cos(t), math.sin(t)
    rz = [[cp, -sp, 0.0], [sp, cp, 0.0], [0.0, 0.0, 1.0]]
    rx = [[1.0, 0.0, 0.0], [0.0, ct, -st], [0.0, st, ct]]
    r = [[sum(rz[i][k] * rx[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    tz = [rz[i][2] * -depth for i in range(3)]
    return [r[0] + [tz[0]], r[1] + [tz[1]], r[2] + [tz[2]], [0.0, 0.0, 0.0, 1.0]]


def lens_point(kind):
    """The camera's lens centre (the HQ's zoom front, or the CM3's glass), head frame."""
    if kind == "zero":
        h = ZERO
        return (h["lens_x"], h["plate_t"] + h["cm3_gap"] - CM3["lens_h"] + 0.9 - h["axis_y"], h["lens_z"])
    h = HQ
    y = h["plate_t"] + h["hq_standoff"] - HQ_CS_SEAT - LENS_ZOOM["profile"][-1][1] - h["axis_y"]
    return (h["hq_x"], y, 0.0)


def parts(kind, wide=True):
    """{piece: {name: (Workplane, material)}} with pieces 'fixed' (stud), 'pan' (yoke, knobs) and 'head', each in its
    own frame: fixed and pan in the mount frame at pan 0, head in the head frame."""
    knobs, screws = tilt_knobs(kind)
    head = head_zero_parts() if kind == "zero" else head_hq_parts(wide=wide)
    return {"fixed": {"ceiling stud": (ceiling_stud(), "steel")},
            "pan": {"yoke": (yoke(kind), "petg"), "stud thumb nut": (stud_knob(), "knob"),
                    "tilt knobs": (knobs, "knob"), "M4 screws": (screws, "steel")},
            "head": head}


def assembly(kind, pan=0.0, tilt=45.0, wide=True):
    """CadQuery Assembly at a pose, mount frame."""
    colours = dict(petg=(0.15, 0.16, 0.17), knob=(0.85, 0.42, 0.10), steel=(0.75, 0.77, 0.80),
                   pcb=(0.12, 0.48, 0.24), lens=(0.08, 0.08, 0.09), glass=(0.30, 0.45, 0.65),
                   white=(0.93, 0.93, 0.93), port=(0.70, 0.72, 0.75), black=(0.1, 0.1, 0.1),
                   cooler=(0.55, 0.58, 0.62), ribbon=(0.85, 0.65, 0.25))
    depth = tilt_depth(kind)
    pc = parts(kind, wide)
    asm = cq.Assembly(name=f"stud_mount_{kind}")
    rz = cq.Location(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), pan)
    for name, (s, m) in pc["fixed"].items():
        asm.add(s, name=name, color=cq.Color(*colours[m]))
    for name, (s, m) in pc["pan"].items():
        asm.add(s, name=name, loc=rz, color=cq.Color(*colours[m]))
    head_loc = rz * cq.Location(cq.Vector(0, 0, -depth)) * cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), tilt)
    for name, (s, m) in pc["head"].items():
        asm.add(s, name=name.replace(" ", "_"), loc=head_loc, color=cq.Color(*colours[m]))
    return asm


PRINTED = {
    "zero": {"yoke_zero": lambda: yoke("zero"), "head_zero_case": lambda: head_zero_parts()["case"][0],
             "head_zero_back_cover": lambda: head_zero_parts()["back cover"][0]},
    "hq": {"yoke_hq": lambda: yoke("hq"), "head_hq_camera_plate": lambda: head_hq_parts()["camera plate"][0],
           "head_hq_cheeks": lambda: head_hq_parts()["cheeks"][0],
           "head_hq_pi_carrier": lambda: head_hq_parts()["Pi carrier"][0],
           "head_hq_wide_nose": lambda: head_hq_parts()["Wide nose"][0]},
    "common": {"stud_thumb_nut": stud_knob, "tilt_knob": lambda: _one_tilt_knob()},
}


def _one_tilt_knob():
    k = TILT
    knob = cyl(k["knob_d"], k["knob_h"])
    for i in range(8):
        a = 2 * math.pi * i / 8
        knob = knob.cut(cyl(5.0, k["knob_h"] + 2, x=(k["knob_d"] / 2 + 1.0) * math.cos(a),
                            y=(k["knob_d"] / 2 + 1.0) * math.sin(a), z=-1))
    knob = knob.cut(cyl(TILT["clear"], k["knob_h"] + 2, z=-1))
    return knob.cut(cq.Workplane("XY").polygon(6, 7.3 / math.cos(math.pi / 6)).extrude(k["head_h"] + 0.2)
                    .translate((0, 0, k["knob_h"] - k["head_h"] - 0.2)))


if __name__ == "__main__":
    for kind in ("zero", "hq"):
        print(kind, "swing radius %.1f, behind %.1f, tilt-axis depth %d mm, lens %s" % (
            swing_radius(kind), swing_radius_behind(kind), tilt_depth(kind),
            tuple(round(c, 1) for c in lens_point(kind))))
