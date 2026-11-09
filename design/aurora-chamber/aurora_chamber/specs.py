"""Equipment in the chamber as primitive specs (boxes, cylinders, rings, tubes), shared by the PyVista scene
(scene.py) and the STEP/STL export (cad.py), so both are built from the same numbers.

Each spec is a dict with a kind, its geometry, a colour and a name:
  box    lo, hi                         axis-aligned box between two corners
  obox   center, size, yaw              box turned by yaw (deg) about z
  cyl    center, direction, r, h        solid cylinder
  ring   center, normal, r_in, r_out, t annulus extruded along its normal
  tube   points, r                      round tube along a spline through the points
  ribbon points, width, normal          flat strip (drawing only; not exported)
"""

import numpy as np

from . import robot
from .params import (BASE_BACK, COLUMN_XY, DOME_C, ESTOP_C, EXF_DECK_Z, EXF_STROKE, EXF_X0, EXF_X1, EXF_Y0,
                     EXF_Y1, FILTER_C, GB_D, GB_H, GB_W, MICRO_OBJ_C, MICRO_STAGE_C, PLATE_C, PLATE_SIZE, RISER_H,
                     SHELF_T, SPOOL_C, T6, TERMINAL_BOX, TIP_C, TRAY_SIZE, CEILING_SLOT)

X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)

STAINLESS = "#c9ced3"
ALUMINIUM = "#d7dadd"
BLACK = "#26282b"
BLUE_TUBE = "#1f6fd1"
RED_HUB = "#d6262b"
BLUE_TAPE = "#2546c4"
WHITE = "#f2f2f2"
YELLOW = "#f2c200"
EPSON_WHITE = "#eceef0"
EPSON_GREY = "#cfd3d7"


def Box(lo, hi, color, name):
    return dict(kind="box", lo=np.asarray(lo, float), hi=np.asarray(hi, float), color=color, name=name)


def BoxC(center, size, color, name):
    c, s = np.asarray(center, float), np.asarray(size, float)
    return Box(c - s / 2, c + s / 2, color, name)


def OBox(center, size, yaw, color, name):
    return dict(kind="obox", center=np.asarray(center, float), size=np.asarray(size, float), yaw=float(yaw),
                color=color, name=name)


def Cyl(center, direction, r, h, color, name):
    return dict(kind="cyl", center=np.asarray(center, float), direction=np.asarray(direction, float), r=float(r),
                h=float(h), color=color, name=name)


def Ring(center, normal, r_in, r_out, t, color, name):
    return dict(kind="ring", center=np.asarray(center, float), normal=np.asarray(normal, float), r_in=float(r_in),
                r_out=float(r_out), t=float(t), color=color, name=name)


def Tube(points, r, color, name):
    return dict(kind="tube", points=np.asarray(points, float), r=float(r), color=color, name=name)


def Ribbon(points, width, normal, color, name):
    return dict(kind="ribbon", points=np.asarray(points, float), width=float(width), normal=normal, color=color,
                name=name)


# --- Exfoliator ------------------------------------------------------------------------------------------
# From the antechamber end: the gantry with its cable chain, the Montalvo controller, the press column with
# the roller under the tape spool, the rear linear stage with the white substrate plate the Epson drops the
# chip tray on, the heater/fan box, the e-stop on the LED source, and the microscope.

def exfoliator_specs():
    out = []
    x0, x1, y0, y1, dz = EXF_X0, EXF_X1, EXF_Y0, EXF_Y1, EXF_DECK_Z
    xb = ESTOP_C[0] - 240.0     # the breadboard stops before the fan box; the far-end items stand on the deck
    out.append(Box((x0, y0, dz - 13), (xb, y1, dz), BLACK, "breadboard"))
    for px in (x0 + 40, (x0 + xb) / 2, xb - 40):
        for py in (y0 + 40, y1 - 40):
            out.append(Cyl((px, py, (dz - 13) / 2), Z, 14, dz - 13, STAINLESS, "breadboard post"))
    out.append(Box((x0, y0 - 18, dz - 30), (xb, y0 + 4, dz + 22), "#2b5fd9", "slotted cable rail"))
    # gantry at the antechamber end: Z axis on a short X axis, drag chain, blue vacuum lines
    gx, gy = x0 + 90, y0 + 190
    out.append(BoxC((gx, gy, dz + 25), (150, 300, 50), ALUMINIUM, "gantry X axis"))
    out.append(BoxC((gx, gy - 30, dz + 200), (60, 70, 300), BLACK, "gantry Z axis"))
    out.append(BoxC((gx + 10, gy - 70, dz + 380), (60, 60, 60), BLACK, "gantry Z motor"))
    for dzz in (0, 16):
        pts = [(gx + 20, gy - 80, dz + 260 + dzz), (gx + 120, gy - 120, dz + 300 + dzz),
               (gx + 260, gy - 150, dz + 140 + dzz), (gx + 330, y0 + 10, dz + 40 + dzz)]
        out.append(Tube(pts, 6, BLUE_TUBE, "vacuum line"))
    out.append(BoxC((x0 + 140, y0 + 30, dz + 70), (110, 35, 80), "#3a8ee8", "Montalvo controller"))
    # rear linear stage: 400 mm-stroke ball-screw axis along x with the white substrate plate
    sy = PLATE_C[1]
    ax_len = EXF_STROKE + 210.0
    ax_x0 = PLATE_C[0] - 0.35 * ax_len
    out.append(Box((ax_x0, sy - 40, dz), (ax_x0 + ax_len, sy + 40, dz + 40), ALUMINIUM, "rear stage axis"))
    out.append(Cyl((ax_x0 + ax_len / 2, sy, dz + 48), X, 8, ax_len - 20, "#b0b4b8", "rear stage screw"))
    out.append(BoxC((ax_x0 + ax_len + 38, sy, dz + 30), (76, 57, 57), BLACK, "rear stage motor"))
    pz = PLATE_C[2]
    out.append(BoxC((PLATE_C[0], sy, (dz + 40 + pz) / 2), (90, 70, pz - dz - 40), BLACK, "plate carriage"))
    out.append(substrate_plate_spec())
    # press column with the roller under the supply spool
    cx, cy = COLUMN_XY
    out.append(BoxC((cx, cy, dz + 160), (150, 26, 320), ALUMINIUM, "press column"))
    tx, ty, tz = TIP_C
    out.append(BoxC((tx, ty, tz + 75), (60, 40, 110), ALUMINIUM, "roller holder"))
    out.append(Cyl((tx, ty, tz + 12), Y, 12, 30, YELLOW, "roller"))
    out.append(BoxC((tx, ty, tz - 6), (200, 70, 8), "#9aa3ad", "carrier on the front stage"))
    sx, sy_, sz = SPOOL_C
    out.append(Ring((sx, sy_, sz), Y, 22, 52, 46, RED_HUB, "spool hub"))
    out.append(Ring((sx, sy_, sz), Y, 52, 76, 40, BLUE_TAPE, "tape on the spool"))
    out.append(BoxC((sx - 120, sy_ + 10, sz), (90, 60, 60), BLACK, "reel motor"))
    out.append(Ribbon([(sx - 30, sy_, sz - 72), (tx + 30, ty, tz + 40), (tx, ty, tz + 25), (tx - 40, ty, tz + 30),
                       (tx - 90, ty, tz + 120)], 17, Y, "#5b8def", "tape web"))
    # heater/fan box, e-stop on the LED source, microscope at the far end
    out.append(BoxC((ESTOP_C[0] - 150, y0 + 90, 80), (150, 140, 160), "#1b1c1e", "heater/fan box"))
    ex, ey, ez = ESTOP_C
    out.append(BoxC((ex, ey, (ez - 35) / 2), (140, 110, ez - 35), "#e9e9e9", "LED source"))
    out.append(BoxC((ex, ey, ez), (80, 80, 70), YELLOW, "e-stop box"))
    out.append(Cyl((ex, ey, ez + 50), Z, 22, 30, RED_HUB, "e-stop"))
    mx, my, mz = MICRO_STAGE_C
    out.append(BoxC((mx, my + 20, mz - 10), (200, 160, 20), "#2d3034", "microscope XY stage"))
    ox, oy, oz = MICRO_OBJ_C
    out.append(BoxC((mx, my + 20, (mz - 20) / 2), (120, 100, mz - 20), "#2d3034", "microscope stage support"))
    out.append(Box((x1 - 120, my + 120, 0), (x1 - 10, y1, dz + 420), "#e4e6e8", "microscope stand"))
    out.append(Box((ox - 70, oy - 60, oz + 40), (x1 - 10, y1, oz + 200), "#e4e6e8", "microscope arm and head"))
    out.append(Cyl((ox, oy, oz + 20), Z, 16, 50, "#2d3034", "microscope objective"))
    return out


def substrate_plate_spec():
    return BoxC((PLATE_C[0], PLATE_C[1], PLATE_C[2] - 4), (PLATE_SIZE[0], PLATE_SIZE[1], 8), "#e6e8ea",
                "substrate plate")


def tray_spec():
    """8 x 8 chip tray in its metal holder, on the substrate plate (simplified to its holder)."""
    return BoxC(PLATE_C + np.array([0.0, 0.0, TRAY_SIZE[2] / 2]), TRAY_SIZE, "#c3c8cd", "chip tray")


# --- Epson T6-B602S ------------------------------------------------------------------------------------------

def _seg(a, b, w, z0, z1, end_r, color, name):
    """Link from a to b (xy), width w, between heights z0 and z1, with rounded ends."""
    vec = b - a
    mid = (a + b) / 2
    zc, h = (z0 + z1) / 2, z1 - z0
    return [OBox((mid[0], mid[1], zc), (np.linalg.norm(vec), w, h), np.degrees(np.arctan2(vec[1], vec[0])), color,
                 name),
            Cyl((a[0], a[1], zc), Z, end_r, h, color, name), Cyl((b[0], b[1], zc), Z, end_r, h, color, name)]


def duct_path(j1, j2, riser=None):
    """Centre line of the black corrugated duct: base top (over J1) to the top of arm 2 (over J2), arching to
    just under the ceiling."""
    bz = RISER_H if riser is None else riser
    top_z, dt = bz + T6["arm2"][1] + 25.0, robot.duct_top(bz) - 18.0
    mid = (j1 + j2) / 2
    return [(j1[0], j1[1], top_z), (j1[0], j1[1], (top_z + dt) / 2 + 20), (*(j1 + 0.25 * (j2 - j1)), dt - 8),
            (mid[0], mid[1], dt), (*(j1 + 0.75 * (j2 - j1)), dt - 8), (j2[0], j2[1], (top_z + dt) / 2 + 20),
            (j2[0], j2[1], top_z)]


def scara_specs(target=None, quill_z=None, riser=None):
    """Epson T6-B602S with J3 over `target` (x, y) and the tool at `quill_z`; returns (specs, tool point)."""
    bx, by, bz = robot.base_xyz(riser)
    target = robot.PARK_J3 if target is None else np.asarray(target, float)[:2]
    quill_z = bz + 120.0 if quill_z is None else quill_z
    j1, j2, j3 = robot.joints(target)
    u = np.asarray(BASE_BACK, float)
    yaw = np.degrees(np.arctan2(u[1], u[0])) - 90.0
    w, front, back = T6["base"]

    def base_box(z0, z1, b0, b1, width, color, name):
        c = j1 + u * (b0 + b1) / 2
        return OBox((c[0], c[1], (z0 + z1) / 2), (width, b1 - b0, z1 - z0), yaw, color, name)

    out = [base_box(SHELF_T, bz, -front - 40, back + 40, w + 80, "#b9bec4", "riser block"),
           base_box(bz, bz + T6["arm1"][0], -front, back, w, EPSON_WHITE, "base"),
           base_box(bz + T6["arm1"][0], bz + T6["box"][0], 70.0, back, w, EPSON_WHITE, "base"),
           base_box(bz + T6["box"][0], bz + T6["box"][1], -10.0, back, w, EPSON_GREY, "controller box"),
           Cyl((bx, by, bz + T6["box"][1] + 12), Z, 12, 24, "#ff9d2e", "lamp")]
    out += _seg(j1, j2, T6["arm1_w"], bz + T6["arm1"][0], bz + T6["arm1"][1], 67.0, EPSON_WHITE, "arm 1")
    out += _seg(j2, j3, T6["arm2_w"], bz + T6["arm2"][0], bz + T6["arm2"][1], T6["arm2_end"], EPSON_GREY, "arm 2")
    out.append(Cyl((j3[0], j3[1], bz + T6["arm2"][0] - 12), Z, 30, 24, "#2f5fb3", "J3 ring"))
    shaft_top = robot.shaft_top_z(quill_z)
    out.append(Cyl((j3[0], j3[1], (quill_z + shaft_top) / 2), Z, T6["shaft_r"], shaft_top - quill_z, "#b5b9bd",
                   "J3 shaft"))
    out.append(Cyl((j3[0], j3[1], shaft_top - 6), Z, T6["nut_r"], 12, "#3a3d41", "shaft nut"))
    out.append(BoxC((j3[0], j3[1], quill_z - 15), (40, 40, 30), "#3a3d41", "vacuum tool"))
    out.append(Tube(duct_path(j1, j2, bz), 18, BLACK, "cable duct"))
    return out, np.array([j3[0], j3[1], quill_z])


def envelope_specs(risers=None):
    """The swept volume as the cylinders round J1 that robot_clearance uses (full J1 turn), each running from
    its bottom at the lowest riser to its top at the highest: the shaft out to 619 mm from the tool's lowest
    point to the shaft top, arm 2 out to 658.5 mm, and the duct arch out to 365 mm. Clip to the box to draw."""
    rs = np.atleast_1d(robot.RISER_RANGE if risers is None else risers).astype(float)
    lo, hi = robot.envelope(rs.min()), robot.envelope(rs.max())
    bx, by = robot.SCARA_XY
    bands = [("shaft", lo["shaft_r"], lo["tool_low"], hi["shaft_top"]),
             ("arm 2", lo["arm2_r"], lo["arm2_low"], hi["arm2_top"]),
             ("duct arch", lo["arch_r"], lo["arch_low"], hi["arch_top"])]
    return [Cyl((bx, by, (za + zb) / 2), Z, r, zb - za, "#7c3aed", f"swept volume: {n}") for n, r, za, zb in bands]


# --- Ceiling ----------------------------------------------------------------------------------------------

def ceiling_specs():
    out = []
    (xa, ya, _), (xb, yb, _) = CEILING_SLOT
    out.append(Box((min(xa, xb), min(ya, yb), GB_H - 3), (max(xa, xb), max(ya, yb), GB_H), "#7f878f", "ceiling recess"))
    (xa, ya, _), (xb, yb, _) = TERMINAL_BOX
    out.append(Box((min(xa, xb), (ya + yb) / 2 - 35, GB_H - 45), (max(xa, xb), (ya + yb) / 2 + 35, GB_H), BLACK,
                   "terminal rail"))
    out.append(Cyl((FILTER_C[0], FILTER_C[1], GB_H - 75), Z, 34, 150, WHITE, "filter cartridge"))
    out.append(Cyl(DOME_C - (0, 0, 15), Z, 60, 30, WHITE, "Amcrest base"))
    return out


def interior_bounds():
    return (0.0, GB_W, 0.0, GB_D, 0.0, GB_H)
