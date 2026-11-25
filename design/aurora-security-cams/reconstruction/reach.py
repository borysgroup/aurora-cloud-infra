"""Where the Epson can pick and place: a reach map over the deck, the stations it serves, and where the
gantry can hand it the chip tray.

    python reach.py      # -> out/epson_reach.json, out/epson_reach.png

Uses the same robot (Epson's CAD on the fitted base, out/epson_cad_pose.json), joint limits and 10 mm
voxel collision test as motion.py, and adds the vertical axis:

- **Height map:** a ray cast straight down every 5 mm over the deck gives the top of whatever is there
  (static parts only; cables included, the robot left out).
- **Reach map:** for every 5 mm cell, inverse kinematics gives the two arm configurations (elbow to
  either side) that put the J3 axis over it. A configuration counts when it is within Epson's limits,
  its arm clears the box and every other part with the shaft up, and it lies in the free region of joint
  space connected to the parked pose, so the arm can get there without a collision. The cell then shows
  the lowest height the gripper's fingertips reach coming straight down: the 200 mm stroke, or the top
  of the tallest part under the gripper's footprint (a 35 mm radius round the shaft), whichever is higher.
- **Stations:** the places the robot serves in the AURORA workflow (the chip tray on the gantry, the
  ASI stage's sample insert and the two docking fixtures) are checked one by one: reachable or not, with
  which elbow, and how much of the stroke it takes to bring the fingertips down to the station's top.
- **Gantry hand-off:** the chip tray rides on the gantry's X and Y axes, so the robot need not reach it
  where the stills show it. The tray's travel follows from the axes' lengths (the carriage keeps 70 mm
  from each end); the part of it the J3 axis can reach with the arm clear is the hand-off zone.
- **Joint space:** the free (J1, J2) poses on a 1 degree grid, shaded by clearance, with the parked pose,
  the two poses read off the AURORA video and the stations' inverse-kinematics solutions.

All of it rests on the model, so it carries the model's errors (parts placed from one view can be 20 to
50 mm off) and its gaps (black cables are missing). The parked pose's conflict with the far end of the
box (README) is left as it is.
"""
import json
import os

import numpy as np
import trimesh

import epson_cad as E
import motion as MO
import scene_detail as SD
from cameras import CAL
from scene import GB_D, GB_H, GB_W

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
CELL = 5.0
STROKE = 200.0
FOOT_R = 35.0
CARRIAGE_END = 70.0


def load_pose():
    p = json.load(open(os.path.join(OUT, "epson_cad_pose.json")))
    return dict(j1=tuple(p["base"]["j1"]), z0=p["base"]["z0"], yaw=p["base"]["yaw"]), p


def height_map(parts):
    """Top surface height (mm) on a CELL grid over the deck, by casting rays straight down."""
    ms = [p.mesh for p in parts if getattr(p, "material", "") not in ("window", "lens_glass")
          and p.name not in ("ceiling",) and p.group not in ("epson", "cameras")]
    m = trimesh.util.concatenate(ms)
    try:
        from trimesh.ray.ray_pyembree import RayMeshIntersector
        rt = RayMeshIntersector(m)
    except Exception:
        rt = m.ray
    xs = np.arange(CELL / 2, GB_W, CELL)
    ys = np.arange(CELL / 2, GB_D, CELL)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    O = np.c_[X.ravel(), Y.ravel(), np.full(X.size, GB_H - 12.0)]
    D = np.tile([0, 0, -1.0], (len(O), 1))
    loc, ri, _ = rt.intersects_location(O, D, multiple_hits=False)
    Hm = np.zeros(len(O))
    Hm[ri] = loc[:, 2]
    return xs, ys, Hm.reshape(X.shape)


def footprint_max(Hm, r_mm):
    from scipy.ndimage import maximum_filter
    r = int(np.ceil(r_mm / CELL))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return maximum_filter(Hm, footprint=(xx ** 2 + yy ** 2) <= r * r, mode="nearest")


def ik(pose, x, y):
    """Joint angles (j1, j2) putting the J3 axis at (x, y), both elbows: arrays of shape (2, n); NaN where out
    of reach. Inverse of epson_cad.link_transforms on the fitted base."""
    yaw = np.radians(pose["yaw"])
    dx, dy = np.asarray(x) - pose["j1"][0], np.asarray(y) - pose["j1"][1]
    lx = np.cos(yaw) * dx + np.sin(yaw) * dy           # into the base's local frame
    ly = -np.sin(yaw) * dx + np.cos(yaw) * dy
    r2 = lx ** 2 + ly ** 2
    c2 = (r2 - E.L1 ** 2 - E.L2 ** 2) / (2 * E.L1 * E.L2)
    ok = np.abs(c2) <= 1
    out = np.full((2, 2, np.size(lx)), np.nan)
    for k, s in enumerate((1.0, -1.0)):
        t2 = s * np.arccos(np.clip(c2, -1, 1))
        t1 = np.arctan2(ly, lx) - np.arctan2(E.L2 * np.sin(t2), E.L1 + E.L2 * np.cos(t2))
        j1 = (np.degrees(t1) + 180) % 360 - 180
        j2 = np.degrees(t2)
        out[k, 0] = np.where(ok, j1, np.nan)
        out[k, 1] = np.where(ok, j2, np.nan)
    return out


def pose_points(samples, B, j1, j2):
    T = E.link_transforms(j1, j2)
    return np.vstack([trimesh.transform_points(samples["arm1"], B @ T["arm1"]),
                      trimesh.transform_points(samples["arm2"], B @ T["arm2"]),
                      trimesh.transform_points(samples["unit"], B @ T["unit"]),
                      trimesh.transform_points(samples["shaft"], B @ T["shaft"]),
                      trimesh.transform_points(samples["ee_arm2"], B @ T["arm2"]),
                      trimesh.transform_points(samples["ee_shaft"], B @ T["shaft"])])


def collides(P, occ):
    if MO.outside_box(P).any():
        return True
    ijk = np.clip(np.floor(P / MO.VOX).astype(int) + 1, 0, np.array(occ.shape) - 1)
    return bool(occ[tuple(ijk.T)].any())


def clearance_field(occ):
    from scipy.ndimage import distance_transform_edt
    return distance_transform_edt(~occ) * MO.VOX


def cspace(pose, occ, samples, step=1.0):
    """Free/blocked on a `step` degree grid, and each free pose's clearance (mm) to the nearest part."""
    B = E.base_transform(pose)
    j1s = np.arange(-E.LIMITS["j1"], E.LIMITS["j1"] + 1e-6, step)
    j2s = np.arange(-E.LIMITS["j2"], E.LIMITS["j2"] + 1e-6, step)
    clr = clearance_field(occ)
    free = np.zeros((len(j1s), len(j2s)), bool)
    gap = np.zeros((len(j1s), len(j2s)))
    for a, j1 in enumerate(j1s):
        for b, j2 in enumerate(j2s):
            P = pose_points(samples, B, j1, j2)
            if MO.outside_box(P).any():
                continue
            ijk = np.clip(np.floor(P / MO.VOX).astype(int) + 1, 0, np.array(occ.shape) - 1)
            if occ[tuple(ijk.T)].any():
                continue
            free[a, b] = True
            gap[a, b] = float(clr[tuple(ijk.T)].min())
    return j1s, j2s, free, gap


def thin_samples(n=700):
    S = MO.link_samples(n)
    return {k: (v[:: max(1, len(v) // n)] if len(v) > n else v) for k, v in S.items()}


def tip_height_up(pose):
    """Lowest point of the gripper's fingertips with the shaft fully up (mm above the deck)."""
    B = E.base_transform(pose)
    T = E.link_transforms(0.0, 0.0)
    ee = SD.end_effector(B @ T["shaft"], B @ T["arm2"])
    return float(min(q.mesh.bounds[0][2] for q in ee if "finger" in q.name or "gripper" in q.name))


def stations(cal):
    t = cal["tray"]
    return {
        "chip tray (gantry)": dict(xy=t["centre"][:2], top=t["centre"][2]),
        "ASI stage sample insert": dict(xy=[1118.0 - 25.0, 379.0], top=182.0),
        "docking fixture A": dict(xy=[930.0, 710.0], top=282.0),
        "docking fixture B": dict(xy=[1046.5, 692.5], top=282.0),
    }


def nearest_node(j1s, j2s, j1, j2):
    return int(np.argmin(np.abs(j1s - j1))), int(np.argmin(np.abs(j2s - j2)))


def main():
    pose, p = load_pose()
    B = E.base_transform(pose)
    parts = MO.static_parts()
    occ = MO.occupancy(parts)
    S = thin_samples()
    print("C-space ...", flush=True)
    j1s, j2s, free, gap = cspace(pose, occ, S)
    from scipy.ndimage import label
    lab, _ = label(free, structure=np.ones((3, 3)))
    park = nearest_node(j1s, j2s, p["parked"]["j1"], p["parked"]["j2"])
    # the parked pose itself overlaps the far end in the model (README); use the largest free region
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    region = lab == int(np.argmax(sizes))
    print("height map ...", flush=True)
    xs, ys, Hm = height_map(parts + [q for q in SD.cables()])
    Hfp = footprint_max(Hm, FOOT_R)
    z_up = tip_height_up(pose)
    z_low = z_up - STROKE
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    sol = ik(pose, X.ravel(), Y.ravel())
    lowest = np.full((2, X.size), np.nan)
    for k in range(2):
        j1, j2 = sol[k]
        ok = np.isfinite(j1) & (np.abs(j1) <= E.LIMITS["j1"]) & (np.abs(j2) <= E.LIMITS["j2"])
        idx = np.where(ok)[0]
        a = np.clip(np.round((j1[idx] + E.LIMITS["j1"])).astype(int), 0, len(j1s) - 1)
        b = np.clip(np.round((j2[idx] + E.LIMITS["j2"])).astype(int), 0, len(j2s) - 1)
        good = region[a, b]
        lo = np.maximum(z_low, Hfp.ravel()[idx] + 2.0)
        lo = np.where(lo <= z_up, lo, np.nan)
        lowest[k, idx[good]] = lo[good]
    best = np.nanmin(np.where(np.isfinite(lowest), lowest, np.inf), axis=0)
    best = np.where(np.isfinite(best), best, np.nan).reshape(X.shape)
    either = np.isfinite(lowest).any(0).reshape(X.shape)
    # stations
    st = {}
    for name, s in stations(CAL).items():
        x, y = s["xy"]
        q = ik(pose, [x], [y])
        rec = dict(xy_mm=[round(x, 1), round(y, 1)], top_mm=round(s["top"], 1), configs=[])
        for k, elbow in enumerate(("J2 > 0", "J2 < 0")):
            j1, j2 = float(q[k, 0, 0]), float(q[k, 1, 0])
            if not np.isfinite(j1):
                rec["configs"].append(dict(elbow=elbow, reachable=False, why="out of the arm's reach"))
                continue
            within = abs(j1) <= E.LIMITS["j1"] and abs(j2) <= E.LIMITS["j2"]
            P = pose_points(S, B, j1, j2)
            hit = collides(P, occ)
            a, b = nearest_node(j1s, j2s, j1, j2)
            conn = bool(region[a, b])
            i, j = int(np.clip(x // CELL, 0, len(xs) - 1)), int(np.clip(y // CELL, 0, len(ys) - 1))
            need = z_up - (s["top"] + 1.0)
            rec["configs"].append(dict(
                elbow=elbow, j1_deg=round(j1, 1), j2_deg=round(j2, 1), within_limits=within,
                arm_clear_with_shaft_up=not hit, connected_to_free_region=conn,
                stroke_needed_mm=round(need, 1), stroke_ok=bool(0 <= need <= STROKE),
                tallest_under_gripper_mm=round(float(Hfp[i, j]), 1),
                reachable=bool(within and not hit and conn and 0 <= need <= STROKE)))
        rec["reachable"] = any(c.get("reachable") for c in rec["configs"])
        st[name] = rec
    # gantry hand-off: the tray's travel on the X and Y axes (scene_detail.gantry: X axis (285, 505) ->
    # (680, 520), Y axis (600, 262) -> (600, 492)); the carriage keeps CARRIAGE_END mm from each end
    t = CAL["tray"]
    off = np.array(t["centre"][:2]) - np.array([285 + 0.7 * 395, 262 + 0.55 * 230])   # tray vs carriages
    gx = np.arange(285 + CARRIAGE_END, 680 - CARRIAGE_END + 1e-6, CELL) + off[0]
    gy = np.arange(262 + CARRIAGE_END, 492 - CARRIAGE_END + 1e-6, CELL) + off[1]
    GX, GY = np.meshgrid(gx, gy, indexing="ij")
    qq = ik(pose, GX.ravel(), GY.ravel())
    # the gripper takes the tray by its fork at the tray's own height, so for the hand-off only the arm
    # (arm 1, arm 2, the unit on it, the collar) has to stay clear, and the tray, its holder and carriage
    # (which move with the gantry) are not obstacles
    tray_like = ("chip tray", "chips", "tray carriage")
    occ_h = MO.occupancy([q for q in parts if not q.name.startswith(tray_like)])
    S_arm = {k: v for k, v in S.items() if k not in ("shaft", "ee_shaft")}
    S_arm["shaft"] = np.zeros((0, 3))
    S_arm["ee_shaft"] = np.zeros((0, 3))
    print("hand-off C-space ...", flush=True)
    _, _, free_h, _ = cspace(pose, occ_h, S_arm)
    lab_h, _ = label(free_h, structure=np.ones((3, 3)))
    sz = np.bincount(lab_h.ravel())
    sz[0] = 0
    region_h = lab_h == int(np.argmax(sz))
    hand = np.zeros(GX.size, bool)
    for k in range(2):
        j1, j2 = qq[k]
        okk = np.isfinite(j1) & (np.abs(j1) <= E.LIMITS["j1"]) & (np.abs(j2) <= E.LIMITS["j2"])
        idx = np.where(okk)[0]
        a = np.clip(np.round(j1[idx] + E.LIMITS["j1"]).astype(int), 0, len(j1s) - 1)
        b = np.clip(np.round(j2[idx] + E.LIMITS["j2"]).astype(int), 0, len(j2s) - 1)
        hand[idx[region_h[a, b]]] = True
    hand = hand.reshape(GX.shape)
    d_now = float(np.hypot(*(np.array(t["centre"][:2]) - np.array(pose["j1"]))))
    handoff = dict(
        tray_travel_x_mm=[round(float(gx[0]), 1), round(float(gx[-1]), 1)],
        tray_travel_y_mm=[round(float(gy[0]), 1), round(float(gy[-1]), 1)],
        assumption="the tray rides on the X and Y axes' carriages, which keep 70 mm from each end of their screws; "
                   "the gripper takes the tray by its fork at the tray's height, so only the arm (arm 1, arm 2, the "
                   "unit and the collar) must clear the other parts, and the tray, its holder and carriage are not "
                   "obstacles",
        tray_now_from_j1_mm=round(d_now, 1), arm_reach_mm=E.L1 + E.L2,
        reachable_fraction_of_travel=round(float(hand.mean()), 3),
        reachable_x_mm=[round(float(GX[hand].min()), 1), round(float(GX[hand].max()), 1)] if hand.any() else None,
        reachable_y_mm=[round(float(GY[hand].min()), 1), round(float(GY[hand].max()), 1)] if hand.any() else None,
        nearest_reachable_from_now_mm=round(float(np.hypot(GX[hand] - t["centre"][0], GY[hand] - t["centre"][1]).min()), 1)
        if hand.any() else None)
    vp = json.load(open(os.path.join(OUT, "video_robot_poses.json")))
    video = {}
    for k in ("video_transfer_612", "video_transfer_640"):
        if k in vp:
            q = vp[k]["pose"]
            a, b = nearest_node(j1s, j2s, q["j1"], q["j2"])
            P = pose_points(S, B, q["j1"], q["j2"])
            video[k] = dict(j1_deg=q["j1"], j2_deg=q["j2"], free_in_model=bool(free[a, b]),
                            in_largest_free_region=bool(region[a, b]), clearance_mm=round(float(gap[a, b]), 1),
                            arm_hits=None if not collides(P, occ) else "equipment or box")
    res = dict(
        base_pose=pose, cell_mm=CELL, gripper_footprint_radius_mm=FOOT_R,
        fingertips_with_shaft_up_mm=round(z_up, 1), fingertips_lowest_mm=round(z_low, 1),
        joint_grid_deg=1.0, free_fraction=round(float(free.mean()), 3), largest_free_region=round(float(region.mean()), 3),
        parked_in_largest_region=bool(region[park]),
        reachable_area_m2=round(float(either.sum()) * CELL * CELL / 1e6, 3),
        stations=st, gantry_handoff=handoff, video_poses=video)
    json.dump(res, open(os.path.join(OUT, "epson_reach.json"), "w"), indent=1)
    plot(xs, ys, Hm, best, st, pose, (gx, gy, hand), (j1s, j2s, free, region, gap), p, video)
    print(json.dumps({k: v["reachable"] for k, v in st.items()}), json.dumps(handoff), json.dumps(video))


def plot(xs, ys, Hm, best, st, pose, gant, cs, p, video):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    gx, gy, hand = gant
    j1s, j2s, free, region, gap = cs
    fig, ax = plt.subplots(1, 2, figsize=(15.5, 6.6), gridspec_kw=dict(width_ratios=[1.12, 1]))
    ext = [0, GB_W, 0, GB_D]
    a = ax[0]
    a.imshow(Hm.T, origin="lower", extent=ext, cmap="Greys", vmin=-80, vmax=520, interpolation="nearest")
    im = a.imshow(np.ma.masked_invalid(best).T, origin="lower", extent=ext, cmap="viridis_r", vmin=30, vmax=240,
                  alpha=0.82, interpolation="nearest")
    cb = fig.colorbar(im, ax=a, shrink=0.8, pad=0.01)
    cb.set_label("lowest fingertip height coming straight down (mm above the deck)")
    a.add_patch(Rectangle((gx[0], gy[0]), gx[-1] - gx[0], gy[-1] - gy[0], fill=False, ec="#c0392b", lw=1.5, ls="--"))
    if hand.any():
        GX, GY = np.meshgrid(gx, gy, indexing="ij")
        a.scatter(GX[hand], GY[hand], s=3, c="#c0392b", lw=0)
    a.annotate("chip tray travel on the gantry\n(dots: J3 can reach the tray)", (gx[0], gy[0]), xytext=(-10, -34),
               textcoords="offset points", fontsize=7.5, color="#c0392b")
    for name, r in st.items():
        x, y = r["xy_mm"]
        a.plot(x, y, "o", ms=8, mec="k", color="#2ca02c" if r["reachable"] else "#d62728")
        a.annotate(name, (x, y), xytext=(6, 5), textcoords="offset points", fontsize=7.5,
                   bbox=dict(boxstyle="round,pad=0.2", fc="w", alpha=0.85))
    a.plot(*pose["j1"], "ks", ms=7)
    a.annotate("J1", pose["j1"], xytext=(6, -10), textcoords="offset points", fontsize=8)
    a.set_xlim(-10, GB_W + 10)
    a.set_ylim(-10, GB_D + 10)
    a.set_aspect("equal")
    a.set_xlabel("x (mm, from the antechamber wall)")
    a.set_ylabel("y (mm, from the open side)")
    a.set_title("Where the gripper can come down, and how low (shaft up to 200 mm stroke)", fontsize=10)
    a = ax[1]
    img = np.where(region, np.clip(gap, 0, 120), np.nan)
    im2 = a.imshow(np.ma.masked_invalid(img).T, origin="lower", cmap="YlGn", vmin=0, vmax=120, aspect="auto",
                   extent=[j1s[0] - 0.5, j1s[-1] + 0.5, j2s[0] - 0.5, j2s[-1] + 0.5], interpolation="nearest")
    blocked = np.where(~free, 1.0, np.nan)
    a.imshow(np.ma.masked_invalid(blocked).T, origin="lower", cmap=matplotlib.colors.ListedColormap(["#d9d9d9"]),
             aspect="auto", extent=[j1s[0] - 0.5, j1s[-1] + 0.5, j2s[0] - 0.5, j2s[-1] + 0.5], interpolation="nearest")
    cb2 = fig.colorbar(im2, ax=a, shrink=0.8, pad=0.01)
    cb2.set_label("clearance to the nearest part (mm)")
    a.plot(p["parked"]["j1"], p["parked"]["j2"], "w*", ms=14, mec="k", label="parked (Overhead 1 fit)")
    for k, v in video.items():
        a.plot(v["j1_deg"], v["j2_deg"], "D", ms=7, mec="k", color="#3778bf",
               label="AURORA video frames 612, 640" if k.endswith("612") else None)
    for name, r in st.items():
        for c in r["configs"]:
            if c.get("j1_deg") is not None:
                a.plot(c["j1_deg"], c["j2_deg"], "o", ms=6, mfc="none", mec="#d62728", mew=1.4)
    a.plot([], [], "o", mfc="none", mec="#d62728", label="stations (both elbows)")
    a.set_xlabel("J1 (deg)")
    a.set_ylabel("J2 (deg)")
    a.set_title("Joint space with the shaft up: free poses (green, by clearance), blocked (grey)", fontsize=10)
    a.legend(loc="lower left", fontsize=7.5, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "epson_reach.png"), dpi=105)


if __name__ == "__main__":
    main()
