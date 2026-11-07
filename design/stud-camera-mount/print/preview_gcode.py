"""Previews of the sliced plates, read back from the G-code inside the .gcode.3mf files:

  preview_plates.png  first layer of each plate, with each part's name (the H2D's 350 x 320 mm bed)
  preview_ribs.png    one layer through each crush-rib pocket, extrusions drawn at their 0.42 mm width over the
                      designed outline, to check that the 0.3 mm ribs survive slicing

and prints the printed pocket sizes (the circle through the rib crests, and across the plain flats) from the
innermost wall's path.

    python print/preview_gcode.py          # from design/stud-camera-mount, after slice_h2d.py
"""

from __future__ import annotations

import json
import math
import re
import sys
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import stud_mount as sm  # noqa: E402

SURFACE, INK, INK2 = "#fcfcfb", "#0b0b0b", "#52514e"
FEATURE_COLOURS = {"Outer wall": "#2a78d6", "Inner wall": "#eb6834", "infill": "#1baf7a"}
LINE_W = 0.42
BED = (350.0, 320.0)
SHORT = {"yoke_zero": "yoke", "yoke_hq": "yoke", "head_zero_case": "case", "head_zero_back_cover": "cover",
         "head_hq_frame": "frame", "head_hq_pi_carrier": "carrier", "head_hq_wide_nose": "nose",
         "stud_thumb_nut": "nut", "tilt_knob": "knob"}


def read_gcode(path: Path) -> tuple[str, dict]:
    with zipfile.ZipFile(path) as z:
        return z.read("Metadata/plate_1.gcode").decode(), json.loads(z.read("Metadata/plate_1.json"))


def moves(gcode: str):
    """Extruding XY moves as (z, feature, x0, y0, x1, y1); relative E (M83) as Bambu Studio writes."""
    x = y = z = 0.0
    feature = ""
    out = []
    num = re.compile(r"([XYZE])(-?\d*\.?\d+)")
    for line in gcode.splitlines():
        if line.startswith("; FEATURE:"):
            feature = line.split(":", 1)[1].strip()
            continue
        if line.startswith("; Z_HEIGHT:"):
            z = float(line.split(":", 1)[1])
            continue
        if not (line.startswith("G1 ") or line.startswith("G0 ")):
            continue
        v = {k: float(n) for k, n in num.findall(line.split(";", 1)[0])}
        nx, ny = v.get("X", x), v.get("Y", y)
        if v.get("E", 0.0) > 0 and (nx != x or ny != y):
            out.append((z, feature, x, y, nx, ny))
        x, y = nx, ny
    return out


def colour(feature: str) -> str:
    if feature in FEATURE_COLOURS:
        return FEATURE_COLOURS[feature]
    return FEATURE_COLOURS["infill"]


def layer(ms, z, tol=0.05):
    return [m for m in ms if abs(m[0] - z) < tol]


def section(stl: Path, z: float):
    """Designed outline of a printed part at height z (print frame), as polylines."""
    mesh = trimesh.load_mesh(stl)
    s = mesh.section(plane_origin=(0, 0, z), plane_normal=(0, 0, 1))
    return [] if s is None else [np.asarray(d)[:, :2] for d in s.discrete]


def pocket_sizes(ms, centre, p):
    """Diameter of the circle through the rib crests and across the plain flats, mm, of the hole edge left by the
    innermost wall's path around a hex pocket centred at `centre` (half a line width inside the path). The CLI
    arranges parts without turning them, so the ribs are at their designed angles."""
    af, rib_h, n = p["af"], p["rib_h"], p.get("ribs", 6)
    cx, cy = centre
    pts = []
    for _, f, x0, y0, x1, y1 in ms:
        if f not in ("Outer wall", "Inner wall"):
            continue
        for t in np.linspace(0.0, 1.0, max(2, int(math.hypot(x1 - x0, y1 - y0) / 0.05) + 1)):   # every 0.05 mm
            px, py = x0 + t * (x1 - x0) - cx, y0 + t * (y1 - y0) - cy
            r = math.hypot(px, py)
            if r < af / 2 / math.cos(math.pi / 6) + 0.6:
                pts.append((math.degrees(math.atan2(py, px)) % 360.0, r))
    pts = np.array(pts)
    if len(pts) == 0:
        return None

    def edge(angle, half=3.0):
        d = np.abs((pts[:, 0] - angle + 180.0) % 360.0 - 180.0)
        sel = pts[d < half]
        return sel[:, 1].min() - LINE_W / 2 if len(sel) else float("nan")

    ribs = [30.0 + 360.0 / n * k for k in range(n)]
    plain = [a for a in (30.0 + 60.0 * k for k in range(6)) if min(abs((a - b + 180) % 360 - 180) for b in ribs) > 1]
    flats = plain if plain else [a + s * 15.0 for a in ribs for s in (-1, 1)]
    k = 1.0 if plain else math.cos(math.radians(15.0))
    crest = 2 * np.mean([edge(a) for a in ribs])
    flat = 2 * np.mean([edge(a) * k for a in flats])
    return dict(ribs=n, crest_d=round(float(crest), 3), flat_af=round(float(flat), 3),
                design_crest_d=round(af - 2 * rib_h, 3), design_flat_af=af)


def draw_paths(ax, ms, lw_pt):
    for f in ("infill", "Inner wall", "Outer wall"):
        segs = [((x0, y0), (x1, y1)) for _, ff, x0, y0, x1, y1 in ms
                if (ff if ff in FEATURE_COLOURS else "infill") == f]
        if segs:
            ax.add_collection(LineCollection(segs, colors=colour(f), linewidths=lw_pt, capstyle="round",
                                             alpha=0.85 if f == "infill" else 1.0, zorder=2))


def ribs_figure(path3mf: Path, out: Path):
    gcode, meta = read_gcode(path3mf)
    ms = moves(gcode)
    objs = {o["name"].replace(".stl", ""): o["bbox"] for o in meta["bbox_objects"]}
    nut_z = sm.KNOB["h"] - 0.5 * (sm.NUT_POCKET["depth"] - sm.NUT_POCKET["lead"])
    knob_z = sm.TILT["knob_h"] - 0.5 * (sm.HEAD_POCKET["depth"] - sm.HEAD_POCKET["lead"])
    cases = [("stud_thumb_nut", nut_z, sm.NUT_POCKET, "Thumb nut: M6 nut pocket"),
             ("tilt_knob", knob_z, sm.HEAD_POCKET, "Tilt knob: M4 bolt-head pocket")]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 5.6), facecolor=SURFACE)
    sizes = {}
    for ax, (name, z, p, title) in zip(axes, cases):
        zs = sorted({m[0] for m in ms})
        zl = min(zs, key=lambda q: abs(q - z))
        bx0, by0, bx1, by1 = objs[name]
        c = ((bx0 + bx1) / 2, (by0 + by1) / 2)
        lay = [m for m in layer(ms, zl) if bx0 - 1 < m[2] < bx1 + 1 and by0 - 1 < m[3] < by1 + 1]
        half = p["af"] / 2 / math.cos(math.pi / 6) + 2.2
        ax.set_xlim(c[0] - half, c[0] + half)
        ax.set_ylim(c[1] - half, c[1] + half)
        ax.set_aspect("equal")
        ax.set_facecolor(SURFACE)
        fig.canvas.draw()
        mm_per_pt = (2 * half) / (ax.get_window_extent().width * 72.0 / fig.dpi)
        draw_paths(ax, lay, LINE_W / mm_per_pt)
        # designed outline: the STL's section, centred on the part in its print frame
        stl = HERE / "stl" / f"{name}.stl"
        mesh_c = trimesh.load_mesh(stl).bounds.mean(axis=0)[:2]
        for poly in section(stl, zl):
            q = poly - mesh_c
            q = q + np.array(c)
            ax.plot(q[:, 0], q[:, 1], color=INK, lw=1.0, ls=(0, (4, 2)), zorder=3)
        sizes[name] = s = pocket_sizes(lay, c, p)
        ax.set_title(title, color=INK, fontsize=11, loc="left")
        if s:
            ax.text(0.02, 0.02, (f"layer z = {zl:.1f} mm, {s['ribs']} ribs\n"
                                 f"circle through the rib crests: {s['crest_d']:.2f} mm printed, "
                                 f"{s['design_crest_d']:.2f} designed\nacross the plain flats: {s['flat_af']:.2f} mm "
                                 f"printed, {s['design_flat_af']:.2f} designed"), transform=ax.transAxes, fontsize=8.5, color=INK2, va="bottom",
                    bbox=dict(facecolor=SURFACE, edgecolor="none", alpha=0.9))
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color("#d9d8d4")
    handles = [plt.Line2D([], [], color=FEATURE_COLOURS["Outer wall"], lw=4, label="outer wall (0.42 mm line)"),
               plt.Line2D([], [], color=FEATURE_COLOURS["Inner wall"], lw=4, label="inner walls"),
               plt.Line2D([], [], color=FEATURE_COLOURS["infill"], lw=4, label="solid infill"),
               plt.Line2D([], [], color=INK, lw=1.0, ls=(0, (4, 2)), label="designed outline")]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=9, labelcolor=INK)
    fig.suptitle("Crush-rib pockets in the sliced G-code (H2D 0.4 mm, PLA Basic, 0.2 mm layers)", color=INK,
                 fontsize=12, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return sizes


def plates_figure(files: list[Path], out: Path):
    fig, axes = plt.subplots(1, len(files), figsize=(5.0 * len(files), 4.9), facecolor=SURFACE)
    for ax, f in zip(np.atleast_1d(axes), files):
        gcode, meta = read_gcode(f)
        ms = moves(gcode)
        segs = [((x0, y0), (x1, y1)) for z, f, x0, y0, x1, y1 in ms if abs(z - 0.2) < 0.05 and f != "Custom"]
        ax.add_collection(LineCollection(segs, colors=FEATURE_COLOURS["Outer wall"], linewidths=0.4))
        ax.add_patch(plt.Rectangle((0, 0), *BED, fill=False, ec=INK2, lw=1.0))
        for o in meta["bbox_objects"]:
            x0, y0, x1, y1 = o["bbox"]
            ax.text((x0 + x1) / 2, (y0 + y1) / 2, SHORT.get(o["name"].replace(".stl", ""), o["name"]), ha="center",
                    va="center", fontsize=6.5, color=INK,
                    bbox=dict(facecolor=SURFACE, edgecolor="none", alpha=0.8, pad=0.8))
        ax.set_xlim(-5, BED[0] + 5)
        ax.set_ylim(-5, BED[1] + 5)
        ax.set_aspect("equal")
        ax.set_facecolor(SURFACE)
        ax.set_title(f.name.replace(".gcode.3mf", "").replace("_", " "), color=INK, fontsize=11, loc="left")
        ax.tick_params(colors=INK2, labelsize=7)
        for sp in ax.spines.values():
            sp.set_visible(False)
    fig.suptitle("First layer of each plate on the H2D bed (350 x 320 mm)", color=INK, fontsize=12, x=0.02,
                 ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    sizes = ribs_figure(HERE / "test_fit_pockets.gcode.3mf", HERE / "preview_ribs.png")
    print(json.dumps(sizes, indent=1))
    plates_figure([HERE / f"{n}.gcode.3mf" for n in ("test_fit_pockets", "zero_mounts_x2", "hq_mount")],
                  HERE / "preview_plates.png")
