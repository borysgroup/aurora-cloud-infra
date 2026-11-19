"""Blur what a still shows outside the glovebox, and blur faces, before it is published.

1. Faces: deface's CenterFace detector (https://github.com/ORB-HD/deface) runs on the
   whole, unmodified frame, and each detection is blurred with an ellipse, as the
   `deface` CLI does.
2. Outside the glovebox: the hand-drawn polygons in outside_glovebox.json (one set per
   camera, for the fixed views) get a heavy Gaussian blur with a feathered edge. The
   camera's burned-in date and time are kept legible.

    pip install deface onnxruntime opencv-python-headless numpy
    python privacy_blur.py --cam 0 IN.jpg OUT.jpg [--mask-out INSIDE.png]

Prints how many faces were blurred.
"""
import argparse
import json
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
POLYGONS = os.path.join(HERE, "outside_glovebox.json")
OSD_TIME_BOX = (1300, 30, 1860, 105)  # x0, y0, x1, y1 of the burned-in date/time at 1920x1080


def outside_mask(cam, shape, path=POLYGONS):
    """uint8 mask, 255 where the image shows the room outside the glovebox."""
    polys = json.load(open(path))[f"cam{cam}"]
    sx, sy = shape[1] / 1920.0, shape[0] / 1080.0
    m = np.zeros(shape[:2], np.uint8)
    for p in polys:
        cv2.fillPoly(m, [np.round(np.array(p, float) * (sx, sy)).astype(np.int32)], 255)
    return m


def blur_faces(img, threshold=0.2, mask_scale=1.3):
    from deface.centerface import CenterFace
    from deface.deface import anonymize_frame

    dets, _ = CenterFace(in_shape=(img.shape[1], img.shape[0]), backend="auto")(img, threshold=threshold)
    out = img.copy()
    anonymize_frame(dets, out, mask_scale=mask_scale, replacewith="blur", ellipse=True, draw_scores=False,
                    replaceimg=None, mosaicsize=20)
    return out, len(dets)


def blur_outside(img, outside, ksize=151, feather=31):
    blurred = cv2.GaussianBlur(img, (ksize, ksize), 0)
    blurred = cv2.GaussianBlur(blurred, (ksize, ksize), 0)
    a = cv2.GaussianBlur(outside, (feather, feather), 0).astype(np.float32)[..., None] / 255.0
    a = np.maximum(a, (outside[..., None] > 0).astype(np.float32))  # fully blurred inside the polygons
    out = (img.astype(np.float32) * (1 - a) + blurred.astype(np.float32) * a).astype(np.uint8)
    # keep the burned-in date/time: near-white glyphs plus their dark outline
    x0, y0, x1, y1 = OSD_TIME_BOX
    roi = img[y0:y1, x0:x1]
    glyph = (roi.min(axis=2) > 235).astype(np.uint8)
    glyph = cv2.dilate(glyph, np.ones((3, 3), np.uint8), iterations=2).astype(bool)
    out[y0:y1, x0:x1][glyph] = roi[glyph]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cam", type=int, required=True, choices=(0, 1))
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--face-threshold", type=float, default=0.2)
    ap.add_argument("--mask-out", help="also write the inside-the-glovebox mask (white = inside) here")
    ap.add_argument("--quality", type=int, default=90)
    a = ap.parse_args()
    img = cv2.imread(a.src)
    outside = outside_mask(a.cam, img.shape)
    faced, n = blur_faces(img, a.face_threshold)
    out = blur_outside(faced, outside)
    cv2.imwrite(a.dst, out, [cv2.IMWRITE_JPEG_QUALITY, a.quality])
    if a.mask_out:
        cv2.imwrite(a.mask_out, 255 - outside)
    print(f"cam{a.cam}: {n} face(s) blurred, {100 * (outside > 0).mean():.0f} % of the frame outside the glovebox")


if __name__ == "__main__":
    main()
