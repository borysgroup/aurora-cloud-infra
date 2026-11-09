"""Stud pan/tilt camera mount: printed parts plus M2 and M2.5 screws from a standoff kit (CadQuery + mesh threads).

The all-printed mount (../printed/) with its boards and covers screwed down. In the all-printed mount the boards sit on
printed pegs and are held on by covers whose ears are clamped under the yoke's arms by the tilt screws, so loosening a
tilt screw to re-aim also unclamps the boards. Here every board is screwed down with pan-head machine screws that form
their own thread in pilot holes in printed posts, and the covers are screwed on, so the tilt screws clamp only the
yoke's arms on the bosses.

  pan    printed thumb nut with an M6 x 1 thread on the welded stud (the all-printed mount's part, unchanged)
  tilt   printed M10 x 1.25 thumb screws through the yoke's arms into threads printed in the head's bosses. No ears
         between arm and boss, so the screws are 2.5 mm shorter and the arms sit 2.5 mm further in.
  boards Pi Zero 2 W, Pi 5 and HQ Camera on M2.5 x 6; Camera Module 3 and CM3 Wide on M2 x 6
  covers Pi Zero head: back cover on four M2.5 x 6 into posts outside the cheeks. HQ head: Pi 5 carrier on four
         M2.5 x 6 into the tub's cheeks, Wide nose on three M2.5 x 6 from inside the tub; no retainers.

Only M2 x 6 and M2.5 x 6 screws are used, no nuts or standoffs. The welded stud is the only other metal.
Frames as in ../stud_mount.py: mount frame z up from where the stud leaves the ceiling; head frame on the tilt axis,
camera looking along -y at tilt 0.
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
from stud_mount import (CM3, HQ_BOARD, HQ_PCB_T, HQ_PITCH, PAD, PI5, PIZ, STUD, _hq_tripod_outline, _poly_z,  # noqa: E402
                        _rot, _strip, _to_head, box, cm3_parts, cyl, hq_camera_parts, pi5_parts, pi_zero_parts, xcyl,
                        ycyl)

# ------------------------------------------------------------------------------------------- kit screws
# Pan-head machine screws (ISO 7045 heads, rounded up) that form their own thread in a printed pilot hole. Print
# stl/pilot_coupon.stl first and change `pilot` if a screw is loose or splits its post.
SCREW = {"M2.5": dict(d=2.5, L=6.0, head_d=5.0, head_k=2.0, pilot=2.2, clear=2.8, cbore=5.6),
         "M2": dict(d=2.0, L=6.0, head_d=4.0, head_k=1.6, pilot=1.7, clear=2.3, cbore=4.6)}

ZK = dict(spm.ZP)                                         # Pi Zero head: the all-printed case, plus
ZK.update(ear_t=0.0, cm3_gap=2.5, lens_x=-13.5, pi_post_d=5.0, cm3_shoulder=4.2, cover_post_d=6.0,
          cover_post=(39.3, 11.8))
HK = dict(spm.HP)                                         # HQ head
HK.update(ear_t=0.0, hq_post_d=5.0, pi_post_d=6.0, wide_shoulder=4.2, carrier_screw=(44.0, 20.0), rib_w=3.5,
          cbore_floor=1.5, wide_slot=(15.0, 30.0, -13.5, -10.5), wide_ribbon_x=22.5,
          nose_screws=((13.0, -17.0), (36.0, -17.0), (38.5, 4.0)))


def _yscrew(size, x, y_face, z, into=-1):
    """A kit screw along y, head bearing on the face at y_face, shank going `into` (+1/-1) along y. The shank is drawn
    at the pilot diameter: the thread it forms is the intended overlap with the printed post."""
    s = SCREW[size]
    shank = ycyl(s["pilot"] - 0.02, y_face, y_face + into * s["L"], x, z)
    head = ycyl(s["head_d"], y_face, y_face - into * s["head_k"], x, z)
    return shank.union(head)


def _union(shapes):
    out = None
    for s in shapes:
        out = s if out is None else out.union(s)
    return out


# ------------------------------------------------------------------------------------------ Pi Zero head
def _zero_case_frame():
    """Pi Zero case, its own frame (front face y = 0). Returns (case, back cover, thread ops, screws by size)."""
    h, m25, m2 = ZK, SCREW["M2.5"], SCREW["M2"]
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
    screws = {"M2 screws, CM3": [], "M2.5 screws, Pi Zero": [], "M2.5 screws, back cover": []}
    # Camera Module 3: four shoulders, M2 pilot holes right through (the 5 mm under the board takes an M2 x 6)
    cam_back = pt + h["cm3_gap"] + CM3["pcb_t"]
    for sx in (-1, 1):
        for dz in (CM3["lens_from_top"] - 2.0, CM3["lens_from_top"] - 14.5):
            x, z = lx + sx * 10.5, lz + dz
            case = case.union(ycyl(h["cm3_shoulder"], pt - 0.5, pt + h["cm3_gap"], x, z))
            case = case.cut(ycyl(m2["pilot"], -1, pt + h["cm3_gap"] + 1, x, z))
            screws["M2 screws, CM3"].append(_yscrew("M2", x, cam_back, z))
    # Pi Zero: posts up to its underside with blind M2.5 pilot holes
    pi_back = h["pi_y"] + PIZ["t"]
    for u, v in PIZ["holes"]:
        x, z = PIZ["w"] / 2 - u, v - PIZ["h"] / 2
        case = case.union(ycyl(h["pi_post_d"], pt - 0.5, h["pi_y"], x, z))
        case = case.cut(ycyl(m25["pilot"], h["pi_y"] + 1, h["pi_y"] - (m25["L"] - PIZ["t"]) - 1.0, x, z))
        screws["M2.5 screws, Pi Zero"].append(_yscrew("M2.5", x, pi_back, z))
    # posts for the back cover's screws, on the cheeks' outer faces above and below the bosses
    cpx, cpz = h["cover_post"]
    posts = [(sx * cpx, sz * cpz) for sx in (-1, 1) for sz in (-1, 1)]
    for x, z in posts:
        case = case.union(ycyl(h["cover_post_d"], 0.0, b0, x, z))
        case = case.cut(ycyl(m25["pilot"], b0 + 1, b0 - (m25["L"] - (b1 - b0)) - 1.0, x, z))
    # back cover: plate, vents, four lugs with clearance holes
    back = box(-a - ct, b0, -zm, a + ct, b1, zm).edges("|Y").fillet(3.0)
    for i in range(5):
        back = back.cut(box(-20 + i * 10, b0 - 1, -8, -16 + i * 10, b1 + 1, 8))
    r = h["cover_post_d"] / 2
    for x, z in posts:
        xi = math.copysign(a + ct - 0.5, x)
        back = back.union(ycyl(h["cover_post_d"], b0, b1, x, z)).union(
            box(min(xi, x), b0, z - r, max(xi, x), b1, z + r))
        back = back.cut(ycyl(m25["clear"], b0 - 1, b1 + 1, x, z))
        screws["M2.5 screws, back cover"].append(_yscrew("M2.5", x, b1, z))
    return case, back, ops, screws


def head_zero_parts():
    """Pi Zero 2 W + Camera Module 3 head, head frame."""
    h = ZK
    case, back, _, screws = _zero_case_frame()
    p = {"case": (case, "petg"), "back cover": (back, "petg")}
    p.update({n: (_union(v), "steel") for n, v in screws.items()})
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
    posts), the Pi 5 carrier screwed to the cheeks' back ends, the Wide nose screwed to the plate's front.
    Returns (parts, thread ops, positions, screws by size)."""
    h, m25, m2 = HK, SCREW["M2.5"], SCREW["M2"]
    x0, x1, z0, z1 = h["plate"]
    pt, ay, ct = h["plate_t"], h["axis_y"], h["cheek_t"]
    bd, bt = h["boss_d"], h["boss_t"]
    cy0 = h["pi_carrier_y"]                                  # carrier front face
    cy1 = cy0 + 4.0
    hq_at = (h["hq_x"], pt + h["hq_standoff"], 0.0)
    screws = {"M2.5 screws, HQ Camera": [], "M2.5 screws, Wide nose": [], "M2.5 screws, carrier": [],
              "M2.5 screws, Pi 5": [], "M2 screws, Wide": []}
    # tub: plate with the lens-mount opening, cheeks, bosses with blind M10 threads
    tub = box(x0, 0, z0, x1, pt, z1).edges("|Y").fillet(4.0)
    tub = tub.cut(cq.Workplane("XZ").circle(37.0 / 2).extrude(-pt - 2).translate((h["hq_x"], -1, 0)))
    foot = _to_head(_poly_z(_hq_tripod_outline(), -10.35 - 1, 2.0), hq_at)
    lock = _to_head(box(-6.1, 15.0, -10.35 - 1, 6.1, 22.6, 2.0), hq_at)
    tub = tub.cut(foot).cut(lock)
    tub = tub.union(box(x0, pt, z0, x0 + ct, cy0, z1)).union(box(x1 - ct, pt, z0, x1, cy0, z1))
    # ribs inside the cheeks' corners, from the plate to the carrier, with pilot holes for the carrier's screws
    cx, cz = h["carrier_screw"]
    car = [(sx * cx, sz * cz) for sx in (-1, 1) for sz in (-1, 1)]
    for x, z in car:
        xi = x1 - ct if x > 0 else x0 + ct
        xr = xi - math.copysign(h["rib_w"], x)
        tub = tub.union(box(min(xi, xr) - 0.5 * (x < 0), pt - 0.5, z - 4.0, max(xi, xr) + 0.5 * (x > 0), cy0, z + 4.0))
        tub = tub.cut(ycyl(m25["pilot"], cy0 + 1, cy0 - (m25["L"] - h["cbore_floor"]) - 1.0, x, z))
    ops = []
    for sx in (-1, 1):
        xb = x1 if sx > 0 else x0 - bt
        tub = tub.union(xcyl(bd, xb, xb + bt, ay, 0.0).union(box(xb, 0.0, -bd / 2, xb + bt, ay, bd / 2)))
        xo = x1 + bt if sx > 0 else x0 - bt
        depth = spm.hole_depth()
        tub = tub.cut(xcyl(spm.TILT_CORE_INT, xo + sx * 1.0, xo - sx * depth, ay, 0.0))
        ops.append(dict(kind="tap", thread="tilt", origin=(xo, ay, 0.0), axis=(-sx, 0, 0), length=depth, blind=True,
                        part="tub"))
    # HQ Camera: posts (the old 4 mm standoffs) with blind M2.5 pilot holes; 2 mm of plate left in front
    hq_back = pt + h["hq_standoff"] + HQ_PCB_T
    hq_holes = [(h["hq_x"] + sx * HQ_PITCH / 2, sz * HQ_PITCH / 2) for sx in (-1, 1) for sz in (-1, 1)]
    for x, z in hq_holes:
        tub = tub.union(ycyl(h["hq_post_d"], pt - 0.5, pt + h["hq_standoff"], x, z))
        tub = tub.cut(ycyl(m25["pilot"], pt + h["hq_standoff"] + 1, 2.0, x, z))
        screws["M2.5 screws, HQ Camera"].append(_yscrew("M2.5", x, hq_back, z))
    # the Wide's ribbon goes through a slot in the plate; the nose's screws come through counterbored holes from inside
    sx0, sx1, sz0, sz1 = h["wide_slot"]
    tub = tub.cut(box(sx0, -1, sz0, sx1, pt + 1, sz1))
    for x, z in h["nose_screws"]:
        tub = tub.cut(ycyl(m25["clear"], -1, pt + 1, x, z)).cut(ycyl(m25["cbore"], h["cbore_floor"], pt + 1, x, z))
        screws["M2.5 screws, Wide nose"].append(_yscrew("M2.5", x, h["cbore_floor"], z, into=-1))
    # carrier: plate, counterbored holes onto the ribs, posts with blind M2.5 pilot holes for the Pi 5 on its back
    carrier = box(x0, cy0, z0 - 4, x1, cy1, z1 + 4).edges("|Y").fillet(4.0)
    for x, z in car:
        carrier = carrier.cut(ycyl(m25["clear"], cy0 - 1, cy1 + 1, x, z))
        carrier = carrier.cut(ycyl(m25["cbore"], cy0 + h["cbore_floor"], cy1 + 1, x, z))
        screws["M2.5 screws, carrier"].append(_yscrew("M2.5", x, cy0 + h["cbore_floor"], z))
    pi_y = cy1 + h["pi_standoff"]
    pi_holes = [(PI5["w"] / 2 - u, v - PI5["h"] / 2) for u, v in PI5["holes"]]
    for x, z in pi_holes:
        carrier = carrier.union(ycyl(h["pi_post_d"], cy1 - 0.5, pi_y, x, z))
        carrier = carrier.cut(ycyl(m25["pilot"], pi_y + 1, pi_y - (m25["L"] - PI5["t"]) - 1.0, x, z))
        screws["M2.5 screws, Pi 5"].append(_yscrew("M2.5", x, pi_y + PI5["t"], z))
    # Wide nose: frame level with the zoom's front, a 6 mm floor and a side wall back to the plate, shoulders with M2
    # pilot holes for the Wide, M2.5 pilot holes in the floor's and the wall's ends for the screws from the tub
    wx0, wx1 = h["wide_x"] - 14.0, h["wide_x"] + 18.0
    ny, wz = h["nose_y"], h["wide_z"]
    nose = box(wx0, ny, wz - 16, wx1, ny + 5, wz + 16)
    nose = nose.cut(box(h["wide_x"] - 5.7, ny - 1, wz - 5.7, h["wide_x"] + 5.7, ny + 6, wz + 5.7))
    nose = nose.union(box(wx0, ny, wz - 22, wx1, 0, wz - 16))
    nose = nose.union(box(wx1 - 4, ny + 5, wz - 16, wx1, 0, wz + 8))
    block = cq.Workplane("XY").polyline([(wx1 - 7, -8.0), (wx1 - 7, 0.0), (wx1 - 3.5, 0.0), (wx1 - 3.5, -11.5)]) \
        .close().extrude(12.0).translate((0, 0, wz - 4.0))    # 45 deg underside: prints without support
    nose = nose.union(block)
    wide_back = ny + 5 + 2.5 + CM3["pcb_t"]
    for sx in (-1, 1):
        for dz in (CM3["lens_from_top"] - 2.0, CM3["lens_from_top"] - 14.5):
            x, z = h["wide_x"] + sx * 10.5, wz + dz
            nose = nose.union(ycyl(h["wide_shoulder"], ny + 4.5, ny + 5 + 2.5, x, z))
            nose = nose.cut(ycyl(m2["pilot"], ny + 5 + 2.5 + 1, ny + 2.0, x, z))
            screws["M2 screws, Wide"].append(_yscrew("M2", x, wide_back, z))
    for x, z in h["nose_screws"]:
        nose = nose.cut(ycyl(m25["pilot"], 1.0, -(m25["L"] - h["cbore_floor"]) - 1.0, x, z))
    parts = {"tub": tub, "carrier": carrier, "Wide nose": nose}
    return parts, ops, dict(hq_at=hq_at, pi_y=pi_y), screws


def head_hq_parts(wide=True):
    h = HK
    pr, _, at, screws = _hq_frame()
    p = {"tub": (pr["tub"], "petg"), "carrier": (pr["carrier"], "petg")}
    p.update({n: (_union(v), "steel") for n, v in screws.items() if wide or "Wide" not in n})
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


def pilot_coupon():
    """Posts like the head's, each with a different pilot hole, left to right: M2 1.6 / 1.7 / 1.8 in 4.2 mm posts,
    then M2.5 2.1 / 2.2 / 2.3 in 5.0 mm posts, 8 mm deep. The chamfered corner is at the M2 1.6 end."""
    base = box(-4, -6, 0, 52, 6, 2.0).edges("|Z").fillet(1.5).edges(">Z").chamfer(0.4)
    base = base.cut(box(-5, -7, -1, -1.5, -3.5, 3))
    for i, (d_post, pilot) in enumerate(((4.2, 1.6), (4.2, 1.7), (4.2, 1.8), (5.0, 2.1), (5.0, 2.2), (5.0, 2.3))):
        x = i * 9.6
        base = base.union(cyl(d_post, 9.0, x=x, z=1.0)).cut(cyl(pilot, 8.5, x=x, z=2.0))
    return base


# ----------------------------------------------------------------------------------------- assembly
def parts(kind, wide=True):
    head = head_zero_parts() if kind == "zero" else head_hq_parts(wide=wide)
    return {"fixed": {"ceiling stud": (sm.ceiling_stud(), "steel")},
            "pan": {"yoke": (yoke(kind), "petg"), "stud thumb nut": (spm.stud_knob(), "knob"),
                    "tilt screws": (tilt_screws(kind), "knob")},
            "head": head}


def assembly(kind, pan=0.0, tilt=45.0, wide=True):
    colours = dict(petg=(0.15, 0.16, 0.17), knob=(0.85, 0.42, 0.10), steel=(0.75, 0.77, 0.80),
                   pcb=(0.12, 0.48, 0.24), lens=(0.08, 0.08, 0.09), glass=(0.30, 0.45, 0.65),
                   white=(0.93, 0.93, 0.93), port=(0.70, 0.72, 0.75), black=(0.1, 0.1, 0.1),
                   cooler=(0.55, 0.58, 0.62), ribbon=(0.85, 0.65, 0.25))
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
    """Kit screws per mount: {kind: {screw: count}}."""
    out = {}
    for kind in ("zero", "hq"):
        if kind == "zero":
            _, _, _, s = _zero_case_frame()
        else:
            _, _, _, s = _hq_frame()
        n = {}
        for k, v in s.items():
            size = k.split()[0]
            n[f"{size} x 6 pan head"] = n.get(f"{size} x 6 pan head", 0) + len(v)
        out[kind] = n
    return out


if __name__ == "__main__":
    for kind in ("zero", "hq"):
        print(kind, "half %.1f, swing %.1f, tilt-axis depth %d mm, screw %.1f mm, hole %.1f mm" % (
            head_half(kind), _radius(kind, kind != "zero"), tilt_depth(kind), screw_len(), spm.hole_depth()))
    print(bom())
