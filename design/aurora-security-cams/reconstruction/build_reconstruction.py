"""Build the glovebox reconstruction, export it, and render it from both cameras and from outside.

    xvfb-run -a python build_reconstruction.py [--photos DIR]

Writes out/glovebox.glb (one coloured node per part), out/stl/<group>.stl, out/parts.json (name, group,
colour, bounds and the source of each part's numbers), and renders:
  out/overview_open_side.png, out/overview_top.png       the model from outside, cameras marked
  out/view_cam0.jpg, out/view_cam1.jpg                    the model as each camera sees it (lens distortion
                                                          applied), next to the published, blurred frame
  out/overlay_cam0.jpg, out/overlay_cam1.jpg              the model blended over the blurred frame
  out/turntable.gif                                       an orbit around the model
--photos defaults to the published 18:22 UTC stills in ../captures (already blurred).
"""
import argparse
import json
import os

import cv2
import numpy as np
import pyvista as pv
import trimesh

import render
import scene
from cameras import CAL, CAM0, CAM1

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
STILLS = {"cam0": "2026-11-19_1822Z_cam0_192.168.3.150.jpg", "cam1": "2026-11-19_1822Z_cam1_192.168.3.151.jpg"}


def camera_glyph(cam, size=60.0):
    """A small pyramid for a camera: apex at the centre, base along its view direction."""
    c, R = cam.centre, cam.R
    f, r, d = R[2], R[0], R[1]
    base = [c + size * (1.4 * f + sx * 0.8 * r + sy * 0.45 * d) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    V = np.array([c] + base)
    F = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1], [1, 3, 2], [1, 4, 3]])
    return trimesh.Trimesh(V, F)


def turntable(parts, path, n=30, size=(800, 520)):
    """Orbit around the box (ceiling and near frames hidden) and write an animated GIF."""
    import imageio.v2 as imageio
    shown = [p for p in parts if p.name not in ("ceiling", "open side window frame")]
    extra = [(camera_glyph(c), "#ff2d2d") for c in (CAM0, CAM1)]
    frames = []
    for k in range(n):
        a = np.radians(-90 + 360.0 * k / n)
        pos = (600 + 2300 * np.cos(a), 560 + 2300 * np.sin(a), 1500)
        frames.append(render.render_view(shown, position=pos, focal=(600, 560, 220), size=size, view_angle=34,
                                         extra=extra)[:, :, ::-1])
    imageio.mimsave(path, frames, duration=0.25, loop=0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photos", default=os.path.join(HERE, "..", "captures"))
    a = ap.parse_args()
    os.makedirs(os.path.join(OUT, "stl"), exist_ok=True)
    parts = scene.build(CAL)

    # exports
    scene.export(parts, os.path.join(OUT, "glovebox.glb"))
    groups = {}
    for p in parts:
        groups.setdefault(p.group, []).append(p.mesh)
    for g, ms in groups.items():
        trimesh.util.concatenate(ms).export(os.path.join(OUT, "stl", f"{g}.stl"))
    rows = []
    for p in parts:
        lo, hi = p.mesh.bounds
        key = next((k for k in scene.SOURCES if p.name.lower().startswith(k.lower()) or k.lower() in p.name.lower()
                    or k == p.group), None)
        rows.append(dict(name=p.name, group=p.group, colour=p.color, bounds_mm=[np.round(lo, 1).tolist(),
                                                                                np.round(hi, 1).tolist()],
                         source=scene.SOURCES.get(key, scene.SOURCES.get(p.group, {})) if key else
                         scene.SOURCES.get(p.group, {})))
    json.dump(dict(frame="aurora_chamber scene frame, mm: x from the antechamber-end wall, y from the open side, "
                         "z up from the deck", robot_pose=scene.ROBOT, tray=CAL["tray"],
                   cameras={k: dict(centre=np.round(CAL["cameras"][k]["centre"], 1).tolist(),
                                    view_dir=np.round(CAL["cameras"][k]["view_dir"], 3).tolist()) for k in ("cam0", "cam1")},
                   sources=scene.SOURCES, parts=rows), open(os.path.join(OUT, "parts.json"), "w"), indent=1)

    # renders from the cameras, next to and over the published (blurred) frames
    for cam in (CAM0, CAM1):
        photo = cv2.imread(os.path.join(a.photos, STILLS[cam.name]))
        img, m = render.render_camera(parts, cam)
        img[m == 0] = (245, 245, 245)
        side = np.hstack([cv2.resize(photo, (960, 540)), cv2.resize(img, (960, 540))])
        cv2.imwrite(os.path.join(OUT, f"view_{cam.name}.jpg"), side, [cv2.IMWRITE_JPEG_QUALITY, 88])
        ov = render.overlay(photo, img, m, alpha=0.5)
        cv2.imwrite(os.path.join(OUT, f"overlay_{cam.name}.jpg"), cv2.resize(ov, (1280, 720)),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])

    # overviews from outside: drop the ceiling and the near window frames so the inside shows
    hide = ("ceiling", "open side window frame")
    shown = [p for p in parts if p.name not in hide]
    extra = [(camera_glyph(c), "#ff2d2d") for c in (CAM0, CAM1)]
    im = render.render_view(shown, position=(600, -1500, 1500), focal=(620, 520, 200), size=(1920, 1200),
                            view_angle=38, extra=extra)
    cv2.imwrite(os.path.join(OUT, "overview_open_side.png"), im)
    im = render.render_view(shown, position=(600, 560, 3200), focal=(600, 560, 0), up=(1, 0, 0), size=(1600, 1600),
                            view_angle=26, extra=extra)
    cv2.imwrite(os.path.join(OUT, "overview_top.png"), im)
    turntable(parts, os.path.join(OUT, "turntable.gif"))
    print(f"{len(parts)} parts, {sum(len(p.mesh.faces) for p in parts)} faces; wrote {OUT}")


if __name__ == "__main__":
    main()
