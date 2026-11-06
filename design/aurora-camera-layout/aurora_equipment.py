"""Approximate geometry of the Aurora glovebox and the equipment inside it.

Dimensions are estimated from the issue #23 photos and three frames of the
AURORA overview video (youtu.be/moBCWzP9Izw), not measured, and are only meant
to make camera placement legible. Units are millimetres. Coordinates: x runs
left to right as seen from the front (the side whose window was off during the
26 Oct walkthrough), y runs from the front window towards the back window, z is
up from the glovebox floor.

What the photos and frames support: windows and glove ports on both long sides
(the lab is visible through the back behind the Epson, and photo 4 is taken
through a window with two glove-port rings); the large antechamber door, the
mini antechamber and the NSF/MonArk signs on the left end wall; the Amcrest dome
just behind the top front flange; the Epson on a raised black breadboard with
its conduit to the ceiling; the e-stop on an Olympus LED source on a black
breadboard; a 400 mm-stroke ball-screw axis on the gantry ("400mm" is written
on it in the video).
"""

import numpy as np
import pyvista as pv

from scene_primitives import box, box_from, cyl, ring, tube_path

# --- Glovebox shell -----------------------------------------------------------

GB_W, GB_D, GB_H = 1900.0, 820.0, 900.0  # interior
WALL_T = 12.0
WINDOW_SETBACK = 160.0  # both windows lean in by this much at the top
STAND_H = 880.0
GLOVE_R = 102.0  # 8-inch glove ports
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


def front_window_y(z):
    """y-coordinate of the sloped front window at height z."""
    return WINDOW_SETBACK * z / GB_H


def back_window_y(z):
    """y-coordinate of the sloped back window at height z (mirror of the front)."""
    return GB_D - WINDOW_SETBACK * z / GB_H


def _quad(p0, p1, p2, p3):
    return pv.PolyData(np.array([p0, p1, p2, p3], float), faces=[4, 0, 1, 2, 3])


def _end_wall(x0, x1):
    """Trapezoidal end wall that follows both window slopes."""
    face = _quad((x0, 0, 0), (x0, GB_D, 0), (x0, GB_D - WINDOW_SETBACK, GB_H), (x0, WINDOW_SETBACK, GB_H))
    return face.extrude((x1 - x0, 0, 0), capping=True)


def _window(side):
    """Glass, outward normal, glove-port rings and a bolted frame for one long side."""
    s = WINDOW_SETBACK
    if side == "front":
        y_at, n = front_window_y, np.array([0.0, -GB_H, s])
    else:
        y_at, n = back_window_y, np.array([0.0, GB_H, s])
    n /= np.linalg.norm(n)
    glass = _quad((0, y_at(0), 0), (GB_W, y_at(0), 0), (GB_W, y_at(GB_H), GB_H), (0, y_at(GB_H), GB_H))
    ports = pv.merge([ring((gx, y_at(GLOVE_Z), GLOVE_Z), n, GLOVE_R, GLOVE_R + 25.0, 34.0) for gx in GLOVE_X])
    frame = []
    out = 40.0 * np.sign(n[1])  # frame flange sits just outside the glass
    frame.append(box_from((-40, min(0, out), -40), (GB_W + 40, max(0, out), 0)) if side == "front" else
                 box_from((-40, GB_D + min(0, out), -40), (GB_W + 40, GB_D + max(0, out), 0)))
    yt = y_at(GB_H)
    frame.append(box_from((-40, min(yt, yt + out), GB_H), (GB_W + 40, max(yt, yt + out), GB_H + 40)))
    for x0 in (-20.0, GB_W + 20.0):
        frame.append(pv.Line((x0, y_at(0), 0), (x0, yt, GB_H)).tube(radius=20, n_sides=4))
    # welded studs and nuts all round the opening (the window bolts on over them)
    bolts = []
    for x in np.arange(40.0, GB_W - 20.0, 115.0):
        for z in (-20.0, GB_H + 20.0):
            bolts.append(cyl((x, y_at(max(min(z, GB_H), 0)) + out * 0.9, z), n, 6, 16, res=8))
    for x0 in (-20.0, GB_W + 20.0):
        for z in np.arange(80.0, GB_H - 40.0, 115.0):
            bolts.append(cyl((x0, y_at(z) + out * 0.6, z), n, 6, 16, res=8))
    return glass, ports, pv.merge(frame), pv.merge(bolts)


def glovebox_shell():
    """Returns {name: (mesh, style)} for the walls, so each can be styled separately."""
    parts = {}
    parts["floor"] = (box_from((0, 0, -WALL_T), (GB_W, GB_D, 0)), dict(color=STAINLESS, specular=0.6))
    parts["left_wall"] = (_end_wall(-WALL_T, 0), dict(color=STAINLESS, specular=0.5))
    parts["right_wall"] = (_end_wall(GB_W, GB_W + WALL_T), dict(color=STAINLESS, specular=0.5))
    parts["ceiling"] = (box_from((0, WINDOW_SETBACK, GB_H), (GB_W, GB_D - WINDOW_SETBACK, GB_H + WALL_T)),
                        dict(color=STAINLESS, specular=0.4))
    front_glass, front_ports, front_frame, front_bolts = _window("front")
    back_glass, back_ports, back_frame, back_bolts = _window("back")
    parts["window"] = (front_glass, dict(color="#bfe3ff", opacity=0.10, specular=1.0))
    parts["back_window"] = (back_glass, dict(color="#bfe3ff", opacity=0.14, specular=1.0))
    parts["glove_ports"] = (front_ports, dict(color=WHITE, specular=0.3))
    parts["back_glove_ports"] = (back_ports, dict(color=WHITE, specular=0.3))
    parts["window_frame"] = (pv.merge([front_frame, front_bolts]), dict(color=STAINLESS_DARK, specular=0.6))
    parts["back_window_frame"] = (pv.merge([back_frame, back_bolts]), dict(color=STAINLESS_DARK, specular=0.6))
    return parts


def wall_signs():
    """NSF and MonArk Quantum Foundry signs on the inside of the left end wall."""
    out = [(box((1.5, 235, 770), (3, 150, 130)), WHITE), (box((2.5, 235, 770), (2, 70, 70)), "#1d4f9c")]
    out.append((box((1.5, 215, 668), (3, 150, 48)), WHITE))
    return out


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
    # LC Technology Solutions sizes: 15 in x 24 in large antechamber, 6 in mini
    big_c = (-WALL_T, GB_D * 0.52, 470.0)
    big = [ring((10, big_c[1], big_c[2]), (1, 0, 0), 0, 212, 14),                    # inner door
           ring((2, big_c[1], big_c[2]), (1, 0, 0), 190, 222, 12),                   # flange
           box((22, big_c[1], big_c[2]), (12, 40, 420)),                             # swing arm
           cyl((-WALL_T - 305, big_c[1], big_c[2]), (1, 0, 0), 205, 610)]            # tube, outside
    mini_c = (-WALL_T, GB_D * 0.20, 190.0)
    mini = [cyl((-WALL_T - 150, mini_c[1], mini_c[2]), (1, 0, 0), 80, 300),   # tube, outside
            cyl((55, mini_c[1], mini_c[2]), (1, 0, 0), 80, 110),               # tube, inside
            ring((112, mini_c[1], mini_c[2]), (1, 0, 0), 0, 88, 12),           # inner door
            box((122, mini_c[1], mini_c[2]), (10, 150, 18))]                   # latch bar
    return pv.merge(big), pv.merge(mini)


# --- Tape exfoliation / pick-and-place gantry (centre-left) ------------------------

EXF_C = np.array([930.0, 480.0, 0.0])  # footprint centre on the floor
EXF_DECK_Z = 190.0
EXF_STROKE = 400.0
EXF_DECK_W = 640.0


def exfoliator():
    """Returns a list of (mesh, color) for the tape exfoliation gantry."""
    out = []
    cx, cy, _ = EXF_C
    deck = box((cx, cy, EXF_DECK_Z - 6), (EXF_DECK_W, 330, 12))
    out.append((deck, BLACK))
    for sx in (-1, 1):
        for sy in (-1, 1):
            out.append((cyl((cx + sx * (EXF_DECK_W / 2 - 35), cy + sy * 135, (EXF_DECK_Z - 12) / 2), (0, 0, 1),
                            14, EXF_DECK_Z - 12), STAINLESS))
    # long linear axis: 400 mm-stroke ball-screw module (marked "400mm" in the video frame),
    # about 210 mm longer than its stroke for the carriage and end blocks, NEMA 23 on the end
    ax_y = cy + 70
    ax_len = EXF_STROKE + 210.0
    ax_cx = cx - 38.0
    out.append((box((ax_cx, ax_y, EXF_DECK_Z + 25), (ax_len, 70, 50)), ALUMINIUM))
    out.append((cyl((ax_cx, ax_y, EXF_DECK_Z + 62), (1, 0, 0), 8, ax_len - 20), "#b0b4b8"))
    out.append((box((ax_cx + ax_len / 2 + 38, ax_y, EXF_DECK_Z + 45), (76, 57, 57)), BLACK))  # NEMA 23
    # carriage + drag chain + blue vacuum lines
    car_x = cx - 40
    out.append((box((car_x, ax_y - 10, EXF_DECK_Z + 75), (110, 90, 30)), "#1d4fbf"))
    out.append((box((cx + 60, ax_y - 85, EXF_DECK_Z + 40), (420, 30, 40)), BLACK))
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
    out.append((cyl((tx + 140, ty - 60, EXF_DECK_Z + 120), (0, 1, 0), 32, 58), "#e4e6e8"))  # Montalvo X load cell
    out.append((cyl((tx + 140, ty - 95, EXF_DECK_Z + 120), (0, 1, 0), 15, 12), YELLOW))     # roller on its shaft
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
    # spare tape roll on the floor in front of the deck (photos 2 and 3)
    out.append((ring((cx + 230, cy - 330, 22), (0, 0, 1), 26, 52, 44), WHITE))
    out.append((ring((cx + 230, cy - 330, 22), (0, 0, 1), 14, 26, 44), RED_HUB))
    return out


# --- Thorlabs Nexus breadboard with the LED source and e-stop (right of the gantry) ----

BENCH_C = np.array([1480.0, 270.0, 0.0])
BENCH_TOP_Z = 95.0


def optics_bench():
    """Black Nexus breadboard on short posts, Olympus LED source with the e-stop on top, linear stage."""
    out = []
    cx, cy, _ = BENCH_C
    out.append((box((cx, cy, BENCH_TOP_Z - 30), (420, 300, 60)), BLACK))      # 61 mm thick breadboard
    for sx in (-1, 1):
        for sy in (-1, 1):
            out.append((cyl((cx + sx * 170, cy + sy * 110, (BENCH_TOP_Z - 60) / 2), (0, 0, 1), 16,
                            BENCH_TOP_Z - 60), STAINLESS))
    lx, ly = cx - 120, cy - 70
    out.append((box((lx, ly, BENCH_TOP_Z + 32), (150, 110, 64)), "#e9e9e9"))    # Olympus LED source
    out.append((box((lx, ly, BENCH_TOP_Z + 99), (80, 80, 70)), YELLOW))         # e-stop box
    out.append((cyl((lx, ly, BENCH_TOP_Z + 149), (0, 0, 1), 22, 30), RED_HUB))
    out.append((box((cx + 80, cy - 20, BENCH_TOP_Z + 15), (220, 70, 30)), "#2d3034"))  # linear stage
    out.append((box((cx + 40, cy - 20, BENCH_TOP_Z + 36), (70, 70, 12)), "#43474d"))   # its carriage
    return out


# --- Epson T-series SCARA and its raised work plate (back right) ---------------------
#
# The Borys Lab photo of the same robot model arriving at Montana State (Aug 2024)
# shows an all-in-one Epson T-series SCARA (controller in the base) on a riser,
# with its black cable duct arcing from the base to the top of arm 2. That matches
# photo 2 here: the light-grey EPSON body is arm 2 and the black conduit is the
# duct. Dimensions follow the T3-B401S (225 + 175 mm arms, 150 mm Z stroke,
# 491 mm tall, about 600 mm with the duct); a T6-B is the other candidate.

SHELF_C = np.array([1445.0, 575.0])   # centre (x, y) of the raised black breadboard
SHELF_TOP_Z = 380.0
SHELF_SIZE = (310.0, 330.0)
SCARA_RISER = 130.0
SCARA_BASE = np.array([1700.0, 560.0, SCARA_RISER])  # J1 axis, on its riser
EPSON_L1, EPSON_L2 = 225.0, 175.0
EPSON_H = 491.0
PNP_C = np.array([1420.0, 520.0, SHELF_TOP_Z])  # substrate tray on the plate, under the overhead camera


def raised_shelf():
    """Raised black breadboard the Epson works over, on four posts (photo 2, right)."""
    cx, cy = SHELF_C
    sx, sy = SHELF_SIZE
    out = [(box((cx, cy, SHELF_TOP_Z - 6.5), (sx, sy, 13)), BLACK)]
    for dx in (-1, 1):
        for dy in (-1, 1):
            out.append((cyl((cx + dx * (sx / 2 - 30), cy + dy * (sy / 2 - 30), (SHELF_TOP_Z - 13) / 2),
                            (0, 0, 1), 12.7, SHELF_TOP_Z - 13), STAINLESS))
    return out


def scara(target=None, quill_z=None):
    """Epson T-series SCARA, arm posed over `target` (x, y); returns (parts, tool point)."""
    out = []
    bx, by, bz = SCARA_BASE
    target = PNP_C if target is None else np.asarray(target, float)
    quill_z = SHELF_TOP_Z + 40.0 if quill_z is None else quill_z
    grey, white = "#d5d9dd", "#f4f5f6"
    out.append((box_from((bx - 60, by - 100, 0), (bx + 190, by + 100, bz)), ALUMINIUM))       # riser block
    out.append((box_from((bx + 10, by - 90, bz), (bx + 190, by + 90, bz + 420)), grey))       # base + controller
    out.append((cyl((bx, by, bz + 150), (0, 0, 1), 70, 300), grey))                           # J1 housing
    out.append((cyl((bx + 150, by, bz + 428), (0, 0, 1), 14, 16), "#ff9d2e"))                  # status lamp
    dx, dy = target[0] - bx, target[1] - by
    r = np.clip(np.hypot(dx, dy), abs(EPSON_L1 - EPSON_L2) + 1, EPSON_L1 + EPSON_L2 - 1)
    elbow = np.arccos((r**2 - EPSON_L1**2 - EPSON_L2**2) / (2 * EPSON_L1 * EPSON_L2))
    t1 = np.arctan2(dy, dx) - np.arctan2(EPSON_L2 * np.sin(elbow), EPSON_L1 + EPSON_L2 * np.cos(elbow))
    t2 = t1 + elbow
    j1 = np.array([bx, by, 0.0])
    j2 = j1 + EPSON_L1 * np.array([np.cos(t1), np.sin(t1), 0.0])
    j3 = j2 + EPSON_L2 * np.array([np.cos(t2), np.sin(t2), 0.0])
    links = ((j1, j2, 120, bz + 300, bz + 360), (j2, j3, 125, bz + 360, bz + EPSON_H - 20))
    for a, b, w, z0, z1 in links:
        mid, vec = (a + b) / 2, b - a
        seg = box((0, 0, 0), (np.linalg.norm(vec), w, z1 - z0))
        seg.rotate_z(np.degrees(np.arctan2(vec[1], vec[0])), inplace=True)
        seg.translate((mid[0], mid[1], (z0 + z1) / 2), inplace=True)
        out.append((seg, white))
        for p in (a, b):
            out.append((cyl((p[0], p[1], (z0 + z1) / 2), (0, 0, 1), w / 2, z1 - z0), white))
    out.append((cyl((j3[0], j3[1], bz + 330), (0, 0, 1), 42, 60), "#2f5fb3"))                 # J3/J4 ring
    q_top = bz + EPSON_H
    out.append((cyl((j3[0], j3[1], (q_top + quill_z + 30) / 2), (0, 0, 1), 8, q_top - quill_z - 30), "#b5b9bd"))
    out.append((box((j3[0], j3[1], quill_z + 15), (40, 40, 30)), "#3a3d41"))                 # vacuum tool
    # black corrugated duct from the top of the base, arcing over to the top of arm 2
    a2 = j2 + 0.35 * (j3 - j2)
    duct = [(bx + 100, by, bz + 420), (bx + 90, by, bz + 560), (bx + 20, by, bz + 610),
            ((bx + a2[0]) / 2, (by + a2[1]) / 2, bz + 600), (a2[0], a2[1], bz + EPSON_H + 40), (a2[0], a2[1], q_top - 5)]
    out.append((tube_path(duct, 18), BLACK))
    return out, np.array([j3[0], j3[1], quill_z])


# --- Ceiling-mounted items already present ---------------------------------------

DOME_C = np.array([280.0, 245.0, GB_H])  # Amcrest dome, just behind the top front flange


def ceiling_items():
    out = []
    out.append((box((1100, 430, GB_H - 6), (520, 210, 12)), "#e9eef4"))   # light panel
    out.append((box((1250, 615, GB_H - 25), (240, 80, 50)), BLACK))        # PoE switch / USB hubs
    out.append((box((1250, 615, GB_H - 70), (200, 70, 36)), BLACK))
    # slotted wire duct along the top of the left end wall and down the back-left corner
    out.append((box((14, GB_D / 2, GB_H - 30), (28, GB_D - 2 * WINDOW_SETBACK - 40, 50)), "#9da3a8"))
    out.append((box((14, back_window_y(450) - 40, 450), (28, 50, GB_H - 120)), "#9da3a8"))
    out.append((cyl((DOME_C[0] - 115, DOME_C[1] - 25, GB_H - 75), (0, 0, 1), 34, 150), WHITE))  # filter
    return out


def amcrest_dome():
    """The PoE dome camera already on the ceiling at the front left."""
    c = DOME_C
    base = cyl(c - (0, 0, 15), (0, 0, 1), 60, 30)
    dome = pv.Sphere(radius=48, center=c - (0, 0, 40), theta_resolution=40, phi_resolution=40)
    return pv.merge([base, dome]), c - (0, 0, 60)


# --- Designated work areas named in the 26 Oct walkthrough --------------------------

UNPACK_C = np.array([200.0, 480.0, 0.0])      # beside the antechamber inner door
MOTHER_TAPE_C = np.array([480.0, 270.0, 0.0])  # between the unpacking area and the gantry


def floor_zone(center, size, color):
    """Thin coloured mat marking a designated area on the glovebox floor (or a shelf)."""
    return box((center[0], center[1], center[2] + 1.5), (size[0], size[1], 3.0)), color


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
    """Gel-Pak style substrate tray in the Epson's pick-and-place zone, on the raised shelf."""
    cx, cy, cz = PNP_C
    out = [floor_zone(PNP_C, (220, 180), "#d9f5e6")]
    out.append((box((cx, cy, cz + 10), (150, 110, 14)), "#30343a"))
    for i in range(4):
        for j in range(3):
            out.append((box((cx - 52 + i * 35, cy - 35 + j * 35, cz + 18), (16, 16, 2)), "#8fb3d9"))
    return out
