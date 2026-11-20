"""Focal length from the chip tray, used as a planar calibration target in each view.

chip_tray.py fits a homography from the tray's pocket grid (i, j) to image pixels
in each camera. This script maps the 10 x 6 pocket centres through it, removes
lens distortion with the division model in intrinsics.json, refits the
homography H on the undistorted points, and solves the focal length f with the
principal point at the frame centre, square pixels and no skew:

    orthogonality  h1' W h2 = 0              (holds for any pocket pitch, even unequal pitches)
    equal norms    h1' W h1 = h2' W h2       (assumes the same pitch along both axes)

with W = K^-T K^-1. The spread comes from re-solving with 0.5 px of noise added to
the pocket centres.

    python tray_focal.py out/chip_tray.json out/intrinsics.json
"""
import json
import sys

import cv2
import numpy as np


def undistort(p, c, l1, l2):
    q = (p - c) / 1000.0
    r2 = (q ** 2).sum(1, keepdims=True)
    return c + (p - c) / (1 + l1 * r2 + l2 * r2 ** 2)


def focal(H):
    h1, h2 = H[:, 0], H[:, 1]
    f_orth = -(h1[0] * h2[0] + h1[1] * h2[1]) / (h1[2] * h2[2])
    f_norm = -(h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2) / (h1[2] ** 2 - h2[2] ** 2)
    return [float(np.sqrt(v)) if v > 0 else float("nan") for v in (f_orth, f_norm)]


def main(tray_json, intr_json, noise_px=0.5, trials=300):
    tray, intr = json.load(open(tray_json)), json.load(open(intr_json))
    l1, l2 = intr["adopted"]["division"]
    c = np.array([intr["adopted"]["cx"], intr["adopted"]["cy"]])
    rng = np.random.default_rng(0)
    out = {}
    for cam, v in tray["views"].items():
        H0 = np.array(v["homography_grid_ij_to_image"])
        ni, nj = v["raw_grid_shape_ij"]
        ij = np.array([(i, j) for i in range(ni) for j in range(nj)], float)
        p = np.c_[ij, np.ones(len(ij))] @ H0.T
        p = p[:, :2] / p[:, 2:]
        row = {}
        for label, pts in (("distorted", p), ("undistorted", undistort(p, c, l1, l2))):
            H, _ = cv2.findHomography(ij, pts - c, 0)
            row[label] = dict(zip(("f_orth", "f_equal_norm"), focal(H / H[2, 2])))
        fs = []
        u = undistort(p, c, l1, l2)
        for _ in range(trials):
            H, _ = cv2.findHomography(ij, u - c + rng.normal(0, noise_px, u.shape), 0)
            fs.append(focal(H / H[2, 2]))
        fs = np.array(fs)
        row["noise_16_50_84"] = {k: [round(float(x)) for x in np.nanpercentile(fs[:, i], [16, 50, 84])]
                                 for i, k in enumerate(("f_orth", "f_equal_norm"))}
        out[cam] = row
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(*sys.argv[1:3])
