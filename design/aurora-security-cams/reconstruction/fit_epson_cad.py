"""Pose Epson's own T6-B602S CAD in the reconstruction: fit it to the robot's SAM 2.1 silhouette in
Overhead 1 (../vision/masks/robot_cam0.png), with a prior that keeps J2 and J3 near the two-view fit of
the hand-built outline (scene.ROBOT, which also used Overhead 2's silhouette of arm 2).

Overhead 1 alone does not fix the arm's depth: the Overhead-1-only fit in ../vision/out/epson_pose.json
matches the mask at IoU 0.78 but parks J3 at x = 1416 mm, past the far end of the 1200 mm box. The
prior removes that ambiguity. Writes out/epson_cad_pose.json.

    python fit_epson_cad.py
"""
import json
import os
import sys
import time

import cv2
import numpy as np
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "vision", "robotseg"))
import epson_render as R  # noqa: E402
from scene import ROBOT  # noqa: E402

S = 0.5
OUT = os.path.join(HERE, "out", "epson_cad_pose.json")
PRIOR_MM = 60.0          # J2/J3 within about this of the two-view fit costs little


def joints(pose, j1, j2):
    y = np.radians(pose["yaw"] + j1)
    J1 = np.asarray(pose["j1"], float)
    J2 = J1 + 325.0 * np.array([np.cos(y), np.sin(y)])
    y2 = y + np.radians(j2)
    return J2, J2 + 275.0 * np.array([np.cos(y2), np.sin(y2)])


def main():
    sam = cv2.imread(os.path.join(HERE, "..", "vision", "masks", "robot_cam0.png"), cv2.IMREAD_GRAYSCALE)
    spec = json.load(open(os.path.join(HERE, "..", "vision", "inside_masks.json")))["cam0"]
    zone = np.zeros_like(sam)
    cv2.fillPoly(zone, [np.array(spec["robot_zone"], np.int32)], 255)
    tgt = cv2.resize(sam, None, fx=S, fy=S, interpolation=cv2.INTER_NEAREST) > 0
    zs = cv2.resize(zone, None, fx=S, fy=S, interpolation=cv2.INTER_NEAREST) > 0
    pose0, j10, j20 = R.E.from_scene_robot(ROBOT)
    J2h, J3h = joints(pose0, j10, j20)
    x0 = np.array([pose0["j1"][0], pose0["j1"][1], pose0["z0"], pose0["yaw"], j10, j20])

    def unpack(x):
        return dict(j1=(x[0], x[1]), z0=x[2], yaw=x[3]), x[4], x[5]

    def iou(x):
        pose, j1, j2 = unpack(x)
        m = R.silhouette(R.posed_meshes(pose, j1, j2), R.CAM0, scale=S) > 0
        a, b = m & zs, tgt & zs
        return (a & b).sum() / max((a | b).sum(), 1)

    def cost(x):
        pose, j1, j2 = unpack(x)
        if abs(j1) > 132 or abs(j2) > 150:
            return 2.0
        J2, J3 = joints(pose, j1, j2)
        prior = (np.sum((J2 - J2h) ** 2) + np.sum((J3 - J3h) ** 2)) / PRIOR_MM ** 2
        return 1.0 - iou(x) + 0.01 * prior

    t = time.time()
    print("start IoU", round(iou(x0), 3))
    rng = np.random.default_rng(0)
    starts = [x0] + [x0 + rng.normal(0, 1, 6) * np.array([25, 25, 20, 5, 15, 15]) for _ in range(7)]
    best, best_cost = x0, cost(x0)
    for k, xs in enumerate(starts):
        x = xs
        for step in (np.array([30, 30, 20, 6, 8, 8]), np.array([10, 10, 8, 2, 3, 3])):
            r = minimize(cost, x, method="Nelder-Mead",
                         options=dict(initial_simplex=np.vstack([x] + [x + np.eye(6)[i] * step[i] for i in range(6)]),
                                      maxiter=300, xatol=0.5, fatol=1e-4))
            x = r.x
        c = cost(x)
        print(f"start {k}: IoU {iou(x):.3f}, cost {c:.3f}, {time.time() - t:.0f} s")
        if c < best_cost:
            best, best_cost = x, c
    pose, j1, j2 = unpack(best)
    J2, J3 = joints(pose, j1, j2)
    out = dict(source="Epson's T6-B602S CAD fitted to the SAM 2.1 silhouette in Overhead 1 (robot zone, half "
                      "resolution), with J2 and J3 held near the two-view fit of the hand-built outline "
                      f"(scene.ROBOT; {PRIOR_MM:.0f} mm prior)",
               iou_cam0=round(float(iou(best)), 3), iou_cam0_start=round(float(iou(x0)), 3),
               base=dict(j1=[round(pose["j1"][0], 1), round(pose["j1"][1], 1)], z0=round(pose["z0"], 1),
                         yaw=round(pose["yaw"], 2)),
               parked=dict(j1=round(j1, 2), j2=round(j2, 2), z=0.0, u=0.0),
               j2_xy=np.round(J2, 1).tolist(), j3_xy=np.round(J3, 1).tolist(),
               j3_from_two_view_fit_mm=round(float(np.linalg.norm(J3 - J3h)), 1))
    json.dump(out, open(OUT, "w"), indent=1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
