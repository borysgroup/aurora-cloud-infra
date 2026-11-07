"""Plate thumbnails for the sliced .gcode.3mf files (the H2D's screen and Bambu Studio's file list show them).

The command-line slicer only renders thumbnails when it can open an OpenGL window, which the Linux AppImage can't do
on a headless machine, so this renders each plate with PyVista instead: the parts' STLs placed at the positions the
slicer arranged them (from Metadata/plate_1.json; arranging moves parts but doesn't turn them), in the filament's
colour on the 350 x 320 mm bed, and writes Metadata/plate_1.png (512 px) and plate_1_small.png (128 px).

    xvfb-run -a python print/thumbnails.py          # from design/stud-camera-mount, after slice_h2d.py
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pyvista as pv
from PIL import Image

HERE = Path(__file__).resolve().parent
BED = (350.0, 320.0)


def render(path3mf: Path, stl_dir: Path, size=512) -> Image.Image:
    with zipfile.ZipFile(path3mf) as z:
        meta = json.loads(z.read("Metadata/plate_1.json"))
    colour = meta.get("filament_colors", ["#00AE42"])[0]
    p = pv.Plotter(off_screen=True, window_size=(size, size))
    p.add_mesh(pv.Plane(center=(BED[0] / 2, BED[1] / 2, -0.2), i_size=BED[0], j_size=BED[1]), color="#3b3e42")
    for o in meta["bbox_objects"]:
        mesh = pv.read(str(stl_dir / o["name"]))
        b = mesh.bounds
        x0, y0, x1, y1 = o["bbox"]
        mesh = mesh.translate(((x0 + x1) / 2 - (b[0] + b[1]) / 2, (y0 + y1) / 2 - (b[2] + b[3]) / 2, -b[4]))
        p.add_mesh(mesh, color=colour, smooth_shading=True, specular=0.2)
    bx = meta["bbox_all"]
    c = np.array([(bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2, 0.0])
    span = max(bx[2] - bx[0], bx[3] - bx[1], 60.0)
    p.camera_position = [tuple(c + np.array([0.0, -0.8, 1.0]) * span), tuple(c), (0, 0, 1)]
    p.reset_camera(bounds=(bx[0], bx[2], bx[1], bx[3], 0.0, 40.0))
    p.camera.zoom(1.15)
    p.set_background("#1f2124")
    img = p.screenshot(return_img=True, transparent_background=False)
    p.close()
    return Image.fromarray(img)


def add_thumbnails(path3mf: Path, stl_dir: Path):
    img = render(path3mf, stl_dir)
    pngs = {}
    for name, px in (("Metadata/plate_1.png", 512), ("Metadata/plate_1_small.png", 128)):
        buf = io.BytesIO()
        img.resize((px, px), Image.LANCZOS).save(buf, format="PNG")
        pngs[name] = buf.getvalue()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / path3mf.name
        with zipfile.ZipFile(path3mf) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in pngs:
                    continue
                zout.writestr(item, zin.read(item.filename))
            for name, data in pngs.items():
                zout.writestr(name, data)
        shutil.move(str(tmp), path3mf)


if __name__ == "__main__":
    for f in sorted(HERE.glob("*.gcode.3mf")):
        add_thumbnails(f, HERE / "stl")
        print("thumbnail:", f.name)
    sys.exit(0)
