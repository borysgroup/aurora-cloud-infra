"""Simplified camera hardware, modelled in a local frame: +Y is the optical axis,
+Z is "up" in the image, +X is image right. Units are millimetres.
"""

from scene_primitives import box, cyl

PCB_GREEN = "#1f7a3c"
CASE_RED = "#c8102e"
CASE_WHITE = "#f4f4f4"
LENS_BLACK = "#141516"
HQ_BLACK = "#1c1d1f"
ZOOM_SILVER = "#8d939a"


def picam_zero():
    """Pi Zero 2 W + Camera Module 3 in the official Zero case with the camera lid.

    Case is 69 x 34 x 14 mm (approx.); the lens looks out through the lid.
    """
    case = box((0, -7, 0), (69, 8, 34))
    lid = box((0, -1.5, 0), (69, 3, 34))
    lens = cyl((0, 1.5, 0), (0, 1, 0), 4.5, 6)
    glass = cyl((0, 4.6, 0), (0, 1, 0), 3.2, 0.6)
    return [(case, CASE_RED), (lid, CASE_WHITE), (lens, LENS_BLACK), (glass, "#3d6fa5")]


def hq_camera(zoom_len=68.3):
    """Raspberry Pi HQ Camera (38 x 38 mm board) with the 8-50 mm C-mount zoom lens."""
    board = box((0, -2, 0), (38, 4, 38))
    mount = cyl((0, 9, 0), (0, 1, 0), 18, 18)
    lens = cyl((0, 18 + zoom_len / 2, 0), (0, 1, 0), 20, zoom_len)
    rings = [cyl((0, 18 + zoom_len * f, 0), (0, 1, 0), 21.5, 6) for f in (0.3, 0.62, 0.9)]
    out = [(board, PCB_GREEN), (mount, HQ_BLACK), (lens, ZOOM_SILVER)]
    out += [(r, HQ_BLACK) for r in rings]
    return out


def pi5_box():
    """Raspberry Pi 5 with Active Cooler on its tray (85 x 56 mm board)."""
    tray = box((0, 0, -5), (97, 68, 4))
    board = box((0, 0, 3), (85, 56, 1.6))
    cooler = box((-5, 0, 10), (40, 40, 10))
    return [(tray, "#3b3f45"), (board, PCB_GREEN), (cooler, "#a7acb2")]
