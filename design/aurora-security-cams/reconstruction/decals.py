"""Decal textures for printed marks: logos and labels typeset from fonts, and labels too small or too
specific to typeset (QR sign, sticker, handwriting, safety labels) rectified out of the published
stills through the calibrated camera and lens model.

Typeset marks use Liberation Sans (metric-compatible with Arial), the closest freely licensed face to
the printed wordmarks; they are not the vendors' logo artwork.
"""
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
STILLS = {"cam0": os.path.join(HERE, "..", "captures", "2026-11-19_1822Z_cam0_192.168.3.150.jpg"),
          "cam1": os.path.join(HERE, "..", "captures", "2026-11-19_1822Z_cam1_192.168.3.151.jpg")}
FONTS = ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
FONTS_REG = ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def _font(paths, size):
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def typeset(text, w_mm, h_mm, fg, bg=None, px_per_mm=16, pad=0.06, bold=True, spacing=0.0):
    """Text centred on a w x h mm tile; bg None gives a transparent (RGBA cut-out) tile."""
    W, H = max(8, int(w_mm * px_per_mm)), max(8, int(h_mm * px_per_mm))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0) if bg is None else tuple(bg) + (255,))
    d = ImageDraw.Draw(img)
    paths = FONTS if bold else FONTS_REG
    size = H
    while size > 4:
        f = _font(paths, size)
        widths = [d.textlength(ch, font=f) for ch in text]
        tw = sum(widths) + spacing * size * (len(text) - 1)
        x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
        if tw <= W * (1 - 2 * pad) and (y1 - y0) <= H * (1 - 2 * pad):
            break
        size -= 1
    f = _font(paths, size)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
    widths = [d.textlength(ch, font=f) for ch in text]
    tw = sum(widths) + spacing * size * (len(text) - 1)
    x = (W - tw) / 2
    y = (H - (y1 - y0)) / 2 - y0
    for ch, wch in zip(text, widths):
        d.text((x, y), ch, font=f, fill=tuple(fg) + (255,))
        x += wch + spacing * size
    return img


def label(lines, w_mm, h_mm, bg=(236, 236, 230), fg=(30, 30, 30), px_per_mm=16, border=None):
    """A printed paper label with a few lines of small text."""
    W, H = int(w_mm * px_per_mm), int(h_mm * px_per_mm)
    img = Image.new("RGBA", (W, H), tuple(bg) + (255,))
    d = ImageDraw.Draw(img)
    if border:
        d.rectangle([1, 1, W - 2, H - 2], outline=tuple(border) + (255,), width=max(2, W // 60))
    n = len(lines)
    y = H * 0.12
    for i, (txt, rel, bold) in enumerate(lines):
        f = _font(FONTS if bold else FONTS_REG, max(6, int(H * rel)))
        tw = d.textlength(txt, font=f)
        d.text(((W - tw) / 2, y), txt, font=f, fill=tuple(fg) + (255,))
        y += H * rel * 1.25
    return img


def round_label(d_mm, ring=(40, 90, 190), px_per_mm=16, text=None):
    """Round motor label: white disc, coloured ring, a few lines of grey print (unreadable in the frames)."""
    W = int(d_mm * px_per_mm)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, W - 1, W - 1], fill=(238, 240, 240, 255))
    d.ellipse([W * 0.04, W * 0.04, W * 0.96, W * 0.96], outline=tuple(ring) + (255,), width=max(2, W // 14))
    d.rectangle([W * 0.18, W * 0.42, W * 0.82, W * 0.56], fill=tuple(ring) + (255,))
    for k in range(3):
        y = W * (0.62 + 0.07 * k)
        d.line([W * 0.3, y, W * 0.7, y], fill=(90, 90, 90, 255), width=max(1, W // 60))
    if text:
        f = _font(FONTS, int(W * 0.1))
        tw = d.textlength(text, font=f)
        d.text(((W - tw) / 2, W * 0.43), text, font=f, fill=(255, 255, 255, 255))
    return img


def warning_triangle(side_mm, px_per_mm=16):
    """ISO 7010-style yellow warning triangle with a black border (pictogram not legible in the frames)."""
    W = int(side_mm * px_per_mm)
    H = int(W * 0.9)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(W / 2, 0), (W, H - 1), (0, H - 1)], fill=(20, 20, 20, 255))
    m = W * 0.09
    d.polygon([(W / 2, m * 1.6), (W - m * 1.1, H - 1 - m * 0.65), (m * 1.1, H - 1 - m * 0.65)],
              fill=(250, 205, 0, 255))
    d.rectangle([W * 0.46, H * 0.36, W * 0.54, H * 0.68], fill=(20, 20, 20, 255))
    d.ellipse([W * 0.455, H * 0.73, W * 0.545, H * 0.83], fill=(20, 20, 20, 255))
    return img


def from_photo(cam, center, x_axis, normal, w_mm, h_mm, px_per_mm=4.0, still=None, fill=None, margin=6):
    """Rectify the w x h mm patch of a plane (centre, x along its width, outward normal) out of the
    published still of `cam`, through the calibrated pose and lens distortion. Returns an RGB image.
    fill: colour for the part of the patch outside the frame (default: stretch the frame's edge)."""
    img = cv2.imread(still or STILLS[cam.name])
    nrm = np.asarray(normal, float) / np.linalg.norm(normal)
    x = np.asarray(x_axis, float)
    x = x - (x @ nrm) * nrm
    x /= np.linalg.norm(x)
    y = np.cross(nrm, x)
    W, H = max(4, int(w_mm * px_per_mm)), max(4, int(h_mm * px_per_mm))
    uu, vv = np.meshgrid((np.arange(W) + 0.5) / W - 0.5, 0.5 - (np.arange(H) + 0.5) / H)
    P = np.asarray(center, float) + uu.reshape(-1, 1) * w_mm * x + vv.reshape(-1, 1) * h_mm * y
    uv, _ = cam.project(P)
    mx = uv[:, 0].reshape(H, W).astype(np.float32)
    my = uv[:, 1].reshape(H, W).astype(np.float32)
    out = cv2.remap(img, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    if fill is not None:
        h, w = img.shape[:2]
        off = (mx < margin) | (my < margin) | (mx > w - 1 - margin) | (my > h - 1 - margin)
        out[off] = fill[::-1]
    return Image.fromarray(out[:, :, ::-1])
