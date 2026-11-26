"""Register the two Amcrest cameras into the aurora_chamber model (scene frame, mm).

Intrinsics: principal point at the frame centre, zero skew, square pixels, focal length f (px) and the
two-parameter division model from plumbline.py (out/intrinsics.json). Landmark pixels are undistorted
with the division model, then the pose (and optionally f) is fitted by robust least squares to
  - point landmarks (landmarks.json, model coordinates evaluated from aurora_chamber), and
  - line landmarks: snapped edge points (plumbline.edge_points) against a projected 3D line.
Residuals are weighted by the model's stated uncertainty projected to pixels.

    AURORA_CHAMBER_PATH=/path/to/design/aurora-chamber python register_chamber.py
"""
import argparse
import importlib
import json
import os
import sys
import types

import cv2
import numpy as np
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lensmodel import distort_px, undistort_px, opencv_coeffs, opencv_rational  # noqa: E402
from plumbline import edge_points  # noqa: E402


def load_chamber(path):
    """Import aurora_chamber's params/robot/specs without its __init__ (which needs pyvista)."""
    pkg = types.ModuleType("aurora_chamber")
    pkg.__path__ = [os.path.join(path, "aurora_chamber")]
    sys.modules["aurora_chamber"] = pkg
    p = importlib.import_module("aurora_chamber.params")
    s = importlib.import_module("aurora_chamber.specs")
    return p, s


def rodrigues(r):
    return cv2.Rodrigues(np.asarray(r, float).reshape(3, 1))[0]


def project(X, rvec, t, f, c):
    R = rodrigues(rvec)
    Xc = (R @ np.asarray(X, float).T).T + t
    return c + f * Xc[:, :2] / Xc[:, 2:3], Xc[:, 2]


def residuals(x, pts_X, pts_u, pts_s, lines, c, f_fixed, sig_px=2.0):
    rvec, t = x[:3], x[3:6]
    f = f_fixed if f_fixed is not None else x[6]
    res = []
    if len(pts_X):
        uv, z = project(pts_X, rvec, t, f, c)
        s = np.sqrt(sig_px ** 2 + (f * pts_s / np.maximum(z, 50)) ** 2)
        res.append(((uv - pts_u) / s[:, None]).ravel())
    for (p0, d, U, smm) in lines:
        A = np.array([p0 - 400 * d, p0 + 400 * d])
        uv, z = project(A, rvec, t, f, c)
        n = np.array([uv[1, 1] - uv[0, 1], uv[0, 0] - uv[1, 0]])
        n /= np.linalg.norm(n)
        dist = (U - uv[0]) @ n
        s = np.sqrt(sig_px ** 2 + (f * smm / max(z.mean(), 50)) ** 2)
        # one line = two constraints: use mean and slope-like split (first/second half) to avoid over-weighting
        h = len(dist) // 2
        res.append(np.array([dist[:h].mean(), dist[h:].mean()]) / s)
    R = rodrigues(rvec)
    C = -R.T @ t
    lo, hi = np.array([0.0, 0.0, 400.0]), np.array([1200.0, 1120.0, 790.0])
    res.append(np.maximum(0, lo - C) / 25.0 + np.maximum(0, C - hi) / 25.0)
    return np.concatenate(res)


MIRROR_Y = None   # set to GB_D to test a model mirrored across the box (y -> GB_D - y)


def _m(X):
    X = np.array(X, float)
    if MIRROR_Y is not None:
        X[..., 1] = MIRROR_Y - X[..., 1]
    return X


def solve(cam, spec, P, f0, c, lam, raw, free_f=False, init=None, drop=()):
    g = cv2.imread(os.path.join(raw, f"{cam}.jpg"), cv2.IMREAD_GRAYSCALE)
    env = {k: getattr(P, k) for k in dir(P) if not k.startswith("_")}
    env["np"] = np
    pts = [q for q in spec["points"] if q["name"] not in drop and q.get("use", True)]
    checks = [q for q in spec["points"] if not q.get("use", True)]
    X = _m(np.array([np.asarray(eval(q["model"], env), float) for q in pts])) if pts else np.zeros((0, 3))
    u = undistort_px(np.array([q["px"] for q in pts], float), c, lam) if pts else np.zeros((0, 2))
    s = np.array([q["sigma_mm"] for q in pts], float)
    plumb = json.load(open(os.path.join(HERE, "plumb_lines.json")))[cam]
    lines = []
    for L in spec.get("lines", []):
        if L["name"] in drop or not L.get("use", True):
            continue
        e = next(z for z in plumb if z["name"] == L["edge"])
        E = edge_points(g, e["a"], e["b"])
        dvec = np.array(L["dir"], float) / np.linalg.norm(L["dir"])
        if MIRROR_Y is not None:
            dvec[1] = -dvec[1]
        lines.append((_m(L["p0"]), dvec,
                      undistort_px(E, c, lam), float(L["sigma_mm"])))
    best = None
    inits = [init] if init is not None else []
    # coarse multi-start over viewing directions from cameras near the ceiling
    for yaw in np.radians(np.arange(0, 360, 30)):
        for pitch in np.radians([20, 35, 50, 65]):
            for cx in (200, 600, 1000):
                for cy in (150, 560, 950):
                    C = np.array([cx, cy, 720.0])
                    fwd = np.array([np.cos(yaw) * np.cos(pitch), np.sin(yaw) * np.cos(pitch), -np.sin(pitch)])
                    right = np.cross(fwd, [0, 0, 1.0]); right /= np.linalg.norm(right)
                    down = np.cross(fwd, right)
                    R = np.stack([right, down, fwd])
                    inits.append(np.r_[cv2.Rodrigues(R)[0].ravel(), -R @ C])
    for x0 in inits:
        x0 = np.r_[x0, f0] if free_f else np.asarray(x0, float)
        try:
            r = least_squares(residuals, x0, args=(X, u, s, lines, c, None if free_f else f0), loss="soft_l1",
                              f_scale=1.0, max_nfev=400)
        except Exception:
            continue
        uv, z = project(X, r.x[:3], r.x[3:6], r.x[6] if free_f else f0, c) if len(X) else (None, np.array([1.0]))
        if (z <= 0).any():
            continue
        if best is None or r.cost < best.cost:
            best = r
    r = best
    f = r.x[6] if free_f else f0
    R = rodrigues(r.x[:3])
    t = r.x[3:6]
    C = -R.T @ t
    out = dict(R=R.tolist(), t=t.tolist(), rvec=r.x[:3].tolist(), centre=C.tolist(), f=float(f),
               view_dir=R[2].tolist(), cost=float(r.cost))
    # per-landmark residuals (px, in the undistorted pinhole image; distorted-frame residuals too)
    det = []
    if len(X):
        uv, z = project(X, r.x[:3], t, f, c)
        uvd = distort_px(uv, c, lam)
        for q, a, b, zz in zip(pts, uv, uvd, z):
            det.append(dict(name=q["name"], px=q["px"], model_xyz=None, proj_px=b.tolist(),
                            err_px=float(np.linalg.norm(b - np.array(q["px"]))), depth_mm=float(zz)))
    for (p0, d, U, smm), L in zip(lines, [L for L in spec.get("lines", []) if L.get("use", True) and L["name"] not in drop]):
        A = np.array([p0 - 400 * d, p0 + 400 * d])
        uv, z = project(A, r.x[:3], t, f, c)
        n = np.array([uv[1, 1] - uv[0, 1], uv[0, 0] - uv[1, 0]]); n /= np.linalg.norm(n)
        dist = (U - uv[0]) @ n
        det.append(dict(name=L["name"], line=True, n_edge_points=len(U), rms_dist_px=float(np.sqrt(np.mean(dist ** 2))),
                        mean_dist_px=float(dist.mean())))
    for dd, q in zip(det, pts):
        dd["model_xyz"] = np.asarray(eval(q["model"], env), float).tolist()
        dd["param"] = q["param"]; dd["sigma_mm"] = q["sigma_mm"]
    for q in checks:
        Xq = _m(np.asarray(eval(q["model"], env), float))[None]
        uv, z = project(Xq, r.x[:3], t, f, c)
        b = distort_px(uv, c, lam)[0]
        det.append(dict(name=q["name"], px=q["px"], model_xyz=Xq[0].tolist(), proj_px=b.tolist(), used=False,
                        err_px=float(np.linalg.norm(b - np.array(q["px"]))), depth_mm=float(z[0]),
                        param=q["param"], sigma_mm=q["sigma_mm"], why_not_used=q.get("why_not_used")))
    out["residuals"] = det
    pe = [d["err_px"] for d in det if "err_px" in d and d.get("used", True)]
    out["point_rms_px"] = float(np.sqrt(np.mean(np.square(pe)))) if pe else None
    J = r.jac
    try:
        cov = np.linalg.inv(J.T @ J)
        out["param_sd"] = np.sqrt(np.diag(cov)).tolist()
    except np.linalg.LinAlgError:
        out["param_sd"] = None
    return out, r.x


def model_edges(P, S):
    """3D polylines to draw: glovebox shell, exfoliator boxes, Epson base, ceiling items."""
    segs = []
    W, D, H, fl, bl = P.GB_W, P.GB_D, P.GB_H, P.FRONT_LEAN, P.BACK_LEAN
    deck = [(0, 0, 0), (W, 0, 0), (W, D, 0), (0, D, 0)]
    ceil = [(0, fl, H), (W, fl, H), (W, D - bl, H), (0, D - bl, H)]
    segs.append(("shell", deck + [deck[0]]))
    segs.append(("shell", ceil + [ceil[0]]))
    for a, b in zip(deck, ceil):
        segs.append(("shell", [a, b]))
    # QR sign and antechamber door
    s0 = P.SIGN[0]; sw, sh = P.SIGN_SIZE
    segs.append(("sign", [s0, s0 + (0, sw, 0), s0 + (0, sw, sh), s0 + (0, 0, sh), s0]))
    th = np.linspace(0, 2 * np.pi, 60)
    segs.append(("door", [P.ANTE_DOOR_C + (0, P.ANTE_DOOR_R * np.cos(a), P.ANTE_DOOR_R * np.sin(a)) for a in th]))

    def box_edges(lo, hi, R=np.eye(3), ctr=None):
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        cs = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        if ctr is not None:
            cs = (R @ (cs - ctr).T).T + ctr
        E = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
        return [[cs[i], cs[j]] for i, j in E]

    items = S.exfoliator_specs() + S.scara_specs()[0][:5] + S.ceiling_specs()
    for it in items:
        k = it["kind"]
        tag = "epson" if it["name"] in ("riser block", "base", "controller box", "lamp") else "equipment"
        if k == "box":
            for e in box_edges(it["lo"], it["hi"]):
                segs.append((tag, e))
        elif k == "obox":
            c, sz, yaw = it["center"], it["size"], np.radians(it["yaw"])
            R = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
            for e in box_edges(c - sz / 2, c + sz / 2, R, c):
                segs.append((tag, e))
        elif k in ("cyl", "ring"):
            c = it["center"]; d = np.asarray(it.get("direction", it.get("normal")), float); d /= np.linalg.norm(d)
            r = it.get("r", it.get("r_out")); h = it.get("h", it.get("t"))
            a = np.cross(d, [1, 0, 0] if abs(d[0]) < 0.9 else [0, 1, 0]); a /= np.linalg.norm(a); b = np.cross(d, a)
            for sgn in (-0.5, 0.5):
                segs.append((tag, [c + sgn * h * d + r * (np.cos(q) * a + np.sin(q) * b) for q in th]))
    return segs


def draw_overlay(img, segs, rvec, t, f, c, lam, landmarks=None):
    out = img.copy()
    col = dict(shell=(0, 255, 255), equipment=(255, 160, 0), epson=(0, 0, 255), sign=(0, 255, 0), door=(255, 0, 255))
    R = rodrigues(rvec)
    for tag, pts in segs:
        pts = np.asarray(pts, float)
        # densify
        dense = []
        for a, b in zip(pts[:-1], pts[1:]):
            n = max(2, int(np.linalg.norm(b - a) / 10))
            dense += [a + (b - a) * s for s in np.linspace(0, 1, n)]
        dense = np.array(dense)
        Xc = (R @ dense.T).T + t
        ok = Xc[:, 2] > 30
        uv = c + f * Xc[:, :2] / np.where(ok, Xc[:, 2], 1)[:, None]
        uvd = distort_px(uv, c, lam)
        for i in range(len(uvd) - 1):
            if ok[i] and ok[i + 1] and np.all(np.abs(uvd[i:i + 2]) < 4000):
                cv2.line(out, tuple(np.round(uvd[i]).astype(int)), tuple(np.round(uvd[i + 1]).astype(int)),
                         col[tag], 2, cv2.LINE_AA)
    if landmarks:
        for d in landmarks:
            if "px" in d:
                p = tuple(int(v) for v in d["px"]); q = tuple(int(v) for v in d["proj_px"])
                cv2.circle(out, p, 7, (0, 255, 0), 2)
                cv2.drawMarker(out, q, (0, 0, 255), cv2.MARKER_CROSS, 16, 2)
                cv2.line(out, p, q, (255, 255, 255), 1)
                cv2.putText(out, d["name"], (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chamber", default=os.environ.get("AURORA_CHAMBER_PATH", "/tmp/aurora-vision/ref/design/aurora-chamber"))
    ap.add_argument("--raw", default="/tmp/aurora-vision/raw")
    ap.add_argument("--intrinsics", default=os.path.join(HERE, "out", "intrinsics.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "out", "registration.json"))
    ap.add_argument("--calib", default="/tmp/aurora-vision/calib")
    ap.add_argument("--f", type=float, default=None)
    ap.add_argument("--masks", default="/tmp/aurora-vision/masks", help="<cam>_inside.png (white = inside the box); "
                    "if present, a copy of each overlay with everything outside the glovebox blurred goes to out/")
    ap.add_argument("--drop", nargs="*", default=[])
    ap.add_argument("--mirror-test", action="store_true", help="also fit a y-mirrored model and report it")
    ap.add_argument("--cams", nargs="*", default=["cam0", "cam1"])
    a = ap.parse_args()
    P, S = load_chamber(a.chamber)
    intr = json.load(open(a.intrinsics)) if os.path.exists(a.intrinsics) else {}
    adopted = intr.get("adopted", {})
    f0 = a.f or adopted.get("f_px", 950.0)
    lam = adopted.get("division", [-0.28937, -0.08972])
    spec = json.load(open(os.path.join(HERE, "landmarks.json")))
    segs = model_edges(P, S)
    res = dict(frame="aurora_chamber scene frame, mm (x from the antechamber-end wall, y from the open side, z up "
                     "from the deck)", image_size=[1920, 1080], dome_c_model=np.asarray(P.DOME_C).tolist(),
               note="R, t map scene to camera (x_cam = R X + t), OpenCV camera axes (x right, y down, z forward)",
               cameras={})
    for cam in ("cam0", "cam1"):
        img = cv2.imread(os.path.join(a.raw, f"{cam}.jpg"))
        c = np.array([(img.shape[1] - 1) / 2, (img.shape[0] - 1) / 2])
        fixed, x = solve(cam, spec[cam], P, f0, c, lam, a.raw, free_f=False, drop=a.drop)
        free, _ = solve(cam, spec[cam], P, f0, c, lam, a.raw, free_f=True, init=x, drop=a.drop)
        K = np.array([[f0, 0, c[0]], [0, f0, c[1]], [0, 0, 1]])
        r_max = float(np.hypot(*c)) + 2
        dist5, e5 = opencv_coeffs(lam, f0, r_max)
        dist8, e8 = opencv_rational(lam, f0, r_max)
        C = np.array(fixed["centre"])
        res["cameras"][cam] = dict(
            K=K.tolist(), division_model=dict(l1=lam[0], l2=lam[1], norm_px=1000.0, centre=c.tolist()),
            dist_opencv_rational=dist8.tolist(), dist_opencv_rational_max_err_px=e8,
            dist_opencv_5=dist5.tolist(), dist_opencv_5_max_err_px=e5,
            R=fixed["R"], t=fixed["t"], rvec=fixed["rvec"], camera_centre=fixed["centre"],
            view_dir=fixed["view_dir"], point_rms_px=fixed["point_rms_px"], residuals=fixed["residuals"],
            pose_param_sd=fixed["param_sd"],
            dist_to_dome_c_mm=float(np.linalg.norm(C - np.asarray(P.DOME_C))),
            free_f=dict(f=free["f"], camera_centre=free["centre"], point_rms_px=free["point_rms_px"],
                        param_sd=free["param_sd"], residuals=free["residuals"]))
        ov = draw_overlay(img, segs, np.array(fixed["rvec"]), np.array(fixed["t"]), f0, c, lam, fixed["residuals"])
        os.makedirs(a.calib, exist_ok=True)
        cv2.imwrite(os.path.join(a.calib, f"overlay_{cam}.jpg"), ov, [cv2.IMWRITE_JPEG_QUALITY, 90])
        mpath = os.path.join(a.masks, f"{cam}_inside.png")
        if os.path.exists(mpath):   # privacy: only frames with the lab outside the glovebox blurred go in the repo
            m = cv2.imread(mpath, cv2.IMREAD_GRAYSCALE)
            m = cv2.resize(m, (ov.shape[1], ov.shape[0]), interpolation=cv2.INTER_NEAREST) > 127
            m = cv2.erode(m.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
            blur = cv2.GaussianBlur(cv2.resize(ov, None, fx=0.125, fy=0.125), (0, 0), 6)
            blur = cv2.resize(blur, (ov.shape[1], ov.shape[0]), interpolation=cv2.INTER_LINEAR)
            ovm = np.where(m[..., None], ov, blur)
            ovm = cv2.resize(ovm, (1280, 720), interpolation=cv2.INTER_AREA)
            cv2.imwrite(os.path.join(os.path.dirname(a.out), f"overlay_{cam}_masked.jpg"), ovm,
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
        print(cam, "C", np.round(C, 0), "view", np.round(fixed["view_dir"], 3), "rms", fixed["point_rms_px"],
              "| free f", round(free["f"], 1), np.round(free["centre"], 0), free["point_rms_px"])
        for d in fixed["residuals"]:
            print("   ", d["name"], round(d.get("err_px", d.get("rms_dist_px", -1)), 1))
    json.dump(res, open(a.out, "w"), indent=1)
    os.makedirs(a.calib, exist_ok=True)
    json.dump(res, open(os.path.join(a.calib, "registration.json"), "w"), indent=1)
