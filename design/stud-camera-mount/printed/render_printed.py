"""Renders of the all-printed stud mount, and STEP assemblies (threads shown as plain cores in the STEP).

    xvfb-run -a python printed/render_printed.py

Writes printed/printed_overview.png, printed_mount_zero.png, printed_mount_hq.png, printed_zero_exploded.png,
printed_hq_exploded.png, printed_parts.png (the STLs as printed, threads included) and printed/stud_mount_printed_*.step.
Uses ../render_stud_mount.py's scene, lights and colours.
"""

from __future__ import annotations

import math
import pathlib
import sys
import types

import numpy as np
import pyvista as pv

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import render_stud_mount as rsm  # noqa: E402
import stud_mount as sm  # noqa: E402
import stud_mount_printed as spm  # noqa: E402

rsm.sm = types.SimpleNamespace(parts=spm.parts, tilt_depth=spm.tilt_depth, ceiling_stud=sm.ceiling_stud)
C = rsm.COLOURS


def overview(out):
    p = rsm.new_plotter((1600, 900))
    za, ha = (-150.0, 0.0, 0.0), (130.0, 0.0, 0.0)
    rsm.ceiling_section(p, [za[:2], ha[:2]], size=(600.0, 280.0), centre=(-10.0, 0.0))
    rsm.add_mount(p, "zero", 30.0, 50.0, za, skip_fixed=True)
    rsm.add_mount(p, "hq", -20.0, 90.0, ha, skip_fixed=True)
    rsm.label(p, "Pi Zero 2 W + Camera Module 3", (za[0] - 20, -40, -110))
    rsm.label(p, "Pi 5 + HQ Camera (8-50 mm zoom) + CM3 Wide", (ha[0] - 30, -30, -190))
    rsm.label(p, "printed thumb nut, M6 thread on the steel stud: pan", (za[0] + 40, 0, -16), "#b0541a")
    rsm.label(p, "printed M10 thumb screws: tilt", (za[0] - 75, 0, -62), "#b0541a")
    p.camera_position = [(-170.0, -700.0, -450.0), (-10.0, 0.0, -115.0), (0.0, 0.0, 1.0)]
    p.camera.view_angle = 30.0
    p.screenshot(str(out / "printed_overview.png"))
    p.close()
    for kind, pan, tilt in (("zero", 25.0, 45.0), ("hq", -25.0, 70.0)):
        p = rsm.new_plotter((1200, 900))
        rsm.ceiling_section(p, [(0.0, 0.0)], size=(340.0, 230.0))
        rsm.add_mount(p, kind, pan, tilt, skip_fixed=True)
        d = spm.tilt_depth(kind)
        f = 1.0 if kind == "zero" else 1.7
        p.camera_position = [(-250.0 * f, -360.0 * f, -60.0 * f - d), (0.0, -10.0, -d - 10.0 * f), (0, 0, 1)]
        p.camera.view_angle = 30.0
        p.screenshot(str(out / f"printed_mount_{kind}.png"))
        p.close()


def exploded(out, kind):
    """The head's parts pulled apart along the view axis, the tilt screws pulled out sideways (head frame, tilt 0)."""
    head = spm.head_zero_parts() if kind == "zero" else spm.head_hq_parts()
    if kind == "zero":
        offs = {"case": 0.0, "CM3": -0.0, "Pi Zero": 22.0, "back cover": 45.0, "ribbon": 1e9, "USB": 1e9}
    else:
        offs = {"tub": 0.0, "HQ": 0.0, "zoom": 0.0, "lens": 0.0, "Wide": 0.0, "HQ retainer": 30.0, "carrier": 60.0,
                "Pi 5 ports": 90.0, "Pi 5": 90.0, "Active Cooler": 90.0, "Pi 5 retainer": 125.0, "ribbon": 1e9}
    p = rsm.new_plotter((1600, 900))
    for name, (wp, mat) in head.items():
        key = next((k for k in sorted(offs, key=len, reverse=True) if k in name), None)
        dy = offs.get(key, 0.0)
        if dy > 1e8:
            continue
        m = rsm.to_mesh(wp, tol=0.08).translate((0.0, dy, 0.0), inplace=False)
        p.add_mesh(m, color=C[mat], specular=rsm.SPECULAR.get(mat, 0.25), smooth_shading=True)
    half = spm.head_half(kind)
    for sx in (-1, 1):
        s = spm.tilt_screw_local(kind).rotate((0, 0, 0), (0, 1, 0), -90 * sx).translate((sx * (half + 28.0), 0, 0))
        p.add_mesh(rsm.to_mesh(s, tol=0.08), color=C["knob"], specular=0.25, smooth_shading=True)
    f = 0.62 if kind == "zero" else 1.05
    p.camera_position = [(260.0 * f, -40.0 + 300.0 * f, 170.0 * f), (0.0, 22.0 if kind == "zero" else 60.0, 0.0),
                         (0, 0, 1)]
    p.camera.view_angle = 30.0
    if kind == "zero":
        rsm.label(p, "case: CM3 on pegs, Pi posts + pegs, threaded bosses", (-30, -12, 24))
        rsm.label(p, "Pi Zero 2 W", (-10, 22, 20))
        rsm.label(p, "back cover: pillars press the Pi, ears go under the yoke arms", (10, 50, -26))
        rsm.label(p, "M10 thumb screw", (half + 28, 0, 16), "#b0541a")
    else:
        rsm.label(p, "tub: plate, cheeks, threaded bosses, HQ pegs", (-45, -10, 34))
        rsm.label(p, "HQ retainer", (-15, 30, -28))
        rsm.label(p, "carrier: Pi 5 posts + pegs", (-40, 62, 40))
        rsm.label(p, "Pi 5 retainer, ears under the yoke arms", (30, 128, -38))
    p.screenshot(str(out / f"printed_{kind}_exploded.png"))
    p.close()


def parts_sheet(out):
    """Every printed STL as it lies on the bed, in a grid (threads visible on the screw and the thumb nut)."""
    names = ["stud_thumb_nut", "tilt_screw", "yoke_zero", "head_zero_case", "head_zero_back_cover", "yoke_hq",
             "head_hq_tub", "head_hq_retainer", "head_hq_carrier", "head_hq_pi5_retainer", "head_hq_wide_nose",
             "coupon_m6_vertical", "coupon_m10_horizontal"]
    p = pv.Plotter(off_screen=True, window_size=(1800, 1000), lighting="none")
    p.set_background("#f8fafc", top="#dde5ee")
    p.add_light(pv.Light(position=(400, -600, 900), focal_point=(270, -150, 0), intensity=0.9))
    p.add_light(pv.Light(position=(-300, 200, 600), focal_point=(270, -150, 0), intensity=0.45))
    p.add_light(pv.Light(light_type="headlight", intensity=0.3))
    p.enable_anti_aliasing("ssaa")
    x, y, row_h, cols = 0.0, 0.0, 0.0, 0
    for n in names:
        m = pv.read(str(HERE / "stl" / f"{n}.stl"))
        b = m.bounds
        w, h = b[1] - b[0], b[3] - b[2]
        if x + w > 520.0:
            x, y, row_h = 0.0, y - row_h - 25.0, 0.0
        m = m.translate((x - b[0], y - b[3], -b[4]), inplace=False)
        colour = C["knob"] if n in ("stud_thumb_nut", "tilt_screw") else ("#8fa3b8" if "coupon" in n else "#5b6470")
        p.add_mesh(m.compute_normals(split_vertices=True, feature_angle=35), color=colour, specular=0.3,
                   smooth_shading=True)
        p.add_point_labels([(x + w / 2, y + 4.0, 0.0)], [n], font_size=12, text_color="#1f2933", shape_color="white",
                           shape_opacity=0.85, show_points=False, always_visible=True)
        x += w + 25.0
        row_h = max(row_h, h)
    bed = pv.Box(bounds=(-20, 560, y - row_h - 40, 30, -3.0, 0.0))
    p.add_mesh(bed, color="#c9ced4")
    p.camera_position = [(265.0, y * 0.5 - 560.0, 620.0), (265.0, y * 0.5 - 45, 0.0), (0, 0, 1)]
    p.camera.view_angle = 32.0
    p.screenshot(str(out / "printed_parts.png"))
    p.close()


def steps(out):
    for kind, tilt in (("zero", 45.0), ("hq", 90.0)):
        spm.assembly(kind, 0.0, tilt).save(str(out / f"stud_mount_printed_{kind}.step"))


if __name__ == "__main__":
    only = sys.argv[1:] or ["overview", "exploded", "parts", "steps"]
    if "overview" in only:
        overview(HERE)
    if "exploded" in only:
        exploded(HERE, "zero")
        exploded(HERE, "hq")
    if "parts" in only:
        parts_sheet(HERE)
    if "steps" in only:
        steps(HERE)
