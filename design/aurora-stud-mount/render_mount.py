"""Renders the stud pan/tilt pod (assembly, tilt range, print layout) to PNG.

    xvfb-run -a python design/aurora-stud-mount/render_mount.py

Reads the STLs written by stud_pan_tilt_mount.py, so run that first. The ceiling,
stud, nut, bolt, Pi Zero 2 W and Camera Module 3 are simple stand-ins.
"""

import sys
from pathlib import Path

import numpy as np
import pyvista as pv
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stud_pan_tilt_mount as sm  # noqa: E402

pv.OFF_SCREEN = True
PETG = "#2f3338"
CRADLE = "#3a4a63"
KNOB = "#c8102e"
STEEL = "#c9ced3"
PCB = "#1f7a3c"

# print orientation -> installed frame (inverse of the rotations in export_all)
UNDO = {"pod_base": ("x", 180), "stud_knob": ("x", 180), "cm3_cradle": ("x", -90)}


def installed(name):
    m = pv.read(HERE / f"{name}.stl")
    axis, deg = UNDO[name]
    return m.rotate_x(deg, inplace=False)


def place_cradle(mesh, tilt, pan=0.0, origin=(0, 0, 0)):
    """Cradle frame -> installed frame at a tilt, then pan about the stud and move to `origin`."""
    m = mesh.rotate_y(-tilt, inplace=False).translate((sm.PIVOT_X, 0, sm.PIVOT_Z), inplace=False)
    return m.rotate_z(pan, inplace=False).translate(origin, inplace=False)


def camera_parts():
    """Camera Module 3 + ribbon stub in the cradle frame (tilt 0)."""
    w, h, t = sm.BOARD
    a = sm.board_point(-w / 2, 0, 0)
    b = sm.board_point(w / 2, h, t)
    board = pv.Box(bounds=(min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]),
                           min(a[2], b[2]), max(a[2], b[2])))
    c, d = sm.lens_axis()
    module = pv.Box(bounds=(c[0] - 5.4, c[0] + 5.4, c[1] - 5.4, c[1] + 5.4, c[2] - 4.1, c[2]))
    lens = pv.Cylinder(center=c + d * 6.2, direction=d, radius=4.25, height=4.2)
    e = sm.board_point(0, 0, -1.3)
    ribbon = pv.Box(bounds=(e[0] - 16, e[0], e[1] - 8, e[1] + 8, e[2] - 0.3, e[2]))
    return [(board, PCB), (module, "#151617"), (lens, "#0b0c0d"), (ribbon, "#e9e3cf")]


def static_parts(origin=(0, 0, 0), pan=0.0, ceiling=True):
    out = []
    if ceiling:
        out.append((pv.Box(bounds=(-110, 90, -45, 45, 0, 3)), STEEL))
    out.append((pv.Cylinder(center=(0, 0, -14), direction=(0, 0, 1), radius=sm.STUD_D / 2, height=28), "#8a9097"))
    out.append((installed("pod_base"), PETG))
    out.append((installed("stud_knob").translate((0, 0, -sm.BASE_T), inplace=False), KNOB))
    # Pi Zero 2 W hanging under the base
    zx, zz = sm.ZERO_CX, -sm.BASE_T - sm.ZERO_STANDOFF
    out.append((pv.Box(bounds=(zx - sm.ZERO_L / 2, zx + sm.ZERO_L / 2, -sm.ZERO_W / 2, sm.ZERO_W / 2, zz - 1.6, zz)), PCB))
    out.append((pv.Box(bounds=(zx - 6, zx + 6, -6, 6, zz - 2.8, zz - 1.6)), "#9ea3a8"))  # RP3A0 can
    # M4 hinge bolt
    out.append((pv.Cylinder(center=(sm.PIVOT_X, sm.TAB_T / 2 - 1, sm.PIVOT_Z), direction=(0, 1, 0), radius=2.0,
                            height=2 * sm.TAB_T + 8), "#8a9097"))
    out.append((pv.Cylinder(center=(sm.PIVOT_X, -sm.TAB_T - 1.4, sm.PIVOT_Z), direction=(0, 1, 0), radius=3.6,
                            height=2.8, resolution=6), "#8a9097"))
    return [(m.rotate_z(pan, inplace=False).translate(origin, inplace=False), c) for m, c in out]


def moving_parts(tilt, pan=0.0, origin=(0, 0, 0)):
    cradle = installed("cm3_cradle")
    out = [(place_cradle(cradle, tilt, pan, origin), CRADLE)]
    out += [(place_cradle(m, tilt, pan, origin), c) for m, c in camera_parts()]
    return out


def view_ray(tilt, pan=0.0, origin=(0, 0, 0), length=60.0):
    c, d = sm.lens_axis()
    p0 = place_cradle(pv.PolyData(np.array([c])), tilt, pan, origin).points[0]
    p1 = place_cradle(pv.PolyData(np.array([c + d * length])), tilt, pan, origin).points[0]
    return pv.Line(p0, p1).tube(radius=0.8)


def plotter(size):
    p = pv.Plotter(off_screen=True, window_size=size, lighting="none")
    p.set_background("#f8fafc", top="#e3e9f0")
    p.add_light(pv.Light(position=(300, -500, -400), focal_point=(0, 0, -30), intensity=0.85))
    p.add_light(pv.Light(position=(-400, 300, -100), focal_point=(0, 0, -30), intensity=0.35))
    p.add_light(pv.Light(position=(100, 200, 400), focal_point=(0, 0, -30), intensity=0.3))
    p.add_light(pv.Light(light_type="headlight", intensity=0.25))
    p.enable_anti_aliasing("ssaa")
    return p


def panel_iso(size=(900, 700), tilt=45):
    p = plotter(size)
    for m, c in static_parts():
        p.add_mesh(m, color=c, specular=0.3, opacity=0.35 if c == STEEL else 1.0)
    for m, c in moving_parts(tilt):
        p.add_mesh(m, color=c, specular=0.3)
    p.add_mesh(view_ray(tilt, length=90), color="#ff7a1a")
    p.camera_position = [(170, -230, -170), (-10, 0, -28), (0, 0, 1)]
    p.camera.zoom(1.05)
    img = p.screenshot(return_img=True)
    p.close()
    return img


def panel_side(size=(900, 700)):
    p = plotter(size)
    for m, c in static_parts():
        p.add_mesh(m, color=c, specular=0.3, opacity=0.35 if c == STEEL else 1.0)
    for k, tilt in enumerate((0, 45, 90)):
        op = 1.0 if tilt == 45 else 0.28
        for m, c in moving_parts(tilt):
            p.add_mesh(m, color=c, opacity=op)
        p.add_mesh(view_ray(tilt, length=70), color="#ff7a1a", opacity=max(op, 0.6))
    p.camera_position = [(-10, -520, -40), (-10, 0, -40), (0, 0, 1)]
    p.enable_parallel_projection()
    p.camera.parallel_scale = 72
    img = p.screenshot(return_img=True)
    p.close()
    return img


def panel_print(size=(900, 700)):
    p = plotter(size)
    p.add_mesh(pv.Box(bounds=(-95, 95, -55, 75, -1.0, 0)), color="#cfd5db")
    parts = [("pod_base", (0, 30, 0), PETG), ("stud_knob", (-55, -30, 0), KNOB), ("cm3_cradle", (40, -40, 0), CRADLE)]
    for name, off, col in parts:
        m = pv.read(HERE / f"{name}.stl")
        b = m.bounds
        m = m.translate((-(b[0] + b[1]) / 2 + off[0], -(b[2] + b[3]) / 2 + off[1], -b[4]), inplace=False)
        p.add_mesh(m, color=col, specular=0.3)
    p.camera_position = [(60, -260, 230), (0, 10, 10), (0, 0, 1)]
    img = p.screenshot(return_img=True)
    p.close()
    return img


def font(size, bold=False):
    path = Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def labelled(img, title, lines):
    im = Image.fromarray(img).convert("RGB")
    d = ImageDraw.Draw(im)
    d.text((22, 16), title, font=font(24, True), fill=(28, 36, 48))
    y = 50
    for ln in lines:
        d.text((24, y), ln, font=font(15), fill=(82, 92, 106))
        y += 21
    return im


def main():
    a = labelled(panel_iso(), "Stud pan/tilt pod (tilt 45 deg)",
                 ["Base clamps to the ceiling on one welded stud with the red knob.",
                  "Pan: loosen the knob, turn the pod about the stud.",
                  "Tilt: M4 hinge + M2 index pin, 0-90 deg in 15 deg steps.",
                  "Pi Zero 2 W under the base, Camera Module 3 on the cradle."])
    b = labelled(panel_side(), "Tilt range: 0, 45, 90 deg (side view)",
                 ["Orange line: optical axis. 0 = straight down, 90 = horizontal.",
                  "No part collides at any of the seven index positions."])
    c = labelled(panel_print(), "Print layout (PETG, no supports)",
                 ["pod_base 138 x 36 x 40 mm, stud_knob 28 x 12 mm,",
                  "cm3_cradle 32 x 44 x 28 mm. All fit the A1 mini bed."])
    w = a.width + b.width
    sheet = Image.new("RGB", (w, a.height + c.height), (248, 250, 252))
    sheet.paste(a, (0, 0))
    sheet.paste(b, (a.width, 0))
    sheet.paste(c, (0, a.height))
    # hardware list beside the print layout
    d = ImageDraw.Draw(sheet)
    x0, y = a.width + 30, a.height + 24
    d.text((x0, y), "Hardware per pod", font=font(24, True), fill=(28, 36, 48))
    y += 40
    rows = ["1 x M6 hex nut (pressed into the knob) - MEASURE stud thread",
            "1 x M4 x 16 bolt + M4 nyloc nut (hinge)",
            "1 x M2 x 12 screw (tilt index pin)",
            "4 x M2 x 6 self-tapping screws (Camera Module 3)",
            "4 x M2.5 x 6 self-tapping screws (Pi Zero 2 W)",
            "1 x Pi Zero camera cable, 22-to-15 pin, 150 mm",
            "",
            "Assumed, not measured:",
            "- stud thread M6 and at least 12 mm proud of the ceiling",
            "- ceiling flat within the 138 x 36 mm footprint",
            "",
            "Edit STUD_D / NUT_AF in stud_pan_tilt_mount.py for",
            "1/4\"-20 or M5 studs and re-run."]
    for r in rows:
        d.text((x0, y), r, font=font(17, r.endswith(":")), fill=(52, 60, 72))
        y += 27
    sheet.save(HERE / "stud_mount_overview.png", optimize=True)
    print("wrote", HERE / "stud_mount_overview.png", sheet.size)


if __name__ == "__main__":
    main()
