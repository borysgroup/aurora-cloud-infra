"""Assemble the dataset and train the one-class Epson segmentation model (YOLO11n-seg, COCO weights) on CPU,
then export it to ONNX at the live-blur input size (448 x 256).

    python train.py --syn-train DIR --syn-val DIR --work DIR [--epochs 12] [--init WEIGHTS.pt]
                    [--video-labels DIR --video-shots ...]

Training set: the mixed-reality samples from synth.py only. Video shots labelled by label_video.py can be
added with --video-shots, but by default none are: SAM 2.1 missed part of the robot in the "retrieval"
shot, and the "transfer" shot (this glovebox's T6) and the real Overhead 1 stills are held out for
evaluate.py. Validation (for checkpoint selection) is synthetic.
"""
import argparse
import glob
import os
import shutil

import cv2
import numpy as np

from synth import polygons

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO_SIZE = (448, 252)


def link_split(src, dst):
    for d in ("images", "labels"):
        os.makedirs(os.path.join(dst, d), exist_ok=True)
        for p in glob.glob(os.path.join(src, d, "*")):
            q = os.path.join(dst, d, os.path.basename(p))
            if not os.path.exists(q):
                os.symlink(os.path.abspath(p), q)


def add_video(video_labels, dst, shots):
    n = 0
    for shot in shots:
        for mp in sorted(glob.glob(os.path.join(video_labels, shot, "*.png"))):
            img = cv2.resize(cv2.imread(mp[:-4] + ".jpg"), VIDEO_SIZE, interpolation=cv2.INTER_AREA)
            m = cv2.resize(cv2.imread(mp, cv2.IMREAD_GRAYSCALE), VIDEO_SIZE, interpolation=cv2.INTER_NEAREST)
            name = f"vid_{shot}_{os.path.basename(mp)[:-4]}"
            cv2.imwrite(os.path.join(dst, "images", name + ".jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            with open(os.path.join(dst, "labels", name + ".txt"), "w") as f:
                f.writelines(f"0 {p}\n" for p in polygons(m))
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--syn-train", required=True)
    ap.add_argument("--syn-val", required=True)
    ap.add_argument("--video-labels", default=None)
    ap.add_argument("--video-shots", nargs="*", default=[], help="video shots to add to training")
    ap.add_argument("--work", required=True)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--freeze", type=int, default=0)
    ap.add_argument("--init", default="yolo11n-seg.pt", help="starting weights (COCO by default)")
    a = ap.parse_args()
    data = os.path.join(a.work, "data")
    if os.path.exists(data):
        shutil.rmtree(data)
    link_split(a.syn_train, os.path.join(data, "train"))
    link_split(a.syn_val, os.path.join(data, "val"))
    nv = add_video(a.video_labels, os.path.join(data, "train"), a.video_shots) if a.video_shots else 0
    yaml = os.path.join(a.work, "epson.yaml")
    open(yaml, "w").write(f"path: {data}\ntrain: train/images\nval: val/images\nnames:\n  0: epson_t6\n")
    print(f"train: {len(os.listdir(os.path.join(data, 'train', 'images')))} images ({nv} video frames); "
          f"val: {len(os.listdir(os.path.join(data, 'val', 'images')))}")
    from ultralytics import YOLO
    model = YOLO(a.init)
    model.train(data=yaml, imgsz=a.imgsz, epochs=a.epochs, batch=a.batch, workers=4, device="cpu", single_cls=True,
                project=a.work, name="train", exist_ok=True, cache="ram", patience=100, close_mosaic=3,
                degrees=3.0, translate=0.1, scale=0.4, fliplr=0.5, hsv_h=0.02, hsv_s=0.5, hsv_v=0.4, mosaic=0.7,
                freeze=a.freeze or None, plots=False, verbose=False, seed=0, deterministic=False, amp=False)
    best = os.path.join(a.work, "train", "weights", "best.pt")
    onnx = YOLO(best).export(format="onnx", imgsz=(256, 448), simplify=True, opset=17, dynamic=False)
    os.makedirs(os.path.join(HERE, "models"), exist_ok=True)
    shutil.copy(onnx, os.path.join(HERE, "models", "epson_t6_seg.onnx"))
    print("exported", onnx)


if __name__ == "__main__":
    main()
