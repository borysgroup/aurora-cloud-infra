"""PyVista meshes of the chamber for renders. Every size comes from params.py.

Each builder returns either a mesh or a list of (mesh, colour) pairs. The
simplified solids for CAD (STEP/STL) are in cad.py; both read the same numbers.
"""

import numpy as np
import pyvista as pv

from . import robot
from .params import (ANTE_DOOR_C, ANTE_DOOR_R, BACK_LEAN, CEILING_SLOT, CEILING_STUD_LEN, CEILING_STUD_NOTES,
                     CEILING_STUDS_DROP, COLUMN_XY, DOME_C, ESTOP_C, EXF_DECK_Z, EXF_STROKE, EXF_X0, EXF_X1,
                     EXF_Y0, EXF_Y1, FILTER_C, FLANGE_PITCH, FLANGE_STUD_LEN, FRONT_LEAN, GB_D, GB_H, GB_W,
                     GLOVE_R, GLOVE_X, GLOVE_Z, MICRO_OBJ_C, MICRO_STAGE_C, MINI_C, MINI_R, OPENING, PLATE_C,
                     PLATE_SIZE, RISER_H, SHELF_T, SIGN, SPOOL_C, STAND_H, STUD_D, T6, TERMINAL_BOX,
                     TIP_C, TRAY_SIZE, WALL_T, BASE_BACK, from_drop)
from .primitives import box, box_from, cyl, ring, tube_path

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
ENVELOPE = "#7c3aed"


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


def window_normal(side):
    """Outward unit normal of a long-side window ('front' = open side, 'back' = far window)."""
    n = np.array([0.0, -GB_H, FRONT_LEAN]) if side == "front" else np.array([0.0, GB_H, BACK_LEAN])
    return n / np.linalg.norm(n)


def flange_studs(side):
    """(position, outward direction) of each welded stud round one window opening; the position is the stud's
    root on the flange."""
    y_at = front_window_y if side == "front" else back_window_y
    n = window_normal(side)
    out = 30.0 * np.sign(n[1])
    x0, x1, z0, z1 = OPENING
    pts = []
    for x in np.arange(x0 + 25.0, x1 - 10.0, FLANGE_PITCH):
        for z in ((z0 - 10.0), (z1 + 10.0)):
            pts.append(np.array([x, y_at(z) + out, z]))
    for x in (x0 - 25.0, x1 + 25.0):
        for z in np.arange(z0 + 40.0, z1 - 20.0, FLANGE_PITCH):
            pts.append(np.array([x, y_at(z) + out, z]))
    return [(p, n) for p in pts]


def _window(side):
    """Glass, glove-port rings, flange and its studs for one long side."""
    y_at = front_window_y if side == "front" else back_window_y
    n = window_normal(side)
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
    studs = [cyl(p + n * FLANGE_STUD_LEN / 2, n, STUD_D / 2 + 0.2, FLANGE_STUD_LEN, res=8)
             for p, n in flange_studs(side)]
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


# --- Antechambers ---------------------------------------------------------------------------------------

def antechambers():
    """Large antechamber on the end wall, mini antechamber in the lower corner."""
    _, cy, cz = ANTE_DOOR_C
    big = [ring((8, cy, cz), (1, 0, 0), 0, ANTE_DOOR_R, 12),                       # inner door
           ring((2, cy, cz), (1, 0, 0), ANTE_DOOR_R - 15, ANTE_DOOR_R + 22, 10),   # flange
           cyl((16, cy, cz), (1, 0, 0), 22, 18),                                   # hub
           cyl((-WALL_T - 305, cy, cz), (1, 0, 0), 205, 610)]                      # tube, outside
    _, my, mz = MINI_C
    mini = [cyl((-WALL_T - 150, my, mz), (1, 0, 0), MINI_R, 300),   # tube, outside
            cyl((55, my, mz), (1, 0, 0), MINI_R, 110),              # tube, inside
            ring((112, my, mz), (1, 0, 0), 0, MINI_R + 8, 12),      # inner door
            box((122, my, mz), (10, 150, 18))]                      # latch bar
    return pv.merge(big), pv.merge(mini)


# --- Exfoliator ------------------------------------------------------------------------------------------
# From the antechamber end: the gantry with its cable chain, the Montalvo controller, the press column with
# the roller under the tape spool, the rear linear stage with the white substrate plate the Epson drops the
# chip tray on, the heater/fan box, the e-stop on the LED source, and the microscope.

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


def exfoliator_tip():
    """Where the roller meets the mother tape."""
    return TIP_C.copy()


TRAY_C = PLATE_C.copy()   # the chip tray sits on the substrate plate


def pnp_tray():
    """8 x 8 chip tray in its metal holder, on the substrate plate (6 Nov close-up)."""
    cx, cy, cz = TRAY_C
    out = [(box((cx, cy, cz + TRAY_SIZE[2] / 2), TRAY_SIZE), "#c3c8cd")]
    for i in range(8):
        for j in range(8):
            out.append((box((cx - 56 + i * 16, cy - 49 + j * 14, cz + 15), (11, 10, 2)), "#6f7f99"))
    return out


# --- Epson T6-B602S ---------------------------------------------------------------------------------------

def _seg(a, b, w, z0, z1, end_r=None):
    """Link from a to b (xy), width w, between heights z0 and z1, with rounded ends."""
    vec = b - a
    seg = box((0, 0, 0), (np.linalg.norm(vec), w, z1 - z0))
    seg.rotate_z(np.degrees(np.arctan2(vec[1], vec[0])), inplace=True)
    mid = (a + b) / 2
    seg.translate((mid[0], mid[1], (z0 + z1) / 2), inplace=True)
    r = w / 2 if end_r is None else end_r
    return [seg] + [cyl((p[0], p[1], (z0 + z1) / 2), (0, 0, 1), r, z1 - z0) for p in (a, b)]


def duct_path(j1, j2, riser=None):
    """Centre line of the black corrugated duct: base top (over J1) to the top of arm 2 (over J2), arching to
    just under the ceiling."""
    bz = RISER_H if riser is None else riser
    top_z, dt = bz + T6["arm2"][1] + 25.0, robot.duct_top(bz) - 18.0
    mid = (j1 + j2) / 2
    return [(j1[0], j1[1], top_z), (j1[0], j1[1], (top_z + dt) / 2 + 20), (*(j1 + 0.25 * (j2 - j1)), dt - 8),
            (mid[0], mid[1], dt), (*(j1 + 0.75 * (j2 - j1)), dt - 8), (j2[0], j2[1], (top_z + dt) / 2 + 20),
            (j2[0], j2[1], top_z)]


def scara(target=None, quill_z=None, riser=None):
    """Epson T6-B602S, arm posed over `target` (x, y); returns (parts, tool point)."""
    out = []
    bx, by, bz = robot.base_xyz(riser)
    target = robot.PARK_J3 if target is None else np.asarray(target, float)[:2]
    quill_z = bz + 120.0 if quill_z is None else quill_z
    j1, j2, j3 = robot.joints(target)
    u = np.asarray(BASE_BACK, float)
    w, front, back = T6["base"]

    def base_box(z0, z1, b0, b1, width):
        c = j1 + u * (b0 + b1) / 2
        m = box((0, 0, 0), (width, b1 - b0, z1 - z0))
        m.rotate_z(np.degrees(np.arctan2(u[1], u[0])) - 90.0, inplace=True)
        return m.translate((c[0], c[1], (z0 + z1) / 2), inplace=False)

    out.append((base_box(SHELF_T, bz, -front - 40, back + 40, w + 80), "#b9bec4"))           # riser block
    out.append((base_box(bz, bz + T6["arm1"][0], -front, back, w), EPSON_WHITE))             # lower base
    out.append((base_box(bz + T6["arm1"][0], bz + T6["box"][0], 70.0, back, w), EPSON_WHITE))
    out.append((base_box(bz + T6["box"][0], bz + T6["box"][1], -10.0, back, w), EPSON_GREY))  # controller box
    out.append((cyl((bx, by, bz + T6["box"][1] + 12), (0, 0, 1), 12, 24), "#ff9d2e"))       # lamp
    for m in _seg(j1, j2, T6["arm1_w"], bz + T6["arm1"][0], bz + T6["arm1"][1], end_r=67.0):
        out.append((m, EPSON_WHITE))
    for m in _seg(j2, j3, T6["arm2_w"], bz + T6["arm2"][0], bz + T6["arm2"][1], end_r=T6["arm2_end"]):
        out.append((m, EPSON_GREY))
    out.append((cyl((j3[0], j3[1], bz + T6["arm2"][0] - 12), (0, 0, 1), 30, 24), "#2f5fb3"))  # blue ring
    shaft_top = robot.shaft_top_z(quill_z)
    out.append((cyl((j3[0], j3[1], (quill_z + shaft_top) / 2), (0, 0, 1), T6["shaft_r"], shaft_top - quill_z),
                "#b5b9bd"))
    out.append((cyl((j3[0], j3[1], shaft_top - 6), (0, 0, 1), T6["nut_r"], 12), "#3a3d41"))
    out.append((box((j3[0], j3[1], quill_z - 15), (40, 40, 30)), "#3a3d41"))                # vacuum tool
    out.append((tube_path(duct_path(j1, j2, bz), 18), BLACK))
    return out, np.array([j3[0], j3[1], quill_z])


def scara_envelope(riser=None):
    """The robot's swept volume (full J1 turn) as one mesh, clipped to the box."""
    e = robot.envelope(riser)
    bx, by, _ = robot.base_xyz(riser)
    z0 = e["riser"] - 12.0

    def c(r, za, zb, res=96):
        return pv.Cylinder(center=(bx, by, (za + zb) / 2), direction=(0, 0, 1), radius=r, height=zb - za,
                           resolution=res)
    parts = [c(e["arm2_r"], z0, e["arm2_top"]), c(e["shaft_r"], e["arm2_top"], e["shaft_top"]),
             c(e["arch_r"], e["shaft_top"], e["arch_top"], 64)]
    clip = (0, GB_W, 0, GB_D, 0, GB_H)
    return pv.merge([m.clip_box(clip, invert=False).extract_surface(algorithm="dataset_surface") for m in parts])


def raised_shelf():
    """Black breadboard under the robot (its teal strips show in the 6 Nov close-up)."""
    bx, by = robot.SCARA_XY
    return [(box_from((bx - 240, by - 190, 0), (min(bx + 240, GB_W - 20), min(by + 260, GB_D - 30), SHELF_T)),
             BLACK)]


# --- Ceiling ------------------------------------------------------------------------------------------------

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
    """The PoE camera already on the ceiling at the front left; returns (mesh, lens point)."""
    c = DOME_C
    base = cyl(c - (0, 0, 15), (0, 0, 1), 60, 30)
    dome = pv.Sphere(radius=48, center=c - (0, 0, 40), theta_resolution=40, phi_resolution=40)
    return pv.merge([base, dome]), c - (0, 0, 60)


# --- Welded ceiling studs --------------------------------------------------------------------------------------

def _ceiling_studs():
    studs = {}
    for name, xy in CEILING_STUDS_DROP.items():
        state, note = CEILING_STUD_NOTES[name]
        p = from_drop(*xy)[:2]
        if state == "free" and robot.robot_top_at(p) > 0:
            state, note = "reach", note + "; inside the robot's reach"
        studs[name] = dict(xy=tuple(p), state=state, note=note)
    return studs


CEILING_STUDS = _ceiling_studs()
STUD_COLORS = {"free": "#16b364", "taken": "#7d8590", "used": "#ff7a1a", "needed": "#d6262b", "reach": ENVELOPE}


def ceiling_studs(used=(), studs=None):
    """Each stud plus a coloured washer-sized marker, so it reads at room scale. `studs` defaults to
    CEILING_STUDS; pass a copy with extra entries (state "needed") for studs a design adds."""
    out = []
    for name, st in (CEILING_STUDS if studs is None else studs).items():
        x, y = st["xy"]
        state = "used" if name in used else st["state"]
        out.append((cyl((x, y, GB_H - CEILING_STUD_LEN / 2), (0, 0, 1), STUD_D / 2, CEILING_STUD_LEN, res=16),
                    "#8a9097"))
        out.append((ring((x, y, GB_H - 1.5), (0, 0, 1), 6, 24, 3, res=32), STUD_COLORS[state]))
    return out


def static_parts(robot_target=None, riser=None, with_dome=True):
    """Everything fixed in the chamber plus the robot at one pose, as (mesh, colour) pairs. Used for line-of-
    sight checks and quick renders; the shell's glass is left out (cameras see through it)."""
    shell = glovebox_shell()
    out = [(shell[k][0], shell[k][1]["color"]) for k in ("floor", "left_wall", "right_wall", "ceiling")]
    big, mini = antechambers()
    out += [(big, STAINLESS), (mini, STAINLESS)]
    out += exfoliator() + pnp_tray() + raised_shelf() + ceiling_items() + ceiling_studs()
    out += scara(target=robot_target, riser=riser)[0]
    if with_dome:
        out.append((amcrest_dome()[0], WHITE))
    return out

