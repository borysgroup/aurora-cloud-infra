"""Renders the inside of both heads from behind (Pi Zero head with its back cover off, HQ frame with the Pi 5
carrier off) and the printed parts as they sit on the bed: print/heads_inside.png and print/printed_parts.png.

    xvfb-run -a python print/render_heads.py          # from design/stud-camera-mount
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyvista as pv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import render_stud_mount as rs  # noqa: E402
import stud_mount as sm  # noqa: E402

LABELS = {"case": "printed posts for the Pi, bosses for the camera", "ribbon": "camera ribbon, U-turn into the Pi",
          "inserts": "M4 inserts in blind holes", "frame": "frame: plate, cheeks, columns, bosses"}


def head_view(p, parts, hide, cam):
    for name, (s, m) in parts.items():
        if any(h in name for h in hide) or "lead" in name:
            continue
        p.add_mesh(rs.to_mesh(s), color=rs.COLOURS[m], specular=rs.SPECULAR.get(m, 0.15), smooth_shading=True)
    p.camera_position = cam
    p.set_background("#fcfcfb")


def main():
    p = pv.Plotter(shape=(1, 2), off_screen=True, window_size=(1600, 760))
    p.subplot(0, 0)
    head_view(p, sm.head_zero_parts(), ("back cover", "USB"), [(-70, 140, 60), (0, 3, 0), (0, 0, 1)])
    p.add_text("Pi Zero head, back cover off", font_size=12, color="#0b0b0b")
    p.subplot(0, 1)
    head_view(p, sm.head_hq_parts(), ("Pi carrier", "Pi 5", "Active Cooler", "HQ ribbon", "Wide ribbon"),
              [(-110, 220, 90), (0, 0, 0), (0, 0, 1)])
    p.add_text("HQ frame, Pi 5 carrier off", font_size=12, color="#0b0b0b")
    p.screenshot(str(HERE / "heads_inside.png"))
    p.close()

    names = [n for g in sm.PRINTED.values() for n in g]
    cols = 5
    rows = int(np.ceil(len(names) / cols))
    p = pv.Plotter(shape=(rows, cols), off_screen=True, window_size=(1700, 360 * rows))
    for i, name in enumerate(names):
        p.subplot(i // cols, i % cols)
        mesh = pv.read(str(HERE / "stl" / f"{name}.stl"))
        p.add_mesh(mesh, color="#d96b1a" if "knob" in name or "nut" in name else "#3a3d42", smooth_shading=True,
                   specular=0.2)
        b = mesh.bounds
        p.add_mesh(pv.Plane(center=((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, -0.05), i_size=(b[1] - b[0]) * 1.4,
                            j_size=(b[3] - b[2]) * 1.4), color="#b8bcc2")
        p.camera_position = "iso"
        p.camera.zoom(1.1)
        p.add_text(name, font_size=9, color="#0b0b0b")
        p.set_background("#fcfcfb")
    p.screenshot(str(HERE / "printed_parts.png"))
    p.close()


if __name__ == "__main__":
    main()
