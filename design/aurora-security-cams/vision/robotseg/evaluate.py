"""Score the Epson segmentation model (ONNX, run exactly as on the Pi 5 by yolo_onnx.py) on real frames that
were held out from training:

- Overhead 1: every stored still, in the robot zone the live blur uses (1350 x 700 px at 1080p). The arm
  is parked in all of them. Ground truth is SAM 2.1 with point prompts on the base, controller box, arm 1
  and arm 2, and negatives on the riser block, the docking fixtures, the microscope and the room
  (gt/cam0_*.png). The training images contain no real pixels of this robot from this camera: the parked
  robot was cut out of every plate.
- The "transfer" shot of the AURORA video: this glovebox's T6 moving, handheld camera, ground truth from
  label_video.py. No frame of the shot was used in training.

    python evaluate.py --stills RAW0.jpg ... --video-labels DIR [--model models/epson_t6_seg.onnx]

Writes ../out/robotseg_eval.json and, for the published stills only, ../out/robotseg_cam0.jpg.
"""
import argparse
import glob
import json
import os

import cv2
import numpy as np

from yolo_onnx import DEFAULT, EpsonSeg

HERE = os.path.dirname(os.path.abspath(__file__))
VIS = os.path.join(HERE, "..")
ZONE = (0, 0, 1350, 700)
CAM0_POS = [(375, 135), (495, 435), (450, 495), (630, 270), (840, 105), (435, 322)]
CAM0_NEG = [(705, 435), (450, 578), (1035, 210), (120, 300), (600, 45)]


def sam_gt(img):
    import sys
    sys.path.insert(0, VIS)
    from privacy_blur import sam_mask
    return sam_mask(img, CAM0_POS, CAM0_NEG)


def scores(pred, gt):
    p, g = pred > 0, gt > 0
    tp, fp, fn = (p & g).sum(), (p & ~g).sum(), (~p & g).sum()
    return dict(iou=float(tp / max(tp + fp + fn, 1)), precision=float(tp / max(tp + fp, 1)),
                recall=float(tp / max(tp + fn, 1)), fp_share_of_frame=float(fp / p.size))


def summary(rows):
    keys = ("iou", "precision", "recall", "fp_share_of_frame")
    return {k: round(float(np.mean([r[k] for r in rows])), 3) for k in keys} | dict(frames=len(rows))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stills", nargs="*", default=[], help="extra (unpublished, unblurred) Overhead 1 stills")
    ap.add_argument("--video-labels", required=True)
    ap.add_argument("--model", default=DEFAULT)
    ap.add_argument("--gt-dir", default=os.path.join(HERE, "gt"))
    a = ap.parse_args()
    seg = EpsonSeg(a.model, threads=4)
    os.makedirs(a.gt_dir, exist_ok=True)
    published = sorted(glob.glob(os.path.join(VIS, "..", "captures", "*_cam0_*.jpg")))
    x0, y0, x1, y1 = ZONE
    rows0, figs = [], []
    for p in published + list(a.stills):
        img = cv2.imread(p)
        gp = os.path.join(a.gt_dir, "cam0_" + os.path.basename(p).replace(".jpg", ".png"))
        if not os.path.exists(gp):
            cv2.imwrite(gp, sam_gt(img))
        gt = cv2.imread(gp, cv2.IMREAD_GRAYSCALE)[y0:y1, x0:x1]
        crop = img[y0:y1, x0:x1]
        pred = seg(crop)
        r = scores(pred, gt) | dict(frame=os.path.basename(p), published=p in published)
        rows0.append(r)
        print("cam0", r)
        if p in published and len(figs) < 2:
            figs.append(overlay(crop, pred, gt))
    rows1 = []
    for mp in sorted(glob.glob(os.path.join(a.video_labels, "transfer", "*.png"))):
        img = cv2.imread(mp[:-4] + ".jpg")
        gt = cv2.imread(mp, cv2.IMREAD_GRAYSCALE)
        pred = seg(img)
        rows1.append(scores(pred, gt) | dict(frame=os.path.basename(mp)[:-4]))
    print("video", summary(rows1))
    out = dict(model=os.path.basename(a.model),
               overhead1=dict(summary=summary(rows0), frames=rows0,
                              note="robot zone 1350 x 700 px; arm parked; ground truth SAM 2.1 with point prompts"),
               video_transfer=dict(summary=summary(rows1), frames=rows1,
                                   note="AURORA video, transfer shot (this glovebox's T6), every 2nd frame, "
                                        "held out; ground truth SAM 2.1 video predictor"))
    json.dump(out, open(os.path.join(VIS, "out", "robotseg_eval.json"), "w"), indent=1)
    if figs:
        cv2.imwrite(os.path.join(VIS, "out", "robotseg_cam0.jpg"), np.hstack(figs), [cv2.IMWRITE_JPEG_QUALITY, 85])


def overlay(img, pred, gt):
    """Green: model and ground truth agree; red: model only; blue: ground truth only."""
    p, g = pred > 0, gt > 0
    o = img.copy()
    o[p & g] = (0.5 * o[p & g] + (0, 110, 0)).astype(np.uint8)
    o[p & ~g] = (0.4 * o[p & ~g] + (0, 0, 150)).astype(np.uint8)
    o[g & ~p] = (0.4 * o[g & ~p] + (150, 0, 0)).astype(np.uint8)
    return cv2.resize(o, (o.shape[1] * 2 // 3, o.shape[0] * 2 // 3), interpolation=cv2.INTER_AREA)


if __name__ == "__main__":
    main()
