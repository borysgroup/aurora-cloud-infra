"""Draw Epson's own T6-B602S CAD (reconstruction/epson_cad.py) through a calibrated Amcrest camera, lens
distortion included: a shaded image and an exact mask of the robot in any joint pose.

Painter's algorithm: every triangle is projected with the camera's division model, given a flat
Lambert-plus-specular shade from a light chosen by the caller, sorted far to near and filled with
OpenCV at 2x, then box-filtered down. Fast (about 0.1 s for the whole robot at 1350 x 700) and needs
no OpenGL. Accurate enough for training data and silhouettes, not for photorealism.
"""
import json
import os
import sys

import cv2
import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "reconstruction"))
import epson_cad as E  # noqa: E402
from cameras import CAM0, CAM1  # noqa: E402

CAMS = {0: CAM0, 1: CAM1}
POSE_FILE = os.path.join(HERE, "..", "out", "epson_pose.json")
LINK_RGB = dict(base=(212, 218, 213), arm1=(212, 218, 213), arm2=(212, 218, 213), shaft=(200, 204, 206),
                cable=(32, 32, 32), unit=(21, 21, 21), tool=(60, 60, 60))


def fitted_pose():
    """Base pose and parked joints fitted by fit_pose.py (falls back to scene.py's hand fit)."""
    if os.path.exists(POSE_FILE):
        p = json.load(open(POSE_FILE))
        return dict(j1=tuple(p["base"]["j1"]), z0=p["base"]["z0"], yaw=p["base"]["yaw"]), p["parked"]
    from scene import ROBOT
    pose, j1, j2 = E.from_scene_robot(ROBOT)
    return pose, dict(j1=j1, j2=j2, z=0.0, u=0.0)


def tool_mesh(size=(40.0, 40.0, 50.0)):
    """A stand-in end effector under the shaft (the real tool is not in Epson's CAD)."""
    b = trimesh.creation.box(extents=size)
    b.apply_translation((E.L1 + E.L2, 0.0, 173.5 - size[2] / 2))
    return b


def posed_meshes(pose, j1, j2, z=0.0, u=0.0, tool=None):
    from scene import GB_H
    ms = E.posed(pose, j1, j2, z, u, ceiling=GB_H)
    if tool is not None:
        B = E.base_transform(pose)
        L = E.link_transforms(j1, j2, z, u)
        ms["tool"] = tool.copy().apply_transform(B @ L["shaft"])
    return ms


def project(cam, V, dR=None):
    """Distorted pixel coordinates and camera depth of world points; dR perturbs the camera rotation."""
    if dR is None:
        return cam.project(V)
    R0 = cam.R
    cam.R = dR @ R0
    try:
        return cam.project(V)
    finally:
        cam.R = R0


def render(meshes, cam, crop, out_size, colors=None, light=(0.3, -0.4, 1.0), ambient=0.45, diffuse=0.6,
           spec=0.25, shininess=12.0, dR=None, ss=2):
    """Render meshes ({name: trimesh}) inside crop = (x0, y0, x1, y1) of the 1920 x 1080 frame, resized to
    out_size = (w, h). Returns (bgr uint8, alpha float32 in 0..1)."""
    colors = colors or {}
    x0, y0, x1, y1 = crop
    w, h = out_size
    sx, sy = w * ss / (x1 - x0), h * ss / (y1 - y0)
    canvas = np.zeros((h * ss, w * ss, 3), np.uint8)
    mask = np.zeros((h * ss, w * ss), np.uint8)
    L = np.asarray(light, float)
    L /= np.linalg.norm(L)
    tris, depth, cols = [], [], []
    for name, m in meshes.items():
        V, F = m.vertices, m.faces
        uv, z = project(cam, V, dR)
        tri = uv[F]
        zf = z[F]
        ok = (zf > 30).all(axis=1) & (np.abs(tri) < 8000).all(axis=(1, 2))
        n = m.face_normals
        c = V[F].mean(axis=1)
        v = cam.centre - c
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        n = n * np.sign((n * v).sum(1, keepdims=True) + 1e-9)          # two-sided
        lam = np.clip(n @ L, 0, 1)
        r = 2 * (n @ L)[:, None] * n - L
        sp = np.clip((r * v).sum(1), 0, 1) ** shininess
        base = np.asarray(colors.get(name, LINK_RGB.get(name, (200, 200, 200))), float)[::-1]   # BGR
        shade = base[None, :] * (ambient + diffuse * lam)[:, None] + 255 * spec * sp[:, None]
        tris.append(tri[ok])
        depth.append(zf[ok].mean(axis=1))
        cols.append(np.clip(shade[ok], 0, 255))
    if not tris:
        return np.zeros((h, w, 3), np.uint8), np.zeros((h, w), np.float32)
    tri = np.concatenate(tris)
    dep = np.concatenate(depth)
    col = np.concatenate(cols)
    order = np.argsort(-dep)
    P = np.empty_like(tri)
    P[..., 0] = (tri[..., 0] - x0) * sx
    P[..., 1] = (tri[..., 1] - y0) * sy
    P = np.round(P * 4).astype(np.int32)          # 2 bits of sub-pixel precision
    lim = 4 * 4 * max(w, h) * ss
    for i in order:
        t = P[i]
        if (np.abs(t) > lim).any():
            continue
        cv2.fillConvexPoly(canvas, t, col[i].tolist(), lineType=cv2.LINE_8, shift=2)
        cv2.fillConvexPoly(mask, t, 255, lineType=cv2.LINE_8, shift=2)
    img = cv2.resize(canvas, (w, h), interpolation=cv2.INTER_AREA)
    a = cv2.resize(mask, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    return img, a


def silhouette(meshes, cam, shape=(1080, 1920), scale=1.0, dR=None):
    """Binary mask (uint8 0/255) of the meshes in the full frame, optionally at a reduced scale."""
    h, w = int(round(shape[0] * scale)), int(round(shape[1] * scale))
    m = np.zeros((h, w), np.uint8)
    for mesh in meshes.values():
        uv, z = project(cam, mesh.vertices, dR)
        tri = uv[mesh.faces] * scale
        good = (z[mesh.faces] > 30).all(axis=1) & (np.abs(tri) < 8000).all(axis=(1, 2))
        for t in np.round(tri[good] * 4).astype(np.int32):
            cv2.fillConvexPoly(m, t, 255, lineType=cv2.LINE_8, shift=2)
    return m
