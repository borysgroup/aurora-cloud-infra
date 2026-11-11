"""Stud pan/tilt camera mount: printed parts plus the COMRUN M2 and M2.5 black nylon standoff kits (CadQuery + mesh
threads).

The all-printed mount (../printed/) with its boards and covers held by nylon screws, nuts and standoffs from two
350-piece COMRUN kits. Each kit (one M2, one M2.5) has M-F and F-F standoffs 6 / 10 / 15 / 20 mm (25 of each), 50 nuts,
40 washers and pan-head screws 6 / 8 / 12 mm (20 of each). Nylon screws can't cut their own thread in PLA, so every
screw goes into a kit nut or a kit standoff. Each nut sits in a hex pocket or a side slot, so it can't turn.

  pan    printed thumb nut with an M6 x 1 thread on the welded stud (the all-printed mount's part, unchanged)
  tilt   printed M10 x 1.25 thumb screws through the yoke's arms into threads printed in the head's bosses. Nothing
         sits between arm and boss, so the tilt screws clamp only the arms.
  Pi Zero head
    CM3        4 x M2 x 6 from the board's back into M2 nuts in hex pockets in the case's front face
    Pi Zero    4 x M2.5 x 12 from the case's front face (heads in counterbores), through the posts and the board, into
               M2.5 F-F 6 mm standoffs on the board's back, which act as the nuts
    back cover 4 x M2.5 x 6 through the cover into the other ends of the same standoffs
  HQ head
    HQ Camera  4 x M2.5 x 12 from the tub's front face, through the posts and the board, M2.5 nuts on the board's back
    Pi 5       4 x M2.5 x 6 into M2.5 nuts in side slots in the carrier's posts
    carrier    4 x M2.5 x 8 through counterbores into M2.5 nuts in side slots in ribs inside the cheeks
    Wide nose  3 x M2.5 x 8 from inside the tub into M2.5 nuts in side slots in the nose
    Wide       4 x M2 x 8 from the board's back into M2 nuts in hex pockets in the nose's front face

The welded stud is the only metal. Frames as in ../stud_mount.py: mount frame z up from where the stud leaves the
ceiling; head frame on the tilt axis, camera looking along -y at tilt 0.
"""

from __future__ import annotations

import math
import pathlib
import sys

import cadquery as cq

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "printed"))
import stud_mount as sm  # noqa: E402
import stud_mount_printed as spm  # noqa: E402
from stud_mount import (CM3, HQ_BOARD, HQ_CS_SEAT, HQ_PCB_T, HQ_PITCH, LENS_ZOOM, PAD, PI5, PIZ, STUD,  # noqa: E402
                        _hq_tripod_outline, _poly_z, _rot, _strip, _to_head, box, cm3_parts, cyl, hq_camera_parts,
                        pi5_parts, pi_zero_parts, xcyl, ycyl)

# ------------------------------------------------------------------------------------------- kit hardware
# The listing gives no dimensions, so these are ISO 7045 pan heads and ISO 4032 nuts (heads rounded up) and hex
# standoffs as wide across flats as the nuts. Print stl/fit_coupon.stl first; if a nut is loose or tight in its pocket
# change NUT_FIT, if a screw binds change `clear`.
HW = {"M2.5": dict(d=2.5, p=0.45, head_d=5.0, head_k=2.0, nut_af=5.0, nut_m=2.0, standoff_af=5.0, clear=2.9,
                   cbore=5.6),
      "M2": dict(d=2.0, p=0.4, head_d=4.0, head_k=1.6, nut_af=4.0, nut_m=1.6, standoff_af=4.0, clear=2.4, cbore=4.6)}
NUT_FIT = 0.25           # added across flats for a nut's pocket or slot
SLOT_GAP = 0.3           # added to the nut's thickness in a side slot
PAST = 0.2               # a screw ends at least this far past the far face of its nut
KIT = {size: {"screw 6": 20, "screw 8": 20, "screw 12": 20, "nut": 50, "washer": 40, "F-F 6": 25, "F-F 10": 25,
              "F-F 15": 25, "F-F 20": 25, "M-F 6+6": 25, "M-F 10+6": 25, "M-F 15+6": 25, "M-F 20+6": 25}
       for size in HW}
MOUNTS = {"zero": 2, "hq": 1}   # the plates print two Pi Zero mounts and one HQ mount

ZK = dict(spm.ZP)                                         # Pi Zero head: the all-printed case, plus
ZK.update(ear_t=0.0, cm3_gap=2.5, lens_x=-13.0, pi_post_d=5.0, cm3_shoulder=4.2, back=(17.5, 20.5), front_cbore=2.0,
          standoff=6.0)
HK = dict(spm.HP)                                         # HQ head
HK.update(ear_t=0.0, hq_post_d=5.0, hq_standoff=3.2, pi_post_d=8.5, pi_post_top=(6.0, 1.0), pi_roof=1.4,
          wide_shoulder=4.2, carrier_screw=(43.5, 14.0), rib=(4.5, 8.0), carrier_roof=2.5, cbore_floor=1.5,
          wide_slot=(15.0, 30.0, -13.5, -10.5), wide_ribbon_x=22.5, floor=(-25.0, -16.0), nose_roof=3.0,
          nose_screws=((13.0, -18.5, "-z"), (36.0, -18.5, "-z"), (39.0, 4.0, "+x")))
HK["nose_y"] = -(round(HQ_CS_SEAT - HK["plate_t"] - HK["hq_standoff"] + LENS_ZOOM["profile"][-1][1]))  # lens front


# ------------------------------------------------------------------------------------------------ helpers
def yhex(af, y0, y1, x, z, flats="x"):
    """Hexagonal prism along y from y0 to y1, `af` across flats, centred on (x, z). flats="x": two flats normal to x
    (corners on +-z); flats="z": two flats normal to z (corners on +-x)."""
    r = af / math.sqrt(3)
    a0 = 90.0 if flats == "x" else 0.0
    pts = [(r * math.cos(math.radians(a0 + 60 * i)), r * math.sin(math.radians(a0 + 60 * i))) for i in range(6)]
    lo, hi = min(y0, y1), max(y0, y1)
    return cq.Workplane("XZ").polyline(pts).close().extrude(-(hi - lo)).translate((x, lo, z))


def screw(size, L, x, z, y_seat, into):
    """A pan-head screw along y: head bearing on y = y_seat, shank L long going `into` (+1/-1) along y."""
    s = HW[size]
    shank = ycyl(s["d"] - 0.02, y_seat, y_seat + into * L, x, z)
    return shank.union(ycyl(s["head_d"], y_seat, y_seat - into * s["head_k"], x, z))


def nut(size, x, z, y_seat, away, flats="x"):
    """A hex nut on a screw along y, bearing face on y = y_seat, its body going `away` (+1/-1) along y."""
    s = HW[size]
    body = yhex(s["nut_af"], y_seat, y_seat + away * s["nut_m"], x, z, flats)
    return body.cut(ycyl(s["d"], y_seat - away * 1.0, y_seat + away * (s["nut_m"] + 1), x, z))


def standoff_ff(size, L, x, z, y0, flats="x"):
    """A female-female hex standoff along y from y0 to y0 + L."""
    s = HW[size]
    return yhex(s["standoff_af"], y0, y0 + L, x, z, flats).cut(ycyl(s["d"], y0 - 1, y0 + L + 1, x, z))


def nut_pocket(size, x, z, y_seat, y_face, flats="x"):
    """Cutter: hex pocket from a nut's seat (y_seat) out through a face (y_face), the nut going in along y."""
    s = HW[size]
    return yhex(s["nut_af"] + NUT_FIT, y_seat, y_face + math.copysign(1.0, y_face - y_seat), x, z, flats)


def nut_slot(size, x, z, y_seat, away, out, length):
    """Cutter: side slot for a nut: hex pocket on the screw at (x, z), seat on y = y_seat, body going `away` along y,
    and a channel `length` long toward `out` ("+x", "-x", "+z" or "-z") to push the nut in."""
    s = HW[size]
    af = s["nut_af"] + NUT_FIT
    y1 = y_seat + away * (s["nut_m"] + SLOT_GAP)
    lo, hi = min(y_seat, y1), max(y_seat, y1)
    sign = 1.0 if out[0] == "+" else -1.0
    cut = yhex(af, lo, hi, x, z, "x" if out[1] == "z" else "z")
    if out[1] == "z":
        ch = box(x - af / 2, lo, min(z, z + sign * length), x + af / 2, hi, max(z, z + sign * length))
    else:
        ch = box(min(x, x + sign * length), lo, z - af / 2, max(x, x + sign * length), hi, z + af / 2)
    return cut.union(ch)


def seat_for(size, L, y_head, into):
    """Seat of the nut a screw (head on y_head, going `into`) fully engages with PAST to spare: the nut's face toward
    the head."""
    return y_head + into * (L - PAST - HW[size]["nut_m"])


def _union(shapes):
    out = None
    for s in shapes:
        out = s if out is None else out.union(s)
    return out


class Hardware(dict):
    """{group name: [shapes]} plus a parts count: add(group, item, shape)."""

    def __init__(self):
        super().__init__()
        self.count = {}

    def add(self, group, item, shape):
        self.setdefault(group, []).append(shape)
        self.count[item] = self.count.get(item, 0) + 1


# ------------------------------------------------------------------------------------------ Pi Zero head
def _zero_case_frame():
    """Pi Zero case, its own frame (front face y = 0). Returns (case, back cover, thread ops, hardware)."""
    h, m25, m2 = ZK, HW["M2.5"], HW["M2"]
    a, zm, pt, ct = h["half"], h["zmax"], h["plate_t"], h["cheek_t"]
    ay, bd, bt, b0, b1 = h["axis_y"], h["boss_d"], h["boss_t"], h["back"][0], h["back"][1]
    case = box(-a - ct, 0, -zm, a + ct, pt, zm).edges("|Y").fillet(3.0)
    case = case.union(box(-a - ct, pt, -zm, -a, b0, zm)).union(box(a, pt, -zm, a + ct, b0, zm))
    ops = []
    for sx in (-1, 1):
        x0 = a + ct if sx > 0 else -a - ct - bt
        case = case.union(xcyl(bd, x0, x0 + bt, ay, 0.0).union(box(x0, 0.0, -bd / 2, x0 + bt, ay, bd / 2)))
        xo = a + ct + bt if sx > 0 else -a - ct - bt                                # boss's outer face
        depth = spm.hole_depth()
        case = case.cut(xcyl(spm.TILT_CORE_INT, xo + sx * 1.0, xo - sx * depth, ay, 0.0))
        ops.append(dict(kind="tap", thread="tilt", origin=(xo, ay, 0.0), axis=(-sx, 0, 0), length=depth, blind=True,
                        part="case"))
    lx, lz = h["lens_x"], h["lens_z"]
    case = case.cut(box(lx - 5.0, -1, lz - 5.0, lx + 5.0, pt + 1, lz + 5.0))         # lens window
    case = case.cut(box(a - 1, h["pi_y"] - 1, -6.0, a + ct, b0 + 1, 6.0))           # microSD clearance
    hw = Hardware()
    # Camera Module 3: shoulders, M2 x 6 from its back into nuts in pockets in the front face
    cam_back = pt + h["cm3_gap"] + CM3["pcb_t"]
    for sx in (-1, 1):
        for dz in (CM3["lens_from_top"] - 2.0, CM3["lens_from_top"] - 14.5):
            x, z = lx + sx * 10.5, lz + dz
            case = case.union(ycyl(h["cm3_shoulder"], pt - 0.5, pt + h["cm3_gap"], x, z))
            case = case.cut(ycyl(m2["clear"], -1, cam_back, x, z))
            seat = seat_for("M2", 6, cam_back, -1)
            case = case.cut(nut_pocket("M2", x, z, seat, 0.0))
            hw.add("M2 screws, CM3", ("M2", "screw 6"), screw("M2", 6, x, z, cam_back, -1))
            hw.add("M2 nuts, CM3", ("M2", "nut"), nut("M2", x, z, seat, -1))
    # Pi Zero: posts up to its underside, M2.5 x 12 from counterbores in the front face, F-F standoffs on its back
    pi_back = h["pi_y"] + PIZ["t"]
    cb = h["front_cbore"]
    assert abs(pi_back + h["standoff"] - b0) < 1e-9, "the standoffs span the Pi's back to the cover"
    assert cb + 12 - pi_back >= 2.0 and b1 - 6 - (cb + 12) >= 0.4, "front screw, cover screw: engagement, gap"
    for u, v in PIZ["holes"]:
        x, z = PIZ["w"] / 2 - u, v - PIZ["h"] / 2
        case = case.union(ycyl(h["pi_post_d"], pt - 0.5, h["pi_y"], x, z))
        case = case.cut(ycyl(m25["clear"], -1, h["pi_y"] + 1, x, z)).cut(ycyl(m25["cbore"], -1, cb, x, z))
        hw.add("M2.5 screws, Pi Zero", ("M2.5", "screw 12"), screw("M2.5", 12, x, z, cb, 1))
        hw.add("M2.5 standoffs, Pi Zero", ("M2.5", "F-F 6"), standoff_ff("M2.5", h["standoff"], x, z, pi_back))
    # back cover: plate, vents, clearance holes over the standoffs, M2.5 x 6 into them
    back = box(-a - ct, b0, -zm, a + ct, b1, zm).edges("|Y").fillet(3.0)
    for i in range(5):
        back = back.cut(box(-20 + i * 10, b0 - 1, -8, -16 + i * 10, b1 + 1, 8))
    for u, v in PIZ["holes"]:
        x, z = PIZ["w"] / 2 - u, v - PIZ["h"] / 2
        back = back.cut(ycyl(m25["clear"], b0 - 1, b1 + 1, x, z))
        hw.add("M2.5 screws, back cover", ("M2.5", "screw 6"), screw("M2.5", 6, x, z, b1, -1))
    return case, back, ops, hw


def head_zero_parts():
    """Pi Zero 2 W + Camera Module 3 head, head frame."""
    h = ZK
    case, back, _, hw = _zero_case_frame()
    p = {"case": (case, "petg"), "back cover": (back, "petg")}
    p.update({n: (_union(v), "nylon") for n, v in hw.items()})
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
                          x=lx - 7.0, w=11.0), "ribbon")
    p["USB power lead"] = (ycyl(4.0, h["pi_y"] + 2.0, h["pi_y"] + 2.1, -21.5, -zm).union(
        cyl(4.0, 40.0, x=-21.5, y=h["pi_y"] + 3.5, z=-zm - 40.0)), "black")
    ay = h["axis_y"]
    return {n: (s.translate((0, -ay, 0)), m) for n, (s, m) in p.items() if s is not None}


# --------------------------------------------------------------------------------------------- HQ head
def _hq_frame():
    """HQ head printed parts in the case frame (front face y = 0): the tub (camera plate, cheeks, threaded bosses, HQ
    posts, ribs with nut slots for the carrier), the Pi 5 carrier on the cheeks' back ends, the Wide nose on the
    plate's front. Returns (parts, thread ops, positions, hardware)."""
    h, m25, m2 = HK, HW["M2.5"], HW["M2"]
    x0, x1, z0, z1 = h["plate"]
    pt, ay, ct = h["plate_t"], h["axis_y"], h["cheek_t"]
    bd, bt = h["boss_d"], h["boss_t"]
    cy0 = h["pi_carrier_y"]                                  # carrier front face
    cy1 = cy0 + 4.0
    hq_at = (h["hq_x"], pt + h["hq_standoff"], 0.0)
    hw = Hardware()
    # tub: plate with the lens-mount opening, cheeks, bosses with blind M10 threads
    tub = box(x0, 0, z0, x1, pt, z1).edges("|Y").fillet(4.0)
    tub = tub.cut(cq.Workplane("XZ").circle(37.0 / 2).extrude(-pt - 2).translate((h["hq_x"], -1, 0)))
    foot = _to_head(_poly_z(_hq_tripod_outline(), -10.35 - 1, 2.0), hq_at)
    lock = _to_head(box(-6.1, 15.0, -10.35 - 1, 6.1, 22.6, 2.0), hq_at)
    tub = tub.cut(foot).cut(lock)
    tub = tub.union(box(x0, pt, z0, x0 + ct, cy0, z1)).union(box(x1 - ct, pt, z0, x1, cy0, z1))
    # ribs inside the cheeks, from the plate to the carrier; a nut slot in each, opening into the tub
    cx, cz = h["carrier_screw"]
    rw, rh = h["rib"]
    car = [(sx * cx, sz * cz) for sx in (-1, 1) for sz in (-1, 1)]
    head_c = cy0 + h["cbore_floor"]                          # carrier screws' heads bear here
    seat_c = cy0 - h["carrier_roof"]
    assert head_c - 8 <= seat_c - m25["nut_m"] - PAST
    for x, z in car:
        xi = x1 - ct if x > 0 else x0 + ct
        xr = xi - math.copysign(rw, x)
        tub = tub.union(box(min(xi, xr) - 0.5 * (x < 0), pt - 0.5, z - rh / 2, max(xi, xr) + 0.5 * (x > 0), cy0,
                            z + rh / 2))
        tub = tub.cut(ycyl(m25["clear"], cy0 + 1, head_c - 8 - 1.0, x, z))
        tub = tub.cut(nut_slot("M2.5", x, z, seat_c, -1, "-x" if x > 0 else "+x", abs(x - xr) + 1.0))
        hw.add("M2.5 nuts, carrier", ("M2.5", "nut"), nut("M2.5", x, z, seat_c, -1, "z"))
    ops = []
    for sx in (-1, 1):
        xb = x1 if sx > 0 else x0 - bt
        tub = tub.union(xcyl(bd, xb, xb + bt, ay, 0.0).union(box(xb, 0.0, -bd / 2, xb + bt, ay, bd / 2)))
        xo = x1 + bt if sx > 0 else x0 - bt
        depth = spm.hole_depth()
        tub = tub.cut(xcyl(spm.TILT_CORE_INT, xo + sx * 1.0, xo - sx * depth, ay, 0.0))
        ops.append(dict(kind="tap", thread="tilt", origin=(xo, ay, 0.0), axis=(-sx, 0, 0), length=depth, blind=True,
                        part="tub"))
    # HQ Camera: posts with clearance holes; M2.5 x 12 from the front face (heads on it), nuts on the board's back
    hq_back = pt + h["hq_standoff"] + HQ_PCB_T
    assert hq_back + m25["nut_m"] + PAST <= 12.0
    hq_holes = [(h["hq_x"] + sx * HQ_PITCH / 2, sz * HQ_PITCH / 2) for sx in (-1, 1) for sz in (-1, 1)]
    for x, z in hq_holes:
        tub = tub.union(ycyl(h["hq_post_d"], pt - 0.5, pt + h["hq_standoff"], x, z))
        tub = tub.cut(ycyl(m25["clear"], -1, pt + h["hq_standoff"] + 1, x, z))
        hw.add("M2.5 screws, HQ Camera", ("M2.5", "screw 12"), screw("M2.5", 12, x, z, 0.0, 1))
        hw.add("M2.5 nuts, HQ Camera", ("M2.5", "nut"), nut("M2.5", x, z, hq_back, 1))
    # the Wide's ribbon goes through a slot in the plate; the nose's screws come through counterbored holes from inside
    sx0, sx1, sz0, sz1 = h["wide_slot"]
    tub = tub.cut(box(sx0, -1, sz0, sx1, pt + 1, sz1))
    head_n = h["cbore_floor"]
    for x, z, _ in h["nose_screws"]:
        tub = tub.cut(ycyl(m25["clear"], -1, pt + 1, x, z)).cut(ycyl(m25["cbore"], head_n, pt + 1, x, z))
        hw.add("M2.5 screws, Wide nose", ("M2.5", "screw 8"), screw("M2.5", 8, x, z, head_n, -1))
    # carrier: plate, counterbored holes onto the ribs, posts for the Pi 5 with nut slots opening outward
    carrier = box(x0, cy0, z0 - 4, x1, cy1, z1 + 4).edges("|Y").fillet(4.0)
    for x, z in car:
        carrier = carrier.cut(ycyl(m25["clear"], cy0 - 1, cy1 + 1, x, z))
        carrier = carrier.cut(ycyl(m25["cbore"], head_c, cy1 + 1, x, z))
        hw.add("M2.5 screws, carrier", ("M2.5", "screw 8"), screw("M2.5", 8, x, z, head_c, -1))
    pi_y = cy1 + h["pi_standoff"]
    pi_back = pi_y + PI5["t"]
    seat_p = pi_y - h["pi_roof"]
    assert pi_back - 6 <= seat_p - m25["nut_m"] - PAST
    pd, (td, th) = h["pi_post_d"], h["pi_post_top"]
    pi_holes = [(PI5["w"] / 2 - u, v - PI5["h"] / 2) for u, v in PI5["holes"]]
    for x, z in pi_holes:
        carrier = carrier.union(ycyl(pd, cy1 - 0.5, pi_y - th, x, z)).union(ycyl(td, pi_y - th - 0.5, pi_y, x, z))
        carrier = carrier.cut(ycyl(m25["clear"], pi_y + 1, cy1 - 2.0, x, z))
        carrier = carrier.cut(nut_slot("M2.5", x, z, seat_p, -1, "+z" if z > 0 else "-z", pd / 2 + 1.0))
        hw.add("M2.5 screws, Pi 5", ("M2.5", "screw 6"), screw("M2.5", 6, x, z, pi_back, -1))
        hw.add("M2.5 nuts, Pi 5", ("M2.5", "nut"), nut("M2.5", x, z, seat_p, -1))
    # Wide nose: frame level with the zoom's front, a floor and a side wall back to the plate, shoulders for the Wide
    # with M2 nuts in pockets in the frame's front face, nut slots in the floor's and the wall's ends
    wx0, wx1 = h["wide_x"] - 14.0, h["wide_x"] + 18.0
    ny, wz = h["nose_y"], h["wide_z"]
    f0, f1 = h["floor"]
    nose = box(wx0, ny, wz - 16, wx1, ny + 5, wz + 16)
    nose = nose.cut(box(h["wide_x"] - 5.7, ny - 1, wz - 5.7, h["wide_x"] + 5.7, ny + 6, wz + 5.7))
    nose = nose.union(box(wx0, ny, wz + f0, wx1, 0, wz + f1))
    nose = nose.union(box(wx1 - 4, ny + 5, wz + f1, wx1, 0, wz + 8))
    block = cq.Workplane("XY").polyline([(wx1 - 7, -8.0), (wx1 - 7, 0.0), (wx1 - 3.5, 0.0), (wx1 - 3.5, -11.5)]) \
        .close().extrude(12.0).translate((0, 0, wz - 4.0))    # 45 deg underside: prints without support
    nose = nose.union(block)
    wide_back = ny + 5 + 2.5 + CM3["pcb_t"]
    seat_w = seat_for("M2", 8, wide_back, -1)
    assert seat_w - m2["nut_m"] >= ny - 1e-9
    for sx in (-1, 1):
        for dz in (CM3["lens_from_top"] - 2.0, CM3["lens_from_top"] - 14.5):
            x, z = h["wide_x"] + sx * 10.5, wz + dz
            nose = nose.union(ycyl(h["wide_shoulder"], ny + 4.5, ny + 5 + 2.5, x, z))
            nose = nose.cut(ycyl(m2["clear"], ny - 1, wide_back, x, z)).cut(nut_pocket("M2", x, z, seat_w, ny))
            hw.add("M2 screws, Wide", ("M2", "screw 8"), screw("M2", 8, x, z, wide_back, -1))
            hw.add("M2 nuts, Wide", ("M2", "nut"), nut("M2", x, z, seat_w, -1))
    seat_n = -h["nose_roof"]
    assert head_n - 8 <= seat_n - m25["nut_m"] - PAST
    for x, z, out in h["nose_screws"]:
        nose = nose.cut(ycyl(m25["clear"], 1.0, head_n - 8 - 1.0, x, z))
        reach = (z - (wz + f0)) if out == "-z" else (wx1 - x)
        nose = nose.cut(nut_slot("M2.5", x, z, seat_n, -1, out, reach + 1.0))
        hw.add("M2.5 nuts, Wide nose", ("M2.5", "nut"), nut("M2.5", x, z, seat_n, -1, "x" if out[1] == "z" else "z"))
    parts = {"tub": tub, "carrier": carrier, "Wide nose": nose}
    return parts, ops, dict(hq_at=hq_at, pi_y=pi_y), hw


def head_hq_parts(wide=True):
    h = HK
    pr, _, at, hw = _hq_frame()
    p = {"tub": (pr["tub"], "petg"), "carrier": (pr["carrier"], "petg")}
    p.update({n: (_union(v), "nylon") for n, v in hw.items() if wide or "Wide" not in n})
    for name, (s, m) in hq_camera_parts().items():
        p[name] = (_to_head(s, at["hq_at"]), m)
    pi_y = at["pi_y"]
    pi_at = (PI5["w"] / 2, pi_y, -PI5["h"] / 2)
    for name, (s, m) in pi5_parts().items():
        p[name] = (_rot(s, [((1, 0, 0), -90), ((0, 1, 0), 180)]).translate(pi_at), m)
    x0, x1, z0, z1 = h["plate"]
    pt = h["plate_t"]
    zr = z0 - 6.0
    yb = pi_y + PI5["t"] + 4.5
    p["HQ ribbon"] = (_strip([(at["hq_at"][1] + 2.0, -HQ_BOARD / 2 + 3.0), (at["hq_at"][1] + 2.0, zr), (yb, zr),
                              (yb, -PI5["h"] / 2 + 12.0)], x=-10.0), "ribbon")
    if wide:
        p["Wide nose"] = (pr["Wide nose"], "petg")
        wide_at = (h["wide_x"], h["nose_y"] + 5 + 2.5, h["wide_z"])
        for name, (s, m) in cm3_parts(wide=True).items():
            p[name] = (_to_head(s, wide_at), m)
        zs = h["wide_z"] - 14.5
        p["Wide ribbon"] = (_strip([(wide_at[1] + 2.0, h["wide_z"] - 9.0), (wide_at[1] + 2.0, zs), (pt + 3.0, zs),
                                    (pt + 3.0, zr - 1.2), (yb + 1.2, zr - 1.2), (yb + 1.2, -PI5["h"] / 2 + 12.0)],
                                   x=h["wide_ribbon_x"]), "ribbon")
    ay = h["axis_y"]
    return {n: (s.translate((0, -ay, 0)), m) for n, (s, m) in p.items() if s is not None}


def lens_point(kind):
    """The camera's lens centre (the HQ's zoom front, or the CM3's glass), head frame."""
    if kind == "zero":
        h = ZK
        return (h["lens_x"], h["plate_t"] + h["cm3_gap"] - CM3["lens_h"] + 0.9 - h["axis_y"], h["lens_z"])
    h = HK
    y = h["plate_t"] + h["hq_standoff"] - HQ_CS_SEAT - LENS_ZOOM["profile"][-1][1] - h["axis_y"]
    return (h["hq_x"], y, 0.0)


# ----------------------------------------------------------------------------- yoke, knobs, stud
def head_half(kind):
    if kind == "zero":
        return ZK["half"] + ZK["cheek_t"] + ZK["boss_t"]
    return HK["plate"][1] + HK["boss_t"]


def screw_len(kind=None):
    """Tilt screw shank from the knob's bearing face: arm + open gap + engagement (no ears)."""
    return spm.ARM_T + spm.ARM_GAP + spm.TSCREW["engage"]


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
    top = max(PAD["t"] + spm.KNOB["h"], STUD["length"])
    return math.ceil(top + spm.SWING_CLEAR + _radius(kind, kind != "zero"))


def yoke(kind):
    """As the all-printed yoke, arms moved in to the narrower head (no ears)."""
    half = head_half(kind)
    depth = tilt_depth(kind)
    at, gap = spm.ARM_T, spm.ARM_GAP
    a0, a1 = half + gap, half + gap + at
    t, bw = PAD["t"], PAD["bar_w"]
    y = cyl(PAD["d"], t, z=-t).union(box(-a1, -bw / 2, -t, a1, bw / 2, 0).edges("|Z").fillet(3.0))
    br = 11.0
    for sx in (-1, 1):
        x0 = a0 if sx > 0 else -a1
        prof = [(-bw / 2, 0.0), (bw / 2, 0.0), (br, -depth), (-br, -depth)]
        arm = cq.Workplane("YZ").polyline(prof).close().extrude(at).translate((x0, 0, 0))
        arm = arm.union(xcyl(2 * br, x0, x0 + at, 0.0, -depth))
        y = y.union(arm)
        y = y.cut(xcyl(spm.ARM_HOLE, x0 - 1, x0 + at + 1, 0.0, -depth))
    y = y.cut(cyl(STUD["clear"], t + 2, z=-t - 1))
    y = y.cut(cyl(STUD["weld_d"], STUD["weld_h"], z=-STUD["weld_h"]))
    return y


def tilt_screw_local(kind=None):
    """One thumb screw, its own frame: knob from z = -knob_h to 0 (bearing face at z = 0), shank core along +z."""
    t = spm.TSCREW
    knob = cyl(t["knob_d"], t["knob_h"], z=-t["knob_h"])
    for i in range(8):
        a = 2 * math.pi * i / 8
        knob = knob.cut(cyl(5.0, t["knob_h"] + 2, x=(t["knob_d"] / 2 + 1.0) * math.cos(a),
                            y=(t["knob_d"] / 2 + 1.0) * math.sin(a), z=-t["knob_h"] - 1))
    knob = knob.edges("<Z").chamfer(0.6)
    root = cq.Workplane("XY").circle(spm.TILT_CORE_EXT / 2 + t["root_fillet"]).workplane(offset=t["root_fillet"]) \
        .circle(spm.TILT_CORE_EXT / 2).loft()
    return knob.union(root).union(cyl(spm.TILT_CORE_EXT, screw_len()))


def tilt_screw_ops_local(kind=None):
    return [dict(kind="external", thread="tilt", origin=(0.0, 0.0, 0.0), axis=(0, 0, 1), length=screw_len(),
                 part="tilt screw")]


def tilt_screws(kind):
    """Both thumb screws in the mount frame (pan 0), knobs outside the arms."""
    a1 = head_half(kind) + spm.ARM_GAP + spm.ARM_T
    depth = tilt_depth(kind)
    out = None
    for sx in (-1, 1):
        s = tilt_screw_local().rotate((0, 0, 0), (0, 1, 0), -90 * sx).translate((sx * a1, 0, -depth))
        out = s if out is None else out.union(s)
    return out


def fit_coupon():
    """Print first. Two bars joined at the left end, M2.5 (wider) and M2. Each has three nut pockets open to the bed,
    NUT_FIT - 0.1, NUT_FIT and NUT_FIT + 0.1 across flats from left to right, and a clearance hole through each. At the
    right end is a post with a side slot (NUT_FIT) opening to the right. The chamfered corner is at the M2.5 bar's
    tightest pocket."""
    out = None
    y_m2 = HW["M2.5"]["nut_af"] + 10.0
    for i, size in enumerate(("M2.5", "M2")):
        s = HW[size]
        pitch = s["nut_af"] + 5.0
        w = s["nut_af"] + 6.0
        y0 = i * y_m2
        x_end = 3.5 * pitch + 1
        zt = 2.5 + s["nut_m"] + 3.0
        bar = box(-pitch / 2 - 1, y0 - w / 2, 0, x_end, y0 + w / 2, 2.5)
        bar = bar.union(box(2.5 * pitch, y0 - w / 2, 0, x_end, y0 + w / 2, zt))
        for j, fit in enumerate((NUT_FIT - 0.1, NUT_FIT, NUT_FIT + 0.1)):
            x = j * pitch
            r = (s["nut_af"] + fit) / math.sqrt(3)
            pocket = cq.Workplane("XY").polygon(6, 2 * r).extrude(s["nut_m"] + 0.4).translate((x, y0, -0.01))
            bar = bar.cut(pocket).cut(cyl(s["clear"], 4.0, x=x, y=y0, z=-1))
        # side slot in the post, toward +x, the nut seated 1.5 mm below the post's top (corners on +-x, as in the heads)
        xs = 3.0 * pitch
        af = s["nut_af"] + NUT_FIT
        z1 = zt - 1.5
        z0 = z1 - s["nut_m"] - SLOT_GAP
        hexp = cq.Workplane("XY").polygon(6, 2 * af / math.sqrt(3)).extrude(z1 - z0).translate((xs, y0, z0))
        bar = bar.cut(hexp).cut(box(xs, y0 - af / 2, z0, x_end + 1, y0 + af / 2, z1))
        bar = bar.cut(cyl(s["clear"], zt + 2, x=xs, y=y0, z=-1))
        if i == 0:
            bar = bar.cut(box(-pitch / 2 - 2, y0 - w / 2 - 1, -1, -pitch / 2 + 1.5, y0 - w / 2 + 2.5, 4))
        out = bar if out is None else out.union(bar)
    x_l = -(HW["M2.5"]["nut_af"] + 5.0) / 2 - 1
    return out.union(box(x_l, 0.0, 0, x_l + 4.0, y_m2, 2.5))


# ----------------------------------------------------------------------------------------- assembly
def parts(kind, wide=True):
    head = head_zero_parts() if kind == "zero" else head_hq_parts(wide=wide)
    return {"fixed": {"ceiling stud": (sm.ceiling_stud(), "steel")},
            "pan": {"yoke": (yoke(kind), "petg"), "stud thumb nut": (spm.stud_knob(), "knob"),
                    "tilt screws": (tilt_screws(kind), "knob")},
            "head": head}


def assembly(kind, pan=0.0, tilt=45.0, wide=True):
    colours = dict(petg=(0.15, 0.16, 0.17), knob=(0.85, 0.42, 0.10), steel=(0.75, 0.77, 0.80),
                   nylon=(0.06, 0.06, 0.07), pcb=(0.12, 0.48, 0.24), lens=(0.08, 0.08, 0.09),
                   glass=(0.30, 0.45, 0.65), white=(0.93, 0.93, 0.93), port=(0.70, 0.72, 0.75),
                   black=(0.1, 0.1, 0.1), cooler=(0.55, 0.58, 0.62), ribbon=(0.85, 0.65, 0.25))
    depth = tilt_depth(kind)
    pc = parts(kind, wide)
    asm = cq.Assembly(name=f"stud_mount_kit_{kind}")
    rz = cq.Location(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), pan)
    for name, (s, m) in pc["fixed"].items():
        asm.add(s, name=name.replace(" ", "_"), color=cq.Color(*colours[m]))
    for name, (s, m) in pc["pan"].items():
        asm.add(s, name=name.replace(" ", "_"), loc=rz, color=cq.Color(*colours[m]))
    head_loc = rz * cq.Location(cq.Vector(0, 0, -depth)) * cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), tilt)
    for name, (s, m) in pc["head"].items():
        asm.add(s, name=name.replace(", ", "_").replace(" ", "_").replace(".", "_"), loc=head_loc,
                color=cq.Color(*colours[m]))
    return asm


def head_thread_ops(kind):
    """Thread ops of the head's printed parts in the head frame."""
    if kind == "zero":
        _, _, ops, _ = _zero_case_frame()
        ay = ZK["axis_y"]
    else:
        _, ops, _, _ = _hq_frame()
        ay = HK["axis_y"]
    return [dict(o, origin=(o["origin"][0], o["origin"][1] - ay, o["origin"][2])) for o in ops]


def bom():
    """Kit parts per mount and for the printed set (2 Pi Zero mounts + 1 HQ mount), against one kit of each size."""
    per = {"zero": _zero_case_frame()[3].count, "hq": _hq_frame()[3].count}
    total = {}
    for kind, cnt in per.items():
        for k, n in cnt.items():
            total[k] = total.get(k, 0) + n * MOUNTS[kind]
    out = {"per mount": {kind: {f"{s} {i}": n for (s, i), n in sorted(c.items())} for kind, c in per.items()},
           "2 Pi Zero + 1 HQ": {f"{s} {i}": n for (s, i), n in sorted(total.items())},
           "left in the kits": {f"{s} {i}": KIT[s][i] - n for (s, i), n in sorted(total.items())}}
    assert all(v >= 0 for v in out["left in the kits"].values()), out
    return out


if __name__ == "__main__":
    import json
    for kind in ("zero", "hq"):
        print(kind, "half %.1f, swing %.1f, tilt-axis depth %d mm, screw %.1f mm, hole %.1f mm" % (
            head_half(kind), _radius(kind, kind != "zero"), tilt_depth(kind), screw_len(), spm.hole_depth()))
    print(json.dumps(bom(), indent=1))
