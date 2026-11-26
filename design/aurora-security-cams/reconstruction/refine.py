"""Photo-consistency refinement of the parts placed from one camera.

    python refine.py        # -> out/refine.json, out/refine.png

A part placed from one camera (back-projected onto an assumed height) sits right in that camera's
frame, but its distance along the camera's rays rests on the assumption: README, "How each part is
placed". Sliding the part along those rays keeps it where it is in that camera's frame and moves it in
the other camera's. So for each such part, or group of parts placed together, this tries offsets
along the source camera's ray through its centre and keeps the one where the two photos agree best when
carried through the model (the cross-view check in phototexture.py, restricted to the part's pixels):
the median local normalised cross-correlation (15 x 15 px) over the part's textured pixels, both ways.

An offset is accepted only when the agreement at the best offset beats the agreement at zero by
MIN_GAIN and the best offset is a clear single peak (no other offset within PEAK_MARGIN of it more
than two steps away). Repeating patterns (breadboard holes on a 25 mm grid) and shiny or plain surfaces
fail that test, and the part stays where it was.
"""
import json
import os

import cv2
import numpy as np
import trimesh

import phototexture as PT
from cameras import CAM0, CAM1

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
STEP_PX = 2
OFFSETS = np.arange(-100.0, 100.0 + 1e-6, 10.0)
MIN_GAIN = 0.08
PEAK_MARGIN = 0.08

# rigid units placed from one camera (scene.py / scene_detail.py SOURCES), by part-name prefix
UNITS = {
    "Thorlabs platform": dict(cam="cam0", prefixes=("Thorlabs platform", "THORLABS")),
    "exfoliator stage": dict(cam="cam0", prefixes=("exfoliator stage",)),
    "exfoliator housing and press motor": dict(cam="cam0", prefixes=("exfoliator housing", "housing screws", "press stepper",
                                                                     )),
    "docking fixtures": dict(cam="cam0", prefixes=("docking fixture",)),
    "gantry X axis": dict(cam="cam1", prefixes=("X axis",)),
    "gantry Y axis": dict(cam="cam1", prefixes=("Y axis",)),
    "printed carriage and motors": dict(cam="cam1", prefixes=("printed carriage", "carriage motor")),
    "tape measure": dict(cam="cam1", prefixes=("tape measure",)),
    "loose breadboard": dict(cam="cam1", prefixes=("loose breadboard",)),
    "exfoliator breadboard": dict(cam="cam1", prefixes=("exfoliator breadboard",)),
    "main breadboard": dict(cam="cam0", prefixes=("main breadboard",)),
}
CAMS = {"cam0": CAM0, "cam1": CAM1}


def members(parts, prefixes):
    return [i for i, p in enumerate(parts) if p.name.startswith(prefixes) and PT.occluder(p)]


class Split:
    """The scene without the unit (one BVH) and the unit alone (another), so moving the unit is a shift of
    the rays' origins rather than a rebuild."""

    def __init__(self, parts, idx):
        keep = [p for i, p in enumerate(parts) if i not in set(idx)]
        self.rest = PT.Scene(keep)
        self.unit = trimesh.util.concatenate([parts[i].mesh for i in idx])
        try:
            from trimesh.ray.ray_pyembree import RayMeshIntersector
            self.rt = RayMeshIntersector(self.unit)
        except Exception:
            self.rt = self.unit.ray

    def unit_dist(self, O, D):
        t = np.full(len(D), np.inf)
        if len(D) == 0:
            return t
        loc, ri, _ = self.rt.intersects_location(O, D, multiple_hits=False)
        t[ri] = np.linalg.norm(loc - O[ri], axis=1)
        return t


def local_ncc(a, b, valid, k=15):
    mw, mr = cv2.blur(a, (k, k)), cv2.blur(b, (k, k))
    cov = cv2.blur(a * b, (k, k)) - mw * mr
    va, vb = cv2.blur(a * a, (k, k)) - mw ** 2, cv2.blur(b * b, (k, k)) - mr ** 2
    ncc = cov / np.sqrt(np.maximum(va * vb, 1e-6))
    tex = (va > 25) & (vb > 25)
    v = valid & (cv2.erode(valid.astype(np.uint8), np.ones((k, k), np.uint8)) > 0) & tex
    return ncc, v


class View:
    """Per-camera pixel rays and their hits on the rest of the scene."""

    def __init__(self, cam, split, gray):
        self.cam = cam
        self.px, self.O, self.D, self.shape = PT.pixel_rays(cam, STEP_PX)
        _, face, self.t_rest = split.rest.cast(self.O, self.D)
        self.t_rest[face < 0] = np.inf
        self.valid = PT.valid_pixels(cam.name, self.shape).ravel()
        self.gray = gray


def score(split, vB, vA, shift, photos_gray):
    """Median local NCC over B's pixels on the shifted unit, comparing B's photo with A's photo looked up
    through the model. Returns (score, pixels)."""
    tu = split.unit_dist(vB.O - shift, vB.D)
    on = (tu < vB.t_rest) & vB.valid
    idx = np.where(on)[0]
    if len(idx) < 300:
        return np.nan, int(len(idx))
    X = vB.O[idx] + tu[idx, None] * vB.D[idx]                   # in the shifted world
    A = vA.cam
    dA = X - A.centre
    r = np.linalg.norm(dA, axis=1)
    d = dA / r[:, None]
    _, fA, tA = split.rest.cast(np.repeat(A.centre[None], len(idx), 0), d)
    tA[fA < 0] = np.inf
    tAu = split.unit_dist(np.repeat(A.centre[None], len(idx), 0) - shift, d)
    vis = np.abs(np.minimum(tA, tAu) - r) < np.maximum(6.0, 0.006 * r)
    uv, z = A.project(X[vis])
    okA = PT.valid_pixels(A.name, (1080, 1920))
    ins = (z > 0) & (uv[:, 0] >= 0) & (uv[:, 0] < 1919) & (uv[:, 1] >= 0) & (uv[:, 1] < 1079)
    ins[ins] &= okA[uv[ins, 1].round().astype(int), uv[ins, 0].round().astype(int)]
    sel = idx[vis][ins]
    if len(sel) < 300:
        return np.nan, int(len(sel))
    warped = np.zeros(len(vB.O), np.float32)
    warped[sel] = PT.bilinear(photos_gray[A.name][..., None], uv[ins])[:, 0]
    have = np.zeros(len(vB.O), bool)
    have[sel] = True
    real = photos_gray[vB.cam.name][vB.px[:, 1].astype(int), vB.px[:, 0].astype(int)].astype(np.float32)
    g = np.median(real[have] + 1) / np.median(warped[have] + 1)
    W = (warped * g).reshape(vB.shape)
    R = real.reshape(vB.shape)
    ncc, v = local_ncc(W, R, have.reshape(vB.shape))
    if v.sum() < 150:
        return np.nan, int(v.sum())
    return float(np.median(ncc[v])), int(v.sum())


def refine_unit(parts, name, spec, photos_gray):
    idx = members(parts, spec["prefixes"])
    if not idx:
        return dict(found=False)
    split = Split(parts, idx)
    src = CAMS[spec["cam"]]
    oth = CAM1 if src is CAM0 else CAM0
    c = split.unit.centroid
    d = (c - src.centre) / np.linalg.norm(c - src.centre)
    vS, vO = View(src, split, photos_gray[src.name]), View(oth, split, photos_gray[oth.name])
    curve = []
    for off in OFFSETS:
        sh = off * d
        s1, n1 = score(split, vO, vS, sh, photos_gray)      # other camera's pixels, source photo looked up
        s2, n2 = score(split, vS, vO, sh, photos_gray)      # source camera's pixels, other photo looked up
        vals = [s for s in (s1, s2) if np.isfinite(s)]
        curve.append(dict(offset_mm=float(off), ncc=float(np.mean(vals)) if vals else None, px=[n1, n2]))
    ys = np.array([q["ncc"] if q["ncc"] is not None else np.nan for q in curve])
    rec = dict(parts=len(idx), source=spec["cam"], ray_dir=np.round(d, 4).tolist(), centre_mm=np.round(c, 1).tolist(),
               curve=curve)
    if not np.isfinite(ys).any() or not np.isfinite(ys[len(ys) // 2]):
        rec.update(accepted=False, why="the other camera doesn't see enough of it")
        return rec
    k = int(np.nanargmax(ys))
    zero = float(ys[len(ys) // 2])
    far = np.abs(np.arange(len(ys)) - k) > 2
    rival = float(np.nanmax(ys[far])) if np.isfinite(ys[far]).any() else -1.0
    gain = float(ys[k] - zero)
    ok = gain >= MIN_GAIN and ys[k] - rival >= PEAK_MARGIN and 0 < k < len(ys) - 1
    rec.update(best_offset_mm=float(OFFSETS[k]), ncc_at_zero=round(zero, 3), ncc_at_best=round(float(ys[k]), 3),
               gain=round(gain, 3), rival=round(rival, 3), accepted=bool(ok),
               shift_mm=np.round(OFFSETS[k] * d, 1).tolist() if ok else [0.0, 0.0, 0.0],
               why=None if ok else ("no clear gain" if gain < MIN_GAIN else
                                    "best offset at the end of the search range" if not 0 < k < len(ys) - 1 else
                                    "more than one peak"))
    return rec


def main():
    import pickle
    import sys
    parts = pickle.load(open(sys.argv[1], "rb")) if len(sys.argv) > 1 else PT.load_parts()
    photos = {k: cv2.imread(os.path.join(HERE, "..", "captures", v)) for k, v in PT.STILLS.items()}
    gray = {k: cv2.cvtColor(v, cv2.COLOR_BGR2GRAY) for k, v in photos.items()}
    res = {}
    for name, spec in UNITS.items():
        res[name] = refine_unit(parts, name, spec, gray)
        r = res[name]
        print(name, {k: r.get(k) for k in ("best_offset_mm", "ncc_at_zero", "ncc_at_best", "accepted", "why")},
              flush=True)
    json.dump(dict(method=__doc__.strip().split("\n\n")[1], offsets_mm=OFFSETS.tolist(), min_gain=MIN_GAIN,
                   peak_margin=PEAK_MARGIN, units=res), open(os.path.join(OUT, "refine.json"), "w"), indent=1)
    plot(res)


def plot(res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = [n for n, r in res.items() if r.get("curve")]
    n = len(names)
    cols = 4
    rows = int(np.ceil(n / cols))
    fig, ax = plt.subplots(rows, cols, figsize=(3.4 * cols, 2.5 * rows), squeeze=False, sharex=True)
    for a, nm in zip(ax.ravel(), names):
        r = res[nm]
        x = [q["offset_mm"] for q in r["curve"]]
        y = [q["ncc"] if q["ncc"] is not None else np.nan for q in r["curve"]]
        a.plot(x, y, "-o", ms=3, color="#1f77b4" if r.get("accepted") else "#7f7f7f")
        a.axvline(0, color="k", lw=0.6)
        if r.get("accepted"):
            a.axvline(r["best_offset_mm"], color="#2ca02c", lw=1.2, ls="--")
        a.set_title(f"{nm} ({r['source']})", fontsize=8.5)
        a.tick_params(labelsize=7)
        a.grid(alpha=0.3)
    for a in ax.ravel()[n:]:
        a.axis("off")
    for a in ax[-1]:
        a.set_xlabel("offset along the source camera's ray (mm)", fontsize=7.5)
    for a in ax[:, 0]:
        a.set_ylabel("two-camera agreement\n(median local NCC)", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "refine.png"), dpi=110)


if __name__ == "__main__":
    main()
