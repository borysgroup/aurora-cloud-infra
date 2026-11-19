"""Fit a part's pose to its silhouette: rasterise the projected triangles (distorted frame) and compare
with a SAM mask of the same object."""
import cv2
import numpy as np


def raster(parts, cam, shape=(1080, 1920), groups=None):
    m = np.zeros(shape, np.uint8)
    for p in parts:
        if groups and p.group not in groups:
            continue
        V, Fc = p.mesh.vertices, p.mesh.faces
        uv, z = cam.project(V)
        ok = z > 30
        tri = uv[Fc]
        good = ok[Fc].all(axis=1) & (np.abs(tri) < 6000).all(axis=(1, 2))
        pts = np.round(tri[good] * 4).astype(np.int32)    # 2 bits of sub-pixel precision
        for t in pts:
            cv2.fillConvexPoly(m, t, 255, lineType=cv2.LINE_8, shift=2)
    return m


def iou(a, b, region=None):
    a, b = a > 0, b > 0
    if region is not None:
        a, b = a & region, b & region
    u = (a | b).sum()
    return (a & b).sum() / u if u else 0.0
