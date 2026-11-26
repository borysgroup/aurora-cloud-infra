"""Mixed-reality training images for the Epson segmentation model.

Each sample is a real Overhead 1 or Overhead 2 frame with the parked robot cut out and refilled with
room imagery, and Epson's own CAD robot (epson_render.py) drawn at random joint angles through that
camera's calibrated pose and lens. The label is the rendered robot's exact mask.

- Plates: the stored frames of each camera. The parked robot (its fitted CAD silhouette, plus the SAM
  2.1 mask in Overhead 1) is filled with a crop of a lab room from the AURORA video's robot-free shots,
  so the cut-out never leaves a robot behind that is labelled background.
- Room behind the windows: the stored stills are blurred outside the glovebox, the live feed is not.
  So the outside is often replaced with an unblurred room crop, which also gives the model people,
  benches and screens next to the arm as hard negatives.
- Two looks for the robot: flat-shaded CAD with a random grey level, tint and light; or "textured",
  each face coloured from Overhead 1's 18:22 frame where the camera saw it at the parked pose (the
  face colours then travel with the arm to any pose, with the frame's light baked in).
- Two kinds of camera: the two calibrated Amcrest cameras, or (with --virtual) a random pinhole camera
  0.35 to 1.5 m from a random part of the robot, from any side and up to 65 deg above it, over a room
  crop or a plate. The second kind is for cameras that get moved or re-aimed, and for the video test.
- Randomised: joints over the full range (j1 +/-132 deg, j2 +/-150 deg, z 0-200 mm, u), base position
  (8 mm), height (5 mm) and yaw (1 deg), camera rotation (0.4 deg), a stand-in end effector, blur,
  noise, JPEG quality and occluders cut from the plate.

    python synth.py --raw raw_cam0.jpg raw_cam1.jpg --video VIDEO.mp4 --out DIR -n 1600 [--textured 0.5]
                    [--virtual 0.35] [--workers 4]

writes DIR/images/*.jpg and DIR/labels/*.txt (YOLO segmentation polygons, class 0 = Epson robot).
"""
import argparse
import glob
import os
from multiprocessing import Pool

import cv2
import numpy as np

import epson_render as R

VIS = os.path.join(R.HERE, "..")
CAPS = os.path.join(VIS, "..", "captures")
CROPS = {0: (0, 0, 1350, 700), 1: (0, 0, 1920, 1080)}   # cam0: the robot zone, as the live blur runs it
OUT_W = 448
ROOM_FRAMES = list(range(200, 301, 6)) + list(range(450, 506, 5)) + list(range(1320, 1501, 12)) + \
    list(range(1530, 1601, 10))    # robot-free shots of the AURORA video (labs, people, a server room)


def out_size(cam):
    x0, y0, x1, y1 = CROPS[cam]
    return OUT_W, int(round(OUT_W * (y1 - y0) / (x1 - x0)))


def to_out(img, cam, interp=cv2.INTER_AREA):
    x0, y0, x1, y1 = CROPS[cam]
    return cv2.resize(img[y0:y1, x0:x1], out_size(cam), interpolation=interp)


def plates(cam, raw):
    """[(image, hole, inside)] at output size for every stored frame of this camera."""
    pose, pk = R.fitted_pose()
    sil = R.silhouette(R.posed_meshes(pose, pk["j1"], pk["j2"]), R.CAMS[cam])
    sam = cv2.imread(os.path.join(VIS, "masks", f"robot_cam{cam}.png"), cv2.IMREAD_GRAYSCALE)
    hole = cv2.bitwise_or(sil, sam if sam is not None else np.zeros_like(sil))
    hole = cv2.dilate(hole, np.ones((41, 41), np.uint8))
    inside = cv2.imread(os.path.join(VIS, "masks", f"inside_cam{cam}.png"), cv2.IMREAD_GRAYSCALE)
    paths = sorted(glob.glob(os.path.join(CAPS, f"*_cam{cam}_*.jpg"))) + \
        [os.path.join(VIS, "masks", f"reference_cam{cam}.jpg")] + [p for p in raw if f"cam{cam}" in os.path.basename(p)]
    out = []
    for p in paths:
        img = cv2.imread(p)
        out.append((to_out(img, cam), to_out(hole, cam, cv2.INTER_NEAREST),
                    to_out(inside, cam, cv2.INTER_NEAREST), "raw" if p in raw else "blurred"))
    return out


def room_pool(video):
    cap = cv2.VideoCapture(video)
    want, pool, i = set(ROOM_FRAMES), [], 0
    while i <= max(ROOM_FRAMES):
        ok, f = cap.read()
        if not ok:
            break
        if i in want:   # the top 160 rows carry the video's captions
            pool.append(cv2.resize(f[160:], (960, 460), interpolation=cv2.INTER_AREA))
        i += 1
    return pool


def room_crop(rng, pool, w, h):
    src = pool[rng.integers(len(pool))]
    s = rng.uniform(0.35, 1.0)
    cw, ch = int(src.shape[1] * s), int(src.shape[0] * s)
    x, y = rng.integers(0, src.shape[1] - cw + 1), rng.integers(0, src.shape[0] - ch + 1)
    c = cv2.resize(src[y:y + ch, x:x + cw], (w, h), interpolation=cv2.INTER_AREA)
    if rng.random() < 0.5:
        c = c[:, ::-1]
    return np.ascontiguousarray(c)


def feather(m, k):
    k = k | 1
    return cv2.GaussianBlur(m.astype(np.float32) / 255.0, (k, k), 0)[..., None]


def sample_joints(rng):
    if rng.random() < 0.35:     # around the parked pose, where the arm spends its idle time
        pk = R.fitted_pose()[1]
        j1, j2 = pk["j1"] + rng.normal(0, 25), pk["j2"] + rng.normal(0, 30)
    else:
        j1, j2 = rng.uniform(-132, 132), rng.uniform(-150, 150)
    return float(np.clip(j1, -132, 132)), float(np.clip(j2, -150, 150)), float(rng.uniform(0, 200)), \
        float(rng.uniform(-180, 180))


def small_rot(rng, deg):
    a = np.radians(rng.normal(0, deg, 3))
    cx, cy, cz = np.cos(a)
    sx, sy, sz = np.sin(a)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def polygons(mask, min_area=30):
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = mask.shape
    out = []
    for c in cnts:
        if cv2.contourArea(c) < min_area:
            continue
        c = cv2.approxPolyDP(c, 0.8, True).reshape(-1, 2)
        if len(c) >= 3:
            out.append(" ".join(f"{x / w:.5f} {y / h:.5f}" for x, y in c))
    return out


_G = {}
TEX_FRAME = ("masks/reference_cam0.jpg", "robotseg/gt/cam0_2026-11-19_1822Z_cam0_192.168.3.150.png")
MAX_EDGE = 12.0     # mm, face size of the textured meshes


def _init(raw, video, p_tex, p_virt):
    _G["plates"] = {c: plates(c, raw) for c in (0, 1)}
    _G["room"] = room_pool(video)
    pose, pk = R.fitted_pose()
    _G["pose"], _G["p_tex"], _G["p_virt"] = pose, p_tex, p_virt
    if p_tex > 0:
        img = cv2.imread(os.path.join(VIS, TEX_FRAME[0]))
        m = cv2.imread(os.path.join(VIS, TEX_FRAME[1]), cv2.IMREAD_GRAYSCALE)
        ms = R.posed_meshes(pose, pk["j1"], pk["j2"], max_edge=MAX_EDGE)
        _G["tex"] = R.texture_from_frame(img, R.CAM0, ms, m)[0]


def virtual_cam(rng, meshes):
    """A random pinhole camera looking at a random part of the robot."""
    names = [k for k in ("base", "arm1", "arm2", "shaft") if k in meshes]
    target = meshes[names[rng.integers(len(names))]].vertices.mean(axis=0) + rng.normal(0, 60, 3)
    az, el = rng.uniform(0, 2 * np.pi), np.radians(rng.uniform(0, 65))
    d = rng.uniform(350, 1500)
    centre = target + d * np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
    return R.VirtualCam(centre, target, rng.uniform(700, 1500))


def make(args):
    i, seed, out = args
    rng = np.random.default_rng(seed)
    virtual = rng.random() < _G["p_virt"]
    textured = rng.random() < _G["p_tex"]
    cam = 0 if rng.random() < 0.75 else 1
    img, hole, inside, kind = _G["plates"][cam][rng.integers(len(_G["plates"][cam]))]
    img = img.astype(np.float32)
    if virtual:
        w, h = OUT_W, int(round(OUT_W * 1080 / 1920))
        if rng.random() < 0.6:
            img = room_crop(rng, _G["room"], w, h).astype(np.float32)
        else:
            a = feather(hole, 9)
            img = img * (1 - a) + room_crop(rng, _G["room"], img.shape[1], img.shape[0]) * a
            img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    else:
        h, w = img.shape[:2]
        a = feather(hole, 9)
        img = img * (1 - a) + room_crop(rng, _G["room"], w, h) * a                   # parked robot out
        if rng.random() < (0.3 if kind == "raw" else 0.7):                            # unblurred room
            o = cv2.bitwise_and(cv2.bitwise_not(inside), cv2.bitwise_not(hole))
            a = feather(o, 7)
            img = img * (1 - a) + room_crop(rng, _G["room"], w, h) * a
    p0 = _G["pose"]
    pose = dict(j1=(p0["j1"][0] + rng.normal(0, 8), p0["j1"][1] + rng.normal(0, 8)), z0=p0["z0"] + rng.normal(0, 5),
                yaw=p0["yaw"] + rng.normal(0, 1.0))
    j1, j2, z, u = sample_joints(rng)
    tool = R.tool_mesh(tuple(rng.uniform((20, 20, 20), (70, 70, 90)))) if rng.random() < 0.7 else None
    g = rng.uniform(165, 240)
    white = tuple(np.clip(g + rng.normal(0, 6, 3), 0, 255))
    colors = dict(base=white, arm1=white, arm2=white, shaft=tuple([rng.uniform(140, 215)] * 3),
                  cable=tuple([rng.uniform(10, 60)] * 3), unit=tuple([rng.uniform(10, 50)] * 3),
                  tool=[(40, 40, 40), (60, 100, 200), (190, 195, 200), (25, 25, 25)][rng.integers(4)])
    light = (rng.normal(0, 0.6), rng.normal(0, 0.6), rng.uniform(0.3, 1.2))
    ms = R.posed_meshes(pose, j1, j2, z, u, tool=tool, max_edge=MAX_EDGE if textured else None)
    if virtual:
        vc = virtual_cam(rng, ms)
        cam_obj, crop, dR = vc, (0, 0, 1920, 1080), None
    else:
        cam_obj, crop, dR = R.CAMS[cam], CROPS[cam], small_rot(rng, 0.4)
    rob, al = R.render(ms, cam_obj, crop, (w, h), colors=colors, light=light,
                       ambient=rng.uniform(0.35, 0.7), diffuse=rng.uniform(0.25, 0.6), spec=rng.uniform(0, 0.3),
                       shininess=rng.uniform(5, 30), dR=dR, face_rgb=_G.get("tex") if textured else None,
                       tex_shade=rng.uniform(0.0, 0.3), cull=True)
    if rng.random() < 0.5:
        s = rng.uniform(0.3, 1.0)
        rob = cv2.GaussianBlur(rob, (0, 0), s)
        al = cv2.GaussianBlur(al, (0, 0), s)
    rob = np.clip(rob.astype(np.float32) * rng.uniform(0.8, 1.15) + rng.normal(0, 6), 0, 255)
    img = img * (1 - al[..., None]) + rob * al[..., None]
    lab = (al > 0.5).astype(np.uint8) * 255
    if rng.random() < 0.25 and lab.any():                                             # occluders
        ys, xs = np.nonzero(lab)
        for _ in range(rng.integers(1, 3)):
            cx, cy = xs[rng.integers(len(xs))], ys[rng.integers(len(ys))]
            bw, bh = rng.integers(12, 70, 2)
            box = cv2.boxPoints(((float(cx), float(cy)), (float(bw), float(bh)), float(rng.uniform(0, 180))))
            m = np.zeros((h, w), np.uint8)
            cv2.fillConvexPoly(m, np.round(box).astype(np.int32), 255)
            sx, sy = rng.integers(-w // 3, w // 3), rng.integers(-h // 3, h // 3)
            src = np.roll(np.roll(img, sy, 0), sx, 1)
            img[m > 0] = src[m > 0]
            lab[m > 0] = 0
    if rng.random() < 0.5:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.3, 0.9))
    img = np.clip(img + rng.normal(0, rng.uniform(0, 4), img.shape), 0, 255).astype(np.uint8)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(55, 96))])
    name = f"{'virt' if virtual else f'syn{cam}'}{'t' if textured else ''}_{i:05d}"
    open(os.path.join(out, "images", name + ".jpg"), "wb").write(enc.tobytes())
    with open(os.path.join(out, "labels", name + ".txt"), "w") as f:
        f.writelines(f"0 {p}\n" for p in polygons(lab))
    return (2 if virtual else cam), int((lab > 0).sum())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", nargs="*", default=[], help="unblurred stills of either camera (name contains camN)")
    ap.add_argument("--video", required=True, help="the AURORA video (robot-free shots give the room crops)")
    ap.add_argument("--out", required=True)
    ap.add_argument("-n", type=int, default=1600)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--textured", type=float, default=0.0, help="share of robots coloured from the real frame")
    ap.add_argument("--virtual", type=float, default=0.0, help="share of samples seen by a random camera")
    a = ap.parse_args()
    for d in ("images", "labels"):
        os.makedirs(os.path.join(a.out, d), exist_ok=True)
    jobs = [(i, a.seed * 1000003 + i, a.out) for i in range(a.n)]
    with Pool(a.workers, initializer=_init, initargs=(a.raw, a.video, a.textured, a.virtual)) as p:
        res = p.map(make, jobs, chunksize=8)
    cams = np.array([r[0] for r in res])
    px = np.array([r[1] for r in res])
    print(f"{a.n} samples: {int((cams == 0).sum())} Overhead 1, {int((cams == 1).sum())} Overhead 2, "
          f"{int((cams == 2).sum())} random cameras; "
          f"robot visible in {int((px > 0).sum())}; median robot area {np.median(px):.0f} px")


if __name__ == "__main__":
    main()
