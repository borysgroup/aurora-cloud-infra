"""The detailed glovebox reconstruction: the same parts, positions and sources as scene.py's outline,
with each part's shape refined (fillets, chamfers, real holes, threads, chain links, revolved
profiles), Epson's own CAD for the robot, a finish per part (materials.py) and the printed marks as
decals (decals.py).

Positions are unchanged from the outline unless a comment says otherwise, so the camera checks of
the outline (README, "CAD reconstruction") still hold. New shape detail comes from catalogue drawings
(detail.py lists them) or, where no drawing exists, from the 18:22 UTC frames; SOURCES records which.
"""
import json
import os

import numpy as np
import trimesh

import decals as DC
import detail as D
import scene as S
from cameras import CAM0, CAM1
from parts import Part
from scene import GB_D, GB_H, GB_W, WALL_T, src

HERE = os.path.dirname(os.path.abspath(__file__))
EPSON_POSE = os.path.join(HERE, "out", "epson_cad_pose.json")


def mk(name, mesh, group, material, color=None):
    import materials
    return Part(name, mesh, color or materials.M[material]["color"], group, material=material)


def decal(name, group, center, x_axis, normal, w, h, image, lift=0.25):
    m, uv = D.quad(center, x_axis, normal, w, h, lift)
    return Part(name, m, "#ffffff", group, material="decal", image=image, uv=uv)


# ---- glovebox shell -------------------------------------------------------------------------------------

OPENING = (50.0, 1150.0, 55.0, 765.0)        # chamber model: window opening x0, x1, z0, z1 (long sides)
FLANGE_PITCH = 95.0
# No glove ports: the chamber model assumes 8-inch ports at x 348 / 852 mm, z 400 mm on both long sides, but
# all four spots show the room through clear window in the unblurred 2026-11-19 00:23 UTC frames.


def _side_plane(far):
    """Origin, along-x and up-the-slope unit vectors of a long side's window plane, and the sign that turns
    cross(x, up) into the outward normal."""
    lean = S.BACK_LEAN if far else S.FRONT_LEAN
    up = D.unit([0.0, -lean if far else lean, GB_H])
    return np.array([0.0, GB_D if far else 0.0, 0.0]), np.array([1.0, 0, 0]), up, (-1.0 if far else 1.0)


def shell():
    out = []
    out.append(mk("deck", D.box_at((0, 0, -WALL_T), (GB_W, GB_D, 0)), "glovebox", "stainless_deck"))
    out.append(mk("antechamber-end wall", D.box_at((-WALL_T, 0, 0), (0, GB_D, GB_H)), "glovebox", "stainless_wall"))
    out.append(mk("ceiling", D.box_at((0, S.FRONT_LEAN, GB_H), (GB_W, GB_D - S.BACK_LEAN, GB_H + WALL_T)), "glovebox",
                  "stainless_wall"))
    # far end: a clear window in a stainless frame (40 mm sides and bottom, 25 mm top)
    T_end = D.frame((GB_W, GB_D / 2, GB_H / 2), (0, 1, 0), (1, 0, 0))
    frame_poly = D.rrect(GB_D, GB_H, 2).difference(D.rrect(GB_D - 80, GB_H - 65, 18, 0, -7.5))
    out.append(mk("far-end window frame", D.extrude(frame_poly, WALL_T, T_end), "glovebox", "stainless_frame"))
    out.append(mk("far-end window", D.extrude(D.rrect(GB_D - 76, GB_H - 61, 20, 0, -7.5), 8, T_end, 1),
                  "glovebox", "window"))
    # long sides: sloped window frames with the clear pane, glove ports and the outer clamp bars
    for far in (False, True):
        o, ax, up, sgn = _side_plane(far)
        L = GB_H / (up[2])
        name = "far side" if far else "open side"
        T = np.eye(4)
        T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = ax, up, np.cross(ax, up), o
        x0, x1, z0, z1 = OPENING
        s0, s1 = z0 / up[2], z1 / up[2]
        outer = D.rrect(GB_W, L, 2, GB_W / 2, L / 2)
        hole = D.rrect(x1 - x0, s1 - s0, 25, (x0 + x1) / 2, (s0 + s1) / 2)
        out.append(mk(f"{name} window flange", D.extrude(outer.difference(hole), WALL_T, T, -WALL_T / 2), "glovebox",
                      "stainless_frame"))
        pane = D.rrect(x1 - x0 + 40, s1 - s0 + 40, 30, (x0 + x1) / 2, (s0 + s1) / 2)
        n_out = np.cross(ax, up)                              # sgn * n_out points out of the box
        out.append(mk(f"{name} window", D.extrude(pane, 8, T, sgn * (WALL_T / 2) if sgn > 0 else -WALL_T / 2 - 8),
                      "glovebox", "window"))
        # outer clamp bars with acorn nuts on the welded studs, every ~95 mm round the opening
        bar_w = 30.0
        bars = []
        nuts = []
        nout = sgn * n_out
        for (a0, b0, a1, b1) in ((x0 - bar_w, s0 - bar_w, x1 + bar_w, s0), (x0 - bar_w, s1, x1 + bar_w, s1 + bar_w),
                                 (x0 - bar_w, s0, x0, s1), (x1, s0, x1 + bar_w, s1)):
            r = D.rrect(a1 - a0, b1 - b0, 2, (a0 + a1) / 2, (b0 + b1) / 2)
            bars.append(D.extrude(r, 6, T, sgn * (WALL_T / 2 + 8) if sgn > 0 else -(WALL_T / 2 + 8) - 6))
        perim = []
        for xx in np.arange(x0 - bar_w / 2, x1 + bar_w / 2 + 1, FLANGE_PITCH):
            perim += [(xx, s0 - bar_w / 2), (xx, s1 + bar_w / 2)]
        for ss in np.arange(s0 + FLANGE_PITCH / 2, s1, FLANGE_PITCH):
            perim += [(x0 - bar_w / 2, ss), (x1 + bar_w / 2, ss)]
        for xx, ss in perim:
            p = o + ax * xx + up * ss + nout * (WALL_T / 2 + 14)
            nuts.append(D.acorn_nut(p, nout, 6.0))
        out.append(mk(f"{name} clamp bars", D.cat(bars), "glovebox", "stainless_frame"))
        out.append(mk(f"{name} acorn nuts", D.cat(nuts), "glovebox", "steel_ground"))
    src("glovebox", "chamber", "1200 x 1120 x 790 mm interior, sloped long windows (57 and 60 mm lean); window "
        "openings 1100 x 710 mm with welded studs every ~95 mm (acorn nuts outside); no glove ports where the chamber "
        "model assumes them (the frames show clear window there)")
    # antechamber inner door: 15-inch LC Technology door (dished disc, hub, clamp bar, centre screw)
    hub = np.array([0.0, 460.0, 226.0])
    T = D.frame(hub, (0, 1, 0), (1, 0, 0))
    disc = D.revolve(D.fillet_profile([(0, 0), (186, 0), (186, 6), (178, 12), (40, 16), (0, 16)], 4), T, 128)
    out.append(mk("antechamber door", disc, "glovebox", "stainless_door"))
    out.append(mk("antechamber door hub", D.revolve(D.fillet_profile([(0, 16), (30, 16), (30, 40), (22, 52), (0, 52)],
                                                                     3), T, 48), "glovebox", "alu_machined"))
    bar = D.round_box((300, 30, 10), 4, D.frame(hub + (30, 0, 0), (0, np.cos(np.radians(-40)), np.sin(np.radians(-40))),
                                              (1, 0, 0)))
    out.append(mk("antechamber door bar", bar, "glovebox", "stainless_frame"))
    out.append(mk("antechamber door screw", D.threaded_rod(hub + (40, 0, 0), hub + (150, 0, 0), 12, 1.75, 0.6, 16, 6),
                  "glovebox", "steel_ground"))
    src("antechamber door", "one-view", "hub and rim back-projected onto the wall plane from Overhead 2: radius "
        "180-190 mm, matching the 15-inch antechamber (datasheet 190 mm)")
    # QR sign on the wall: US Letter sheet with the QR panel, texture rectified from Overhead 2
    c = np.array([1.5, 827.5, 372.0])
    img = DC.from_photo(CAM1, c, (0, 1, 0), (1, 0, 0), 245, 196, 4.0, fill=(236, 236, 230))
    out.append(decal("QR sign (photo texture, Overhead 2)", "glovebox", c, (0, 1, 0), (1, 0, 0), 245, 196, img, 0.5))
    src("QR sign", "one-view", "bottom edge back-projected onto the wall from Overhead 2; the top is out of view; "
        "texture rectified from the 18:22 UTC Overhead 2 still (only its lower part is in view)")
    return out


def ducts():
    out = []
    for name, p0, p1 in (("duct, far window", (60, GB_D - 28, 0), (GB_W - 40, GB_D - 28, 0)),
                         ("duct, antechamber wall", (24, 300, 0), (24, GB_D - 50, 0))):
        out.append(mk(name, D.slotted_duct(p0, p1), "ducts", "grey_pvc"))
    src("ducts", "standard", "Panduit Type G 1 x 2 in slotted duct (32 x 54 mm, fingers on a 12.7 mm pitch, "
        "cover off as in the frames), along the edges seen in both views")
    return out


# ---- breadboards ----------------------------------------------------------------------------------------

def breadboard(name, x0, y0, sx, sy, z_top, legs=False, t=12.7):
    plate, floors = D.breadboard(x0, y0, sx, sy, z_top, t)
    out = [mk(name, plate, "breadboards", "black_anodised"), mk(name + " hole floors", floors, "breadboards",
                                                                   "hole_floor")]
    if legs:
        h = z_top - t
        posts = []
        for px in (x0 + 40, x0 + sx - 40):
            for py in (y0 + 40, y0 + sy - 40):
                posts.append(D.rounded_cylinder((px, py, 0), (px, py, h), 12.7, 1.0, 40))
        out.append(mk(name + " posts", D.cat(posts), "breadboards", "steel_post"))
    return out


def breadboards():
    out = []
    out += breadboard("main breadboard", 838, 380, 362, 700, 75.7, legs=True)
    out += breadboard("exfoliator breadboard", 230, 240, 450, 420, 160.0, legs=True)
    out += breadboard("loose breadboard", 700, 545, 225, 150, 30.0)
    src("breadboards", "one-view", "edges back-projected onto their planes; Thorlabs metric skin with M6 holes on "
        "25 mm, 12.5 mm from the edges (the hole rows measure 24.5-26.4 mm at these heights); sizes rounded to "
        "Thorlabs metric sizes where the edges are hidden")
    return out


# ---- chip tray and gantry -------------------------------------------------------------------------------

def tray(cal):
    out = []
    t = cal["tray"]
    c = np.array(t["centre"])
    yaw = np.radians(t["yaw_deg"])
    p = t["pitch_mm"]
    u = np.array([np.cos(yaw), np.sin(yaw), 0.0]) * t["mirror"]
    v = np.array([-np.sin(yaw), np.cos(yaw), 0.0])
    W, L = 6 * p + 16, 10 * p + 16
    T = D.frame(c, u, (0, 0, 1))
    pockets = [D.rrect(0.8 * p, 0.8 * p, 0.6, (i - 2.5) * p, (j - 4.5) * p) for i in range(6) for j in range(10)]
    top = D.rrect(W, L, 3).difference(D.unary_union(pockets))
    out.append(mk("chip tray", D.cat([D.extrude(top, 3.0, T, -3.0), D.extrude(D.rrect(W, L, 3), 5.0, T, -8.0)]),
                  "gantry", "tray_white", "#c9cfd0"))
    holder = D.rrect(W + 22, L + 22, 4).difference(D.rrect(W + 1, L + 1, 3))
    out.append(mk("chip tray holder", D.cat([D.extrude(holder, 6, T, -10), D.extrude(D.rrect(W + 22, L + 22, 4), 6, T,
                                                                                         -16)]),
                  "gantry", "alu_blasted", "#b9bfc0"))
    tr = json.load(open(os.path.join(HERE, "..", "vision", "out", "chip_tray.json")))
    chips = []
    for q in tr["pockets"]:
        state = q["cam0"]["state"]
        if state == "empty":
            continue
        pc = c + (q["col"] - 2.5) * p * u + (q["row"] - 4.5) * p * v + (0, 0, -1.6)
        ang = np.radians(q["cam0"]["angle_deg_canonical"] if state == "misplaced" else 0.0)
        R = np.cos(ang) * u + np.sin(ang) * v
        chips.append(D.extrude(D.crect(0.68 * p, 0.68 * p, 0.5), 1.0, D.frame(pc, R, (0, 0, 1))))
    out.append(mk("chips", D.cat(chips), "gantry", "chip"))
    # the handwritten row-0 edge, rectified from Overhead 1 (the tray is calibrated in both views)
    edge_c = c + (-4.5 - 0.87) * p * v
    img = DC.from_photo(CAM0, edge_c, u, (0, 0, 1), W - 4, 0.9 * p, 8.0)
    out.append(decal("chip tray handwriting (photo texture, Overhead 1)", "gantry", edge_c, u, (0, 0, 1), W - 4,
                     0.9 * p, img, 0.15))
    src("chip tray", "two-view", f"6 x 10 pockets fitted in both views; pitch {p:.1f} mm, centre and yaw from the "
        "joint calibration; chips placed per pocket from chip_tray.json (3 empty, 1 rotated); pockets 0.8 of the "
        "pitch and 3 mm deep (estimate); the handwritten edge is a texture rectified from Overhead 1")
    return out


def stepper_parts(name, face, axis, frame_size, length, group, xdir=None, label_on_back=False, cable_side=None):
    s = D.stepper(face, axis, frame_size, length, xdir, cable_side=cable_side)
    out = [mk(name + " end caps", s["caps"], group, "black_anodised", "#2a2b2d"),
           mk(name + " stator", s["stator"], group, "black_oxide", "#1d1d1f"),
           mk(name + " boss", s["boss"], group, "alu_machined"),
           mk(name + " shaft", s["shaft"], group, "steel_ground"),
           mk(name + " mounting holes", s["holes"], group, "hole_floor"),
           mk(name + " cable exit", s["exit"], group, "black_plastic")]
    for col, m in s["leads"]:
        out.append(mk(name + " lead", m, group, {"#c02020": "wire_red", "#2050c0": "wire_blue",
                                                 "#20a040": "wire_green"}.get(col, "wire_black")))
    if label_on_back:
        T = s["T"]
        back = np.asarray(face, float) - D.unit(axis) * length
        d = 0.7 * s["size"]
        out.append(decal(name + " label", group, back, T[:3, 0], -D.unit(axis), d, d, DC.round_label(d), 0.2))
    return out


def gantry(cal):
    out = []
    t = cal["tray"]
    c = np.array(t["centre"])
    for nm, p0, p1, z, at in (("Y axis", (600, 262), (600, 492), 172.0, 0.55), ("X axis", (285, 505), (680, 520), 192.0,
                                                                                0.7),
                              ("top axis", (180, 290), (180, 440), 205.0, 0.5)):
        for pn, m, mat in D.axis_module(nm, p0, p1, z, carriage_at=at):
            out.append(mk(pn, m, "gantry", mat))
    out += stepper_parts("Y axis motor", (600, 520, 194), (0, -1, 0), 23, 76, "gantry", label_on_back=True)
    out += stepper_parts("X axis motor", (262, 504, 214), (1, 0, 0), 23, 76, "gantry", label_on_back=True)
    out.append(mk("Y axis coupling", D.rounded_cylinder((600, 520, 194), (600, 492 + 18, 194), 12.5, 1.0), "gantry",
                  "alu_machined"))
    out.append(mk("X axis coupling", D.rounded_cylinder((262, 504, 214), (285 - 18, 505, 214), 12.5, 1.0), "gantry",
                  "alu_machined"))
    out.append(mk("tray carriage", D.round_box((110, 90, 40), 3, D.frame(c - (0, 0, 40), (np.cos(np.radians(t["yaw_deg"])),
                                                                                         np.sin(np.radians(t["yaw_deg"])),
                                                                                         0), (0, 0, 1))),
                  "gantry", "black_anodised"))
    # yellow printed carriage: PLA, 3 mm fillets, a slot for the belt side and four heat-set inserts
    out.append(mk("printed carriage", D.round_box((135, 75, 65), 4, D.frame((322.5, 462.5, 287.5), (1, 0, 0), (0, 0, 1))),
                  "gantry", "yellow_pla"))
    ins = [D.cylinder((x, y, 320), (x, y, 320.4), 2.6, 16) for x in (265, 380) for y in (435, 490)]
    out.append(mk("printed carriage inserts", D.cat(ins), "gantry", "copper"))
    out += stepper_parts("carriage motor 1", (330, 455, 320), (0, 0, -1), 17, 48, "gantry")
    out += stepper_parts("carriage motor 2", (391, 515, 320), (0, 0, -1), 17, 48, "gantry")
    for nm, pts in (("drag chain", [(250, 300, 260), (220, 360, 330), (240, 430, 340), (300, 470, 330)]),
                    ("drag chain 2", [(420, 560, 210), (480, 610, 260), (560, 610, 250), (620, 560, 215)])):
        plates, bars = D.drag_chain(pts)
        out.append(mk(nm + " links", plates, "gantry", "black_plastic"))
        out.append(mk(nm + " crossbars", bars, "gantry", "black_plastic", "#2a2826"))
    src("gantry", "one-view", "posts (147 mm), plate edge, both screw axes and the Y motor back-projected from "
        "Overhead 2 at their heights; NEMA 23 (57.2 mm) and NEMA 17 (42.3 mm) to the NEMA flange drawings; SFU1605 "
        "screws (16 mm, 5 mm lead) on BK12/BF12 supports, HGR15 rails and blocks (catalogue sizes); chain links "
        "26 x 18 mm on a 17 mm pitch (igus-style, estimate)")
    return out


# ---- exfoliator -----------------------------------------------------------------------------------------

def reel(name, ctr, tape_mat):
    ctr = np.asarray(ctr, float)
    T = D.frame(ctr - (17, 0, 0), (0, 1, 0), (1, 0, 0))
    out = []
    flange = D.fillet_profile([(12, 0), (48, 0), (48, 3.5), (12, 3.5)], 1.2)
    for dz in (0.0, 30.5):
        out.append(mk(name + " flange", D.revolve(flange + np.array([0, dz]), T, 96), "exfoliator", "red_plastic"))
    out.append(mk(name + " tape", D.revolve(D.fillet_profile([(22, 3.5), (42, 3.5), (42, 30.5), (22, 30.5)], 0.8), T, 96),
                  "exfoliator", tape_mat))
    core = D.gear(9.5, 11.0, 12).buffer(0)
    hub = D.circ(22, n=64).difference(core)
    out.append(mk(name + " hub", D.extrude(hub, 34, T), "exfoliator", "red_plastic"))
    return out


def exfoliator():
    out = []
    out += reel("supply reel (blue tape)", (669, 309, 399), "tape_blue")
    out += reel("take-up reel (white tape)", (670, 142, 401), "tape_white")
    # aluminium housing between the reels: machined block, 3 mm edge radius, M4 screws on top
    out.append(mk("exfoliator housing", D.round_box((90, 200, 170), 3, D.frame((745, 170, 245), (1, 0, 0), (0, 0, 1))),
                  "exfoliator", "alu_machined"))
    heads = []
    for x in (712, 778):
        for y in (85, 255):
            h, hx = D.cap_screw((x, y, 330), (0, 0, 1), 4.0)
            heads.append(h)
    out.append(mk("housing screws", D.cat(heads), "exfoliator", "steel_ground"))
    out += stepper_parts("press stepper", (745, 230, 330), (0, 0, -1), 23, 80, "exfoliator", label_on_back=True)
    # the pin-fin unit with the QR label in front of the supply reel is a Teknic ClearPath NEMA 23
    # integrated servo (pin-fin rear cap, QR label and status LED, as in the video and Teknic's CAD): Teknic's
    # own STEP, rear cap towards Overhead 1, shaft along +x into the housing, connector side up
    body_c = np.array([640.0, 300.0, 290.0])
    try:
        import clearpath_cad
        cp = clearpath_cad.mesh().copy()
        T = np.eye(4)
        T[:3, :3] = [[0, 0, -1], [0, -1, 0], [-1, 0, 0]]     # Teknic z (rear) -> -x, Teknic -x (connectors) -> +z
        T[:3, 3] = (626.8, 300.0, 279.0)
        cp.apply_transform(T)
        out.append(mk("ClearPath CPM NEMA 23 servo (Teknic CAD)", cp, "exfoliator", "alu_blasted"))
        lbl_x = float(cp.bounds[0][0]) - 0.3
        src("ClearPath", "datasheet", "Teknic's STEP for the CPM-231x (keyed shaft), from teknic.com without a login; "
            "identified by its pin-fin rear cap, QR label and status LED; placed where the hand-built unit was "
            "(back-projected from Overhead 1); the stack length (231x) is assumed")
    except Exception as e:          # no network or no gmsh: the hand-built block
        print("ClearPath CAD unavailable, using the block:", e)
        out.append(mk("roller drive body", D.round_box((60, 66, 80), 4, D.frame(body_c, (1, 0, 0), (0, 0, 1))),
                      "exfoliator", "alu_blasted"))
        pins = [D.rounded_cylinder(body_c + (-30, y, z), body_c + (-42, y, z), 2.0, 0.6, 12)
                for y in np.arange(-27, 28, 6.0) for z in np.arange(-36, 10, 6.0)]
        out.append(mk("roller drive pin fins", D.cat(pins), "exfoliator", "alu_blasted"))
        lbl_x = body_c[0] - 30.6
    out.append(mk("ClearPath connector", D.round_box((26, 20, 14), 2, D.frame(body_c + (10, 0, 48), (1, 0, 0), (0, 0, 1))),
                  "exfoliator", "black_plastic"))
    img = DC.from_photo(CAM0, np.r_[lbl_x, body_c[1:] + (0, 26)], (0, -1, 0), (-1, 0, 0), 60, 26, 6.0)
    out.append(decal("ClearPath label (photo texture, Overhead 1)", "exfoliator", np.r_[lbl_x, body_c[1:] + (0, 26)],
                     (0, -1, 0), (-1, 0, 0), 60, 26, img, 0.3))
    for pn, m, mat in D.axis_module("exfoliator stage", (690, 482), (767, 253), 178.0, carriage_at=0.45):
        out.append(mk(pn, m, "exfoliator", mat))
    # 'EXFOLIATOR' label on the stage base's open-side face (seen from Overhead 1)
    a = D.unit(np.r_[np.subtract((767, 253), (690, 482)), 0])
    w = np.cross((0, 0, 1), a)
    lc = np.r_[(690 + 767) / 2, (482 + 253) / 2, 178.0 - 12] - w * 45.3 + a * 30
    nrm = -w if (-w)[0] < 0 else w
    out.append(decal("exfoliator stage label", "exfoliator", lc, np.cross((0, 0, 1.0), nrm), nrm, 60, 12,
                     DC.typeset("EXFOLIATOR", 60, 12, (20, 20, 20), (240, 240, 236), pad=0.1), 0.2))
    src("exfoliator", "two-view", "reel centres triangulated; housing, motors and stage back-projected from "
        "Overhead 1; reel diameter 85-95 mm from the image size at the triangulated distance; reel hubs with a "
        "12-spline bore and the pin-fin drive from Overhead 2 and Overhead 1 close-ups (estimate)")
    return out


# ---- microscope, stages, Thorlabs box -------------------------------------------------------------------

def microscope():
    out = []
    ox, oy = 1118.0, 379.0
    z_tip = 250.0
    z_mount = z_tip + 75
    T0 = lambda z: D.frame((ox, oy, z), (1, 0, 0), (0, 0, 1))  # noqa: E731
    # ASI XY stage: two stacked black carriages, the top one open for the insert
    lower = D.rrect(229, 216, 3, ox - 45.5, oy)
    out.append(mk("ASI stage, lower (X) carriage", D.extrude(lower, 22, None, 130), "microscope", "black_anodised"))
    upper = D.rrect(200, 216, 3, ox - 45.5, oy).difference(D.rrect(118, 84, 4, ox - 25, oy))
    out.append(mk("ASI stage, upper (Y) carriage", D.extrude(upper, 23, None, 152), "microscope", "black_anodised"))
    out.append(mk("ASI stage riser", D.round_box((170, 180, 54.3), 2, D.frame((ox - 45, oy, 102.85), (1, 0, 0), (0, 0, 1))),
                  "microscope", "black_anodised"))
    out.append(mk("sample insert (acrylic)", D.extrude(D.rrect(116, 82, 4, ox - 25, oy), 6, None, 169), "microscope",
                  "window"))
    sc = []
    for dx in (-80, 30):
        for dy in (-36, 36):
            h, hx = D.cap_screw((ox - 25 + dx * 0.95 + 22, oy + dy, 175), (0, 0, 1), 3.0)
            sc.append(h)
    out.append(mk("insert screws", D.cat(sc), "microscope", "steel_ground"))
    # 20x objective: revolved barrel, green 20x band, knurled grip
    obj = D.fillet_profile([(0, 0), (6.5, 0), (9, 6), (12.5, 14), (12.5, 30), (13.2, 30), (13.2, 41), (10, 41), (10, 45),
                            (0, 45)], 0.8)
    out.append(mk("20x objective", D.revolve(obj, T0(z_tip), 64), "microscope", "black_anodised", "#202224"))
    out.append(mk("objective 20x band", D.revolve([(12.55, 30), (12.9, 30), (12.9, 33.5), (12.55, 33.5)], T0(z_tip), 64),
                  "microscope", "green_anod"))
    out.append(mk("objective knurl", D.extrude(D.gear(13.2, 13.9, 60, per=4), 9, T0(z_tip + 31.5)), "microscope",
                  "black_anodised", "#1b1c1e"))
    out.append(mk("objective front lens", D.revolve([(0, -0.2), (3.2, -0.2), (3.2, 0.3), (0, 0.6)], T0(z_tip), 32),
                  "microscope", "lens_glass"))
    out.append(mk("nosepiece", D.revolve(D.fillet_profile([(0, 45), (42, 45), (42, 75), (0, 75)], 3), T0(z_tip), 96),
                  "microscope", "olympus_paint", "#d9ddd9"))
    # BX3-URA reflected-light illuminator: filter drum ahead of the axis, body behind, lamp port
    drum = D.fillet_profile([(0, 0), (90, 0), (90, 84), (0, 84)], 8)
    out.append(mk("BX3-URA illuminator drum", D.revolve(drum, D.frame((ox, oy + 51.5, z_mount), (1, 0, 0), (0, 0, 1)), 128),
                  "microscope", "olympus_paint"))
    ticks = []
    for k in range(48):
        a = 2 * np.pi * k / 48
        p = np.array([ox + 89.6 * np.cos(a), oy + 51.5 + 89.6 * np.sin(a), z_mount + 62])
        ticks.append(trimesh.creation.box(extents=(0.9, 1.2, 7 if k % 4 == 0 else 4),
                                          transform=D.frame(p, (-np.sin(a), np.cos(a), 0), (0, 0, 1))))
    out.append(mk("illuminator drum scale", D.cat(ticks), "microscope", "black_plastic", "#5a5e60"))
    out.append(mk("BX3-URA illuminator body", D.round_box((90, 241, 74), 10, D.frame((ox, oy - 100.5, z_mount + 47),
                                                                                    (1, 0, 0), (0, 0, 1))),
                  "microscope", "olympus_paint"))
    out.append(mk("BX3-URA lamp port", D.rounded_cylinder((ox, oy - 221, z_mount + 47), (ox, oy - 261, z_mount + 47), 22,
                                                          2), "microscope", "olympus_paint", "#c9ccc9"))
    zt = z_mount + 84
    out.append(mk("U-DP dual port", D.round_box((88, 151, 57), 6, D.frame((ox, oy - 24.5, zt + 28.5), (1, 0, 0), (0, 0, 1))),
                  "microscope", "olympus_paint"))
    out.append(mk("U-TLU tube", D.rounded_cylinder((ox, oy, zt + 57), (ox, oy, zt + 114.6), 30, 1.5), "microscope",
                  "black_anodised", "#1b1b1c"))
    out.append(mk("microscope camera", D.rounded_cylinder((ox, oy, zt + 114.6), (ox, oy, zt + 200), 34, 3), "microscope",
                  "black_anodised", "#151515"))
    # the custom plate the modules hang from: aluminium, with a large relief cut-out
    plate = D.rrect(240, z_mount + 40 - 75.7, 6, 0, 0).difference(D.rrect(150, 120, 40, 0, -30))
    Tp = np.eye(4)
    Tp[:3, 0], Tp[:3, 1], Tp[:3, 2] = (0, 1, 0), (0, 0, 1), (1, 0, 0)
    Tp[:3, 3] = (ox + 60, oy, (75.7 + z_mount + 40) / 2)
    out.append(mk("microscope mounting plate", D.extrude(plate, 15, Tp), "microscope", "alu_blasted", "#c9ccc9"))
    for p in breadboard("microscope breadboard", 965, 150, 235, 195, 380.0):
        p.group = "microscope"
        out.append(p)
    out.append(mk("light source", D.rounded_cylinder((1060, 150, 400), (1060, 90, 400), 38, 3), "microscope",
                  "black_anodised", "#151515"))
    out.append(mk("light source fins", D.cat([D.revolve([(38, z), (41, z), (41, z + 2), (38, z + 2)],
                                                        D.frame((1060, 150, 400), (1, 0, 0), (0, -1, 0)), 64)
                                             for z in np.arange(8, 50, 5.0)]), "microscope", "black_anodised", "#151515"))
    # Thorlabs box: black anodised, THORLABS on the face Overhead 1 sees
    out.append(mk("Thorlabs platform", D.round_box((175, 144, 124.3), 2.5, D.frame((902.5, 443, 137.85), (1, 0, 0), (0, 0, 1))),
                  "microscope", "black_anodised", "#202124"))
    out.append(decal("THORLABS logo", "microscope", (814.8, 443, 150), (0, -1, 0), (-1, 0, 0), 90, 13,
                     DC.typeset("THORLABS", 90, 13, (235, 235, 235), None, pad=0.04, spacing=0.02), 0.2))
    # two black docking fixtures: slotted side plates and a top plate with cap screws
    for x0, x1, y0, y1 in ((885, 975, 645, 775), (1000, 1093, 625, 760)):
        for yy in (y0, y1 - 12):
            side = D.rrect(x1 - x0, 270 - 75.7, 3, (x0 + x1) / 2, (75.7 + 270) / 2)
            slots = D.unary_union([D.rrect(10, 120, 5, (x0 + x1) / 2 + dx, (75.7 + 270) / 2) for dx in (-20, 20)])
            Ts = np.eye(4)
            Ts[:3, 0], Ts[:3, 1], Ts[:3, 2] = (1, 0, 0), (0, 0, 1), (0, -1, 0)
            Ts[:3, 3] = (0, yy + 12, 0)
            out.append(mk("docking fixture side", D.extrude(side.difference(slots), 12, Ts), "microscope",
                          "black_anodised", "#1e1c1a"))
        out.append(mk("docking fixture top", D.round_box((x1 - x0, y1 - y0, 12), 1.5,
                                                         D.frame(((x0 + x1) / 2, (y0 + y1) / 2, 276), (1, 0, 0), (0, 0, 1))),
                      "microscope", "black_anodised", "#1e1c1a"))
        hs = []
        for dx in (-0.35, 0.35):
            for dy in (-0.35, 0.35):
                h, hx = D.cap_screw(((x0 + x1) / 2 + dx * (x1 - x0), (y0 + y1) / 2 + dy * (y1 - y0), 282), (0, 0, 1), 6.0)
                hs.append(h)
        out.append(mk("docking fixture screws", D.cat(hs), "microscope", "steel_ground"))
    src("microscope", "datasheet", "Olympus BX3-URA, U-DP and U-TLU sizes (Evident components guide); ASI "
        "OE-1250 stage size; positions from the objective on the Overhead 1 ray at z 250, elevated breadboard "
        "back-projected at z 380, Thorlabs platform front edge at z 180-220; fillets, drum scale, objective "
        "profile and the THORLABS mark from the Overhead 1 frame (estimate)")
    return out


def deck_items():
    out = []
    T = D.frame((255, 865, 25), (np.cos(np.radians(30)), np.sin(np.radians(30)), 0), (0, 0, 1))
    out.append(mk("tape measure case", D.round_box((86, 84, 46), 14, T), "deck", "yellow_abs"))
    out.append(mk("tape measure bumper", D.round_box((90, 52, 50), 10, T @ trimesh.transformations.translation_matrix(
        (0, -20, 0))), "deck", "black_rubber"))
    out.append(mk("tape measure blade tip", D.round_box((6, 26, 10), 1, T @ trimesh.transformations.translation_matrix(
        (45, -36, -15))), "deck", "steel_ground", "#d8c040"))
    out.append(mk("tape measure lock", D.round_box((22, 10, 8), 3, T @ trimesh.transformations.translation_matrix(
        (25, -30, 24))), "deck", "black_rubber"))
    out.append(mk("tape measure belt clip", D.round_box((60, 3, 34), 1.2, T @ trimesh.transformations.translation_matrix(
        (0, 44, 2))), "deck", "steel_ground", "#303030"))
    src("tape measure", "one-view", "back-projected onto the deck from Overhead 2; case about 90 x 90 x 50 with a "
        "black bumper (FatMax-style, estimate)")
    return out


# ---- Epson T6-B602S (Epson's own CAD) ---------------------------------------------------------------------

def epson_vendor(r):
    import epson_cad as E
    if os.path.exists(EPSON_POSE):
        p = json.load(open(EPSON_POSE))
        pose = dict(j1=tuple(p["base"]["j1"]), z0=p["base"]["z0"], yaw=p["base"]["yaw"])
        j1, j2 = p["parked"]["j1"], p["parked"]["j2"]
    else:
        pose, j1, j2 = E.from_scene_robot(r)
    meshes = E.posed(pose, j1, j2, ceiling=GB_H, with_unit=False, hi=True)
    out = []
    mats = dict(base="epson_paint", arm1="epson_paint", arm2="epson_paint", shaft="steel_ground", cable="black_rubber")
    for k, m in meshes.items():
        out.append(mk(f"Epson {k} (Epson CAD)", m, "epson", mats[k]))
    B = E.base_transform(pose)
    Lt = E.link_transforms(j1, j2)
    # the black unit Overhead 2 sees on arm 2 (make unknown): rounded box with a cable gland
    U = B @ Lt["unit"]
    out.append(mk("black unit on arm 2", D.round_box((120, 100, 45), 6, U @ trimesh.transformations.translation_matrix(
        (E.L1 + 100, 0, 465.3 + 22.5))), "epson", "black_plastic", "#151515"))
    out += end_effector(B @ Lt["shaft"], B @ Lt["arm2"])
    # riser block under the base flange: machined aluminium, flange footprint plus 5 mm
    h = pose["z0"] - 75.7
    Rb = B @ trimesh.transformations.translation_matrix((-71.0, 0, -h / 2))
    out.append(mk("Epson riser block", D.round_box((288, 179, h), 2.5, Rb), "epson", "alu_machined"))
    # printed marks: Epson's CAD models the EPSON wordmark in relief on both sides of arm 2, so those
    # faces get the print colour; a badge and labels on the base are decals
    lamp_T = B @ trimesh.transformations.translation_matrix((45.0, -52.0, 484.0))
    out.append(mk("Epson status lamp base (photo)", D.revolve([(0, 0), (10.5, 0), (10.5, 6), (0, 6)], lamp_T, 32),
                  "epson", "black_plastic"))
    out.append(mk("Epson status lamp lens (photo)", D.revolve(D.fillet_profile([(0, 6), (8, 6), (8, 19), (0, 19)], 3.0),
                                                              lamp_T, 32), "epson", "lamp_orange"))
    lg = E.logo()
    if lg is not None:
        out.append(mk("EPSON wordmarks, arm 2 (Epson CAD relief)", lg.apply_transform(B @ Lt["arm2"]), "epson",
                      "epson_print"))
    base = meshes["base"]
    for nm, o_loc, d_loc, w, hgt, img in (
            ("EPSON badge, base", (20.0, -200.0, 45.0), (0, 1, 0), 34, 9,
             DC.typeset("EPSON", 34, 9, (25, 40, 110), (226, 230, 228), pad=0.12)),
            ("warning label, base", (0.0, 200.0, 85.0), (0, -1, 0), 26, 23, DC.warning_triangle(26)),
            ("rating label, base", (-120.0, -200.0, 120.0), (0, 1, 0), 40, 60,
             DC.label([("EPSON", 0.1, True), ("SCARA ROBOT", 0.06, False), ("MODEL: T6-B602S", 0.06, False),
                       ("MANIPULATOR WITH CONTROLLER", 0.05, False)], 40, 60, border=(120, 120, 120)))):
        o = (B @ np.r_[o_loc, 1])[:3]
        dvec = (B @ np.r_[d_loc, 0])[:3]
        loc, idx, _ = base.ray.intersects_location([o], [dvec], multiple_hits=False)
        if len(loc):
            n = base.face_normals[idx[0]]
            n = -n if n @ dvec > 0 else n
            xd = np.cross((0, 0, 1), n)
            out.append(decal(nm, "epson", loc[0], xd, n, w, hgt, img, 0.3))
    src("epson", "datasheet", "Epson's own T6-B602S CAD (STEP from Epson's support page, meshed per link; fetched "
        "at build time, not redistributed as STEP), posed by fit_epson_cad.py: Overhead 1 silhouette with J2/J3 "
        "held near the two-view outline fit; the EPSON wordmarks are Epson's own relief, coloured; badge and labels "
        "as decals (typeset, positions estimated from Overhead 1); the black unit on arm 2 is placed from Overhead 2, make unknown")
    return out, pose, (j1, j2)


def end_effector(T_shaft, T_arm2):
    """The tool on the J3 shaft as the AURORA video's Sample Transfer shot shows it (frames 600-662,
    2026-07): a dark-blue cone collar where the shaft leaves arm 2, a stainless body clamped on the
    shaft end with a loop of clear-green 4 mm tubing round its top, and a black pneumatic parallel
    gripper whose finger plates hold the chip tray's fork. Sizes are scaled from the shaft (ø20 mm) in
    those frames (estimate); the November stills don't show the tool."""
    import epson_cad as E
    x3 = E.L1 + E.L2
    z_arm = 227.5                    # underside of arm 2 at the shaft (Epson CAD)
    z_end = 173.5                    # shaft's lower end with J3 fully up (Epson CAD)
    out = []
    Ta = T_arm2 @ trimesh.transformations.translation_matrix((x3, 0, 0))
    cone = D.revolve([(9.5, z_arm - 24), (17.0, z_arm - 24), (29.0, z_arm - 2), (29.0, z_arm), (9.5, z_arm)], Ta, 64)
    out.append(mk("end effector: shaft collar (video)", cone, "epson", "blue_anod"))
    Ts = T_shaft @ trimesh.transformations.translation_matrix((x3, 0, 0))
    body = D.revolve(D.fillet_profile([(0, z_end - 58), (17.5, z_end - 58), (17.5, z_end + 4), (0, z_end + 4)], 1.5),
                     Ts, 64)
    out.append(mk("end effector: body (video)", body, "epson", "alu_machined"))
    ring_pts = [(22.0 * np.cos(a), 22.0 * np.sin(a), z_end - 8 + 3 * np.sin(2 * a)) for a in np.linspace(0, 2 * np.pi, 40)]
    loop = D.sweep_circle(trimesh.transform_points(np.array(ring_pts), Ts), 2.0, 10)
    out.append(mk("end effector: tubing loop (video)", loop, "epson", "tube_green"))
    lead = D.spline(trimesh.transform_points(np.array([(22, 0, z_end - 8), (40, 10, z_end + 10), (60, 25, z_end + 60),
                                                       (40, 40, z_end + 130)]), Ts), 8)
    out.append(mk("end effector: tubing lead (video)", D.sweep_circle(lead, 2.0, 10), "epson", "tube_green"))
    grip = D.round_box((52, 34, 30), 2.0, Ts @ trimesh.transformations.translation_matrix((0, 0, z_end - 58 - 15)))
    out.append(mk("end effector: parallel gripper (video)", grip, "epson", "black_anodised"))
    fingers = [D.round_box((10, 30, 34), 1.0, Ts @ trimesh.transformations.translation_matrix((sx * 20, 0, z_end - 58 - 30 - 17)))
               for sx in (-1, 1)]
    out.append(mk("end effector: finger plates (video)", D.cat(fingers), "epson", "black_anodised"))
    # three clear-teal tubes from arm 2's duct fitting into the top of the hollow shaft (Borys lab photo
    # of this T6), kept under the glovebox ceiling
    tubes = []
    for dy in (-6.0, 0.0, 6.0):
        P = D.spline([(352, dy, 478), (420, dy * 1.4, 560), (520, dy * 1.2, 592), (594, dy * 0.6, 590),
                      (600, dy * 0.4, 584)], 8)
        tubes.append(D.sweep_circle(trimesh.transform_points(P, T_arm2), 2.0, 10))
    out.append(mk("Epson tubing into the shaft top (photo)", D.cat(tubes), "epson", "tube_green"))
    src("end effector", "estimate", "from the AURORA video's Sample Transfer shot (2026-07) and a Borys lab photo "
        "of this T6: collar, body, tubing loop and parallel gripper, scaled from the ø20 mm J3 shaft; tubing into "
        "the hollow shaft's top; not visible in the November stills")
    return out


def amcrest_cameras(cal):
    """The two Amcrest IP5M-T1179EW turret cameras: the ball (85 mm) with its lens and IR window, at each
    calibrated centre and view direction. Their mounts are out of both views and not modelled."""
    out = []
    for k in ("cam0", "cam1"):
        c = cal["cameras"][k]
        R = np.array(c["R"])
        centre = -R.T @ np.array(c["t"])
        f, right = R[2], R[0]
        T = D.frame(centre - f * 30, right, f)
        ball = D.revolve([(0, -30)] + [(42.5 * np.cos(a), 42.5 * np.sin(a)) for a in np.linspace(-np.pi / 2 + 0.3,
                                                                                                    np.pi / 2 - 0.5, 14)]
                         + [(0, 42.5 * np.sin(np.pi / 2 - 0.5))], T, 64)
        out.append(mk(f"Amcrest camera {k} housing", ball, "cameras", "epson_paint", "#e6e8e6"))
        out.append(mk(f"Amcrest camera {k} face", D.revolve([(0, 20.5), (36, 20.5), (36, 22), (0, 22)], T, 64),
                      "cameras", "black_plastic", "#101010"))
        out.append(mk(f"Amcrest camera {k} lens", D.revolve([(0, 27), (9, 26.5), (11, 22), (0, 22)], T, 48), "cameras",
                      "lens_glass"))
    src("cameras", "two-view", "Amcrest IP5M-T1179EW ball (85 mm, datasheet) at each camera's calibrated centre, "
        "facing its view direction; the turret base and mount are out of view and not modelled")
    return out


def cables():
    """Cables and tubing traced in the two stills by colour and lifted onto the model (cables.py writes
    out/cables.json): blue signal and motor cables, green and clear-green tubing, red wires."""
    f = os.path.join(HERE, "out", "cables.json")
    if not os.path.exists(f):
        return []
    out = []
    by = {}
    for c in json.load(open(f))["cables"]:
        P = np.array(c["points"], float)
        if len(P) < 2:
            continue
        P = D.spline(P, 4) if len(P) >= 3 else P
        by.setdefault(c["finish"], []).append(D.sweep_circle(P, c["radius_mm"], 10))
    for fin, ms in by.items():
        out.append(mk(f"cables, {fin.replace('_', ' ')} (traced)", D.cat(ms), "cables", fin))
    src("cables", "one-view", "traced by colour in the published stills and lifted onto the model's depth "
        "(cables.py): right in the view they were traced from, lying on the surfaces under them from others")
    return out


def build(cal, robot=None, vendor_epson=True, with_cables=True):
    r = dict(S.ROBOT, **(robot or {}))
    parts = []
    if with_cables:
        parts += cables()
    parts += shell()
    parts += ducts()
    parts += breadboards()
    parts += tray(cal)
    parts += gantry(cal)
    parts += exfoliator()
    parts += microscope()
    parts += deck_items()
    parts += amcrest_cameras(cal)
    if vendor_epson:
        try:
            ep, _, _ = epson_vendor(r)
            parts += ep
            return parts
        except Exception as e:     # no network / no gmsh: fall back to the hand-built outline
            print("Epson CAD unavailable, using the outline:", e)
    b = np.array([np.cos(np.radians(r["back_yaw_deg"])), np.sin(np.radians(r["back_yaw_deg"]))])
    ep, _ = S.epson(np.array(r["j1"]), r["base_underside_z"], b, r["th1_deg"], r["th2_deg"])
    ep.append(S.riser_block(np.array(r["j1"]), b, r["base_underside_z"], r["riser_h"]))
    parts += ep
    return parts
