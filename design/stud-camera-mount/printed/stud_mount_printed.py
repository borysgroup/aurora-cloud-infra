"""All-printed variant of the stud pan/tilt camera mount (CadQuery + mesh threads in threads.py).

Same yoke-and-head layout as ../stud_mount.py, with every nut, bolt, washer, heat-set insert, standoff and screw
replaced by a printed feature. The only metal left is the glovebox's welded M6 stud.

  pan    a printed thumb nut with an M6 x 1 internal thread screws straight onto the steel stud and clamps the yoke's
         pad against the ceiling (no nut, no washer)
  tilt   two printed thumb screws, M10 x 1.25, through the yoke's arms into M10 threads printed in the head's bosses
  boards Pi Zero 2 W, Camera Module 3, HQ Camera and Pi 5 sit on printed pegs through their mounting holes; printed
         covers press them onto the pegs. The outermost cover has ears that sit between the yoke's arm and the boss,
         so the two tilt screws also hold the covers on: no clips, no glue.

Threads are modelled as plain cores here (thread_ops() lists them) and cut/added at mesh level when the STLs are
exported (export_printed_stls.py), because that is what the slicer reads.

Frames as in stud_mount.py: mount frame z up from where the stud leaves the ceiling; head frame on the tilt axis,
camera looking along -y at tilt 0.
"""

from __future__ import annotations

import math
import pathlib
import sys

import cadquery as cq

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import stud_mount as sm  # noqa: E402
from stud_mount import (CM3, HQ_BOARD, HQ_CS_SEAT, HQ_PCB_T, HQ_PITCH, LENS_ZOOM, PAD, PI5, PIZ, STUD,  # noqa: E402
                        _hq_tripod_outline, _poly_z, _rot, _strip, _to_head, box, cm3_parts, cyl, hq_camera_parts,
                        pi5_parts, pi_zero_parts, xcyl, ycyl)

# ------------------------------------------------------------------------------------------- threads
# Allowances are radial, per side. Print the fit coupon first and change these if the fit is off.
STUD_THREAD = dict(d=6.0, p=1.0, allowance=0.20, entry_chamfer=0.8)      # PLA nut on the steel M6 stud (6g)
TILT_THREAD = dict(d=10.0, p=1.25, ext_allowance=0.15, int_allowance=0.15, entry_chamfer=0.6)  # M10 x 1.25 fine


def _minor(d, p):
    return d - 1.22687 * p


# Plain cores in the CadQuery solids, 0.1 mm inside the thread's own minor diameter so the mesh booleans never meet a
# coincident surface: holes are a little smaller than the tap's crest, shanks a little thinner than the thread's root.
STUD_CORE = _minor(STUD_THREAD["d"], STUD_THREAD["p"]) + 2 * STUD_THREAD["allowance"] - 0.1   # PLA thread crest 5.17
TILT_CORE_INT = _minor(TILT_THREAD["d"], TILT_THREAD["p"]) + 2 * TILT_THREAD["int_allowance"] - 0.1
TILT_CORE_EXT = _minor(TILT_THREAD["d"], TILT_THREAD["p"]) - 2 * TILT_THREAD["ext_allowance"] - 0.1
TILT_MAJOR_EXT = TILT_THREAD["d"] - 2 * TILT_THREAD["ext_allowance"]

# ---------------------------------------------------------------------------------------- parameters
KNOB = dict(d=34.0, h=13.0, flutes=10)                   # stud thumb nut, threaded right through
# Tilt thumb screw: knurled knob + M10 x 1.25 shank threaded to the knob. Shank = arm-to-boss gap + arm + cover ear + engage.
TSCREW = dict(knob_d=24.0, knob_h=9.0, engage=10.0, bottom=1.0, root_fillet=1.0)
ARM_T = 5.0
ARM_GAP = 0.3                                            # each side, boss face to arm, closed by the clamp
ARM_HOLE = 10.8                                          # clearance for the printed M10 (9.7 mm major)
SWING_CLEAR = 3.0
PEG = dict(cm3_d=2.15, cm3_shoulder=3.8, pi_d=2.5, post_d=4.4, socket_d=2.75, socket_extra=0.3, tip=0.4)

ZP = dict(sm.ZERO)                                       # Pi Zero head: the hardware version's case, plus
ZP.update(boss_d=18.0, boss_t=12.0, ear_t=2.5, ear_r=9.0, peg_top=10.0, pi_peg_up=1.8, pillar_d=4.6)
HP = dict(sm.HQ)                                         # HQ head
HP.update(boss_d=20.0, boss_t=9.0, ear_t=2.5, ear_r=10.0, cheek_t=5.0, hq_post_d=5.0, hq_peg_up=1.8,
          pi_post_d=5.0, pi_peg_up=1.8, pi_pillar_d=4.6, retainer_t=3.0)


def ears(kind):
    """Thickness of the ear between the arm and the boss: the back cover's on the Pi Zero head, the Pi 5 retainer's on
    the HQ head."""
    return ZP["ear_t"] if kind == "zero" else HP["ear_t"]


def screw_len(kind):
    """Shank length from the knob's bearing face: arm + open gap + ears + engagement."""
    return ARM_T + ARM_GAP + ears(kind) + TSCREW["engage"]


def hole_depth():
    """Blind M10 hole in the boss: the engagement plus the gap that closes when clamped, plus room at the bottom."""
    return TSCREW["engage"] + ARM_GAP + TSCREW["bottom"]


# ------------------------------------------------------------------------------------- Pi Zero head
def _zero_case_frame():
    """Pi Zero case, its own frame (front face y = 0). Returns (case, back cover, thread ops in this frame)."""
    h = ZP
    a, zm, pt, ct = h["half"], h["zmax"], h["plate_t"], h["cheek_t"]
    ay, bd, bt, b0, b1 = h["axis_y"], h["boss_d"], h["boss_t"], h["back"][0], h["back"][1]
    case = box(-a - ct, 0, -zm, a + ct, pt, zm).edges("|Y").fillet(3.0)
    case = case.union(box(-a - ct, pt, -zm, -a, b0, zm)).union(box(a, pt, -zm, a + ct, b0, zm))
    ops = []
    for sx in (-1, 1):
        x0 = a + ct if sx > 0 else -a - ct - bt
        boss = xcyl(bd, x0, x0 + bt, ay, 0.0).union(box(x0, 0.0, -bd / 2, x0 + bt, ay, bd / 2))
        boss = boss.cut(box(x0 - 1, b0, -bd, x0 + bt + 1, b0 + bd, bd))            # room for the cover's wing
        case = case.union(boss)
        xo = a + ct + bt if sx > 0 else -a - ct - bt                                # boss's outer face
        depth = hole_depth()
        case = case.cut(xcyl(TILT_CORE_INT, xo + sx * 1.0, xo - sx * depth, ay, 0.0))
        ops.append(dict(kind="tap", thread="tilt", origin=(xo, ay, 0.0), axis=(-sx, 0, 0), length=depth, blind=True,
                        part="case"))
    lx, lz = h["lens_x"], h["lens_z"]
    case = case.cut(box(lx - 5.0, -1, lz - 5.0, lx + 5.0, pt + 1, lz + 5.0))         # lens window
    case = case.cut(box(a - 1, h["pi_y"] - 1, -6.0, a + ct, b0 + 1, 6.0))           # microSD clearance
    # Camera Module 3: shoulders (the 1.5 mm gap) and long pegs through its four holes, so it stays captive between
    # the front plate and the Pi even if the light press fit lets go
    for sx in (-1, 1):
        for dz in (CM3["lens_from_top"] - 2.0, CM3["lens_from_top"] - 14.5):
            x, z = lx + sx * 10.5, lz + dz
            case = case.union(ycyl(PEG["cm3_shoulder"], pt - 0.5, pt + h["cm3_gap"], x, z))
            case = case.union(ycyl(PEG["cm3_d"], pt, h["peg_top"], x, z))
    # Pi Zero: posts up to its underside, pegs through its holes
    for u, v in PIZ["holes"]:
        x, z = PIZ["w"] / 2 - u, v - PIZ["h"] / 2
        case = case.union(ycyl(PEG["post_d"], pt - 0.5, h["pi_y"], x, z))
        case = case.union(ycyl(PEG["pi_d"], h["pi_y"] - 0.5, h["pi_y"] + PIZ["t"] + h["pi_peg_up"], x, z))
    # back cover: plate, vents, pillars that press the Pi onto its posts (sockets for the peg tips), and wings out to
    # ears that sit on the bosses' outer faces under the yoke's arms
    back = box(-a - ct, b0, -zm, a + ct, b1, zm).edges("|Y").fillet(3.0)
    for i in range(5):
        back = back.cut(box(-20 + i * 10, b0 - 1, -8, -16 + i * 10, b1 + 1, 8))
    pi_back = h["pi_y"] + PIZ["t"]
    for u, v in PIZ["holes"]:
        x, z = PIZ["w"] / 2 - u, v - PIZ["h"] / 2
        back = back.union(ycyl(h["pillar_d"], pi_back, b0 + 0.5, x, z))
        back = back.cut(ycyl(PEG["socket_d"], pi_back - 1, pi_back + h["pi_peg_up"] + PEG["socket_extra"], x, z))
    er, et = h["ear_r"], h["ear_t"]
    for sx in (-1, 1):
        xo = a + ct + bt
        wing = box(a + ct - 0.5, b0, -er, xo + et, b1, er)
        ear = box(xo, 0.5, -er, xo + et, b1, er).edges("|X").fillet(2.0)
        w = wing.union(ear)
        if sx < 0:
            w = w.mirror("YZ")
        back = back.union(w)
        back = back.cut(xcyl(ARM_HOLE, sx * (xo - 1), sx * (xo + et + 1), ay, 0.0))
    return case, back, ops


def head_zero_parts():
    """Pi Zero 2 W + Camera Module 3 head, head frame (as stud_mount.head_zero_parts, all printed)."""
    h = ZP
    case, back, _ = _zero_case_frame()
    p = {"case": (case, "petg"), "back cover": (back, "petg")}
    lx, lz = h["lens_x"], h["lens_z"]
    cam_at = (lx, h["plate_t"] + h["cm3_gap"], lz)
    for name, (s, m) in cm3_parts(wide=False).items():
        p[name] = (_to_head(s, cam_at), m)
    pi_at = (PIZ["w"] / 2, h["pi_y"], -PIZ["h"] / 2)
    for name, (s, m) in pi_zero_parts().items():
        p[name] = (_to_head(s, pi_at), m)
    cy = h["plate_t"] + h["cm3_gap"] + CM3["pcb_t"] + 1.5
    zm = h["zmax"]
    p["ribbon"] = (_strip([(cy, lz - 9.0), (cy, -zm + 2.5), (h["pi_y"] - 1.2, -zm + 2.5), (h["pi_y"] - 1.2, -6.0)],
                          x=-21.0, w=11.0), "ribbon")
    p["USB power lead"] = (ycyl(4.0, h["pi_y"] + 2.0, h["pi_y"] + 2.1, -21.5, -zm).union(
        cyl(4.0, 40.0, x=-21.5, y=h["pi_y"] + 3.5, z=-zm - 40.0)), "black")
    ay = h["axis_y"]
    return {n: (s.translate((0, -ay, 0)), m) for n, (s, m) in p.items() if s is not None}


# ------------------------------------------------------------------------------------------ HQ head
def _hq_frame():
    """HQ head printed parts in the case frame (front face y = 0). One clamp chain, closed by the two tilt screws:

      Pi 5 retainer (ears under the yoke's arms) -> its pillars -> Pi 5 -> carrier posts -> carrier -> HQ retainer
      -> its pillars -> HQ Camera board -> tub posts -> tub (camera plate, cheeks, threaded bosses)

    The carrier sits on two pins on the tub's cheeks; pegs through every board hole locate the boards. Each part has
    all its features on one side, so each prints flat without supports. Returns (parts, thread ops, positions)."""
    h = HP
    x0, x1, z0, z1 = h["plate"]
    pt, ay, ct = h["plate_t"], h["axis_y"], h["cheek_t"]
    bd, bt, er, et = h["boss_d"], h["boss_t"], h["ear_r"], h["ear_t"]
    cy0 = h["pi_carrier_y"]                                  # carrier front face
    cy1 = cy0 + 4.0
    hq_at = (h["hq_x"], pt + h["hq_standoff"], 0.0)
    # tub: plate with the lens-mount opening, cheeks, bosses with blind M10 threads
    tub = box(x0, 0, z0, x1, pt, z1).edges("|Y").fillet(4.0)
    tub = tub.cut(cq.Workplane("XZ").circle(37.0 / 2).extrude(-pt - 2).translate((h["hq_x"], -1, 0)))
    foot = _to_head(_poly_z(_hq_tripod_outline(), -10.35 - 1, 2.0), hq_at)
    lock = _to_head(box(-6.1, 15.0, -10.35 - 1, 6.1, 22.6, 2.0), hq_at)
    tub = tub.cut(foot).cut(lock)
    tub = tub.union(box(x0, pt, z0, x0 + ct, cy0, z1)).union(box(x1 - ct, pt, z0, x1, cy0, z1))
    pins = [(sx * (x1 - ct / 2), sz * (z1 - 6.0)) for sx in (-1, 1) for sz in (-1, 1)]
    for x, z in pins:                                        # locating pins for the carrier
        tub = tub.union(ycyl(3.6, cy0 - 0.5, cy0 + 3.0, x, z))
    ops = []
    for sx in (-1, 1):
        xb = x1 if sx > 0 else x0 - bt
        boss = xcyl(bd, xb, xb + bt, ay, 0.0).union(box(xb, 0.0, -bd / 2, xb + bt, ay, bd / 2))
        tub = tub.union(boss)
        xo = x1 + bt if sx > 0 else x0 - bt
        depth = hole_depth()
        tub = tub.cut(xcyl(TILT_CORE_INT, xo + sx * 1.0, xo - sx * depth, ay, 0.0))
        ops.append(dict(kind="tap", thread="tilt", origin=(xo, ay, 0.0), axis=(-sx, 0, 0), length=depth, blind=True,
                        part="tub"))
    # HQ Camera: posts (the old 4 mm standoffs) and pegs through its M2.5 holes
    hq_back = pt + h["hq_standoff"] + HQ_PCB_T
    hq_holes = [(h["hq_x"] + sx * HQ_PITCH / 2, sz * HQ_PITCH / 2) for sx in (-1, 1) for sz in (-1, 1)]
    for x, z in hq_holes:
        tub = tub.union(ycyl(h["hq_post_d"], pt - 0.5, pt + h["hq_standoff"], x, z))
        tub = tub.union(ycyl(PEG["pi_d"], pt + h["hq_standoff"] - 0.5, hq_back + h["hq_peg_up"], x, z))
    # HQ retainer: a frame behind the HQ board, pillars onto its hole rings (sockets for the peg tips); the carrier's
    # front face pushes it forward. 0.2 mm longer than the gap so the chain is preloaded.
    rt = 3.0
    hqr = box(h["hq_x"] - 19, cy0 - rt, -19, h["hq_x"] + 19, cy0 + 0.2, 19).edges("|Y").fillet(3.0)
    hqr = hqr.cut(box(h["hq_x"] - 11, cy0 - rt - 1, -11, h["hq_x"] + 11, cy0 + 1, 11))
    for x, z in hq_holes:
        hqr = hqr.union(ycyl(4.6, hq_back, cy0 - rt + 0.5, x, z))
        hqr = hqr.cut(ycyl(PEG["socket_d"], hq_back - 1, hq_back + h["hq_peg_up"] + PEG["socket_extra"], x, z))
    hqr = hqr.translate((0, -0.2, 0))
    # carrier: plate on the tub's pins, posts and pegs for the Pi 5 on its back
    carrier = box(x0, cy0, z0 - 4, x1, cy1, z1 + 4).edges("|Y").fillet(4.0)
    for x, z in pins:
        carrier = carrier.cut(ycyl(4.0, cy0 - 1, cy0 + 3.4, x, z))
    pi_y = cy1 + h["pi_standoff"]
    pi_holes = [(PI5["w"] / 2 - u, v - PI5["h"] / 2) for u, v in PI5["holes"]]
    for x, z in pi_holes:
        carrier = carrier.union(ycyl(h["pi_post_d"], cy1 - 0.5, pi_y, x, z))
        carrier = carrier.union(ycyl(PEG["pi_d"], pi_y - 0.5, pi_y + PI5["t"] + h["pi_peg_up"], x, z))
    # Pi 5 retainer: a frame behind the Pi 5 (clear of the Active Cooler and the ports), pillars onto its four hole
    # rings, and ears forward to the bosses, under the yoke's arms
    pi_back = pi_y + PI5["t"]
    ry0 = pi_back + 17.0                                     # behind the tallest port (16 mm)
    ry1 = ry0 + h["retainer_t"]
    xs = sorted({x for x, _ in pi_holes})
    zs = sorted({z for _, z in pi_holes})
    ret = None
    for x in xs:
        bar = box(x - 3.0, ry0, zs[0] - 3.0, x + 3.0, ry1, zs[1] + 3.0)
        ret = bar if ret is None else ret.union(bar)
    xo = x1 + bt                                             # boss's outer face
    ret = ret.union(box(-(xo + et), ry0, -er, xo + et, ry1, er))
    for x, z in pi_holes:
        ret = ret.union(ycyl(4.6, pi_back, ry0 + 0.5, x, z))
        ret = ret.cut(ycyl(PEG["socket_d"], pi_back - 1, pi_back + h["pi_peg_up"] + PEG["socket_extra"], x, z))
    for sx in (-1, 1):
        ear = box(xo, ay - er, -er, xo + et, ry1, er).edges("|X").fillet(2.0)
        if sx < 0:
            ear = ear.mirror("YZ")
        ret = ret.union(ear)
        ret = ret.cut(xcyl(ARM_HOLE, sx * (xo - 1), sx * (xo + et + 1), ay, 0.0))
    # Wide nose: shoulders and pegs for the Wide's four holes instead of M2 screws
    wx0, wx1 = h["wide_x"] - 14.0, h["wide_x"] + 18.0
    ny, wz = h["nose_y"], h["wide_z"]
    nose = box(wx0, ny, wz - 16, wx1, ny + 5, wz + 16)
    nose = nose.cut(box(h["wide_x"] - 5.7, ny - 1, wz - 5.7, h["wide_x"] + 5.7, ny + 6, wz + 5.7))
    nose = nose.union(box(wx0, ny, wz - 20, wx1, 0, wz - 16))
    nose = nose.union(box(wx1 - 4, ny + 5, wz - 16, wx1, 0, wz + 8))
    for sx in (-1, 1):
        for dz in (CM3["lens_from_top"] - 2.0, CM3["lens_from_top"] - 14.5):
            x, z = h["wide_x"] + sx * 10.5, wz + dz
            nose = nose.union(ycyl(PEG["cm3_shoulder"], ny + 4.5, ny + 5 + 2.5, x, z))
            nose = nose.union(ycyl(PEG["cm3_d"], ny + 5, ny + 5 + 2.5 + CM3["pcb_t"] + 1.6, x, z))
    parts = {"tub": tub, "HQ retainer": hqr, "carrier": carrier, "Pi 5 retainer": ret, "Wide nose": nose}
    return parts, ops, dict(hq_at=hq_at, pi_y=pi_y, ry1=ry1)


def head_hq_parts(wide=True):
    h = HP
    pr, _, at = _hq_frame()
    p = {n: (pr[n], "petg") for n in ("tub", "HQ retainer", "carrier", "Pi 5 retainer")}
    for name, (s, m) in hq_camera_parts().items():
        p[name] = (_to_head(s, at["hq_at"]), m)
    pi_at = (PI5["w"] / 2, at["pi_y"], -PI5["h"] / 2)
    for name, (s, m) in pi5_parts().items():
        p[name] = (_rot(s, [((1, 0, 0), -90), ((0, 1, 0), 180)]).translate(pi_at), m)
    if wide:
        p["Wide nose"] = (pr["Wide nose"], "petg")
        wide_at = (h["wide_x"], h["nose_y"] + 5 + 2.5, h["wide_z"])
        for name, (s, m) in cm3_parts(wide=True).items():
            p[name] = (_to_head(s, wide_at), m)
    ay = h["axis_y"]
    return {n: (s.translate((0, -ay, 0)), m) for n, (s, m) in p.items() if s is not None}


# ----------------------------------------------------------------------------- yoke, knobs, stud
def head_half(kind):
    if kind == "zero":
        return ZP["half"] + ZP["cheek_t"] + ZP["boss_t"] + ZP["ear_t"]
    return HP["plate"][1] + HP["boss_t"] + HP["ear_t"]


_SWING: dict = {}


def _radius(kind, behind_only):
    key = (kind, behind_only)
    if key not in _SWING:
        parts = head_zero_parts() if kind == "zero" else head_hq_parts()
        r = 0.0
        for name, (s, _) in parts.items():
            if "lead" in name:
                continue
            for sol in s.vals():
                verts, _ = sol.tessellate(0.5)
                for v in verts:
                    if behind_only and v.y <= -12.0:
                        continue
                    r = max(r, math.hypot(v.y, v.z))
        _SWING[key] = r
    return _SWING[key]


def tilt_depth(kind):
    top = max(PAD["t"] + KNOB["h"], STUD["length"])
    r = _radius(kind, kind != "zero")
    return math.ceil(top + SWING_CLEAR + r)


def yoke(kind):
    """As stud_mount.yoke, with M10 clearance holes in the arms and the arms moved out to the wider head."""
    half = head_half(kind)
    depth = tilt_depth(kind)
    a0, a1 = half + ARM_GAP, half + ARM_GAP + ARM_T
    t, bw = PAD["t"], PAD["bar_w"]
    y = cyl(PAD["d"], t, z=-t).union(box(-a1, -bw / 2, -t, a1, bw / 2, 0).edges("|Z").fillet(3.0))
    br = 11.0
    for sx in (-1, 1):
        x0 = a0 if sx > 0 else -a1
        prof = [(-bw / 2, 0.0), (bw / 2, 0.0), (br, -depth), (-br, -depth)]
        arm = cq.Workplane("YZ").polyline(prof).close().extrude(ARM_T).translate((x0, 0, 0))
        arm = arm.union(xcyl(2 * br, x0, x0 + ARM_T, 0.0, -depth))
        y = y.union(arm)
        y = y.cut(xcyl(ARM_HOLE, x0 - 1, x0 + ARM_T + 1, 0.0, -depth))
    y = y.cut(cyl(STUD["clear"], t + 2, z=-t - 1))
    y = y.cut(cyl(STUD["weld_d"], STUD["weld_h"], z=-STUD["weld_h"]))
    return y


def stud_knob():
    """Thumb nut, mount frame: knurled disc with an M6 x 1 thread right through (cut at export), its top face
    clamping the yoke's pad."""
    k = KNOB
    ztop = -PAD["t"]
    z0 = ztop - k["h"]
    knob = cyl(k["d"], k["h"], z=z0)
    for i in range(k["flutes"]):
        a = 2 * math.pi * i / k["flutes"]
        knob = knob.cut(cyl(6.0, k["h"] + 2, x=(k["d"] / 2 + 1.2) * math.cos(a), y=(k["d"] / 2 + 1.2) * math.sin(a),
                            z=z0 - 1))
    knob = knob.edges(">Z or <Z").chamfer(0.6)
    return knob.cut(cyl(STUD_CORE, k["h"] + 2, z=z0 - 1))


def stud_knob_ops():
    """The stud nut's thread: entry at the top face (the stud comes down into it)."""
    return [dict(kind="tap", thread="stud", origin=(0.0, 0.0, -PAD["t"]), axis=(0, 0, -1), length=KNOB["h"],
                 blind=False, part="stud thumb nut")]


def tilt_screw_local(kind):
    """One thumb screw, its own frame: knob from z = -knob_h to 0 (bearing face at z = 0), shank core along +z."""
    t = TSCREW
    knob = cyl(t["knob_d"], t["knob_h"], z=-t["knob_h"])
    for i in range(8):
        a = 2 * math.pi * i / 8
        knob = knob.cut(cyl(5.0, t["knob_h"] + 2, x=(t["knob_d"] / 2 + 1.0) * math.cos(a),
                            y=(t["knob_d"] / 2 + 1.0) * math.sin(a), z=-t["knob_h"] - 1))
    knob = knob.edges("<Z").chamfer(0.6)
    root = cq.Workplane("XY").circle(TILT_CORE_EXT / 2 + t["root_fillet"]).workplane(offset=t["root_fillet"]) \
        .circle(TILT_CORE_EXT / 2).loft()
    core = cyl(TILT_CORE_EXT, screw_len(kind))
    return knob.union(root).union(core)


def tilt_screw_ops_local(kind):
    return [dict(kind="external", thread="tilt", origin=(0.0, 0.0, 0.0), axis=(0, 0, 1), length=screw_len(kind),
                 part="tilt screw")]


def tilt_screws(kind):
    """Both thumb screws in the mount frame (pan 0), knobs outside the arms."""
    half = head_half(kind)
    depth = tilt_depth(kind)
    a1 = half + ARM_GAP + ARM_T
    out = None
    for sx in (-1, 1):
        s = tilt_screw_local(kind)
        s = s.rotate((0, 0, 0), (0, 1, 0), -90 * sx).translate((sx * a1, 0, -depth))
        out = s if out is None else out.union(s)
    return out


# ----------------------------------------------------------------------------------------- assembly
def parts(kind, wide=True):
    head = head_zero_parts() if kind == "zero" else head_hq_parts(wide=wide)
    return {"fixed": {"ceiling stud": (sm.ceiling_stud(), "steel")},
            "pan": {"yoke": (yoke(kind), "petg"), "stud thumb nut": (stud_knob(), "knob"),
                    "tilt screws": (tilt_screws(kind), "knob")},
            "head": head}


def assembly(kind, pan=0.0, tilt=45.0, wide=True):
    colours = dict(petg=(0.15, 0.16, 0.17), knob=(0.85, 0.42, 0.10), steel=(0.75, 0.77, 0.80),
                   pcb=(0.12, 0.48, 0.24), lens=(0.08, 0.08, 0.09), glass=(0.30, 0.45, 0.65),
                   white=(0.93, 0.93, 0.93), port=(0.70, 0.72, 0.75), black=(0.1, 0.1, 0.1),
                   cooler=(0.55, 0.58, 0.62), ribbon=(0.85, 0.65, 0.25))
    depth = tilt_depth(kind)
    pc = parts(kind, wide)
    asm = cq.Assembly(name=f"stud_mount_printed_{kind}")
    rz = cq.Location(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), pan)
    for name, (s, m) in pc["fixed"].items():
        asm.add(s, name=name.replace(" ", "_"), color=cq.Color(*colours[m]))
    for name, (s, m) in pc["pan"].items():
        asm.add(s, name=name.replace(" ", "_"), loc=rz, color=cq.Color(*colours[m]))
    head_loc = rz * cq.Location(cq.Vector(0, 0, -depth)) * cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), tilt)
    for name, (s, m) in pc["head"].items():
        asm.add(s, name=name.replace(" ", "_"), loc=head_loc, color=cq.Color(*colours[m]))
    return asm


def head_thread_ops(kind):
    """Thread ops of the head's printed parts in the head frame."""
    if kind == "zero":
        _, _, ops = _zero_case_frame()
        ay = ZP["axis_y"]
    else:
        _, ops, _ = _hq_frame()
        ay = HP["axis_y"]
    return [dict(o, origin=(o["origin"][0], o["origin"][1] - ay, o["origin"][2])) for o in ops]


if __name__ == "__main__":
    for kind in ("zero", "hq"):
        print(kind, "half %.1f, swing %.1f, tilt-axis depth %d mm, screw %.1f mm, hole %.1f mm" % (
            head_half(kind), _radius(kind, kind != "zero"), tilt_depth(kind), screw_len(kind), hole_depth()))
