#!/usr/bin/env python3
"""Dense two-view reconstruction of the glovebox interior with VGGT on CPU.

Runs VGGT-1B on two simultaneous stills from the two opposed Amcrest cameras and

1. saves per-view depth maps, point maps, confidences, the predicted intrinsics (also
   rescaled to the full 1920x1080 frame) and the predicted relative pose (npz);
2. aligns the prediction to the glovebox model's metric frame (mm) with a similarity
   transform from the predicted to the registered camera poses, refined with Umeyama on
   landmarks when the registration lists landmark pixels with model coordinates;
3. exports a coloured point cloud of the glovebox interior (inside-mask, confidence and
   overlay-text filtering, voxel downsampling, binary PLY) and matplotlib renders with both
   camera frusta.

Without a registration file the cloud stays in VGGT's own frame (camera 0 at the origin,
OpenCV axes, unit-free scale).

Setup (CPU only; tested on a 4 vCPU x86_64 runner, Python 3.14)
-----------------------------------------------------------------
    pip install uv
    uv venv /tmp/vggt-env --python 3.14
    uv pip install --python /tmp/vggt-env/bin/python torch==2.15.0 torchvision==0.29.2 \
        --index-url https://download.pytorch.org/whl/cpu
    git clone https://github.com/facebookresearch/vggt /tmp/vggt-src/vggt   # tested at a288dd0
    uv pip install --python /tmp/vggt-env/bin/python --no-deps -e /tmp/vggt-src/vggt
    uv pip install --python /tmp/vggt-env/bin/python huggingface_hub einops safetensors \
        opencv-python-headless matplotlib scipy
    /tmp/vggt-env/bin/python -c "from huggingface_hub import hf_hub_download as d; \
        [d('facebook/VGGT-1B', f, revision='860abec7937da0a4c03c41d3c269c366e82abdf9', \
        local_dir='/tmp/aurora-vision/dense/models/VGGT-1B') \
        for f in ('config.json', 'model.safetensors')]"

`vggt` 0.0.1 pins numpy<2 in its pyproject; installed with --no-deps it runs inference fine
with numpy 2.x. Weights are loaded from model.safetensors (5.0 GB, no pickle). On 4 vCPUs the
weights load in about 10 s and two 518x294 frames take 30 to 40 s (fp32); peak RSS is about
10 GB. --reuse skips inference and re-runs alignment and export from the saved npz.

Inputs and outputs
------------------
registration.json (optional) holds, per camera, K, distortion (`dist_opencv_rational`, or
`distortion`/`dist` with a model name; `fisheye` selects cv2.fisheye), R and t (scene to
camera, mm), `camera_centre`, and landmarks under `residuals` (`px` raw pixel, `model_xyz`;
those with `err_px` above --max-landmark-err-px are skipped as registration outliers). With it, frames are undistorted to a pinhole with a centred principal point and
f = --undistort-focal-scale x K (0.8 keeps about 93 to 99 % of the inside-mask pixels of the
2.8 mm Amcrest frames). <work-dir>/vggt_two_view_<raw|undistorted>.npz holds the depth, point
maps, confidences, extrinsics (VGGT world = cam0), intrinsics at model and full resolution and
the relative pose; summary_<tag>_<fusion>.json holds timings, predicted intrinsics, relative
pose and alignment residuals.

--fusion joint (default) maps the whole two-view prediction with one similarity: rotation from
both camera poses, scale and translation from the camera centres, then Umeyama on landmarks +
centres when there are at least 3 landmarks. --fusion per-view instead places each view's depth
along the calibrated rays on its registered pose, with one scale per view fitted to that view's
landmarks (it ignores VGGT's relative pose).

Licences: the VGGT code (github.com/facebookresearch/vggt) is under the VGGT License v1
(2025-07-29), which allows commercial use except military applications. The
facebook/VGGT-1B checkpoint used here is CC BY-NC 4.0, i.e. non-commercial use only; the
gated facebook/VGGT-1B-Commercial checkpoint is the drop-in replacement for commercial use.

Example
-------
    /tmp/vggt-env/bin/python design/aurora-security-cams/vision/dense_two_view.py \
        --cam0 /tmp/aurora-vision/raw/cam0.jpg --cam1 /tmp/aurora-vision/raw/cam1.jpg \
        --mask0 /tmp/aurora-vision/masks/cam0_inside.png \
        --mask1 /tmp/aurora-vision/masks/cam1_inside.png \
        --registration /tmp/aurora-vision/calib/registration.json \
        --weights /tmp/aurora-vision/dense/models/VGGT-1B \
        --work-dir /tmp/aurora-vision/dense \
        --out-dir design/aurora-security-cams/vision/out
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np

# Burned-in overlays on the 1920x1080 Amcrest frames, (x0, y0, x1, y1) with a margin.
TEXT_BOXES = [(1290, 25, 1880, 115), (35, 970, 160, 1050)]
MODEL_W = 518  # VGGT's native width; the height keeps the aspect ratio, rounded to /14
CAM_COLOURS = ["tab:blue", "tab:red"]


# ----------------------------------------------------------------------------- geometry


def rot_angle_deg(R: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))))


def vec_angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    c = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def project_so3(M: np.ndarray) -> np.ndarray:
    U, _, Vt = np.linalg.svd(M)
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))])
    return U @ D @ Vt


def umeyama(src: np.ndarray, dst: np.ndarray, with_scale: bool = True):
    """s, R, t minimising sum |dst - (s R src + t)|^2."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    U, S, Vt = np.linalg.svd(xd.T @ xs / len(src))
    D = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        D[2, 2] = -1.0
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / ((xs**2).sum() / len(src))) if with_scale else 1.0
    return s, R, mu_d - s * R @ mu_s


def bilinear(img: np.ndarray, u: float, v: float) -> np.ndarray:
    h, w = img.shape[:2]
    u = float(np.clip(u, 0, w - 1.001))
    v = float(np.clip(v, 0, h - 1.001))
    u0, v0 = int(u), int(v)
    a, b = u - u0, v - v0
    return (
        img[v0, u0] * (1 - a) * (1 - b)
        + img[v0, u0 + 1] * a * (1 - b)
        + img[v0 + 1, u0] * (1 - a) * b
        + img[v0 + 1, u0 + 1] * a * b
    )


# ------------------------------------------------------------------------- registration


def _pick(d: dict, *keys):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return None


def _camera_nodes(reg: dict) -> dict:
    node = _pick(reg, "cameras", "cams") or reg
    if isinstance(node, list):
        return {str(_pick(c, "name", "id", "camera") or f"cam{i}"): c for i, c in enumerate(node)}
    return node


def load_registration(path: Path | None, names=("cam0", "cam1"), max_err_px: float = np.inf):
    """Parse registration.json: per camera K, distortion (+ model), R, t (world->camera, mm)."""
    if path is None or not path.exists():
        return None
    reg = json.loads(path.read_text())
    nodes = _camera_nodes(reg)
    cams = {}
    for name in names:
        c = nodes.get(name)
        if c is None:  # e.g. "0"/"1" keys
            c = nodes.get(name[-1])
        if c is None:
            raise KeyError(f"camera {name} not found in {path}")
        intr = _pick(c, "intrinsics") if isinstance(_pick(c, "intrinsics"), dict) else c
        K = np.asarray(_pick(intr, "K", "camera_matrix", "intrinsics", "K_mat"), float).reshape(3, 3)
        dist_node = _pick(c, "dist_opencv_rational", "distortion", "dist", "dist_coeffs", "D",
                          "distortion_coefficients", "dist_opencv_5")
        model = _pick(c, "distortion_model", "dist_model", "camera_model", "model")
        if isinstance(dist_node, dict):
            model = _pick(dist_node, "model", "name", "type") or model
            dist_node = _pick(dist_node, "coeffs", "coefficients", "params", "values", "k")
        dist = np.asarray(dist_node if dist_node is not None else [], float).ravel()
        ext = _pick(c, "extrinsics", "pose", "world_to_camera")
        ext = ext if isinstance(ext, dict) else c
        R = np.asarray(_pick(ext, "R", "R_world_to_cam", "R_wc", "rotation"), float).reshape(3, 3)
        t = np.asarray(_pick(ext, "t", "t_world_to_cam", "t_wc", "translation"), float).ravel()
        C = _pick(c, "C", "center", "centre", "camera_center", "camera_centre", "C_world")
        C = np.asarray(C, float).ravel() if C is not None else -R.T @ t
        cams[name] = dict(K=K, dist=dist, model=str(model or "opencv").lower(), R=R, t=t, C=C)
    lms = [l for l in parse_landmarks(reg, nodes, names) if not l["err_px"] > max_err_px]
    return dict(cams=cams, landmarks=lms, raw=reg)


def parse_landmarks(reg: dict, nodes: dict, names) -> list:
    """Landmarks as dicts {name, cam, uv (raw px), X (model mm)}; accepts a few layouts."""
    out = []

    def xyz_of(d):
        v = _pick(d, "model_xyz", "xyz", "X", "world", "model", "model_mm", "xyz_mm", "world_mm", "point")
        return None if v is None else np.asarray(v, float).ravel()[:3]

    def uv_of(d):
        v = _pick(d, "px", "uv", "pixel", "pix", "image", "uv_raw", "pixel_raw")
        return None if v is None else np.asarray(v, float).ravel()[:2]

    top = _pick(reg, "landmarks", "points", "correspondences")
    if isinstance(top, dict):
        top = [dict(v, name=k) for k, v in top.items()]
    for i, lm in enumerate(top or []):
        X = xyz_of(lm)
        if X is None:
            continue
        nm = str(_pick(lm, "name", "id", "label") or i)
        cam = _pick(lm, "cam", "camera", "view")
        uv = uv_of(lm)
        if cam is not None and uv is not None:
            out.append(dict(name=nm, cam=str(cam), uv=uv, X=X, err_px=float(lm.get("err_px", np.nan))))
        pix = _pick(lm, "pixels", "uv_per_cam", "observations") or {}
        if isinstance(pix, dict):
            for cn in names:
                if cn in pix and pix[cn] is not None:
                    v = pix[cn]
                    v = uv_of(v) if isinstance(v, dict) else np.asarray(v, float).ravel()[:2]
                    out.append(dict(name=nm, cam=cn, uv=v, X=X, err_px=np.nan))
        for cn in names:
            if cn in lm and lm[cn] is not None and not isinstance(lm[cn], (str, bool)):
                v = lm[cn]
                v = uv_of(v) if isinstance(v, dict) else np.asarray(v, float).ravel()[:2]
                if v is not None and v.size == 2:
                    out.append(dict(name=nm, cam=cn, uv=v, X=X, err_px=np.nan))
    for cn in names:
        c = nodes.get(cn) or {}
        for i, lm in enumerate(_pick(c, "residuals", "landmarks", "points", "correspondences") or []):
            X, uv = xyz_of(lm), uv_of(lm)
            if X is not None and uv is not None:
                out.append(dict(name=str(_pick(lm, "name", "id", "label") or i), cam=cn, uv=uv, X=X,
                                err_px=float(lm.get("err_px", np.nan))))
    return out


def is_fisheye(model: str) -> bool:
    return any(k in model for k in ("fisheye", "kannala", "equidistant", "kb"))


def pinhole_for(cam: dict, size, focal_scale: float) -> np.ndarray:
    """Target pinhole for undistortion: centred principal point (as VGGT assumes)."""
    W, H = size
    K = cam["K"]
    return np.array(
        [[K[0, 0] * focal_scale, 0, W / 2.0], [0, K[1, 1] * focal_scale, H / 2.0], [0, 0, 1]]
    )


def undistort_maps(cam: dict, newK: np.ndarray, size):
    K, D = cam["K"], cam["dist"]
    if is_fisheye(cam["model"]):
        return cv2.fisheye.initUndistortRectifyMap(K, D[:4], np.eye(3), newK, size, cv2.CV_32FC1)
    return cv2.initUndistortRectifyMap(K, D, None, newK, size, cv2.CV_32FC1)


def undistort_pixels(cam: dict, uv: np.ndarray, newK: np.ndarray) -> np.ndarray:
    pts = np.asarray(uv, float).reshape(-1, 1, 2)
    if is_fisheye(cam["model"]):
        return cv2.fisheye.undistortPoints(pts, cam["K"], cam["dist"][:4], P=newK).reshape(-1, 2)
    crit = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 200, 1e-10)
    return cv2.undistortPoints(pts, cam["K"], cam["dist"], R=np.eye(3), P=newK, criteria=crit).reshape(-1, 2)


# ------------------------------------------------------------------------------- views


def prepare_views(args, reg):
    """Load both frames (undistorted to a centred pinhole when calibrated) + masks at full res."""
    views = []
    for i, (img_p, mask_p) in enumerate([(args.cam0, args.mask0), (args.cam1, args.mask1)]):
        name = f"cam{i}"
        bgr = cv2.imread(str(img_p), cv2.IMREAD_COLOR)
        H, W = bgr.shape[:2]
        valid = np.full((H, W), 255, np.uint8)
        for x0, y0, x1, y1 in TEXT_BOXES:
            valid[int(y0 * H / 1080) : int(y1 * H / 1080), int(x0 * W / 1920) : int(x1 * W / 1920)] = 0
        inside = None
        if mask_p is not None and Path(mask_p).exists():
            m = cv2.imread(str(mask_p), cv2.IMREAD_GRAYSCALE)
            inside = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST) if m.shape != (H, W) else m
        newK = None
        if reg is not None and not args.raw:
            cam = reg["cams"][name]
            newK = pinhole_for(cam, (W, H), args.undistort_focal_scale)
            m1, m2 = undistort_maps(cam, newK, (W, H))
            bgr = cv2.remap(bgr, m1, m2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            valid = cv2.remap(valid, m1, m2, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
            if inside is not None:
                inside = cv2.remap(inside, m1, m2, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
        views.append(dict(name=name, bgr=bgr, valid=valid, inside=inside, newK=newK, W=W, H=H))
    return views


def to_model_res(views):
    """VGGT 'crop' preprocessing (width 518, height to /14), PIL bicubic like vggt.utils.load_fn."""
    from PIL import Image

    W, H = views[0]["W"], views[0]["H"]
    mw, mh = MODEL_W, int(round(H * MODEL_W / W / 14) * 14)
    if mh > MODEL_W:
        raise ValueError("portrait frames are not handled")
    for v in views:
        rgb = cv2.cvtColor(v["bgr"], cv2.COLOR_BGR2RGB)
        v["rgb_model"] = np.asarray(Image.fromarray(rgb).resize((mw, mh), Image.Resampling.BICUBIC))
        v["rgb_colour"] = cv2.resize(rgb, (mw, mh), interpolation=cv2.INTER_AREA)
        v["valid_model"] = cv2.resize((v["valid"] > 0).astype(np.float32), (mw, mh), interpolation=cv2.INTER_AREA) > 0.999
        if v["inside"] is not None:
            v["inside_model"] = cv2.resize((v["inside"] > 127).astype(np.float32), (mw, mh), interpolation=cv2.INTER_AREA) > 0.5
        else:
            v["inside_model"] = np.ones((mh, mw), bool)
    return mw, mh


# ---------------------------------------------------------------------------- inference


def run_vggt(views, weights: Path, threads: int):
    import torch
    from safetensors.torch import load_file
    from vggt.models.vggt import VGGT
    from vggt.utils.geometry import unproject_depth_map_to_point_map
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    torch.set_num_threads(threads)
    cfg = json.loads((weights / "config.json").read_text()) if (weights / "config.json").exists() else {}
    t0 = time.time()
    model = VGGT(**cfg)
    state = load_file(str(weights / "model.safetensors"))
    model.load_state_dict(state, strict=True)
    del state
    model.eval()
    t_load = time.time() - t0
    x = torch.from_numpy(np.stack([v["rgb_model"] for v in views])).permute(0, 3, 1, 2).float() / 255.0
    t1 = time.time()
    with torch.inference_mode():
        pred = model(x)
    t_inf = time.time() - t1
    mh, mw = x.shape[-2:]
    extr, intr = pose_encoding_to_extri_intri(pred["pose_enc"], (mh, mw))
    out = dict(
        pose_enc=pred["pose_enc"][0].numpy(),
        extrinsic=extr[0].numpy().astype(np.float64),
        intrinsic_model=intr[0].numpy().astype(np.float64),
        depth=pred["depth"][0, ..., 0].numpy(),
        depth_conf=pred["depth_conf"][0].numpy(),
        world_points=pred["world_points"][0].numpy(),
        world_points_conf=pred["world_points_conf"][0].numpy(),
    )
    out["points_from_depth"] = unproject_depth_map_to_point_map(
        pred["depth"][0].numpy(), out["extrinsic"], out["intrinsic_model"]
    ).astype(np.float32)
    del model, pred
    return out, dict(load_s=t_load, inference_s=t_inf, torch=torch.__version__, threads=threads)


def camera_summary(pred, W, H, mw, mh):
    """Full-res intrinsics, relative pose of cam1 w.r.t. cam0 (VGGT world = cam0)."""
    fov_h, fov_w = pred["pose_enc"][:, 7], pred["pose_enc"][:, 8]
    fx = (W / 2.0) / np.tan(fov_w / 2.0)
    fy = (H / 2.0) / np.tan(fov_h / 2.0)
    K_full = np.stack([np.array([[fx[i], 0, W / 2.0], [0, fy[i], H / 2.0], [0, 0, 1]]) for i in range(2)])
    R0, t0 = pred["extrinsic"][0][:, :3], pred["extrinsic"][0][:, 3]
    R1, t1 = pred["extrinsic"][1][:, :3], pred["extrinsic"][1][:, 3]
    C0, C1 = -R0.T @ t0, -R1.T @ t1
    R_rel = R1 @ R0.T  # cam0 coords -> cam1 coords
    base = R0 @ (C1 - C0)  # baseline in cam0 coords
    z0, z1 = R0[2], R1[2]  # optical axes in the VGGT world
    med_depth = [float(np.median(pred["depth"][i])) for i in range(2)]
    return dict(
        K_full=K_full,
        fx_full=fx,
        fy_full=fy,
        hfov_deg=np.degrees(fov_w),
        vfov_deg=np.degrees(fov_h),
        C_pred=np.stack([C0, C1]),
        R_rel=R_rel,
        t_rel=R1 @ (C0 - C1),
        baseline_pred=float(np.linalg.norm(C1 - C0)),
        baseline_dir_cam0=base / np.linalg.norm(base),
        rel_rot_deg=rot_angle_deg(R_rel),
        optical_axis_angle_deg=vec_angle_deg(z0, z1),
        median_depth_pred=med_depth,
    )


# ---------------------------------------------------------------------------- alignment


def align_to_metric(pred, cams_sum, reg, views, mw, mh, points_key):
    """Similarity pred -> metric from the two camera poses, then Umeyama with landmarks."""
    names = ["cam0", "cam1"]
    Rm = [reg["cams"][n]["R"] for n in names]
    Cm = np.stack([reg["cams"][n]["C"] for n in names])
    Rp = [pred["extrinsic"][i][:, :3] for i in range(2)]
    Cp = cams_sum["C_pred"]
    R_each = [Rm[i].T @ Rp[i] for i in range(2)]  # maps predicted-world vectors to metric
    R = project_so3(R_each[0] + R_each[1])
    mu_m, mu_p = Cm.mean(0), Cp.mean(0)
    dp = (Cp - mu_p) @ R.T
    s = float(((Cm - mu_m) * dp).sum() / (dp**2).sum())
    T = mu_m - s * R @ mu_p
    res = dict(
        method="camera poses (rotation chordal mean, scale/translation from centres)",
        s=s,
        R=R,
        T=T,
        rot_disagreement_deg=rot_angle_deg(R_each[0].T @ R_each[1]),
        cam_rot_err_deg=[rot_angle_deg(R.T @ R_each[i]) for i in range(2)],
        centre_err_mm=[float(np.linalg.norm(s * R @ Cp[i] + T - Cm[i])) for i in range(2)],
        baseline_metric_mm=float(np.linalg.norm(Cm[1] - Cm[0])),
        baseline_pred_scaled_mm=float(s * np.linalg.norm(Cp[1] - Cp[0])),
        baseline_dir_err_deg=vec_angle_deg(Cm[1] - Cm[0], R @ (Cp[1] - Cp[0])),
        optical_axis_angle_metric_deg=vec_angle_deg(Rm[0][2], Rm[1][2]),
    )
    res["baseline_ratio_pred_over_metric"] = res["baseline_pred_scaled_mm"] / res["baseline_metric_mm"]
    # Landmarks: sample the predicted point map at the (undistorted) landmark pixels.
    lms = []
    for lm in reg["landmarks"]:
        if lm["cam"] not in names:
            continue
        i = names.index(lm["cam"])
        v = views[i]
        uv = lm["uv"]
        if v["newK"] is not None:
            uv = undistort_pixels(reg["cams"][lm["cam"]], uv, v["newK"])[0]
        um, vm = (uv[0] + 0.5) * mw / v["W"] - 0.5, (uv[1] + 0.5) * mh / v["H"] - 0.5
        if not (0 <= um <= mw - 1 and 0 <= vm <= mh - 1):
            continue
        Xp = bilinear(pred[points_key][i], um, vm)
        conf = float(bilinear(pred["depth_conf"][i], um, vm))
        lms.append(dict(name=lm["name"], cam=lm["cam"], uv_model=[float(um), float(vm)], Xp=Xp, X=lm["X"], conf=conf))
    res["n_landmarks"] = len(lms)
    res["_lms"] = lms
    if lms:
        Xp = np.stack([l["Xp"] for l in lms])
        Xm = np.stack([l["X"] for l in lms])
        err_cam = np.linalg.norm((s * Xp @ R.T + T) - Xm, axis=1)
        res["landmark_err_mm_camera_fit"] = dict(
            median=float(np.median(err_cam)), mean=float(err_cam.mean()), max=float(err_cam.max())
        )
    # Per view (no relative pose involved): VGGT depth at that view's landmarks -> metric.
    res["per_view"] = {}
    for i, n in enumerate(names):
        sel = [l for l in lms if l["cam"] == n]
        if len(sel) < 3:
            continue
        Rp_i, tp_i = pred["extrinsic"][i][:, :3], pred["extrinsic"][i][:, 3]
        Xc = np.stack([Rp_i @ l["Xp"] + tp_i for l in sel])  # VGGT camera-i coordinates
        Xm_i = np.stack([l["X"] for l in sel])
        s_i, R_i, T_i = umeyama(Xc, Xm_i)
        err_i = np.linalg.norm(s_i * Xc @ R_i.T + T_i - Xm_i, axis=1)
        reg_c = reg["cams"][n]
        res["per_view"][n] = dict(
            n_landmarks=len(sel),
            s=s_i,
            landmark_err_mm=[float(e) for e in err_i],
            implied_centre_mm=T_i.tolist(),
            centre_vs_registered_mm=float(np.linalg.norm(T_i - reg_c["C"])),
            view_dir_vs_registered_deg=vec_angle_deg(R_i[:, 2], reg_c["R"][2]),
        )
    if len(lms) >= 3:
        src = np.vstack([Xp, Cp])
        dst = np.vstack([Xm, Cm])
        s2, R2, T2 = umeyama(src, dst)
        err = np.linalg.norm((s2 * Xp @ R2.T + T2) - Xm, axis=1)
        res["umeyama"] = dict(
            s=s2,
            R=R2,
            T=T2,
            landmark_err_mm=dict(median=float(np.median(err)), mean=float(err.mean()), max=float(err.max())),
            centre_err_mm=[float(np.linalg.norm(s2 * R2 @ Cp[i] + T2 - Cm[i])) for i in range(2)],
            per_landmark=[
                dict(name=l["name"], cam=l["cam"], err_mm=float(e), err_camera_fit_mm=float(ec), conf=l["conf"])
                for l, e, ec in zip(lms, err, err_cam)
            ],
        )
    return res


def per_view_metric(pred, views, reg, i, mw, mh, lms, s_default):
    """View i's VGGT depth along the calibrated (undistorted) rays, placed with its registered
    pose; one scale per view fitted to that view's landmarks (s_default if it has none)."""
    v, cam = views[i], reg["cams"][f"cam{i}"]
    S = np.array([[mw / v["W"], 0, 0.5 * mw / v["W"] - 0.5], [0, mh / v["H"], 0.5 * mh / v["H"] - 0.5], [0, 0, 1]])
    uu, vv = np.meshgrid(np.arange(mw, dtype=float), np.arange(mh, dtype=float))
    rays = np.stack([uu, vv, np.ones_like(uu)], -1) @ np.linalg.inv(S @ v["newK"]).T
    Xc = rays * pred["depth"][i][..., None].astype(np.float64)
    sel = [l for l in lms if l["cam"] == f"cam{i}"]
    if sel:
        P = np.stack([bilinear(Xc, *l["uv_model"]) for l in sel])
        Q = np.stack([cam["R"] @ (l["X"] - cam["C"]) for l in sel])  # landmarks in camera coords, mm
        s_i = float((P * Q).sum() / (P**2).sum())
        err = np.linalg.norm(s_i * P - Q, axis=1)
    else:
        s_i, err = s_default, np.zeros(0)
    Xm = s_i * Xc @ cam["R"] + cam["C"]
    return Xm, dict(s=s_i, n_landmarks=len(sel), landmark_err_mm=[float(e) for e in err],
                    landmark_names=[l["name"] for l in sel])


# ------------------------------------------------------------------------------ export


def depth_edges(depth: np.ndarray, rel: float) -> np.ndarray:
    """True where the relative depth jump to a 4-neighbour exceeds `rel` (flying pixels)."""
    d = depth
    jump = np.zeros_like(d)
    jump[:, 1:] = np.maximum(jump[:, 1:], np.abs(d[:, 1:] - d[:, :-1]))
    jump[:, :-1] = np.maximum(jump[:, :-1], np.abs(d[:, 1:] - d[:, :-1]))
    jump[1:] = np.maximum(jump[1:], np.abs(d[1:] - d[:-1]))
    jump[:-1] = np.maximum(jump[:-1], np.abs(d[1:] - d[:-1]))
    return jump / np.maximum(d, 1e-9) > rel


def fit_plane_ransac(xyz, tol, iters=400, seed=0, axis=None, max_tilt_deg=90.0):
    """Dominant plane: unit normal n, offset d (n.x + d = 0), inlier mask. With `axis`, only
    planes whose normal is within max_tilt_deg of it are considered (e.g. the deck vs +z)."""
    rng = np.random.default_rng(seed)
    best = (None, None, np.zeros(len(xyz), bool))
    for _ in range(iters):
        p = xyz[rng.choice(len(xyz), 3, replace=False)]
        n = np.cross(p[1] - p[0], p[2] - p[0])
        if np.linalg.norm(n) < 1e-12:
            continue
        n /= np.linalg.norm(n)
        if axis is not None and vec_angle_deg(np.abs(n @ axis) * n / (n @ axis), axis) > max_tilt_deg:
            continue
        inl = np.abs(xyz @ n - n @ p[0]) < tol
        if inl.sum() > best[2].sum():
            best = (n, -n @ p[0], inl)
    n, d, inl = best
    c = xyz[inl].mean(0)  # least-squares refit on the inliers
    n = np.linalg.svd(xyz[inl] - c, full_matrices=False)[2][2]
    d = -n @ c
    return n, d, np.abs(xyz @ n + d) < tol


def voxel_downsample(xyz, rgb, voxel):
    keys = np.floor(xyz / voxel).astype(np.int64)
    keys -= keys.min(0)
    dims = keys.max(0) + 1
    lin = (keys[:, 0] * dims[1] + keys[:, 1]) * dims[2] + keys[:, 2]
    _, inv, cnt = np.unique(lin, return_inverse=True, return_counts=True)
    xyz_o = np.stack([np.bincount(inv, xyz[:, k]) for k in range(3)], 1) / cnt[:, None]
    rgb_o = np.stack([np.bincount(inv, rgb[:, k].astype(np.float64)) for k in range(3)], 1) / cnt[:, None]
    return xyz_o, np.clip(np.round(rgb_o), 0, 255).astype(np.uint8)


def write_ply(path: Path, xyz, rgb, comments=()):
    arr = np.empty(len(xyz), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    arr["x"], arr["y"], arr["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    arr["r"], arr["g"], arr["b"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    header = ["ply", "format binary_little_endian 1.0"]
    header += [f"comment {c}" for c in comments]
    header += [
        f"element vertex {len(xyz)}",
        "property float x",
        "property float y",
        "property float z",
        "property uchar red",
        "property uchar green",
        "property uchar blue",
        "end_header",
    ]
    with open(path, "wb") as f:
        f.write(("\n".join(header) + "\n").encode())
        arr.tofile(f)


def frustum(K, R, C, W, H, depth):
    corners = np.array([[0, 0, 1], [W, 0, 1], [W, H, 1], [0, H, 1]], float)
    rays = (np.linalg.inv(K) @ corners.T).T
    pts = C + (rays * depth) @ R  # R is world->camera, so camera->world is R.T (row form)
    return pts


def render(path: Path, xyz, rgb, frusta, elev, azim, title, unit, max_pts=220_000, max_bytes=1_000_000):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    rng = np.random.default_rng(0)
    idx = rng.choice(len(xyz), min(len(xyz), max_pts), replace=False)
    fig = plt.figure(figsize=(10, 8), dpi=110)
    ax = fig.add_subplot(projection="3d")
    ax.scatter(*xyz[idx].T, c=rgb[idx] / 255.0, s=1.0, marker=".", linewidths=0, depthshade=False)
    allp = [xyz]
    for fr in frusta:
        C, P, col, ls, lab = fr["C"], fr["corners"], fr["colour"], fr["ls"], fr["label"]
        for p in P:
            ax.plot(*np.stack([C, p]).T, color=col, lw=1.2, ls=ls)
        ax.plot(*np.vstack([P, P[:1]]).T, color=col, lw=1.2, ls=ls, label=lab)
        allp += [C[None], P]
    lo = np.percentile(np.vstack(allp), 0.5, axis=0)
    hi = np.percentile(np.vstack(allp), 99.5, axis=0)
    lo = np.minimum(lo, np.vstack([np.vstack([f["C"][None], f["corners"]]) for f in frusta]).min(0))
    hi = np.maximum(hi, np.vstack([np.vstack([f["C"][None], f["corners"]]) for f in frusta]).max(0))
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(hi - lo)
    ax.view_init(elev=elev, azim=azim)
    ax.set_xlabel(f"x ({unit})")
    ax.set_ylabel(f"y ({unit})")
    ax.set_zlabel(f"z ({unit})")
    if abs(elev) > 80:  # top view: the z axis is edge-on, drop its clutter
        ax.set_zticks([])
        ax.set_zlabel("")
    ax.set_title(title, fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    if path.stat().st_size > max_bytes:
        im = Image.open(path).convert("RGB")
        im.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)
    return path.stat().st_size


# --------------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cam0", type=Path, required=True)
    ap.add_argument("--cam1", type=Path, required=True)
    ap.add_argument("--mask0", type=Path, help="cam0 inside-glovebox mask (white = inside)")
    ap.add_argument("--mask1", type=Path, help="cam1 inside-glovebox mask (white = inside)")
    ap.add_argument("--registration", type=Path, help="registration.json (K, distortion, R, t in mm)")
    ap.add_argument("--raw", action="store_true", help="feed raw frames even when calibrated")
    ap.add_argument("--max-landmark-err-px", type=float, default=50.0,
                    help="skip landmarks whose registration reprojection error (err_px) exceeds this")
    ap.add_argument("--undistort-focal-scale", type=float, default=0.8,
                    help="focal of the undistorted pinhole relative to the calibrated K")
    ap.add_argument("--weights", type=Path, default=Path("/tmp/aurora-vision/dense/models/VGGT-1B"))
    ap.add_argument("--work-dir", type=Path, default=Path("/tmp/aurora-vision/dense"))
    ap.add_argument("--out-dir", type=Path, help="PLY + renders (default: <work-dir>/out)")
    ap.add_argument("--tag", default="", help="suffix for the npz/json in work-dir")
    ap.add_argument("--reuse", action="store_true", help="reuse predictions from the npz")
    ap.add_argument("--fusion", choices=["joint", "per-view"], default="joint",
                    help="joint: one similarity (VGGT relative pose); per-view: each view's depth on its "
                         "registered pose, scale from its landmarks")
    ap.add_argument("--points", choices=["depth", "pointmap"], default="depth",
                    help="depth+camera unprojection (VGGT's recommended) or the point head")
    ap.add_argument("--conf-percentile", type=float, default=30.0,
                    help="drop the lowest N%% depth confidences among inside pixels")
    ap.add_argument("--edge-rel", type=float, default=0.05, help="flying-pixel relative depth jump")
    ap.add_argument("--voxel", type=float, default=3.0, help="voxel size, mm (model frame: x 1e-3 of scene)")
    ap.add_argument("--crop-margin", type=float, default=150.0,
                    help="metric mode: drop points further than this (mm) outside the interior box")
    ap.add_argument("--interior", type=float, nargs=3, default=[1200.0, 1120.0, 790.0],
                    help="interior box size (mm), from the origin of the metric frame")
    ap.add_argument("--max-ply-bytes", type=int, default=8_000_000)
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    out_dir = args.out_dir or args.work_dir / "out"
    reg = load_registration(args.registration, max_err_px=args.max_landmark_err_px)
    views = prepare_views(args, reg)
    mw, mh = to_model_res(views)
    W, H = views[0]["W"], views[0]["H"]
    undist = views[0]["newK"] is not None
    tag = args.tag or ("undistorted" if undist else "raw")
    npz_path = args.work_dir / f"vggt_two_view_{tag}.npz"

    if args.reuse and npz_path.exists():
        z = np.load(npz_path)
        pred = {k: z[k] for k in ["pose_enc", "extrinsic", "intrinsic_model", "depth", "depth_conf",
                                  "world_points", "world_points_conf", "points_from_depth"]}
        timing = json.loads(str(z["timing"]))
    else:
        pred, timing = run_vggt(views, args.weights, args.threads)
    cs = camera_summary(pred, W, H, mw, mh)
    np.savez_compressed(
        npz_path,
        **pred,
        intrinsic_full=cs["K_full"],
        C_pred=cs["C_pred"],
        R_rel_cam0_to_cam1=cs["R_rel"],
        t_rel_cam0_to_cam1=cs["t_rel"],
        baseline_dir_cam0=cs["baseline_dir_cam0"],
        images_model=np.stack([v["rgb_model"] for v in views]),
        inside_model=np.stack([v["inside_model"] for v in views]),
        valid_model=np.stack([v["valid_model"] for v in views]),
        undistorted=undist,
        pinhole_full=np.stack([v["newK"] for v in views]) if undist else np.zeros((2, 3, 3)),
        full_size_wh=np.array([W, H]),
        model_size_wh=np.array([mw, mh]),
        timing=json.dumps(timing),
    )
    summary = dict(
        input="undistorted" if undist else "raw",
        model="facebook/VGGT-1B (rev 860abec), CC BY-NC 4.0",
        model_size_wh=[mw, mh],
        timing=timing,
        fx_full_px=cs["fx_full"].tolist(),
        fy_full_px=cs["fy_full"].tolist(),
        hfov_deg=cs["hfov_deg"].tolist(),
        vfov_deg=cs["vfov_deg"].tolist(),
        baseline_dir_cam0=cs["baseline_dir_cam0"].tolist(),
        rel_rot_deg=cs["rel_rot_deg"],
        optical_axis_angle_deg=cs["optical_axis_angle_deg"],
        baseline_pred=cs["baseline_pred"],
        median_depth_pred=cs["median_depth_pred"],
    )
    if undist:
        summary["pinhole_fx_full_px"] = [float(v["newK"][0, 0]) for v in views]
        summary["registered_fx_px"] = [float(reg["cams"][n]["K"][0, 0]) for n in ("cam0", "cam1")]

    pts_key = "points_from_depth" if args.points == "depth" else "world_points"
    conf_key = "depth_conf" if args.points == "depth" else "world_points_conf"
    align = None
    if reg is not None:
        align = align_to_metric(pred, cs, reg, views, mw, mh, pts_key)
        summary["alignment"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                                for k, v in align.items() if k != "umeyama" and not k.startswith("_")}
        if "umeyama" in align:
            summary["alignment"]["umeyama"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                                               for k, v in align["umeyama"].items()}

    # ---- filter + transform points
    xyz_l, rgb_l, keep_stats = [], [], []
    inside_conf = np.concatenate([pred[conf_key][i][views[i]["inside_model"] & views[i]["valid_model"]]
                                  for i in range(2)])
    thr = float(np.percentile(inside_conf, args.conf_percentile))
    per_view = args.fusion == "per-view" and align is not None and undist
    if args.fusion == "per-view" and not per_view:
        raise SystemExit("--fusion per-view needs --registration and undistorted input")
    summary["fusion"] = "per-view (registered poses, VGGT depth)" if per_view else "joint (VGGT relative pose)"
    pv_fit = {}
    for i, v in enumerate(views):
        keep = v["inside_model"] & v["valid_model"] & (pred[conf_key][i] >= thr)
        keep &= ~depth_edges(pred["depth"][i], args.edge_rel)
        keep_stats.append(dict(inside=int((v["inside_model"] & v["valid_model"]).sum()), kept=int(keep.sum())))
        if per_view:
            Xm, pv_fit[f"cam{i}"] = per_view_metric(pred, views, reg, i, mw, mh, align["_lms"], align["s"])
            xyz_l.append(Xm[keep])
        else:
            xyz_l.append(pred[pts_key][i][keep].astype(np.float64))
        rgb_l.append(v["rgb_colour"][keep])
    view_id = np.concatenate([np.full(len(x), i) for i, x in enumerate(xyz_l)])
    xyz, rgb = np.vstack(xyz_l), np.vstack(rgb_l)
    summary["conf_threshold"] = thr
    summary["points_per_view"] = keep_stats
    if align is not None:
        fit = align.get("umeyama", align)
        s, R, T = fit["s"], fit["R"], fit["T"]
        summary["export_alignment"] = "umeyama (landmarks + centres)" if "umeyama" in align else "camera poses"
        if per_view:
            summary["export_alignment"] = "per view: registered pose + landmark scale"
            summary["per_view_fusion"] = pv_fit
        else:
            xyz = s * xyz @ R.T + T
        unit, voxel = "mm", args.voxel
        box = np.array(args.interior)
        inb = np.all((xyz >= -args.crop_margin) & (xyz <= box + args.crop_margin), axis=1)
        summary["dropped_outside_box"] = int((~inb).sum())
        xyz, rgb, view_id = xyz[inb], rgb[inb], view_id[inb]
        # Independent check: the largest roughly horizontal plane should be the deck, z = 0.
        n, d, inl = fit_plane_ransac(xyz, tol=10.0, iters=1500, axis=np.array([0, 0, 1.0]), max_tilt_deg=35.0)
        n, d = (n, d) if n[2] > 0 else (-n, -d)
        summary["deck_plane_check"] = dict(normal=n.tolist(), tilt_from_z_deg=vec_angle_deg(n, np.array([0, 0, 1.0])),
                                           median_z_inliers_mm=float(np.median(xyz[inl, 2])),
                                           inlier_fraction=float(inl.mean()))
        render_tf = None
        frusta = []
        for i, n in enumerate(("cam0", "cam1")):
            Rp, Cp = pred["extrinsic"][i][:, :3], cs["C_pred"][i]
            if not per_view:
                frusta.append(dict(C=s * R @ Cp + T, corners=frustum(cs["K_full"][i], Rp @ R.T, s * R @ Cp + T, W, H, 150.0),
                                   colour=CAM_COLOURS[i], ls="-", label=f"{n} VGGT (aligned)"))
            cm = reg["cams"][n]
            Kr = views[i]["newK"] if undist else cm["K"]
            frusta.append(dict(C=cm["C"], corners=frustum(Kr, cm["R"], cm["C"], W, H, 150.0),
                               colour=CAM_COLOURS[i], ls="-" if per_view else "--", label=f"{n} registered"))
    else:
        unit = "VGGT units"
        scale = float(np.median([np.median(pred["depth"][i]) for i in range(2)]))
        voxel = args.voxel * 1e-3 * scale
        frusta = [dict(C=cs["C_pred"][i], corners=frustum(cs["K_full"][i], pred["extrinsic"][i][:, :3],
                                                         cs["C_pred"][i], W, H, 0.15 * scale),
                       colour=CAM_COLOURS[i], ls="-", label=f"cam{i} VGGT") for i in range(2)]
        # Renders only: rotate into a deck-aligned frame (z = deck normal towards the cameras,
        # x = baseline projected on the deck). The PLY stays in VGGT's frame.
        n, d, inl = fit_plane_ransac(xyz, tol=0.01 * scale)
        if np.mean(cs["C_pred"] @ n + d) < 0:
            n, d = -n, -d
        bx = cs["C_pred"][1] - cs["C_pred"][0]
        bx -= (bx @ n) * n
        bx /= np.linalg.norm(bx)
        Rr = np.stack([bx, np.cross(n, bx), n])
        o = xyz[inl].mean(0)
        render_tf = lambda P: (np.atleast_2d(P) - o) @ Rr.T  # noqa: E731
        summary["deck_plane_model_frame"] = dict(normal=n.tolist(), offset=float(d), inlier_fraction=float(inl.mean()))
    summary["points_before_voxel"] = int(len(xyz))

    if not args.no_export:
        out_dir.mkdir(parents=True, exist_ok=True)
        ply = out_dir / "glovebox_two_view.ply"
        while True:
            xyz_d, rgb_d = voxel_downsample(xyz, rgb, voxel)
            if 15 * len(xyz_d) + 1000 <= args.max_ply_bytes:
                break
            voxel *= 1.25
        comments = [
            "VGGT-1B two-view reconstruction (facebook/VGGT-1B, CC BY-NC 4.0)",
            f"frame: {'glovebox model metric frame, mm' if align is not None else 'VGGT cam0 frame, unit-free'}",
            f"voxel {voxel:.4g} {unit}",
            f"fusion: {summary['fusion']}",
        ]
        if align is not None:
            if per_view:
                errs = [e for f in pv_fit.values() for e in f["landmark_err_mm"]]
            else:
                errs = align["umeyama"]["landmark_err_mm"]["median"] if "umeyama" in align else \
                    align.get("landmark_err_mm_camera_fit", {}).get("median", np.nan)
            comments.append(f"alignment: {summary['export_alignment']}, landmark error median "
                            f"{float(np.median(errs)):.0f} mm")
        write_ply(ply, xyz_d, rgb_d, comments)
        summary["ply"] = dict(path=str(ply), points=int(len(xyz_d)), bytes=ply.stat().st_size, voxel=voxel)
        renders = []
        if align is not None:
            views_spec = [("top", 90, -90, "top view (looking down -z)"),
                          ("oblique_cam0_side", 35, -125, "oblique view"),
                          ("oblique_cam1_side", 35, 55, "oblique view, opposite side")]
        else:
            views_spec = [("top", 90, -90, "deck-aligned VGGT frame, top view"),
                          ("oblique", 35, -60, "deck-aligned VGGT frame, oblique")]
        pts_r, fr_r = xyz_d, frusta
        if render_tf is not None:
            pts_r = render_tf(xyz_d)
            fr_r = [dict(f, C=render_tf(f["C"])[0], corners=render_tf(f["corners"])) for f in frusta]
        for nm, el, az, ttl in views_spec:
            p = out_dir / f"glovebox_two_view_{nm}.png"
            size = render(p, pts_r, rgb_d, fr_r, el, az,
                          f"Glovebox interior, VGGT-1B ({summary['input']} frames, {summary['fusion'].split(' (')[0]} "
                          f"fusion): {ttl}", unit)
            renders.append(dict(path=str(p), bytes=size))
        summary["renders"] = renders

    (args.work_dir / f"summary_{tag}_{args.fusion}.json").write_text(json.dumps(summary, indent=2, default=float))
    print(json.dumps(summary, indent=2, default=float))


if __name__ == "__main__":
    main()
