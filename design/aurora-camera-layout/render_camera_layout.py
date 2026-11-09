"""Animated 3D render of the Aurora glovebox and the planned camera positions.

    xvfb-run -a python design/aurora-camera-layout/render_camera_layout.py [--stills-only | --report]

The glovebox, the equipment and the Epson come from the chamber model in
../aurora-chamber (aurora_chamber); this file only adds the cameras, their mounts
and the proposed work areas (work_areas.py). --report prints each camera's aim,
view, target coverage and 3D gap to the robot's swept volume over the riser range.

Writes PNG stills, an MP4 and a GIF next to this file. Needs pyvista, imageio,
imageio-ffmpeg, pillow and cadquery (gifsicle optional, shrinks the GIF); on a headless
machine run it under xvfb-run. The ceiling cameras hang from the yoke mounts in
../stud-camera-mount (byu-vcl PR 318's head, STUD_MOUNT = "yoke"), or from the
stud pods in ../aurora-stud-mount (STUD_MOUNT = "pod"), posed with the pod's tilt stops.
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
sys.path.insert(0, str(HERE.parent / "aurora-chamber"))
sys.path.insert(0, str(HERE.parent / "aurora-stud-mount"))
sys.path.insert(0, str(HERE.parent / "stud-camera-mount"))

import aurora_chamber as ch  # noqa: E402
import camera_models as cm  # noqa: E402
import work_areas as wa  # noqa: E402
import render_mount as rm  # noqa: E402
import stud_pan_tilt_mount as sm  # noqa: E402
import render_stud_mount as ym  # noqa: E402  (yoke mount: meshes and pose matrices)
import stud_mount as yoke_mount  # noqa: E402
from aurora_chamber.primitives import frustum, frustum_edges, look_frame  # noqa: E402

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

# The chamber at the design riser (RISER_H, 180 mm until someone measures it) and the studs this plan uses:
# S1-S4 from the chamber model, plus S5, a stud the plan needs.
ENV = ch.envelope()
J1 = ch.base_xyz()
STUDS = {k: dict(v) for k, v in ch.CEILING_STUDS.items()}


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
    stud: str = ""          # ceiling stud carrying a stud pod, if any
    pan: float = 0.0
    tilt: float = 0.0
    yoke: bool = False      # on the yoke mount (../stud-camera-mount) rather than a stud pod
    hardware: bool = True   # False when another camera's head already carries this one
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


TIP = ch.exfoliator_tip()


def stud_pod_pose(stud, target, iters=4):
    """Pan (free) and tilt (nearest index stop) that aim a stud pod's lens at `target`.

    Returns pan, tilt, lens position and viewing direction in scene coordinates."""
    sx, sy = STUDS[stud]["xy"]
    origin = np.array([sx, sy, ch.GB_H])
    lens_c, lens_d = sm.lens_axis()
    target = np.asarray(target, float)
    pos = origin.copy()
    pan = tilt = 0.0
    for _ in range(iters):
        d = target - pos
        pan = float(np.degrees(np.arctan2(d[1], d[0])))
        want = float(np.degrees(np.arctan2(np.hypot(d[0], d[1]), -d[2])))
        tilt = float(min(sm.TILTS, key=lambda a: abs(a - want)))
        if tilt == 0:  # looking straight down: pan only turns the image; put image-up towards the far side
            pan = 90.0
        pts = rm.place_cradle(pv.PolyData(np.array([lens_c, lens_c + lens_d])), tilt, pan, origin).points
        pos = pts[0]
    return pan, tilt, pts[0], (pts[1] - pts[0]) / np.linalg.norm(pts[1] - pts[0])


def stud_camera(key, title, detail, stud, target):
    """Pi Zero 2 W + Camera Module 3 on a stud pod, aimed at the nearest tilt stop."""
    pan, tilt, pos, d = stud_pod_pose(stud, target)
    floor_hit = pos + d * (pos[2] / max(-d[2], 1e-3))
    a = np.radians(pan)
    up = np.array([np.cos(np.radians(tilt)) * np.cos(a), np.cos(np.radians(tilt)) * np.sin(a), np.sin(np.radians(tilt))])
    return CameraPlacement(key, title, f"{detail}, stud {stud}, tilt stop {tilt:.0f} deg",
                           "zero", tuple(pos), tuple(floor_hit), CM3, up_hint=tuple(up), overshoot=1.0,
                           stud=stud, pan=pan, tilt=tilt)


# Which stud mount the ceiling cameras use: "yoke" (../stud-camera-mount, byu-vcl PR 318's
# head on a yoke that pans on the stud, tilt anywhere) or "pod" (../aurora-stud-mount).
STUD_MOUNT = "yoke"


def stud_root(stud):
    x, y = STUDS[stud]["xy"]
    return np.array([x, y, ch.GB_H])


def yoke_aim(kind, stud, target, iters=10):
    """Pan and tilt that put a yoke mount's optical axis through `target`.

    Returns (lens centre, pan, tilt, image-up vector), scene frame. The lens sits off
    the pan and tilt axes, so this iterates from a first guess.
    """
    root = stud_root(stud)
    lens = np.r_[yoke_mount.lens_point(kind), 1.0]
    pan, tilt = 0.0, 45.0
    for _ in range(iters):
        o = (ym.mount_matrices(kind, pan, tilt, root)["head"] @ lens)[:3]
        d = np.asarray(target, float) - o
        d /= np.linalg.norm(d)
        tilt = float(np.degrees(np.arcsin(-d[2])))
        pan = float(np.degrees(np.arctan2(d[0], -d[1])))
    m = ym.mount_matrices(kind, pan, tilt, root)["head"]
    return (m @ lens)[:3], pan, tilt, m[:3, :3] @ np.array([0.0, 0.0, 1.0])


def yoke_camera(key, title, detail, kind, stud, target, fov, **kw):
    o, pan, tilt, up = yoke_aim(kind, stud, target)
    return CameraPlacement(key, title, f"{detail}, stud {stud}, tilt {tilt:.0f} deg", kind, tuple(o),
                           tuple(target), fov, up_hint=tuple(up), stud=stud, pan=pan, tilt=tilt, yoke=True, **kw)


def wide_on_hq_head(cam, title, detail):
    """The Camera Module 3 Wide on the same head as `cam` (byu-vcl's nose), on the Pi 5's second port."""
    m = ym.mount_matrices("hq", cam.pan, cam.tilt, stud_root(cam.stud))["head"]
    h = yoke_mount.HQ
    lens_y = h["nose_y"] + 5.0 + 2.5 - yoke_mount.CM3["lens_h"] - h["axis_y"]   # the Wide's lens front
    o = (m @ np.array([h["wide_x"], lens_y, h["wide_z"], 1.0]))[:3]
    aim = np.asarray(cam.direction)
    return CameraPlacement("pnp_wide", title, detail, "hq", tuple(o), tuple(o + aim * (o[2] - ch.TRAY_C[2])
                                                                          / max(-aim[2], 1e-3)), CM3_WIDE,
                           up_hint=cam.up_hint, aspect=3 / 2, overshoot=1.0, stud=cam.stud, pan=cam.pan,
                           tilt=cam.tilt, yoke=True, hardware=False)


# A new stud over the mother-tape area: S3, the only free stud near it, is inside the reach of the
# Epson's shaft, which rises to within 10 mm (riser 180) to 40 mm (riser 150) of the ceiling.
STUDS["S5"] = dict(xy=tuple(wa.MOTHER_TAPE_C[:2]), state="needed", note="needed: a new stud over the mother-tape area")

# overhead camera of the pod variant: flat on the ceiling, straight above the tray
PNP_CAM_Z = ch.GB_H - 60.0
PNP_LENS_FRONT = PNP_CAM_Z - 18.0 - 68.3  # HQ Camera mount + 8-50 mm zoom (camera_models.hq_camera)

if STUD_MOUNT == "yoke":
    # The tray is at the edge of the Epson's reach, where its shaft rises to 10-40 mm under the ceiling,
    # so the HQ camera hangs from S2, outside the reach, and looks at the tray at an angle.
    _PNP = yoke_camera(
        "pnp", "Pick-and-place: tray on the substrate plate",
        "Pi 5 + HQ Camera, 8-50 mm zoom, yoke mount", "hq", "S2", tuple(ch.TRAY_C + np.array([0.0, 0.0, 15.0])),
        HQ_12MM, aspect=4 / 3, overshoot=1.0)
    _STUD_CAMS = [
        yoke_camera("unpack", "Bulk-crystal unpacking area", "Priority 1. Pi Zero 2 W + CM3 on a yoke mount",
                    "zero", "S1", (wa.UNPACK_C[0], wa.UNPACK_C[1], 0.0), CM3),
        yoke_camera("mother_tape", "Mother-tape preparation area", "Priority 1. Pi Zero 2 W + CM3 on a yoke mount",
                    "zero", "S5", (wa.MOTHER_TAPE_C[0], wa.MOTHER_TAPE_C[1], 0.0), CM3)]
    _OVERHEAD = [_PNP, wide_on_hq_head(_PNP, "Overhead wide: the Epson's work area",
                                       "Optional. CM3 Wide on the same head, the Pi 5's second port (#16)")]
else:
    _STUD_CAMS = [
        stud_camera("unpack", "Bulk-crystal unpacking area", "Priority 1. Pi Zero 2 W + CM3 on a stud pod",
                    "S1", (wa.UNPACK_C[0], wa.UNPACK_C[1], 0.0)),
        stud_camera("mother_tape", "Mother-tape preparation area", "Priority 1. Pi Zero 2 W + CM3 on a stud pod",
                    "S5", (wa.MOTHER_TAPE_C[0], wa.MOTHER_TAPE_C[1], 0.0))]
    _OVERHEAD = [CameraPlacement(
        "pnp", "Overhead: pick-and-place",
        f"Pi 5 + HQ Camera, straight above the tray, lens {PNP_LENS_FRONT - ENV['arm2_top']:.0f} mm above the SCARA",
        "hq", (ch.TRAY_C[0], ch.TRAY_C[1], PNP_CAM_Z), (ch.TRAY_C[0], ch.TRAY_C[1] + 1.0, ch.TRAY_C[2]), HQ_12MM,
        up_hint=(0, 1, 0), aspect=4 / 3, overshoot=1.0)]

# Numbered in the order a sample passes them, from the antechamber to the tray.
# Both long sides of the box are windows, so the cameras hang from welded ceiling
# studs, apart from the close-up on the roller.
CAMERAS = _STUD_CAMS + [
    CameraPlacement(
        "tip", "Exfoliator tip + mother tape (close-up)",
        "Priority 1. Pi Zero 2 W + CM3 (autofocus), on a post beside the roller",
        "zero", (TIP[0] + 130.0, TIP[1] - 110.0, TIP[2] + 25.0), tuple(TIP), CM3, overshoot=1.3),
] + _OVERHEAD + [
    CameraPlacement(
        "dome", "Existing Amcrest dome (overview)",
        "Already on the ceiling, front left, behind the top flange",
        "existing", tuple(ch.DOME_C - np.array([0.0, 0.0, 60.0])), (0.6 * ch.GB_W, 0.55 * ch.GB_D, 0.0), AMCREST,
        overshoot=1.0),
]

# Sample route: antechamber door -> unpacking -> mother tape -> tip -> tray
SAMPLE_STOPS = [
    np.array([40.0, ch.ANTE_DOOR_C[1], ch.ANTE_DOOR_C[2]]),
    wa.UNPACK_C + np.array([-40.0, -20.0, 40.0]),
    wa.MOTHER_TAPE_C + np.array([20.0, 0.0, 30.0]),
    TIP + np.array([0.0, 0.0, -12.0]),
    ch.TRAY_C + np.array([0.0, 0.0, 34.0]),
]

# The Epson's parked pose in the walkthrough (arm folded back over its base)
SCARA_PARK = tuple(ch.robot.PARK_J3)


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
    shell = ch.glovebox_shell()
    for name, (mesh, style) in shell.items():
        style = dict(style)
        if cutaway and name == "ceiling":
            style["opacity"] = 0.16
        if cutaway and name == "window_frame":
            style["opacity"] = 0.45
        plotter.add_mesh(mesh, **style)
    plotter.add_mesh(ch.stand(), color=ch.STAINLESS_DARK, specular=0.5)
    big, mini = ch.antechambers()
    plotter.add_mesh(big, color=ch.STAINLESS, specular=0.6)
    plotter.add_mesh(mini, color=ch.STAINLESS, specular=0.6)
    add_parts(plotter, ch.wall_signs())
    add_parts(plotter, ch.exfoliator())
    add_parts(plotter, ch.raised_shelf())
    scara_parts, _ = ch.scara(target=SCARA_PARK)
    add_parts(plotter, scara_parts)
    if cutaway:
        plotter.add_mesh(ch.scara_envelope(), color="#7c3aed", opacity=0.07, lighting=False)
    add_parts(plotter, ch.ceiling_studs(studs=STUDS, used=[c.stud for c in camera_plan() if c.stud]))
    add_parts(plotter, wa.unpack_area())
    add_parts(plotter, wa.mother_tape_area())
    add_parts(plotter, ch.pnp_tray())
    add_parts(plotter, ch.ceiling_items(), opacity=0.35 if cutaway else 1.0)
    add_parts(plotter, camera_supports())


def camera_supports():
    """Posts and brackets the planned cameras hang from (shown even before they appear)."""
    out = []
    for c in camera_plan():
        o = np.asarray(c.origin, float)
        if c.yoke:
            if c.hardware:
                mats = ym.mount_matrices(c.kind, c.pan, c.tilt, stud_root(c.stud))
                out += [(m.transform(mats["pan"], inplace=False), ym.COLOURS[mat])
                        for m, mat in ym.mount_meshes(c.kind)["pan"]]
        elif c.stud:
            sx, sy = STUDS[c.stud]["xy"]
            out += [(m, col) for m, col in rm.static_parts((sx, sy, ch.GB_H), c.pan, ceiling=False)]
        elif c.key == "tip":
            out.append((pv.Cylinder(center=(o[0], o[1], (ch.EXF_DECK_Z + o[2]) / 2 - 10), direction=(0, 0, 1),
                                    radius=6.35, height=o[2] - ch.EXF_DECK_Z - 20), ch.STAINLESS))
            out.append((pv.Box(bounds=(o[0] - 25, o[0] + 25, o[1] - 25, o[1] + 25, ch.EXF_DECK_Z - 8, ch.EXF_DECK_Z)),
                        ch.BLACK))
        elif c.key == "pnp":
            # plate flat on the ceiling, drop to the camera, Pi 5 beside it
            out.append((pv.Box(bounds=(o[0] - 70, o[0] + 120, o[1] - 50, o[1] + 50, ch.GB_H - 12, ch.GB_H)),
                        ch.BLACK))
            out.append((pv.Box(bounds=(o[0] - 26, o[0] - 20, o[1] - 20, o[1] + 20, o[2] + 30, ch.GB_H - 12)),
                        ch.BLACK))
            for m, col in cm.pi5_box():
                m = m.rotate_x(180, inplace=False).translate((o[0] + 75, o[1], ch.GB_H - 22), inplace=False)
                out.append((m, col))
    return out


def camera_hardware(cam):
    if cam.yoke:
        if not cam.hardware:
            return []
        mats = ym.mount_matrices(cam.kind, cam.pan, cam.tilt, stud_root(cam.stud))
        return [(m.transform(mats["head"], inplace=False), ym.COLOURS[mat]) for m, mat in ym.mount_meshes(cam.kind)["head"]]
    if cam.stud:
        sx, sy = STUDS[cam.stud]["xy"]
        return rm.moving_parts(cam.tilt, cam.pan, (sx, sy, ch.GB_H))
    if cam.kind == "hq":
        parts = cm.hq_camera()
    elif cam.kind == "zero":
        parts = cm.picam_zero()
    else:
        dome, _ = ch.amcrest_dome()
        return [(dome, ch.WHITE)]
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
    hi = np.maximum([ch.GB_W, ch.GB_D, ch.GB_H], o + 5)
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
    center = (ch.GB_W / 2, ch.GB_D / 2, 300)
    p.add_light(pv.Light(position=(950, -2600, 2600), focal_point=center, intensity=0.80))
    p.add_light(pv.Light(position=(-1800, 1800, 2200), focal_point=center, intensity=0.35))
    p.add_light(pv.Light(position=(3600, 1200, 1500), focal_point=center, intensity=0.30))
    p.add_light(pv.Light(light_type="headlight", intensity=0.25))
    p.enable_anti_aliasing("ssaa")
    return p


# --- camera path -------------------------------------------------------------------

CENTER = np.array([ch.GB_W / 2, ch.GB_D / 2, 230.0])
VIEW_DIST = 3800.0


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
    note = ("Box, equipment and studs measured on the walkthrough's 3D reconstruction (+/-5 %). Robot, cameras "
            "and mounts to scale. Purple: the Epson's swept volume.")
    title = "Aurora glovebox: planned camera locations"
    subtitle = (f"Measured interior {ch.GB_W / 1000:.2f} x {ch.GB_D / 1000:.2f} x {ch.GB_H / 1000:.2f} m. The cameras "
                f"hang from welded ceiling studs on pan/tilt mounts; the tray camera stays outside the Epson's reach, "
                f"whose shaft rises to {ch.GB_H - ENV['shaft_top']:.0f} mm under the ceiling on a "
                f"{ch.RISER_H:.0f} mm riser.")

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
            el, dist = 27.0, VIEW_DIST
            if name == "intro":
                az = lerp(-42.0, -30.0, ease(t))
            elif name.startswith("cam"):
                az = lerp(az_prev, hold_az[int(name[3:])], ease(t / 0.2))
            elif name == "overview":
                az = lerp(az_prev, 2.0, ease(t / 0.25))
            else:  # top
                az = lerp(az_prev, 0.0, ease(t / 0.7))
                el = lerp(27.0, 80.0, ease(t / 0.7))
                dist = lerp(VIEW_DIST, VIEW_DIST * 0.95, ease(t / 0.7))
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
    ff = shutil.which("ffmpeg")
    if ff is None:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
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


def ceiling_still(out_dir, size=(1600, 900)):
    """The ceiling seen from below (parallel projection, front window at the top, as in the 6 Nov photo of the
    studs): the studs, the mounts on them, the Epson and the reach of its swept volume."""
    p = new_plotter(size)
    cx, cy = ch.GB_W / 2, ch.GB_D / 2
    p.add_light(pv.Light(position=(cx, cy, -1500), focal_point=(cx, cy, ch.GB_H), intensity=0.75))
    ceiling = pv.Box(bounds=(0, ch.GB_W, ch.front_window_y(ch.GB_H), ch.back_window_y(ch.GB_H), ch.GB_H, ch.GB_H + 12))
    p.add_mesh(ceiling, color=ch.STAINLESS, specular=0.4)
    add_parts(p, ch.ceiling_items())
    add_parts(p, ch.ceiling_studs(studs=STUDS, used=[c.stud for c in camera_plan() if c.stud]))
    scara_parts, _ = ch.scara(target=SCARA_PARK)
    add_parts(p, scara_parts, opacity=0.35)
    for c in camera_plan():
        if c.stud and c.hardware:
            for mesh, col in camera_supports_for(c) + camera_hardware(c):
                col = "#8a94a3" if col in (ym.COLOURS["petg"], ch.BLACK) else col   # lighter, to read from below
                p.add_mesh(mesh, color=col, specular=0.3, ambient=0.35)
    dome, _ = ch.amcrest_dome()
    p.add_mesh(dome, color=ch.WHITE)
    for name, s in STUDS.items():
        x, y = s["xy"]
        users = [c for c in camera_plan() if c.stud == name and c.hardware]
        cams = ", ".join(f"camera {camera_plan().index(c) + 1}" for c in users)
        text = f"{name}: {cams}" if users else f"{name}: {s['note']}"
        if s["state"] == "needed" and users:
            text += " (no stud here yet)"
        if s["state"] == "reach":
            text = f"{name}: in the shaft's reach"
        p.add_point_labels([(x, y - 80.0, ch.GB_H - 200.0)], [text], font_size=18, bold=True, text_color="white",
                           shape_color={"needed": "#b91c1c", "reach": "#6d28d9"}.get(s["state"], "#334155"),
                           shape="rounded_rect",
                           shape_opacity=0.92, show_points=False, always_visible=True, margin=5)
    for r_, z_ in ((ENV["arm2_r"], ENV["arm2_top"]), (ENV["shaft_r"], ENV["shaft_top"]), (ENV["arch_r"], ENV["arch_top"])):
        ring = pv.Circle(radius=r_, resolution=160).translate((J1[0], J1[1], z_),
                                                               inplace=False)
        ring = ring.clip_box((0, ch.GB_W, 0, ch.GB_D, 0, ch.GB_H), invert=False).extract_feature_edges(
            boundary_edges=True, feature_edges=False, manifold_edges=False, non_manifold_edges=False)
        p.add_mesh(ring.tube(radius=4.0), color="#7c3aed")
    p.add_point_labels([(J1[0] - 120.0, J1[1] - 420.0, ENV["arm2_top"] - 50.0)],
                       [f"Epson reach: arm 2 (top {ENV['arm2_top']:.0f}), shaft (top {ENV['shaft_top']:.0f}), duct arch"],
                       font_size=15,
                       text_color="#6d28d9", shape_color="white", shape_opacity=0.9, show_points=False,
                       always_visible=True, margin=4)
    p.add_text("Ceiling from below, open side at the top. S1-S4 located on the 3D reconstruction (+/-50 mm); "
               "S5 is not a circled stud.", position=(20, 18), font_size=12, color="#334155")
    p.enable_parallel_projection()
    p.camera_position = [(cx, cy, -2500.0), (cx, cy, ch.GB_H), (0.0, -1.0, 0.0)]
    p.camera.parallel_scale = 640.0
    p.camera.clipping_range = (10, 8000)
    p.screenshot(str(out_dir / "still_ceiling_studs.png"))
    p.close()


def camera_supports_for(c):
    """The stud-mounted parts of one camera's mount (yoke and knobs), scene frame."""
    if c.yoke:
        mats = ym.mount_matrices(c.kind, c.pan, c.tilt, stud_root(c.stud))
        return [(m.transform(mats["pan"], inplace=False), ym.COLOURS[mat]) for m, mat in ym.mount_meshes(c.kind)["pan"]]
    sx, sy = STUDS[c.stud]["xy"]
    return list(rm.static_parts((sx, sy, ch.GB_H), c.pan, ceiling=False))


REPORT_TARGETS = {
    # points each camera is meant to see, for the coverage columns of the report
    "unpack": lambda: ch.grid_on_rect(wa.UNPACK_C + (0, 0, 3.0), (260, 220)),
    "mother_tape": lambda: ch.grid_on_rect(wa.MOTHER_TAPE_C + (0, 0, 3.0), (240, 180)),
    "tip": lambda: ch.grid_on_rect(TIP + (0, 0, -1.5), (60, 40), (7, 5)),   # carrier top round the roller
    "pnp": lambda: ch.grid_on_rect(ch.TRAY_C + (0, 0, ch.TRAY_SIZE[2]), ch.TRAY_SIZE[:2]),
    "pnp_wide": lambda: ch.grid_on_rect(ch.TRAY_C + (0, 0, ch.TRAY_SIZE[2]), ch.TRAY_SIZE[:2]),
}


def clearance_report():
    """Per camera: aim, distance, view size at the target, the share of its target in view and in line of
    sight (robot parked), and the 3D gap between its mount and head and the Epson's swept volume, taken over
    the whole riser range (aurora_chamber.robot_clearance)."""
    print(f"ceiling {ch.GB_H:.0f} mm; Epson J1 at ({J1[0]:.0f}, {J1[1]:.0f}); riser {ch.RISER_RANGE[0]:.0f} to "
          f"{ch.RISER_RANGE[1]:.0f} mm, scene drawn at {ch.RISER_H:.0f}")
    for r in ch.RISER_RANGE:
        e = ch.envelope(r)
        print(f"  riser {r:.0f}: arm 2 top {e['arm2_top']:.0f} (r <= {e['arm2_r']:.0f}); shaft top {e['shaft_top']:.1f} "
              f"(r <= {e['shaft_r']:.0f}), {ch.GB_H - e['shaft_top']:.1f} mm under the ceiling; duct arch "
              f"{e['arch_top']:.0f} (r <= {e['arch_r']:.0f})")
    tray = ch.TRAY_C
    print(f"tray (plate top) at ({tray[0]:.0f}, {tray[1]:.0f}, {tray[2]:.0f}), {np.hypot(*(tray[:2] - J1[:2])):.0f} "
          f"from J1. Straight above it the robot reaches "
          + ", ".join(f"{ch.robot_top_at(tray[:2], r):.1f} (riser {r:.0f})" for r in ch.RISER_RANGE))
    flat = np.array([[tray[0], tray[1], ch.GB_H - 25.0]])
    print("  a flat Camera Module 3 (25 mm deep) on the ceiling straight above it: gap "
          + ", ".join(f"{ch.robot_clearance(flat, risers=r)['gap']:.1f} mm (riser {r:.0f})" for r in ch.RISER_RANGE))
    for name, st in STUDS.items():
        x, y = st["xy"]
        print(f"  {name}: ({x:.0f}, {y:.0f}) {st['state']:6s} {np.hypot(x - J1[0], y - J1[1]):5.0f} "
              f"from J1, robot top there {ch.robot_top_at((x, y)):.0f}")
    occluders = ch.static_parts(with_dome=False)
    rows = []
    for i, c in enumerate(camera_plan()):
        view = ch.camera_view(c.origin, c.target, c.fov, c.up_hint)
        w, h = view.footprint(c.reach)
        parts = camera_hardware(c) + (camera_supports_for(c) if c.stud and c.hardware else [])
        gap = ch.robot_clearance(parts)["gap"] if parts else None
        low = min(float(np.asarray(m.points)[:, 2].min()) for m, _ in parts) if parts else float("nan")
        cover = (ch.view_coverage(view, REPORT_TARGETS[c.key](), occluders) if c.key in REPORT_TARGETS
                 else dict(in_view=None, visible=None))
        rows.append(dict(n=i + 1, key=c.key, stud=c.stud or "-", tilt=view.tilt, dist=c.reach, view=(w, h),
                         lowest=low, gap=gap, in_view=cover["in_view"], visible=cover["visible"]))
    print(" #  key          stud  tilt  dist   view at target   lowest  gap to robot  target in view / visible")
    for r in rows:
        g = "-" if r["gap"] is None else f"{r['gap']:.0f}"
        cov = "-" if r["in_view"] is None else f"{100 * r['in_view']:.0f} % / {100 * r['visible']:.0f} %"
        print(f"{r['n']:2d}  {r['key']:12s} {r['stud']:4s} {r['tilt']:5.0f} {r['dist']:5.0f}   {r['view'][0]:4.0f} x "
              f"{r['view'][1]:4.0f} mm   {r['lowest']:5.0f}   {g:>6s}        {cov}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="print the clearance report and stop")
    ap.add_argument("--stills-only", action="store_true")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    clearance_report()
    if args.report:
        return
    ceiling_still(HERE)
    run((args.width, args.height), args.fps, HERE, stills_only=args.stills_only)


if __name__ == "__main__":
    main()
