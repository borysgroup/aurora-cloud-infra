"""Animated 3D render of the Aurora glovebox and the planned camera positions.

    xvfb-run -a python design/aurora-camera-layout/render_camera_layout.py [--stills-only]

Writes PNG stills, an MP4 and a GIF next to this file. Needs pyvista, imageio,
imageio-ffmpeg and pillow, plus ffmpeg on PATH (gifsicle optional, shrinks the GIF);
on a headless machine run it under xvfb-run.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
import pyvista as pv
import vtk
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import aurora_equipment as eq  # noqa: E402
import camera_models as cm  # noqa: E402
from scene_primitives import frustum, frustum_edges, look_frame  # noqa: E402

pv.OFF_SCREEN = True

ZERO_COLOR = "#ff7a1a"  # Pi Zero 2 W + Camera Module 3 livestreams
HQ_COLOR = "#16b364"    # Pi 5 + HQ Camera channels
EXISTING_COLOR = "#7d8590"
KIND_COLOR = {"zero": ZERO_COLOR, "hq": HQ_COLOR, "existing": EXISTING_COLOR}

# Camera Module 3: 66 x 41 deg; Module 3 Wide: 102 x 67 deg; HQ Camera with the
# 8-50 mm zoom at about 12 mm on the IMX477 (6.29 x 4.71 mm): about 29 x 22 deg.
CM3 = (66.0, 41.0)
CM3_WIDE = (102.0, 67.0)
HQ_12MM = (29.0, 22.0)
AMCREST = (90.0, 50.0)


@dataclass
class CameraPlacement:
    key: str
    title: str
    detail: str
    kind: str  # "zero" | "hq" | "existing"
    origin: tuple
    target: tuple
    fov: tuple
    up_hint: tuple = (0, 0, 1)
    aspect: float = 16 / 9
    overshoot: float = 1.6  # how far past the target the frustum runs before clipping
    actors: list = field(default_factory=list)

    @property
    def direction(self):
        d = np.asarray(self.target, float) - np.asarray(self.origin, float)
        return d / np.linalg.norm(d)

    @property
    def reach(self):
        return float(np.linalg.norm(np.asarray(self.target, float) - np.asarray(self.origin, float)))

    @property
    def color(self):
        return KIND_COLOR[self.kind]


TIP = eq.exfoliator_tip()
WALL_Y = eq.GB_D - 25.0  # camera face, just off the back wall

# Numbered in the order a sample passes them, from the antechamber to the tray.
CAMERAS = [
    CameraPlacement(
        "unpack", "Bulk-crystal unpacking area",
        "Priority 1. Pi Zero 2 W + Camera Module 3, back wall, looking down",
        "zero", (eq.UNPACK_C[0], WALL_Y, 640.0), (eq.UNPACK_C[0], eq.UNPACK_C[1] - 60, 0.0), CM3),
    CameraPlacement(
        "mother_tape", "Mother-tape preparation area",
        "Priority 1. Pi Zero 2 W + Camera Module 3, back wall, looking down",
        "zero", (eq.MOTHER_TAPE_C[0], WALL_Y, 640.0), (eq.MOTHER_TAPE_C[0], eq.MOTHER_TAPE_C[1] - 40, 0.0), CM3),
    CameraPlacement(
        "tip", "Exfoliator tip + mother tape (close-up)",
        "Priority 1. Pi Zero 2 W + Camera Module 3 (autofocus), post on gantry deck",
        "zero", (TIP[0] - 150.0, TIP[1] - 120.0, TIP[2] + 25.0), tuple(TIP), CM3, overshoot=1.3),
    CameraPlacement(
        "pnp", "Overhead: pick-and-place",
        "Decided earlier. Pi 5 + HQ Camera, 8-50 mm zoom, ceiling, straight down",
        "hq", (eq.PNP_C[0], eq.PNP_C[1], eq.GB_H - 70.0), (eq.PNP_C[0], eq.PNP_C[1] + 1.0, 0.0), HQ_12MM,
        up_hint=(0, 1, 0), aspect=4 / 3, overshoot=1.0),
    CameraPlacement(
        "dome", "Existing Amcrest dome (overview)",
        "Already installed on the ceiling, back left",
        "existing", (520.0, eq.GB_D - 150.0, eq.GB_H - 60.0), (1000.0, 380.0, 0.0), AMCREST, overshoot=1.0),
]

# Sample route: antechamber door -> unpacking -> mother tape -> tip -> tray
SAMPLE_STOPS = [
    np.array([40.0, eq.GB_D * 0.52, 300.0]),
    eq.UNPACK_C + np.array([-40.0, -20.0, 40.0]),
    eq.MOTHER_TAPE_C + np.array([20.0, 0.0, 30.0]),
    TIP + np.array([0.0, 0.0, -12.0]),
    eq.PNP_C + np.array([0.0, 0.0, 34.0]),
]


def camera_plan():
    """Planned positions. Edit CAMERAS above; everything else follows."""
    return CAMERAS


# --- scene construction ------------------------------------------------------------

def place(parts, origin, direction, up_hint=(0, 0, 1)):
    r, u, f = look_frame(direction, up_hint)
    t = np.eye(4)
    t[:3, 0], t[:3, 1], t[:3, 2], t[:3, 3] = r, f, u, origin
    return [(m.transform(t, inplace=False), c) for m, c in parts]


def add_parts(plotter, parts, **kw):
    return [plotter.add_mesh(m, color=c, **kw) for m, c in parts]


def build_static_scene(plotter, cutaway=True):
    shell = eq.glovebox_shell()
    for name, (mesh, style) in shell.items():
        style = dict(style)
        if cutaway and name == "ceiling":
            style["opacity"] = 0.16
        if cutaway and name == "window_frame":
            style["opacity"] = 0.45
        plotter.add_mesh(mesh, **style)
    plotter.add_mesh(eq.stand(), color=eq.STAINLESS_DARK, specular=0.5)
    big, mini = eq.antechambers()
    plotter.add_mesh(big, color=eq.STAINLESS, specular=0.6)
    plotter.add_mesh(mini, color=eq.STAINLESS, specular=0.6)
    add_parts(plotter, eq.exfoliator())
    scara_parts, _ = eq.scara()
    add_parts(plotter, scara_parts)
    add_parts(plotter, eq.unpack_area())
    add_parts(plotter, eq.mother_tape_area())
    add_parts(plotter, eq.pnp_tray())
    add_parts(plotter, eq.ceiling_items())
    add_parts(plotter, camera_supports())


def camera_supports():
    """Posts and brackets the planned cameras hang from (shown even before they appear)."""
    out = []
    for c in camera_plan():
        o = np.asarray(c.origin, float)
        if c.key == "tip":
            out.append((pv.Cylinder(center=(o[0], o[1], (eq.EXF_DECK_Z + o[2]) / 2 - 10), direction=(0, 0, 1),
                                    radius=6.35, height=o[2] - eq.EXF_DECK_Z - 20), eq.STAINLESS))
        elif c.key in ("unpack", "mother_tape"):
            # laser-cut plate on one of the box's welded studs, held with a standard nut
            out.append((pv.Box(bounds=(o[0] - 25, o[0] + 25, o[1] + 8, eq.GB_D - 4, o[2] + 20, o[2] + 32)),
                        eq.BLACK))
            out.append((pv.Box(bounds=(o[0] - 30, o[0] + 30, eq.GB_D - 4, eq.GB_D, o[2] + 5, o[2] + 75)),
                        eq.BLACK))
            out.append((pv.Cylinder(center=(o[0], eq.GB_D - 12, o[2] + 52), direction=(0, 1, 0), radius=3.0,
                                    height=24), eq.STAINLESS_DARK))
            out.append((pv.Cylinder(center=(o[0], eq.GB_D - 8, o[2] + 52), direction=(0, 1, 0), radius=6.0,
                                    height=5, resolution=6), eq.STAINLESS_DARK))
        elif c.key == "pnp":
            out.append((pv.Box(bounds=(o[0] - 70, o[0] + 120, o[1] - 50, o[1] + 50, eq.GB_H - 12, eq.GB_H)),
                        eq.BLACK))
            for m, col in cm.pi5_box():
                m = m.rotate_x(180, inplace=False).translate((o[0] + 75, o[1], eq.GB_H - 22), inplace=False)
                out.append((m, col))
    return out


def camera_hardware(cam):
    if cam.kind == "hq":
        parts = cm.hq_camera()
    elif cam.kind == "zero":
        parts = cm.picam_zero()
    else:
        dome, _ = eq.amcrest_dome()
        return [(dome, eq.WHITE)]
    return place(parts, cam.origin, cam.direction, cam.up_hint)


def clipped_frustum(cam):
    """Field-of-view pyramid, run long and then cut at the glovebox walls and floor.

    The camera itself may sit just outside the interior (on the window or a
    wall), so the clip box is grown to include it.
    """
    length = cam.reach * cam.overshoot
    fr = frustum(cam.origin, cam.direction, cam.fov[0], cam.fov[1], length, cam.up_hint)
    ed = frustum_edges(cam.origin, cam.direction, cam.fov[0], cam.fov[1], length, cam.up_hint)
    o = np.asarray(cam.origin, float)
    lo = np.minimum([0.0, 0.0, 0.0], o - 5)
    hi = np.maximum([eq.GB_W, eq.GB_D, eq.GB_H], o + 5)
    bounds = (lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])
    fr = fr.clip_box(bounds, invert=False).extract_surface(algorithm="dataset_surface")
    ed = ed.clip_box(bounds, invert=False)
    return fr, ed


def add_camera(plotter, cam, number):
    """Adds the hardware, frustum and numbered tag; returns the actors."""
    hw = add_parts(plotter, camera_hardware(cam), specular=0.4)
    fr, ed = clipped_frustum(cam)
    fr_actor = plotter.add_mesh(fr, color=cam.color, opacity=0.12, lighting=False)
    ed_actor = plotter.add_mesh(ed, color=cam.color, line_width=2.5, lighting=False)
    tag = plotter.add_point_labels(
        [np.asarray(cam.origin) + np.array([0, 0, 55])], [str(number)], font_size=22, bold=True,
        text_color="white", shape_color=cam.color, shape="rounded_rect", shape_opacity=1.0,
        show_points=False, always_visible=True, margin=5)
    cam.actors = dict(hw=hw, frustum=fr_actor, edges=ed_actor, tag=tag)
    return cam.actors


def set_camera_state(cam, grow, fade, show_tag):
    """grow, fade in [0, 1]: hardware scale-in and frustum opacity."""
    o = np.asarray(cam.origin, float)
    for a in cam.actors["hw"]:
        a.SetOrigin(*o)
        s = max(grow, 1e-3)
        a.SetScale(s, s, s)
        a.SetVisibility(bool(grow > 0))
    for key, full in (("frustum", 0.12), ("edges", 1.0)):
        a = cam.actors[key]
        a.SetOrigin(*o)
        s = max(fade, 1e-3)
        a.SetScale(s, s, s)
        a.GetProperty().SetOpacity(full * min(1.0, fade * 1.2))
        a.SetVisibility(bool(fade > 0))
    cam.actors["tag"].SetVisibility(bool(show_tag))


def new_plotter(size):
    p = pv.Plotter(off_screen=True, window_size=size, lighting="none")
    p.set_background("#f8fafc", top="#d9e2ec")
    center = (eq.GB_W / 2, eq.GB_D / 2, 300)
    p.add_light(pv.Light(position=(950, -2600, 2600), focal_point=center, intensity=0.80))
    p.add_light(pv.Light(position=(-1800, 1800, 2200), focal_point=center, intensity=0.35))
    p.add_light(pv.Light(position=(3600, 1200, 1500), focal_point=center, intensity=0.30))
    p.add_light(pv.Light(light_type="headlight", intensity=0.25))
    p.enable_anti_aliasing("ssaa")
    return p


# --- camera path -------------------------------------------------------------------

CENTER = np.array([eq.GB_W / 2, eq.GB_D / 2, 260.0])


def orbit_pose(az_deg, el_deg, dist, center=CENTER):
    az, el = np.radians(az_deg), np.radians(el_deg)
    offset = dist * np.array([np.sin(az) * np.cos(el), -np.cos(az) * np.cos(el), np.sin(el)])
    return [tuple(center + offset), tuple(center), (0, 0, 1)]


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * t)


def lerp(a, b, t):
    return a + (b - a) * t


# --- point-of-view insets -------------------------------------------------------------

def render_pov(cam, size=(560, 315)):
    """What the camera would see, rendered from its pose with its field of view."""
    h = size[1]
    w = int(round(h * cam.aspect))
    p = new_plotter((w, h))
    build_static_scene(p, cutaway=False)
    for other in camera_plan():
        if other is cam or other.kind == "existing" and cam.kind == "existing":
            continue
        add_parts(p, camera_hardware(other))
    r, u, f = look_frame(cam.direction, cam.up_hint)
    p.camera_position = [tuple(cam.origin), tuple(np.asarray(cam.origin) + f * 500), tuple(u)]
    p.camera.view_angle = cam.fov[1]
    p.camera.clipping_range = (5, 6000)
    img = p.screenshot(return_img=True)
    p.close()
    return img


def font(size, bold=False):
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for n in names:
        for d in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF"):
            path = Path(d) / n
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


SIDEBAR_W = 560


def _rgb(hex_color):
    return tuple(int(hex_color[k:k + 2], 16) for k in (1, 3, 5))


def _wrap(d, text, fnt, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=fnt) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    return lines + [cur] if cur else lines


def composite(frame, overlays):
    """Sidebar with title, legend and the active camera's point of view."""
    img = Image.fromarray(frame).convert("RGB")
    W, H = img.size
    side = Image.new("RGBA", (SIDEBAR_W, H), (255, 255, 255, 232))
    img.paste(side, (0, 0), side)
    d = ImageDraw.Draw(img, "RGBA")
    d.line((SIDEBAR_W, 0, SIDEBAR_W, H), fill=(190, 200, 212, 255), width=2)
    ink, sub_ink = (28, 36, 48), (82, 92, 106)
    d.text((26, 20), overlays["title"], font=font(25, True), fill=ink + (255,))
    y = 56
    for line in _wrap(d, overlays["subtitle"], font(15), SIDEBAR_W - 50):
        d.text((27, y), line, font=font(15), fill=sub_ink + (255,))
        y += 20
    y += 12
    for i, (cam, alpha, active) in enumerate(overlays.get("legend", [])):
        a = int(255 * alpha)
        col = _rgb(cam.color)
        if alpha > 0:
            if active:
                d.rounded_rectangle((16, y - 5, SIDEBAR_W - 16, y + 49), 9, fill=col + (int(34 * alpha),),
                                    outline=col + (a,), width=2)
            d.rounded_rectangle((26, y + 3, 54, y + 31), 7, fill=col + (a,))
            num = str(i + 1)
            tw = d.textlength(num, font=font(17, True))
            d.text((40 - tw / 2, y + 6), num, font=font(17, True), fill=(255, 255, 255, a))
            d.text((66, y + 1), cam.title, font=font(17, True), fill=ink + (a,))
            d.text((66, y + 24), cam.detail, font=font(13), fill=sub_ink + (a,))
        y += 58
    pov = overlays.get("pov")
    if pov is not None and pov[2] > 0:
        pov_img, cam, alpha = pov
        inset = Image.fromarray(pov_img).convert("RGBA")
        max_w, max_h = SIDEBAR_W - 40, 280
        scale = min(max_w / inset.width, max_h / inset.height)
        inset = inset.resize((int(inset.width * scale), int(inset.height * scale)), Image.LANCZOS)
        x0 = (SIDEBAR_W - inset.width) // 2
        y0 = H - 58 - inset.height
        col = _rgb(cam.color)
        d.text((x0, y0 - 26), f"Simulated view from camera {overlays['pov_number']}", font=font(15, True),
               fill=ink + (int(255 * alpha),))
        inset.putalpha(int(255 * alpha))
        img.paste(inset, (x0, y0), inset)
        d.rectangle((x0 - 2, y0 - 2, x0 + inset.width + 1, y0 + inset.height + 1), outline=col + (int(255 * alpha),),
                    width=3)
    y = H - 44
    for line in _wrap(d, overlays["note"], font(12), SIDEBAR_W - 44)[:2]:
        d.text((24, y), line, font=font(12), fill=(110, 118, 130, 255))
        y += 16
    return np.asarray(img.convert("RGB"))


# --- timeline ------------------------------------------------------------------------

def build_timeline(n_cams, fps):
    """Segments: intro, one per camera, overview, top view. Returns list of (name, frames)."""
    seg = [("intro", int(3.0 * fps))]
    seg += [(f"cam{i}", int(4.0 * fps)) for i in range(n_cams)]
    seg += [("overview", int(5.0 * fps)), ("top", int(3.5 * fps))]
    return seg


def sample_position(stop_from, stop_to, t):
    """Hop between two stops on an arc, so the marker clears the equipment."""
    a, b = SAMPLE_STOPS[stop_from], SAMPLE_STOPS[stop_to]
    e = ease(t)
    pos = a + (b - a) * e
    pos[2] += 160.0 * np.sin(np.pi * e)
    return pos


def run(size, fps, out_dir, stills_only=False):
    cams = camera_plan()
    povs = [render_pov(c) for c in cams]
    p = new_plotter(size)
    build_static_scene(p)
    for i, c in enumerate(cams):
        add_camera(p, c, i + 1)
        set_camera_state(c, 0, 0, False)
    marker = p.add_mesh(pv.Sphere(radius=16, center=(0, 0, 0)), color="#c026d3", specular=0.9,
                        ambient=0.35)
    marker_tag = vtk.vtkBillboardTextActor3D()
    marker_tag.SetInput("sample")
    tp = marker_tag.GetTextProperty()
    tp.SetFontSize(17)
    tp.SetBold(True)
    tp.SetColor(0.53, 0.10, 0.56)
    tp.SetBackgroundColor(1, 1, 1)
    tp.SetBackgroundOpacity(0.85)
    tp.SetJustificationToCentered()
    p.renderer.AddActor(marker_tag)
    note = ("Layout schematic: glovebox and equipment estimated from the issue #23 photos; camera "
            "hardware and fields of view to scale. The magenta marker follows a sample from the antechamber.")
    title = "Aurora glovebox: planned camera locations"
    subtitle = ("From the 26 Oct 2026 walkthrough. Goal: record a sample's full provenance, from "
                "unpacking to the tray, synchronised with sensor data.")

    n_flow = len(SAMPLE_STOPS) - 1
    seg = build_timeline(len(cams), fps)
    # The view swings to a new azimuth at the start of each segment and then holds
    # still, which keeps the GIF small (only the changing regions are re-encoded).
    hold_az = [-30.0 + 56.0 * i / max(len(cams) - 1, 1) for i in range(len(cams))]
    frames_dir = Path(tempfile.mkdtemp(prefix="aurora_frames_"))
    k = 0
    stills = {}
    az_prev = -30.0
    for name, n in seg:
        for j in range(n):
            t = j / max(n - 1, 1)
            k += 1
            want_still = j == n - 1 and name != "intro"
            if stills_only and not want_still:
                continue
            el, dist = 27.0, 4300.0
            if name == "intro":
                az = lerp(-42.0, -30.0, ease(t))
            elif name.startswith("cam"):
                az = lerp(az_prev, hold_az[int(name[3:])], ease(t / 0.2))
            elif name == "overview":
                az = lerp(az_prev, 2.0, ease(t / 0.25))
            else:  # top
                az = lerp(az_prev, 0.0, ease(t / 0.7))
                el = lerp(27.0, 80.0, ease(t / 0.7))
                dist = lerp(4300.0, 4100.0, ease(t / 0.7))
            if j == n - 1:
                az_prev = az
            p.camera_position = orbit_pose(az, el, dist)
            p.camera.SetWindowCenter(-SIDEBAR_W / size[0], 0.0)

            ci = int(name[3:]) if name.startswith("cam") else None
            if name == "intro":
                spos = SAMPLE_STOPS[0]
            elif ci is not None and ci < n_flow:
                spos = sample_position(ci, ci + 1, t / 0.4)
            else:
                spos = SAMPLE_STOPS[-1]
            marker.SetPosition(*spos)
            marker_tag.SetPosition(*(spos + np.array([0, 0, 40.0])))

            legend, pov = [], None
            for i, c in enumerate(cams):
                if ci is not None:
                    if i < ci:
                        set_camera_state(c, 1, 1, True)
                        legend.append((c, 1.0, False))
                    elif i == ci:
                        t0 = 0.3 if ci < n_flow else 0.0  # wait for the sample to arrive
                        u = (t - t0) / (1 - t0)
                        set_camera_state(c, ease(u / 0.25), ease((u - 0.12) / 0.35), u > 0.08)
                        legend.append((c, ease(u / 0.2), True))
                        pov = (povs[i], c, ease((u - 0.3) / 0.25))
                    else:
                        set_camera_state(c, 0, 0, False)
                        legend.append((c, 0.0, False))
                elif name in ("overview", "top"):
                    set_camera_state(c, 1, 1, True)
                    legend.append((c, 1.0, False))
                else:
                    set_camera_state(c, 0, 0, False)
                    legend.append((c, 0.0, False))
            p.render()
            frame = p.screenshot(return_img=True)
            ov = dict(title=title, subtitle=subtitle, legend=legend, note=note)
            if pov is not None:
                ov["pov"] = pov
                ov["pov_number"] = ci + 1
            frame = composite(frame, ov)
            if want_still:
                stills[name] = frame
            if not stills_only:
                imageio.imwrite(frames_dir / f"f{k - 1:05d}.png", frame)
    p.close()
    for key, img in stills.items():
        imageio.imwrite(out_dir / f"still_{key}.png", img)
    if stills_only:
        shutil.rmtree(frames_dir)
        return
    ff = shutil.which("ffmpeg") or "ffmpeg"
    mp4 = out_dir / "aurora_camera_layout.mp4"
    subprocess.run([ff, "-y", "-v", "error", "-framerate", str(fps), "-i", str(frames_dir / "f%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "21", "-movflags", "+faststart",
                    str(mp4)], check=True)
    palette = frames_dir / "palette.png"
    vf = f"fps={fps // 3},scale=1120:-1:flags=lanczos"
    subprocess.run([ff, "-y", "-v", "error", "-i", str(mp4), "-vf",
                    f"{vf},palettegen=max_colors=128:stats_mode=diff", str(palette)], check=True)
    subprocess.run([ff, "-y", "-v", "error", "-i", str(mp4), "-i", str(palette), "-lavfi",
                    f"{vf}[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle",
                    str(out_dir / "aurora_camera_layout.gif")], check=True)
    if shutil.which("gifsicle"):
        gif = str(out_dir / "aurora_camera_layout.gif")
        subprocess.run(["gifsicle", "-O3", "--lossy=40", gif, "-o", gif], check=True)
    shutil.rmtree(frames_dir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills-only", action="store_true")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    run((args.width, args.height), args.fps, HERE, stills_only=args.stills_only)


if __name__ == "__main__":
    main()
