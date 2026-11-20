"""Fit the Epson's base pose and parked joint angles to its SAM 2.1 silhouette in Overhead 1
(masks/robot_cam0.png), using Epson's own CAD. Writes out/epson_pose.json.

The base (J1 position, underside height and yaw) is fixed to the deck, so it is what the synthetic
training data reuses; the parked j1/j2 only matter for this one frame.
"""
import json
import os
import time

import cv2
import numpy as np
from scipy.optimize import minimize

import epson_render as R

HERE = R.HERE
S = 0.5   # fit at half resolution


def main():
    sam = cv2.imread(os.path.join(HERE, "..", "masks", "robot_cam0.png"), cv2.IMREAD_GRAYSCALE)
    spec = json.load(open(os.path.join(HERE, "..", "inside_masks.json")))["cam0"]
    zone = np.zeros_like(sam)
    cv2.fillPoly(zone, [np.array(spec["robot_zone"], np.int32)], 255)
    tgt = cv2.resize(sam, None, fx=S, fy=S, interpolation=cv2.INTER_NEAREST) > 0
    zs = cv2.resize(zone, None, fx=S, fy=S, interpolation=cv2.INTER_NEAREST) > 0
    from scene import ROBOT
    pose0, j10, j20 = R.E.from_scene_robot(ROBOT)
    x0 = np.array([pose0["j1"][0], pose0["j1"][1], pose0["z0"], pose0["yaw"], j10, j20])

    def unpack(x):
        return dict(j1=(x[0], x[1]), z0=x[2], yaw=x[3]), x[4], x[5]

    def cost(x):
        pose, j1, j2 = unpack(x)
        if abs(j1) > 132 or abs(j2) > 150:
            return 1.0
        m = R.silhouette(R.posed_meshes(pose, j1, j2), R.CAM0, scale=S) > 0
        a, b = m & zs, tgt & zs
        return 1.0 - (a & b).sum() / max((a | b).sum(), 1)

    t = time.time()
    print("start IoU", 1 - cost(x0))
    best = x0
    for step in (np.array([30, 30, 20, 6, 8, 8]), np.array([10, 10, 8, 2, 3, 3])):
        r = minimize(cost, best, method="Nelder-Mead",
                     options=dict(initial_simplex=np.vstack([best] + [best + np.eye(6)[i] * step[i] for i in range(6)]),
                                  maxiter=260, xatol=0.5, fatol=1e-4))
        best = r.x
        print(f"IoU {1 - r.fun:.3f} after {r.nfev} evals, {time.time() - t:.0f} s")
    pose, j1, j2 = unpack(best)
    out = dict(source="Nelder-Mead on Epson's T6-B602S CAD vs the SAM 2.1 silhouette in Overhead 1 (robot zone, "
                      "half resolution)",
               iou_cam0=round(1 - cost(best), 3),
               base=dict(j1=[round(pose["j1"][0], 1), round(pose["j1"][1], 1)], z0=round(pose["z0"], 1),
                         yaw=round(pose["yaw"], 2)),
               parked=dict(j1=round(j1, 2), j2=round(j2, 2), z=0.0, u=0.0))
    json.dump(out, open(R.POSE_FILE, "w"), indent=1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
