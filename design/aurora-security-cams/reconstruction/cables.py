"""Cables and tubing, traced in the two Overhead stills and lifted onto the model.

    xvfb-run -a python cables.py        # -> out/cables.json (3D polylines with radius and finish)

The model had no cables, the most visible gap in both views. Here:
  1. Pixels of each cable colour are segmented in each published still (HSV thresholds, inside the
     glovebox mask only): blue signal/motor cables, green and clear-green tubing, red wires, and the
     grey/white sensor cables. Black cables are not segmented: they can't be told from the black
     anodised parts by colour.
  2. Each mask is thinned to its skeleton and split at junctions into runs; short runs are dropped.
  3. Each run is lifted to 3D along its camera's rays. A cable lies on or in front of what is behind
     it, so its depth is the nearest model surface within a window along the run (a front envelope),
     less its radius, smoothed. Its radius comes from the run's width in pixels at that depth.

So a cable is right in the view it was traced from and lies on the surfaces under it from any other
view; cables in free air between two parts drop onto the nearer part. Two views would fix that, but
cables can't be matched between them by colour alone.
"""
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cameras import CAL, CAM0, CAM1  # noqa: E402

OUT = os.path.join(HERE, "out")
CAPS = os.path.join(HERE, "..", "captures")
MASKS = os.path.join(HERE, "..", "vision", "masks")
STILLS = {"cam0": "2026-11-19_1822Z_cam0_192.168.3.150.jpg", "cam1": "2026-11-19_1822Z_cam1_192.168.3.151.jpg"}

# (finish, HSV lower, HSV upper) in OpenCV units (H 0-180)
KINDS = {
    "cable_blue": ((100, 120, 45), (124, 255, 255)),
    "tube_green": ((58, 90, 50), (88, 255, 255)),
    "wire_red": ((0, 150, 70), (6, 255, 255)),
}
MIN_RUN_PX = 40
# patches that have a cable colour but aren't cables: (camera, kind) -> boxes (x0, y0, x1, y1)
EXCLUDE = {("cam0", "tube_green"): [(400, 585, 610, 675)]}   # green tape labels on the Epson's breadboard


def skeleton_runs(mask):
    from skimage.morphology import skeletonize
    sk = skeletonize(mask > 0)
    k = np.ones((3, 3), np.uint8)
    nb = cv2.filter2D(sk.astype(np.uint8), -1, k) - sk.astype(np.uint8)
    junction = sk & (nb > 2)
    junction = cv2.dilate(junction.astype(np.uint8), k) > 0
    seg = sk & ~junction
    n, lab = cv2.connectedComponents(seg.astype(np.uint8), connectivity=8)
    runs = []
    for i in range(1, n):
        ys, xs = np.nonzero(lab == i)
        if len(xs) < MIN_RUN_PX:
            continue
        pts = set(zip(xs.tolist(), ys.tolist()))
        # walk from an endpoint
        def nbrs(p):
            return [(p[0] + dx, p[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    if (dx or dy) and (p[0] + dx, p[1] + dy) in pts]
        ends = [p for p in pts if len(nbrs(p)) == 1]
        cur = ends[0] if ends else next(iter(pts))
        order, seen = [cur], {cur}
        while True:
            nx = [q for q in nbrs(cur) if q not in seen]
            if not nx:
                break
            cur = nx[0]
            seen.add(cur)
            order.append(cur)
        if len(order) >= MIN_RUN_PX:
            runs.append(np.array(order, float))
    return runs


def lift_run(cam, depth, run, width_px):
    from video_register import lift
    P = lift(cam, depth, run)
    z = np.linalg.norm(P - cam.centre, axis=1)
    ok = np.isfinite(z)
    if ok.sum() < 0.6 * len(z):
        return None
    z = np.interp(np.arange(len(z)), np.nonzero(ok)[0], z[ok])
    # front envelope over a +-12 px window, then smooth
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    zf = uniform_filter1d(minimum_filter1d(z, 25, mode="nearest"), 15, mode="nearest")
    r_mm = float(np.clip(np.median(width_px) / 2 * np.median(zf) / cam.f, 1.5, 6.0))
    d = (P - cam.centre)
    d[~ok] = np.nan
    rays = cam.ray(run)
    Q = cam.centre + rays * (zf - r_mm)[:, None]
    step = max(1, len(Q) // 40)
    return Q[::step].tolist() + [Q[-1].tolist()], r_mm


def main():
    import scene_detail as SD
    from video_register import model_depth
    parts = [p for p in SD.build(CAL, with_cables=False) if getattr(p, "image", None) is None and p.group != "cameras"]
    out = []
    for cam in (CAM0, CAM1):
        img = cv2.imread(os.path.join(CAPS, STILLS[cam.name]))
        inside = cv2.imread(os.path.join(MASKS, f"inside_{cam.name}.png"), 0)
        inside = cv2.erode((inside > 127).astype(np.uint8), np.ones((9, 9), np.uint8))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        depth = model_depth(parts, cam)
        for kind, (lo, hi) in KINDS.items():
            m = cv2.inRange(hsv, np.array(lo), np.array(hi)) & (inside * 255)
            for x0, y0, x1, y1 in EXCLUDE.get((cam.name, kind), []):
                m[y0:y1, x0:x1] = 0
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            n, lab, st, _ = cv2.connectedComponentsWithStats(m)
            for i in range(1, n):
                if st[i, cv2.CC_STAT_AREA] < 150:
                    m[lab == i] = 0
            dist = cv2.distanceTransform(m, cv2.DIST_L2, 5)
            for run in skeleton_runs(m):
                w = 2 * dist[run[:, 1].astype(int), run[:, 0].astype(int)]
                if np.median(w) > 26:        # wider than any cable here: a part of that colour, not a cable
                    continue
                r = lift_run(cam, depth, run, w)
                if r is None:
                    continue
                pts, rad = r
                out.append(dict(camera=cam.name, finish=kind, radius_mm=round(rad, 2),
                                points=np.round(pts, 1).tolist()))
        print(cam.name, sum(1 for o in out if o["camera"] == cam.name), "runs", flush=True)
    json.dump(dict(source="traced in the published 18:22 UTC stills by colour, lifted onto the model's depth "
                          "(front envelope), see cables.py", cables=out),
              open(os.path.join(OUT, "cables.json"), "w"))


if __name__ == "__main__":
    main()
