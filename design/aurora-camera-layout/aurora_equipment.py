"""Approximate geometry of the Aurora glovebox and the equipment inside it.

Dimensions are estimated from photos (issue #23), not measured, and are only
meant to make camera placement legible. Units are millimetres. Coordinates:
x runs left to right as seen from the glove-port side, y runs from that side
towards the back wall, z is up from the glovebox floor.
"""

import numpy as np
import pyvista as pv

from scene_primitives import box, box_from, cyl, ring, tube_path

# --- Glovebox shell -----------------------------------------------------------

GB_W, GB_D, GB_H = 1900.0, 820.0, 900.0  # interior
WALL_T = 12.0
WINDOW_SETBACK = 160.0  # the front window leans back by this much at the top
STAND_H = 880.0
GLOVE_R = 105.0
GLOVE_X = (330.0, 750.0, 1150.0, 1570.0)
GLOVE_Z = 330.0

STAINLESS = "#c9ced3"
STAINLESS_DARK = "#9aa1a8"
ALUMINIUM = "#d7dadd"
BLACK = "#26282b"
BLUE_TUBE = "#1f6fd1"
RED_HUB = "#d6262b"
BLUE_TAPE = "#2546c4"
WHITE = "#f2f2f2"
YELLOW = "#f2c200"


def window_x_at(z):
    """y-coordinate of the sloped front window at height z."""
    return WINDOW_SETBACK * z / GB_H


def glovebox_shell():
    """Returns {name: (mesh, style)} for the walls, so each can be styled separately."""
    parts = {}
    parts["floor"] = (box_from((0, 0, -WALL_T), (GB_W, GB_D, 0)), dict(color=STAINLESS, specular=0.6))
    parts["back_wall"] = (box_from((0, GB_D, 0), (GB_W, GB_D + WALL_T, GB_H)),
                          dict(color=STAINLESS, specular=0.5))
    parts["left_wall"] = (box_from((-WALL_T, 0, 0), (0, GB_D, GB_H)), dict(color=STAINLESS, specular=0.5))
    parts["right_wall"] = (box_from((GB_W, 0, 0), (GB_W + WALL_T, GB_D, GB_H)),
                           dict(color=STAINLESS, specular=0.5))
    parts["ceiling"] = (box_from((0, WINDOW_SETBACK, GB_H), (GB_W, GB_D, GB_H + WALL_T)),
                        dict(color=STAINLESS, specular=0.4))

    # sloped front window: a thin glass slab in a stainless frame
    p0 = np.array([0.0, 0.0, 0.0])
    p1 = np.array([0.0, WINDOW_SETBACK, GB_H])
    glass = pv.Plane(center=(GB_W / 2, WINDOW_SETBACK / 2, GB_H / 2),
                     direction=(0, -GB_H, WINDOW_SETBACK), i_size=GB_W, j_size=GB_H * 1.013,
                     i_resolution=1, j_resolution=1)
    parts["window"] = (glass, dict(color="#bfe3ff", opacity=0.10, specular=1.0))
    frame = []
    n = np.array([0.0, -GB_H, WINDOW_SETBACK]) / np.hypot(GB_H, WINDOW_SETBACK)
    for gx in GLOVE_X:
        c = np.array([gx, window_x_at(GLOVE_Z), GLOVE_Z])
        frame.append(ring(c, n, GLOVE_R, GLOVE_R + 22.0, 30.0))
    edge = [box_from((-40, -40, -40), (GB_W + 40, 0, 0)),
            box_from((-40, WINDOW_SETBACK - 40, GB_H), (GB_W + 40, WINDOW_SETBACK, GB_H + 40))]
    for x0 in (-40, GB_W):
        side = pv.Line(p0 + (x0 + 20, 0, 0), p1 + (x0 + 20, 0, 0)).tube(radius=20, n_sides=4)
        edge.append(side)
    parts["window_frame"] = (pv.merge(frame + edge), dict(color=STAINLESS_DARK, specular=0.6))
    return parts


def stand():
    legs = []
    for x in (40, GB_W / 2, GB_W - 40):
        for y in (60, GB_D - 60):
            legs.append(box((x, y, -STAND_H / 2 - WALL_T), (50, 50, STAND_H)))
            legs.append(cyl((x, y, -STAND_H - WALL_T - 20), (0, 0, 1), 32, 14))
    rails = [box((GB_W / 2, y, -STAND_H + 120), (GB_W - 30, 40, 40)) for y in (60, GB_D - 60)]
    rails += [box((GB_W / 2, y, -60), (GB_W - 30, 50, 60)) for y in (60, GB_D - 60)]
    braces = []
    for x0, x1 in ((40, GB_W / 2), (GB_W - 40, GB_W / 2)):
        for y in (60, GB_D - 60):
            braces.append(pv.Line((x0, y, -STAND_H + 120), (x1, y, -90)).tube(radius=18, n_sides=8))
    return pv.merge(legs + rails + braces)


# --- Antechambers ---------------------------------------------------------------

def antechambers():
    """Large antechamber on the left wall, mini antechamber below it."""
    big_c = (-WALL_T, GB_D * 0.52, 470.0)
    big = [ring(big_c, (1, 0, 0), 0, 225, 18),                      # inner door
           ring((big_c[0] + 12, big_c[1], big_c[2]), (1, 0, 0), 225, 250, 14),
           cyl((-WALL_T - 330, big_c[1], big_c[2]), (1, 0, 0), 250, 640)]  # tube, outside
    mini_c = (-WALL_T, GB_D * 0.20, 190.0)
    mini = [ring(mini_c, (1, 0, 0), 0, 85, 16),
            cyl((-WALL_T - 180, mini_c[1], mini_c[2]), (1, 0, 0), 85, 340)]
    return pv.merge(big), pv.merge(mini)


# --- Tape exfoliation / pick-and-place gantry (centre-left) ------------------------

EXF_C = np.array([930.0, 480.0, 0.0])  # footprint centre on the floor
EXF_DECK_Z = 190.0


def exfoliator():
    """Returns a list of (mesh, color) for the tape exfoliation gantry."""
    out = []
    cx, cy, _ = EXF_C
    deck = box((cx, cy, EXF_DECK_Z - 6), (480, 330, 12))
    out.append((deck, BLACK))
    for sx in (-1, 1):
        for sy in (-1, 1):
            out.append((cyl((cx + sx * 205, cy + sy * 135, (EXF_DECK_Z - 12) / 2), (0, 0, 1), 14,
                            EXF_DECK_Z - 12), STAINLESS))
    # long linear axis (ball screw) running left-right across the back of the deck
    ax_y = cy + 70
    out.append((box((cx + 20, ax_y, EXF_DECK_Z + 25), (440, 70, 50)), ALUMINIUM))
    out.append((cyl((cx + 20, ax_y, EXF_DECK_Z + 62), (1, 0, 0), 8, 420), "#b0b4b8"))
    out.append((box((cx + 270, ax_y, EXF_DECK_Z + 45), (76, 57, 57)), BLACK))  # NEMA 23
    # carriage + drag chain + blue vacuum lines
    car_x = cx - 40
    out.append((box((car_x, ax_y - 10, EXF_DECK_Z + 75), (110, 90, 30)), "#1d4fbf"))
    out.append((box((cx + 40, ax_y - 85, EXF_DECK_Z + 40), (300, 30, 40)), BLACK))
    for dz in (0, 18):
        pts = [(car_x, ax_y - 30, EXF_DECK_Z + 90 + dz), (car_x + 90, ax_y + 30, EXF_DECK_Z + 140 + dz),
               (cx + 200, ax_y + 40, EXF_DECK_Z + 110 + dz), (cx + 265, ax_y - 40, EXF_DECK_Z - 30 - dz),
               (cx + 250, cy - 120, 30 + dz), (cx + 120, cy - 230, 18 + dz)]
        out.append((tube_path(pts, 7), BLUE_TUBE))
    # vertical tower with the Z axis and the tape spools
    tx, ty = cx - 120, cy + 10
    out.append((box((tx, ty, EXF_DECK_Z + 170), (150, 26, 340)), ALUMINIUM))
    out.append((box((tx + 10, ty - 40, EXF_DECK_Z + 300), (60, 60, 70)), BLACK))  # Z motor
    out.append((box((tx + 75, ty - 40, EXF_DECK_Z + 150), (190, 50, 34)), ALUMINIUM))  # arm
    out.append((cyl((tx + 140, ty - 75, EXF_DECK_Z + 120), (0, 1, 0), 26, 42), "#e4e6e8"))  # load cell
    out.append((box((tx + 135, ty - 75, EXF_DECK_Z + 70), (70, 40, 26)), "#c27a3a"))  # stamp/press
    spools = [(tx - 60, ty - 55, EXF_DECK_Z + 250), (tx + 230, ty - 55, EXF_DECK_Z + 250)]
    for sc in spools:
        out.append((ring(sc, (0, 1, 0), 22, 52, 46), RED_HUB))
        out.append((ring(sc, (0, 1, 0), 52, 76, 40), BLUE_TAPE))
    # mother tape web: off the supply spool, under the stamp tip, onto the take-up spool
    web_z = EXF_DECK_Z + 70 - 13 - 2
    web = pv.Spline(np.array([
        (spools[0][0] + 20, ty - 55, spools[0][2] - 74), (tx + 60, ty - 70, web_z + 20),
        (tx + 80, ty - 75, web_z), (tx + 190, ty - 75, web_z), (tx + 205, ty - 70, web_z + 20),
        (spools[1][0] - 20, ty - 55, spools[1][2] - 74)]), 80)
    out.append((web.ribbon(width=17, normal=(0, 1, 0)), "#5b8def"))
    # e-stop on the LED light source, front right of the deck
    out.append((box((cx + 200, cy - 300, 45), (150, 110, 90)), "#e9e9e9"))
    out.append((box((cx + 200, cy - 300, 130), (90, 90, 80)), YELLOW))
    out.append((cyl((cx + 200, cy - 300, 185), (0, 0, 1), 22, 30), RED_HUB))
    return out


# --- Epson SCARA (right) ------------------------------------------------------------

SCARA_BASE = np.array([1660.0, 600.0, 0.0])
PNP_C = np.array([1390.0, 360.0, 0.0])  # substrate tray the SCARA picks from and places to


def scara(target=None, quill_z=300.0):
    """Epson SCARA on a pedestal, arm posed over `target` (x, y); returns (parts, tool point)."""
    out = []
    bx, by, _ = SCARA_BASE
    target = PNP_C if target is None else np.asarray(target, float)
    out.append((box((bx, by, 15), (300, 300, 30)), BLACK))  # breadboard plate
    out.append((box((bx, by + 30, 230), (170, 230, 400)), WHITE))  # base column
    out.append((box((bx, by + 30, 455), (150, 200, 50)), "#dadada"))
    l1, l2 = 325.0, 275.0
    dx, dy = target[0] - bx, target[1] - by
    r = np.clip(np.hypot(dx, dy), abs(l1 - l2) + 1, l1 + l2 - 1)
    elbow = np.arccos((r**2 - l1**2 - l2**2) / (2 * l1 * l2))
    t1 = np.arctan2(dy, dx) - np.arctan2(l2 * np.sin(elbow), l1 + l2 * np.cos(elbow))
    t2 = t1 + elbow
    j1 = np.array([bx, by, 470.0])
    j2 = j1 + l1 * np.array([np.cos(t1), np.sin(t1), 0.0])
    j3 = j2 + l2 * np.array([np.cos(t2), np.sin(t2), 0.0])
    for a, b, w, z in ((j1, j2, 120, 470), (j2, j3, 100, 525)):
        mid, vec = (a + b) / 2, b - a
        seg = box((0, 0, 0), (np.linalg.norm(vec) + w, w, 55))
        seg.rotate_z(np.degrees(np.arctan2(vec[1], vec[0])), inplace=True)
        seg.translate((mid[0], mid[1], z), inplace=True)
        out.append((seg, WHITE))
        out.append((cyl((b[0], b[1], z), (0, 0, 1), w / 2, 56), WHITE))
    out.append((cyl((j1[0], j1[1], 470), (0, 0, 1), 60, 56), WHITE))
    out.append((cyl((j3[0], j3[1], quill_z + 120), (0, 0, 1), 10, 340), "#b5b9bd"))  # quill
    out.append((box((j3[0], j3[1], quill_z - 60), (46, 46, 40)), "#3a3d41"))  # end effector
    duct = [(bx, by + 60, 460), (bx + 20, by + 120, 760), (j2[0] + 10, j2[1] + 40, 760), (j3[0], j3[1], 565)]
    out.append((tube_path(duct, 16), BLACK))
    return out, j3


# --- Ceiling-mounted items already present ---------------------------------------

def ceiling_items():
    out = []
    out.append((box((1150, 520, GB_H - 10), (520, 220, 20)), "#1b1c1e"))   # LED panel
    out.append((box((1650, 690, GB_H - 25), (260, 120, 50)), BLACK))       # power/USB hubs
    out.append((box((GB_W / 2, GB_D - 30, GB_H - 40), (GB_W - 200, 60, 60)), "#9da3a8"))  # wire duct
    out.append((cyl((330, GB_D - 120, GB_H - 90), (0, 0, 1), 34, 150), WHITE))  # filter cartridge
    return out


def amcrest_dome():
    """The PoE dome camera already on the ceiling at the back left."""
    c = np.array([520.0, GB_D - 150.0, GB_H])
    base = cyl(c - (0, 0, 15), (0, 0, 1), 60, 30)
    dome = pv.Sphere(radius=48, center=c - (0, 0, 40), theta_resolution=40, phi_resolution=40)
    return pv.merge([base, dome]), c - (0, 0, 60)


# --- Designated work areas named in the 26 Oct walkthrough --------------------------

UNPACK_C = np.array([220.0, 470.0, 0.0])      # beside the antechamber inner door
MOTHER_TAPE_C = np.array([520.0, 300.0, 0.0])  # between the unpacking area and the gantry


def floor_zone(center, size, color):
    """Thin coloured mat marking a designated area on the glovebox floor."""
    return box((center[0], center[1], 1.5), (size[0], size[1], 3.0)), color


def unpack_area():
    out = [floor_zone(UNPACK_C, (300, 260), "#ffd8b5")]
    cx, cy, _ = UNPACK_C
    out.append((cyl((cx - 60, cy + 40, 35), (0, 0, 1), 32, 70), "#7a4b2a"))   # shipping jar
    out.append((cyl((cx - 60, cy + 40, 74), (0, 0, 1), 34, 10), "#333333"))   # lid
    out.append((box((cx + 60, cy - 30, 8), (110, 80, 10)), "#e9eef3"))       # opened bag
    out.append((cyl((cx + 40, cy + 70, 12), (0, 0, 1), 18, 18), "#bfc6cc"))   # vial
    return out


def mother_tape_area():
    out = [floor_zone(MOTHER_TAPE_C, (260, 200), "#cfe8ff")]
    cx, cy, _ = MOTHER_TAPE_C
    out.append((box((cx, cy, 6), (200, 120, 6)), "#2a8c6e"))                # cutting mat
    out.append((ring((cx - 70, cy + 70, 22), (0, 0, 1), 18, 34, 22), BLUE_TAPE))  # tape roll
    out.append((box((cx + 20, cy, 10), (120, 40, 1.5)), BLUE_TAPE))          # mother tape strip
    return out


def exfoliator_tip():
    """Point where the stamp tip meets the mother tape on the gantry."""
    cx, cy, _ = EXF_C
    return np.array([cx - 120 + 135, cy + 10 - 75, EXF_DECK_Z + 55])


def pnp_tray():
    """Gel-Pak style substrate tray in the SCARA's pick-and-place zone."""
    cx, cy, _ = PNP_C
    out = [floor_zone(PNP_C, (240, 200), "#d9f5e6")]
    out.append((box((cx, cy, 10), (150, 110, 14)), "#30343a"))
    for i in range(4):
        for j in range(3):
            out.append((box((cx - 52 + i * 35, cy - 35 + j * 35, 18), (16, 16, 2)), "#8fb3d9"))
    return out
