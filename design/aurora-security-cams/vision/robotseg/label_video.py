"""Label the Epson T6 in the two shots of the AURORA video (https://www.youtube.com/watch?v=moBCWzP9Izw)
that show one, with SAM 2.1's video predictor: point prompts on each shot's first frame, then SAM 2.1
tracks the robot through the shot. Every second frame is used.

The video is not redistributed here. Download it once (the runner's IP is blocked by YouTube, so it went
through the Pi 5 as a SOCKS proxy at 800 KB/s), then:

    yt-dlp -f 137 -o video.mp4 https://www.youtube.com/watch?v=moBCWzP9Izw
    python label_video.py video.mp4 OUT_DIR       # OUT_DIR/<shot>/<frame>.jpg and .png (255 = robot)
"""
import os
import sys

import cv2
import numpy as np

# shot: (first frame, last frame, positive prompts, negative prompts), pixels at 1920 x 1080
SHOTS = {
    # another T6 in the Utah glovebox, beside the sample-retrieval gantry
    "retrieval": (526, 588, [(420, 220), (450, 640), (130, 300), (380, 470)],
                  [(1100, 480), (700, 300), (900, 820), (1300, 300)]),
    # this glovebox's T6, over the chip tray and the microscope; handheld camera
    "transfer": (604, 668, [(560, 60), (900, 110), (600, 330), (880, 300)],
                 [(1300, 230), (760, 540), (150, 200), (1150, 420)]),
}
STRIDE = 2


def main(video, out):
    from ultralytics.models.sam import SAM2VideoPredictor
    cap = cv2.VideoCapture(video)
    frames, i = {}, 0
    lo = min(s[0] for s in SHOTS.values())
    hi = max(s[1] for s in SHOTS.values())
    while i <= hi:
        ok, f = cap.read()
        if not ok:
            break
        if i >= lo:
            frames[i] = f
        i += 1
    for name, (a, b, pos, neg) in SHOTS.items():
        d = os.path.join(out, name)
        os.makedirs(d, exist_ok=True)
        idx = list(range(a, b + 1, STRIDE))
        clip = os.path.join(out, f"{name}.mp4")
        w = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"mp4v"), 15, (1920, 1080))
        for k in idx:
            w.write(frames[k])
        w.release()
        pred = SAM2VideoPredictor(overrides=dict(conf=0.25, task="segment", mode="predict", imgsz=1024,
                                                 model=os.environ.get("SAM_WEIGHTS", "sam2.1_b.pt"), save=False,
                                                 verbose=False))
        pts = [list(p) for p in pos + neg]
        lab = [1] * len(pos) + [0] * len(neg)
        for k, r in zip(idx, pred(source=clip, points=[pts], labels=[lab], stream=True)):
            m = np.zeros((1080, 1920), np.uint8) if r.masks is None else \
                (r.masks.data.cpu().numpy().any(axis=0) * 255).astype(np.uint8)
            if m.shape != (1080, 1920):
                m = cv2.resize(m, (1920, 1080), interpolation=cv2.INTER_NEAREST)
            cv2.imwrite(os.path.join(d, f"{k:04d}.png"), m)
            cv2.imwrite(os.path.join(d, f"{k:04d}.jpg"), frames[k], [cv2.IMWRITE_JPEG_QUALITY, 95])
            print(name, k, int((m > 0).sum()), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
