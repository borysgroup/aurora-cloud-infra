"""Register every frame of the AURORA video's two shots of this glovebox to the chamber frame, and
estimate the video camera's intrinsics from all of them.

    python video_register.py FRAMES_DIR [--shots transfer,exfol]  # -> out/video_cameras.json

The video (https://www.youtube.com/watch?v=moBCWzP9Izw, 2026-07-22) is not redistributed. FRAMES_DIR
holds its frames as NNNN.jpg (frame index at 29.97 fps, 1920 x 1080), e.g. dumped with OpenCV.

How each frame is placed:
  1. LoFTR (kornia, outdoor weights) matches the frame against the published Overhead 1 and
     Overhead 2 stills; MAGSAC on the fundamental matrix keeps the consistent matches.
  2. Each matched still pixel is lifted to 3D through that camera's calibrated pose and lens
     (cameras.py) onto the model's depth (scene_detail.build, rendered from that camera).
  3. The frame's pose comes from PnP + RANSAC on those 2D-3D pairs.
  4. One focal length and one radial term per shot (SIMPLE_RADIAL, principal point at the centre)
     and every frame's pose are refined together by robust least squares over all frames.

The 3D points rest on the model, so a part that moved between the video (July) and the stills
(November) shows up as outliers, not as a wrong pose; a frame needs at least 25 inliers.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render  # noqa: E402
from cameras import C, CAL, CAM0, CAM1, LAM  # noqa: E402
from lensmodel import undistort_px  # noqa: E402

OUT = os.path.join(HERE, "out")
CAPS = os.path.join(HERE, "..", "captures")
STILLS = {"cam0": "2026-11-19_1822Z_cam0_192.168.3.150.jpg", "cam1": "2026-11-19_1822Z_cam1_192.168.3.151.jpg"}
SHOTS = {"transfer": (600, 662), "exfol": (675, 746)}
TITLE = (855, 10, 1890, 165)          # the video's title box (x0, y0, x1, y1)
W, H = 1920, 1080


def model_depth(parts, cam):
    """z-depth (mm along the view axis) of the model on render.CANVAS, a pinhole canvas with the
    camera's focal length centred on its principal point."""
    pl = render._plotter(parts, render.CANVAS, bg="black")
    fwd, down = cam.R[2], cam.R[1]
    pl.camera.position = cam.centre.tolist()
    pl.camera.focal_point = (cam.centre + 1000 * fwd).tolist()
    pl.camera.up = (-down).tolist()
    pl.camera.view_angle = float(np.degrees(2 * np.arctan((render.CANVAS[1] / 2) / cam.f)))
    pl.camera.clipping_range = (20, 6000)
    pl.show(auto_close=False)
    d = pl.get_image_depth(fill_value=np.nan)
    pl.close()
    return -d


def lift(cam, depth, px):
    """Distorted pixels of a calibrated camera -> 3D points on the model (NaN where no geometry)."""
    u = undistort_px(np.atleast_2d(px), C, LAM)
    cw, ch = render.CANVAS
    cx = np.round(u[:, 0] - C[0] + (cw - 1) / 2).astype(int)
    cy = np.round(u[:, 1] - C[1] + (ch - 1) / 2).astype(int)
    ok = (cx >= 0) & (cx < cw) & (cy >= 0) & (cy < ch)
    z = np.full(len(u), np.nan)
    z[ok] = depth[cy[ok], cx[ok]]
    Xc = np.c_[(u - C) / cam.f, np.ones(len(u))] * z[:, None]
    return (cam.R.T @ (Xc - cam.t).T).T


_loftr = None


def loftr_match(img_a, img_b, mask_title=True):
    import kornia.feature as KF
    import torch
    global _loftr
    if _loftr is None:
        torch.set_num_threads(4)
        _loftr = KF.LoFTR(pretrained="outdoor").eval()

    def prep(im, w=960):
        s = w / im.shape[1]
        g = cv2.cvtColor(cv2.resize(im, (w, int(im.shape[0] * s) // 8 * 8)), cv2.COLOR_BGR2GRAY)
        return torch.from_numpy(g)[None, None].float() / 255.0, s

    ta, sa = prep(img_a)
    tb, sb = prep(img_b)
    with torch.inference_mode():
        r = _loftr({"image0": ta, "image1": tb})
    pa, pb, cf = r["keypoints0"].numpy() / sa, r["keypoints1"].numpy() / sb, r["confidence"].numpy()
    keep = cf > 0.4
    if mask_title:
        x0, y0, x1, y1 = TITLE
        keep &= ~((pa[:, 0] > x0) & (pa[:, 0] < x1) & (pa[:, 1] > y0) & (pa[:, 1] < y1))
    keep &= ~((pb[:, 1] < 125) & (pb[:, 0] > 1280)) & ~((pb[:, 1] > 950) & (pb[:, 0] < 170))   # burned-in text
    pa, pb = pa[keep], pb[keep]
    if len(pa) < 12:
        return pa[:0], pb[:0]
    F, inl = cv2.findFundamentalMat(pa, pb, cv2.USAC_MAGSAC, 4.0, 0.999, 10000)
    if inl is None:
        return pa[:0], pb[:0]
    inl = inl.ravel().astype(bool)
    return pa[inl], pb[inl]


def project(X, rvec, tvec, f, k):
    R, _ = cv2.Rodrigues(rvec)
    Xc = X @ R.T + tvec
    xn = Xc[:, :2] / Xc[:, 2:3]
    r2 = (xn ** 2).sum(1, keepdims=True)
    return xn * (1 + k * r2) * f + np.array([W / 2, H / 2]), Xc[:, 2]


def pnp(X, x, f, k=0.0):
    K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1.0]])
    ok, rv, tv, inl = cv2.solvePnPRansac(X.astype(np.float64), x.astype(np.float64), K, np.array([k, 0, 0, 0.0]),
                                         iterationsCount=3000, reprojectionError=12.0, confidence=0.999,
                                         flags=cv2.SOLVEPNP_SQPNP)
    if not ok or inl is None:
        return None
    inl = inl.ravel()
    rv, tv = cv2.solvePnPRefineLM(X[inl].astype(np.float64), x[inl].astype(np.float64), K, np.array([k, 0, 0, 0.0]),
                                  rv, tv)
    return rv.ravel(), tv.ravel(), inl


def refine(obs, f0, k0):
    """Shared (f, k) and per-frame (rvec, tvec) by robust least squares over all frames."""
    keys = sorted(obs)
    x0 = [f0, k0]
    for kf in keys:
        x0 += list(obs[kf]["rvec"]) + list(obs[kf]["tvec"])

    def res(p):
        f, k = p[0], p[1]
        out = []
        for i, kf in enumerate(keys):
            rv, tv = p[2 + 6 * i:5 + 6 * i], p[5 + 6 * i:8 + 6 * i]
            o = obs[kf]
            uv, _ = project(o["X"], rv, tv, f, k)
            out.append((uv - o["x"]).ravel())
        return np.concatenate(out)

    r = least_squares(res, np.array(x0, float), loss="soft_l1", f_scale=4.0, max_nfev=300, x_scale="jac")
    f, k = r.x[:2]
    for i, kf in enumerate(keys):
        obs[kf]["rvec"], obs[kf]["tvec"] = r.x[2 + 6 * i:5 + 6 * i], r.x[5 + 6 * i:8 + 6 * i]
    J = r.jac
    try:
        cov = np.linalg.pinv(J.T @ J) * (np.median(np.abs(r.fun)) / 0.6745) ** 2
        sf, sk = np.sqrt(cov[0, 0]), np.sqrt(cov[1, 1])
    except Exception:
        sf = sk = float("nan")
    return f, k, sf, sk, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames")
    ap.add_argument("--shots", default="transfer,exfol")
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--f0", type=float, default=1550.0)
    a = ap.parse_args()
    import scene_detail as SD
    parts = [p for p in SD.build(CAL) if getattr(p, "image", None) is None and p.group != "cameras"]
    depth = {c.name: model_depth(parts, c) for c in (CAM0, CAM1)}
    stills = {k: cv2.imread(os.path.join(CAPS, v)) for k, v in STILLS.items()}
    cams = {"cam0": CAM0, "cam1": CAM1}
    result = dict(video="https://www.youtube.com/watch?v=moBCWzP9Izw (frames at 29.97 fps, 1920 x 1080)",
                  frame="aurora_chamber scene frame, mm", camera_model="SIMPLE_RADIAL, principal point at the centre",
                  shots={})
    for shot in a.shots.split(","):
        lo, hi = SHOTS[shot]
        obs = {}
        for kf in range(lo, hi + 1, a.stride):
            fr = cv2.imread(os.path.join(a.frames, f"{kf:04d}.jpg"))
            if fr is None:
                continue
            Xs, xs, src = [], [], {}
            for cn, still in stills.items():
                pa, pb = loftr_match(fr, still)
                if len(pa) == 0:
                    continue
                X = lift(cams[cn], depth[cn], pb)
                ok = np.isfinite(X).all(1)
                Xs.append(X[ok])
                xs.append(pa[ok])
                src[cn] = int(ok.sum())
            if not Xs:
                continue
            X, x = np.vstack(Xs), np.vstack(xs)
            if len(X) < 25:
                print(shot, kf, "too few matches", src, flush=True)
                continue
            best = None
            for f in (a.f0 * s for s in (0.75, 0.85, 1.0, 1.15, 1.3)):
                r = pnp(X, x, f)
                if r is not None and (best is None or len(r[2]) > len(best[1][2])):
                    best = (f, r)
            if best is None or len(best[1][2]) < 25:
                print(shot, kf, "PnP failed", src, flush=True)
                continue
            f, (rv, tv, inl) = best
            obs[kf] = dict(X=X[inl], x=x[inl], rvec=rv, tvec=tv, n_matches=src, f_scan=f)
            print(shot, kf, "matches", src, "inliers", len(inl), "f scan", round(f), flush=True)
        if len(obs) < 3:
            result["shots"][shot] = dict(registered=len(obs), note="too few frames registered")
            continue
        f0 = float(np.median([o["f_scan"] for o in obs.values()]))
        f, k, sf, sk, r = refine(obs, f0, 0.0)
        # drop gross outliers and refine once more
        for kf, o in obs.items():
            uv, z = project(o["X"], o["rvec"], o["tvec"], f, k)
            e = np.linalg.norm(uv - o["x"], axis=1)
            keep = (e < 10) & (z > 0)
            o["X"], o["x"] = o["X"][keep], o["x"][keep]
        obs = {kf: o for kf, o in obs.items() if len(o["X"]) >= 20}
        f, k, sf, sk, r = refine(obs, f, k)
        frames = {}
        errs = []
        for kf, o in sorted(obs.items()):
            R, _ = cv2.Rodrigues(o["rvec"])
            uv, _ = project(o["X"], o["rvec"], o["tvec"], f, k)
            e = np.linalg.norm(uv - o["x"], axis=1)
            errs.append(e)
            frames[str(kf)] = dict(R=np.round(R, 6).tolist(), t=np.round(o["tvec"], 2).tolist(),
                                   centre=np.round(-R.T @ o["tvec"], 1).tolist(), inliers=int(len(e)),
                                   median_err_px=round(float(np.median(e)), 2), matches=o["n_matches"])
        e = np.concatenate(errs)
        cen = np.array([v["centre"] for v in frames.values()])
        hfov = float(np.degrees(2 * np.arctan(W / 2 / f)))
        result["shots"][shot] = dict(frames_in_shot=hi - lo + 1, registered=len(frames), f_px=round(float(f), 1),
                                     f_px_sigma=round(float(sf), 1), k1=round(float(k), 4),
                                     k1_sigma=round(float(sk), 4), hfov_deg=round(hfov, 1),
                                     median_reproj_px=round(float(np.median(e)), 2),
                                     camera_path_length_mm=round(float(np.linalg.norm(np.diff(cen, axis=0), axis=1).sum()), 1),
                                     camera_centre_mean=np.round(cen.mean(0), 1).tolist(), frames=frames)
        print(shot, "f", round(f, 1), "+-", round(sf, 1), "k1", round(k, 4), "registered", len(frames), "median err",
              round(float(np.median(e)), 2), flush=True)
    json.dump(result, open(os.path.join(OUT, "video_cameras.json"), "w"), indent=1)


if __name__ == "__main__":
    main()


# ---- the robot's pose in a registered frame ------------------------------------------------------------

def scara_ik(pose, xy):
    """Both (J1, J2) solutions, degrees, that put J3 over chamber point xy for the base pose."""
    import epson_cad as E
    yaw = np.radians(pose["yaw"])
    d = np.asarray(xy, float) - np.asarray(pose["j1"], float)
    X, Y = np.cos(-yaw) * d[0] - np.sin(-yaw) * d[1], np.sin(-yaw) * d[0] + np.cos(-yaw) * d[1]
    r2 = X * X + Y * Y
    c2 = np.clip((r2 - E.L1 ** 2 - E.L2 ** 2) / (2 * E.L1 * E.L2), -1, 1)
    out = []
    for s in (1, -1):
        j2 = s * np.arccos(c2)
        j1 = np.arctan2(Y, X) - np.arctan2(E.L2 * np.sin(j2), E.L1 + E.L2 * np.cos(j2))
        out.append((float((np.degrees(j1) + 180) % 360 - 180), float(np.degrees(j2))))
    return out


def robot_pose_in_frame(shot, kf, collar_px, j2_px, z_stroke=0.0):
    """J1/J2 for one registered frame: the shaft's exit from arm 2 (collar_px) is lifted onto the plane of
    arm 2's underside (fixed height whatever J3 does), J3 = that point, and of the two IK solutions the
    one whose J2 projects nearer j2_px is kept."""
    import epson_cad as E
    vc = json.load(open(os.path.join(OUT, "video_cameras.json")))["shots"][shot]
    fr = vc["frames"][str(kf)]
    R, t, f, k = np.array(fr["R"]), np.array(fr["t"]), vc["f_px"], vc["k1"]
    p = json.load(open(os.path.join(OUT, "epson_cad_pose.json")))
    pose = dict(j1=tuple(p["base"]["j1"]), z0=p["base"]["z0"], yaw=p["base"]["yaw"])
    # undistort the pixel (SIMPLE_RADIAL), ray in the chamber frame
    xd = (np.asarray(collar_px, float) - [W / 2, H / 2]) / f
    xu = xd.copy()
    for _ in range(8):
        xu = xd / (1 + k * (xu ** 2).sum())
    d = R.T @ np.r_[xu, 1.0]
    c = -R.T @ t
    z = pose["z0"] + 227.5
    P = c + d * (z - c[2]) / d[2]
    best = None
    for j1, j2 in scara_ik(pose, P[:2]):
        B = E.base_transform(pose)
        J2 = (B @ E.link_transforms(j1, j2)["arm2"] @ np.r_[E.L1, 0, 300.0, 1])[:3]
        uv, _ = project(J2[None], cv2.Rodrigues(R)[0].ravel(), t, f, k)
        e = float(np.linalg.norm(uv[0] - j2_px))
        if best is None or e < best[0]:
            best = (e, j1, j2)
    _, j1, j2 = best
    for lim, v in ((E.LIMITS["j1"], j1), (E.LIMITS["j2"], j2)):
        if abs(v) > lim:
            print("warning: outside Epson's joint range", round(v, 1), flush=True)
    return dict(j1=round(j1, 2), j2=round(j2, 2), z=z_stroke, u=0.0, j3_xy=np.round(P[:2], 1).tolist())


def robot_deltas(pose, parked, new):
    """4x4 chamber-frame transforms that move each robot link group from the parked pose to `new`."""
    import epson_cad as E
    B = E.base_transform(pose)
    a = E.link_transforms(parked["j1"], parked["j2"], parked.get("z", 0.0), parked.get("u", 0.0))
    b = E.link_transforms(new["j1"], new["j2"], new.get("z", 0.0), new.get("u", 0.0))
    return {g: (B @ b[g] @ np.linalg.inv(B @ a[g])).tolist() for g in ("arm1", "arm2", "shaft")}
