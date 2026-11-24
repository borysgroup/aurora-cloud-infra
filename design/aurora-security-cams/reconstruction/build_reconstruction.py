"""Build the glovebox reconstruction, export it, and render it from both cameras and from outside.

    xvfb-run -a python build_reconstruction.py [--photos DIR] [--blender PATH] [--samples N]

Writes out/glovebox.glb (one node per part, each with its finish as a PBR material and the printed marks
as textured decals), out/stl/<group>.stl (decimated to at most 40k faces per group, for GitHub's STL
viewer), out/parts.json (name, group, finish, colour, bounds and the source of each part's numbers), and:
  out/overlay_cam0.jpg, out/overlay_cam1.jpg     the model blended over the published frame, edges in yellow
                                                 (quick OpenGL render, lens distortion applied)
With Blender 4.2 (--blender, or $BLENDER), also the Cycles renders (blender_render.py):
  out/view_cam0.jpg, out/view_cam1.jpg           the published frame next to the model through the same
                                                 camera and lens
  out/render_open_side.jpg, render_far_end.jpg,  the model from outside (ceiling and open-side window
  render_top.jpg                                 hidden) and from above
  out/render_epson.jpg, render_gantry.jpg        two views inside the box
--photos defaults to the published 18:22 UTC stills in ../captures (already blurred).
"""
import argparse
import json
import os
import shutil
import subprocess

import cv2
import numpy as np
import trimesh

import render
import scene
from cameras import C, CAL, CAM0, CAM1, LAM
from lensmodel import undistort_px

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
STILLS = {"cam0": "2026-11-19_1822Z_cam0_192.168.3.150.jpg", "cam1": "2026-11-19_1822Z_cam1_192.168.3.151.jpg"}


def distort_canvas(canvas, s, size=(1920, 1080)):
    """Pinhole render on a canvas twice the frame (times s) -> the camera's distorted frame at scale s."""
    Wo, Ho = int(round(size[0] * s)), int(round(size[1] * s))
    uu, vv = np.meshgrid((np.arange(Wo) + 0.5) / s - 0.5, (np.arange(Ho) + 0.5) / s - 0.5)
    pu = undistort_px(np.c_[uu.ravel(), vv.ravel()], C, LAM)
    ch, cw = canvas.shape[:2]
    mx = ((pu[:, 0] - C[0]) * s + (cw - 1) / 2).reshape(Ho, Wo).astype(np.float32)
    my = ((pu[:, 1] - C[1]) * s + (ch - 1) / 2).reshape(Ho, Wo).astype(np.float32)
    return cv2.remap(canvas, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def blender_renders(blender, glb, photos, samples, views=()):
    tmp = os.path.join(OUT, "_blender")
    os.makedirs(tmp, exist_ok=True)
    subprocess.run([blender, "-b", "--factory-startup", "-P", os.path.join(HERE, "blender_render.py"), "--", glb, tmp,
                    *views, "--samples", str(samples)], check=True)
    for cam in (CAM0, CAM1):
        if not os.path.exists(os.path.join(tmp, f"{cam.name}_pinhole.png")):
            continue
        canvas = cv2.imread(os.path.join(tmp, f"{cam.name}_pinhole.png"))
        img = distort_canvas(canvas, 0.5)
        photo = cv2.resize(cv2.imread(os.path.join(photos, STILLS[cam.name])), (img.shape[1], img.shape[0]))
        cv2.imwrite(os.path.join(OUT, f"view_{cam.name}.jpg"), np.hstack([photo, img]), [cv2.IMWRITE_JPEG_QUALITY, 90])
    for v in ("open_side", "far_end", "epson", "gantry", "top"):
        p = os.path.join(tmp, f"{v}.png")
        if os.path.exists(p):
            cv2.imwrite(os.path.join(OUT, f"render_{v}.jpg"), cv2.imread(p), [cv2.IMWRITE_JPEG_QUALITY, 90])
    shutil.rmtree(tmp)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photos", default=os.path.join(HERE, "..", "captures"))
    ap.add_argument("--blender", default=os.environ.get("BLENDER", shutil.which("blender")))
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--views", nargs="*", default=[], help="Blender views to render (default: all)")
    ap.add_argument("--renders-only", action="store_true", help="re-render out/glovebox.glb without rebuilding it")
    a = ap.parse_args()
    if a.renders_only:
        blender_renders(a.blender, os.path.join(OUT, "glovebox.glb"), a.photos, a.samples, a.views)
        return
    os.makedirs(os.path.join(OUT, "stl"), exist_ok=True)
    parts = scene.build(CAL)

    # exports
    glb = os.path.join(OUT, "glovebox.glb")
    scene.export(parts, glb)
    groups = {}
    for p in parts:
        if getattr(p, "image", None) is None:
            groups.setdefault(p.group, []).append(p.mesh)
    for g, ms in groups.items():
        m = trimesh.util.concatenate(ms)
        if len(m.faces) > 40000:
            m = m.simplify_quadric_decimation(face_count=40000)
        m.export(os.path.join(OUT, "stl", f"{g}.stl"))
    rows = []
    for p in parts:
        lo, hi = p.mesh.bounds
        key = next((k for k in scene.SOURCES if p.name.lower().startswith(k.lower()) or k.lower() in p.name.lower()
                    or k == p.group), None)
        rows.append(dict(name=p.name, group=p.group, finish=getattr(p, "material", None), colour=p.color,
                         faces=int(len(p.mesh.faces)),
                         bounds_mm=[np.round(lo, 1).tolist(), np.round(hi, 1).tolist()],
                         source=scene.SOURCES.get(key, scene.SOURCES.get(p.group, {})) if key else
                         scene.SOURCES.get(p.group, {})))
    pose_file = os.path.join(OUT, "epson_cad_pose.json")
    json.dump(dict(frame="aurora_chamber scene frame, mm: x from the antechamber-end wall, y from the open side, "
                         "z up from the deck", robot_pose=json.load(open(pose_file)) if os.path.exists(pose_file)
                   else scene.ROBOT, tray=CAL["tray"],
                   cameras={k: dict(centre=np.round(CAL["cameras"][k]["centre"], 1).tolist(),
                                    view_dir=np.round(CAL["cameras"][k]["view_dir"], 3).tolist()) for k in ("cam0", "cam1")},
                   sources=scene.SOURCES, parts=rows), open(os.path.join(OUT, "parts.json"), "w"), indent=1)

    # quick OpenGL renders over the published (blurred) frames: the geometric check
    for cam in (CAM0, CAM1):
        photo = cv2.imread(os.path.join(a.photos, STILLS[cam.name]))
        img, m = render.render_camera([p for p in parts if p.group != "cameras"], cam)
        ov = render.overlay(photo, img, m, alpha=0.5)
        cv2.imwrite(os.path.join(OUT, f"overlay_{cam.name}.jpg"), cv2.resize(ov, (1280, 720)),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
    if a.blender:
        blender_renders(a.blender, glb, a.photos, a.samples, a.views)
    else:
        print("Blender not found (--blender or $BLENDER): skipped the Cycles renders")
    print(f"{len(parts)} parts, {sum(len(p.mesh.faces) for p in parts)} faces; wrote {OUT}")


if __name__ == "__main__":
    main()
