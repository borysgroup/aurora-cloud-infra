"""Renders of the nylon-kit stud mount, and STEP assemblies (threads shown as plain cores in the STEP).

    xvfb-run -a python kit/render_kit.py

Writes kit/kit_overview.png, kit_mount_zero.png, kit_mount_hq.png, kit_zero_exploded.png, kit_hq_exploded.png,
kit_parts.png (the STLs as printed, threads included) and kit/stud_mount_kit_*.step.
Uses ../render_stud_mount.py's scene, lights and colours. The black nylon screws, nuts and standoffs are drawn
slate grey so they show against the dark printed parts.
"""

from __future__ import annotations

import pathlib
import sys
import types

import pyvista as pv

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "printed"))
import render_stud_mount as rsm  # noqa: E402
import stud_mount as sm  # noqa: E402
import stud_mount_kit as sk  # noqa: E402

rsm.sm = types.SimpleNamespace(parts=sk.parts, tilt_depth=sk.tilt_depth, ceiling_stud=sm.ceiling_stud)
C = rsm.COLOURS
C["nylon"] = "#5d6672"
rsm.SPECULAR["nylon"] = 0.45


def overview(out):
    p = rsm.new_plotter((1600, 900))
    za, ha = (-150.0, 0.0, 0.0), (130.0, 0.0, 0.0)
    rsm.ceiling_section(p, [za[:2], ha[:2]], size=(600.0, 280.0), centre=(-10.0, 0.0))
    rsm.add_mount(p, "zero", 30.0, 50.0, za, skip_fixed=True)
    rsm.add_mount(p, "hq", -20.0, 90.0, ha, skip_fixed=True)
    rsm.label(p, "Pi Zero 2 W + Camera Module 3", (za[0] - 20, -40, -110))
    rsm.label(p, "Pi 5 + HQ Camera (8-50 mm zoom) + CM3 Wide", (ha[0] - 30, -30, -190))
    rsm.label(p, "printed thumb nut on the stud: pan", (za[0] + 40, 0, -16), "#b0541a")
    rsm.label(p, "printed M10 thumb screws: tilt", (za[0] - 75, 0, -62), "#b0541a")
    rsm.label(p, "boards and covers on nylon M2 / M2.5 screws, nuts, standoffs", (ha[0] - 60, 40, -40), "#4b5563")
    p.camera_position = [(-170.0, -700.0, -450.0), (-10.0, 0.0, -115.0), (0.0, 0.0, 1.0)]
    p.camera.view_angle = 30.0
    p.screenshot(str(out / "kit_overview.png"))
    p.close()
    for kind, pan, tilt in (("zero", 25.0, 45.0), ("hq", -25.0, 70.0)):
        p = rsm.new_plotter((1200, 900))
        rsm.ceiling_section(p, [(0.0, 0.0)], size=(340.0, 230.0))
        rsm.add_mount(p, kind, pan, tilt, skip_fixed=True)
        d = sk.tilt_depth(kind)
        f = 1.0 if kind == "zero" else 1.7
        p.camera_position = [(-250.0 * f, -360.0 * f, -60.0 * f - d), (0.0, -10.0, -d - 10.0 * f), (0, 0, 1)]
        p.camera.view_angle = 30.0
        p.screenshot(str(out / f"kit_mount_{kind}.png"))
        p.close()


def exploded(out, kind):
    """The head's parts and kit hardware pulled apart along the view axis (head frame, tilt 0), tilt screws out
    sideways. Offsets (dy, dz) are matched by the longest key contained in the part's name; hardware that goes in
    from the front floats above the head so it isn't hidden behind it."""
    head = sk.head_zero_parts() if kind == "zero" else sk.head_hq_parts()
    if kind == "zero":
        offs = {"case": (0, 0), "CM3": (14, 0), "M2 screws, CM3": (26, 0), "M2 nuts, CM3": (-16, 34),
                "M2.5 screws, Pi Zero": (-34, 34), "Pi Zero": (40, 0), "M2.5 standoffs, Pi Zero": (54, 0),
                "back cover": (74, 0), "M2.5 screws, back cover": (92, 0), "ribbon": None, "USB": None}
    else:
        offs = {"tub": (0, 0), "HQ": (0, 0), "zoom": (0, 0), "lens": (0, 0), "M2.5 screws, HQ Camera": (-40, 60),
                "M2.5 nuts, HQ Camera": (16, 0), "M2.5 screws, Wide nose": (14, 0), "M2.5 nuts, Wide nose": (-20, 0),
                "Wide nose": (-20, 0), "Wide": (-20, 0), "M2 screws, Wide": (-6, 0), "M2 nuts, Wide": (-34, 0),
                "M2.5 nuts, carrier": (0, 40), "carrier": (50, 0), "M2.5 screws, carrier": (72, 0),
                "M2.5 nuts, Pi 5": (50, 0), "Pi 5": (95, 0), "Active Cooler": (95, 0), "M2.5 screws, Pi 5": (120, 0),
                "ribbon": None}
    p = rsm.new_plotter((1600, 900))
    for name, (wp, mat) in head.items():
        key = next((k for k in sorted(offs, key=len, reverse=True) if k in name), None)
        off = offs.get(key, (0, 0))
        if off is None:
            continue
        m = rsm.to_mesh(wp, tol=0.04 if mat == "nylon" else 0.08).translate((0.0, off[0], off[1]), inplace=False)
        p.add_mesh(m, color=C[mat], specular=rsm.SPECULAR.get(mat, 0.25), smooth_shading=True)
    half = sk.head_half(kind)
    for sx in (-1, 1):
        s = sk.tilt_screw_local().rotate((0, 0, 0), (0, 1, 0), -90 * sx).translate((sx * (half + 28.0), 0, 0))
        p.add_mesh(rsm.to_mesh(s, tol=0.08), color=C["knob"], specular=0.25, smooth_shading=True)
    if kind == "zero":
        p.camera_position = [(185.0, 190.0, 150.0), (0.0, 30.0, 8.0), (0, 0, 1)]
        rsm.label(p, "case: threaded bosses, CM3 shoulders, Pi posts", (-30, -12, 24))
        rsm.label(p, "4 x M2 nut, into the front face", (-14, -16, 44), "#4b5563")
        rsm.label(p, "4 x M2.5 x 12, from the front face", (24, -34, 50), "#4b5563")
        rsm.label(p, "4 x M2 x 6", (-14, 26, 20), "#4b5563")
        rsm.label(p, "4 x F-F 6 mm standoff", (0, 54, 22), "#4b5563")
        rsm.label(p, "back cover, 4 x M2.5 x 6 into the standoffs", (20, 92, -30), "#4b5563")
        rsm.label(p, "M10 thumb screw", (half + 28, 0, 16), "#b0541a")
    else:
        p.camera_position = [(300.0, 230.0, 210.0), (0.0, 40.0, 10.0), (0, 0, 1)]
        rsm.label(p, "tub: plate, cheeks, threaded bosses, HQ posts", (-45, -10, 36))
        rsm.label(p, "HQ Camera: 4 x M2.5 x 12 from the front", (-15, -40, 82), "#4b5563")
        rsm.label(p, "4 x M2.5 nut on the HQ board", (-15, 16, 26), "#4b5563")
        rsm.label(p, "4 x M2.5 nut, side slots in the cheeks", (40, 20, 62), "#4b5563")
        rsm.label(p, "carrier: 4 x M2.5 x 8", (-40, 72, 40), "#4b5563")
        rsm.label(p, "Pi 5: 4 x M2.5 x 6, nuts in the posts' slots", (20, 122, 36), "#4b5563")
        rsm.label(p, "Wide nose: 3 x M2.5 x 8 from inside, nuts in slots; Wide: 4 x M2 x 8", (30, -90, -30),
                  "#4b5563")
    p.camera.view_angle = 30.0
    p.screenshot(str(out / f"kit_{kind}_exploded.png"))
    p.close()


def parts_sheet(out):
    """Every printed STL as it lies on the bed, in a grid (threads visible on the screw and the thumb nut)."""
    names = ["tilt_screw", "yoke_zero", "head_zero_case", "head_zero_back_cover", "yoke_hq", "head_hq_tub",
             "head_hq_carrier", "head_hq_wide_nose", "fit_coupon"]
    stls = {n: HERE / "stl" / f"{n}.stl" for n in names}
    stls = {"stud_thumb_nut": HERE.parent / "printed" / "stl" / "stud_thumb_nut.stl", **stls}
    p = pv.Plotter(off_screen=True, window_size=(1800, 1000), lighting="none")
    p.set_background("#f8fafc", top="#dde5ee")
    p.add_light(pv.Light(position=(400, -600, 900), focal_point=(270, -150, 0), intensity=0.9))
    p.add_light(pv.Light(position=(-300, 200, 600), focal_point=(270, -150, 0), intensity=0.45))
    p.add_light(pv.Light(light_type="headlight", intensity=0.3))
    p.enable_anti_aliasing("ssaa")
    x, y, row_h = 0.0, 0.0, 0.0
    for n, path in stls.items():
        m = pv.read(str(path))
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
    p.screenshot(str(out / "kit_parts.png"))
    p.close()


def steps(out):
    for kind, tilt in (("zero", 45.0), ("hq", 90.0)):
        sk.assembly(kind, 0.0, tilt).save(str(out / f"stud_mount_kit_{kind}.step"))


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
