"""Allowable motion of the Epson T6-B602S inside the glovebox: its joint limits (Epson T-B manual)
intersected with the space the box and the other equipment leave it.

    python motion.py            # -> out/epson_motion.json, out/epson_motion.png

Every (J1, J2) pair on a 2 degree grid within the manual's limits is posed with Epson's own CAD
(arm 1, arm 2 with the black unit, the J3 shaft fully up, and the end effector seen in the AURORA
video) on the fitted base pose
(out/epson_cad_pose.json). A pose is free when no point sampled on those links comes within one voxel
(10 mm) of the walls, the ceiling or any other part of the model. The shaft's lowered positions are
not swept: the shaft is meant to reach the deck items. The user duct (the corrugated hose from the base to
arm 2) is left out: it flexes with J2, and Epson's CAD has it in one shape only.

This uses the model, so it inherits its accuracy (tens of mm for parts placed from one view) and its
gaps (no cables, the hidden backs of parts are inferred).
"""
import json
import os

import numpy as np
import trimesh

import epson_cad as E
import scene_detail as SD
from cameras import CAL
from scene import GB_D, GB_H, GB_W, FRONT_LEAN, BACK_LEAN

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
VOX = 10.0
STEP = 2.0


def static_parts():
    parts = []
    for f in (SD.shell, SD.ducts, SD.breadboards, SD.exfoliator, SD.microscope, SD.deck_items):
        parts += f()
    for f in (SD.tray, SD.gantry, SD.amcrest_cameras):
        parts += f(CAL)
    return [p for p in parts if getattr(p, "image", None) is None and p.group not in ("cameras",)]


def occupancy(parts):
    """Boolean voxel grid (VOX mm) of the parts' surfaces, dilated by one voxel."""
    shape = (int(np.ceil(GB_W / VOX)) + 2, int(np.ceil(GB_D / VOX)) + 2, int(np.ceil(GB_H / VOX)) + 2)
    occ = np.zeros(shape, bool)
    for p in parts:
        m = p.mesh
        if m.area <= 0:
            continue
        n = int(min(400000, max(200, m.area / (VOX * VOX / 6))))
        pts, _ = trimesh.sample.sample_surface(m, n, seed=0)
        ijk = np.floor(pts / VOX).astype(int) + 1
        ok = np.all((ijk >= 0) & (ijk < shape), axis=1)
        occ[tuple(ijk[ok].T)] = True
    from scipy.ndimage import binary_dilation
    return binary_dilation(occ, iterations=1)


def outside_box(P):
    """Points beyond the walls, the sloped long windows or the ceiling."""
    z = np.clip(P[:, 2], 0, GB_H)
    y_open = FRONT_LEAN * z / GB_H
    y_far = GB_D - BACK_LEAN * z / GB_H
    return (P[:, 0] < 0) | (P[:, 0] > GB_W) | (P[:, 1] < y_open) | (P[:, 1] > y_far) | (P[:, 2] > GB_H - 3)


def link_samples(n=2500):
    L = E.links()
    out = {}
    for k in ("arm1", "arm2", "shaft", "cable"):
        pts, _ = trimesh.sample.sample_surface(L[k], n, seed=1)
        out[k] = pts
    u = E.unit_box()
    out["unit"] = trimesh.sample.sample_surface(u, 600, seed=2)[0]
    # the end effector seen in the video (scene_detail.end_effector), in the links' own frames; the
    # tubing into the shaft top is flexible and left out like the duct
    ee = [q for q in SD.end_effector(np.eye(4), np.eye(4)) if "tubing" not in q.name]
    out["ee_arm2"] = np.vstack([trimesh.sample.sample_surface(q.mesh, 300, seed=3)[0] for q in ee if "collar" in q.name])
    out["ee_shaft"] = np.vstack([trimesh.sample.sample_surface(q.mesh, 400, seed=4)[0] for q in ee
                                 if "collar" not in q.name])
    return out


def sweep(pose, occ, samples, ceiling_squash=True):
    B = E.base_transform(pose)
    cab = samples["cable"].copy()
    if ceiling_squash:
        top = GB_H - pose["z0"] - 8.0
        lo = 443.8
        if cab[:, 2].max() > top:
            cab[:, 2] = np.where(cab[:, 2] > lo, lo + (cab[:, 2] - lo) * (top - lo) / (cab[:, 2].max() - lo), cab[:, 2])
    j1s = np.arange(-E.LIMITS["j1"], E.LIMITS["j1"] + 1e-6, STEP)
    j2s = np.arange(-E.LIMITS["j2"], E.LIMITS["j2"] + 1e-6, STEP)
    state = np.zeros((len(j1s), len(j2s)), np.uint8)     # 0 free, 1 wall/ceiling, 2 equipment
    j3 = np.zeros((len(j1s), len(j2s), 2))
    for a, j1 in enumerate(j1s):
        for b, j2 in enumerate(j2s):
            T = E.link_transforms(j1, j2)
            P = np.vstack([trimesh.transform_points(samples["arm1"], B @ T["arm1"]),
                           trimesh.transform_points(samples["arm2"], B @ T["arm2"]),
                           trimesh.transform_points(samples["unit"], B @ T["unit"]),
                           trimesh.transform_points(samples["shaft"], B @ T["shaft"]),
                           trimesh.transform_points(samples["ee_arm2"], B @ T["arm2"]),
                           trimesh.transform_points(samples["ee_shaft"], B @ T["shaft"])])
            if outside_box(P).any():
                state[a, b] = 1
            else:
                ijk = np.floor(P / VOX).astype(int) + 1
                ijk = np.clip(ijk, 0, np.array(occ.shape) - 1)
                if occ[tuple(ijk.T)].any():
                    state[a, b] = 2
            j3[a, b] = (B @ T["shaft"] @ np.r_[E.L1 + E.L2, 0, 0, 1])[:2]
    return j1s, j2s, state, j3


def main():
    p = json.load(open(os.path.join(OUT, "epson_cad_pose.json")))
    pose = dict(j1=tuple(p["base"]["j1"]), z0=p["base"]["z0"], yaw=p["base"]["yaw"])
    parts = static_parts()
    occ = occupancy(parts)
    j1s, j2s, state, j3 = sweep(pose, occ, link_samples())
    free = state == 0
    # the largest connected free region: where the arm can move between poses without a collision
    from scipy.ndimage import label
    lab, n = label(free)
    reach = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1) if n else np.zeros_like(free)
    parked_conflicts = conflicts(pose, p["parked"], occ, parts)
    res = dict(
        robot="Epson T6-B602S (SCARA, controller in the base)",
        limits_manual=dict(j1_deg=[-132, 132], j2_deg=[-150, 150], j3_stroke_mm=200, j4_deg=[-360, 360],
                           arm1_mm=E.L1, arm2_mm=E.L2, source="Epson T-B series manual (Rev.13): joint ranges and arm lengths"),
        base_pose=pose, parked=p["parked"], parked_pose_conflicts=parked_conflicts,
        grid_step_deg=STEP, clearance_mm=VOX,
        fraction_of_manual_range=dict(free=round(float(free.mean()), 3),
                                      walls_or_ceiling=round(float((state == 1).mean()), 3),
                                      equipment=round(float((state == 2).mean()), 3),
                                      largest_connected_free_region=round(float(reach.mean()), 3)),
        j1_free_range_deg=[float(j1s[np.any(reach, 1)].min()), float(j1s[np.any(reach, 1)].max())] if reach.any() else None,
        j3_reach_xy_mm=dict(x=[round(float(j3[reach][:, 0].min()), 1), round(float(j3[reach][:, 0].max()), 1)],
                            y=[round(float(j3[reach][:, 1].min()), 1), round(float(j3[reach][:, 1].max()), 1)])
        if reach.any() else None,
        note="Shaft fully up (J3 = 0); points sampled on Epson's CAD links within 10 mm of the box or another part count "
             "as a collision. Uses the model, so it is as good as the model's part positions.")
    json.dump(res, open(os.path.join(OUT, "epson_motion.json"), "w"), indent=1)
    plot(j1s, j2s, state, reach, j3, p, occ)
    print(json.dumps(res["fraction_of_manual_range"]), res["j1_free_range_deg"], res["j3_reach_xy_mm"])


def conflicts(pose, parked, occ, parts):
    """Where the parked pose fitted from Overhead 1 already overlaps the box or another part: a check of
    the model's consistency (a real robot can't stand inside the microscope)."""
    S = link_samples()
    B = E.base_transform(pose)
    T = E.link_transforms(parked["j1"], parked["j2"])
    out = {}
    names = [p for p in parts if len(p.mesh.faces) < 300000]
    for k in ("arm1", "arm2", "unit", "shaft", "ee_shaft"):
        P = trimesh.transform_points(S[k], B @ T["shaft" if k == "ee_shaft" else k])
        ob = outside_box(P)
        ijk = np.clip(np.floor(P / VOX).astype(int) + 1, 0, np.array(occ.shape) - 1)
        hit = occ[tuple(ijk.T)] & ~ob
        rec = dict(points_outside_box=int(ob.sum()), points_in_equipment=int(hit.sum()),
                   max_x_mm=round(float(P[:, 0].max()), 1))
        if hit.any():
            H = P[hit][:: max(1, int(hit.sum()) // 25)]
            near = {}
            for q in H:
                d = [(float(np.linalg.norm(m.mesh.nearest.on_surface([q])[0][0] - q)), m.name) for m in names
                     if np.all(q > m.mesh.bounds[0] - 30) and np.all(q < m.mesh.bounds[1] + 30)]
                if d:
                    nm = min(d)[1]
                    near[nm] = near.get(nm, 0) + 1
            rec["near_parts"] = dict(sorted(near.items(), key=lambda kv: -kv[1])[:5])
        out[k] = rec
    return out


def plot(j1s, j2s, state, reach, j3, p, occ):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    fig, ax = plt.subplots(1, 2, figsize=(13, 5.6), gridspec_kw=dict(width_ratios=[1, 1.08]))
    img = np.where(reach, 3, state)
    cmap = ListedColormap(["#c9d8c5", "#9a9a9a", "#d9822b", "#3b7d3b"])
    ax[0].imshow(img.T, origin="lower", cmap=cmap, vmin=0, vmax=3, aspect="auto",
                 extent=[j1s[0] - STEP / 2, j1s[-1] + STEP / 2, j2s[0] - STEP / 2, j2s[-1] + STEP / 2],
                 interpolation="nearest")
    ax[0].plot(p["parked"]["j1"], p["parked"]["j2"], "w*", ms=14, mec="k")
    ax[0].set_xlabel("J1 (deg)")
    ax[0].set_ylabel("J2 (deg)")
    ax[0].set_title("Joint space, shaft up (Epson limits: J1 ±132°, J2 ±150°)", fontsize=10)
    from matplotlib.patches import Patch
    ax[0].legend(handles=[Patch(color="#3b7d3b", label="free (largest connected region)"),
                          Patch(color="#c9d8c5", label="free, cut off from it"),
                          Patch(color="#d9822b", label="hits equipment"),
                          Patch(color="#9a9a9a", label="hits a wall or the ceiling"),
                          plt.Line2D([], [], marker="*", color="w", mec="k", ms=12, ls="", label="parked (Overhead 1 fit)")],
                 loc="lower left", fontsize=7.5, framealpha=0.9)
    top = occ[:, :, 4:-3].any(axis=2).astype(float)     # footprint of everything above the deck surface
    ax[1].imshow(np.where(top.T > 0, 1.0, np.nan), origin="lower", cmap=ListedColormap(["#bdbdbd"]), vmin=0, vmax=1,
                 extent=[-VOX, top.shape[0] * VOX - VOX, -VOX, top.shape[1] * VOX - VOX], interpolation="nearest")
    q = j3[reach]
    ax[1].scatter(q[:, 0], q[:, 1], s=1.2, c="#3b7d3b", alpha=0.35, lw=0)
    ax[1].plot(*p["base"]["j1"], "ks", ms=7)
    ax[1].plot(*np.array(p["j3_xy"]), "w*", ms=13, mec="k")
    ax[1].add_patch(plt.Rectangle((0, 0), GB_W, GB_D, fill=False, lw=1.2))
    ax[1].set_xlim(-30, GB_W + 30)
    ax[1].set_ylim(-30, GB_D + 30)
    ax[1].set_aspect("equal")
    ax[1].set_xlabel("x (mm, from the antechamber wall)")
    ax[1].set_ylabel("y (mm, from the open side)")
    ax[1].set_title("Where the J3 shaft can go (green), over the model's footprint (grey)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "epson_motion.png"), dpi=110)


if __name__ == "__main__":
    main()
