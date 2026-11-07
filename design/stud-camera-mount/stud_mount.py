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
STUD = dict(d=6.0, clear=6.6, length=25.0, weld_d=14.0, weld_h=1.5)   # assumed M6 x 25
# Hardware, from the standards' limits (min/max), so press_fit.py can stack the tolerances.
NUT_M6 = dict(s_max=10.00, s_min=9.78, m_max=5.20, m_min=4.90, e_min=11.05)            # ISO 4032 M6 hex nut
BOLT_M4 = dict(s_max=7.00, s_min=6.78, k_max=2.925, k_min=2.675, e_min=7.66, l=16.0)    # ISO 4017 M4 x 16 hex bolt
WASHER_M6 = dict(d_in=6.4, d_out=12.0, t=1.6)                                           # ISO 7089 M6, nut to pad
WASHER_M4 = dict(d_in=4.3, d_out=9.0, t=0.8)                                            # ISO 7089 M4, in the knob
INSERT_M4 = dict(l=8.1, od=6.3, hole_d=5.6, hole_l=8.6)    # M4 x 8.1 heat-set insert (Ruthex / CNC Kitchen type)
# Crush-rib hex pockets. The hex clears the largest nut or bolt head; one rib per flat stands rib_h proud of it and
# crushes as the part is pressed in, so every part between the standard's limits is gripped without splitting the
# knob (press_fit.py). `lead` is a 45-degree lead-in at the mouth; the ribs stop below it.
NUT_POCKET = dict(af=10.20, depth=4.7, rib_h=0.30, rib_r=0.50, lead=0.6)    # M6 nut, mouth toward the yoke's pad
HEAD_POCKET = dict(af=7.20, depth=2.9, rib_h=0.30, rib_r=0.50, lead=0.5, washer_d=9.4, washer_t=0.9)  # M4 head
KNOB = dict(d=34.0, h=13.0, flutes=10)                   # thumb nut on the stud
TILT = dict(clear=4.4, knob_d=24.0, knob_h=8.0)          # tilt knobs, M4 x 16 hex bolts into heat-set inserts
PAD = dict(t=8.0, d=46.0, bar_w=24.0)                    # the yoke's top, against the ceiling
ARM_T = 5.0
ARM_GAP = 0.3                                            # arm to boss face before the tilt knob is tightened
GUSSET = 5.0                                             # 45-degree gusset inside each arm's root
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


def hex_prism(af, z0, z1):
    """Hexagonal prism, flats `af` apart, corners on the x axis, from z0 to z1."""
    return cq.Workplane("XY").polygon(6, af / math.cos(math.pi / 6)).extrude(z1 - z0).translate((0, 0, z0))


def rib_hex_pocket(p, z_top):
    """Cutter for a crush-rib hex pocket whose mouth is at z_top and floor at z_top - p['depth'] (axis z). Subtracting
    it leaves one rib per flat (a cylinder of radius rib_r standing rib_h proud of the flat, from the floor to the
    lead-in) and a 45-degree lead-in of p['lead'] at the mouth."""
    af, depth, h, r, lead = p["af"], p["depth"], p["rib_h"], p["rib_r"], p["lead"]
    z0 = z_top - depth
    cut = hex_prism(af, z0, z_top + 0.01)
    k = 1.0 / math.cos(math.pi / 6)
    mouth = (cq.Workplane("XY").workplane(offset=z_top - lead).polygon(6, af * k)
             .workplane(offset=lead + 0.01).polygon(6, (af + 2 * lead + 0.02) * k).loft())
    cut = cut.union(mouth)
    d = af / 2 - h + r                                       # rib axis, just outside the flat
    for i in range(6):
        a = math.radians(30 + 60 * i)                        # flat normals (corners are at 0, 60, ...)
        rib = cyl(2 * r, depth - lead - 0.01 + 0.01, x=d * math.cos(a), y=d * math.sin(a), z=z0 - 0.01)
        cut = cut.cut(rib)
    return cut


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
# Zero head: a front plate and two cheeks (a U open at the top and bottom) and a back cover. The camera sits on four
# printed bosses behind the window, the Pi on four printed posts behind the camera, and the cover's spacer tubes clamp
# the Pi onto its posts with four M2.5 x 12 screws. The tilt bosses are blocks down to the print bed, with blind holes
# for the M4 inserts so neither the inserts nor the bolts reach the Pi. The interior leaves 4.5 mm beyond each end of
# the Pi: room for the camera ribbon's U-turn into the Pi's connector, and for the microSD card.
ZERO = dict(half=37.0, cheek_t=2.5, zmax=17.0, plate_t=2.5, back=(15.5, 18.0), lens_x=-13.0, lens_z=1.5,
            cm3_gap=1.5, pi_y=10.0, axis_y=9.0, boss_d=16.0, boss_t=7.0, post_d=5.0, tube_d=5.0, cm3_boss_d=4.0)
# HQ head: byu-vcl's head, with the camera plate, cheeks and four corner columns printed as one frame; the Pi 5
# carrier screws onto the columns, the Wide's nose onto the plate (both M2.5, thread-forming into PLA).
HQ = dict(plate=(-48.0, 48.0, -26.0, 26.0), plate_t=5.0, hq_x=-15.0, hq_standoff=4.0, wide_x=24.0, wide_z=2.0,
          pi_carrier_y=24.0, pi_standoff=5.0, axis_y=10.0, boss_d=18.0, boss_t=5.5, cheek_t=4.0,
          col=(37.0, 44.0, 11.0, 19.0), nose_screws=((20.0, -19.0), (33.0, -19.0)), post_d=6.0, hq_post_d=5.2)
HQ["nose_y"] = -(round(HQ_CS_SEAT - HQ["plate_t"] - HQ["hq_standoff"] + LENS_ZOOM["profile"][-1][1]))  # lens front
M25 = dict(clear=2.7, pilot=2.2, head_d=4.5, head_k=1.8)  # M2.5 screws thread-forming into printed pilot holes
M2 = dict(clear=2.2, pilot=1.7)


def _tilt_bosses(x_face_in, boss_t, boss_d, axis_y, y_bed):
    """Tilt bosses on both sides, head frame before the axis shift: a disc around the tilt axis carried down to the
    print bed as a block, outboard of x = +/-x_face_in, with a blind hole for the M4 insert in each."""
    out, holes = None, None
    r = boss_d / 2
    for sx in (-1, 1):
        x0, x1 = sorted((sx * x_face_in, sx * (x_face_in + boss_t)))
        b = xcyl(boss_d, x0, x1, axis_y, 0.0).union(box(x0, y_bed, -r, x1, axis_y, r))
        out = b if out is None else out.union(b)
        xf = sx * (x_face_in + boss_t)
        h = xcyl(INSERT_M4["hole_d"], xf + sx * 0.01, xf - sx * INSERT_M4["hole_l"], axis_y, 0.0)
        holes = h if holes is None else holes.union(h)
    return out, holes


def head_zero_parts():
    """Pi Zero 2 W + Camera Module 3 head, head frame (tilt axis at the origin)."""
    h = ZERO
    a, zm, pt, ct = h["half"], h["zmax"], h["plate_t"], h["cheek_t"]
    case = box(-a - ct, 0, -zm, a + ct, pt, zm).edges("|Y").fillet(3.0)
    cheeks = box(-a - ct, pt, -zm, -a, h["back"][0], zm).union(box(a, pt, -zm, a + ct, h["back"][0], zm))
    case = case.union(cheeks)
    bosses, insert_holes = _tilt_bosses(a + ct, h["boss_t"], h["boss_d"], h["axis_y"], 0.0)
    case = case.union(bosses)
    lx, lz = h["lens_x"], h["lens_z"]
    cam_y = pt + h["cm3_gap"]                                   # the camera's PCB front face
    cm3_holes = [(lx + sx * 10.5, lz + dz) for sx in (-1, 1) for dz in (CM3["lens_from_top"] - 2.0,
                                                                        CM3["lens_from_top"] - 14.5)]
    for x, z in cm3_holes:                                      # bosses the camera screws onto (M2 x 4)
        case = case.union(ycyl(h["cm3_boss_d"], pt - 0.01, cam_y, x, z))
    pi_holes = [(PIZ["w"] / 2 - u, v - PIZ["h"] / 2) for u, v in PIZ["holes"]]
    for x, z in pi_holes:                                       # posts the Pi sits on
        case = case.union(ycyl(h["post_d"], pt - 0.01, h["pi_y"], x, z))
    case = case.cut(insert_holes)
    case = case.cut(box(lx - 5.0, -1, lz - 5.0, lx + 5.0, pt + 1, lz + 5.0))           # window for the lens housing
    for x, z in cm3_holes:
        case = case.cut(ycyl(M2["pilot"], 1.0, cam_y + 0.01, x, z))
    for x, z in pi_holes:
        case = case.cut(ycyl(M25["pilot"], h["pi_y"] - 6.0, h["pi_y"] + 0.01, x, z))
    y0, y1 = h["back"]
    back = box(-a - ct, y0, -zm, a + ct, y1, zm).edges("|Y").fillet(3.0)
    for i in range(5):                                                                # vents
        back = back.cut(box(-20 + i * 10, y0 - 1, -8, -16 + i * 10, y1 + 1, 8))
    pi_back = h["pi_y"] + PIZ["t"]
    for x, z in pi_holes:                                       # spacer tubes onto the Pi, screw holes through
        back = back.union(ycyl(h["tube_d"], pi_back, y0 + 0.01, x, z))
        back = back.cut(ycyl(M25["clear"], pi_back - 0.01, y1 + 0.01, x, z))
    p = {"case": (case, "petg"), "back cover": (back, "petg")}
    for name, (s, m) in cm3_parts(wide=False).items():
        p[name] = (_to_head(s, (lx, cam_y, lz)), m)
    pi_at = (PIZ["w"] / 2, h["pi_y"], -PIZ["h"] / 2)         # board centred in x and z, parts toward the back
    for name, (s, m) in pi_zero_parts().items():
        p[name] = (_to_head(s, pi_at), m)
    screws = None
    for x, z in pi_holes:                                       # M2.5 x 12 pan heads on the cover
        s = ycyl(2.5, y1 - 12.0, y1, x, z).union(ycyl(M25["head_d"], y1, y1 + M25["head_k"], x, z))
        screws = s if screws is None else screws.union(s)
    for x, z in cm3_holes:                                      # M2 x 4 from behind the camera
        s = ycyl(2.0, cam_y + CM3["pcb_t"] - 4.0, cam_y + CM3["pcb_t"], x, z).union(
            ycyl(3.8, cam_y + CM3["pcb_t"], cam_y + CM3["pcb_t"] + 1.3, x, z))
        screws = screws.union(s)
    ins = None
    for sx in (-1, 1):                                          # the heat-set inserts, flush with the boss faces
        xf = sx * (a + ct + h["boss_t"])
        s = xcyl(INSERT_M4["od"] - 0.4, xf, xf - sx * INSERT_M4["l"], h["axis_y"], 0.0)
        ins = s if ins is None else ins.union(s)
    p["screws"] = (screws, "steel")
    p["inserts"] = (ins, "brass")
    # the camera's ribbon (16 mm at the camera, 11.5 mm at the Pi; drawn 11.5 wide past the fold): out of the camera's
    # connector, folded up behind the camera, along the front of the Pi to beyond its end, U-turned into its connector
    cy = cam_y + CM3["pcb_t"] + 1.4
    bot = lz - (CM3["h"] - CM3["lens_from_top"])
    rib = _strip([(cy, bot), (cy, -11.5), (9.0, -11.5), (9.0, 0.0)], x=lx, w=16.0, t=0.3)
    rib = rib.union(box(-35.5, 8.85, -5.75, lx - 8.0, 9.15, 5.75))
    rib = rib.union(box(-35.8, 8.85, -5.75, -35.5, 11.75, 5.75))
    rib = rib.union(box(-35.5, 11.45, -5.75, -30.5, 11.75, 5.75))
    p["ribbon"] = (rib, "ribbon")
    p["USB power lead"] = (ycyl(4.0, h["pi_y"] + 2.0, h["pi_y"] + 2.1, -21.5, -zm).union(
        cyl(4.0, 40.0, x=-21.5, y=h["pi_y"] + 3.5, z=-zm - 40.0)), "black")
    ay = h["axis_y"]
    return {n: (s.translate((0, -ay, 0)), m) for n, (s, m) in p.items() if s is not None}


def head_hq_parts(wide=True):
    """byu-vcl's head with the zoom lens in place of the 16 mm one, head frame (tilt axis at the origin): a frame
    (camera plate, cheeks, tilt bosses, four corner columns) with the HQ Camera on printed posts behind the plate, the
    Pi 5 on posts on a carrier screwed to the columns, and the Wide on a nose level with the lens's front."""
    h = HQ
    x0, x1, z0, z1 = h["plate"]
    pt, ct = h["plate_t"], h["cheek_t"]
    cy = h["pi_carrier_y"]
    p = {}
    hq_at = (h["hq_x"], pt + h["hq_standoff"], 0.0)
    frame = box(x0, 0, z0, x1, pt, z1).edges("|Y").fillet(4.0)
    frame = frame.union(box(x0, pt - 0.01, z0, x0 + ct, cy, z1)).union(box(x1 - ct, pt - 0.01, z0, x1, cy, z1))
    cx0, cx1, cz0, cz1 = h["col"]
    cols = [(sx, sz) for sx in (-1, 1) for sz in (-1, 1)]
    for sx, sz in cols:
        xa, xb = sorted((sx * cx0, sx * (cx1 + 0.01)))
        za, zb = sorted((sz * cz0, sz * cz1))
        frame = frame.union(box(xa, pt - 0.01, za, xb, cy, zb))
    bosses, insert_holes = _tilt_bosses(x1, h["boss_t"], h["boss_d"], h["axis_y"], 0.0)
    frame = frame.union(bosses)
    hq_holes = [(h["hq_x"] + sx * HQ_PITCH / 2, sz * HQ_PITCH / 2) for sx in (-1, 1) for sz in (-1, 1)]
    for x, z in hq_holes:
        frame = frame.union(ycyl(h["hq_post_d"], pt - 0.01, hq_at[1], x, z))
    frame = frame.cut(insert_holes)
    frame = frame.cut(cq.Workplane("XZ").circle(37.0 / 2).extrude(-pt - 2).translate((h["hq_x"], -1, 0)))
    foot = _to_head(_poly_z(_hq_tripod_outline(), -HQ_HOUSING_FRONT - 1, 2.0), hq_at)
    lock = _to_head(box(-6.1, 15.0, -HQ_HOUSING_FRONT - 1, 6.1, 22.6, 2.0), hq_at)
    frame = frame.cut(foot).cut(lock)
    for x, z in hq_holes:
        frame = frame.cut(ycyl(M25["pilot"], hq_at[1] - 6.0, hq_at[1] + 0.01, x, z))
    col_c = [(sx * 0.5 * (cx0 + cx1), sz * 0.5 * (cz0 + cz1)) for sx, sz in cols]
    for x, z in col_c:
        frame = frame.cut(ycyl(M25["pilot"], cy - 8.0, cy + 0.01, x, z))
    carrier = box(x0, cy, z0 - 4, x1, cy + 4, z1 + 4).edges("|Y").fillet(4.0)
    pi_y = cy + 4 + h["pi_standoff"]
    pi_holes = [(PI5["w"] / 2 - u, v - PI5["h"] / 2) for u, v in PI5["holes"]]
    for x, z in pi_holes:
        carrier = carrier.union(ycyl(h["post_d"], cy + 4 - 0.01, pi_y, x, z))
        carrier = carrier.cut(ycyl(M25["pilot"], pi_y - 6.0, pi_y + 0.01, x, z))
    for x, z in col_c:                                          # countersunk M2.5 x 10 into the columns
        carrier = carrier.cut(ycyl(M25["clear"], cy - 0.01, cy + 4.01, x, z))
        carrier = carrier.cut(cq.Workplane("XZ").workplane(offset=-(cy + 4.01)).circle(2.6)
                              .workplane(offset=1.5).circle(1.35).loft().translate((x, 0, z)))
    if wide:
        frame = frame.cut(box(h["wide_x"] - 12.0, -1, h["wide_z"] - 16.0, h["wide_x"] + 4.0, pt + 1,
                              h["wide_z"] - 13.0))
        for x, z in h["nose_screws"]:
            frame = frame.cut(ycyl(M25["clear"], -0.01, pt + 0.01, x, z))
        wx0, wx1 = h["wide_x"] - 14.0, h["wide_x"] + 18.0
        ny = h["nose_y"]
        nose = box(wx0, ny, h["wide_z"] - 16, wx1, ny + 5, h["wide_z"] + 16)
        nose = nose.cut(box(h["wide_x"] - 5.7, ny - 1, h["wide_z"] - 5.7, h["wide_x"] + 5.7, ny + 6,
                            h["wide_z"] + 5.7))
        nose = nose.union(box(wx0, ny, h["wide_z"] - 20, wx1, 0, h["wide_z"] - 16))
        nose = nose.union(box(wx1 - 4, ny + 5, h["wide_z"] - 16, wx1, 0, h["wide_z"] + 8))
        nose = nose.union(box(wx0, -6.0, -24.0, wx1, 0.0, h["wide_z"] - 16))          # flange against the plate
        wide_y = ny + 5 + 2.5                                   # the Wide's PCB front face
        wide_holes = [(h["wide_x"] + sx * 10.5, h["wide_z"] + dz) for sx in (-1, 1)
                      for dz in (CM3["lens_from_top"] - 2.0, CM3["lens_from_top"] - 14.5)]
        for x, z in wide_holes:                                 # bosses the Wide screws onto (M2 x 4)
            nose = nose.union(ycyl(ZERO["cm3_boss_d"], ny + 5 - 0.01, wide_y, x, z))
            nose = nose.cut(ycyl(M2["pilot"], wide_y - 3.5, wide_y + 0.01, x, z))
        for x, z in h["nose_screws"]:
            nose = nose.cut(ycyl(M25["pilot"], -6.0 - 0.01, 0.01, x, z))
        for name, (s, m) in cm3_parts(wide=True).items():
            p[name] = (_to_head(s, (h["wide_x"], ny + 5 + 2.5, h["wide_z"])), m)
        p["Wide nose"] = (nose, "petg")
        zs = h["wide_z"] - 14.5
        wide_at = (h["wide_x"], ny + 5 + 2.5, h["wide_z"])
    p["frame"] = (frame, "petg")
    p["Pi carrier"] = (carrier, "petg")
    for name, (s, m) in hq_camera_parts().items():
        p[name] = (_to_head(s, hq_at), m)
    for name, (s, m) in pi5_parts().items():
        p[name] = (_rot(s, [((1, 0, 0), -90), ((0, 1, 0), 180)]).translate((PI5["w"] / 2, pi_y, -PI5["h"] / 2)), m)
    screws = None
    for x, z in hq_holes:                                       # M2.5 x 6 through the HQ board
        y = hq_at[1] + HQ_PCB_T
        s = ycyl(2.5, y - 6.0, y, x, z).union(ycyl(M25["head_d"], y, y + M25["head_k"], x, z))
        screws = s if screws is None else screws.union(s)
    for x, z in pi_holes:                                       # M2.5 x 6 through the Pi 5
        y = pi_y + PI5["t"]
        screws = screws.union(ycyl(2.5, y - 6.0, y, x, z).union(ycyl(M25["head_d"], y, y + M25["head_k"], x, z)))
    for x, z in col_c:                                          # countersunk M2.5 x 10, carrier to columns
        screws = screws.union(ycyl(2.5, cy + 4 - 10.0, cy + 2.5, x, z))
    if wide:
        for x, z in wide_holes:                                 # M2 x 4 from behind the Wide
            yb_ = wide_y + CM3["pcb_t"]
            screws = screws.union(ycyl(2.0, yb_ - 4.0, yb_, x, z).union(ycyl(3.8, yb_, yb_ + 1.3, x, z)))
        for x, z in h["nose_screws"]:                           # M2.5 x 10 from inside the frame into the nose
            screws = screws.union(ycyl(2.5, pt - 10.0, pt, x, z).union(ycyl(M25["head_d"], pt, pt + M25["head_k"],
                                                                                 x, z)))
    ins = None
    for sx in (-1, 1):
        xf = sx * (x1 + h["boss_t"])
        s = xcyl(INSERT_M4["od"] - 0.4, xf, xf - sx * INSERT_M4["l"], h["axis_y"], 0.0)
        ins = s if ins is None else ins.union(s)
    p["screws"] = (screws, "steel")
    p["inserts"] = (ins, "brass")
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
    bar out to two arms that drop to the tilt axis, each with an M4 clearance hole and a gusset inside its root
    (tightening a tilt knob bends the arm in by ARM_GAP, which puts the root's layers in tension)."""
    half, _ = head_spec(kind)
    depth = tilt_depth(kind)
    a0, a1 = half + ARM_GAP, half + ARM_GAP + ARM_T
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
        xi = sx * a0                                     # the arm's inner face
        g = GUSSET
        gus = (cq.Workplane("XZ").polyline([(xi, -t + 0.01), (xi - sx * g, -t + 0.01), (xi, -t - g)]).close()
               .extrude(bw / 2 - 2.0, both=True))
        y = y.union(arm).union(gus)
        y = y.cut(xcyl(TILT["clear"], x0 - 1, x0 + ARM_T + 1, 0.0, -depth))
    y = y.cut(cyl(STUD["clear"], t + 2, z=-t - 1))
    y = y.cut(cyl(STUD["weld_d"], STUD["weld_h"], z=-STUD["weld_h"]))
    return y


def stud_knob_part():
    """Thumb nut in its print frame: the face against the yoke's pad on top (z = KNOB['h']), with the crush-rib pocket
    for the M6 nut opening there, so it prints without supports. The nut stands proud of the face, so it, not the
    knob, clamps the washer and pad; the knob only turns it."""
    k = KNOB
    knob = cyl(k["d"], k["h"])
    for i in range(k["flutes"]):
        a = 2 * math.pi * i / k["flutes"]
        knob = knob.cut(cyl(6.0, k["h"] + 2, x=(k["d"] / 2 + 1.2) * math.cos(a), y=(k["d"] / 2 + 1.2) * math.sin(a),
                            z=-1))
    knob = knob.faces("<Z").edges().chamfer(0.4)               # no elephant's foot on the grip
    knob = knob.cut(cyl(STUD["clear"], k["h"] + 2, z=-1))
    return knob.cut(rib_hex_pocket(NUT_POCKET, k["h"]))


def stud_knob():
    """Thumb nut, mount frame: below the washer under the pad."""
    return stud_knob_part().translate((0, 0, -PAD["t"] - WASHER_M6["t"] - KNOB["h"] + nut_proud()))


def nut_proud():
    """How far the nominal M6 nut stands above the thumb nut's face."""
    return 0.5 * (NUT_M6["m_max"] + NUT_M6["m_min"]) - NUT_POCKET["depth"]


def tilt_knob_part():
    """Tilt knob in its print frame: the face against the yoke's arm on the bed (z = 0), the crush-rib pocket for the
    M4 bolt's head opening on top, with a recess under it for an M4 washer that spreads the clamp load."""
    k, hp = TILT, HEAD_POCKET
    knob = cyl(k["knob_d"], k["knob_h"])
    for i in range(8):
        a = 2 * math.pi * i / 8
        knob = knob.cut(cyl(5.0, k["knob_h"] + 2, x=(k["knob_d"] / 2 + 1.0) * math.cos(a),
                            y=(k["knob_d"] / 2 + 1.0) * math.sin(a), z=-1))
    knob = knob.faces("<Z").edges().chamfer(0.4)
    knob = knob.cut(cyl(TILT["clear"], k["knob_h"] + 2, z=-1))
    z_hex = k["knob_h"] - hp["depth"]
    knob = knob.cut(cyl(hp["washer_d"], hp["washer_t"] + 0.01, z=z_hex - hp["washer_t"]))
    return knob.cut(rib_hex_pocket(hp, k["knob_h"]))


def tilt_stack(kind):
    """x positions (+ side; the - side mirrors) along the tilt axis: boss face, arm inner and outer faces, the knob's
    outer face, the bolt head's bearing face and its tip. The arm closes the ARM_GAP when the knob is tightened."""
    half, _ = head_spec(kind)
    a0 = half + ARM_GAP
    a1 = a0 + ARM_T
    k1 = a1 + TILT["knob_h"]
    bear = k1 - HEAD_POCKET["depth"] - WASHER_M4["t"]          # under-head face, on the washer
    return dict(boss=half, arm0=a0, arm1=a1, knob1=k1, bear=bear, tip=bear - BOLT_M4["l"])


def bolt_m4(x_bear, x_tip, y=0.0, z=0.0):
    """ISO 4017 M4 hex bolt along x: bearing face at x_bear, tip at x_tip."""
    sx = 1 if x_bear > x_tip else -1
    k = 0.5 * (BOLT_M4["k_max"] + BOLT_M4["k_min"])
    shank = xcyl(4.0, x_tip, x_bear, y, z)
    head = (cq.Workplane("YZ").polygon(6, 7.0 / math.cos(math.pi / 6)).extrude(k)
            .translate((x_bear if sx > 0 else x_bear - k, y, z)))
    return shank.union(head)


def tilt_knobs(kind):
    """Two tilt knobs with their bolts and washers, mount frame, outside the yoke's arms on the tilt axis.
    Returns (knobs, steel: bolts and washers)."""
    depth = tilt_depth(kind)
    s = tilt_stack(kind)
    out, steel = None, None
    for sx in (-1, 1):
        k = tilt_knob_part().rotate((0, 0, 0), (0, 1, 0), 90 * sx)    # knob z -> +x on the + side
        k = k.translate((s["arm1"] * sx, 0.0, -depth))
        out = k if out is None else out.union(k)
        b = bolt_m4(s["bear"] * sx, s["tip"] * sx, 0.0, -depth)
        w = xcyl(WASHER_M4["d_out"], sx * s["bear"], sx * (s["bear"] - WASHER_M4["t"]), 0.0, -depth).cut(
            xcyl(WASHER_M4["d_in"], sx * (s["bear"] + 1), sx * (s["bear"] - WASHER_M4["t"] - 1), 0.0, -depth))
        b = b.union(w)
        steel = b if steel is None else steel.union(b)
    return out, steel


def ceiling_stud():
    """The welded stud with its weld bead, the M6 washer under the pad, and the M6 nut, mount frame."""
    stud = cyl(STUD["d"], STUD["length"], z=-STUD["length"])
    bead = cyl(STUD["weld_d"] - 3.0, STUD["weld_h"] - 0.3, z=-(STUD["weld_h"] - 0.3))
    zw = -PAD["t"] - WASHER_M6["t"]
    washer = cyl(WASHER_M6["d_out"], WASHER_M6["t"], z=zw).cut(cyl(WASHER_M6["d_in"], 4, z=zw - 1))
    m = 0.5 * (NUT_M6["m_max"] + NUT_M6["m_min"])
    nut = hex_prism(10.0, zw - m, zw).cut(cyl(STUD["d"], m + 2, z=zw - m - 1))
    return stud.union(bead).union(washer).union(nut)


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
    """{piece: {name: (Workplane, material)}} with pieces 'fixed' (stud, washer, nut), 'pan' (yoke, knobs) and 'head',
    each in its own frame: fixed and pan in the mount frame at pan 0, head in the head frame."""
    knobs, bolts = tilt_knobs(kind)
    head = head_zero_parts() if kind == "zero" else head_hq_parts(wide=wide)
    return {"fixed": {"ceiling stud": (ceiling_stud(), "steel")},
            "pan": {"yoke": (yoke(kind), "petg"), "stud thumb nut": (stud_knob(), "knob"),
                    "tilt knobs": (knobs, "knob"), "tilt bolts": (bolts, "steel")},
            "head": head}


COLOURS = dict(petg=(0.15, 0.16, 0.17), knob=(0.85, 0.42, 0.10), steel=(0.75, 0.77, 0.80), brass=(0.80, 0.62, 0.25),
               pcb=(0.12, 0.48, 0.24), lens=(0.08, 0.08, 0.09), glass=(0.30, 0.45, 0.65), white=(0.93, 0.93, 0.93),
               port=(0.70, 0.72, 0.75), black=(0.1, 0.1, 0.1), cooler=(0.55, 0.58, 0.62), ribbon=(0.85, 0.65, 0.25))


def assembly(kind, pan=0.0, tilt=45.0, wide=True):
    """CadQuery Assembly at a pose, mount frame."""
    depth = tilt_depth(kind)
    pc = parts(kind, wide)
    asm = cq.Assembly(name=f"stud_mount_{kind}")
    rz = cq.Location(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), pan)
    for name, (s, m) in pc["fixed"].items():
        asm.add(s, name=name, color=cq.Color(*COLOURS[m]))
    for name, (s, m) in pc["pan"].items():
        asm.add(s, name=name, loc=rz, color=cq.Color(*COLOURS[m]))
    head_loc = rz * cq.Location(cq.Vector(0, 0, -depth)) * cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), tilt)
    for name, (s, m) in pc["head"].items():
        asm.add(s, name=name.replace(" ", "_"), loc=head_loc, color=cq.Color(*COLOURS[m]))
    return asm


def on_bed(shape, steps):
    """`shape` rotated by `steps` [(axis, degrees)] and moved so it sits on z = 0, centred in x and y."""
    s = _rot(shape, steps)
    bb = s.val().BoundingBox()
    return s.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))


X, Y = (1, 0, 0), (0, 1, 0)
# Printed parts in their print orientation (on the bed at z = 0), chosen so none needs support: yokes on the face
# that meets the ceiling, heads on their front faces, the back cover and carrier with their posts up, the Wide's
# nose on its side strip, knobs on the face that meets the yoke (the thumb nut on its grip face, pocket up).
PRINTED = {
    "zero": {"yoke_zero": lambda: on_bed(yoke("zero"), [(X, 180)]),
             "head_zero_case": lambda: on_bed(head_zero_parts()["case"][0], [(X, 90)]),
             "head_zero_back_cover": lambda: on_bed(head_zero_parts()["back cover"][0], [(X, -90)])},
    "hq": {"yoke_hq": lambda: on_bed(yoke("hq"), [(X, 180)]),
           "head_hq_frame": lambda: on_bed(head_hq_parts()["frame"][0], [(X, 90)]),
           "head_hq_pi_carrier": lambda: on_bed(head_hq_parts()["Pi carrier"][0], [(X, 90)]),
           "head_hq_wide_nose": lambda: on_bed(head_hq_parts()["Wide nose"][0], [(Y, 90)])},
    "common": {"stud_thumb_nut": stud_knob_part, "tilt_knob": tilt_knob_part},
}
# copies of each printed part per mount
PER_MOUNT = {"yoke_zero": 1, "head_zero_case": 1, "head_zero_back_cover": 1, "yoke_hq": 1, "head_hq_frame": 1,
             "head_hq_pi_carrier": 1, "head_hq_wide_nose": 1, "stud_thumb_nut": 1, "tilt_knob": 2}


if __name__ == "__main__":
    for kind in ("zero", "hq"):
        print(kind, "swing radius %.1f, behind %.1f, tilt-axis depth %d mm, lens %s, stack %s" % (
            swing_radius(kind), swing_radius_behind(kind), tilt_depth(kind),
            tuple(round(c, 1) for c in lens_point(kind)), {k: round(v, 2) for k, v in tilt_stack(kind).items()}))
