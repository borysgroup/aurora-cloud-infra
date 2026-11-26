"""Render the reconstruction from each calibrated camera (with the lens distortion applied), so it can be
laid over the camera's own frame, and from an outside viewpoint for an overview."""
import os

import cv2
import numpy as np
import pyvista as pv

from cameras import C, LAM, CAM0, CAM1  # noqa: F401
from lensmodel import undistort_px

pv.OFF_SCREEN = True
W, H = 1920, 1080
CANVAS = (3840, 2160)   # pinhole canvas, same focal length; covers the undistorted frame corners


def _plotter(parts, size, bg="white"):
    pl = pv.Plotter(off_screen=True, window_size=size)
    pl.set_background(bg)
    for p in parts:
        m = pv.wrap(p.mesh)
        pl.add_mesh(m, color=p.color, smooth_shading=False, specular=0.15, ambient=0.25, diffuse=0.75)
    return pl


_maps = None


def _distort_maps():
    global _maps
    if _maps is None:
        uu, vv = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
        pu = undistort_px(np.c_[uu.ravel(), vv.ravel()], C, LAM)
        mx = (pu[:, 0] - C[0] + (CANVAS[0] - 1) / 2).reshape(H, W).astype(np.float32)
        my = (pu[:, 1] - C[1] + (CANVAS[1] - 1) / 2).reshape(H, W).astype(np.float32)
        _maps = (mx, my)
    return _maps


def render_camera(parts, cam):
    """RGB render (H x W x 3, uint8) as camera `cam` sees it, and a mask of where geometry is."""
    pl = _plotter(parts, CANVAS, bg="black")
    fwd, down = cam.R[2], cam.R[1]
    pl.camera.position = cam.centre.tolist()
    pl.camera.focal_point = (cam.centre + 1000 * fwd).tolist()
    pl.camera.up = (-down).tolist()
    pl.camera.view_angle = float(np.degrees(2 * np.arctan((CANVAS[1] / 2) / cam.f)))
    pl.camera.clipping_range = (20, 6000)
    pl.enable_lightkit()
    img = pl.screenshot(return_img=True)
    depth = pl.get_image_depth(fill_value=np.nan)
    pl.close()
    mask = (~np.isnan(depth)).astype(np.uint8) * 255
    mx, my = _distort_maps()
    out = cv2.remap(img[:, :, :3], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    m = cv2.remap(mask, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    return out[:, :, ::-1].copy(), m   # BGR for OpenCV


def overlay(photo_bgr, render_bgr, mask, alpha=0.55):
    out = photo_bgr.copy()
    sel = mask > 0
    out[sel] = (alpha * render_bgr[sel] + (1 - alpha) * photo_bgr[sel]).astype(np.uint8)
    edges = cv2.Canny(cv2.cvtColor(render_bgr, cv2.COLOR_BGR2GRAY), 40, 120)
    out[edges > 0] = (0, 255, 255)
    return out


def render_view(parts, position, focal, up=(0, 0, 1), size=(1920, 1080), view_angle=35.0, extra=None):
    pl = _plotter(parts, size)
    if extra:
        for mesh, color in extra:
            pl.add_mesh(mesh, color=color)
    pl.camera.position, pl.camera.focal_point, pl.camera.up = position, focal, up
    pl.camera.view_angle = view_angle
    pl.enable_lightkit()
    img = pl.screenshot(return_img=True)
    pl.close()
    return img[:, :, :3][:, :, ::-1].copy()


def draw_edges(photo_bgr, parts, cam, color=(0, 255, 255), angle_deg=25.0, groups=None):
    """Project each part's sharp mesh edges into the (distorted) frame: a fast alignment check."""
    out = photo_bgr.copy()
    for p in parts:
        if groups and p.group not in groups:
            continue
        m = p.mesh
        try:
            sharp = m.face_adjacency_edges[m.face_adjacency_angles > np.radians(angle_deg)]
        except Exception:
            continue
        if len(sharp) == 0:
            continue
        P = m.vertices[sharp.reshape(-1)]
        # densify long edges so the distortion bends them correctly
        a, b = P[0::2], P[1::2]
        n = np.maximum(2, (np.linalg.norm(b - a, axis=1) / 15).astype(int))
        for ai, bi, ni in zip(a, b, n):
            s = np.linspace(0, 1, ni)[:, None]
            Q = ai + (bi - ai) * s
            uv, z = cam.project(Q)
            ok = (z > 30) & (np.abs(uv) < 5000).all(axis=1)
            for k in range(len(Q) - 1):
                if ok[k] and ok[k + 1]:
                    cv2.line(out, tuple(np.round(uv[k]).astype(int)), tuple(np.round(uv[k + 1]).astype(int)), color,
                             1, cv2.LINE_AA)
    return out
