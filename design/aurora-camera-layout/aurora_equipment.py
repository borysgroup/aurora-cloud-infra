"""Geometry of the Aurora glovebox and the equipment inside it, in millimetres.

Positions are measured on the metric 3D reconstruction of the in-person
walkthrough video (dense cloud, mesh and solved keyframe poses, shared privately
for issue #23). Only the derived numbers are kept here. Read positions as
+/-30-50 mm and the absolute size as +/-5 %: one tape reading (the QR sign's
width, 279.4 mm in the reconstruction, or the open-side window frame's inner
length) gives SCALE = measured / modelled, which rescales the box and every
measured position. The Epson and the camera hardware keep their catalogue sizes.

Scene frame: x runs along the box from the antechamber-end wall (x = 0) to the
far end, y runs from the open side (the window that was off during the
walkthrough, y = 0 at deck level) to the far window, z is up from the deck.
"""

import numpy as np
import pyvista as pv

from scene_primitives import box, box_from, cyl, ring, tube_path

SCALE = 1.0

# The reconstruction's own frame: origin at the bottom-left corner of the QR sign
# on the antechamber-end wall, x into the box from the open side, y along the box
# (negative away from the antechamber), z up.
DROP_WALL_Y = 15.0      # antechamber-end inner wall
DROP_FRONT_X = -162.0   # open-side window frame, at deck level
DROP_DECK_Z = -460.0    # deck


def from_drop(x, y, z=DROP_DECK_Z):
    """Scene position of a point measured in the reconstruction's frame."""
    return SCALE * np.array([DROP_WALL_Y - y, x - DROP_FRONT_X, z - DROP_DECK_Z], float)


# --- Glovebox shell -----------------------------------------------------------

GB_W = SCALE * 1200.0     # antechamber-end wall to the far end wall (drop y +15 to -1185)
GB_D = SCALE * 1120.0     # open-side frame to the far window, at the deck (drop x -162 to +958)
GB_H = SCALE * 790.0      # deck to ceiling (drop z -460 to +330)
FRONT_LEAN = SCALE * 57.0  # the open-side frame is 57 mm further in at the ceiling than at the deck
BACK_LEAN = SCALE * 60.0   # the far window leans in by about the same
WINDOW_SETBACK = FRONT_LEAN
WALL_T = 12.0
STAND_H = 880.0
OPENING = SCALE * np.array([50.0, 1150.0, 55.0, 765.0])  # open-side window opening: x0, x1, z0, z1
FLANGE_PITCH = SCALE * 95.0   # studs round the opening, about 45 mm long, acorn nuts on some
GLOVE_R = 102.0               # 8-inch glove ports, two per side (not in the reconstruction)
GLOVE_X = (0.29 * GB_W, 0.71 * GB_W)
GLOVE_Z = SCALE * 400.0

STAINLESS = "#c9ced3"
STAINLESS_DARK = "#9aa1a8"
ALUMINIUM = "#d7dadd"
BLACK = "#26282b"
BLUE_TUBE = "#1f6fd1"
RED_HUB = "#d6262b"
BLUE_TAPE = "#2546c4"
WHITE = "#f2f2f2"
YELLOW = "#f2c200"
EPSON_WHITE = "#eceef0"
EPSON_GREY = "#cfd3d7"


def front_window_y(z):
    """y of the sloped open-side window at height z."""
    return FRONT_LEAN * z / GB_H


def back_window_y(z):
    """y of the sloped far window at height z."""
    return GB_D - BACK_LEAN * z / GB_H


def _quad(p0, p1, p2, p3):
    return pv.PolyData(np.array([p0, p1, p2, p3], float), faces=[4, 0, 1, 2, 3])


def _end_wall(x0, x1):
    """End wall following both window slopes."""
    face = _quad((x0, 0, 0), (x0, GB_D, 0), (x0, back_window_y(GB_H), GB_H), (x0, front_window_y(GB_H), GB_H))
    return face.extrude((x1 - x0, 0, 0), capping=True)


def _window(side):
    """Glass, glove-port rings, flange and its studs for one long side."""
    if side == "front":
        y_at, n = front_window_y, np.array([0.0, -GB_H, FRONT_LEAN])
    else:
        y_at, n = back_window_y, np.array([0.0, GB_H, BACK_LEAN])
    n /= np.linalg.norm(n)
    glass = _quad((0, y_at(0), 0), (GB_W, y_at(0), 0), (GB_W, y_at(GB_H), GB_H), (0, y_at(GB_H), GB_H))
    ports = pv.merge([ring((gx, y_at(GLOVE_Z), GLOVE_Z), n, GLOVE_R, GLOVE_R + 25.0, 34.0) for gx in GLOVE_X])
    x0, x1, z0, z1 = OPENING
    out = 30.0 * np.sign(n[1])     # the flange stands just outside the glass
    frame = []
    for za, zb in ((-10.0, z0), (z1, GB_H + 10.0)):
        ym = y_at((za + zb) / 2)
        frame.append(box_from((-10, min(ym, ym + out), za), (GB_W + 10, max(ym, ym + out), zb)))
    for xa, xb in ((-10.0, x0), (x1, GB_W + 10.0)):
        frame.append(pv.Line(((xa + xb) / 2, y_at(0) + out / 2, 0), ((xa + xb) / 2, y_at(GB_H) + out / 2, GB_H))
                     .tube(radius=(xb - xa) / 2, n_sides=4))
    studs = []
    for x in np.arange(x0 + 25.0, x1 - 10.0, FLANGE_PITCH):
        for z in ((z0 - 10.0), (z1 + 10.0)):
            studs.append(cyl((x, y_at(z) + out + 22.0 * np.sign(out), z), n, 3.2, 45.0, res=8))
    for x in (x0 - 25.0, x1 + 25.0):
        for z in np.arange(z0 + 40.0, z1 - 20.0, FLANGE_PITCH):
            studs.append(cyl((x, y_at(z) + out + 22.0 * np.sign(out), z), n, 3.2, 45.0, res=8))
    return glass, ports, pv.merge(frame), pv.merge(studs)


def glovebox_shell():
    """Returns {name: (mesh, style)} for the walls, so each can be styled separately."""
    parts = {}
    parts["floor"] = (box_from((0, 0, -WALL_T), (GB_W, GB_D, 0)), dict(color=STAINLESS, specular=0.6))
    parts["left_wall"] = (_end_wall(-WALL_T, 0), dict(color=STAINLESS, specular=0.5))
    parts["right_wall"] = (_end_wall(GB_W, GB_W + WALL_T), dict(color=STAINLESS, specular=0.5))
    parts["ceiling"] = (box_from((0, front_window_y(GB_H), GB_H), (GB_W, back_window_y(GB_H), GB_H + WALL_T)),
                        dict(color=STAINLESS, specular=0.4))
    front_glass, front_ports, front_frame, front_studs = _window("front")
    back_glass, back_ports, back_frame, back_studs = _window("back")
    parts["window"] = (front_glass, dict(color="#bfe3ff", opacity=0.10, specular=1.0))
    parts["back_window"] = (back_glass, dict(color="#bfe3ff", opacity=0.14, specular=1.0))
    parts["glove_ports"] = (front_ports, dict(color=WHITE, specular=0.3))
    parts["back_glove_ports"] = (back_ports, dict(color=WHITE, specular=0.3))
    parts["window_frame"] = (pv.merge([front_frame, front_studs]), dict(color=STAINLESS_DARK, specular=0.6))
    parts["back_window_frame"] = (pv.merge([back_frame, back_studs]), dict(color=STAINLESS_DARK, specular=0.6))
    return parts


SIGN = (from_drop(0.0, 0.0, 0.0), from_drop(279.4, 0.0, 215.9))   # US Letter landscape, bottom-left at the origin


def wall_signs():
    """The bug-report sign on the antechamber-end wall (blank here: just its outline)."""
    (_, y0, z0), (_, y1, z1) = SIGN
    c, s = ((y0 + y1) / 2, (z0 + z1) / 2), (y1 - y0, z1 - z0)
    return [(box((1.5, c[0], c[1]), (3, s[0], s[1])), WHITE),
            (box((2.5, c[0], c[1] - 5), (2, 0.72 * s[0], 0.9 * s[1])), "#1d2430")]


def stand():
    legs = []
    for x in (40, GB_W - 40):
        for y in (60, GB_D - 60):
            legs.append(box((x, y, -STAND_H / 2 - WALL_T), (50, 50, STAND_H)))
            legs.append(cyl((x, y, -STAND_H - WALL_T - 20), (0, 0, 1), 32, 14))
    rails = [box((GB_W / 2, y, -STAND_H + 120), (GB_W - 30, 40, 40)) for y in (60, GB_D - 60)]
    rails += [box((GB_W / 2, y, -60), (GB_W - 30, 50, 60)) for y in (60, GB_D - 60)]
    braces = [pv.Line((40, y, -STAND_H + 120), (GB_W - 40, y, -90)).tube(radius=18, n_sides=8) for y in (60, GB_D - 60)]
    return pv.merge(legs + rails + braces)


# --- Antechambers ---------------------------------------------------------------
# Large antechamber: inner door hub about 250 mm below the sign, door about 380 mm
# across (LC Technology's 15-inch antechamber). The mini antechamber's tube shows at
# the lower open-side corner of the same wall in the 6 Nov photo; its position is
# read off that photo only.

ANTE_DOOR_C = from_drop(297.0, 0.0, -249.0) * np.array([0.0, 1.0, 1.0])
ANTE_DOOR_R = SCALE * 190.0
MINI_C = np.array([0.0, SCALE * 150.0, SCALE * 150.0])


def antechambers():
    """Large antechamber on the end wall, mini antechamber in the lower corner."""
    _, cy, cz = ANTE_DOOR_C
    big = [ring((8, cy, cz), (1, 0, 0), 0, ANTE_DOOR_R, 12),                       # inner door
           ring((2, cy, cz), (1, 0, 0), ANTE_DOOR_R - 15, ANTE_DOOR_R + 22, 10),   # flange
           cyl((16, cy, cz), (1, 0, 0), 22, 18),                                   # hub
           cyl((-WALL_T - 305, cy, cz), (1, 0, 0), 205, 610)]                      # tube, outside
    _, my, mz = MINI_C
    mini = [cyl((-WALL_T - 150, my, mz), (1, 0, 0), 80, 300),   # tube, outside
            cyl((55, my, mz), (1, 0, 0), 80, 110),              # tube, inside
            ring((112, my, mz), (1, 0, 0), 0, 88, 12),          # inner door
            box((122, my, mz), (10, 150, 18))]                  # latch bar
    return pv.merge(big), pv.merge(mini)


# --- Exfoliator: along the open side, x 165-1165 -----------------------------------
# From the antechamber end: the gantry with its cable chain, the Montalvo
# controller, the press column with the roller under the tape spool, the rear
# linear stage with the white substrate plate the Epson drops the chip tray on,
# the heater/fan box, the e-stop on the LED source, and the microscope.

EXF_X0, EXF_X1 = from_drop(0, -150)[0], from_drop(0, -1150)[0]
EXF_Y0, EXF_Y1 = from_drop(-130, 0)[1], from_drop(370, 0)[1]
EXF_DECK_Z = SCALE * 160.0                          # breadboard top on its posts (drop z -300)
EXF_C = np.array([(EXF_X0 + EXF_X1) / 2, (EXF_Y0 + EXF_Y1) / 2, 0.0])
EXF_STROKE = 400.0
COLUMN_XY = from_drop(106, -547)[:2]                # vertical press column
SPOOL_C = from_drop(150, -720, -156)                # supply spool (red flange, blue tape)
TIP_C = from_drop(130, -690, -245)                  # roller on the tape: the exfoliation point
PLATE_C = from_drop(256, -502, -245)                # white substrate plate on the rear stage (top)
PLATE_SIZE = SCALE * np.array([160.0, 180.0])
ESTOP_C = from_drop(43, -992, -274)
MICRO_STAGE_C = from_drop(176, -966, -236)
MICRO_OBJ_C = from_drop(219, -1102, -192)


def exfoliator():
    """Returns a list of (mesh, color) for the exfoliator."""
    out = []
    x0, x1, y0, y1, dz = EXF_X0, EXF_X1, EXF_Y0, EXF_Y1, EXF_DECK_Z
    xb = ESTOP_C[0] - 240.0     # the breadboard stops before the fan box; the far-end items stand on the deck
    out.append((box_from((x0, y0, dz - 13), (xb, y1, dz)), BLACK))                        # breadboard
    for px in (x0 + 40, (x0 + xb) / 2, xb - 40):
        for py in (y0 + 40, y1 - 40):
            out.append((cyl((px, py, (dz - 13) / 2), (0, 0, 1), 14, dz - 13), STAINLESS))
    out.append((box_from((x0, y0 - 18, dz - 30), (xb, y0 + 4, dz + 22)), "#2b5fd9"))    # slotted cable rail, front
    # gantry at the antechamber end: Z axis on a short X axis, drag chain, blue vacuum lines
    gx, gy = x0 + 90, y0 + 190
    out.append((box((gx, gy, dz + 25), (150, 300, 50)), ALUMINIUM))
    out.append((box((gx, gy - 30, dz + 200), (60, 70, 300)), BLACK))
    out.append((box((gx + 10, gy - 70, dz + 380), (60, 60, 60)), BLACK))                 # Z motor
    for dzz in (0, 16):
        pts = [(gx + 20, gy - 80, dz + 260 + dzz), (gx + 120, gy - 120, dz + 300 + dzz),
               (gx + 260, gy - 150, dz + 140 + dzz), (gx + 330, y0 + 10, dz + 40 + dzz)]
        out.append((tube_path(pts, 6), BLUE_TUBE))
    out.append((box((x0 + 140, y0 + 30, dz + 70), (110, 35, 80)), "#3a8ee8"))             # Montalvo controller
    # rear linear stage: 400 mm-stroke ball-screw axis along x with the white substrate plate
    sy = PLATE_C[1]
    ax_len = EXF_STROKE + 210.0
    ax_x0 = PLATE_C[0] - 0.35 * ax_len
    out.append((box_from((ax_x0, sy - 40, dz), (ax_x0 + ax_len, sy + 40, dz + 40)), ALUMINIUM))
    out.append((cyl((ax_x0 + ax_len / 2, sy, dz + 48), (1, 0, 0), 8, ax_len - 20), "#b0b4b8"))
    out.append((box((ax_x0 + ax_len + 38, sy, dz + 30), (76, 57, 57)), BLACK))           # NEMA 23
    pz = PLATE_C[2]
    out.append((box((PLATE_C[0], sy, (dz + 40 + pz) / 2), (90, 70, pz - dz - 40)), BLACK))  # carriage riser
    out.append((box((PLATE_C[0], sy, pz - 4), (PLATE_SIZE[0], PLATE_SIZE[1], 8)), "#e6e8ea"))
    # press column with the roller under the supply spool
    cx, cy = COLUMN_XY
    out.append((box((cx, cy, dz + 160), (150, 26, 320)), ALUMINIUM))
    tx, ty, tz = TIP_C
    out.append((box((tx, ty, tz + 75), (60, 40, 110)), ALUMINIUM))
    out.append((cyl((tx, ty, tz + 12), (0, 1, 0), 12, 30), YELLOW))                       # roller
    out.append((box((tx, ty, tz - 6), (200, 70, 8)), "#9aa3ad"))                           # carrier on the front stage
    sx, sy_, sz = SPOOL_C
    out.append((ring((sx, sy_, sz), (0, 1, 0), 22, 52, 46), RED_HUB))
    out.append((ring((sx, sy_, sz), (0, 1, 0), 52, 76, 40), BLUE_TAPE))
    out.append((box((sx - 120, sy_ + 10, sz), (90, 60, 60)), BLACK))                       # reel motor
    web = pv.Spline(np.array([(sx - 30, sy_, sz - 72), (tx + 30, ty, tz + 40), (tx, ty, tz + 25),
                              (tx - 40, ty, tz + 30), (tx - 90, ty, tz + 120)]), 60)
    out.append((web.ribbon(width=17, normal=(0, 1, 0)), "#5b8def"))
    # heater/fan box, e-stop on the LED source, microscope at the far end
    out.append((box((ESTOP_C[0] - 150, y0 + 90, 80), (150, 140, 160)), "#1b1c1e"))
    ex, ey, ez = ESTOP_C
    out.append((box((ex, ey, (ez - 35) / 2), (140, 110, ez - 35)), "#e9e9e9"))             # LED source
    out.append((box((ex, ey, ez), (80, 80, 70)), YELLOW))
    out.append((cyl((ex, ey, ez + 50), (0, 0, 1), 22, 30), RED_HUB))
    mx, my, mz = MICRO_STAGE_C
    out.append((box((mx, my + 20, mz - 10), (200, 160, 20)), "#2d3034"))                 # XY stage
    ox, oy, oz = MICRO_OBJ_C
    out.append((box((mx, my + 20, (mz - 20) / 2), (120, 100, mz - 20)), "#2d3034"))       # stage support
    out.append((box_from((x1 - 120, my + 120, 0), (x1 - 10, y1, dz + 420)), "#e4e6e8"))   # stand
    out.append((box_from((ox - 70, oy - 60, oz + 40), (x1 - 10, y1, oz + 200)), "#e4e6e8"))  # arm and head
    out.append((cyl((ox, oy, oz + 20), (0, 0, 1), 16, 50), "#2d3034"))                    # objective
    return out


def optics_bench():
    """Kept for the renderer's scene list; the LED source and e-stop are part of exfoliator()."""
    return []


# --- Epson T6-B602S SCARA, standing on a riser behind the exfoliator --------------
#
# Model settled from the reconstruction: J1 to J2 measures about 300 mm and J2 to
# J3 about 260 mm in the parked pose (T6-B: 325 + 275 mm; T3-B: 225 + 175 mm), the
# arm 2 housing is about 350 x 170 x 200 mm, and the substrate plate the robot
# drops the tray on is 590 mm from J1, out of a T3-B's 400 mm reach. Sizes below
# are from Epson's T6-B outline drawing (T-B manual rev. 6, section 2.3.2),
# measured from the bottom of the base. The arm 2 top sits at drop z ~ +155 (the
# fittings on it reach +185), which puts the base on a riser ~150 mm above the deck.

EPSON_L1, EPSON_L2 = 325.0, 275.0
EPSON_STROKE = 200.0
T6 = dict(arm1=(209.5, 259.5), arm2=(272.5, 465.3), box=(289.2, 465.3), shaft_top=590.5, duct_max=700.0,
          arm1_w=90.0, arm2_w=135.5, arm2_end=58.5, shaft_r=10.0, nut_r=19.0, base=(150.0, 35.0, 160.0))
SCARA_BASE = np.r_[from_drop(670, -925)[:2], SCALE * 152.0]   # J1 axis and the bottom of the base (riser top)
BASE_BACK = np.array([0.0, 1.0])     # base and cable outlet towards the far window
SCARA_PARK_J3 = from_drop(568, -895)[:2]                    # J3 in the parked pose


def _seg(a, b, w, z0, z1, end_r=None):
    """Link from a to b (xy), width w, between heights z0 and z1, with rounded ends."""
    vec = b - a
    seg = box((0, 0, 0), (np.linalg.norm(vec), w, z1 - z0))
    seg.rotate_z(np.degrees(np.arctan2(vec[1], vec[0])), inplace=True)
    mid = (a + b) / 2
    seg.translate((mid[0], mid[1], (z0 + z1) / 2), inplace=True)
    r = w / 2 if end_r is None else end_r
    return [seg] + [cyl((p[0], p[1], (z0 + z1) / 2), (0, 0, 1), r, z1 - z0) for p in (a, b)]


def scara_joints(target):
    """J1, J2, J3 (xy) for the arm reaching `target` (xy), elbow on the left."""
    bx, by = SCARA_BASE[:2]
    dx, dy = target[0] - bx, target[1] - by
    r = np.clip(np.hypot(dx, dy), abs(EPSON_L1 - EPSON_L2) + 1, EPSON_L1 + EPSON_L2 - 1)
    elbow = np.arccos((r**2 - EPSON_L1**2 - EPSON_L2**2) / (2 * EPSON_L1 * EPSON_L2))
    t1 = np.arctan2(dy, dx) - np.arctan2(EPSON_L2 * np.sin(elbow), EPSON_L1 + EPSON_L2 * np.cos(elbow))
    j1 = np.array([bx, by])
    j2 = j1 + EPSON_L1 * np.array([np.cos(t1), np.sin(t1)])
    j3 = j2 + EPSON_L2 * np.array([np.cos(t1 + elbow), np.sin(t1 + elbow)])
    return j1, j2, j3


def _duct_top(bz):
    """Duct arch's top: 700 mm above the base in Epson's drawing, but no higher than just under the ceiling."""
    return min(bz + T6["duct_max"], GB_H - 6.0)


def scara(target=None, quill_z=None):
    """Epson T6-B602S, arm posed over `target` (x, y); returns (parts, tool point)."""
    out = []
    bx, by, bz = SCARA_BASE
    target = SCARA_PARK_J3 if target is None else np.asarray(target, float)[:2]
    quill_z = bz + 120.0 if quill_z is None else quill_z
    j1, j2, j3 = scara_joints(target)
    u, v = BASE_BACK, np.array([-BASE_BACK[1], BASE_BACK[0]])
    w, front, back = T6["base"]

    def base_box(z0, z1, b0, b1, width):
        c = j1 + u * (b0 + b1) / 2
        m = box((0, 0, 0), (width, b1 - b0, z1 - z0))
        m.rotate_z(np.degrees(np.arctan2(u[1], u[0])) - 90.0, inplace=True)
        return m.translate((c[0], c[1], (z0 + z1) / 2), inplace=False)

    out.append((base_box(SCALE * 13.0, bz, -front - 40, back + 40, w + 80), "#b9bec4"))      # riser block
    out.append((base_box(bz, bz + T6["arm1"][0], -front, back, w), EPSON_WHITE))             # lower base
    out.append((base_box(bz + T6["arm1"][0], bz + T6["box"][0], 70.0, back, w), EPSON_WHITE))
    out.append((base_box(bz + T6["box"][0], bz + T6["box"][1], -10.0, back, w), EPSON_GREY))  # controller box
    out.append((cyl((bx, by, bz + T6["box"][1] + 12), (0, 0, 1), 12, 24), "#ff9d2e"))       # lamp
    for m in _seg(j1, j2, T6["arm1_w"], bz + T6["arm1"][0], bz + T6["arm1"][1], end_r=67.0):
        out.append((m, EPSON_WHITE))
    for m in _seg(j2, j3, T6["arm2_w"], bz + T6["arm2"][0], bz + T6["arm2"][1], end_r=T6["arm2_end"]):
        out.append((m, EPSON_GREY))
    out.append((cyl((j3[0], j3[1], bz + T6["arm2"][0] - 12), (0, 0, 1), 30, 24), "#2f5fb3"))  # blue ring
    shaft_top = quill_z + (T6["shaft_top"] - EPSON_STROKE)
    out.append((cyl((j3[0], j3[1], (quill_z + shaft_top) / 2), (0, 0, 1), T6["shaft_r"], shaft_top - quill_z),
                "#b5b9bd"))
    out.append((cyl((j3[0], j3[1], shaft_top - 6), (0, 0, 1), T6["nut_r"], 12), "#3a3d41"))
    out.append((box((j3[0], j3[1], quill_z - 15), (40, 40, 30)), "#3a3d41"))                # vacuum tool
    # black corrugated duct: base top (over J1) to the top of arm 2 (over J2), arching up to the ceiling
    top_z, dt = bz + T6["arm2"][1] + 25.0, _duct_top(bz) - 18.0
    mid = (j1 + j2) / 2
    duct = [(j1[0], j1[1], top_z), (j1[0], j1[1], (top_z + dt) / 2 + 20), (*(j1 + 0.25 * (j2 - j1)), dt - 8),
            (mid[0], mid[1], dt), (*(j1 + 0.75 * (j2 - j1)), dt - 8), (j2[0], j2[1], (top_z + dt) / 2 + 20),
            (j2[0], j2[1], top_z)]
    out.append((tube_path(duct, 18), BLACK))
    return out, np.array([j3[0], j3[1], quill_z])


# The space the robot can sweep, taken over a full J1 turn (the real J1 range is
# +/-132 deg, so this is on the safe side): arm 2's housing out to 658.5 mm from J1
# up to its fittings; the J3 shaft out to 610 mm up to its top with Z fully up;
# the duct arch over arm 1 up to the ceiling.
SCARA_REACH = EPSON_L1 + EPSON_L2 + T6["arm2_end"]
SHAFT_REACH = EPSON_L1 + EPSON_L2 + T6["nut_r"]
SCARA_TOP = SCARA_BASE[2] + T6["arm2"][1] + 25.0
SHAFT_TOP = SCARA_BASE[2] + T6["shaft_top"] + 10.0
SCARA_ARCH = (EPSON_L1 + 40.0, _duct_top(SCARA_BASE[2]))


def scara_envelope():
    bx, by, bz = SCARA_BASE
    z0 = bz - 12.0
    parts = [pv.Cylinder(center=(bx, by, (z0 + SCARA_TOP) / 2), direction=(0, 0, 1), radius=SCARA_REACH,
                         height=SCARA_TOP - z0, resolution=96),
             pv.Cylinder(center=(bx, by, (SCARA_TOP + SHAFT_TOP) / 2), direction=(0, 0, 1), radius=SHAFT_REACH,
                         height=SHAFT_TOP - SCARA_TOP, resolution=96),
             pv.Cylinder(center=(bx, by, (SHAFT_TOP + SCARA_ARCH[1]) / 2), direction=(0, 0, 1), radius=SCARA_ARCH[0],
                         height=SCARA_ARCH[1] - SHAFT_TOP, resolution=64)]
    clip = (0, GB_W, 0, GB_D, 0, GB_H)
    return pv.merge([m.clip_box(clip, invert=False).extract_surface(algorithm="dataset_surface") for m in parts])


def robot_top_at(xy):
    """Highest point the robot can reach above (x, y): duct, shaft or arm 2, whichever applies (0 if none)."""
    r = float(np.hypot(xy[0] - SCARA_BASE[0], xy[1] - SCARA_BASE[1]))
    if r <= SCARA_ARCH[0]:
        return SCARA_ARCH[1]
    if r <= SHAFT_REACH:
        return SHAFT_TOP
    if r <= SCARA_REACH:
        return SCARA_TOP
    return 0.0


def swept_bands_at(xy):
    """Height bands (z0, z1) the robot can occupy above (x, y): shaft and tool, arm 2, arm 1, duct."""
    bz = SCARA_BASE[2]
    r = float(np.hypot(xy[0] - SCARA_BASE[0], xy[1] - SCARA_BASE[1]))
    bands = []
    if r <= SHAFT_REACH:
        bands.append((bz - 45.0, SHAFT_TOP))
    if r <= SCARA_REACH:
        bands.append((bz + T6["arm2"][0], SCARA_TOP))
    if r <= EPSON_L1 + 67.0:
        bands.append((bz + T6["arm1"][0], bz + T6["arm1"][1]))
    if r <= SCARA_ARCH[0]:
        bands.append((bz + T6["arm2"][1], SCARA_ARCH[1]))
    return bands


def raised_shelf():
    """Black breadboard under the robot (its teal strips show in the 6 Nov close-up)."""
    bx, by, _ = SCARA_BASE
    return [(box_from((bx - 240, by - 190, 0), (min(bx + 240, GB_W - 20), min(by + 260, GB_D - 30), SCALE * 13.0)),
             BLACK)]


# --- Ceiling ----------------------------------------------------------------------

DOME_C = np.array([SCALE * 300.0, SCALE * 130.0, GB_H])   # Amcrest, front left (not in the reconstruction)
CEILING_SLOT = (from_drop(-15, -307), from_drop(50, -841))  # recess along the top of the open side
TERMINAL_BOX = (from_drop(716, -225), from_drop(699, -615))  # black terminal rail with red wiring, far edge
FILTER_C = from_drop(-13, -134)


def ceiling_items():
    out = []
    (xa, ya, _), (xb, yb, _) = CEILING_SLOT
    out.append((box_from((min(xa, xb), min(ya, yb), GB_H - 3), (max(xa, xb), max(ya, yb), GB_H)), "#7f878f"))
    (xa, ya, _), (xb, yb, _) = TERMINAL_BOX
    out.append((box_from((min(xa, xb), (ya + yb) / 2 - 35, GB_H - 45), (max(xa, xb), (ya + yb) / 2 + 35, GB_H)), BLACK))
    for t in np.linspace(0.1, 0.9, 6):
        x = xa + (xb - xa) * t
        out.append((pv.Line((x, (ya + yb) / 2 - 30, GB_H - 45), (x + 30, (ya + yb) / 2 - 60, GB_H - 260))
                    .tube(radius=1.6), "#d6262b"))
    out.append((cyl((FILTER_C[0], FILTER_C[1], GB_H - 75), (0, 0, 1), 34, 150), WHITE))   # filter cartridge
    return out


def amcrest_dome():
    """The PoE camera already on the ceiling at the front left."""
    c = DOME_C
    base = cyl(c - (0, 0, 15), (0, 0, 1), 60, 30)
    dome = pv.Sphere(radius=48, center=c - (0, 0, 40), theta_resolution=40, phi_resolution=40)
    return pv.merge([base, dome]), c - (0, 0, 60)


# --- Welded ceiling studs (circled in the 6 Nov upward photo) ---------------------------
# Located by casting rays from the solved 14:06 keyframe (the same view as that
# photo) onto the ceiling. A stud is "used" when the camera plan hangs a mount on
# it, and "reach" when the robot's shaft can pass under it.

CEILING_STUDS = {
    "S1": dict(xy=tuple(from_drop(420, -46)[:2]), state="free", note="between two ceiling ports, antechamber end"),
    "S2": dict(xy=tuple(from_drop(122, -230)[:2]), state="free", note="single stud, open side"),
    "S3": dict(xy=tuple(from_drop(427, -421)[:2]), state="free", note="between two ceiling ports, middle"),
    "S4": dict(xy=tuple(from_drop(129, -562)[:2]), state="taken", note="clamp bracket already on it"),
}
for _s in CEILING_STUDS.values():
    if np.hypot(_s["xy"][0] - SCARA_BASE[0], _s["xy"][1] - SCARA_BASE[1]) <= SHAFT_REACH and _s["state"] == "free":
        _s["state"], _s["note"] = "reach", _s["note"] + "; inside the shaft's reach"
STUD_COLORS = {"free": "#16b364", "taken": "#7d8590", "used": "#ff7a1a", "needed": "#d6262b", "reach": "#7c3aed"}


def add_needed_stud(name, xy, note):
    CEILING_STUDS[name] = dict(xy=tuple(xy), state="needed", note=note)


def ceiling_studs(used=()):
    """Each stud plus a coloured washer-sized marker, so it reads at room scale."""
    out = []
    for name, st in CEILING_STUDS.items():
        x, y = st["xy"]
        state = "used" if name in used else st["state"]
        out.append((cyl((x, y, GB_H - 14), (0, 0, 1), 3.0, 28, res=16), "#8a9097"))
        out.append((ring((x, y, GB_H - 1.5), (0, 0, 1), 6, 24, 3, res=32), STUD_COLORS[state]))
    return out


# --- Work areas named in the 26 Oct walkthrough -------------------------------------
# Not designated yet. Drawn on the deck behind the exfoliator, beside the
# antechamber door and outside the robot's reach. That corner isn't empty in the
# reconstruction (something about 0.5 m tall stands at x 50-400, y 800-1060).

UNPACK_C = np.array([SCALE * 150.0, SCALE * 690.0, 0.0])
MOTHER_TAPE_C = np.array([SCALE * 190.0, SCALE * 950.0, 0.0])


def floor_zone(center, size, color):
    """Thin coloured mat marking a designated area on the deck (or a plate)."""
    return box((center[0], center[1], center[2] + 1.5), (size[0], size[1], 3.0)), color


def unpack_area():
    out = [floor_zone(UNPACK_C, (260, 220), "#ffd8b5")]
    cx, cy, _ = UNPACK_C
    out.append((cyl((cx - 60, cy + 40, 35), (0, 0, 1), 32, 70), "#7a4b2a"))   # shipping jar
    out.append((cyl((cx - 60, cy + 40, 74), (0, 0, 1), 34, 10), "#333333"))   # lid
    out.append((box((cx + 50, cy - 30, 8), (110, 80, 10)), "#e9eef3"))       # opened bag
    out.append((cyl((cx + 40, cy + 60, 12), (0, 0, 1), 18, 18), "#bfc6cc"))   # vial
    return out


def mother_tape_area():
    out = [floor_zone(MOTHER_TAPE_C, (240, 180), "#cfe8ff")]
    cx, cy, _ = MOTHER_TAPE_C
    out.append((box((cx, cy, 6), (190, 110, 6)), "#2a8c6e"))                     # cutting mat
    out.append((ring((cx - 60, cy + 60, 22), (0, 0, 1), 18, 34, 22), BLUE_TAPE))  # tape roll
    out.append((box((cx + 20, cy, 10), (120, 40, 1.5)), BLUE_TAPE))              # mother tape strip
    return out


def exfoliator_tip():
    """Where the roller meets the mother tape."""
    return TIP_C.copy()


PNP_C = PLATE_C.copy()   # the chip tray sits on the substrate plate: the pick-and-place view's target


def pnp_tray():
    """8 x 8 chip tray in its metal holder, on the substrate plate (6 Nov close-up)."""
    cx, cy, cz = PNP_C
    out = [(box((cx, cy, cz + 7), (150, 120, 14)), "#c3c8cd")]
    for i in range(8):
        for j in range(8):
            out.append((box((cx - 56 + i * 16, cy - 49 + j * 14, cz + 15), (11, 10, 2)), "#6f7f99"))
    return out
