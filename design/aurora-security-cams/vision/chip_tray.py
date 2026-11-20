#!/usr/bin/env python3
"""Locate the chip tray in two glovebox stills, classify every pocket, and
cross-check the two views.

Usage:
    python chip_tray.py CAM0.jpg CAM1.jpg --out DIR \
        [--roi0 x0,y0,x1,y1] [--roi1 x0,y0,x1,y1]

Method
------
1. Segmentation (per camera, inside a generous ROI hint). The ROI is
   upsampled so morphology has room to work. The bright aluminium tray is the
   largest bright connected region (Otsu threshold); its filled outline is
   the tray mask. Inside it, a second Otsu threshold separates dark chips
   from aluminium, and compact dark blobs of a consistent size are chip
   candidates.
2. Pocket lattice. Nearest-neighbour displacements between blob centroids
   give the two lattice directions. A breadth-first walk from a central blob
   assigns integer (i, j) indices, then a RANSAC homography maps grid
   indices to image pixels. Blobs are re-indexed through the homography and
   the fit is repeated. The grid extent is the span of indexed blobs.
3. Rectification and classification. The homography warps each view to a
   top-down grid with a fixed number of pixels per pitch. The dark mask there
   uses a threshold between the typical pocket-centre and wall grey levels
   (thin walls in a low-resolution view otherwise bridge neighbouring
   chips). Each pocket is classified from that mask: dark fraction in the
   pocket centre, and
   for the dark blob in the pocket its centroid offset, minAreaRect angle,
   area relative to the median chip, and the share of it lying beyond the
   pocket walls.
       chip       dark, centred, square to the grid, normal size
       empty      bright (aluminium pocket floor)
       misplaced  dark but offset > 25 % of pitch, rotated > 10 deg,
                  size anomalous, or more than 25 % beyond the walls
       unsure     partly dark without a clear anomaly (glare, occlusion)
   Chip-like dark blobs on the tray but off the lattice are listed too.
4. Canonical tray frame, from tray features only. Rows run along the long
   axis, columns along the short axis. Row 0 is the short edge that carries
   the handwriting, found as the end strip with the most thin dark strokes
   (black-hat filter, with long straight rib shadows along the long axis
   removed). Columns are numbered so the frame has the same handedness in
   both images: the Amcrest cameras are not mirrored (Mirror=false) and both
   look down on the tray, so with row 0 at the top, column 0 is on the left
   as seen from above.
5. Cross-view check. In the canonical frame, pocket states from the two
   views are compared pocket by pocket. A misplacement counts as
   corroborated only when both views flag it. Separately, all 8 dihedral
   alignments of the raw index grids are scored by occupancy agreement, and
   the best one is compared with the feature-based mapping.

Limitations: a homography over a small tray ignores lens distortion and
the chip/wall height difference; a pocket row or column that is entirely
empty at the grid edge would not be found (the extent comes from chips).
"""

import argparse
import json
import os
from collections import deque

import cv2
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

UPSAMPLE = 3
PX_PER_PITCH = 48          # rectified grid resolution
STATE_BGR = {
    "chip": (40, 190, 40),
    "empty": (150, 150, 150),
    "misplaced": (40, 40, 230),
    "unsure": (0, 215, 255),
}
SYMBOL = {"chip": "C", "empty": ".", "misplaced": "M", "unsure": "?"}
OFFSET_MAX = 0.25          # pitch
ANGLE_MAX = 10.0           # degrees
AREA_RANGE = (0.6, 1.5)    # relative to median chip
OUTSIDE_MAX = 0.25         # share of blob beyond the pocket walls


# --------------------------------------------------------------------------
# 1. Segmentation
# --------------------------------------------------------------------------
def segment(img, roi, up=UPSAMPLE):
    """Return tray mask, dark mask (both in upsampled ROI pixels) and blobs."""
    x0, y0, x1, y1 = roi
    crop = img[y0:y1, x0:x1]
    big = cv2.resize(crop, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), (0, 0), 0.6 * up)

    t_bright, bright = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    tray = np.uint8(lab == biggest) * 255
    contours, _ = cv2.findContours(tray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    tray_filled = np.zeros_like(tray)
    cv2.drawContours(tray_filled, contours, -1, 255, -1)

    inside = gray[tray_filled > 0]
    t_dark, _ = cv2.threshold(inside.reshape(-1, 1), 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    core = cv2.erode(tray_filled, np.ones((2 * up + 1, 2 * up + 1), np.uint8))
    dark = np.uint8((gray < t_dark) & (core > 0)) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (up + 1, up + 1)))

    n, lab, stats, cents = cv2.connectedComponentsWithStats(dark, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA].astype(float)
    big_enough = areas > (4 * up) ** 2
    ref = np.median(areas[big_enough]) if big_enough.any() else 0
    blobs = []
    for k in range(1, n):
        a = stats[k, cv2.CC_STAT_AREA]
        if not (0.3 * ref < a < 2.5 * ref):
            continue
        cnt, _ = cv2.findContours(np.uint8(lab == k), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        hull_area = cv2.contourArea(cv2.convexHull(cnt[0]))
        if hull_area <= 0 or a / hull_area < 0.7:
            continue
        cx, cy = cents[k]
        blobs.append((x0 + cx / up, y0 + cy / up))
    return {
        "gray_up": gray, "tray_up": tray_filled, "dark_up": dark,
        "t_bright": float(t_bright), "t_dark": float(t_dark),
        "blobs": np.array(blobs, float), "ref_area_native": ref / up ** 2,
    }


# --------------------------------------------------------------------------
# 2. Pocket lattice
# --------------------------------------------------------------------------
def lattice_directions(pts):
    """Two dominant nearest-neighbour displacement vectors."""
    tree = cKDTree(pts)
    d, idx = tree.query(pts, k=5)
    nn = float(np.median(d[:, 1]))
    vecs = np.array([pts[idx[a, k]] - pts[a] for a in range(len(pts)) for k in range(1, 5)])
    vecs = vecs[np.linalg.norm(vecs, axis=1) < 1.45 * nn]
    ang = np.degrees(np.arctan2(vecs[:, 1], vecs[:, 0])) % 180
    hist = np.histogram(ang, bins=60, range=(0, 180))[0].astype(float)
    hist = np.convolve(np.r_[hist[-2:], hist, hist[:2]], np.ones(5) / 5, "valid")
    p1 = int(np.argmax(hist))
    circ = np.minimum(np.abs(np.arange(60) - p1), 60 - np.abs(np.arange(60) - p1))
    p2 = int(np.argmax(np.where(circ > 10, hist, -1)))
    basis = []
    for p in (p1, p2):
        centre = (p + 0.5) * 3.0
        diff = (ang - centre + 90) % 180 - 90
        sel = vecs[np.abs(diff) < 12]
        unit = np.array([np.cos(np.radians(centre)), np.sin(np.radians(centre))])
        sel = np.where((sel @ unit)[:, None] < 0, -sel, sel)
        basis.append(np.median(sel, axis=0))
    return np.array(basis), nn


def walk_indices(pts, basis, nn):
    """Breadth-first walk assigning integer indices, local basis updated per step."""
    tree = cKDTree(pts)
    seed = int(np.argmin(np.linalg.norm(pts - np.median(pts, axis=0), axis=1)))
    index = {seed: (0, 0)}
    local = {seed: basis.copy()}
    queue = deque([seed])
    while queue:
        p = queue.popleft()
        i, j = index[p]
        for axis in (0, 1):
            for sign in (1, -1):
                pred = pts[p] + sign * local[p][axis]
                dist, q = tree.query(pred)
                if dist < 0.35 * nn and q not in index:
                    index[q] = (i + sign * (axis == 0), j + sign * (axis == 1))
                    b = local[p].copy()
                    b[axis] = sign * (pts[q] - pts[p])
                    local[q] = b
                    queue.append(q)
    return index


def apply_h(H, pts):
    pts = np.asarray(pts, float).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)


def fit_lattice(pts):
    basis, nn = lattice_directions(pts)
    index = walk_indices(pts, basis, nn)
    ids = sorted(index)
    src = np.array([index[k] for k in ids], float)
    dst = pts[ids]
    H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 0.15 * nn)
    for _ in range(3):
        g = apply_h(np.linalg.inv(H), pts)
        r = np.round(g)
        resid = np.linalg.norm(g - r, axis=1)
        best = {}
        for k in np.where(resid < 0.3)[0]:
            key = (int(r[k, 0]), int(r[k, 1]))
            if key not in best or resid[k] < resid[best[key]]:
                best[key] = k
        keys = sorted(best)
        src = np.array(keys, float)
        dst = pts[[best[k] for k in keys]]
        H, _ = cv2.findHomography(src, dst, 0)
    # shift indices so the grid starts at (0, 0)
    lo = src.min(axis=0)
    shape = tuple(int(v) for v in (src.max(axis=0) - lo + 1))
    shift = np.array([[1, 0, lo[0]], [0, 1, lo[1]], [0, 0, 1]], float)
    H = H @ shift
    resid_px = np.linalg.norm(apply_h(H, src - lo) - dst, axis=1)
    return H, shape, nn, float(np.median(resid_px)), float(resid_px.max()), len(keys)


# --------------------------------------------------------------------------
# 3. Rectification and per-pocket classification
# --------------------------------------------------------------------------
def grid_to_canvas(margin, s=PX_PER_PITCH):
    """Affine taking canvas pixels to grid coordinates (pocket centres at integers)."""
    return np.array([[1 / s, 0, -margin + 0.5 / s - 0.5],
                     [0, 1 / s, -margin + 0.5 / s - 0.5],
                     [0, 0, 1]], float)


def rectify(img, H, shape, margin, s=PX_PER_PITCH, interp=cv2.INTER_CUBIC):
    """Top-down canvas, axis 0 of the grid along x, axis 1 along y."""
    A = grid_to_canvas(margin, s)
    w = int(round((shape[0] + 2 * margin) * s))
    h = int(round((shape[1] + 2 * margin) * s))
    return cv2.warpPerspective(img, H @ A, (w, h), flags=interp | cv2.WARP_INVERSE_MAP,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def cell_px(i, j, margin, s=PX_PER_PITCH):
    """Canvas pixel box of pocket (i, j): x0, y0, x1, y1."""
    return (int(round((i + margin) * s)), int(round((j + margin) * s)),
            int(round((i + margin + 1) * s)), int(round((j + margin + 1) * s)))


def dark_threshold(gray_r, shape, margin, t_seg, s=PX_PER_PITCH):
    """Threshold between typical pocket-centre and wall-line grey levels.

    Thin walls (cam1 pitch is about 14 px) blur towards the chip grey level,
    so the Otsu threshold from segmentation can bridge neighbouring chips.
    """
    centres = []
    for i in range(shape[0]):
        for j in range(shape[1]):
            x0, y0, x1, y1 = cell_px(i, j, margin, s)
            m = int(0.3 * s)
            centres.append(np.median(gray_r[y0 + m:y1 - m, x0 + m:x1 - m]))
    walls = []
    y0, y1 = int(margin * s), int((margin + shape[1]) * s)
    for i in range(1, shape[0]):
        x = int((i + margin) * s)
        walls.append(gray_r[y0:y1, x - 1:x + 2].max(axis=1))
    chip_level, wall_level = float(np.median(centres)), float(np.median(np.concatenate(walls)))
    return min(t_seg, chip_level + 0.45 * (wall_level - chip_level)), chip_level, wall_level


def blob_features(comp, x0, y0, x1, y1, s):
    ys, xs = np.nonzero(comp)
    area = float(len(xs))
    cx, cy = xs.mean(), ys.mean()
    pad = int(0.1 * s)
    in_cell = ((xs >= x0 - pad) & (xs < x1 + pad) & (ys >= y0 - pad) & (ys < y1 + pad)).sum()
    (_, _), (_, _), ang = cv2.minAreaRect(np.c_[xs, ys].astype(np.float32))
    return {
        "area_px": area,
        "offset_pitch": [round((cx - (x0 + x1) / 2) / s, 3), round((cy - (y0 + y1) / 2) / s, 3)],
        "angle_deg": round(float((ang + 45) % 90 - 45), 1),
        "outside_frac": round(1 - float(in_cell) / area, 3),
    }


def classify(gray_r, tray_r, shape, margin, t_seg, s=PX_PER_PITCH):
    t_dark, chip_level, wall_level = dark_threshold(gray_r, shape, margin, t_seg, s)
    dark = np.uint8((gray_r < t_dark) & (tray_r > 0)) * 255
    k_open = int(0.15 * s) | 1
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_open, k_open)))
    n, lab, stats, cents = cv2.connectedComponentsWithStats(dark, connectivity=8)
    cells = {}
    for i in range(shape[0]):
        for j in range(shape[1]):
            x0, y0, x1, y1 = cell_px(i, j, margin, s)
            m = int(0.2 * s)
            inner = dark[y0 + m:y1 - m, x0 + m:x1 - m]
            frac = float((inner > 0).mean())
            sub = lab[y0:y1, x0:x1]
            ks, counts = np.unique(sub[sub > 0], return_counts=True)
            rec = {"dark_frac": round(frac, 3)}
            if len(ks):
                k = int(ks[np.argmax(counts)])
                rec.update({"blob": k, "cell_overlap": round(float(counts.max()) / (s * s), 3)})
                rec.update(blob_features(lab == k, x0, y0, x1, y1, s))
            cells[(i, j)] = rec
    owner = {}
    for key, c in cells.items():
        if "blob" in c:
            owner.setdefault(c["blob"], []).append(key)
    # A blob shared by pockets whose centres are all fully dark is two chips
    # joined across an unresolved wall: measure each pocket's own part.
    for blob, keys in owner.items():
        if len(keys) > 1 and all(cells[k]["dark_frac"] >= 0.85 for k in keys):
            for (i, j) in keys:
                x0, y0, x1, y1 = cell_px(i, j, margin, s)
                pad = int(0.1 * s)
                clip = np.zeros(lab.shape, bool)
                clip[y0 - pad:y1 + pad, x0 - pad:x1 + pad] = lab[y0 - pad:y1 + pad, x0 - pad:x1 + pad] == blob
                cells[(i, j)].update(blob_features(clip, x0, y0, x1, y1, s))
                cells[(i, j)]["blob"] = f"{blob}:{i},{j}"
                cells[(i, j)]["note"] = "joined to a neighbour across an unresolved wall"

    # reference chip area: median blob area over clearly occupied pockets
    good = [c["area_px"] for c in cells.values() if c["dark_frac"] > 0.6 and "area_px" in c]
    ref = float(np.median(good)) if good else float(s * s * 0.6)
    owner = {}
    for key, c in cells.items():
        if "blob" in c:
            owner.setdefault(c["blob"], []).append(key)
    levels = {"dark_threshold": round(t_dark, 1), "chip_level": chip_level, "wall_level": wall_level}
    for key, c in cells.items():
        reasons = []
        if c["dark_frac"] < 0.15 and c.get("cell_overlap", 0) < 0.15:
            c["state"] = "empty"
        else:
            if "blob" not in c:
                c["state"] = "unsure"
                c["reasons"] = ["dark pixels but no blob"]
                continue
            off = float(np.hypot(*c["offset_pitch"]))
            rel = c["area_px"] / ref
            c["area_rel"] = round(rel, 2)
            c["offset_abs"] = round(off, 3)
            if len(owner[c["blob"]]) > 1:
                reasons.append(f"blob spans pockets {sorted(owner[c['blob']])}")
            if off > OFFSET_MAX:
                reasons.append(f"offset {off:.2f} pitch")
            if abs(c["angle_deg"]) > ANGLE_MAX:
                reasons.append(f"rotated {abs(c['angle_deg']):.1f} deg")
            if not AREA_RANGE[0] <= rel <= AREA_RANGE[1]:
                reasons.append(f"area {rel:.2f}x median")
            if c["outside_frac"] > OUTSIDE_MAX:
                reasons.append(f"{c['outside_frac']:.0%} beyond walls")
            if reasons:
                c["state"] = "misplaced"
            elif c["dark_frac"] >= 0.6:
                c["state"] = "chip"
            else:
                c["state"] = "unsure"
                reasons.append(f"dark fraction {c['dark_frac']:.2f}")
        c["reasons"] = reasons

    # chip-like dark blobs on the tray but off the lattice
    off_lattice = []
    for k in range(1, n):
        cx, cy = cents[k]
        gx, gy = cx / s - margin - 0.5, cy / s - margin - 0.5
        if -0.6 < gx < shape[0] - 0.4 and -0.6 < gy < shape[1] - 0.4:
            continue
        a = stats[k, cv2.CC_STAT_AREA]
        if not 0.4 * ref < a < 2.0 * ref:
            continue
        cnt, _ = cv2.findContours(np.uint8(lab == k), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        hull = cv2.contourArea(cv2.convexHull(cnt[0]))
        if hull <= 0 or a / hull < 0.8:
            continue
        off_lattice.append({"grid_xy": [round(gx, 2), round(gy, 2)], "area_rel": round(a / ref, 2)})
    return cells, dark, ref, off_lattice, levels


# --------------------------------------------------------------------------
# 4. Canonical tray frame from the handwriting edge
# --------------------------------------------------------------------------
def edge_scores(gray_r, tray_r, shape, margin, s=PX_PER_PITCH):
    """Thin-dark-stroke density just outside each grid side (canvas coords)."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.3 * s) | 1,) * 2)
    bh = cv2.morphologyEx(gray_r, cv2.MORPH_BLACKHAT, k).astype(np.float32)
    valid = cv2.erode(tray_r, np.ones((int(0.15 * s),) * 2, np.uint8)) > 0
    # remove long straight strokes along either grid axis (rib shadows, tray edges)
    lx = cv2.morphologyEx(bh, cv2.MORPH_OPEN, np.ones((1, int(0.7 * s)), np.uint8))
    ly = cv2.morphologyEx(bh, cv2.MORPH_OPEN, np.ones((int(0.7 * s), 1), np.uint8))
    ink = np.clip(bh - np.maximum(lx, ly), 0, None)

    def strip(a0, a1, b0, b1):
        # a along canvas x (grid axis 0), b along canvas y (grid axis 1), in grid units
        X0, X1 = int((a0 + margin + 0.5) * s), int((a1 + margin + 0.5) * s)
        Y0, Y1 = int((b0 + margin + 0.5) * s), int((b1 + margin + 0.5) * s)
        v = valid[Y0:Y1, X0:X1]
        if v.sum() < 0.3 * v.size:
            return 0.0
        return float(ink[Y0:Y1, X0:X1][v].mean())

    n0, n1 = shape
    return {
        "axis0_low": strip(-1.4, -0.65, 0, n1 - 1),
        "axis0_high": strip(n0 - 0.35, n0 + 0.4, 0, n1 - 1),
        "axis1_low": strip(0, n0 - 1, -1.4, -0.65),
        "axis1_high": strip(0, n0 - 1, n1 - 0.35, n1 + 0.4),
    }, ink


def canonical_transform(H, shape, scores):
    """3x3 affine D taking canonical (c, r) to raw grid (i, j), plus a description."""
    n0, n1 = shape
    if n0 != n1:
        long_axis = 0 if n0 > n1 else 1
    else:  # square grid: rows run away from whichever edge carries the handwriting
        long_axis = int(max(scores["axis1_low"], scores["axis1_high"]) >
                        max(scores["axis0_low"], scores["axis0_high"]))
    n_r, n_c = (n0, n1) if long_axis == 0 else (n1, n0)
    lo, hi = scores[f"axis{long_axis}_low"], scores[f"axis{long_axis}_high"]
    hand_high = hi > lo
    # raw index along long / short axis from canonical (c, r)
    # r_raw = r or n_r-1-r ; c_raw = c or n_c-1-c
    def build(flip_c):
        M = np.zeros((3, 3))
        M[2, 2] = 1
        r_row, c_row = (0, 1) if long_axis == 0 else (1, 0)
        if hand_high:
            M[r_row, 1], M[r_row, 2] = -1, n_r - 1
        else:
            M[r_row, 1] = 1
        if flip_c:
            M[c_row, 0], M[c_row, 2] = -1, n_c - 1
        else:
            M[c_row, 0] = 1
        return M
    D = build(False)
    centre = np.array([(n_c - 1) / 2, (n_r - 1) / 2])
    pts = np.array([centre, centre + [1, 0], centre + [0, 1]])
    raw = (D @ np.c_[pts, np.ones(3)].T).T[:, :2]
    img = apply_h(H, raw)
    e_c, e_r = img[1] - img[0], img[2] - img[0]
    if e_c[0] * e_r[1] - e_c[1] * e_r[0] < 0:   # make handedness match a top view
        D = build(True)
    return D, (n_c, n_r), {
        "long_axis": f"axis{long_axis}", "handwriting_end": "high" if hand_high else "low",
        "handwriting_score_ratio": round(max(lo, hi) / max(min(lo, hi), 1e-6), 2),
        "handwriting_end_confident": bool(max(lo, hi) >= 1.3 * min(lo, hi)),
    }


def describe(D, names=("c", "r"), outs=("i", "j")):
    """Text form of out = D @ in, for a signed axis permutation D."""
    terms = []
    for row, out in zip(D[:2], outs):
        k = int(np.argmax(np.abs(row[:2])))
        const, var = int(round(row[2])), names[k]
        if row[k] > 0:
            rhs = f"{const} + {var}" if const else var
        else:
            rhs = f"{const} - {var}" if const else f"-{var}"
        terms.append(f"{out} = {rhs}")
    return ", ".join(terms)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------
def draw_overlay(img, H, shape, cells, roi_pad=1.9, scale=3):
    n0, n1 = shape
    corners = apply_h(H, [[-roi_pad, -roi_pad], [n0 - 1 + roi_pad, -roi_pad],
                          [n0 - 1 + roi_pad, n1 - 1 + roi_pad], [-roi_pad, n1 - 1 + roi_pad]])
    x0, y0 = np.floor(corners.min(axis=0)).astype(int)
    x1, y1 = np.ceil(corners.max(axis=0)).astype(int)
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, img.shape[1]), min(y1, img.shape[0])
    crop = cv2.resize(img[y0:y1, x0:x1], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    def to_crop(p):
        return ((np.asarray(p) - [x0, y0]) * scale).astype(np.int32)

    for i in range(n0 + 1):
        line = apply_h(H, [[i - 0.5, -0.5], [i - 0.5, n1 - 0.5]])
        cv2.line(crop, *map(tuple, to_crop(line)), (255, 200, 0), 1, cv2.LINE_AA)
    for j in range(n1 + 1):
        line = apply_h(H, [[-0.5, j - 0.5], [n0 - 0.5, j - 0.5]])
        cv2.line(crop, *map(tuple, to_crop(line)), (255, 200, 0), 1, cv2.LINE_AA)
    for (i, j), c in cells.items():
        q = apply_h(H, [[i - 0.32, j - 0.32], [i + 0.32, j - 0.32], [i + 0.32, j + 0.32], [i - 0.32, j + 0.32]])
        cv2.polylines(crop, [to_crop(q)], True, STATE_BGR[c["state"]], 2, cv2.LINE_AA)
    return crop, (int(x0), int(y0), int(x1), int(y1))


def put_label(im, text, org, scale=0.5):
    cv2.putText(im, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(im, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


def draw_canonical(img, H, D, canon_shape, cells_canon, margin=1.5, s=PX_PER_PITCH):
    n_c, n_r = canon_shape
    rect = rectify(img, H @ D, (n_c, n_r), margin, s)
    for (c, r), st in cells_canon.items():
        x0, y0, x1, y1 = cell_px(c, r, margin, s)
        cv2.rectangle(rect, (x0 + 4, y0 + 4), (x1 - 4, y1 - 4), STATE_BGR[st], 2)
    for c in range(n_c):
        x = int((c + margin + 0.5) * s)
        put_label(rect, f"c{c}", (x - 9, int(margin * s) - 6))
    for r in range(n_r):
        y = int((r + margin + 0.5) * s)
        put_label(rect, f"r{r}", (int(margin * s) - 28, y + 5))
    return rect


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def analyse(path, roi, margin=1.5):
    img = cv2.imread(path)
    if img is None:
        raise SystemExit(f"cannot read {path}")
    seg = segment(img, roi)
    if len(seg["blobs"]) < 8:
        raise SystemExit(f"{path}: only {len(seg['blobs'])} chip-like blobs in ROI {roi}")
    H, shape, nn, med_res, max_res, n_fit = fit_lattice(seg["blobs"])

    # tray mask in full-frame coordinates, for rectification
    x0, y0, x1, y1 = roi
    tray_full = np.zeros(img.shape[:2], np.uint8)
    tray_full[y0:y1, x0:x1] = cv2.resize(seg["tray_up"], (x1 - x0, y1 - y0),
                                         interpolation=cv2.INTER_NEAREST)
    gray_full = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray_r = cv2.GaussianBlur(rectify(gray_full, H, shape, margin), (0, 0), 1.0)
    tray_r = rectify(tray_full, H, shape, margin, interp=cv2.INTER_NEAREST)
    cells, dark_r, ref, off_lattice, levels = classify(gray_r, tray_r, shape, margin, seg["t_dark"])
    scores, ink = edge_scores(gray_r, tray_r, shape, margin)
    D, canon_shape, frame = canonical_transform(H, shape, scores)
    steps = [float(np.linalg.norm(np.diff(apply_h(H, [[a, b], [a + da, b + db]]), axis=0)))
             for a in range(shape[0] - 1) for b in range(shape[1] - 1)
             for da, db in ((1, 0), (0, 1))]
    pitch_px = float(np.mean(steps))
    pitch_range = (float(np.min(steps)), float(np.max(steps)))
    return {
        "img": img, "seg": seg, "H": H, "shape": shape, "nn": nn,
        "fit_median_resid_px": med_res, "fit_max_resid_px": max_res, "n_fit": n_fit,
        "cells": cells, "ref_area": ref, "off_lattice": off_lattice, "levels": levels,
        "edge_scores": scores, "D": D, "canon_shape": canon_shape, "frame": frame,
        "pitch_px": pitch_px, "pitch_range": pitch_range,
        "gray_r": gray_r, "dark_r": dark_r, "ink": ink, "margin": margin,
    }


def to_canonical(view):
    """Map raw cells to canonical (c, r) keys."""
    D = view["D"]
    n_c, n_r = view["canon_shape"]
    out = {}
    for c in range(n_c):
        for r in range(n_r):
            i, j = (D @ [c, r, 1])[:2].round().astype(int)
            out[(c, r)] = (int(i), int(j))
    return out


def canonical_geometry(cell, D):
    """Blob offset (pitch) and angle (deg) expressed in the canonical (c, r) frame."""
    if "offset_pitch" not in cell:
        return {}
    lin = D[:2, :2]
    dc, dr = np.linalg.inv(lin) @ np.array(cell["offset_pitch"])
    return {"offset_cr_pitch": [round(float(dc), 3), round(float(dr), 3)],
            "angle_deg_canonical": round(float(cell["angle_deg"] * np.sign(np.linalg.det(lin))), 1),
            "area_rel": cell.get("area_rel"), "outside_frac": cell.get("outside_frac")}


def occupancy(state):
    return {"chip": 1, "misplaced": 1, "empty": 0}.get(state)


def dihedral_check(v0, v1):
    """Best of 8 dihedral alignments of cam1's raw grid onto cam0's, by occupancy."""
    def grid(v):
        a = np.full(v["shape"], np.nan)
        for (i, j), c in v["cells"].items():
            o = occupancy(c["state"])
            a[i, j] = np.nan if o is None else o
        return a
    g0, g1 = grid(v0), grid(v1)
    ids1 = np.arange(g1.size).reshape(g1.shape)
    results = []
    for k in range(4):
        for flip in (False, True):
            t = np.rot90(np.fliplr(g1) if flip else g1, k)
            tid = np.rot90(np.fliplr(ids1) if flip else ids1, k)
            name = f"rot90 x{k}" + (" after left-right flip" if flip else "")
            if t.shape != g0.shape:
                results.append({"transform": name, "possible": False})
                continue
            both = ~np.isnan(t) & ~np.isnan(g0)
            agree = int((t[both] == g0[both]).sum())
            results.append({"transform": name, "possible": True, "agree": agree,
                            "compared": int(both.sum()), "ids": tid})
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cam0")
    ap.add_argument("cam1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--roi0", default="700,760,1060,1080", help="x0,y0,x1,y1 in cam0")
    ap.add_argument("--roi1", default="430,350,720,600", help="x0,y0,x1,y1 in cam1")
    ap.add_argument("--debug", help="scratch directory for diagnostic masks (keep out of the repo)")
    args = ap.parse_args()
    rois = [tuple(int(v) for v in r.split(",")) for r in (args.roi0, args.roi1)]
    os.makedirs(args.out, exist_ok=True)

    views = [analyse(p, r) for p, r in zip((args.cam0, args.cam1), rois)]
    canon_maps = [to_canonical(v) for v in views]
    if views[0]["canon_shape"] != views[1]["canon_shape"]:
        print("WARNING: grid sizes differ between views:",
              views[0]["canon_shape"], views[1]["canon_shape"])
    n_c, n_r = views[0]["canon_shape"]

    pockets, agree_state, agree_occ, compared_occ = [], 0, 0, 0
    flagged = []
    for r in range(n_r):
        for c in range(n_c):
            rec = {"col": c, "row": r}
            states = []
            for k, v in enumerate(views):
                raw = canon_maps[k].get((c, r))
                cell = v["cells"].get(raw) if raw else None
                st = cell["state"] if cell else "unsure"
                states.append(st)
                rec[f"cam{k}"] = {"raw_ij": list(raw) if raw else None, "state": st,
                                  **({"reasons": cell["reasons"]} if cell and cell.get("reasons") else {}),
                                  **({"dark_frac": cell["dark_frac"]} if cell else {}),
                                  **(canonical_geometry(cell, v["D"]) if cell else {})}
            rec["agree"] = states[0] == states[1]
            agree_state += rec["agree"]
            o = [occupancy(s) for s in states]
            if None not in o:
                compared_occ += 1
                agree_occ += o[0] == o[1]
            rec["corroborated_misplaced"] = states == ["misplaced", "misplaced"]
            pockets.append(rec)
            if any(s in ("misplaced", "unsure") for s in states) or not rec["agree"]:
                flagged.append(rec)

    checks = dihedral_check(*views)
    possible = [c for c in checks if c["possible"]]
    best = max(possible, key=lambda c: c["agree"]) if possible else None
    # feature-based mapping expressed on cam0's raw grid as cam1 raw ids
    feat_ids = np.full(views[0]["shape"], -1)
    n1 = views[1]["shape"][1]
    for (c, r), (i0, j0) in canon_maps[0].items():
        i1, j1 = canon_maps[1][(c, r)]
        feat_ids[i0, j0] = i1 * n1 + j1
    for c in possible:
        c["matches_feature_mapping"] = bool(np.array_equal(c["ids"], feat_ids))
    feat_entry = next((c for c in possible if c["matches_feature_mapping"]), None)

    summary = {}
    for k, v in enumerate(views):
        counts = {s: sum(c["state"] == s for c in v["cells"].values()) for s in STATE_BGR}
        summary[f"cam{k}"] = counts

    result = {
        "inputs": {"cam0": os.path.basename(args.cam0), "cam1": os.path.basename(args.cam1),
                   "roi0": rois[0], "roi1": rois[1]},
        "grid": {"columns": n_c, "rows": n_r, "pockets": n_c * n_r,
                 "frame": "row 0 = handwriting edge; with row 0 at the top, column 0 is on the "
                          "left as seen from above",
                 "symbols": SYMBOL},
        "views": {
            f"cam{k}": {
                "raw_grid_shape_ij": list(v["shape"]),
                "pitch_px_mean": round(v["pitch_px"], 2),
                "pitch_px_min_max": [round(x, 2) for x in v["pitch_range"]],
                "homography_grid_ij_to_image": np.round(v["H"] / v["H"][2, 2], 6).tolist(),
                "fit_blobs": v["n_fit"],
                "fit_median_resid_px": round(v["fit_median_resid_px"], 2),
                "fit_max_resid_px": round(v["fit_max_resid_px"], 2),
                "grey_levels_rectified": v["levels"],
                "edge_ink_scores": {k2: round(s, 3) for k2, s in v["edge_scores"].items()},
                "canonical_frame": v["frame"],
                "raw_from_canonical": describe(v["D"]),
                "counts": summary[f"cam{k}"],
                "canonical_grid": [" ".join(SYMBOL[v["cells"][canon_maps[k][(c, r)]]["state"]]
                                            for c in range(n_c)) for r in range(n_r)],
                "off_lattice_blobs": v["off_lattice"],
            } for k, v in enumerate(views)},
        "mapping_cam0_to_cam1": {
            "method": "both views put in the canonical frame from tray features only "
                      "(handwriting edge, long axis, top-view handedness); occupancy not used",
            "cam0_raw_from_canonical": describe(views[0]["D"]),
            "cam1_raw_from_canonical": describe(views[1]["D"]),
            "cam1_raw_from_cam0_raw": describe(views[1]["D"] @ np.linalg.inv(views[0]["D"]),
                                               ("i0", "j0"), ("i1", "j1")),
        },
        "agreement": {
            "state_agree": agree_state, "state_disagree": n_c * n_r - agree_state,
            "occupancy_agree": agree_occ, "occupancy_compared": compared_occ,
            "corroborated_misplaced": [[p["col"], p["row"]] for p in pockets if p["corroborated_misplaced"]],
        },
        "dihedral_sanity_check": {
            "note": "occupancy only; transforms act on cam1's raw (i, j) occupancy array "
                    "(np.fliplr, then np.rot90) to match cam0's; unsure pockets are skipped",
            "alignments": [{k: v for k, v in c.items() if k != "ids"} for c in checks],
            "best_by_occupancy": best["transform"] if best else None,
            "best_is_unique": bool(best and sum(c["agree"] == best["agree"] for c in possible) == 1),
            "feature_mapping_is": feat_entry["transform"] if feat_entry else None,
            "best_equals_feature_mapping": bool(best and best.get("matches_feature_mapping")),
        },
        "flagged": flagged,
        "pockets": pockets,
    }
    with open(os.path.join(args.out, "chip_tray.json"), "w") as f:
        json.dump(result, f, indent=1)

    # figure: per camera, overlay crop + canonical top-down grid
    panels = []
    for k, v in enumerate(views):
        overlay, box = draw_overlay(v["img"], v["H"], v["shape"], v["cells"])
        canon_states = {(c, r): v["cells"][canon_maps[k][(c, r)]]["state"]
                        for (c, r) in canon_maps[k]}
        canon = draw_canonical(v["img"], v["H"], v["D"], v["canon_shape"], canon_states)
        panels.append((overlay, canon, box))
    H_target = 640
    v_pitch = [v["pitch_px"] for v in views]
    rows = []
    for k, (overlay, canon, box) in enumerate(panels):
        a = cv2.resize(overlay, (int(overlay.shape[1] * H_target / overlay.shape[0]), H_target),
                       interpolation=cv2.INTER_AREA)
        b = cv2.resize(canon, (int(canon.shape[1] * H_target / canon.shape[0]), H_target),
                       interpolation=cv2.INTER_AREA)
        c = summary[f"cam{k}"]
        lines = [f"cam{k}: tray crop x {box[0]}-{box[2]}, y {box[1]}-{box[3]} with fitted lattice"
                 f" (left); canonical top view, row 0 = handwriting edge (right)",
                 f"pitch {v_pitch[k]:.1f} px;  chip {c['chip']}, empty {c['empty']}, "
                 f"misplaced {c['misplaced']}, unsure {c['unsure']}"]
        bar = np.full((52, a.shape[1] + 12 + b.shape[1], 3), 255, np.uint8)
        for n_line, text in enumerate(lines):
            cv2.putText(bar, text, (8, 20 + 22 * n_line), cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                        (0, 0, 0), 1, cv2.LINE_AA)
        body = np.full((H_target, bar.shape[1], 3), 255, np.uint8)
        body[:, :a.shape[1]] = a
        body[:, a.shape[1] + 12:] = b
        rows.append(np.vstack([bar, body]))
    width = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 0), (0, width - r.shape[1]), (0, 0)), constant_values=255) for r in rows]
    legend = np.full((36, width, 3), 255, np.uint8)
    x = 8
    for name, col in STATE_BGR.items():
        cv2.rectangle(legend, (x, 10), (x + 18, 26), col, -1)
        cv2.putText(legend, name, (x + 24, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        x += 130
    ag = result["agreement"]
    cv2.putText(legend, f"views agree on {ag['state_agree']}/{n_c * n_r} pocket states, "
                        f"occupancy {ag['occupancy_agree']}/{ag['occupancy_compared']}",
                (x + 20, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    fig = np.vstack(rows + [legend])
    # A 256-colour palette keeps the PNG well under 1.5 MB; the verdict colours
    # are added to the palette explicitly so rare ones are not merged away.
    rgb = Image.fromarray(cv2.cvtColor(fig, cv2.COLOR_BGR2RGB))
    palette = rgb.quantize(colors=252, method=Image.Quantize.MEDIANCUT).getpalette()[:252 * 3]
    for b, g, r in STATE_BGR.values():
        palette += [r, g, b]
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette(palette)
    rgb.quantize(palette=pal_img, dither=Image.Dither.NONE).save(
        os.path.join(args.out, "chip_tray_views.png"), optimize=True)

    if args.debug:
        os.makedirs(args.debug, exist_ok=True)
        for k, v in enumerate(views):
            cv2.imwrite(os.path.join(args.debug, f"dark_r{k}.png"), v["dark_r"])
            cv2.imwrite(os.path.join(args.debug, f"gray_r{k}.png"), v["gray_r"])
            cv2.imwrite(os.path.join(args.debug, f"ink{k}.png"),
                        np.uint8(np.clip(v["ink"] * 4, 0, 255)))
            cv2.imwrite(os.path.join(args.debug, f"dark_up{k}.png"), v["seg"]["dark_up"])
            cv2.imwrite(os.path.join(args.debug, f"tray_up{k}.png"), v["seg"]["tray_up"])

    for k in (0, 1):
        vv = result["views"][f"cam{k}"]
        print(f"cam{k}: raw grid {vv['raw_grid_shape_ij']}, pitch {vv['pitch_px_mean']} px, "
              f"fit {vv['fit_blobs']} blobs, resid med {vv['fit_median_resid_px']} max "
              f"{vv['fit_max_resid_px']} px, counts {vv['counts']}, frame {vv['canonical_frame']}, "
              f"{vv['raw_from_canonical']}, ink {vv['edge_ink_scores']}, off-lattice {vv['off_lattice_blobs']}")
    print("agreement:", result["agreement"])
    print("dihedral:", result["dihedral_sanity_check"]["best_by_occupancy"],
          "feature:", result["dihedral_sanity_check"]["feature_mapping_is"],
          [(c["transform"], c.get("agree"), c.get("compared")) for c in checks])
    for p in flagged:
        print("flag", p["col"], p["row"], p["cam0"], p["cam1"])


if __name__ == "__main__":
    main()
