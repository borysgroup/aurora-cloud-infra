"""PyVista meshes of the chamber for renders. Every size comes from params.py.

Each builder returns either a mesh or a list of (mesh, colour) pairs. The
simplified solids for CAD (STEP/STL) are in cad.py; both read the same numbers.
"""

import numpy as np
import pyvista as pv

from . import robot, specs
from .params import (ANTE_DOOR_C, ANTE_DOOR_R, BACK_LEAN, CEILING_SLOT, CEILING_STUD_LEN, CEILING_STUD_NOTES,
                     CEILING_STUDS_DROP, DOME_C, FILTER_C, FLANGE_PITCH, FLANGE_STUD_LEN, FRONT_LEAN, GB_D, GB_H,
                     GB_W, GLOVE_R, GLOVE_X, GLOVE_Z, MINI_C, MINI_R, OPENING, PLATE_C, SHELF_T, SIGN, STAND_H,
                     STUD_D, TERMINAL_BOX, TIP_C, WALL_T, from_drop)
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


# --- Specs to meshes ------------------------------------------------------------------------------------------

def to_pv(spec):
    """PyVista mesh of one primitive spec (see specs.py)."""
    k = spec["kind"]
    if k == "box":
        return box_from(spec["lo"], spec["hi"])
    if k == "obox":
        m = box((0, 0, 0), spec["size"])
        m.rotate_z(spec["yaw"], inplace=True)
        return m.translate(spec["center"], inplace=False)
    if k == "cyl":
        return cyl(spec["center"], spec["direction"], spec["r"], spec["h"])
    if k == "ring":
        return ring(spec["center"], spec["normal"], spec["r_in"], spec["r_out"], spec["t"])
    if k == "tube":
        return tube_path(spec["points"], spec["r"])
    if k == "ribbon":
        return pv.Spline(spec["points"], 60).ribbon(width=spec["width"], normal=spec["normal"])
    raise ValueError(k)


def from_specs(spec_list):
    return [(to_pv(sp), sp["color"]) for sp in spec_list]


def exfoliator():
    """Returns a list of (mesh, color) for the exfoliator (specs.exfoliator_specs)."""
    return from_specs(specs.exfoliator_specs())


def exfoliator_tip():
    """Where the roller meets the mother tape."""
    return TIP_C.copy()


TRAY_C = PLATE_C.copy()   # the chip tray sits on the substrate plate


def pnp_tray():
    """8 x 8 chip tray in its metal holder, on the substrate plate (6 Nov close-up)."""
    cx, cy, cz = TRAY_C
    out = from_specs([specs.tray_spec()])
    for i in range(8):
        for j in range(8):
            out.append((box((cx - 56 + i * 16, cy - 49 + j * 14, cz + 15), (11, 10, 2)), "#6f7f99"))
    return out


# --- Epson T6-B602S ---------------------------------------------------------------------------------------

def scara(target=None, quill_z=None, riser=None):
    """Epson T6-B602S, arm posed over `target` (x, y); returns (parts, tool point)."""
    sp, tool = specs.scara_specs(target, quill_z, riser)
    return from_specs(sp), tool


def scara_envelope(risers=None):
    """The robot's swept volume (full J1 turn, over the riser range) as one mesh, clipped to the box."""
    clip = (0, GB_W, 0, GB_D, 0, GB_H)
    meshes = [pv.Cylinder(center=sp["center"], direction=sp["direction"], radius=sp["r"], height=sp["h"],
                          resolution=96) for sp in specs.envelope_specs(risers)]
    return pv.merge([m.clip_box(clip, invert=False).extract_surface(algorithm="dataset_surface") for m in meshes])


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

