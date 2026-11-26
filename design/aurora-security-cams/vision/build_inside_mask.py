"""Build the static inside-the-glovebox mask for one camera view, and the change guard's reference.

    python build_inside_mask.py --cam N FRAME.jpg

Reads inside_masks.json, fills its hand-drawn polygons, adds a SAM 2.1 mask for each
'sam_static' object (exact outlines of equipment that stands in front of a window), and writes:

    masks/inside_camN.png     white = glovebox interior that does not move
    masks/reference_camN.jpg  FRAME with everything else blurred (privacy_blur's change guard
                              compares new frames with it, and it is safe to publish)
    masks/robot_camN.png      the Epson's mask on FRAME (privacy_blur keeps robot pixels only where
                              this mask has them or where the frame has changed)

The robot's moving parts are deliberately not in the static mask; privacy_blur.py segments the
Epson on every frame. Re-run after re-aiming a camera or moving equipment near a window.
"""
import argparse
import os

import cv2
import numpy as np

import privacy_blur as pb


def build(img, cam):
    s = pb.spec(cam)
    m = pb.poly_mask(img.shape, list(s["polygons"].values()))
    parts = {}
    for name, o in s["sam_static"].items():
        parts[name] = pb.sam_mask(img, o["pos"], o.get("neg", ()))
        m |= parts[name]
    # fill pinholes between objects; never grow the outer boundary
    filled = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cv2.bitwise_not(filled))
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 600:  # small enclosed specks, not a view of the room
            filled[lab == i] = 255
    return filled, parts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cam", type=int, required=True, choices=(0, 1))
    ap.add_argument("frame")
    a = ap.parse_args()
    img = cv2.imread(a.frame)
    inside, _ = build(img, a.cam)
    os.makedirs(pb.MASK_DIR, exist_ok=True)
    cv2.imwrite(os.path.join(pb.MASK_DIR, f"inside_cam{a.cam}.png"), inside)
    robot = pb.robot_mask(img, a.cam)
    cv2.imwrite(os.path.join(pb.MASK_DIR, f"robot_cam{a.cam}.png"), robot)
    ref = pb.blur_outside(img, cv2.bitwise_or(inside, robot))
    osd = pb.osd_glyphs(img)
    ref[osd] = img[osd]
    cv2.imwrite(os.path.join(pb.MASK_DIR, f"reference_cam{a.cam}.jpg"), ref, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"cam{a.cam}: static interior {100 * (inside > 0).mean():.1f} % of the frame, "
          f"with the robot {100 * ((inside | robot) > 0).mean():.1f} %")


if __name__ == "__main__":
    main()
