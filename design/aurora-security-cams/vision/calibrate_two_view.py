"""Fit both Amcrest cameras' poses jointly, in the aurora_chamber frame (mm).

What ties the two views together is the chip tray: its 6 x 10 pocket lattice is fitted in both
frames (chip_tray.py, out/chip_tray.json), and the pocket correspondence between the views is known
from tray features alone. Each pocket centre is one point seen by both cameras, on a plane, so the
relative pose of the cameras follows from it once the focal length is shared. The chamber model's
landmarks (landmarks.json, with their stated uncertainties) then place the pair in the chamber frame
and set the scale, and the cameras' shared focal length is fitted with the published-FOV prior
(1070 +/- 45 px, out/intrinsics.json).

Unknowns: f; rotation and translation of each camera; the tray's centre (x, y, z), its yaw and its
pocket pitch (mm). The tray is taken as level (it sits on the substrate plate).

    AURORA_CHAMBER_PATH=/path/to/design/aurora-chamber python calibrate_two_view.py RAW_DIR
    (RAW_DIR holds cam0.jpg and cam1.jpg, unpublished full frames)

Writes out/cameras.json: K, distortion, R, t per camera, the tray pose and pitch, and residuals.
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
from lensmodel import distort_px, undistort_px  # noqa: E402
from plumbline import edge_points  # noqa: E402
from register_chamber import load_chamber  # noqa: E402

F_PRIOR = (1070.0, 45.0)
SIG_TRAY = float(os.environ.get("SIG_TRAY", "3.0"))  # px; the chamber landmarks are only good to a few cm
C = np.array([959.5, 539.5])


def rot(rvec):
    return cv2.Rodrigues(np.asarray(rvec, float).reshape(3, 1))[0]


def proj(X, rvec, t, f):
    Xc = (rot(rvec) @ np.asarray(X, float).T).T + t
    return C + f * Xc[:, :2] / Xc[:, 2:3], Xc[:, 2]


def tray_points(tc, yaw, pitch, mirror):
    """3D centres of the 60 pockets, canonical (col 0-5, row 0-9), on a level tray."""
    cs, rs = np.meshgrid(np.arange(6), np.arange(10), indexing="xy")
    u = (cs.ravel() - 2.5) * pitch * mirror
    v = (rs.ravel() - 4.5) * pitch
    cy, sy = np.cos(yaw), np.sin(yaw)
    return np.c_[tc[0] + cy * u - sy * v, tc[1] + sy * u + cy * v, np.full(u.shape, tc[2])], cs.ravel(), rs.ravel()


def tray_obs(tray, cam, lam):
    """Undistorted pixel of each canonical pocket in one view, from the fitted lattice homography."""
    v = tray["views"][cam]
    H = np.array(v["homography_grid_ij_to_image"], float)
    cs, rs = np.meshgrid(np.arange(6), np.arange(10), indexing="xy")
    cs, rs = cs.ravel(), rs.ravel()
    i = rs if cam == "cam0" else 9 - rs          # raw_from_canonical, from chip_tray.json
    j = cs
    p = cv2.perspectiveTransform(np.c_[i, j].astype(float).reshape(-1, 1, 2), H).reshape(-1, 2)
    return undistort_px(p, C, lam)


def landmark_obs(cam, spec, P, lam, raw):
    env = {k: getattr(P, k) for k in dir(P) if not k.startswith("_")}
    env["np"] = np
    pts = [q for q in spec["points"] if q.get("use", True) and not q["name"].startswith("tray")]
    X = np.array([np.asarray(eval(q["model"], env), float) for q in pts]).reshape(-1, 3)
    u = undistort_px(np.array([q["px"] for q in pts], float).reshape(-1, 2), C, lam)
    s = np.array([q["sigma_mm"] for q in pts], float)
    g = cv2.imread(os.path.join(raw, f"{cam}.jpg"), cv2.IMREAD_GRAYSCALE)
    plumb = json.load(open(os.path.join(HERE, "plumb_lines.json")))[cam]
    lines = []
    for L in spec.get("lines", []):
        if not L.get("use", True):
            continue
        e = next(z for z in plumb if z["name"] == L["edge"])
        E = edge_points(g, e["a"], e["b"])
        d = np.array(L["dir"], float) / np.linalg.norm(L["dir"])
        lines.append((L["name"], np.array(L["p0"], float), d, undistort_px(E, C, lam), float(L["sigma_mm"])))
    return [q["name"] for q in pts], X, u, s, lines


def unpack(x):
    return dict(f=x[0], r0=x[1:4], t0=x[4:7], r1=x[7:10], t1=x[10:13], tc=x[13:16], yaw=x[16], pitch=x[17])


def residuals(x, obs, mirror, sig_tray=SIG_TRAY, sig_px=2.0):
    p = unpack(x)
    res = [np.array([(p["f"] - F_PRIOR[0]) / F_PRIOR[1]])]
    T, _, _ = tray_points(p["tc"], p["yaw"], p["pitch"], mirror)
    for k, cam in enumerate(("cam0", "cam1")):
        r, t = p[f"r{k}"], p[f"t{k}"]
        uv, z = proj(T, r, t, p["f"])
        res.append(((uv - obs[cam]["tray"]) / sig_tray).ravel())
        names, X, u, s, lines = obs[cam]["lm"]
        if len(X):
            uv, z = proj(X, r, t, p["f"])
            sd = np.sqrt(sig_px ** 2 + (p["f"] * s / np.maximum(z, 50)) ** 2)
            res.append(((uv - u) / sd[:, None]).ravel())
        for name, p0, d, U, smm in lines:
            A = np.array([p0 - 400 * d, p0 + 400 * d])
            uv, z = proj(A, r, t, p["f"])
            n = np.array([uv[1, 1] - uv[0, 1], uv[0, 0] - uv[1, 0]]); n /= np.linalg.norm(n)
            dist = (U - uv[0]) @ n
            sd = np.sqrt(sig_px ** 2 + (p["f"] * smm / max(z.mean(), 50)) ** 2)
            h = len(dist) // 2
            res.append(np.array([dist[:h].mean(), dist[h:].mean()]) / sd)
    return np.concatenate(res)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", help="directory with cam0.jpg and cam1.jpg")
    ap.add_argument("--out", default=os.path.join(HERE, "out", "cameras.json"))
    a = ap.parse_args()
    P, _ = load_chamber(os.environ["AURORA_CHAMBER_PATH"])
    reg = json.load(open(os.path.join(HERE, "out", "registration.json")))["cameras"]
    lam = (reg["cam0"]["division_model"]["l1"], reg["cam0"]["division_model"]["l2"])
    tray = json.load(open(os.path.join(HERE, "out", "chip_tray.json")))
    L = json.load(open(os.path.join(HERE, "landmarks.json")))
    obs = {cam: dict(tray=tray_obs(tray, cam, lam), lm=landmark_obs(cam, L[cam], P, lam, a.raw))
           for cam in ("cam0", "cam1")}
    tc0 = np.array([579.9, P.PLATE_C[1], P.PLATE_C[2] + P.TRAY_SIZE[2]])
    best = None
    for mirror in (1.0, -1.0):
        for yaw in np.radians(np.arange(0, 360, 45)):
            x0 = np.r_[F_PRIOR[0], reg["cam0"]["rvec"], reg["cam0"]["t"], reg["cam1"]["rvec"], reg["cam1"]["t"],
                       tc0, yaw, 13.0]
            r = least_squares(residuals, x0, args=(obs, mirror), loss="soft_l1", f_scale=2.0, max_nfev=3000)
            if best is None or r.cost < best[0].cost:
                best = (r, mirror)
    r, mirror = best
    p = unpack(r.x)
    T, cs, rs = tray_points(p["tc"], p["yaw"], p["pitch"], mirror)
    J = r.jac
    try:
        sd = np.sqrt(np.diag(np.linalg.inv(J.T @ J)))
    except np.linalg.LinAlgError:
        sd = np.full(len(r.x), np.nan)
    out = dict(frame=reg["cam0"].get("frame", "aurora_chamber scene frame, mm; x_cam = R X + t (OpenCV axes)"),
               image_size=[1920, 1080], f_px=float(p["f"]), f_sd_px=float(sd[0]),
               division_model=dict(l1=lam[0], l2=lam[1], norm_px=1000.0, centre=C.tolist()),
               tray=dict(centre=p["tc"].tolist(), yaw_deg=float(np.degrees(p["yaw"]) % 360), pitch_mm=float(p["pitch"]),
                         pitch_sd_mm=float(sd[17]), mirror=mirror,
                         size_mm=[6 * float(p["pitch"]), 10 * float(p["pitch"])]),
               cameras={})
    for k, cam in enumerate(("cam0", "cam1")):
        R, t = rot(p[f"r{k}"]), p[f"t{k}"]
        uv, _ = proj(T, p[f"r{k}"], t, p["f"])
        e_tray = np.linalg.norm(distort_px(uv, C, lam) - distort_px(obs[cam]["tray"], C, lam), axis=1)
        names, X, u, s, lines = obs[cam]["lm"]
        lm = []
        if len(X):
            uv, z = proj(X, p[f"r{k}"], t, p["f"])
            for n_, a_, b_, z_ in zip(names, distort_px(uv, C, lam), distort_px(u, C, lam), z):
                lm.append(dict(name=n_, err_px=float(np.linalg.norm(a_ - b_)), depth_mm=float(z_)))
        for name, p0, d, U, smm in lines:
            A = np.array([p0 - 400 * d, p0 + 400 * d])
            uv, z = proj(A, p[f"r{k}"], t, p["f"])
            n = np.array([uv[1, 1] - uv[0, 1], uv[0, 0] - uv[1, 0]]); n /= np.linalg.norm(n)
            lm.append(dict(name=name, line=True, rms_dist_px=float(np.sqrt(np.mean(((U - uv[0]) @ n) ** 2)))))
        out["cameras"][cam] = dict(K=[[p["f"], 0, C[0]], [0, p["f"], C[1]], [0, 0, 1]], R=R.tolist(), t=t.tolist(),
                                   rvec=p[f"r{k}"].tolist(), centre=(-R.T @ t).tolist(), view_dir=R[2].tolist(),
                                   tray_rms_px=float(np.sqrt(np.mean(e_tray ** 2))), landmarks=lm)
    C0, C1 = (np.array(out["cameras"][c]["centre"]) for c in ("cam0", "cam1"))
    out["baseline_mm"] = float(np.linalg.norm(C1 - C0))
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "cameras"}, indent=1))
    for cam, c in out["cameras"].items():
        print(cam, "centre", np.round(c["centre"]), "tray rms px", round(c["tray_rms_px"], 2),
              [(d["name"], round(d.get("err_px", d.get("rms_dist_px", 0)), 1)) for d in c["landmarks"]])


if __name__ == "__main__":
    main()
