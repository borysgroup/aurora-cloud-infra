"""Plumb-line estimate of the division-model parameter (see lensmodel.py) from long straight edges.

Each edge is given by two approximate endpoints (plumb_lines.json, read off zoomed crops). Along the chord,
the strongest gradient across the chord is searched within +/-SEARCH px; a RANSAC quadratic in the chord
frame drops points that jumped to other edges. lam then minimises the RMS distance of the undistorted edge
points from their own best-fit straight lines (all edges of a camera together). Uncertainty: jackknife over
edges. The principal point is fixed at the frame centre.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from scipy.optimize import minimize_scalar

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lensmodel import undistort_px  # noqa: E402

SEARCH = 30
NS = 80


def edge_points(gray, a, b, search=SEARCH, ns=NS, rng=np.random.default_rng(0)):
    g = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 1.2)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    a, b = np.asarray(a, float), np.asarray(b, float)
    t_hat = (b - a) / np.linalg.norm(b - a)
    n_hat = np.array([-t_hat[1], t_hat[0]])
    L = np.linalg.norm(b - a)
    pts = []
    for t in np.linspace(0.03 * L, 0.97 * L, ns):
        offs = np.arange(-search, search + 0.5, 0.5)
        P = a + t * t_hat + offs[:, None] * n_hat
        mx = cv2.remap(gx, P[:, 0:1].astype(np.float32), P[:, 1:2].astype(np.float32), cv2.INTER_LINEAR).ravel()
        my = cv2.remap(gy, P[:, 0:1].astype(np.float32), P[:, 1:2].astype(np.float32), cv2.INTER_LINEAR).ravel()
        resp = np.abs(mx * n_hat[0] + my * n_hat[1])
        i = int(np.argmax(resp))
        if resp[i] < 20:
            continue
        pts.append((t, offs[i]))
    pts = np.array(pts)
    if len(pts) < 10:
        return np.zeros((0, 2))
    # RANSAC quadratic offset(t)
    best = None
    for _ in range(300):
        idx = rng.choice(len(pts), 3, replace=False)
        try:
            co = np.polyfit(pts[idx, 0], pts[idx, 1], 2)
        except Exception:
            continue
        inl = np.abs(np.polyval(co, pts[:, 0]) - pts[:, 1]) < 2.0
        if best is None or inl.sum() > best.sum():
            best = inl
    co = np.polyfit(pts[best, 0], pts[best, 1], 2)
    inl = np.abs(np.polyval(co, pts[:, 0]) - pts[:, 1]) < 2.0
    q = pts[inl]
    return a + q[:, :1] * t_hat + q[:, 1:2] * n_hat


def line_resid(P):
    m = P.mean(0)
    _, s, vt = np.linalg.svd(P - m, full_matrices=False)
    return (P - m) @ vt[1]


def cost(lam, lines, c):
    r = np.concatenate([line_resid(undistort_px(P, c, lam)) for P in lines])
    return float(np.sqrt(np.mean(r ** 2)))


def fit(lines, c):
    res = minimize_scalar(lambda l: cost(l, lines, c), bounds=(-0.9, 0.2), method="bounded",
                          options=dict(xatol=1e-5))
    return float(res.x), float(res.fun)


def fit2(lines_c):
    """Two-parameter division model on [(points, centre), ...]."""
    from scipy.optimize import minimize
    def f(l):
        r = np.concatenate([line_resid(undistort_px(P, c, l)) for P, c in lines_c])
        return float(np.mean(r ** 2))
    res = minimize(f, x0=[-0.4, 0.0], method="Nelder-Mead", options=dict(xatol=1e-6, fatol=1e-10, maxiter=4000))
    return res.x.tolist(), float(np.sqrt(res.fun))


def usable(P, c):
    """A line constrains the distortion if it is well snapped and not radial."""
    lam1, _ = fit([P], c)
    r_own = np.sqrt(np.mean(line_resid(undistort_px(P, c, lam1)) ** 2))
    return (-0.85 < lam1 < 0.15) and r_own < 1.5, lam1, float(r_own)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "plumb_lines.json"))
    ap.add_argument("--raw", default="/tmp/aurora-vision/raw")
    ap.add_argument("--out", default=None)
    ap.add_argument("--debug", default=None, help="directory for debug overlays (full frames; not for the repo)")
    a = ap.parse_args()
    spec = json.load(open(a.lines))
    out = {}
    all_lines = []
    for cam, segs in spec.items():
        if cam.startswith("_"):
            continue
        img = cv2.imread(os.path.join(a.raw, f"{cam}.jpg"))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        c = np.array([(gray.shape[1] - 1) / 2, (gray.shape[0] - 1) / 2])
        lines, names, rejected = [], [], {}
        for s in segs:
            P = edge_points(gray, s["a"], s["b"])
            ok, l_own, r_own = usable(P, c) if len(P) >= 15 else (False, None, None)
            if ok:
                lines.append(P)
                names.append(s["name"])
            else:
                rejected[s["name"]] = dict(n=len(P), lam_single=l_own, rms_own=r_own)
            print(cam, s["name"], "points", len(P), "raw rms", round(float(np.sqrt(np.mean(line_resid(P) ** 2))), 2)
                  if len(P) else "")
        lam, rms = fit(lines, c)
        jk = [fit(lines[:i] + lines[i + 1:], c)[0] for i in range(len(lines))]
        n = len(jk)
        se = float(np.sqrt((n - 1) / n * np.sum((np.array(jk) - np.mean(jk)) ** 2)))
        per = {nm: dict(n=len(P), rms_raw=float(np.sqrt(np.mean(line_resid(P) ** 2))),
                        rms_corrected=float(np.sqrt(np.mean(line_resid(undistort_px(P, c, lam)) ** 2))),
                        lam_single=fit([P], c)[0])
               for nm, P in zip(names, lines)}
        out[cam] = dict(lam=lam, lam_se_jackknife=se, rms_px=rms, rms_px_lam0=cost(0.0, lines, c), lines=per,
                        rejected=rejected, centre=c.tolist(), two_param=fit2([(P, c) for P in lines]))
        all_lines += [(cam, P, c) for P in lines]
        print(cam, "lam", round(lam, 4), "+/-", round(se, 4), "rms", round(rms, 3), "(lam=0:",
              round(cost(0.0, lines, c), 2), ")")
        if a.debug:
            dbg = img.copy()
            for P in lines:
                for p in P:
                    cv2.circle(dbg, tuple(int(v) for v in p), 2, (0, 0, 255), -1)
            for s in segs:
                cv2.line(dbg, tuple(map(int, s["a"])), tuple(map(int, s["b"])), (0, 255, 0), 1)
                cv2.putText(dbg, s["name"], tuple(map(int, s["a"])), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.imwrite(os.path.join(a.debug, f"plumb_{cam}.jpg"), dbg)
    # joint fit (same lens model for both cameras)
    def jcost(l):
        r = np.concatenate([line_resid(undistort_px(P, c, l)) for _, P, c in all_lines])
        return float(np.sqrt(np.mean(r ** 2)))
    res = minimize_scalar(jcost, bounds=(-0.9, 0.2), method="bounded", options=dict(xatol=1e-5))
    l2, r2 = fit2([(P, c) for _, P, c in all_lines])
    jk = []
    for i in range(len(all_lines)):
        sub = all_lines[:i] + all_lines[i + 1:]
        jk.append(minimize_scalar(lambda l: float(np.sqrt(np.mean(np.concatenate(
            [line_resid(undistort_px(P, c, l)) for _, P, c in sub]) ** 2))), bounds=(-0.9, 0.2),
            method="bounded", options=dict(xatol=1e-5)).x)
    n = len(jk)
    se = float(np.sqrt((n - 1) / n * np.sum((np.array(jk) - np.mean(jk)) ** 2)))
    out["joint"] = dict(lam=float(res.x), lam_se_jackknife=se, rms_px=float(res.fun), two_param=l2,
                        two_param_rms_px=r2, n_lines=len(all_lines))
    print("joint lam", round(res.x, 4), "+/-", round(se, 4), "rms", round(res.fun, 3), "two-param", l2, round(r2, 3))
    if a.out:
        json.dump(out, open(a.out, "w"), indent=1)
