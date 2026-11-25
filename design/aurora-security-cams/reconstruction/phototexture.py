"""Photo textures for the reconstruction: every static part takes the colours the two calibrated cameras
saw on it, so the model carries the real labels, stickers, wear, stains and colour variation.

    xvfb-run -a python phototexture.py            # -> out/glovebox_photo.glb, out/phototexture.json
    xvfb-run -a python phototexture.py --check    # also the cross-view check -> out/crossview.jpg

How it works:
1. Each static part gets texture coordinates from xatlas, one atlas per group at TEXEL mm per texel.
2. For each camera, a ray through every pixel of its published 18:22 UTC still (the lens distortion
   undone through the division model) is cast into the model with Embree. The windows and lenses are
   left out, so rays pass through the glass.
3. Where the first surface hit belongs to a static part, the pixel's colour goes into that part's
   texture at the hit point. Each sample is weighted by how squarely and how closely the camera saw
   the surface, so where both cameras see a surface the better view dominates.
4. Pixels are skipped when they are outside the glovebox-interior mask (the blurred room), on the
   robot (its SAM mask: the robot moves, so its pixels must not be painted onto what is behind it), on
   the burned-in clock or title, or on a depth edge, where a small pose error would put one part's
   colour onto its neighbour.
5. Texels no camera saw keep the part's finish colour; the edge between seen and unseen is feathered.
   The two cameras' white balance is matched over the texels both saw.

The robot, the cables, the camera housings and the decals keep their own finishes: the robot moves, and
its fitted pose is not tight enough to carry a projected texture (IoU 0.63 in Overhead 1).

The cross-view check (--check) is a test of the geometry that needs no textures: each pixel of one
camera is traced to the model's surface, and that surface point is looked up in the other camera's
photo, if that camera sees it. With perfect geometry (and matte surfaces) the result would reproduce the
first camera's photo. Where a part is misplaced, the two disagree. out/crossview.json scores each part
by the normalised cross-correlation of the two.
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np
import trimesh

import materials

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.join(HERE, "..", "vision"))
from cameras import CAL, CAM0, CAM1  # noqa: E402

STILLS = {"cam0": "2026-11-19_1822Z_cam0_192.168.3.150.jpg", "cam1": "2026-11-19_1822Z_cam1_192.168.3.151.jpg"}
TEXEL = 1.5                      # mm per texel
SKIP_GROUPS = ("epson", "cables", "cameras")
CLEAR = ("window", "lens_glass")
# burned-in overlays (full-resolution pixels): the clock (top centre) and the title (bottom left)
OVERLAYS = ((1290, 15, 1880, 125), (20, 960, 190, 1065))
COS_LO, COS_HI = 0.45, 0.75      # cosine of the viewing angle: samples fade in between these
PHOTO_ROUGH = 0.6               # roughness where the photo covers a surface
TWO_VIEW_ONLY = ("deck",)        # parts textured only where both cameras saw them and agree: cables and tubing
                                 # lying above the deck would otherwise be painted onto it far from where they are
AGREE_PX = (35.0, 90.0)          # colour difference (0-255) where two cameras start / stop counting as agreeing


def texturable(p):
    return (getattr(p, "image", None) is None and p.group not in SKIP_GROUPS
            and getattr(p, "material", "") not in CLEAR)


def occluder(p):
    """Everything but glass, and the camera housings (each camera sits inside its own)."""
    return getattr(p, "material", "") not in CLEAR and p.group != "cameras"


# ---- texture coordinates ---------------------------------------------------------------------------------

def unwrap(parts, texel=TEXEL, max_size=4096):
    """xatlas per group. Returns {part index: (vertices, faces, uv, group)} and {group: (W, H)}. Faces keep
    their order, so a face index from the ray cast still points at the same triangle."""
    import xatlas
    groups = {}
    for i, p in enumerate(parts):
        if texturable(p):
            groups.setdefault(p.group, []).append(i)
    out, sizes = {}, {}
    for g, idx in groups.items():
        t = texel
        while True:
            atlas = xatlas.Atlas()
            for i in idx:
                m = parts[i].mesh
                atlas.add_mesh(np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.uint32))
            co = xatlas.ChartOptions()
            co.max_iterations = 1
            po = xatlas.PackOptions()
            po.texels_per_unit = 1.0 / t
            po.padding = 4
            po.bilinear = True
            po.blockAlign = True
            atlas.generate(co, po)
            if max(atlas.width, atlas.height) <= max_size:
                break
            t *= 1.25
        sizes[g] = (atlas.width, atlas.height, t)
        for k, i in enumerate(idx):
            vmap, ind, uv = atlas[k]
            m = parts[i].mesh
            out[i] = (np.asarray(m.vertices)[vmap], ind.astype(np.int64), uv.astype(np.float64), g)
        print(f"  {g}: {len(idx)} parts, atlas {atlas.width} x {atlas.height} at {t:.2f} mm", flush=True)
    return out, sizes


# ---- ray casting -------------------------------------------------------------------------------------------

class Scene:
    """All occluding parts as one mesh for Embree, with the face -> (part, local face) map."""

    def __init__(self, parts):
        ms, owner, local = [], [], []
        for i, p in enumerate(parts):
            if occluder(p) and len(p.mesh.faces):
                ms.append(p.mesh)
                owner.append(np.full(len(p.mesh.faces), i))
                local.append(np.arange(len(p.mesh.faces)))
        self.mesh = trimesh.util.concatenate(ms)
        self.owner, self.local = np.concatenate(owner), np.concatenate(local)
        try:
            from trimesh.ray.ray_pyembree import RayMeshIntersector
            self.rt = RayMeshIntersector(self.mesh)
        except Exception:
            self.rt = self.mesh.ray

    def cast(self, origins, dirs):
        """First hit per ray: (hit point, global face, distance); face -1 where nothing is hit."""
        n = len(dirs)
        face = np.full(n, -1, np.int64)
        P = np.full((n, 3), np.nan)
        loc, ri, ti = self.rt.intersects_location(origins, dirs, multiple_hits=False)
        face[ri] = ti
        P[ri] = loc
        dist = np.linalg.norm(P - origins, axis=1)
        return P, face, dist


def pixel_rays(cam, step=1):
    H, W = CAL["image_size"][1], CAL["image_size"][0]
    vv, uu = np.mgrid[0:H:step, 0:W:step]
    px = np.c_[uu.ravel(), vv.ravel()].astype(float)
    d = cam.ray(px)
    return px, np.repeat(cam.centre[None], len(d), 0), d, (len(range(0, H, step)), len(range(0, W, step)))


def valid_pixels(cam_name, shape):
    """Interior mask minus the robot and the burned-in overlays (full resolution)."""
    vm = os.path.join(HERE, "..", "vision", "masks")
    ok = cv2.imread(os.path.join(vm, f"inside_{cam_name}.png"), 0) > 127
    rb = cv2.imread(os.path.join(vm, f"robot_{cam_name}.png"), 0)
    if rb is not None:
        ok &= ~(cv2.dilate((rb > 127).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0)
    for x0, y0, x1, y1 in OVERLAYS:
        ok[y0:y1, x0:x1] = False
    ok = cv2.erode(ok.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return cv2.resize(ok.astype(np.uint8), (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST) > 0


def depth_edges(dist, shape, rel=0.03):
    """Pixels next to a jump in depth of more than rel (3 %): silhouettes, where a pose error of a few mm
    moves one part's colour onto another."""
    D = dist.reshape(shape).copy()
    D[~np.isfinite(D)] = 1e6
    mx = cv2.dilate(D.astype(np.float32), np.ones((5, 5), np.uint8))
    mn = cv2.erode(D.astype(np.float32), np.ones((5, 5), np.uint8))
    return ((mx - mn) / np.maximum(mn, 1.0) > rel).ravel()


# ---- splatting into the atlases --------------------------------------------------------------------------

def bary(P, tri):
    return trimesh.triangles.points_to_barycentric(tri, P)


def splat_camera(parts, uvmap, sizes, scene, cam, photo, acc, step=1):
    px, O, Dr, shape = pixel_rays(cam, step)
    t0 = time.time()
    P, face, dist = scene.cast(O, Dr)
    print(f"  {cam.name}: {len(Dr)} rays in {time.time() - t0:.1f} s, {np.mean(face >= 0):.2f} hit", flush=True)
    ok = (face >= 0) & valid_pixels(cam.name, shape).ravel() & ~depth_edges(dist, shape)
    lf = scene.local[np.maximum(face, 0)]
    img = photo.astype(np.float32)
    col = img[px[:, 1].astype(int), px[:, 0].astype(int)]
    nrm = scene.mesh.face_normals[np.maximum(face, 0)]
    cosang = np.abs(np.einsum("ij,ij->i", nrm, -Dr))
    # grazing views smear anything not in the model (cables, clutter) across the surface behind it, so
    # samples fade out between COS_LO and COS_HI and are dropped below COS_LO
    ramp = np.clip((cosang - COS_LO) / (COS_HI - COS_LO), 0, 1)
    ok &= cosang > COS_LO
    w_all = ramp * cosang ** 2 / np.maximum(dist / 1000.0, 0.05) ** 2
    pi = np.where(ok, scene.owner[np.maximum(face, 0)], -1)
    stats = {}
    for i in np.unique(pi[pi >= 0]):
        if i not in uvmap:
            continue
        sel = np.where(pi == i)[0]
        V, F, UV, g = uvmap[i]
        tri = V[F[lf[sel]]]
        b = bary(P[sel], tri)
        uv = np.einsum("ij,ijk->ik", b, UV[F[lf[sel]]])
        W, H, _ = sizes[g]
        x = uv[:, 0] * W - 0.5
        y = (1.0 - uv[:, 1]) * H - 0.5
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        fx, fy = x - x0, y - y0
        a = acc[g]
        for dx, dy, ww in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            xx, yy = np.clip(x0 + dx, 0, W - 1), np.clip(y0 + dy, 0, H - 1)
            wt = (ww * w_all[sel]).astype(np.float32)
            np.add.at(a[cam.name]["w"], (yy, xx), wt)
            for c in range(3):
                np.add.at(a[cam.name]["c"][..., c], (yy, xx), wt * col[sel, c])
        stats[parts[i].name] = stats.get(parts[i].name, 0) + int(len(sel))
    return stats


def normalised(c, w, sigma=1.2):
    """Normalised convolution: fills the gaps between splatted samples (far surfaces get fewer pixels than
    texels) without spreading colour far beyond where samples are."""
    k = int(2 * round(3 * sigma) + 1)
    ws = cv2.GaussianBlur(w, (k, k), sigma)
    cs = np.stack([cv2.GaussianBlur(c[..., i], (k, k), sigma) for i in range(3)], -1)
    return cs / np.maximum(ws, 1e-9)[..., None], ws


def finish(parts, uvmap, sizes, acc):
    """Blend the cameras, match their white balance, fill to the finish colour where unseen."""
    # white balance: cam1's gains to cam0 over texels both saw well
    num, den = [], []
    for g, a in acc.items():
        c0, w0 = normalised(a["cam0"]["c"], a["cam0"]["w"])
        c1, w1 = normalised(a["cam1"]["c"], a["cam1"]["w"])
        both = (w0 > np.percentile(w0[w0 > 0], 20) if (w0 > 0).any() else w0 > 0) & \
               (w1 > np.percentile(w1[w1 > 0], 20) if (w1 > 0).any() else w1 > 0)
        if both.sum() > 200:
            num.append(c0[both])
            den.append(c1[both])
    gain = np.ones(3)
    if num:
        A, B = np.vstack(num), np.vstack(den)
        gain = np.median(A + 1, 0) / np.median(B + 1, 0)
    print("  cam1 -> cam0 gains (B, G, R):", np.round(gain, 3), flush=True)
    images, conf, mr = {}, {}, {}
    for g, a in acc.items():
        W, H, _ = sizes[g]
        c0, w0 = normalised(a["cam0"]["c"], a["cam0"]["w"])
        c1, w1 = normalised(a["cam1"]["c"] * gain.astype(np.float32), a["cam1"]["w"])
        c0, c1 = np.nan_to_num(c0), np.nan_to_num(c1)
        sup = []
        for ws in (w0, w1):
            ref = np.percentile(ws[ws > 0], 10) if (ws > 0).any() else 1.0
            sup.append(np.clip(ws / max(ref, 1e-9), 0, 1).astype(np.float32))
        s0, s1 = sup
        col = (c0 * w0[..., None] + c1 * w1[..., None]) / np.maximum(w0 + w1, 1e-9)[..., None]
        # where both cameras saw a texel, they should agree on its colour; when they don't, one of them
        # is looking at something the model lacks (a cable, a moved part) and the texel falls back
        # towards the part's finish colour
        diff = np.abs(c0 - c1).max(-1)
        agree = np.clip(1 - (diff - AGREE_PX[0]) / (AGREE_PX[1] - AGREE_PX[0]), 0.15, 1.0)
        both = (s0 > 0.2) & (s1 > 0.2)
        base = np.zeros((H, W, 3), np.float32)
        finish_mr = np.zeros((H, W, 2), np.float32)          # the part's own roughness and metallic
        strict = np.zeros((H, W), np.uint8)
        for i, (V, F, UV, gg) in uvmap.items():
            if gg != g:
                continue
            bgr = np.array([int(parts[i].color.lstrip("#")[k:k + 2], 16) for k in (4, 2, 0)], np.float32)
            spec = materials.M.get(parts[i].material, materials.M["paint"])
            rm = [float(spec.get("roughness", 0.5)), float(spec.get("metallic", 0.0))]
            pts = np.c_[UV[:, 0] * W, (1 - UV[:, 1]) * H].astype(np.float32)
            tris = pts[F].round().astype(np.int32)
            for t in tris:
                cv2.fillConvexPoly(base, t, bgr.tolist(), lineType=cv2.LINE_8)
                cv2.fillConvexPoly(finish_mr, t, rm, lineType=cv2.LINE_8)
            if parts[i].name in TWO_VIEW_ONLY:
                cv2.fillPoly(strict, list(tris), 1)
        cf = np.where(strict > 0, np.minimum(s0, s1) * agree * both,
                      np.maximum(s0, s1) * np.where(both, agree, 1.0))
        cf = cv2.GaussianBlur(cf.astype(np.float32), (0, 0), 1.0)
        # grow each part's base colour into the padding so bilinear lookups at chart edges stay on-part
        out = cf[..., None] * np.nan_to_num(col) + (1 - cf[..., None]) * base
        images[g] = np.clip(out, 0, 255).astype(np.uint8)
        conf[g] = cf
        # metallic-roughness texture (glTF reads G as roughness and B as metallic; R is free and carries the
        # photo coverage for blender_render.py): where the photo covers a texel, it already holds the light
        # the camera saw, so the surface turns matte and non-metallic there; elsewhere the finish stays
        rough = cf * PHOTO_ROUGH + (1 - cf) * finish_mr[..., 0]
        metal = (1 - cf) * finish_mr[..., 1]
        mr[g] = np.clip(np.dstack([metal, rough, cf]) * 255, 0, 255).astype(np.uint8)   # BGR order for cv2
    return images, conf, gain, mr


# ---- export -------------------------------------------------------------------------------------------------

def export(parts, uvmap, images, mr, path):
    """GLB: textured static parts (photo colour as base colour, matte, so any viewer shows the photo's
    colours), the robot, cables, cameras and decals with their own finishes."""
    from PIL import Image
    sc = trimesh.Scene()
    pil = {g: Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)) for g, im in images.items()}
    pil_mr = {g: Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)) for g, im in mr.items()}
    mats = {}
    for i, p in enumerate(parts):
        if i in uvmap:
            V, F, UV, g = uvmap[i]
            m = trimesh.Trimesh(V, F, process=False)
            if g not in mats:
                mats[g] = trimesh.visual.material.PBRMaterial(
                    name=f"photo {g}", baseColorTexture=pil[g], metallicRoughnessTexture=pil_mr[g],
                    metallicFactor=1.0, roughnessFactor=1.0, doubleSided=False)
            m.visual = trimesh.visual.TextureVisuals(uv=UV, material=mats[g])
        elif getattr(p, "image", None) is not None:
            m = p.mesh.copy()
            m.visual = trimesh.visual.TextureVisuals(uv=p.uv, material=materials.pbr("decal", image=p.image))
        else:
            m = materials.smooth(p.mesh.copy())
            spec = materials.M.get(p.material, materials.M["paint"])
            col = p.color if p.color.lower() != spec["color"] else None
            m.visual = trimesh.visual.TextureVisuals(material=materials.pbr(
                p.material if p.material in materials.M else "paint", color=col))
        sc.add_geometry(m, node_name=f"{i:03d} {p.name}", geom_name=f"{i:03d} {p.name}")
    sc.export(path)


# ---- cross-view check ----------------------------------------------------------------------------------------

def bilinear(img, xy, width=1024):
    n = len(xy)
    pad = (-n) % width
    q = np.vstack([xy, np.zeros((pad, 2))]).astype(np.float32)
    m = cv2.remap(img, q[:, 0].reshape(-1, width), q[:, 1].reshape(-1, width), cv2.INTER_LINEAR,
                  borderMode=cv2.BORDER_CONSTANT)
    return m.reshape(n + pad, -1)[:n]


def crossview(parts, scene, photos, step=2):
    """Warp each camera's photo into the other through the model's surface. Returns the figure and the
    per-part scores."""
    rows, scores = [], {}
    for A, B in ((CAM0, CAM1), (CAM1, CAM0)):
        px, O, Dr, shape = pixel_rays(B, step)
        P, face, dist = scene.cast(O, Dr)
        ok = (face >= 0) & valid_pixels(B.name, shape).ravel()
        # visible from A? cast from A's centre to the point and compare distances
        dA = P - A.centre
        rA = np.linalg.norm(dA, axis=1)
        dirA = dA / np.maximum(rA, 1e-9)[:, None]
        sel = np.where(ok)[0]
        _, fA, distA = scene.cast(np.repeat(A.centre[None], len(sel), 0), dirA[sel])
        vis = np.zeros(len(P), bool)
        vis[sel] = np.abs(distA - rA[sel]) < np.maximum(6.0, 0.006 * rA[sel])
        uvA, zA = A.project(P[vis])
        inside = (zA > 0) & (uvA[:, 0] >= 0) & (uvA[:, 0] < 1919) & (uvA[:, 1] >= 0) & (uvA[:, 1] < 1079)
        okA = valid_pixels(A.name, (1080, 1920))
        inside &= okA[np.clip(uvA[:, 1].round().astype(int), 0, 1079), np.clip(uvA[:, 0].round().astype(int), 0, 1919)]
        vi = np.where(vis)[0][inside]
        warped = np.zeros((len(P), 3), np.float32)
        warped[vi] = bilinear(photos[A.name], uvA[inside])
        have = np.zeros(len(P), bool)
        have[vi] = True
        real = photos[B.name][px[:, 1].astype(int), px[:, 0].astype(int)].astype(np.float32)
        # exposure / white balance: per-channel gain over the overlap
        g = np.median(real[have] + 1, 0) / np.median(warped[have] + 1, 0)
        warped *= g
        Wimg = warped.reshape(*shape, 3)
        Rimg = real.reshape(*shape, 3)
        Hm = have.reshape(shape)
        # local normalised cross-correlation of the grey images over 15 x 15 windows
        gw = cv2.cvtColor(np.clip(Wimg, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
        gr = cv2.cvtColor(Rimg.astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
        k = (15, 15)
        mw, mr = cv2.blur(gw, k), cv2.blur(gr, k)
        cov = cv2.blur(gw * gr, k) - mw * mr
        vw, vr = cv2.blur(gw * gw, k) - mw ** 2, cv2.blur(gr * gr, k) - mr ** 2
        ncc = cov / np.sqrt(np.maximum(vw * vr, 1e-6))
        textured = (vr > 25) & (vw > 25)
        Hm_t = Hm & (cv2.erode(Hm.astype(np.uint8), np.ones(k, np.uint8)) > 0) & textured
        owner = np.where(face >= 0, scene.owner[np.maximum(face, 0)], -1).reshape(shape)
        for i in np.unique(owner[Hm_t]):
            sel_i = Hm_t & (owner == i)
            if sel_i.sum() >= 150:
                nm = parts[i].name
                s = scores.setdefault(nm, {})
                s[f"{A.name}->{B.name}"] = dict(ncc=round(float(np.median(ncc[sel_i])), 3), px=int(sel_i.sum()))
        overall = float(np.median(ncc[Hm_t])) if Hm_t.any() else float("nan")
        vis_img = np.where(Hm[..., None], np.clip(Wimg, 0, 255), (Rimg * 0.25)).astype(np.uint8)
        heat = cv2.applyColorMap(np.clip((1 - np.nan_to_num(ncc)) * 127, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
        heat = np.where(Hm_t[..., None], heat, (Rimg * 0.25).astype(np.uint8))
        row = np.hstack([Rimg.astype(np.uint8), vis_img, heat])
        lab = [f"{B.name} photo", f"{A.name} photo, through the model into {B.name}", "disagreement (1 - local NCC)"]
        for j, t in enumerate(lab):
            cv2.putText(row, t, (j * shape[1] + 12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        rows.append(row)
        scores.setdefault("_overall", {})[f"{A.name}->{B.name}"] = dict(
            median_ncc=round(overall, 3), overlap_px=int(Hm_t.sum()), step_px=step)
    return np.vstack(rows), scores


def load_parts():
    import scene
    return scene.build(CAL)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="also run the cross-view check")
    ap.add_argument("--parts", help="pickled parts list (development)")
    ap.add_argument("--texel", type=float, default=TEXEL)
    ap.add_argument("--out", default=os.path.join(OUT, "glovebox_photo.glb"))
    ap.add_argument("--atlases", help="also write each group's texture and coverage map to this directory")
    a = ap.parse_args()
    t0 = time.time()
    if a.parts:
        import pickle
        parts = pickle.load(open(a.parts, "rb"))
    else:
        parts = load_parts()
    photos = {k: cv2.imread(os.path.join(HERE, "..", "captures", v)) for k, v in STILLS.items()}
    scene = Scene(parts)
    print(f"{len(parts)} parts, {len(scene.mesh.faces)} occluding faces ({time.time() - t0:.0f} s)", flush=True)
    if a.check:
        fig, scores = crossview(parts, scene, photos)
        cv2.imwrite(os.path.join(OUT, "crossview.jpg"), cv2.resize(fig, None, fx=0.5, fy=0.5,
                                                                   interpolation=cv2.INTER_AREA),
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
        json.dump(scores, open(os.path.join(OUT, "crossview.json"), "w"), indent=1)
        print("cross-view:", scores["_overall"], flush=True)
    uvmap, sizes = unwrap(parts, a.texel)
    print(f"unwrapped ({time.time() - t0:.0f} s)", flush=True)
    acc = {g: {c: dict(c=np.zeros((H, W, 3), np.float32), w=np.zeros((H, W), np.float32)) for c in ("cam0", "cam1")}
           for g, (W, H, _) in sizes.items()}
    seen = {}
    for cam in (CAM0, CAM1):
        seen[cam.name] = splat_camera(parts, uvmap, sizes, scene, cam, photos[cam.name], acc)
    images, conf, gain, mr = finish(parts, uvmap, sizes, acc)
    if a.atlases:
        os.makedirs(a.atlases, exist_ok=True)
        for g, im in images.items():
            cv2.imwrite(os.path.join(a.atlases, f"{g}.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 88])
            cv2.imwrite(os.path.join(a.atlases, f"{g}_seen.png"), (conf[g] * 255).astype(np.uint8))
    export(parts, uvmap, images, mr, a.out)
    area = {g: 0.0 for g in sizes}
    seen_area = {g: 0.0 for g in sizes}
    for i, (V, F, UV, g) in uvmap.items():
        W, H, _ = sizes[g]
        tri = np.c_[UV[:, 0] * W, (1 - UV[:, 1]) * H][F]
        mask = np.zeros((H, W), np.uint8)
        cv2.fillPoly(mask, tri.round().astype(np.int32), 1)
        area[g] += float(mask.sum())
        seen_area[g] += float((conf[g][mask > 0] > 0.5).sum())
    rep = dict(texel_mm={g: round(s[2], 2) for g, s in sizes.items()},
               atlas_px={g: [s[0], s[1]] for g, s in sizes.items()},
               seen_fraction={g: round(seen_area[g] / max(area[g], 1), 3) for g in sizes},
               cam1_to_cam0_gain_bgr=np.round(gain, 3).tolist(),
               pixels_used={k: sum(v.values()) for k, v in seen.items()},
               stills=STILLS, skipped_groups=list(SKIP_GROUPS))
    json.dump(rep, open(os.path.join(OUT, "phototexture.json"), "w"), indent=1)
    print(json.dumps(rep["seen_fraction"]), f"({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
