"""Blur everything in a still that is not the inside of the glovebox, and any face, before publishing.

The rule is "sharp only where we know it is the glovebox interior"; anything else is blurred.

1. Static interior: masks/inside_camN.png, built once per camera view by build_inside_mask.py
   from hand-drawn polygons and SAM 2.1 outlines of the fixed equipment (inside_masks.json).
2. The Epson, wherever it is: SAM 2.1 runs on every frame with point prompts on the robot's
   fixed base, so the arm is segmented in its current pose. Only the part inside the camera's
   robot_zone is kept. If the segmentation misses the arm, the arm is blurred, never the room.
3. Change guard: interior pixels that differ from masks/reference_camN.jpg, in a blob that
   touches the blurred region, are blurred too. That catches equipment that has been moved or
   removed from in front of a window (which would otherwise expose the room through the mask)
   without blurring ordinary motion in the middle of the deck.
4. Faces: deface's CenterFace detector (https://github.com/ORB-HD/deface) on the whole,
   unmodified frame; each detection gets an elliptical blur.
5. The camera's burned-in date and time are kept: only small, near-white glyph strokes with a
   dark outline are copied back, so no patch of a bright background comes through with them.

    pip install deface onnxruntime opencv-python-headless numpy ultralytics
    python privacy_blur.py --cam 0 IN.jpg OUT.jpg [--mask-out INSIDE.png] [--no-robot] [--no-guard]

Prints the share of the frame kept sharp, the robot and guard pixel counts, and the face count.
"""
import argparse
import json
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "inside_masks.json")
MASK_DIR = os.path.join(HERE, "masks")
OSD_TIME_BOX = (1300, 30, 1860, 105)  # x0, y0, x1, y1 of the burned-in date/time at 1920x1080
SAM_WEIGHTS = os.environ.get("SAM_WEIGHTS", "sam2.1_b.pt")  # ultralytics downloads it on first use

_sam = None


def spec(cam):
    return json.load(open(SPEC))[f"cam{cam}"]


def poly_mask(shape, polys):
    """uint8 mask, 255 inside any of the polygons (lists of [x, y], or 'ellipse cx cy ax ay')."""
    m = np.zeros(shape[:2], np.uint8)
    sx, sy = shape[1] / 1920.0, shape[0] / 1080.0
    for p in polys:
        if isinstance(p, str) and p.startswith("ellipse"):
            cx, cy, ax, ay = map(float, p.split()[1:])
            cv2.ellipse(m, (round(cx * sx), round(cy * sy)), (round(ax * sx), round(ay * sy)), 0, 0, 360, 255, -1)
        else:
            cv2.fillPoly(m, [np.round(np.array(p, float) * (sx, sy)).astype(np.int32)], 255)
    return m


def sam_mask(img, pos, neg=()):
    """One SAM 2.1 mask (uint8 0/255) for a set of positive and negative point prompts."""
    global _sam
    if _sam is None:
        from ultralytics import SAM
        _sam = SAM(SAM_WEIGHTS)
    sx, sy = img.shape[1] / 1920.0, img.shape[0] / 1080.0
    pts = [[round(x * sx), round(y * sy)] for x, y in list(pos) + list(neg)]
    lab = [1] * len(pos) + [0] * len(neg)
    r = _sam(img, points=[pts], labels=[lab], verbose=False)
    return r[0].masks.data[0].numpy().astype(np.uint8) * 255


def static_inside(cam, shape):
    m = cv2.imread(os.path.join(MASK_DIR, f"inside_cam{cam}.png"), cv2.IMREAD_GRAYSCALE)
    if m is None:
        raise SystemExit(f"masks/inside_cam{cam}.png is missing: run build_inside_mask.py first")
    if m.shape != shape[:2]:
        m = cv2.resize(m, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return m


def robot_mask(img, cam):
    s = spec(cam)
    r = sam_mask(img, s["robot"]["pos"], s["robot"].get("neg", ()))
    return cv2.bitwise_and(r, poly_mask(img.shape, [s["robot_zone"]]))


def change_guard(img, ref, inside, thresh=32, min_area=400):
    """Interior pixels that changed against the reference, in blobs touching the outside."""
    if ref is None:
        return np.zeros(img.shape[:2], np.uint8)
    if ref.shape != img.shape:
        ref = cv2.resize(ref, (img.shape[1], img.shape[0]))
    core = cv2.erode(inside, np.ones((9, 9), np.uint8))  # the reference is feathered at the edge
    g1 = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (7, 7), 0).astype(np.float32)
    g0 = cv2.GaussianBlur(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), (7, 7), 0).astype(np.float32)
    sel = core > 0
    g1 *= np.median(g0[sel]) / max(np.median(g1[sel]), 1.0)  # overall exposure change is not a change
    ch = ((np.abs(g1 - g0) > thresh) & sel).astype(np.uint8) * 255
    ch = cv2.morphologyEx(ch, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    ch = cv2.morphologyEx(ch, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    border = cv2.dilate(cv2.bitwise_not(inside), np.ones((25, 25), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ch)
    out = np.zeros_like(ch)
    for i in range(1, n):
        blob = lab == i
        if stats[i, cv2.CC_STAT_AREA] >= min_area and (border[blob] > 0).any():
            out[blob] = 255
    return cv2.dilate(out, np.ones((21, 21), np.uint8))


def blur_faces(img, threshold=0.2, mask_scale=1.3):
    from deface.centerface import CenterFace
    from deface.deface import anonymize_frame

    dets, _ = CenterFace(in_shape=(img.shape[1], img.shape[0]), backend="auto")(img, threshold=threshold)
    out = img.copy()
    anonymize_frame(dets, out, mask_scale=mask_scale, replacewith="blur", ellipse=True, draw_scores=False,
                    replaceimg=None, mosaicsize=20)
    return out, len(dets)


def osd_glyphs(img):
    """Mask of the burned-in date/time strokes: small near-white components next to a dark outline."""
    x0, y0, x1, y1 = OSD_TIME_BOX
    roi = img[y0:y1, x0:x1]
    core = (roi.min(axis=2) > 245).astype(np.uint8)
    dark = cv2.dilate((roi.max(axis=2) < 70).astype(np.uint8), np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(core)
    keep = np.zeros_like(core)
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        blob = lab == i
        if h <= 60 and w <= 60 and a <= 1500 and dark[blob].mean() > 0.3:
            keep[blob] = 1
    keep = cv2.dilate(keep, np.ones((3, 3), np.uint8), iterations=2)  # the strokes' black outline
    m = np.zeros(img.shape[:2], bool)
    m[y0:y1, x0:x1] = keep.astype(bool)
    return m


def blur_outside(img, inside, ksize=151, feather=15):
    outside = cv2.bitwise_not(inside)
    blurred = cv2.GaussianBlur(img, (ksize, ksize), 0)
    blurred = cv2.GaussianBlur(blurred, (ksize, ksize), 0)
    a = cv2.GaussianBlur(outside, (feather, feather), 0).astype(np.float32)[..., None] / 255.0
    a = np.maximum(a, (outside[..., None] > 0).astype(np.float32))  # the outside is fully blurred
    return (img.astype(np.float32) * (1 - a) + blurred.astype(np.float32) * a).astype(np.uint8)


def inside_mask(img, cam, robot=True, guard=True):
    """Final 'keep sharp' mask for one frame, and the robot and guard masks that went into it."""
    inside = static_inside(cam, img.shape)
    g = np.zeros(img.shape[:2], np.uint8)
    if guard:
        ref = cv2.imread(os.path.join(MASK_DIR, f"reference_cam{cam}.jpg"))
        g = change_guard(img, ref, inside)
    r = robot_mask(img, cam) if robot else np.zeros(img.shape[:2], np.uint8)
    keep = cv2.bitwise_or(cv2.bitwise_and(inside, cv2.bitwise_not(g)), r)
    return keep, r, g


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cam", type=int, required=True, choices=(0, 1))
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--face-threshold", type=float, default=0.2)
    ap.add_argument("--mask-out", help="also write the final keep-sharp mask (white = inside) here")
    ap.add_argument("--no-robot", action="store_true", help="skip the per-frame Epson segmentation")
    ap.add_argument("--no-guard", action="store_true", help="skip the change guard")
    ap.add_argument("--quality", type=int, default=90)
    a = ap.parse_args()
    img = cv2.imread(a.src)
    keep, r, g = inside_mask(img, a.cam, robot=not a.no_robot, guard=not a.no_guard)
    faced, n = blur_faces(img, a.face_threshold)
    out = blur_outside(faced, keep)
    osd = osd_glyphs(img)
    out[osd] = img[osd]
    cv2.imwrite(a.dst, out, [cv2.IMWRITE_JPEG_QUALITY, a.quality])
    if a.mask_out:
        cv2.imwrite(a.mask_out, keep)
    print(f"cam{a.cam}: {100 * (keep > 0).mean():.1f} % of the frame kept sharp; robot {int((r > 0).sum())} px, "
          f"guard {int((g > 0).sum())} px; {n} face(s) blurred")


if __name__ == "__main__":
    main()
