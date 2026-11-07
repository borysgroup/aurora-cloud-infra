"""Exports the stud mount (STL per printed part in print/stl, STEP per assembly) and renders it hanging from a ceiling stud.

    xvfb-run -a python render_stud_mount.py            # exports, stills, pan/tilt animation (MP4 + GIF)
    xvfb-run -a python render_stud_mount.py --stills   # exports and stills only
    xvfb-run -a python render_stud_mount.py --animation
"""

from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
from pathlib import Path

import cadquery as cq
import imageio.v2 as imageio
import imageio_ffmpeg
import numpy as np
import pyvista as pv

import stud_mount as sm

HERE = Path(__file__).resolve().parent
COLOURS = dict(petg="#26282b", knob="#d96b1a", steel="#c0c4cb", pcb="#1f7a3c", lens="#141516", glass="#4d73a6",
               white="#eeeeee", port="#b3b8bf", black="#1a1a1a", cooler="#8c949e", ribbon="#d9a640")
SPECULAR = dict(steel=0.7, glass=0.9, lens=0.4)


def to_mesh(wp, tol=0.15):
    pts, faces, off = [], [], 0
    for sol in wp.vals():
        v, t = sol.tessellate(tol, 0.3)
        pts += [(p.x, p.y, p.z) for p in v]
        faces += [[3, a + off, b + off, c + off] for a, b, c in t]
        off += len(v)
    return pv.PolyData(np.array(pts, float), np.array(faces).ravel()).compute_normals(split_vertices=True)


def rot(axis, deg, pivot=(0.0, 0.0, 0.0)):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    t = math.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    R = np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * K @ K
    m = np.eye(4)
    m[:3, :3] = R
    p = np.asarray(pivot, float)
    m[:3, 3] = p - R @ p
    return m


def trans(v):
    m = np.eye(4)
    m[:3, 3] = v
    return m


def mount_matrices(kind, pan, tilt, at=(0.0, 0.0, 0.0)):
    """{piece: 4x4} for a mount whose stud root is at `at` (scene frame, ceiling underside at z = at[2])."""
    depth = sm.tilt_depth(kind)
    base = trans(at)
    mp = base @ rot((0, 0, 1), pan)
    mh = mp @ trans((0, 0, -depth)) @ rot((1, 0, 0), tilt)
    return {"fixed": base, "pan": mp, "head": mh}


_MESHES: dict = {}


def mount_meshes(kind, wide=True):
    """{piece: [(mesh, material)]} in each piece's own frame (cached)."""
    key = (kind, wide)
    if key not in _MESHES:
        _MESHES[key] = {piece: [(to_mesh(s), m) for s, m in items.values()]
                        for piece, items in sm.parts(kind, wide).items()}
    return _MESHES[key]


def add_mount(p, kind, pan, tilt, at=(0.0, 0.0, 0.0), wide=True, skip_fixed=False):
    """Adds a posed mount to a plotter; returns {piece: [actors]} for animating with set_pose."""
    mats = mount_matrices(kind, pan, tilt, at)
    actors = {}
    for piece, items in mount_meshes(kind, wide).items():
        if skip_fixed and piece == "fixed":
            continue
        actors[piece] = []
        for mesh, mat in items:
            a = p.add_mesh(mesh, color=COLOURS[mat], specular=SPECULAR.get(mat, 0.25), smooth_shading=True)
            a.user_matrix = mats[piece]
            actors[piece].append(a)
    return actors


def set_pose(actors, kind, pan, tilt, at=(0.0, 0.0, 0.0)):
    mats = mount_matrices(kind, pan, tilt, at)
    for piece, acts in actors.items():
        for a in acts:
            a.user_matrix = mats[piece]


def ceiling_section(p, studs, size=(520.0, 260.0), centre=(0.0, 0.0)):
    """A piece of the stainless ceiling (seen from below) with its studs."""
    cx, cy = centre
    sheet = pv.Box(bounds=(cx - size[0] / 2, cx + size[0] / 2, cy - size[1] / 2, cy + size[1] / 2, 0.0, 3.0))
    p.add_mesh(sheet, color="#d5dade", specular=0.5)
    stud = to_mesh(sm.ceiling_stud())
    for x, y in studs:
        p.add_mesh(stud.translate((x, y, 0.0), inplace=False), color=COLOURS["steel"], specular=0.7)


def new_plotter(size, aa="ssaa"):
    p = pv.Plotter(off_screen=True, window_size=size, lighting="none")
    p.set_background("#f8fafc", top="#dde5ee")
    p.add_light(pv.Light(position=(500, -1500, -700), focal_point=(0, 0, -100), intensity=0.85))
    p.add_light(pv.Light(position=(-1300, -300, -500), focal_point=(0, 0, -100), intensity=0.40))
    p.add_light(pv.Light(position=(900, 900, -900), focal_point=(0, 0, -100), intensity=0.30))
    p.add_light(pv.Light(light_type="headlight", intensity=0.25))
    p.enable_anti_aliasing(aa)
    return p


ZERO_AT, HQ_AT = (-140.0, 0.0, 0.0), (120.0, 0.0, 0.0)


def label(p, text, xyz, colour="#1f2933"):
    p.add_point_labels([xyz], [text], font_size=15, text_color="white", shape_color=colour, shape="rounded_rect",
                       shape_opacity=0.92, show_points=False, always_visible=True, margin=4)


def stills(out):
    """Overview of both mounts, and a close-up of each."""
    size = (1600, 900)
    p = new_plotter(size)
    ceiling_section(p, [ZERO_AT[:2], HQ_AT[:2]])
    add_mount(p, "zero", 30.0, 50.0, ZERO_AT, skip_fixed=True)
    add_mount(p, "hq", -20.0, 90.0, HQ_AT, skip_fixed=True)
    label(p, "Pi Zero 2 W + Camera Module 3", (ZERO_AT[0] - 20, -40, -105))
    label(p, "Pi 5 + HQ Camera (8-50 mm zoom) + CM3 Wide", (HQ_AT[0] - 30, -30, -175))
    label(p, "thumb nut on the stud: pan", (ZERO_AT[0] + 30, 0, -16), "#b0541a")
    label(p, "thumb knobs: tilt", (ZERO_AT[0] - 62, 0, -62), "#b0541a")
    p.camera_position = [(-170.0, -640.0, -420.0), (-10.0, 0.0, -105.0), (0.0, 0.0, 1.0)]
    p.camera.view_angle = 30.0
    p.screenshot(str(out / "stud_mount_overview.png"))
    p.close()
    for kind, pan, tilt in (("zero", 25.0, 45.0), ("hq", -25.0, 70.0)):
        p = new_plotter((1200, 900))
        ceiling_section(p, [(0.0, 0.0)], size=(320.0, 220.0))
        add_mount(p, kind, pan, tilt, skip_fixed=True)
        d = sm.tilt_depth(kind)
        f = 1.0 if kind == "zero" else 1.7
        p.camera_position = [(-230.0 * f, -330.0 * f, -60.0 * f - d), (0.0, -10.0, -d - 10.0 * f), (0, 0, 1)]
        p.camera.view_angle = 30.0
        p.screenshot(str(out / f"stud_mount_{kind}.png"))
        p.close()


def animation(out, fps=24):
    """Both mounts on one ceiling section: pan one way and back, then tilt from level to straight down."""
    size = (1280, 720)
    p = new_plotter(size, aa="fxaa")
    ceiling_section(p, [ZERO_AT[:2], HQ_AT[:2]])
    za = add_mount(p, "zero", 0.0, 0.0, ZERO_AT, skip_fixed=True)
    ha = add_mount(p, "hq", 0.0, 0.0, HQ_AT, skip_fixed=True)
    caption = p.add_text("", position=(24, 24), font_size=14, color="#1f2933")
    p.camera_position = [(-190.0, -700.0, -470.0), (-10.0, 0.0, -115.0), (0.0, 0.0, 1.0)]
    p.camera.view_angle = 30.0
    # (seconds, caption, pan from -> to, tilt from -> to)
    acts = [(1.5, "One ceiling stud per mount. Left: Pi Zero 2 W + CM3. Right: Pi 5 + HQ zoom + CM3 Wide",
             (0, 0), (0, 0)),
            (2.5, "Pan: loosen the thumb nut on the stud a quarter turn, turn the yoke, retighten", (0, 60), (0, 0)),
            (2.5, "", (60, -45), (0, 0)),
            (3.0, "Tilt: loosen the two side knobs; the head turns between the yoke's arms",
             (-45, -45), (0, 90)),
            (2.0, "HQ head straight down (overhead), Zero head forward and down",
             (-45, 0), (90, 90)),
            (1.5, "", (0, 0), (90, 90))]
    frames = []
    for dur, text, (p0, p1), (t0, t1) in acts:
        if text:
            caption.SetInput(text)
        n = max(1, int(dur * fps))
        for i in range(n):
            s = 0.5 - 0.5 * math.cos(math.pi * i / max(1, n - 1))
            pan, tilt = p0 + (p1 - p0) * s, t0 + (t1 - t0) * s
            set_pose(za, "zero", pan, min(tilt, 50.0), ZERO_AT)
            set_pose(ha, "hq", -pan, tilt, HQ_AT)
            p.render()
            frames.append(p.screenshot(return_img=True))
    p.close()
    mp4 = out / "stud_mount_pan_tilt.mp4"
    imageio.mimsave(mp4, frames, fps=fps, quality=8, macro_block_size=8)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    vf = "fps=12,scale=800:-1:flags=lanczos"
    with tempfile.TemporaryDirectory() as tmp:
        pal = Path(tmp) / "palette.png"
        subprocess.run([ff, "-y", "-v", "error", "-i", str(mp4), "-vf", f"{vf},palettegen=max_colors=96:stats_mode=diff",
                        str(pal)], check=True)
        subprocess.run([ff, "-y", "-v", "error", "-i", str(mp4), "-i", str(pal), "-lavfi",
                        f"{vf}[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle",
                        str(out / "stud_mount_pan_tilt.gif")], check=True)


def exports(out):
    """STL per printed part in its print orientation (print/stl, as print/slice_h2d.py slices them), STEP per
    assembly."""
    stl = out / "print" / "stl"
    stl.mkdir(parents=True, exist_ok=True)
    for group in sm.PRINTED.values():
        for name, make in group.items():
            cq.exporters.export(make(), str(stl / f"{name}.stl"), tolerance=0.01, angularTolerance=0.1)
    for kind, tilt in (("zero", 45.0), ("hq", 90.0)):
        sm.assembly(kind, 0.0, tilt).save(str(out / f"stud_mount_{kind}.step"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", action="store_true", help="exports and stills only")
    ap.add_argument("--animation", action="store_true", help="the animation only")
    a = ap.parse_args()
    if not a.animation:
        exports(HERE)
        stills(HERE)
    if not a.stills:
        animation(HERE)


if __name__ == "__main__":
    main()
