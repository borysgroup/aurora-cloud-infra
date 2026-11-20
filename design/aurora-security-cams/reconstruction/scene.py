"""The Aurora glovebox interior as individual CAD parts, placed in the aurora_chamber frame (mm).

Frame: x along the box from the antechamber-end wall, y from the open side (deck edge, y = 0) to the
far window, z up from the deck. Every part records where its size and position come from in SOURCES:

  datasheet    manufacturer drawing or catalogue size (not scaled)
  standard     a standard size (NEMA flange, breadboard hole pitch, US Letter, ...)
  two-view     triangulated from both calibrated cameras (cameras.py)
  one-view     back-projected from one camera onto a known plane
  chamber      the walkthrough-measured chamber model (design/aurora-chamber, issue #23)
  estimate     read off the images by eye; no measurement

Colours are the median sRGB of each part in the 2026-11-19 18:22 UTC frames (camera white balance).
"""
import numpy as np
import trimesh

from parts import Part, box, cyl, hole_grid, obox, ring, rounded_box, slot, stepper, tube

# ---- colours (sampled from the frames) -------------------------------------------------------------
STAINLESS, STEEL_WALL, DUCT = "#b5b0a3", "#bdb39c", "#8f8c88"
BLACK_ANOD, BLACK, ALU = "#34363a", "#1e1c1a", "#d3d8d6"
EPSON_WHITE, EPSON_GREY, EPSON_DUCT = "#d4dad5", "#aeb4b2", "#202020"
RED, TAPE_WHITE, TAPE_BLUE = "#b3150d", "#e4ebec", "#6a90cf"
YELLOW, BLUE_TUBE, ORANGE = "#e6d200", "#2a62c4", "#f08a1c"
MICRO_WHITE, TRAY_ALU, CHIP = "#d2d8d2", "#c9cfd0", "#3a1f3f"

# ---- glovebox shell (chamber model, walkthrough reconstruction) -------------------------------------
GB_W, GB_D, GB_H = 1200.0, 1120.0, 790.0
FRONT_LEAN, BACK_LEAN = 57.0, 60.0
WALL_T = 6.0

SOURCES = {}


def src(name, kind, note):
    SOURCES[name] = dict(source=kind, note=note)


def shell():
    out = []
    out.append(Part("deck", box((0, 0, -WALL_T), (GB_W, GB_D, 0)), STAINLESS, "glovebox"))
    out.append(Part("antechamber-end wall", box((-WALL_T, 0, 0), (0, GB_D, GB_H)), STEEL_WALL, "glovebox"))
    # the far end is clear too (the room shows through it in Overhead 1): frame only
    for lo, hi in (((GB_W, 0, 0), (GB_W + WALL_T, GB_D, 40)), ((GB_W, 0, GB_H - 25), (GB_W + WALL_T, GB_D, GB_H)),
                   ((GB_W, 0, 0), (GB_W + WALL_T, 40, GB_H)), ((GB_W, GB_D - 40, 0), (GB_W + WALL_T, GB_D, GB_H))):
        out.append(Part("far-end window frame", box(lo, hi), STEEL_WALL, "glovebox"))
    out.append(Part("ceiling", box((0, FRONT_LEAN, GB_H), (GB_W, GB_D - BACK_LEAN, GB_H + WALL_T)), STEEL_WALL,
                    "glovebox"))
    # the two long sides are clear windows in stainless frames: draw the frames only
    for y0, y1, name in ((0, FRONT_LEAN, "open side"), (GB_D, GB_D - BACK_LEAN, "far side")):
        for z0, z1 in ((0, 55), (GB_H - 25, GB_H)):
            ya = y0 + (y1 - y0) * z0 / GB_H
            yb = y0 + (y1 - y0) * z1 / GB_H
            out.append(Part(f"{name} window frame", box((0, min(ya, yb) - 8, z0), (GB_W, max(ya, yb) + 8, z1)),
                            STEEL_WALL, "glovebox"))
    src("glovebox", "chamber", "1200 x 1120 x 790 mm interior, sloped long windows (57 and 60 mm lean)")
    # antechamber inner door: 15-inch LC Technology antechamber, hub back-projected from Overhead 2
    hub = np.array([0.0, 460.0, 226.0])
    out.append(Part("antechamber door", cyl(hub, hub + (10, 0, 0), 186.0, 64), "#c4c4b8", "glovebox"))
    out.append(Part("antechamber door hub", cyl(hub, hub + (45, 0, 0), 22.0, 32), "#9c9a92", "glovebox"))
    out.append(Part("antechamber door bar", obox(hub + (14, 0, 0), (8, 300, 30), 0).apply_transform(
        trimesh.transformations.rotation_matrix(np.radians(-40), (1, 0, 0), hub + (14, 0, 0))), "#a7a59c",
        "glovebox"))
    src("antechamber door", "one-view", "hub and rim back-projected onto the wall plane from Overhead 2: radius "
        "180-190 mm, matching the 15-inch antechamber (datasheet 190 mm)")
    # QR sign (white sheet, black QR panel) on the wall, bottom edge back-projected from Overhead 2
    out.append(Part("QR sign", box((0.5, 705, 274), (2.0, 950, 470)), "#e9e9e4", "glovebox"))
    out.append(Part("QR panel", box((2.0, 760, 300), (3.0, 900, 450)), "#1c1c1c", "glovebox"))
    src("QR sign", "one-view", "bottom edge back-projected onto the wall from Overhead 2; the top is out of view")
    return out


def ducts():
    """Slotted grey wiring duct along the deck edges: Panduit Type G 1 x 2 in (32 x 54 mm), slots every 12.7 mm."""
    out = []
    w, h = 32.0, 54.0

    def run(p0, p1, name):
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        v = p1 - p0
        L = np.linalg.norm(v)
        yaw = np.degrees(np.arctan2(v[1], v[0]))
        c = (p0 + p1) / 2
        out.append(Part(name, obox((c[0], c[1], h / 2), (L, w, h), yaw), DUCT, "ducts"))
        n = np.array([-v[1], v[0], 0]) / L
        slots = []
        for s in np.arange(10, L - 10, 12.7):
            q = p0 + v * s / L
            for side in (-1, 1):
                slots.append(obox(q + side * n * (w / 2 + 0.3) + (0, 0, h * 0.62), (5.0, 0.8, h * 0.55), yaw))
        out.append(Part(name + " slots", trimesh.util.concatenate(slots), "#3c3b39", "ducts"))

    run((60, GB_D - 28, 0), (GB_W - 40, GB_D - 28, 0), "duct, far window")
    run((24, 300, 0), (24, GB_D - 50, 0), "duct, antechamber wall")
    src("ducts", "standard", "Panduit Type G 1 x 2 in slotted duct (32 x 54 mm), along the edges seen in both views")
    return out


# ---- chip tray and XY gantry (tray pose from the two-view calibration) ------------------------------

def tray_and_gantry(cal):
    out = []
    t = cal["tray"]
    c = np.array(t["centre"])
    yaw = np.radians(t["yaw_deg"])
    p = t["pitch_mm"]
    u = np.array([np.cos(yaw), np.sin(yaw), 0.0]) * t["mirror"]   # along the 6 columns
    v = np.array([-np.sin(yaw), np.cos(yaw), 0.0])                 # along the 10 rows
    yawd = np.degrees(np.arctan2(u[1], u[0]))
    W, L = 6 * p + 16, 10 * p + 16
    out.append(Part("chip tray", obox(c - (0, 0, 4), (W, L, 8), yawd), TRAY_ALU, "gantry"))
    out.append(Part("chip tray holder", obox(c - (0, 0, 12), (W + 22, L + 22, 8), yawd), "#b9bfc0", "gantry"))
    import json, os
    tr = json.load(open(os.path.join(os.path.dirname(__file__), "..", "vision", "out", "chip_tray.json")))
    chips = []
    for q in tr["pockets"]:
        state = q["cam0"]["state"]
        if state == "empty":
            continue
        pc = c + (q["col"] - 2.5) * p * u + (q["row"] - 4.5) * p * v + (0, 0, 0.6)
        ang = np.radians(q["cam0"]["angle_deg_canonical"] if state == "misplaced" else 0.0)
        chips.append(obox(pc, (0.68 * p, 0.68 * p, 1.2), yawd + np.degrees(ang)))
    out.append(Part("chips", trimesh.util.concatenate(chips), CHIP, "gantry"))
    src("chip tray", "two-view", f"6 x 10 pockets fitted in both views; pitch {p:.1f} mm, centre and yaw from the "
        "joint calibration; chips placed per pocket from chip_tray.json (3 empty, 1 rotated)")
    return out


# ---- Epson T6-B602S SCARA on its riser --------------------------------------------------------------
# Epson's dimensioned T-B drawing (T-B manual Rev.13, pp. 43, 45, 52, 162). Local frame: origin on the J1
# axis at the base's underside, X towards J2 with the arm straight (the base's front), Y to its left, Z up.
T6 = dict(L1=325.0, L2=275.0, arm1=(209.5, 259.5), arm1_w=103.0, arm1_x=(-60.0, 376.0), arm2=(272.5, 465.3),
          arm2_w=135.5, arm2_tip=58.5, arm2_top=((-67.75, 465.3), (125.0, 465.3), (175.0, 451.0), (245.0, 414.0),
                                                  (333.5, 340.0)),
          flange=((-160.0, 35.0), 84.5, 8.0), column_w=129.0,
          column=((-160.0, 8.0), (30.0, 8.0), (66.0, 150.0), (66.0, 200.0), (-160.0, 200.0)),
          rear_column=(-160.0, -100.0), box=((65.5, 272.0), (65.5, 465.0), (-70.0, 465.0), (-151.0, 421.0),
                                              (-160.8, 421.0), (-160.8, 272.0)), box_w=130.0,
          shaft_top=590.5, shaft_len=410.0, stroke=200.0, shaft_r=10.0, duct_od=32.0, duct_fitting=(23.0, 33.0),
          j1_range=132.0, j2_range=150.0)


def _hull(pts):
    return trimesh.convex.convex_hull(np.asarray(pts, float))


def epson(j1, base_underside_z, back_dir, th1_deg, th2_deg, z_down=0.0):
    """Parts of the T6 for joint angles th1 (arm 1, from world +x) and th2 (arm 2 relative to arm 1), the
    shaft lowered by z_down from fully up. back_dir: unit xy vector from J1 to the back of the base."""
    out = []
    j1 = np.asarray(j1, float)
    z0 = base_underside_z
    b = np.asarray(back_dir, float) / np.linalg.norm(back_dir)
    fx = -b                                   # the base's front (local +X)
    fy = np.array([-fx[1], fx[0]])            # local +Y

    def base_pts(profile_xz, half_w):
        P = []
        for X, Zl in profile_xz:
            for Y in (-half_w, half_w):
                q = j1 + X * fx + Y * fy
                P.append((q[0], q[1], z0 + Zl))
        return P

    (fx0, fx1), fyh, ft = T6["flange"]
    out.append(Part("Epson base flange", _hull(base_pts([(fx0, 0), (fx1, 0), (fx1, ft), (fx0, ft)], fyh)),
                    EPSON_GREY, "epson"))
    out.append(Part("Epson base", _hull(base_pts(T6["column"], T6["column_w"] / 2)), EPSON_WHITE, "epson"))
    out.append(Part("Epson J1 bearing", cyl((j1[0], j1[1], z0 + 200), (j1[0], j1[1], z0 + 209.5), 60), EPSON_GREY,
                    "epson"))
    r0, r1 = T6["rear_column"]
    out.append(Part("Epson rear column", _hull(base_pts([(r0, 200), (r1, 200), (r1, 272), (r0, 272)],
                                                         T6["column_w"] / 2)), EPSON_WHITE, "epson"))
    out.append(Part("Epson controller box", _hull(base_pts(T6["box"], T6["box_w"] / 2)), EPSON_WHITE, "epson"))
    led = j1 + (-39.0) * fx
    out.append(Part("Epson LED dome", cyl((led[0], led[1], z0 + 465), (led[0], led[1], z0 + 474), 14), "#e8eaea",
                    "epson"))
    t1 = np.radians(th1_deg)
    u1 = np.array([np.cos(t1), np.sin(t1)])
    j2 = j1 + T6["L1"] * u1
    t2 = t1 + np.radians(th2_deg)
    u2 = np.array([np.cos(t2), np.sin(t2)])
    j3 = j2 + T6["L2"] * u2
    w1 = T6["arm1_w"]
    a1z = (z0 + T6["arm1"][0], z0 + T6["arm1"][1])
    out.append(Part("Epson arm 1", slot(j1 + (T6["arm1_x"][0] + w1 / 2) * u1, j1 + (T6["arm1_x"][1] - w1 / 2) * u1,
                                        w1, *a1z), EPSON_WHITE, "epson"))
    # arm 2: its side profile (top falls towards the tip) across its width, plus the rounded J2 end and tip
    n2 = np.array([-u2[1], u2[0]])
    P = []
    for sx, zt in T6["arm2_top"]:
        for sy in (-T6["arm2_w"] / 2, T6["arm2_w"] / 2):
            q = j2 + sx * u2 + sy * n2
            P += [(q[0], q[1], z0 + T6["arm2"][0]), (q[0], q[1], z0 + zt)]
    out.append(Part("Epson arm 2", _hull(P), EPSON_WHITE, "epson"))
    out.append(Part("Epson arm 2 J2 end", cyl((j2[0], j2[1], z0 + T6["arm2"][0]), (j2[0], j2[1], z0 + T6["arm2"][1]),
                                              T6["arm2_w"] / 2, 40), EPSON_WHITE, "epson"))
    out.append(Part("Epson arm 2 tip", cyl((j3[0], j3[1], z0 + T6["arm2"][0]), (j3[0], j3[1], z0 + 380),
                                           T6["arm2_tip"], 40), EPSON_WHITE, "epson"))
    top = z0 + T6["shaft_top"] - z_down
    out.append(Part("Epson J3 shaft", cyl((j3[0], j3[1], top - T6["shaft_len"]), (j3[0], j3[1], top), T6["shaft_r"], 24),
                    "#c8ccce", "epson"))
    out.append(Part("Epson shaft top stop", cyl((j3[0], j3[1], top - 12), (j3[0], j3[1], top), 19), "#9da3a6", "epson"))
    out.append(Part("Epson shaft lower stop", cyl((j3[0], j3[1], top - T6["shaft_len"]),
                                                 (j3[0], j3[1], top - T6["shaft_len"] + 12), 20), "#9da3a6", "epson"))
    # user duct: corrugated, OD 32, from the fitting on the box top over J1 to the fitting on arm 2 over J2;
    # a semicircle of radius L1/2 in Epson's drawing, flattened here to stay under the ceiling
    fr, fh = T6["duct_fitting"]
    p0 = np.r_[j1, z0 + 465.0]
    p1 = np.r_[j2, z0 + T6["arm2"][1]]
    out.append(Part("Epson duct fitting (J1)", cyl(p0, p0 + (0, 0, fh), fr, 24), EPSON_DUCT, "epson"))
    out.append(Part("Epson duct fitting (J2)", cyl(p1, p1 + (0, 0, fh), fr, 24), EPSON_DUCT, "epson"))
    a0, a1 = p0 + (0, 0, fh), p1 + (0, 0, fh)
    rise = min(T6["L1"] / 2, GB_H - 6 - T6["duct_od"] / 2 - max(a0[2], a1[2]))
    arc = [a0 + (a1 - a0) * (0.5 - 0.5 * np.cos(q)) + np.array([0, 0, rise * np.sin(q)])
           for q in np.linspace(0, np.pi, 13)]
    out.append(Part("Epson user duct", tube(arc, T6["duct_od"] / 2, 16), EPSON_DUCT, "epson"))
    return out, dict(j2=j2, j3=j3)


# ---- breadboards (black anodised, M6 on a 25 mm grid; Thorlabs metric sizes) -------------------------

def breadboard(name, x0, y0, sx, sy, z_top, t=12.7, pitch=25.0, edge=12.5, legs=None):
    out = [Part(name, box((x0, y0, z_top - t), (x0 + sx, y0 + sy, z_top)), BLACK_ANOD, "breadboards")]
    nu, nv = int((sx - 2 * edge) // pitch) + 1, int((sy - 2 * edge) // pitch) + 1
    out.append(Part(name + " holes", hole_grid((x0 + edge, y0 + edge, z_top), (1, 0, 0), (0, 1, 0), nu, nv, pitch),
                    "#0e0e0f", "breadboards"))
    if legs:
        h = z_top - t
        for px in (x0 + 40, x0 + sx - 40):
            for py in (y0 + 40, y0 + sy - 40):
                out.append(Part(name + " post", cyl((px, py, 0), (px, py, h), 12.7), "#c6cacc", "breadboards"))
    return out


def breadboards():
    out = []
    # under the Epson, the ASI stages and the microscope: front (-x) edge at x 835 seen from Overhead 1
    out += breadboard("main breadboard", 838, 380, 362, 700, 75.7, legs=True)
    # exfoliator breadboard on 147 mm posts (post foot and top measured from Overhead 2)
    out += breadboard("exfoliator breadboard", 230, 240, 450, 420, 160.0, legs=True)
    # loose breadboard lying on the deck, seen at the bottom right of Overhead 2 (hole rows at 25 mm pitch)
    out += breadboard("loose breadboard", 700, 545, 225, 150, 30.0)
    src("breadboards", "one-view", "edges back-projected onto their planes; holes M6 on 25 mm (the hole rows "
        "measure 24.5-26.4 mm at these heights); sizes rounded to Thorlabs metric sizes where the edges are hidden")
    return out


# ---- XY gantry under the chip tray (Overhead 2 back-projections) -------------------------------------

def ballscrew_axis(name, p0, p1, z, rail_w=20.0, screw_d=16.0, color_block=BLACK):
    """Linear axis: profile rail + SFU1605 ball screw (16 mm) with end supports."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    v = p1 - p0; L = np.linalg.norm(v); yaw = np.degrees(np.arctan2(v[1], v[0]))
    c = (p0 + p1) / 2
    n = np.array([-v[1], v[0]]) / L
    out = [Part(name + " base", obox((c[0], c[1], z - 12), (L + 40, 90, 24), yaw), ALU, "gantry")]
    for side in (-1, 1):
        q = c + side * n * 32
        out.append(Part(name + " rail", obox((q[0], q[1], z + 7), (L + 30, rail_w, 14), yaw), "#9ea4a8", "gantry"))
    out.append(Part(name + " screw", cyl((p0[0], p0[1], z + 22), (p1[0], p1[1], z + 22), screw_d / 2, 20), "#c9cdd0",
                    "gantry"))
    for q in (p0, p1):
        out.append(Part(name + " end support", obox((q[0], q[1], z + 18), (24, 60, 40), yaw), color_block, "gantry"))
    return out


def gantry(cal):
    out = []
    t = cal["tray"]
    c = np.array(t["centre"])
    # lower axis along y at x ~ 600, upper axis along x at y ~ 510, plate top 160 (post 147 + 12.7)
    out += ballscrew_axis("Y axis", (600, 262), (600, 492), 172.0)
    out += ballscrew_axis("X axis", (285, 505), (680, 520), 192.0)  # seen from both views
    out.append(Part("Y axis motor", stepper((600, 520, 194), (0, -1, 0), 57.2, 76), BLACK, "gantry"))
    out.append(Part("X axis motor", stepper((262, 504, 214), (1, 0, 0), 57.2, 76), BLACK, "gantry"))
    # tray carriage: plate under the tray holder, on the X axis carriage
    out.append(Part("tray carriage", obox(c - (0, 0, 40), (110, 90, 40), t["yaw_deg"]), BLACK, "gantry"))
    # yellow printed carriage with two steppers, riding at the -x end of the X axis (Overhead 2, top at z ~ 320)
    out.append(Part("printed carriage", box((255, 425, 255), (390, 500, 320)), YELLOW, "gantry"))
    out.append(Part("carriage motor 1", stepper((330, 455, 320), (0, 0, -1), 42.3, 48), BLACK, "gantry"))
    out.append(Part("carriage motor 2", stepper((391, 515, 320), (0, 0, -1), 42.3, 48), BLACK, "gantry"))
    # third axis along y at x ~ 180 (top screw in Overhead 2, z ~ 210)
    out += ballscrew_axis("top axis", (180, 290), (180, 440), 205.0)
    # drag chains (igus-style, black)
    out.append(Part("drag chain", tube([(250, 300, 260), (220, 360, 330), (240, 430, 340), (300, 470, 330)], 14),
                    BLACK, "gantry"))
    out.append(Part("drag chain 2", tube([(420, 560, 210), (480, 610, 260), (560, 610, 250), (620, 560, 215)], 14),
                    BLACK, "gantry"))
    src("gantry", "one-view", "posts (147 mm), plate edge, both screw axes and the Y motor back-projected from "
        "Overhead 2 at their heights; NEMA 23 (57.2 mm) and NEMA 17 (42.3 mm) flanges; SFU1605 screws (16 mm)")
    return out


# ---- exfoliator: tape reels, aluminium housing, press motor, linear stage ----------------------------

def exfoliator():
    out = []
    # the two red tape reels, flange centres triangulated from both views (ray gaps 2 and 9 mm), axes along x
    for name, ctr, tape in (("supply reel (blue tape)", (669, 309, 399), TAPE_BLUE),
                            ("take-up reel (white tape)", (670, 142, 401), TAPE_WHITE)):
        ctr = np.array(ctr, float)
        out.append(Part(name + " flange", ring(ctr - (16, 0, 0), (1, 0, 0), 12, 48, 4), RED, "exfoliator"))
        out.append(Part(name + " flange", ring(ctr + (16, 0, 0), (1, 0, 0), 12, 48, 4), RED, "exfoliator"))
        out.append(Part(name + " tape", ring(ctr, (1, 0, 0), 22, 42, 28), tape, "exfoliator"))
        out.append(Part(name + " hub", ring(ctr, (1, 0, 0), 6, 22, 30), RED, "exfoliator"))
    # aluminium housing between the reels (top face back-projected from Overhead 1 at z 300)
    out.append(Part("exfoliator housing", box((700, 70, 160), (790, 270, 330)), ALU, "exfoliator"))
    out.append(Part("press stepper", stepper((745, 230, 330), (0, 0, -1), 57.2, 80), BLACK, "exfoliator"))
    out.append(Part("press stepper label", cyl((745, 230, 410), (745, 230, 412), 22), "#2a5bd0", "exfoliator"))
    # finned roller motor in front of the supply reel
    out.append(Part("roller motor", cyl((640, 300, 330), (640, 300, 250), 32, 32), "#c7cbcd", "exfoliator"))
    # 'EXFOLIATOR' linear stage behind the tray, along y (seen from Overhead 1)
    out += [Part("exfoliator stage", p.mesh, p.color, "exfoliator") for p in
            ballscrew_axis("exfoliator stage", (690, 482), (767, 253), 178.0)]
    src("exfoliator", "two-view", "reel centres triangulated; housing, motors and stage back-projected from "
        "Overhead 1; reel diameter 85-95 mm from the image size at the triangulated distance")
    return out


# ---- microscope, ASI stages, Thorlabs box ------------------------------------------------------------

def microscope():
    """Olympus/Evident BX3 modules on a custom plate (no stand), on an ASI XY stage. Module sizes from the
    Evident components guide: BX3-URA illuminator 402.5 long (incl. a 40 mm lamp port), 84 tall, drum 180
    wide reaching 141.5 ahead of the optical axis; U-DP dual port 88 x 151 x 57; U-TLU tube 60 x 57.6.
    ASI OE-1250 XY stage 228.6 x 215.9 x 45.1 (best guess from its screw rows and size)."""
    out = []
    ox, oy = 1118.0, 379.0                    # optical axis (objective, Overhead 1 ray at the model's height)
    z_tip = 250.0                             # objective tip
    z_mount = z_tip + 75                      # nosepiece mount = illuminator underside
    # ASI stage on a riser, sample insert, objective and nosepiece
    out.append(Part("ASI OE-1250 XY stage", box((ox - 160, oy - 108, 130), (ox + 69, oy + 108, 175)), BLACK,
                    "microscope"))
    out.append(Part("ASI stage riser", box((ox - 130, oy - 90, 75.7), (ox + 40, oy + 90, 130)), BLACK, "microscope"))
    out.append(Part("sample insert", box((ox - 80, oy - 55, 175), (ox + 30, oy + 55, 182)), "#8d9397", "microscope"))
    out.append(Part("20x objective", cyl((ox, oy, z_tip), (ox, oy, z_tip + 45), 13), "#202224", "microscope"))
    out.append(Part("objective green ring", cyl((ox, oy, z_tip + 30), (ox, oy, z_tip + 34), 13.5), "#2f9a4a",
                    "microscope"))
    out.append(Part("nosepiece", cyl((ox, oy, z_tip + 45), (ox, oy, z_mount), 42), "#d9ddd9", "microscope"))
    # BX3-URA: drum ahead of the axis (towards +y, the Epson side in Overhead 1), body and lamp port behind
    out.append(Part("BX3-URA illuminator drum", cyl((ox, oy + 51.5, z_mount), (ox, oy + 51.5, z_mount + 84), 90),
                    MICRO_WHITE, "microscope"))
    out.append(Part("BX3-URA illuminator body", box((ox - 45, oy - 221, z_mount + 10), (ox + 45, oy + 20, z_mount + 84)),
                    MICRO_WHITE, "microscope"))
    out.append(Part("BX3-URA lamp port", cyl((ox, oy - 221, z_mount + 47), (ox, oy - 261, z_mount + 47), 22),
                    "#c9ccc9", "microscope"))
    zt = z_mount + 84
    out.append(Part("U-DP dual port", box((ox - 44, oy - 100, zt), (ox + 44, oy + 51, zt + 57)), MICRO_WHITE,
                    "microscope"))
    out.append(Part("U-TLU tube", cyl((ox, oy, zt + 57), (ox, oy, zt + 114.6), 30), "#1b1b1c", "microscope"))
    out.append(Part("microscope camera", box((ox - 35, oy - 35, zt + 114.6), (ox + 35, oy + 35, zt + 180)), "#151515",
                    "microscope"))
    # the custom plate the modules hang from, on the main breadboard
    out.append(Part("microscope mounting plate", box((ox + 60, oy - 120, 75.7), (ox + 75, oy + 120, z_mount + 40)),
                    "#c9ccc9", "microscope"))
    out += breadboard("microscope breadboard", 965, 150, 235, 195, 380.0)
    out.append(Part("light source", cyl((1060, 150, 400), (1060, 90, 400), 38), "#151515", "microscope"))
    out.append(Part("Thorlabs platform", box((815, 371, 75.7), (990, 515, 200)), "#202124", "microscope"))
    # two black docking fixtures on the main breadboard between the Epson and the stages (Overhead 1:
    # feet back-projected at the board height, tops at z 280)
    for x0, x1, y0, y1 in ((885, 975, 645, 775), (1000, 1093, 625, 760)):
        for yy in (y0, y1 - 12):
            out.append(Part("docking fixture side", box((x0, yy, 75.7), (x1, yy + 12, 270)), BLACK, "microscope"))
        out.append(Part("docking fixture top", box((x0, y0, 270), (x1, y1, 282)), BLACK, "microscope"))
    src("microscope", "datasheet", "Olympus BX3-URA, U-DP and U-TLU sizes (Evident components guide); ASI "
        "OE-1250 stage size; positions from the objective on the Overhead 1 ray at z 250, elevated breadboard "
        "back-projected at z 380, Thorlabs platform front edge at z 180-220")
    return out


def deck_items():
    out = []
    # Stanley-style 25 ft tape measure on the deck, footprint back-projected from Overhead 2
    out.append(Part("tape measure", rounded_box((255, 865, 25), (90, 90, 50), 12, 30), YELLOW, "deck"))
    out.append(Part("tape measure belt clip", box((215, 850, 10), (226, 880, 38)), "#202020", "deck"))
    src("tape measure", "one-view", "back-projected onto the deck from Overhead 2; case about 90 x 90 x 50 (FatMax-style, estimate)")
    return out


# ---- assembled scene ---------------------------------------------------------------------------------

# fitted to the SAM silhouettes in both views (silhouette.py; IoU 0.64 in Overhead 1, 0.82 in Overhead 2),
# within J1 +/-132 and J2 +/-150 deg, with arm 2's tip kept inside the box
ROBOT = dict(j1=(934.6, 879.4), base_underside_z=161.4, back_yaw_deg=73.5, th1_deg=-79.9, th2_deg=17.6,
             riser_h=85.7)


def riser_block(j1, back_dir, base_underside_z, h):
    """Aluminium block under the Epson's base flange (flange footprint plus 10 mm all round)."""
    b = np.asarray(back_dir, float) / np.linalg.norm(back_dir)
    (x0, x1), yh, _ = T6["flange"]
    c = np.asarray(j1, float) - b * (x0 + x1) / 2
    yaw = np.degrees(np.arctan2(b[1], b[0]))
    return Part("Epson riser block", obox((c[0], c[1], base_underside_z - h / 2), (x1 - x0 + 20, 2 * yh + 20, h), yaw),
                ALU, "epson")


def build(cal, robot=None):
    r = dict(ROBOT, **(robot or {}))
    parts = []
    parts += shell()
    parts += ducts()
    parts += breadboards()
    parts += tray_and_gantry(cal)
    parts += gantry(cal)
    parts += exfoliator()
    parts += microscope()
    parts += deck_items()
    b = np.array([np.cos(np.radians(r["back_yaw_deg"])), np.sin(np.radians(r["back_yaw_deg"]))])
    j1 = np.array(r["j1"])
    ep, jj = epson(j1, r["base_underside_z"], b, r["th1_deg"], r["th2_deg"])
    ep.append(riser_block(j1, b, r["base_underside_z"], r["riser_h"]))
    # Overhead 2's out-of-focus black object lies exactly on arm 2's silhouette (the model alone matches the
    # white housing plus the black object at IoU 0.77), so it rides on arm 2; its make is not known
    u2 = (jj["j3"] - jj["j2"]) / np.linalg.norm(jj["j3"] - jj["j2"])
    c = jj["j2"] + 100 * u2
    ep.append(Part("black unit on arm 2", obox((c[0], c[1], r["base_underside_z"] + 465.3 + 22.5), (120, 100, 45),
                                               np.degrees(np.arctan2(u2[1], u2[0]))), "#151515", "epson"))
    parts += ep
    src("epson", "datasheet", "Epson T6-B602S outline from Epson's dimensioned T-B drawing (T-B manual Rev.13, pp. 43, "
        "45, 52, 162); J1, base yaw and height, riser and both arm angles fitted to the robot's SAM silhouettes in "
        "both views (IoU 0.64 and 0.82); the black unit on arm 2 is placed from Overhead 2, make unknown")
    return parts


def export(parts, path_glb):
    sc = trimesh.Scene()
    for i, p in enumerate(parts):
        sc.add_geometry(p.mesh, node_name=f"{i:03d} {p.name}", geom_name=f"{i:03d} {p.name}")
    sc.export(path_glb)


